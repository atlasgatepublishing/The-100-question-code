#!/usr/bin/env python3
"""V13 best-rules run — Movement Capital Composite.
Best-rules form (frozen in BEST-RULES-SPEC.md): published trend sleeve 25%
verbatim + passive stocks 50% (incl. folded macro weight) + passive bonds 25%,
monthly month-end close, NO floor. Benchmarks: static mix 25/25/25/25 and
SPY buy-hold (same plumbing). Placebo: 20-seed shuffled-decision timing twins.
Costs: 0.10% of traded value per side + $0.01 per sell order (program standard).
Prices: Yahoo chart adjclose JSON in ../data (read-only caches + SHV download).
"""
import json, os, random, sys
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

def ret_months(ticker, date, months):
    a = aligned(ticker)
    mes = month_ends(end=date)
    if len(mes) <= months: return None
    d0 = mes[-1 - months]
    p0, p1 = a.loc[d0], a.loc[date]
    if pd.isna(p0) or pd.isna(p1) or p0 <= 0: return None
    return p1 / p0 - 1.0

# ---------- signals ----------
def _mom(t, date):
    rs = [ret_months(t, date, k) for k in (3, 6, 9, 12, 15)]
    return None if any(r is None for r in rs) else sum(rs) / len(rs)

def trend_pick(date):
    ms, me, mshv = _mom("SPY", date), _mom("EFA", date), _mom("SHV", date)
    if ms is None or me is None or mshv is None: return None
    winner = "SPY" if ms >= me else "EFA"
    return winner if max(ms, me) > mshv else "IEF"

def best_rules(date, rng=None):
    w = {"SPY": 0.25, "EFA": 0.25, "IEF": 0.125, "TIP": 0.125}  # passive stocks 50% + bonds 25%
    pick = trend_pick(date)
    if pick is not None: w[pick] = w.get(pick, 0.0) + 0.25
    return w

def static_mix(date, rng=None):
    return {"SPY": 0.25, "EFA": 0.25, "IEF": 0.25, "TIP": 0.25}

def spy_only(date, rng=None):
    return {"SPY": 1.0}

# ---------- simulator (v12 chassis, no floor in any v13 form) ----------
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
            for t, w in weights.items(): r += w * _ret_array(t)[gi]
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
    return s, float(s.iloc[-1]) if len(s) else 100.0

def period_stats(eq):
    m = eq.resample("M").last().dropna()
    rets = m.pct_change().dropna()
    if len(rets) == 0: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    hi_pos = [i for i in range(len(m)) if m.iloc[i] >= m.iloc[:i + 1].max()]
    longest = 0; prev = 0
    for p in hi_pos: longest = max(longest, p - prev); prev = p
    longest = max(longest, len(m) - 1 - prev)
    dd = (eq / eq.cummax() - 1.0).min()
    return {"n_periods": int(len(rets)), "share_positive": round(float((rets > 0).mean()), 3),
            "median_pct": round(float(rets.median()) * 100, 2), "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2), "mean_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak": int(streak), "longest_between_highs_months": int(longest),
            "max_drawdown_pct": round(float(dd) * 100, 1)}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def main():
    # precompute best-rules decisions for the shuffled placebo
    mes_all = month_ends("2009-01-01", "2026-11-20")
    dec = {d: best_rules(d, None) for d in mes_all}
    keys = list(dec.keys()); vals = [dec[k] for k in keys]
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        for name, fn in (("best_rules", best_rules), ("static_mix", static_mix), ("spy_plumbing", spy_only)):
            eq, final = simulate(st, en, fn)
            res[name] = {"final": round(final, 2), "periods": period_stats(eq)}
            if road in ("CONT", "LONG"):
                res[name]["curve"] = {str(k.date()): round(float(v), 4) for k, v in eq.items()}
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            v = vals[:]; rng.shuffle(v)
            mp = dict(zip(keys, v))
            eq, final = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}))
            finals.append(round(final, 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "best_rules_beats_of_20": int(sum(1 for f in finals if res["best_rules"]["final"] > f)),
                          "all_finals": finals}
        out[road] = res
        print(road, "best", res["best_rules"]["final"], "static", res["static_mix"]["final"],
              "spy_plumb", res["spy_plumbing"]["final"], "placebo_med", res["placebo"]["median"],
              "beats", res["placebo"]["best_rules_beats_of_20"], flush=True)
    path = os.path.join(HERE, "..", "results.json")
    json.dump(out, open(path, "w"), indent=1)
    print("WROTE", path)

if __name__ == "__main__":
    main()
