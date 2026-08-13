"""Testbench cocotb de la latencia wire->BBO por tipo (fase 3, criterio 8) —
área phase3.

Espejo SEC-LAT-01: sobre la cadena parser->book a DW=32 y una secuencia fija
(el subset del feed real, o el corpus sintético si no hay pcap), se mide por
tipo de mensaje la latencia en ciclos desde el handshake de la word que cubre
el primer byte del mensaje en s_axis hasta su evento BBO en bbo_tvalid.
La re-ejecución debe producir el histograma idéntico (determinismo), y el
histograma se persiste como evidencia (derivada, sin datos crudos) en
verification/vectors/latency/latency_dw32.json.
"""
import json
import os
import struct

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import run_book, _pcap_msgs_subset, _fields_from_body
from golden_model.src import book as book_golden
from golden_model.src import message_oracle

LAT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "../../vectors/latency/latency_dw32.json")
NS_PER_CYCLE = 1e9 / 322.265625e6


async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, units="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    dut.depth_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


def _chunks32(payload):
    chunks = []
    for i in range(0, len(payload), 4):
        bite = payload[i:i + 4]
        chunks.append(int.from_bytes(bite, "big") << (8 * (4 - len(bite))))
    return chunks


def _payload_seq(messages, seq):
    payload = struct.pack(">10sQH", b"SIM0000001", seq, len(messages))
    payload += b"".join(len(m).to_bytes(2, "big") + m for m in messages)
    return payload


def _msg_offsets(messages):
    """Byte de inicio de cada mensaje dentro del payload MoldUDP64."""
    offs = []
    cur = 20  # cabecera MoldUDP64: sesión 10 B + seq 8 B + count 2 B
    for m in messages:
        offs.append(cur)
        cur += 2 + len(m)
    return offs


def _emitting_indexes(messages):
    """Índices (en el stream) de los mensajes que emiten evento BBO, en orden.
    El evento j-ésimo del RTL corresponde al índice j-ésimo (CHAIN-01, bit a
    bit, garantiza el orden)."""
    bk = book_golden.Book()
    idxs = []
    for idx, raw in enumerate(messages):
        mtype = chr(raw[0])
        locate = int.from_bytes(raw[1:3], "big")
        body = raw[message_oracle.COMMON_HEADER_LEN:]
        fields = _fields_from_body(mtype, body)
        ev = bk.apply((idx, mtype, locate, 0, 0, fields))
        if ev is not None:
            idxs.append(idx)
    return idxs


async def drive_lat(dut, payloads, max_cycles=3_000_000, window=8000):
    """Conduce payloads a la cadena y devuelve (accepts, events, cross, anomaly,
    gaps): accepts[i] = ciclo del handshake de la i-ésima word aceptada en
    s_axis; events = [(ciclo, locate, tdata, changed)] de cada handshake BBO."""
    await _reset(dut)
    concat = b"".join(payloads)
    chunks = _chunks32(concat)
    len_acc = 0
    lastbyte = set()
    for p in payloads:
        len_acc += len(p)
        lastbyte.add(len_acc - 1)
    lasts = set()
    for bi in range(len(concat)):
        if bi in lastbyte:
            lasts.add(bi // 4)
    n = len(chunks)
    ci = 0
    out = []
    accepts = []
    quiet = 0
    cross = 0
    anomaly = 0
    gaps = 0
    for cycle in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = chunks[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci in lasts else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.gap_detected.value) == 1:
            gaps += 1
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            out.append((cycle, int(dut.bbo_locate.value),
                        int(dut.bbo_tdata.value), int(dut.bbo_changed.value)))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                accepts.append(cycle)
                ci += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > window:
            break
    return accepts, out, cross, anomaly, gaps


def _latencies(msgs, accepts, events):
    """Latencia por tipo: para cada evento, ciclo del BBO menos ciclo del
    handshake de la word que cubre el primer byte de su mensaje."""
    offs = _msg_offsets(msgs)
    emitters = _emitting_indexes(msgs)
    assert len(emitters) == len(events), (
        f"SEC-LAT-01: {len(emitters)} eventos golden vs {len(events)} del RTL")
    lat = {}
    for j, (cycle, _, _, _) in enumerate(events):
        mi = emitters[j]
        wi = offs[mi] // 4
        arrival = accepts[wi]
        t = msgs[mi][0]
        lat.setdefault(t, []).append(cycle - arrival)
    return lat


def _hist_summary(lats):
    if not lats:
        return None
    s = sorted(lats)
    n = len(s)
    p = lambda q: s[min(n - 1, int(q * n))]
    return {
        "n": n,
        "min_ciclos": s[0],
        "max_ciclos": s[-1],
        "mean_ciclos": round(sum(s) / n, 3),
        "p50_ciclos": p(0.50),
        "p99_ciclos": p(0.99),
        "hist_ciclos": {str(k): s.count(k) for k in sorted(set(s))},
    }


@cocotb.test()
async def test_sec_lat01_histograma_determinista_por_tipo(dut):
    """Espejo §SEC-LAT-01: histograma wire->BBO por tipo, determinista entre
    dos re-ejecuciones, con evidencia JSON persistida (sin datos crudos)."""
    import os as _os
    pcap = "/tmp/real_trading.pcap"
    if _os.path.exists(pcap):
        msgs, keep = _pcap_msgs_subset(pcap, max_symbols=20)
        stream = f"subset de {len(keep)} símbolos del feed real (2019-12-30)"
    else:
        from test_orderbook import S, A
        AMZN = 393
        msgs = [
            S(AMZN, 1_000_000_000, ord("Q")),
            A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
            A(AMZN, 1_000_000_002, 2, b"S", 50, b"AMZN    ", 1_005_00),
            E(AMZN, 1_000_000_003, 1, 40, 1001),
            A(AMZN, 1_000_000_004, 3, b"B", 200, b"AMZN    ", 999_00),
        ]
        stream = "corpus sintético (env sin pcap local)"
    payload = _payload_seq(msgs, 1)
    accepts1, ev1, cross, anomaly, gaps = await drive_lat(dut, [payload])
    accepts2, ev2, cross2, anomaly2, gaps2 = await drive_lat(dut, [payload])
    lat1 = _latencies(msgs, accepts1, ev1)
    lat2 = _latencies(msgs, accepts2, ev2)
    assert lat1 == lat2, (
        f"SEC-LAT-01: histogramas distintos entre re-ejecuciones "
        f"({lat1} vs {lat2})")
    assert cross == cross2 and anomaly == anomaly2 and gaps == gaps2, (
        f"SEC-LAT-01: contadores distintos entre re-ejecuciones")
    total = [l for v in lat1.values() for l in v]
    by_type = {chr(t): _hist_summary(v) for t, v in sorted(lat1.items())}
    doc = {
        "campana": "fase3-optimizacion",
        "criterio": 8,
        "espejo": "SEC-LAT-01",
        "medicion": "latencia wire->BBO: handshake en s_axis (word del primer "
                    "byte del mensaje) -> bbo_tvalid en la cadena parser->book "
                    "a DW=32",
        "frecuencia_hz": 322.265625e6,
        "ns_por_ciclo": round(NS_PER_CYCLE, 4),
        "stream": stream,
        "n_mensajes": len(msgs),
        "n_eventos": len(ev1),
        "gaps": gaps,
        "anomaly": anomaly,
        "cross": cross,
        "por_tipo": by_type,
        "total": _hist_summary(total),
    }
    _os.makedirs(_os.path.dirname(LAT_PATH), exist_ok=True)
    with open(LAT_PATH, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    cocotb.log.info(
        f"SEC-LAT-01 OK: {len(ev1)} eventos, determinista (2 ejecuciones "
        f"idénticas); evidencia en {LAT_PATH}")
    for t, s in by_type.items():
        cocotb.log.info(
            f"  tipo {t}: n={s['n']} min={s['min_ciclos']} "
            f"max={s['max_ciclos']} mean={s['mean_ciclos']} ciclos "
            f"({s['mean_ciclos']*NS_PER_CYCLE:.1f} ns)")