"""Switch B engine (ported) — champion first half, then the blend.

Source of truth: ``backtests/v8/switch-champion-to-blend/
switch-champion-to-blend.py`` — one $100 pot, one plain -15% floor:
Phase 1 runs the V+M champion alone on the full pot; at the first
quarterly selection date on/after 2023-01-01 (2023-01-03) the pot
splits into the 50/50 champion x N-F3 blend, constructed exactly as
in the original combo machinery (each sleeve its own sub-pot, budgets
reset to 50/50 of the combined close at each selection date, sells ->
inter-sleeve cash transfer -> buys at the next open). That module is
loaded and its ``run_switch`` called verbatim.

Published record ($100 start, plain floor):
  continuous 2019-01-02 -> 2026-11-20 : $549.43
  (validation window opens on the switch date itself, so it is the
  pure blend by construction: $290.45 in the original run — reported
  by the integrity test for information, not part of the task's
  asserted figures.)

Replay data (read-only): the champion's EDGAR companyfacts + Yahoo
price caches, loaded by the original modules' own loaders; the
original script's Scorer class memoizes both parents' signals.
"""
import os

from . import common

_ORIG = None
_DATA = {}

SWITCH_ON_OR_AFTER = "2023-01-01"  # frozen by the original spec


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "switch_b_orig",
            os.path.join(common.V8, "switch-champion-to-blend",
                         "switch-champion-to-blend.py"))
    return _ORIG


def _load_data(prices, fundamentals):
    sw = _orig()
    champ = sw.champ
    # R2-E2: one-of-the-pair supplied is an error, never a silent replay.
    common.require_injected_pair("switch_b engine", prices, fundamentals)
    if prices is not None and fundamentals is not None:
        if not prices:
            raise ValueError("switch_b engine: no price data supplied")
        missing = [t for t in list(champ.UNIVERSE) + ["SPY"] if not prices.get(t)]
        if missing:
            raise ValueError(f"switch_b engine: missing price data for {', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows, engine="switch_b engine")
        # R2-E13/E8: shape + coverage named here, not a bare KeyError.
        common.require_fundamentals("switch_b engine", fundamentals,
                                    "equity_rows", "shares_rows", "facts_by_ticker")
        fmissing = [t for t in champ.UNIVERSE
                    if t not in fundamentals["equity_rows"]
                    or t not in fundamentals["shares_rows"]
                    or t not in fundamentals["facts_by_ticker"]]
        if fmissing:
            raise ValueError(f"switch_b engine: missing fundamentals for "
                             f"{', '.join(fmissing)}")
        common.assert_finite_tree("switch_b engine", fundamentals)
        pb = champ.PriceBook(prices)
        scorer = sw.Scorer(pb, fundamentals["equity_rows"],
                           fundamentals["shares_rows"],
                           fundamentals["facts_by_ticker"])
        return pb, scorer
    if "scorer" not in _DATA:
        ciks = champ.get_ciks()
        overrides = {"XOM": 34088}  # champion engine's parent-CIK fix
        facts, equity_rows, shares_rows = {}, {}, {}
        for t in champ.UNIVERSE:
            cik = overrides.get(t, ciks[t][0])
            f = champ.get_companyfacts(cik)
            facts[t] = f
            equity_rows[t] = (
                champ.pit_series(f, "us-gaap", "StockholdersEquity",
                                 prio=2)
                + champ.pit_series(
                    f, "us-gaap",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                    prio=1))
            shares_rows[t] = (
                champ.pit_series(f, "dei",
                                 "EntityCommonStockSharesOutstanding",
                                 prio=3)
                + champ.pit_series(f, "us-gaap",
                                   "CommonStockSharesOutstanding", prio=2)
                + champ.pit_series(
                    f, "us-gaap",
                    "WeightedAverageNumberOfSharesOutstandingBasic",
                    prio=1))
        bars = {t: champ.get_prices(t) for t in champ.UNIVERSE + ["SPY"]}
        pb = champ.PriceBook(bars)
        _DATA.update(pb=pb,
                     scorer=sw.Scorer(pb, equity_rows, shares_rows, facts))
    return _DATA["pb"], _DATA["scorer"]


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None,
        switch_on_or_after=SWITCH_ON_OR_AFTER):
    sw = _orig()
    start_cash = common.validate_start_cash("switch_b engine", start_cash)
    pb, scorer = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end)
    floor = common.resolve_floor(start_cash, protection)
    r = sw.run_switch(pb, scorer, s, e, switch_on_or_after,
                      start_cash=float(start_cash), floor0=floor,
                      label=f"{wname} SWITCH-B")
    if r is None:
        raise ValueError(f"switch_b engine: no trading days in window {s} to {e}")
    extra = {"switch_date": r.get("switch_date"),
             "switch_close_value": r.get("switch_close"),
             "switch_exec_date": r.get("switch_exec_date"),
             "sleeve_finals": r.get("sleeve_finals"),
             "transfers": r.get("transfers")}
    if prices is not None:
        warnings = common.coverage_warnings("switch_b engine", prices, e)
        if warnings:
            extra["warnings"] = warnings
    return common.make_result(
        "switch_b", wname, s, e, start_cash, r["final"], r["costs"],
        common.trade_dicts(r["trades"], with_sleeve=True), r["halted"],
        r["curve"], halt_info=r.get("halt_info"),
        extra=extra)
