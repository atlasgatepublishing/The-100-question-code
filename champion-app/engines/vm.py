"""V+M — Value + Momentum champion engine (ported).

Source of truth: ``backtests/v4/value-momentum-plainfloor.py`` — the
promoted champion run (book-to-market + 12-1 momentum percentile-
average rank, quarterly top-5 equal weight, costs 0.10%/side +
$0.01/sell, plain -15% floor). That module is loaded and called
verbatim; this file only adapts its inputs/outputs to the common
engine interface. (The older ``value-momentum.py`` is the superseded
ladder/hindsight-universe variant and is NOT the champion record.)

Published record (plain-floor basis, $100 start):
  continuous 2019-01-02 -> 2026-11-20 : $544.47
  validation 2023-01-03 -> 2026-11-20 : $288.05

Replay data (read-only): EDGAR companyfacts cached in
``backtests/v4/data/`` and Yahoo prices cached in
``backtests/v4/data/`` + ``backtests/v4/value-momentum-honest-data/``,
loaded by the original module's own loaders.

Optional explicit inputs for ``run``:
  prices       = {ticker: [{"d":..., "o":..., "c":...}, ...]}
  fundamentals = {"equity_rows": {ticker: rows}, "shares_rows": {...}}
                 in the original module's pit_series row format.
"""
import os

from . import common

_ORIG = None
_DATA = {}


def _orig():
    global _ORIG
    if _ORIG is None:
        # DERIVED APP ADAPTATION (recorded in BUILD-REPORT.md): the
        # frozen adapter loaded the original script from the external
        # backtests folder. The derived app vendors the script in its
        # own tree as engines/champion_original.py (byte identical to
        # backtests/v4/value-momentum-plainfloor.py, SHA-256 checked)
        # and loads that copy. The script resolves its replay caches
        # relative to its own file, so after loading, its cache
        # globals are repointed at the program's cache directory
        # (default: the frozen v4 folder; override with the
        # CHAMPION_APP_V4_DIR environment variable). The script file
        # itself is never modified.
        mod = common.load_module(
            "vm_plainfloor_orig",
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "champion_original.py"))
        v4 = os.environ.get("CHAMPION_APP_V4_DIR", common.V4)
        mod.HERE = v4
        mod.SHARED = os.path.join(v4, "data")
        mod.DATA = os.path.join(v4, "value-momentum-honest-data")
        # The script creates its cache folder beside itself at import;
        # after the repoint above that folder is unused, so remove it
        # if it is a real, empty directory (never a symlink, never
        # anything with content).
        try:
            os.rmdir(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "value-momentum-honest-data"))
        except OSError:
            pass
        _ORIG = mod
    return _ORIG


def _load_data(prices, fundamentals):
    """Build (PriceBook, equity_rows, shares_rows) from the original
    caches, or from caller-supplied prices/fundamentals."""
    champ = _orig()
    # R2-E2: one-of-the-pair supplied is an error, never a silent replay.
    common.require_injected_pair("vm engine", prices, fundamentals)
    if prices is not None and fundamentals is not None:
        # QA M-13/H-1: fail with the missing symbol named, not a bare
        # TypeError deep inside the original engine.
        if not prices:
            raise ValueError("vm engine: no price data supplied "
                             f"(need series for {', '.join(champ.UNIVERSE[:3])}, …)")
        missing = [t for t in list(champ.UNIVERSE) + ["SPY"] if not prices.get(t)]
        if missing:
            raise ValueError(f"vm engine: missing price data for {', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows, engine="vm engine")
        # R2-E13/E8: fundamentals shape + universe coverage, named here.
        common.require_fundamentals("vm engine", fundamentals,
                                    "equity_rows", "shares_rows")
        fmissing = [t for t in champ.UNIVERSE
                    if t not in fundamentals["equity_rows"]
                    or t not in fundamentals["shares_rows"]]
        if fmissing:
            raise ValueError(f"vm engine: missing fundamentals for "
                             f"{', '.join(fmissing)}")
        # R2-E1: no NaN/infinite fundamentals values, anywhere.
        common.assert_finite_tree("vm engine", fundamentals)
        return (champ.PriceBook(prices), fundamentals["equity_rows"],
                fundamentals["shares_rows"])
    if "pb" not in _DATA:
        ciks = champ.get_ciks()
        overrides = {"XOM": 34088}  # champion engine's parent-CIK fix
        equity_rows, shares_rows = {}, {}
        for t in champ.UNIVERSE:
            cik = overrides.get(t, ciks[t][0])
            facts = champ.get_companyfacts(cik)
            equity_rows[t] = (
                champ.pit_series(facts, "us-gaap", "StockholdersEquity",
                                 prio=2)
                + champ.pit_series(
                    facts, "us-gaap",
                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                    prio=1))
            shares_rows[t] = (
                champ.pit_series(facts, "dei",
                                 "EntityCommonStockSharesOutstanding",
                                 prio=3)
                + champ.pit_series(facts, "us-gaap",
                                   "CommonStockSharesOutstanding", prio=2)
                + champ.pit_series(
                    facts, "us-gaap",
                    "WeightedAverageNumberOfSharesOutstandingBasic",
                    prio=1))
        bars = {t: champ.get_prices(t) for t in champ.UNIVERSE + ["SPY"]}
        _DATA.update(pb=champ.PriceBook(bars), equity_rows=equity_rows,
                     shares_rows=shares_rows)
    return _DATA["pb"], _DATA["equity_rows"], _DATA["shares_rows"]


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    champ = _orig()
    start_cash = common.validate_start_cash("vm engine", start_cash)
    pb, equity_rows, shares_rows = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end)
    floor = common.resolve_floor(start_cash, protection)
    r = champ.run_pot(pb, equity_rows, shares_rows, s, e,
                      float(start_cash), floor, [],  # ladder=[]: plain floor
                      label=f"{wname} VM", quiet=True)
    if r is None:
        # R2-E5: the original returns None when no days fall in window.
        raise ValueError(f"vm engine: no trading days in window {s} to {e}")
    extra = None
    if prices is not None:
        # QA M-13: thin injected data must not silently look like a real run.
        warnings = []
        thin = [t for t, rows in prices.items() if len(rows) < 30]
        if thin:
            warnings.append(f"thin price history (<30 bars) for: {', '.join(sorted(thin))} — "
                            "result may reflect little or no trading")
        warnings += common.coverage_warnings("vm engine", prices, e)
        if warnings:
            extra = {"warnings": warnings}
    return common.make_result(
        "vm", wname, s, e, start_cash, r["final"], r["costs"],
        common.trade_dicts(r["trades"]), r["halted"], r["curve"],
        halt_info=r.get("halt_info"), extra=extra)
