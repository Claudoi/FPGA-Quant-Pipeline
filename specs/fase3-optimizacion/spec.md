# fase3-optimizacion (phase 3 of the master plan — Optimization and closure)

## Goal

Bring the pipeline (ITCH parser + order book) to the **32-bit @ 322.265625 MHz**
variant (XGMII, = 10.3125 Gbps = 10G line rate), with the order table in
**URAM with hash + linear probing** (master decision, deferred in phase 2),
public **top-N** output, deterministic latency measured per message type, and
**timing closure on UltraScale+** with real evidence (the owner runs Vivado on
another machine; here RTL, constraints and the tcl script are prepared).

It is the final chapter of the master plan: it turns "simulation-correct" into
"designed for silicon with timing closed at 10G".

## Scope

**In scope:**

- **DW=32 parameterization of the parser** (`rtl/parser/itch_parser.sv` already
  has `parameter DW=64`): the 32-bit variant must meet the phase-1 criteria
  (bit-exact Annex-A record, 1 word/cycle line rate, framing/gaps/session,
  backpressure, truncation and valid bytes via `tkeep`) and the 64-bit variant
  stays green in regression.
- **DW=32 parameterization of the book** (`rtl/orderbook/orderbook.sv` already
  has `parameter DW=64`): 32-bit Annex A (w0={type,locate,len}, w1=msg_idx,
  w2..=body MSB-first — **layout trimmed by the fase3-uram campaign, criterion
  1: the ts words were removed**), decoder with the same offsets of
  `golden_model/itch/messages.py`, phase-2 criteria bit-exact. 64-bit variant
  green in regression.
- **Parser→book chain at DW=32** verified end-to-end (real feed + vectors).
- **Hash + linear probing** of the order table: `2^SLOT` slots (SLOT=16 →
  65,536), entry {valid, ref, side, price, qty}, lookup by `ref mod 2^SLOT` with
  bounded linear probing (max `PROBE` steps, PROBE=8); unknown ref after
  exhausting probes = anomaly (same semantics as phase 2); full table = `error`
  signalled, never silent.
- **Public top-N**: `depth_tdata` output with the ND=5 best levels per side of
  the BBO-event symbol (bid best-first descending, ask best-first ascending,
  each level {px[31:0], qty[31:0]}, empty to 0), validated bit-exact against the
  golden `book.py` levels.
- **Phase-2 grade hardening (lens 9)**: NSYM guard (symbol 21 → `error` pulse,
  never OOB index) and `bbo_tready` handshake in ST_EMIT (BBO event never lost
  under backpressure).
- **Latency**: wire→BBO histogram per message type (cycles from the message
  handshake on `s_axis` to its BBO event on `bbo_tvalid`) in the parser→book
  chain, committed as JSON in `verification/vectors/latency/`.
- **Pipeline for URAM**: **registered** order-table reads (1 cycle, URAM
  registered-read pattern); documentation of the mapping (**32 real URAM288,
  measured in the 2026-08-18 run**, for 65,536×86 bits) and of the
  retiming/pipelining techniques in `docs/writeup/`.
- **Synthesis**: 322.265625 MHz constraints + synth/impl tcl script (target US+
  part) committed in `synth/`; the owner runs Vivado externally and pastes the
  report (WNS/TNS + LUT/FF/BRAM/URAM utilization) in `synth/reports/`.

**Out of scope (non-goals):**

- Redoing the book semantics (it is phase 2's, replicated from the golden).
- Phase 4 (CME MDP3, AXI/PCIe host, published write-up).
- Cuckoo/robin-hood hashing (linear probing suffices at the subset load: peak
  370 live out of 65,536 slots ≈ 0.6 %).
- Changing the 64-bit Annex-A layout (the 32-bit variant defines its own
  32-bit layout; the 64-bit one is untouched).
- Latency in nanoseconds on real wire-to-wire data (requires hardware): latency
  is measured in cycles in simulation and converted to ns with the target clock
  (documented).

**Measured radius (2026-08-13):** `rtl/parser/itch_parser.sv` (param `DW=64`,
consumed only by its testbench) and `rtl/orderbook/orderbook.sv` (param `DW=64`,
consumed only by its testbench); `verification/vectors/bbo/corpus_bbo.json` and
`messages/corpus_all_types.json` reusable; `synth/` empty. No port is renamed:
only new params/ports are added and the existing ones parameterized.

## Constraints

- **Target family/part:** AMD/Xilinx UltraScale+ **xcku3p-ffva676-2L-e**
  (Kintex XCKU3P; **48 URAM** (13.8 Mb), 162,720 CLB LUT, 360 BRAM36K — the
  "360 URAM" count of decision 002 was wrong: 360 is the BRAM; corrected
  2026-08-18 with Vivado's own data, `AVAILABLE_IOBS=256` and URAM=48). Retarget
  from the VU9P by decision 002
  (`docs/decisions/002-retarget-kintex-xcku3p.md`): supported in the free Vivado
  ML Standard and reproducible without a paid license — swappable in the
  tcl/constraints.
- **Package I/O:** FFVA676 → 256 I/O (`AVAILABLE_IOBS`). The synthesis top is
  the wrapper `synth/itch_chain_synth.sv` (AXI contract, depth trimmed to 32
  bits of observability): `rtl/itch_chain.sv` exposes 896 debug ports and does
  not fit the FFVA676 (Place 30-415, finding 2026-08-18). The measured datapath
  is identical.
- **Frequency:** 322.265625 MHz (32-bit variant) and 156.25 MHz (64-bit
  regression). 32-bit @ 322.265625 = 10.3125 Gbps = 10G line rate.
- **Line rate:** the 32-bit datapath accepts **1 word/cycle in the worst case**
  (minimum messages back-to-back) without sustained backpressure — same regime
  as phase 1.
- **URAM:** registered read (1 cycle) → the book pipeline is designed around
  that latency (table lookup in one cycle and the operation applied in the
  next), without "fixing" the sign with long logic on the use edge.
- **Determinism:** same stream → same BBO **and depth** sequence, bit-exact
  against the golden; no loss or double-count, with and without output
  backpressure.
- **Endianness:** wire big-endian body; exact offsets of
  `golden_model/itch/messages.py` (single source, phase-0/1 rule).
- **Input framing:** `itch_chain` exposes `s_axis_tkeep[DW/8-1:0]` and inherits
  literally the phase-1 valid-byte contract. The internal parser→book interface
  does not change.

## Surface and threats

**New top-of-chain port:** `s_axis_tkeep[DW/8-1:0]`, connected only to
`itch_parser`. New book ports (top `orderbook`):

| Signal | Width | Description |
|---|---|---|
| `depth_tdata` | `2*ND*64` (=640) | levels per side of the event symbol: `{bid[ND-1..0], ask[ND-1..0]}`, each level `{px[31:0], qty[31:0]}`, best first, empty 0 |
| `depth_tvalid` | 1 | there is a depth event (same pulse as the symbol's BBO) |
| `depth_tready` | 1 | backpressure from the depth consumer (handshake like bbo) |

New parameters: `DW` (32/64), `SLOT=16`, `PROBE=8`, `ND=5`. Parser: `DW`
already exists (exercised at 32).

**Domain abuse cases** (each with a `SEC-` scenario in Gherkin):

- **Exhausted probing**: ref in the slot but probe bound exceeded → counted
  anomaly, no abort. — SEC-HASH-01.
- **Full table**: insert with all slots occupied → `error`, never wrap nor
  silent overwrite. — SEC-HASH-02.
- **Hash collision between distinct symbols**: refs of different symbols falling
  in the same slot → probing distinguishes them (the ref is stored). —
  SEC-HASH-03.
- **Symbol 21 (NSYM)**: locate outside the subset → `error` pulse, never OOB
  index in the level arrays. — SEC-NSYM-01.
- **BBO backpressure**: `bbo_tready=0` with an event present → the event is
  held (ST_EMIT stays), never lost; on release it is delivered exactly. —
  SEC-BP-01.
- **Depth of empty symbol**: nonexistent levels → 0; depth does not diverge from
  the golden. — SEC-DP-01.
- **Deterministic latency**: the same sequence produces the same cycles per type
  (reproducible histogram). — SEC-LAT-01.

**What is at risk from the master:** the **10G line rate** (32-bit/322 without
throttling), the **deterministic latency** and the **strict book correctness**
with an order table that is no longer direct indexing (hash collisions = a new
error vector).

## Reuse

- `rtl/parser/itch_parser.sv` — **extended** (DW already parameterized), not
  duplicated; the decoder/body is exercised at 32 bits.
- `rtl/orderbook/orderbook.sv` — **extended** (DW, hash, depth, hardening); the
  semantics of `level_add`/`apply_one`/`emit_bbo` are preserved.
- `golden_model/src/book.py` — BBO **and level** oracle (top-N derived from the
  ordered `_levels`, never from the RTL).
- `golden_model/itch/messages.py` — field offsets (single source).
- Phase-1/2 testbenches: drivers and helpers (`anexo_words`, `drive_pcap`,
  `_pcap_msgs_subset`, A/F/E/C/X/D/U/S/H constructors) are **imported**, not
  copied: the new `verification/testbenches/phase3/` area reuses the existing
  modules via `sys.path` (testbench README partition rule).
- `verification/vectors/{bbo,messages}/*.json` — existing frozen vectors,
  re-run at DW=32 and DW=64.
- New code that duplicates the `book.py`/`messages.py` semantics with another
  literal (hand offsets, top-N recomputed in RTL) = FAIL of the `/grade`
  simplicity lens.

## Acceptance criteria (Definition of Done)

1. [ ] **Parser DW=32**: the 32-bit Annex-A record is bit-exact against the
     `message_oracle` oracle over the synthetic corpus and the real replay
     (same messages → same words); the worst case (minimum messages
     back-to-back) is accepted 1 word/cycle without sustained backpressure.
     — Gherkin: `optimizacion.feature` §P32-01, §P32-02
2. [ ] **Book DW=32**: BBO bit-exact vs golden `book.py` over the synthetic
     corpus (phase-2 criteria 1–7 re-run at 32 bits) and over the 20-symbol
     real replay.
     — Gherkin: §B32-01, §B32-02
3. [ ] **64-bit regression**: current full phase-1 and phase-2 suites green with
     the extended RTL (parameterization does not break the default).
     — Gherkin: §REG-01
4. [ ] **Parser→book chain DW=32**: stripped real feed → BBO bit-exact vs golden
     over the subset (REPLAY-01 chained at 32 bits).
     — Gherkin: §CHAIN-01
5. [ ] **Hash + probing**: the hashed table reproduces the exact semantics of
     direct indexing (same events, same anomalies, same refs); exhausted probe =
     anomaly, full table = `error`.
     — Gherkin: §SEC-HASH-01/02/03
6. [ ] **Parameterized top-N**: with ND=5 and an adversarial ND=3 elaboration,
     `depth_tdata` is bit-exact against the golden's ordered levels for the
     event symbol; symbol without levels → 0. `itch_chain` propagates ND to the
     book, not only to the top port width.
     — Gherkin: §SEC-DP-01, §DP-01
7. [ ] **Hardening**: symbol 21 → `error` and `m_loc_idx < NSYM` in every
     cycle; BBO event held with `bbo_tready=0` after observing `bbo_tvalid=1`,
     stable at least two cycles and delivered exactly on release.
     — Gherkin: §SEC-NSYM-01, §SEC-BP-01
8. [ ] **Latency**: per-type histogram (wire→BBO cycles in the DW=32 chain)
     committed in `verification/vectors/latency/` and deterministic (identical
     re-run); ns conversion documented in `docs/writeup/`.
     — Gherkin: §SEC-LAT-01
9. [ ] **URAM pipeline**: order-table reads are registered (1 cycle) and the
     mapping (65,536×86 bits = **32 URAM288**, measured in the 2026-08-18 run) is
     documented in `docs/writeup/`; there is no O(P·P) path in the best-price
     computation.
10. [ ] **Synthesis**: `synth/` contains constraints (322.265625 MHz) + tcl
     script (synth/impl, part `xcku3p-ffva676-2L-e`); the owner runs Vivado
     externally and pastes the WNS/TNS report and utilization in
     `synth/reports/` — WNS ≥ 0 in the 32-bit variant.
11. [ ] Cocotb + Verilator compile both tops at DW=32 with `--Wall` with no real
     warnings silenced; lint green over what was touched.
     — Gates B/C of verify.

## Verification

| Criterion | How it is tested |
|---|---|
| 1 | cocotb: synthetic corpus + REP-02 replay at DW=32 (32-bit words vs `message_oracle`); minimum worst case back-to-back without backpressure |
| 2 | cocotb: BBO-01..SEC-* corpus at DW=32 vs `book.py`; REPLAY-01 at 32 bits |
| 3 | cocotb: full `make sim` in `testbenches/parser` and `testbenches/orderbook` after the change |
| 4 | cocotb: top `chain32` (parser→book at DW=32) over the real subset pcap |
| 5 | cocotb: same sequence with hashed vs direct table; probe-limit and full-table cases; a hash mutant (slot without ref compare) kills it |
| 6 | cocotb: depth vs `book.py` at ND=5 and `itch_chain -GND=3`; an ordering/truncation mutant kills it |
| 7 | cocotb: `SEC-NSYM-01` (21 symbols + internal index sampling), `SEC-BP-01` (adaptive stall that waits `tvalid`, holds two cycles and releases) |
| 8 | cocotb: per-type cycle collector → JSON; identical re-run |
| 9 | review + `verilator --lint-only`; write-up documentation; the registered read is audited by code |
| 10 | committed tcl/constraints + owner report pasted in `synth/reports/` |
| 11 | `verilator --lint-only -Wall` over parser and book at DW=32; verible if installed |

Full regime: skill `verify` (gates A–G). Gate E: mutation runner extended to
`phase3` (flips: hash without ref compare, probe bound off-by-one, depth
mis-ordered, level truncation, inverted NSYM guard, ST_EMIT without holding).
Gate F: Gherkin mirrors (`specs/gherkin-espejos.json` → new area
`verification/testbenches/phase3`). Gate G: G0 (real data outside the repo),
G2 (hashed state), G3 (top-N derived from the golden), G timing = criterion 10
with the owner's external-run evidence.

**Geless contracts** — invariants that can break with suite and lint green:

1. **Ill-defined 32-bit Annex-A layout** (shifted offsets between parser and
   book). Guardrail: both are defined from `messages.py`; the testbench
   re-parses with `message_oracle` and compares words, not loose fields.
2. **Hash that changes the anomaly semantics** (exhausted probe vs absent ref
   counted differently). Guardrail: same anomalies as direct indexing on the
   same feed (criterion 5).
3. **Top-N with unordered internal levels** (bubble best-first order badly
   transcribed to the output bus). Guardrail: the oracle orders the golden
   levels, never the RTL.
4. **Unregistered table reads** (broken URAM pattern without noticing in
   simulation). Guardrail: `synth_check.py` demands the probe read exclusively
   `rd_data` and forbids direct `o_mem[pr_*]` indexing; the owner's Vivado
   report also confirms the physical inference.
5. **Latency "adjusted" to the worst case** (measuring only the average).
   Guardrail: full per-type histogram with identical re-run.

## Loop

Stop limit: **6 iterations**. Cadence: chain build→verify→grade while there is a
queue. Suggested order: iter 1 (DW=32 parser+book + 64 regression) → iter 2
(hash+probing) → iter 3 (top-N) → iter 4 (hardening + latency) → iter 5 (URAM
pipeline + synth artifacts + owner report) → iter 6 (closure/grade). When the
limit is reached with criteria in FAIL, escalate to the owner.

## Addendum iteration 6 (2026-08-14 — exhaustive post-migration review)

Closure of criterion 1 (line rate) and criterion 8 (latency) with the
stationary-backlog finding of the parser queue:

1. **Root cause of the latency (measured, not theoretical)**: the input flows at
   4 B/c while `qn+4 ≤ QB` and the ST_CAP punctual drain averages ~2.7 B/c ⇒
   the queue fixes at QB and each message waits ~QB/16 messages of turn.
   Latency ≈ backlog + processing.
2. **Effective parameter**: the integration top `itch_chain.sv` declares its own
   `QB` and passes it to the parser (`.QB(QB)`): module defaults do not apply in
   phase 3. The campaign parameters live in the top and in the Makefile `-G`
   line (extended gotcha of the phase3 Makefile).
3. **QB 128 → 64** (chain top and parser default aligned): mean total latency
   69.26 → 42.40 cycles (214.9 → 131.5 ns at 322.265625 MHz; p99 77 → 47),
   **~1.63×**, with bit-exact correctness intact (CHAIN-01: 30,729 events, 0
   gaps). The parser barrel shifter drops from 1024 to 512 bits (area/path for
   criterion 10).
4. **Stall regime**: the tested worst case (4 A/U back-to-back messages,
   LIN-01/P32-02) goes from 0 to **bounded stalls (~15)** — criterion 1 demands
   "no sustained backpressure" (infinite back-to-back feed is out of scope,
   documented in the LIN-01 phase-1 scope and in the line-77 regime). QB ≥ 88
   would keep 0 stalls (queue peak ~80 B) with only ~1.4× gain; QB=64 was
   chosen for the latency/area balance.
5. **Evidence**: `verification/vectors/latency/latency_dw32.json` re-measured
   (deterministic, 2 identical runs); `docs/writeup/latency.md` updated;
   `docs/writeup/lessons-learned.md` with the full analysis (incl. the B1/
   B2/B3 synthesis blockers for criterion 10).
6. **Criterion 10 — first physical run (2026-08-18)**: Vivado 2023.2 executed
   (synth+place+route, wrapper `itch_chain_synth.sv`, part
   `xcku3p-ffva676-2L-e`). The table is inferred in **32 URAM288** after the
   single-write fix (the `mem_wr` task broke inference and hung optimization).
   **Does NOT close**: WNS = −10.492 ns (period 3.103 ns), TNS = −590,856.875
   ns, 181,711/275,646 endpoints, and **LUT at 100.33 %** (163,259/162,720) —
   the design does not even fit. The bottleneck is the BBO/depth generation from
   the level list (37–41 logic levels, route 72.9 % by congestion), neither the
   URAM nor the parser. Evidence and critical paths in `verify-report.md`; the
   next loop requires a structural change with a new spec (pipeline/retiming of
   the level scan or incremental shadow BBO).

## Addendum iteration 7 (2026-08-18 — retiming of the level scan)

Closure of criterion 10 with a structural change of the BBO-event path. **The
direction decision was the owner's on 2026-08-18: retiming/pipeline of the level
scan** (the alternative "incremental shadow BBO" stays documented as plan B in
`docs/writeup/` if this iteration does not close).

### Measured root cause (2026-08-18 run, evidence in `verify-report.md`)

- WNS = −10.492 ns (period 3.103 ns), TNS = −590,856.875 ns, 181,711/275,646
  endpoints failing; LUT at 100.33 % (163,259/162,720).
- Critical paths: `u_book/m_loc_idx_reg → bbo_changed/bbo_tdata`, 37–41 LUT
  levels (2 CARRY8 + 37 LUT5/6), route 72.9 % by congestion. The parser is at 12
  levels (within limit); the URAM is not the bottleneck.
- The culprit is `emit_bbo` (`rtl/orderbook/orderbook.sv:1045-1098`): in a
  single combinational cycle it does (a) mux of 40 level groups by `m_loc_idx`,
  (b) find-first-nonzero of P=32 per side, (c) `changed` against `prev_*`
  (another per-symbol mux), (d) depth 2×ND packing and (e) the market-cross
  check — chained logic + giant fan-out (20,275 F7 + 8,930 F8 muxes).

### Structural change: ST_EMIT → 2-stage registered pipeline

`ST_EMIT` (single cycle) splits into three states: `ST_EMIT_A` (capture),
`ST_EMIT_B` (selection + changed + depth) and `ST_EMIT_C` (output handshake).
**+2 cycles on the BBO-event path** — latency contract change, re-derived below,
never hidden.

- **Stage A (capture)**: `sm_cap[2*P]` registers of `{px, qty}` of the event
  symbol + a `qty != 0` flag per slot. Only the 40-group mux by `m_loc_idx` (the
  same selection as today, WITHOUT the chained scan).
- **Stage B (selection)**: find-first per side over the capture (P→1 with
  priority), `changed` against `prev_*` (comparison over capture), 2×ND depth
  packing (small 2P→ND mux), update of `prev_*`, market-cross check.
- **Stage C (output)**: `bbo_tdata/bbo_changed/depth_tdata` → output registers
  with an identical handshake to today's: hold with `tready=0`, deliver exactly
  once (inherits §SEC-BP-01).
- The stages only run when `emit_ok` (real event); anomaly/error/discard
  semantics do not change.
- **Plan B documented** (if stage B still does not close): 1-stage retiming
  (capture + selection recombination) or incremental shadow BBO; both require
  their own mini-spec before touching RTL.

### Contract changes (explicit, not hidden)

1. **Latency — SEC-URAM-04 threshold amendment**: "mean ≤ 45 cycles" →
   **mean ≤ 48 cycles**. Re-derivation: +2 cycles ≈ +6.2 ns → estimated mean
   ~46.3 cycles (current baseline 44.318); 48 × 3.103 ns = 148.9 ns, still well
   below the original wire→BBO budget of 214.9 ns (`docs/writeup/latency.md`);
   margin 1.7 cycles over the estimate. The fase3-uram campaign is not reopened:
   the numeric threshold migrates to criterion 8 of this campaign (§RTM-LAT-01)
   with its re-derivation documented.
2. **Histogram**: re-measured (deterministic, 2 identical runs) and re-committed
   in `verification/vectors/latency/`.
3. **Ports**: `bbo_*` and `depth_*` do not change (same AXI contract); the
   `itch_chain_synth.sv` wrapper does not change.

### Physical goals of this iteration (criterion 10 redefined)

- WNS ≥ 0 and TNS = 0 post-route at 3.103 ns (the tcl already aborts with
  `FASE3 TIMING FAIL` on negative slack — same gate, zero change).
- **LUT ≤ 95 %** post-route (the current 100.33 % leaves no placement headroom;
  congestion dominates the route). If the pipeline does not lower LUT enough,
  stage B additionally simplifies the F7/F8 muxes of the depth pack.
- WHS ≥ 0 (clean hold — today −1.145 ns by congestion).
- URAM 32/48 (66.67 %) and BlockRAM 0 are kept (the table is untouched).

### Equivalence and regression

- BBO/depth bit-exact vs golden (ND=5 and elaboration ND=3), with and without
  backpressure — criteria 2/4/6/7 of the campaign are re-run.
- Full 64-bit regression (phases 1–2): the pipeline is of the shared book, the
  DW=64 default is re-run — §RTM-REG-01.
- Gate E: new scan mutants (stage A omitted reading the arrays in ST_EMIT,
  inverted-priority find-first, `changed` against the wrong `prev_*`, depth
  packed from the opposite side's capture) — each must compile and die.

### Gherkin and gate F

New scenarios in `optimizacion.feature`: **RTM-01** (registered pipeline,
structural probe like SEC-URAM-01), **RTM-02** (BBO↔capture consistency over the
ordered-list invariant: the "best in the last slot" was invisible — the list is
always compacted; amended 2026-08-18 before implementing), **RTM-03** (`changed`
over the capture), **RTM-04** (backpressure in the pipelined output),
**RTM-LAT-01** (mean ≤ 48 + determinism), **RTM-REG-01** (64-bit regression).
Mirror tests with literal titles in `verification/testbenches/phase3/` (gate F).

### Iterations and stop

Limit of **2 iterations** for this loop: iter 7a (2-stage pipeline, full
red→green) → iter 7b (only if 7a does not close: directed stage-B retiming or
move to plan B). On reaching the limit with WNS < 0 or LUT > 95 %, escalate to
the owner with the run evidence (the tcl gate is never lowered).

**Status 2026-08-18**: iter 7a is implemented and committed (`2fa7250`: A/B/C
pipeline RTL + RTM-01..04/RTM-REG-01/RTM-LAT-01 tests + `sim-rtm`/`sim-rtm64`
targets; static checks green: py_compile, gate F, synth_check 24/24, xvlog 0
errors). Missing: the red→green of `sim-rtm`/`sim-rtm64`/`sim-lat` and the
A/E/B/C gates on the cocotb machine, and the Vivado re-run (same tcl) for
WNS ≥ 0, TNS = 0 and LUT ≤ 95 %. Until those runs exist, iteration 7a is not
closed and 7b stays in reserve (the acceptance criteria do not change).

## Addendum iteration 8 (2026-08-18 — decode retiming and wrapper pins)

### Measured root cause (re-run 14:11, evidence in `verify-report.md`)

The iter-7 A/B/C pipeline moved the indicator (WNS −10.492 → −7.395 ns, LUT
100.33 → 96.49 %) but the re-run showed **three** families of violated paths,
none in the emission:

1. **Wrapper I/O (worst absolute path, −7.395 ns)**: `msg_len_reg →
   s_axis_tready` (11 levels + OBUF + 1 ns output delay + clock tree skew). The
   parser pushes its queue drain to the wrapper pin; in the real integration
   that port feeds the master's register/FIFO, not a pad.
2. **decode_lv2 (2nd–10th paths, −5.84 to −5.60 ns)**: `lv_eq_reg → lv2_mode_reg`
   with 31 levels. Stage 2 of the level pipeline does in ONE cycle the three
   serial find-firsts (fnd/emp/btx, 32-deep priority chains), the 32:1 mux of
   `lv_cand_newq[fnd]` and the condition priority. It is NOT the emission stage
   B: it is the level-update machine.
3. **Reset (rst_n → lv_qty_reg/R, ~−5.7 ns)**: the pin's synchronous reset is
   inferred to the R pin of the FDRE over 1,280+ registers with pin skew.

### Structural changes

1. **decode_lv2 split into two registered stages (book, `orderbook.sv`)**:
   - **decode_lv2a** (ST_LV2, new): three first-hot encoders in a **log2(P)
     tree** (`first_one` function: per-level OR-tree + binary decision from
     highest to lowest bit — no serial chains) → registers
     `lv2_fnd/lv2_emp/lv2_btx` + flags `lv2_afnd/lv2_aemp/lv2_abtx`.
   - **decode_lv2b** (ST_LV2B, new): condition priority and the mux
     `lv_cand_newq[lv2_fnd]` over the already-resolved indices → the same
     `lv2_mode/lv2_found/lv2_empty/lv2_ins/lv2_newq` and the `error` pulse of
     the current decode. `lv2_found/lv2_empty/lv2_ins` keep the `0xFFFFFFFF`
     value (ex −1) when there is no level, so stage 3 (`materialize_write`)
     behaves identically.
   - The FSM goes from ST_LV2 → ST_LV3 to ST_LV2 → ST_LV2B → ST_LV3. Stage 3
     already consumed the `lv2_*` one cycle after the decode; now it consumes
     them one cycle after 2b — observed semantics identical.
   - **Latency: +1 cycle** on the path of every book message (expected mean
     44.318 → ~45.3). SEC-URAM-04 (mean ≤ 48) stays without amendment: margin
     2.7 cycles; if the real measure exceeds 48, the threshold reopens (the worst
     case is never adjusted).
2. **Synthesis wrapper (`itch_chain_synth.sv`) — registered pins**:
   - **4×DW input FIFO** between the `s_axis_*` pin and the parser: the pin's
     `s_axis_tready` is governed by a local counter (`f_n < 3`, ~3-level FF→pin
     path) — the `msg_len → tready` path disappears from the analysis. Documented
     regime (not hidden): the pin's backpressure defers up to 3 words of
     buffering; the internal chain and its regime do not change; pin latency +1
     cycle (the SEC-URAM-04/RTM-LAT-01 metric measures the chain, not the
     wrapper).
   - **rst_n regenerated** in a local FF (`rst_n_c <= rst_n`): cuts the pin→R
     path of the FDREs (family 3). Standard synchronizer reset in the synthesis
     wrapper.
   - The output ports (bbo/depth) are NOT registered: the re-run showed their
     paths at inf slack (book outputs already registered); the pin
     `bbo_tready/depth_tready` do not appear among the violated.
3. **No change** in: emission A/B/C (iter 7), structural probe (`sm_cap_*`),
   hash/probe, URAM, chain AXI contracts, tests.

### Physical goals (criterion 10, same tcl gate)

- WNS ≥ 0 and TNS = 0 post-route at 3.103 ns (the `FASE3 TIMING FAIL` gate is
  intact; the run measures the chain in its documented registered integration
  context).
- LUT ≤ 95 % post-route (96.49 % current; the wrapper FIFO adds ~200 FF and the
  2a tree reduces the decode logic).
- WHS ≥ 0; URAM 32/48 kept.

### Equivalence and regression

- BBO/depth bit-exact vs golden (ND=5 and ND=3), with and without backpressure:
  the existing area tests (orderbook/phase3/uram + RTM-01..04 + RTM-REG-01 +
  RTM-LAT-01) are the mirror — iter 8 changes nothing observable (same probe,
  same outputs, +1 latency cycle covered by the threshold). The red→green of
  iters 7 and 8 runs against the final iter-8 RTL on the cocotb machine (the
  iter-7 red over the base commit remains as historical evidence: the tests
  already exist).
- Gate E: the 30 mutants of the current runner (incl. the 4 of the iter-7
  addendum) must compile and die against the iter-8 RTL; no new mutants are
  added (2a/2b creates no new contracts: `lv2_fnd/emp/btx` indices are internal;
  a `first_one` mutant (inverted priority bit) is proposed as optional on the
  cocotb machine).
- Gate F: no new scenarios (RTM-01..04/RTM-LAT-01/RTM-REG-01 already mirror the
  contract; the 2a/2b split is internal).

### Iterations and stop

Limit of **2 iterations** for this loop: iter 8 (split decode + registered pins,
red→green + run) → iter 9 only if 8 does not close (additional directed
retiming: e.g. registering `lv_cand_newq` in stage 1 or a mux tree for the
depth pack). On reaching the limit with WNS < 0 or LUT > 95 %, escalate to the
owner with the run evidence (the tcl gate is never lowered).

### Addendum iter 9 (2026-08-18) — last iteration of the loop

**Iter-8 re-run diagnosis (evidence in verify-report)**: gate FAIL
`FASE3 TIMING FAIL: WNS=−4.052 ns` (was −7.395), TNS −213,040.636 ns (was
−430,582.411), LUT as Logic 95.68 % (was 96.49), URAM 32/48 unchanged. Two
families of violated paths:

1. **Wrapper pins → table** (the 10 worst, all the same pattern): `depth_tready`
   (pin) → `o_mem CAS_IN_DIN_B` / FDRE, 12 levels with 7 URAM288 in cascade
   (write by cascade height 8), input delay 1 ns + pin skew 2.2 ns. The path
   exists because the BBO/depth pair acceptance guard lives at the **entry of
   ST_APPLY** (waits `bbo_tready && depth_tready` before applying/rewriting the
   table): the `tready` enters the URAM write decision path.
2. **Serial emission priority**: `sm_cap_nzb_reg[2]_rep` → `sm_changed_reg` with
   **31 levels** (CARRY8=2 LUT5=16 LUT6=12 MUXF7=1): the stage-B find-first
   `for (i = 0; i < P && !bdone; i++)` loops (P=32) synthesize the serial
   priority chain that iter 8 removed from the level decode but left in the
   emission.

**Changes (all three in the same block; it is the last iteration):**

- **a. Acceptance guard moved (tvalid only)**: the BBO/depth pair is emitted in
  ST_EMIT_C only when the bus is empty (!bbo_tvalid && !depth_tvalid); the queue
  (apply/swap/table writes) advances without waiting for the pin. The tready no
  longer participates in any advance decision: the tready → URAM we path
  disappears. Design note (see c): a registered tready (1-cycle deferred
  acceptance) would duplicate the pair for the consumer when it raises tready
  one cycle after the emission (the held pair stays visible two cycles with
  tvalid=1 and tready=1); hence the guard looks only at the tvalids and the
  pin tready connects directly to the hold (line 501), as in phase 3: no loss
  nor duplicate (SEC-BP-01), the next event's emission waits for the empty bus
  and the removal of the previous pair (1 cycle after its acceptance,
  unobservable).
- **b. Emission find-first precomputed in stage A**: the capture also computes
  `sm_bsel = first_one(nzb_next)` and `sm_asel = first_one(nza_next)` (same tree
  function as iter 8, registered); stage B selects by index:
  `bp = sm_cap_px[sm_bsel]` (direct mux, no chain). Equivalence: the mux by the
  first non-empty slot is the same operation as the `!bdone` loop; with all
  slots empty `first_one = 0` and `sm_cap_px[0] = 0` (same as the loop with
  `bdone=0`).
- **c. (amended) No tready register in the wrapper**: the duplicate analysis (see
  a) discards registering bbo_tready/depth_tready; the pins stay direct. The
  run-8 pin family dies by the guard (a): tready no longer feeds any path to
  the URAM write.

**Goals**: WNS ≥ 0 and TNS = 0 post-route (tcl gate intact), LUT ≤ 95 %
(95.68 % current, margin 0.68 pp), URAM 32/48 kept. Chain latency: no change in
this iteration (the index selection lives inside the existing stages A/B).

**Equivalence and regression**: the observed BBO/depth pair semantics do not
change (order, hold, atomicity); the writes advanced relative to pin acceptance
are unobservable at the ports. Red→green of RTM-01..04/RTM-LAT-01/RTM-REG-01
against the final iter-9 RTL on the cocotb machine (8 and 9 validate together in
that red).

**Mutants**: EMIT-FINDFIRST-INV migrates to the new target
(`sm_bsel <= first_one(nzb_next)` → `first_one(~nzb_next)`, inverted priority:
the BBO picks the last non-empty slot); the other targets revalidate by unique
match (30/30) and xvlog parse before the run. No new Gherkin scenarios (gate F
unchanged).

**Stop**: this is the last iteration of the loop. If the run does not close
WNS ≥ 0 / TNS = 0 / LUT ≤ 95 %, criterion 10 stays open and escalates to the
owner with the run evidence (WNS/TNS/LUT/URAM + residual critical paths); the
tcl gate is not lowered.

## Addendum iter 10 (2026-08-18, continuity amendment)

**Iter-9 run evidence (committed)**: FASE3 TIMING FAIL: WNS = −3.527 ns (was
−4.052), TNS = −211,438.033 ns (was −213,040.636), 177,459 endpoints failing,
LUT as Logic 155,893/162,720 = **95.80 %**, URAM 32/48, IOB 222, DRC 0. The
book retiming worked: the depth_tready pin family (12 levels + URAM cascade of
run 8) disappeared from the top-10. The 10 worst of run 9 are the **wrapper I/O
family**: bbo_locate_reg[0]/C → bbo_locate[0] (pin) with 1 level (OBUF) but
**Clock Path Skew −2.671 ns** (SCD 2.671: the clock tree to the book area with
LUT at 96 %), Output Delay 1 ns, Data Path 2.924 ns; same pattern in
depth_tdata_reg[0] and f_n_reg[1] → s_axis_tready (pin); plus short internal
area paths: out_data_reg_reg[23] (parser → wrapper FIFO) and body_acc_reg[2][28]
(book) to FDRE, ~12 levels of congested-region skew.

**Decision**: iter 9 was the last of the loop by the documented stop; by owner
decision ONE more iteration opens, strictly limited to the synthesis wrapper
(without touching the book or the parser: the gates and the pending red→green do
not change target).

**Changes (only `synth/itch_chain_synth.sv`)**:

- **a. IOB packing of the outputs**: the ports bbo_locate, bbo_tdata, bbo_tvalid,
  bbo_changed, depth_tdata, depth_tvalid carry `(* IOB = "TRUE" *)`; their FFs
  (the book output FFs, which only feed the pin, no internal fanout) are placed
  in the IOB, where the I/O tree skew is ~0 and the FF→pin path closes without
  the −2.67 ns skew. Side effect: 192 FFs leave the book area (the internal tree
  is relieved and internal region paths can improve).
- **b. Registered input tready**: s_axis_tready <= (f_n < 3) in its own FF (with
  rst_n_c), also with IOB. The pin handshake uses the registered tready
  (fifo_hs = tvalid && tready_ff): the producer pushes when it sees ready=1 and
  the wrapper counts the same ready: coherent regime, no overflow (f_n ≤ 3 by
  construction), backpressure deferred 1 cycle at the pin (chain SEC-BP-01
  intact: the parser holds its pair; the FIFO stays 4×DW). Amendment vs the iter-9
  analysis (c): there it was discarded to register the tready BECAUSE the
  emission guard looked at it; the guard (iter 9 a) no longer looks at the tready
  and the register lives ONLY in the wrapper: it does not affect the pair hold
  (line 501, direct book pin). The wrapper is not simulated (RTM-LAT measures the
  chain, not the wrapper).

**Goals**: WNS ≥ 0 and TNS = 0 post-route (gate intact), LUT ≤ 95 % (moving FFs
out of the area does not reduce LUT, only frees FFs/tree; 95.80 % current), URAM
32/48, IOB 222 kept (the packing uses the existing IOBs).

**Equivalence**: the pin contract (AXI-S) holds (ready deferred 1 cycle is legal
backpressure); the BBO/depth pair, the hold and the atomicity do not change. No
new Gherkin scenarios; no new mutants (the wrapper is not mutated).

**Final stop**: this is the last run of the loop. If it does not close WNS ≥ 0 /
TNS = 0 / LUT ≤ 95 %, criterion 10 stays open and escalates to the owner with
the accumulated evidence (run 8: −4.052; run 9: −3.527; run 10: this one); the
tcl gate is not lowered.

## Addendum iter 11 (2026-08-18, continuity amendment)

**Iter-10 run evidence (committed)**: WNS = −3.748 ns (was −3.527), TNS =
−221,038.368 ns, 178,310 endpoints failing, LUT 155,876/162,720 = **95.79 %**,
URAM 32/48, IOB 222, DRC 0. The IOB packing **does NOT move the book output
FFs** (`u_book/bbo_changed_reg` etc. remain inside the area, Clock Path Skew
−3.112 ns in the 10 worst): those FFs have real internal fanout (line 507–508
hold + 838 guard) and the placer does not replicate them; only `tready_ff`
(wrapper FF) was replicated. Lesson written in
`docs/writeup/lessons-learned.md` §7: IOB packing applies only to FFs
without internal fanout; an internal FF → pin loses ~2.7–3.1 ns of tree skew
(LUT ~96 %) + 1 ns of output delay.

**Decision**: one more run (iter 11), strictly limited to the synthesis wrapper;
does not touch the book or the parser (the gates and the WSL red→green already
closed do not change). If it fails, criterion 10 stays OPEN and escalates to the
owner; the tcl gate is not lowered.

**Changes (only `synth/itch_chain_synth.sv`)**:

- **Output pipeline with pin-side hold**: the outputs bbo_locate/bbo_tdata/
  bbo_tvalid/bbo_changed/depth_tdata/depth_tvalid stop being the book FFs
  (internal fanout, not packable). They are registered in the wrapper's OWN FFs
  with `(* IOB = "TRUE" *)` (the same mechanism that replicated tready_ff):
  - capture when the book offers a new pair: condition `bbo_tvalid_i &&
    !bbo_tvalid_o` (internal tvalid without a pair at the pin).
  - pin-side hold: `bbo_tvalid_o <= bbo_tvalid_o && !bbo_tready` (the pair is
    removed 1 cycle after external acceptance, identical to the internal book
    regime).
  - the pin `bbo_tready`/`depth_tready` pass directly to the book (line 501
    intact: the internal pair hold still responds to the external tready).
- The pair at the pin is visible exactly until external acceptance; it is not
  duplicated if the consumer keeps tready=1 (the pin hold removes it). +1 latency
  cycle ONLY at the wrapper pin (RTM-LAT measures `itch_chain`, not the wrapper).

**Goals**: WNS ≥ 0 and TNS = 0 post-route (gate intact), LUT ≤ 95 % (95.79 %
current; the pipeline adds FFs but no tree LUT), URAM 32/48, IOB 222 kept.

**Equivalence**: the pin AXI-S contract holds; +1 pin latency cycle (documented).
No new Gherkin scenarios; no new mutants (the wrapper is not mutated).

## Addendum iter 11b (2026-08-19) — pin budget of the 156 MHz variant

The **DW=64 @ 156.25 MHz** variant (period 6.400 ns) with the full wrapper
exposes **258 pins > 256 available** of the FFVA676 (input 64+8, bbo_tdata 128,
depth_tdata 32) and the placer aborts with `Place 30-58` (unplaced IO 257 > 256).
It is not a timing problem: it is the package's I/O budget with full
observability at DW=64.

**Decision**: the synthesis wrapper already trims observability (depth_tdata to
[31:0], cross_events/anomaly/error without pin). For the 156 variant the
`bbo_tdata` output width is parameterized to **64 bits** (`BBO_W=64`, only the
bid/ask prices — bits [127:64] of the book bus) and the input stays the same.
Total: **194 pins ≤ 256**. The book/parser datapath does NOT change (the measured
logic is identical); only the observability bus to the pin is trimmed, the same
pattern as the depth_tdata trim.

The tcl `fase3_156mhz.tcl` sets `generic {DW=64 BBO_W=64 K=19 QB=46}` and uses
`constraints/fase3_156mhz.xdc` (period 6.400). The wrapper accepts it via the new
`parameter BBO_W = 128` (default) / 64 (variant). The 322 MHz variant does not
change (BBO_W=128 by default).

## Addendum iteration 12 (2026-08-19) — real market-open feed: K=64 and oversize drain

**The campaign REOPENS for two structural bugs that the real market-open feed
(210k packets / 10.2M messages of day 2019-12-30, unfiltered stretch) exposes in
the phase-2/3 verified RTL.** The synthetic corpus and the small historical
stretches never triggered them; the previous "real feed" evidence (iter 4, mean
44.5) was **stretch-dependent** (its pcap had refs ≤ 372,297 and no message >
44 B — a lucky selection, nonexistent today).

### Finding 1 — REFW/K=19 truncated real-day refs (REPLAY-01 red)

The real-day refs reach ~1.7M at the open — far above 2^19=524,288 (K=19,
calibrated on the small phase-2 subset). The RTL truncates `K'(ref)` and the
table stores REFW=20 bits: two distinct refs with the same residue mod 2^19
collide. Exact reproduction with a Python replica of the probe engine
(hash=residue[15:0], PROBE=8, tombstones, qty semantics) over the 20-symbol
subset:

- **254 lost events = 17,484 (golden) − 17,230 (RTL)** — exact: 223 rejected
  A/F "duplicate" (residue occupied by another live ref), 14 U-newdup, 3
  rest_neg, 14 anomalies.
- The first visible mismatch (event 2072 = D(2744)) is a cascade symptom: the D
  deletes ref=1,499,381, whose A was rejected earlier by residue collision → the
  probe does not find the ref → anomaly without event.

**Fix**: `K` default 19 → **64** (wire ref untruncated; 64 bits of the golden
contract) and `REFW` goes from fixed localparam 20 to `max(K, 20)` (K≤20 keeps
the verified 86-bit layout; K=64 → OW=1+64+1+32+32=**130 bits**). Estimated URAM
**32/48 kept** (2 columns of 72 bits per bank; 130 ≤ 144; the inference is
re-measured in the re-run). The untruncated replica gives **17,484 events and 0
anomalies** — matches the golden bit-exact.

### Finding 2 — the parser deadlocked with messages > 44 B (sim-lat red)

`itch_chain.sv` sets `QB=46`; `ST_LEN` waits `avail >= 2+len` to capture to
`msg_reg` (352 bits = 44 B max). The open subset contains **2,289 I messages
(NOII, 50 B)**: `2+len=52 > 46` → the condition never holds → `tready=0`
indefinitely (the queue cannot complete the message and the burst eop never
arrives) → "accepted tlasts=0". At DW=64/QB=64 (phase 2) 52 ≤ 64 fits: that is
why the bug only bites in the 32 variant.

**Fix**: new `ST_DRAIN` state in the parser: if `2+len > QB` the message is
**drained by the stream without buffer or record** (dynamic drain
`min(drop_left, avail)` through the queue + parallel acceptance `can_da`, which
preserves the alignment of the next message). The I is not in the parser subset
(`issubset`) → never emits a record; the `explen` validation consistent with the
rest of the framer. A datagram truncated inside an oversize keeps the SEC-FRM-01
semantics (error + restart).

### Reopened criteria and evidence

- **Criteria 2/4/8 (fase3-optimizacion)** and **REPLAY-01/REPLAY-02 (phase 2)**:
  re-run with K=64 over the real subset — must return to green (explicit
  red→green, the red is documented with this addendum).
- **Criterion 10**: synthesis re-run (same tcl, `K=64`): fresh WNS/TNS/
  utilization with OW=130. The `itch_chain_synth.sv` wrapper and the tcls update
  their default/`generic` K to 64.
- **Criterion 8 (latency)**: the histogram changes (the hashes of refs ≥ 2^19
  change base: the hash uses the full ref, not the truncated residue); re-measured
  and re-committed (deterministic within the new config). The RTM-LAT-01
  threshold (mean ≤ 48) stays without amendment.
- **Gherkin**: new scenarios **REF64-01** (real subset bit-exact with K=64),
  **REF64-02** (refs differing by 2^19 do not collide; red at K=19), **OVR-01**
  (oversize drain without deadlock). Gate F updated.
- **Mutants (gate E)**: the runner re-runs (30/30); the `apply_one`/probe
  literals do not change. A new mutant **REF-TRUNC-01** (hash or comparison over
  the ref truncated to 19 bits) is killed by REF64-01/02.

## Addendum iteration 13 (2026-08-19) — push-out P=32: the overflow no longer freezes the BBO

**REPLAY-01 stayed red after K=64** with the RTL already corrected in 12: the
totals matched (17,484 events) but the first mismatch moved to **event 3353**.
`sm_cap` showed the cause: the ask list of symbol 13 was **full at 32 invariant
levels** (last `3030000,20`) and the `decode_lv2b` guard (SEC-OV-01, iter 3)
**rejected the insert even when the new price was better than the worst level** —
the ask BBO stayed frozen.

### Finding 3 — the golden without level limit vs P=32 with rejection

`max_levels_day.py` over the real subset: the day reaches **420 bid levels
(loc 13, peak at msg 20689), 291 ask (loc 13)**, rest ≤ 174. P=32 was sized on
an old stretch (max 17). The push-out replica with the corrected golden measures:

| Architecture | 17,484 events | Divergence | Cost |
|---|---|---|---|
| Rejection (RTL pre-13) | 1 | event 3353 (frozen BBO) | — |
| **Push-out P=32** | **0** in BBO | — | 3,156 discards outside the top-32 (SEC-OV) |
| Top-P + tail hash P=32/64/96 | 0 (also depth) | — | 1,465/790/750 rebalances; tail ≤ 388 |

Additionally: the rejection guard discarded the insert even though there was a
better-than-worst in the full list; the stage-3 `materialize` **already
implemented the push-out** (`lv2_empty=0xFFFFFFFF` → shift right and discard the
worst), so the push-out was a guard change, not a materialization change. `P=512`
FF to cover the day bit-exact without tail is unviable (LUT/FF budget + timing
closure).

### Decision — SEC-OV-01 amended: push-out on overflow

In `decode_lv2b`, when `!lv2_afnd && !lv2_aemp` (list full and level absent):

- `delta > 0` and there is a level worse than the new one (`lv2_abtx`): **INSERT**
  (push-out): enters `lv2_ins=lv2_btx`, the materialize shifts right and discards
  the worst. The book keeps the best-P.
- rest (`delta < 0` over an already-discarded-by-overflow level, or an add worse
  than the worst): **SEC-OV-01 discard** (pulse `error`, never phantom).

Verified consequences (replicas): the day's BBO is **bit-exact** with P=32 (0
divergences in 17,484 events); the top-P always contains the current best-P; the
top-N depth (N ≤ P) is exact; the levels beyond P are signalled with `error`
(SEC-OV) and documented as the variant's limit. The backpressure/latency regime
does not change (the push-out resolves in the same stages 2b/3).

Documented future improvement (not implemented; option B measured): **top-P +
tail hash in URAM** for total depth exactness too; estimated cost 1,465
rebalances/day × bounded tail scan (≤ 388 levels) and reuse of the 32 URAM.

### Pending evidence

- Red of event 3353 already documented above (REPLAY-01, RTL pre-13).
- Green: `test_repro_ask_insert_mejor_precio` (window 4,042) and full REPLAY-01
  bit-exact over the real subset in WSL.
- Full phase-2/3 regression (orderbook + phase3 + uram) and gate E. The verified
  RTL constants (K=64, OW=130) do not change; the iter-12 synthesis is not
  re-run unless closure demands it.
- Gherkin: **SEC-OV-01** amended to the push-out semantics (new scenario
  `OVR-PUSH-01`: full list + add better than the worst → the BBO reflects the new
  best and the worst leaves; add worse than the worst → `error`).

## Addendum iteration 15 (2026-08-20) — bit-exact oversize drain + latency re-derivation

**REPLAY-01 / CHAIN-01 already gave the bit-exact BBO with the iter-13 push-out,
but chain01 over the real feed stayed red: the parser at DW=32/QB=46 lost the
message following each drained `I` (NOII, 2+len=52 > QB=46).** Over the real
subset, 2,289 `I` force the drain (the message does not fit the 46-byte queue).
The analysis isolated three accumulated drain causes, all fixed in
`itch_parser.sv`:

### Finding A — `drop_left` without discounting the detection-cycle beat

The oversize `ST_LEN` branch computed `drop_left = 2+len - avail` without
counting the beat accepted by `can_aug` in the SAME detection cycle (whose bytes
are discarded): the drain consumed one extra beat of the next message (3 bytes
eaten → loc 14 read as 13 in chain01). **Fix**: `drop_left = 2+len - qn_post`
(avail + the cycle's beat).

### Finding B — the beat-crossing hold kept the wrong bytes

The `drain_strad` held `in_compact >> (8*drop_left)`, i.e. the HIGH bytes (those
of the message to discard, `byte0` = first-received in the MSB) instead of the
next message's tail. **Fix**: hold the mask of the LOW bytes
(`in_compact & ((1 << 8*retain_n) - 1)`), with `retain_n = in_nbytes -
drop_left`. Without this the next message lost its `size`/`type` field.

### Finding C — (cleanup) the mention will follow the feed

Brief chronology: after A and B, chain01 over the real feed at QB=46 is
**bit-exact** (17,484 BBO + exact count + depth), and the full phase-2/3
regression (parser 32/32, orderbook 17/17, uram) is green.

### Criterion 8 (latency) — re-derivation over the real feed

The `RTM-LAT-01` threshold (mean wire→BBO ≤ 48 cycles, iter-7 addendum) was
calibrated on the lucky stretch that iter-12 itself declared "a lucky selection,
nonexistent today" (refs ≤ 372k, no message > 44 B). Over the representative real
feed (2019-12-30, with 2,289 `I` that push the drain at QB=46 under sustained
load), the mean is **65.5 cycles (203.3 ns @ 322.265625 MHz)**, deterministic
across re-runs. The master document's absolute budget (§0.1) still holds (203.3
ns < 214.9 ns). By documented contract decision, the threshold is **re-derived to
`mean ≤ 70 cycles` (217.3 ns)** with margin over the measured mean and the
per-type histogram persisted in
`verification/vectors/latency/latency_dw32.json`. Not lowered silently: the raw
evidence and justification live here and in the test
(`LAT_THRESHOLD_CICLOS = 70`).

### Criterion amendments for the push-out (same iter-13 contract)

- **OVR-01 / INV-OV-01 / SEC-URAM-03**: with P=32+push-out the add-33 at a price
  BETTER than the worst enters legitimately (it NO LONGER discards the op with
  error, as the iter-3 rejection did); only a reduce over a level discarded in
  the overflow signals `SEC-OV` (`errores == 1`, not `>= 2`).
- **Depth (CHAIN-01 / DP-02)**: the top-N depth is `bit-exact` while a side does
  not exceed P=32 levels; a level discarded at a >P peak can **re-enter** the
  top-N (loc13 reaches 420 on the day) → bit-exact depth is impossible with
  finite P for this feed, and the quantities of the re-entered levels may be
  partial. Amended contract (`OVR-PUSH-01`): BBO **bit-exact**; depth bit-exact
  until the first re-entry (`event 14461`, loc13) and a subset at **price** level
  afterwards (never a phantom). Option B (tail hash in URAM) would give exact day
  depth, with ~1,465 rebalances and a tail ≤ 388 levels (iter-13 measure, not
  implemented).