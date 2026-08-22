# optimizacion.feature — phase 3: 32-bit @ 322 MHz variant, hashed URAM, top-N

Mirror of "Acceptance criteria" 1-11 of the fase3-optimizacion `spec.md`.
The semantics of each operation is EXACTLY that of `golden_model/src/book.py`
and `golden_model/itch/messages.py` (phases 0-2).

# language: en
Feature: 32-bit @ 322 MHz pipeline with hashed URAM table and public top-N
  As a market-data pipeline at 10G line rate
  I want the parser and the book to work on a 32-bit datapath
  So that the design closes timing at 322.265625 MHz with the table in URAM

  Scenario: P32-01 — the DW=32 parser emits the 32-bit Annex A bit-exact
    Given the phase-1 synthetic corpus
    When the 32-bit parser processes each message
    Then the output words (w0 context, w1 idx, w2.. body, without ts —
      the fase3-uram trimmed layout) are bit-exact against the message_oracle oracle

  Scenario: P32-02 — the DW=32 parser accepts the worst case at 1 word/cycle
    Given a stream of minimum messages back-to-back
    When the 32-bit parser processes them
    Then there is no sustained input backpressure
    And no message is lost

  Scenario: B32-01 — the DW=32 book emits the golden BBO bit-exact
    Given the phase-2 synthetic corpus (A/F/E/C/X/D/U/S/H)
    When the 32-bit book applies each message
    Then the BBO emitted per symbol is bit-exact against the golden book.py

  Scenario: B32-02 — the DW=32 book reproduces the real subset feed
    Given the decapsulated local-day pcap (20 symbols)
    When the 32-bit book processes the subset messages
    Then the BBO sequence is bit-exact against the golden book.py

  Scenario: REG-01 — the 64-bit regression stays green after parameterizing
    Given the RTL extended with parameterized DW (default 64)
    When the phase-1 and phase-2 suites are re-run
    Then all tests keep passing unchanged

  Scenario: CHAIN-01 — the DW=32 parser→book chain is bit-exact
    Given the decapsulated real feed (parser 32 → book 32, no re-parse)
    When the chain processes the subset
    Then the BBO sequence is bit-exact against the golden book.py

  Scenario: SEC-HASH-01 — an exhausted probe counts an anomaly without aborting
    Given an order_ref whose slot is the same after PROBE steps
    When the book looks up that ref
    Then it counts anomaly_count
    And continues processing the next message

  Scenario: SEC-HASH-02 — a full order table is signalled with error
    Given that all slots are occupied
    When an add of a new ref arrives
    Then it signals error
    And does not overwrite nor wrap silently

  Scenario: SEC-HASH-03 — hash collisions of distinct symbols are resolved
    Given two refs of distinct symbols with the same base slot
    When the book processes them
    Then each operation acts on its own order
    And each symbol's BBO matches the golden

  Scenario: SEC-NSYM-01 — symbol 21 signals error without an out-of-range index
    Given a locate outside the NSYM=20 subset
    When a message of that symbol arrives
    Then it signals error
    And the internal symbol index stays below NSYM in every cycle
    And does not corrupt the registered symbols' levels

  Scenario: SEC-BP-01 — the BBO is held under backpressure without loss
    Given a consumer that lowers bbo_tready after observing bbo_tvalid
    When it holds the stall for two full cycles
    Then bbo_tvalid and the payload stay stable until tready rises
    And it is delivered exactly once, without loss or duplicate

  Scenario: SEC-DP-01 — the depth of an empty symbol is all zeros
    Given a symbol with no orders
    When the book emits its depth
    Then depth_tdata is 0 at all levels

  Scenario: DP-01 — the public top-N is bit-exact against the golden levels
    Given a symbol with ND levels or more per side
    When the book emits an event of that symbol
    Then depth_tdata contains the ND best levels per side, best first
    And an itch_chain elaboration with ND=3 produces exactly 384 bits
    And is bit-exact against the ordered levels of the golden book.py

  Scenario: SEC-LAT-01 — per-type latency is deterministic and reproducible
    Given the DW=32 parser→book chain over a fixed sequence
    When the wire→BBO latency per message type is measured
    Then the re-run produces the identical histogram

  # --- iteration 7 (2026-08-18): level-scan retiming ---------------------
  # Addendum iteration 7 of spec.md. The single-cycle ST_EMIT splits into
  # ST_EMIT_A (capture) / ST_EMIT_B (selection+changed+depth) / ST_EMIT_C
  # (handshake) — +2 cycles on the event path, latency re-derived.

  Scenario: RTM-01 — the BBO/depth level scan is registered in stages
    Given the book with pipelined ST_EMIT (stages A/B/C)
    When an update event is processed
    Then the symbol's level capture is a register (verified with an internal probe)
    And the per-side find-first operates on the capture, not on the level arrays
    And the emitted payload is bit-exact against the golden book.py

  Scenario: RTM-02 — the pipelined event's BBO is consistent with the capture
    Given a symbol with levels in slots 0..k-1 and empty afterwards (ordered-list
      invariant: the best level lives in the first non-empty slot)
    When the book emits an event of that symbol through the A/B/C pipeline
    Then the BBO is the first non-empty level of the capture (slot 0 if there are levels)
    And the first ND levels of the capture match depth_tdata
    And a symbol with no levels emits a zero BBO, changed 0 and zero depth

  Scenario: RTM-03 — changed is computed over the capture and is not lost
    Given two consecutive identical events for the same symbol
    When the second is emitted
    Then bbo_changed is 0 in the second
    And an event with a distinct change is 1

  Scenario: RTM-04 — the output handshake holds the pipelined event
    Given a consumer that lowers bbo_tready after observing bbo_tvalid
    When the event comes from the A/B/C stage pipeline
    Then bbo_tvalid and the payload stay stable until tready rises
    And it is delivered exactly once, without loss or duplicate

  Scenario: RTM-LAT-01 — the re-measured latency meets the re-derived threshold
    Given the DW=32 parser→book chain over the fixed latency sequence
    When the wire→BBO latency per message type is measured after the pipeline
    Then the total mean is ≤ 70 cycles (re-derived from 48 over the real feed)
    And the re-run produces the identical histogram

  Scenario: RTM-REG-01 — the 64-bit regression stays green with the pipeline
    Given the pipelined book with DW=64 (default)
    When the phase-1 and phase-2 suites are re-run
    Then all tests keep passing unchanged

  # --- iteration 12 (2026-08-19): market-open real feed — K=64 and drain ---
  # Addendum iteration 12 of spec.md. The real open stretch (210k packets,
  # refs ~1.6-1.7M) exposes two structural bugs: K=19 truncated refs > 2^19
  # (254 lost events, exact numeric reproduction) and the QB=46 parser
  # deadlocked on messages > 44 B (I=50 B, 2+len=52 > 46).

  Scenario: REF64-01 — the K=64 book reproduces the real market-open feed
    Given the decapsulated real open-day pcap (refs > 2^19, 20 symbols)
    When the book processes the subset messages with K=64
    Then the BBO is bit-exact against the golden book.py
    And there are no anomalies (no ref truncated nor collided)

  Scenario: REF64-02 — refs differing by 2^19 do not collide with K=64
    Given two orders whose refs differ exactly by 2^19 (same residue mod 2^19)
    When the book processes them with K=64
    Then both live in the table without a duplicate-ref error
    And the deletion of each acts on its own order
    (with K=19 the second add is rejected as duplicate and its deletion counts
    an anomaly — the amendment's red)

  Scenario: OVR-01 — the parser drains oversize messages without deadlock
    Given a datagram with a 50 B message (2+len=52 > QB=46) between normal messages
    When the 32-bit parser (or the chain) processes it
    Then the datagram's tlast is accepted and the stream continues
    And the messages after the oversize are processed correctly
    And no record is emitted for the oversize message (outside the subset)

  Scenario: OVR-PUSH-01 — level overflow with push-out (SEC-OV-01 amended)
    Given a symbol with the ask list full at P levels (no holes)
    When an add at a price better than the current worst level arrives
    Then the new level enters the top-P and the worst leaves (push-out)
    And the BBO reflects the new best price exactly
    And no error is signalled
    When an add at a price worse than the current worst level arrives
    Then the op is discarded and SEC-OV is signalled (error pulse)
    And the BBO does not change
    (with the pre-13 rejection the first case froze the BBO — the red of event
    3353 over the real feed)

  Scenario: OVR-DRN-01 — the oversize NOII is drained without breaking the stream
    Given a datagram with interleaved I messages (2+len > QB)
    When the 32-bit parser (QB=46) processes them against the real feed
    Then each I message is drained by the stream with the beat boundary
    And the next message stays byte-aligned (drop_left with the cycle's beat and
      the low-tail retention at the crossing)
    And the chain BBO is bit-exact against the golden book.py
    (iter 13-14 reds: 3 bytes eaten by the crossing -> loc 14 as 13)

  Scenario: OVR-DEPTH-01 — the depth respects the push-out contract
    Given the real feed (loc13 exceeds 32 levels at the peak)
    When the book emits the top-N depth
    Then the depth is bit-exact until the first re-entry of a level discarded at
      the peak (>P)
    And from there there is no phantom price (every depth price is in the golden;
      the quantities of re-entered levels may be partial)
    (bit-exact depth with finite P is impossible for a feed with >P peaks; the
    URAM tail would provide it — option B, not implemented)

  Scenario: RTM-LAT-01 — latency threshold re-derived over the real feed
    Given the representative market-open feed (2,289 NOII)
    When the DW=32 parser->book chain processes the subset
    Then the wire->BBO histogram is deterministic across re-runs
    And the total mean stays <= 70 cycles (203.3 ns measured; the iter-7 48
      threshold was a lucky, non-representative stretch)