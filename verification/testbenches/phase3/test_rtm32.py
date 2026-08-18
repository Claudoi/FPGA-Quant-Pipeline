"""Testbench cocotb del retiming del escaneo de niveles (fase 3, iter 7) —
área phase3.

Espejos RTM-01..RTM-04 y RTM-REG-01 (addendum iter 7 de la spec): el ST_EMIT
de un solo ciclo combinacional se parte en ST_EMIT_A (captura registrada de
los 2*P niveles del símbolo del evento), ST_EMIT_B (selección del mejor nivel,
changed y depth sobre la captura) y ST_EMIT_C (handshake de salida). La sonda
estructural muestrea `st` y la captura `sm_cap_*` — ambas public en el RTL,
como SEC-URAM-01: la emisión ocurre solo en ST_EMIT_C y la captura espeja el
depth emitido.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, S, run_book, drive_and_collect_bbo)
from test_orderbook32 import anexo_words32

# etapas del pipeline de emisión (orderbook.sv, addendum iter 7); el FSM de
# recepción usa st[3:0] con ST_EMIT=4, ST_UADD=5, ST_WAIT_PROBE=6, ST_INVAL=7,
# ST_LV2=8, ST_LV3=9, ST_SWAP=10 -> 11/12/13 son las etapas A/B/C
ST_EMIT_A = 11
ST_EMIT_B = 12
ST_EMIT_C = 13
# P = niveles de precio por lado (default del RTL, contrato de campaña; el
# Makefile de phase3 nunca lo sobrescribe)
P = 32


def depth_slot(depth, j, ask=False):
    """Nivel j (0 = mejor) del bus depth_tdata: {bid[ND-1..0], ask[ND-1..0]}
    MSB->LSB, cada nivel {px[31:0], qty[31:0]} — packing idéntico a
    pack_depth del golden (test_orderbook)."""
    base = (288 if ask else 608) - 64 * j
    px = (depth >> base) & 0xFFFFFFFF
    qy = (depth >> (base - 32)) & 0xFFFFFFFF
    return px, qy


async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    dut.depth_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def drive_and_trace_rtm(dut, messages, stall=None, max_cycles=300000):
    """Conduce Anexo A de 32 bits y muestrea por ciclo el estado `st` y la
    captura `sm_cap_*` (sonda estructural del pipeline de emisión).

    `stall` es una función ciclo->bool (True = tready en 0, backpressure).
    Devuelve (events, st_seq, caps, cross, anomaly, errors):
      events = [(ciclo, locate, (bid_px, bid_qty, ask_px, ask_qty), changed,
                 depth_tdata)]
      st_seq = [st] por ciclo
      caps   = [(cap_bid, cap_ask)] por evento, con los ND primeros niveles
               de la captura por lado: cap_bid[j] = (px, qty) del slot j."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    caps = []
    st_seq = []
    quiet = 0
    cross = 0
    anomaly = 0
    errors = 0
    nd = len(dut.depth_tdata) // 128
    for cycle in range(max_cycles):
        stall_now = bool(stall(cycle)) if stall else False
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 0 if stall_now else 1
        dut.depth_tready.value = 0 if stall_now else 1
        await RisingEdge(dut.clk)
        st_seq.append(int(dut.st.value))
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            depth = int(dut.depth_tdata.value)
            bid_px = (td >> 96) & 0xFFFFFFFF
            bid_qty = (td >> 64) & 0xFFFFFFFF
            ask_px = (td >> 32) & 0xFFFFFFFF
            ask_qty = td & 0xFFFFFFFF
            out.append((cycle, loc, (bid_px, bid_qty, ask_px, ask_qty), ch, depth))
            cap_bid = [(int(dut.sm_cap_px[j].value),
                        int(dut.sm_cap_qt[j].value)) for j in range(nd)]
            cap_ask = [(int(dut.sm_cap_px[P + j].value),
                        int(dut.sm_cap_qt[P + j].value)) for j in range(nd)]
            caps.append((cap_bid, cap_ask))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if int(dut.error.value) == 1:
            errors += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > 200:
            break
    return out, st_seq, caps, cross, anomaly, errors


@cocotb.test()
async def test_rtm01_escaneo_registrado_en_etapas(dut):
    """Espejo §RTM-01: el escaneo del BBO/depth está registrado en etapas
    (ST_EMIT_A captura / ST_EMIT_B selecciona / ST_EMIT_C emite). Sonda
    estructural: la emisión ocurre solo en ST_EMIT_C, cada evento recorre
    las tres etapas en orden y la captura espeja el depth emitido."""
    if len(dut.s_axis_tdata) != 32:
        raise cocotb.SkipTest("RTM-01 se ejercita en la elaboración sim-rtm (DW=32)")
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_003, 1, 40, 1001),
        A(AMZN, 1_000_000_004, 3, b"B", 200, b"AMZN    ", 999_00),
    ]
    expected, golden = run_book(msgs)
    got, st_seq, caps, cross, anomaly, errors = await drive_and_trace_rtm(dut, msgs)
    nd = len(dut.depth_tdata) // 128
    # 1) cada handshake del BBO ocurre en el ciclo de ST_EMIT_C
    for cycle, _loc, _bbo, _ch, _depth in got:
        assert st_seq[cycle] == ST_EMIT_C, (
            f"RTM-01: handshake en st={st_seq[cycle]} (ciclo {cycle}); "
            f"esperado ST_EMIT_C={ST_EMIT_C}")
    # 2) cada evento recorre A->B->C en ciclos consecutivos
    triplets = sum(
        1 for i in range(2, len(st_seq))
        if st_seq[i - 2] == ST_EMIT_A and st_seq[i - 1] == ST_EMIT_B
        and st_seq[i] == ST_EMIT_C)
    assert triplets == len(got), (
        f"RTM-01: {triplets} recorridos A->B->C para {len(got)} eventos")
    # 3) la captura del evento espeja el depth emitido (slot j == depth j)
    for (_cycle, _loc, _bbo, _ch, depth), (cap_bid, cap_ask) in zip(got, caps):
        for j in range(nd):
            assert cap_bid[j] == depth_slot(depth, j, ask=False), (
                f"RTM-01: captura bid[{j}]={cap_bid[j]} != depth "
                f"{depth_slot(depth, j)}")
            assert cap_ask[j] == depth_slot(depth, j, ask=True), (
                f"RTM-01: captura ask[{j}]={cap_ask[j]} != depth ask "
                f"{depth_slot(depth, j, ask=True)}")
    # 4) equivalencia bit a bit vs golden
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-01: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies, (
        f"RTM-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-01: {errors} errores espurios"
    cocotb.log.info(
        f"RTM-01 OK: {len(got)} eventos con recorrido A->B->C, emisión solo "
        f"en ST_EMIT_C, captura espejo del depth, bit a bit vs golden")


@cocotb.test()
async def test_rtm02_bbo_consistente_con_la_captura(dut):
    """Espejo §RTM-02: el BBO del evento pipelined es el primer nivel no vacío
    de la captura (slot 0 por la invariante de lista ordenada), los ND
    primeros niveles de la captura coinciden con depth_tdata, y un símbolo
    sin niveles emite BBO a cero, changed a 0 y depth a cero."""
    if len(dut.s_axis_tdata) != 32:
        raise cocotb.SkipTest("RTM-02 se ejercita en la elaboración sim-rtm (DW=32)")
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"S", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 200, b"AMZN    ", 999_00),
        D(AMZN, 1_000_000_003, 1),           # deja el libro vacío
        A(AMZN, 1_000_000_004, 3, b"B", 50, b"AMZN    ", 1_000_00),
    ]
    expected, golden = run_book(msgs)
    got, st_seq, caps, cross, anomaly, errors = await drive_and_trace_rtm(dut, msgs)
    nd = len(dut.depth_tdata) // 128
    for (cycle, loc, bbo, ch, depth), (cap_bid, cap_ask) in zip(got, caps):
        # BBO = primer nivel no vacío (slot 0) por lado; vacío -> ceros
        bid_px, bid_qty, ask_px, ask_qty = bbo
        if bid_qty != 0:
            assert cap_bid[0] == (bid_px, bid_qty), (
                f"RTM-02: BBO bid {cap_bid[0]} != captura slot 0 "
                f"({bid_px}, {bid_qty}) en ciclo {cycle}")
        if ask_qty != 0:
            assert cap_ask[0] == (ask_px, ask_qty), (
                f"RTM-02: BBO ask != captura slot 0 en ciclo {cycle}")
        # depth = primeros ND niveles de la captura
        for j in range(nd):
            assert cap_bid[j] == depth_slot(depth, j, ask=False), (
                f"RTM-02: captura bid[{j}] != depth en ciclo {cycle}")
            assert cap_ask[j] == depth_slot(depth, j, ask=True), (
                f"RTM-02: captura ask[{j}] != depth en ciclo {cycle}")
    # el evento del libro vacío (delete de la última orden): BBO a cero,
    # changed a 1 (venía de un estado no vacío) y depth a cero
    empty = [e for e in got if e[2] == (0, 0, 0, 0)]
    assert len(empty) == 1, f"RTM-02: {len(empty)} eventos vacíos, esperado 1"
    assert empty[0][3] == 1, "RTM-02: changed del evento vacío != 1"
    assert empty[0][4] == 0, "RTM-02: depth del evento vacío != 0"
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-02: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies and cross == golden.cross_events, (
        f"RTM-02 contadores: anomaly {anomaly}/{golden.anomalies}, "
        f"cross {cross}/{golden.cross_events}")
    assert errors == 0, f"RTM-02: {errors} errores espurios"
    cocotb.log.info(
        f"RTM-02 OK: BBO consistente con la captura, evento vacío a cero "
        f"({len(got)} eventos, bit a bit vs golden)")


@cocotb.test()
async def test_rtm03_changed_sobre_la_captura(dut):
    """Espejo §RTM-03: bbo_changed se calcula sobre la captura (comparación
    contra el evento previo del símbolo): idéntico -> 0, distinto -> 1."""
    if len(dut.s_axis_tdata) != 32:
        raise cocotb.SkipTest("RTM-03 se ejercita en la elaboración sim-rtm (DW=32)")
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 1_000_000_003, 1, 40, 1001),
        A(AMZN, 1_000_000_004, 3, b"B", 100, b"AMZN    ", 1_000_00),
    ]
    expected, golden = run_book(msgs)
    got, _st, _caps, cross, anomaly, errors = await drive_and_trace_rtm(dut, msgs)
    changed = [ch for _c, _l, _b, ch, _d in got]
    assert changed == [1, 0, 1, 0], (
        f"RTM-03: changed={changed}, esperado [1, 0, 1, 0]")
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-03: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies and cross == golden.cross_events, (
        f"RTM-03 contadores: anomaly {anomaly}/{golden.anomalies}, "
        f"cross {cross}/{golden.cross_events}")
    assert errors == 0, f"RTM-03: {errors} errores espurios"
    cocotb.log.info(
        f"RTM-03 OK: changed={changed} sobre la captura (idéntico -> 0, "
        "distinto -> 1)")


@cocotb.test()
async def test_rtm04_handshake_retiene_evento_pipelined(dut):
    """Espejo §RTM-04: el handshake de salida retiene el evento pipelined bajo
    backpressure (tready=0 tras observar tvalid, dos ciclos estables) y se
    entrega exactamente una vez, sin pérdida ni duplicado, bit a bit contra
    el golden."""
    if len(dut.s_axis_tdata) != 32:
        raise cocotb.SkipTest("RTM-04 se ejercita en la elaboración sim-rtm (DW=32)")
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 50, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 3, b"S", 200, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),
        X(AMZN, 1_000_000_005, 3, 80),
        D(AMZN, 1_000_000_006, 1),
        A(AMZN, 1_000_000_007, 4, b"S", 90, b"AMZN    ", 1_003_00),
    ]
    expected, golden = run_book(msgs)

    hold = {"seen": False, "remaining": 2, "released": False, "payload": None}

    def stall(_cycle):
        if not hold["seen"]:
            if int(dut.bbo_tvalid.value) == 1:
                hold["seen"] = True
                hold["payload"] = (int(dut.bbo_tdata.value),
                                   int(dut.depth_tdata.value))
            return True
        if hold["released"]:
            return False
        assert int(dut.bbo_tvalid.value) == 1, (
            "RTM-04: bbo_tvalid cayó mientras tready seguía a cero")
        assert int(dut.depth_tvalid.value) == 1, (
            "RTM-04: depth_tvalid cayó mientras tready seguía a cero")
        assert (int(dut.bbo_tdata.value), int(dut.depth_tdata.value)) == hold["payload"], (
            "RTM-04: el payload cambió durante la retención")
        if hold["remaining"]:
            hold["remaining"] -= 1
            return True
        hold["released"] = True
        return False

    got, st_seq, _caps, cross, anomaly, errors = await drive_and_trace_rtm(
        dut, msgs, stall=stall)
    assert hold["seen"] and hold["released"], (
        "RTM-04: el test no observó y liberó un evento retenido")
    # el evento retenido se emitió en su ciclo de ST_EMIT_C (antes del stall)
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-04: got({len(bbo_got)}) exp({len(expected)}) "
        f"— evento perdido o duplicado bajo backpressure")
    assert anomaly == golden.anomalies, (
        f"RTM-04 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-04 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-04: {errors} errores espurios"
    cocotb.log.info(
        f"RTM-04 OK: {len(got)} eventos entregados exactamente una vez tras "
        "dos ciclos de retención estable (handshake pipelined)")


@cocotb.test()
async def test_rtm_reg01_regresion_64_bits_con_pipeline(dut):
    """Espejo §RTM-REG-01: el book pipelined a DW=64 (default) re-ejecuta el
    corpus de fase 2 bit a bit contra el golden (regresión de la
    parametrización; se ejercita en la elaboración sim-rtm64)."""
    if len(dut.s_axis_tdata) != 64:
        raise cocotb.SkipTest("RTM-REG-01 se ejercita en la elaboración sim-rtm64 (DW=64)")
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_003, 1, 40, 1001),
        X(AMZN, 1_000_000_004, 2, 80),
        D(AMZN, 1_000_000_005, 1),
        A(AMZN, 1_000_000_006, 3, b"B", 200, b"AMZN    ", 999_00),
    ]
    expected, golden = run_book(msgs)
    got, cross, anomaly, errors = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"RTM-REG-01: got={got} exp={expected}")
    assert anomaly == golden.anomalies, (
        f"RTM-REG-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-REG-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-REG-01: {errors} errores espurios"
    cocotb.log.info(
        f"RTM-REG-01 OK: DW=64, {len(got)} eventos bit a bit vs golden "
        f"(regresión de la parametrización con el pipeline de emisión)")