# language: en
Feature: Golden model order book
  The book maintains per symbol the live order table (by order reference),
  the aggregated price levels and the BBO. It is the reference semantics that
  the phase-2 RTL must reproduce bit-exact.

  Scenario: LIB-01 add order creates a level and updates the BBO
    Given an empty book for the test symbol
    When an A buy message arrives at price 1000000 and qty 100
    Then the symbol's BBO is bid 1000000 x100, ask 0 x0
    And the change flag of the emitted record is 1

  Scenario: LIB-02 partial execute reduces qty without moving the BBO price
    Given a book with a buy order of 100 at price 1000000 as the best bid
    When an E message of 40 arrives on that order
    Then the BBO is bid 1000000 x60
    And the order stays live with a remaining qty of 60

  Scenario: LIB-03 total execute deletes the order and retracts the BBO
    Given a book with a single buy order of 100 at price 1000000
    When an E message of 100 arrives on that order
    Then the order ceases to exist
    And the BBO becomes bid 0 x0

  Scenario: LIB-04 cancel and delete keep levels consistent
    Given a book with two sell orders at the same price 2000000 for 50 and 70
    When an X of 30 arrives on the first and a D on the second
    Then the ask level 2000000 is left with qty 20
    And after an X of 20 on the first the 2000000 level disappears

  Scenario: LIB-05 replace is atomic and emits a single resulting state
    Given a book with a buy order of 100 at price 1000000 as the best bid
    When a U message replaces it with price 990000 and qty 200
    Then the resulting BBO is bid 990000 x200
    And only one record is emitted for the U message
    And the original reference ceases to exist and the new one stays live

  Scenario: LIB-06 an empty book emits a zero BBO
    Given a book whose orders have all been deleted
    When the record of the last modifying message is emitted
    Then bid and ask hold price 0 and qty 0

  Scenario: SEC-04 operation on an unknown order reference is counted as an anomaly
    Given a book in progress
    When an E, X, D or U arrives on a nonexistent reference
    Then the operation is skipped without modifying the book
    And the anomaly counter increments
    And the run does not abort

  Scenario: SEC-05 a crossed book in auction state does not trigger the invariant
    Given a symbol in a trading state other than continuous per S and H messages
    When the best bid exceeds the best ask by orders crossed in auction
    Then the run continues without invariant violation
    And the BBO is emitted as-is

  Scenario: INV-01 book invariants are checked message by message
    Given a run with active invariants in strict mode
    When any message would leave non-positive quantities, duplicate references, inconsistent levels, or a closed/crossed book in continuous trading
    Then the run aborts indicating the violated invariant and the message index

  Scenario: SEC-08 a locked book in continuous trading on real data is counted, not aborted
    Given a book in default mode (not strict)
    And a symbol whose book stayed locked during a halt and resumed trading
    When the next modifying message of that symbol arrives
    Then the run does not abort
    And the cross event is counted with its message index