"""ITCH parser tests (independent oracle).

The synthetic payloads are built here with offsets written by hand from
NQTVITCHSpecification.pdf. NOTHING is imported from golden_model.itch.messages
to fabricate messages: if the canonical table is mis-transcribed, these tests
shout it.
"""
from __future__ import annotations

import io
import unittest

from golden_model.itch.parser import (
    BadLengthError,
    TruncatedMessageError,
    UnknownTypeError,
    iter_messages,
)


# --- payload builders with literal offsets from the spec PDF -------------

def _hdr(mtype: bytes, locate: int, tracking: int, ts: int) -> bytes:
    # offsets 0,1,3,5: type(1) locate(2) tracking(2) timestamp(6)
    return mtype + locate.to_bytes(2, "big") + tracking.to_bytes(2, "big") + ts.to_bytes(6, "big")


def p_s(event: bytes = b"O", ts: int = 0) -> bytes:
    return _hdr(b"S", 0, 0, ts) + event  # event code @11 -> 12 bytes


def p_r(locate: int = 1, stock: bytes = b"AAPL    ", ts: int = 1) -> bytes:
    rest = (
        stock  # stock @11 (8)
        + b"Q"   # market category @19
        + b"N"   # financial status @20
        + (100).to_bytes(4, "big")   # round lot size @21
        + b"N"   # round lots only @25
        + b"C"   # issue classification @26
        + b"  "  # issue sub-type @27 (2)
        + b"P"   # authenticity @29
        + b"N"   # short sale threshold @30
        + b"N"   # ipo flag @31
        + b" "   # luld ref price tier @32
        + b"N"   # etp flag @33
        + (0).to_bytes(4, "big")     # etp leverage factor @34
        + b"N"   # inverse indicator @38
    )
    return _hdr(b"R", locate, 0, ts) + rest  # 39 bytes


def p_h(locate: int = 1, state: bytes = b"T", ts: int = 2) -> bytes:
    return _hdr(b"H", locate, 0, ts) + b"AAPL    " + state + b" " + b"T1  "  # 25 bytes


def p_a(locate: int = 1, ref: int = 123456789, side: bytes = b"B",
        shares: int = 100, price: int = 1000000, ts: int = 3) -> bytes:
    # ref @11(8), side @19, shares @20(4), stock @24(8), price @32(4) -> 36 bytes
    return (
        _hdr(b"A", locate, 0, ts)
        + ref.to_bytes(8, "big")
        + side
        + shares.to_bytes(4, "big")
        + b"AAPL    "
        + price.to_bytes(4, "big")
    )


def p_f(locate: int = 1, ref: int = 222, ts: int = 4) -> bytes:
    return (
        _hdr(b"F", locate, 0, ts)
        + ref.to_bytes(8, "big")
        + b"S"
        + (50).to_bytes(4, "big")
        + b"AAPL    "
        + (2000000).to_bytes(4, "big")
        + b"MPID"  # attribution @36 -> 40 bytes
    )


def p_e(ref: int = 123456789, shares: int = 40, match: int = 777, ts: int = 5) -> bytes:
    # ref @11, executed shares @19(4), match @23(8) -> 31 bytes
    return _hdr(b"E", 1, 0, ts) + ref.to_bytes(8, "big") + shares.to_bytes(4, "big") + match.to_bytes(8, "big")


def p_c(ref: int = 123456789, ts: int = 6) -> bytes:
    # ref @11, shares @19(4), match @23(8), printable @31, price @32(4) -> 36 bytes
    return (
        _hdr(b"C", 1, 0, ts)
        + ref.to_bytes(8, "big")
        + (10).to_bytes(4, "big")
        + (888).to_bytes(8, "big")
        + b"Y"
        + (999000).to_bytes(4, "big")
    )


def p_x(ref: int = 123456789, shares: int = 30, ts: int = 7) -> bytes:
    return _hdr(b"X", 1, 0, ts) + ref.to_bytes(8, "big") + shares.to_bytes(4, "big")  # 23 bytes


def p_d(ref: int = 123456789, ts: int = 8) -> bytes:
    return _hdr(b"D", 1, 0, ts) + ref.to_bytes(8, "big")  # 19 bytes


def p_u(orig: int = 123456789, new: int = 987654321, ts: int = 9) -> bytes:
    # orig @11, new @19, shares @27(4), price @31(4) -> 35 bytes
    return (
        _hdr(b"U", 1, 0, ts)
        + orig.to_bytes(8, "big")
        + new.to_bytes(8, "big")
        + (200).to_bytes(4, "big")
        + (990000).to_bytes(4, "big")
    )


def binaryfile(*payloads: bytes) -> io.BytesIO:
    """BinaryFILE stream: length u16be + payload (BinaryFILE spec framing)."""
    return io.BytesIO(b"".join(len(p).to_bytes(2, "big") + p for p in payloads))


# Length table transcribed by hand from NQTVITCHSpecification.pdf
# (independent oracle of messages.py: if the two transcriptions differ,
# this test shouts it).
KNOWN_LENGTHS = {
    "S": 12, "R": 39, "H": 25, "Y": 20, "L": 26, "V": 35, "W": 12, "K": 28,
    "J": 35, "O": 21, "A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19,
    "U": 35, "P": 44, "Q": 40, "B": 19, "I": 50, "N": 20,
}


class TestParser(unittest.TestCase):
    def test_par01_iterar_un_binaryfile_completo_sin_errores(self):
        # a "complete" BinaryFILE: one message of each ITCH 5.0 type
        payloads = [t.encode() + b"\x00" * (n - 1) for t, n in KNOWN_LENGTHS.items()]
        msgs = list(iter_messages(binaryfile(*payloads)))
        self.assertEqual(len(msgs), len(KNOWN_LENGTHS))
        self.assertEqual(msgs[-1][0], len(KNOWN_LENGTHS) - 1)
        # and with messages with real fields
        stream = binaryfile(p_s(), p_r(), p_h(), p_a(), p_e(), p_c(), p_x(), p_d(), p_u(), p_f())
        msgs = list(iter_messages(stream))
        self.assertEqual(len(msgs), 10)
        self.assertEqual(msgs[-1][0], 9)  # last index = total - 1

    def test_par02_conteo_por_tipo_de_mensaje_del_dia_real(self):
        # the mirror verifies the counting behavior; the real day is reported separately
        stream = binaryfile(p_s(), p_s(), p_r(), p_a(), p_a(), p_a(), p_e())
        counts: dict[str, int] = {}
        for _, mtype, *_ in iter_messages(stream):
            counts[mtype] = counts.get(mtype, 0) + 1
        self.assertEqual(sum(counts.values()), 7)
        self.assertEqual(counts["A"], 3)
        self.assertGreater(counts["S"], 0)

    def test_par03_decodifica_campos_completos_del_subset(self):
        casos = [
            # (payload, type, fields expected after the header)
            (p_a(), "A", (123456789, "B", 100, "AAPL", 1000000)),
            (p_f(), "F", (222, "S", 50, "AAPL", 2000000, "MPID")),
            (p_e(), "E", (123456789, 40, 777)),
            (p_c(), "C", (123456789, 10, 888, "Y", 999000)),
            (p_x(), "X", (123456789, 30)),
            (p_d(), "D", (123456789,)),
            (p_u(), "U", (123456789, 987654321, 200, 990000)),
            (p_s(), "S", ("O",)),
            (p_h(), "H", ("AAPL", "T", "", "T1")),  # reserved decodes to ""
        ]
        for payload, tipo, esperado in casos:
            with self.subTest(tipo=tipo):
                msgs = list(iter_messages(binaryfile(payload)))
                self.assertEqual(len(msgs), 1)
                idx, mtype, locate, tracking, ts, fields = msgs[0]
                self.assertEqual(idx, 0)
                self.assertEqual(mtype, tipo)
                self.assertEqual(fields, esperado)
        # independent offset pin: the ref of A lives in bytes 11..18 of the payload
        self.assertEqual(p_a()[11:19], (123456789).to_bytes(8, "big"))
        # R: stock and market category (fields of the message example)
        _, mtype, locate, _, _, fields = list(iter_messages(binaryfile(p_r(locate=42))))[0]
        self.assertEqual(mtype, "R")
        self.assertEqual(locate, 42)
        self.assertEqual(fields[0], "AAPL")
        self.assertEqual(fields[1], "Q")

    def test_sec01_tipo_de_mensaje_desconocido_es_error_duro(self):
        stream = binaryfile(b"Z" + b"\x00" * 10)
        with self.assertRaises(UnknownTypeError):
            list(iter_messages(stream))

    def test_sec02_longitud_incorrecta_para_el_tipo_es_error_duro(self):
        # shorter than specified
        payload = p_a()[:-1]  # declares 35, type A requires 36
        stream = io.BytesIO(len(payload).to_bytes(2, "big") + payload)
        with self.assertRaises(BadLengthError):
            list(iter_messages(stream))
        # longer than specified (kills the `declared < expected` mutant)
        payload = p_a() + b"\x00"  # declares 37
        stream = io.BytesIO(len(payload).to_bytes(2, "big") + payload)
        with self.assertRaises(BadLengthError):
            list(iter_messages(stream))

    def test_sec03_mensaje_truncado_al_final_del_fichero_es_error_duro(self):
        stream = binaryfile(p_s())
        data = stream.getvalue()
        cortado = io.BytesIO(data + (36).to_bytes(2, "big") + p_a()[:10])
        with self.assertRaises(TruncatedMessageError):
            list(iter_messages(cortado))


if __name__ == "__main__":
    unittest.main()