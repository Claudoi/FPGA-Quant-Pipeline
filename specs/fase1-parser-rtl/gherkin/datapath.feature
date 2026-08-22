# datapath.feature — line rate, alignment and 64-bit datapath

Mirror of "Acceptance criteria" 2 and 3 of `spec.md`.

# language: en
Feature: 64-bit datapath at line rate with a message aligner
  As a market-data pipeline
  I want the datapath to accept one word per cycle in the worst case and align messages
  So that the hard line-rate requirement of the master document is met

Scenario: LIN-01 — the parser bounds stalls in the agreed stretch with QB=64
  Given an input of four A/U messages back-to-back and QB equal to 64
  When the downstream consumes with tready high
  Then the output is bit-exact against the golden
  And the accumulated stall-cycle counter is less than or equal to 24

# language: en
Scenario Outline: ALN-01 — the aligner decodes correctly any offset within the word
  Given a message of type <tipo> whose first byte falls at offset <offset> of the 64-bit word
  And whose length crosses <cruce> the word boundary
  When the RTL processes the stream
  Then it decodes the message and produces the correct record byte-exact
  And adds no stall cycles relative to the non-crossing alignment

  Examples:
    | tipo | offset | cruce |
    | A    | 0      | yes   |
    | A    | 1      | yes   |
    | A    | 2      | yes   |
    | A    | 3      | yes   |
    | A    | 4      | yes   |
    | A    | 5      | yes   |
    | A    | 6      | yes   |
    | A    | 7      | yes   |

# language: en
Scenario: SEC-LIN-01 — out-of-subset messages do not break the line rate
  Given a canonical H message outside the subset between two A messages
  When the downstream consumes with tready high
  Then the H length is validated and the flow continues without error
  And records are only emitted for the subset messages