"""Testbench cocotb del recorte del Anexo A de 32 bits (fase3-uram, criterio 1)
— área uram.

Espejos ANX-01/ANX-02: el parser a DW=32 emite el Anexo A recortado
(w0={type,locate,len}, w1=idx, w2..=cuerpo — sin words de ts) bit a bit contra
el oráculo, y el peor caso sigue aceptándose a 1 palabra/ciclo con stalls
acotados. El layout vive SOLO en `oracle_words32`/`anexo_words32` (oráculos de
phase3); aquí se importan, nunca se re-escriben (contrato sin gate nº 2).
"""
import cocotb

from test_parser32 import (corpus_all_types, oracle_words32, run_oracle32,
                           drive_raw32, _packet_seq, _reset)
from test_orderbook import _pcap_msgs_subset


@cocotb.test()
async def test_anx_01_anexo_a_32_bits_recortado_es_bit_a_bit_contra_el_oraculo(dut):
    """Espejo §ANX-01: words del Anexo A recortado bit a bit contra el oráculo."""
    msgs = corpus_all_types()
    expected = run_oracle32(msgs)
    got, _ = await drive_raw32(dut, _packet_seq(msgs, 1))
    assert got == expected, (
        f"ANX-01: got({len(got)}) exp({len(expected)}) — layout recortado "
        f"(sin w2/w3 de ts)\n got={got}\n exp={expected}")
    cocotb.log.info(
        f"ANX-01 OK: {len(expected)} words de 32 bits bit a bit "
        f"({len(msgs)} mensajes, layout recortado)")

    import os
    pcap = "/tmp/real_trading.pcap"
    if os.path.exists(pcap):
        msgs_real, keep = _pcap_msgs_subset(pcap, max_symbols=20)
        expected_real = run_oracle32(msgs_real)
        got_real, _ = await drive_raw32(dut, _packet_seq(msgs_real, 1),
                                        max_cycles=3_000_000)
        assert got_real == expected_real, (
            f"ANX-01 (feed real): got({len(got_real)}) exp({len(expected_real)}) "
            f"sobre {len(msgs_real)} mensajes de {len(keep)} símbolos")
        cocotb.log.info(
            f"ANX-01 OK (feed real): {len(msgs_real)} mensajes -> "
            f"{len(expected_real)} words bit a bit")


@cocotb.test()
async def test_anx_02_el_peor_caso_sigue_a_1_palabra_por_ciclo_con_el_layout_recortado(dut):
    """Espejo §ANX-02: mensajes mínimos back-to-back con el layout recortado ->
    stalls acotados (régimen LIN-01, QB=64)."""
    msgs = [corpus_all_types()[2] if i % 2 == 0 else corpus_all_types()[8]
            for i in range(4)]
    words, stalls = await drive_raw32(dut, _packet_seq(msgs, 1))
    expected = run_oracle32(msgs)
    assert words == expected, (
        f"ANX-02: got({len(words)}) exp({len(expected)})")
    assert stalls <= 24, (
        f"ANX-02: {stalls} ciclos de stall con downstream consumiendo "
        f"(acotados <= 24, QB=64, iter 6 fase 3)")
    cocotb.log.info(
        f"ANX-02 OK: {stalls} stalls acotados con {len(msgs)} mensajes "
        f"back-to-back ({len(expected)} words)")
