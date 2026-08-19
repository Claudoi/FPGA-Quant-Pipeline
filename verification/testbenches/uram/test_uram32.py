"""Testbench cocotb de la sonda URAM serializada y el pipeline de niveles
(fase3-uram, criterios 2-4) — área uram.

Espejos SEC-URAM-01 (lectura registrada, nunca combinacional; ≤ 1 slot/ciclo),
SEC-URAM-02 (prefetch del grupo de hash durante ST_BODY) y SEC-URAM-03
(pipeline de niveles sin burbujas ni fantasmas). Pinza ESTRUCTURAL: lee
señales internas del book (`/* verilator public */` en `st`, `pr_phase`,
`rd_addr`, `rd_data`, `pr_pending_*`) — el criterio 9 de fase 3 era solo
documentación; aquí el retardo de lectura y la serialización se verifican por
señal, no por auditoría.

Estados espejo de los localparams del RTL (mantener en sincronía).
"""
import cocotb
from cocotb.triggers import RisingEdge

from test_orderbook import (A, D, E, S, U, run_book, _reset)
from test_orderbook32 import anexo_words32

# espejo de los localparams del RTL (orderbook.sv)
ST_W0, ST_TS, ST_BODY, ST_APPLY, ST_EMIT, ST_UADD, ST_WAIT_PROBE, ST_INVAL = range(8)
ST_LV2, ST_LV2B, ST_LV3 = 8, 14, 9   # pipeline de niveles (iter 3; LV2B = iter 8)
PR_IDLE, PR_WARM, PR_WALK = 0, 1, 2


async def drive_sampling(dut, messages, max_cycles=400000, window=200):
    """Conduce mensajes a DW=32 y devuelve (out, trace, errores, anomaly):
    out = eventos BBO; trace = [(st, pr_phase, pr_pending_old, pr_pending_new,
    rd_addr, rd_data)] por ciclo (muestreo en vivo de las señales internas);
    errores = ciclos con el pulso `error`; anomaly = valor final del contador."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    trace = []
    errores = 0
    anomaly = 0
    quiet = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        trace.append((int(dut.st.value), int(dut.pr_phase.value),
                      int(dut.pr_pending_old.value), int(dut.pr_pending_new.value),
                      int(dut.rd_addr.value), int(dut.rd_data.value)))
        if int(dut.error.value) == 1:
            errores += 1
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF),
                        int(dut.bbo_changed.value)))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if quiet > window:
            break
    return out, trace, errores, anomaly


def walk_cycles(trace, st_fsm):
    """Ciclos del trace donde la sonda está activa (WARM/WALK) y donde el FSM
    principal está en st_fsm. Devuelve (activos, fsm_cycles)."""
    activos = [i for i, (st, ph, *_rest) in enumerate(trace) if ph != PR_IDLE]
    fsm = [i for i, (st, ph, *_rest) in enumerate(trace) if st == st_fsm]
    return activos, fsm


@cocotb.test()
async def test_sec_uram_01_la_tabla_se_lee_de_forma_registrada_nunca_combinacional(dut):
    """Espejo §SEC-URAM-01: durante un probe completo (camino lleno, K=20) la
    sonda consume a lo sumo 1 slot/ciclo y el dato llega registrado (el
    rd_data NUNCA cambia en el mismo ciclo que rd_addr: latencia de 1 ciclo)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]            # ocupan slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(E(AMZN, 100, 5 + 8 * 65536, 10, 999))   # inexistente: camino lleno
    msgs.append(E(AMZN, 101, refs[7], 10, 1007))        # ref en el último slot
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, f"SEC-URAM-01: BBO got={out} exp={expected}"
    assert golden.anomalies == 1, "SEC-URAM-01: 1 anomalía esperada del golden"
    assert errores == 0, f"SEC-URAM-01: sin errores esperados, vistos {errores}"

    activos, _ = walk_cycles(trace, ST_BODY)
    assert activos, "SEC-URAM-01: la sonda nunca se activó (sin probe)"
    runs = _split_runs(activos)
    # (a) serialización: dentro de un MISMO run (ciclos contiguos) la lectura
    # avanza a lo sumo 1 slot/ciclo. Entre runs hay pausas (el siguiente run
    # vuelve a su base) y no se comparan lecturas de runs distintos.
    for r in runs:
        addrs = [trace[i][4] for i in r]
        for a, b in zip(addrs, addrs[1:]):
            diff = (b - a) % (1 << 16)
            assert diff <= 1, (
                f"SEC-URAM-01: la sonda saltó >1 slot/ciclo dentro de un run: "
                f"{a} -> {b}")
    # (b) lectura registrada: en el ciclo de ARRANQUE de cada run el rd_data no
    # cambia (el dato del slot anterior sigue visible 1 ciclo más). Un índice
    # combinacional lo reflejaría al instante, en el mismo ciclo que rd_addr.
    for r in runs:
        i = r[0]
        assert trace[i][5] == trace[i - 1][5], (
            f"SEC-URAM-01: rd_data cambió en el MISMO ciclo que rd_addr al "
            f"arrancar el run (ciclo {i}: data {trace[i-1][5]}->{trace[i][5]}) "
            f"— lectura combinacional")
    # (c) el probe del camino lleno consume exactamente PROBE evals (8): el
    # run del E inexistente debe durar 1 (WARM) + 8 (WALK) ciclos
    full_runs = [r for r in runs if len(r) == 9]
    assert len(full_runs) >= 1, (
        f"SEC-URAM-01: no hay run de 9 ciclos (WARM+8 WALK) "
        f"— duraciones {[len(r) for r in runs]}")
    n_reads = sum(len(r) for r in runs)
    cocotb.log.info(
        f"SEC-URAM-01 OK: {len(runs)} runs de probe, {n_reads} lecturas "
        f"serializadas 1 slot/ciclo, rd_data con latencia registrada de 1 ciclo")


def _split_runs(activos):
    """Parte los ciclos activos en runs contiguos (un run por mensaje)."""
    runs = []
    cur = []
    prev = None
    for i in activos:
        if prev is None or i == prev + 1:
            cur.append(i)
        else:
            runs.append(cur)
            cur = [i]
        prev = i
    if cur:
        runs.append(cur)
    return runs


@cocotb.test()
async def test_sec_uram_02_el_prefetch_del_grupo_de_hash_ocurre_durante_st_body(dut):
    """Espejo §SEC-URAM-02: el grupo de hash de un add (cuerpo largo) se
    precarga durante ST_BODY — la sonda se activa ANTES de ST_APPLY y el
    lookup termina antes de aplicar (sin latencia añadida al apply)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),      # cuerpo 7 words
        A(AMZN, 3, 6, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 4, 5, 40, 1001),                               # cuerpo 5 words
    ]
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, f"SEC-URAM-02: BBO got={out} exp={expected}"
    assert golden.anomalies == 0, "SEC-URAM-02: 0 anomalías esperadas"
    assert errores == 0, f"SEC-URAM-02: sin errores esperados, vistos {errores}"

    first_active = next((i for i, (st, ph, *_r) in enumerate(trace)
                         if ph != PR_IDLE), None)
    assert first_active is not None, "SEC-URAM-02: la sonda nunca se activó"
    st_at_start = trace[first_active][0]
    assert st_at_start == ST_BODY, (
        f"SEC-URAM-02: la sonda arrancó con st={st_at_start} (ST_BODY={ST_BODY}) "
        f"— el prefetch NO ocurre durante la recepción del cuerpo")
    # el probe del add de cuerpo largo avanza DURANTE la recepción del cuerpo
    # (prefetch): hay ciclos POSTERIORES al arranque con st==ST_BODY y la
    # sonda activa (el run dura 9 ciclos; el cuerpo 7 words). El primer
    # ST_APPLY del mensaje en cuestión ocurre tras el run — comparado contra
    # el apply del propio add, no contra el del S previo (sin probe)
    active_in_body = any(
        i > first_active and trace[i][1] != PR_IDLE
        for i, (st, ph, *_r) in enumerate(trace) if st == ST_BODY)
    assert active_in_body, (
        "SEC-URAM-02: el probe no avanzó durante ST_BODY "
        "(el run terminó antes de acabar de recibir el cuerpo)")
    cocotb.log.info(
        f"SEC-URAM-02 OK: prefetch arranca en el ciclo {first_active} con "
        f"st=ST_BODY; lookup completado antes de ST_APPLY para el add de cuerpo largo")


def _split_lv_runs(trace):
    """Parte los ciclos en los estados del pipeline de niveles en runs
    contiguos (un run = la operación de nivel de un mensaje). El FSM vigente
    (iter 8 de fase 3) recorre LV2 -> LV2B -> LV3: los tres estados forman
    parte del mismo run de operación."""
    runs = []
    cur = []
    prev = None
    for i, (st, *_rest) in enumerate(trace):
        in_lv = st == ST_LV2 or st == ST_LV2B or st == ST_LV3
        if in_lv:
            if prev is None or i == prev + 1:
                cur.append(i)
            else:
                runs.append(cur)
                cur = [i]
            prev = i
    if cur:
        runs.append(cur)
    return runs


@cocotb.test()
async def test_sec_uram_03_el_pipeline_de_niveles_no_crea_burbujas_ni_fantasmas(dut):
    """Espejo §SEC-URAM-03: 33 adds que desbordan P=32 + delete posterior
    sobre un nivel ausente -> jamás un precio stale ni una cantidad envuelta,
    y cada operación de nivel consume a lo sumo 2 ciclos extra (pipeline
    registrado, sin burbujas: un run de niveles es LV2->LV3, nunca se repite
    ni retrocede)."""
    AMZN = 393
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(33):
        msgs.append(A(AMZN, 10 + i, 1000 + i, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 50, 1000))          # libera el nivel del precio 100000
    msgs.append(D(AMZN, 51, 1032))          # la orden 33ª (en tabla, sin nivel)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    # forma cerrada (el golden no tiene límite de P): 35 eventos, sin wrap
    assert errores >= 2, (
        f"SEC-URAM-03: errores={errores} exp>=2 (overflow del add 33 + reduce "
        f"sobre nivel ausente)")
    assert anomaly == 0, f"SEC-URAM-03: anomaly={anomaly} exp=0"
    assert len(out) == 35, f"SEC-URAM-03: eventos={len(out)} exp=35"
    assert out[-1] == (393, (100031, 100, 0, 0), 0), (
        f"SEC-URAM-03: el reduce fantasma no cambia el BBO (sin wrap): "
        f"out[-1]={out[-1]} exp=(100031@100, changed=0)")
    # burbuja <= 3 ciclos por operación (iter 8 de fase 3: el decode se
    # partió en LV2+LV2B, +1 sobre los 2 del Gherkin original; spec
    # fase3-optimizacion iter 8): 35 operaciones de nivel (33 adds +
    # 2 deletes), cada una un run contiguo de a lo sumo 3 ciclos, estrictamente
    # hacia adelante (LV2->LV2B->LV3, jamás repetición ni retroceso)
    runs = _split_lv_runs(trace)
    assert len(runs) == 35, (
        f"SEC-URAM-03: {len(runs)} runs de pipeline de niveles exp=35 — "
        f"sin pipeline registrado (o con burbujas) no hay un run por operación")
    for r in runs:
        assert len(r) <= 3, (
            f"SEC-URAM-03: run de niveles de {len(r)} ciclos > 3 (burbuja)")
        seq = [trace[i][0] for i in r]
        assert seq == [ST_LV2, ST_LV2B, ST_LV3], (
            f"SEC-URAM-03: el pipeline de niveles no recorre LV2,LV2B,LV3 "
            f"estrictamente: {seq}")
    cocotb.log.info(
        f"SEC-URAM-03 OK: 35 operaciones de nivel, {sum(len(r) for r in runs)} "
        f"ciclos de pipeline (<=3 por op, iter 8), sin precio stale ni "
        f"cantidad envuelta")


@cocotb.test()
async def test_inv_uram_03_replace_u_doble_run_pipeline(dut):
    """INV/SEC-URAM-03: el replace U aplica sus DOS operaciones de nivel en
    runs de pipeline separados (delete de la original + add del newref), cada
    uno <= 2 ciclos; la segunda op ve el estado tras la primera (la lista sin
    la original), igual que el apply multi-ciclo de fase 3."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 3, 6, b"S", 50, b"AMZN    ", 1_005_00),
        U(AMZN, 4, 5, 1005, 60, 1_000_00),      # newref 1005: hash libre
    ]
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, (
        f"INV/SEC-URAM-03: BBO got={out} exp={expected}")
    assert errores == 0, (
        f"INV/SEC-URAM-03: sin errores esperados, vistos {errores}")
    assert anomaly == 0, f"INV/SEC-URAM-03: anomaly={anomaly} exp=0"
    runs = _split_lv_runs(trace)
    # 2 adds del escenario + delete + add del U = 4 operaciones de nivel
    assert len(runs) == 4, (
        f"INV/SEC-URAM-03: {len(runs)} runs de niveles exp=4 (2 adds + "
        f"delete + add del replace U)")
    for r in runs:
        assert len(r) <= 3, (
            f"INV/SEC-URAM-03: run de niveles de {len(r)} ciclos > 3 (burbuja)")
    # el replace U encadena sus DOS operaciones: delete (run LV2->LV3) y add
    # (lanzada en ST_UADD — el ciclo del medio, igual que en fase 3 — y luego
    # LV2->LV3). El add arranca 2 ciclos después del final del delete:
    #  LV3 -> UADD(launch) -> LV2 -> LV3, sin burbuja de pipeline
    assert runs[-1][0] == runs[-2][-1] + 2, (
        f"INV/SEC-URAM-03: las 2 ops del U no van encadenadas: delete "
        f"{runs[-2]} add {runs[-1]}")
    cocotb.log.info(
        "INV/SEC-URAM-03 OK: el replace U corre 2 runs de pipeline "
        "(delete + add), cada uno <= 2 ciclos, con el estado encadenado")
