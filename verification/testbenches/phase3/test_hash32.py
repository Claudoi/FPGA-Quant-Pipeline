"""Cocotb testbench for the hashed order table (phase 3, iteration 2) — area
phase3. Mirrors SEC-HASH-01/02/03.

The suite runs with K=20 (more than PROBE refs per hash in 2^K): see the
`sim-hash` target of the Makefile. With K=19 the 8-slots-per-hash theorem makes
the exhausted probe unreachable (the 9th ref of the same hash truncates to an
existing one); K=20 makes it real: ref 5+8*65536 exists in 2^20 without
truncating.
"""
import cocotb
from cocotb.triggers import RisingEdge

from test_orderbook import (A, D, E, U, X, S, run_book)
from test_orderbook32 import anexo_words32, _reset


async def drive_and_collect_bbo32_err(dut, messages, max_cycles=200000):
    """Drives 32-bit Annex A and collects (events, cross, anomaly, errores).

    Samples the `error` pulse live (like the phase 1 drivers)."""
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
    """Mirror §SEC-HASH-03: refs of distinct symbols with the same hash are
    distinguished (the ref is stored in the slot, the probing compares the ref)."""
    AMZN = 393
    AAPL = 13
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),       # hash(5)=5
        A(AAPL, 3, 65541, b"S", 50, b"AAPL    ", 1_500_00),    # hash(65541)=5
        E(AMZN, 4, 5, 40, 1001),                                # reduces the AMZN one
        A(AAPL, 5, 11, b"B", 200, b"AAPL    ", 1_400_00),
        X(AAPL, 6, 65541, 20),                                  # cancels the AAPL one
    ]
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert got == expected, f"SEC-HASH-03: got={got} exp={expected}"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-03 anomaly: got={anomaly} exp={golden.anomalies}")
    assert errores == 0, f"SEC-HASH-03: no errors expected, saw {errores}"


@cocotb.test()
async def test_sec_hash01_probe_agotado_anomalia(dut):
    """Mirror §SEC-HASH-01: nonexistent ref whose probing path is full -> counted
    anomaly, the book continues (without error or abort)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # 8 refs hash 5 -> slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(E(AMZN, 100, 5 + 8 * 65536, 10, 999))   # nonexistent, full path
    msgs.append(A(AMZN, 101, 1000, b"S", 50, b"AMZN    ", 1_100_00))  # continues
    msgs.append(E(AMZN, 102, refs[7], 10, 1007))        # ref in the last probing slot
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-01: anomaly={anomaly} exp={golden.anomalies}")
    assert errores == 0, (
        f"SEC-HASH-01: exhausted probe is NOT an error, saw {errores}")
    assert got == expected, f"SEC-HASH-01: got={got} exp={expected}"


@cocotb.test()
async def test_sec_hash02_tabla_llena_error(dut):
    """Mirror §SEC-HASH-02: insert with a full probing path -> error signaled,
    no wrap nor silent overwrite; the prior refs intact and the subsequent
    message is processed anyway.

    The golden model has no table limit (it inserts the order), so the state
    diverges after the failure: the bit-exact comparison covers the prior
    events and the absence of the event of the failed add; the subsequent
    event is verified in closed form (reduce 40/100 -> best bid unchanged)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # occupy slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(A(AMZN, 100, 5 + 8 * 65536, b"B", 50, b"AMZN    ", 1_200_00))
    msgs.append(E(AMZN, 101, refs[0], 40, 999))              # prior ref intact
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-02: the full table must signal an error"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-02: anomaly={anomaly} exp={golden.anomalies}")
    # the 8 prior adds bit-exact (the failed insert did not corrupt the table)
    assert got[:8] == expected[:8], (
        f"SEC-HASH-02: prior adds altered: got={got[:8]} exp={expected[:8]}")
    # the failed add does not emit a BBO and the subsequent E is processed
    assert len(got) == 9, f"SEC-HASH-02: events={len(got)} exp=9"
    assert got[8] == (393, (100007, 100, 0, 0), 0), (
        f"SEC-HASH-02: BBO of the E: got={got[8]} exp=(393, (100007, 100, 0, 0), 0)")


@cocotb.test()
async def test_sec_hash02c_replace_half_llena_error(dut):
    """INV/SEC-HASH-02: the add half of the replace does not fit (newref path
    full, newref distinct from the orig) -> error and the replace's BBO
    canceled; the prior ref intact. Closed-form verification (the golden model
    does not model the table limit)."""
    AMZN = 393
    refs = [100 + i * 65536 for i in range(8)]   # hash 100 -> slots 100..107
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 2_000_00 + i))
    msgs.append(A(AMZN, 20, 5, b"B", 50, b"AMZN    ", 1_000_00))     # ref 5
    # 5 -> 524388 (9th ref of hash 100, nonexistent; path 100..107 full)
    msgs.append(U(AMZN, 21, 5, 100 + 8 * 65536, 30, 1_500_00))
    msgs.append(E(AMZN, 22, refs[0], 10, 2000))      # prior ref intact
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-02c: the full add half must signal an error"
    assert anomaly == 0, f"SEC-HASH-02c: anomaly={anomaly} exp=0"
    # 8 adds + add 5 + E refs[0] = 10 events; the failed U does not emit
    assert len(got) == 10, f"SEC-HASH-02c: events={len(got)} exp=10"
    assert got[9] == (393, (200007, 100, 0, 0), 0), (
        f"SEC-HASH-02c: BBO of the E: got={got[9]} exp=(393, (200007, 100, 0, 0), 0)")


@cocotb.test()
async def test_sec_hash04_ref_duplicada_error(dut):
    """INV/SEC-HASH-02: add with duplicate ref -> error without emitting a BBO nor
    corrupting (the golden model raises InvariantError; closed-form verification)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 3, 5, b"B", 50, b"AMZN    ", 1_100_00),    # dup ref 5 -> error
        A(AMZN, 4, 6, b"B", 200, b"AMZN    ", 1_000_00),   # the book continues
    ]
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "SEC-HASH-04: duplicate ref must signal an error"
    assert anomaly == 0, f"SEC-HASH-04: anomaly={anomaly} exp=0"
    assert got == [(393, (100000, 100, 0, 0), 1),
                   (393, (100000, 300, 0, 0), 1)], (
        f"SEC-HASH-04: got={got} exp=[(100000,100), (100000,300)]")


@cocotb.test()
async def test_sec_hash02b_tombstone_reutilizado(dut):
    """INV/SEC-HASH-02 (edge): the deleted slot (tombstone) is reused in the
    insert and the lookup of the live ref traverses tombstones without a false
    anomaly."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]    # occupy slots 5..12 (hash 5)
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 100, refs[0]))          # deletes ref[0] -> slot 5 tombstone
    msgs.append(A(AMZN, 101, 5 + 8 * 65536, b"B", 60, b"AMZN    ", 1_300_00))
    # the new ref (hash 5) reuses slot 5; ref[1] (slot 6) stays alive
    msgs.append(E(AMZN, 102, refs[1], 30, 1001))
    expected, golden = run_book(msgs)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert got == expected, f"SEC-HASH-02b: got={got} exp={expected}"
    assert anomaly == golden.anomalies, (
        f"SEC-HASH-02b: anomaly={anomaly} exp={golden.anomalies}")


@cocotb.test()
async def test_inv_u01_tabla_llena_no_borra_la_original(dut):
    """INV/SEC-HASH-02 (U): the replace with the newref path full signals an error
    WITHOUT applying the delete half — the original order survives.

    MAJOR reviewer finding (G5): the RTL applied the delete in ST_APPLY and
    only detected the full table in ST_UADD -> the original order was silently
    lost (error pulse and book diverging from the golden model).

    The newref path (hash 9) stays full with FOREIGN refs (group B); the delete
    of the original (group A, hash 5) frees another slot, not the one in the
    path.

    Closed form (the golden model has no table limit): after the failed U, an
    E on the original ref reduces its level (the original stays alive)."""
    AMZN = 393
    refsA = [5 + i * 65536 for i in range(8)]       # slots 5..12 (hash 5)
    refsB = [100 + i * 65536 for i in range(8)]     # slots 100..107 (hash 100),
    # disjoint from A's path: the 16 adds fit without error
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refsA):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    for i, r in enumerate(refsB):
        msgs.append(A(AMZN, 20 + i, r, b"B", 100, b"AMZN    ", 999_00 + i))
    msgs.append(U(AMZN, 90, refsA[0], 100 + 8 * 65536, 100, 1_000_00))
    msgs.append(E(AMZN, 91, refsA[0], 100, 1001))   # the original must stay alive
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores > 0, "INV-U-01: the U with the full table must signal an error"
    assert anomaly == 0, (
        f"INV-U-01: anomaly={anomaly} exp=0 (the original must not be lost: "
        f"the subsequent E reduces it)")
    assert len(got) == 17, f"INV-U-01: events={len(got)} exp=17 (16 adds + E)"
    assert got[-1] == (393, (100007, 100, 0, 0), 0), (
        f"INV-U-01: the E reduces the original -> best bid intact 100007@100: "
        f"got[-1]={got[-1]}")


@cocotb.test()
async def test_inv_ov01_phantom_no_envuelve_cantidad(dut):
    """INV/SEC-OV-01 (phantom): a reduce on a level that does not exist (order in
    the table without a level due to P=32 overflow) CANNOT write a wrapped
    quantity (~4.29e9) into a free slot.

    MAJOR reviewer finding (G5): with a free slot (after a D) the reduction
    with negative delta and absent price wrote QW'(delta) wrapped -> phantom
    level that came out as the best bid.

    With the push-out (addendum iter 13/15) the 33rd add at a price BETTER than
    the worst enters the top-P legitimately (it discards the worst 100000) —
    it is not an error. Only the reduce on the already-discarded level (D of
    the worst) signals SEC-OV.
    """
    AMZN = 393
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(33):
        msgs.append(A(AMZN, 10 + i, 1000 + i, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 50, 1000))          # frees a slot (order 100000 discarded)
    msgs.append(D(AMZN, 51, 1032))          # the 33rd order (in top, with level)
    got, _, anomaly, errores = await drive_and_collect_bbo32_err(dut, msgs)
    assert errores == 1, (
        f"INV-OV-01: errores={errores} exp=1 (only the reduce on the level "
        f"discarded by the push-out; add-33 entered for being better than the worst)")
    assert anomaly == 0, f"INV-OV-01: anomaly={anomaly} exp=0"
    assert len(got) == 35, f"INV-OV-01: events={len(got)} exp=35"
    assert got[-1] == (393, (100031, 100, 0, 0), 1), (
        f"INV-OV-01: after the push-out the D of the best 100032 lowers it to "
        f"100031 (changed=1, without wrap): got[-1]={got[-1]}")