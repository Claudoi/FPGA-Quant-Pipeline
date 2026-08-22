# Verification Report — fase2-orderbook (condensed)

## Verdict

**Phase 2 CLOSED functionally.** The order book applies the Annex-A records and
emits a BBO bit-exact against the golden `book.py`, with atomic `U` replace,
RAW-hazard handling, exact single subtract, and observed overflow/error. Current
suite **17/17**; the real replay contributes 30,729 bit-exact BBO events
(cross=0, anomaly=671). Timing (Vivado) is out of scope for phase 2.

## Criteria

| Criterion | Test(s) | Evidence | Status |
|---|---|---|---|
| 1 — BBO vs golden | `test_bbo01` | multi-type sequence bit-exact | PASS |
| 2 — empty symbol / (0,0) side | `test_sec_em01` | AAPL stays empty, no event; ask=(0,0) | PASS |
| 3 — atomic `U` | `test_sec_u01`, `test_inv_u01` | single final state | PASS |
| 4 — RAW hazards | `test_sec_hz01/02` | add→execute, replace→execute | PASS |
| 5 — no double subtract | `test_sec_dc01/02` | exact subtract vs golden | PASS |
| 6 — overflow signaled | `test_sec_ov01` | `error` pulse observed, discard + recovery | PASS |
| 7 — unknown ref anomaly | `test_sec_an01` | `anomaly_count` + continuation | PASS |
| 8 — crossed book | `test_sec_cr01` | `cross_events` counter | PASS |
| 9 — multi-symbol | `test_multi01` | independent BBO per locate | PASS |
| 10 — real replay | `test_replay01` | **30,729 BBO events bit-exact**, cross=0, anomaly=671 | PASS |
| 11 — frozen BBO vectors | `test_rep02` | synthetic frozen vector reproduced | PASS |

## Gates

| Gate | Result |
|---|---|
| A — simulation | `make sim` → **17/17 PASS** (14/14 historical suite + repaired `SEC-OV-01`/`SEC-EM-01` + replay) |
| B — compile | `verilator --lint-only --Wall --top-module orderbook`, 0 warnings (removed a real `UNSIGNED` warning, not suppressed) |
| C — style | verible NOT EXECUTED (not installed) |
| D — coverage | level-1 spec↔test map; instrumented coverage NOT EXECUTED |
| E — mutation | `mutate_orderbook.py` phase-2 mutants **9/9 killed** |
| F — completeness | 12 scenarios in `orderbook.feature`, mirror in `gherkin-espejos.json` |
| G — rigor | real replay local, independent golden, no versioned data; timing NOT APPLICABLE |

## Key numbers

- Real replay: **31,400 messages / 20 symbols** against the golden → **30,729
  BBO events bit-exact**, cross=0, anomaly=671.
- Mutation: 9/9 killed (OV-BEST, OV-EMPTY, U-NOTATOMIC, U-DELETE-HALF,
  U-SKIP-ROUTE, D-DOUBLE, RED-REF, QTY-NOERROR, EMIT-NOCHANGED).
- Phase-0 suite green (36 tests); WSL regression (2026-08-19) 13/14 + 1 SKIP
  (replay pcap absent on that machine — the real-replay evidence is recorded in
  this campaign).

## Honest limits

- Scope starts at the decapsulated `MoldUDP64` payload; 10G MAC and
  Ethernet/IP/UDP are not claimed by this repository.
- `/tmp/real_trading.pcap` is read locally and does not appear in `git status`.
- Vivado / WNS / TNS / utilization belong to phase 3; none are inferred here.
- Three phase-3 mutants (`URAM-COMB-INDEX`, `NSYM-GUARD`, `BP-NORET`) survived
  the shared phase-2/3 runner; they do not affect this campaign's closure but
  block the integrated gate E — resolved in the phase-3 campaign.