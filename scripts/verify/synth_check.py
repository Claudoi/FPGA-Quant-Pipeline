#!/usr/bin/env python3
"""Validación estática de los artefactos de síntesis (criterio 10, gate G4).

Sin Vivado, verifica que `synth/fase3_synth.tcl` y
`synth/constraints/fase3_322mhz.xdc` son coherentes con el RTL y la spec:

1. part objetivo = xcvu9p-flga2104-2L-e (spec, swappable).
2. top del tcl = módulo de `rtl/itch_chain.sv`.
3. Ficheros RTL que lee el tcl existen.
4. Periodo del reloj 3,103 ns == 1/322,265625e6 (tolerancia 0,01 %).
5. Cada puerto referenciado en el xdc (input/output delay) existe en el
   port list del top.
6. El generic DW=32 de la variante objetivo está fijado en el tcl.

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

PART = "xcvu9p-flga2104-2L-e"
FREQ_HZ = 322.265625e6
PERIOD_NS = 1e9 / FREQ_HZ  # 3,10303... ns

FAILS = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    if not os.path.exists(TCL):
        print(f"[FAIL] tcl ausente: {TCL}")
        sys.exit(1)

    tcl = open(TCL).read()
    top = re.search(r"set top\s+(\w+)", tcl).group(1)
    part = re.search(r"set part\s+(\S+)", tcl).group(1)
    check("part objetivo de la spec", part == PART, f"{part}")

    sv = open(TOP_SV).read()
    sv_nocom = re.sub(r"//.*", "", sv)
    m = re.search(r"module\s+(\w+)\s*(?:#\s*\([^)]*\))?\s*\(", sv_nocom)
    check("top del tcl == módulo del RTL", m and m.group(1) == top,
          f"tcl:{top} rtl:{m and m.group(1)}")

    rtl_reads = re.findall(r"read_verilog\s+-sv\s+(\S+)", tcl)
    check("el tcl lee los 3 módulos del pipeline", len(rtl_reads) == 3,
          f"{len(rtl_reads)} read_verilog")
    for r in rtl_reads:
        p = os.path.normpath(os.path.join(os.path.dirname(TCL), r))
        check(f"RTL leído existe: {r}", os.path.exists(p))

    check("generic DW=32 fijado (variante 322 MHz)",
          "DW=32" in tcl or "DW 32" in tcl)

    xdc = open(XDC).read()
    period = re.search(r"create_clock[^;]*?-period\s+([\d.]+)", xdc)
    check("create_clock presente en el xdc", bool(period))
    if period:
        per = float(period.group(1))
        rel = abs(per - PERIOD_NS) / PERIOD_NS
        check("periodo == 1/322,265625e6 (tol 0,01 %)", rel < 1e-4,
              f"{per} ns vs {PERIOD_NS:.4f} ns (Δ {rel:.2e})")

    # puertos del top (Anexo de la spec + BBO/depth/handshake)
    ports = re.findall(
        r"^\s*(?:input|output)\s+(?:wire|reg)?\s*(?:\[[^\]]*\]\s*)?(\w+)",
        sv, re.M)
    ports = set(ports)
    xdc_ports = set()
    for pat in re.findall(r"get_ports\s+(\{[^}]*\}|[\w\[\]\*]+)", xdc):
        for p in re.findall(r"\w+", pat.strip("{}")):
            base = p.split("[")[0]
            if base not in ("clk",):
                xdc_ports.add(base)
    missing = sorted(xdc_ports - ports - {"clk"})
    check("puertos del xdc existen en el top", not missing,
          f"{missing or 'todos presentes'}")

    print()
    if FAILS:
        print(f"synth_check: {len(FAILS)} FAIL — artefactos NO listos")
        sys.exit(1)
    print("synth_check: OK — tcl/constraints coherentes con el RTL y la spec")


if __name__ == "__main__":
    main()