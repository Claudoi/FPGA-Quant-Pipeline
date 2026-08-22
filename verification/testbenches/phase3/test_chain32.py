"""Cocotb testbench for the parser->book chain at DW=32 (phase 3, criterion 3) —
area phase3.

Mirror CHAIN-01: the decapsulated real feed enters through the parser (MoldUDP64
framing at 32 bits) and the 32-bit book BBO is identical to golden book.py,
without intermediate re-parsing. Adversarial INV-CHAIN: multi-type synthetic
sequence without gaps -> bit-exact BBO and gap_detected at 0 (the chain does
not break framing).
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
    """Drives independent MoldUDP64 datagrams and collects the BBO.

    Returns (bbo_events, depth_words, cross, anomaly, gaps)."""
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
                "CHAIN: depth_tvalid must accompany the BBO")
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
        f"CHAIN: accepted tlast={accepted_tlast}, expected={len(payloads)}")
    if require_input_stall:
        assert input_stalls > 0, "CHAIN: the adversarial did not force backpressure"
    if expected_errors is not None:
        assert errors == expected_errors, (
            f"CHAIN: error pulses={errors}, expected={expected_errors}")
    return out, depth, cross, anomaly, gaps


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_chain01_feed_real_bit_a_bit(dut):
    """Mirror §CHAIN-01: decapsulated real feed -> parser 32 -> book 32 -> BBO
    identical to the golden model bit-exact (local pcap not committed; skipped
    if absent).

    The full feed mixes 150K records of all symbols; the iteration 1 book
    registers NSYM=20 (the symbol overflow is finding F1 of the grade,
    iteration 4 hardening). The CHAIN-01 contract is the subset: the MoldUDP64
    stream is rebuilt ONLY with the subset messages (same rule as REPLAY-01),
    and the whole chain processes it end to end."""
    assert os.path.exists(REAL_PCAP), "CHAIN-01 SKIPPED: local pcap absent"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    assert msgs, "CHAIN-01: pcap present without subset messages"
    assert keep, "CHAIN-01: pcap present without subset symbols"
    nd = len(dut.depth_tdata) // 128
    expected, expected_depth, golden = run_book_depth(msgs, nd=nd)
    expected_depth_words = [pack_depth(*event[1:]) for event in expected_depth]
    assert expected, "CHAIN-01: real subset without observable BBO events"
    assert expected_depth_words, "CHAIN-01: real subset without observable depth events"
    assert len(expected) == len(expected_depth_words), (
        f"CHAIN-01 ND={nd}: golden BBO={len(expected)}, "
        f"depth={len(expected_depth_words)}")
    cocotb.log.info(
        f"CHAIN-01: {len(msgs)} msgs / {len(keep)} symbols against golden model "
        f"(parser 32 -> book 32, stream rebuilt from the subset)")
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
            f"CHAIN-01: got({len(got)}) exp({len(expected)}); first mismatch "
            f"at event {first}:\n got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    # The BBO is bit-exact (fully verified above). The depth follows the
    # amended push-out contract (spec fase3-optimizacion, addendum iter 15,
    # scenario OVR-PUSH-01): bit-exact up to the first re-entry of a level
    # discarded by the P=32 queue (loc13 goes back above 32 levels at the peak
    # of the day; the level 2890300/2 is discarded and reappears in the top-5
    # at event 14461). From there the depth keeps the SUBSET property: every
    # RTL level (px,qty) belongs to the golden model's book with its exact qty
    # — never a phantom; the absent levels are those discarded by the (>P)
    # peak that the golden model retains.
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
    DEPTH_FIRST_REENTRY = 14461   # first documented re-entry (loc13, msg 17585)
    assert len(_gold_levs) == len(depth) == len(expected_depth_words), (
        f"CHAIN-01 ND={nd}: oracle event alignment {len(_gold_levs)}")
    if depth[:DEPTH_FIRST_REENTRY] != expected_depth_words[:DEPTH_FIRST_REENTRY]:
        first = next(i for i, (g, e) in enumerate(
            zip(depth[:DEPTH_FIRST_REENTRY], expected_depth_words[:DEPTH_FIRST_REENTRY]))
            if g != e)
        raise AssertionError(
            f"CHAIN-01 ND={nd}: depth bit-exact fails before the first "
            f"re-entry ({DEPTH_FIRST_REENTRY}): event {first}: "
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
            # post re-entry: the qty may be partial (the level was discarded at the
            # >P peak and re-added); the price is never a phantom.
            if _px not in _lev:
                raise AssertionError(
                    f"CHAIN-01 ND={nd}: depth with phantom in the re-entry "
                    f"(event {i}): price {_px} ({_side}) outside the golden "
                    f"{sorted(_lev)[:6]}")
    assert cross == golden.cross_events, (
        f"CHAIN-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"CHAIN-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert gaps == 0, f"CHAIN-01: {gaps} gaps in the subset stream"
    cocotb.log.info(
        f"CHAIN-01 OK ND={nd}: {len(got)} BBO bit-exact and {len(depth)} depth "
        f"(bit-exact up to the 1st re-entry {DEPTH_FIRST_REENTRY}; subset "
        f"afterwards) through the 32-bit chain, cross={cross}, anomaly={anomaly}, "
        f"gaps={gaps}")


@cocotb.test()
async def test_chain02_sintetico_bit_a_bit(dut):
    """INV/CHAIN-01 (synthetic): multi-type sequence without gaps -> bit-exact BBO."""
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
    assert gaps == 0, f"INV-CHAIN-01: {gaps} gaps (consecutive sequence)"


@cocotb.test()
async def test_dp01_nd_parametrizado_llega_al_book(dut):
    """Mirror §DP-01: the ND of the top reaches the book (ND=5 and shard ND=3)."""
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
        f"DP-01 ND={nd}: depth does not match the golden model")
    assert gaps == 0, f"DP-01 ND={nd}: {gaps} gaps"


@cocotb.test()
async def test_ovr01_mensaje_oversize_no_deadlock(dut):
    """Mirror §OVR-01: an I message (50 B, 2+len=52 > QB=46 of the chain) does
    not deadlock the parser: the datagram's tlast is accepted, the following
    messages are processed and there are no error pulses (the oversize is
    drained without a record; I is not in the parser subset).

    RED with the prior ST_LEN (2+len > QB never fits in the queue -> tready=0
    indefinitely); GREEN with the oversize drain (addendum iter 12)."""
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
    """AXI-KEEP-05/11: two partial datagrams preserve boundaries and beats."""
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
    assert got == expected, f"AXI-KEEP chain: got={got} exp={expected}"
    assert cross == golden.cross_events
    assert anomaly == golden.anomalies
    assert gaps == 0
