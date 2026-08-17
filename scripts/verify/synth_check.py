#!/usr/bin/env python3
"""Validación estática de los artefactos de síntesis (criterio 10, gate G4).

Sin Vivado, verifica que `synth/fase3_synth.tcl` y
`synth/constraints/fase3_322mhz.xdc` son coherentes con el RTL y la spec:

1. part objetivo = xcku3p-ffva676-2L-e (spec, decisión 002; swappable).
2. top del tcl = módulo de `rtl/itch_chain.sv`.
3. Ficheros RTL que lee el tcl existen.
4. Periodo del reloj 3,103 ns == 1/322,265625e6 (tolerancia 0,01 %).
5. Cada puerto referenciado en el xdc (input/output delay) existe en el
   port list del top.
6. El generic DW=32 de la variante objetivo está fijado en el tcl.
7. El Tcl genera check_timing/metodología/clocks y aborta si existe slack
   negativo tras route.
8. Todo puerto síncrono no-clock tiene delays min/max de entrada o salida.

Uso:
    python3 scripts/verify/synth_check.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TCL = os.path.join(REPO, "synth", "fase3_synth.tcl")
XDC = os.path.join(REPO, "synth", "constraints", "fase3_322mhz.xdc")
TOP_SV = os.path.join(REPO, "rtl", "itch_chain.sv")
BOOK_SV = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")

PART = "xcku3p-ffva676-2L-e"
FREQ_HZ = 322.265625e6
PERIOD_NS = 1e9 / FREQ_HZ  # 3,10303... ns

FAILS = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def delay_ports(xdc, kind, bound):
    """Puertos cubiertos por set_{input,output}_delay -{min,max}."""
    found = set()
    pattern = rf"set_{kind}_delay[^\n]*-{bound}\s+\S+[^\n]*\[get_ports\s+\{{([^}}]+)\}}\]"
    for group in re.findall(pattern, xdc):
        for token in group.split():
            found.add(token.split("[")[0])
    return found


def main():
    if not os.path.exists(TCL):
        print(f"[FAIL] tcl ausente: {TCL}")
        sys.exit(1)

    tcl = open(TCL, encoding="utf-8").read()
    top = re.search(r"set top\s+(\w+)", tcl).group(1)
    part = re.search(r"set part\s+(\S+)", tcl).group(1)
    check("part objetivo de la spec", part == PART, f"{part}")

    sv = open(TOP_SV, encoding="utf-8").read()
    sv_nocom = re.sub(r"//.*", "", sv)
    m = re.search(r"module\s+(\w+)\s*(?:#\s*\([^)]*\))?\s*\(", sv_nocom)
    check("top del tcl == módulo del RTL", m and m.group(1) == top,
          f"tcl:{top} rtl:{m and m.group(1)}")
    check("itch_chain propaga ND al orderbook", bool(re.search(r"\.ND\s*\(\s*ND\s*\)", sv)))

    rtl_reads = re.findall(r"read_verilog\s+-sv\s+(\S+)", tcl)
    check("el tcl lee los 3 módulos del pipeline", len(rtl_reads) == 3,
          f"{len(rtl_reads)} read_verilog")
    for r in rtl_reads:
        p = os.path.normpath(os.path.join(os.path.dirname(TCL), r))
        check(f"RTL leído existe: {r}", os.path.exists(p))

    check("generic DW=32 fijado (variante 322 MHz)",
          "DW=32" in tcl or "DW 32" in tcl)
    check("check_timing verbose post-synth y post-route",
          tcl.count("check_timing -verbose") >= 2)
    check("report_methodology post-synth y post-route",
          tcl.count("report_methodology") >= 2)
    check("informe de clocks presente", "report_clocks" in tcl)
    check("timing informa endpoints sin constraint",
          "-report_unconstrained" in tcl)
    check("el Tcl aborta ante slack negativo",
          "slack_lesser_than 0.0" in tcl and "error" in tcl)

    book = open(BOOK_SV, encoding="utf-8").read()
    check("lectura de tabla registrada por rd_data",
          bool(re.search(r"rd_data\s*<=\s*o_mem\s*\[\s*rd_addr\s*\]", book)))
    direct_probe_read = re.search(r"o_mem\s*\[\s*pr_", book)
    check("la sonda no indexa o_mem combinacionalmente",
          not direct_probe_read,
          "sin lecturas o_mem[pr_*]" if not direct_probe_read else
          f"lectura directa en offset {direct_probe_read.start()}")

    xdc = open(XDC, encoding="utf-8").read()
    period = re.search(r"create_clock[^;]*?-period\s+([\d.]+)", xdc)
    check("create_clock presente en el xdc", bool(period))
    if period:
        per = float(period.group(1))
        rel = abs(per - PERIOD_NS) / PERIOD_NS
        check("periodo == 1/322,265625e6 (tol 0,01 %)", rel < 1e-4,
              f"{per} ns vs {PERIOD_NS:.4f} ns (delta {rel:.2e})")

    # puertos del top (Anexo de la spec + BBO/depth/handshake)
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
    check("puertos del xdc existen en el top", not missing,
          f"{missing or 'todos presentes'}")

    expected_inputs = {name for direction, name in port_defs
                       if direction == "input" and name != "clk"}
    expected_outputs = {name for direction, name in port_defs
                        if direction == "output"}
    for bound in ("min", "max"):
        got_inputs = delay_ports(xdc, "input", bound)
        got_outputs = delay_ports(xdc, "output", bound)
        check(f"todos los inputs tienen delay {bound}",
              got_inputs == expected_inputs,
              f"faltan={sorted(expected_inputs-got_inputs)} sobran={sorted(got_inputs-expected_inputs)}")
        check(f"todos los outputs tienen delay {bound}",
              got_outputs == expected_outputs,
              f"faltan={sorted(expected_outputs-got_outputs)} sobran={sorted(got_outputs-expected_outputs)}")

    print()
    if FAILS:
        print(f"synth_check: {len(FAILS)} FAIL — artefactos NO listos")
        sys.exit(1)
    print("synth_check: OK — tcl/constraints coherentes con el RTL y la spec")


if __name__ == "__main__":
    main()
