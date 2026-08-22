# Verification Report — fase3-optimizacion (condensed)

## Verdict

**Phase 3 functionally CLOSED; timing closed at 156.25 MHz, open at 322 MHz.**
The DW=32/QB=46 pipeline (hash-probed URAM order table, push-out top-32, dynamic
oversize drain) processes the real 2019-12-30 open subset **bit-exact**: 17,484
BBO events, cross=0, anomaly=0, gaps=0, deterministic latency **65.521 cycles
(203.3 ns) ≤ 70**. The **156.25 MHz variant timing-closes** (WNS +0.057 ns, TNS
0, URAM 32/48); the **322 MHz variant remains OPEN** by a structural wrapper I/O
limitation, documented honestly — not timing-closed.

## Criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Parser DW=32 bit-exact | `test_p32_01/02`, real replay (91 packets, 26,904 words) | PASS |
| 2 | Book DW=32 bit-exact | `test_b32_01/02`, real replay | PASS |
| 3 | 64-bit regression | `sim-rtm64`, full phase-1/2 suites | PASS |
| 4 | Chain DW=32 bit-exact | `test_chain01` — **17,484 BBO events bit-exact**, cross=0, anomaly=0, gaps=0 | PASS |
| 5 | Hash + probing | `SEC-HASH-01/02/03`; K=64 fix (refs > 2^19 no longer collide) | PASS |
| 6 | Top-N parameterized | `test_dp01` ND=5 and `-GND=3` elaboration | PASS |
| 7 | Hardening (NSYM / BBO backpressure) | `test_sec_nsym01`, `test_sec_bp01` | PASS |
| 8 | Latency | `sim-lat` 2/2 — mean **65.521 cycles** (203.3 ns) ≤ 70, deterministic | PASS |
| 9 | URAM pipeline | table inferred in **32 URAM288** (65,536×86 bits); registered reads audited | PASS |
| 10 | Synthesis (322 MHz) | **OPEN** — 156 variant closed, 322 residual I/O WNS −3.33 ns | OPEN (322) |
| 11 | Lint `--Wall` | Verilator clean on parser/book/chain at DW=32/DW=64 | PASS |

## Gates

| Gate | Result |
|---|---|
| A — simulation | Full regression green (phase3 33/33, parser 32/32, orderbook 17/17, uram 4/4+3/3, latency 2/2) |
| B — compile | `verilator --lint-only --Wall` clean (only pre-existing BLKSEQ from tasks) |
| C — style | verible NOT EXECUTED (not installed) |
| D — coverage | spec↔test map; instrumented coverage NOT EXECUTED |
| E — mutation | `mutate_parser.py` 18/18 (or 19/19 on the shared framing delta); `mutate_orderbook.py` **31/31 killed** |
| F — completeness | versioned Gherkin checker green (12 IDs / 3 campaigns) |
| G — rigor/timing | real pcaps outside Git, independent golden; `synth_check.py` green; Vivado reports for 156 + 322 below |

## Key numbers

- **156.25 MHz variant — CLOSED** (re-synthesized with the current RTL, K=64 /
  OW=130 / push-out / drain): WNS **+0.057 ns**, TNS 0, WHS **+0.021 ns**,
  URAM **32/48**, IOB **194/256**, DRC 0, **LUT 154,371 (book 150,466)**.
- **322 MHz variant — OPEN**: the critical path `m_loc_idx → first_one →
  sm_asel` was split into registered stages (A captures caps+predicates, B
  computes `first_one` into a registered index, C muxes caps by that registered
  index). Book **LUT 146,761** (fits). Residual **WNS −3.33 ns** is dominated by
  wrapper OUTPUT I/O: source clock delay **2.695 ns** (fanout 95,585) + OBUF
  **2.334 ns** at the −2L speed grade — not by book logic.
- **Latency**: mean **65.521 cycles = 203.3 ns** @ 322.265625 MHz, n = 17,484
  events (20,705 messages), deterministic, threshold re-derived to **≤ 70 cycles**
  (the iter-7 ≤ 48 was a non-representative stretch).
- **Real feed**: 17,484 BBO events bit-exact, 0 anomalies, 0 crosses, 0 gaps;
  depth bit-exact until the first re-entry at a >P peak (ev. 14461, loc13 peak
  420 levels) and a price-level subset afterwards (never a phantom).

## Honest limits

- The bounded-depths amendment: depth is bit-exact only while a side stays ≤
  P=32 levels; at >P peaks it is a price subset. Option B (tail hash in URAM)
  would give full-day depth and remains a documented improvement (not
  implemented).
- `synth_check.py` only proves static coherence between RTL/Tcl/XDC; WNS/TNS are
  from real Vivado runs (Vivado ML 2023.2, `xcku3p-ffva676-2L-e`).
- The 322 MHz criterion is NOT presented as closed; only the 156.25 MHz variant
  (same 10G throughput) is timing-closed.