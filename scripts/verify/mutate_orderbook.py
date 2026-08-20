#!/usr/bin/env python3
"""Mutación HDL del order book (gate E de /verify, campaña fase3-uram).

Cada mutante flipa un guard de la tabla URAM (sonda serializada + prefetch),
del pipeline de niveles (etapas registradas), del pipeline de emisión
(A/B/C, iter 7) o del engine de fases 2-3 y corre las suites cocotb (fase 2
a DW=64, phase3 hash/depth/hard/rtm y uram a K=20); si ninguna suite se pone
roja, el mutante sobrevive (test que falta). Uso:

    python3 scripts/verify/mutate_orderbook.py [--mutant <ID>]
"""
import subprocess, sys, os, shutil, re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl", "orderbook", "orderbook.sv")
BACKUP = RTL + ".bak"
# (área, comando make): la fase 2 corre el feed real a DW=64 (REPLAY-01),
# phase3 corre la suite hash a K=20 (probe agotado y tabla llena reales),
# la suite depth a DW=32 (top-N vs golden, DP-01/DP-02), la suite hard
# (símbolo 21 y retención bajo backpressure, SEC-NSYM-01/SEC-BP-01), la suite
# rtm (pipeline de emisión A/B/C, RTM-01..04 a DW=32 y RTM-REG-01 a DW=64,
# iter 7) y el área uram (SEC-URAM-01/02/03: sonda serializada, prefetch y
# pipeline registrado).
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
    ("OV-BEST", "best bid <= en vez de >= (cambio de mejor precio)",
     "lv_beat[i] <= (lv_qty[base+i] != 0) &&\n                              (ask ? (lv_price[base+i] > price)\n                                   : (lv_price[base+i] < price));",
     "lv_beat[i] <= (lv_qty[base+i] != 0) &&\n                              (ask ? (lv_price[base+i] < price)\n                                   : (lv_price[base+i] > price));"),
    ("OV-EMPTY", "push-out: el descarte SEC-OV en el desborde no señala error (reduce-ausente y add peor que el peor aceptados en silencio)",
     "if (lv_delta[31]) begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b1;\n                end else if (lv2_abtx) begin\n                    lv2_mode <= LV_MODE_INSERT;\n                end else begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b1;\n                end",
     "if (lv_delta[31]) begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b0;\n                end else if (lv2_abtx) begin\n                    lv2_mode <= LV_MODE_INSERT;\n                end else begin\n                    lv2_mode <= LV_MODE_NONE;\n                    lverr = 1'b0;\n                end"),
    ("U-NOTATOMIC", "replace no atómico (borra la orig pero no añade la nueva)",
     "launch_lv(u_side, u_price, u_shares);\n                    wr_en = 1'b1;\n                    wr_addr = u_nidx;\n                    wr_data = entry_new(u_newref, u_side, u_price, u_shares);",
     "launch_lv(u_side, u_price, u_shares);"),
    ("U-DELETE-HALF", "replace conserva la qty de la orig en el nivel (doble cuenta)",
     "launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));\n                        wr_en = 1'b1;\n                        wr_addr = pr_slot;\n                        wr_data = {OW{1'b0}};\n                        u_newref <= newref;",
     "launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));\n                        u_newref <= newref;"),
    ("U-SKIP-ROUTE", "replace no entra en ST_UADD (la nueva ref nunca se registra)",
     "st <= lv_uadd ? ST_UADD : ST_EMIT_A;",
     "st <= ST_EMIT_A;"),
    ("D-DOUBLE", "delete descuenta dos veces del nivel",
     "8'h44: begin\n                    oref = K'(b64(0));\n                    if (!pr_found) anomaly_count <= anomaly_count + 1;\n                    else begin\n                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));",
     "8'h44: begin\n                    oref = K'(b64(0));\n                    if (!pr_found) anomaly_count <= anomaly_count + 1;\n                    else begin\n                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),\n                                  -2*$signed(e_qty(pr_entry[OW-1:OW-QW])));"),
    ("RED-REF", "reduce sobre ref desconocida no cuenta anomalía",
     "if (!pr_found) begin\n                        anomaly_count <= anomaly_count + 1;\n                    end else begin",
     "if (1'b0) begin\n                        anomaly_count <= anomaly_count + 1;\n                    end else begin"),
    ("QTY-NOERROR", "reduce por encima de la cantidad no señala error",
     "if (rest[33]) error <= 1'b1;   // execute > restante",
     "if (rest[33]) error <= 1'b0;   // execute > restante"),
    ("EMIT-NOCHANGED", "changed siempre 0 (rompe el flag de cambio)",
     "sm_changed <= (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                          (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);",
     "sm_changed <= 1'b0;"),
    ("HASH-NOREF", "el lookup no compara el ref (colisión -> op sobre la ref equivocada)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (rd_data[0]) begin"),
    ("REF-TRUNC", "comparación del ref truncada a 19 bits (replica el bug K=19 pre-iter 12: refs que comparten el residuo mod 2^19 colisionan)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (rd_data[0] && (rd_data[19:1] == pr_target[18:0])) begin"),
    ("HASH-LOOKUP-BOUND", "la sonda proba de menos (off-by-one: la ref del último slot no se encuentra)",
     "if (pr_i == 16'(PROBE-1)) begin",
     "if (pr_i == 16'(PROBE-2)) begin"),
    ("HASH-FULLNOCHECK", "tabla llena inserta igual (wrap/overwrite silencioso)",
     "if (pr_full) begin\n                        error <= 1'b1;      // tabla llena (SEC-HASH-02)",
     "if (1'b0) begin\n                        error <= 1'b1;      // tabla llena (SEC-HASH-02)"),
    ("HASH-UADD-FULL", "el U con el camino del newref lleno aplica el delete igualmente (la original se pierde)",
     "else if (pr_new_full) error <= 1'b1;    // U atómico: la",
     "else if (1'b0) error <= 1'b1;    // U atómico: la"),
    ("HASH-DUPNOCHECK", "add con ref duplicada no señala error",
     "if (pr_found || shares == 0) begin",
     "if (shares == 0) begin"),
    ("HASH-INSERT-NOVALID", "el insert no escribe la entrada (la orden nunca aparece)",
     "wr_en = 1'b1;\n                        wr_addr = pr_empty;\n                        wr_data = entry_new(oref, ask, price, shares);",
     "wr_en = 1'b0;\n                        wr_addr = pr_empty;\n                        wr_data = entry_new(oref, ask, price, shares);"),
    ("URAM-COMB-INDEX", "la sonda indexa la tabla combinacionalmente (patrón de URAM roto)",
     "if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin",
     "if (o_mem[pr_base + pr_i][0] && (o_mem[pr_base + pr_i][REFW:1] == pr_target)) begin"),
    ("URAM-NO-PREFETCH", "sin prefetch del grupo de hash en ST_BODY (lookup entra en ST_APPLY)",
     "if (bi == 4'd1 && lt(m_type)) begin",
     "if (bi == 4'd1 && lt(m_type) && 1'b0) begin"),
    ("PIPE-SKIP-STAGE", "el pipeline salta la etapa 2b (el decode de prioridad nunca corre, lv2_* stale)",
     "if (s_axis_tvalid && !nx_done) nx_recv();\n                    decode_lv2b();",
     "if (s_axis_tvalid && !nx_done) nx_recv();\n                    if (1'b0) decode_lv2b();"),
    ("LV-STALE-STAGE", "la etapa 3 escribe la qty pre-op (nivel stale, el delta se pierde)",
     "wq[i] = (i == lv2_found) ? QW'(lv2_newq[31:0]) : lv_qt[i];",
     "wq[i] = lv_qt[i];"),
    ("DP-BADORDER", "el top-N invierte el orden (peor nivel primero)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[ND-1-di][31:0],\n                        sm_cap_qt[ND-1-di][31:0]};"),
    ("DP-ASKSWAP", "el top-N emite el ask en el grupo del bid (y viceversa)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[P+di][31:0],\n                        sm_cap_qt[P+di][31:0]};",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};"),
    ("DP-NOVALID", "depth nunca se valida (el consumidor ve 0)",
     "depth_tdata <= sm_dacc;\n                        depth_tvalid <= 1'b1;",
     "depth_tdata <= sm_dacc;"),
    ("DP-TOPNCOUNT", "el top-N emite ND-1 niveles (el último queda fuera del bus)",
     "for (di = 0; di < ND; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "for (di = 0; di < ND-1; di = di + 1)\n                dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};"),
    ("NSYM-GUARD", "sin guard del símbolo 21 (el locate fuera del subset entra con m_loc_idx=31 -> OOB)",
     "bad_sym <= 1'b1;\n                            error <= 1'b1;\n                            m_loc_idx <= 0;\n                        end else begin\n                            m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);",
     "m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);"),
    ("BP-NORET", "el par BBO/depth no se retiene (se pierde si tready=0 durante el evento)",
     "bbo_tvalid <= bbo_tvalid && !bbo_tready;",
     "bbo_tvalid <= 1'b0;"),
    ("LV-NEGWRAP", "el reduce sobre nivel ausente escribe la cantidad envuelta (phantom ~4,29e9)",
     "            end else if (!lv2_afnd && lv_delta[31]) begin\n                // reduce sobre un nivel que no existe (orden en tabla sin\n                // nivel por overflow previo): jamás una cantidad envuelta\n                // (hallazgo G5)\n                lv2_mode <= LV_MODE_NONE;",
     "            end else if (!lv2_afnd && lv_delta[31]) begin\n                // reduce sobre un nivel que no existe (orden en tabla sin\n                // nivel por overflow previo): jamás una cantidad envuelta\n                // (hallazgo G5)\n                lv2_mode <= LV_MODE_INSERT;"),
    # --- mutantes del pipeline de emisión (addendum iter 7) ---
    ("EMIT-NOCAPTURE", "etapa A omitida: la selección lee la captura stale (sm_cap_*)",
     "if (emit_ok) capture_emit_a();",
     "if (1'b0) capture_emit_a();"),
    ("EMIT-FINDFIRST-INV", "prioridad del find-first invertida (primer slot vacío, no el mejor)",
     "sm_bsel <= first_one(nzb_next);",
     "sm_bsel <= first_one(~nzb_next);"),
    ("EMIT-CHANGED-WRONG-PREV", "changed compara el bid contra el prev del ask (flag erróneo)",
     "sm_changed <= (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                          (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);",
     "sm_changed <= (bp != prev_ap[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||\n                          (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);"),
    ("EMIT-DEPTH-WRONGSIDE", "el depth del bid se empaqueta desde el grupo ask capturado",
     "dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[di][31:0],\n                        sm_cap_qt[di][31:0]};",
     "dacc = {dacc[2*ND*64-65:0],\n                        sm_cap_px[P+di][31:0],\n                        sm_cap_qt[P+di][31:0]};"),
]


def apply(mutant, raw):
    _, _, old, new = mutant
    n = raw.count(old)
    if n == 0:
        raise SystemExit(f"ERROR: {mutant[0]} objetivo no encontrado: {old[:40]!r}")
    if n > 1:
        raise SystemExit(f"ERROR: {mutant[0]} {n} coincidencias (se esperaba 1)")
    return raw.replace(old, new)


def apply_safe(mutant, raw):
    # escribe el mutante en un archivo temporal y solo reemplaza el RTL si el
    # patrón se encontró: un SystemExit de apply() NUNCA puede truncar el RTL
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
    """el mutante debe seguir compilando: un archivo roto NO cuenta como kill
    (mataría el gate con un falso positivo)."""
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    r = subprocess.run(
        ["verilator", "--lint-only", "-Wall",
         "-Wno-BLKSEQ", "-Wno-WIDTHEXPAND", "-Wno-CASEOVERLAP",
         "-Wno-CASEINCOMPLETE",
         "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM",  # el mutante suele dejar
                            # señales sin usar (colateral esperado del flip)
                            # -Wno-BLKSEQ: los 9 blocking-assigments de tasks
                            # (estilo preexistente en HEAD, iter 13) tumban el
                            # lint de TODOS los candidatos sin ser culpa del
                            # mutante
         "--top-module", "orderbook", "rtl/orderbook/orderbook.sv"],
        cwd=REPO, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.returncode == 0


def clean():
    env = dict(os.environ)
    env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env.get("PATH", "")
    for area, _ in SUITES:
        # clean-all borra los SIM_BUILD dedicados (phase3: sim_build_hash,
        # sim_build_chain, ...) que el clean de cocotb deja intactos: un cache
        # construido con un mutante aplicado se reutilizaría en silencio
        # (falso FAIL post-restauración, hallazgo iter 5).
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
                    fails = -1   # archivo roto: ni kill ni survive — error de mutación
                else:
                    fails = run_suites()
            finally:
                if os.path.exists(BACKUP):
                    shutil.move(BACKUP, RTL)
                clean()
            killed = fails > 0
            if fails == -1:
                print(f"[ERROR] {mid}: el mutante no compila (lint) — NO cuenta como kill")
            else:
                results.append((mid, killed, fails))
                print(f"[{'MATADO' if killed else 'SOBREVIVE'}] {mid}: FAIL={fails} ({mutant[1]})")
    finally:
        clean()
    survivors = [r for r in results if not r[1]]
    print("\n=== RESUMEN MUTACION ORDERBOOK (gate E, fase3-uram iter 6) ===")
    for mid, killed, fails in results:
        print(f"  {mid}: {'killed' if killed else 'SOBREVIVE!'}")
    if survivors:
        print("\n" + ", ".join(mid for mid, _, _ in survivors) + " SOBREVIVEN (tests que faltan)")
        raise SystemExit(1)
    print("\nTODOS LOS MUTANTES MUERTOS. Gate E PASS.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
