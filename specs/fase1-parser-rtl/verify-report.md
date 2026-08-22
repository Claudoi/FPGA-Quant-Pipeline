# Verification Report — fase1-parser-rtl (condensed)

## Verdict

**Phase 1 CLOSED (2026-08-19).** The parser consumes the MoldUDP64 payload
with the `s_axis_tkeep` framing contract, emits a byte-exact Annex-A record per
subset message, and closes REP-02 (line rate) on a real stretch. Suite 32/32;
REP-02 measures **9 stalls ≤ 24** on a real A/U window selected from the pcap
without manual indices, with the downstream always ready and bit-exact output
against the oracle. The physical timing gate does not apply to this campaign.

## Criteria

| Criterion | Evidence | Status |
|---|---|---|
| 1 — decoded record per subset type, byte-exact | `test_par01`, `test_sec_par04`, `test_out01` vs. `--emit-messages` | PASS |
| 2 — line rate (bounded stretch) | `test_lin01`, four A/U back-to-back, QB=64, stalls ≤ 24 | PASS |
| 3 — aligner across 8 alignments | `test_aln01` sweep of all offsets | PASS |
| 4 — MoldUDP64 framing (seq/count/session/gaps) | `test_sec_gap01/02`, `test_sec_frm03/04/05/06/07`, `test_frm01/02` | PASS |
| 5 — AXI-Stream backpressure | `test_out02/03`, `test_sec_frm08` | PASS |
| 6 — 22 types validated, out-of-subset counted | `test_sec_par04/05` | PASS |
| 7 — truncated/incoherent length cancels cleanly | `test_sec_par03`, `test_sec_frm01/02` | PASS |
| 8 — real replay (hybrid oracle) + frozen vectors | `test_rep01`, `test_rep02_*` | PASS — **REP-02 closed** |
| 9 — phase-0 loose ends | regression day + committed vectors | PASS |
| 10/11 — lint `--Wall` / style | Verilator clean; verible NOT EXECUTED (not installed) | PASS / NOT EXECUTED |

## Gates

| Gate | Result |
|---|---|
| A — simulation | `make sim` clean → **32/32 PASS**; REP-02 real: 5,200 packets, 100,673 words, A/U window (msgs 241733..241736) **9 stalls ≤ 24** |
| B — compile | `verilator --lint-only --Wall --top-module itch_parser` exit 0, zero warnings |
| C — style | verible not installed — NOT EXECUTED |
| D — coverage | SEC-FRM-04..08 covered; REP-02 covers oracle/`tlast` + contractual A/U window |
| E — mutation | `mutate_parser.py` 19/19 mutants compiled and killed |
| F — completeness | versioned checker: 12 IDs / 3 campaigns, unique Gherkin per campaign |
| G — rigor | real pcap outside Git, independent Python oracle, real replay executed |

## Key numbers

- REP-02 closure (2026-08-19, WSL — cocotb 2.0.1 + Verilator 5.046, Python 3.12):
  reproducible subset of **5,200 packets / 251,375 messages** of the real day
  2019-12-30, replay bit-exact (**32/32**), first sliding A/U window
  (msgs 241733..241736) with **9 stalls ≤ 24**, downstream always ready,
  bit-exact against the oracle.
- Full replay accepted **5,200 input `tlast` handshakes** (one per decapsulated
  datagram); 107,477 total input-stall cycles with `m_axis_tready=1` (this
  aggregate does not replace the contractual window measure).
- The local artifact `/tmp/real_subset.pcap` (129,930 B, 91 packets) was
  replaced by the reproducible 5,200-packet subset; the old artifact could not
  close REP-02.
- Phase-0 golden suite re-run green: 37 tests.

## Honest limits

- Replay evidence depends on a local pcap not committed to Git; if absent on
  another machine the test is `SKIP`, not PASS.
- The `.md5sum` endpoint no longer serves (404); download verified by exact
  size (3,524,013,057 B = Content-Length) and message count (268,744,780 =
  phase-0 day), documented with `--no-md5-verify` + warning (fail-closed
  respected).
- Instrumented coverage and Verible were not run.
- This campaign does not measure WNS/TNS or utilization and does not claim the
  physical frequency of phase 3.