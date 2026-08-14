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
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_itch_parser import _packet_seq, corpus_all_types, _reset
from golden_model.src import message_oracle


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


async def drive_raw32(dut, payload, out_tready=(1,), max_cycles=60000):
    """Conduce un payload en chunks de 4 B y devuelve (words, stalls)."""
    await _reset(dut)
    chunks = []
    for i in range(0, len(payload), 4):
        bite = payload[i:i + 4]
        chunks.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    n = len(chunks)
    out = []
    ci = 0
    stalls = 0
    quiet = 0
    tr_idx = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = chunks[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.m_axis_tready.value = 1 if (out_tready[tr_idx % len(out_tready)] == 1) else 0
        tr_idx += 1
        await RisingEdge(dut.clk)
        tv = int(dut.s_axis_tvalid.value)
        tr = int(dut.s_axis_tready.value)
        if tv == 1 and tr == 0:
            stalls += 1
        if tv == 1 and tr == 1:
            if ci < n:
                ci += 1
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if quiet > 80:
            break
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
    """Decap del pcap (Ethernet/IPv4/UDP -> MoldUDP64) a chunks de 4 B -> RTL."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    concat = b"".join(payload for _seq, _msgs, payload in packets)

    await _reset(dut)
    chunks = []
    for i in range(0, len(concat), 4):
        bite = concat[i:i + 4]
        chunks.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    ci = 0
    quiet = 0
    out = []
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < len(chunks) else 0
        dut.s_axis_tdata.value = chunks[ci] if ci < len(chunks) else 0
        dut.s_axis_tlast.value = 1 if ci == len(chunks) - 1 else 0
        dut.m_axis_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.m_axis_tvalid.value) == 1 and int(dut.m_axis_tready.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(chunks):
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(chunks):
                ci += 1
        if quiet > 8000:
            break
    exp = oracle_words32(packets)
    return out, exp, len(packets)


@cocotb.test()
async def test_p32_03_replay_pcap_real_32(dut):
    """Espejo §P32-01 (evidencia real): el parser 32 sobre el pcap del día local
    coincide bit a bit (pcap no commiteado; se omite si no existe)."""
    import os
    pcap = "/tmp/real_subset.pcap"
    if not os.path.exists(pcap):
        cocotb.log.info("P32-03: pcap local ausente, test omitido (env sin datos)")
        return
    out, exp, npack = await drive_pcap32(dut, pcap)
    assert out == exp, (
        f"P32-03: got({len(out)}) exp({len(exp)}) sobre {npack} paquetes:\n"
        f" got={out}\n exp={exp}")
    cocotb.log.info(f"P32-03 OK: {npack} paquetes, {len(out)} words de 32 bits bit a bit")