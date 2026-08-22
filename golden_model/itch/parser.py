"""BinaryFILE iterator -> typed ITCH 5.0 messages.

BinaryFILE (format of the emi.nasdaq.com files): sequence of
`length u16be + payload`, where the payload is exactly one ITCH message
(the same framing that carries each message inside MoldUDP64).

Contract (spec phase 0, criterion 1): all types are validated by length;
unknown type, wrong length, or truncated message = hard error.

Each message is delivered as a tuple:

    (msg_idx, mtype, locate, tracking, ts_ns, fields)

- msg_idx: global index in the file, 0-based.
- mtype: 1-character str ('A', 'S', ...).
- locate/tracking/ts_ns: common header (ts in ns since midnight).
- fields: tuple with the fields after the header for the types with a full
  layout (book subset + R/S/H, see messages.LAYOUTS); None for the
  rest (validated and countable via the header).
"""
from __future__ import annotations

import gzip
import io
from os import PathLike
from typing import BinaryIO, Iterator

from .messages import LAYOUTS, MESSAGE_LENGTHS

_HEADER_LEN = 2


class ItchError(ValueError):
    """Base class for ITCH/BinaryFILE protocol errors."""


class UnknownTypeError(ItchError):
    """Message type not defined in ITCH 5.0."""


class BadLengthError(ItchError):
    """Declared length differs from the one specified for the type."""


class TruncatedMessageError(ItchError):
    """The file ends in the middle of a message."""


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
    """Iterates a BinaryFILE yielding typed messages (see module docstring)."""
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
                    f"message {idx}: truncated length prefix"
                )
            declared = int.from_bytes(prefix, "big")
            payload = f.read(declared)
            if len(payload) < declared:
                raise TruncatedMessageError(
                    f"message {idx}: declares {declared} B, {len(payload)} left"
                )
            mtype = chr(payload[0])
            entry = lengths.get(mtype)
            if entry is None:
                raise UnknownTypeError(
                    f"message {idx}: unknown type {mtype!r}"
                )
            expected = entry[1]
            if declared != expected:
                raise BadLengthError(
                    f"message {idx}: type {mtype!r} declares {declared} B, "
                    f"the spec requires {expected} B"
                )
            layout = layouts.get(mtype)
            if layout is None:
                # validated by length; common header only
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