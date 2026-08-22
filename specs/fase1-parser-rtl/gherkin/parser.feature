# parser.feature — subset message decoding + type/length handling

Functional mirror of "Acceptance criteria" 1, 6, 7 of `spec.md`.

# language: en
Feature: ITCH subset message decoding and type/length handling
  As a market-data pipeline
  I want the parser to decode the 10 subset types to normalized records
  and validate types/lengths without breaking the line rate
  So that the order book (phase 2) is fed byte-exact

Scenario: PAR-01 — each subset type decodes to a record byte-exact against the golden
  Given a subset message of type T from {S, R, A, F, E, C, X, D, U, P} in a synthetic pcap
  And the golden model --emit-messages oracle over the same pcap
  When the RTL processes the input stream
  Then the parser output is byte-exact against the oracle for that message
  And the record emits tlast at the end of the burst and msg_type matches

# language: en
Scenario: SEC-PAR-04 — an out-of-subset type is validated and advances the index without emitting a record
  Given a synthetic pcap containing an H message (outside the subset) between subset messages
  When the RTL processes the stream
  Then it emits no record for the H message
  And counts H in the global msg_idx and continues without breaking the line rate
  And the following A record reflects that H was consumed

Scenario: SEC-PAR-05 — a known out-of-subset type with an incorrect length gives an error
  Given an H message declaring 24 bytes though its canonical length is 25
  When the RTL processes it between two valid A messages
  Then it signals error and emits no record for H
  And continues with the second A message without misalignment

# language: en
Scenario: SEC-PAR-03 — an incoherent declared length cancels the message with error and continues
  Given an input stream containing a message whose declared length does not match the available bytes
  When the RTL processes the stream
  Then it signals error and discards that message's record
  And continues processing the next message without aborting the stream

# language: en
Scenario: SEC-FRM-01 — a truncated frame signals error and the parser continues at the next message
  Given a synthetic pcap whose payload ends in the middle of a message without the declared bytes
  When the RTL processes the stream
  Then it signals error on the truncated message
  And discards the rest of the datagram and continues with the next intact packet

# language: en
Scenario: SEC-FRM-02 — a message cannot be split between packets and is handled firmly
  Given a stream where tlast arrives in the middle of a message (count inconsistent with packet closure)
  When the RTL processes the stream
  Then it signals error and emits no partial record
  And resets the parsing state for the next packet