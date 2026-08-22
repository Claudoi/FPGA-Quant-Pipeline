# replay.feature — real pcap replay and frozen vectors

Mirror of "Acceptance criteria" 8 of `spec.md`.

# language: en
Feature: Pcap replay and hybrid oracle
  As a market-data pipeline
  I want to verify the parser against real data (replay) and frozen vectors
  So that byte-exact correctness against the true feed is assured

Scenario: REP-01 — the RTL reproduces the committed frozen vectors byte-exact
  Given a frozen message vector in verification/vectors/messages/
  When the parser processes the synthetic pcap that originated it
  Then its output is byte-exact against the frozen vector

# language: en
Scenario: REP-02 — the RTL over a real-day pcap is byte-exact against the --emit-messages oracle
  Given a pcap generated from the real day with binaryfile_to_pcap.py (local, not committed)
  And the golden model --emit-messages oracle over that same pcap
  When the RTL processes the input stream
  Then the subset messages' output is byte-exact against the oracle
  And it observes exactly one input handshake with tlast per decapsulated payload
  And the line rate holds over the real back-to-back stretches