"""Trade ledger -- paper/replay only. No real-money capability."""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from datetime import date

_TRADE_FIELDS = {"date","symbol","side","shares","price","gross","cost","net","reason"}
_SIDES = {"buy","sell"}

@dataclass
class Trade:
    date: str; symbol: str; side: str  # buy | sell
    shares: float; price: float; gross: float; cost: float; net: float
    reason: str = ""
    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        # Forward-tolerant (H7): unknown fields from a newer version are
        # ignored instead of crashing the loader; known fields are validated.
        if not isinstance(d, dict):
            raise ValueError(f"trade entry must be an object, got {type(d).__name__}")
        missing = _TRADE_FIELDS - {"reason"} - set(d)
        if missing:
            raise ValueError(f"trade entry missing fields: {sorted(missing)}")
        kw = {k: d[k] for k in _TRADE_FIELDS if k in d}
        if kw["side"] not in _SIDES:
            raise ValueError(f"trade side must be one of {sorted(_SIDES)}, got {kw['side']!r}")
        # R2-M3: the date and symbol were unvalidated -- a garbage date or
        # an integer symbol loaded and poisoned reports downstream.
        if not isinstance(kw["symbol"], str) or not kw["symbol"]:
            raise ValueError(f"trade symbol must be a non-empty string, got {kw['symbol']!r}")
        if not isinstance(kw["date"], str):
            raise ValueError(f"trade date must be an ISO date string, got {kw['date']!r}")
        try:
            date.fromisoformat(kw["date"])
        except ValueError:
            raise ValueError(f"trade date is not a valid ISO date: {kw['date']!r}") from None
        if "reason" in kw and not isinstance(kw["reason"], str):
            raise ValueError(f"trade reason must be a string, got {kw['reason']!r}")
        for f in ("shares","price","gross","cost","net"):
            v = kw[f]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"trade {f} must be a finite number, got {v!r}")
        if kw["shares"] <= 0 or kw["price"] <= 0:
            raise ValueError("trade shares and price must be positive")
        if kw["gross"] < 0 or kw["cost"] < 0:
            raise ValueError("trade gross and cost must be >= 0")
        return cls(**kw)

class Ledger:
    def __init__(self, trades: list[Trade]|None=None):
        self.trades: list[Trade]=trades or []
    def add(self, t: Trade): self.trades.append(t)
    @property
    def total_costs(self) -> float: return round(sum(t.cost for t in self.trades),2)
    @property
    def trade_count(self) -> int: return len(self.trades)
    def to_list(self): return [t.to_dict() for t in self.trades]
    @classmethod
    def from_list(cls, rows):
        if rows is None: rows = []
        if not isinstance(rows, list):
            raise ValueError(f"ledger must be a list, got {type(rows).__name__}")
        return cls([Trade.from_dict(r) for r in rows])
