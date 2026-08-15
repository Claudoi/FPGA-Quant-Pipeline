"""Testbench cocotb del order book (fase 2) — área verification/testbenches/orderbook.

Alimenta el top `orderbook` con el registro del Anexo A (word0 de contexto,
word1 ts, words 2..N cuerpo big-endian) que emite el parser de fase 1, y
compara el BBO emitido **bit a bit** contra el oráculo
`golden_model.src.book.Book` (semántica de fase 0, validada contra día real).

Vectores sintéticos (regla G0) y replay del día local (no commiteado).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import struct
import os

from golden_model.src import book as book_golden
from golden_model.src import message_oracle

REAL_PCAP = "/tmp/real_trading.pcap"


# ---------------------------------------------------------------------------
# construcción de mensajes ITCH (literales desde el PDF / messages.py)
# ---------------------------------------------------------------------------
def _mk(t, locate, ts, body):
    return (t + struct.pack(">H", locate) + b"\x00\x00" +
            int.to_bytes(ts, 6, "big") + body)


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


def S(locate, ts, event):
    return _mk(b"S", locate, ts, bytes([event]))


def H(locate, ts, state):
    return _mk(b"H", locate, ts, b"AMZN    " + bytes([state]) + b"\x00" * 5)


# ---------------------------------------------------------------------------
# oráculo: feed Anexo A + BBO esperado del golden
# ---------------------------------------------------------------------------
def iter_records(messages, start_idx=0):
    """Recorre mensajes crudos y emite registros Anexo A (igual que el parser).
    Devuelve (msg_type, locate, body, msg_idx)."""
    idx = start_idx
    for raw in messages:
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        yield mtype, locate, body, idx
        idx += 1


def run_book(messages):
    """Oráculo: aplica los mensajes con book.py y devuelve eventos BBO.
    Evento: (locate, (bid_px, bid_qty, ask_px, ask_qty), changed)."""
    bk = book_golden.Book()
    events = []
    for idx, raw in enumerate(messages):
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        # reconstruir los fields que book.py espera (mismo parseo de fase 0)
        fields = _fields_from_body(mtype, body)
        msg = (idx, mtype, locate, 0, 0, fields)
        ev = bk.apply(msg)
        if ev is not None:
            events.append(ev)
    return events, bk


def run_book_depth(messages, nd=5):
    """Oráculo top-N (fase 3, criterio 6): por cada evento BBO captura los ND
    mejores niveles por lado del símbolo del evento, best-first (bid por precio
    descendente, ask ascendente), rellenando con (0, 0) hasta ND.

    Devuelve (bbo_events, depth_events, book) con cada depth_event =
    (locate, bid_levels, ask_levels); bid_levels[i]/ask_levels[i] = (px, qty).
    Los niveles se derivan SIEMPRE de _levels del golden, nunca del RTL."""
    bk = book_golden.Book()
    events = []
    depth = []
    for idx, raw in enumerate(messages):
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        fields = _fields_from_body(mtype, body)
        ev = bk.apply((idx, mtype, locate, 0, 0, fields))
        if ev is not None:
            events.append(ev)
            bid = sorted(bk._levels.get((locate, book_golden.BID), {}).items(), reverse=True)
            ask = sorted(bk._levels.get((locate, book_golden.ASK), {}).items())
            bid = (list(bid) + [(0, 0)] * nd)[:nd]
            ask = (list(ask) + [(0, 0)] * nd)[:nd]
            depth.append((locate, bid, ask))
    return events, depth, bk


def pack_depth(bid, ask):
    """Empaqueta (bid best-first, ask best-first) en el word de 2*ND*64 bits
    del bus depth_tdata: {mejor_bid, ..., 5º_bid, mejor_ask, ..., 5º_ask} de
    MSB a LSB, cada nivel {px[31:0], qty[31:0]}, vacíos a 0."""
    w = 0
    for px, qty in list(bid) + list(ask):
        w = (w << 64) | ((px & 0xFFFFFFFF) << 32) | (qty & 0xFFFFFFFF)
    return w


def _fields_from_body(mtype, body):
    """Extrae la tupla de campos que book.py consume (campos del struct)."""
    if mtype == "S":
        return (chr(body[0]),)  # el golden compara contra "Q"/"M" (str)
    if mtype == "H":
        return (body[0:8], chr(body[8]))  # stock, trading_state ("T" = continuo)
    if mtype in ("A", "F"):
        ref = int.from_bytes(body[0:8], "big")
        side = chr(body[8])
        shares = int.from_bytes(body[9:13], "big")
        stock = body[13:21]
        price = int.from_bytes(body[21:25], "big")
        if mtype == "A":
            return (ref, side, shares, stock, price)
        return (ref, side, shares, stock, price, body[25:29])
    if mtype in ("E", "C"):
        ref = int.from_bytes(body[0:8], "big")
        exsh = int.from_bytes(body[8:12], "big")
        match = int.from_bytes(body[12:20], "big")
        if mtype == "E":
            return (ref, exsh, match)
        printable = chr(body[20])
        price = int.from_bytes(body[21:25], "big")
        return (ref, exsh, match, printable, price)
    if mtype == "X":
        return (int.from_bytes(body[0:8], "big"), int.from_bytes(body[8:12], "big"))
    if mtype == "D":
        return (int.from_bytes(body[0:8], "big"),)
    if mtype == "U":
        return (int.from_bytes(body[0:8], "big"), int.from_bytes(body[8:16], "big"),
                int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big"))
    return None


# ---------------------------------------------------------------------------
# driver: Anexo A -> top orderbook, recolectar BBO
# ---------------------------------------------------------------------------
async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


def anexo_words(messages):
    """Convierte mensajes a words del Anexo A (w0 contexto, ts, body) flat."""
    words = []
    for mtype, locate, body, idx in iter_records(messages):
        w0 = (ord(mtype) << 56) | (locate << 40) | ((11 + len(body)) << 32) | (idx & 0xFFFFFFFF)
        words.append(w0)
        ts = int.from_bytes(b"", "big") if False else 0  # ts no es usado por el book
        words.append(ts)
        for i in range(0, len(body), 8):
            bite = body[i:i + 8]
            words.append(int.from_bytes(bite, "big") << (8 * (8 - len(bite))))
    return words


async def drive_and_collect_bbo(dut, messages, max_cycles=200000):
    """Conduce los Anexo A (words) y recolecta eventos BBO del top.

    Devuelve (bbo_events, cross_count, anomaly_count, error_cycles).
    bbo_events es lista de (locate, (bid_px,bid_qty,ask_px,ask_qty), changed).
    """
    await _reset(dut)
    words = anexo_words(messages)
    # chunks de 64 bits, tlast al final de cada registro (burst)
    ci = 0
    n = len(words)
    out = []
    quiet = 0
    cross = 0
    anomaly = 0
    error_cycles = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        # tlast: cada burst de mensaje termina según su longitud; simplificamos
        # a un burst único para el feed completo (el book no usa tlast por msg)
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            # bbo_tdata[127:0] = {bid_px, bid_qty, ask_px, ask_qty} (4×32)
            bid_px = (td >> 96) & 0xFFFFFFFF
            bid_qty = (td >> 64) & 0xFFFFFFFF
            ask_px = (td >> 32) & 0xFFFFFFFF
            ask_qty = td & 0xFFFFFFFF
            out.append((loc, (bid_px, bid_qty, ask_px, ask_qty), ch))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        error_cycles += int(dut.error.value)
        if quiet > 200:
            break
    return out, cross, anomaly, error_cycles


# ---------------------------------------------------------------------------
# BBO-01: secuencia multi-tipo -> BBO bit a bit contra el golden
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_bbo01_secuencia_bbo_igual_golden(dut):
    """Espejo §BBO-01: secuencia add/execute/cancel/delete -> BBO del golden."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),          # market open
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 50, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 3, b"S", 200, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),        # reduce 40/100
        X(AMZN, 1_000_000_005, 3, 80),              # cancel 80/200
        C(AMZN, 1_000_000_006, 2, 50, 1002, b"Y", 1_000_00),  # exec hasta 0 -> delete
        D(AMZN, 1_000_000_007, 1),                  # delete ref 1 (queda 60? no: rest 60)
        U(AMZN, 1_000_000_008, 2, 10, 30, 999_00),  # replace ref2 (ya borrada) -> anomaly
    ]
    expected, golden = run_book(msgs)
    got, cross, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    # normalizar: el golden emite (locate, (bbo), changed); got idéntico
    assert got == expected, (
        f"BBO-01:\n got={got}\n exp={expected}")
    assert anomaly == golden.anomalies, (
        f"BBO-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"BBO-01 cross: got={cross} exp={golden.cross_events}")


# ---------------------------------------------------------------------------
# SEC-U-01: replace atómico — nunca BBO intermedio con la orden ausente
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_u01_replace_atomico(dut):
    """Espejo §SEC-U-01: el BBO del U es el del estado final (sin ventana)."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        U(AMZN, 2, 1, 2, 50, 1_001_00),   # replace atómico: bid 100000->100100
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    # el BBO del U es el final (100100, 50) — el bid anterior (100000) ya no existe
    assert got == expected, f"SEC-U-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-HZ-01: add seguido de execute sobre la misma ref (RAW)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_hz01_add_execute_raw(dut):
    """Espejo §SEC-HZ-01: el execute ve el estado del add previo."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 2, 1, 40, 1001),   # reduce 40/100 -> 60
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-HZ-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-HZ-02: replace seguido de execute sobre la nueva ref (RAW)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_hz02_replace_execute_raw(dut):
    """Espejo §SEC-HZ-02: el execute actúa sobre la orden reemplazada."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        U(AMZN, 2, 1, 2, 50, 1_001_00),   # new ref=2
        E(AMZN, 3, 2, 30, 1002),          # reduce ref2 50->20
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-HZ-02: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-DC-01: execute + cancel no descuentan dos veces
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_dc01_sin_doble_descuento(dut):
    """Espejo §SEC-DC-01: el total descontado es exactamente el inicial."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        E(AMZN, 2, 1, 40, 1001),   # 100-40=60
        X(AMZN, 3, 1, 60,),        # 60-60=0 -> delete
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-DC-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-DC-02: delete descuenta exactamente la cantidad (no 2×)
#   Mata al mutante D-DOUBLE (delete con -2*qty -> newq negativo -> error).
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_dc02_delete_descuenta_exacto(dut):
    """Espejo §SEC-DC-01 (borde): delete vacía el nivel sin error ni 2×."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        D(AMZN, 2, 1),              # delete de la única orden bid -> nivel 0
    ]
    # el golden NO aborta (delete de ref existente es válido) -> BBO (0,0)
    expected, golden = run_book(msgs)
    assert golden.anomalies == 0, "SEC-DC-02: delete de ref existente no es anomalía"
    got, _, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    # el BBO final debe ser (0,0,0,0) y sin error ni anomalía
    assert got == expected, f"SEC-DC-02: got={got} exp={expected}"
    assert anomaly == 0, f"SEC-DC-02: anomaly={anomaly} (delete válido no cuenta)"


# ---------------------------------------------------------------------------
# SEC-AN-01: ref desconocida -> anomaly, continúa
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_an01_ref_desconocida(dut):
    """Espejo §SEC-AN-01: op sobre ref ausente cuenta anomaly y continúa."""
    AMZN = 393
    msgs = [
        E(AMZN, 1, 99, 10, 1),     # ref 99 no existe -> anomaly
        A(AMZN, 2, 1, b"B", 100, b"AMZN    ", 1_000_00),
    ]
    expected, golden = run_book(msgs)
    got, _, anomaly, _ = await drive_and_collect_bbo(dut, msgs)
    assert anomaly == golden.anomalies, f"SEC-AN-01: anomaly={anomaly} exp={golden.anomalies}"
    assert got == expected, f"SEC-AN-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-OV-01: reduce más de lo que hay -> error (invariante golden)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_ov01_overflow_cantidad(dut):
    """Espejo §SEC-OV-01: error observable, descarte y recuperación."""
    AMZN = 393
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        X(AMZN, 2, 1, 200,),        # cancel 200 > 100 -> error (golden aborta)
        A(AMZN, 3, 2, b"S", 50, b"AMZN    ", 1_005_00),
    ]
    # el golden lanza InvariantError; el RTL debe señalar `error` sin abortar
    try:
        run_book(msgs)
        raise AssertionError("SEC-OV-01: el golden debería abortar ante qty negativa")
    except book_golden.InvariantError:
        pass  # esperado
    # La operación inválida no emite; el add posterior sí se conserva.
    expected, _ = run_book([msgs[0], msgs[2]])
    got, _, _, error_cycles = await drive_and_collect_bbo(dut, msgs)
    assert error_cycles >= 1, "SEC-OV-01: no se observó el pulso error"
    assert got == expected, f"SEC-OV-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-CR-01: libro cruzado en trading continuo -> cross_events cuenta
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_cr01_libro_cruzado(dut):
    """Espejo §SEC-CR-01: bid>=ask en trading continuo cuenta cross_events."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),                # market open
        H(AMZN, 2, ord("T")),                # trading state continuous
        A(AMZN, 3, 1, b"S", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 4, 2, b"B", 100, b"AMZN    ", 1_000_00),  # bid == ask -> cross
    ]
    expected, golden = run_book(msgs)
    got, cross, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert cross == golden.cross_events, f"SEC-CR-01: cross={cross} exp={golden.cross_events}"
    assert got == expected, f"SEC-CR-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# SEC-EM-01: símbolo sin órdenes -> BBO (0,0,0,0)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sec_em01_simbolo_vacio(dut):
    """Espejo §BBO-02: locate vacío aislado y lado ask a cero."""
    AMZN = 393
    AAPL = 13
    msgs = [A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00)]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"SEC-EM-01: got={got} exp={expected}"
    assert all(loc != AAPL for loc, _, _ in got), "BBO-02: evento espurio para AAPL vacío"
    assert got[-1][1][2:] == (0, 0), f"BBO-02: ask vacío no está a cero: {got[-1]}"


# ---------------------------------------------------------------------------
# MULTI-01: dos símbolos intercalados con libros independientes
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_multi01_dos_simbolos_independientes(dut):
    """Espejo §MULTI-01: los mensajes de distintos locates no se contaminan."""
    AMZN = 393      # locate[4:0] = 9
    AAPL = 13       # locate[4:0] = 13
    msgs = [
        A(AMZN, 1, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AAPL, 2, 10, b"S", 50, b"AAPL    ", 1_500_00),
        E(AMZN, 3, 1, 40, 1001),   # reduce AMZN, no afecta AAPL
        A(AAPL, 4, 11, b"B", 200, b"AAPL    ", 1_400_00),
        X(AAPL, 5, 10, 20),        # cancel AAPL, no afecta AMZN
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, f"MULTI-01: got={got} exp={expected}"


# ---------------------------------------------------------------------------
# INV-U-01: replace sobre el mejor nivel — el BBO final ve la baja del precio
#   Pinca el BUG-U: dos level_add en el mismo ciclo (la segunda no ve la
#   primera por el sincronismo no-bloqueante) -> mejor bid stale.
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_inv_u01_replace_best_bid_estado_final(dut):
    """INV/SEC-U-01 (borde): U sobre el mejor bid -> el estado final es visible."""
    AMZN = 1101
    msgs = [
        A(AMZN, 1, 247097, b"B", 500, b"AMZN    ", 425_800),
        A(AMZN, 2, 246365, b"B", 300, b"AMZN    ", 425_500),
        U(AMZN, 3, 247097, 247657, 500, 425_700),  # baja el mejor bid 425800->425700
    ]
    expected, golden = run_book(msgs)
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"INV-U-01: got={got} exp={expected} "
        f"(el U debe dejar visible el nivel 425700, no el 425800 stale)")


# ---------------------------------------------------------------------------
# REPLAY-02: vectores congelados de BBO -> reproducción bit a bit
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_rep02_vectores_congelados_bbo(dut):
    """Espejo §REPLAY-02: el book reproduce los vectores congelados de BBO."""
    import os, json
    here = os.path.dirname(os.path.abspath(__file__))
    vec = os.path.join(here, "..", "..", "vectors", "bbo", "corpus_bbo.json")
    with open(vec) as f:
        data = json.load(f)
    msgs = [bytes.fromhex(h) for h in data["messages_hex"]]
    expected = [(e["locate"], (e["bid_px"], e["bid_qty"], e["ask_px"], e["ask_qty"]), e["changed"])
                for e in data["events"]]
    got, _, _, _ = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"REPLAY-02 ({data['name']}): got={got} exp={expected}")


# ---------------------------------------------------------------------------
# REPLAY-01: feed real (pcap del día local) -> BBO idéntico al golden
# ---------------------------------------------------------------------------
def _pcap_msgs_symbol(pcap_path, target_locate):
    """Lee un pcap y filtra los mensajes de UN símbolo (locate)."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    msgs = []
    for _seq, msgs_pkt, _pay in packets:
        for m in msgs_pkt:
            if int.from_bytes(m[1:3], "big") == target_locate:
                msgs.append(m)
    return msgs


def _pcap_msgs_subset(pcap_path, max_symbols=20):
    """Lee un pcap y filtra a los primeros `max_symbols` locates distintos."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "scripts"))
    from binaryfile_to_pcap import iter_pcap_packets
    packets = list(iter_pcap_packets(pcap_path))
    keep = set()
    msgs = []
    for _seq, msgs_pkt, _pay in packets:
        for m in msgs_pkt:
            loc = int.from_bytes(m[1:3], "big")
            if loc not in keep and len(keep) < max_symbols:
                keep.add(loc)
            if loc in keep:
                msgs.append(m)
    return msgs, keep


@cocotb.test(skip=not os.path.exists(REAL_PCAP))
async def test_replay01_feed_real_bbo(dut):
    """Espejo §REPLAY-01: el BBO del feed real (subset 20 símbolos) es idéntico
    al golden book.py — bit a bit, evento a evento, incluido changed.

    El pcap local no se commitea (regla G0); el test se omite si no existe."""
    assert os.path.exists(REAL_PCAP), "REPLAY-01 OMITIDO: pcap local ausente"
    msgs, keep = _pcap_msgs_subset(REAL_PCAP, max_symbols=20)
    cocotb.log.info(
        f"REPLAY-01: {len(msgs)} mensajes de {len(keep)} símbolos "
        f"({sorted(keep)[:3]}...) contra golden")
    expected, golden = run_book(msgs)
    got, cross, anomaly, _ = await drive_and_collect_bbo(dut, msgs, max_cycles=2_000_000)
    if got != expected:
        first = next(i for i, (g, e) in enumerate(zip(got, expected)) if g != e)
        raise AssertionError(
            f"REPLAY-01: got({len(got)}) exp({len(expected)}) sobre {len(msgs)} msgs "
            f"/ {len(keep)} símbolos; primer desajuste en evento {first}:\n"
            f" got={got[first-2:first+3]}\n exp={expected[first-2:first+3]}")
    assert cross == golden.cross_events, (
        f"REPLAY-01 cross: got={cross} exp={golden.cross_events}")
    assert anomaly == golden.anomalies, (
        f"REPLAY-01 anomaly: got={anomaly} exp={golden.anomalies}")
    cocotb.log.info(
        f"REPLAY-01 OK: {len(got)} eventos bit a bit, "
        f"cross={cross}, anomaly={anomaly}")
