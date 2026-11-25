"""N-F3 "Paying in Stock" engine (ported).

Source of truth: ``backtests/v8/novel-f3-paying-in-stock/
novel-f3-paying-in-stock.py`` — SBC-intensity acceleration
(TTM ShareBasedCompensation / TTM revenue, now minus year-ago),
ranked ascending, quarterly top-5 equal weight, champion mechanics/
costs, plain -15% floor. That module is loaded and called verbatim
(it itself imports the champion plain-floor module for data loading).

Published record ($100 start, plain floor):
  continuous (FULL) 2019-01-02 -> 2026-11-20 : $505.43
  validation       2023-01-03 -> 2026-11-20 : $289.53

Replay data (read-only): EDGAR companyfacts + Yahoo prices from the
champion's caches (``backtests/v4/data/`` and
``backtests/v4/value-momentum-honest-data/``), loaded by the original
modules' own loaders.

Optional explicit inputs for ``run``:
  prices       = {ticker: [{"d":..., "o":..., "c":...}, ...]}
  fundamentals = {"facts_by_ticker": {ticker: companyfacts dict}}
"""
import os

from . import common

_ORIG = None
_DATA = {}


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "nf3_orig",
            os.path.join(common.V8, "novel-f3-paying-in-stock",
                         "novel-f3-paying-in-stock.py"))
    return _ORIG


def _load_data(prices, fundamentals):
    nf3m = _orig()
    champ = nf3m.champ
    # R2-E2: one-of-the-pair supplied is an error, never a silent replay.
    common.require_injected_pair("nf3 engine", prices, fundamentals)
    if prices is not None and fundamentals is not None:
        if not prices:
            raise ValueError("nf3 engine: no price data supplied")
        missing = [t for t in list(champ.UNIVERSE) + ["SPY"] if not prices.get(t)]
        if missing:
            raise ValueError(f"nf3 engine: missing price data for {', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows, engine="nf3 engine")
        # R2-E13/E8: shape + coverage named here, not a bare KeyError.
        common.require_fundamentals("nf3 engine", fundamentals, "facts_by_ticker")
        fmissing = [t for t in champ.UNIVERSE if t not in fundamentals["facts_by_ticker"]]
        if fmissing:
            raise ValueError(f"nf3 engine: missing fundamentals for {', '.join(fmissing)}")
        common.assert_finite_tree("nf3 engine", fundamentals)
        return (champ.PriceBook(prices), fundamentals["facts_by_ticker"])
    if "pb" not in _DATA:
        ciks = champ.get_ciks()
        overrides = {"XOM": 34088}  # champion engine's parent-CIK fix
        facts = {}
        for t in champ.UNIVERSE:
            cik = overrides.get(t, ciks[t][0])
            facts[t] = champ.get_companyfacts(cik)
        bars = {t: champ.get_prices(t) for t in champ.UNIVERSE + ["SPY"]}
        _DATA.update(pb=champ.PriceBook(bars), facts=facts)
    return _DATA["pb"], _DATA["facts"]


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    nf3m = _orig()
    start_cash = common.validate_start_cash("nf3 engine", start_cash)
    pb, facts = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end)
    floor = common.resolve_floor(start_cash, protection)
    stats = {"direct": 0, "derived": 0}
    r = nf3m.run_pot(pb, facts, s, e, float(start_cash), floor,
                     label=f"{wname} NF3", stats=stats)
    if r is None:
        raise ValueError(f"nf3 engine: no trading days in window {s} to {e}")
    extra = {"quarter_values": stats}
    if prices is not None:
        warnings = common.coverage_warnings("nf3 engine", prices, e)
        if warnings:
            extra["warnings"] = warnings
    return common.make_result(
        "nf3", wname, s, e, start_cash, r["final"], r["costs"],
        common.trade_dicts(r["trades"]), r["halted"], r["curve"],
        halt_info=r.get("halt_info"),
        extra=extra)
