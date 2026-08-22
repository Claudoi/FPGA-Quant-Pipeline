# fase3-uram.feature — URAM campaign: table in URAM + serialized probe +
# level pipeline + 32-bit Annex-A trim.

Mirror of "Acceptance criteria" 1-8 of the fase3-uram `spec.md`.
The semantics of each operation is EXACTLY that of `golden_model/src/book.py`
and `golden_model/itch/messages.py` (phases 0-2) and of the previous phase 3
(30,729 bit-exact BBO/depth events over the real subset feed).

# language: en
Feature: Order book over URAM synthesizable at 322.265625 MHz
  As a market-data pipeline at 10G line rate
  I want the order table to live in URAM with registered reads
  So that the design closes timing at 3.103 ns without losing a single bit of correctness

  Scenario: ANX-01 — the trimmed 32-bit Annex A is bit-exact against the oracle
    Given the phase-1 synthetic corpus
    When the 32-bit parser processes each message
    Then the output words (w0 context, w1 idx, w2.. body, without ts)
      are bit-exact against the updated message_oracle oracle
    And the 32-bit book consumes the same layout without misalignment

  Scenario: ANX-02 — the worst case stays at 1 word/cycle with the trimmed layout
    Given a stream of minimum messages back-to-back
    When the 32-bit parser processes them with the trimmed layout
    Then there is no sustained input backpressure
    And the tested stretch's stalls stay bounded (≤ 24, LIN-01 regime)

  Scenario: SEC-URAM-01 — the table is read in a registered way, never combinationally
    Given an order-table probe
    When a slot address is emitted in cycle N
    Then the data is valid exactly in cycle N+1
    And the probe consumes at most 1 slot per cycle
    And no probe comparison indexes o_mem directly

  Scenario: SEC-URAM-02 — the hash-group prefetch happens during ST_BODY
    Given a message whose hash group has PROBE+ refs colliding (K=20)
    When the book receives the message body
    Then the group slots are read before entering ST_APPLY
    And the lookup ends with the same semantics as the phase-3 hash

  Scenario: SEC-URAM-03 — the level pipeline creates no bubbles nor phantoms
    Given 33 adds that overflow P=32 and a later delete on an absent level
    When the book processes the sequence
    Then a stale price or a wrapped qty never appears
    And each level operation consumes at most 3 extra cycles (2 + 1 of the LV2B
    stage split in phase-3 iteration 8)

  Scenario: REG-01 — the full regression stays green with the new RTL
    Given the refactored RTL (URAM + serialized probe + pipeline + trimmed Annex)
    When the phase-1, phase-2 and phase-3 suites are re-run
    Then all tests keep passing unchanged
    And the real feed anomalies/cross stay identical

  Scenario: CHAIN-01 — the parser→book chain is bit-exact with the trimmed Annex
    Given the decapsulated real feed (parser 32 → book 32, no re-parse)
    When the chain processes the subset
    Then the BBO and depth sequence is bit-exact against the golden book.py
    And anomaly=671, cross=0 and gaps=0 (phase-3 evidence)

  Scenario: SEC-URAM-04 — the mean latency stays below 70 cycles (re-derived)
    Given the DW=32 parser→book chain over the fixed latency sequence
    When the wire→BBO latency per message type is measured
    Then the total mean is ≤ 70 cycles (re-derived from 45/48 over the real feed)
    And the re-run produces the identical histogram (SEC-LAT-01 determinism)