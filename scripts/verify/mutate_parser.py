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
    ("ALN-OFFBYONE", "offset del body capturado (off-by-one en base)",
     "7'(11 + BYTES*bi)", "7'(12 + BYTES*bi)"),
    ("ALN-PAD-FILL", "relleno del cuerpo en lugar de cero",
     "r[DW-1 - 8*k -: 8] = 8'h0;", "r[DW-1 - 8*k -: 8] = 8'hff;"),
    ("SEQ-GAP-NOGAP", "nunca detecta gap (flip != a ==)",
     "!= exp_seq) gap_detected <= 1'b1;",
     "== exp_seq) gap_detected <= 1'b1;"),
    ("SEQ-GAP-SESSION", "cambio de sesion marca gap (flip != a ==)",
     "pbyte(q,8),pbyte(q,9)} != session_id) begin",
     "pbyte(q,8),pbyte(q,9)} == session_id) begin"),
    ("NEXT-OFFBYONE", "off-by-one en pack_left (vuelve al > 0)",
     "if (pack_left > 1) begin", "if (pack_left > 0) begin"),
    ("LEN-BODY_W", "body_w calculado con ceil incorrecto",
     "8'(BYTES-1)) >> L2B", "8'(BYTES)) >> L2B"),
    ("CAP-SUBSET", "emite aunque no seja subset",
     "st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);",
     "st <= ST_W0;"),
    ("OUT-FREE", "heap sin out_take (re-presenta aunque no accepten)",
     "wire out_free   = !out_valid_reg || out_take;",
     "wire out_free   = !out_valid_reg;"),
    ("LEN-CAPT-ERR", "marca como inválido el borde estructural len=11",
     "(8'({pbyte(q,0), pbyte(q,1)}) < 11) ||",
     "(8'({pbyte(q,0), pbyte(q,1)}) <= 11) ||"),
    ("LEN-H", "acepta H con longitud 24 en lugar de 25",
     "8'h48: explen = 8'd25;", "8'h48: explen = 8'd24;"),
    ("SEQ-ZERO-SESSION", "count cero conserva el esperado de la sesión anterior",
     "                                exp_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),\n                                            pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};\n                                eop_seen <= 1'b0;",
     "                                exp_seq <= exp_seq;\n                                eop_seen <= 1'b0;"),
    ("TRUNC-EOP", "ignora tlast aceptado y no detecta el truncado",
     "if (in_take && s_axis_tlast) eop_seen <= 1'b1;",
     "if (1'b0) eop_seen <= 1'b1;"),
    ("KEEP-ALL-BYTES", "cuenta BYTES aunque el beat final sea parcial",
     "((in_take && in_keep_ok) ? in_nbytes : 8'd0);",
     "((in_take && in_keep_ok) ? 8'(BYTES) : 8'd0);"),
    ("KEEP-LSB-FIRST", "invierte la orientación al compactar lanes válidos",
     "(s_axis_tdata >> (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;",
     "(s_axis_tdata << (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;"),
    ("KEEP-HOLES", "acepta cualquier máscara tkeep no cero",
     "else if (seen_zero) keep_is_msb_prefix = 1'b0;",
     "else if (seen_zero) keep_is_msb_prefix = 1'b1;"),
    ("KEEP-PARTIAL-NONLAST", "acepta un beat parcial sin tlast",
     "wire in_keep_ok = keep_shape_ok &&\n                      (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}});",
     "wire in_keep_ok = keep_shape_ok;"),
    ("KEEP-NODRAIN", "no drena tras una máscara inválida no final",
     "drop_packet <= !s_axis_tlast;", "drop_packet <= 1'b0;"),
    ("COUNT-NO-EOP", "cierra count sin exigir fin de paquete",
     "end else if (eop_eff && qn_post == 0) begin",
     "end else if (qn_post == 0) begin"),
    ("COUNT-RESIDUAL", "cierra count aunque queden bytes residuales",
     "end else if (eop_eff && qn_post == 0) begin",
     "end else if (eop_eff) begin"),
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
        raise SystemExit(f"mutante {only} no encontrado")
    for mutant in selected:
        apply(mutant, raw)
    if os.path.exists(BACKUP):
        raise SystemExit(f"ERROR: existe backup previo: {BACKUP}")
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
            status = "MATADO" if killed else ("SOBREVIVE" if compiled else "ERROR")
            killers = ",".join(failed_tests) if failed_tests else "-"
            print(f"[{status}] {mid}: compiló={'sí' if compiled else 'no'} "
                  f"FAIL={fails} tests={killers} ({mutant[1]})")
    finally:
        if os.path.exists(BACKUP):
            shutil.move(BACKUP, RTL)
        # Deja el sim_build limpio: el makefile no recompila RTL si el objeto
        # queda con timestamp del mutante (evita falsos verdes en la suite real).
        import glob
        subprocess.run(["make", "clean"], cwd=TESTDIR,
                       env=dict(os.environ), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    survivors = [r for r in results if not r[2]]
    print("\n=== RESUMEN MUTACION (gate E) ===")
    for mid, compiled, killed, fails, failed_tests in results:
        print(f"  {mid}: {'killed' if killed else 'SOBREVIVE!'}")
    if survivors:
        print(f"\n{len(survivors)} MUTANTES SOBREVIVEN (tests que faltan): "
              + ", ".join(r[0] for r in survivors))
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES MUERTOS. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
