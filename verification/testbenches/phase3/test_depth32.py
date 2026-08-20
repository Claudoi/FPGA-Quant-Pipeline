"""Testbench cocotb del top-N público (fase 3, criterio 6) — área phase3.

Espejos DP-01/SEC-DP-01: depth_tdata (2*ND*64 = 640 bits) bit a bit contra los
niveles ordenados del golden book.py para el símbolo de cada evento BBO,
best-first (bid descendente, ask ascendente), vacíos a 0. DP-02: replay del
feed real del día local (20 símbolos) con depth en TODOS los eventos.

Empaquetado del bus (spec): {bid[ND-1..0], ask[ND-1..0]} con el mejor nivel a
la izquierda (MSB): depth[639:576] = mejor bid {px[31:0], qty[31:0]}.
"""
import cocotb
import os
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, S, run_book_depth, pack_depth,
                            _pcap_msgs_subset, _reset, REAL_PCAP,
                            _fields_from_body)
from test_orderbook32 import anexo_words32


async def drive_and_collect_depth32(dut, messages, max_cycles=200000):
    """Conduce Anexo A de 32 bits y recolecta (bbo_events, depth_words,
    cross_count, anomaly_count). depth_tdata se muestrea en el mismo ciclo
    del handshake del BBO (el par BBO/depth es atómico)."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    depth = []
    quiet = 0
    cross = 0
    anomaly = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            # el par BBO/depth es atómico: el depth acompaña al BBO siempre
            if int(dut.depth_tvalid.value) != 1:
                raise AssertionError(
                    "DP: depth_tvalid debe acompañar al handshake del BBO")
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF), ch))
            depth.append(int(dut.depth_tdata.value))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > 200:
            break
    return out, depth, cross, anomaly


@cocotb.test()
async def test_dp01_topn_igual_golden(dut):
    """Espejo §DP-01: depth bit a bit contra el golden en cada evento, con un
    símbolo de >= ND niveles por lado y otro de pocos (vacíos a 0), y un
    reduce que debe reflejarse en la qty del nivel."""
    AMZN = 393
    AAPL = 13
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(6):   # 6 niveles bid y 6 ask de AMZN
        msgs.append(A(AMZN, 10 + i, 100 + i, b"B", 100 + i, b"AMZN    ", 1_000_00 + i * 10))
    for i in range(6):
        msgs.append(A(AMZN, 20 + i, 200 + i, b"S", 50 + i, b"AMZN    ", 2_000_00 + i * 10))
    msgs.append(A(AAPL, 30, 1000, b"B", 300, b"AAPL    ", 5_000_00))   # AAPL: 2 bid, 1 ask
    msgs.append(A(AAPL, 31, 1001, b"B", 200, b"AAPL    ", 5_100_00))
    msgs.append(A(AAPL, 32, 1002, b"S", 150, b"AAPL    ", 5_300_00))
    msgs.append(E(AMZN, 40, 105, 10, 1))   # reduce la qty del mejor bid de AMZN
    expected, exp_depth, golden = run_book_depth(msgs)
    got, got_depth, cross, anomaly = await drive_and_collect_depth32(dut, msgs)
    assert got == expected, f"DP-01: BBO got={got} exp={expected}"
    for i, (g, e) in enumerate(zip(got_depth, exp_depth)):
        exp_word = pack_depth(*e[1:])
        assert g == exp_word, (
            f"DP-01: depth del evento {i} (locate {e[0]}) diverge:\n"
            f" got={g:0160x}\n exp={exp_word:0160x}")
    assert anomaly == golden.anomalies, (
        f"DP-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"DP-01 cross: got={cross} exp={golden.cross_events}")


@cocotb.test()
async def test_sec_dp01_simbolo_vacio_ceros(dut):
    """Espejo §SEC-DP-01: niveles inexistentes -> 0: lado ask vacío y slots
    sobrantes del bid a cero en el word de 640 bits."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 1, b"B", 100, b"AMZN    ", 1_000_00),   # solo 1 nivel bid
    ]
    _, exp_depth, _ = run_book_depth(msgs)
    _, got_depth, _, _ = await drive_and_collect_depth32(dut, msgs)
    w = got_depth[0]
    # mejor bid en [639:576] = (100000, 100); los 4 slots restantes del bid y
    # los 5 del ask (bits [319:0]) a cero
    assert (w >> 320) == (((1_000_00 << 32) | 100) << 256), hex(w)
    assert (w & ((1 << 320) - 1)) == 0, hex(w)
    assert got_depth == [pack_depth(*e[1:]) for e in exp_depth], (
        f"SEC-DP-01: got={got_depth} exp={[pack_depth(*e[1:]) for e in exp_depth]}")


# ---------------------------------------------------------------------------
# DP-02: feed real (subset 20 símbolos) -> depth en todos los eventos
# ---------------------------------------------------------------------------
@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_dp02_replay_feed_real_depth(dut):
    """INV/DP-02: depth de TODOS los eventos del feed real (20 símbolos) bit a
    bit contra el golden (pcap local no commiteado; se omite si no existe)."""
    assert os.path.exists(REAL_PCAP), "DP-02 OMITIDO: pcap local ausente"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    nd = len(dut.depth_tdata) // 128
    cocotb.log.info(
        f"DP-02: {len(msgs)} mensajes de {len(keep)} símbolos, "
        f"depth bit a bit en cada evento")
    expected, exp_depth, golden = run_book_depth(msgs)
    got, got_depth, cross, anomaly = await drive_and_collect_depth32(
        dut, msgs, max_cycles=2_000_000)
    assert len(got) == len(expected), (
        f"DP-02: got({len(got)}) exp({len(expected)}) eventos")
    # El depth sigue el contrato enmendado del push-out (spec fase3-optimizacion,
    # addendum iter 15, OVR-PUSH-01): bit a bit hasta la primera re-entrada de
    # un nivel descartado por la cola P=32 (loc13 supera 32 niveles en el pico
    # del día; ausencia/cantidad parcial en los niveles descartados). Desde el
    # evento 14461 se exige solo propiedad de SUBconjunto a nivel de precio:
    # todo precio del depth RTL está en el golden (jamás un fantasma).
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
    DEPTH_FIRST_REENTRY = 14461
    assert len(_gold_levs) == len(got_depth) == len(exp_depth), (
        f"DP-02: alineación del oracle {len(_gold_levs)}")
    for i, (g, e) in enumerate(zip(got_depth, exp_depth)):
        exp_word = pack_depth(*e[1:])
        if g != exp_word:
            if i < DEPTH_FIRST_REENTRY:
                raise AssertionError(
                    f"DP-02: depth diverge ANTES de la re-entrada en evento "
                    f"{i} (locate {e[0]}):\n got={g:0160x}\n exp={exp_word:0160x}")
            _loc, _gb_bid, _gb_ask = _gold_levs[i]
            for _k in range(2 * nd):
                _px = (g >> (64 * (2 * nd - 1 - _k) + 32)) & 0xFFFFFFFF
                _qy = (g >> (64 * (2 * nd - 1 - _k))) & 0xFFFFFFFF
                if _qy == 0:
                    continue
                _side = book_golden.BID if _k < nd else book_golden.ASK
                _lev = _gb_bid if _side == book_golden.BID else _gb_ask
                if _px not in _lev:
                    raise AssertionError(
                        f"DP-02: depth con fantasma en la re-entrada (evento "
                        f"{i}): precio {_px} ({_side}) fuera del golden")
    assert cross == golden.cross_events, (
        f"DP-02 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"DP-02 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"DP-02 OK: {len(got_depth)} depth (bit a bit hasta la 1ª re-entrada "
        f"{DEPTH_FIRST_REENTRY}; subconjunto después), "
        f"cross={cross}, anomaly={anomaly}")
