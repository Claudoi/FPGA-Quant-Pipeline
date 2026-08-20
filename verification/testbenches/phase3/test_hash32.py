"""Testbench cocotb de la tabla de órdenes hashada (fase 3, iteración 2) —
área phase3. Espejos SEC-HASH-01/02/03.

La suite se ejecuta con K=20 (más de PROBE refs por hash en 2^K): ver el
target `sim-hash` del Makefile. Con K=19 el teorema de los 8 slots por hash
hace inalcanzable el probe agotado (9ª ref del mismo hash se trunca a una
existente); K=20 lo hace real: la ref 5+8*65536 existe en 2^20 sin truncarse.
"""
import cocotb
from cocotb.triggers import RisingEdge

from test_orderbook import (A, D, E, U, X, S, run_book)
from test_orderbook32 import anexo_words32, _reset


async def drive_and_collect_bbo32_err(dut, messages, max_cycles=200000):
    """Conduce Anexo A de 32 bits y recolecta (events, cross, anomaly, errores).

    Muestrea el pulso `error` en vivo (igual que los drivers de fase 1)."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    quiet = 0
    cross = 0
    anomaly = 0
    errores = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        if int(dut.error.value) == 1:
            errores += 1
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            ch = int(dut.bbo_changed.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF), ch))
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
        if quiet > 200:
            break
    return out, cross, anomaly, errores


@cocotb.test()
async def test_sec_hash03_colision_entre_simbolos(dut):
    """Espejo §SEC-HASH-03: refs de símbolos distintos con el mismo hash se
    distinguen (el ref se guarda en el slot, el probing compara el ref)."""
    AMZN = 393
    AAPL = 13
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),       # hash(5)=5
        A(AAPL, 3, 65541, b"S", 50, b"AAPL    ", 1_500_00),    # hash(65541)=5
        E(AMZN, 4, 5, 40, 1001),                                # reduce la de AMZN
        A(AAPL, 5, 11, b"B", 200, b"AAPL    ", 1_400_00),
        X(AAPL, 6, 65541, 20),                                  # cancel la de AAPL
    ]
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert got == expected, f"SEC-HASH-03: got={got} exp={expected}"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-03 anomaly: got={anomaly} exp={golden.anomalies}")
    assert errores == 0, f"SEC-HASH-03: sin errores esperados, vistos {errores}"


@cocotb.test()
async def test_sec_hash01_probe_agotado_anomalia(dut):
    """Espejo §SEC-HASH-01: ref inexistente cuyo camino de probing está lleno
    -> anomalía contada, el book continúa (sin error ni aborto)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # 8 refs hash 5 -> slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(E(AMZN, 100, 5 + 8 * 65536, 10, 999))   # inexistente, camino lleno
    msgs.append(A(AMZN, 101, 1000, b"S", 50, b"AMZN    ", 1_100_00))  # continúa
    msgs.append(E(AMZN, 102, refs[7], 10, 1007))        # ref en el último slot de probing
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-01: anomaly={anomaly} exp={golden.anomalies}")
    assert errores == 0, (
        f"SEC-HASH-01: probe agotado NO es error, vistos {errores}")
    assert got == expected, f"SEC-HASH-01: got={got} exp={expected}"


@cocotb.test()
async def test_sec_hash02_tabla_llena_error(dut):
    """Espejo §SEC-HASH-02: insert con el camino de probing lleno -> error
    señalizado, sin wrap ni overwrite silencioso; las refs previas intactas y
    el mensaje posterior se procesa igualmente.

    El golden no tiene límite de tabla (inserta la orden), así que el estado
    diverge tras el fallo: la comparación bit a bit cubre los eventos previos
    y la ausencia del evento del add fallido; el evento posterior se verifica
    de forma cerrada (reduce 40/100 -> mejor bid inalterado)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # ocupan slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(A(AMZN, 100, 5 + 8 * 65536, b"B", 50, b"AMZN    ", 1_200_00))
    msgs.append(E(AMZN, 101, refs[0], 40, 999))              # ref previa intacta
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-02: la tabla llena debe señalar error"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-02: anomaly={anomaly} exp={golden.anomalies}")
    # los 8 adds previos bit a bit (el insert fallido no corrompió la tabla)
    assert got[:8] == expected[:8], (
        f"SEC-HASH-02: adds previos alterados: got={got[:8]} exp={expected[:8]}")
    # el add fallido no emite BBO y el E posterior sí se procesa
    assert len(got) == 9, f"SEC-HASH-02: eventos={len(got)} exp=9"
    assert got[8] == (393, (100007, 100, 0, 0), 0), (
        f"SEC-HASH-02: BBO del E: got={got[8]} exp=(393, (100007, 100, 0, 0), 0)")


@cocotb.test()
async def test_sec_hash02c_replace_half_llena_error(dut):
    """INV/SEC-HASH-02: la mitad add del replace no cabe (camino del newref
    lleno, newref distinto a la orig) -> error y BBO del replace cancelado;
    la ref previa intacta. Verificación cerrada (el golden no modela la
    limitación de tabla)."""
    AMZN = 393
    refs = [100 + i * 65536 for i in range(8)]   # hash 100 -> slots 100..107
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 2_000_00 + i))
    msgs.append(A(AMZN, 20, 5, b"B", 50, b"AMZN    ", 1_000_00))     # ref 5
    # 5 -> 524388 (9ª ref del hash 100, inexistente; camino 100..107 lleno)
    msgs.append(U(AMZN, 21, 5, 100 + 8 * 65536, 30, 1_500_00))
    msgs.append(E(AMZN, 22, refs[0], 10, 2000))      # ref previa intacta
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-02c: la mitad add llena debe señalar error"
    assert anomaly == 0, f"SEC-HASH-02c: anomaly={anomaly} exp=0"
    # 8 adds + add 5 + E refs[0] = 10 eventos; el U fallido no emite
    assert len(got) == 10, f"SEC-HASH-02c: eventos={len(got)} exp=10"
    assert got[9] == (393, (200007, 100, 0, 0), 0), (
        f"SEC-HASH-02c: BBO del E: got={got[9]} exp=(393, (200007, 100, 0, 0), 0)")


@cocotb.test()
async def test_sec_hash04_ref_duplicada_error(dut):
    """INV/SEC-HASH-02: add con ref duplicada -> error sin emitir BBO ni
    corromper (el golden lanza InvariantError; verificación cerrada)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 3, 5, b"B", 50, b"AMZN    ", 1_100_00),    # dup ref 5 -> error
        A(AMZN, 4, 6, b"B", 200, b"AMZN    ", 1_000_00),   # el book continúa
    ]
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-04: ref duplicada debe señalar error"
    assert anomaly == 0, f"SEC-HASH-04: anomaly={anomaly} exp=0"
    assert got == [(393, (100000, 100, 0, 0), 1),
                   (393, (100000, 300, 0, 0), 1)], (
        f"SEC-HASH-04: got={got} exp=[(100000,100), (100000,300)]")


@cocotb.test()
async def test_sec_hash02b_tombstone_reutilizado(dut):
    """INV/SEC-HASH-02 (borde): el slot borrado (tombstone) se reutiliza en el
    insert y el lookup de la ref viva atraviesa tombstones sin falsa anomalía."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # ocupan slots 5..12 (hash 5)
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 100, refs[0]))          # borra ref[0] -> slot 5 tombstone
    msgs.append(A(AMZN, 101, 5 + 8 * 65536, b"B", 60, b"AMZN    ", 1_300_00))
    # la nueva ref (hash 5) reutiliza el slot 5; la ref[1] (slot 6) sigue viva
    msgs.append(E(AMZN, 102, refs[1], 30, 1001))
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert got == expected, f"SEC-HASH-02b: got={got} exp={expected}"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-02b: anomaly={anomaly} exp={golden.anomalies}")


@cocotb.test()
async def test_inv_u01_tabla_llena_no_borra_la_original(dut):
    """INV/SEC-HASH-02 (U): el replace con el camino del newref lleno señala
    error SIN aplicar la mitad delete — la orden original sobrevive.

    Hallazgo MAYOR del reviewer (G5): el RTL aplicaba el delete en ST_APPLY y
    solo detectaba la tabla llena en ST_UADD -> la orden original se perdía
    silenciosamente (error de pulso y libro divergente del golden).

    El path del newref (hash 9) queda lleno con refs AJENAS (grupo B); el
    delete de la original (grupo A, hash 5) libera otro slot, no el del path.

    Forma cerrada (el golden no tiene límite de tabla): tras el U fallido, un
    E sobre la ref original reduce su nivel (la original sigue viva)."""
    AMZN = 393
    refsA = [5 + i * 65536 for i in range(8)]       # slots 5..12 (hash 5)
    refsB = [100 + i * 65536 for i in range(8)]     # slots 100..107 (hash 100),
    # disjunto del path de A: los 16 adds caben sin error
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refsA):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    for i, r in enumerate(refsB):
        msgs.append(A(AMZN, 20 + i, r, b"B", 100, b"AMZN    ", 999_00 + i))
    msgs.append(U(AMZN, 90, refsA[0], 100 + 8 * 65536, 100, 1_000_00))
    msgs.append(E(AMZN, 91, refsA[0], 100, 1001))   # la original debe seguir viva
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "INV-U-01: el U con tabla llena debe señalar error"
    assert anomaly == 0, (
        f"INV-U-01: anomaly={anomaly} exp=0 (la original no debe perderse: "
        f"el E posterior la reduce)")
    assert len(got) == 17, f"INV-U-01: eventos={len(got)} exp=17 (16 adds + E)"
    assert got[-1] == (393, (100007, 100, 0, 0), 0), (
        f"INV-U-01: el E reduce la original -> mejor bid intacto 100007@100: "
        f"got[-1]={got[-1]}")


@cocotb.test()
async def test_inv_ov01_phantom_no_envuelve_cantidad(dut):
    """INV/SEC-OV-01 (phantom): un reduce sobre un nivel que no existe (orden
    en tabla sin nivel por overflow de P=32) NO puede escribir una cantidad
    envuelta (~4,29e9) en un slot libre.

    Hallazgo MAYOR del reviewer (G5): con un slot libre (tras un D) la
    reducción con delta negativo y precio ausente escribía QW'(delta) envuelto
    -> nivel fantasma que salía como mejor bid.

    Con el push-out (addendum iter 13/15) el 33º add a un precio MEJOR que el
    peor entra legítimamente al top-P (descarta el peor 100000) — no es error.
    Solo el reduce sobre el nivel ya descartado (D del peor) señala SEC-OV.
    """
    AMZN = 393
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(33):
        msgs.append(A(AMZN, 10 + i, 1000 + i, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 50, 1000))          # libera un slot (orden 100000 descartada)
    msgs.append(D(AMZN, 51, 1032))          # la orden 33ª (en top, con nivel)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores == 1, (
        f"INV-OV-01: errores={errores} exp=1 (solo el reduce sobre el nivel "
        f"descartado por el push-out; el add-33 entró por ser mejor que el peor)")
    assert anomaly == 0, f"INV-OV-01: anomaly={anomaly} exp=0"
    assert len(got) == 35, f"INV-OV-01: eventos={len(got)} exp=35"
    assert got[-1] == (393, (100031, 100, 0, 0), 1), (
        f"INV-OV-01: tras el push-out el D del mejor 100032 lo baja a 100031 "
        f"(changed=1, sin wrap): got[-1]={got[-1]}")