# Verification Report — fase4-mdp3-parser (condensed)

## Verdict

**Phase 4 functionally CLOSED (2026-08-19).** The CME MDP 3.0 (SBE) parser is
verified bit-exact against the schema-driven golden (little-endian, subset
46/47/52/53, Annex M MBP/MBOFD). Suite **14/14 DW=32 and 14/14 DW=64**; gate E
**14/14 mutants killed**; gate C (verible) **0 findings**. `tkeep` mask
validation (criterion 7), schemaId/version passthrough + MAX_MSG (criterion 5),
and output backpressure (criterion 10) are closed. **Timing remains OPEN**: the
parser does not fit the XCKU3P (LUT over-utilization in both width variants).

## Criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Golden MDP3 (schema loader/decoder/generator) | Python mirrors; semantic round-trip from non-zero known vectors | PASS |
| 2 | Framing (packet + SBE messages → Annex M) | `test_m3frm01/02/05`, bit-exact vs golden, word-crossing, `tkeep` | PASS |
| 3 | Input regime (24× template-47, run ≤ 16) | `test_m3frm03`: max stall run **8 (DW=32) / 16 (DW=64)** | PASS |
| 4 | Decoded subset 46/47/52/53 | `test_m3sub01/02`, composite price + multi-entry bit-exact | PASS |
| 5 | Passthrough (schema/version + MAX_MSG 256/257) | `test_m3pass01/02`, `test_m3size01/02` — **CLOSED** | PASS |
| 6 | Sequence gaps | `test_m3gap01` | PASS |
| 7 | Robustness / invalid `tkeep` masks | `test_m3inv01/02/03/04a/04a2/04b` — **CLOSED** (streaming discard, `CS_DISCARD`) | PASS |
| 8 | Regression | 14/14 DW=32 and 14/14 DW=64 | PASS |
| 9 | Lint / XML↔RTL checker | Verilator clean; verible **0 findings**; `check_mdp3_schema.py` **58 localparams matched** (XML id=1 version=12) | PASS |
| 10 | Output backpressure | `test_m3bp01` — stable tuple, bit-exact on release — **CLOSED** | PASS |

## Gates

| Gate | Result |
|---|---|
| A — simulation | 14/14 DW=32 and 14/14 DW=64 (0 FAIL, 0 SKIP) |
| B — compile | `verilator --lint-only --Wall` clean (0 warnings) |
| C — style | verible **0 findings** over `mdp3_parser.sv` |
| D — coverage | literal 14-scenario map; schema v12↔RTL checker |
| E — mutation | `mutate_mdp3.py` **14/14 killed** (incl. TKINV-HUECOS/PARTIAL, ERR-INV, DISCARD-*, TKCNT-ALWAYS) |
| F — completeness | 14 unique IDs in `mdp3.feature`; mirror in `gherkin-espejos.json` |
| G — rigor/timing | golden from XML, synthetic corpus, no versioned real data; **timing OPEN** (over-utilization) |

## Key numbers

- Suite: **14/14 DW=32, 14/14 DW=64**, gate E 14/14 mutants killed.
- M3-FRM-03 stall regime: max `tvalid && !tready` run **8 cycles (DW=32)**,
  **16 cycles (DW=64)**.
- XML↔RTL checker (`check_mdp3_schema.py`): **58 structural localparams** match
  the pinned schema (`templates_FixBinary_v12.xml`, id=1, version=12, md5
  `e6eb6c60…`), including `SCHEMA_ID=1`, `SCHEMA_VER=12`, `PKT_HDR=12`,
  `MAX_MSG=256`, `EXP_BYTE=8'hF7` and offsets O46/O47/O52/O53 — diff empty.
- Golden: pinned schema fetched fail-closed (CME FTP 403 → Wayback fallback +
  md5 pinned). byteOrder little-endian; subset IDs 46/47/52/53; `msg_size`
  includes the 10 B prefix (roq-cme evidence).

## Timing (OPEN — honest)

- **DW=32 @ 322 MHz**: synthesis over-utilized — **179,222 LUTs** (Logic) vs
  162,720 available; DRC `UTLZ-1`, `place_design` aborted, no post-route WNS/TNS.
- **DW=64 @ 156 MHz**: worse — **283,659 LUTs** vs 162,720; `place_design`
  aborted.
- Root cause: `mbuf0/mbuf1/qbytes[off % 256]` with a variable index expand as a
  combinational mux (the 256 B buffers are not inferred as RAM — 0 RAMB, 264
  LUTRAM). Closing requires a decoder re-partition (explicit RAM inference or FSM
  pipeline): a spec addendum, red→green and a 14/14 gate-E re-run.

## Honest limits

- No DataMine (paid) real data: the corpus is synthetic, generated from the
  official schema. Real-data replay (REPLAY-03) is optional and not claimed.
- The `literal_subset` vector (m53, 87 B) in the test was incoherent with the
  template-53 layout and was never used by the suite; M3-INV-04a2 uses a corpus
  message (seed 31) instead.
- Timing is not presented as closed in either variant.