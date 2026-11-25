#!/usr/bin/env python3
"""V13 Best-Rules Pragmatic AA: monthly single-portfolio, no lag, no tranche,
no stop-loss, no floor. Headline: momentum + 12m-MA trend guard, NO yield gate.
Variant G: + yield-curve gate. Variant T: no trend guard."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from engine import month_ends, aligned, yield_curve

RISK = ["ACWI", "QQQ", "EEM"]
DEF = ["IEF", "GLD", "BIL"]

def _me_prices(t, sd, n=13):
    a = aligned(t); mes = month_ends(end=sd)
    if len(mes) < n: return None
    vals = [a.loc[d] for d in mes[-n:]]
    if any(pd.isna(v) for v in vals): return None
    return vals

def _select(cands, sd, guard=True):
    scored = []
    for t in cands:
        vals = _me_prices(t, sd)
        if vals is None: continue
        chg = vals[-1] / vals[-13] - 1.0
        ma = sum(vals[-12:]) / 12.0
        if guard and not (vals[-1] > ma): continue
        scored.append((chg, t))
    scored.sort(reverse=True)
    return [t for _, t in scored[:2]]

def _yc_inverted(sd):
    yc = yield_curve()
    cand = yc.index[yc.index <= sd]
    if len(cand) == 0: return False
    return float(yc.loc[cand[-1]]) < 0

def make_target(use_gate=False, use_guard=True):
    def fn(date, rng=None):
        # signal at THIS month-end (date is a month-end when called by engine)
        sd = date
        sel = {}
        defensive_only = use_gate and _yc_inverted(sd)
        if not defensive_only:
            for t in _select(RISK, sd, guard=use_guard):
                sel[t] = 0.5
            rem = 1.0 - sum(sel.values())
            if rem > 1e-9:
                for t in _select(DEF, sd, guard=use_guard):
                    if t == "BIL": continue
                    sel[t] = sel.get(t, 0.0) + rem / 2.0
        else:
            for t in _select(DEF, sd, guard=use_guard):
                if t == "BIL": continue
                sel[t] = sel.get(t, 0.0) + 0.5
        return sel
    return fn

def static_mix(date, rng=None):
    return {"ACWI": 0.60, "IEF": 0.30, "GLD": 0.10}
