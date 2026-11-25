"""SPY shadow benchmark — buy-and-hold SPY on the same cash/dates.

Uses the champion engine's own ``spy_net`` (backtests/v4/
value-momentum-plainfloor.py) and its cached SPY prices, so the
benchmark is computed with exactly the published method: buy at the
first window day's open with the buy cost taken out of the pot
(shares = (cash / 1.001) / open), value at the final close, sell cost
0.10% + $0.01 deducted at the end.

Published record ($100 start): continuous $313.62 / validation $187.77.
"""
import os

from . import common

_ORIG = None
_PB = None


def _orig():
    global _ORIG
    if _ORIG is None:
        _ORIG = common.load_module(
            "spy_champ_orig",
            os.path.join(common.V4, "value-momentum-plainfloor.py"))
    return _ORIG


def _price_book(prices):
    global _PB
    champ = _orig()
    if prices is not None:
        # QA M-13/H-1: name the problem instead of IndexError / NaN finals.
        if not isinstance(prices, dict) or not prices.get("SPY"):
            raise ValueError("spy engine: no price data for SPY "
                             "(prices must be {'SPY': [{d, o, c}, ...]})")
        common.validate_price_series("SPY", prices["SPY"], engine="spy engine")
        return champ.PriceBook(prices)
    if _PB is None:
        _PB = champ.PriceBook({"SPY": champ.get_prices("SPY")})
    return _PB


def buy_and_hold(prices=None, start_cash=100.0, window="continuous",
                 start=None, end=None):
    champ = _orig()
    start_cash = common.validate_start_cash("spy engine", start_cash)
    pb = _price_book(prices)
    s, e, wname = common.resolve_window(window, start, end)
    # Daily close curve of the holding (pre-end-liquidation), for
    # charting against the strategy curves.
    days = [d for d in pb.dates if s <= d <= e]
    if not days:
        # R2-E5: a named error, not an IndexError on days[0].
        raise ValueError(f"spy engine: no trading days in window {s} to {e}")
    final, costs = champ.spy_net(pb, s, e, float(start_cash))
    o = pb.bar("SPY", days[0])["o"]
    sh = (float(start_cash) / 1.001) / o
    curve = [[d, sh * pb.close_on_or_before("SPY", d)] for d in days]
    return common.make_result(
        "spy", wname, s, e, start_cash, final, costs,
        [{"date": days[0], "ticker": "SPY", "side": "BUY", "shares": sh,
          "price": o, "value": sh * o, "cost": float(start_cash) - sh * o},
         {"date": days[-1], "ticker": "SPY", "side": "SELL-END",
          "shares": sh, "price": pb.close_on_or_before("SPY", days[-1]),
          "value": sh * pb.close_on_or_before("SPY", days[-1]),
          "cost": costs - (float(start_cash) - sh * o)}],
        None, curve)


# Common-interface alias.
def run(prices=None, fundamentals=None, start_cash=100.0, protection=None,
        window="continuous", start=None, end=None):
    r = buy_and_hold(prices=prices, start_cash=start_cash,
                     window=window, start=start, end=end)
    notes = []
    if protection is not None:
        # R2-E10: SPY is a buy-and-hold benchmark — a floor cannot apply.
        # Say so on the result instead of silently discarding the input.
        notes.append("protection has no effect on the SPY buy-and-hold "
                     "benchmark (no floor is applied to a shadow holding)")
    if fundamentals is not None:
        notes.append("fundamentals are ignored: the SPY benchmark needs none")
    if notes:
        r["warnings"] = notes
    return r
