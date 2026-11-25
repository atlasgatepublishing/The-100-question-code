#!/usr/bin/env python3
"""Pragmatic Asset Allocation (Vojtko & Javorska / Quantpedia), AllocateSmartly
published form. 4 tranches, each trades ANNUALLY in its stagger month
(Jan/Apr/Jul/Oct), signal from previous month-end. Yield-curve gate
(inverted -> defensive selection). Risk: top-2 of ACWI/QQQ/EEM by 12m price
change that closed above their 12m MA, 50% of tranche each; unfilled ->
defensive selection: top-2 of IEF/GLD/BIL by 12m change above MA (BIL->cash).
Stop-loss at each tranche-trade month for the OTHER tranches: asset held
>12 months and prev month-end close below its 12m MA -> cash until that
tranche trades again. Portfolio target = equal 25% tranches (monthly
rebalance to tranche weights, per AS/authors' simplifying assumption)."""
import sys
sys.path.insert(0, "/tmp/slice7")
import pandas as pd
from engine import month_ends, price_at, aligned, yield_curve

RISK = ["ACWI", "QQQ", "EEM"]
DEF = ["IEF", "GLD", "BIL"]
TRANCHE_MONTH = {0: 1, 1: 4, 2: 7, 3: 10}

def _me_prices(t, sd, n=13):
    a = aligned(t); mes = month_ends(end=sd)
    if len(mes) < n: return None
    vals = [a.loc[d] for d in mes[-n:]]
    if any(pd.isna(v) for v in vals): return None
    return vals

def _select(cands, sd):
    """Return up to 2 tickers: ranked by 12m change desc, must be above 12m MA."""
    scored = []
    for t in cands:
        vals = _me_prices(t, sd)
        if vals is None: continue
        chg = vals[-1] / vals[0] - 1.0 if False else vals[-1] / vals[-13] - 1.0 if len(vals) >= 13 else None
        if chg is None: continue
        ma = sum(vals[-12:]) / 12.0
        if vals[-1] > ma: scored.append((chg, t))
    scored.sort(reverse=True)
    return [t for _, t in scored[:2]]

def _yc_inverted(sd):
    yc = yield_curve()
    cand = yc.index[yc.index <= sd]
    if len(cand) == 0: return False
    return float(yc.loc[cand[-1]]) < 0

class Pragmatic:
    def __init__(self):
        self.tranches = [dict() for _ in range(4)]       # ticker -> weight within tranche
        self.entry = [dict() for _ in range(4)]          # ticker -> (year, month) entered
        self.started = [False] * 4
    def _trade_tranche(self, k, date, sd):
        sel = {}
        if not _yc_inverted(sd):
            picks = _select(RISK, sd)
            for t in picks: sel[t] = 0.5
            rem = 1.0 - sum(sel.values())
            if rem > 1e-9:
                dpicks = _select(DEF, sd)
                for t in dpicks:
                    if t == "BIL": continue
                    sel[t] = sel.get(t, 0.0) + rem / 2.0
        else:
            dpicks = _select(DEF, sd)
            for t in dpicks:
                if t == "BIL": continue
                sel[t] = sel.get(t, 0.0) + 0.5
        ym = (date.year, date.month)
        new_entry = {}
        for t in sel:
            new_entry[t] = self.entry[k].get(t, ym)
        self.tranches[k] = sel; self.entry[k] = new_entry; self.started[k] = True
    def _stop_loss(self, k, date, sd):
        ym = (date.year, date.month)
        for t in list(self.tranches[k]):
            e = self.entry[k].get(t)
            if e is None: continue
            held_months = (ym[0] - e[0]) * 12 + (ym[1] - e[1])
            if held_months <= 12: continue
            vals = _me_prices(t, sd)
            if vals is None: continue
            ma = sum(vals[-12:]) / 12.0
            if vals[-1] < ma:
                del self.tranches[k][t]; del self.entry[k][t]
    def __call__(self, date, rng=None):
        mes = month_ends(end=date)
        if len(mes) < 2: return {}
        sd = mes[-2]
        m = date.month
        current = [k for k in range(4) if TRANCHE_MONTH[k] == m]
        for k in current:
            for j in range(4):
                if j != k and self.started[j]: self._stop_loss(j, date, sd)
            self._trade_tranche(k, date, sd)
        w = {}
        for k in range(4):
            for t, tw in self.tranches[k].items():
                w[t] = w.get(t, 0.0) + 0.25 * tw
        return w

def make_pragmatic():
    return Pragmatic()
