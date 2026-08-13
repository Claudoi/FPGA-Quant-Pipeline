"""Tests del oráculo de mensajes de fase 1 (Anexo A de fase1-parser-rtl).

El oráculo `message_oracle.iter_message_records` consume el mismo stream que
alimenta al RTL (payload MoldUDP64: sesión + seq + count + mensajes ya
decapado de IP/UDP) y emite, para cada mensaje de los 10 tipos del subset, las
palabras del registro normalizado del Anexo A (word0 cabecera, word1 ts, words
2..N cuerpo del wire). Es la fuente del criterio 1 y del comparador cocotb.

Nomenclatura espejo: título = escenario Gherkin de fase1 normalizado
(minúsculas, espacios->_, prefijo test_). Aquí se ejercitan los del oráculo.
"""
from __future__ import annotations

import io
import struct
import unittest

from golden_model.src.message_oracle import iter_message_records


def pcap_packets(messages: list[bytes]) -> list[tuple[int, list[bytes], bytes]]:
    """Construye una lista de "paquetes" MoldUDP64 tal como la entrega
    iter_pcap_packets: (seq, mensajes, payload crudo). Pone N mensajes por
    paquete según el prefijo de count."""
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
    """Costruye un mensaje Add Order 'A' válido (36 B) literal desde la spec."""
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
    """Costruye un System Event 'S' (12 B) literal desde la spec."""
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
    """Cubre criterio 1 (oráculo) — espejo de §PAR-01."""

    def test_par01_oraculo_emite_el_registro_anexo_a_para_cada_mensaje_del_subset(self):
        a = A(393, 1_000_000_000, 0x1122334455667788, b"\x01", 1000, b"AMZN    ", 1_234_567)
        s = S(393, 1_000_000_001, 0x4F)  # O = start of hours
        packets = pcap_packets([s, a])
        recs = list(iter_message_records(packets))
        self.assertEqual(len(recs), 2)
        # System Event (msg 0): len 12, body 1 B (event_code=0x4F)
        w0, w1, body = recs[0]
        self.assertEqual(w0, msg_word0(ord("S"), 393, 12, 0))
        self.assertEqual(w1, 1_000_000_001 + 0)  # ts real del mensaje S
        self.assertEqual(body, bytes([0x4F]))
        # Add Order (msg 1, after S): len 36, body 25 B
        w0, w1, body = recs[1]
        self.assertEqual(w0, msg_word0(ord("A"), 393, 36, 1))
        self.assertEqual(len(body), 25)
        # primeros 8 B del cuerpo: ref big-endian
        self.assertEqual(body[:8], struct.pack(">Q", 0x1122334455667788))

    def test_sec_par04_oraculo_valida_longitud_de_tipo_fuera_del_subset_sin_registro(self):
        # 'I' (NOII, 50 B) no está en el subset: se cuenta pero no emite.
        i = b"I" + struct.pack(">H", 1) + b"\x00\x00" + (0).to_bytes(6, "big") + b"\x00" * 39
        self.assertEqual(len(i), 50)
        recs = list(iter_message_records(pcap_packets([i])))
        self.assertEqual(recs, [])
        # el msg_idx del siguiente mensaje debe seguir contando la 'I'
        a = A(393, 2, 7, b"\x01", 10, b"AMZN    ", 3)
        recs = list(iter_message_records(pcap_packets([i, a])))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0][0] & 0xFFFFFFFF, 1)  # msg_idx global 1


class EmitMessagesBadLengthTest(unittest.TestCase):
    """Espejo de §SEC-PAR-03 / §SEC-FRM-01: longitud incoherente es error duro."""

    def test_sec_par03_oraculo_longitud_incoherente_es_error_duro(self):
        # 'A' con longitud distinta a 36
        malformed = b"A" + b"\x00" * 34  # 35 B
        with self.assertRaises(ValueError):
            list(iter_message_records(pcap_packets([malformed])))


if __name__ == "__main__":
    unittest.main()