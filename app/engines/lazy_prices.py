"""Lazy Prices engine (ported) — Cohen, Malloy & Nguyen 2020.

Source of truth: ``backtests/v7/gap-a5-lazy-prices/lazy-prices.py`` —
quarterly top-5 by most-recent 10-K whole-document cosine similarity
vs the prior-year 10-K, equal weight, champion mechanics/costs, plain
-15% floor. That module is loaded and called verbatim.

Published record ($100 start, plain floor):
  continuous 2019-01-02 -> 2026-11-20 : $504.34
  validation 2023-01-03 -> 2026-11-20 : $324.12

Replay data (read-only): the original test's own cached signal file
``backtests/v7/gap-a5-lazy-prices/data/similarities.json`` (the output
of the original script's build_signals(), computed from its cached
EDGAR documents/vectors) and prices via the original module's
get_prices() (champion's shared caches).

Optional explicit inputs for ``run``:
  prices       = {ticker: [{"d":..., "o":..., "c":...}, ...]}
  fundamentals = {"signals": {ticker: [(accept_date, similarity, acc)]}}
"""
import json
import os

from . import common

_ORIG = None
_DATA = {}


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "lazy_prices_orig",
            os.path.join(common.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
    return _ORIG


def _load_data(prices, fundamentals):
    lazy = _orig()
    # R2-E2: one-of-the-pair supplied is an error, never a silent replay.
    common.require_injected_pair("lazy_prices engine", prices, fundamentals)
    if prices is not None and fundamentals is not None:
        if not prices:
            raise ValueError("lazy_prices engine: no price data supplied")
        # R2-E8: the universe check V+M always had — Lazy had none, so
        # prices for one unknown ticker silently returned $100.00.
        missing = [t for t in list(lazy.UNIVERSE) + ["SPY"] if not prices.get(t)]
        if missing:
            raise ValueError(f"lazy_prices engine: missing price data for "
                             f"{', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows, engine="lazy_prices engine")
        common.require_fundamentals("lazy_prices engine", fundamentals, "signals")
        common.assert_finite_tree("lazy_prices engine", fundamentals)
        return lazy.PriceBook(prices), fundamentals["signals"]
    if "pb" not in _DATA:
        sig_path = os.path.join(common.V7, "gap-a5-lazy-prices", "data",
                                "similarities.json")
        with open(sig_path) as f:
            cached = json.load(f)
        signals = {t: [tuple(x) for x in rows]
                   for t, rows in cached["signals"].items()}
        bars = {t: lazy.get_prices(t) for t in lazy.UNIVERSE + ["SPY"]}
        _DATA.update(pb=lazy.PriceBook(bars), signals=signals)
    return _DATA["pb"], _DATA["signals"]


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    lazy = _orig()
    start_cash = common.validate_start_cash("lazy_prices engine", start_cash)
    pb, signals = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end)
    floor = common.resolve_floor(start_cash, protection)
    r = lazy.run_pot(pb, signals, s, e, start_cash=float(start_cash),
                     floor0=floor, label=f"{wname} LAZY")
    if r is None:
        raise ValueError(f"lazy_prices engine: no trading days in window {s} to {e}")
    extra = None
    if prices is not None:
        warnings = common.coverage_warnings("lazy_prices engine", prices, e)
        if warnings:
            extra = {"warnings": warnings}
    return common.make_result(
        "lazy_prices", wname, s, e, start_cash, r["final"], r["costs"],
        common.trade_dicts(r["trades"]), r["halted"], r["curve"],
        halt_info=r.get("halt_info"), extra=extra)
