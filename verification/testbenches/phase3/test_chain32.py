"""Testbench cocotb de la cadena parser->book a DW=32 (fase 3, criterio 3) —
área phase3.

Espejo CHAIN-01: el feed real decapado entra por el parser (framing MoldUDP64
a 32 bits) y el BBO del book a 32 bits es idéntico al golden book.py, sin
re-parseo intermedio. Adversarial INV-CHAIN: secuencia sintética multi-tipo
sin gaps -> BBO bit a bit y gap_detected en 0 (la cadena no rompe framing).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, U, S, H, run_book, _pcap_msgs_subset)
from test_itch_parser import _packet_seq


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


def _chunks32(payload):
    chunks = []
    for i in range(0, len(payload), 4):
        bite = payload[i:i + 4]
        chunks.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    return chunks


async def drive_chain(dut, payloads, max_cycles=3_000_000, window=8000):
    """Conduce payloads MoldUDP64 concatenados a la cadena y recolecta BBO.

    Devuelve (bbo_events, cross, anomaly, gaps)."""
    await _reset(dut)
    concat = b"".join(payloads)
    chunks = _chunks32(concat)
    len_acc = 0
    lastbyte = set()
    for p in payloads:
        len_acc += len(p)
        lastbyte.add(len_acc - 1)
    lasts = set()
    for bi in range(len(concat)):
        if bi in lastbyte:
            lasts.add(bi // 4)
    n = len(chunks)
    out = []
    ci = 0
    quiet = 0
    cross = 0
    anomaly = 0
    gaps = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = chunks[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci in lasts else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.gap_detected.value) == 1:
            gaps += 1
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF), ch))
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
        if quiet > window:
            break
    return out, cross, anomaly, gaps


@cocotb.test()
async def test_chain01_feed_real_bit_a_bit(dut):
    """Espejo §CHAIN-01: feed real decapado -> parser 32 -> book 32 -> BBO
    idéntico al golden bit a bit (pcap local no commiteado; se omite si no existe).

    El feed completo mezcla 150K registros de todos los símbolos; el book de la
    iteración 1 registra NSYM=20 (el overflow de símbolos es el hallazgo F1 del
    grade, hardening de la iteración 4). El contrato de CHAIN-01 es el subset:
    el stream MoldUDP64 se reconstruye SOLO con los mensajes del subset (misma
    regla que REPLAY-01), y la cadena completa lo procesa de principio a fin."""
    import os
    pcap = "/tmp/real_trading.pcap"
    if not os.path.exists(pcap):
        cocotb.log.info("CHAIN-01: pcap local ausente, test omitido (env sin datos)")
        return
    msgs, keep = _pcap_msgs_subset(pcap, max_symbols=20)
    expected, golden = run_book(msgs)
    cocotb.log.info(
        f"CHAIN-01: {len(msgs)} msgs / {len(keep)} símbolos contra golden "
        f"(parser 32 -> book 32, stream reconstruido del subset)")
    got, cross, anomaly, gaps = await drive_chain(dut, [_packet_seq(msgs, 1)])
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"CHAIN-01: got({len(got)}) exp({len(expected)}); primer desajuste "
            f"en evento {first}:\n got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert cross == golden.cross_events, (
        f"CHAIN-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"CHAIN-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"CHAIN-01: {gaps} gaps en el stream del subset"
    cocotb.log.info(
        f"CHAIN-01 OK: {len(got)} eventos bit a bit por la cadena de 32 bits, "
        f"cross={cross}, anomaly={anomaly}, gaps={gaps}")


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
    got, cross, anomaly, gaps = await drive_chain(dut, [_packet_seq(msgs, 1)])
    assert got == expected, f"INV-CHAIN-01: got={got} exp={expected}"
    assert cross == golden.cross_events, (
        f"INV-CHAIN-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"INV-CHAIN-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"INV-CHAIN-01: {gaps} gaps (secuencia consecutiva)"