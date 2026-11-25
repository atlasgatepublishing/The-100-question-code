"""Shared helpers for the ported strategy engines.

Common interface (every engine module in this package):

    run(prices=None, fundamentals=None, start_cash=100.0,
        protection=None, window="continuous") -> dict

- ``prices`` / ``fundamentals``: optional pre-loaded data in the shape
  each engine documents. In replay mode both are ``None`` and the
  engine loads the ORIGINAL backtest's cached data, read-only, from
  ``~/workspace/stock-app/backtests/`` — the exact bytes the published
  records were produced from.
- ``protection``: ``None`` means the published integrity basis — a
  plain -15% floor from the starting balance (floor = 0.85 *
  start_cash); a close at/below the floor liquidates at the next open
  and ends the run. A dict may override with ``{"floor": <dollars>}``.
- ``window``: "continuous" or "validation" (each engine also accepts
  explicit ``start=`` / ``end=`` overrides).

Result dict (every engine):

    {
      "engine": str, "window": str, "start": str, "end": str,
      "start_cash": float,
      "final": float,                # final balance, dollars
      "final_balance": float,        # alias of "final"
      "costs": float,                # total trading costs, dollars
      "equity_curve": [[date, value], ...],   # daily close equity
      "curve_dates": [date, ...], "curve_values": [value, ...],
      "trades": [ {date, ticker, side, shares, price, value, cost}, ...],
      "orders": int,                 # == len(trades) unless noted
      "halted": date-or-None,        # floor-halt signal date, if any
      "halts": [ {date, ...}, ...],  # halt events (0 or 1 on this basis)
    }

No strategy logic lives here — only data plumbing and result shaping.
The strategy logic lives in the original backtest scripts, which the
engine modules load and call verbatim (see each module's docstring).
Nothing in this package retunes, re-parameters, or "improves" anything.
Simulation / replay only. No broker, no orders, no real money.
"""
import importlib.util
import math
import os

BACKTESTS = os.path.expanduser("~/workspace/stock-app/backtests")
V4 = os.path.join(BACKTESTS, "v4")
V7 = os.path.join(BACKTESTS, "v7")
V8 = os.path.join(BACKTESTS, "v8")

# Published windows (identical across the quarterly engines).
CONTINUOUS = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")
WINDOWS = {"continuous": CONTINUOUS, "full": CONTINUOUS,
           "validation": VALIDATION}


def load_module(name, path):
    """Load an original backtest script as a module (read-only)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_window(window, start=None, end=None, windows=None):
    windows = windows or WINDOWS
    if start is not None and end is not None:
        s, e, wname = start, end, window or "custom"
    else:
        if window not in windows:
            raise ValueError(f"unknown window {window!r}; use one of "
                             f"{sorted(windows)} or pass start=/end=")
        ws, we = windows[window]
        s, e, wname = (start or ws), (end or we), window
    # R2-E5: a reversed window is a caller error, named here — not a
    # cryptic crash from an original engine finding no days.
    if str(s) > str(e):
        raise ValueError(f"window start {s} is after window end {e}")
    return s, e, wname


def validate_start_cash(engine, start_cash):
    """R2-E6/E10: the starting pot must be a positive finite number —
    named as a pot-size problem, never blamed on the data."""
    if isinstance(start_cash, bool) or not isinstance(start_cash, (int, float)) \
            or not math.isfinite(float(start_cash)) or float(start_cash) <= 0:
        raise ValueError(f"{engine}: start_cash must be a positive finite "
                         f"number, got {start_cash!r}")
    return float(start_cash)


def resolve_floor(start_cash, protection):
    """Plain -15% floor from the starting balance, unless overridden.

    R2-E3: the floor is the user's one safety feature, so an override
    is validated hard — it must be finite and within [0, start_cash]
    (a fraction within [0, 1]). A NaN floor used to slip through every
    comparison and silently disable the -15% protection entirely; a
    negative floor and a floor above the starting balance are config
    errors, not strategies."""
    start_cash = float(start_cash)
    if protection is None:
        return 0.85 * start_cash

    def _num(v, what):
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise ValueError(f"protection {what} must be a finite number, "
                             f"got {v!r} — refusing to run with an "
                             f"unverifiable loss floor")
        return float(v)

    if isinstance(protection, (int, float)) and not isinstance(protection, bool):
        floor = _num(protection, "floor")
    elif isinstance(protection, dict):
        if "floor" in protection:
            floor = _num(protection["floor"], "floor")
        elif "floor_fraction" in protection:
            frac = _num(protection["floor_fraction"], "floor_fraction")
            if not 0.0 <= frac <= 1.0:
                raise ValueError(f"protection floor_fraction must be within "
                                 f"[0, 1], got {frac}")
            floor = frac * start_cash
        elif "max_loss_pct" in protection:
            pct = _num(protection["max_loss_pct"], "max_loss_pct")
            if not 0.0 <= pct <= 1.0:
                raise ValueError(f"protection max_loss_pct must be within "
                                 f"[0, 1], got {pct}")
            floor = (1.0 - pct) * start_cash
        else:
            raise ValueError(f"unrecognized protection spec: {protection!r}")
    else:
        raise ValueError(f"unrecognized protection spec: {protection!r}")
    if floor < 0 or floor > start_cash:
        raise ValueError(f"protection floor ${floor:,.2f} is outside "
                         f"[0, start_cash ${start_cash:,.2f}] — refusing to "
                         f"run with a meaningless loss floor")
    return floor


def trade_dicts(raw_trades, with_sleeve=False):
    """Normalize an original engine's trade tuples to dicts.

    Quarterly engines emit (date, ticker, side, shares, price, value,
    cost); the switch/combo machinery emits (date, sleeve, side,
    shares, price, value, cost).
    """
    out = []
    for tr in raw_trades or []:
        if with_sleeve:
            d, sleeve, side, sh, px, val, cost = tr
            out.append({"date": d, "sleeve": sleeve, "ticker": None,
                        "side": side, "shares": sh, "price": px,
                        "value": val, "cost": cost})
        else:
            d, t, side, sh, px, val, cost = tr
            out.append({"date": d, "ticker": t, "side": side,
                        "shares": sh, "price": px, "value": val,
                        "cost": cost})
    return out


def validate_price_series(symbol, rows, engine="engine"):
    """Validate caller-injected price rows (QA H-1 / M-13, hardened R2-E4).

    Every row must be a dict carrying a REAL ISO calendar date under
    'd' and positive, finite 'o' and 'c' values — present, not None.
    Raises a ValueError naming the engine, symbol and offending date —
    bad input is rejected here instead of surfacing downstream as a
    bare TypeError/KeyError inside an original engine, or as a NaN or
    negative final balance. Returns the rows unchanged on success.
    """
    if rows is None or len(rows) == 0:
        raise ValueError(f"{engine}: no price data for {symbol}")
    seen = set()
    prev_d = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{engine}: price row for {symbol} is not an "
                             f"object: {row!r}")
        d = row.get("d")
        if not isinstance(d, str) or not d:
            raise ValueError(f"{engine}: price row for {symbol} has no 'd' "
                             f"date: {row!r}")
        try:
            from datetime import date as _date
            _date.fromisoformat(d)
        except ValueError:
            raise ValueError(f"{engine}: price date {d!r} for {symbol} is "
                             f"not a real calendar date") from None
        if d in seen:
            raise ValueError(f"{engine}: duplicate price date {d} for {symbol}")
        seen.add(d)
        # QA M-3: engines assert sorted, unique dates (the loaders sort
        # and de-dupe; injected series must arrive sorted too).
        if prev_d is not None and d < prev_d:
            raise ValueError(f"{engine}: price dates for {symbol} are not sorted "
                             f"({prev_d} followed by {d})")
        prev_d = d
        for key in ("o", "c"):
            if key not in row or row[key] is None:
                raise ValueError(f"{engine}: price row for {symbol} on {d} "
                                 f"is missing '{key}'")
            v = row[key]
            if not isinstance(v, (int, float)) or isinstance(v, bool) \
                    or not math.isfinite(float(v)) or float(v) <= 0:
                raise ValueError(
                    f"{engine}: invalid {key} price for {symbol} on {d}: {v!r} "
                    "(prices must be positive and finite)")
    return rows


def require_injected_pair(engine, prices, fundamentals):
    """R2-E2: supplying exactly one of prices/fundamentals is an error,
    never a silent replay — a caller who passed their own prices and
    forgot fundamentals used to get the published backtest numbers
    back, labelled as their run."""
    if (prices is None) != (fundamentals is None):
        missing = "fundamentals" if prices is not None else "prices"
        raise ValueError(f"{engine}: {missing} not supplied — pass BOTH "
                         f"prices and fundamentals to run on your own "
                         f"data, or neither to run the replay record")
    if prices is not None and not isinstance(prices, dict):
        raise ValueError(f"{engine}: prices must be a dict of "
                         f"ticker -> rows, got {type(prices).__name__}")
    if fundamentals is not None and not isinstance(fundamentals, dict):
        raise ValueError(f"{engine}: fundamentals must be a dict, got "
                         f"{type(fundamentals).__name__}")


def require_fundamentals(engine, fundamentals, *keys):
    """R2-E13: a wrong-shape fundamentals dict fails HERE with the
    expected shape named — not as a bare KeyError from original code."""
    for k in keys:
        if k not in fundamentals:
            raise ValueError(f"{engine}: fundamentals is missing {k!r} — "
                             f"expected a dict with keys {list(keys)}")
        if not fundamentals[k]:
            raise ValueError(f"{engine}: fundamentals[{k!r}] is empty")


def assert_finite_tree(engine, obj, path="fundamentals"):
    """R2-E1: fundamentals get the same finite-value discipline as
    prices. Any NaN/infinite number anywhere in the injected
    fundamentals structure is rejected with its location named — an
    all-NaN fundamentals file used to produce a plausible $259.75
    'result' computed entirely from garbage."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"{engine}: non-finite value in {path}: {obj!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_finite_tree(engine, v, f"{path}[{k!r}]")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_finite_tree(engine, v, f"{path}[{i}]")


def coverage_warnings(engine, prices, end):
    """R2-E8: an injected series that ends long before the window does
    silently changes the answer (a truncated SPY/universe series moved
    V+M by $12 with no note). Surface it as a warning on the result."""
    out = []
    for t, rows in sorted((prices or {}).items()):
        if rows:
            last = rows[-1].get("d") if isinstance(rows[-1], dict) else None
            if last and str(last) < str(end):
                out.append(f"{engine}: price series for {t} ends {last}, "
                           f"before the window end {end} — result covers "
                           f"a truncated history")
    return out


def make_result(engine, window, start, end, start_cash, final, costs,
                trades, halted, curve, halt_info=None, extra=None):
    # QA H-1: an engine must never *return* a NaN, infinite or negative
    # final balance (or non-finite costs) — that is garbage produced from
    # bad input data, so fail loudly here instead of reporting it.
    final_f, costs_f = float(final), float(costs)
    if not math.isfinite(final_f) or final_f < 0:
        raise ValueError(f"{engine}: refusing to report invalid final balance "
                         f"{final!r} (non-finite or negative — check the "
                         f"input data and the start_cash of {start_cash!r})")
    if not math.isfinite(costs_f) or costs_f < 0:
        # R2-E9: negative costs were happily reported as fact.
        raise ValueError(f"{engine}: refusing to report invalid costs "
                         f"{costs!r} (non-finite or negative)")
    curve = [[d, float(v)] for d, v in (curve or [])]
    for d, v in curve:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"{engine}: invalid equity value on {d}: {v!r} "
                             f"(non-finite or negative)")
    halts = []
    if halted:
        h = {"date": halted}
        if halt_info:
            h.update(halt_info)
        halts.append(h)
    res = {
        "engine": engine,
        "window": window,
        "start": start,
        "end": end,
        "start_cash": float(start_cash),
        "final": float(final),
        "final_balance": float(final),
        "costs": float(costs),
        "equity_curve": curve,
        "curve_dates": [d for d, _ in curve],
        "curve_values": [v for _, v in curve],
        "trades": trades,
        "orders": len(trades),
        "halted": halted,
        "halts": halts,
    }
    if extra:
        res.update(extra)
    return res
