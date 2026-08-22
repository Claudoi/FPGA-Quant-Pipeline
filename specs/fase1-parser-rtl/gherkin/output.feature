# output.feature — AXI-Stream output interface

Mirror of "Acceptance criteria" 1 and 5 of `spec.md`.

# language: en
Feature: AXI-Stream output interface with backpressure
  As a market-data pipeline
  I want the AXI-Stream output to respect tvalid/tready/tlast and be holdable
  So that the downstream (order book) can backpressure without loss

Scenario: OUT-01 — each decoded message is emitted as a burst with tlast at the end
  Given a stream of subset messages of different types
  When the RTL emits the output
  Then each record starts with tvalid high and ends with tlast
  And the number of words in the burst matches the message type

# language: en
Scenario: OUT-02 — with tready low the parser holds the stream without loss or duplicate
  Given a downstream that intermittently lowers tready
  When the RTL processes the stream
  Then the final output contains the same burst of records as the oracle
  And no record is lost or duplicated

# language: en
Scenario: OUT-03 — the tvalid/tready handshake only advances when both are high
  Given a downstream with non-constant tready
  When the RTL performs the output handshake
  Then the data only advances in cycles with tvalid and tready high
  And the data does not change while tvalid is high and tready low