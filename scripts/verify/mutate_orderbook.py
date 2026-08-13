#!/usr/bin/env python3
"""Mutación HDL del order book (gate E de /verify, campaña fase3-optimizacion).

Cada mutante flipa un guard de la tabla hashada (criterio 5) o del engine de
fases 2-3 y corre ambas suites cocotb (fase 2 a DW=64 y phase3 hash a K=20);
si ninguna suite se pone roja, el mutante sobrevive (test que falta). Uso:

    python3 scripts/verify/mutate_orderbook.py [--mutant <ID>]
"""
import subprocess, sys, os, shutil, re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")
BACKUP = RTL + ".bak"
# (área, comando make): la fase 2 corre el feed real a DW=64 (REPLAY-01),
# phase3 corre la suite hash a K=20 (probe agotado y tabla llena reales),
# la suite depth a DW=32 (top-N vs golden, DP-01/DP-02) y la suite hard
# (símbolo 21 y retención bajo backpressure, SEC-NSYM-01/SEC-BP-01).
SUITES = [
    ("verification/testbenches/orderbook", ["make", "sim"]),
    ("verification/testbenches/phase3", ["make", "sim-hash"]),
    ("verification/testbenches/phase3", ["make", "sim-depth"]),
    ("verification/testbenches/phase3", ["make", "sim-hard"]),
]

MUTANTS = [
    ("OV-BEST", "best bid <= en vez de >= (cambio de mejor precio)",
     "ask ? (lpr[j] < lpr[i]) : (lpr[j] > lpr[i])",
     "ask ? (lpr[j] > lpr[i]) : (lpr[j] < lpr[i])"),
    ("OV-EMPTY", "nunca marca overflow de niveles (acepta silencioso)",
     "if (found == -1 && empty == -1) begin",
     "if (found == -1 && empty == -1) begin error <= 1'b1; end else if (found == -1) begin\n                lpr[empty] = price; lpr[empty] = price;"),
    ("U-NOTATOMIC", "replace no atómico (borra la orig pero no añade la nueva)",
     "level_add(u_side, u_price, u_shares);\n                o_valid[nidx] <= 1'b1;",
     "o_valid[nidx] <= 1'b1;"),
    ("U-DELETE-HALF", "replace conserva la qty de la orig en el nivel (doble cuenta)",
     "level_add(o_side[sidx], o_price[sidx], -$signed(o_qty[sidx]));\n                            o_valid[sidx] <= 1'b0;\n                            u_newref <= newref;",
     "o_valid[sidx] <= 1'b0;\n                            u_newref <= newref;"),
    ("U-SKIP-ROUTE", "replace no entra en ST_UADD (la nueva ref nunca se registra)",
     "if (do_uadd) st <= ST_UADD;",
     "if (do_uadd) st <= ST_EMIT;"),
    ("D-DOUBLE", "delete descuenta dos veces del nivel",
     "level_add(o_side[sidx], o_price[sidx], -$signed(o_qty[sidx]));\n                        o_valid[sidx] <= 1'b0;\n                        do_emit = 1'b1;",
     "level_add(o_side[sidx], o_price[sidx], -2*$signed(o_qty[sidx]));\n                        o_valid[sidx] <= 1'b0;\n                        do_emit = 1'b1;"),
    ("RED-REF", "reduce sobre ref desconocida no cuenta anomalía",
     "if (!found) anomaly_count <= anomaly_count + 1;\n                    else reduce_order(sidx, b32(8), do_emit);",
     "reduce_order(sidx, b32(8), do_emit);"),
    ("EMIT-NOCHANGED", "changed siempre 0 (rompe el flag de cambio)",
     "changed = (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);",
     "changed = 1'b0;"),
    ("HASH-NOREF", "el lookup no compara el ref (colisión -> op sobre la ref equivocada)",
     "if (o_valid[h + SLOT'(ii)] && o_ref[h + SLOT'(ii)] == r) begin",
     "if (o_valid[h + SLOT'(ii)]) begin"),
    ("HASH-LOOKUP-BOUND", "lookup proba de menos (off-by-one: la ref del último slot no se encuentra)",
     "for (ii = 0; ii < PROBE; ii = ii + 1) begin\n            if (o_valid[h + SLOT'(ii)] && o_ref[h + SLOT'(ii)] == r) begin",
     "for (ii = 0; ii < PROBE - 1; ii = ii + 1) begin\n            if (o_valid[h + SLOT'(ii)] && o_ref[h + SLOT'(ii)] == r) begin"),
    ("HASH-INSERT-BOUND", "insert proba de menos (el 8º add del hash dice tabla llena)",
     "for (ii = 0; ii < PROBE; ii = ii + 1) begin\n            if (!o_valid[h + SLOT'(ii)]) begin",
     "for (ii = 0; ii < PROBE - 1; ii = ii + 1) begin\n            if (!o_valid[h + SLOT'(ii)]) begin"),
    ("HASH-FULLNOCHECK", "tabla llena inserta igual (wrap/overwrite silencioso)",
     "if (full) begin\n                            error <= 1'b1;  // tabla llena (SEC-HASH-02)",
     "if (1'b0) begin\n                            error <= 1'b1;  // tabla llena (SEC-HASH-02)"),
    ("HASH-UADD-FULL", "la mitad add del replace llena inserta igual (wrap)",
     "if (full) begin\n                error <= 1'b1;\n                emit_ok <= 1'b0;",
     "if (1'b0) begin\n                error <= 1'b1;\n                emit_ok <= 1'b0;"),
    ("HASH-DUPNOCHECK", "add con ref duplicada no señala error",
     "if (found || shares == 0) begin",
     "if (shares == 0) begin"),
    ("HASH-INSERT-NOVALID", "el insert no marca valid (la orden nunca aparece)",
     "o_valid[nidx] <= 1'b1;\n                            o_ref[nidx]   <= oref;",
     "o_ref[nidx]   <= oref;"),
    ("DP-BADORDER", "el top-N invierte el orden (peor nivel primero)",
     "dacc = {dacc[2*ND*64-65:0],\n                        lv_price[m_loc_idx*2*P + di][31:0],\n                        lv_qty[m_loc_idx*2*P + di][31:0]};",
     "dacc = {dacc[2*ND*64-65:0],\n                        lv_price[m_loc_idx*2*P + (ND-1-di)][31:0],\n                        lv_qty[m_loc_idx*2*P + (ND-1-di)][31:0]};"),
    ("DP-ASKSWAP", "el top-N emite el ask en el grupo del bid (y viceversa)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        lv_price[m_loc_idx*2*P + P + di][31:0],\n                        lv_qty[m_loc_idx*2*P + P + di][31:0]};",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        lv_price[m_loc_idx*2*P + di][31:0],\n                        lv_qty[m_loc_idx*2*P + di][31:0]};"),
    ("DP-NOVALID", "depth nunca se valida (el consumidor ve 0)",
     "depth_tdata <= dacc;\n            depth_tvalid <= 1'b1;",
     "depth_tdata <= dacc;"),
    ("DP-EMPTYSTALE", "el nivel vacío conserva el precio stale (el depth filtra precios muertos)",
     "lqt[found] = 0;\n                    lpr[found] = 0;",
     "lqt[found] = 0;"),
    ("NSYM-GUARD", "sin guard del símbolo 21 (el locate fuera del subset entra con m_loc_idx=31 -> OOB)",
     "bad_sym <= 1'b1;\n                            error <= 1'b1;\n                            m_loc_idx <= 0;\n                        end else begin\n                            m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);",
     "m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);"),
    ("BP-NORET", "el par BBO/depth no se retiene (se pierde si tready=0 durante el evento)",
     "bbo_tvalid <= bbo_tvalid && !bbo_tready;",
     "bbo_tvalid <= 1'b0;"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: {mutant[0]} objetivo no encontrado: {old[:40]!r}")
    if n > 1:
        raise SystemExit(f"ERROR: {mutant[0]} {n} coincidencias (se esperaba 1)")
    return raw.replace(old, new)


def run_suites():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.pathsep.join([REPO, os.path.join(REPO, "golden_model")]) + \
        os.pathsep + env.get("PYTHONPATH", "")
    fails = 0
    for area, cmd in SUITES:
        r = subprocess.run(cmd, cwd=os.path.join(REPO, area), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        m = re.search(r"TESTS=\d+ PASS=\d+ FAIL=(\d+)", r.stdout)
        if m:
            fails += int(m.group(1))
        elif r.returncode != 0:
            fails += 999
    return fails


def clean():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    for area, _ in SUITES:
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
            with open(RTL, "w") as f:
                f.write(apply(mutant, raw))
            fails = run_suites()
            shutil.move(BACKUP, RTL)
            clean()
            killed = fails > 0
            results.append((mid, killed, fails))
            print(f"[{'MATADO' if killed else 'SOBREVIVE'}] {mid}: FAIL={fails} ({mutant[1]})")
    finally:
        clean()
    survivors = [r for r in results if not r[1]]
    print("\n=== RESUMEN MUTACION ORDERBOOK (gate E, fase 3 iter 2) ===")
    for mid, killed, fails in results:
        print(f"  {mid}: {'killed' if killed else 'SOBREVIVE!'}")
    if survivors:
        print("\n" + ", ".join(mid for mid, _, _ in survivors) + " SOBREVIVEN (tests que faltan)")
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES MUERTOS. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()