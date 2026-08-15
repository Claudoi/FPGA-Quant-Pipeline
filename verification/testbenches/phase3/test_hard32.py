"""Testbench cocotb del hardening del book a DW=32 (fase 3, criterios 7-8) —
área phase3.

Espejos SEC-NSYM-01 (hallazgo F1 del grade): un locate fuera del subset de
NSYM=20 señala error y se descarta sin corromper el libro (nunca un índice
OOB). Espejo SEC-BP-01 (hallazgo F2): el par BBO/depth se retiene bajo
backpressure y se entrega exactamente una vez, sin pérdida ni duplicado.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import (A, E, X, D, S, run_book, _reset)
from test_orderbook32 import anexo_words32


async def drive_and_collect_hard32(dut, messages, stall=None, wait_w0_at=(),
                                   max_cycles=300000):
    """Conduce Anexo A de 32 bits con backpressure opcional en bbo/depth.

    `stall` es una función ciclo->bool (True = tready en 0, backpressure);
    None = sin backpressure. Muestrea el pulso de `error` por ciclo.

    Devuelve (bbo_events, cross_count, anomaly_count, error_cycles,
    oob_index_cycles)."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    quiet = 0
    cross = 0
    anomaly = 0
    errors = 0
    oob_index_cycles = 0
    w0_released = set()
    for cycle in range(max_cycles):
        stall_now = bool(stall(cycle)) if stall else False
        wait_w0 = ci in wait_w0_at and ci not in w0_released
        if wait_w0 and int(dut.st.value) == 0:  # ST_W0
            w0_released.add(ci)
            wait_w0 = False
        dut.s_axis_tvalid.value = 1 if ci < n and not wait_w0 else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 0 if stall_now else 1
        dut.depth_tready.value = 0 if stall_now else 1
        await RisingEdge(dut.clk)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
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
        if int(dut.error.value) == 1:
            errors += 1
        if int(dut.m_loc_idx.value) >= 20:
            oob_index_cycles += 1
        if int(dut.cross_events.value) != 0:
            cross = int(dut.cross_events.value)
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if quiet > 200:
            break
    return out, cross, anomaly, errors, oob_index_cycles


@cocotb.test()
async def test_sec_nsym01_simbolo_21_error_sin_oob(dut):
    """Espejo §SEC-NSYM-01: el locate 21 (fuera del subset) señala error, se
    descarta sin emitir BBO y no corrompe los niveles de los 20 registrados.

    Forma cerrada: el golden procesa SOLO los mensajes del subset; el RTL recibe
    también los del símbolo 21 y debe emitir exactamente lo mismo (el 21 solo
    cuenta error)."""
    AMZN = 393
    locs = [AMZN] + [10_000 + i for i in range(19)]
    msgs = [S(l, 2_000_000_000 + i, ord("Q")) for i, l in enumerate(locs)]
    msgs.append(A(7777, 3_000_000_000, 100, b"B", 100, b"MSFT    ", 3_000_00))
    msgs.append(A(AMZN, 3_000_000_001, 101, b"B", 200, b"AMZN    ", 2_000_00))
    msgs.append(E(AMZN, 3_000_000_002, 101, 40, 2001))
    boundary = len(anexo_words32(msgs[:20]))
    gold_msgs = [m for m in msgs if int.from_bytes(m[1:3], "big") != 7777]
    expected, golden = run_book(gold_msgs)
    got, cross, anomaly, errors, oob_cycles = await drive_and_collect_hard32(
        dut, msgs, wait_w0_at=(boundary,))
    assert errors > 0, "SEC-NSYM-01: el símbolo 21 no señalizó error"
    assert oob_cycles == 0, (
        f"SEC-NSYM-01: m_loc_idx quedó fuera de NSYM durante {oob_cycles} ciclos")
    assert got == expected, (
        f"SEC-NSYM-01: got={got} exp={expected} "
        f"(el símbolo 21 no debe emitir ni corromper el libro)")
    assert anomaly == golden.anomalies, (
        f"SEC-NSYM-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"SEC-NSYM-01 cross: got={cross} exp={golden.cross_events}")
    cocotb.log.info(
        f"SEC-NSYM-01 OK: {errors} pulsos de error, {len(got)} eventos del "
        f"subset intactos, cross={cross}, anomaly={anomaly}")


@cocotb.test()
async def test_sec_bp01_bbo_se_retiene_bajo_backpressure(dut):
    """Espejo §SEC-BP-01: con bbo_tready/depth_tready en 0 durante el evento,
    el par se retiene y se entrega exactamente una vez (sin pérdida ni
    duplicado), y la secuencia sigue siendo bit a bit la del golden.

    Patrón de backpressure determinista: tready permanece a cero hasta ver
    tvalid, comprueba dos ciclos de retención estable y entonces libera."""
    AMZN = 393
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"B", 50, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_003, 3, b"S", 200, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_004, 1, 40, 1001),
        X(AMZN, 1_000_000_005, 3, 80),
        D(AMZN, 1_000_000_006, 1),
        A(AMZN, 1_000_000_007, 4, b"S", 90, b"AMZN    ", 1_003_00),
    ]
    expected, golden = run_book(msgs)

    hold = {"seen": False, "remaining": 2, "released": False, "payload": None}

    def stall(_cycle):
        if not hold["seen"]:
            if int(dut.bbo_tvalid.value) == 1:
                hold["seen"] = True
                hold["payload"] = (int(dut.bbo_tdata.value),
                                   int(dut.depth_tdata.value))
            return True
        if hold["released"]:
            return False
        assert int(dut.bbo_tvalid.value) == 1, (
            "SEC-BP-01: bbo_tvalid cayó mientras tready seguía a cero")
        assert int(dut.depth_tvalid.value) == 1, (
            "SEC-BP-01: depth_tvalid cayó mientras tready seguía a cero")
        assert (int(dut.bbo_tdata.value), int(dut.depth_tdata.value)) == hold["payload"], (
            "SEC-BP-01: el payload cambió durante la retención")
        if hold["remaining"]:
            hold["remaining"] -= 1
            return True
        hold["released"] = True
        return False

    got, cross, anomaly, errors, oob_cycles = await drive_and_collect_hard32(
        dut, msgs, stall=stall)
    assert hold["seen"] and hold["released"], (
        "SEC-BP-01: el test no observó y liberó un evento retenido")
    assert got == expected, (
        f"SEC-BP-01: got({len(got)}) exp({len(expected)}) "
        f"— evento perdido o duplicado bajo backpressure:\n"
        f" got={got}\n exp={expected}")
    assert anomaly == golden.anomalies, (
        f"SEC-BP-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"SEC-BP-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"SEC-BP-01: {errors} errores espurios bajo backpressure"
    assert oob_cycles == 0, f"SEC-BP-01: {oob_cycles} ciclos con índice OOB"
    cocotb.log.info(
        f"SEC-BP-01 OK: {len(got)} eventos entregados exactamente una vez "
        "tras dos ciclos de retención estable")
