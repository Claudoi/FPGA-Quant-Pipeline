"""Multi-symbol order book of the golden model (reference semantics for the RTL).

Deliberately simple structures (auditable correctness beats
cleverness):

- `orders`: flat dict order_ref -> (locate, side, price, qty). The order
  reference number is unique per day across the whole market (ITCH spec), so
  a single dict serves all symbols.
- `_levels`: dict (locate, side) -> {price: aggregated qty}.
- `_best`: cache of the best price per (locate, side); only recomputed
  when the best level empties.

Semantics (spec phase 0, contract consumed by the RTL in phases 1-2):

- `U` (replace) is ATOMIC: delete + add produce a single resulting state.
- Empty BBO side = price 0, qty 0.
- Operation on an unknown ref: counted anomaly, skipped, does not abort
  (happens in partial windows of the day).
- `C` reduces like `E` (the exec_price does not change the order's price).

Invariants (criterion 3, iteration 2 correction): duplicate refs,
non-positive quantities and inconsistent levels always abort. A locked/crossed
book in continuous trading (S at 'Q' and H at 'T') exists in real data
(halt->trading transitions; evidence: main day, msg 39778763,
symbol ZJZZT): by default it is COUNTED in `cross_events` and the run reports it;
with `strict_cross=True` it aborts (mode exercised by the synthetic tests).
`check_deep()` revalidates levels against orders (periodic + at close).
"""
from __future__ import annotations

BID = "B"
ASK = "S"

#: System Event states that delimit continuous trading
_MARKET_OPEN = "Q"   # start of market hours
_MARKET_CLOSE = "M"  # end of market hours
_CONTINUOUS = "T"    # trading state: resumption/continuous trading


class InvariantError(RuntimeError):
    """Book invariant violated: the run must abort."""


#: event emitted by apply(): (locate, (bid_px, bid_qty, ask_px, ask_qty), changed)
BookEvent = tuple[int, tuple[int, int, int, int], int]


class Book:
    """Book of the whole market; emits BBO per modifying message."""

    def __init__(self, strict_cross: bool = False) -> None:
        self.strict_cross = strict_cross
        self.cross_events = 0
        self.orders: dict[int, tuple[int, str, int, int]] = {}
        self._levels: dict[tuple[int, str], dict[int, int]] = {}
        self._best: dict[tuple[int, str], int | None] = {}
        self._last_bbo: dict[int, tuple[int, int, int, int]] = {}
        self._trading_state: dict[int, str] = {}
        self._market_hours = False
        self.anomalies = 0
        self.live_per_locate: dict[int, int] = {}

    # -- internal pieces ----------------------------------------------------

    def _level_add(self, locate: int, side: str, price: int, delta: int) -> None:
        key = (locate, side)
        levels = self._levels.setdefault(key, {})
        new_qty = levels.get(price, 0) + delta
        if new_qty < 0:
            raise InvariantError(f"negative level at {key}@{price}: {new_qty}")
        if new_qty == 0:
            del levels[price]
        else:
            levels[price] = new_qty
        best = self._best.get(key)
        if side == BID:
            if best is None or price > best:
                self._best[key] = price
            elif price == best and new_qty == 0:
                self._best[key] = max(levels) if levels else None
        else:
            if best is None or price < best:
                self._best[key] = price
            elif price == best and new_qty == 0:
                self._best[key] = min(levels) if levels else None

    def _bbo(self, locate: int) -> tuple[int, int, int, int]:
        bid_best = self._best.get((locate, BID))
        ask_best = self._best.get((locate, ASK))
        bid_qty = self._levels[(locate, BID)][bid_best] if bid_best is not None else 0
        ask_qty = self._levels[(locate, ASK)][ask_best] if ask_best is not None else 0
        return (bid_best or 0, bid_qty, ask_best or 0, ask_qty)

    def _emit(self, locate: int, msg_idx: int) -> BookEvent:
        bbo = self._bbo(locate)
        bid_px, _, ask_px, _ = bbo
        if (
            self._market_hours
            and self._trading_state.get(locate) == _CONTINUOUS
            and bid_px != 0
            and ask_px != 0
            and bid_px >= ask_px
        ):
            if self.strict_cross:
                raise InvariantError(
                    f"message {msg_idx}: crossed book in continuous trading "
                    f"(locate {locate}: bid {bid_px} >= ask {ask_px})"
                )
            self.cross_events += 1
        prev = self._last_bbo.get(locate)
        changed = 1 if prev != bbo else 0
        self._last_bbo[locate] = bbo
        return (locate, bbo, changed)

    def _add(self, msg_idx: int, locate: int, ref: int, side: str, shares: int, price: int) -> None:
        if ref in self.orders:
            raise InvariantError(f"message {msg_idx}: duplicate order_ref {ref}")
        if shares <= 0:
            raise InvariantError(f"message {msg_idx}: add with qty {shares}")
        self.orders[ref] = (locate, side, price, shares)
        self.live_per_locate[locate] = self.live_per_locate.get(locate, 0) + 1
        self._level_add(locate, side, price, shares)

    def _remove(self, ref: int) -> None:
        locate, side, price, qty = self.orders.pop(ref)
        self.live_per_locate[locate] -= 1
        self._level_add(locate, side, price, -qty)

    def _reduce(self, msg_idx: int, ref: int, shares: int, kind: str) -> int | None:
        """Reduces the qty of an order; returns its locate or None if it is an anomaly."""
        order = self.orders.get(ref)
        if order is None:
            self.anomalies += 1
            return None
        locate, side, price, qty = order
        rest = qty - shares
        if rest < 0:
            raise InvariantError(
                f"message {msg_idx}: {kind} of {shares} on an order with {qty} live"
            )
        if rest == 0:
            self._remove(ref)
        else:
            self.orders[ref] = (locate, side, price, rest)
            self._level_add(locate, side, price, -shares)
        return locate

    # -- API -----------------------------------------------------------------

    def apply(self, msg: tuple[int, str, int, int, int, tuple | None]) -> BookEvent | None:
        """Applies a parser message; emits a BBO event if it modifies the book."""
        msg_idx, mtype, locate, _tracking, _ts, fields = msg
        if mtype == "S":
            code = fields[0]  # type: ignore[index]
            if code == _MARKET_OPEN:
                self._market_hours = True
            elif code == _MARKET_CLOSE:
                self._market_hours = False
            return None
        if mtype == "H":
            self._trading_state[locate] = fields[1]  # type: ignore[index]
            return None
        if mtype == "A" or mtype == "F":
            ref, side, shares, _stock, price = fields[:5]  # type: ignore[index]
            self._add(msg_idx, locate, ref, side, shares, price)
            return self._emit(locate, msg_idx)
        if mtype == "E" or mtype == "C":
            loc = self._reduce(msg_idx, fields[0], fields[1], "execute")  # type: ignore[index]
            return self._emit(loc, msg_idx) if loc is not None else None
        if mtype == "X":
            loc = self._reduce(msg_idx, fields[0], fields[1], "cancel")  # type: ignore[index]
            return self._emit(loc, msg_idx) if loc is not None else None
        if mtype == "D":
            if fields[0] not in self.orders:  # type: ignore[index]
                self.anomalies += 1
                return None
            loc = locate
            self._remove(fields[0])  # type: ignore[index]
            return self._emit(loc, msg_idx)
        if mtype == "U":
            orig_ref, new_ref, shares, price = fields  # type: ignore[misc]
            orig = self.orders.get(orig_ref)
            if orig is None:
                self.anomalies += 1
                return None
            if shares <= 0:
                raise InvariantError(f"message {msg_idx}: replace with qty {shares}")
            if new_ref in self.orders:
                raise InvariantError(f"message {msg_idx}: duplicate order_ref {new_ref}")
            loc, side, _p, _q = orig
            # atomic delete + add: one single resulting state
            self._remove(orig_ref)
            self.orders[new_ref] = (loc, side, price, shares)
            self.live_per_locate[loc] += 1
            self._level_add(loc, side, price, shares)
            return self._emit(loc, msg_idx)
        return None  # remaining types: they do not touch the book

    def level_count(self, locate: int) -> int:
        """Number of live price levels of the symbol (bid + ask)."""
        return len(self._levels.get((locate, BID), ())) + len(
            self._levels.get((locate, ASK), ())
        )

    def check_deep(self) -> None:
        """Revalidates levels against orders (the run calls it periodically)."""
        esperados: dict[tuple[int, str], dict[int, int]] = {}
        for ref, (locate, side, price, qty) in self.orders.items():
            if qty <= 0:
                raise InvariantError(f"order {ref} with qty {qty}")
            esperados.setdefault((locate, side), {})[price] = (
                esperados.setdefault((locate, side), {}).get(price, 0) + qty
            )
        for key, levels in self._levels.items():
            for price, qty in levels.items():
                if qty <= 0:
                    raise InvariantError(f"empty level {key}@{price}")
        if esperados != {k: v for k, v in self._levels.items() if v}:
            raise InvariantError("levels inconsistent with the live orders")