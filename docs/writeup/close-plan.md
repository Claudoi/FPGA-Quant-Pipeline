# Close plan — FPGA Nasdaq ITCH → URAM order book pipeline (phases 1-4)

> Close index. The **contract** (CLO-* criteria, batches, 322 ladder,
> improvements and DoD) lives in `specs/cierre/spec.md` + `gherkin/cierre.feature`.
> The evidence of that campaign: `specs/cierre/verify-report.md` (starts at
> NOT EXECUTED). This file does not redefine thresholds.
>
> Sources of truth: `AGENTS.md`, `specs/cierre/spec.md`,
> `specs/<campaign>/spec.md` + `gherkin/`, `specs/<campaign>/verify-report.md`,
> `docs/writeup/pipeline-itch-uram.md`, `docs/writeup/marks.md`. State cut-off
> date: 2026-08-20.

---

## 1. Consolidated state

### 1.1. Phases and criteria

| Phase | State | Key evidence |
|---|---|---|
| **0 — Golden ITCH** (Python) | ✅ **CLOSED** | 22 types validated, real-day evidence |
| **1 — ITCH parser RTL** (MoldUDP64 → Annex A) | ✅ **CLOSED (2026-08-20)** | **REP-02 line-rate**: real A/U stretch msgs 241733..241736, **9 stalls ≤ 24**, bit-exact output; suite 32/32 |
| **2 — Order book RTL** (URAM, BBO) | ✅ **CLOSED functional** | REPLAY-01: 17,484 BBO bit-exact; atomic replace; real subset replay (17/17) |
| **3 — Phase 3 (DW=32/URAM, real feed)** | ✅ **CLOSED end-to-end functional** | chain01 real feed: 17,484 BBO bit-exact, cross=0, anomaly=0, gaps=0; full regression green (gate E 31/31) |
| **3 — 156.25 MHz timing close** | ✅ **CLOSED** | WNS **+0.057 ns**, TNS 0, WHS +0.021 ns, URAM **32/48**, IOB **194/256**, DRC 0 (current RTL) |
| **3 — 322 MHz timing close** | ⛔ **OPEN** | internal selector path split (CLO-322-02), book **146,761 LUT** (fits); residual WNS **−3.33 ns** is output-I/O-bound (SCD 2.695 ns + OBUF 2.334 ns at −2L) |
| **4 — MDP3 (CME) parser** | ✅ **CLOSED functional** | suite 14/14 (DW=32/64), gate E 14/14 mutants, gate C verible 0 |
| **4 — MDP3 timing** | ⛔ **OPEN (over-utilized)** | DW=32 179.222 LUT / DW=64 283.659 LUT vs 162.720 available (DRC UTLZ-1); re-partition pending |
| **4 — XML↔RTL checker** | ✅ **CLOSED** | `check_mdp3_schema.py` (gate G, CLO-SCH-01): pinned XML (id=1, version=12) vs 58 structural localparams, empty diff |

### 1.2. Reference metrics (persisted, not re-derived from memory)

- Wire→BBO mean latency at **DW=32/QB=46**: **65.521 cycles = 203.3 ns @
  322.265625 MHz**, deterministic across re-executions (n = 17,484 events).
  Per-type histogram persisted in
  `verification/vectors/latency/latency_dw32.json`. Contract threshold:
  **mean ≤ 70 cycles** (RTM-LAT-01, re-derived in the iter-15 addendum).
- 156.25 MHz variant: **64b @ 156.25 MHz = 10G**; period 6.400 ns; WNS +0.057 ns.
- 322 MHz variant: **32b @ 322.265625 MHz**; period 3.103 ns; WNS −3.33 ns (open).
- Order table: **URAM 32/48** (array `o_mem` of 65,536 slots × 130 bits = 8.52 Mbit).
- Target part: **Kintex UltraScale+ xcku3p-ffva676-2L-e** (Vivado ML 2023.2 on this machine).

### 1.3. Contract amendments in force (iter 13/15) — NOT renegotiable without a re-campaign

1. **Push-out P=32** (`SEC-OV-01`): with the level list full, an add with
   `delta > 0` better than the worst **enters the top-P** and drops the worst;
   only a reduce on a dropped level (or an add worse than the worst) signals an
   error. The BBO stays bit-exact always (event 3353 of the real feed was the
   pre-fix red).
2. **Depth top-N**: bit-exact **until the 1st re-entry** of a level dropped in
   a peak >P (loc13 reaches **420 levels** on the day 2019-12-30; event 14461
   is the first re-entry); after that the depth is a **subset of prices** of
   the golden (never a ghost). BBO always bit-exact.
3. **Latency RTM-LAT-01**: threshold re-derived to **mean ≤ 70 cycles** (the
   iter-7 ≤48 was from a "lucky" stretch declared non-existent in the iter-12
   addendum of the repo; the representative measure is 65.521).
4. **K=64** (ref not truncated; OW=130 bits) and **QB=46** (latency floor;
   raising it to 64 broke the mean). The 50 B `I` NOII (2+len=52 > QB=46) is
   **drained** via `ST_DRAIN` with the beat boundary corrected (iter 15).

---

## 2. Pending work — exact scopes and risks

### 2.1. PENDING-A — Criterion 10 at 322 MHz (phase 3)

**State**: residual WNS **−3.33 ns**. The internal selector path was split
(CLO-322-02, amendment 17 of `specs/cierre/spec.md`): stage A registers
caps+predicates, stage B does `first_one` → registered `sm_bsel`/`sm_asel`,
stage C does the cap mux by that registered index + `changed`/`cross` +
handshake. Result: latency **65.521** (CLO-322-04 closed), book **146,761 LUT**
(fits the part), and the formerly critical internal route is split — no longer
critical. The residual slack is now dominated by the wrapper's **output I/O**:
`bbo_locate_o`/`depth_tdata_o` (SCD 2.695 ns with fanout 95,585 + OBUF 2.334 ns
at −2L; negative output budget at 3.103 ns). The datapath closes at
64b/156.25 MHz with +0.057 ns, which confirms the limit is the combination
**32b + 322 MHz + maximum observability/output I/O**, not the parser/book
logic.

**Objective**: bring WNS to ≥ 0 and TNS = 0 at the 3.103 ns period.

**Engineering candidates (ordered by impact/risk):**
1. **Output-I/O relief on the 322 wrapper**: reduce the pin fanout/encoding
   cost of `bbo_locate_o`/`depth_tdata_o` (re-encode the locate bus or repack
   the top-N output), and enable `phys_opt_design` automatic retiming. (The
   former selector retiming candidate landed as CLO-322-02.)
2. **Additional observability trim on the 322 wrapper**: `depth_tdata` to fewer
   bits (smaller ND on the pin), as already done with `BBO_W`; frees output
   I/O. Document as an iter-11b addendum amendment.
3. **Output pipeline**: register `bbo_tdata/depth_tdata` one extra cycle (the
   consumer already tolerates latency; it would impact the histogram —
   re-measure, re-derive RTM-LAT-01 if needed, following the usual red→green
   process).
4. **Floorplanning / placement constraint** around `u_book` (e.g. a `Pblock`
   for the 32 URAM and the selector slice) — last resort; should not be needed
   if the output-I/O relief in point 1 closes.

**Risks**: re-measure latency if the output pipeline is touched; LUT/FF and
URAM utilization must not change; simulation must stay **bit-exact** (phase 2/3
re-regression + sim-lat). **Close criterion**: `fase3_synth.tcl` (DW=32, K=64,
QB=46) returning `FASE3 SYNTH/IMPL OK` + reports in `synth/reports/` versioned.

### 2.2. PENDING-B — MDP3 timing (phase 4)

**State**: the MDP3 parser (`rtl/parser/mdp3_parser.sv`, standalone module,
parameterized DW 32 target/64 regression) is functional and mutated (14/14),
but its Vivado timing runs (CLO-M3T-01/02) are **red on both variants**: the
parser does not fit the XCKU3P — DW=32 **179.222 LUTs** and DW=64 **283.659
LUTs** vs 162.720 available (DRC UTLZ-1, `place_design` aborts in both; the
accesses `mbuf[off % 256]` expand as a combinatorial mux, 0 RAMB, 264 LUTRAM).
Re-partitioning requires a spec addendum + red→green + gate E (CLO-M3T-01
pattern).

**Objective**: reduce LUTs below the part budget and close timing (same part
`xcku3p-ffva676-2L-e`; period 3.103 ns at DW=32; 6.400 ns at DW=64) on top
`mdp3_parser` (AXI-Stream ports: `s_axis_*`/`m_axis_*`, `gap_detected`,
`error`; no observability wrapper — the module is already small). Same gate as
phase 3: fail the batch if there is slack ≤ 0.

**Candidates**: the `mbuf[off % 256]` combinatorial-mux expansion is the
priority (map toward RAM/LUTRAM or bound the offset); the field aligner (shift
+ mux by `MessageSize`/template) can be staged as a fallback if it closes
barely.

**Risks**: none on the repo (isolated module); only run hours.
**Close criterion**: `mdp3_synth.tcl` OK + versioned reports + MDP3 regression
14/14 (DW=32 and DW=64) unchanged.

### 2.3. DONE-C — MDP3 XML↔RTL checker (gate G / rigor) — CLOSED

`scripts/verify/check_mdp3_schema.py` (gate G, `CLO-SCH-01`) is implemented and
closed. It loads the SBE schema XML (templates with `blockLength`,
`templateId`, fields with offset/length/encoding), extracts from
`mdp3_parser.sv` the `template_id → length` table and the emitted fields, and
compares them against the pinned manifest (schemaId==1 && version==12, md5
`e6eb6c60…`) over the 58 structural localparams (SCHEMA_ID/VER, PKT_HDR,
MAX_MSG, EXP_BYTE + offsets O46/47/52/53) — empty diff. `test_m3sch01_*`
delegate to the script (one table). Run `python3 scripts/verify/check_mdp3_schema.py`
as gate G.

### 2.4. PENDING-D — Master-document stretch (does NOT block the close)

- **Public write-up** (blog / GitHub Pages) with latency benchmarks and
  decision 002 (Kintex xcku3p retarget): CV artifact.
- **Host AXI/PCIe interface** to dump the BBO to software: separate campaign
  (out of the scope implemented today, an explicit non-goal of the repo).
- **Real MDP3 data (DataMine)**: paid; **out-of-scope**; the MDP3 corpus is
  synthetic by design (REPLAY-03 optional if there are ever pcaps).
- **Order book port to MDP3 (campaign 4b)**: designed (Annex M) but not
  implemented.

---

## 3. Recommended execution order (batches)

> Order, 322 ladder, improvements (LUT, latency, depth, CI, 4b) and DoD
> verbatim: `specs/cierre/spec.md` §Execution order and criteria
> CLO-DOC-01 … CLO-PUB-01. What follows is the historical A–D summary.

### Batch 1 — MDP3 re-partition (isolated, does not touch closed work)

1. Re-partition the MDP3 parser to fit the XCKU3P (red→green for CLO-M3T-01/02;
   the DONE-C checker is already closed).
2. Re-run `mdp3_synth.tcl` + XDC; evidence in `synth/reports/`.

Async: at any time, PENDING-A (322 MHz) in a long Vivado window.

### Batch 2 — 322 MHz close (critical risk/pending of the prior)

3. Output-I/O relief on the 322 wrapper (the internal selector split CLO-322-02
   is already in).
4. Re-synthesis + full re-regression (phase3 10/10, parser 32/32, orderbook
   17/17, uram 7/7) + sim-lat re-measured.
5. If the output relief is not enough: trim `depth_tdata` on the 322 pin and
   re-measure latency. Do NOT resort to an output PIPELINE without documenting
   the RTM-LAT-01 impact (contract decision, requires an explicit red→green).

### Batch 3 — Docs and CI (when A and B close)

6. Paste WNS/TNS/utilization of both campaigns into their verify-reports; update
   `AGENTS.md` (phase 3 criterion 10 CLOSED if applicable; phase 4 timing
   closed).
7. Simulation CI on GitHub Actions (the Makefiles are already
   cocotb/Verilator); local pcaps out (rule G0).

---

## 4. Rules that any implementation MUST respect

- **Red→green**: do not modify spec/Gherkin to hide a failure; red first, green
  after, with evidence.
- **Gates A–G**: each campaign executes and pastes real outputs into its
  `verify-report.md`. A gate without output is not passed.
- **Golden independent of the RTL**: never generate the oracle from the RTL
  under test.
- **Real data not versioned**: only synthetic samples and small vectors in
  `verification/vectors/`.
- **Spanish + Conventional Commits** in all documentation/commits.
- **Do not lower `--Wall`**, do not omit mutants, do not turn a data omission
  into a PASS.
- The **effective QB** of phase 3 lives in `itch_chain.sv` and in the Makefile,
  not in submodule defaults. Changing a port/signal/param requires finding all
  its consumers.
- Any change in latency/backpressure requires re-measuring and re-persisting
  the histogram (RTM-LAT-01).