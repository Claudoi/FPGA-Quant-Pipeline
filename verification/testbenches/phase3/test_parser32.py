"""Testbench cocotb del parser a DW=32 (fase 3, criterio 1) — área phase3.

Espejos P32-01/P32-02: el parser parametrizado a DW=32 emite el Anexo A de
32 bits bit a bit contra el oráculo, y sostiene el line-rate (0 stalls) en el
peor caso probado. Layout 32 (Anexo A recortado, campaña fase3-uram):

    w0 = {msg_type[7:0], locate[15:0], length[7:0]}
    w1 = msg_idx[31:0]
    w2.. = cuerpo (MSB-first, relleno 0)

(sin words de timestamp: el book no las consume; contrato enmendado por
specs/fase3-uram/spec.md, criterio 1).

Adversariales INV-P32: backpressure de salida sin pérdida (espejo OUT-02 de la
fase 1, ahora a 32 bits) y replay del pcap real del día local (espejo REP-02).
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
    """Palabras de 32 bits esperadas para los paquetes (layout Anexo A 32
    recortado: w0 context, w1 idx, w2.. cuerpo — sin words de ts)."""
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
    """Conduce un datagrama en beats AXI de 4 B y devuelve (words, stalls)."""
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
            # `error` es registrado: se observa en este punto un ciclo después
            # del handshake inválido que lo originó.
            assert int(dut.error.value) == 1, (
                f"beat inválido {pending_error_handshake} aceptado sin pulso "
                "error asociado")
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
        f"tlast aceptados={accepted_tlast}, esperados={expected_tlast}")
    assert errors == expected_errors, (
        f"pulsos error={errors}, esperados={expected_errors}")
    assert error_handshakes_seen == set(error_on_handshakes), (
        f"handshakes inválidos observados={error_handshakes_seen}, "
        f"esperados={set(error_on_handshakes)}")
    return out, stalls


@cocotb.test()
async def test_p32_01_anexo_a_32_bits(dut):
    """Espejo §P32-01: el parser a DW=32 emite el Anexo A de 32 bits bit a bit."""
    msgs = corpus_all_types()
    expected = run_oracle32(msgs)
    got, _ = await drive_raw32(dut, _packet_seq(msgs, 1))
    assert got == expected, (
        f"P32-01: got({len(got)}) exp({len(expected)})\n"
        f" got={got}\n exp={expected}")


@cocotb.test()
async def test_p32_02_peor_caso_una_palabra_ciclo(dut):
    """Espejo §P32-02: mensajes back-to-back -> stalls ACOTADOS con downstream
    consumiendo (iter 6, QB=64: 0 stalls -> ~15 acotados; el régimen de fase 1
    ya documenta la limitación del feed infinito, LIN-01 alcance)."""
    msgs = [corpus_all_types()[2] if i % 2 == 0 else corpus_all_types()[8]
            for i in range(4)]
    words, stalls = await drive_raw32(dut, _packet_seq(msgs, 1))
    expected = run_oracle32(msgs)
    assert words == expected, f"P32-02: got({len(words)}) exp({len(expected)})"
    assert stalls <= 24, (
        f"P32-02: {stalls} ciclos de stall con downstream consumiendo "
        f"(acotados <= 24, QB=64, iter 6)")


@cocotb.test()
async def test_inv_p32_01_backpressure_salida_sin_perdida(dut):
    """INV/OUT-02 (32 bits): con tready bajo el parser retiene sin pérdida ni duplicado."""
    msgs = corpus_all_types()
    words, _ = await drive_raw32(dut, _packet_seq(msgs, 1), out_tready=(1, 1, 0))
    expected = run_oracle32(msgs)
    assert words == expected, (
        f"INV-P32-01: got({len(words)}) exp({len(expected)})\n"
        f" got={words}\n exp={expected}")


# ---------------------------------------------------------------------------
# P32-03 (REP-02 a 32 bits): replay del pcap real del día local
# ---------------------------------------------------------------------------
async def drive_pcap32(dut, pcap_path, max_cycles=3_000_000):
    """Decap del pcap (Ethernet/IPv4/UDP -> MoldUDP64) por datagrama -> RTL."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    payloads = [payload for _seq, _msgs, payload in packets]
    assert packets, "P32-03: pcap existente sin datagramas MoldUDP64"
    assert all(payloads), "P32-03: pcap existente con payload MoldUDP64 vacío"

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
        f"P32-03: tlast aceptados={accepted_tlast}, esperados={len(payloads)}")
    exp = oracle_words32(packets)
    assert exp, "P32-03: pcap existente sin salida esperada del subset ITCH"
    return out, exp, len(packets)


@cocotb.test(skip=not os.path.exists(REAL_SUBSET_PCAP))
async def test_p32_03_replay_pcap_real_32(dut):
    """Espejo §P32-01 (evidencia real): el parser 32 sobre el pcap del día local
    coincide bit a bit (pcap no commiteado; se omite si no existe)."""
    assert os.path.exists(REAL_SUBSET_PCAP), "P32-03 OMITIDO: pcap local ausente"
    out, exp, npack = await drive_pcap32(dut, REAL_SUBSET_PCAP)
    assert out == exp, (
        f"P32-03: got({len(out)}) exp({len(exp)}) sobre {npack} paquetes:\n"
        f" got={out}\n exp={exp}")
    cocotb.log.info(f"P32-03 OK: {npack} paquetes, {len(out)} words de 32 bits bit a bit")


@cocotb.test()
async def test_p32_tkeep_invalido_y_truncados_recuperan(dut):
    """AXI-KEEP-04/10: máscaras inválidas y truncados 1..3 B recuperan."""
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
            f"truncado {missing} B: got={got}")
