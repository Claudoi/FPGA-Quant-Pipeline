"""Cocotb testbench for the order book (phase 2) — area verification/testbenches/orderbook.

Feeds the `orderbook` top with the Annex A record (context word0, word1 ts,
words 2..N big-endian body) emitted by the phase 1 parser, and compares the
emitted BBO **bit-exact** against the oracle
`golden_model.src.book.Book` (phase 0 semantics, validated against a real day).

Synthetic vectors (rule G0) and local-day replay (not committed).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import struct
import os

from golden_model.src import book as book_golden
from golden_model.src import message_oracle

REAL_PCAP = "/tmp/real_trading.pcap"


# ---------------------------------------------------------------------------
# ITCH message construction (literals from the PDF / messages.py)
# ---------------------------------------------------------------------------
def _mk(t, locate, ts, body):
    return (t + struct.pack(">H", locate) + b"\x00\x00" +
            int.to_bytes(ts, 6, "big") + body)


def A(locate, ts, ref, side, shares, stock, price):
    return _mk(b"A", locate, ts, struct.pack(">Q", ref) + side +
               struct.pack(">I", shares) + stock + struct.pack(">I", price))


def F(locate, ts, ref, side, shares, stock, price, attr):
    return _mk(b"F", locate, ts, struct.pack(">Q", ref) + side +
               struct.pack(">I", shares) + stock + struct.pack(">I", price) + attr)


def E(locate, ts, ref, exsh, match):
    return _mk(b"E", locate, ts, struct.pack(">Q", ref) +
               struct.pack(">I", exsh) + struct.pack(">Q", match))


def C(locate, ts, ref, exsh, match, printable, price):
    return _mk(b"C", locate, ts, struct.pack(">Q", ref) + struct.pack(">I", exsh) +
               struct.pack(">Q", match) + printable + struct.pack(">I", price))


def X(locate, ts, ref, cansh):
    return _mk(b"X", locate, ts, struct.pack(">Q", ref) + struct.pack(">I", cansh))


def D(locate, ts, ref):
    return _mk(b"D", locate, ts, struct.pack(">Q", ref))


def U(locate, ts, orig, new, shares, price):
    return _mk(b"U", locate, ts, struct.pack(">QQ", orig, new) +
               struct.pack(">II", shares, price))


def S(locate, ts, event):
    return _mk(b"S", locate, ts, bytes([event]))


def H(locate, ts, state):
    return _mk(b"H", locate, ts, b"AMZN    " + bytes([state]) + b"\x00" * 5)


# ---------------------------------------------------------------------------
# oracle: Annex A feed + expected BBO from the golden model
# ---------------------------------------------------------------------------
def iter_records(messages, start_idx=0):
    """Walks raw messages and emits Annex A records (like the parser).
    Returns (msg_type, locate, body, msg_idx)."""
    idx = start_idx
    for raw in messages:
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        yield mtype, locate, body, idx
        idx += 1


def run_book(messages):
    """Oracle: applies the messages with book.py and returns BBO events.
    Event: (locate, (bid_px, bid_qty, ask_px, ask_qty), changed)."""
    bk = book_golden.Book()
    events = []
    for idx, raw in enumerate(messages):
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        # rebuild the fields book.py expects (same phase 0 parsing)
        fields = _fields_from_body(mtype, body)
        msg = (idx, mtype, locate, 0, 0, fields)
        ev = bk.apply(msg)
        if ev is not None:
            events.append(ev)
    return events, bk


def run_book_depth(messages, nd=5):
    """Top-N oracle (phase 3, criterion 6): for each BBO event, captures the ND
    best levels per side of the event's symbol, best-first (bid by descending
    price, ask ascending), padded with (0, 0) up to ND.

    Returns (bbo_events, depth_events, book) with each depth_event =
    (locate, bid_levels, ask_levels); bid_levels[i]/ask_levels[i] = (px, qty).
    The levels are ALWAYS derived from _levels of the golden model, never from
    the RTL."""
    bk = book_golden.Book()
    events = []
    depth = []
    for idx, raw in enumerate(messages):
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        fields = _fields_from_body(mtype, body)
        ev = bk.apply((idx, mtype, locate, 0, 0, fields))
        if ev is not None:
            events.append(ev)
            bid = sorted(bk._levels.get((locate, book_golden.BID), {}).items(), reverse=True)
            ask = sorted(bk._levels.get((locate, book_golden.ASK), {}).items())
            bid = (list(bid) + [(0, 0)] * nd)[:nd]
            ask = (list(ask) + [(0, 0)] * nd)[:nd]
            depth.append((locate, bid, ask))
    return events, depth, bk


def pack_depth(bid, ask):
    """Packs (best-first bid, best-first ask) into the 2*ND*64-bit word of the
    depth_tdata bus: {best_bid, ..., 5th_bid, best_ask, ..., 5th_ask} from MSB
    to LSB, each level {px[31:0], qty[31:0]}, empties at 0."""
    w = 0
    for px, qty in list(bid) + list(ask):
        w = (w << 64) | ((px & 0xFFFFFFFF) << 32) | (qty & 0xFFFFFFFF)
    return w


def _fields_from_body(mtype, body):
    """Extracts the field tuple book.py consumes (struct fields)."""
    if mtype == "S":
        return (chr(body[0]),)  # the golden model compares against "Q"/"M" (str)
    if mtype == "H":
        return (body[0:8], chr(body[8]))  # stock, trading_state ("T" = continuous)
    if mtype in ("A", "F"):
        ref = int.from_bytes(body[0:8], "big")
        side = chr(body[8])
        shares = int.from_bytes(body[9:13], "big")
        stock = body[13:21]
        price = int.from_bytes(body[21:25], "big")
        if mtype == "A":
            return (ref, side, shares, stock, price)
        return (ref, side, shares, stock, price, body[25:29])
    if mtype in ("E", "C"):
        ref = int.from_bytes(body[0:8], "big")
        exsh = int.from_bytes(body[8:12], "big")
        match = int.from_bytes(body[12:20], "big")
        if mtype == "E":
            return (ref, exsh, match)
        printable = chr(body[20])
        price = int.from_bytes(body[21:25], "big")
        return (ref, exsh, match, printable, price)
    if mtype == "X":
        return (int.from_bytes(body[0:8], "big"), int.from_bytes(body[8:12], "big"))
    if mtype == "D":
        return (int.from_bytes(body[0:8], "big"),)
    if mtype == "U":
        return (int.from_bytes(body[0:8], "big"), int.from_bytes(body[8:16], "big"),
                int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big"))
    return None


# ---------------------------------------------------------------------------
# driver: Annex A -> orderbook top, collect BBO
# ---------------------------------------------------------------------------
async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


def anexo_words(messages):
    """Converts messages to Annex A words (w0 context, ts, body) flat."""
    words = []
    for mtype, locate, body, idx in iter_records(messages):
        w0 = (ord(mtype) << 56) | (locate << 40) | ((11 + len(body)) << 32) | (idx & 0xFFFFFFFF)
        words.append(w0)
        ts = int.from_bytes(b"", "big") if False else 0  # ts is not used by the book
        words.append(ts)
        for i in range(0, len(body), 8):
            bite = body[i:i + 8]
            words.append(int.from_bytes(bite, "big") << (8 * (8 - len(bite))))
    return words


async def drive_and_collect_bbo(dut, messages, max_cycles=200000):
    """Drives the Annex A (words) and collects BBO events from the top.

    Returns (bbo_events, cross_count, anomaly_count, error_cycles).
    bbo_events is a list of (locate, (bid_px,bid_qty,ask_px,ask_qty), changed).
    """
    await _reset(dut)
    words = anexo_words(messages)
    # 64-bit chunks, tlast at the end of each record (burst)
    ci = 0
    n = len(words)
    out = []
    quiet = 0
    cross = 0
    anomaly = 0
    error_cycles = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        # tlast: each message burst ends by its length; we simplify to a single
        # burst for the whole feed (the book does not use tlast per msg)
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            # bbo_tdata[127:0] = {bid_px, bid_qty, ask_px, ask_qty} (4×32)
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
        error_cycles += int(dut.error.value)
        if quiet > 200:
            break
    return out, cross, anomaly, error_cycles


# ---------------------------------------------------------------------------
# BBO-01: multi-type sequence -> BBO bit-exact against the golden model
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_bbo01_secuencia_bbo_igual_golden(dut):
    """Mirror §BBO-01: add/execute/cancel/delete sequence -> golden BBO."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),          # market open
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 50, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 3, b"S", 200, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),        # reduce 40/100
        X(AMZN, 1_000_000_005, 3, 80),              # cancel 80/200
        C(AMZN, 1_000_000_006, 2, 50, 1002, b"Y", 1_000_00),  # exec down to 0 -> delete
        D(AMZN, 1_000_000_007, 1),                  # delete ref 1 (left 60? no: rest 60)
        U(AMZN, 1_000_000_008, 2, 10, 30, 999_00),  # replace ref2 (already deleted) -> anomaly
    ]
    expected, golden = run_book(msgs)
    got, cross, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    # normalize: the golden model emits (locate, (bbo), changed); got identical
    assert got == expected, (
        f"BBO-01:\n got={got}\n exp={expected}")
    assert anomaly == golden.anomalies, (
        f"BBO-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"BBO-01 cross: got={cross} exp={golden.cross_events}")


# ---------------------------------------------------------------------------
# SEC-U-01: atomic replace — never an intermediate BBO with the order absent
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_u01_replace_atomico(dut):
    """Mirror §SEC-U-01: the BBO of the U is that of the final state (no window)."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        U(AMZN, 2, 1, 2, 50, 1_001_00),   # atomic replace: bid 100000->100100
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    # the BBO of the U is the final (100100, 50) — the prior bid (100000) no longer exists
    assert got == expected, f"SEC-U-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-HZ-01: add followed by execute on the same ref (RAW)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_hz01_add_execute_raw(dut):
    """Mirror §SEC-HZ-01: the execute sees the state of the prior add."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 2, 1, 40, 1001),   # reduce 40/100 -> 60
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-HZ-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-HZ-02: replace followed by execute on the new ref (RAW)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_hz02_replace_execute_raw(dut):
    """Mirror §SEC-HZ-02: the execute acts on the replaced order."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        U(AMZN, 2, 1, 2, 50, 1_001_00),   # new ref=2
        E(AMZN, 3, 2, 30, 1002),          # reduce ref2 50->20
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-HZ-02: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-DC-01: execute + cancel do not double-decrement
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_dc01_sin_doble_descuento(dut):
    """Mirror §SEC-DC-01: the total decremented is exactly the initial one."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 2, 1, 40, 1001),   # 100-40=60
        X(AMZN, 3, 1, 60,),        # 60-60=0 -> delete
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-DC-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-DC-02: delete decrements exactly the qty (not 2×)
#   Kills the D-DOUBLE mutant (delete with -2*qty -> negative newq -> error).
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_dc02_delete_descuenta_exacto(dut):
    """Mirror §SEC-DC-01 (edge): delete empties the level without error nor 2×."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        D(AMZN, 2, 1),              # delete of the only bid order -> level 0
    ]
    # the golden model does NOT abort (delete of an existing ref is valid) -> BBO (0,0)
    expected, golden = run_book(msgs)
    assert golden.anomalies == 0, "SEC-DC-02: delete of existing ref is not an anomaly"
    got, _, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    # the final BBO must be (0,0,0,0) and without error or anomaly
    assert got == expected, f"SEC-DC-02: got={got} exp={expected}"
    assert anomaly == 0, f"SEC-DC-02: anomaly={anomaly} (valid delete does not count)"


# ---------------------------------------------------------------------------
# SEC-AN-01: unknown ref -> anomaly, continues
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_an01_ref_desconocida(dut):
    """Mirror §SEC-AN-01: op on an absent ref counts an anomaly and continues."""
    AMZN = 393
    msgs = [
        E(AMZN, 1, 99, 10, 1),     # ref 99 does not exist -> anomaly
        A(AMZN, 2, 1, b"B", 100, b"AMZN    ", 1_000_00),
    ]
    expected, golden = run_book(msgs)
    got, _, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    assert anomaly == golden.anomalies, f"SEC-AN-01: anomaly={anomaly} exp={golden.anomalies}"
    assert got == expected, f"SEC-AN-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-OV-01: reduce more than available -> error (golden invariant)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_ov01_overflow_cantidad(dut):
    """Mirror §SEC-OV-01: observable error, discard and recovery."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        X(AMZN, 2, 1, 200,),        # cancel 200 > 100 -> error (golden model aborts)
        A(AMZN, 3, 2, b"S", 50, b"AMZN    ", 1_005_00),
    ]
    # the golden model raises InvariantError; the RTL must signal `error` without aborting
    try:
        run_book(msgs)
        raise AssertionError("SEC-OV-01: the golden model should abort on negative qty")
    except book_golden.InvariantError:
        pass  # expected
    # The invalid operation does not emit; the subsequent add is kept.
    expected, _ = run_book([msgs[0], msgs[2]])
    got, _, _, error_cycles = await drive_and_collect_bbo(dut, msgs)
    assert error_cycles >= 1, "SEC-OV-01: the error pulse was not observed"
    assert got == expected, f"SEC-OV-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# OVR-PUSH-01: level overflow with push-out (SEC-OV-01 amended, iter 13)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_ovr_push01_desborde_push_out(dut):
    """Mirror §OVR-PUSH-01: ask list full; add better than the worst -> push-out
    without error and BBO at the new best; add worse than the worst -> SEC-OV
    (error) and BBO intact. The golden model, without a level limit, emits the
    changed=0 event of the deep add; the RTL emits it identical (materializes
    the top-P per the discard)."""
    AMZN = 393
    base_ts = 10_000_000_000
    adds = [A(AMZN, base_ts + i, i + 1, b"S", 5, b"AMZN    ", 50_000 + 100 * i)
            for i in range(32)]
    mejor = A(AMZN, base_ts + 32, 100, b"S", 5, b"AMZN    ", 49_500)
    peor = A(AMZN, base_ts + 33, 101, b"S", 5, b"AMZN    ", 60_000)

    # case 1: add better than the current worst -> push-out, without error
    msgs1 = adds + [mejor]
    expected1, _ = run_book(msgs1)
    got1, _, _, err1 = await drive_and_collect_bbo(dut, msgs1)
    assert err1 == 0, f"OVR-PUSH-01: unexpected error in the push-out: {err1}"
    assert got1 == expected1, f"OVR-PUSH-01: got={got1} exp={expected1}"
    assert got1[-1][1][2] == 49_500, f"OVR-PUSH-01: ask BBO={got1[-1][1][2]} != 49_500"

    # case 2: add worse than the current worst -> SEC-OV with error pulse, BBO intact
    msgs2 = adds + [mejor, peor]
    expected2, _ = run_book(msgs2)
    got2, _, _, err2 = await drive_and_collect_bbo(dut, msgs2)
    assert err2 >= 1, "OVR-PUSH-01: the SEC-OV error pulse was not observed"
    assert got2 == expected2, f"OVR-PUSH-01: got={got2} exp={expected2}"


# ---------------------------------------------------------------------------
# SEC-CR-01: crossed book in continuous trading -> cross_events counts
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_cr01_libro_cruzado(dut):
    """Mirror §SEC-CR-01: bid>=ask in continuous trading counts cross_events."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),                # market open
        H(AMZN, 2, ord("T")),                # trading state continuous
        A(AMZN, 3, 1, b"S", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 4, 2, b"B", 100, b"AMZN    ", 1_000_00),  # bid == ask -> cross
    ]
    expected, golden = run_book(msgs)
    got, cross, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert cross == golden.cross_events, f"SEC-CR-01: cross={cross} exp={golden.cross_events}"
    assert got == expected, f"SEC-CR-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-EM-01: symbol without orders -> BBO (0,0,0,0)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_em01_simbolo_vacio(dut):
    """Mirror §BBO-02: empty isolated locate and zero ask side."""
    AMZN = 393
    AAPL = 13
    msgs = [A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00)]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-EM-01: got={got} exp={expected}"
    assert all(loc != AAPL for loc, _, _ in got), "BBO-02: spurious event for empty AAPL"
    assert got[-1][1][2:] == (0, 0), f"BBO-02: empty ask is not zeroed: {got[-1]}"


# ---------------------------------------------------------------------------
# MULTI-01: two interleaved symbols with independent books
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_multi01_dos_simbolos_independientes(dut):
    """Mirror §MULTI-01: messages of distinct locates do not contaminate each other."""
    AMZN = 393      # locate[4:0] = 9
    AAPL = 13       # locate[4:0] = 13
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AAPL, 2, 10, b"S", 50, b"AAPL    ", 1_500_00),
        E(AMZN, 3, 1, 40, 1001),   # reduce AMZN, does not affect AAPL
        A(AAPL, 4, 11, b"B", 200, b"AAPL    ", 1_400_00),
        X(AAPL, 5, 10, 20),        # cancel AAPL, does not affect AMZN
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"MULTI-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# INV-U-01: replace on the best level — the final BBO sees the price drop
#   Pins the BUG-U: two level_add in the same cycle (the second does not see
#   the first due to non-blocking timing) -> stale best bid.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_inv_u01_replace_best_bid_estado_final(dut):
    """INV/SEC-U-01 (edge): U on the best bid -> the final state is visible and the
    original ref stays out of the table (a later D counts an anomaly)."""
    AMZN = 1101
    msgs = [
        A(AMZN, 1, 247097, b"B", 500, b"AMZN    ", 425_800),
        A(AMZN, 2, 246365, b"B", 300, b"AMZN    ", 425_500),
        U(AMZN, 3, 247097, 247657, 500, 425_700),  # drops the best bid 425800->425700
        D(AMZN, 4, 247097),   # original ref already deleted by the U -> anomaly
    ]
    expected, golden = run_book(msgs)
    got, _, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"INV-U-01: got={got} exp={expected} "
        f"(the U must leave the 425700 level visible, not the stale 425800)")
    # U-DELETE-HALF (gate E): if the replace kept the original ref in the table,
    # the D(247097) would find it (anomaly=0); the golden model deemed it deleted.
    assert anomaly == golden.anomalies == 1, (
        f"INV-U-01: anomaly={anomaly} exp={golden.anomalies} (the original ref "
        f"must stay out of the table after the U)")


# ---------------------------------------------------------------------------
# REPLAY-02: frozen BBO vectors -> bit-exact replay
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_rep02_vectores_congelados_bbo(dut):
    """Mirror §REPLAY-02: the book replays the frozen BBO vectors."""
    import os, json
    here = os.path.dirname(os.path.abspath(__file__))
    vec = os.path.join(here, "..", "..", "vectors", "bbo", "corpus_bbo.json")
    with open(vec) as f:
        data = json.load(f)
    msgs = [bytes.fromhex(h) for h in data["messages_hex"]]
    expected = [(e["locate"], (e["bid_px"], e["bid_qty"], e["ask_px"], e["ask_qty"]), e["changed"])
                for e in data["events"]]
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"REPLAY-02 ({data['name']}): got={got} exp={expected}")


# ---------------------------------------------------------------------------
# REPLAY-01: real feed (local-day pcap) -> BBO identical to the golden model
# ---------------------------------------------------------------------------
def _pcap_msgs_symbol(pcap_path, target_locate):
    """Reads a pcap and filters the messages of ONE symbol (locate)."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    msgs = []
    for _seq, msgs_pkt, _pay in packets:
        for m in msgs_pkt:
            if int.from_bytes(m[1:3], "big") == target_locate:
                msgs.append(m)
    return msgs


def _pcap_msgs_subset(pcap_path, max_symbols=20):
    """Reads a pcap and filters to the first `max_symbols` distinct locates."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    keep = set()
    msgs = []
    for _seq, msgs_pkt, _pay in packets:
        for m in msgs_pkt:
            loc = int.from_bytes(m[1:3], "big")
            if loc not in keep and len(keep) < max_symbols:
                keep.add(loc)
            if loc in keep:
                msgs.append(m)
    return msgs, keep


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_repro_ask_insert_mejor_precio(dut):
    """Reduced repro of the event 3353 divergence (real feed): the minimal
    synthetic case (4 asks + best ask) passes; the bug requires the real
    window. The first 4042 messages of the pcap are fed (faithful prior state)
    and the BBO is compared with the golden model — it must diverge at event
    3353."""
    msgs, _ = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    msgs = msgs[:4042]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"REPRO-3353: first mismatch at event {first}\n"
            f" got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert got == expected, "REPRO-3353: got==exp"


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_debug_smcap_evento_3353(dut):
    """DEBUG: dumps sm_cap_px/sm_cap_qt (emission capture, verilator public) at
    events 3351-3356 with msgs[:4038] to see the state of the RTL's ask levels
    at the divergence."""
    msgs, _ = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    msgs = msgs[:4038]
    await _reset(dut)
    words = anexo_words(msgs)
    cocotb.log.info(f"DEBUG: {len(msgs)} msgs -> {len(words)} words")
    P_ASK_OFF = 32  # P=32 levels per side; ask in sm_cap[P..2P-1]
    ev_idx = [0]
    samples = {}
    ci = 0
    n = len(words)
    quiet = 0

    async def sample():
        n_ = ev_idx[0]
        if 3351 <= n_ <= 3356:
            asks = [(int(dut.sm_cap_px[P_ASK_OFF + i].value),
                     int(dut.sm_cap_qt[P_ASK_OFF + i].value))
                    for i in range(32)]
            samples[n_] = [(p, q) for p, q in asks if q != 0]

    for _ in range(2_000_000):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            await sample()
            ev_idx[0] += 1
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if quiet > 200:
            break
    cocotb.log.info(f"DEBUG: total events {ev_idx[0]}, words {ci}/{n}")
    for k in sorted(samples):
        cocotb.log.info(f"smcap EV{k}: asks={samples[k]}")


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_replay01_feed_real_bbo(dut):
    """Mirror §REPLAY-01: the BBO of the real feed (subset of 20 symbols) is
    identical to golden book.py — bit-exact, event by event, including changed.

    The local pcap is not committed (rule G0); the test is skipped if absent."""
    assert os.path.exists(REAL_PCAP), "REPLAY-01 SKIPPED: local pcap absent"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    cocotb.log.info(
        f"REPLAY-01: {len(msgs)} messages of {len(keep)} symbols "
        f"({sorted(keep)[:3]}...) against golden model")
    expected, golden = run_book(msgs)
    got, cross, anomaly, _ = await drive_and_collect_bbo(dut, msgs, max_cycles=2_000_000)
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"REPLAY-01: got({len(got)}) exp({len(expected)}) over {len(msgs)} msgs "
            f"/ {len(keep)} symbols; first mismatch at event {first}: "
            f"anomaly={anomaly} cross={cross} golden.cross={golden.cross_events}\n"
            f" got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert cross == golden.cross_events, (
        f"REPLAY-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"REPLAY-01 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"REPLAY-01 OK: {len(got)} events bit-exact, "
        f"cross={cross}, anomaly={anomaly}")
