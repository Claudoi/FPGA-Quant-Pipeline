"""Cocotb testbench for the DW=32 book hardening (phase 3, criteria 7-8) — area
phase3.

Mirrors SEC-NSYM-01 (finding F1 of the grade): a locate outside the NSYM=20
subset signals an error and is discarded without corrupting the book (never an
OOB index). Mirror SEC-BP-01 (finding F2): the BBO/depth pair is held under
backpressure and delivered exactly once, without loss or duplication.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, S, run_book, _reset)
from test_orderbook32 import anexo_words32


async def drive_and_collect_hard32(dut, messages, stall=None, wait_w0_at=(),
                                   max_cycles=300000):
    """Drives 32-bit Annex A with optional backpressure on bbo/depth.

    `stall` is a cycle->bool function (True = tready at 0, backpressure);
    None = without backpressure. Samples the `error` pulse per cycle.

    Returns (bbo_events, cross_count, anomaly_count, error_cycles,
    oob_index_cycles)."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    quiet = 0
    cross = 0
    anomaly = 0
    errors = 0
    oob_index_cycles = 0
    w0_released = set()
    for cycle in range(max_cycles):
        stall_now = bool(stall(cycle)) if stall else False
        wait_w0 = ci in wait_w0_at and ci not in w0_released
        if wait_w0 and int(dut.st.value) == 0:  # ST_W0
            w0_released.add(ci)
            wait_w0 = False
        dut.s_axis_tvalid.value = 1 if ci < n and not wait_w0 else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 0 if stall_now else 1
        dut.depth_tready.value = 0 if stall_now else 1
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
        if int(dut.error.value) == 1:
            errors += 1
        if int(dut.m_loc_idx.value) >= 20:
            oob_index_cycles += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > 200:
            break
    return out, cross, anomaly, errors, oob_index_cycles


@cocotb.test()
async def test_sec_nsym01_simbolo_21_error_sin_oob(dut):
    """Mirror §SEC-NSYM-01: locate 21 (outside the subset) signals an error, is
    discarded without emitting a BBO and does not corrupt the levels of the 20
    registered ones.

    Closed form: the golden model processes ONLY the subset messages; the RTL
    also receives those of symbol 21 and must emit exactly the same (the 21
    only counts an error)."""
    AMZN = 393
    locs = [AMZN] + [10_000 + i for i in range(19)]
    msgs = [S(l, 2_000_000_000 + i, ord("Q")) for i, l in enumerate(locs)]
    msgs.append(A(7777, 3_000_000_000, 100, b"B", 100, b"MSFT    ", 3_000_00))
    msgs.append(A(AMZN, 3_000_000_001, 101, b"B", 200, b"AMZN    ", 2_000_00))
    msgs.append(E(AMZN, 3_000_000_002, 101, 40, 2001))
    boundary = len(anexo_words32(msgs[:20]))
    gold_msgs = [m for m in msgs if int.from_bytes(m[1:3], "big") != 7777]
    expected, golden = run_book(gold_msgs)
    got, cross, anomaly, errors, oob_cycles = await drive_and_collect_hard32(
        dut, msgs, wait_w0_at=(boundary,))
    assert errors > 0, "SEC-NSYM-01: symbol 21 did not signal an error"
    assert oob_cycles == 0, (
        f"SEC-NSYM-01: m_loc_idx stayed out of NSYM for {oob_cycles} cycles")
    assert got == expected, (
        f"SEC-NSYM-01: got={got} exp={expected} "
        f"(symbol 21 must not emit nor corrupt the book)")
    assert anomaly == golden.anomalies, (
        f"SEC-NSYM-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"SEC-NSYM-01 cross: got={cross} exp={golden.cross_events}")
    cocotb.log.info(
        f"SEC-NSYM-01 OK: {errors} error pulses, {len(got)} intact subset "
        f"events, cross={cross}, anomaly={anomaly}")


@cocotb.test()
async def test_sec_bp01_bbo_se_retiene_bajo_backpressure(dut):
    """Mirror §SEC-BP-01: with bbo_tready/depth_tready at 0 during the event, the
    pair is held and delivered exactly once (without loss or duplication), and
    the sequence still matches the golden model bit-exact.

    Deterministic backpressure pattern: tready stays at zero until tvalid is
    seen, checks two stable hold cycles and then releases."""
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
            "SEC-BP-01: bbo_tvalid dropped while tready stayed at zero")
        assert int(dut.depth_tvalid.value) == 1, (
            "SEC-BP-01: depth_tvalid dropped while tready stayed at zero")
        assert (int(dut.bbo_tdata.value), int(dut.depth_tdata.value)) == hold["payload"], (
            "SEC-BP-01: the payload changed during the hold")
        if hold["remaining"]:
            hold["remaining"] -= 1
            return True
        hold["released"] = True
        return False

    got, cross, anomaly, errors, oob_cycles = await drive_and_collect_hard32(
        dut, msgs, stall=stall)
    assert hold["seen"] and hold["released"], (
        "SEC-BP-01: the test did not observe and release a held event")
    assert got == expected, (
        f"SEC-BP-01: got({len(got)}) exp({len(expected)}) "
        f"— event lost or duplicated under backpressure:\n"
        f" got={got}\n exp={expected}")
    assert anomaly == golden.anomalies, (
        f"SEC-BP-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"SEC-BP-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"SEC-BP-01: {errors} spurious errors under backpressure"
    assert oob_cycles == 0, f"SEC-BP-01: {oob_cycles} cycles with OOB index"
    cocotb.log.info(
        f"SEC-BP-01 OK: {len(got)} events delivered exactly once "
        "after two stable hold cycles")
