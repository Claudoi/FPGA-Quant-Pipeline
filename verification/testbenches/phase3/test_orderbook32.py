"""Cocotb testbench for the DW=32 order book (phase 3, criterion 2) — area
phase3.

Mirrors B32-01/B32-02: the book parameterized at DW=32 (trimmed 32-bit Annex A
layout: w0={type,locate,len}, w1=idx, w2..=body — without ts) emits the BBO
bit-exact against golden book.py, over the synthetic corpus and over the
local-day real feed. Adversarials INV-B32: atomic replace, RAW add->execute and
multi-symbol at 32 bits (pin body byte-indexing errors at 4 B/word).
"""
import cocotb
import os
from cocotb.triggers import RisingEdge

from test_orderbook import (A, C, E, X, D, U, S, H, run_book, iter_records,
                            _pcap_msgs_subset, _reset, drive_and_collect_bbo,
                            REAL_PCAP)


def anexo_words32(messages):
    """Converts messages to 32-bit Annex A words (trimmed layout, fase3-uram
    campaign: w0 context, w1 idx, w2.. body — without ts) flat."""
    words = []
    for mtype, locate, body, idx in iter_records(messages):
        words.append((ord(mtype) << 24) | (locate << 8) | (11 + len(body)))
        words.append(idx)
        for i in range(0, len(body), 4):
            bite = body[i:i + 4]
            words.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    return words


async def drive_and_collect_bbo32(dut, messages, max_cycles=200000):
    """Drives 32-bit Annex A and collects BBO events from the top.

    Returns (bbo_events, cross_count, anomaly_count)."""
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
    """Mirror §B32-01: multi-type sequence -> golden BBO bit-exact (32 bits)."""
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
    """INV/SEC-U-01 (32 bits): U on the best bid -> the final state is visible."""
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
        f"(the U must leave the 425700 level visible, not the stale 425800)")


@cocotb.test()
async def test_inv_b32_02_raw_add_execute(dut):
    """INV/SEC-HZ-01 (32 bits): the execute sees the state of the prior add (RAW)."""
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
    """INV/MULTI-01 (32 bits): independent per-symbol books at 32 bits."""
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
# B32-02: real feed (subset of 20 symbols) -> BBO identical to the golden model
# ---------------------------------------------------------------------------
@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_b32_02_replay_feed_real_32(dut):
    """Mirror §B32-02: the 32-bit real-feed BBO is identical to the golden model,
    bit-exact, event by event (local pcap not committed; skipped if absent)."""
    assert os.path.exists(REAL_PCAP), "B32-02 SKIPPED: local pcap absent"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    cocotb.log.info(
        f"B32-02: {len(msgs)} messages of {len(keep)} symbols "
        f"({sorted(keep)[:3]}...) against golden model at 32 bits")
    expected, golden = run_book(msgs)
    got, cross, anomaly = await drive_and_collect_bbo32(dut, msgs, max_cycles=2_000_000)
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"B32-02: got({len(got)}) exp({len(expected)}) over {len(msgs)} msgs "
            f"/ {len(keep)} symbols; first mismatch at event {first}:\n"
            f" got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert cross == golden.cross_events, (
        f"B32-02 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"B32-02 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"B32-02 OK: {len(got)} events bit-exact at 32 bits, "
        f"cross={cross}, anomaly={anomaly}")
