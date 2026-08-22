# fase3-uram (phase 3 of the master plan — URAM iteration and criterion-10 closure)

## Goal

Make the order book synthesizable and close the master's **criterion 10
(322.265625 MHz)**: turn the order table from flat registers (NSLOT=65,536 with
a parallel combinational probe — not synthesizable at 3.103 ns, blockers B1/B2,
analysis in section 7 of `docs/writeup/lessons-learned.md`) into a **URAM
design with a serialized probe and a registered level pipeline**, without losing
A SINGLE BIT of the correctness verified in phases 2–3 (30,729 bit-exact BBO
events) nor the current latency (~42 cycles of mean; target ≤ 45).

Additionally, by owner decision (2026-08-14): **mandatory trim of the 32-bit
Annex A** (remove the timestamp words w2/w3 that the book discards) — an
explicit contract change of phase-3 criterion 1 that lowers ~2 cycles/message
and ~15 % of the internal stream words.

## Scope

**In scope:**

- **32-bit Annex-A trim**: new layout `w0={type[7:0], locate[15:0], len[7:0]}`,
  `w1=msg_idx[31:0]`, `w2..=body MSB-first` (without w2/w3 of ts). Parser and
  book aligned; the book's `m_idx` sanity is captured from w1 as today. The
  64-bit Annex A is NOT touched (phases 1/2 regression).
- **Order table in URAM**: the 5 arrays `o_valid/o_ref/o_side/o_price/o_qty` are
  consolidated into a single NSLOT×86-bit array (65,536×86 ≈ 20 URAM of the
  XCKU3P) with **registered synchronous read** (address → data at 1 cycle),
  never combinational indexing. Reset by slot invalidation (pattern that does not
  block inference: never a global array reset).
- **Serialized probe with prefetch**: `lookup_ref`/`first_empty` consume
  ≤ 1 slot/cycle; the probe of up to PROBE=8 slots takes ≤ 8+2 cycles; the first
  read of the current message's hash group is emitted **during ST_BODY** (the
  hash is known before ST_APPLY) so as not to add latency to the case with body
  ≥ 4 words (pattern documented in criterion 2/6 and in
  `docs/decisions/002-retarget-kintex-xcku3p.md`).
- **Level-maintenance pipeline** (`level_add`): the current O(P) reordering in
  one combinational pass (~6–8 ns, blocker B2) is split into registered stages;
  each operation consumes ≤ 2–3 extra cycles in ST_APPLY/ST_UADD; phase-3
  invariants intact (empty level does not exist, best-first ordered list, never a
  stale price nor a wrapped qty).
- **Full regression**: 30,729 bit-exact BBO events + 640-bit depth + identical
  anomalies/cross/gaps (CHAIN-01) with the trimmed layout; full current phases
  1, 2 and 3 suites green, without fixing an obsolete count.
- **Latency**: per-type wire→BBO histogram regenerated with the new layout;
  mean ≤ 45 cycles (improvable to ~35–40 with the Annex-A trim), SEC-LAT-01
  determinism kept.
- **Synthesis artifacts (criterion 10)**: 3.103 ns constraints + tcl script
  (part `xcku3p-ffva676-2L-e`, top `itch_chain`, DW=32) updated if the new RTL
  changes ports or memory structure; `scripts/verify/synth_check.py` 10/10; WNS
  ≥ 0 from the owner's external run in `synth/reports/`.

**Out of scope (non-goals):**

- Changing the book semantics (it is phase 2/3's, replicated from the golden).
- Changing the 64-bit Annex-A layout (untouchable).
- The 32-bit Annex A loses the timestamp **only** because no consumer uses it; if
  a future stage requires it, it is a new campaign.
- Cuckoo/robin-hood hashing (linear probing suffices: peak load 0.4 %).
- Real Vivado timing closure (external to the owner, as in phase 3).
- Phase 4 (CME MDP3).

**Measured radius (2026-08-14):** the 32-bit Annex-A trim touches
`rtl/parser/itch_parser.sv` (ST_TS, `hw` counter, 3 words → 1 header word at
DW=32), `rtl/orderbook/orderbook.sv` (ST_TS, `hrem` 3→1),
`verification/testbenches/orderbook/test_orderbook.py` (helper `anexo_words`,
2 occurrences — oracle shared by phase 2 and phase3),
`verification/testbenches/phase3/{test_orderbook32,test_depth32,test_hash32,
test_hard32}.py` (2 occurrences each), `test_parser32.py`, `test_lat32.py`,
`verification/vectors/latency/latency_dw32.json` (regenerate) and the phase-3
criterion-1 contract (`specs/fase3-optimizacion/spec.md`, lines 24–25). The
hashed URAM table touches only `rtl/orderbook/orderbook.sv` + its phase-3 tests
(no top-port change: the book's external contract does not change in this
campaign).

## Constraints

- **Family/part:** UltraScale+ **xcku3p-ffva676-2L-e** (48 URAM ≈ 13.8 Mb,
  162,720 CLB LUT, 360 BRAM36K — corrected 2026-08-18 with Vivado's data; the
  original "360 URAM" was the BRAM). Retarget from the VU9P by decision 002
  (`docs/decisions/002-retarget-kintex-xcku3p.md`): the XCKU3P is supported in
  the free Vivado ML Standard; the real table inference (32 URAM288 with
  `(* ram_style = "ultra" *)`) fits with margin 32/48 ≈ 1.5×.
- **Frequency:** 322.265625 MHz (period 3.103 ns) — the campaign's raison d'être
  is that the RTL WITHSTANDS that path, not just the simulation.
- **URAM:** registered read mandatory (1 cycle latency); inference only with the
  synchronous pattern. No global memory-array reset (would kill the inference).
- **Line rate:** the phase-3 criterion-1 contract holds (1 word/cycle without
  sustained backpressure; bounded stalls ≤ 24 in the tested stretch).
- **Determinism:** same stream → same BBO **and depth** sequence, bit-exact
  against the golden, with and without backpressure.
- **Latency:** mean wire→BBO ≤ 45 cycles (current measurable baseline: 42.40
  with QB=64; the Annex-A trim must lower it, not raise it).
- **Semantics:** same anomalies, same `anomaly_count` (671 in the subset feed),
  same cross (0) and same signalled errors as phase 3.

## Surface and threats

**One new framing port in `itch_chain`:** `s_axis_tkeep[DW/8-1:0]`, inherited
from phase 1 to mark the valid bytes of the UDP payload. `orderbook` does not
change ports; the output contract (`bbo_*`, `depth_*`, `cross/anomaly/error`) is
still phase 3's.

**Domain abuse cases** (each with a Gherkin scenario):

- **Unregistered table read**: the probe indexes combinationally (broken URAM
  pattern) without functional simulation noticing. — SEC-URAM-01 pinches the
  structural delay (data valid exactly 1 cycle after the address; 1 slot/cycle
  probe) and `synth_check.py` forbids any direct `o_mem[pr_*]` read that eludes
  `rd_data`.
- **Decoupled prefetch**: the hash group is not preloaded in ST_BODY and the
  serialized lookup enters ST_APPLY → worse latency and throughput. — SEC-URAM-02
  (forced collision, K=20, same result and same lookup-cycle count as today).
- **Level pipeline with bubble**: `level_add` writes split over two cycles
  leaving a stale price or a phantom qty (phase-3 INV-OV-01) or breaking the
  "empty level does not exist" invariant (mutant DP-EMPTYSTALE/DP-TOPNCOUNT). —
  SEC-URAM-03.
- **Misaligned Annex-A trim**: parser emits 2 words and the book expects 3 (or
  vice versa) → CHAIN-01 diverges and the `m_idx` sanity corrupts. — ANX-01/ANX-02
  + CHAIN-01.
- **Changed hash semantics**: a URAM table that alters the anomalies (exhausted
  probe vs absent ref) or the atomic U (INV-U-01). — SEC-HASH-01/02, phase-3
  INV-U-01 in regression.
- **Global array reset**: the `always @(posedge clk) for (i...) mem[i] <= 0`
  pattern that kills the URAM inference without breaking the simulation. —
  guardrail: pattern audit in `synth_check.py` (criterion 7) + code review.

**What is at risk from the master:** the **322 MHz timing closure** (criterion
10, the only FAIL criterion of the phase-3 grade) and the **deterministic
latency** due to the multi-cycle apply stretch.

## Reuse

- `rtl/orderbook/orderbook.sv` — **refactored** internally (memory + probe FSM +
  level pipeline); ports and effective parameters kept (SLOT=16, PROBE=8, ND=5,
  K=19, P=32, NSYM=20).
- `rtl/parser/itch_parser.sv` — keeps the ST_TS trim and adds the valid-byte
  contract in the capture/input queue; the output format does not change.
- `rtl/itch_chain.sv` — propagates `s_axis_tkeep` to the parser; the normalized
  parser→book link and the effective parameters do not change.
- `golden_model/src/book.py` / `golden_model/itch/messages.py` — single oracles;
  the trimmed layout is defined from the oracle, NEVER with new hand offsets in
  RTL.
- `verification/testbenches/phase3/*` — the existing suites and helpers (25
  tests) are the regression battering ram; the new area imports via `sys.path`,
  does not copy (testbench README partition rule).
- `scripts/verify/mutate_orderbook.py` — gate-E runner extended with the new
  probe/pipeline mutants (PIPE-SKIP-STAGE, URAM-NO-PREFETCH, URAM-COMB-INDEX,
  LV-STALE-STAGE).

## Acceptance criteria (Definition of Done)

1. [ ] **Trimmed 32-bit Annex A**: parser and book emit/consume
     `w0={type,locate,len}`, `w1=idx`, `w2..=body` bit-exact against the oracle
     (explicit edit of phase-3 criterion 1); the worst case is still accepted
     1 word/cycle with bounded stalls.
     — Gherkin: `fase3-uram.feature` §ANX-01, §ANX-02
2. [ ] **Table in URAM**: the order table is a single NSLOT×86-bit array with
     registered synchronous read; no path indexes the memory combinationally
     (SEC-URAM-01 pinches the 1-cycle delay); reset by invalidation without
     anti-inference pattern.
     — Gherkin: §SEC-URAM-01
3. [ ] **Serialized probe + prefetch**: lookup/first_empty at ≤ 1 slot/cycle via
     registered reads; full probe ≤ 8+2 cycles; the hash group is preloaded
     during ST_BODY (SEC-URAM-02) and the phase-3 hash semantics is EXACT (same
     anomalies, full table → error, atomic U).
     — Gherkin: §SEC-URAM-02, regression §SEC-HASH-01/02/03, INV-U-01
4. [ ] **Level pipeline**: `level_add` in registered stages; bubbles ≤ 2 cycles
     per operation; phase-3 invariants intact (no stale price, no phantom, no
     wrapped qty).
     — Gherkin: §SEC-URAM-03 + regression INV-OV-01, DP-01/02, SEC-DP-01
5. [ ] **Total regression**: full current phases 1, 2 and 3 suites green with the
     new RTL; CHAIN-01: 30,729 bit-exact BBO events + 640-bit depth, anomaly=671,
     cross=0, gaps=0 with the trimmed layout.
     — Gherkin: §REG-01, §CHAIN-01
6. [ ] **Latency**: per-type histogram regenerated (deterministic JSON, double
     run identical); **mean ≤ 45 cycles** in the DW=32 chain.
     — Gherkin: §SEC-URAM-04
7. [ ] **Criterion 10 (synthesis)**: `synth/` with 3.103 ns constraints + tcl
     coherent with the new RTL; `scripts/verify/synth_check.py` 10/10 (incl. the
     synchronous-memory and no-global-reset pattern audit); WNS ≥ 0 and
     utilization (LUT/FF/BRAM/**URAM**) of the owner's run pasted in
     `synth/reports/`.
8. [ ] Lint: Verilator `--lint-only -Wall` clean in the 3 modules at DW=32 and
     DW=64 (gates B/C of verify).
     — Gates B/C

## Verification

| Criterion | How it is tested |
|---|---|
| 1 | cocotb `ANX-01` (32-bit words vs trimmed oracle) + `ANX-02` (worst case, stalls ≤ 24) + end-to-end CHAIN-01 |
| 2 | `SEC-URAM-01`: structural pinch — address emitted → data valid 1 cycle later; 1 slot/cycle probe (probe cycle counter in the driver) |
| 3 | `SEC-URAM-02`: forced collision (K=20, 9th ref of the same hash) with prefetch; same anomalies as phase 3 (bit-exact) |
| 4 | `SEC-URAM-03`: 33 adds + D (INV-OV-01 scenario) without phantom and with bubble ≤ 2; DP-01/02 bit-exact |
| 5 | full phase-1/2/3 suites + `sim-chain` (CHAIN-01 bit-exact) |
| 6 | regenerated `sim-lat`: deterministic SEC-LAT-01 + mean ≤ 45 → new JSON in `verification/vectors/latency/` |
| 7 | updated tcl/constraints + `python3 scripts/verify/synth_check.py` 10/10; owner report pasted |
| 8 | `verilator --lint-only -Wall` at DW=32/DW=64 over orderbook, itch_parser, itch_chain |

Full regime: skill `verify` (gates A–G). Gate E: `mutate_orderbook.py` extended
(mutants URAM-COMB-INDEX, URAM-NO-PREFETCH, PIPE-SKIP-STAGE, LV-STALE-STAGE +
the 22 existing re-verified against the new RTL). Gate F: new Gherkin mirror
(`specs/gherkin-espejos.json` → `verification/testbenches/uram`). Gate G: G0
(vectors only in `verification/vectors/`), G5 adversarial over the level
pipeline and the probe at campaign closure.

**Geless contracts** — invariants that can break with suite and lint green:

1. **URAM really inferred**: simulation (Verilator) does not distinguish a flat
   register from a URAM; the guardrail is the auditable synchronous pattern
   (`synth_check.py`) + the owner's synth inference (criterion 7).
2. **Trimmed layout defined in one place**: the new 32-bit Annex A exists only
   in the oracle (`anexo_words`/`message_oracle`); any hand-written offset in RTL
   or test without passing through the oracle = FAIL.
3. **Hash anomaly semantics**: the URAM table cannot change what counts as
   anomaly vs error (bit-exact against phase 3 on the same feed).

## Loop

Stop limit: **5 iterations** (the 4 of the session plan + 1 for the Annex-A
trim, now mandatory; see `docs/writeup/lessons-learned.md` §4). Cadence:
build → verify → grade chained. Suggested order: iter 1 (Annex-A trim +
regression: isolate the contract change) → iter 2 (URAM memory + serialized
probe + prefetch) → iter 3 (level pipeline) → iter 4 (re-measured latency + synth
artifacts + synth_check) → iter 5 (extended mutation + G5 adversarial review +
closure). On reaching the limit with criteria in FAIL, escalate to the owner.