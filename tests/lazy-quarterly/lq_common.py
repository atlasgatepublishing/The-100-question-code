#!/usr/bin/env python3
"""
LAZY PRICES QUARTERLY (LQ) — shared plumbing. Simulation only.

Reuses the long-run-2010 test's plumbing verbatim (lr_common /
lr_engines: point-in-time ponds, era 10-K similarity signals, the v9
protection wrapper) and the original promoted gap-a5 Lazy Prices
module (imported, never modified). Nothing is retuned anywhere.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

END = C.END
GAPA5 = os.path.join(C.V7, "gap-a5-lazy-prices")

WINDOWS = {
    "long": ("2010-01-04", END),
    "continuous": ("2019-01-02", END),
    "validation": ("2023-01-03", END),
}


def lazy_module():
    return C.load_module("lazy_lq", os.path.join(GAPA5, "lazy-prices.py"))


def gap_book():
    """The published 2019-2026 setup: Nov-2016 pond (the module's
    UNIVERSE), the module's own PriceBook on the champion's shared
    price cache, and the cached gap-a5 similarity signals."""
    lazy = lazy_module()
    with open(os.path.join(GAPA5, "data", "similarities.json")) as f:
        sims = json.load(f)["signals"]
    bars = {t: lazy.get_prices(t) for t in lazy.UNIVERSE + ["SPY"]}
    return lazy, lazy.PriceBook(bars), sims


def era_signals():
    """Era (2007-fetched) 10-K similarity signals for the 2010 pond,
    built by the long-run test — read-only."""
    with open(os.path.join(C.MYDATA, "lazy", "similarities_era.json")) as f:
        return json.load(f)["signals"]


def pond2010():
    """The 2010 point-in-time pond exactly as the long-run test built
    and published it."""
    with open(os.path.join(LR, "results_lazy.json")) as f:
        return json.load(f)["pond"]


def spec_selection_dates(pb, start, end):
    """The LQ frozen spec's calendar, implemented from the words of
    the spec alone: the first trading day of each calendar quarter
    (Jan/Apr/Jul/Oct) inside the window."""
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out
