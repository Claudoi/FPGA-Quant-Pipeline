# language: en
Feature: Campaign data: download and statistics
  The real feeds are never committed: they are downloaded with md5 verification
  to data/itch_sample/ (gitignored) and from them come the statistics that fix
  the symbol subset and the RTL memory sizing.

  Scenario: DAT-01 download verified with a correct md5
    Given the main-day file present on the server
    When fetch_itch.py runs
    Then the file lands in data/itch_sample/
    And its md5 matches the one published by Nasdaq

  Scenario: DAT-03 an unserved md5sum aborts fail closed with a clear error
    Given a server that serves the file but whose md5sum endpoint answers 404
    When fetch_itch.py runs without the skip flag
    Then it aborts with a clear error (no traceback) and a nonzero exit code
    And no usable file remains as a run input
    And with --no-md5-verify it downloads warning on stderr that integrity was not verified by md5

  Scenario: SEC-07 an incorrect md5 aborts without leaving a seemingly valid file
    Given a deliberately corrupted downloaded file
    When the verification runs
    Then the script aborts with an md5 error
    And no usable file remains as a run input

  Scenario: DAT-02 per-symbol sizing statistics
    Given the main-day BinaryFILE
    When a full run finishes
    Then a per-symbol table is emitted with messages, peak live orders and peak levels
    And from it select_subset.py writes verification/vectors/subset_symbols.json with the top 20 by peak live orders