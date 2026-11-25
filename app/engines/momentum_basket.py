"""Momentum basket engine (ported) — honest-universe monthly basket.

Source of truth: ``backtests/v4/momentum-basket-honest.py`` — monthly
selection, eligible = close above own 200-day SMA, rank by 12-1
momentum, top-5 at 20% of pot each, rebalance at the selection day's
open, costs 0.10%/side + $0.01/sell. That module is loaded and its
``simulate`` called verbatim. (The older ``momentum-basket.py`` used
the hindsight 20-name universe and is NOT the published record.)

Published record ($100 start): full/continuous $439.45 / validation
$208.27. The published basis for judging is the PLAIN -15% floor:
``backtests/v4/basket-walkforward-results.json`` re-ran this engine
with the ladder removed and got the identical $439.45 (the ladder
rungs never changed the outcome on these windows). Accordingly this
port runs the original engine with its FLOORS table set to the plain
floor for the integrity basis — a protection setting, not a strategy
change; every selection/sizing/cost rule is the original's.

Windows (the basket's own, from the original script):
  continuous/full 2016-11-21 -> 2026-11-20
  validation      2023-01-01 -> 2026-11-20

Replay data (read-only): Yahoo bars cached in
``backtests/v4/momentum-basket-honest-data/``, loaded by the original
module's own Market class.

Faithfulness notes:
- The original engine does not keep a per-trade log; it records an
  aggregate order count and total costs. ``trades`` is therefore an
  empty list and the true counts are in ``orders``/``costs``.
- The original's final balance on a non-halted run is the closing
  mark-to-market equity (it does not charge an end-of-window
  liquidation). That is the published $439.45 basis and is preserved.
"""
import os

from . import common

_ORIG = None
_MKT = None

WINDOWS = {"continuous": ("2016-11-21", "2026-11-20"),
           "full": ("2016-11-21", "2026-11-20"),
           "validation": ("2023-01-01", "2026-11-20")}


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "momentum_basket_honest_orig",
            os.path.join(common.V4, "momentum-basket-honest.py"))
    return _ORIG


def _market(prices):
    global _MKT
    orig = _orig()
    if prices is not None:
        raise ValueError("momentum_basket replay uses the original "
                         "cached Market data; explicit price injection "
                         "is not supported by the original engine")
    if _MKT is None:
        _MKT = orig.Market(orig.UNIVERSE)
    return _MKT


def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    orig = _orig()
    if fundamentals is not None:
        # The basket consumes no fundamentals; an unused input must not
        # be silently ignored (R2-E2 principle).
        raise ValueError("momentum_basket engine: fundamentals are not "
                         "used by this engine — pass fundamentals=None")
    mkt = _market(prices)
    s, e, wname = common.resolve_window(window, start, end,
                                        windows=WINDOWS)
    start_cash = common.validate_start_cash("momentum_basket engine", start_cash)
    floor = common.resolve_floor(start_cash, protection)
    # R2-E6: the original engine keys its FLOORS table by whole-dollar
    # pot. A fractional start used to be silently rounded ($100.49 ran
    # as $100 while the result claimed 100.49) — refuse it by name.
    if float(start_cash) != int(float(start_cash)):
        raise ValueError(f"momentum_basket engine: the original engine "
                         f"runs whole-dollar pots only; start_cash "
                         f"{start_cash!r} would have to be rounded — "
                         f"refusing to change the pot silently")
    pot = int(float(start_cash))
    # Plain-floor protection basis (see module docstring): swap the
    # original's FLOORS entry for a ladder-free floor, run, restore —
    # including restoring ABSENCE (R2-E6: a leaked key persisted in the
    # original module's global FLOORS for the rest of the process).
    had_key = pot in orig.FLOORS
    saved = orig.FLOORS.get(pot)
    orig.FLOORS[pot] = (floor, [])
    try:
        try:
            r = orig.simulate(mkt, s, e, pot, "ranked")
        except StopIteration:
            # R2-E5: empty window surfaced as a bare StopIteration.
            raise ValueError(f"momentum_basket engine: no trading days "
                             f"in window {s} to {e}") from None
    finally:
        if had_key:
            orig.FLOORS[pot] = saved
        else:
            orig.FLOORS.pop(pot, None)
    return common.make_result(
        "momentum_basket", wname, s, e, start_cash, r.final, r.costs,
        [], r.halt_date, r.equity_curve,
        extra={"orders": r.orders,
               "trades_note": "original engine records aggregate order "
                              "count/costs only; no per-trade log exists",
               "final_basis": "closing mark-to-market equity on a "
                              "non-halted run (original engine basis)"})
