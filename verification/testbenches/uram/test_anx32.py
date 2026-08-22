"""Cocotb testbench for the 32-bit Annex A trimming (phase3-uram, criterion 1)
— area uram.

Mirrors ANX-01/ANX-02: the DW=32 parser emits the trimmed Annex A
(w0={type,locate,len}, w1=idx, w2..=body — without ts words) bit-exact against
the oracle, and the worst case still gets accepted at 1 word/cycle with
bounded stalls. The layout lives ONLY in `oracle_words32`/`anexo_words32` (phase3
oracles); here they are imported, never re-written (contract without gate 2).
"""
import os

import cocotb

from test_parser32 import (corpus_all_types, oracle_words32, run_oracle32,
                           drive_raw32, _packet_seq, _reset)
from test_orderbook import _pcap_msgs_subset

REAL_TRADING_PCAP = "/tmp/real_trading.pcap"


@cocotb.test()
async def test_anx_01_anexo_a_32_bits_recortado_es_bit_a_bit_contra_el_oraculo(dut):
    """Mirror §ANX-01: trimmed Annex A words bit-exact against the oracle."""
    msgs = corpus_all_types()
    expected = run_oracle32(msgs)
    got, _ = await drive_raw32(dut, _packet_seq(msgs, 1))
    assert got == expected, (
        f"ANX-01: got({len(got)}) exp({len(expected)}) — trimmed layout "
        f"(without w2/w3 of ts)\n got={got}\n exp={expected}")
    cocotb.log.info(
        f"ANX-01 OK: {len(expected)} 32-bit words bit-exact "
        f"({len(msgs)} messages, trimmed layout)")


@cocotb.test(skip=not os.path.exists(REAL_TRADING_PCAP))
async def test_anx_01_replay_real_es_bit_a_bit_contra_el_oraculo(dut):
    """ANX-01 real: absence is SKIP; empty/unobservable artifact fails."""
    msgs_real, keep = _pcap_msgs_subset(REAL_TRADING_PCAP, max_symbols=20)
    assert msgs_real, "ANX-01 real: pcap present without subset messages"
    assert keep, "ANX-01 real: pcap present without subset symbols"
    expected_real = run_oracle32(msgs_real)
    assert expected_real, "ANX-01 real: subset without observable Annex A words"
    got_real, _ = await drive_raw32(
        dut, _packet_seq(msgs_real, 1), max_cycles=3_000_000)
    assert got_real == expected_real, (
        f"ANX-01 real: got({len(got_real)}) exp({len(expected_real)}) "
        f"over {len(msgs_real)} messages of {len(keep)} symbols")
    cocotb.log.info(
        f"ANX-01 OK (real feed): {len(msgs_real)} messages -> "
        f"{len(expected_real)} words bit-exact")


@cocotb.test()
async def test_anx_02_el_peor_caso_sigue_a_1_palabra_por_ciclo_con_el_layout_recortado(dut):
    """Mirror §ANX-02: minimal messages back-to-back with the trimmed layout ->
    bounded stalls (LIN-01 regime, QB=64)."""
    msgs = [corpus_all_types()[2] if i % 2 == 0 else corpus_all_types()[8]
            for i in range(4)]
    words, stalls = await drive_raw32(dut, _packet_seq(msgs, 1))
    expected = run_oracle32(msgs)
    assert words == expected, (
        f"ANX-02: got({len(words)}) exp({len(expected)})")
    assert stalls <= 24, (
        f"ANX-02: {stalls} stall cycles with downstream consuming "
        f"(bounded <= 24, QB=64, iter 6 phase 3)")
    cocotb.log.info(
        f"ANX-02 OK: {stalls} bounded stalls with {len(msgs)} messages "
        f"back-to-back ({len(expected)} words)")
