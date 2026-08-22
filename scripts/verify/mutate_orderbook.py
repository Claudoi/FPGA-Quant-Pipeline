#!/usr/bin/env python3
"""HDL mutation of the order book (gate E of /verify, fase3-uram campaign).

Each mutant flips a guard of the URAM table (serialized probe + prefetch), of
the level pipeline (registered stages), of the emission pipeline (A/B/C,
iter 7) or of the phase 2-3 engine and runs the cocotb suites (phase 2 at
DW=64, phase3 hash/depth/hard/rtm and uram at K=20); if no suite goes red,
the mutant survives (missing test). Usage:

    python3 scripts/verify/mutate_orderbook.py [--mutant <ID>]
"""
import subprocess, sys, os, shutil, re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")
BACKUP = RTL + ".bak"
# (area, make command): phase 2 runs the real feed at DW=64 (REPLAY-01),
# phase3 runs the hash suite at K=20 (probe exhausted and real full table),
# the depth suite at DW=32 (top-N vs golden, DP-01/DP-02), the hard suite
# (symbol 21 and retention under backpressure, SEC-NSYM-01/SEC-BP-01), the rtm
# suite (A/B/C emission pipeline, RTM-01..04 at DW=32 and RTM-REG-01 at DW=64,
# iter 7) and the uram area (SEC-URAM-01/02/03: serialized probe, prefetch and
# registered pipeline).
SUITES = [
    ("verification/testbenches/orderbook", ["make", "sim"]),
    ("verification/testbenches/phase3", ["make", "sim-hash"]),
    ("verification/testbenches/phase3", ["make", "sim-depth"]),
    ("verification/testbenches/phase3", ["make", "sim-hard"]),
    ("verification/testbenches/phase3", ["make", "sim-rtm"]),
    ("verification/testbenches/phase3", ["make", "sim-rtm64"]),
    ("verification/testbenches/uram", ["make", "sim-uram"]),
]

MUTANTS = [
    ("OV-BEST", "best bid <= instead of >= (best price change)",
     "lv_beat[i] <= (lv_qty[base+i] != 0) &&\n                              (ask ? (lv_price[base+i] > price)\n                                   : (lv_price[base+i] < price));",
     "lv_beat[i] <= (lv_qty[base+i] != 0) &&\n                              (ask ? (lv_price[base+i] < price)\n                                   : (lv_price[base+i] > price));"),
    ("OV-EMPTY", "push-out: the SEC-OV discard on overflow does not signal error (missing-reduce and add worse than the worst silently accepted)",
     "if (lv_delta[31]) begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b1;\n                end else if (lv2_abtx) begin\n                    lv2_mode <= LV_MODE_INSERT;\n                end else begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b1;\n                end",
     "if (lv_delta[31]) begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b0;\n                end else if (lv2_abtx) begin\n                    lv2_mode <= LV_MODE_INSERT;\n                end else begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b0;\n                end"),
    ("U-NOTATOMIC", "non-atomic replace (deletes the orig but does not add the new one)",
     "launch_lv(u_side, u_price, u_shares);\n                    wr_en = 1'b1;\n                    wr_addr = u_nidx;\n                    wr_data = entry_new(u_newref, u_side, u_price, u_shares);",
     "launch_lv(u_side, u_price, u_shares);"),
    ("U-DELETE-HALF", "replace keeps the orig qty at the level (double count)",
     "launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));\n                        wr_en = 1'b1;\n                        wr_addr = pr_slot;\n                        wr_data = {OW{1'b0}};\n                        u_newref <= newref;",
     "launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));\n                        u_newref <= newref;"),
    ("U-SKIP-ROUTE", "replace does not enter ST_UADD (the new ref is never registered)",
     "st <= lv_uadd ? ST_UADD : ST_EMIT_A;",
     "st <= ST_EMIT_A;"),
    ("D-DOUBLE", "delete subtracts twice from the level",
     "8'h44: begin\n                    oref = K'(b64(0));\n                    if (!pr_found) anomaly_count <= anomaly_count + 1;\n                    else begin\n                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));",
     "8'h44: begin\n                    oref = K'(b64(0));\n                    if (!pr_found) anomaly_count <= anomaly_count + 1;\n                    else begin\n                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -2*$signed(e_qty(pr_entry[OW-1:OW-QW])));"),
    ("RED-REF", "reduce on unknown ref does not count anomaly",
     "if (!pr_found) begin\n                        anomaly_count <= anomaly_count + 1;\n                    end else begin",
     "if (1'b0) begin\n                        anomaly_count <= anomaly_count + 1;\n                    end else begin"),
    ("QTY-NOERROR", "reduce above the quantity does not signal error",
     "if (rest[33]) error <= 1'b1;   // execute > remaining",
     "if (rest[33]) error <= 1'b0;   // execute > remaining"),
    ("EMIT-NOCHANGED", "changed always 0 (breaks the change flag)",
     "changed = (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);",
     "changed = 1'b0;"),
    ("HASH-NOREF", "the lookup does not compare the ref (collision -> op on the wrong ref)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (rd_data[0]) begin"),
    ("REF-TRUNC", "ref comparison truncated to 19 bits (replicates the pre-iter 12 K=19 bug: refs sharing the residue mod 2^19 collide)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (rd_data[0] && (rd_data[19:1] == pr_target[18:0])) begin"),
    ("HASH-LOOKUP-BOUND", "the probe tests one too few (off-by-one: the last slot's ref is not found)",
     "if (pr_i == 16'(PROBE-1)) begin",
     "if (pr_i == 16'(PROBE-2)) begin"),
    ("HASH-FULLNOCHECK", "full table still inserts (silent wrap/overwrite)",
     "if (pr_full) begin\n                        error <= 1'b1;      // full table (SEC-HASH-02)",
     "if (1'b0) begin\n                        error <= 1'b1;      // full table (SEC-HASH-02)"),
    ("HASH-UADD-FULL", "the U with the full newref path still applies the delete (the original is lost)",
     "else if (pr_new_full) error <= 1'b1;    // atomic U: the",
     "else if (1'b0) error <= 1'b1;    // atomic U: the"),
    ("HASH-DUPNOCHECK", "add with duplicate ref does not signal error",
     "if (pr_found || shares == 0) begin",
     "if (shares == 0) begin"),
    ("HASH-INSERT-NOVALID", "the insert does not write the entry (the order never appears)",
     "wr_en = 1'b1;\n                        wr_addr = pr_empty;\n                        wr_data = entry_new(oref, ask, price, shares);",
     "wr_en = 1'b0;\n                        wr_addr = pr_empty;\n                        wr_data = entry_new(oref, ask, price, shares);"),
    ("URAM-COMB-INDEX", "the probe indexes the table combinationally (broken URAM pattern)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (o_mem[pr_base + pr_i][0] && (o_mem[pr_base + pr_i][REFW:1] == pr_target)) begin"),
    ("URAM-NO-PREFETCH", "no hash group prefetch in ST_BODY (lookup enters ST_APPLY)",
     "if (bi == 4'd1 && lt(m_type)) begin",
     "if (bi == 4'd1 && lt(m_type) && 1'b0) begin"),
    ("PIPE-SKIP-STAGE", "the pipeline skips stage 2b (priority decode never runs, lv2_* stale)",
     "if (s_axis_tvalid && !nx_done) nx_recv();\n                    decode_lv2b();",
     "if (s_axis_tvalid && !nx_done) nx_recv();\n                    if (1'b0) decode_lv2b();"),
    ("LV-STALE-STAGE", "stage 3 writes the pre-op qty (stale level, the delta is lost)",
     "wq[i] = (i == lv2_found) ? QW'(lv2_newq[31:0]) : lv_qt[i];",
     "wq[i] = lv_qt[i];"),
    ("DP-BADORDER", "the top-N inverts the order (worst level first)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[ND-1-di][31:0],\n                        sm_cap_qt[ND-1-di][31:0]};"),
    ("DP-ASKSWAP", "the top-N emits the ask in the bid group (and vice versa)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[P+di][31:0],\n                        sm_cap_qt[P+di][31:0]};",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};"),
    ("DP-NOVALID", "depth is never validated (the consumer sees 0)",
     "depth_tdata <= sm_dacc;\n                depth_tvalid <= 1'b1;",
     "depth_tdata <= sm_dacc;"),
    ("DP-TOPNCOUNT", "the top-N emits ND-1 levels (the last one stays off the bus)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "for (di = 0; di < ND-1; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};"),
    ("NSYM-GUARD", "no symbol 21 guard (the out-of-subset locate enters with m_loc_idx=31 -> OOB)",
     "bad_sym <= 1'b1;\n                            error <= 1'b1;\n                            m_loc_idx <= 0;\n                        end else begin\n                            m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);",
     "m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);"),
    ("BP-NORET", "the BBO/depth pair is not retained (lost if tready=0 during the event)",
     "bbo_tvalid <= bbo_tvalid && !bbo_tready;",
     "bbo_tvalid <= 1'b0;"),
    ("LV-NEGWRAP", "the reduce on an absent level writes the wrapped quantity (phantom ~4.29e9)",
     "            end else if (!lv2_afnd && lv_delta[31]) begin\n                // reduce over a level that does not exist (an order in the\n                // table without a level due to a prior overflow): never a\n                // wrapped qty (finding G5)\n                lv2_mode <= LV_MODE_NONE;",
     "            end else if (!lv2_afnd && lv_delta[31]) begin\n                // reduce over a level that does not exist (an order in the\n                // table without a level due to a prior overflow): never a\n                // wrapped qty (finding G5)\n                lv2_mode <= LV_MODE_INSERT;"),
    # --- emission pipeline mutants (iter 7 addendum) ---
    ("EMIT-NOCAPTURE", "stage A omitted: selection reads the stale capture (sm_cap_*)",
     "if (emit_ok) capture_emit_a();",
     "if (1'b0) capture_emit_a();"),
    ("EMIT-FINDFIRST-INV", "find-first priority inverted (first empty slot, not the best)",
      "sm_bsel <= first_one(sm_nzb_next);",
      "sm_bsel <= first_one(~sm_nzb_next);"),
    ("EMIT-CHANGED-WRONG-PREV", "changed compares the bid against the ask's prev (wrong flag)",
     "changed = (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);",
     "changed = (bp != prev_ap[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);"),
    ("EMIT-DEPTH-WRONGSIDE", "the bid depth is packed from the captured ask group",
     "dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[P+di][31:0],\n                        sm_cap_qt[P+di][31:0]};"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: {mutant[0]} target not found: {old[:40]!r}")
    if n > 1:
        raise SystemExit(f"ERROR: {mutant[0]} {n} matches (expected 1)")
    return raw.replace(old, new)


def apply_safe(mutant, raw):
    # writes the mutant to a temp file and only replaces the RTL if the pattern
    # was found: a SystemExit from apply() can NEVER truncate the RTL
    mutated = apply(mutant, raw)
    with open(RTL + ".mut", "w") as f:
        f.write(mutated)
    os.replace(RTL + ".mut", RTL)


def run_suites():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join([REPO, os.path.join(REPO, "golden_model")]) + \
        os.pathsep + env.get("PYTHONPATH", "")
    structural = subprocess.run(
        [sys.executable, "scripts/verify/synth_check.py"], cwd=REPO, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if structural.returncode != 0:
        return 1
    for area, cmd in SUITES:
        r = subprocess.run(cmd, cwd=os.path.join(REPO, area), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        m = re.search(r"TESTS=\d+ PASS=\d+ FAIL=(\d+)", r.stdout)
        if m:
            fails = int(m.group(1))
            if fails:
                return fails
        elif r.returncode != 0:
            return 999
    return 0


def lints():
    """the mutant must still compile: a broken file does NOT count as a kill
    (it would kill the gate with a false positive)."""
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    r = subprocess.run(
        ["verilator", "--lint-only", "-Wall",
         "-Wno-BLKSEQ", "-Wno-WIDTHEXPAND", "-Wno-CASEOVERLAP",
         "-Wno-CASEINCOMPLETE",
         "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM",  # the mutant usually leaves
                            # signals unused (expected collateral of the flip)
                            # -Wno-BLKSEQ: the 9 blocking assignments in tasks
                            # (pre-existing style at HEAD, iter 13) fail the
                            # lint of ALL candidates without being the mutant's
                            # fault
         "--top-module", "orderbook", "rtl/orderbook/orderbook.sv"],
        cwd=REPO, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.returncode == 0


def clean():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    for area, _ in SUITES:
        # clean-all removes the dedicated SIM_BUILDs (phase3: sim_build_hash,
        # sim_build_chain, ...) that cocotb's clean leaves intact: a cache
        # built with a mutant applied would be silently reused (false FAIL
        # post-restoration, iter 5 finding).
        subprocess.run(["make", "clean-all"], cwd=os.path.join(REPO, area), env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["make", "clean"], cwd=os.path.join(REPO, area), env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--mutant":
        only = sys.argv[2]
    raw = open(RTL).read()
    results = []
    try:
        for mutant in MUTANTS:
            mid = mutant[0]
            if only and only != mid:
                continue
            with open(BACKUP, "w") as f:
                f.write(raw)
            try:
                apply_safe(mutant, raw)
                if not lints():
                    fails = -1   # broken file: neither kill nor survive — mutation error
                else:
                    fails = run_suites()
            finally:
                if os.path.exists(BACKUP):
                    shutil.move(BACKUP, RTL)
                clean()
            killed = fails > 0
            if fails == -1:
                print(f"[ERROR] {mid}: the mutant does not compile (lint) — does NOT count as a kill")
            else:
                results.append((mid, killed, fails))
                print(f"[{'KILLED' if killed else 'SURVIVES'}] {mid}: FAIL={fails} ({mutant[1]})")
    finally:
        clean()
    survivors = [r for r in results if not r[1]]
    print("\n=== ORDERBOOK MUTATION SUMMARY (gate E, fase3-uram iter 6) ===")
    for mid, killed, fails in results:
        print(f"  {mid}: {'killed' if killed else 'SURVIVES!'}")
    if survivors:
        print("\n" + ", ".join(mid for mid, _, _ in survivors) + " SURVIVE (missing tests)")
        raise SystemExit(1)
    print("\nALL MUTANTS KILLED. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
