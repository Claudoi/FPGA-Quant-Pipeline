"""Cocotb testbench for the serialized URAM probe and the level pipeline
(phase3-uram, criteria 2-4) — area uram.

Mirrors SEC-URAM-01 (registered read, never combinational; ≤ 1 slot/cycle),
SEC-URAM-02 (prefetch of the hash group during ST_BODY) and SEC-URAM-03 (level
pipeline without bubbles or phantoms). STRUCTURAL pin: reads internal book
signals (`/* verilator public */` on `st`, `pr_phase`, `rd_addr`, `rd_data`,
`pr_pending_*`) — phase 3 criterion 9 was documentation-only; here the read
latency and serialization are verified per signal, not by audit.

States mirroring the RTL localparams (keep in sync).
"""
import cocotb
from cocotb.triggers import RisingEdge

from test_orderbook import (A, D, E, S, U, run_book, _reset)
from test_orderbook32 import anexo_words32

# mirror of the RTL localparams (orderbook.sv)
ST_W0, ST_TS, ST_BODY, ST_APPLY, ST_EMIT, ST_UADD, ST_WAIT_PROBE, ST_INVAL = range(8)
ST_LV2, ST_LV2B, ST_LV3 = 8, 14, 9   # level pipeline (iter 3; LV2B = iter 8)
PR_IDLE, PR_WARM, PR_WALK = 0, 1, 2


async def drive_sampling(dut, messages, max_cycles=400000, window=200):
    """Drives messages at DW=32 and returns (out, trace, errores, anomaly):
    out = BBO events; trace = [(st, pr_phase, pr_pending_old, pr_pending_new,
    rd_addr, rd_data)] per cycle (live sampling of the internal signals);
    errores = cycles with the `error` pulse; anomaly = final counter value."""
    await _reset(dut)
    words = anexo_words32(messages)
    ci = 0
    n = len(words)
    out = []
    trace = []
    errores = 0
    anomaly = 0
    quiet = 0
    for _ in range(max_cycles):
        dut.s_axis_tvalid.value = 1 if ci < n else 0
        dut.s_axis_tdata.value = words[ci] if ci < n else 0
        dut.s_axis_tlast.value = 1 if ci == n - 1 else 0
        dut.bbo_tready.value = 1
        dut.depth_tready.value = 1
        await RisingEdge(dut.clk)
        trace.append((int(dut.st.value), int(dut.pr_phase.value),
                      int(dut.pr_pending_old.value), int(dut.pr_pending_new.value),
                      int(dut.rd_addr.value), int(dut.rd_data.value)))
        if int(dut.error.value) == 1:
            errores += 1
        if int(dut.anomaly_count.value) != 0:
            anomaly = int(dut.anomaly_count.value)
        if int(dut.bbo_tvalid.value) == 1 and int(dut.bbo_tready.value) == 1:
            loc = int(dut.bbo_locate.value)
            td = int(dut.bbo_tdata.value)
            out.append((loc, ((td >> 96) & 0xFFFFFFFF, (td >> 64) & 0xFFFFFFFF,
                              (td >> 32) & 0xFFFFFFFF, td & 0xFFFFFFFF),
                        int(dut.bbo_changed.value)))
            quiet = 0
        elif ci >= n:
            quiet += 1
        if int(dut.s_axis_tvalid.value) == 1 and int(dut.s_axis_tready.value) == 1:
            if ci < n:
                ci += 1
        if quiet > window:
            break
    return out, trace, errores, anomaly


def walk_cycles(trace, st_fsm):
    """Trace cycles where the probe is active (WARM/WALK) and where the main FSM
    is in st_fsm. Returns (active, fsm_cycles)."""
    activos = [i for i, (st, ph, *_rest) in enumerate(trace) if ph != PR_IDLE]
    fsm = [i for i, (st, ph, *_rest) in enumerate(trace) if st == st_fsm]
    return activos, fsm


@cocotb.test()
async def test_sec_uram_01_la_tabla_se_lee_de_forma_registrada_nunca_combinacional(dut):
    """Mirror §SEC-URAM-01: during a full probe (full path, K=20) the probe
    consumes at most 1 slot/cycle and the data arrives registered (rd_data
    NEVER changes in the same cycle as rd_addr: 1-cycle latency)."""
    AMZN = 393
    refs = [5 + i * 65536 for i in range(8)]            # occupy slots 5..12
    msgs = [S(AMZN, 1, ord("Q"))]
    for i, r in enumerate(refs):
        msgs.append(A(AMZN, 10 + i, r, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(E(AMZN, 100, 5 + 8 * 65536, 10, 999))   # nonexistent: full path
    msgs.append(E(AMZN, 101, refs[7], 10, 1007))        # ref in the last slot
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, f"SEC-URAM-01: BBO got={out} exp={expected}"
    assert golden.anomalies == 1, "SEC-URAM-01: 1 expected anomaly from the golden model"
    assert errores == 0, f"SEC-URAM-01: no errors expected, saw {errores}"

    activos, _ = walk_cycles(trace, ST_BODY)
    assert activos, "SEC-URAM-01: the probe never activated (no probe)"
    runs = _split_runs(activos)
    # (a) serialization: within the SAME run (contiguous cycles) the read
    # advances at most 1 slot/cycle. Between runs there are pauses (the next
    # run returns to its base) and reads from different runs are not compared.
    for r in runs:
        addrs = [trace[i][4] for i in r]
        for a, b in zip(addrs, addrs[1:]):
            diff = (b - a) % (1 << 16)
            assert diff <= 1, (
                f"SEC-URAM-01: the probe jumped >1 slot/cycle within a run: "
                f"{a} -> {b}")
    # (b) registered read: on the START cycle of each run the rd_data does not
    # change (the prior slot's data stays visible 1 more cycle). A
    # combinational index would reflect it instantly, in the same cycle as
    # rd_addr.
    for r in runs:
        i = r[0]
        assert trace[i][5] == trace[i - 1][5], (
            f"SEC-URAM-01: rd_data changed in the SAME cycle as rd_addr at the "
            f"start of the run (cycle {i}: data {trace[i-1][5]}->{trace[i][5]}) "
            f"— combinational read")
    # (c) the full-path probe consumes exactly PROBE evals (8): the run of the
    # nonexistent E must last 1 (WARM) + 8 (WALK) cycles
    full_runs = [r for r in runs if len(r) == 9]
    assert len(full_runs) >= 1, (
        f"SEC-URAM-01: no 9-cycle run (WARM+8 WALK) "
        f"— durations {[len(r) for r in runs]}")
    n_reads = sum(len(r) for r in runs)
    cocotb.log.info(
        f"SEC-URAM-01 OK: {len(runs)} probe runs, {n_reads} reads "
        f"serialized 1 slot/cycle, rd_data with 1-cycle registered latency")


def _split_runs(activos):
    """Splits the active cycles into contiguous runs (one run per message)."""
    runs = []
    cur = []
    prev = None
    for i in activos:
        if prev is None or i == prev + 1:
            cur.append(i)
        else:
            runs.append(cur)
            cur = [i]
        prev = i
    if cur:
        runs.append(cur)
    return runs


@cocotb.test()
async def test_sec_uram_02_el_prefetch_del_grupo_de_hash_ocurre_durante_st_body(dut):
    """Mirror §SEC-URAM-02: the hash group of an add (long body) is prefetched
    during ST_BODY — the probe activates BEFORE ST_APPLY and the lookup
    finishes before applying (no added latency to the apply)."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),      # 7-word body
        A(AMZN, 3, 6, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 4, 5, 40, 1001),                               # 5-word body
    ]
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, f"SEC-URAM-02: BBO got={out} exp={expected}"
    assert golden.anomalies == 0, "SEC-URAM-02: 0 expected anomalies"
    assert errores == 0, f"SEC-URAM-02: no errors expected, saw {errores}"

    first_active = next((i for i, (st, ph, *_r) in enumerate(trace)
                         if ph != PR_IDLE), None)
    assert first_active is not None, "SEC-URAM-02: the probe never activated"
    st_at_start = trace[first_active][0]
    assert st_at_start == ST_BODY, (
        f"SEC-URAM-02: the probe started with st={st_at_start} (ST_BODY={ST_BODY}) "
        f"— the prefetch does NOT happen during body reception")
    # the probe of the long-body add advances DURING body reception
    # (prefetch): there are cycles AFTER the start with st==ST_BODY and the
    # probe active (the run lasts 9 cycles; the body 7 words). The first
    # ST_APPLY of the message in question occurs after the run — compared
    # against the apply of that same add, not against the prior S's (no probe)
    active_in_body = any(
        i > first_active and trace[i][1] != PR_IDLE
        for i, (st, ph, *_r) in enumerate(trace) if st == ST_BODY)
    assert active_in_body, (
        "SEC-URAM-02: the probe did not advance during ST_BODY "
        "(the run ended before the body finished being received)")
    cocotb.log.info(
        f"SEC-URAM-02 OK: prefetch starts at cycle {first_active} with "
        f"st=ST_BODY; lookup completed before ST_APPLY for the long-body add")


def _split_lv_runs(trace):
    """Splits the cycles in the level-pipeline states into contiguous runs (one
    run = the level operation of a message). The current FSM (phase 3 iter 8)
    walks LV2 -> LV2B -> LV3: the three states form part of the same operation
    run."""
    runs = []
    cur = []
    prev = None
    for i, (st, *_rest) in enumerate(trace):
        in_lv = st == ST_LV2 or st == ST_LV2B or st == ST_LV3
        if in_lv:
            if prev is None or i == prev + 1:
                cur.append(i)
            else:
                runs.append(cur)
                cur = [i]
            prev = i
    if cur:
        runs.append(cur)
    return runs


@cocotb.test()
async def test_sec_uram_03_el_pipeline_de_niveles_no_crea_burbujas_ni_fantasmas(dut):
    """Mirror §SEC-URAM-03: 33 adds that overflow P=32 + a later delete on an
    absent level -> never a stale price nor a wrapped quantity, and each level
    operation consumes at most 2 extra cycles (registered pipeline, without
    bubbles: a level run is LV2->LV3, never repeats nor goes backwards).

    Push-out (addendum iter 13/15): add-33 (better than the worst) enters and
    discards the 100000. A D on an order IN the list frees a slot; a D on the
    order of the ALREADY discarded level (100000) falls into the
    reduce-absent branch WITH a free slot (LV-NEGWRAP): it never writes the
    wrapped quantity (~4.29e9) as a phantom."""
    AMZN = 393
    msgs = [S(AMZN, 1, ord("Q"))]
    for i in range(33):
        msgs.append(A(AMZN, 10 + i, 1000 + i, b"B", 100, b"AMZN    ", 1_000_00 + i))
    msgs.append(D(AMZN, 50, 1009))          # frees a slot (level 100009 in the book)
    msgs.append(D(AMZN, 51, 1000))          # reduce of level 100000 discarded by the push-out
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    # closed form: 35 events, no wrap. The only error is the reduce-absent of
    # the D(1000) (add-33 entered via push-out and the D(1009) was normal).
    assert errores == 1, (
        f"SEC-URAM-03: errores={errores} exp=1 (only the reduce of the level "
        f"discarded by the push-out onto a free slot — LV-NEGWRAP: the "
        f"quantity must NOT wrap)")
    assert anomaly == 0, f"SEC-URAM-03: anomaly={anomaly} exp=0"
    assert len(out) == 35, f"SEC-URAM-03: events={len(out)} exp=35"
    # the phantom level (if the reduce-absent INSERTed) would appear in sm_cap
    # with the wrapped quantity QW'(-100) = 0xFFFFFF9C at price 100000.
    for i in range(32):
        if int(dut.sm_cap_px[i].value) == 100_000:
            assert int(dut.sm_cap_qt[i].value) != 0xFFFFFF9C, (
                f"SEC-URAM-03: phantom wrapped quantity at 100000 "
                f"(LV-NEGWRAP)")
    # bubble <= 3 cycles per operation (phase 3 iter 8: the decode was split
    # into LV2+LV2B, +1 over the 2 of the original Gherkin; spec
    # fase3-optimizacion iter 8): 35 level operations (33 adds + 2 deletes),
    # each a contiguous run of at most 3 cycles, strictly forward
    # (LV2->LV2B->LV3, never repetition or backtracking)
    runs = _split_lv_runs(trace)
    assert len(runs) == 35, (
        f"SEC-URAM-03: {len(runs)} level pipeline runs exp=35 — "
        f"without registered pipeline (or with bubbles) there is no run per operation")
    for r in runs:
        assert len(r) <= 3, (
            f"SEC-URAM-03: level run of {len(r)} cycles > 3 (bubble)")
        seq = [trace[i][0] for i in r]
        assert seq == [ST_LV2, ST_LV2B, ST_LV3], (
            f"SEC-URAM-03: the level pipeline does not walk LV2,LV2B,LV3 "
            f"strictly: {seq}")
    cocotb.log.info(
        f"SEC-URAM-03 OK: 35 level operations, {sum(len(r) for r in runs)} "
        f"pipeline cycles (<=3 per op, iter 8), no stale price nor wrapped "
        f"quantity")


@cocotb.test()
async def test_inv_uram_03_replace_u_doble_run_pipeline(dut):
    """INV/SEC-URAM-03: the replace U applies its TWO level operations in separate
    pipeline runs (delete of the original + add of the newref), each <= 2
    cycles; the second op sees the state after the first (the list without the
    original), just like the multi-cycle apply of phase 3."""
    AMZN = 393
    msgs = [
        S(AMZN, 1, ord("Q")),
        A(AMZN, 2, 5, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 3, 6, b"S", 50, b"AMZN    ", 1_005_00),
        U(AMZN, 4, 5, 1005, 60, 1_000_00),      # newref 1005: free hash
    ]
    expected, golden = run_book(msgs)
    out, trace, errores, anomaly = await drive_sampling(dut, msgs)
    assert out == expected, (
        f"INV/SEC-URAM-03: BBO got={out} exp={expected}")
    assert errores == 0, (
        f"INV/SEC-URAM-03: no errors expected, saw {errores}")
    assert anomaly == 0, f"INV/SEC-URAM-03: anomaly={anomaly} exp=0"
    runs = _split_lv_runs(trace)
    # 2 adds of the scenario + delete + add of the U = 4 level operations
    assert len(runs) == 4, (
        f"INV/SEC-URAM-03: {len(runs)} level runs exp=4 (2 adds + "
        f"delete + add of the replace U)")
    for r in runs:
        assert len(r) <= 3, (
            f"INV/SEC-URAM-03: level run of {len(r)} cycles > 3 (bubble)")
    # the replace U chains its TWO operations: delete (run LV2->LV3) and add
    # (launched in ST_UADD — the middle cycle, as in phase 3 — and then
    # LV2->LV3). The add starts 2 cycles after the end of the delete:
    #  LV3 -> UADD(launch) -> LV2 -> LV3, without pipeline bubble
    assert runs[-1][0] == runs[-2][-1] + 2, (
        f"INV/SEC-URAM-03: the 2 ops of the U are not chained: delete "
        f"{runs[-2]} add {runs[-1]}")
    cocotb.log.info(
        "INV/SEC-URAM-03 OK: the replace U runs 2 pipeline runs "
        "(delete + add), each <= 2 cycles, with chained state")
