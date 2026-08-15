"""Testbench cocotb del parser ITCH (fase 1) — área verification/testbenches/parser.

Conduce el payload MoldUDP64 (post-decap IP/UDP) al top `itch_parser` palabra a
palabra (s_axis) y recolecta la salida AXI-Stream (m_axis) reconstruyendo cada
registro del Anexo A (burst delimitado por tlast). Compara byte a byte contra el
oráculo `golden_model.src.message_oracle.iter_message_records`.

Vectores sintéticos (regla G0). Comparación byte a byte (gate G3).
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
# oráculo: palabras de salida esperadas (flat) para `messages`
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
    """Oráculo multi-paquete: msg_idx GLOBAL (0,1,2,...) a través de todos los
    datagramas. El RTL incrementa msg_idx por registro emitido sin reiniciar
    entre paquetes; el oráculo debe hacer lo mismo."""
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
        assert payload, "un datagrama no puede carecer de beat final"
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
            "AXI de entrada cambió antes de liberar el backpressure: "
            f"{held} -> {beat}")
    if valid and not ready:
        return beat, 0
    if valid and ready:
        return None, int(dut.s_axis_tlast.value)
    return None, 0


# ---------------------------------------------------------------------------
# constructores de mensajes sintéticos (literales desde la spec del PDF)
# ---------------------------------------------------------------------------
def _mk(t, locate, ts, body):
    return (t + struct.pack(">H", locate) + b"\x00\x00" +
            int.to_bytes(ts, 6, "big") + body)


def S(locate, ts, event):
    return _mk(b"S", locate, ts, bytes([event]))


def R(locate, ts):
    # 39 B: stock(8) mcat(1) fin(1) round(4) rlo(1) ic(1) isub(2) auth(1)
    #        sst(1) ipo(1) luld(1) etp(1) lev(4) inv(1) = 28 B de cuerpo
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
    # 44 B: ref(8) side(1) shares(4) stock(8) price(4) match(8) = 33 de cuerpo
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
    """Conduce un paquete y devuelve las palabras de salida (burst AXI-Stream).

    La salida se lee en la fase ReadOnly (post-flanco de subida) para obtener
    valores registrados estables. Programa la entrada en la fase de escritura
    (antes del RisingEdge) y sigue hasta drenar la entrada más una ventana de
    silencio.
    """
    await _reset(dut)
    payload = _packet(messages)
    beats = packet_beats([payload], 8)

    out = []
    ci = 0          # siguiente chunk de entrada a presentar
    quiet = 0       # ciclos SIN salida tras agotar la entrada (ventana de drenaje)
    held = None
    accepted_tlast = 0
    for _ in range(max_cycles):
        # presentar la palabra del ciclo actual (handshake: tready combinacional
        # del RTL cierra el transfer en el MISMO flanco).
        _present_beat(dut, beats, ci)
        if not tready_high:
            dut.m_axis_tready.value = 1 if (_ % 3) != 1 else 0
        await RisingEdge(dut.clk)
        # si en este flanco hubo transferencia (tvalid y tready altos),
        # avanzar al siguiente chunk
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        # recolectar salida; ventana de cierre tras agotar la entrada
        if int(dut.m_axis_tvalid.value) == 1:
            out.append(int(dut.m_axis_tdata.value))
            quiet = 0
        elif ci >= len(beats):
            quiet += 1
        if quiet > 64:
            break
    assert accepted_tlast == 1, f"se aceptaron {accepted_tlast} tlast, esperado 1"
    return out


@cocotb.test()
async def test_par01_all_types_match_oracle(dut):
    """Espejo §PAR-01: cada tipo del subset -> registro byte a byte como el oráculo."""
    await _reset(dut)
    msgs = corpus_all_types()
    expected = run_oracle(msgs)
    got = await drive_and_collect(dut, msgs)
    assert got == expected, (
        f"Desajuste.\n got({len(got)}): {got}\nexp({len(expected)}): {expected}")


@cocotb.test()
async def test_sec_par04_no_subset_no_register(dut):
    """Espejo §SEC-PAR-04: H válido avanza msg_idx sin emitir registro."""
    a0 = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    h = H(13, 3)
    a2 = A(13, 4, 8, b"\x00", 11, b"AAPL    ", 4)
    msgs = [a0, h, a2]
    payload = _packet_seq(msgs, 1)
    got, errores, _ = await drive_packets_err(dut, [payload])
    expected = run_oracle(msgs)
    assert errores == 0, f"SEC-PAR-04: H canónico produjo {errores} errores"
    assert got == expected, f"got={got} exp={expected}"

# ---------------------------------------------------------------------------
# driver flexible: feed crudo (payload + seq) con opts de backpressure y
# conteo de stalls de entrada. Devuelve (out_words, stalls_in, accepted_ci).
# ---------------------------------------------------------------------------
async def drive_raw(dut, payload, seq=1, out_tready=(1,), max_cycles=30000):
    """Conduce un payload (session+seq+count+msgs) y devuelve (words, stalls)."""
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
    assert accepted_tlast == 1, f"se aceptaron {accepted_tlast} tlast, esperado 1"
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
    """Conduce cada datagrama como burst AXI independiente y cuenta gaps."""
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
        f"se aceptaron {accepted_tlast} tlast, esperado {len(packets)}")
    return out, gaps


# ---------------------------------------------------------------------------
# LIN-01: cuatro mensajes A/U back-to-back -> stalls acotados con tready alto
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_lin01_back_to_back_min_no_stall(dut):
    """Espejo §LIN-01: cuatro mensajes A/U back-to-back -> stalls acotados.

    El tramo cabe en la cola (amortiguamiento del diseño de captura a
    msg_reg): el parser no deja meter atrás mientras el downstream consume.
    El requisito de feed back-to-back INFINITO (sería exigir la cola
    infinita o un aligner con drenaje en emisión) queda documentado como
    pendiente en spec/fase1 (ver spec.md: LIN-01 alcance).

    Iteración 6 (2026-08-14): QB 128->64 recorta el backlog estacionario de
    la cola (~2,7x de latencia wire->BBO); el tramo probado pasa de 0 a
    stalls ACOTADOS (~15 en 4 mensajes A/U): "sin backpressure sostenida"
    del régimen de fase 1. El límite caza regresiones groseras (p. ej. un
    drenaje roto); la corrección bit a bit se valida abajo."""
    # Tramo literal A/U pactado. El peor caso de mensajes mínimos back-to-back
    # infinito queda como non-goal físico en la spec; este test mide el régimen
    # real de QB=64 y no afirma cero stalls.
    msgs = [A(13, i + 10, i, b"\x01", 1000, b"AAPL    ", 1000 + i) if i % 2 == 0
            else U(13, i + 10, i, i + 1, 200, 1100 + i)
            for i in range(4)]
    payload = _packet_seq(msgs, 1)
    words, stalls = await drive_raw(dut, payload, out_tready=(1,))
    expected = run_oracle(msgs)
    assert words == expected, f"LIN words mismatch: {len(words)} vs {len(expected)}"
    assert stalls <= 24, (
        f"LIN: {stalls} stalls con downstream consumiendo (acotados <= 24, "
        f"QB=64, iter 6)")


# ---------------------------------------------------------------------------
# ALN-01: un mensaje que cruza palabra con cualquier desplazamiento inicial
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_aln01_message_not_word_aligned(dut):
    """Espejo §ALN-01: A se decodifica en los ocho offsets de la word."""
    a = A(393, 1_000_000_002, 0x1122334455667788, b"\x01", 1000, b"AMZN    ", 1_234_567)
    # Offset del type A = (header 20 + frames previos + len A 2) mod 8.
    # Estos prefijos canónicos no-subset producen exactamente las ocho fases.
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
    """Espejo §FRM-01+02: seq consecutivas sin hueco -> sin gap_detected."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    payload = _packet_seq(msgs, 1)
    await _reset(dut)
    _, _ = await drive_raw(dut, payload)
    # tras el feed el parser reporta gap si hubo hueco; con seq=1 continua no hay
    # gap_detected (pulso) no se ve post-hoc: comprobamos solo funcionalidad salida
    words, _ = await drive_raw(dut, payload)
    assert words == run_oracle(msgs), "FRM seq ok"


# ---------------------------------------------------------------------------
# OUT-02/03: backpressure de salida (tready intermitente) sin pérdida
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_out02_backpressure_salida_sin_perdida(dut):
    """Espejo §OUT-02: con tready bajo el parser retiene el stream sin pérdida ni duplicado."""
    msgs = corpus_all_types()
    payload = _packet_seq(msgs, 1)
    words, _ = await drive_raw(dut, payload, out_tready=(1, 1, 0))
    expected = run_oracle(msgs)
    assert words == expected, (
        f"OUT-02: got({len(words)}) exp({len(expected)})\n"
        f" got={words}\n exp={expected}")


@cocotb.test()
async def test_out03_handshake_tvalid_tready(dut):
    """Espejo §OUT-03: el handshake tvalid/tready solo avanza cuando ambos están altos."""
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
            # OUT-03: los datos NO cambian mientras tvalid alto y tready bajo
            if tvalid_high:
                assert last_tdata_while_stalled is None or td == last_tdata_while_stalled, (
                    f"OUT-03: tdata cambió con tvalid alto y tready bajo: "
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
    assert accepted_tlast == 1, f"se aceptaron {accepted_tlast} tlast, esperado 1"

@cocotb.test()
async def test_sec_gap01_seq_gap_detectado(dut):
    """Espejo §SEC-GAP-01: un hueco de secuencia se señaliza, se cuenta y el parsing continúa."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # paquete1 seq=1 (esperado), paquete2 seq=3 -> hueco (2 saltado), continúa
    p1 = _packet_seq(msgs, 1)
    p2 = _packet_seq(msgs, 3)
    out, gaps = await drive_packets(dut, [p1, p2], expect_gap=1)
    exp = run_oracle_packets([(1, msgs, p1), (3, msgs, p2)])
    assert gaps == 1, f"SEC-GAP-01: se esperaba 1 gap, vistos {gaps}"
    assert out == exp, f"SEC-GAP-01: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_gap02_seq_igual_no_gap(dut):
    """Espejo §SEC-GAP-02: un seq igual al esperado no señaliza gap."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # paquete1 seq=1 (1 msg), paquete2 seq=2 (esperado) -> sin gap
    p1 = _packet_seq(msgs, 1)
    p2 = _packet_seq(msgs, 2)
    out, gaps = await drive_packets(dut, [p1, p2], expect_gap=0)
    exp = run_oracle_packets([(1, msgs, p1), (2, msgs, p2)])
    assert out == exp, f"SEC-GAP-02: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm03_cambio_sesion_resetea_seq(dut):
    """Espejo §SEC-FRM-03: un cambio de sesión resetea el seq esperado."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # sesión A seq=100, luego sesión B seq=7 (no es 101 -> sin gap por cambio sesión)
    pA = _packet_session(b"SESSIONAAA", 100, msgs)
    pB = _packet_session(b"SESSIONBBB", 7, msgs)
    out, gaps = await drive_packets(dut, [pA, pB], expect_gap=0)
    exp = run_oracle_packets([(100, msgs, pA), (7, msgs, pB)])
    assert gaps == 0, f"SEC-FRM-03: cambio de sesión NO debe marcar gap, vistos {gaps}"
    assert out == exp, f"SEC-FRM-03: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm04_count_cero_valido(dut):
    """Espejo §SEC-FRM-04: un paquete con count igual a cero es válido."""
    msgs = [A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)]
    # La sesión nueva fuerza exp_seq=100; count=0 debe conservar ese 100.
    p0 = _packet_session(b"SESSIONBBB", 100, [])
    p1 = _packet_session(b"SESSIONBBB", 100, msgs)
    out, gaps = await drive_packets(dut, [p0, p1], expect_gap=0)
    exp = run_oracle_packets([(100, [], p0), (100, msgs, p1)])
    assert gaps == 0, f"SEC-FRM-04: count=0 no debe marcar gap, vistos {gaps}"
    assert out == exp, f"SEC-FRM-04: got {len(out)} exp {len(exp)}"


@cocotb.test()
async def test_sec_frm05_datagramas_no_alineados_no_comparten_beat(dut):
    """Espejo §SEC-FRM-05: el padding final no invade el header siguiente.

    Mata la mutación de producción que concatena datagramas antes de formar
    beats y usa bytes de relleno como si fueran el comienzo del siguiente
    header MoldUDP64.
    """
    a = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    b = A(14, 3, 8, b"\x00", 11, b"MSFT    ", 4)
    p1 = _packet_seq([a], 1)
    p2 = _packet_seq([b], 2)
    assert len(p1) % 8 != 0 and len(p2) % 8 != 0
    got, errores, accepted_tlast = await drive_packets_err(dut, [p1, p2])
    expected = run_oracle_packets([(1, [a], p1), (2, [b], p2)])
    assert errores == 0, f"SEC-FRM-05: errores inesperados: {errores}"
    assert accepted_tlast == 2, f"SEC-FRM-05: tlast aceptados {accepted_tlast}"
    assert got == expected, f"SEC-FRM-05: got={got} exp={expected}"


@cocotb.test()
async def test_sec_frm04_count_cero_parcial_msb_y_recuperacion(dut):
    """Espejo §SEC-FRM-04: count=0 de 20 B termina con keep=11110000.

    Mata la mutación que interpreta los cuatro lanes de relleno como payload o
    que deja estado de count=0 contaminando el datagrama posterior.
    """
    p0 = _packet_session(b"SIM0000001", 1, [])
    valid = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    p1 = _packet_session(b"SIM0000001", 1, [valid])
    assert len(p0) == 20
    assert packet_beats([p0], 8)[-1][1:] == (0b11110000, True)
    got, errores, accepted_tlast = await drive_packets_err(dut, [p0, p1])
    assert errores == 0, f"SEC-FRM-04: errores inesperados: {errores}"
    assert accepted_tlast == 2, f"SEC-FRM-04: tlast aceptados {accepted_tlast}"
    assert got == run_oracle([valid]), f"SEC-FRM-04: got={got}"


@cocotb.test()
async def test_sec_frm02_campo_len_final_conserva_eop_y_recupera(dut):
    """Un tlast aceptado con solo el campo len no se pierde al drenar HDR."""
    partial = struct.pack(">10sQH", b"SIM0000001", 1, 1) + (36).to_bytes(2, "big")
    recovery = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    recovered = _packet_session(b"SIM0000002", 100, [recovery])
    assert len(partial) == 22

    got, errors, accepted_tlast = await drive_packets_err(
        dut, [partial, recovered])

    assert errors == 1, f"SEC-FRM-02 len final: errores={errors}"
    assert accepted_tlast == 2, (
        f"SEC-FRM-02 len final: tlast aceptados={accepted_tlast}")
    assert got == run_oracle([recovery]), (
        f"SEC-FRM-02 len final: got={got}")


@cocotb.test()
async def test_sec_frm07_count_tlast_cierre_exacto(dut):
    """Espejo §SEC-FRM-07: count y tlast cierran el mismo datagrama.

    Mata las mutaciones que aceptan bytes residuales, permiten cierre antes de
    count o reinterpretan un residuo como header del siguiente paquete.
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
            f"SEC-FRM-07 {name}: tlast aceptados {accepted_tlast}")
        assert got == expected, f"SEC-FRM-07 {name}: got={got} exp={expected}"


@cocotb.test()
async def test_sec_frm06_tkeep_invalido_descarta_y_recupera(dut):
    """Espejo §SEC-FRM-06: tkeep inválido da un pulso y drena hasta tlast.

    Mata las mutaciones que aceptan lane cero, huecos, orientación LSB o un
    parcial fuera del beat final.
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
            f"SEC-FRM-06 {name}: tlast aceptados {accepted_tlast}")
        assert got == run_oracle([recovery]), f"SEC-FRM-06 {name}: got={got}"


@cocotb.test()
async def test_sec_frm06_registro_capturado_termina_antes_de_recuperar(dut):
    """Un descarte termina el record capturado antes de recuperar el siguiente."""
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
        out_beat = (int(dut.m_axis_tdata.value), int(dut.m_axis_tlast.value))
        if held_out is not None:
            assert out_beat == held_out, (
                f"SEC-FRM-06 salida cambió bajo stall: {held_out} -> {out_beat}")
        if out_valid and not out_ready:
            held_out = out_beat
        elif out_valid and out_ready:
            out.append(out_beat)
            held_out = None

        if int(dut.s_axis_tvalid.value) and int(dut.s_axis_tready.value):
            ci += 1
        if ci >= len(beats) and not out_valid:
            quiet += 1
        else:
            quiet = 0
        if quiet > 80:
            break

    assert errors == 1, f"SEC-FRM-06 salida pendiente: errores={errors}"
    assert accepted_tlast == 2, (
        f"SEC-FRM-06 salida pendiente: tlast aceptados={accepted_tlast}")
    expected_words = run_oracle([first, recovery])
    assert [word for word, _last in out] == expected_words, (
        f"SEC-FRM-06 records incompletos o duplicados: got={out}")
    first_words = len(run_oracle([first]))
    expected_last = [
        int(index in (first_words - 1, len(expected_words) - 1))
        for index in range(len(expected_words))
    ]
    assert [last for _word, last in out] == expected_last, (
        f"SEC-FRM-06 límites de record incorrectos: got={out}")
    assert out[first_words][0] & 0xFFFFFFFF == 1, (
        f"SEC-FRM-06 msg_idx de recuperación={out[first_words][0] & 0xFFFFFFFF}")


@cocotb.test()
async def test_sec_frm06_tkeep_invalido_no_depende_de_capacidad(dut):
    """El primer beat inválido se acepta aunque su popcount no quepa en q."""
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
        f"SEC-FRM-06 no se alcanzó presión de capacidad: qn={qn_before}")
    assert ci < len(beats) and not beats[ci][2], (
        "SEC-FRM-06 el setup agotó el datagrama antes del beat inválido")

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
        f"SEC-FRM-06 beat inválido bloqueado con qn={qn_before}")
    assert errors == 1, f"SEC-FRM-06 errores del bypass={errors}"


@cocotb.test()
async def test_sec_frm08_fuente_estable_bajo_backpressure_entrada(dut):
    """Espejo §SEC-FRM-08: el productor retiene data, keep y last en stall.

    Mata una mutación RTL que mantiene s_axis_tready alto cuando la cola no
    puede aceptar, perdiendo o duplicando beats bajo presión. El monitor del
    feeder verifica por separado que la fuente de prueba no cambie la terna
    antes de handshake; no atribuye ese fallo de estímulo al RTL.
    """
    messages = corpus_all_types() * 3
    words, stalls = await drive_raw(
        dut, _packet_seq(messages, 1), out_tready=(0, 0, 1))
    assert stalls > 0, "SEC-FRM-08 no forzó s_axis_tready bajo"
    assert words == run_oracle(messages), "SEC-FRM-08: pérdida bajo backpressure"


@cocotb.test()
async def test_axi_keep_orientacion_msb_lsb(dut):
    """El prefijo MSB es válido; la máscara equivalente en LSB se rechaza.

    Mata la mutación de interpretación little-endian de s_axis_tkeep.
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
    """Espejo §SEC-PAR-03: longitud declarada incoherente -> error señalizado."""
    await _reset(dut)
    bad = b"A" + b"\x00" * 34   # 'A' de 35 B (spec exige 36)
    ok = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    payload = _packet_seq([bad, ok], 1)
    words, _ = await drive_raw(dut, payload)
    # el 'A' incoherente (35 B, spec 36) NO emite registro pero se cuenta
    # (msg_idx global avanza a 1); el 'A' válido sí se emite con msg_idx=1.
    expected = run_oracle([ok])
    expected[0] = expected[0] + 1   # msg_idx=1 por el desecho del bad
    assert words == expected, f"SEC-PAR-03: got {len(words)} exp {len(expected)}"


@cocotb.test()
async def test_sec_par05_las_22_longitudes_conocidas_se_validan(dut):
    """Espejo §SEC-PAR-05: todo tipo conocido con longitud errónea da error."""
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
        f"SEC-PAR-05: {errores} errores para {len(MESSAGE_LENGTHS)} longitudes inválidas")
    assert words == expected, "SEC-PAR-05: no recuperó el A posterior"


# ---------------------------------------------------------------------------
# OUT-01: burst AXI-Stream con tlast en la última palabra de cada registro
# ---------------------------------------------------------------------------
def _bursts_from_words(words_with_tlast):
    """Reconstruye bursts (lista de words) a partir de (word, tlast)."""
    bursts = []
    cur = []
    for w, last in words_with_tlast:
        cur.append(w)
        if last:
            bursts.append(cur)
            cur = []
    return bursts


async def drive_bursts(dut, payload):
    """Devuelve (bursts, words_con_tlast) reconstruyendo registros por tlast."""
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
        elif ci >= len(beats):
            quiet += 1
        held, took_last = _check_input_stability(dut, held)
        accepted_tlast += took_last
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < len(beats):
                ci += 1
        if quiet > 80:
            break
    assert accepted_tlast == 1, f"se aceptaron {accepted_tlast} tlast, esperado 1"
    return bursts, tagged


@cocotb.test()
async def test_out01_burst_con_tlast(dut):
    """Espejo §OUT-01: cada mensaje se emite como un burst con tlast al final."""
    msgs = corpus_all_types()
    payload = _packet_seq(msgs, 1)
    bursts, tagged = await drive_bursts(dut, payload)
    flat = [w for b in bursts for w in b]
    exp = run_oracle(msgs)
    assert flat == exp, f"OUT-01 flat: got {len(flat)} exp {len(exp)}"
    # número de bursts == número de mensajes del subset del corpus (10)
    assert len(bursts) == len(corpus_all_types()), (
        f"OUT-01: {len(bursts)} bursts, esperado {len(corpus_all_types())}")
    # tlast solo en la última palabra de cada burst
    for tag in tagged:
        assert len([w for (w, l) in tagged if l]) == len(bursts), "OUT-01: tlast por burst"


# ---------------------------------------------------------------------------
# SEC-FRM-01: frame truncado -> error, se continúa en el siguiente mensaje
# ---------------------------------------------------------------------------
async def drive_packets_err(dut, packets, out_tready=(1,), max_cycles=200000,
                            window=200, beats=None):
    """Conduce `packets` muestreando `error` en vivo.

    Devuelve (out_words, errores). `beats` permite inyectar una máscara AXI
    malformada sin derivar el oráculo del RTL.
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
# SEC-FRM-01/02: frame truncado / tlast en medio -> error sin cuelgue
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_frm01_frame_truncado(dut):
    """Espejo §SEC-FRM-01: un frame truncado señaliza error y continúa."""
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
            f"SEC-FRM-01 missing={missing}: esperaba un error, vistos {errores}")
        assert accepted_tlast == 2, (
            f"SEC-FRM-01 missing={missing}: tlast aceptados {accepted_tlast}")
        exp = run_oracle([ok, next_ok])
        assert words == exp, (
            f"SEC-FRM-01 missing={missing}: got({len(words)}) exp({len(exp)})")


@cocotb.test()
async def test_sec_frm02_tlast_en_medio(dut):
    """Espejo §SEC-FRM-02: tlast en medio de un mensaje -> error, sin registro parcial."""
    ok = A(13, 2, 7, b"\x01", 10, b"AAPL    ", 3)
    full = struct.pack(">10sQH", b"SIM0000001", 1, 1) + len(ok).to_bytes(2, "big") + ok
    mid = len(full) // 2
    truncated = full[:mid]   # el feed termina a mitad del 'A' (tlast a mitad)
    words, errores, accepted_tlast = await drive_packets_err(dut, [truncated])
    assert errores > 0, f"SEC-FRM-02: mensaje cortado a mitad debe señalar error, vistos {errores}"
    assert words == [], f"SEC-FRM-02: no debe emitir registro parcial, got {words}"
    assert accepted_tlast == 1, f"SEC-FRM-02: tlast aceptados {accepted_tlast}"


# ---------------------------------------------------------------------------
# SEC-LIN-01: tipos fuera de subset no rompen el line rate
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_lin01_no_subset_no_rompe_line_rate(dut):
    """Espejo §SEC-LIN-01: mensajes fuera de subset no rompen el line rate."""
    msgs = [A(13, 1, 6, b"\x01", 9, b"AAPL    ", 2),
            H(13, 2),
            A(13, 3, 7, b"\x00", 10, b"AAPL    ", 3)]
    payload = _packet_seq(msgs, 1)
    words, stalls = await drive_raw(dut, payload, out_tready=(1,))
    assert stalls <= 24, f"SEC-LIN-01: {stalls} stalls con downstream consumiendo"
    assert words == run_oracle(msgs), "SEC-LIN-01: salida correcta"


# ---------------------------------------------------------------------------
# REP-01: vector congelado de mensajes -> reproducción byte a byte
# ---------------------------------------------------------------------------
def _load_frozen_messages(path):
    """Carga un vector congelado (messages_hex) desde verification/vectors/."""
    import json
    with open(path) as f:
        data = json.load(f)
    return [bytes.fromhex(h) for h in data["messages_hex"]], data


@cocotb.test()
async def test_rep01_vectores_congelados_byte_a_byte(dut):
    """Espejo §REP-01: el RTL reproduce los vectores congelados byte a byte."""
    here = os.path.dirname(os.path.abspath(__file__))
    vec = os.path.join(here, "..", "..", "vectors", "messages", "corpus_all_types.json")
    msgs, meta = _load_frozen_messages(vec)
    # el oráculo re-decodifica el propio stream congelado (independiente del RTL)
    expected = run_oracle(msgs)
    payload = _packet_seq(msgs, 1)
    words, _ = await drive_raw(dut, payload, out_tready=(1,))
    assert words == expected, (
        f"REP-01 ({meta['name']}): got({len(words)}) exp({len(expected)})")
    # msg_idx global arranca en 0 y coincide con el oráculo
    assert words[0] & 0xFFFFFFFF == 0, "REP-01: msg_idx del primer registro == 0"


# ---------------------------------------------------------------------------
# REP-02: replay de un pcap real (día local) contra el oráculo --emit-messages
# ---------------------------------------------------------------------------
async def drive_pcap(dut, pcap_path, max_cycles=2_000_000):
    """Hace decap del pcap (Ethernet/IPv4/UDP -> payload MoldUDP64), lo
    alimenta al RTL y recolecta las words de salida. El parser puede retener
    el feed (backpressure correcto AXI) pero jamás pierde; se espera hasta que
    la cola drene por completo."""
    from scripts.binaryfile_to_pcap import iter_pcap_packets

    packets = list(iter_pcap_packets(pcap_path))
    payloads = [payload for _seq, _msgs, payload in packets]
    orac_packets = [(seq, msgs, payload) for seq, msgs, payload in packets]
    assert packets, "REP-02: pcap existente sin datagramas MoldUDP64"
    assert payloads and all(payloads), (
        "REP-02: pcap existente sin payload MoldUDP64 no vacío")

    await _reset(dut)
    beats = packet_beats(payloads, 8)
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
        # drenaje completo: feed consumido y cola vacía (sin salida tras 8000 ciclos)
        if quiet > 8000:
            break
    exp = []
    for w0, ts, body in message_oracle.iter_message_records(orac_packets):
        exp.append(w0)
        exp.append(ts)
        for i in range(0, len(body), 8):
            exp.append(int.from_bytes(body[i:i + 8], "big") << (8 * (8 - len(body[i:i + 8]))))
    assert exp, "REP-02: pcap sin salida esperada del subset ITCH"
    assert accepted_tlast == len(payloads), (
        f"REP-02: tlast aceptados {accepted_tlast}, esperado {len(payloads)}")
    return out, exp, len(packets)


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_rep02_replay_pcap_real_dia_local(dut):
    """Espejo §REP-02: el RTL sobre un pcap del día real coincide byte a byte.
    (pcap local no commiteado; el decorador declara la omisión si no existe)."""
    out, exp, npack = await drive_pcap(dut, REAL_PCAP)
    assert out == exp, (
        f"REP-02: got({len(out)}) exp({len(exp)}) sobre {npack} paquetes:\n"
        f" got={out}\n exp={exp}")
    cocotb.log.info(f"REP-02 OK: {npack} paquetes, {len(out)} words byte a byte")


# ---------------------------------------------------------------------------
# SEC-PAR-03b: longitud declarada == 11 (borde) NO marca error
#   Mata al mutante LEN-CAPT-ERR (flip < 11 -> <= 11).
# ---------------------------------------------------------------------------
async def drive_and_sample_error(dut, payload, max_cycles=20000):
    """Conduce un payload muestreando el pulso `error` en vivo."""
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
        # ventana de drenaje: 16 ciclos tras consumir la entrada y sin salida
        if quiet > 16:
            break
    assert accepted_tlast == 1, f"se aceptaron {accepted_tlast} tlast, esperado 1"
    return errores


@cocotb.test()
async def test_sec_par03b_len_igual_once_no_error(dut):
    """Espejo §SEC-PAR-03 (borde): longitud declarada == 11 NO señaliza error.
    len mínima válida de un mensaje ITCH es 11 (solo cabecera común sin cuerpo).
    Un tipo desconocido se consume como passthrough; un tipo canónico conserva
    su longitud exacta. Un mutante con `<=` marcaría este borde erróneamente."""
    # Tipo desconocido de exactamente 11 B (cabecera común, sin cuerpo).
    m = b"Z" + bytes([0]) * 10
    assert len(m) == 11
    payload = _packet_seq([m], 1)
    errores = await drive_and_sample_error(dut, payload)
    assert errores == 0, f"SEC-PAR-03b: len==11 NO debe marcar error, vistos {errores}"
