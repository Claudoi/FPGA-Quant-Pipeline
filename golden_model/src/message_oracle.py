"""Phase-1 message oracle: consumer of the RTL stream -> Annex A record.

The RTL (phase 1) consumes the MoldUDP64 payload already decapsulated from
IP/UDP: a sequence of packets, each one `session(10) + seq(8) + count(2) +
[len u16 + message]*`. This module is the **oracle**: it walks exactly that
stream and, for each message of the 10 subset types (`S,R,A,F,E,C,X,D,U,P`),
emits the normalized Annex A record of `specs/fase1-parser-rtl/spec.md`:

    word0 = (msg_type<<56)|(locate<<40)|(length<<32)|(msg_idx)
    word1 = ts_ns
    body  = bytes of the message after the 11 B ITCH common header (wire
            fields, big-endian; the same struct as golden_model/itch/messages.py)

Compared byte-for-byte against the RTL output in cocotb. Types outside the
subset are validated by length and counted, without emitting a record
(identical to the phase-1 criterion 6 semantics).

Determinism: same stream -> same records. Wire order, no swap.
"""
from __future__ import annotations

from typing import Iterator, Sequence

from ..itch.messages import MESSAGE_LENGTHS

#: phase-1 subset types (10): S,R,A,F,E,C,X,D,U,P
SUBSET_TYPES = frozenset("SRCFDECXUAP")

#: type -> total message length (bytes); basis for length validation.
_FOUND: dict[str, int] = MESSAGE_LENGTHS

#: message record tuple: (word0, word1_ts, body bytes)
MessageRecord = tuple[int, int, bytes]

COMMON_HEADER_LEN = 11


class BadMessageError(ValueError):
    """Message with a type outside the table, incoherent length, or truncated."""


def _word0(msg_type: str, locate: int, length: int, msg_idx: int) -> int:
    return (ord(msg_type) << 56) | (locate << 40) | (length << 32) | (msg_idx & 0xFFFFFFFF)


def iter_message_records(
    packets: Sequence[tuple[int, list[bytes], bytes]],
) -> Iterator[MessageRecord]:
    """Walks the MoldUDP64 packet stream and emits Annex A records.

    `packets` follows the `binaryfile_to_pcap.iter_pcap_packets` contract:
    for each packet, (seq, [ITCH messages], raw payload). The seq drives the
    global message count; the raw payload is not required to decode.
    """
    global_idx = 0
    for _seq, messages, _payload in packets:
        for raw in messages:
            mtype = chr(raw[0])
            declared = len(raw)
            expected = _FOUND.get(mtype)
            if expected is None:
                raise BadMessageError(f"msg {global_idx}: unknown type {mtype!r}")
            if declared != expected[1]:
                raise BadMessageError(
                    f"msg {global_idx}: type {mtype!r} declares {declared} B, "
                    f"the spec requires {expected[1]} B"
                )
            if mtype not in SUBSET_TYPES:
                global_idx += 1
                continue
            locate = int.from_bytes(raw[1:3], "big")
            ts_ns = int.from_bytes(raw[5:11], "big")
            w0 = _word0(mtype, locate, declared, global_idx)
            yield w0, ts_ns, raw[COMMON_HEADER_LEN:]
            global_idx += 1