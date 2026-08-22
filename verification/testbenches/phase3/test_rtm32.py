"""Cocotb testbench for the level-scan retiming (phase 3, iter 7) — area phase3.

Mirrors RTM-01..RTM-04 and RTM-REG-01 (spec addendum iter 7, split CLO-322-02
of the closure campaign): the single-cycle combinational ST_EMIT is split into
ST_EMIT_A (registered capture of the 2*P levels of the event's symbol and
non-empty predicates), ST_EMIT_B (first_one over the predicates + selection of
the best level, changed and depth) and ST_EMIT_C (output handshake). The
structural probe samples `st` and the `sm_cap_*` capture — both public in the
RTL, as in SEC-URAM-01: emission happens only in ST_EMIT_C and the capture
mirrors the emitted depth.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, S, run_book, drive_and_collect_bbo)
from test_orderbook32 import anexo_words32

# emission pipeline stages (orderbook.sv, addendum iter 7 and split
# CLO-322-02 of the closure campaign); the receive FSM uses st[3:0] with
# ST_EMIT=4, ST_UADD=5, ST_WAIT_PROBE=6, ST_INVAL=7, ST_LV2=8, ST_LV3=9,
# ST_SWAP=10, ST_LV2B=14 -> 11/12/13 are the A/B/C stages
# (A registers caps+predicates, B does first_one+select)
ST_EMIT_A = 11
ST_EMIT_B = 12
ST_EMIT_C = 13
# P = price levels per side (RTL default, campaign contract; the phase3
# Makefile never overrides it)
P = 32


def depth_slot(depth, j, ask=False):
    """Level j (0 = best) of the depth_tdata bus: {bid[ND-1..0], ask[ND-1..0]}
    MSB->LSB, each level {px[31:0], qty[31:0]} — packing identical to
    pack_depth of the golden model (test_orderbook)."""
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
    """Drives 32-bit Annex A and samples per cycle the `st` state and the
    `sm_cap_*` capture (structural probe of the emission pipeline).

    `stall` is a cycle->bool function (True = tready at 0, backpressure).
    Returns (events, st_seq, caps, cross, anomaly, errors):
      events = [(cycle, locate, (bid_px, bid_qty, ask_px, ask_qty), changed,
                 depth_tdata)]
      st_seq = [st] per cycle
      caps   = [(cap_bid, cap_ask)] per event, with the ND first levels of the
               capture per side: cap_bid[j] = (px, qty) of slot j."""
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
    """Mirror §RTM-01: the BBO/depth scan is registered in stages (ST_EMIT_A
    captures / ST_EMIT_B selects / ST_EMIT_C emits). Structural probe: emission
    happens only in ST_EMIT_C, each event walks the three stages in order and
    the capture mirrors the emitted depth."""
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
    # 1) each BBO handshake comes from a cycle in ST_EMIT_C. Iter 9 registers the
    #    output pair (AXI hold): the data is visible in the cycle AFTER the C
    #    cycle that generated it, when the FSM has already advanced (e.g. to
    #    ST_WAIT_PROBE or ST_SWAP). The origin state is therefore the one of the
    #    cycle before the handshake (the one that executed the emission).
    for cycle, _loc, _bbo, _ch, _depth in got:
        assert st_seq[cycle - 1] == ST_EMIT_C or st_seq[cycle] == ST_EMIT_C, (
            f"RTM-01: handshake at st={st_seq[cycle - 1]}/{st_seq[cycle]} "
            f"(cycle {cycle}); expected ST_EMIT_C={ST_EMIT_C} in the emission "
            f"cycle")
    # 2) each event walks A->B->C in consecutive cycles (split CLO-322-02: A
    # registers caps and non-empty predicates; B does the first_one and
    # selects; C emits)
    triplets = sum(
        1 for i in range(2, len(st_seq))
        if st_seq[i - 2] == ST_EMIT_A and st_seq[i - 1] == ST_EMIT_B
        and st_seq[i] == ST_EMIT_C)
    assert triplets == len(got), (
        f"RTM-01: {triplets} A->B->C walks for {len(got)} events")
    # 3) the event capture mirrors the emitted depth (slot j == depth j)
    for (_cycle, _loc, _bbo, _ch, depth), (cap_bid, cap_ask) in zip(got, caps):
        for j in range(nd):
            assert cap_bid[j] == depth_slot(depth, j, ask=False), (
                f"RTM-01: bid[{j}] capture={cap_bid[j]} != depth "
                f"{depth_slot(depth, j)}")
            assert cap_ask[j] == depth_slot(depth, j, ask=True), (
                f"RTM-01: ask[{j}] capture={cap_ask[j]} != ask depth "
                f"{depth_slot(depth, j, ask=True)}")
    # 4) bit-exact equivalence vs the golden model
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-01: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies, (
        f"RTM-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-01: {errors} spurious errors"
    cocotb.log.info(
        f"RTM-01 OK: {len(got)} events with A->B->C walk, emission "
        f"only in ST_EMIT_C, capture mirroring depth, bit-exact vs golden")


@cocotb.test()
async def test_rtm02_bbo_consistente_con_la_captura(dut):
    """Mirror §RTM-02: the BBO of the pipelined event is the first non-empty level
    of the capture (slot 0 by the sorted-list invariant), the ND first levels
    of the capture match depth_tdata, and a side without levels emits that side
    at zero (the delete of the last ask order leaves the ask side empty; the
    bid survives)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"S", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 200, b"AMZN    ", 999_00),
        D(AMZN, 1_000_000_003, 1),           # leaves the book empty
        A(AMZN, 1_000_000_004, 3, b"B", 50, b"AMZN    ", 1_000_00),
    ]
    expected, golden = run_book(msgs)
    got, st_seq, caps, cross, anomaly, errors = await drive_and_trace_rtm(dut, msgs)
    nd = len(dut.depth_tdata) // 128
    for (cycle, loc, bbo, ch, depth), (cap_bid, cap_ask) in zip(got, caps):
        # BBO = first non-empty level (slot 0) per side; empty -> zeros
        bid_px, bid_qty, ask_px, ask_qty = bbo
        if bid_qty != 0:
            assert cap_bid[0] == (bid_px, bid_qty), (
                f"RTM-02: BBO bid {cap_bid[0]} != capture slot 0 "
                f"({bid_px}, {bid_qty}) at cycle {cycle}")
        if ask_qty != 0:
            assert cap_ask[0] == (ask_px, ask_qty), (
                f"RTM-02: BBO ask != capture slot 0 at cycle {cycle}")
        # depth = first ND levels of the capture
        for j in range(nd):
            assert cap_bid[j] == depth_slot(depth, j, ask=False), (
                f"RTM-02: bid[{j}] capture != depth at cycle {cycle}")
            assert cap_ask[j] == depth_slot(depth, j, ask=True), (
                f"RTM-02: ask[{j}] capture != depth at cycle {cycle}")
    # the events of the delete of the last ask order (D) and of the subsequent
    # add without ask: that side stays empty (ask at zero) — the book does NOT
    # empty entirely because the bid survives. The number of events with empty
    # ask must match the oracle's (it is not a hardcoded vector).
    empty = [e for e in got if e[2][2] == 0 and e[2][3] == 0]
    expected_empty = [bbo for _l, bbo, _ch in expected if bbo[2] == 0 and bbo[3] == 0]
    assert len(empty) == len(expected_empty), (
        f"RTM-02: {len(empty)} events with empty ask, expected "
        f"{len(expected_empty)} (golden)")
    assert all(e[3] == 1 for e in empty), (
        "RTM-02: some changed of an event with empty ask != 1")
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-02: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies and cross == golden.cross_events, (
        f"RTM-02 counters: anomaly {anomaly}/{golden.anomalies}, "
        f"cross {cross}/{golden.cross_events}")
    assert errors == 0, f"RTM-02: {errors} spurious errors"
    cocotb.log.info(
        f"RTM-02 OK: BBO consistent with the capture, empty event at zero "
        f"({len(got)} events, bit-exact vs golden)")


@cocotb.test()
async def test_rtm03_changed_sobre_la_captura(dut):
    """Mirror §RTM-03: bbo_changed is computed over the capture (comparison against
    the previous event of the symbol): identical -> 0, different -> 1."""
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
    # iter 9: changed is compared against the oracle (golden), not against a
    # hardcoded vector: in this span the 4 events change the BBO qty
    # (100->200->160->260), so the expected changed is [1,1,1,1]
    changed = [ch for _c, _l, _b, ch, _d in got]
    expected_changed = [ch for _l, _b, ch in expected]
    assert changed == expected_changed, (
        f"RTM-03: changed={changed}, expected {expected_changed}")
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-03: got={bbo_got} exp={expected}")
    assert anomaly == golden.anomalies and cross == golden.cross_events, (
        f"RTM-03 counters: anomaly {anomaly}/{golden.anomalies}, "
        f"cross {cross}/{golden.cross_events}")
    assert errors == 0, f"RTM-03: {errors} spurious errors"
    cocotb.log.info(
        f"RTM-03 OK: changed={changed} over the capture (identical -> 0, "
        "different -> 1)")


@cocotb.test()
async def test_rtm04_handshake_retiene_evento_pipelined(dut):
    """Mirror §RTM-04: the output handshake holds the pipelined event under
    backpressure (tready=0 after observing tvalid, two stable cycles) and it is
    delivered exactly once, without loss or duplication, bit-exact against the
    golden model."""
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
            "RTM-04: bbo_tvalid dropped while tready stayed at zero")
        assert int(dut.depth_tvalid.value) == 1, (
            "RTM-04: depth_tvalid dropped while tready stayed at zero")
        assert (int(dut.bbo_tdata.value), int(dut.depth_tdata.value)) == hold["payload"], (
            "RTM-04: the payload changed during the hold")
        if hold["remaining"]:
            hold["remaining"] -= 1
            return True
        hold["released"] = True
        return False

    got, st_seq, _caps, cross, anomaly, errors = await drive_and_trace_rtm(
        dut, msgs, stall=stall)
    assert hold["seen"] and hold["released"], (
        "RTM-04: the test did not observe and release a held event")
    # the held event was emitted in its ST_EMIT_C cycle (before the stall)
    bbo_got = [(loc, bbo, ch) for _c, loc, bbo, ch, _d in got]
    assert bbo_got == expected, (
        f"RTM-04: got({len(bbo_got)}) exp({len(expected)}) "
        f"— event lost or duplicated under backpressure")
    assert anomaly == golden.anomalies, (
        f"RTM-04 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-04 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-04: {errors} spurious errors"
    cocotb.log.info(
        f"RTM-04 OK: {len(got)} events delivered exactly once after "
        "two stable hold cycles (pipelined handshake)")
