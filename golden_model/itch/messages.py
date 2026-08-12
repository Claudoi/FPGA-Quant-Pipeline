"""Tabla canónica de layouts Nasdaq TotalView-ITCH 5.0.

Transcrita de NQTVITCHSpecification.pdf (offsets y longitudes verificados
campo a campo contra la sección 1.x del documento). Fuente única del
protocolo: ningún literal de layout ITCH fuera de este fichero.

Nota DLCR: la revisión de abril 2023 añade el mensaje «Direct Listing with
Capital Raise». Nuestra extracción del PDF muestra la letra 'O' en su tabla,
en colisión con Operational Halt (2018); los datos de la campaña (2019) son
anteriores a DLCR, así que se omite de la tabla a propósito: si algún día
aparece en un fichero, el parser falla en ruido (tipo desconocido), que es
el comportamiento diseñado.
"""
from __future__ import annotations

import struct
from typing import NamedTuple

#: tipo -> (nombre, longitud total del payload en bytes, sin el prefijo BinaryFILE)
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
    """Decoder de un tipo: struct big-endian + nombres de campo + índices alpha.

    `fields` nombra los campos DESPUÉS de la cabecera común (tipo, locate,
    tracking, ts). `alpha` son los índices dentro de la tupla completa de
    valores cuyo bytes hay que decodificar a str (rstrip de espacios).
    """

    fmt: struct.Struct
    fields: tuple[str, ...]
    alpha: frozenset[int]


#: Layouts con campos completos: subset del libro (A/F/E/C/X/D/U) + R, S, H.
#: El resto de tipos se valida por longitud y se decodifica solo la cabecera.
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

#: Tipos que modifican el libro (emite registro de vector el run).
BOOK_MODIFYING_TYPES = frozenset("AFECXDU")
