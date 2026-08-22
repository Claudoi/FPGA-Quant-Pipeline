# language: en
Feature: BinaryFILE to MoldUDP64 pcap wrapper
  binaryfile_to_pcap.py converts the Nasdaq sample files into real pcaps
  (Ethernet/IP/UDP/MoldUDP64) to feed the RTL testbenches. Its correctness is
  demonstrated by byte-exact round-trip.

  Scenario: PCA-01 the pcap opens with tcpdump without errors
    Given a valid input BinaryFILE
    When the pcap is generated and tcpdump -r runs over it
    Then tcpdump reads it without errors
    And all datagrams are UDP toward the configured IP and port

  Scenario: PCA-02 packing respects the configurable payload maximum
    Given a BinaryFILE with messages of varied lengths
    When the pcap is generated with the default limit
    Then no datagram exceeds 1400 bytes of UDP payload
    And the MoldUDP64 message-count field matches the datagram's messages

  Scenario: PCA-03 monotonic sequence numbers from 1
    Given a generated pcap
    When the MoldUDP64 packets are walked in order
    Then the first sequence number is 1
    And each packet advances the sequence by its message count

  Scenario: PCA-04 pcap round trip to an identical BinaryFILE stream
    Given an input BinaryFILE and the pcap generated from it
    When the message payloads of all packets are extracted in sequence order
    Then the reconstructed stream is byte-exact to the payload of the original BinaryFILE

  Scenario: SEC-06 a message larger than the max payload produces a clear error
    Given a BinaryFILE with a message whose length exceeds the max UDP payload
    When the conversion runs
    Then it aborts with an error indicating the message index and its length