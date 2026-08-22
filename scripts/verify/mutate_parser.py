#!/usr/bin/env python3
"""HDL mutation of the ITCH parser (gate E of /verify, fase1-parser-rtl campaign).

Each mutant applies a flip to the RTL and runs the cocotb suite; if the suite
stays green, the mutant survives (missing test). Usage:

    python3 mutate_parser.py                  # all mutants
    python3 mutate_parser.py --mutant S1NEXT  # a single one, with detail

The mutants (exact strings that must be APPLIED; their presence is verified):
"""
import subprocess
import sys
import os
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "parser", "itch_parser.sv")
TESTDIR = os.path.join(REPO, "verification", "testbenches", "parser")
BACKUP = RTL + ".bak"

# (id, description, old, new) — old must exist exactly once in the RTL.
MUTANTS = [
    ("ALN-OFFBYONE", "captured body offset (off-by-one in base)",
     "7'(11 + BYTES*bi)", "7'(12 + BYTES*bi)"),
    ("ALN-PAD-FILL", "body fill instead of zero",
     "r[DW-1 - 8*k -: 8] = 8'h0;", "r[DW-1 - 8*k -: 8] = 8'hff;"),
    ("SEQ-GAP-NOGAP", "never detects a gap (flip != to ==)",
     "!= exp_seq) gap_detected <= 1'b1;",
     "== exp_seq) gap_detected <= 1'b1;"),
    ("SEQ-GAP-SESSION", "session change marks a gap (flip != to ==)",
     "pbyte(q,8),pbyte(q,9)} != session_id) begin",
     "pbyte(q,8),pbyte(q,9)} == session_id) begin"),
    ("NEXT-OFFBYONE", "off-by-one in pack_left (reverts to > 0)",
     "if (pack_left > 1) begin", "if (pack_left > 0) begin"),
    ("LEN-BODY_W", "body_w computed with wrong ceil",
     "8'(BYTES-1)) >> L2B", "8'(BYTES)) >> L2B"),
    ("CAP-SUBSET", "emits even when not subset",
     "st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);",
     "st <= ST_W0;"),
    ("OUT-FREE", "heap without out_take (re-presents even when not accepted)",
     "wire out_free   = !out_valid_reg || out_take;",
     "wire out_free   = !out_valid_reg;"),
    ("LEN-CAPT-ERR", "marks the structural len=11 boundary as invalid",
     "(8'({pbyte(q,0), pbyte(q,1)}) < 11) ||",
     "(8'({pbyte(q,0), pbyte(q,1)}) <= 11) ||"),
    ("LEN-H", "accepts H with length 24 instead of 25",
     "8'h48: explen = 8'd25;", "8'h48: explen = 8'd24;"),
    ("SEQ-ZERO-SESSION", "zero count keeps the previous session's expected",
     "                                exp_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),\n                                            pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};\n                                eop_seen <= 1'b0;",
     "                                exp_seq <= exp_seq;\n                                eop_seen <= 1'b0;"),
    ("TRUNC-EOP", "ignores accepted tlast and does not detect the truncation",
     "if (in_take && s_axis_tlast) eop_seen <= 1'b1;",
     "if (1'b0) eop_seen <= 1'b1;"),
    ("KEEP-ALL-BYTES", "counts BYTES even when the final beat is partial",
     "((in_take && in_keep_ok) ? in_nbytes : 8'd0);",
     "((in_take && in_keep_ok) ? 8'(BYTES) : 8'd0);"),
    ("KEEP-LSB-FIRST", "inverts the orientation when compacting valid lanes",
     "(s_axis_tdata >> (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;",
     "(s_axis_tdata << (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;"),
    ("KEEP-HOLES", "accepts any nonzero tkeep mask",
     "else if (seen_zero) keep_is_msb_prefix = 1'b0;",
     "else if (seen_zero) keep_is_msb_prefix = 1'b1;"),
    ("KEEP-PARTIAL-NONLAST", "accepts a partial beat without tlast",
     "wire in_keep_ok = keep_shape_ok &&\n                      (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}});",
     "wire in_keep_ok = keep_shape_ok;"),
    ("KEEP-NODRAIN", "does not drain after a non-final invalid mask",
     "drop_packet <= !s_axis_tlast;", "drop_packet <= 1'b0;"),
    ("COUNT-NO-EOP", "closes count without requiring end of packet",
     "end else if (eop_eff && qn_post == 0) begin",
     "end else if (qn_post == 0) begin"),
    ("COUNT-RESIDUAL", "closes count even when residual bytes remain",
     "end else if (eop_eff && qn_post == 0) begin",
     "end else if (eop_eff) begin"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: mutant {mutant[0]} does not find its target "
                         f"(count=0). old={old!r}")
    # COUNT-NO-EOP/COUNT-RESIDUAL: the closing chain `eop_eff && qn_post==0`
    # lives in ST_NEXT and (since the iter 15 addendum) in the ST_DRAIN close
    # (draining the last message). The flip must touch BOTH (the datagram close
    # semantics is common) — all occurrences are replaced.
    return raw.replace(old, new)


def run_suite():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [REPO, os.path.join(REPO, "golden_model"), TESTDIR]) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        ["make", "sim"], cwd=TESTDIR,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # green if TESTS=.. PASS=.. and FAIL=0
    import re
    m = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+)", r.stdout)
    failed_tests = re.findall(
        r"cocotb\.regression\s+test_itch_parser\.(test_[A-Za-z0-9_]+) failed",
        r.stdout)
    return r.returncode, r.stdout, (int(m.group(3)) if m else -1), failed_tests


def main():
    args = sys.argv[1:]
    only = None
    if args and args[0] == "--mutant":
        only = args[1]
    raw = open(RTL).read()
    selected = [m for m in MUTANTS if not only or m[0] == only]
    if only and not selected:
        raise SystemExit(f"mutant {only} not found")
    for mutant in selected:
        apply(mutant, raw)
    if os.path.exists(BACKUP):
        raise SystemExit(f"ERROR: previous backup exists: {BACKUP}")
    results = []
    try:
        for mutant in selected:
            mid = mutant[0]
            mut = apply(mutant, raw)
            with open(BACKUP, "w") as f:
                f.write(raw)
            try:
                with open(RTL, "w") as f:
                    f.write(mut)
                rc, out, fails, failed_tests = run_suite()
            finally:
                shutil.move(BACKUP, RTL)
            compiled = (fails >= 0)
            killed = compiled and (fails > 0)
            results.append((mid, compiled, killed, fails, failed_tests))
            status = "KILLED" if killed else ("SURVIVES" if compiled else "ERROR")
            killers = ",".join(failed_tests) if failed_tests else "-"
            print(f"[{status}] {mid}: compiled={'yes' if compiled else 'no'} "
                  f"FAIL={fails} tests={killers} ({mutant[1]})")
    finally:
        if os.path.exists(BACKUP):
            shutil.move(BACKUP, RTL)
        # Leaves the sim_build clean: the makefile does not recompile RTL if
        # the object keeps the mutant timestamp (avoids false greens in the
        # real suite).
        import glob
        subprocess.run(["make", "clean"], cwd=TESTDIR,
                       env=dict(os.environ), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    survivors = [r for r in results if not r[2]]
    print("\n=== MUTATION SUMMARY (gate E) ===")
    for mid, compiled, killed, fails, failed_tests in results:
        print(f"  {mid}: {'killed' if killed else 'SURVIVES!'}")
    if survivors:
        print(f"\n{len(survivors)} MUTANTS SURVIVE (missing tests): "
              + ", ".join(r[0] for r in survivors))
        raise SystemExit(1)
    print("\nALL MUTANTS KILLED. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
