# Verification Report — cierre (closure and improvement campaign, condensed)

## Verdict

**IN PROGRESS.** `CLO-LAT-01` closed (mean **65.521 cycles ≤ 70**, real feed,
deterministic, JSON re-persisted). `CLO-RPT-01`, `CLO-REG-01`, `CLO-SCH-01`,
`CLO-M3T-00` closed. `CLO-322-02` (split) implemented and verified (regression +
gate E 31/31 + latency 65.521). `CLO-322-03` (322 MHz) advances: the internal
path `m_loc_idx → sm_asel` is split, but closure is now blocked by wrapper OUTPUT
I/O (SCD 2.695 ns + OBUF 2.334 ns, WNS −3.33 ns). `CLO-M3T-01/02` stay red on
MDP3 over-utilization (repartition pending a spec addendum).

## Criteria status

| ID | Criterion | Evidence | Status |
|---|---|---|---|
| CLO-LAT-01 | Latency JSON re-persisted | `sim-lat` over current RTL — **mean 65.521 cycles (203.3 ns) ≤ 70**, n=17,484, deterministic | CLOSED |
| CLO-RPT-01 | Reports per variant | tcl outdirs `322mhz/`/`156mhz/` distinct; 156 iter-16 archived (WNS +0.057) | CLOSED |
| CLO-REG-01 | Full regression | parser 32/32, orderbook 17/17, phase3 33/33, uram 4/4+3/3, MDP3 14/14+14/14 (golden 38, 1 env-only SKIP) | CLOSED |
| CLO-SCH-01 | XML↔RTL schema gate G | `check_mdp3_schema.py` — **58 structural localparams identical** (diff empty; id=1 version=12 md5 ok) | CLOSED |
| CLO-M3T-00 | MDP3 synth artifacts | `mdp3_synth.tcl` + 2 XDC; `synth_check.py` 55/55 | CLOSED |
| CLO-M3T-01 | MDP3 DW=32 @ 322 MHz | **red** — 179,222 LUTs > 162,720 (DRC UTLZ-1, no post-route) | OPEN |
| CLO-M3T-02 | MDP3 DW=64 @ 156 MHz | **red** — 283,659 LUTs > 162,720 | OPEN |
| CLO-322-00 | 322 baseline run | reproduced WNS **−3.458 ns** (confirms iter 16), on disk in `322mhz/` | RED documented |
| CLO-322-01 | phys_opt -retime (no RTL) | WNS −3.633 ns post-route (worse) — does not close | NOT CLOSED |
| CLO-322-02 | `m_loc_idx → sm_asel` split | `sim-rtm` 4/4, `sim-chain` 5/5 bit-exact (17,484), gate E **31/31** | CLOSED |
| CLO-322-03 | Criterion 10 @ 322 MHz | book **146,761 LUT** (fits), internal path closed, residual **WNS −3.33 ns** on output I/O | OPEN |
| CLO-322-04 | Post-split latency | mean **65.521 ≤ 66.521** (≤ +1.0), JSON re-persisted | CLOSED |
| CLO-322-05 / -99 | Ladder / denial amendment | pending (next if 03 does not close) | pending |
| CLO-LUT-01 / WNS-01 / LAT-02 / DEP-01 / CI-01 / 4B-01 / PUB-01 | Improvements | pending (stretch / batch 3) | pending |

## Gates

| Gate | Result |
|---|---|
| A — simulation | `sim-lat` 2/2 (CLO-LAT-01) + full post-split regression green |
| B — compile | `verilator --lint-only --Wall` on `itch_chain` — only pre-existing BLKSEQ; DW=32 WIDTHEXPAND fix (`32'(...)` casts, no semantic change) |
| C — style | verible on touched `itch_parser.sv` — 9 pre-existing convention findings, 0 new |
| D — coverage | Gherkin map published; mirror tests not yet written — NOT EXECUTED |
| E — mutation | `mutate_orderbook.py` **31/31 killed** (emit mutants migrated to the split) |
| F — completeness | `cierre.feature` exists; not yet in `gherkin-espejos.json` — NOT EXECUTED (deliberate) |
| G — rigor/timing | schema checker (58 params); MDP3 red (over-util); 322 phase-3 internal closed, output I/O −3.33 ns |

## Key numbers

- **Latency**: mean 65.521 cycles = **203.3 ns** @ 322.265625 MHz, n = 17,484
  events (20,705 messages), deterministic; JSON re-persisted (`total.mean_ciclos =
  65.521`).
- **322 split**: book LUT **146,761** (fits; the combinational-index fold was
  161,831 > 162,720). Residual WNS **−3.33 ns** — source clock delay (SCD)
  **2.695 ns** (fanout 95,585) + OBUF **2.334 ns** at the −2L grade against a
  3.103 ns period; `set_output_delay -max 1.0 ns` makes the output budget
  negative. The `m_loc_idx → sm_asel` path is no longer in the top-10.
- **MDP3 over-utilization**: 179,222 LUTs (DW=32) / 283,659 LUTs (DW=64) vs
  162,720 available — `mbuf[off % 256]` expands as a combinational mux (0 RAMB,
  264 LUTRAM).

## Honest limits / notes

- Nothing from phases 1–4 is pasted as this campaign's evidence; each closure
  criterion is closed here with fresh output.
- The `test_m3sch01_*` unittest now **delegates** to `check_mdp3_schema.py` (one
  table, no duplication).
- The `32'(...)` parser casts are an explicit width fix without behavioral
  change (full regression green, mean 65.521 identical to the historical 65.5).
- MDP3 timing is not improvised closed: repartitioning requires a spec addendum,
  red→green and a 14/14 gate-E re-run first.