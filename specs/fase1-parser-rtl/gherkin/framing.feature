# framing.feature — MoldUDP64 framing, sequence and gap detection

Mirror of "Acceptance criteria" 4 of `spec.md`.

# language: en
Feature: MoldUDP64 framing and sequence-gap detection
  As a market-data pipeline
  I want the parser to validate session, seq and count and detect sequence gaps
  So that the real MoldUDP64 feed is handled without losing messages

Scenario: FRM-01 — the parser extracts session, seq and count from each MoldUDP64 payload
  Given a MoldUDP64 payload with a session, a sequence number and a message count
  When the RTL processes the framing header
  Then it extracts the session, seq and count correctly
  And emits that packet's messages in order

# language: en
Scenario: FRM-02 — the expected seq advances as seq_prev plus count_prev
  Given a sequence of packets whose seq are consecutive per the previous count
  When the RTL processes the sequence
  Then the expected seq of packet n is the seq of packet n-1 plus its count
  And it signals no gap

# language: en
Scenario: SEC-GAP-01 — a sequence hole is signalled, counted and parsing continues
  Given a sequence of packets where seq_actual is greater than expected
  When the RTL processes the packet with the hole
  Then it signals gap_detected and counts it internally
  And continues processing the packet's messages without aborting

# language: en
Scenario: SEC-GAP-02 — a seq equal to the expected does not signal a gap
  Given a sequence of consecutive packets without holes
  When the RTL processes each packet
  Then it signals no gap_detected

# language: en
Scenario: SEC-FRM-03 — a session change resets the expected seq
  Given a payload whose session differs from the previous packet
  When the RTL processes the session change
  Then it resets the expected-sequence state to the first seq of the new session
  And does not count the reset as a gap

# language: en
Scenario: SEC-FRM-04 — a packet with count equal to zero is valid
  Given a new session with seq 100 and a zero message count
  And the 20-byte payload ends with tkeep equal to 8'b11110000 at DW=64
  When the next packet of the same session arrives in a new burst also with seq 100
  Then it emits no record and signals no error
  And signals no gap because the expected seq advanced by zero

# language: en
Scenario: SEC-FRM-05 — unaligned datagrams do not share an AXI word
  Given two consecutive MoldUDP64 payloads whose lengths are not multiples of eight
  And each payload uses its own tlast and tkeep in the last word
  When the RTL processes both bursts
  Then it extracts both headers without incorporating padding between them
  And the complete output is byte-exact against the golden

# language: en
Scenario: SEC-FRM-06 — an invalid tkeep mask is discarded with a signal
  Given a beat with zero tkeep, with holes, or partial without tlast
  When the RTL accepts the beat and then receives an intact packet
  Then it pulses error and discards the invalid datagram
  And processes the following packet without corrupt state or header

# language: en
Scenario: SEC-FRM-07 — count and tlast must close the datagram at the same byte
  Given a payload whose count ends before tlast, leaves residual bytes, or is zero with additional payload
  When the RTL finishes consuming the declared messages
  Then it pulses error and drains the remaining bytes up to tlast
  And never interprets those bytes as the header of a new packet

# language: en
Scenario: SEC-FRM-08 — the input stays stable during backpressure
  Given a valid burst in which the parser deasserts tready
  When tvalid stays active without handshake
  Then tdata, tkeep and tlast keep their value exactly
  And the beat transfers only once when tready returns