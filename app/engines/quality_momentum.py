"""Quality + Momentum engine (ported) — App v2 Horizon Picker build.

Source of truth: ``backtests/v10-retest/quality-momentum/qm_v10.py``
— THE GREAT RETEST (v10). That module is loaded and called verbatim;
this file only adapts its inputs/outputs to the common engine
interface. No strategy logic is retuned or "improved" here.

Strategy (frozen, from the source): rank the 20-name pond by
Novy-Marx gross profitability (quality) plus 12-1 momentum (average
of the two percentile ranks), hold the top 5 equal-weighted.
Selection is scored on the cadence date's close and executed at the
next trading day's open; the -15% floor check stays daily.
Protections are the source's v9 form, exactly as its ``run_v9``
implements them: plain -15% floor from the starting balance, NO
ladder, 90-day sit-out after a halt, restart at the next cadence
date, episode-2 floor -15% from the restart balance, second halt
ends the run. Costs: 0.10% of trade value per side + $0.01 per sell.

Published record ($100 start, v9 protections):
  DECADE 2016-11-21 -> 2026-11-20:
    daily $847.62 / weekly $1,164.49 / biweekly $1,096.12 /
    monthly $1,097.93
  continuous 2019-01-02 -> 2026-11-20, weekly form: $698.38
  (confirmation run, ``confirmation/CONFIRMATION.md``)

Cadence forms: ``run(..., form=...)`` with form one of "daily",
"weekly", "biweekly", "monthly" (the four picker forms). The source
script's other cadences ("quarterly" — the strategy's native form —
"semiannual", "annual") are also accepted, since the source supports
them verbatim. Default form is "weekly" (the confirmed money
cadence). ``cadence=`` is accepted as an alias for ``form=``.

Windows: "decade" (2016-11-21 -> 2026-11-20, the sweep road),
"continuous" (2019-01-02 -> 2026-11-20) and "validation"
(2023-01-03 -> 2026-11-20), plus explicit ``start=`` / ``end=``.

Replay data (read-only): full-range Yahoo payloads from
``backtests/v7/long-hold/data/`` (GOOGL from
``backtests/long-run-2010/data/``, AMD from the v10 folder's own
``data/``) and EDGAR companyfacts from ``backtests/v4/data/``,
loaded by the original module's own loaders (``load_bars_full`` /
``load_quality``) — the exact plumbing that produced the published
sweep and confirmation numbers.

Optional explicit inputs for ``run``:
  prices       = {ticker: [{"d":..., "o":..., "c":...}, ...]}
                 for the 20 universe names (+ SPY optional).
  fundamentals = {"quality_obs": {ticker: [(filed, end, value,
                 method), ...]}} in the original module's quality-
                 observation format, OR {"facts": {ticker: <EDGAR
                 companyfacts dict>}}, which is converted with the
                 original ``build_quality_observations``.

Deviations from the common interface (documented, unavoidable):
  * The result's "halted" is the FIRST halt's signal date (or None);
    the v9 chassis can halt, sit out 90 days and restart, so the full
    halt list is returned under "halts" (replacing the single-entry
    list ``common.make_result`` builds) plus "restart" /
    "second_halt" flags.
  * On the published basis (start_cash=100, protection=None) the
    original ``run_v9`` is called verbatim. For any other start_cash
    or an explicit protection floor, a parameterised copy of that
    wrapper is used (same code path via the original ``run_episode``;
    episode-2 floor keeps the same fraction of the restart balance
    as the caller's floor bears to start_cash). The published
    figures are unaffected.
"""
import os
from datetime import timedelta

from . import common

_ORIG = None
_DATA = {}

QM_DIR = os.path.join(common.BACKTESTS, "v10-retest", "quality-momentum")
FORMS = ("daily", "weekly", "biweekly", "monthly")
WINDOWS = dict(common.WINDOWS)
WINDOWS["decade"] = ("2016-11-21", "2026-11-20")


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "qm_v10_orig", os.path.join(QM_DIR, "qm_v10.py"))
    return _ORIG


def _load_data(prices, fundamentals):
    """Build (PriceBook, quality_obs) from caller-supplied data, or
    from the original caches via the original loaders."""
    qm = _orig()
    common.require_injected_pair("quality_momentum engine",
                                 prices, fundamentals)
    if prices is not None and fundamentals is not None:
        if not prices:
            raise ValueError("quality_momentum engine: no price data "
                             "supplied (need series for "
                             f"{', '.join(qm.UNIVERSE[:3])}, …)")
        missing = [t for t in qm.UNIVERSE if not prices.get(t)]
        if missing:
            raise ValueError("quality_momentum engine: missing price "
                             f"data for {', '.join(missing)}")
        for t, rows in prices.items():
            common.validate_price_series(t, rows,
                                         engine="quality_momentum engine")
        common.assert_finite_tree("quality_momentum engine", fundamentals)
        if "quality_obs" in fundamentals:
            if not fundamentals["quality_obs"]:
                raise ValueError("quality_momentum engine: "
                                 "fundamentals['quality_obs'] is empty")
            fmissing = [t for t in qm.UNIVERSE
                        if t not in fundamentals["quality_obs"]]
            if fmissing:
                raise ValueError("quality_momentum engine: missing "
                                 "quality observations for "
                                 f"{', '.join(fmissing)}")
            quality = {t: [tuple(o) for o in fundamentals["quality_obs"][t]]
                       for t in qm.UNIVERSE}
        elif "facts" in fundamentals:
            if not fundamentals["facts"]:
                raise ValueError("quality_momentum engine: "
                                 "fundamentals['facts'] is empty")
            fmissing = [t for t in qm.UNIVERSE
                        if t not in fundamentals["facts"]]
            if fmissing:
                raise ValueError("quality_momentum engine: missing "
                                 f"companyfacts for {', '.join(fmissing)}")
            quality = {t: qm.build_quality_observations(fundamentals["facts"][t])
                       for t in qm.UNIVERSE}
        else:
            raise ValueError("quality_momentum engine: fundamentals must "
                             "carry 'quality_obs' or 'facts' — got keys "
                             f"{sorted(fundamentals)}")
        return qm.PriceBook(prices), quality
    if "pb" not in _DATA:
        bars = {t: qm.load_bars_full(t) for t in qm.UNIVERSE + ["SPY"]}
        _DATA.update(pb=qm.PriceBook(bars), quality=qm.load_quality())
    return _DATA["pb"], _DATA["quality"]


def _run_v9_param(qm, pb, quality, start, end, cadence, start_cash, floor):
    """Parameterised copy of the source's run_v9 wrapper (used only
    off the published basis): plain floor, no ladder; on first halt,
    sit 90 calendar days, restart at the next cadence date on/after
    eligibility; episode-2 floor keeps the caller's floor fraction of
    the restart balance; second halt ends the run."""
    from datetime import date
    sel_all = qm.cadence_dates(pb, cadence, start, end)
    ep1 = qm.run_episode(pb, quality, start, end, float(start_cash),
                         float(floor), [], sel_all, want_curve=True)
    if ep1 is None:
        return None
    out = {"episode1": ep1, "episode2": None, "final": ep1["final"],
           "halts": [], "restart": False, "second_halt": False,
           "costs": ep1["costs"], "orders": len(ep1["trades"]),
           "curve": list(ep1["curve"])}
    if ep1["halted"] is None:
        return out
    out["halts"].append({"episode": 1, "signal_date": ep1["halted"],
                         "signal_close": ep1["halt_close"],
                         "floor": ep1["floor_in_effect"],
                         "liquidation_date": ep1["end"],
                         "cash_after": ep1["final"]})
    liq = date.fromisoformat(ep1["end"])
    cash1 = ep1["final"]
    eligible = (liq + timedelta(days=90)).isoformat()
    cands = [d for d in sel_all if d >= eligible]
    if not cands:
        return out
    restart = cands[0]
    out["restart"] = True
    out["restart_date"] = restart
    out["restart_balance"] = cash1
    frac = float(floor) / float(start_cash) if start_cash else 0.85
    ep2 = qm.run_episode(pb, quality, restart, end, cash1, frac * cash1,
                         [], [d for d in sel_all if d >= restart],
                         want_curve=True)
    out["episode2"] = ep2
    out["final"] = ep2["final"]
    out["costs"] += ep2["costs"]
    out["orders"] += len(ep2["trades"])
    curve = list(ep1["curve"])
    have = {d for d, _ in curve}
    dcur = liq
    while dcur.isoformat() < restart:
        ds = dcur.isoformat()
        if ds in pb.didx and start <= ds <= end and ds not in have:
            curve.append((ds, round(cash1, 4)))
        dcur += timedelta(days=1)
    curve.extend(ep2["curve"])
    curve.sort()
    out["curve"] = curve
    if ep2["halted"] is not None:
        out["second_halt"] = True
        out["halts"].append({"episode": 2, "signal_date": ep2["halted"],
                             "signal_close": ep2["halt_close"],
                             "floor": ep2["floor_in_effect"],
                             "liquidation_date": ep2["end"],
                             "cash_after": ep2["final"]})
    return out


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None, form="weekly",
        cadence=None):
    qm = _orig()
    if cadence is not None:
        form = cadence
    if form not in qm.CADENCES:
        raise ValueError(f"quality_momentum engine: unknown form "
                         f"{form!r}; use one of {list(qm.CADENCES)}")
    start_cash = common.validate_start_cash("quality_momentum engine",
                                            start_cash)
    pb, quality = _load_data(prices, fundamentals)
    s, e, wname = common.resolve_window(window, start, end,
                                        windows=WINDOWS)
    floor = common.resolve_floor(start_cash, protection)
    if start_cash == 100.0 and protection is None:
        # Published basis: the original wrapper, verbatim.
        r = qm.run_v9(pb, quality, s, e, form, want_curve=True)
    else:
        r = _run_v9_param(qm, pb, quality, s, e, form, start_cash, floor)
    if r is None or r.get("episode1") is None:
        raise ValueError(f"quality_momentum engine: no trading days in "
                         f"window {s} to {e}")
    trades = list(r["episode1"]["trades"])
    if r.get("episode2"):
        trades += list(r["episode2"]["trades"])
    halts = r.get("halts") or []
    halted = halts[0]["signal_date"] if halts else None
    extra = {"form": form, "cadence": form,
             "halts": halts,
             "restart": bool(r.get("restart")),
             "second_halt": bool(r.get("second_halt"))}
    if r.get("restart"):
        extra["restart_date"] = r.get("restart_date")
        extra["restart_balance"] = r.get("restart_balance")
    if prices is not None:
        warnings = []
        thin = [t for t, rows in prices.items() if len(rows) < 30]
        if thin:
            warnings.append(f"thin price history (<30 bars) for: "
                            f"{', '.join(sorted(thin))} — result may "
                            "reflect little or no trading")
        warnings += common.coverage_warnings("quality_momentum engine",
                                             prices, e)
        if warnings:
            extra["warnings"] = warnings
    return common.make_result(
        "quality_momentum", wname, s, e, start_cash, r["final"],
        r["costs"], common.trade_dicts(trades), halted, r["curve"],
        extra=extra)
