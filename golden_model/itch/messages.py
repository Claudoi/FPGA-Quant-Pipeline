"""Canonical layout table for Nasdaq TotalView-ITCH 5.0.

Transcribed from NQTVITCHSpecification.pdf (offsets and lengths verified
field by field against section 1.x of the document). Single source of
the protocol: no ITCH layout literal lives outside this file.

DLCR note: the April 2023 revision adds the "Direct Listing with
Capital Raise" message. Our extraction of the PDF shows the letter 'O' in its table,
colliding with Operational Halt (2018); the campaign data (2019)
predate DLCR, so it is omitted from the table on purpose: if it ever
shows up in a file, the parser fails as noise (unknown type), which is
the designed behavior.
"""
from __future__ import annotations

import struct
from typing import NamedTuple

#: type -> (name, total payload length in bytes, without the BinaryFILE prefix)
MESSAGE_LENGTHS: dict[str, tuple[str, int]] = {
    "S": ("System Event", 12),
    "R": ("Stock Directory", 39),
    "H": ("Stock Trading Action", 25),
    "Y": ("Reg SHO Restriction", 20),
    "L": ("Market Participant Position", 26),
    "V": ("MWCB Decline Level", 35),
    "W": ("MWCB Status", 12),
    "K": ("IPO Quoting Period Update", 28),
    "J": ("LULD Auction Collar", 35),
    "O": ("Operational Halt", 21),
    "A": ("Add Order", 36),
    "F": ("Add Order MPID", 40),
    "E": ("Order Executed", 31),
    "C": ("Order Executed With Price", 36),
    "X": ("Order Cancel", 23),
    "D": ("Order Delete", 19),
    "U": ("Order Replace", 35),
    "P": ("Trade (Non-Cross)", 44),
    "Q": ("Cross Trade", 40),
    "B": ("Broken Trade", 19),
    "I": ("NOII", 50),
    "N": ("RPII", 20),
}


class Layout(NamedTuple):
    """Decoder for a type: big-endian struct + field names + alpha indices.

    `fields` names the fields AFTER the common header (type, locate,
    tracking, ts). `alpha` are the indices within the full tuple of
    values whose bytes must be decoded to str (rstrip spaces).
    """

    fmt: struct.Struct
    fields: tuple[str, ...]
    alpha: frozenset[int]


#: Layouts with full fields: book subset (A/F/E/C/X/D/U) + R, S, H.
#: The rest of the types are validated by length and only the header is decoded.
LAYOUTS: dict[str, Layout] = {
    "A": Layout(
        struct.Struct(">cHH6sQcI8sI"),
        ("order_ref", "side", "shares", "stock", "price"),
        frozenset({5, 7}),
    ),
    "F": Layout(
        struct.Struct(">cHH6sQcI8sI4s"),
        ("order_ref", "side", "shares", "stock", "price", "attribution"),
        frozenset({5, 7, 9}),
    ),
    "E": Layout(
        struct.Struct(">cHH6sQIQ"),
        ("order_ref", "executed_shares", "match"),
        frozenset(),
    ),
    "C": Layout(
        struct.Struct(">cHH6sQIQcI"),
        ("order_ref", "executed_shares", "match", "printable", "exec_price"),
        frozenset({7}),
    ),
    "X": Layout(
        struct.Struct(">cHH6sQI"),
        ("order_ref", "cancelled_shares"),
        frozenset(),
    ),
    "D": Layout(
        struct.Struct(">cHH6sQ"),
        ("order_ref",),
        frozenset(),
    ),
    "U": Layout(
        struct.Struct(">cHH6sQQII"),
        ("orig_ref", "new_ref", "shares", "price"),
        frozenset(),
    ),
    "R": Layout(
        struct.Struct(">cHH6s8sccIcc2scccccIc"),
        (
            "stock", "market_category", "financial_status", "round_lot_size",
            "round_lots_only", "issue_classification", "issue_subtype",
            "authenticity", "short_sale_threshold", "ipo_flag",
            "luld_ref_price_tier", "etp_flag", "etp_leverage_factor",
            "inverse_indicator",
        ),
        frozenset({4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 17}),
    ),
    "S": Layout(
        struct.Struct(">cHH6sc"),
        ("event_code",),
        frozenset({4}),
    ),
    "H": Layout(
        struct.Struct(">cHH6s8scc4s"),
        ("stock", "trading_state", "reserved", "reason"),
        frozenset({4, 5, 6, 7}),
    ),
}

#: Types that modify the book (the run emits a vector record).
BOOK_MODIFYING_TYPES = frozenset("AFECXDU")