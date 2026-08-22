#!/usr/bin/env python3
"""Static validation of the synthesis artifacts (criterion 10, gate G4).

Without Vivado, verifies that `synth/fase3_synth.tcl` and
`synth/constraints/fase3_322mhz.xdc` are consistent with the RTL and the spec:

1. target part = xcku3p-ffva676-2L-e (spec, decision 002; swappable).
2. tcl top = module from `synth/itch_chain_synth.sv` (AXI contract wrapper;
   rtl/itch_chain.sv has 896 I/O and the FFVA676 only 256 — Place 30-415,
   finding 2026-08-18).
3. RTL files read by the tcl exist (3 from the pipeline + the wrapper).
4. Clock period 3.103 ns == 1/322.265625e6 (0.01% tolerance).
5. Every port referenced in the xdc (input/output delay) exists in the
   top port list (the wrapper).
6. The DW=32 generic of the target variant is set in the tcl.
7. The Tcl generates check_timing/methodology/clocks and aborts if negative
   slack exists after route.
8. Every synchronous non-clock port has min/max input or output delays.

Usage:
    python3 scripts/verify/synth_check.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TCL = os.path.join(REPO, "synth", "fase3_synth.tcl")
TCL156 = os.path.join(REPO, "synth", "fase3_156mhz.tcl")
XDC = os.path.join(REPO, "synth", "constraints", "fase3_322mhz.xdc")
TOP_SV = os.path.join(REPO, "synth", "itch_chain_synth.sv")
CHAIN_SV = os.path.join(REPO, "rtl", "itch_chain.sv")
BOOK_SV = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")
MDP3_TCL = os.path.join(REPO, "synth", "mdp3_synth.tcl")
MDP3_XDC_322 = os.path.join(REPO, "synth", "constraints", "mdp3_322mhz.xdc")
MDP3_XDC_156 = os.path.join(REPO, "synth", "constraints", "mdp3_156mhz.xdc")
MDP3_RTL = os.path.join(REPO, "rtl", "parser", "mdp3_parser.sv")

PART = "xcku3p-ffva676-2L-e"
FREQ_HZ = 322.265625e6
PERIOD_NS = 1e9 / FREQ_HZ  # 3.10303... ns

FAILS = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def delay_ports(xdc, kind, bound):
    """Ports covered by set_{input,output}_delay -{min,max}."""
    found = set()
    pattern = rf"set_{kind}_delay[^\n]*-{bound}\s+\S+[^\n]*\[get_ports\s+\{{([^}}]+)\}}\]"
    for group in re.findall(pattern, xdc):
        for token in group.split():
            found.add(token.split("[")[0])
    return found


def check_mdp3_artifacts():
    """CLO-M3T-00: MDP3 synthesis artifacts (gate G, phase 4 criterion 10)."""
    for f, what in ((MDP3_TCL, "tcl"), (MDP3_XDC_322, "xdc 322"),
                    (MDP3_XDC_156, "xdc 156"), (MDP3_RTL, "rtl")):
        check(f"MDP3 artifact present: {what}", os.path.exists(f), f)

    if not os.path.exists(MDP3_TCL):
        return
    tcl = open(MDP3_TCL, encoding="utf-8").read()
    part = re.search(r"set part\s+(\S+)", tcl)
    check("MDP3: spec target part", bool(part) and part.group(1) == PART,
          part and part.group(1))
    check("MDP3: top = mdp3_parser (no wrapper)", "set top mdp3_parser" in tcl)
    check("MDP3: read_verilog of the parser", "../rtl/parser/mdp3_parser.sv" in tcl)
    check("MDP3: DW=32 generic set", "DW=$dw" in tcl or "DW=$dw}" in tcl
          or re.search(r"generic\s+\"DW=\$dw\"", tcl) is not None)
    check("MDP3: DW=64 regression run planned",
          re.search(r"DW=64", tcl) is not None)
    check("MDP3: outdir 322mhz", re.search(r"reports/mdp3/322mhz", tcl) is not None)
    check("MDP3: outdir 156mhz", re.search(r"reports/mdp3/156mhz", tcl) is not None)
    check("MDP3: abort on negative slack", "MDP3 TIMING FAIL" in tcl
          and "slack_lesser_than 0.0" in tcl and "error" in tcl)
    check("MDP3: check_timing/methodology in each variant",
          tcl.count("check_timing -verbose") >= 2
          and tcl.count("report_methodology") >= 2)

    sv = open(MDP3_RTL, encoding="utf-8").read()
    sv_nocom = re.sub(r"//.*", "", sv)
    m = re.search(r"module\s+(\w+)\s*(?:#\s*\([^)]*\))?\s*\(", sv_nocom)
    check("MDP3: the RTL defines the mdp3_parser module",
          bool(m) and m.group(1) == "mdp3_parser")

    for xdc, period_ns in ((MDP3_XDC_322, PERIOD_NS), (MDP3_XDC_156, 6.400)):
        x = open(xdc, encoding="utf-8").read()
        period = re.search(r"create_clock[^;]*?-period\s+([\d.]+)", x)
        check(f"MDP3: create_clock in {os.path.basename(xdc)}", bool(period))
        if period:
            per = float(period.group(1))
            rel = abs(per - period_ns) / period_ns
            check(f"MDP3: period == {period_ns:.3f} ns (tol 0.01%)",
                  rel < 1e-4, f"{per} ns vs {period_ns:.4f} ns (delta {rel:.2e})")

        port_defs = re.findall(
            r"^\s*(input|output)\s+(?:wire|reg)?\s*(?:\[[^\]]*\]\s*)?(\w+)",
            sv_nocom[: sv_nocom.index(");")], re.M)
        ports = {name for _, name in port_defs}
        xdc_ports = set()
        for pat in re.findall(r"get_ports\s+(\{[^}]*\}|[\w\[\]\*]+)", x):
            for p in re.findall(r"\w+", pat.strip("{}")):
                base = p.split("[")[0]
                if base != "clk":
                    xdc_ports.add(base)
        missing = sorted(xdc_ports - ports - {"clk"})
        check(f"MDP3: xdc ports exist in the top ({os.path.basename(xdc)})",
              not missing, f"{missing or 'all present'}")

        expected_inputs = {name for direction, name in port_defs
                          if direction == "input" and name != "clk"}
        expected_outputs = {name for direction, name in port_defs
                           if direction == "output"}
        for bound in ("min", "max"):
            got_inputs = delay_ports(x, "input", bound)
            got_outputs = delay_ports(x, "output", bound)
            check(f"MDP3: all inputs have {bound} delay "
                  f"({os.path.basename(xdc)})",
                  got_inputs == expected_inputs,
                  f"missing={sorted(expected_inputs-got_inputs)} "
                  f"extra={sorted(got_inputs-expected_inputs)}")
            check(f"MDP3: all outputs have {bound} delay "
                  f"({os.path.basename(xdc)})",
                  got_outputs == expected_outputs,
                  f"missing={sorted(expected_outputs-got_outputs)} "
                  f"extra={sorted(got_outputs-expected_outputs)}")


def main():
    if not os.path.exists(TCL):
        print(f"[FAIL] tcl missing: {TCL}")
        sys.exit(1)

    tcl = open(TCL, encoding="utf-8").read()
    top = re.search(r"set top\s+(\w+)", tcl).group(1)
    part = re.search(r"set part\s+(\S+)", tcl).group(1)
    check("spec target part", part == PART, f"{part}")

    sv = open(TOP_SV, encoding="utf-8").read()
    sv_nocom = re.sub(r"//.*", "", sv)
    m = re.search(r"module\s+(\w+)\s*(?:#\s*\([^)]*\))?\s*\(", sv_nocom)
    check("tcl top == synthesis wrapper module", m and m.group(1) == top,
          f"tcl:{top} synth:{m and m.group(1)}")
    chain = open(CHAIN_SV, encoding="utf-8").read()
    check("itch_chain propagates ND to the orderbook", bool(re.search(r"\.ND\s*\(\s*ND\s*\)", chain)))
    check("the wrapper instantiates itch_chain", "itch_chain" in sv)

    rtl_reads = re.findall(r"read_verilog\s+-sv\s+(\S+)", tcl)
    check("the tcl reads the 3 pipeline modules + the wrapper",
          len(rtl_reads) == 4, f"{len(rtl_reads)} read_verilog")
    for r in rtl_reads:
        p = os.path.normpath(os.path.join(os.path.dirname(TCL), r))
        check(f"read RTL exists: {r}", os.path.exists(p))

    check("DW=32 generic set (322 MHz variant)",
          "DW=32" in tcl or "DW 32" in tcl)

    # CLO-RPT-01: each variant writes its own report directory; a 322 run never
    # overwrites the archived 156 (and vice versa).
    tcl156 = open(TCL156, encoding="utf-8").read()
    m_outdir = re.search(r"set outdir\s+\[file normalize\s+([\w./\\-]+)\]", tcl)
    m156_outdir = re.search(
        r"set outdir\s+\[file normalize\s+([\w./\\-]+)\]", tcl156)
    outdir = m_outdir.group(1).rstrip("/") if m_outdir else ""
    outdir156 = m156_outdir.group(1).rstrip("/") if m156_outdir else ""
    check("tcl 322 outdir == reports/322mhz", outdir.endswith("322mhz"),
          outdir)
    check("tcl 156 outdir == reports/156mhz",
          outdir156.endswith("156mhz"), outdir156)
    check("outdirs differ between variants", outdir != outdir156,
          f"{outdir} vs {outdir156}")

    check("verbose check_timing post-synth and post-route",
          tcl.count("check_timing -verbose") >= 2)
    check("report_methodology post-synth and post-route",
          tcl.count("report_methodology") >= 2)
    check("clocks report present", "report_clocks" in tcl)
    check("timing reports unconstrained endpoints",
          "-report_unconstrained" in tcl)
    check("the Tcl aborts on negative slack",
          "slack_lesser_than 0.0" in tcl and "error" in tcl)

    book = open(BOOK_SV, encoding="utf-8").read()
    check("table read registered by rd_data",
          bool(re.search(r"rd_data\s*<=\s*o_mem\s*\[\s*rd_addr\s*\]", book)))
    direct_probe_read = re.search(r"o_mem\s*\[\s*pr_", book)
    check("the probe does not index o_mem combinationally",
          not direct_probe_read,
          "no o_mem[pr_*] reads" if not direct_probe_read else
          f"direct read at offset {direct_probe_read.start()}")

    xdc = open(XDC, encoding="utf-8").read()
    period = re.search(r"create_clock[^;]*?-period\s+([\d.]+)", xdc)
    check("create_clock present in the xdc", bool(period))
    if period:
        per = float(period.group(1))
        rel = abs(per - PERIOD_NS) / PERIOD_NS
        check("period == 1/322.265625e6 (tol 0.01%)", rel < 1e-4,
              f"{per} ns vs {PERIOD_NS:.4f} ns (delta {rel:.2e})")

    # top ports (spec Annex + BBO/depth/handshake)
    port_defs = re.findall(
        r"^\s*(input|output)\s+(?:wire|reg)?\s*(?:\[[^\]]*\]\s*)?(\w+)",
        sv, re.M)
    ports = {name for _, name in port_defs}
    xdc_ports = set()
    for pat in re.findall(r"get_ports\s+(\{[^}]*\}|[\w\[\]\*]+)", xdc):
        for p in re.findall(r"\w+", pat.strip("{}")):
            base = p.split("[")[0]
            if base not in ("clk",):
                xdc_ports.add(base)
    missing = sorted(xdc_ports - ports - {"clk"})
    check("xdc ports exist in the top", not missing,
          f"{missing or 'all present'}")

    expected_inputs = {name for direction, name in port_defs
                       if direction == "input" and name != "clk"}
    expected_outputs = {name for direction, name in port_defs
                        if direction == "output"}
    for bound in ("min", "max"):
        got_inputs = delay_ports(xdc, "input", bound)
        got_outputs = delay_ports(xdc, "output", bound)
        check(f"all inputs have {bound} delay",
              got_inputs == expected_inputs,
              f"missing={sorted(expected_inputs-got_inputs)} extra={sorted(got_inputs-expected_inputs)}")
        check(f"all outputs have {bound} delay",
              got_outputs == expected_outputs,
              f"missing={sorted(expected_outputs-got_outputs)} extra={sorted(got_outputs-expected_outputs)}")

    print()
    check_mdp3_artifacts()
    print()
    if FAILS:
        print(f"synth_check: {len(FAILS)} FAIL — artifacts NOT ready")
        sys.exit(1)
    print("synth_check: OK — tcl/constraints consistent with the RTL and the spec")


if __name__ == "__main__":
    main()
