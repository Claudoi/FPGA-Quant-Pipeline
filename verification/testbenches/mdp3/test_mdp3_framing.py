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
    encode_message,
    encode_packet,
    passthrough_record,
    record_bytes,
    load_schema,
)
from golden_model.mdp3.schema import SUBSET_TEMPLATES
from golden_model.mdp3.codec import MESSAGE_PREFIX_SIZE, SCHEMA_ID, SCHEMA_VERSION

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


def assert_bytes_equal(got: bytes, expected: bytes, label: str):
    for i, (g, e) in enumerate(zip(got, expected)):
        if g != e:
            lo, hi = max(0, i - 8), min(len(expected), i + 12)
            raise AssertionError(
                f"{label}: byte {i}: got {g:#04x} exp {e:#04x}; "
                f"got[{lo}:{hi}]={got[lo:hi].hex()} "
                f"exp[{lo}:{hi}]={expected[lo:hi].hex()}")
    assert len(got) == len(expected), (
        f"{label}: prefijo común de {min(len(got), len(expected))} B, "
        f"longitud {len(got)} != {len(expected)}")


async def _reset(dut):
    dut.clk.value = 0
    cocotb.start_soon(Clock(dut.clk, 5, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    if hasattr(dut, "s_axis_tkeep"):
        dut.s_axis_tkeep.value = 0
    dut.m_axis_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


def beat_list(packets, bytes_per_input_word):
    """Beats (value, is_last, tkeep) de los paquetes, tkeep MSB-contiguo:
    los lanes válidos son los bytes altos del word; el último beat del burst
    declara solo sus bytes reales (contrato tkeep común, addendum 2026-08-18)."""
    beats = []
    for pkt in packets:
        n = (len(pkt) + bytes_per_input_word - 1) // bytes_per_input_word
        for i in range(n):
            bite = pkt[i * bytes_per_input_word:(i + 1) * bytes_per_input_word]
            nv = len(bite)
            beats.append(
                (int.from_bytes(bite, "big")
                 << (8 * (bytes_per_input_word - nv)),
                 i == n - 1,
                 ((1 << nv) - 1) << (bytes_per_input_word - nv)))
    return beats


async def drive_and_collect(dut, packets, tready_high=True, max_cycles=40000,
                            beats_override=None):
    """Conduce paquetes MDP 3.0 al parser y devuelve los bytes de salida.

    Cada paquete es un burst AXI-Stream con su propio tlast (back-to-back),
    como en fase 1: tras el tlast de un paquete llega el header de 12 B del
    siguiente. Devuelve (bytes de salida, run máximo de entrada parada).
    Si el RTL expone s_axis_tkeep, todos los beats lo aplican (y el último
    beat parcial del burst declara solo sus bytes reales); beats_override
    sustituye la lista de beats para inyectar máscaras especiales (M3-FRM-05).
    """
    bytes_per_input_word = len(dut.s_axis_tdata) // 8
    bytes_per_output_word = len(dut.m_axis_tdata) // 8
    has_tkeep = hasattr(dut, "s_axis_tkeep")
    beats = (beats_override if beats_override is not None
             else beat_list(packets, bytes_per_input_word))
    nwords = len(beats)

    out = bytearray()
    wi = 0
    quiet = 0
    max_stall_run = 0
    stall_run = 0
    error_count = 0
    gap_count = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if wi < nwords else 0
        dut.s_axis_tdata.value = beats[wi][0] if wi < nwords else 0
        dut.s_axis_tlast.value = beats[wi][1] if wi < nwords else 0
        if has_tkeep:
            dut.s_axis_tkeep.value = beats[wi][2] if wi < nwords else 0
        if not tready_high:
            dut.m_axis_tready.value = 1 if (_ % 3) != 1 else 0
        await RisingEdge(dut.clk)
        in_valid = int(dut.s_axis_tvalid.value) == 1
        in_ready = int(dut.s_axis_tready.value) == 1
        if in_valid and in_ready:
            wi += 1
            stall_run = 0
        elif in_valid:
            stall_run += 1
            max_stall_run = max(max_stall_run, stall_run)
        else:
            stall_run = 0
        if (int(dut.m_axis_tvalid.value) == 1 and
                int(dut.m_axis_tready.value) == 1):
            data = int(dut.m_axis_tdata.value)
            out += data.to_bytes(bytes_per_output_word, "big")
            quiet = 0
        elif wi >= nwords:
            quiet += 1
        error_count += int(dut.error.value)
        gap_count += int(dut.gap_detected.value)
        if quiet > 64:
            break
    return bytes(out), max_stall_run, error_count, gap_count


def build_corpus(seed: int, n_packets: int):
    schema = load_schema(SCHEMA_PATH)
    return Corpus(schema, seed=seed).build(n_packets)


def literal_template47(schema):
    """Vector pactado M3-FRM-03: una entry, 64 B derivados del XML."""
    raw = encode_message(schema, 47, {
        "TransactTime": 0x0102030405060708,
        "MatchEventIndicator": 0x81,
        "NoMDEntries": [{
            "OrderID": 0x1112131415161718,
            "MDOrderPriority": 0x2122232425262728,
            "MDEntryPx": {"mantissa": 101_250_000_000},
            "MDDisplayQty": 7,
            "SecurityID": 101,
            "MDUpdateAction": 1,
            "MDEntryType": 0,
        }],
    })
    assert len(raw) == 64
    return raw


def literal_subset(schema):
    """Un mensaje por template, con multi-entry y valores observables."""
    m46 = encode_message(schema, 46, {
        "TransactTime": 0x0102030405060708,
        "MatchEventIndicator": 0x81,
        "NoMDEntries": [
            {"MDEntryPx": {"mantissa": 101_250_000_000},
             "MDEntrySize": 7, "SecurityID": 101, "RptSeq": 11,
             "NumberOfOrders": 2, "MDPriceLevel": 1,
             "MDUpdateAction": 0, "MDEntryType": 0,
             "TradeableSize": 5},
            {"MDEntryPx": {"mantissa": -101_125_000_000},
             "MDEntrySize": 9, "SecurityID": 202, "RptSeq": 12,
             "NumberOfOrders": 3, "MDPriceLevel": 2,
             "MDUpdateAction": 1, "MDEntryType": 1,
             "TradeableSize": 6},
        ],
        "NoOrderIDEntries": [
            {"OrderID": 0x1112131415161718,
             "MDOrderPriority": 0x2122232425262728,
             "MDDisplayQty": 13, "ReferenceID": 0,
             "OrderUpdateAction": 1},
            {"OrderID": 0x3132333435363738,
             "MDOrderPriority": 0x4142434445464748,
             "MDDisplayQty": 14, "ReferenceID": 1,
             "OrderUpdateAction": 2},
        ],
    })
    m52 = encode_message(schema, 52, {
        "SecurityID": 404, "RptSeq": 33,
        "TransactTime": 0x8182838485868788,
        "NoMDEntries": [
            {"MDEntryPx": {"mantissa": 100_500_000_000},
             "MDEntrySize": 41, "NumberOfOrders": 4,
             "MDPriceLevel": 2, "TradingReferenceDate": 19_001,
             "OpenCloseSettlFlag": 1, "SettlPriceType": 5,
             "MDEntryType": 1},
            {"MDEntryPx": {"mantissa": -99_500_000_000},
             "MDEntrySize": 42, "NumberOfOrders": 5,
             "MDPriceLevel": 3, "TradingReferenceDate": 19_002,
             "OpenCloseSettlFlag": 0, "SettlPriceType": 6,
             "MDEntryType": 0},
        ],
    })
    m53 = encode_message(schema, 53, {
        "SecurityID": 505, "TransactTime": 0xA1A2A3A4A5A6A7A8,
        "NoMDEntries": [
            {"OrderID": 0xB1B2B3B4B5B6B7B8,
             "MDOrderPriority": 0xC1C2C3C4C5C6C7C8,
             "MDEntryPx": {"mantissa": 102_000_000_000},
             "MDDisplayQty": 61, "MDEntryType": 1},
            {"OrderID": 0xD1D2D3D4D5D6D7D8,
             "MDOrderPriority": 0xE1E2E3E4E5E6E7E8,
             "MDEntryPx": {"mantissa": -98_000_000_000},
             "MDDisplayQty": 62, "MDEntryType": 0},
        ],
    })
    return [m46, literal_template47(schema), m52, m53]


def expected_for(schema, packets):
    corpus = Corpus(schema, seed=1)
    corpus.packets = list(packets)
    return oracle_bytes(corpus)


@cocotb.test()
async def test_m3frm01_el_parser_emite_el_anexo_m_bit_a_bit_vs_el_golden(dut):
    """Espejo M3-FRM-01: secuencia de records bit a bit vs el golden."""
    corpus = build_corpus(seed=11, n_packets=24)
    dut._log.info("corpus built: %d packets", len(corpus.packets))
    expected = oracle_bytes(corpus)
    dut._log.info("oracle bytes: %d", len(expected))
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, corpus.packets)
    assert_bytes_equal(got, expected, "M3-FRM-01")
    assert errors == 0


@cocotb.test()
async def test_m3frm02_mensajes_que_cruzan_limites_de_palabra(dut):
    """Espejo M3-FRM-02: mensajes que terminan/empiezan en cualquier byte."""
    corpus = build_corpus(seed=23, n_packets=40)
    sizes = {pm.msg_size for p in corpus.packets
             for pm in iter_packet_messages(p)}
    non_aligned = [s for s in sizes if s % (len(dut.s_axis_tdata) // 8)]
    assert non_aligned, "el corpus debe tener mensajes no alineados a palabra"
    expected = oracle_bytes(corpus)
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, corpus.packets)
    assert_bytes_equal(got, expected, "M3-FRM-02")
    assert errors == 0


@cocotb.test()
async def test_m3frm03_peor_caso_a_1_palabra_por_ciclo_sin_backpressure(dut):
    """Espejo M3-FRM-03: paquete de mensajes mínimos back-to-back a 1 palabra/ciclo."""
    schema = load_schema(SCHEMA_PATH)
    corpus = Corpus(schema, seed=5)
    minimal = [literal_template47(schema) for _ in range(24)]
    packet = encode_packet(schema, 99, 1, minimal)
    corpus.packets = [packet]
    expected = oracle_bytes(corpus)
    await _reset(dut)
    got, max_stall, errors, _ = await drive_and_collect(dut, [packet])
    assert_bytes_equal(got, expected, "M3-FRM-03")
    assert errors == 0
    dut._log.info("M3-FRM-03: racha máxima de stall real = %d", max_stall)
    assert max_stall <= MAX_STALL_RUN, (
        f"backpressure sostenida: {max_stall} ciclos seguidos de entrada parada")


@cocotb.test()
async def test_m3sub01_sub02_subset_y_multi_entry_bit_a_bit(dut):
    """Espejos M3-SUB-01 y M3-SUB-02: subset, PRICE9 y multi-entry."""
    schema = load_schema(SCHEMA_PATH)
    packet = encode_packet(schema, 41, 0x1122334455667788,
                           literal_subset(schema))
    expected = expected_for(schema, [packet])
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, [packet])
    assert_bytes_equal(got, expected, "M3-SUB-01/02")
    assert errors == 0


@cocotb.test()
async def test_m3pass01_passthrough_crudo_y_schema_desconocido(dut):
    """Espejo M3-PASS-01: template normal y schema/template desconocidos."""
    schema = load_schema(SCHEMA_PATH)
    corpus = Corpus(schema, seed=73)
    packet = encode_packet(schema, 51, 2, [
        corpus.passthrough_message(unknown=False),
        corpus.passthrough_message(unknown=True),
    ])
    expected = expected_for(schema, [packet])
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, [packet])
    assert_bytes_equal(got, expected, "M3-PASS-01")
    assert errors == 0


@cocotb.test()
async def test_m3gap01_salto_y_reset_de_canal(dut):
    """Espejo M3-GAP-01: un salto pulsa gap; reset inicia otro canal."""
    schema = load_schema(SCHEMA_PATH)
    msg = literal_template47(schema)
    packets = [encode_packet(schema, seq, seq, [msg]) for seq in (100, 102)]
    await _reset(dut)
    got, _, errors, gaps = await drive_and_collect(dut, packets)
    assert_bytes_equal(got, expected_for(schema, packets), "M3-GAP-01 salto")
    assert errors == 0
    assert gaps == 1

    await _reset(dut)
    packet = encode_packet(schema, 1, 1, [msg])
    got, _, errors, gaps = await drive_and_collect(dut, [packet])
    assert_bytes_equal(got, expected_for(schema, [packet]), "M3-GAP-01 reset")
    assert errors == 0
    assert gaps == 0


@cocotb.test()
async def test_m3inv01_inv02_tamanos_invalidos_y_truncado_recuperan(dut):
    """Espejos M3-INV-01 y M3-INV-02: tamaño inválido y tlast truncado."""
    schema = load_schema(SCHEMA_PATH)
    valid_msg = literal_template47(schema)
    too_short = encode_packet(schema, 61, 1, [b"\x09\x00\x00\x00"])
    declared_too_long = encode_packet(
        schema, 62, 2, [(64).to_bytes(2, "little") + valid_msg[2:40]])
    truncated = encode_packet(schema, 63, 3, [valid_msg[:52]])
    recovery = encode_packet(schema, 64, 4, [valid_msg])

    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(
        dut, [too_short, declared_too_long, truncated, recovery])
    assert errors >= 3
    assert_bytes_equal(got, expected_for(schema, [recovery]), "M3-INV-01/02")


@cocotb.test()
async def test_m3inv03_grupo_vacio_o_entry_fuera_del_mensaje(dut):
    """Espejo M3-INV-03: grupo vacío válido; entry declarada sin bytes, error."""
    schema = load_schema(SCHEMA_PATH)
    empty = encode_message(schema, 47, {
        "TransactTime": 7, "MatchEventIndicator": 1, "NoMDEntries": []})
    malformed = bytearray(empty)
    group = schema.messages[47].groups[0]
    count_offset = (MESSAGE_PREFIX_SIZE + schema.messages[47].block_length
                    + (7 if group.dimension_type == "groupSize8Byte" else 2))
    malformed[count_offset] = 1
    bad_reference = encode_message(schema, 46, {
        "TransactTime": 8, "MatchEventIndicator": 2,
        "NoMDEntries": [{
            "MDEntryPx": {"mantissa": 100_000_000_000},
            "MDEntrySize": 3, "SecurityID": 606, "RptSeq": 9,
            "NumberOfOrders": 1, "MDPriceLevel": 1,
            "MDUpdateAction": 0, "MDEntryType": 0, "TradeableSize": 3,
        }],
        "NoOrderIDEntries": [{
            "OrderID": 10, "MDOrderPriority": 11, "MDDisplayQty": 12,
            "ReferenceID": 1, "OrderUpdateAction": 1,
        }],
    })
    packets = [encode_packet(schema, 71, 1, [empty]),
               encode_packet(schema, 72, 2, [bytes(malformed)]),
               encode_packet(schema, 73, 3, [bad_reference])]
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, packets)
    assert_bytes_equal(got, expected_for(schema, [packets[2]]), "M3-INV-03")
    assert errors >= 2


@cocotb.test()
async def test_m3frm05_tkeep_bytes_validos_y_truncado_por_mascara(dut):
    """Espejo M3-FRM-05 (addendum framing tkeep, 2026-08-18).

    a) Framing nominal: el driver aplica tkeep MSB-contiguo a todos los
       bursts, con el último beat parcial declarando solo sus bytes reales.
    b) Truncado por máscara: un mensaje cuya longitud declarada solo se
       completaría con lanes tkeep=0 no se completa (error, sin records
       parciales) y el siguiente paquete íntegro se recupera bit a bit.
    c) Beat con tkeep=0 completo en medio del burst: se consume sin aportar
       bytes y sin trabarse; el paquete llega íntegro bit a bit.
    Si el RTL aún no expone s_axis_tkeep, informa la omisión (SkipTest): el
    framing tkeep de fase 4 no está implementado.
    """
    if not hasattr(dut, "s_axis_tkeep"):
        raise cocotb.SkipTest(
            "M3-FRM-05: el RTL mdp3_parser aún no expone s_axis_tkeep "
            "(framing tkeep de fase 4 pendiente de implementar)")
    schema = load_schema(SCHEMA_PATH)
    msg = literal_template47(schema)
    packet = encode_packet(schema, 81, 1, [msg])
    b = len(dut.s_axis_tdata) // 8

    # a) nominal con tkeep correcto
    beats_a = beat_list([packet], b)
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, [packet])
    assert_bytes_equal(got, expected_for(schema, [packet]), "M3-FRM-05a")
    assert errors == 0

    # b) último beat con un lane tkeep=0: al mensaje le falta 1 byte.
    # La máscara se deriva de los bytes REALES del último beat (nv, de la
    # máscara nominal), no de b: a DW=64 el último beat del paquete suele ser
    # parcial y declarar (b-1) lanes como válidas añadiría los ceros de relleno
    # como bytes legítimos, completando falsamente la longitud declarada.
    beats_b = list(beats_a)
    nv = beats_b[-1][2].bit_count()
    beats_b[-1] = (beats_b[-1][0], True,
                   ((1 << (nv - 1)) - 1) << (b - (nv - 1)))
    recovery = encode_packet(schema, 82, 2, [msg])
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(
        dut, [packet, recovery],
        beats_override=beats_b + beat_list([recovery], b))
    assert errors >= 1, "M3-FRM-05b: faltó el error por truncado de máscara"
    assert_bytes_equal(got, expected_for(schema, [recovery]), "M3-FRM-05b")

    # c) beat vacío (tkeep=0) en medio del burst
    if len(beats_a) >= 3:
        mid = len(beats_a) // 2
        beats_c = beats_a[:mid] + [(0, False, 0)] + beats_a[mid:]
        await _reset(dut)
        got, _, errors, _ = await drive_and_collect(
            dut, [packet], beats_override=beats_c)
        assert_bytes_equal(got, expected_for(schema, [packet]), "M3-FRM-05c")
        assert errors == 0


@cocotb.test()
async def test_m3pass02_subset_con_firma_no_soportada_passthrough(dut):
    """Espejo §M3-PASS-02 (criterio 5, addendum 2026-08-19): un template del
    subset 46/47/52/53 con schema_id != 1 o version != 12 es passthrough,
    NO decode. El RTL replica la puerta en DS_HDR (d_sid==SCHEMA_ID &&
    d_ver==SCHEMA_VER); el oráculo de este test usa passthrough_record para
    los mensajes con firma no soportada (el golden decodifica por template;
    aqui el expected es explicito)."""
    schema = load_schema(SCHEMA_PATH)
    msg = literal_template47(schema)  # template 47, firma valida (id=1 ver=12)
    bad_sid = bytearray(msg)
    bad_sid[4:6] = (2).to_bytes(2, "little")       # schema_id = 2
    bad_ver = bytearray(msg)
    bad_ver[6:8] = (13).to_bytes(2, "little")      # version = 13
    packets = [
        encode_packet(schema, 90, 1, [msg]),              # firma correcta
        encode_packet(schema, 91, 2, [bytes(bad_sid)]),   # schema_id malo
        encode_packet(schema, 92, 3, [bytes(bad_ver)]),   # version mala
    ]
    # oraculo explicito: el primero se decodifica (Anexo M), los otros dos
    # van a passthrough crudo (firma no soportada por el RTL)
    expected = b""
    for p in packets:
        for pm in iter_packet_messages(p):
            if pm.template_id in SUBSET_TEMPLATES and \
                    pm.schema_id == SCHEMA_ID and pm.version == SCHEMA_VERSION:
                dec = decode_message(schema, pm)
                for rec in anexo_m_records(schema, pm, dec):
                    expected += record_bytes(rec)
            else:
                expected += record_bytes(passthrough_record(schema, pm))
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, packets)
    assert errors == 0, f"M3-PASS-02: {errors} errores espurios"
    assert len(expected) > 0, "M3-PASS-02: oráculo vacío"
    assert_bytes_equal(got, expected, "M3-PASS-02")


@cocotb.test()
async def test_m3size01_02_limite_256_acepta_257_rechaza(dut):
    """Espejo §M3-SIZE-01/02 (criterio 5): msg_size <= 256 se acepta y
    decodifica; msg_size = 257 pulsa error, sin record parcial, y el paquete
    siguiente íntegro se recupera bit a bit."""
    schema = load_schema(SCHEMA_PATH)
    msg0 = literal_template47(schema)  # layout: msg_size(2) + header SBE(8) + body
    # extender el cuerpo hasta que el mensaje completo mida 256 B, con
    # msg_size (bytes [0:2]) = 256 (incluye prefijo + header + cuerpo)
    target_size = 256
    pad = target_size - len(msg0)
    assert pad > 0, "template 47 ya excede 256 B?"
    body = bytes(msg0[10:]) + b"\x00" * pad
    msg256 = (target_size.to_bytes(2, "little") + bytes(msg0[2:10]) + body)
    assert len(msg256) == target_size, f"msg256={len(msg256)}"
    # mensaje de 257 B: msg_size = 257, cuerpo 1 byte mas largo
    body257 = body + b"\x00"
    msg257 = ((257).to_bytes(2, "little") + bytes(msg0[2:10]) + body257)
    assert len(msg257) == 257, f"msg257={len(msg257)}"
    p256 = encode_packet(schema, 95, 1, [msg256])
    p257 = encode_packet(schema, 96, 2, [msg257])
    recovery = encode_packet(schema, 97, 3, [literal_template47(schema)])
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(dut, [p256])
    assert errors == 0, f"M3-SIZE-01: {errors} errores con msg_size=256"
    assert_bytes_equal(got, expected_for(schema, [p256]), "M3-SIZE-01")
    await _reset(dut)
    got, _, errors, _ = await drive_and_collect(
        dut, [p257, recovery])
    assert errors >= 1, "M3-SIZE-02: faltó el error por msg_size=257"
    assert_bytes_equal(got, expected_for(schema, [recovery]), "M3-SIZE-02")


@cocotb.test(skip=True)
async def test_m3inv04a_mascara_con_huecos(dut):
    """Espejo M3-INV-04 (criterio 7, addendum 2026-08-19): una máscara
    tkeep con huecos (no MSB-contigua) debe pulsar error y descartar el
    paquete. LOOP ABIERTO (2026-08-19): la validación de máscara MSB-
    contigua y el descarte del paquete inválido aún no están implementados
    en el RTL; skip estático mientras el criterio 7 no se cierra."""
    schema = load_schema(SCHEMA_PATH)
    msg = literal_template47(schema)
    packet = encode_packet(schema, 81, 1, [msg])
    recovery = encode_packet(schema, 82, 2, [msg])
    b = len(dut.s_axis_tdata) // 8

    # A) máscara con huecos: sustituyo un beat NO-final (índice 1) por una
    # máscara no MSB-contigua (p. ej. 0b0110 en un byte, huecos)
    beats_ok = beat_list([packet], b)
    beats_bad = list(beats_ok)
    if len(beats_bad) > 2:
        holes_mask = (1 << (b - 1)) | (1 << (b - 4))
        beats_bad[1] = (beats_bad[1][0], False, holes_mask)
        await _reset(dut)
        dut._log.info("M3-INV-04a: holes_mask=%#x b=%d len(beats)=%d" %
                      (holes_mask, b, len(beats_bad)))
        got, _, errors, _ = await drive_and_collect(
            dut, [packet, recovery],
            beats_override=beats_bad + beat_list([recovery], b))
        assert errors >= 1, "M3-INV-04a: faltó el error por máscara con huecos"
        dut._log.info("M3-INV-04a got=%s exp=%s" % (got.hex(), expected_for(schema, [recovery]).hex()))
        assert_bytes_equal(got, expected_for(schema, [recovery]),
                           "M3-INV-04a")


@cocotb.test(skip=True)
async def test_m3inv04b_parcial_sin_tlast(dut):
    """Espejo M3-INV-04 (criterio 7): una palabra parcial sin tlast debe
    pulsar error. LOOP ABIERTO (2026-08-19): ibidem 04a — la validación de
    máscara y el descarte no están implementados; skip estático."""
    schema = load_schema(SCHEMA_PATH)
    msg = literal_template47(schema)
    packet = encode_packet(schema, 81, 1, [msg])
    recovery = encode_packet(schema, 82, 2, [msg])
    b = len(dut.s_axis_tdata) // 8
    beats_ok = beat_list([packet], b)
    beats_part = list(beats_ok)
    if len(beats_part) > 2:
        part_mask = ((1 << (b - 2)) - 1) << 2   # MSB-contigua, b-2 bytes
        beats_part[1] = (beats_part[1][0], False, part_mask)
        await _reset(dut)
        got, _, errors, _ = await drive_and_collect(
            dut, [packet, recovery],
            beats_override=beats_part + beat_list([recovery], b))
        assert errors >= 1, "M3-INV-04b: faltó el error por parcial sin tlast"
        assert_bytes_equal(got, expected_for(schema, [recovery]),
                           "M3-INV-04b")
