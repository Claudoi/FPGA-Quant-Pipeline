"""Estadísticas del día: conteo por tipo y dimensionado por símbolo.

La salida alimenta dos cosas (spec fase0, criterio 9): la selección del
subset de símbolos para los vectores y la tabla de dimensionado de memoria
del RTL (pico de órdenes vivas / niveles por símbolo → URAM).
"""
from __future__ import annotations

import csv
from collections import Counter
from os import PathLike
from typing import TextIO

from ..itch.messages import BOOK_MODIFYING_TYPES


class SymbolStats:
    __slots__ = ("locate", "symbol", "messages", "peak_orders", "peak_levels")

    def __init__(self, locate: int) -> None:
        self.locate = locate
        self.symbol = ""
        self.messages = 0
        self.peak_orders = 0
        self.peak_levels = 0


class StatsCollector:
    """Acumula conteo por tipo y stats por símbolo mensaje a mensaje."""

    def __init__(self) -> None:
        self.by_type: Counter[str] = Counter()
        self.symbols: dict[int, SymbolStats] = {}

    def observe(self, msg: tuple[int, str, int, int, int, tuple | None], book) -> None:
        """Llamar DESPUÉS de book.apply(msg) para muestrear los picos."""
        _idx, mtype, locate, _tracking, _ts, fields = msg
        self.by_type[mtype] += 1
        if locate == 0:
            return
        st = self.symbols.get(locate)
        if st is None:
            st = self.symbols[locate] = SymbolStats(locate)
        st.messages += 1
        if mtype == "R":
            st.symbol = fields[0]  # type: ignore[index]
        elif mtype in BOOK_MODIFYING_TYPES:
            live = book.live_per_locate.get(locate, 0)
            if live > st.peak_orders:
                st.peak_orders = live
            levels = book.level_count(locate)
            if levels > st.peak_levels:
                st.peak_levels = levels

    def write_csv(self, dest: str | PathLike[str] | TextIO) -> None:
        close = False
        if hasattr(dest, "write"):
            f = dest
        else:
            f = open(dest, "w", newline="")
            close = True
        try:
            w = csv.writer(f)
            w.writerow(["locate", "symbol", "messages", "peak_orders", "peak_levels"])
            for locate in sorted(self.symbols):
                st = self.symbols[locate]
                w.writerow([st.locate, st.symbol, st.messages, st.peak_orders, st.peak_levels])
        finally:
            if close:
                f.close()
