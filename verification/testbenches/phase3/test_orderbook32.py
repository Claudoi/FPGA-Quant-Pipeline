"""Testbench cocotb del order book a DW=32 (fase 3, criterio 2) — área phase3.

Espejos B32-01/B32-02: el book parametrizado a DW=32 (layout Anexo A 32
recortado: w0={type,locate,len}, w1=idx, w2..=cuerpo — sin ts) emite el BBO
bit a bit
contra el golden book.py, sobre corpus sintético y sobre el feed real del día
local. Adversariales INV-B32: replace atómico, RAW add->execute y multi-símbolo
a 32 bits (pincan errores de indexado de bytes del cuerpo a 4 B/palabra).
"""
import cocotb
from cocotb.triggers import RisingEdge

from test_orderbook import (A, C, E, X, D, U, S, H, run_book, iter_records,
                            _pcap_msgs_subset, _reset, drive_and_collect_bbo)


def anexo_words32(messages):
    """Convierte mensajes a words del Anexo A de 32 bits (layout recortado,
    campaña fase3-uram: w0 context, w1 idx, w2.. cuerpo — sin ts) flat."""
    words = []
    for mtype, locate, body, idx in iter_records(messages):
        words.append((ord(mtype) << 24) | (locate << 8) | (11 + len(body)))
        words.append(idx)
        for i in range(0, len(body), 4):
            bite = body[i:i + 4]
            words.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    return words


async def drive_and_collect_bbo32(dut, messages, max_cycles=200000):
    """Conduce Anexo A de 32 bits y recolecta eventos BBO del top.

    Devuelve (bbo_events, cross_count, anomaly_count)."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
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
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            bid_px = (td >> 96) & 0xFFFFFFFF
            bid_qty = (td >> 64) & 0xFFFFFFFF
            ask_px = (td >> 32) & 0xFFFFFFFF
            ask_qty = td & 0xFFFFFFFF
            out.append((loc, (bid_px, bid_qty, ask_px, ask_qty), ch))
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
    return out, cross, anomaly


@cocotb.test()
async def test_b32_01_bbo_igual_golden(dut):
    """Espejo §B32-01: secuencia multi-tipo -> BBO del golden bit a bit (32 bits)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 50, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 3, b"S", 200, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),
        X(AMZN, 1_000_000_005, 3, 80),
        C(AMZN, 1_000_000_006, 2, 50, 1002, b"Y", 1_000_00),
        D(AMZN, 1_000_000_007, 1),
        U(AMZN, 1_000_000_008, 2, 10, 30, 999_00),
    ]
    expected, golden = run_book(msgs)
    got, cross, anomaly = await drive_and_collect_bbo32(dut, msgs)
    assert got == expected, f"B32-01: got={got} exp={expected}"
    assert anomaly == golden.anomalies, (
        f"B32-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"B32-01 cross: got={cross} exp={golden.cross_events}")


@cocotb.test()
async def test_inv_b32_01_replace_atomico(dut):
    """INV/SEC-U-01 (32 bits): U sobre el mejor bid -> el estado final es visible."""
    AMZN = 1101
    msgs = [
        A(AMZN, 1, 247097, b"B", 500, b"AMZN    ", 425_800),
        A(AMZN, 2, 246365, b"B", 300, b"AMZN    ", 425_500),
        U(AMZN, 3, 247097, 247657, 500, 425_700),
    ]
    expected, golden = run_book(msgs)
    got, _, _ = await drive_and_collect_bbo32(dut, msgs)
    assert got == expected, (
        f"INV-B32-01: got={got} exp={expected} "
        f"(el U debe dejar visible el nivel 425700, no el 425800 stale)")


@cocotb.test()
async def test_inv_b32_02_raw_add_execute(dut):
    """INV/SEC-HZ-01 (32 bits): el execute ve el estado del add previo (RAW)."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 2, 1, 40, 1001),
    ]
    expected, golden = run_book(msgs)
    got, _, _ = await drive_and_collect_bbo32(dut, msgs)
    assert got == expected, f"INV-B32-02: got={got} exp={expected}"


@cocotb.test()
async def test_inv_b32_03_dos_simbolos_independientes(dut):
    """INV/MULTI-01 (32 bits): libros por símbolo independientes a 32 bits."""
    AMZN = 393
    AAPL = 13
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AAPL, 2, 10, b"S", 50, b"AAPL    ", 1_500_00),
        E(AMZN, 3, 1, 40, 1001),
        A(AAPL, 4, 11, b"B", 200, b"AAPL    ", 1_400_00),
        X(AAPL, 5, 10, 20),
    ]
    expected, golden = run_book(msgs)
    got, _, _ = await drive_and_collect_bbo32(dut, msgs)
    assert got == expected, f"INV-B32-03: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# B32-02: feed real (subset 20 símbolos) -> BBO idéntico al golden
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_b32_02_replay_feed_real_32(dut):
    """Espejo §B32-02: el BBO del feed real a 32 bits es idéntico al golden,
    bit a bit, evento a evento (pcap local no commiteado; se omite si no existe)."""
    import os
    pcap = "/tmp/real_trading.pcap"
    if not os.path.exists(pcap):
        cocotb.log.info("B32-02: pcap local ausente, test omitido (env sin datos)")
        return
    msgs, keep = _pcap_msgs_subset(pcap, max_symbols=20)
    cocotb.log.info(
        f"B32-02: {len(msgs)} mensajes de {len(keep)} símbolos "
        f"({sorted(keep)[:3]}...) contra golden a 32 bits")
    expected, golden = run_book(msgs)
    got, cross, anomaly = await drive_and_collect_bbo32(dut, msgs, max_cycles=2_000_000)
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"B32-02: got({len(got)}) exp({len(expected)}) sobre {len(msgs)} msgs "
            f"/ {len(keep)} símbolos; primer desajuste en evento {first}:\n"
            f" got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert cross == golden.cross_events, (
        f"B32-02 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"B32-02 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"B32-02 OK: {len(got)} eventos bit a bit a 32 bits, "
        f"cross={cross}, anomaly={anomaly}")