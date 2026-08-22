# 001 — Locked/crossed book in real data: count, do not abort

**Date:** 2026-08-12 (phase 0, iteration 2) · **Status:** accepted

## Context

The invariant «bid < ask in continuous trading, violation = abort» was written
into the phase-0 spec assuming the Nasdaq book never crosses outside auctions.
The first run over real data (day 2019-12-30) aborted at message 39,778,763:
symbol ZJZZT (Nasdaq's test symbol) with bid == ask == 130000 for 2 messages,
formed in a halt→trading transition.

## Decision

The cross/lock in continuous trading **is counted and reported**
(`Book.cross_events`, run summary), not aborted. Strict mode
(`strict_cross=True` / `--strict`) keeps the abort and is what the synthetic
tests exercise. The remaining invariants (duplicate refs, non-positive qty,
inconsistent levels) abort always.

## Consequences

- Phase-0 spec criterion 3 rewritten (with the evidence) + scenario SEC-08.
- The phase-2 RTL inherits this semantics: the BBO may stay locked
  transiently in real data; the testbench must not treat it as a bug.
- Reference for the write-up: 642 events / 268.7M messages that day.

Full evidence: `specs/fase0-golden-model/verify-report.md` (section
«Iteration 1 → real finding»).