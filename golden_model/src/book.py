"""Order book multi-símbolo del golden model (semántica de referencia del RTL).

Estructuras deliberadamente simples (la corrección auditable prima sobre la
cleverness):

- `orders`: dict plano order_ref -> (locate, side, price, qty). El order
  reference number es único por día en todo el mercado (spec ITCH), así que
  un solo dict sirve para todos los símbolos.
- `_levels`: dict (locate, side) -> {price: qty agregada}.
- `_best`: cache del mejor precio por (locate, side); se recalcula solo
  cuando el mejor nivel se vacía.

Semántica (spec fase0, contrato consumido por el RTL en fases 1-2):

- `U` (replace) es ATÓMICO: delete + add producen un solo estado resultante.
- Lado vacío del BBO = precio 0, qty 0.
- Operación sobre ref desconocida: anomalía contada, se salta, no aborta
  (pasa en ventanas parciales del día).
- `C` reduce como `E` (el exec_price no cambia el precio de la orden).

Invariantes (criterio 3, corrección de iteración 2): refs duplicadas,
cantidades no positivas y niveles inconsistentes abortan siempre. El libro
bloqueado/cruzado en trading continuo (S en 'Q' y H en 'T') existe en datos
reales (transiciones halt->trading; evidencia: día principal, msg 39778763,
símbolo ZJZZT): por defecto se CUENTA en `cross_events` y el run lo reporta;
con `strict_cross=True` aborta (modo que ejercitan los tests sintéticos).
`check_deep()` revalida niveles contra órdenes (periódico + cierre).
"""
from __future__ import annotations

BID = "B"
ASK = "S"

#: estados de System Event que delimitan el trading continuo
_MARKET_OPEN = "Q"   # start of market hours
_MARKET_CLOSE = "M"  # end of market hours
_CONTINUOUS = "T"    # trading state: resumption/continuous trading


class InvariantError(RuntimeError):
    """Invariante del libro violada: el run debe abortar."""


#: evento emitido por apply(): (locate, (bid_px, bid_qty, ask_px, ask_qty), changed)
BookEvent = tuple[int, tuple[int, int, int, int], int]


class Book:
    """Libro de todo el mercado; emite BBO por mensaje modificador."""

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

    # -- piezas internas ----------------------------------------------------

    def _level_add(self, locate: int, side: str, price: int, delta: int) -> None:
        key = (locate, side)
        levels = self._levels.setdefault(key, {})
        new_qty = levels.get(price, 0) + delta
        if new_qty < 0:
            raise InvariantError(f"nivel negativo en {key}@{price}: {new_qty}")
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
                    f"mensaje {msg_idx}: libro cruzado en trading continuo "
                    f"(locate {locate}: bid {bid_px} >= ask {ask_px})"
                )
            self.cross_events += 1
        prev = self._last_bbo.get(locate)
        changed = 1 if prev != bbo else 0
        self._last_bbo[locate] = bbo
        return (locate, bbo, changed)

    def _add(self, msg_idx: int, locate: int, ref: int, side: str, shares: int, price: int) -> None:
        if ref in self.orders:
            raise InvariantError(f"mensaje {msg_idx}: order_ref duplicada {ref}")
        if shares <= 0:
            raise InvariantError(f"mensaje {msg_idx}: add con qty {shares}")
        self.orders[ref] = (locate, side, price, shares)
        self.live_per_locate[locate] = self.live_per_locate.get(locate, 0) + 1
        self._level_add(locate, side, price, shares)

    def _remove(self, ref: int) -> None:
        locate, side, price, qty = self.orders.pop(ref)
        self.live_per_locate[locate] -= 1
        self._level_add(locate, side, price, -qty)

    def _reduce(self, msg_idx: int, ref: int, shares: int, kind: str) -> int | None:
        """Reduce qty de una orden; devuelve su locate o None si es anomalía."""
        order = self.orders.get(ref)
        if order is None:
            self.anomalies += 1
            return None
        locate, side, price, qty = order
        rest = qty - shares
        if rest < 0:
            raise InvariantError(
                f"mensaje {msg_idx}: {kind} de {shares} sobre orden con {qty} vivas"
            )
        if rest == 0:
            self._remove(ref)
        else:
            self.orders[ref] = (locate, side, price, rest)
            self._level_add(locate, side, price, -shares)
        return locate

    # -- API -----------------------------------------------------------------

    def apply(self, msg: tuple[int, str, int, int, int, tuple | None]) -> BookEvent | None:
        """Aplica un mensaje del parser; emite evento BBO si modifica el libro."""
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
                raise InvariantError(f"mensaje {msg_idx}: replace con qty {shares}")
            if new_ref in self.orders:
                raise InvariantError(f"mensaje {msg_idx}: order_ref duplicada {new_ref}")
            loc, side, _p, _q = orig
            # delete + add atomicos: un solo estado resultante
            self._remove(orig_ref)
            self.orders[new_ref] = (loc, side, price, shares)
            self.live_per_locate[loc] += 1
            self._level_add(loc, side, price, shares)
            return self._emit(loc, msg_idx)
        return None  # resto de tipos: no tocan el libro

    def level_count(self, locate: int) -> int:
        """Número de niveles de precio vivos del símbolo (bid + ask)."""
        return len(self._levels.get((locate, BID), ())) + len(
            self._levels.get((locate, ASK), ())
        )

    def check_deep(self) -> None:
        """Revalida niveles contra órdenes (el run lo llama periódicamente)."""
        esperados: dict[tuple[int, str], dict[int, int]] = {}
        for ref, (locate, side, price, qty) in self.orders.items():
            if qty <= 0:
                raise InvariantError(f"orden {ref} con qty {qty}")
            esperados.setdefault((locate, side), {})[price] = (
                esperados.setdefault((locate, side), {}).get(price, 0) + qty
            )
        for key, levels in self._levels.items():
            for price, qty in levels.items():
                if qty <= 0:
                    raise InvariantError(f"nivel vacío {key}@{price}")
        if esperados != {k: v for k, v in self._levels.items() if v}:
            raise InvariantError("niveles inconsistentes con las órdenes vivas")
