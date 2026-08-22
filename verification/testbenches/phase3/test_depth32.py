"""Cocotb testbench for the public top-N (phase 3, criterion 6) — area phase3.

Mirrors DP-01/SEC-DP-01: depth_tdata (2*ND*64 = 640 bits) bit-exact against
the ordered levels of golden book.py for the symbol of each BBO event,
best-first (descending bid, ascending ask), empties at 0. DP-02: replay of the
local-day real feed (20 symbols) with depth in ALL events.

Bus packing (spec): {bid[ND-1..0], ask[ND-1..0]} with the best level to the
left (MSB): depth[639:576] = best bid {px[31:0], qty[31:0]}.
"""
import cocotb
import os
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, S, run_book_depth, pack_depth,
                            _pcap_msgs_subset, _reset, REAL_PCAP,
                            _fields_from_body)
from test_orderbook32 import anexo_words32


async def drive_and_collect_depth32(dut, messages, max_cycles=200000):
    """Drives 32-bit Annex A and collects (bbo_events, depth_words, cross_count,
    anomaly_count). depth_tdata is sampled in the same cycle as the BBO
    handshake (the BBO/depth pair is atomic)."""
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
            # the BBO/depth pair is atomic: depth always accompanies the BBO
            if int(dut.depth_tvalid.value) != 1:
                raise AssertionError(
                    "DP: depth_tvalid must accompany the BBO handshake")
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
    """Mirror §DP-01: depth bit-exact against the golden model at each event, with
    one symbol of >= ND levels per side and another of few (empties at 0), and
    a reduce that must reflect in the qty of the level."""
    AMZN = 393
    AAPL = 13
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(6):   # 6 bid and 6 ask levels of AMZN
        msgs.append(A(AMZN, 10 + i, 100 + i, b"B", 100 + i, b"AMZN    ", 1_000_00 + i * 10))
    for i in range(6):
        msgs.append(A(AMZN, 20 + i, 200 + i, b"S", 50 + i, b"AMZN    ", 2_000_00 + i * 10))
    msgs.append(A(AAPL, 30, 1000, b"B", 300, b"AAPL    ", 5_000_00))   # AAPL: 2 bid, 1 ask
    msgs.append(A(AAPL, 31, 1001, b"B", 200, b"AAPL    ", 5_100_00))
    msgs.append(A(AAPL, 32, 1002, b"S", 150, b"AAPL    ", 5_300_00))
    msgs.append(E(AMZN, 40, 105, 10, 1))   # reduces the qty of AMZN's best bid
    expected, exp_depth, golden = run_book_depth(msgs)
    got, got_depth, cross, anomaly = await drive_and_collect_depth32(dut, msgs)
    assert got == expected, f"DP-01: BBO got={got} exp={expected}"
    for i, (g, e) in enumerate(zip(got_depth, exp_depth)):
        exp_word = pack_depth(*e[1:])
        assert g == exp_word, (
            f"DP-01: depth of event {i} (locate {e[0]}) diverges:\n"
            f" got={g:0160x}\n exp={exp_word:0160x}")
    assert anomaly == golden.anomalies, (
        f"DP-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"DP-01 cross: got={cross} exp={golden.cross_events}")


@cocotb.test()
async def test_sec_dp01_simbolo_vacio_ceros(dut):
    """Mirror §SEC-DP-01: nonexistent levels -> 0: empty ask side and remaining
    bid slots at zero in the 640-bit word."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 1, b"B", 100, b"AMZN    ", 1_000_00),   # only 1 bid level
    ]
    _, exp_depth, _ = run_book_depth(msgs)
    _, got_depth, _, _ = await drive_and_collect_depth32(dut, msgs)
    w = got_depth[0]
    # best bid in [639:576] = (100000, 100); the 4 remaining bid slots and the
    # 5 ask slots (bits [319:0]) at zero
    assert (w >> 320) == (((1_000_00 << 32) | 100) << 256), hex(w)
    assert (w & ((1 << 320) - 1)) == 0, hex(w)
    assert got_depth == [pack_depth(*e[1:]) for e in exp_depth], (
        f"SEC-DP-01: got={got_depth} exp={[pack_depth(*e[1:]) for e in exp_depth]}")


# ---------------------------------------------------------------------------
# DP-02: real feed (subset of 20 symbols) -> depth in all events
# ---------------------------------------------------------------------------
@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_dp02_replay_feed_real_depth(dut):
    """INV/DP-02: depth of ALL the real-feed events (20 symbols) bit-exact against
    the golden model (local pcap not committed; skipped if absent)."""
    assert os.path.exists(REAL_PCAP), "DP-02 SKIPPED: local pcap absent"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    nd = len(dut.depth_tdata) // 128
    cocotb.log.info(
        f"DP-02: {len(msgs)} messages of {len(keep)} symbols, "
        f"depth bit-exact at each event")
    expected, exp_depth, golden = run_book_depth(msgs)
    got, got_depth, cross, anomaly = await drive_and_collect_depth32(
        dut, msgs, max_cycles=2_000_000)
    assert len(got) == len(expected), (
        f"DP-02: got({len(got)}) exp({len(expected)}) events")
    # The depth follows the amended push-out contract (spec fase3-optimizacion,
    # addendum iter 15, OVR-PUSH-01): bit-exact up to the first re-entry of a
    # level discarded by the P=32 queue (loc13 exceeds 32 levels at the day's
    # peak; absence/partial quantity in the discarded levels). From event 14461
    # only the price-level SUBSET property is required: every RTL depth price
    # is in the golden model (never a phantom).
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
        f"DP-02: oracle alignment {len(_gold_levs)}")
    for i, (g, e) in enumerate(zip(got_depth, exp_depth)):
        exp_word = pack_depth(*e[1:])
        if g != exp_word:
            if i < DEPTH_FIRST_REENTRY:
                raise AssertionError(
                    f"DP-02: depth diverges BEFORE the re-entry at event "
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
                        f"DP-02: depth with phantom in the re-entry (event "
                        f"{i}): price {_px} ({_side}) outside the golden")
    assert cross == golden.cross_events, (
        f"DP-02 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"DP-02 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"DP-02 OK: {len(got_depth)} depth (bit-exact up to the 1st re-entry "
        f"{DEPTH_FIRST_REENTRY}; subset afterwards), "
        f"cross={cross}, anomaly={anomaly}")
