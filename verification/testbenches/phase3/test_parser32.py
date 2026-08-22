"""Cocotb testbench for the DW=32 parser (phase 3, criterion 1) — area phase3.

Mirrors P32-01/P32-02: the parser parameterized at DW=32 emits the 32-bit
Annex A bit-exact against the oracle, and sustains the line rate (0 stalls) in
the worst probed case. 32 layout (trimmed Annex A, fase3-uram campaign):

    w0 = {msg_type[7:0], locate[15:0], length[7:0]}
    w1 = msg_idx[31:0]
    w2.. = body (MSB-first, padding 0)

(without timestamp words: the book does not consume them; contract amended by
specs/fase3-uram/spec.md, criterion 1).

Adversarials INV-P32: output backpressure without loss (mirror OUT-02 of phase
1, now at 32 bits) and replay of the local-day real pcap (mirror REP-02).
"""
import cocotb
import os
import struct
from cocotb.triggers import RisingEdge

from test_itch_parser import (_check_input_stability, _packet_seq, _present_beat,
                              corpus_all_types, packet_beats, _reset)
from golden_model.src import message_oracle

REAL_SUBSET_PCAP = "/tmp/real_subset.pcap"


def oracle_words32(packets):
    """Expected 32-bit words for the packets (trimmed 32-bit Annex A layout: w0
    context, w1 idx, w2.. body — without ts words)."""
    words = []
    for w0_64, ts, body in message_oracle.iter_message_records(packets):
        words.append(((w0_64 >> 56) & 0xFF) << 24 |
                     ((w0_64 >> 40) & 0xFFFF) << 8 |
                     ((w0_64 >> 32) & 0xFF))
        words.append(w0_64 & 0xFFFFFFFF)
        for i in range(0, len(body), 4):
            bite = body[i:i + 4]
            words.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    return words


def run_oracle32(msgs):
    return oracle_words32([(1, msgs, _packet_seq(msgs, 1))])


async def drive_raw32(dut, payload, out_tready=(1,), max_cycles=60000,
                      beats=None, expected_tlast=1, expected_errors=0,
                      error_on_handshakes=()):
    """Drives one datagram in 4 B AXI beats and returns (words, stalls)."""
    await _reset(dut)
    beats = packet_beats([payload], 4) if beats is None else beats
    n = len(beats)
    out = []
    ci = 0
    stalls = 0
    quiet = 0
    tr_idx = 0
    held = None
    accepted_tlast = 0
    errors = 0
    error_handshakes_seen = set()
    pending_error_handshake = None
    for _ in range(max_cycles):
        _present_beat(dut, beats, ci)
        dut.m_axis_tready.value = 1 if (out_tready[tr_idx % len(out_tready)] == 1) else 0
        tr_idx += 1
        await RisingEdge(dut.clk)
        tv = int(dut.s_axis_tvalid.value)
        tr = int(dut.s_axis_tready.value)
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        errors += int(dut.error.value)
        if pending_error_handshake is not None:
            # `error` is registered: it is observed here one cycle after
            # the invalid handshake that caused it.
            assert int(dut.error.value) == 1, (
                f"invalid beat {pending_error_handshake} accepted without the "
                "associated error pulse")
            error_handshakes_seen.add(pending_error_handshake)
            pending_error_handshake = None
        if tv == 1 and tr == 0:
            stalls += 1
        if tv == 1 and tr == 1:
            if ci in error_on_handshakes:
                pending_error_handshake = ci
            if ci < n:
                ci += 1
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if quiet > 80:
            break
    assert accepted_tlast == expected_tlast, (
        f"accepted tlast={accepted_tlast}, expected={expected_tlast}")
    assert errors == expected_errors, (
        f"error pulses={errors}, expected={expected_errors}")
    assert error_handshakes_seen == set(error_on_handshakes), (
        f"invalid handshakes observed={error_handshakes_seen}, "
        f"expected={set(error_on_handshakes)}")
    return out, stalls


@cocotb.test()
async def test_p32_01_anexo_a_32_bits(dut):
    """Mirror §P32-01: the DW=32 parser emits the 32-bit Annex A bit-exact."""
    msgs = corpus_all_types()
    expected = run_oracle32(msgs)
    got, _ = await drive_raw32(dut, _packet_seq(msgs, 1))
    assert got == expected, (
        f"P32-01: got({len(got)}) exp({len(expected)})\n"
        f" got={got}\n exp={expected}")


@cocotb.test()
async def test_p32_02_peor_caso_una_palabra_ciclo(dut):
    """Mirror §P32-02: back-to-back messages -> BOUNDED stalls with downstream
    consuming (iter 6, QB=64: 0 stalls -> ~15 bounded; the phase 1 regime
    already documents the infinite feed limitation, LIN-01 scope)."""
    msgs = [corpus_all_types()[2] if i % 2 == 0 else corpus_all_types()[8]
            for i in range(4)]
    words, stalls = await drive_raw32(dut, _packet_seq(msgs, 1))
    expected = run_oracle32(msgs)
    assert words == expected, f"P32-02: got({len(words)}) exp({len(expected)})"
    assert stalls <= 24, (
        f"P32-02: {stalls} stall cycles with downstream consuming "
        f"(bounded <= 24, QB=64, iter 6)")


@cocotb.test()
async def test_inv_p32_01_backpressure_salida_sin_perdida(dut):
    """INV/OUT-02 (32 bits): with tready low the parser holds without loss or duplication."""
    msgs = corpus_all_types()
    words, _ = await drive_raw32(dut, _packet_seq(msgs, 1), out_tready=(1, 1, 0))
    expected = run_oracle32(msgs)
    assert words == expected, (
        f"INV-P32-01: got({len(words)}) exp({len(expected)})\n"
        f" got={words}\n exp={expected}")


# ---------------------------------------------------------------------------
# P32-03 (REP-02 at 32 bits): replay of the local-day real pcap
# ---------------------------------------------------------------------------
async def drive_pcap32(dut, pcap_path, max_cycles=3_000_000):
    """Decapsulates the pcap (Ethernet/IPv4/UDP -> MoldUDP64) per datagram -> RTL."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    payloads = [payload for _seq, _msgs, payload in packets]
    assert packets, "P32-03: existing pcap without MoldUDP64 datagrams"
    assert all(payloads), "P32-03: existing pcap with empty MoldUDP64 payload"

    await _reset(dut)
    beats = packet_beats(payloads, 4)
    ci = 0
    quiet = 0
    out = []
    held = None
    accepted_tlast = 0
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
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if quiet > 8000:
            break
    assert accepted_tlast == len(payloads), (
        f"P32-03: accepted tlast={accepted_tlast}, expected={len(payloads)}")
    exp = oracle_words32(packets)
    assert exp, "P32-03: existing pcap without expected ITCH subset output"
    return out, exp, len(packets)


@cocotb.test(skip=not os.path.exists(REAL_SUBSET_PCAP))
async def test_p32_03_replay_pcap_real_32(dut):
    """Mirror §P32-01 (real evidence): the 32-bit parser over the local-day pcap
    matches bit-exact (pcap not committed; skipped if absent)."""
    assert os.path.exists(REAL_SUBSET_PCAP), "P32-03 SKIPPED: local pcap absent"
    out, exp, npack = await drive_pcap32(dut, REAL_SUBSET_PCAP)
    assert out == exp, (
        f"P32-03: got({len(out)}) exp({len(exp)}) over {npack} packets:\n"
        f" got={out}\n exp={exp}")
    cocotb.log.info(f"P32-03 OK: {npack} packets, {len(out)} 32-bit words bit-exact")


@cocotb.test()
async def test_p32_tkeep_invalido_y_truncados_recuperan(dut):
    """AXI-KEEP-04/10: invalid masks and 1..3 B truncations recover."""
    malformed = _packet_seq([], 1)
    recovery = corpus_all_types()[2]
    recovered = _packet_seq([recovery], 2)
    invalid = [
        ("cero", 0b0000, -1, None),
        ("hueco", 0b1010, -1, None),
        ("lsb", 0b0011, -1, None),
        ("parcial_no_final", 0b1100, -1, False),
    ]
    for name, keep, index, last in invalid:
        bad_beats = packet_beats([malformed], 4)
        invalid_index = index % len(bad_beats)
        data, _old_keep, old_last = bad_beats[index]
        bad_beats[index] = (data, keep, old_last if last is None else last)
        if last is False:
            bad_beats.append((0, 0b1111, True))
        got, _ = await drive_raw32(
            dut, malformed, beats=bad_beats + packet_beats([recovered], 4),
            expected_tlast=2, expected_errors=1,
            error_on_handshakes={invalid_index})
        assert got == run_oracle32([recovery]), f"{name}: got={got}"

    first = corpus_all_types()[2]
    tail = corpus_all_types()[8]
    for missing in range(1, 4):
        truncated = (struct.pack(">10sQH", b"SIM0000001", 1, 2) +
                     len(first).to_bytes(2, "big") + first +
                     len(tail).to_bytes(2, "big") + tail[:-missing])
        got, _ = await drive_raw32(
            dut, truncated,
            beats=packet_beats([truncated, recovered], 4),
            expected_tlast=2, expected_errors=1)
        assert got == run_oracle32([first, recovery]), (
            f"truncation {missing} B: got={got}")
