"""Vectores de referencia: el contrato bit a bit entre golden model y RTL.

Layout canónico del registro (Anexo A de specs/fase0-golden-model/spec.md —
cambiarlo es un edit explícito de spec): 40 bytes, little-endian:

    msg_idx u64 | ts_ns u64 | bid_px u32 | bid_qty u32 | ask_px u32 |
    ask_qty u32 | locate u16 | msg_type u8 (ASCII) | flags u8 | reserved u32

`flags` bit0 = 1 si el BBO cambió respecto al registro anterior del símbolo.
Un registro por mensaje modificador (A/F/E/C/X/D/U) de cada símbolo del
subset. Sin cabecera de fichero.
"""
from __future__ import annotations

import struct
from os import PathLike
from typing import BinaryIO, Iterator, TextIO

from ..src.book import BookEvent  # noqa: F401  (tipo del contrato, documentación)

RECORD = struct.Struct("<QQIIIIHBBI")
RECORD_SIZE = RECORD.size
TEXT_HEADER = "# msg_idx,ts_ns,bid_px,bid_qty,ask_px,ask_qty,locate,msg_type,changed"

#: tupla de registro decodificado: (msg_idx, ts_ns, bid_px, bid_qty, ask_px,
#: ask_qty, locate, msg_type, changed)
Record = tuple[int, int, int, int, int, int, int, str, int]


def write_record(
    out: BinaryIO,
    msg_idx: int,
    ts_ns: int,
    bbo: tuple[int, int, int, int],
    locate: int,
    mtype: str,
    changed: int,
) -> None:
    """Escribe un registro binario de 40 B (layout del Anexo A)."""
    bid_px, bid_qty, ask_px, ask_qty = bbo
    out.write(
        RECORD.pack(
            msg_idx, ts_ns, bid_px, bid_qty, ask_px, ask_qty,
            locate, ord(mtype), 1 if changed else 0, 0,
        )
    )


def iter_records(source: str | PathLike[str] | BinaryIO) -> Iterator[Record]:
    """Lee un fichero de vectores registro a registro (round-trip del writer)."""
    f = open(source, "rb") if not hasattr(source, "read") else source
    try:
        while True:
            blob = f.read(RECORD_SIZE)
            if not blob:
                return
            if len(blob) != RECORD_SIZE:
                raise ValueError(
                    f"registro truncado: {len(blob)} B de {RECORD_SIZE}"
                )
            idx, ts, bid_px, bid_qty, ask_px, ask_qty, locate, mtype, flags, _ = (
                RECORD.unpack(blob)
            )
            yield idx, ts, bid_px, bid_qty, ask_px, ask_qty, locate, chr(mtype), flags & 1
    finally:
        if f is not source:
            f.close()


def dump_text(source: str | PathLike[str] | BinaryIO, out: TextIO) -> None:
    """Vuelca un fichero binario de vectores a texto (un registro por línea)."""
    out.write(TEXT_HEADER + "\n")
    for rec in iter_records(source):
        out.write(
            f"{rec[0]},{rec[1]},{rec[2]},{rec[3]},{rec[4]},{rec[5]}"
            f",{rec[6]},{rec[7]},{rec[8]}\n"
        )


class VectorSink:
    """Política de emisión: un registro por mensaje modificador del subset."""

    def __init__(self, out: BinaryIO, subset: set[int]) -> None:
        self._out = out
        self._subset = subset
        self.records = 0

    def handle(
        self,
        msg: tuple[int, str, int, int, int, tuple | None],
        event: BookEvent | None,
    ) -> None:
        if event is None:
            return
        locate, bbo, changed = event
        if locate not in self._subset:
            return
        write_record(self._out, msg[0], msg[4], bbo, locate, msg[1], changed)
        self.records += 1
