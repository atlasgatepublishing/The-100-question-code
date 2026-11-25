"""N-F3 "Paying in Stock" — HORIZON forms engine (ported).

Source of truth: ``backtests/v10-retest/novel-f3-paying-in-stock/
sweep.py`` — THE GREAT RETEST (v10) cadence sweep. That module is
loaded and called verbatim; this file only adapts its inputs/outputs
to the common engine interface. This is a DIFFERENT published run
from ``engines/nf3.py`` (the v4/v8 quarterly record $505.43/$289.53 on
the 2019+ roads): here the chassis is the v10 sweep on the DECADE
road, with data via ``backtests/long-run-2010/lr_common.py`` (full-
range Yahoo payloads + long-hold EDGAR cache) and v9 protections.

Published record ($100 start, DECADE 2016-11-21 -> 2026-11-20):
  quarterly  (every 3 months, native cadence) : $737.97
  semiannual (every 6 months)                 : $848.79
Costs / orders: quarterly $8.87 / 253, semiannual $7.07 / 141.
No cell halted on the decade road.

Forms: ``run(..., form="quarterly")`` re-ranks on the first trading
day of each calendar quarter (Jan/Apr/Jul/Oct); ``form="semiannual"``
on the first trading day of each half-year (Jan/Jul) — exactly the
sweep's ``cadence_dates`` definition. Signal, trade mechanics and
costs (0.10%/side + $0.01 per sell order) are the sweep's verbatim
copies of the v8 original.

Protections (v9 house rules, as the v10 script implements them):
plain -15% floor from the EPISODE's starting balance; on a first
halt, liquidate at the next open, sit in cash 90 calendar days, and
restart at the next regular cadence date on/after eligibility under
an episode-2 floor of -15% from the restart balance; a second halt
ends the run. Implemented by the sweep module's own ``run_v9``.

Deviations from the common interface / from the sweep script
(documented, none retune anything):
  * ``window="decade"`` is the default and the published window;
    "continuous"/"validation" and explicit start=/end= are accepted
    for picker symmetry but are NOT published records for these
    forms (the sweep ran only the decade road).
  * ``protection``: ``None`` (default) is the published v9 basis
    above — NOT the common plain-floor-ends-the-run basis. An
    explicit protection override (via ``common.resolve_floor``)
    sets the EPISODE-1 floor only; the episode-2 floor stays the
    v9 verbatim 0.85 x restart balance inside ``run_v9``.
  * Scores are computed only for the form's selection dates (40
    quarterly / 20 semiannual on the decade) instead of the sweep's
    all-days precompute. The sweep's ``SignalCache`` makes a score
    depend only on facts filed before the date, so per-date scores
    are identical; the placebo twins (not ported) were the only
    other consumer of the all-days table.
  * Result ``halted`` is the FIRST halt's signal date (or None);
    the full v9 halt list and restart record are in ``halts_v9``
    and ``restart`` extras. ``orders`` counts trades across both
    episodes, as the sweep's cells do.

Optional explicit inputs for ``run``:
  prices       = {ticker: [{"d":..., "o":..., "c":...}, ...]}
                 (adjclose-basis bars, as ``lr_common.bars_adj``
                 builds them; universe + SPY required)
  fundamentals = {"facts_by_ticker": {ticker: companyfacts dict}}
"""
import os

from . import common

_ORIG = None
_DATA = {}

V10_DIR = os.path.join(common.BACKTESTS, "v10-retest",
                       "novel-f3-paying-in-stock")
DECADE = ("2016-11-21", "2026-11-20")
WINDOWS = {"decade": DECADE, "continuous": common.CONTINUOUS,
           "full": common.CONTINUOUS, "validation": common.VALIDATION}
FORMS = ("quarterly", "semiannual")


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "nf3_horizon_sweep_orig", os.path.join(V10_DIR, "sweep.py"))
    return _ORIG


def _load_data(prices, fundamentals):
    """Build (FastPriceBook, {ticker: SignalCache}) from the original
    caches, or from caller-supplied prices/fundamentals."""
    sweep = _orig()
    C = sweep.C  # lr_common, as imported by the sweep itself
    common.require_injected_pair("nf3_horizon engine", prices, fundamentals)
    if prices is not None and fundamentals is not None:
        if not prices:
            raise ValueError("nf3_horizon engine: no price data supplied")
        missing = [t for t in list(sweep.UNIVERSE) + ["SPY"]
                   if not prices.get(t)]
        if missing:
            raise ValueError("nf3_horizon engine: missing price data "
                             f"for {', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows, engine="nf3_horizon engine")
        common.require_fundamentals("nf3_horizon engine", fundamentals,
                                    "facts_by_ticker")
        fmissing = [t for t in sweep.UNIVERSE
                    if t not in fundamentals["facts_by_ticker"]]
        if fmissing:
            raise ValueError("nf3_horizon engine: missing fundamentals "
                             f"for {', '.join(fmissing)}")
        common.assert_finite_tree("nf3_horizon engine", fundamentals)
        caches = {t: sweep.SignalCache(fundamentals["facts_by_ticker"][t])
                  for t in sweep.UNIVERSE}
        return C.FastPriceBook(prices), caches
    if "pb" not in _DATA:
        caches = {}
        for t in sweep.UNIVERSE:
            cik = C.cik_for(t)
            if t == "XOM":
                cik = 34088  # champion engine's override, as in sweep.main
            caches[t] = sweep.SignalCache(C.load_facts(cik))
        bars = {t: C.bars_adj(C.yahoo_payload(t))
                for t in sweep.UNIVERSE + ["SPY"]}
        _DATA.update(pb=C.FastPriceBook(bars), caches=caches)
    return _DATA["pb"], _DATA["caches"]


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="decade", start=None, end=None, form="quarterly"):
    sweep = _orig()
    if form not in FORMS:
        raise ValueError(f"nf3_horizon engine: unknown form {form!r}; "
                         f"use one of {list(FORMS)}")
    start_cash = common.validate_start_cash("nf3_horizon engine", start_cash)
    pb, caches = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end, windows=WINDOWS)
    # Episode-1 floor: published v9 basis is 0.85 * start_cash, which
    # is exactly common.resolve_floor(None); an override replaces it
    # for episode 1 only (see docstring).
    floor0 = common.resolve_floor(start_cash, protection)

    days = [d for d in pb.dates if s <= d <= e]
    if not days:
        raise ValueError(f"nf3_horizon engine: no trading days in "
                         f"window {s} to {e}")
    sel = sweep.cadence_dates(days, form)
    # Scores only for this form's selection dates (see docstring).
    scores_by_date = {}
    for d in sel:
        sc = {}
        for t in sweep.UNIVERSE:
            v, _st = caches[t].get(d)
            if v is not None:
                sc[t] = v
        scores_by_date[d] = sc

    def run_one(s_, e_, cash, floor):
        sub = [d for d in sel if s_ <= d <= e_]
        return sweep.run_pot(pb, scores_by_date, sub, s_, e_, cash, floor)

    if protection is None:
        r = sweep.run_v9(run_one, pb.dates, s, e, float(start_cash))
    else:
        # Override: run_v9 hardcodes the episode-1 floor as
        # 0.85 * start_cash; replicate its wrapper with floor0 for
        # episode 1 by temporarily wrapping run_one's first call.
        # Simplest faithful route: call run_v9's logic via a first
        # episode at floor0, then defer to run_v9 for any restart by
        # re-running from eligibility — implemented inline here using
        # the sweep's own run_pot only (no new mechanics).
        r = _run_with_floor0(sweep, run_one, pb.dates, s, e,
                             float(start_cash), floor0)
    trades = []
    for ep in r["episodes"]:
        trades.extend(ep["trades"])
    halted = r["halts"][0]["signal_date"] if r["halts"] else None
    halt_info = None
    if r["halts"]:
        h0 = r["halts"][0]
        halt_info = {"signal_date": h0["signal_date"],
                     "signal_close": h0["signal_close"],
                     "floor_in_effect": h0["floor_in_effect"],
                     "liquidation_date": h0["liquidation_date"],
                     "proceeds": h0["proceeds"]}
    extra = {"form": form, "halts_v9": r["halts"],
             "restart": r["restart"],
             "episodes": len(r["episodes"]),
             "n_selection_dates": len(sel)}
    if prices is not None:
        warnings = common.coverage_warnings("nf3_horizon engine", prices, e)
        if warnings:
            extra["warnings"] = warnings
    return common.make_result(
        "nf3_horizon", wname, s, e, start_cash, r["final"], r["costs"],
        common.trade_dicts(trades), halted, r["curve"],
        halt_info=halt_info, extra=extra)


def _run_with_floor0(sweep, run_one, trading_days, start, end,
                     start_cash, floor0):
    """run_v9 clone for a non-default episode-1 floor: identical
    stitching/halt bookkeeping to sweep.run_v9, except episode 1 uses
    floor0 and episode 2 (if any) uses 0.85 * episode-1 final, as
    run_v9 does. Only reached when protection= is overridden."""
    from datetime import date, timedelta
    episodes = []
    ep1 = run_one(start, end, start_cash, floor0)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(elig, end, ep1["final"], 0.85 * ep1["final"])
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = None
                if ep2.get("pools"):
                    first = ep2["pools"][0]
                    first_sel = first[0] if isinstance(first, (list, tuple)) \
                        else first.get("date")
                restart = {"halt_date": ep1["halted"],
                           "halt_signal_close":
                               ep1["halt_info"]["signal_close"]
                               if ep1.get("halt_info") else None,
                           "liquidation_proceeds": round(ep1["final"], 2),
                           "eligibility_date": elig,
                           "episode2_first_selection": first_sel,
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "second_halt": ep2["halted"]}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        gap_days = [d for d in trading_days
                    if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap_days]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1, "signal_date": ep["halted"],
                          "signal_close":
                              ep["halt_info"]["signal_close"]
                              if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"episodes": episodes, "final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "halts": halts, "restart": restart, "curve": curve}
