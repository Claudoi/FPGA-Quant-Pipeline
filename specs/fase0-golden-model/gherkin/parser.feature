# language: en
Feature: ITCH 5.0 parser over BinaryFILE
  The golden model parser iterates emi.nasdaq.com BinaryFILEs, validates all
  ITCH 5.0 message types by length, decodes the common header in all of them
  and the full fields of the book subset (A/F/E/C/X/D/U) plus R, S and H. It is
  the entry gate of all the project's real data.

  Scenario: PAR-01 iterate a complete BinaryFILE without errors
    Given the main-day BinaryFILE downloaded and verified with md5
    When the parser iterates the complete file
    Then it consumes all messages without exceptions
    And the last processed message has index equal to the total minus one

  Scenario: PAR-02 per-type message count of the real day
    Given the main-day BinaryFILE
    When the parser iterates the complete file
    Then it emits a per-type count table
    And the sum of the counts equals the file's total messages
    And the book subset types have counts greater than zero

  Scenario Outline: PAR-03 decodes the full fields of the <tipo> subset
    Given a synthetic message of type <tipo> written as a hex literal from the spec PDF
    When the parser decodes it
    Then each extracted field matches the expected value <campos>

    Examples:
      | tipo | campos                                          |
      | A    | locate, tracking, timestamp, ref, side, qty, symbol, price |
      | F    | locate, tracking, timestamp, ref, side, qty, symbol, price, attribution |
      | E    | locate, tracking, timestamp, ref, executed qty, match_id   |
      | C    | locate, tracking, timestamp, ref, executed qty, match_id, printable, price |
      | X    | locate, tracking, timestamp, ref, cancelled qty             |
      | D    | locate, tracking, timestamp, ref                            |
      | U    | locate, tracking, timestamp, original ref, new ref, qty, price |
      | R    | locate, tracking, timestamp, symbol, market category   |
      | S    | tracking, timestamp, event code                       |
      | H    | locate, tracking, timestamp, trading state              |

  Scenario: SEC-01 an unknown message type is a hard error
    Given a BinaryFILE stream with a message of a type undefined in ITCH 5.0
    When the parser reaches it
    Then it raises an exception indicating the type and the message index

  Scenario: SEC-02 an incorrect length for the type is a hard error
    Given a BinaryFILE stream whose A message declares a length different from the specified one
    When the parser reaches it
    Then it raises an exception indicating the declared length, the expected one and the message index

  Scenario: SEC-03 a message truncated at the end of the file is a hard error
    Given a BinaryFILE stream whose last message declares more bytes than remain
    When the parser reaches it
    Then it raises a truncated-message exception with the message index