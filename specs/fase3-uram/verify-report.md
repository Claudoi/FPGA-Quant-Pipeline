# Verification Report — fase3-uram (condensed)

## Verdict

**Functionally CLOSED.** The 32-bit Annex-A trim, the URAM order table with a
serialized probe, and the registered level pipeline are verified bit-exact
against the golden. The table infers into **32 URAM288** and the trimmed chain
reproduces 30,729 bit-exact BBO + depth events. Criterion 10 (322 MHz synthesis)
remains OPEN — resolved later in the closing campaign as: **156.25 MHz closed**
(WNS +0.057 ns), **322 MHz open** by a wrapper I/O limitation.

## Criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Trimmed 32-bit Annex A | ANX-01 (75 words) + ANX-01 real (197,452 words of 31,400 msgs), ANX-02 (2 stalls) bit-exact | PASS |
| 2 | Table in URAM (registered read) | SEC-URAM-01 structural pinch (data valid 1 cycle after address) | PASS |
| 3 | Serialized probe + prefetch | SEC-URAM-02 forced collision (K=20), same hash semantics | PASS |
| 4 | Level pipeline without bubbles | SEC-URAM-03 (33 adds + D), no phantom/stale/wrap | PASS |
| 5 | Total regression | CHAIN-01: **30,729 BBO + 30,729 depth bit-exact**, anomaly=671, cross=0, gaps=0 | PASS |
| 6 | Latency | `sim-lat` deterministic (2 identical runs), mean 44.318 cycles (threshold later re-derived to ≤ 70) | PASS |
| 7 | Criterion 10 (synthesis) | `synth_check.py` green; 32 URAM288 inferred; 322 MHz timing OPEN | PASS (artifacts) / OPEN (timing) |
| 8 | Lint `--Wall` | Verilator clean at DW=32/DW=64 | PASS |

## Gates

| Gate | Result |
|---|---|
| A — simulation | ANX 3/3, parser DW64 31/31, chain ND=5/3 4/4+4/4; real BBO+depth complete |
| B — compile | `verilator --lint-only --Wall` clean on parser/chain at DW=32 |
| C — style | verible NOT EXECUTED (not installed) |
| D — coverage | ANX-01/02 and CHAIN-01 (non-empty, lengths, content) covered |
| E — mutation | parser framing delta 19/19 killed |
| F — completeness | versioned Gherkin checker green (12 IDs / 3 campaigns) |
| G — rigor/timing | independent golden, data outside Git; no WNS/TNS (322 still open) |

## Key numbers

- URAM inference: **32 URAM288** (65,536×86 bits; `o_mem` as a single synchronous
  array, `rd_data <= o_mem[rd_addr]`, no combinational `o_mem[pr_*]` indexing).
- CHAIN-01 (trimmed layout): 31,400 messages → **30,729 BBO + 30,729 depth
  bit-exact** (ND=5 and ND=3), cross=0, anomaly=671, gaps=0.
- P32-03 real replay: 91 packets, 26,904 words bit-exact, `accepted_tlast ==
  len(payloads) == 91`.
- Latency at the time of this campaign: mean 44.318 cycles (simulation; threshold
  re-derived in the closing campaign to **≤ 70 cycles**, final mean 65.521).

## Honest limits

- The `sim-uram` structural target was not re-run in this loop; the URAM
  integration is verified inside `itch_chain`.
- `synth_check.py` is a static guardrail — it does not substitute WNS/TNS nor
  prove URAM inference on the target device; that evidence comes from the owner's
  Vivado runs (documented in the closing campaign).
- The 322 MHz timing criterion remained open at this stage and is not presented
  as closed.