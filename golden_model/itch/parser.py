"""Iterador BinaryFILE -> mensajes ITCH 5.0 tipados.

BinaryFILE (formato de los ficheros de emi.nasdaq.com): secuencia de
`length u16be + payload`, donde el payload es exactamente un mensaje ITCH
(el mismo framing que lleva cada mensaje dentro de MoldUDP64).

Contrato (spec fase0, criterio 1): todos los tipos se validan por longitud;
tipo desconocido, longitud incorrecta o mensaje truncado = error duro.

Cada mensaje se entrega como tupla:

    (msg_idx, mtype, locate, tracking, ts_ns, fields)

- msg_idx: índice global en el fichero, 0-based.
- mtype: str de 1 carácter ('A', 'S', ...).
- locate/tracking/ts_ns: cabecera común (ts en ns desde medianoche).
- fields: tupla con los campos tras la cabecera para los tipos con layout
  completo (subset del libro + R/S/H, ver messages.LAYOUTS); None para el
  resto (validados y contabilizables por la cabecera).
"""
from __future__ import annotations

import gzip
import io
from os import PathLike
from typing import BinaryIO, Iterator

from .messages import LAYOUTS, MESSAGE_LENGTHS

_HEADER_LEN = 2


class ItchError(ValueError):
    """Base de los errores de protocolo ITCH/BinaryFILE."""


class UnknownTypeError(ItchError):
    """Tipo de mensaje no definido en ITCH 5.0."""


class BadLengthError(ItchError):
    """Longitud declarada distinta de la especificada para el tipo."""


class TruncatedMessageError(ItchError):
    """El fichero termina a mitad de un mensaje."""


def _open(source: str | PathLike[str] | BinaryIO) -> BinaryIO:
    if hasattr(source, "read"):
        return source  # type: ignore[return-value]
    path = str(source)
    if path.endswith(".gz"):
        return io.BufferedReader(gzip.open(path, "rb"), buffer_size=1 << 20)
    return open(path, "rb")


def iter_messages(
    source: str | PathLike[str] | BinaryIO,
) -> Iterator[tuple[int, str, int, int, int, tuple | None]]:
    """Itera un BinaryFILE entregando mensajes tipados (ver docstring del módulo)."""
    f = _open(source)
    lengths = MESSAGE_LENGTHS
    layouts = LAYOUTS
    idx = 0
    try:
        while True:
            prefix = f.read(_HEADER_LEN)
            if not prefix:
                return
            if len(prefix) < _HEADER_LEN:
                raise TruncatedMessageError(
                    f"mensaje {idx}: prefijo de longitud truncado"
                )
            declared = int.from_bytes(prefix, "big")
            payload = f.read(declared)
            if len(payload) < declared:
                raise TruncatedMessageError(
                    f"mensaje {idx}: declara {declared} B, quedan {len(payload)}"
                )
            mtype = chr(payload[0])
            entry = lengths.get(mtype)
            if entry is None:
                raise UnknownTypeError(
                    f"mensaje {idx}: tipo desconocido {mtype!r}"
                )
            expected = entry[1]
            if declared != expected:
                raise BadLengthError(
                    f"mensaje {idx}: tipo {mtype!r} declara {declared} B, "
                    f"la spec exige {expected} B"
                )
            layout = layouts.get(mtype)
            if layout is None:
                # validado por longitud; solo cabecera común
                locate = int.from_bytes(payload[1:3], "big")
                tracking = int.from_bytes(payload[3:5], "big")
                ts_ns = int.from_bytes(payload[5:11], "big")
                yield idx, mtype, locate, tracking, ts_ns, None
            else:
                values = layout.fmt.unpack(payload)
                fields = tuple(
                    v.decode("ascii").rstrip() if i in layout.alpha else v
                    for i, v in enumerate(values[4:], start=4)
                )
                ts_ns = int.from_bytes(values[3], "big")
                yield idx, mtype, values[1], values[2], ts_ns, fields
            idx += 1
    finally:
        f.close()
