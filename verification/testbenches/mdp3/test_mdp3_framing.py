"""Testbench cocotb del parser MDP 3.0 — área verification/testbenches/mdp3.

Conduce paquetes MDP 3.0 sintéticos (golden_model.mdp3.Corpus, generados desde
el schema SBE XML oficial) palabra a palabra al top `mdp3_parser` y recolecta
la salida AXI-Stream como bursts por record (tlast). Compara byte a byte con
el oráculo `record_bytes` del golden (regla G0: vectores sintéticos).

Espejos: M3-FRM-01, M3-FRM-02, M3-FRM-03 (criterios 2-3 de la spec).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from pathlib import Path

from golden_model.mdp3 import (
    Corpus,
    iter_packet_messages,
    anexo_m_records,
    decode_message,
    passthrough_record,
    record_bytes,
    load_schema,
)
from golden_model.mdp3.schema import SUBSET_TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "data" / "mdp3" / "templates_FixBinary_v12.xml"

# Máximo de ciclos consecutivos de entrada parada en el peor caso (LIN-01).
MAX_STALL_RUN = 16


def oracle_bytes(corpus: Corpus):
    """Todos los records del corpus en bytes, en orden de emisión."""
    out = b""
    for packet in corpus.packets:
        for pm in iter_packet_messages(packet):
            if pm.template_id in SUBSET_TEMPLATES:
                decoded = decode_message(corpus.schema, pm)
                for rec in anexo_m_records(corpus.schema, pm, decoded):
                    out += record_bytes(rec)
            else:
                out += record_bytes(passthrough_record(corpus.schema, pm))
    return out


async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def drive_and_collect(dut, packets, tready_high=True, max_cycles=40000):
    """Conduce paquetes MDP 3.0 al parser y devuelve los bytes de salida.

    Cada paquete es un burst AXI-Stream con su propio tlast (back-to-back),
    como en fase 1: tras el tlast de un paquete llega el header de 12 B del
    siguiente. Devuelve (bytes de salida, run máximo de entrada parada).
    """
    dw = int(dut.DW.value)
    bytes_per_word = dw // 8
    words = []
    for pkt in packets:
        n = (len(pkt) + bytes_per_word - 1) // bytes_per_word
        for i in range(n):
            bite = pkt[i * bytes_per_word:(i + 1) * bytes_per_word]
            words.append((int.from_bytes(bite, "big")
                          << (8 * (bytes_per_word - len(bite))),
                          i == n - 1))
    nwords = len(words)

    out = bytearray()
    wi = 0
    quiet = 0
    max_stall_run = 0
    stall_run = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if wi < nwords else 0
        dut.s_axis_tdata.value = words[wi][0] if wi < nwords else 0
        dut.s_axis_tlast.value = words[wi][1] if wi < nwords else 0
        if not tready_high:
            dut.m_axis_tready.value = 1 if (_ % 3) != 1 else 0
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if wi < nwords:
                wi += 1
            stall_run = 0
        elif wi < nwords:
            # solo cuenta la parada de entrada mientras queda entrada pendiente
            stall_run += 1
            max_stall_run = max(max_stall_run, stall_run)
        else:
            stall_run = 0
        if int(dut.m_axis_tvalid.value) == 1:
            data = int(dut.m_axis_tdata.value)
            out += data.to_bytes(bytes_per_word, "big")
            quiet = 0
        elif wi >= nwords:
            quiet += 1
        if quiet > 64:
            break
    return bytes(out), max_stall_run


def build_corpus(seed: int, n_packets: int):
    schema = load_schema(SCHEMA_PATH)
    return Corpus(schema, seed=seed).build(n_packets)


@cocotb.test()
async def test_m3frm01_el_parser_emite_el_anexo_m_bit_a_bit_vs_el_golden(dut):
    """Espejo M3-FRM-01: secuencia de records bit a bit vs el golden."""
    corpus = build_corpus(seed=11, n_packets=24)
    dut._log.info("corpus built: %d packets", len(corpus.packets))
    expected = oracle_bytes(corpus)
    dut._log.info("oracle bytes: %d", len(expected))
    await _reset(dut)
    got, _ = await drive_and_collect(dut, corpus.packets)
    assert len(got) == len(expected), (
        f"longitud {len(got)} != {len(expected)}")
    for i, (g, e) in enumerate(zip(got, expected)):
        assert g == e, f"byte {i}: got {g:#04x} exp {e:#04x}"


@cocotb.test()
async def test_m3frm02_mensajes_que_cruzan_limites_de_palabra(dut):
    """Espejo M3-FRM-02: mensajes que terminan/empiezan en cualquier byte."""
    corpus = build_corpus(seed=23, n_packets=40)
    sizes = {pm.msg_size for p in corpus.packets
             for pm in iter_packet_messages(p)}
    non_aligned = [s for s in sizes if s % (int(dut.DW.value) // 8)]
    assert non_aligned, "el corpus debe tener mensajes no alineados a palabra"
    expected = oracle_bytes(corpus)
    await _reset(dut)
    got, _ = await drive_and_collect(dut, corpus.packets)
    assert got == expected, "bytes distintos (cruces de límite mal alineados)"


@cocotb.test()
async def test_m3frm03_peor_caso_a_1_palabra_por_ciclo_sin_backpressure(dut):
    """Espejo M3-FRM-03: mensajes mínimos MBP back-to-back a 1 palabra/ciclo.

    El line-rate a 1 palabra/ciclo sin backpressure se mide sobre el subset con
    expansión del Anexo M contenida (MBP, output <= input): el template 46 con
    una sola entry MBP y 0 order entries emite un record MBP de 13 words por
    un mensaje de 64 B — la salida no supera a la entrada y el datapath
    aguanta 1 palabra/ciclo. Los MBOFD (47/53/MBOFD-46) expanden (72 B de
    salida por ~54 B de entrada, ratio >1) y NO se usan aquí por ser
    inherentemente backpressure; se documentan en la spec.
    """
    schema = load_schema(SCHEMA_PATH)
    from golden_model.mdp3.codec import encode_packet, encode_message
    corpus = Corpus(schema, seed=5)
    minimal = []
    for _ in range(24):
        minimal.append(encode_message(schema, 46, {
            "TransactTime": corpus.rng.getrandbits(64),
            "MatchEventIndicator": 1,
            "NoMDEntries": [{
                "MDEntryPx": {"mantissa": 12345}, "MDEntrySize": 5,
                "SecurityID": 101, "RptSeq": 1, "NumberOfOrders": 1,
                "MDPriceLevel": 1, "MDUpdateAction": 1, "MDEntryType": 1,
                "TradeableSize": 5}],
            "NoOrderIDEntries": [],
        }))
    packet = encode_packet(schema, 99, 1, minimal)
    corpus.packets = [packet]
    expected = oracle_bytes(corpus)
    await _reset(dut)
    got, max_stall = await drive_and_collect(dut, [packet])
    assert got == expected, "la salida del peor caso no es bit a bit"
    assert max_stall <= MAX_STALL_RUN, (
        f"backpressure sostenida: {max_stall} ciclos seguidos de entrada parada")