# mdp3.feature — phase 4: CME MDP 3.0 (SBE) parser verified against the schema golden

Mirror of "Acceptance criteria" 1-10 of the fase4-mdp3-parser `spec.md`.
The semantics of each subset field derives from the official CME SBE XML schema
(`templates_FixBinary.xml`, ftp.cmegroup.com), not from a second manual table in
the testbench.

# language: en
Feature: CME MDP 3.0 (SBE) parser at line rate with normalized Annex M
  As a market-data pipeline at 10G line rate
  I want to decode the MDP 3.0 packet and its SBE messages
  So that the ITCH pipeline is ported to the world's largest futures market

  Scenario: M3-GEN-01 — the golden round-trips decode(encode(m)) == m
    Given the official CME SBE XML schema loaded
    And known subset vectors with root, prices and groups of non-zero values
    When the encoder produces each message and the decoder reads it
    Then each observable decoded field matches its known value
    And PRICE9.mantissa and all multi-entry group entries are preserved
    And the passthrough of a non-subset template preserves the raw body

  Scenario: M3-GEN-02 — the loader derives the expected sizes from the XML
    Given the schema loaded
    When the expected size of each subset message is computed
    Then it matches blockLength + groups + 8 B root padding of the XML

  Scenario: M3-GEN-03 — schemaId and version come from the pinned XML
    Given the official schema with id 1 and version 12
    When the loader loads it and the encoder creates a message without overrides
    Then the SBE header contains schemaId 1 and version 12

  Scenario: M3-FRM-01 — the parser emits Annex M bit-exact vs the golden
    Given a synthetic corpus of MDP 3.0 packets (12 B header + messages)
    When the parser processes the stream
    Then the record sequence (w0, w1, body) is bit-exact identical
    And msg_seq_num, sending_time and msg_size of each message are correct

  Scenario: M3-FRM-02 — messages crossing word boundaries
    Given a corpus whose messages end and start at any byte
    And each UDP payload is presented as a burst with its own tkeep and tlast
    When the parser processes them at DW=32 and DW=64
    Then no message is lost or duplicated

  Scenario: M3-FRM-03 — worst case at 1 word/cycle without backpressure
    Given a packet with 24 literal template-47 messages of one entry and 64 B
    When they are presented at one valid word per cycle
    Then the run of valid-without-ready cycles is at most 16
    And the output sequence is bit-exact against the golden

  Scenario: M3-FRM-04 — exact packet closure leaves no ambiguous residue
    Given a packet of exactly 12 bytes and another with a residual byte after the header
    When the parser receives each with its exact tkeep and tlast
    Then the empty packet emits no records and no error
    And the residual pulses error and allows the next intact packet to be processed

  Scenario: M3-SUB-01 — the book subset is decoded field by field
    Given messages of the book templates (snapshot and incremental)
    When the parser decodes each entry of the NoMDEntries group
    Then Annex M contains security_id, rpt_seq, update_action, entry_type, price
      (mantissa+exponent), size, num_orders and price_level bit-exact against the golden

  Scenario: M3-FRM-05 — the framing consumes s_axis_tkeep byte by byte
    Given a packet presented with MSB-contiguous tkeep and the last partial beat
      declaring only its real bytes
    When the parser processes the stream
    Then Annex M is bit-exact against the golden
    And a message whose declared length would only complete with tkeep=0 lanes
      is not completed: it pulses error, emits no partial record
    And the next intact packet recovers bit-exact
    And a fully-zero tkeep beat in the middle of the burst is consumed without
      contributing bytes nor stalling

  Scenario: M3-SUB-02 — composite price and multi-entry groups
    Given a message with several entries and prices with negative exponents
    When the parser decodes
    Then each record carries its own mantissa and exponent without mixing
    And there is one record per entry in the same group order

  Scenario: M3-PASS-01 — raw passthrough of non-subset templates
    Given messages outside the subset and each 46, 47, 52 and 53 template with unsupported schemaId or version
    When the parser processes them
    Then it emits w0/w1 + raw body bit-exact
    And unknown schemaId or version do not abort the flow

  Scenario: M3-PASS-02 — the maximum message size is explicit and recoverable
    Given a valid passthrough message with msg_size 256 and another declaring 257 bytes
    When each arrives in its own packet followed by an intact packet
    Then the 256-byte message is preserved bit-exact
    And the 257-byte one pulses error, emits no partial record and allows recovery

  Scenario: M3-GAP-01 — sequence gap signalled without aborting
    Given a channel with msg_seq_num jumping a value
    When the parser receives the packet
    Then it signals gap_detected
    And a new channel (sequence restarted) does not count as a gap

  Scenario: M3-INV-01 — incoherent msg_size signals error
    Given a message whose size is smaller than the SBE header or overflows the packet
    When the parser processes it
    Then it signals error
    And does not hang nor corrupt the rest of the stream

  Scenario: M3-INV-02 — packet truncated by tlast handled
    Given a UDP payload missing between 1 and DW/8 minus 1 bytes of a message
    When the parser receives the input tlast
    Then it signals error if the declared message is not complete
    And waits for the next packet without corrupt state

  Scenario: M3-INV-03 — malformed group within the message
    Given an entry whose size exceeds msg_size or a group with numInGroup 0
    When the parser processes it
    Then it signals error or emits an empty record per the golden contract
    And does not silently truncate the following entries

  Scenario: M3-INV-04 — an invalid tkeep mask is discarded with a signal
    Given a beat with zero tkeep, with holes, or partial without tlast
    When the parser accepts it and then receives an intact packet
    Then it signals error and discards the invalid packet
    And processes the following packet without loss nor corrupt state

  Scenario: M3-SCH-01 — the RTL localparams match the v12 schema
    Given the official CME SBE XML schema and the specialized RTL
    When subset IDs, offsets, dimensions and blockLength are compared
    Then each structural RTL literal matches the XML value

  Scenario: M3-REG-01 — phases 1-3 stay green
    Given s_axis_tkeep propagated through itch_parser and itch_chain without changing the book link
    When the phase-1, phase-2 and phase-3 suites are re-run
    Then all tests keep passing unchanged
    And the DW=64 mdp3_parser passes its suite in regression

  Scenario: M3-BP-01 — the output stays stable during backpressure
    Given a record presented with m_axis_tvalid and m_axis_tready low
    When the consumer holds the stall for at least two cycles
    Then the m_axis_tdata, m_axis_tvalid and m_axis_tlast tuple stays stable
    And m_axis_tvalid stays active until the record is delivered exactly once

  Scenario: M3-BP-02 — the input stays stable while the parser does not accept
    Given a valid burst presented at DW=32 or DW=64
    When s_axis_tvalid is active and s_axis_tready stays low
    Then s_axis_tdata, s_axis_tkeep and s_axis_tlast stay stable
    And the beat is counted only once when the handshake happens