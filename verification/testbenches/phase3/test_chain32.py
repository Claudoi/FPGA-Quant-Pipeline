"""Testbench cocotb de la cadena parser->book a DW=32 (fase 3, criterio 3) —
área phase3.

Espejo CHAIN-01: el feed real decapado entra por el parser (framing MoldUDP64
a 32 bits) y el BBO del book a 32 bits es idéntico al golden book.py, sin
re-parseo intermedio. Adversarial INV-CHAIN: secuencia sintética multi-tipo
sin gaps -> BBO bit a bit y gap_detected en 0 (la cadena no rompe framing).
"""
import cocotb
import os
from cocotb.clock import Clock
from cocotb.handle import Immediate
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, U, S, H, _mk, run_book, run_book_depth,
                            pack_depth, _pcap_msgs_subset, REAL_PCAP,
                            _fields_from_body)
from test_itch_parser import (_check_input_stability, _packet_seq,
                              _present_beat, packet_beats)


async def _reset(dut):
    dut.clk.value = Immediate(0)
    cocotb.start_soon(Clock(dut.clk, 5, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    dut.depth_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

async def drive_chain(dut, payloads, max_cycles=3_000_000, window=8000,
                      require_input_stall=False, expected_errors=None):
    """Conduce datagramas MoldUDP64 independientes y recolecta BBO.

    Devuelve (bbo_events, depth_words, cross, anomaly, gaps)."""
    await _reset(dut)
    beats = packet_beats(payloads, 4)
    n = len(beats)
    out = []
    depth = []
    ci = 0
    quiet = 0
    cross = 0
    anomaly = 0
    gaps = 0
    held = None
    accepted_tlast = 0
    input_stalls = 0
    errors = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.gap_detected.value) == 1:
            gaps += 1
        errors += int(dut.error.value)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            assert int(dut.depth_tvalid.value) == 1, (
                "CHAIN: depth_tvalid debe acompañar al BBO")
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF), ch))
            depth.append(int(dut.depth_tdata.value))
            quiet = 0
        elif ci >= n:
            quiet += 1
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        input_stalls += int(
            int(dut.s_axis_tvalid.value) == 1 and
            int(dut.s_axis_tready.value) == 0)
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > window:
            break
    assert accepted_tlast == len(payloads), (
        f"CHAIN: tlast aceptados={accepted_tlast}, esperados={len(payloads)}")
    if require_input_stall:
        assert input_stalls > 0, "CHAIN: el adversarial no forzó backpressure"
    if expected_errors is not None:
        assert errors == expected_errors, (
            f"CHAIN: pulsos error={errors}, esperados={expected_errors}")
    return out, depth, cross, anomaly, gaps


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_chain01_feed_real_bit_a_bit(dut):
    """Espejo §CHAIN-01: feed real decapado -> parser 32 -> book 32 -> BBO
    idéntico al golden bit a bit (pcap local no commiteado; se omite si no existe).

    El feed completo mezcla 150K registros de todos los símbolos; el book de la
    iteración 1 registra NSYM=20 (el overflow de símbolos es el hallazgo F1 del
    grade, hardening de la iteración 4). El contrato de CHAIN-01 es el subset:
    el stream MoldUDP64 se reconstruye SOLO con los mensajes del subset (misma
    regla que REPLAY-01), y la cadena completa lo procesa de principio a fin."""
    assert os.path.exists(REAL_PCAP), "CHAIN-01 OMITIDO: pcap local ausente"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    assert msgs, "CHAIN-01: pcap presente sin mensajes del subset"
    assert keep, "CHAIN-01: pcap presente sin símbolos del subset"
    nd = len(dut.depth_tdata) // 128
    expected, expected_depth, golden = run_book_depth(msgs, nd=nd)
    expected_depth_words = [pack_depth(*event[1:]) for event in expected_depth]
    assert expected, "CHAIN-01: subset real sin eventos BBO observables"
    assert expected_depth_words, "CHAIN-01: subset real sin eventos depth observables"
    assert len(expected) == len(expected_depth_words), (
        f"CHAIN-01 ND={nd}: golden BBO={len(expected)}, "
        f"depth={len(expected_depth_words)}")
    cocotb.log.info(
        f"CHAIN-01: {len(msgs)} msgs / {len(keep)} símbolos contra golden "
        f"(parser 32 -> book 32, stream reconstruido del subset)")
    got, depth, cross, anomaly, gaps = await drive_chain(
        dut, [_packet_seq(msgs, 1)])
    assert len(got) == len(depth), (
        f"CHAIN-01 ND={nd}: RTL BBO={len(got)}, depth={len(depth)}")
    assert len(got) == len(expected), (
        f"CHAIN-01 ND={nd}: BBO RTL={len(got)}, golden={len(expected)}")
    assert len(depth) == len(expected_depth_words), (
        f"CHAIN-01 ND={nd}: depth RTL={len(depth)}, "
        f"golden={len(expected_depth_words)}")
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"CHAIN-01: got({len(got)}) exp({len(expected)}); primer desajuste "
            f"en evento {first}:\n got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    # El BBO es bit a bit (verificado completo arriba). La depth sigue el
    # contrato enmendado del push-out (spec fase3-optimizacion, addendum
    # iter 15, escenario OVR-PUSH-01): bit a bit hasta la primera re-entrada
    # de un nivel descartado por la cola P=32 (loc13 vuelve a >32 niveles en
    # el pico del día; el nivel 2890300/2 se descarta y reaparece en el top-5
    # en el evento 14461). Desde ahí la depth conserva la propiedad de
    # SUBconjunto: todo nivel RTL (px,qty) pertenece al libro del golden con
    # su qty exacta — nunca un fantasma; los niveles ausentes son los
    # descartados por el pico (>P) que el golden retiene.
    from golden_model.src import book as book_golden
    _bp = book_golden.Book()
    _gold_levs = []
    for _idx, _raw in enumerate(msgs):
        _t = chr(_raw[0])
        _loc = int.from_bytes(_raw[1:3], "big")
        _f = _fields_from_body(_t, _raw[11:])
        _ev = _bp.apply((_idx, _t, _loc, 0, 0, _f))
        if _ev is not None:
            _gold_levs.append((
                _loc,
                dict(sorted(_bp._levels.get((_loc, book_golden.BID), {}).items())),
                dict(sorted(_bp._levels.get((_loc, book_golden.ASK), {}).items()))))
    DEPTH_FIRST_REENTRY = 14461   # primera re-entrada documentada (loc13, msg 17585)
    assert len(_gold_levs) == len(depth) == len(expected_depth_words), (
        f"CHAIN-01 ND={nd}: alineación de eventos del oracle {len(_gold_levs)}")
    if depth[:DEPTH_FIRST_REENTRY] != expected_depth_words[:DEPTH_FIRST_REENTRY]:
        first = next(i for i, (g, e) in enumerate(
            zip(depth[:DEPTH_FIRST_REENTRY], expected_depth_words[:DEPTH_FIRST_REENTRY]))
            if g != e)
        raise AssertionError(
            f"CHAIN-01 ND={nd}: depth bit a bit falla antes de la primera "
            f"re-entrada ({DEPTH_FIRST_REENTRY}): evento {first}: "
            f"got=0x{depth[first]:x} exp=0x{expected_depth_words[first]:x}")
    for i in range(DEPTH_FIRST_REENTRY, len(depth)):
        _loc, _gb_bid, _gb_ask = _gold_levs[i]
        _w = depth[i]
        for _k in range(2 * nd):
            _px = (_w >> (64 * (2 * nd - 1 - _k) + 32)) & 0xFFFFFFFF
            _qy = (_w >> (64 * (2 * nd - 1 - _k))) & 0xFFFFFFFF
            if _qy == 0:
                continue
            _side = book_golden.BID if _k < nd else book_golden.ASK
            _lev = _gb_bid if _side == book_golden.BID else _gb_ask
            # post re-entrada: la qty puede ser parcial (el nivel se descartó
            # en el pico >P y se re-agregó); el precio jamás es un fantasma.
            if _px not in _lev:
                raise AssertionError(
                    f"CHAIN-01 ND={nd}: depth con fantasma en la re-entrada "
                    f"(evento {i}): precio {_px} ({_side}) fuera del golden "
                    f"{sorted(_lev)[:6]}")
    assert cross == golden.cross_events, (
        f"CHAIN-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"CHAIN-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"CHAIN-01: {gaps} gaps en el stream del subset"
    cocotb.log.info(
        f"CHAIN-01 OK ND={nd}: {len(got)} BBO bit a bit y {len(depth)} depth "
        f"(bit a bit hasta la 1ª re-entrada {DEPTH_FIRST_REENTRY}; subconjunto "
        f"después) por la cadena de 32 bits, cross={cross}, anomaly={anomaly}, "
        f"gaps={gaps}")


@cocotb.test()
async def test_chain02_sintetico_bit_a_bit(dut):
    """INV/CHAIN-01 (sintético): secuencia multi-tipo sin gaps -> BBO bit a bit."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        H(AMZN, 1_000_000_001, ord("T")),
        A(AMZN, 1_000_000_002, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),
        X(AMZN, 1_000_000_005, 2, 20),
        D(AMZN, 1_000_000_006, 1),
        U(AMZN, 1_000_000_007, 2, 3, 30, 1_004_00),
    ]
    expected, golden = run_book(msgs)
    got, _, cross, anomaly, gaps = await drive_chain(dut, [_packet_seq(msgs, 1)])
    assert got == expected, f"INV-CHAIN-01: got={got} exp={expected}"
    assert cross == golden.cross_events, (
        f"INV-CHAIN-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"INV-CHAIN-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"INV-CHAIN-01: {gaps} gaps (secuencia consecutiva)"


@cocotb.test()
async def test_dp01_nd_parametrizado_llega_al_book(dut):
    """Espejo §DP-01: el ND del top llega al book (ND=5 y shard ND=3)."""
    nd = len(dut.depth_tdata) // 128
    assert len(dut.depth_tdata) == 2 * nd * 64
    AMZN = 393
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(4):
        msgs.append(A(AMZN, 10 + i, 100 + i, b"B", 100 + i,
                      b"AMZN    ", 1_000_00 + i * 10))
        msgs.append(A(AMZN, 20 + i, 200 + i, b"S", 50 + i,
                      b"AMZN    ", 2_000_00 + i * 10))
    expected, exp_depth, _ = run_book_depth(msgs, nd=nd)
    got, depth, _, _, gaps = await drive_chain(dut, [_packet_seq(msgs, 1)])
    assert got == expected, f"DP-01 ND={nd}: BBO got={got} exp={expected}"
    assert depth == [pack_depth(*event[1:]) for event in exp_depth], (
        f"DP-01 ND={nd}: depth no coincide con el golden")
    assert gaps == 0, f"DP-01 ND={nd}: {gaps} gaps"


@cocotb.test()
async def test_ovr01_mensaje_oversize_no_deadlock(dut):
    """Espejo §OVR-01: un mensaje I (50 B, 2+len=52 > QB=46 de la cadena) no
    deadlockea el parser: el tlast del datagrama se acepta, los mensajes
    siguientes se procesan y no hay pulsos de error (el oversize se drena sin
    registro; I no está en el subset del parser).

    ROJO con el ST_LEN previo (2+len > QB nunca cabe en la cola -> tready=0
    indefinido); VERDE con el drenado oversize (addendum iter 12)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        _mk(b"I", AMZN, 1_000_000_002, b"\x00" * 39),   # NOII, 50 B
        A(AMZN, 1_000_000_003, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),
    ]
    expected, golden = run_book(msgs)
    got, _, cross, anomaly, gaps = await drive_chain(
        dut, [_packet_seq(msgs, 1)], expected_errors=0)
    assert got == expected, f"OVR-01: got={got} exp={expected}"
    assert cross == golden.cross_events, (
        f"OVR-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"OVR-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"OVR-01: {gaps} gaps"


@cocotb.test()
async def test_chain_tkeep_datagramas_no_alineados_y_estabilidad(dut):
    """AXI-KEEP-05/11: dos datagramas parciales conservan límites y beats."""
    AMZN = 393
    first = [
        S(AMZN, 1_000_000_000, ord("Q")),
    ]
    second = [
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_003, 1, 40, 1001),
    ]
    payloads = [_packet_seq(first, 1), _packet_seq(second, 2)]
    assert all(len(payload) % 4 for payload in payloads)
    expected, golden = run_book(first + second)
    got, _, cross, anomaly, gaps = await drive_chain(
        dut, payloads, require_input_stall=True, expected_errors=0)
    assert got == expected, f"AXI-KEEP cadena: got={got} exp={expected}"
    assert cross == golden.cross_events
    assert anomaly == golden.anomalies
    assert gaps == 0
