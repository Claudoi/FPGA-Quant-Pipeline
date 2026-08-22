"""Day statistics: per-type counts and per-symbol sizing.

The output feeds two things (spec phase 0, criterion 9): the selection of the
symbol subset for the vectors and the RTL memory sizing table
(peak live orders / levels per symbol → URAM).
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
    """Accumulates per-type counts and per-symbol stats message by message."""

    def __init__(self) -> None:
        self.by_type: Counter[str] = Counter()
        self.symbols: dict[int, SymbolStats] = {}

    def observe(self, msg: tuple[int, str, int, int, int, tuple | None], book) -> None:
        """Call AFTER book.apply(msg) to sample the peaks."""
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