#!/usr/bin/env python3
"""Shared TAA engine — Slice 7 catalog families.
Weight-based simulator: signals at month-end close, trades at that close
(AllocateSmartly convention). Costs: 0.10% of traded value + $0.01 per
sell order (program chassis standard). House form = v9: plain -15% floor
from episode start, breach at a daily close -> liquidate at that close,
90 calendar days cash, one restart, second halt ends the run in cash.
Data: family-local data/ first, then /tmp/slice7/data, then the read-only
v3 data_etf cache (SPY QQQ TLT IEF GLD DBC AGG UUP).
"""
import json, os, random
import datetime as dt
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
COST_RATE = 0.001
SELL_FEE = 0.01
V3 = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")

DATA13 = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-novell-bond-comp/data")
KELLER = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
def _find(ticker):
    for base in (DATA13, os.path.join(HERE, "data"), KELLER, V3):
        p = os.path.join(base, f"{ticker}.json")
        if os.path.exists(p): return p
    raise FileNotFoundError(ticker)

_cache = {}
def prices(ticker):
    if ticker in _cache: return _cache[ticker]
    d = json.load(open(_find(ticker)))
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

def ret_td(ticker, date, days):
    a = aligned(ticker)
    if date not in a.index: return None
    i = a.index.get_loc(date)
    if i - days < 0: return None
    p0, p1 = a.iloc[i - days], a.iloc[i]
    if pd.isna(p0) or pd.isna(p1) or p0 <= 0: return None
    return p1 / p0 - 1.0

def ret_months(ticker, date, months):
    a = aligned(ticker)
    mes = month_ends(end=date)
    if len(mes) <= months: return None
    d0 = mes[-1 - months]
    p0, p1 = a.loc[d0], a.loc[date]
    if pd.isna(p0) or pd.isna(p1) or p0 <= 0: return None
    return p1 / p0 - 1.0

def sma_td(ticker, date, days):
    a = aligned(ticker)
    if date not in a.index: return None
    i = a.index.get_loc(date)
    if i - days + 1 < 0: return None
    w = a.iloc[i - days + 1: i + 1]
    if w.isna().any(): return None
    return float(w.mean())

def price_at(ticker, date):
    a = aligned(ticker)
    if date not in a.index: return None
    v = a.loc[date]
    return None if pd.isna(v) else float(v)

# ---- macro (FRED current vintage; revised-data fence printed in specs) ----
_macro = {}
def _fred(series):
    for base in (DATA13, os.path.join(HERE, "data")):
        p = os.path.join(base, f"{series}.csv")
        if os.path.exists(p): return p
    raise FileNotFoundError(series)

def macro(series):
    if series in _macro: return _macro[series]
    df = pd.read_csv(_fred(series)); df.columns = ["date", "val"]
    df["date"] = pd.to_datetime(df["date"])
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    _macro[series] = df.dropna().set_index("date")["val"]
    return _macro[series]

_mm = {}
def macro_monthly(series):
    if series not in _mm: _mm[series] = macro(series).resample("M").last().dropna()
    return _mm[series]

def icsa_monthly():
    if "icsa" not in _mm: _mm["icsa"] = macro("ICSA").resample("M").mean().dropna()
    return _mm["icsa"]

def real_retail():
    if "rr" not in _mm:
        r = macro_monthly("RSAFS"); c = macro_monthly("CPIAUCSL")
        idx = r.index.intersection(c.index)
        _mm["rr"] = (r.loc[idx] / c.loc[idx] * 100.0)
    return _mm["rr"]

def real_pce():
    return macro_monthly("PCEC96")

def yield_curve():
    if "yc" not in _mm:
        d10 = macro("DGS10").resample("M").last(); d3 = macro("DGS3MO").resample("M").last()
        idx = d10.index.intersection(d3.index)
        _mm["yc"] = (d10.loc[idx] - d3.loc[idx]).dropna()
    return _mm["yc"]

def _lag_idx(series_m, date, lag_months):
    target = (pd.Timestamp(date).to_period("M") - lag_months).to_timestamp("M").normalize()
    cand = series_m.index[series_m.index <= target + pd.Timedelta(days=1)]
    return cand

def lagged(series_m, date, lag_months=1):
    cand = _lag_idx(series_m, date, lag_months)
    return None if len(cand) == 0 else float(series_m.loc[cand[-1]])

def ma12(series_m, date, lag_months=1):
    cand = _lag_idx(series_m, date, lag_months)
    return None if len(cand) < 12 else float(series_m.loc[cand[-12:]].mean())

def vs_ma12(series_m, date, lag_months=1):
    """(value, ma12) at lagged month."""
    v = lagged(series_m, date, lag_months); m = ma12(series_m, date, lag_months)
    return v, m

# ---- simulator ----
_ret_cache = {}
def _ret_array(ticker):
    if ticker in _ret_cache: return _ret_cache[ticker]
    a = aligned(ticker)
    r = (a / a.shift(1) - 1.0).fillna(0.0).to_numpy()
    _ret_cache[ticker] = r
    return r

def simulate(start, end, target_fn, house=False, rng=None, rebalance_months=1):
    cal = calendar()
    pos = {d: i for i, d in enumerate(cal)}
    days = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    all_me = month_ends(start, end)
    mes = set(all_me[::rebalance_months]) if rebalance_months > 1 else set(all_me)
    equity = 100.0; weights = {}; eq = {}
    ep_start = 100.0; halts = 0; halt_until = None; dead = False
    for j, d in enumerate(days):
        if j > 0 and weights:
            gi = pos[d]; r = 0.0
            for t, w in weights.items():
                r += w * _ret_array(t)[gi]
            equity *= (1.0 + r)
        eq[d] = equity
        if house and not dead and halt_until is None and equity <= 0.85 * ep_start:
            cost = COST_RATE * sum(weights.values()) * equity + SELL_FEE * len([w for w in weights.values() if w > 0])
            equity -= cost; eq[d] = equity; weights = {}; halts += 1
            if halts >= 2: dead = True
            else: halt_until = d + pd.Timedelta(days=90)
            continue
        if halt_until is not None:
            if d < halt_until: continue
            halt_until = None; ep_start = equity
        if (d in mes or j == 0) and not dead:
            tgt = target_fn(d, rng) or {}
            tgt = {t: w for t, w in tgt.items() if w > 1e-9}
            all_t = set(weights) | set(tgt)
            turnover = sum(abs(tgt.get(t, 0.0) - weights.get(t, 0.0)) for t in all_t)
            sells = len([t for t in all_t if tgt.get(t, 0.0) < weights.get(t, 0.0) - 1e-9])
            equity -= COST_RATE * turnover * equity + SELL_FEE * sells
            eq[d] = equity; weights = tgt
    s = pd.Series(eq).sort_index()
    return s, {"halts": halts, "final": float(s.iloc[-1]) if len(s) else 100.0}

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
    return {"n_periods": int(len(rets)), "share_positive": round(float((rets > 0).mean()), 3),
            "median_pct": round(float(rets.median()) * 100, 2), "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2), "mean_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak": int(streak), "longest_between_highs_months": int(longest),
            "max_drawdown_pct": round(float(dd) * 100, 1)}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
SPY_FINALS = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def run_roads(target_fn, placebo_fn=None, roads=("LONG", "DECADE", "CONT", "VAL")):
    out = {}
    for road in roads:
        st, en = ROADS[road]; res = {}
        for form, hf in (("native", False), ("house", True)):
            eq, info = simulate(st, en, target_fn, house=hf)
            res[form] = {"final": round(info["final"], 2), "halts": info["halts"], "periods": period_stats(eq)}
            if road == "CONT": res[form]["curve"] = {str(k.date()): round(float(v), 4) for k, v in eq.items()}
        if placebo_fn is not None:
            finals = []
            for seed in range(20):
                rng = random.Random(1000 + seed)
                eq, info = simulate(st, en, placebo_fn, house=False, rng=rng)
                finals.append(round(info["final"], 2))
            finals.sort()
            res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                              "native_beats_of_20": int(sum(1 for f in finals if res["native"]["final"] > f))}
        out[road] = res
    return out
