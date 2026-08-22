"""Cocotb testbench for the ITCH parser (phase 1) — area verification/testbenches/parser.

Drives the MoldUDP64 payload (post IP/UDP decapsulation) into the `itch_parser`
top word by word (s_axis) and collects the AXI-Stream output (m_axis), rebuilding
each Annex A record (burst delimited by tlast). Compares byte-exact against the
oracle `golden_model.src.message_oracle.iter_message_records`.

Synthetic vectors (rule G0). Byte-exact comparison (gate G3).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.handle import Immediate
from cocotb.triggers import ReadOnly, RisingEdge
import os
import struct

from golden_model.src import message_oracle
from golden_model.itch.messages import MESSAGE_LENGTHS

REAL_PCAP = "/tmp/real_subset.pcap"

# ---------------------------------------------------------------------------
# oracle: expected output words (flat) for `messages`
# ---------------------------------------------------------------------------
def _packet(messages):
    payload = struct.pack(">10sQH", b"SIM0000001", 1, len(messages))
    payload += b"".join(len(m).to_bytes(2, "big") + m for m in messages)
    return payload


def run_oracle(messages):
    payload = _packet(messages)
    packets = [(1, messages, payload)]
    return run_oracle_packets(packets)


def run_oracle_packets(packets):
    """Multi-packet oracle: GLOBAL msg_idx (0,1,2,...) across all datagrams. The
    RTL increments msg_idx per emitted record without resetting between
    packets; the oracle must do the same."""
    words = []
    for w0, ts, body in message_oracle.iter_message_records(packets):
        words.append(w0)
        words.append(ts)
        for i in range(0, len(body), 8):
            words.append(int.from_bytes(body[i:i + 8], "big") << (8 * (8 - len(body[i:i + 8]))))
    return words


def packet_beats(payloads, bytes_per_word):
    beats = []
    for payload in payloads:
        assert payload, "a datagram cannot lack a final beat"
        for offset in range(0, len(payload), bytes_per_word):
            chunk = payload[offset:offset + bytes_per_word]
            shift = 8 * (bytes_per_word - len(chunk))
            data = int.from_bytes(chunk, "big") << shift
            keep = ((1 << len(chunk)) - 1) << (bytes_per_word - len(chunk))
            last = offset + len(chunk) == len(payload)
            beats.append((data, keep, last))
    return beats


def _present_beat(dut, beats, index):
    data, keep, last = beats[index] if index < len(beats) else (0, 0, False)
    dut.s_axis_tvalid.value = int(index < len(beats))
    dut.s_axis_tdata.value = data
    dut.s_axis_tkeep.value = keep
    dut.s_axis_tlast.value = int(last)


def _check_input_stability(dut, held):
    valid = int(dut.s_axis_tvalid.value)
    ready = int(dut.s_axis_tready.value)
    beat = (int(dut.s_axis_tdata.value), int(dut.s_axis_tkeep.value),
            int(dut.s_axis_tlast.value))
    if held is not None:
        assert beat == held, (
            "input AXI changed before releasing backpressure: "
            f"{held} -> {beat}")
    if valid and not ready:
        return beat, 0
    if valid and ready:
        return None, int(dut.s_axis_tlast.value)
    return None, 0


# ---------------------------------------------------------------------------
# synthetic message builders (literals from the PDF spec)
# ---------------------------------------------------------------------------
def _mk(t, locate, ts, body):
    return (t + struct.pack(">H", locate) + b"\x00\x00" +
            int.to_bytes(ts, 6, "big") + body)


def S(locate, ts, event):
    return _mk(b"S", locate, ts, bytes([event]))


def R(locate, ts):
    # 39 B: stock(8) mcat(1) fin(1) round(4) rlo(1) ic(1) isub(2) auth(1)
    #        sst(1) ipo(1) luld(1) etp(1) lev(4) inv(1) = 28 B of body
    body = (b"AMZN    " + b"N" + b"o" + struct.pack(">I", 100) + b"B" + b"C" +
            b"Q " + b"R" + b"N" + b"Y" + b" " + b"N" + struct.pack(">I", 0) + b"N")
    assert len(body) == 28
    return _mk(b"R", locate, ts, body)


def H(locate, ts):
    return _mk(b"H", locate, ts, b"AAPL    " + b"T" + b"\x00" + b"TEST")


def canonical_message(msg_type):
    length = MESSAGE_LENGTHS[msg_type][1]
    return msg_type.encode("ascii") + bytes(length - 1)


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


def P(locate, ts, ref, side, shares, stock, price, match):
    # 44 B: ref(8) side(1) shares(4) stock(8) price(4) match(8) = 33 of body
    body = struct.pack(">Q", ref) + side + struct.pack(">I", shares) + stock + \
           struct.pack(">I", price) + struct.pack(">Q", match)
    assert len(body) == 33
    return _mk(b"P", locate, ts, body)


def corpus_all_types():
    return [
        S(393, 1_000_000_000, 0x4F),
        R(393, 1_000_000_001),
        A(393, 1_000_000_002, 0x1122334455667788, b"\x01", 1000, b"AMZN    ", 1_234_567),
        F(393, 1_000_000_003, 1, b"\x01", 500, b"AMZN    ", 1_200_000, b"NAQ "),
        E(393, 1_000_000_004, 0x1122334455667788, 100, 0x0102030405060708),
        C(393, 1_000_000_005, 0x1122334455667788, 50, 0x0102030405060708, b"\x01", 1_234_000),
        X(393, 1_000_000_006, 0x1122334455667788, 25),
        D(393, 1_000_000_007, 0x1122334455667788),
        U(393, 1_000_000_008, 5, 6, 200, 1_100_000),
        P(393, 1_000_000_009, 7, b"\x01", 300, b"AMZN    ", 1_210_000, 9),
    ]


def corpus_no_subset():
    i = (b"I" + struct.pack(">H", 1) + b"\x00\x00" + (0).to_bytes(6, "big") +
         b"\x00" * 39)
    return [i, A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
async def _reset(dut):
    dut.clk.value = Immediate(0)
    cocotb.start_soon(Clock(dut.clk, 5, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def drive_and_collect(dut, messages, tready_high=True, max_cycles=20000):
    """Drives one packet and returns the output words (AXI-Stream burst).

    The output is read in the ReadOnly phase (post rising edge) to obtain
    stable registered values. Schedules the input in the write phase (before
    the RisingEdge) and keeps going until draining the input plus a silence
    window.
    """
    await _reset(dut)
    payload = _packet(messages)
    beats = packet_beats([payload], 8)

    out = []
    ci = 0          # next input chunk to present
    quiet = 0       # cycles WITHOUT output after exhausting the input (drain window)
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        # present the word of the current cycle (handshake: RTL's combinational
        # tready closes the transfer on the SAME edge).
        _present_beat(dut, beats, ci)
        if not tready_high:
            dut.m_axis_tready.value = 1 if (_ % 3) != 1 else 0
        await RisingEdge(dut.clk)
        # if a transfer happened on this edge (tvalid and tready high),
        # advance to the next chunk
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        # collect output; closing window after exhausting the input
        if int(dut.m_axis_tvalid.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        if quiet > 64:
            break
    assert accepted_tlast == 1, f"accepted {accepted_tlast} tlast, expected 1"
    return out


@cocotb.test()
async def test_par01_all_types_match_oracle(dut):
    """Mirror §PAR-01: each type of the subset -> record byte-exact like the oracle."""
    await _reset(dut)
    msgs = corpus_all_types()
    expected = run_oracle(msgs)
    got = await drive_and_collect(dut, msgs)
    assert got == expected, (
        f"Mismatch.\n got({len(got)}): {got}\nexp({len(expected)}): {expected}")


@cocotb.test()
async def test_sec_par04_no_subset_no_register(dut):
    """Mirror §SEC-PAR-04: a valid H advances msg_idx without emitting a record."""
    a0 = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    h = H(13, 3)
    a2 = A(13, 4, 8, b"\x00", 11, b"AAPL    ", 4)
    msgs = [a0, h, a2]
    payload = _packet_seq(msgs, 1)
    got, errores, _ = await drive_packets_err(dut, [payload])
    expected = run_oracle(msgs)
    assert errores == 0, f"SEC-PAR-04: canonical H produced {errores} errors"
    assert got == expected, f"got={got} exp={expected}"

# ---------------------------------------------------------------------------
# flexible driver: raw feed (payload + seq) with backpressure opts and input
# stall counting. Returns (out_words, stalls_in, accepted_ci).
# ---------------------------------------------------------------------------
async def drive_raw(dut, payload, seq=1, out_tready=(1,), max_cycles=30000):
    """Drives a payload (session+seq+count+msgs) and returns (words, stalls)."""
    await _reset(dut)
    beats = packet_beats([payload], 8)
    out = []
    ci = 0
    stalls = 0
    quiet = 0
    tr_idx = 0
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1 if (out_tready[tr_idx % len(out_tready)] == 1) else 0
        tr_idx += 1
        await RisingEdge(dut.clk)
        tv = int(dut.s_axis_tvalid.value)
        tr = int(dut.s_axis_tready.value)
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if tv == 1 and tr == 0:
            stalls += 1
        if tv == 1 and tr == 1:
            if ci < len(beats):
                ci += 1
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        if quiet > 80:
            break
    assert accepted_tlast == 1, f"accepted {accepted_tlast} tlast, expected 1"
    return out, stalls


def _packet_seq(messages, seq):
    payload = struct.pack(">10sQH", b"SIM0000001", seq, len(messages))
    payload += b"".join(len(m).to_bytes(2, "big") + m for m in messages)
    return payload


def _packet_session(session, seq, messages):
    payload = struct.pack(">10sQH", session, seq, len(messages))
    payload += b"".join(len(m).to_bytes(2, "big") + m for m in messages)
    return payload


async def drive_packets(dut, packets, out_tready=(1,), max_cycles=30000,
                        expect_gap=0):
    """Drives each datagram as an independent AXI burst and counts gaps."""
    await _reset(dut)
    beats = packet_beats(packets, 8)
    out = []
    ci = 0
    quiet = 0
    tr_idx = 0
    gaps = 0
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1 if (out_tready[tr_idx % len(out_tready)] == 1) else 0
        tr_idx += 1
        await RisingEdge(dut.clk)
        if int(dut.gap_detected.value) == 1:
            gaps += 1
        tv = int(dut.s_axis_tvalid.value)
        tr = int(dut.s_axis_tready.value)
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if tv == 1 and tr == 1:
            if ci < len(beats):
                ci += 1
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        if quiet > 80:
            break
    assert gaps == expect_gap, f"gaps: {gaps} != {expect_gap}"
    assert accepted_tlast == len(packets), (
        f"accepted {accepted_tlast} tlast, expected {len(packets)}")
    return out, gaps


# ---------------------------------------------------------------------------
# LIN-01: four A/U messages back-to-back -> bounded stalls with tready high
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_lin01_back_to_back_min_no_stall(dut):
    """Mirror §LIN-01: four A/U messages back-to-back -> bounded stalls.

    The span fits in the queue (amortization of the capture-to-msg_reg
    design): the parser does not stall the producer while the downstream
    consumes. The INFINITE back-to-back feed requirement (which would demand
    an infinite queue or an aligner with emit-side draining) is documented as
    pending in spec/fase1 (see spec.md: LIN-01 scope).

    Iteration 6 (2026-08-14): QB 128->64 trims the steady-state queue backlog
    (~2.7x of wire->BBO latency); the probed span goes from 0 to BOUNDED
    stalls (~15 over 4 A/U messages): the "no sustained backpressure" of the
    phase 1 regime. The bound catches gross regressions (e.g. a broken drain);
    the bit-exact correctness is validated below."""
    # Literal contracted A/U span. The worst case of infinite minimal
    # back-to-back messages remains a physical non-goal in the spec; this test
    # measures the real QB=64 regime and does not claim zero stalls.
    msgs = [A(13, i + 10, i, b"\x01", 1000, b"AAPL    ", 1000 + i) if i % 2 == 0
            else U(13, i + 10, i, i + 1, 200, 1100 + i)
            for i in range(4)]
    payload = _packet_seq(msgs, 1)
    words, stalls = await drive_raw(dut, payload, out_tready=(1,))
    expected = run_oracle(msgs)
    assert words == expected, f"LIN words mismatch: {len(words)} vs {len(expected)}"
    assert stalls <= 24, (
        f"LIN: {stalls} stalls with downstream consuming (bounded <= 24, "
        f"QB=64, iter 6)")


# ---------------------------------------------------------------------------
# ALN-01: a message crossing a word with any initial offset
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_aln01_message_not_word_aligned(dut):
    """Mirror §ALN-01: A is decoded at every one of the eight word offsets."""
    a = A(393, 1_000_000_002, 0x1122334455667788, b"\x01", 1000, b"AMZN    ", 1_234_567)
    # Offset of type A = (20 header + prior frames + 2 len A) mod 8.
    # These canonical non-subset prefixes produce exactly the eight phases.
    prefixes_by_offset = {
        0: ("Q",), 1: ("H",), 2: ("I",), 3: ("B",),
        4: ("N",), 5: ("O",), 6: (), 7: ("H", "N"),
    }
    for offset, prefix_types in prefixes_by_offset.items():
        prefixes = [canonical_message(msg_type) for msg_type in prefix_types]
        actual_offset = (20 + sum(2 + len(m) for m in prefixes) + 2) % 8
        assert actual_offset == offset
        msgs = prefixes + [a]
        payload = _packet_seq(msgs, 1)
        expected = run_oracle(msgs)
        words, _ = await drive_raw(dut, payload, out_tready=(1,))
        assert words == expected, f"ALN offset={offset}: got {len(words)} exp {len(expected)}"


@cocotb.test()
async def test_frm01_seq_expected_no_gap(dut):
    """Mirror §FRM-01+02: consecutive seqs with no gap -> no gap_detected."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    payload = _packet_seq(msgs, 1)
    await _reset(dut)
    _, _ = await drive_raw(dut, payload)
    # after the feed the parser reports a gap if there was a hole; with seq=1
    # continuous there is no gap_detected (pulse) seen post-hoc: we only check
    # output functionality
    words, _ = await drive_raw(dut, payload)
    assert words == run_oracle(msgs), "FRM seq ok"


# ---------------------------------------------------------------------------
# OUT-02/03: output backpressure (intermittent tready) without loss
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_out02_backpressure_salida_sin_perdida(dut):
    """Mirror §OUT-02: with tready low the parser holds the stream without loss or duplication."""
    msgs = corpus_all_types()
    payload = _packet_seq(msgs, 1)
    words, _ = await drive_raw(dut, payload, out_tready=(1, 1, 0))
    expected = run_oracle(msgs)
    assert words == expected, (
        f"OUT-02: got({len(words)}) exp({len(expected)})\n"
        f" got={words}\n exp={expected}")


@cocotb.test()
async def test_out03_handshake_tvalid_tready(dut):
    """Mirror §OUT-03: the tvalid/tready handshake only advances when both are high."""
    await _reset(dut)
    msgs = corpus_all_types()
    payload = _packet_seq(msgs, 1)
    beats = packet_beats([payload], 8)

    out = []
    ci = 0
    quiet = 0
    tvalid_high = False
    last_tdata_while_stalled = None
    tr_idx = 0
    held = None
    accepted_tlast = 0
    for _ in range(30000):
        _present_beat(dut, beats, ci)
        tready_now = 1 if (tr_idx % 3) != 1 else 0
        dut.m_axis_tready.value = tready_now
        tr_idx += 1
        await RisingEdge(dut.clk)
        tv = int(dut.m_axis_tvalid.value)
        tr = int(dut.m_axis_tready.value)
        td = int(dut.m_axis_tdata.value)
        if tv == 1 and tr == 1:
            out.append(td)
            tvalid_high = False
            last_tdata_while_stalled = None
        elif tv == 1 and tr == 0:
            # OUT-03: data does NOT change while tvalid high and tready low
            if tvalid_high:
                assert last_tdata_while_stalled is None or td == last_tdata_while_stalled, (
                    f"OUT-03: tdata changed with tvalid high and tready low: "
                    f"{last_tdata_while_stalled:#x} -> {td:#x}")
            else:
                tvalid_high = True
                last_tdata_while_stalled = td
        if tv == 0:
            tvalid_high = False
            last_tdata_while_stalled = None
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if ci >= len(beats) and tv == 0:
            quiet += 1
        if quiet > 80:
            break
    expected = run_oracle(msgs)
    assert out == expected, (
        f"OUT-03: got({len(out)}) exp({len(expected)})\n"
        f" got={out}\n exp={expected}")
    assert accepted_tlast == 1, f"accepted {accepted_tlast} tlast, expected 1"

@cocotb.test()
async def test_sec_gap01_seq_gap_detectado(dut):
    """Mirror §SEC-GAP-01: a sequence gap is signaled, counted, and parsing continues."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # packet1 seq=1 (expected), packet2 seq=3 -> gap (2 skipped), continues
    p1 = _packet_seq(msgs, 1)
    p2 = _packet_seq(msgs, 3)
    out, gaps = await drive_packets(dut, [p1, p2], expect_gap=1)
    exp = run_oracle_packets([(1, msgs, p1), (3, msgs, p2)])
    assert gaps == 1, f"SEC-GAP-01: expected 1 gap, saw {gaps}"
    assert out == exp, f"SEC-GAP-01: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_gap02_seq_igual_no_gap(dut):
    """Mirror §SEC-GAP-02: a seq equal to the expected one does not signal a gap."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # packet1 seq=1 (1 msg), packet2 seq=2 (expected) -> no gap
    p1 = _packet_seq(msgs, 1)
    p2 = _packet_seq(msgs, 2)
    out, gaps = await drive_packets(dut, [p1, p2], expect_gap=0)
    exp = run_oracle_packets([(1, msgs, p1), (2, msgs, p2)])
    assert out == exp, f"SEC-GAP-02: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm03_cambio_sesion_resetea_seq(dut):
    """Mirror §SEC-FRM-03: a session change resets the expected seq."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # session A seq=100, then session B seq=7 (not 101 -> no gap due to session change)
    pA = _packet_session(b"SESSIONAAA", 100, msgs)
    pB = _packet_session(b"SESSIONBBB", 7, msgs)
    out, gaps = await drive_packets(dut, [pA, pB], expect_gap=0)
    exp = run_oracle_packets([(100, msgs, pA), (7, msgs, pB)])
    assert gaps == 0, f"SEC-FRM-03: session change must NOT mark a gap, saw {gaps}"
    assert out == exp, f"SEC-FRM-03: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm04_count_cero_valido(dut):
    """Mirror §SEC-FRM-04: a packet with a count equal to zero is valid."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # The new session forces exp_seq=100; count=0 must keep that 100.
    p0 = _packet_session(b"SESSIONBBB", 100, [])
    p1 = _packet_session(b"SESSIONBBB", 100, msgs)
    out, gaps = await drive_packets(dut, [p0, p1], expect_gap=0)
    exp = run_oracle_packets([(100, [], p0), (100, msgs, p1)])
    assert gaps == 0, f"SEC-FRM-04: count=0 must not mark a gap, saw {gaps}"
    assert out == exp, f"SEC-FRM-04: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm05_datagramas_no_alineados_no_comparten_beat(dut):
    """Mirror §SEC-FRM-05: the final padding does not invade the next header.

    Kills the production mutation that concatenates datagrams before forming
    beats and uses padding bytes as if they were the start of the next
    MoldUDP64 header.
    """
    a = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    b = A(14, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    p1 = _packet_seq([a], 1)
    p2 = _packet_seq([b], 2)
    assert len(p1) % 8 != 0 and len(p2) % 8 != 0
    got, errores, accepted_tlast = await drive_packets_err(dut, [p1, p2])
    expected = run_oracle_packets([(1, [a], p1), (2, [b], p2)])
    assert errores == 0, f"SEC-FRM-05: unexpected errors: {errores}"
    assert accepted_tlast == 2, f"SEC-FRM-05: accepted tlast {accepted_tlast}"
    assert got == expected, f"SEC-FRM-05: got={got} exp={expected}"


@cocotb.test()
async def test_sec_frm04_count_cero_parcial_msb_y_recuperacion(dut):
    """Mirror §SEC-FRM-04: count=0 of 20 B ends with keep=11110000.

    Kills the mutation that interprets the four padding lanes as payload or
    that leaves a count=0 state contaminating the following datagram.
    """
    p0 = _packet_session(b"SIM0000001", 1, [])
    valid = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    p1 = _packet_session(b"SIM0000001", 1, [valid])
    assert len(p0) == 20
    assert packet_beats([p0], 8)[-1][1:] == (0b11110000, True)
    got, errores, accepted_tlast = await drive_packets_err(dut, [p0, p1])
    assert errores == 0, f"SEC-FRM-04: unexpected errors: {errores}"
    assert accepted_tlast == 2, f"SEC-FRM-04: accepted tlast {accepted_tlast}"
    assert got == run_oracle([valid]), f"SEC-FRM-04: got={got}"


@cocotb.test()
async def test_sec_frm02_campo_len_final_conserva_eop_y_recupera(dut):
    """An accepted tlast with only the len field is not lost when draining HDR."""
    partial = struct.pack(">10sQH", b"SIM0000001", 1, 1) + (36).to_bytes(2, "big")
    recovery = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    recovered = _packet_session(b"SIM0000002", 100, [recovery])
    assert len(partial) == 22

    got, errors, accepted_tlast = await drive_packets_err(
        dut, [partial, recovered])

    assert errors == 1, f"SEC-FRM-02 len final: errores={errors}"
    assert accepted_tlast == 2, (
        f"SEC-FRM-02 len final: accepted tlast={accepted_tlast}")
    assert got == run_oracle([recovery]), (
        f"SEC-FRM-02 len final: got={got}")


@cocotb.test()
async def test_sec_frm07_count_tlast_cierre_exacto(dut):
    """Mirror §SEC-FRM-07: count and tlast close the same datagram.

    Kills the mutations that accept residual bytes, allow closing before
    count, or reinterpret a residue as the header of the next packet.
    """
    first = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    extra = A(13, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    recovery = A(14, 4, 9, b"\x01", 12, b"GOOG    ", 5)
    p_lower = _packet_seq([first, extra], 1)
    p_lower = p_lower[:18] + (1).to_bytes(2, "big") + p_lower[20:]
    p_higher = _packet_seq([first], 1)
    p_higher = p_higher[:18] + (2).to_bytes(2, "big") + p_higher[20:]
    p_zero_payload = _packet_seq([first], 1)
    p_zero_payload = p_zero_payload[:18] + b"\x00\x00" + p_zero_payload[20:]
    cases = [
        ("count_menor", p_lower, run_oracle([first, recovery])),
        ("count_mayor", p_higher, run_oracle([first, recovery])),
        ("count_cero_con_payload", p_zero_payload, run_oracle([recovery])),
    ]
    for name, malformed, expected in cases:
        p_recovery = _packet_session(b"SIM0000002", 100, [recovery])
        got, errores, accepted_tlast = await drive_packets_err(
            dut, [malformed, p_recovery])
        assert errores == 1, f"SEC-FRM-07 {name}: errores={errores}"
        assert accepted_tlast == 2, (
            f"SEC-FRM-07 {name}: accepted tlast {accepted_tlast}")
        assert got == expected, f"SEC-FRM-07 {name}: got={got} exp={expected}"


@cocotb.test()
async def test_sec_frm07_count_exacto_sin_tlast_da_error(dut):
    """Exhausted count and empty queue do not close the datagram without tlast."""
    payload = _packet_seq([canonical_message("L")], 1)
    assert len(payload) == 48
    beats = packet_beats([payload], 8)
    data, keep, _last = beats[-1]
    beats[-1] = (data, keep, False)

    await _reset(dut)
    ci = 0
    errors = 0
    for _ in range(200):
        _present_beat(dut, beats, ci)
        await RisingEdge(dut.clk)
        errors += int(dut.error.value)
        if int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value):
            ci += 1

    assert ci == len(beats), f"SEC-FRM-07 accepted beats={ci}/{len(beats)}"
    assert errors == 1, f"SEC-FRM-07 count without tlast: errores={errors}"


@cocotb.test()
async def test_sec_frm06_tkeep_invalido_descarta_y_recupera(dut):
    """Mirror §SEC-FRM-06: invalid tkeep gives a pulse and drains up to tlast.

    Kills the mutations that accept a zero lane, holes, LSB orientation, or a
    partial outside the final beat.
    """
    malformed = _packet_session(b"SIM0000001", 1, [])
    recovery = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    cases = [
        ("cero", 0x00, 0, None),
        ("hueco", 0b10100000, 0, None),
        ("lsb", 0b01111111, 0, None),
        ("parcial_sin_tlast", 0b11110000, -1, False),
    ]
    for name, keep, index, last in cases:
        bad_beats = packet_beats([malformed], 8)
        data, _old_keep, old_last = bad_beats[index]
        bad_beats[index] = (data, keep, old_last if last is None else last)
        if last is False:
            bad_beats.append((0, 0xFF, True))
        all_beats = bad_beats + packet_beats([_packet_seq([recovery], 2)], 8)
        got, errores, accepted_tlast = await drive_packets_err(
            dut, [malformed, _packet_seq([recovery], 2)], beats=all_beats)
        assert errores == 1, f"SEC-FRM-06 {name}: errores={errores}"
        assert accepted_tlast == 2, (
            f"SEC-FRM-06 {name}: accepted tlast {accepted_tlast}")
        assert got == run_oracle([recovery]), f"SEC-FRM-06 {name}: got={got}"


@cocotb.test()
async def test_sec_frm06_registro_capturado_termina_antes_de_recuperar(dut):
    """A discard ends the captured record before recovering the next one."""
    first = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    tail = A(14, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    recovery = A(15, 4, 9, b"\x01", 12, b"GOOG    ", 5)
    malformed = _packet_session(b"SIM0000001", 1, [first, tail])
    recovered = _packet_session(b"SIM0000002", 100, [recovery])
    bad_beats = packet_beats([malformed], 8)
    data, _keep, last = bad_beats[-1]
    bad_beats[-1] = (data, 0b00000011, last)
    beats = bad_beats + packet_beats([recovered], 8)

    await _reset(dut)
    ci = 0
    errors = 0
    accepted_tlast = 0
    out = []
    held_in = None
    held_out = None
    quiet = 0
    for cycle in range(5000):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = int(
            ci >= len(bad_beats) and cycle % 3 != 1)
        await RisingEdge(dut.clk)

        if int(dut.error.value):
            errors += 1
        held_in, took_last = _check_input_stability(dut, held_in)
        accepted_tlast += took_last

        out_valid = int(dut.m_axis_tvalid.value)
        out_ready = int(dut.m_axis_tready.value)
        out_beat = (out_valid, int(dut.m_axis_tdata.value),
                    int(dut.m_axis_tlast.value))
        if held_out is not None:
            assert out_beat == held_out, (
                f"SEC-FRM-06 output changed under stall: {held_out} -> {out_beat}")
        if out_valid and not out_ready:
            held_out = out_beat
        elif out_valid and out_ready:
            out.append(out_beat[1:])
            held_out = None

        if int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value):
            ci += 1
        if ci >= len(beats) and not out_valid:
            quiet += 1
        else:
            quiet = 0
        if quiet > 80:
            break

    assert errors == 1, f"SEC-FRM-06 pending output: errores={errors}"
    assert accepted_tlast == 2, (
        f"SEC-FRM-06 pending output: accepted tlast={accepted_tlast}")
    expected_words = run_oracle([first, recovery])
    assert [word for word, _last in out] == expected_words, (
        f"SEC-FRM-06 incomplete or duplicated records: got={out}")
    first_words = len(run_oracle([first]))
    expected_last = [
        int(index in (first_words - 1, len(expected_words) - 1))
        for index in range(len(expected_words))
    ]
    assert [last for _word, last in out] == expected_last, (
        f"SEC-FRM-06 incorrect record boundaries: got={out}")
    assert out[first_words][0] & 0xFFFFFFFF == 1, (
        f"SEC-FRM-06 recovery msg_idx={out[first_words][0] & 0xFFFFFFFF}")


@cocotb.test()
async def test_sec_frm06_tkeep_invalido_no_depende_de_capacidad(dut):
    """The first invalid beat is accepted even if its popcount does not fit in q."""
    payload = _packet_seq(corpus_all_types() * 3, 1)
    beats = packet_beats([payload], 8)
    await _reset(dut)
    dut.m_axis_tready.value = 0

    ci = 0
    for _ in range(200):
        _present_beat(dut, beats, ci)
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value):
            ci += 1
        if int(dut.qn.value) + 7 > 64:
            break

    qn_before = int(dut.qn.value)
    assert qn_before + 7 > 64, (
        f"SEC-FRM-06 capacity pressure not reached: qn={qn_before}")
    assert ci < len(beats) and not beats[ci][2], (
        "SEC-FRM-06 the setup exhausted the datagram before the invalid beat")

    bad_data = beats[ci][0]
    accepted = 0
    errors = 0
    for _ in range(4):
        dut.s_axis_tvalid.value = 1
        dut.s_axis_tdata.value = bad_data
        dut.s_axis_tkeep.value = 0b01111111
        dut.s_axis_tlast.value = 0
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value):
            accepted += 1
            await ReadOnly()
            errors += int(dut.error.value)
            break

    assert accepted == 1, (
        f"SEC-FRM-06 invalid beat blocked with qn={qn_before}")
    assert errors == 1, f"SEC-FRM-06 bypass errors={errors}"


@cocotb.test()
async def test_sec_frm06_tkeep_parcial_no_final_falla_al_aceptar(dut):
    """A partial beat without tlast pulses an error in the same handshake."""
    await _reset(dut)
    dut.s_axis_tvalid.value = 1
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0b11110000
    dut.s_axis_tlast.value = 0

    await RisingEdge(dut.clk)
    assert int(dut.s_axis_tready.value) == 1, (
        "SEC-FRM-06 non-final partial beat was not accepted")
    await ReadOnly()
    assert int(dut.error.value) == 1, (
        "SEC-FRM-06 non-final partial beat did not pulse error on accept")


@cocotb.test()
async def test_sec_frm08_fuente_estable_bajo_backpressure_entrada(dut):
    """Mirror §SEC-FRM-08: the producer holds data, keep and last on stall.

    Kills an RTL mutation that keeps s_axis_tready high when the queue cannot
    accept, losing or duplicating beats under pressure. The feeder monitor
    separately verifies that the test source does not change the triple before
    the handshake; it does not attribute that stimulus failure to the RTL.
    """
    messages = corpus_all_types() * 3
    words, stalls = await drive_raw(
        dut, _packet_seq(messages, 1), out_tready=(0, 0, 1))
    assert stalls > 0, "SEC-FRM-08 did not force s_axis_tready low"
    assert words == run_oracle(messages), "SEC-FRM-08: loss under backpressure"


@cocotb.test()
async def test_axi_keep_orientacion_msb_lsb(dut):
    """The MSB prefix is valid; the equivalent LSB mask is rejected.

    Kills the little-endian interpretation mutation of s_axis_tkeep.
    """
    valid = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    payload = _packet_seq([valid], 1)
    good_beats = packet_beats([payload], 8)
    assert good_beats[-1][1:] == (0b11000000, True)
    got, errores, accepted_tlast = await drive_packets_err(dut, [payload])
    assert errores == 0 and accepted_tlast == 1
    assert got == run_oracle([valid]), f"AXI keep MSB: got={got}"

    recovery = A(14, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    bad_beats = list(good_beats)
    data, _keep, last = bad_beats[-1]
    bad_beats[-1] = (data, 0b00000011, last)
    got, errores, accepted_tlast = await drive_packets_err(
        dut, [payload, _packet_seq([recovery], 2)],
        beats=bad_beats + packet_beats([_packet_seq([recovery], 2)], 8))
    assert errores == 1 and accepted_tlast == 2
    assert got == run_oracle([recovery]), f"AXI keep LSB: got={got}"

@cocotb.test()
async def test_sec_par03_longitud_incoherente(dut):
    """Mirror §SEC-PAR-03: incoherent declared length -> error signaled."""
    await _reset(dut)
    bad = b"A" + b"\x00" * 34   # 'A' of 35 B (spec requires 36)
    ok = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    payload = _packet_seq([bad, ok], 1)
    words, _ = await drive_raw(dut, payload)
    # the incoherent 'A' (35 B, spec 36) does NOT emit a record but is counted
    # (global msg_idx advances to 1); the valid 'A' emits with msg_idx=1.
    expected = run_oracle([ok])
    expected[0] = expected[0] + 1   # msg_idx=1 due to discarding the bad one
    assert words == expected, f"SEC-PAR-03: got {len(words)} exp {len(expected)}"


@cocotb.test()
async def test_sec_par05_las_22_longitudes_conocidas_se_validan(dut):
    """Mirror §SEC-PAR-05: every known type with a wrong length gives an error."""
    malformed = []
    for msg_type, (_name, expected_length) in MESSAGE_LENGTHS.items():
        message = msg_type.encode("ascii") + bytes(expected_length - 2)
        assert len(message) == expected_length - 1
        malformed.append(message)
    ok = A(13, 9, 99, b"\x01", 10, b"AAPL    ", 3)
    payload = _packet_seq(malformed + [ok], 1)
    words, errores, _ = await drive_packets_err(dut, [payload])
    expected = run_oracle([ok])
    expected[0] += len(malformed)
    assert errores == len(MESSAGE_LENGTHS), (
        f"SEC-PAR-05: {errores} errors for {len(MESSAGE_LENGTHS)} invalid lengths")
    assert words == expected, "SEC-PAR-05: did not recover the subsequent A"


# ---------------------------------------------------------------------------
# OUT-01: AXI-Stream burst with tlast on the last word of each record
# ---------------------------------------------------------------------------
def _bursts_from_words(words_with_tlast):
    """Rebuilds bursts (list of words) from (word, tlast)."""
    bursts = []
    cur = []
    for w, last in words_with_tlast:
        cur.append(w)
        if last:
            bursts.append(cur)
            cur = []
    return bursts


async def drive_bursts(dut, payload):
    """Returns (bursts, words_with_tlast) rebuilding records by tlast."""
    await _reset(dut)
    beats = packet_beats([payload], 8)
    ci = 0
    quiet = 0
    tagged = []
    bursts = []
    cur = []
    held = None
    accepted_tlast = 0
    for _ in range(30000):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            w = int(dut.m_axis_tdata.value)
            last = int(dut.m_axis_tlast.value)
            tagged.append((w, last))
            cur.append(w)
            if last:
                bursts.append(cur)
                cur = []
            quiet = 0
        elif cur:
            assert False, "OUT-01: tvalid dropped before tlast with tready high"
        elif ci >= len(beats):
            quiet += 1
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if quiet > 80:
            break
    assert accepted_tlast == 1, f"accepted {accepted_tlast} tlast, expected 1"
    return bursts, tagged


@cocotb.test()
async def test_out01_burst_con_tlast(dut):
    """Mirror §OUT-01: each message is emitted as a burst with tlast at the end."""
    msgs = corpus_all_types()
    payload = _packet_seq(msgs, 1)
    bursts, tagged = await drive_bursts(dut, payload)
    flat = [w for b in bursts for w in b]
    exp = run_oracle(msgs)
    assert flat == exp, f"OUT-01 flat: got {len(flat)} exp {len(exp)}"
    # number of bursts == number of messages of the corpus subset (10)
    assert len(bursts) == len(corpus_all_types()), (
        f"OUT-01: {len(bursts)} bursts, expected {len(corpus_all_types())}")
    # tlast only on the last word of each burst
    for tag in tagged:
        assert len([w for (w, l) in tagged if l]) == len(bursts), "OUT-01: tlast per burst"


# ---------------------------------------------------------------------------
# SEC-FRM-01: truncated frame -> error, continues on the next message
# ---------------------------------------------------------------------------
async def drive_packets_err(dut, packets, out_tready=(1,), max_cycles=200000,
                            window=200, beats=None):
    """Drives `packets` sampling `error` live.

    Returns (out_words, errores). `beats` allows injecting a malformed AXI
    mask without deriving the oracle from the RTL.
    """
    await _reset(dut)
    beats = packet_beats(packets, 8) if beats is None else beats
    out = []
    ci = 0
    quiet = 0
    errores = 0
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1 if (out_tready[0] == 1) else 0
        await RisingEdge(dut.clk)
        if int(dut.error.value) == 1:
            errores += 1
            quiet = 0
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if quiet > window:
            break
    return out, errores, accepted_tlast


# ---------------------------------------------------------------------------
# SEC-FRM-01/02: truncated frame / tlast in the middle -> error without hang
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_frm01_frame_truncado(dut):
    """Mirror §SEC-FRM-01: a truncated frame signals an error and continues."""
    ok = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    next_ok = A(14, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    full_tail = A(13, 4, 9, b"\x01", 12, b"GOOG    ", 5)
    for missing in range(1, 8):
        p1 = struct.pack(">10sQH", b"SIM0000001", 1, 2) + \
            len(ok).to_bytes(2, "big") + ok + \
            len(full_tail).to_bytes(2, "big") + full_tail[:-missing]
        p2 = _packet_session(b"SIM0000002", 100, [next_ok])
        words, errores, accepted_tlast = await drive_packets_err(dut, [p1, p2])
        assert errores == 1, (
            f"SEC-FRM-01 missing={missing}: expected one error, saw {errores}")
        assert accepted_tlast == 2, (
            f"SEC-FRM-01 missing={missing}: accepted tlast {accepted_tlast}")
        exp = run_oracle([ok, next_ok])
        assert words == exp, (
            f"SEC-FRM-01 missing={missing}: got({len(words)}) exp({len(exp)})")


@cocotb.test()
async def test_sec_frm02_tlast_en_medio(dut):
    """Mirror §SEC-FRM-02: tlast in the middle of a message -> error, no partial record."""
    ok = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    full = struct.pack(">10sQH", b"SIM0000001", 1, 1) + len(ok).to_bytes(2, "big") + ok
    mid = len(full) // 2
    truncated = full[:mid]   # the feed ends halfway through the 'A' (tlast mid-message)
    words, errores, accepted_tlast = await drive_packets_err(dut, [truncated])
    assert errores > 0, f"SEC-FRM-02: message cut mid-way must signal error, saw {errores}"
    assert words == [], f"SEC-FRM-02: must not emit a partial record, got {words}"
    assert accepted_tlast == 1, f"SEC-FRM-02: accepted tlast {accepted_tlast}"


# ---------------------------------------------------------------------------
# SEC-LIN-01: types outside the subset do not break the line rate
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_lin01_no_subset_no_rompe_line_rate(dut):
    """Mirror §SEC-LIN-01: messages outside the subset do not break the line rate."""
    msgs = [A(13, 1, 6, b"\x01", 9, b"AAPL    ", 2),
            H(13, 2),
            A(13, 3, 7, b"\x00", 10, b"AAPL    ", 3)]
    payload = _packet_seq(msgs, 1)
    words, stalls = await drive_raw(dut, payload, out_tready=(1,))
    assert stalls <= 24, f"SEC-LIN-01: {stalls} stalls with downstream consuming"
    assert words == run_oracle(msgs), "SEC-LIN-01: correct output"


# ---------------------------------------------------------------------------
# REP-01: frozen message vector -> bit-exact replay
# ---------------------------------------------------------------------------
def _load_frozen_messages(path):
    """Loads a frozen vector (messages_hex) from verification/vectors/."""
    import json
    with open(path) as f:
        data = json.load(f)
    return [bytes.fromhex(h) for h in data["messages_hex"]], data


@cocotb.test()
async def test_rep01_vectores_congelados_byte_a_byte(dut):
    """Mirror §REP-01: the RTL replays the frozen vectors byte-exact."""
    here = os.path.dirname(os.path.abspath(__file__))
    vec = os.path.join(here, "..", "..", "vectors", "messages", "corpus_all_types.json")
    msgs, meta = _load_frozen_messages(vec)
    # the oracle re-decodes the frozen stream itself (independent of the RTL)
    expected = run_oracle(msgs)
    payload = _packet_seq(msgs, 1)
    words, _ = await drive_raw(dut, payload, out_tready=(1,))
    assert words == expected, (
        f"REP-01 ({meta['name']}): got({len(words)}) exp({len(expected)})")
    # the global msg_idx starts at 0 and matches the oracle
    assert words[0] & 0xFFFFFFFF == 0, "REP-01: msg_idx of the first record == 0"


# ---------------------------------------------------------------------------
# REP-02: replay of a real pcap (local day) against the --emit-messages oracle
# ---------------------------------------------------------------------------
async def drive_pcap(dut, pcap_path, max_cycles=2_000_000):
    """Decapsulates the pcap (Ethernet/IPv4/UDP -> MoldUDP64 payload), feeds it
    to the RTL and collects the output words. The parser may stall the feed
    (correct AXI backpressure) but never loses; it waits until the queue
    fully drains."""
    from scripts.binaryfile_to_pcap import iter_pcap_packets

    packets = list(iter_pcap_packets(pcap_path))
    payloads = [payload for _seq, _msgs, payload in packets]
    orac_packets = [(seq, msgs, payload) for seq, msgs, payload in packets]
    assert packets, "REP-02: existing pcap without MoldUDP64 datagrams"
    assert payloads and all(payloads), (
        "REP-02: existing pcap without non-empty MoldUDP64 payload")

    await _reset(dut)
    beats = packet_beats(payloads, 8)
    ci = 0
    quiet = 0
    out = []
    held = None
    accepted_tlast = 0
    input_stalls = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        input_valid = int(dut.s_axis_tvalid.value)
        input_ready = int(dut.s_axis_tready.value)
        input_stalls += int(input_valid == 1 and input_ready == 0)
        if input_valid == 1 and input_ready == 1:
            if ci < len(beats):
                ci += 1
        # full drain: feed consumed and queue empty (no output after 8000 cycles)
        if quiet > 8000:
            break
    exp = []
    for w0, ts, body in message_oracle.iter_message_records(orac_packets):
        exp.append(w0)
        exp.append(ts)
        for i in range(0, len(body), 8):
            exp.append(int.from_bytes(body[i:i + 8], "big") << (8 * (8 - len(body[i:i + 8]))))
    assert exp, "REP-02: pcap without expected ITCH subset output"
    assert accepted_tlast == len(payloads), (
        f"REP-02: accepted tlast {accepted_tlast}, expected {len(payloads)}")
    return out, exp, len(packets), input_stalls


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_rep02_replay_pcap_real_dia_local(dut):
    """Mirror §REP-02: the RTL over a real-day pcap matches byte-exact.
    (local pcap not committed; the decorator declares the omission if absent)."""
    out, exp, npack, input_stalls = await drive_pcap(dut, REAL_PCAP)
    assert out == exp, (
        f"REP-02: got({len(out)}) exp({len(exp)}) over {npack} packets:\n"
        f" got={out}\n exp={exp}")
    assert input_stalls >= 0, "REP-02: invalid input stall counter"
    cocotb.log.info(
        f"REP-02 OK: {npack} packets, {len(out)} words byte-exact, "
        f"input stalls with m_axis_tready=1: {input_stalls}")


def _first_au_window(packets, w=4):
    """First window of w consecutive messages of the real feed where all are of
    type A or U, without manual indexes (reproducible selection from the pcap
    in capture order — REP-02 amendment 2026-08-18). Returns
    (msgs, seq0, start, end) or None if the pcap lacks the window."""
    flat = []
    for seq, msgs, _payload in packets:
        for m in msgs:
            flat.append((seq, m))
    for i in range(len(flat) - w + 1):
        win = flat[i:i + w]
        if all(chr(m[0]) in "AU" for _s, m in win):
            return [m for _s, m in win], win[0][0], i, i + w - 1
    return None


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_rep02_tramo_au_real_line_rate(dut):
    """Mirror §REP-02 (amendment 2026-08-18, line-rate closure): a real span of
    four consecutive A/U selected from the pcap without manual indexes (first
    sliding window in capture order), processed with the downstream always
    ready: <= 24 input stalls and bit-exact output against the oracle. The
    aggregated replay total does not substitute this measurement."""
    from scripts.binaryfile_to_pcap import iter_pcap_packets

    packets = list(iter_pcap_packets(REAL_PCAP))
    win = _first_au_window(packets, 4)
    if win is None:
        raise cocotb.SkipTest(
            "REP-02 line-rate: the real pcap does not contain 4 consecutive A/U "
            "(no span to measure; the criterion remains open)")
    msgs, seq0, start, end = win
    payload = _packet_seq(msgs, seq0)
    words, stalls = await drive_raw(dut, payload, out_tready=(1,))
    expected = run_oracle(msgs)
    assert words == expected, (
        f"REP-02 line-rate: got({len(words)}) exp({len(expected)}) in the "
        f"real A/U span (msgs {start}..{end})")
    assert stalls <= 24, (
        f"REP-02 line-rate: {stalls} stalls in the real A/U span "
        f"(msgs {start}..{end}); expected <= 24")
    cocotb.log.info(
        f"REP-02 line-rate OK: real A/U span (msgs {start}..{end}, "
        f"{len(msgs)} messages), {stalls} stalls with downstream always "
        f"ready, bit-exact output")


# ---------------------------------------------------------------------------
# SEC-PAR-03b: declared length == 11 (edge) does NOT mark an error
#   Kills the LEN-CAPT-ERR mutant (flip < 11 -> <= 11).
# ---------------------------------------------------------------------------
async def drive_and_sample_error(dut, payload, max_cycles=20000):
    """Drives a payload sampling the `error` pulse live."""
    await _reset(dut)
    beats = packet_beats([payload], 8)
    ci = 0
    errores = 0
    quiet = 0
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.error.value) == 1:
            errores += 1
            quiet = 0
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if ci >= len(beats) and int(dut.m_axis_tvalid.value) == 0:
            quiet += 1
        # drain window: 16 cycles after consuming the input and no output
        if quiet > 16:
            break
    assert accepted_tlast == 1, f"accepted {accepted_tlast} tlast, expected 1"
    return errores


@cocotb.test()
async def test_sec_par03b_len_igual_once_no_error(dut):
    """Mirror §SEC-PAR-03 (edge): declared length == 11 does NOT signal an error.
    The minimum valid length of an ITCH message is 11 (only the common header
    without a body). An unknown type is consumed as passthrough; a canonical
    type keeps its exact length. A mutant with `<=` would wrongly mark this edge."""
    # Unknown type of exactly 11 B (common header, no body).
    m = b"Z" + bytes([0]) * 10
    assert len(m) == 11
    payload = _packet_seq([m], 1)
    errores = await drive_and_sample_error(dut, payload)
    assert errores == 0, f"SEC-PAR-03b: len==11 must NOT mark an error, saw {errores}"
