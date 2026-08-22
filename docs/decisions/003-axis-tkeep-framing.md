# 003 — AXI valid-bytes contract for UDP framing (`s_axis_tkeep`)

**Date:** 2026-08-15 · **Status:** approved and implemented (ITCH phase 1,
phase-3 integration; MDP3 phase 4 pending red→green)

**Campaigns affected:** ITCH phase 1, phase-3 integration and MDP3 phase 4

## Problem

The parsers receive already-decapsulated UDP payloads via
`s_axis_tdata/tvalid/tready/tlast`, but the interface does not state how many
bytes of the last word are valid. The ITCH testbenches hid that absence by
concatenating datagrams before forming words: a single transfer could contain
the end of packet N and the start of N+1 while `tlast` pretended to delimit N.
That transfer is not representable in AXI-Stream, where `tlast` qualifies the
whole beat.

With real words and padding at the end of the burst, the ITCH parser keeps
those bytes ahead of the next header. In MDP3, the padding can falsely satisfy
`msg_size` when the truncated message is missing fewer than `DW/8` bytes. The
local ITCH pcap that motivated the review contains 91 payloads and none is
8-byte aligned, so the edge is part of the real flow.

## Decision

The network-input tops adopt `s_axis_tkeep[DW/8-1:0]`. `tkeep` keeps the
standard bit-to-lane association, while this project restricts the accepted
masks to full word or a contiguous MSB prefix. No own byte-count is introduced
and the internal parser→order book interface is not changed. The elaborations
supported in this campaign are `DW ∈ {32, 64}`.

Each bit qualifies its conventional lane:

```text
s_axis_tkeep[k] == 1  =>  s_axis_tdata[8*k +: 8] is valid
```

The payload is presented MSB-first. Therefore the valid bytes of a partial word
form a prefix from the MSB. In DW=64, four valid bytes are represented with
`tkeep=8'b11110000`; in DW=32, with `tkeep=4'b1111` if the word is complete or
`4'b1100` if it contains two bytes.

For `BYTES=DW/8` and `1 <= valid_bytes <= BYTES`, the only valid partial mask is
`((1 << valid_bytes) - 1) << (BYTES - valid_bytes)`. The bits of `tdata`
associated with `tkeep=0` are *don't care*: no parser may require them to be
zero or inspect them to make decisions.

## Handshake contract

- A transfer happens only with `s_axis_tvalid && s_axis_tready`.
- `s_axis_tdata`, `s_axis_tkeep` and `s_axis_tlast` remain stable during any
  input-backpressure cycle.
- Every non-final beat uses `tkeep={DW/8{1'b1}}`.
- The final beat uses a contiguous MSB prefix of ones followed by zeros.
- `tkeep==0`, a mask with holes or a partial word without `tlast` is invalid
  framing: pulse `error` and discard the current datagram. If the invalid beat
  carries `tlast`, the parser may accept a new datagram immediately; if not, it
  drains inputs until it accepts the `tlast` that closes it.
- Bytes with `tkeep=0` are never incorporated into the queue nor count toward
  `msg_size`, headers or ITCH lengths.
- There is no datagram rollback: the complete messages closed before a defect
  remain emitted and counted. Only the incomplete message is cancelled and the
  rest of the invalid burst is discarded.
- A producer that always delivers full words may set `tkeep` to all ones; no
  implicit compatibility with an absent port is added.

## Changes per component

### `itch_parser`

- Adds `s_axis_tkeep` to the input port.
- Compacts, in stream order, only the bytes marked as valid.
- Increments `qn` by the number of valid bytes, not by `DW/8`.
- Latches end-of-packet only when accepting a beat with `tlast`.
- The `count` must match exactly the physical datagram boundary. On closing the
  last message — or on finishing the 20 bytes of a header with `count=0` —
  `tlast` and zero residual valid bytes must have been accepted.
- If `count` ends without `tlast`, if valid bytes remain after the last message
  or if `count=0` carries additional payload, it pulses `error` and drains until
  the `tlast`; those bytes never form a new header.
- On truncation or an invalid mask it cancels the incomplete message, preserves
  the outputs and the `msg_idx` of already-closed messages, and waits for a new
  datagram.

The Annex A format and the output ports do not change.

### `itch_chain`

- Adds `s_axis_tkeep` to its public input and connects it to `itch_parser`.
- Does not add `tkeep` to the parser→order book link: Annex A emits full words
  and its padding is a defined part of the normalized record.
- The phase-3 XDC must include min/max delays for `s_axis_tkeep[*]`.

### `mdp3_parser`

- Adds `s_axis_tkeep` to the input port.
- `qavail_eff` and the pointers advance by valid bytes.
- A `msg_size` cannot be completed with lanes whose `tkeep` is zero.
- If `tlast` arrives before the declared message is collected, it pulses
  `error`, empties the packet-capture state and accepts a later complete packet.
- As an explicit decision of this project, a packet of exactly 12 header bytes
  and no message is accepted as empty and emits no records; this policy is not
  presented as a general requirement of the CME protocol. One or more residual
  bytes that do not even form the whole `msg_size` field are truncation, pulse
  `error` and do not block recovery.
- The complete records preceding a truncation or invalid mask remain
  observable; the parser neither stores nor reverts the full datagram.

The schema, the ping-pong buffers, the `MAX_MSG` limit, the template selector
and Annex M do not change in this campaign. Their findings have separate loops.

## Drivers and oracle

The drivers produce a list of beats `(data, keep, last)` per datagram. A packet
is split and padded before the next one begins; bytes are never concatenated
across `tlast`.

The real replay keeps the list of payloads returned by the decapsulator and
emits one burst per payload. The evidence must check that the number of input
handshakes with `tlast` matches the number of packets processed. Every driver
incorporates a monitor that, while `tvalid && !tready`, requires the joint
stability of `(tdata, tkeep, tlast)` until the handshake.

The shared helpers are reused between ITCH DW=64, parser DW=32 and chain DW=32.
MDP3 may keep its area helper if it applies exactly the same mask contract.

## Mandatory red matrix

| ID | Case | Observable property |
|---|---|---|
| AXI-KEEP-01 | Two unaligned ITCH packets, DW=64 | two `tlast`, correct headers and output |
| AXI-KEEP-02 | `count=0` of 20 B with `tkeep=8'b11110000`, followed by a valid packet | no gap/error and no padding in the header |
| AXI-KEEP-03 | ITCH `count` smaller or larger than the physical messages | `error`, no residue interpreted as header, and recovery |
| AXI-KEEP-04 | ITCH DW=32/64 truncated by 1..`BYTES-1` B after complete messages | no partial record; previous records preserved |
| AXI-KEEP-05 | ITCH chain DW=32 and ND=3 with unaligned packets | BBO/depth bit-exact vs golden |
| AXI-KEEP-06 | Real ITCH replay | one `tlast` handshake per payload; bit-exact output |
| AXI-KEEP-07 | MDP3 DW=32 truncated by 1..3 B | `error`, no partial record, previous records preserved and recovery |
| AXI-KEEP-08 | MDP3 DW=64 truncated by 1..7 B | same property |
| AXI-KEEP-09 | MDP3 header-only and 1 B residual | valid empty; invalid residual without lockup |
| AXI-KEEP-10 | Invalid masks ITCH and MDP3, DW=32/64 | zero, holes and non-final partial give `error`, discard and recovery |
| AXI-KEEP-11 | Input backpressure in ITCH DW=64, chain DW=32 and MDP3 DW=32/64 | data/keep/last stable until handshake |
| AXI-KEEP-12 | Adversarial MSB/LSB orientation | only the MSB prefix produces the correct stream |

Every test must first observe a red caused by the port or by the absent
behavior. A compile error due to a non-existent port is a valid red only for the
first interface test; the subsequent functional tests must fail on incorrect
output, error or recovery.

## Gates and close

The campaign does not close until, from clean builds, these run:

1. ITCH parser DW=64;
2. ITCH parser DW=32;
3. chain DW=32, including ND=3;
4. real replay if the local pcap is present; otherwise, explicit SKIP;
5. MDP3 DW=32 and DW=64;
6. Verilator `--Wall` lint of both parsers and `itch_chain`;
7. framing mutation: always count `BYTES`, invert MSB/LSB, accept a mask with
   holes, accept a partial without `tlast`, omit draining, allow padding to
   complete `msg_size` and omit the exact `count↔tlast` close;
8. `synth_check.py` with the new port covered by the XDC;
9. Gherkin completeness and `git diff --check`.

The verify-reports must paste the new outputs and replace, not accumulate as
current, the evidence obtained with the drivers that concatenated datagrams.

## Out of scope

- Adding 10G MAC or Ethernet/IP/UDP decap.
- Adding `tkeep` to the parsers' normalized output.
- Fixing MDP3's `schemaId/version` or `MAX_MSG`.
- Testing MDP3 output backpressure.
- Closing phase-3 timing without Vivado.
- Refactoring the order book.