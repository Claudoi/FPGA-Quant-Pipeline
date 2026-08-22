"""Tests of the phase-1 message oracle (Annex A of fase1-parser-rtl).

The oracle `message_oracle.iter_message_records` consumes the same stream that
feeds the RTL (MoldUDP64 payload: session + seq + count + messages already
decapsulated from IP/UDP) and emits, for each message of the 10 subset types,
the words of the normalized Annex A record (word0 header, word1 ts, words
2..N wire body). It is the source of criterion 1 and of the cocotb comparator.

Mirror naming: test titles are normalized scenario names (lowercase,
spaces->_, test_ prefix). Here the oracle's scenarios are exercised.
"""
from __future__ import annotations

import io
import struct
import unittest

from golden_model.src.message_oracle import iter_message_records


def pcap_packets(messages: list[bytes]) -> list[tuple[int, list[bytes], bytes]]:
    """Builds a list of MoldUDP64 "packets" as delivered by
    iter_pcap_packets: (seq, messages, raw payload). Puts N messages per
    packet according to the count prefix."""
    seq = 1
    packets = []
    idx = 0
    payload = struct.pack(">10sQH", b"SIM0000001", seq, len(messages)) + b"".join(
        len(m).to_bytes(2, "big") + m for m in messages
    )
    packets.append((seq, messages, payload))
    return packets


def A(
    locate: int, ts: int, ref: int, side: bytes, shares: int, stock: bytes, price: int
) -> bytes:
    """Builds a valid Add Order 'A' message (36 B) literally from the spec."""
    return (
        b"A"
        + struct.pack(">H", locate)
        + b"\x00\x00"                       # tracking
        + int.to_bytes(ts, 6, "big")
        + struct.pack(">Q", ref)
        + side
        + struct.pack(">I", shares)
        + stock
        + struct.pack(">I", price)
    )


def S(locate: int, ts: int, event: int) -> bytes:
    """Builds a System Event 'S' message (12 B) literally from the spec."""
    return (
        b"S"
        + struct.pack(">H", locate)
        + b"\x00\x00"
        + int.to_bytes(ts, 6, "big")
        + bytes([event])
    )


def msg_word0(msg_type: int, locate: int, length: int, msg_idx: int) -> int:
    return (msg_type << 56) | (locate << 40) | (length << 32) | (msg_idx & 0xFFFFFFFF)


class EmitMessagesOracleTest(unittest.TestCase):
    """Covers criterion 1 (oracle) — mirror of §PAR-01."""

    def test_par01_oraculo_emite_el_registro_anexo_a_para_cada_mensaje_del_subset(self):
        a = A(393, 1_000_000_000, 0x1122334455667788, b"\x01", 1000, b"AMZN    ", 1_234_567)
        s = S(393, 1_000_000_001, 0x4F)  # O = start of hours
        packets = pcap_packets([s, a])
        recs = list(iter_message_records(packets))
        self.assertEqual(len(recs), 2)
        # System Event (msg 0): len 12, body 1 B (event_code=0x4F)
        w0, w1, body = recs[0]
        self.assertEqual(w0, msg_word0(ord("S"), 393, 12, 0))
        self.assertEqual(w1, 1_000_000_001 + 0)  # real ts of the S message
        self.assertEqual(body, bytes([0x4F]))
        # Add Order (msg 1, after S): len 36, body 25 B
        w0, w1, body = recs[1]
        self.assertEqual(w0, msg_word0(ord("A"), 393, 36, 1))
        self.assertEqual(len(body), 25)
        # first 8 B of the body: ref big-endian
        self.assertEqual(body[:8], struct.pack(">Q", 0x1122334455667788))

    def test_sec_par04_oraculo_valida_longitud_de_tipo_fuera_del_subset_sin_registro(self):
        # 'I' (NOII, 50 B) is not in the subset: counted but not emitted.
        i = b"I" + struct.pack(">H", 1) + b"\x00\x00" + (0).to_bytes(6, "big") + b"\x00" * 39
        self.assertEqual(len(i), 50)
        recs = list(iter_message_records(pcap_packets([i])))
        self.assertEqual(recs, [])
        # the msg_idx of the next message must keep counting the 'I'
        a = A(393, 2, 7, b"\x01", 10, b"AMZN    ", 3)
        recs = list(iter_message_records(pcap_packets([i, a])))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0][0] & 0xFFFFFFFF, 1)  # global msg_idx 1


class EmitMessagesBadLengthTest(unittest.TestCase):
    """Mirror of §SEC-PAR-03 / §SEC-FRM-01: incoherent length is a hard error."""

    def test_sec_par03_oraculo_longitud_incoherente_es_error_duro(self):
        # 'A' with a length other than 36
        malformed = b"A" + b"\x00" * 34  # 35 B
        with self.assertRaises(ValueError):
            list(iter_message_records(pcap_packets([malformed])))


if __name__ == "__main__":
    unittest.main()