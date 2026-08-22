# language: en
Feature: Reference vectors for the RTL
  The vectors are the bit-exact contract against which the RTL will be verified
  in phases 1-2: one 40-byte binary record per modifying message of the subset
  symbols, plus a text dump for inspection.

  Scenario: VEC-01 one record per subset modifying message with a change flag
    Given a run over synthetic data with subset and other symbols' messages
    When the vectors are generated
    Then there is exactly one record per A/F/E/C/X/D/U message of the subset symbols
    And no record corresponds to messages of other types or other symbols
    And the change flag is 1 if and only if the BBO differs from the previous record of the same symbol

  Scenario: VEC-02 fixed 40-byte binary layout per record
    Given a generated vector file
    When its size is measured
    Then it is an exact multiple of 40 bytes
    And each record decoded with the Annex-A layout produces valid fields

  Scenario: VEC-03 binary to text round trip preserves fields
    Given a generated binary vector file
    When it is dumped to text and the binary is re-read
    Then each text line reproduces field by field its binary record

  Scenario: VEC-04 message indices are global and monotonic
    Given a vector file generated over a stream with several symbols' messages
    When the records are walked
    Then msg_idx is strictly increasing
    And msg_idx corresponds to the message index in the original BinaryFILE