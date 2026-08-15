#!/usr/bin/env python3
"""Mutación HDL del parser CME MDP 3.0 (gate E de /verify, fase4-mdp3-parser).

Cada mutante aplica un flip sobre `rtl/parser/mdp3_parser.sv` y corre la suite
cocotb completa del área (framing + robustez); si queda verde, el mutante
sobrevive (test que falta). Los tipos de mutante siguen la lista de la spec
(§Verificación): template lookup off-by-one, msg_size sin comprobar, seq sin
comparar, grupo con numInGroup mal contado, passthrough sin bytes y precio con
exponente descontrolado.

    python3 mutate_mdp3.py                  # todos los mutantes
    python3 mutate_mdp3.py --mutant SEQ-GAP # uno solo, con detalle
"""
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "parser", "mdp3_parser.sv")
TESTDIR = os.path.join(REPO, "verification", "testbenches", "mdp3")
BACKUP = RTL + ".bak"

RUNS = [
    ["make", "sim"],
    ["make", "sim", "MODULE=test_mdp3_robustez"],
]

# (id, descripcion, old, new) — old debe existir exactamente una vez en el RTL.
MUTANTS = [
    ("SEQ-GAP", "nunca detecta gap (flip != a ==)",
     "first_pkt && seq != exp_seq", "first_pkt && seq == exp_seq"),
    ("EXP-UNCOND", "exponente MBOFD 46 sin gatear (contrato #5)",
     "rrec[15] <= (rref < g1_n) ? {EXP_BYTE, 24'h0} : 32'd0;",
     "rrec[15] <= {EXP_BYTE, 24'h0};"),
    ("REF-INDEX-OOB", "ReferenceID fuera de rango off-by-one (le <= a <)",
     "rrec[5] <= (rref < g1_n)", "rrec[5] <= (rref <= g1_n)"),
    ("NUMGROUP-52", "numInGroup del 52 leído un byte antes (off-by-one)",
     "O52_DIM + 2", "O52_DIM + 1"),
    ("BODY-BASE-46", "base del body del 46 desplazada un byte",
     "+ 16'(O46_ENT)", "+ 16'(O46_ENT) + 1"),
    ("PASS-NOBODY", "passthrough no emite el cuerpo crudo",
     "if (p_off < d_size) begin", "if (1'b0) begin"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: el mutante {mutant[0]} no encuentra su objetivo "
                         f"(count=0). old={old!r}")
    if n > 1:
        raise SystemExit(f"ERROR: el mutante {mutant[0]} encuentra {n} objetivos "
                         f"(se esperaba exactamente 1). old={old!r}")
    return raw.replace(old, new)


def _fails(stdout: str) -> int:
    m = re.search(r"TESTS=\d+ PASS=\d+ FAIL=(\d+)", stdout)
    return int(m.group(1)) if m else -1


def run_suite():
    """Corre framing + robustez; verdes si ambos acaban sin FAIL."""
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [REPO, os.path.join(REPO, "golden_model"), TESTDIR]) + os.pathsep + env.get("PYTHONPATH", "")
    total = 0
    for cmd in RUNS:
        r = subprocess.run(cmd, cwd=TESTDIR, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        total += max(_fails(r.stdout), 0)
        if total:
            break
    return total


def main():
    args = sys.argv[1:]
    only = None
    if args and args[0] == "--mutant":
        only = args[1]
    raw = open(RTL).read()
    results = []
    try:
        for mutant in MUTANTS:
            mid = mutant[0]
            if only and only != mid:
                continue
            with open(BACKUP, "w") as f:
                f.write(raw)
            mut = apply(mutant, raw)
            with open(RTL, "w") as f:
                f.write(mut)
            fails = run_suite()
            shutil.move(BACKUP, RTL)
            killed = (fails > 0)
            results.append((mid, killed, fails))
            print(f"[{'MATADO' if killed else 'SOBREVIVE'}] {mid}: FAIL={fails} "
                  f"({mutant[1]})")
    finally:
        import glob
        subprocess.run(["make", "clean"], cwd=TESTDIR, env=dict(os.environ),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if only and not any(r[0] == only for r in results):
        raise SystemExit(f"mutante {only} no encontrado")

    survivors = [r for r in results if not r[1]]
    print("\n=== RESUMEN MUTACION (gate E) ===")
    for mid, killed, fails in results:
        print(f"  {mid}: {'killed' if killed else 'SOBREVIVE!'}")
    if survivors:
        print(f"\n{len(survivors)} MUTANTES SOBREVIVEN (tests que faltan): "
              + ", ".join(mid for mid, _, _ in survivors))
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES MUERTOS. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
