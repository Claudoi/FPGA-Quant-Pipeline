#!/usr/bin/env python3
"""Mutación HDL del order book (gate E de /verify, campaña fase2-orderbook).

Cada mutante flipa un guard del order book y corre la suite cocotb; si la
suite queda verde, el mutante sobrevive (test que falta). Uso:

    python3 scripts/verify/mutate_orderbook.py
"""
import subprocess, sys, os, shutil, re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")
TESTDIR = os.path.join(REPO, "verification", "testbenches", "orderbook")
BACKUP = RTL + ".bak"

MUTANTS = [
    ("OV-BEST", "best bid <= en vez de >= (cambio de mejor precio)",
     "ask ? (lpr[j] < lpr[i]) : (lpr[j] > lpr[i])",
     "ask ? (lpr[j] > lpr[i]) : (lpr[j] < lpr[i])"),
    ("OV-EMPTY", "nunca marca overflow de niveles (acepta silencioso)",
     "if (found == -1 && empty == -1) begin",
     "if (found == -1 && empty == -1) begin error <= 1'b1; end else if (found == -1) begin\n                lpr[empty] = price; lpr[empty] = price;"),
    ("U-NOTATOMIC", "replace no atómico (borra la orig pero no añade la nueva)",
     "level_add(o_locate[oref], o_side[oref], o_price[oref], -$signed(o_qty[oref]));\n                        level_add(o_locate[oref], o_side[oref], price, shares);",
     "level_add(o_locate[oref], o_side[oref], o_price[oref], -$signed(o_qty[oref]));"),
    ("D-DOUBLE", "delete descuenta dos veces del nivel",
     "level_add(o_locate[oref], o_side[oref], o_price[oref], -$signed(o_qty[oref]));\n                        o_valid[oref] <= 1'b0;\n                        do_emit = 1'b1;",
     "level_add(o_locate[oref], o_side[oref], o_price[oref], -2*$signed(o_qty[oref]));\n                        o_valid[oref] <= 1'b0;\n                        do_emit = 1'b1;"),
    ("RED-REF", "reduce sobre ref desconocida no cuenta anomalía",
     "did = 1'b0;\n            if (!o_valid[oref]) anomaly_count <= anomaly_count + 1;",
     "did = 1'b0;\n            if (!o_valid[oref]) did = 1'b0;"),
    ("EMIT-NOCHANGED", "changed siempre 0 (rompe el flag de cambio)",
     "changed = (bp != prev_bp[5'(m_locate[4:0])]) || (bq != prev_bq[5'(m_locate[4:0])]) ||\n                      (ap != prev_ap[5'(m_locate[4:0])]) || (aq != prev_aq[5'(m_locate[4:0])]);",
     "changed = 1'b0;"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: {mutant[0]} objetivo no encontrado: {old[:40]!r}")
    if n > 1:
        raise SystemExit(f"ERROR: {mutant[0]} {n} coincidencias (se esperaba 1)")
    return raw.replace(old, new)


def run_suite():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [REPO, os.path.join(REPO, "golden_model"), TESTDIR]) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(["make", "sim"], cwd=TESTDIR, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+)", r.stdout)
    return r.returncode, r.stdout, (int(m.group(3)) if m else -1)


def clean():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    subprocess.run(["make", "clean"], cwd=TESTDIR, env=env,
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
            with open(RTL, "w") as f:
                f.write(apply(mutant, raw))
            _, _, fails = run_suite()
            shutil.move(BACKUP, RTL)
            # limpiar sim_build para que el siguiente mutante recompile fresco
            clean()
            killed = fails > 0
            results.append((mid, killed, fails))
            print(f"[{'MATADO' if killed else 'SOBREVIVE'}] {mid}: FAIL={fails} ({mutant[1]})")
    finally:
        clean()
    survivors = [r for r in results if not r[1]]
    print("\n=== RESUMEN MUTACION ORDERBOOK (gate E) ===")
    for mid, killed, fails in results:
        print(f"  {mid}: {'killed' if killed else 'SOBREVIVE!'}")
    if survivors:
        print("\n" + ", ".join(mid for mid, _, _ in survivors) + " SOBREVIVEN (tests que faltan)")
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES MUERTOS. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()