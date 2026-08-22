# Lessons learned — consolidated operational history

> Single source for the lessons that were costly to learn (2026-08-12 → 2026-08-18),
> so the same mistakes are not repeated and the same numbers are not rediscovered.
> Consolidated (2026-08-18) from the operational content of the 2026-08-14
> session write-ups (`plan-proxima-sesion-uram.md`,
> `revision-exhaustiva-2026-08-14.md`, `uram.md` — removed during cleanup), of
> decisions 001/002 and of the phase-3 synthesis loops (iterations 6-10,
> 2026-08-18). The formal evidence of each campaign lives in
> `specs/<campaign>/verify-report.md`; this document is the operational summary.

---

## 1. Parameters: the effective parameter is not the module default

`itch_chain.sv` declares its **own** `QB` and passes it to the parser with
`.QB(QB)`; changing the default in `itch_parser.sv` **has no effect on the
chain**.

- **Misleading symptom**: two clean builds with supposedly different sources
  gave latencies identical to 3 decimals. The hasty conclusion was wrong; the
  real one: "the parameter I think I am changing is not the one that
  elaborates".
- **How it was resolved**: by instrumenting internal signals with cocotb (trace
  of `dut.u_parser.qn` per cycle → JSON). The queue exceeded QB=64 (69, 73...)
  → the binary used 128. Confirmed with the `git diff` of Verilator's C++
  (constant `0x7f - qn`, 1024-bit shift).
- **Operational rule**: in phase 3 the campaign parameters live in the top
  (`itch_chain.sv`), in `synth/itch_chain_synth.sv` and in the `-G`/`generic`
  line of the Makefile/tcl. Before measuring a parameter change, verify WHICH
  module elaborates the value.

## 2. Latency: the steady-state backlog model

Wire→BBO latency is NOT the message processing time (~14-19 theoretical
cycles) but **backlog + processing**:

- The input flows at 4 B/cycle while `qn+4 ≤ QB`; the parser's drain only
  happens in ST_CAP (the whole message at once, ~38 B every 14 cycles = 2.7
  B/c). Input > drain ⇒ the queue pins at QB and every message waits its turn.
  Model: `latency ≈ (QB/4)/7.7 × 11 + 16`.
- Verified: QB 128→64 gives mean **69.26 → 42.40 cycles** (214.9 → 131.5 ns at
  322.265625 MHz), p99 77→47 — **1.63×** with the bit-exact correction intact
  (CHAIN-01: 30,729 events, 0 gaps).
- The min (27) is the empty queue (first add of the day); steady state is
  backlog.
- QB ≥ 88 would keep 0 stalls in the tested stretch (only 1.4×); QB=64 cuts
  1.63× at the cost of bounded stalls (~15 in the stretch) — documented regime.
- The "no partial register" semantics (SEC-FRM-01/02) requires capturing the
  whole message before emitting ⇒ a streaming aligner does not reduce the
  completion wait; only the queue size sets the steady-state backlog.

> Note: the representative end-to-end latency (DW=32/QB=46) is **65.521 cycles
> (203.3 ns)**, deterministic, n = 17,484 events, threshold ≤ 70 cycles. The
> QB=64 figures above come from a non-representative stretch (iter 7) and are
> kept only as the record of that experiment.

## 3. Diagnosis technique: the internal trace beats theory

Hypothesis → experiment with a clean build (can give a false negative) →
**internal signal instrumentation** (truth) → verdict from the elaborated
binary. Rules:

- The diagnostic test (`dbg_qn`-style) is the standard tool: read
  `dut.<instance>.<signal>` by hierarchy with cocotb. Careful: internal names
  are the RTL's (e.g. `out_valid` does not exist as a port: it is
  `m_axis_tvalid`).
- Do not delete the diagnostic instruments: they are reusable.
- Verilator's binaries can be inspected (elaborated constants from the
  generated C++) to confirm WHICH parameters were compiled.

## 4. Process: a spec criterion with no test that pins it is not closed

Criterion 9 passed on documentation of a URAM mapping that **was never
implemented** (the "registered reads" did not exist in the RTL; the book was
structurally non-synthesizable: combinatorial probes with a variable index =
65,536:1 muxes → millions of LUTs; `level_add` O(P) ≈ 6-8 ns > 3.103 ns).
Lesson: every criterion that requires a concrete implementation must have a
test that pins it (SEC-URAM-01: registered read), not just an audit and a
write-up.

## 5. Rigor: bounded tests still catch regressions

The "0 stalls" → "stalls ≤ 24" amendment (LIN-01/P32-02) does not weaken the
regime: the limit comes from a measurement (~15 in the stretch) and still
kills gross regressions (a broken drain pushes stalls above the limit). Rule:
every test limit must come from a measurement with evidence, and the comment
must cite it. And: real-data replays omitted because a pcap is absent are
declared SKIP, never an early PASS.

## 6. Real data: the "by-the-book" invariants are measured, not assumed

The bid==ask cross in continuous trading (ZJZZT, 2 messages, halt→trading
transition) aborted the real-day run. Decision 001: the cross/lock **is
counted and reported**, not aborted; strict mode is exercised by the synthetic
tests. The phase-2 RTL inherits the semantics: a transiently locked BBO in
real data is not a bug.

## 7. Phase 3 synthesis (loops iter 7-10, 2026-08-18) — the summarized history

| Iter | Change | WNS | TNS | LUT | Dominant family |
|---|---|---|---|---|---|
| Base | original wrapper | -10.492 ns | -590.857 ns | 100.33 % | book logic (37-41 levels) + I/O |
| 7 | ST_EMIT → registered A/B/C stages | -7.395 ns | -430.582 ns | 96.49 % | `lv_eq → lv2_mode` (31 levels) + I/O |
| 8 | split decode 2a/2b + wrapper FIFO | -4.052 ns | -213.041 ns | 95.68 % | `depth_tready` → URAM cascade (12 levels) |
| 9 | guard only tvalid + precomputed find-first | -3.527 ns | -211.438 ns | 95.80 % | wrapper I/O (bbo_locate→pin, skew -2.67) |
| 10 | IOB=TRUE on ports + registered tready | -3.748 ns | -221.038 ns | 95.79 % | book FFs without packing (internal fanout) |

**Criterion 10: OPEN** (WNS < 0, TNS ≠ 0, LUT > 95 %). Full detail and
evidence: `specs/fase3-optimizacion/verify-report.md` and
`synth/reports/README.md`.

> Update (2026-08-21): after the internal `m_loc_idx → sm_asel` path split
> (CLO-322-02, amendment 17) the book now fits at **146,761 LUT**; the residual
> WNS (**−3.33 ns**) is now output-I/O-bound (SCD 2.695 ns + OBUF 2.334 ns at
> −2L). The 156.25 MHz variant is closed (WNS +0.057 ns, TNS 0, WHS +0.021 ns,
> URAM 32/48, IOB 194/256, DRC 0).

### Synthesis lessons (the ones that avoid repeating 2.5 h runs)

1. **Wrapper I/O with tree skew**: any internal FF → pin loses its area
   clock-tree skew (2.7-3.1 ns with LUT at 96 %) + the XDC output delay (1.0
   ns): a 1-level FF→pin path may not close due to the skew, not the logic.
2. **IOB packing only applies to FFs without internal fanout**: the book's
   output FFs (`bbo_tvalid`, `bbo_locate`, …) re-read themselves (retention
   `bbo_tvalid <= bbo_tvalid && !bbo_tready`) and the FSM reads them (guard
   `!bbo_tvalid && !depth_tvalid`): the placer does NOT move them to the IOB.
   Only `tready_ff` (a wrapper FF) was replicated. The correct path: output
   pipeline in the wrapper (own FFs with pin-side retention + IOB).
3. **A registered tready duplicates the pair if the guard watches it**: a
   1-cycle-deferred tready leaves the retained pair visible for two cycles with
   (tvalid=1, tready=1) → the consumer captures it twice. The emission guard
   must look ONLY at the tvalids (or the pin retention must withdraw the pair
   in the acceptance cycle).
4. **Deadlock in FSMs**: every branch of a `case` must update `st` (an else
   branch that does not advance the state freezes the FSM even if the outputs
   look correct).
5. **The `depth_tready` → URAM family (write with a cascade of 7 URAM288) is
   killed by moving the acceptance guard out of the write path**: the pin's
   tready must not feed any table-advance decision.
6. **LUT at ~100 % degrades the clock tree**: internal skews of 1-3 ns are a
   symptom of a full area, not just long routes. Reducing LUT also relieves the
   internal paths.
7. **xvlog 2023.2 is stricter than Verilator**: it rejects legal SV patterns
   (`mru32(...)[15:0]` part-select of a function call, identifiers used before
   their declaration like `qavail`/`hdr_pos`/`rst_n_c`). Validate with verilator
   (the real gate B) or with temporary parse-only patches; the only real error
   in the clean RTL is the pre-existing false positive of `nx_done` (legal in
   SV, Verilator accepts it).
8. **A test that never ran is a claim, not a verification** (uncovered by the
   first cocotb pass on WSL, 2026-08-18): the RTM-01/02/03 tests of iter 7
   never ran against the final iter-9 RTL and assumed semantics that iter 9
   changed (the output pair becomes visible 1 cycle after ST_EMIT_C due to AXI
   retention). Rule: a new structural test must run in the same cycle it is
   written; `py_compile`+gate F does not detect timing assumptions.
9. **cocotb 2.0.1 has no runtime `SkipTest`**: `raise cocotb.SkipTest` (1.x
   API) gives `AttributeError`; only static `@cocotb.test(skip=True)` exists.
   To split by width/elaboration, one module per elaboration (e.g.
   `test_rtm32.py` for DW=32 and `test_rtm64.py` for DW=64) and the Makefile
   points each target.
10. **Test scenarios must be valid for the oracle**: an `X(2,80)` that cancels
    80 of a 50-qty order aborts the golden (book invariant); the corrected test
    uses `X(2,30)`. And hardcoded `expected` (e.g. `changed==[1,0,1,0]`) must
    be derived from the oracle, not assumed.
11. **IOB packing and retention**: the book's output FFs do not pack into the
    IOB because the retention (`tvalid <= tvalid && !tready`) and the FSM guard
    give them internal fanout. The iter-11 output pipeline re-registers them in
    the wrapper's own FFs (IOB) with capture `tvalid_i && !tvalid_o` and
    pin-side retention — no duplication even if the consumer keeps tready=1.

## 8. Windows environment (work PC 2026-08-18)

- **Vivado ML 2023.2** at `C:\Xilinx\Vivado\2023.2` (not on the PATH):
  `vivado.bat -mode batch -source <tcl>` for runs; `xvlog.bat --sv --nolog` for
  a fast RTL parse. The development machine (macOS) has no Vivado: only the
  simulation gates run there.
- **WSL2 Ubuntu 26.04** with Verilator **5.046** (built from source with git in
  `<wsl-user>/verilator-git`; apt's 5.032 does not meet the cocotb 2.0.1
  requirement) + cocotb 2.0.1 + Python **3.12** (Ubuntu's 3.14 is not
  supported) is this PC's simulation machine (2026-08-18). venv path:
  `<wsl-user>/repo/.venv`. WSL's `bash -c` does not load the user's PATH: pass
  it explicitly. It needed `python3.12` from the deadsnakes PPA and the deps
  `git make autoconf g++ flex bison libfl-dev ccache`.
- **PowerShell 5.1 re-interprets heredocs and characters** (`` `'' ``, `<`,
  `>`): every multi-line WSL/Python script must go in a referenced `*.sh` /
  `*.py` file, not inline in the command.
- **PowerShell 5.1 `Add-Content` writes cp1252** (breaks gate F) or UTF-8 with
  BOM: use Python for byte edits or `-Encoding UTF8` and clean the BOM.
- Real data/pcaps are local and ignored; a replay omitted because a pcap is
  absent does NOT count as PASS.

## 9. Reference numbers (so they are not rediscovered)

| Metric | Value | Where |
|---|---|---|
| Mean latency (DW=32/QB=46) | 65.521 cycles (203.3 ns) | `latency_dw32.json`, `docs/writeup/latency.md` |
| Latency threshold (RTM-LAT-01) | mean ≤ 70 cycles | close spec |
| Bit-exact events (real feed) | 17,484 (cross 0, anomaly 0, gaps 0) | CHAIN-01 |
| Inferred URAM (XCKU3P) | 32/48 (66.67 %), cascade height 8 | 2026-08-18 run |
| Order table | 65,536 slots × 86 bits ≈ 5.64 Mb | phase3-uram spec |
| XCKU3P LUTs | 162,720 | decision 002 |
| Target period | 3.103 ns (322.265625 MHz) | phase-3 XDC |
| Max refs in real subset | 372,297 → K=19 | phase-2 spec |
| Max levels per side (subset) | 17 → P=32 | phase-2 spec |
| Physical limit of Annex A | output/input ratio > 1 → infinite line-rate impossible | phase-1 spec (criterion 2) |

## 10. Documentation map (post-cleanup 2026-08-18)

| Need | Location |
|---|---|
| Master state, process, gates A-G | `AGENTS.md` |
| Setup and installation | `docs/DEVELOPMENT.md` |
| Architecture decisions | `docs/decisions/001..003` (ADRs) |
| Contract and criteria per campaign | `specs/<campaign>/spec.md` + `gherkin/` |
| Evidence per campaign (gates A-G) | `specs/<campaign>/verify-report.md` |
| Phase-3 Vivado run history | `synth/reports/README.md` + `synth/reports/*.txt` |
| Operational lessons | this document |
| **Verifiable project marks** | `docs/writeup/marks.md` |
| Close plan (steps, commands, stops) | `docs/writeup/close-plan.md` |
| Wire→BBO latency | `docs/writeup/latency.md` |
| Master document (options/scope) | repo root |