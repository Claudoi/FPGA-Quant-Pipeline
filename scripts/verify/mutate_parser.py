#!/usr/bin/env python3
"""Mutación HDL del parser ITCH (gate E de /verify, campaña fase1-parser-rtl).

Cada mutante aplica un flip sobre el RTL y corre la suite cocotb; si la suite
queda verde, el mutante sobrevive (test que falta). Uso:

    python3 mutate_parser.py                  # todos los mutantes
    python3 mutate_parser.py --mutant S1NEXT  # uno solo, con detalle

Los mutantes (strings exactos que se deben APLICAR; se verifica que aparecen):
"""
import subprocess
import sys
import os
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "parser", "itch_parser.sv")
TESTDIR = os.path.join(REPO, "verification", "testbenches", "parser")
BACKUP = RTL + ".bak"

# (id, descripcion, old, new) — old debe existir exactamente una vez en el RTL.
MUTANTS = [
    ("ALN-OFFBYONE", "offset del body en criado (off-by-one en base)",
     "11 + 8*bi", "11 + 8*bi + 8"),
    ("ALN-PAD-FILL", "relleno del cuerpo en lugar de cero",
     "r[63 - 8*k -: 8] = 8'h0;", "r[63 - 8*k -: 8] = 8'hff;"),
    ("SEQ-GAP-NOGAP", "nunca detecta gap (flip != a ==)",
     "!= exp_seq) gap_detected <= 1'b1;",
     "== exp_seq) gap_detected <= 1'b1;"),
    ("SEQ-GAP-SESSION", "cambio de sesion marca gap (flip != a ==)",
     "pbyte(q,8),pbyte(q,9)} != session_id) begin",
     "pbyte(q,8),pbyte(q,9)} == session_id) begin"),
    ("NEXT-OFFBYONE", "off-by-one en pack_left (vuelve al > 0)",
     "if (pack_left > 1) begin", "if (pack_left > 0) begin"),
    ("LEN-BODY_W", "body_w calculado con ceil incorrecto",
     "- 8'd11 + 8'd7) >> 3", "- 8'd11) >> 3"),
    ("CAP-SUBSET", "emite aunque no seja subset",
     "st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);",
     "st <= ST_W0;"),
    ("OUT-FREE", "heap sin out_take (re-presenta aunque no accepten)",
     "wire out_free   = !out_valid_reg || out_take;",
     "wire out_free   = !out_valid_reg;"),
    ("LEN-CAPT-ERR", "no marca error si len < 11 (off-by-one)",
     "if (8'({pbyte(q,0), pbyte(q,1)}) < 11) error <= 1'b1;",
     "if (8'({pbyte(q,0), pbyte(q,1)}) <= 11) error <= 1'b1;"),
    ("TRUNC-EOP", "ignora el latch de truncado en el mensaje incompleto",
     "if (8'({pbyte(q,0), pbyte(q,1)}) < 11) error <= 1'b1;\n                            eop_seen <= 1'b0;\n                            st <= ST_CAP;\n                        end else if (eop_seen) begin",
     "if (8'({pbyte(q,0), pbyte(q,1)}) < 11) error <= 1'b1;\n                            eop_seen <= 1'b0;\n                            st <= ST_CAP;\n                        end else if (1'b0) begin"),
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


def run_suite():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [REPO, os.path.join(REPO, "golden_model"), TESTDIR]) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        ["make", "sim"], cwd=TESTDIR,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # verde si TESTS=.. PASS=.. y FAIL=0
    import re
    m = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+)", r.stdout)
    return r.returncode, r.stdout, (int(m.group(3)) if m else -1)


def main():
    args = sys.argv[1:]
    only = None
    if args and args[0] == "--mutant":
        only = args[1]
    raw = open(RTL).read()
    mutated_any = False
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
            rc, out, fails = run_suite()
            # restaurar
            shutil.move(BACKUP, RTL)
            killed = (fails > 0)
            results.append((mid, killed, fails))
            print(f"[{'MATADO' if killed else 'SOBREVIVE'}] {mid}: FAIL={fails} "
                  f"({mutant[1]})")
            mutated_any = True
    finally:
        # Deja el sim_build limpio: el makefile no recompila RTL si el objeto
        # queda con timestamp del mutante (evita falsos verdes en la suite real).
        import glob
        subprocess.run(["make", "clean"], cwd=TESTDIR,
                       env=dict(os.environ), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    if (only and not any(r[0] == only for r in results)):
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