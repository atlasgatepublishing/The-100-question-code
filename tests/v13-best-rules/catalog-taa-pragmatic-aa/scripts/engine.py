#!/usr/bin/env python3
"""V13 engine — copied from v12 Slice-7 chassis, data resolved from this
folder's data/ only. Costs 0.10%/side + $0.01/sell. No house floor in v13
headline (spec decision); simulate() retained verbatim in behaviour."""
import json, os
import datetime as dt
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
COST_RATE = 0.001
SELL_FEE = 0.01

_cache = {}
def prices(ticker):
    if ticker in _cache: return _cache[ticker]
    d = json.load(open(os.path.join(DATA, f"{ticker}.json")))
    res = d["chart"]["result"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    dates = [dt.date.fromtimestamp(t) for t in res["timestamp"]]
    s = pd.Series(adj, index=pd.to_datetime(dates), dtype=float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    _cache[ticker] = s
    return s

CAL = None
def calendar():
    global CAL
    if CAL is None: CAL = prices("SPY").index
    return CAL

_al = {}
def aligned(ticker):
    if ticker in _al: return _al[ticker]
    s = prices(ticker)
    a = s.reindex(calendar()).ffill()
    a[calendar() < s.index[0]] = np.nan
    _al[ticker] = a
    return a

_ME = None
def month_ends(start=None, end=None):
    global _ME
    if _ME is None:
        cal = calendar()
        df = pd.DataFrame({"d": cal}); df["ym"] = df["d"].dt.to_period("M")
        _ME = df.groupby("ym")["d"].max().tolist()
    me = list(_ME)
    if start: me = [d for d in me if d >= pd.Timestamp(start)]
    if end: me = [d for d in me if d <= pd.Timestamp(end)]
    return me

_macro = {}
def macro(series):
    if series in _macro: return _macro[series]
    df = pd.read_csv(os.path.join(DATA, f"{series}.csv")); df.columns = ["date", "val"]
    df["date"] = pd.to_datetime(df["date"])
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    _macro[series] = df.dropna().set_index("date")["val"]
    return _macro[series]

_mm = {}
def yield_curve():
    if "yc" not in _mm:
        d10 = macro("DGS10").resample("M").last(); d3 = macro("DGS3MO").resample("M").last()
        idx = d10.index.intersection(d3.index)
        _mm["yc"] = (d10.loc[idx] - d3.loc[idx]).dropna()
    return _mm["yc"]

_ret_cache = {}
def _ret_array(ticker):
    if ticker in _ret_cache: return _ret_cache[ticker]
    a = aligned(ticker)
    r = (a / a.shift(1) - 1.0).fillna(0.0).to_numpy()
    _ret_cache[ticker] = r
    return r

def simulate(start, end, target_fn, rng=None):
    cal = calendar()
    pos = {d: i for i, d in enumerate(cal)}
    days = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    mes = set(month_ends(start, end))
    equity = 100.0; weights = {}; eq = {}
    for j, d in enumerate(days):
        if j > 0 and weights:
            gi = pos[d]; r = 0.0
            for t, w in weights.items():
                r += w * _ret_array(t)[gi]
            equity *= (1.0 + r)
        eq[d] = equity
        if d in mes or j == 0:
            tgt = target_fn(d, rng) or {}
            tgt = {t: w for t, w in tgt.items() if w > 1e-9}
            all_t = set(weights) | set(tgt)
            turnover = sum(abs(tgt.get(t, 0.0) - weights.get(t, 0.0)) for t in all_t)
            sells = len([t for t in all_t if tgt.get(t, 0.0) < weights.get(t, 0.0) - 1e-9])
            equity -= COST_RATE * turnover * equity + SELL_FEE * sells
            eq[d] = equity; weights = tgt
    s = pd.Series(eq).sort_index()
    return s, {"final": float(s.iloc[-1]) if len(s) else 100.0}

def period_stats(eq):
    m = eq.resample("M").last().dropna()
    rets = m.pct_change().dropna()
    if len(rets) == 0: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    hi_pos = [i for i in range(len(m)) if m.iloc[i] >= m.iloc[:i+1].max()]
    longest = 0; prev = 0
    for p in hi_pos: longest = max(longest, p - prev); prev = p
    longest = max(longest, len(m) - 1 - prev)
    dd = (m / m.cummax() - 1.0).min()
    # daily max drawdown too
    dd_d = (eq / eq.cummax() - 1.0).min()
    return {"n_periods": int(len(rets)), "share_positive": round(float((rets > 0).mean()), 3),
            "median_pct": round(float(rets.median()) * 100, 2), "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2), "mean_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak": int(streak), "longest_between_highs_months": int(longest),
            "max_drawdown_pct": round(float(dd_d) * 100, 1)}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
SPY_FINALS = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 385.56, "DECADE": 210.42, "CONT": 158.13, "VAL": 132.03}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
