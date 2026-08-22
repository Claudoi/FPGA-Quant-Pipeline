# orderbook.feature — order book engine: message application and BBO

Mirror of "Acceptance criteria" 1-8 of the fase2-orderbook `spec.md`.
The semantics of each operation is EXACTLY that of `golden_model/src/book.py`.

# language: en
Feature: Annex-A message application to the order book and BBO emission
  As a market-data pipeline
  I want the engine to maintain orders, levels and BBO per symbol
  So that the BBO is bit-exact against the golden model

Scenario: BBO-01 — an add/execute/cancel/delete sequence produces the golden BBO
  Given a stream of Annex-A records of modifying types (A, F, E, C, X, D, U)
  When the order book applies each message
  Then the BBO emitted per symbol is bit-exact against the golden book.py
  And the changed signal matches the golden's event

Scenario: BBO-02 — an empty symbol stays isolated and an empty side emits (0,0)
  Given a symbol with no orders and another symbol with a bid order
  When the book processes only the second symbol's message
  Then the empty ask of the active symbol is (0,0)
  And no event is emitted for the symbol that stays empty

Scenario: SEC-U-01 — the U replace is atomic with no inconsistency window
  Given a symbol with a live order and a non-empty BBO
  When the book processes a U message (delete+add of a single state)
  Then the BBO emitted is that of the U's final state
  And an intermediate BBO with the order absent is never observed

Scenario: SEC-HZ-01 — add followed by execute on the same order (RAW)
  Given an A add and then an E execute on the same order_ref
  When the book processes the sequence
  Then the second message sees the first's state
  And the resulting BBO matches the golden

Scenario: SEC-HZ-02 — replace followed by execute on the new reference (RAW)
  Given a U that creates a new ref and then an E on that ref
  When the book processes the sequence
  Then the execute acts on the replaced order
  And the resulting BBO matches the golden

Scenario: SEC-DC-01 — execute/cancel/delete do not subtract twice
  Given an order with a known qty and a level with that qty
  When the book applies an execute and then a cancel on the remainder
  Then the total subtracted qty is exactly the initial one
  And the level stays consistent with the golden

Scenario: SEC-OV-01 — qty overflow is signalled with error
  Given a message that would reduce an order below its live qty
  When the book applies it and then receives a valid add
  Then it signals error for at least one cycle
  And produces no BBO for the invalid operation nor wraps silently
  And processes the following valid add

Scenario: SEC-AN-01 — an operation on an unknown ref counts an anomaly without aborting
  Given an execute/cancel/delete/replace whose order_ref is not in the book
  When the book applies it
  Then it increments anomaly_count
  And continues processing the next message without aborting the stream

Scenario: SEC-CR-01 — a crossed book in continuous trading counts cross_events
  Given a symbol in continuous trading where after a message bid >= ask
  When the book applies the message
  Then it increments cross_events
  And does not abort the stream (equivalent to the golden's strict_cross=False)

Scenario: MULTI-01 — messages of different symbols keep independent books
  Given a stream with interleaved messages of 2 or more subset locates
  When the book applies the sequence
  Then each symbol keeps its own BBO
  And each symbol's BBO matches the golden applied separately

Scenario: REPLAY-01 — the real feed BBO is identical to the golden
  Given the local day data/itch_sample/12302019… decapsulated (parser → book)
  When the book processes the subset messages
  Then the BBO sequence is bit-exact against the golden book.py

Scenario: REPLAY-02 — the frozen BBO vectors are reproduced
  Given a frozen BBO vector in verification/vectors/bbo/
  When the book processes the synthetic feed that originated it
  Then its BBO output is bit-exact against the frozen vector