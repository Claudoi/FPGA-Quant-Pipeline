"""Testbench cocotb del parser MDP 3.0 — criterios 4-7 (subset, passthrough,
gaps, robustez) y gaps/robustez de la fase 4.

Conduce paquetes MDP 3.0 sintéticos al top `mdp3_parser` y verifica: la
decodificación del subset campo a campo (bit a bit vs golden), el passthrough
crudo de templates no-subset y desconocidos, la señalización de gaps de
secuencia, y la señalización de error ante mensajes incoherentes o paquetes
truncados, todo sin cuelgue ni corrupción del resto del stream.

Espejos: M3-SUB-01/02, M3-PASS-01, M3-GAP-01, M3-INV-01/02/03 (criterios 4-7).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from pathlib import Path

from golden_model.mdp3 import (
    Corpus,
    Schema,
    load_schema,
    encode_packet,
    iter_packet_messages,
    anexo_m_records,
    decode_message,
    passthrough_record,
    record_bytes,
)
from golden_model.mdp3.schema import SUBSET_TEMPLATES
from golden_model.mdp3 import codec

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "data" / "mdp3" / "templates_FixBinary_v12.xml"


def oracle_bytes(schema: Schema, packets) -> bytes:
    """Records de los paquetes en el orden de emisión (golden, no del RTL)."""
    out = b""
    for packet in packets:
        for pm in iter_packet_messages(packet):
            if pm.template_id in SUBSET_TEMPLATES:
                decoded = decode_message(schema, pm)
                for rec in anexo_m_records(schema, pm, decoded):
                    out += record_bytes(rec)
            else:
                out += record_bytes(passthrough_record(schema, pm))
    return out


def _words(packets, bpb):
    words = []
    for pkt in packets:
        n = (len(pkt) + bpb - 1) // bpb
        for i in range(n):
            bite = pkt[i * bpb:(i + 1) * bpb]
            words.append((int.from_bytes(bite, "big") << (8 * (bpb - len(bite))),
                          i == n - 1))
    return words


async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def drive(dut, packets, collect=True, max_cycles=60000):
    """Conduce paquetes y devuelve {bytes, gaps, errors, stall_run_max}."""
    bpb = int(dut.DW.value) // 8
    words = _words(packets, bpb)
    nwords = len(words)
    out = bytearray()
    gaps = 0
    errors = 0
    wi = 0
    stall_run = 0
    max_stall = 0
    quiet = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if wi < nwords else 0
        dut.s_axis_tdata.value = words[wi][0] if wi < nwords else 0
        dut.s_axis_tlast.value = words[wi][1] if wi < nwords else 0
        await RisingEdge(dut.clk)
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if wi < nwords:
                wi += 1
            stall_run = 0
        elif wi < nwords:
            # solo cuenta la parada de entrada mientras queda entrada pendiente
            stall_run += 1
            max_stall = max(max_stall, stall_run)
        else:
            stall_run = 0
        if int(dut.gap_detected.value) == 1:
            gaps += 1
        if int(dut.error.value) == 1:
            errors += 1
        if collect and int(dut.m_axis_tvalid.value) == 1:
            out += int(dut.m_axis_tdata.value).to_bytes(bpb, "big")
            quiet = 0
        elif wi >= nwords:
            quiet += 1
        if quiet > 64:
            break
    return {"bytes": bytes(out), "gaps": gaps, "errors": errors,
            "max_stall": max_stall}


async def _assert_bit_a_bit(dut, packets):
    expected = oracle_bytes(load_schema(SCHEMA_PATH), packets)
    await _reset(dut)
    res = await drive(dut, packets)
    assert res["bytes"] == expected, (
        f"bit a bit: {len(res['bytes'])} != {len(expected)} bytes")


def _schema():
    return load_schema(SCHEMA_PATH)


def subset_only_packets(schema, n_pkts):
    """Paquetes con solo mensajes del subset (46/47/52/53), ojo: 46 con 0 MBP
    genera los MBOFD sin referencia (contrato #5) incluidos en el oráculo."""
    corpus = Corpus(schema, seed=31)
    pkts = []
    for _ in range(n_pkts):
        msgs = [corpus.subset_message(t) for t in (46, 47, 52, 53)]
        pkts.append(encode_packet(schema, corpus.rng.randrange(0, 2**31),
                                  corpus.rng.getrandbits(64), msgs))
    return pkts


@cocotb.test()
async def test_m3sub01_el_subset_se_decodifica_campo_a_campo(dut):
    """Espejo M3-SUB-01: records de 46/47/52/53 bit a bit vs el golden."""
    schema = _schema()
    pkts = subset_only_packets(schema, 6)
    await _assert_bit_a_bit(dut, pkts)


@cocotb.test()
async def test_m3sub02_precio_compuesto_y_grupos_multi_entry(dut):
    """Espejo M3-SUB-02: mantissa/exponente por entry y un record por entry."""
    schema = _schema()
    corpus = Corpus(schema, seed=7)
    many = [corpus.subset_message(52), corpus.subset_message(46),
            corpus.subset_message(53), corpus.subset_message(47)]
    pkts = [encode_packet(schema, 10, 123456789, many)]
    expected = oracle_bytes(schema, pkts)
    # cuántos records por entry: el golden debe emitir >= 1 record por mensaje 52
    n_records = 0
    for pm in iter_packet_messages(pkts[0]):
        if pm.template_id in SUBSET_TEMPLATES:
            n_records += len(anexo_m_records(schema, pm, decode_message(schema, pm)))
    assert n_records >= 4, f"esperado record por entry del multi-entry, {n_records}"
    await _reset(dut)
    res = await drive(dut, pkts)
    assert res["bytes"] == expected


@cocotb.test()
async def test_m3pass01_el_passthrough_crudo_es_bit_a_bit_y_no_aborta(dut):
    """Espejo M3-PASS-01: templates no-subset y desconocidos crudos bit a bit."""
    schema = _schema()
    corpus = Corpus(schema, seed=13)
    pkts = []
    # un paquete con solo passthrough reales + un template desconocido (777)
    msgs = [corpus.passthrough_message() for _ in range(6)]
    msgs.append(corpus.passthrough_message(unknown=True))
    pkts.append(encode_packet(schema, 20, 987654321, msgs))
    # y un paquete con schemaId/version desconocidos deben seguir el flujo
    body = bytes(range(20))
    size = codec.MESSAGE_PREFIX_SIZE + len(body)
    unknown_hdr = (size.to_bytes(2, "little") + (16).to_bytes(2, "little")
                   + (9999).to_bytes(2, "little")
                   + (12345).to_bytes(2, "little")
                   + (0).to_bytes(2, "little") + body)
    pkts.append(encode_packet(schema, 21, 0, [unknown_hdr, corpus.subset_message(47)]))
    await _assert_bit_a_bit(dut, pkts)


@cocotb.test()
async def test_m3gap01_gap_de_secuencia_y_nuevo_canal(dut):
    """Espejo M3-GAP-01: gap_detected en un salto; reset no cuenta como gap."""
    schema = _schema()
    corpus = Corpus(schema, seed=2)
    m = corpus.subset_message(47)
    p1 = encode_packet(schema, 100, 1, [m])
    p2 = encode_packet(schema, 105, 2, [m])   # salta 101-104
    expected = oracle_bytes(schema, [p1, p2])
    await _reset(dut)
    res = await drive(dut, [p1, p2])
    assert res["gaps"] >= 1, "no se señalizó gap_detected en el salto"
    assert res["bytes"] == expected
    # nuevo canal: reset del DUT (secuencia reiniciada) no debe contar como gap
    await _reset(dut)
    p3 = encode_packet(schema, 7, 3, [m])
    res2 = await drive(dut, [p3])
    assert res2["gaps"] == 0, "un canal nuevo no debe señalizar gap"


@cocotb.test()
async def test_m3inv01_msg_size_incoherente_señaliza_error(dut):
    """Espejo M3-INV-01: msg_size < cabecera o que desborda el paquete => error."""
    schema = _schema()
    corpus = Corpus(schema, seed=4)
    good = corpus.subset_message(47)
    # msg_size = 5 (< 10 de prefijo)
    bad_small = (5).to_bytes(2, "little") + bytes(8)
    # msg_size desborda el paquete: declara más bytes de los que hay hasta tlast
    bad_overflow = (b"\xff\xff" + bytes(4))   # msg_size 0xffff > 256 => CS_SKIP error
    pkt = encode_packet(schema, 30, 0, [good, bad_small, good])
    await _reset(dut)
    res = await drive(dut, [pkt])
    assert res["errors"] >= 1, "no se señalizó error ante msg_size incoherente"
    assert res["max_stall"] < 64, "se colgó la entrada por msg_size incoherente"


@cocotb.test()
async def test_m3inv02_paquete_truncado_por_tlast_señaliza_error(dut):
    """Espejo M3-INV-02: tlast en medio de un mensaje => error y sigue el flujo."""
    schema = _schema()
    corpus = Corpus(schema, seed=9)
    good = corpus.subset_message(47)
    # un mensaje declarado pero cortado: 40 bytes de cuerpo pero solo 8 presentes
    trunc = (50).to_bytes(2, "little") + (40).to_bytes(2, "little") \
            + (47).to_bytes(2, "little") + (0).to_bytes(2, "little") \
            + (0).to_bytes(2, "little") + bytes(8)
    pkt = trunc   # tlast llegará tras estos bytes, a mitad del mensaje declarado
    await _reset(dut)
    res = await drive(dut, [pkt])
    assert res["errors"] >= 1, "no se señalizó error ante paquete truncado"
    # tras el error, un paquete bueno debe procesarse sin estado corrupto
    pkt2 = encode_packet(schema, 40, 0, [good])
    res2 = await drive(dut, [pkt2])
    assert res2["bytes"] == oracle_bytes(schema, [pkt2]), \
        "el stream quedó corrupto tras un paquete truncado"


@cocotb.test()
async def test_m3inv03_grupo_con_numin_group_cero_no_trunca(dut):
    """Espejo M3-INV-03: mensaje con NoMDEntries vacío (numInGroup 0) no cuelga."""
    schema = _schema()
    corpus = Corpus(schema, seed=3)
    # fuerzo un mensaje 46 con 0 MBP: el grupo NoMDEntries queda con numInGroup 0
    m46 = corpus.subset_message(46)
    pkts = [encode_packet(schema, 55, 0, [m46, corpus.subset_message(52)])]
    expected = oracle_bytes(schema, pkts)
    await _reset(dut)
    res = await drive(dut, pkts)
    assert res["bytes"] == expected, "numInGroup 0 debe emitir lo mismo que el golden"
