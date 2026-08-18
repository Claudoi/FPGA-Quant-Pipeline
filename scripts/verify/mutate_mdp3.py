#!/usr/bin/env python3
"""Gate E del parser MDP3: cada mutante debe compilar y morir en cocotb."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
RTL = REPO / "rtl/parser/mdp3_parser.sv"
TESTDIR = REPO / "verification/testbenches/mdp3"
BACKUP = RTL.with_suffix(".sv.bak")

MUTANTS = [
    ("TPL47-ID", "template 47 deja de pertenecer al subset",
     "TPL_47 = 16'd47", "TPL_47 = 16'd48"),
    ("TRUNC-NOERROR", "el truncado por tlast no señaliza error",
     "error <= 1;   // mensaje truncado por tlast",
     "error <= 0;   // mutante: truncado silenciado"),
    ("SEQ-NOGAP", "el comparador de secuencia se invierte",
     "if (first_pkt && seq != exp_seq)", "if (first_pkt && seq == exp_seq)"),
    ("GROUP-COUNT", "numInGroup se lee un byte antes",
     "g1_n  <= mrb(32'(MSG_PREFIX) + O46_DIM + 2, dec_sel);",
     "g1_n  <= mrb(32'(MSG_PREFIX) + O46_DIM + 1, dec_sel);"),
    ("GROUP-BOUNDS", "se omite el límite del grupo template 47",
     "(d_tpl == TPL_47 &&\n                         32'(g1_base) + 32'(g1_n) * 32'(O47_BL) > 32'(d_size)) ||",
     "(d_tpl == TPL_47 && 1'b0) ||"),
    ("PASS-NOBODY", "passthrough termina después de w0/w1",
     "p_n <= (d_size == 16'(MSG_PREFIX)) ? 3 : 2;", "p_n <= 3;"),
    ("PRICE-SWAP", "mantissa y exponente se intercambian en template 47",
     "rrec[13] <= mru32(eb + O47_PX, dec_sel);\n                                rrec[14] <= mru32(eb + O47_PX + 4, dec_sel);\n                                rrec[15] <= {EXP_BYTE, 24'h0};",
     "rrec[13] <= {EXP_BYTE, 24'h0};\n                                rrec[14] <= mru32(eb + O47_PX + 4, dec_sel);\n                                rrec[15] <= mru32(eb + O47_PX, dec_sel);"),
    ("PUSH-IDLE", "no se libera el buffer al encolar la última word",
     "if (r_idx == rlen - 1 &&\n                                ((g1_mode",
     "if (1'b0 &&\n                                ((g1_mode"),
    ("TKCNT-ALWAYS", "el beat avanza siempre BYTES (la máscara no limita el aporte)",
     "qw <= 8'((32'(qw) + 32'(tk_cnt)) % 32'(MAX_MSG));",
     "qw <= 8'((32'(qw) + 32'(BYTES)) % 32'(MAX_MSG));"),
]


def env():
    result = dict(os.environ)
    result["PATH"] = str(REPO / ".venv/bin") + os.pathsep + result.get("PATH", "")
    result["PYTHONPATH"] = os.pathsep.join(
        (str(REPO), str(REPO / "golden_model"), str(TESTDIR)))
    return result


def mutate(raw: str, mutant) -> str:
    mid, _, old, new = mutant
    count = raw.count(old)
    if count != 1:
        raise RuntimeError(f"{mid}: objetivo encontrado {count} veces, se esperaba 1")
    return raw.replace(old, new)


def clean():
    subprocess.run(["make", "clean-all"], cwd=TESTDIR, env=env(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def compiles() -> bool:
    for width in (32, 64):
        result = subprocess.run(
            ["verilator", "--lint-only", "--Wall", f"-GDW={width}",
             "--top-module", "mdp3_parser", str(RTL)],
            cwd=REPO, env=env(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            print(result.stdout)
            return False
    return True


def run_suites():
    for target in ("sim", "sim-dw64"):
        clean()
        result = subprocess.run(
            ["make", target], cwd=TESTDIR, env=env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        match = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+)", result.stdout)
        if not match:
            print(result.stdout)
            return None, target
        failures = int(match.group(3))
        if failures:
            return failures, target
        if result.returncode:
            print(result.stdout)
            return None, target
    return 0, "DW32+DW64"


def main():
    only = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--mutant" else None
    selected = [m for m in MUTANTS if only is None or m[0] == only]
    if not selected:
        raise SystemExit(f"mutante desconocido: {only}")

    raw = RTL.read_text()
    results = []
    try:
        for mutant in selected:
            mid, description, _, _ = mutant
            BACKUP.write_text(raw)
            try:
                RTL.write_text(mutate(raw, mutant))
                clean()
                if not compiles():
                    failures, suite = None, "lint"
                else:
                    failures, suite = run_suites()
            finally:
                shutil.move(BACKUP, RTL)
                clean()
            killed = failures is not None and failures > 0
            results.append((mid, killed, failures, suite))
            status = "MATADO" if killed else ("ERROR" if failures is None else "SOBREVIVE")
            print(f"[{status}] {mid}: FAIL={failures} en {suite} ({description})")
    finally:
        if BACKUP.exists():
            shutil.move(BACKUP, RTL)
        clean()

    print("\n=== RESUMEN MUTACION MDP3 (gate E) ===")
    for mid, killed, failures, suite in results:
        print(f"  {mid}: {'killed' if killed else 'NO CERRADO'} ({suite}, FAIL={failures})")
    if any(not killed for _, killed, _, _ in results):
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES COMPILAN Y MUEREN. Gate E PASS.")


if __name__ == "__main__":
    main()
