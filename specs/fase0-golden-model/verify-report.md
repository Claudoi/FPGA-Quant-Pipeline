# Verification Report — fase0-golden-model (condensed)

## Verdict

**Phase 0 CLOSED.** The golden ITCH 5.0 model parses two full Nasdaq days
(22 message types, 268.7M + 368.4M messages) with zero anomalies, produces
14.4M BBO reference vectors, and all gates A–G pass (timing/Vivado is NOT
APPLICABLE — no RTL in this phase).

## Criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Parser validates/iterates all ITCH 5.0 | 38 tests green; 268,744,780 messages, 0 anomalies, full day | PASS |
| 2 | Book known-answer BBO (add/execute/cancel/delete/replace/empty) | `test_lib01…06`, hand-written expected values | PASS |
| 3 | Invariants per message (strict mode aborts; real mode counts crosses) | `test_inv01`, `test_sec04/05/08`; 642 cross events counted (0.0002 %), not aborted | PASS |
| 4 | Vector writer (Annex A, monotonic index, change flag) | `test_vec01/02/04` | PASS |
| 5 | Binary↔text round-trip | `test_vec03` | PASS |
| 6 | Full-day run ≤ 2 h | **17m14s** for 268.7M msgs (≈260k msg/s), ~7× margin | PASS |
| 7 | fetch + md5, fail-closed | `test_dat01/03`, `test_sec07`; 404 endpoint → exit 2 + `--no-md5-verify` with warning | PASS |
| 8 | pcap + round-trip | `test_pca01…04`, `test_sec06`; openable with `tcpdump -r`, byte-exact reconstruction | PASS |
| 9 | subset from stats | `subset_symbols.json` top 20 by peak live orders (AMZN 37,068; AAPL 27,110; MSFT 23,005; TSLA 17,482; FB 14,736 …) | PASS |
| 10 | Pure stdlib | `grep` of imports → only stdlib | PASS |

## Gates

| Gate | Result |
|---|---|
| A — simulation | `unittest discover` → 38 tests OK |
| B — compile/lint | `py_compile` of all touched sources + tests, exit 0 |
| C — style | type hints on public APIs, module docstrings, pure stdlib — PASS |
| D — coverage | spec↔test table + per-type counts of the real day |
| E — mutation | 5/5 manual mutants killed (BBO `<`→`<=`, qty ±1, level-not-removed, inverted change flag, relaxed length) |
| F — Gherkin completeness | 1:1 mirrors declared in `specs/gherkin-espejos.json` |
| G — rigor | real data outside Git, golden as source; timing NOT APPLICABLE |

## Key numbers

- **Main day** `12302019`: 268,744,780 messages, 8,906 symbols, 0 anomalies, 642 cross events, 14,427,667 vector records (577 MB, exact multiple of 40 B), runtime **17m14s**.
- **Regression day** `01302019`: 368,366,634 messages, 8,713 symbols, 0 anomalies, 63 cross events, runtime **22m15s** (margin 1h37m44s vs. the 2 h limit).
- Determinism confirmed: `by_type`/`anomalies`/`cross_events` identical across independent runs.
- Per-type counts coherent with the real market (A/D dominate; NOII `I` 4.0M clustered at open/close; `S` = 6 system events). Types absent that day (B, N, O, W) exercised in PAR-01.
- Real vectors verified: `msg_idx` strictly increasing; first/last text-dump lines field-identical to the first/last binary record; change flag correct on real data (consecutive identical BBO → `changed=0`).

## Honest limits

- The `.md5sum` endpoint on `emi.nasdaq.com` no longer serves (404); download integrity verified by exact Content-Length (3,524,013,057 B) + `gzip -t`. `fetch_itch.py` aborts fail-closed without md5.
- Raw data and generated vectors stay out of Git (`data/itch_sample/**` gitignored).
- The subset top 20 sums to ~250k peak live orders — this anchors the RTL URAM sizing in phase 2.