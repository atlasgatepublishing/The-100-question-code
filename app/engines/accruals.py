"""Accruals-at-2-holdings engine (ported) — VARIANT-CANDIDATE.

Source of truth: ``backtests/v12-completions/catalog-hxz-accruals/
scripts/engine.py`` — the frozen v12 catalog grid engine, loaded and
called verbatim (``run_road``). The ported cell is named exactly as in
that folder's RESULTS.md:

    Dac | native universe | native rules | ANNUAL | 2 holdings

Dac = Xie (2001) discretionary accruals (modified-Jones cross-sectional
residuals by SIC-2 x year, >=12 firms), long the LOWEST scores, annual
June formations, 12-month holds, equal weight, tiered program costs,
vanished -> ZERO. Signals come from the folder's own ``signals.json``
(built by its ``scripts/build_signals.py`` from its frozen EDGAR
frames); prices/shares come from the W04 broad stack the original
engine reads (``backtests/v11-native-rules/_w04_broad_data/``,
read-only). Nothing is retuned, re-parameterised or "improved".

Published record ($100 start, FLOOR-FREE — native rules; this family
is floor-incompatible, max DD -33.5% breaks the v9 -15% floor habitat,
and the house-rulebook twin of this cell in the original grid is a
different, far weaker cell and is NOT this port):

  LONGEST  formations 2016-2025 : $2,032.91  (costs $45.18, DD -33.53%)
  DECADE   formations 2017-2025 : $1,487.30  (costs $32.88, DD -33.53%)
  CONT     formations 2019-2025 :   $936.18  (costs $18.59, DD -33.53%)
  VAL      formations 2023-2025 :   $343.35  (costs  $6.34, DD -17.11%)
  FOLD_A   formations 2016-2020 :   $381.85
  FOLD_B   formations 2021-2025 :   $532.39

Window names: this family's roads are June-formation year sets, not
calendar windows, so ``run`` maps the common names onto them —
"continuous" -> CONT, "validation" -> VAL — and also accepts
"longest", "decade", "cont", "val", "fold_a" and "fold_b" directly.
Explicit ``start=``/``end=`` are read as a formation span: formations
whose June falls in [start, end) (e.g. start="2019-06", end="2026-06"
is CONT).

The original ``run_road`` records no trade list (it is a monthly
matrix engine), so ``trades`` is empty and ``orders`` is 0; the
per-formation holdings are returned in ``holdings_by_formation``
instead. The original also hard-codes a $100 pot: every cost in the
native form is a percentage rate (no fixed fees, no floor), so the
run is exactly linear in the pot and a non-$100 ``start_cash`` scales
the $100 result (identity at the published $100 basis).

Replay only: caller-supplied ``prices``/``fundamentals`` cannot be
honoured — the original engine's inputs are CIK-keyed signals and
monthly W04 bars, not the ticker/daily shape of the other engines —
so supplying either raises instead of silently replaying.
"""
import os

from . import common

_ORIG = None

FAMILY = os.path.join(common.BACKTESTS, "v12-completions",
                      "catalog-hxz-accruals")
SIGNAL, UNIVERSE, RULEBOOK, CADENCE, COUNT = "Dac", "native", "native", "annual", 2

# Road name -> June-formation years (the folder's own ROADS).
ROADS = {
    "longest": list(range(2016, 2026)),
    "decade": list(range(2017, 2026)),
    "continuous": list(range(2019, 2026)),   # CONT — the middle road
    "cont": list(range(2019, 2026)),
    "validation": list(range(2023, 2026)),   # VAL — the judging road
    "val": list(range(2023, 2026)),
    "fold_a": list(range(2016, 2021)),
    "fold_b": list(range(2021, 2026)),
}


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "accruals_orig", os.path.join(FAMILY, "scripts", "engine.py"))
    return _ORIG


def _formations(window, start, end):
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("accruals engine: pass BOTH start= and end= "
                             "(a June-formation span, e.g. start='2019-06', "
                             "end='2026-06'), or neither")
        lo, hi = str(start), str(end)
        if lo > hi:
            raise ValueError(f"accruals engine: window start {lo} is after "
                             f"window end {hi}")
        # Formation June must lie in [start, end); the final formation's
        # hold ends the June after it, which may equal `end`.
        forms = [f for f in range(2016, 2026) if lo <= f"{f:04d}-06" < hi]
        if not forms:
            raise ValueError(f"accruals engine: no June formations in "
                             f"span {lo} to {hi}")
        return forms, (window or "custom")
    if window not in ROADS:
        raise ValueError(f"accruals engine: unknown window {window!r}; use "
                         f"one of {sorted(ROADS)} or pass start=/end=")
    return list(ROADS[window]), window


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    orig = _orig()
    start_cash = common.validate_start_cash("accruals engine", start_cash)
    if prices is not None or fundamentals is not None:
        raise ValueError(
            "accruals engine: replay only — its original inputs are the "
            "folder's CIK-keyed signals.json and the W04 monthly bars, so "
            "caller-supplied prices/fundamentals cannot be honoured and "
            "will not be silently replaced by the replay record")
    forms, wname = _formations(window, start, end)
    # Native rules = house=False in the original engine: NO floor.
    final, curve, costs, max_dd = orig.run_road(
        forms, SIGNAL, UNIVERSE, COUNT, CADENCE, False)
    scale = float(start_cash) / 100.0
    if scale != 1.0:
        final = round(final * scale, 2)
        costs = round(costs * scale, 2)
        curve = [[d, round(v * scale, 2)] for d, v in curve]
    s, e = f"{forms[0]:04d}-06", f"{forms[-1] + 1:04d}-06"
    holdings = {}
    for f in forms:
        picks = orig.picks_for(SIGNAL, f, UNIVERSE, COUNT)
        holdings[str(f)] = [str(orig.cand[c].get("ticker") or c) for c in picks]
    extra = {
        "signal": SIGNAL, "universe": UNIVERSE, "rulebook": RULEBOOK,
        "cadence": CADENCE, "holdings_count": COUNT,
        "formations": forms, "max_dd": max_dd,
        "holdings_by_formation": holdings,
        "pool_sizes": {str(f): len(orig.POOLS[(SIGNAL, f, UNIVERSE)])
                       for f in forms},
    }
    notes = []
    if protection is not None:
        notes.append("protection has no effect on the accruals engine: "
                     "the published cell is floor-FREE under native rules "
                     "(max drawdown -33.5% breaks the -15% floor habitat); "
                     "the floored house-rulebook twin is a different cell "
                     "and is not ported")
    notes.append("the original catalog engine records no trade list; "
                 "orders is 0 and holdings are in holdings_by_formation")
    extra["warnings"] = notes
    return common.make_result(
        "accruals", wname, s, e, start_cash, final, costs,
        [], None, curve, extra=extra)
