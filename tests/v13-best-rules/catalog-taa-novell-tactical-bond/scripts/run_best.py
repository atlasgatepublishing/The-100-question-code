#!/usr/bin/env python3
"""V13 best-rules run: Novell Tactical Bond, blended 3/6/12m momentum, top3,
published 6m>BIL gate, failed slots -> BIL, monthly, NO floor.
Chassis copied from v12 engine (costs 0.10%/side + $0.01/sell, month-end close).
Data: this folder's data/ (Yahoo adjclose daily, fetched fresh for this run)."""
import json, os, random, sys
import datetime as dt
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DATA = os.path.join(BASE, "data")
COST_RATE, SELL_FEE = 0.001, 0.01

_cache = {}
def prices(t):
    if t in _cache: return _cache[t]
    d = json.load(open(os.path.join(DATA, f"{t}.json")))
    res = d["chart"]["result"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    dates = [dt.date.fromtimestamp(x) for x in res["timestamp"]]
    s = pd.Series(adj, index=pd.to_datetime(dates), dtype=float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    _cache[t] = s
    return s

CAL = None
def calendar():
    global CAL
    if CAL is None: CAL = prices("SPY").index
    return CAL

_al = {}
def aligned(t):
    if t not in _al:
        s = prices(t); a = s.reindex(calendar()).ffill()
        a[calendar() < s.index[0]] = np.nan
        _al[t] = a
    return _al[t]

_ME = None
def month_ends(start=None, end=None):
    global _ME
    if _ME is None:
        cal = calendar(); df = pd.DataFrame({"d": cal}); df["ym"] = df["d"].dt.to_period("M")
        _ME = df.groupby("ym")["d"].max().tolist()
    me = list(_ME)
    if start: me = [d for d in me if d >= pd.Timestamp(start)]
    if end: me = [d for d in me if d <= pd.Timestamp(end)]
    return me

def ret_months(t, date, months):
    a = aligned(t); mes = month_ends(end=date)
    if len(mes) <= months: return None
    d0 = mes[-1 - months]; p0, p1 = a.loc[d0], a.loc[date]
    if pd.isna(p0) or pd.isna(p1) or p0 <= 0: return None
    return p1 / p0 - 1.0

_ret = {}
def ret_array(t):
    if t not in _ret:
        a = aligned(t); _ret[t] = (a / a.shift(1) - 1.0).fillna(0.0).to_numpy()
    return _ret[t]

def simulate(start, end, target_fn, rng=None):
    cal = calendar(); pos = {d: i for i, d in enumerate(cal)}
    days = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    mes = set(month_ends(start, end))
    equity = 100.0; weights = {}; eq = {}
    for j, d in enumerate(days):
        if j > 0 and weights:
            gi = pos[d]; r = sum(w * ret_array(t)[gi] for t, w in weights.items())
            equity *= (1.0 + r)
        eq[d] = equity
        if d in mes or j == 0:
            tgt = {t: w for t, w in (target_fn(d, rng) or {}).items() if w > 1e-9}
            all_t = set(weights) | set(tgt)
            turnover = sum(abs(tgt.get(t, 0.0) - weights.get(t, 0.0)) for t in all_t)
            sells = len([t for t in all_t if tgt.get(t, 0.0) < weights.get(t, 0.0) - 1e-9])
            equity -= COST_RATE * turnover * equity + SELL_FEE * sells
            eq[d] = equity; weights = tgt
    s = pd.Series(eq).sort_index()
    return s, float(s.iloc[-1])

def period_stats(eq):
    m = eq.resample("M").last().dropna(); rets = m.pct_change().dropna()
    if len(rets) == 0: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    hi = [i for i in range(len(m)) if m.iloc[i] >= m.iloc[:i+1].max()]
    longest = 0; prev = 0
    for p in hi: longest = max(longest, p - prev); prev = p
    longest = max(longest, len(m) - 1 - prev)
    dd = (eq / eq.cummax() - 1.0).min()
    return {"n_periods": int(len(rets)), "share_positive": round(float((rets > 0).mean()), 3),
            "median_pct": round(float(rets.median()) * 100, 2), "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2), "mean_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak": int(streak), "longest_between_highs_months": int(longest),
            "max_drawdown_pct": round(float(dd) * 100, 1)}

U = ["SHY", "IEF", "TLT", "TIP", "LQD", "HYG", "BNDX", "EMB"]

def blended(date):
    out = {}
    for t in U:
        rs = [ret_months(t, date, k) for k in (3, 6, 12)]
        if all(r is not None for r in rs): out[t] = sum(rs) / 3.0
    return out

def best_rules(date, rng=None):
    s = blended(date); bil6 = ret_months("BIL", date, 6)
    if not s or bil6 is None: return {"BIL": 1.0}
    top = sorted(s, key=s.get, reverse=True)[:3]
    w = {}
    for t in top:
        r6 = ret_months(t, date, 6)
        if r6 is not None and r6 > 0 and r6 > bil6: w[t] = 1.0 / 3.0
    w["BIL"] = w.get("BIL", 0.0) + (1.0 - sum(w.values()))
    return w

def best_placebo(date, rng=None):
    s = blended(date); bil6 = ret_months("BIL", date, 6)
    if not s or bil6 is None: return {"BIL": 1.0}
    picks = rng.sample(sorted(s), min(3, len(s)))
    w = {}
    for t in picks:
        r6 = ret_months(t, date, 6)
        if r6 is not None and r6 > 0 and r6 > bil6: w[t] = 1.0 / 3.0
    w["BIL"] = w.get("BIL", 0.0) + (1.0 - sum(w.values()))
    return w

def published(date, rng=None):
    """V12 published form re-run on this data for an apples-to-apples line."""
    s = {}
    for t in U:
        r = ret_months(t, date, 6)
        if r is not None: s[t] = r
    bil = ret_months("BIL", date, 6)
    if not s or bil is None: return {}
    top = sorted(s, key=s.get, reverse=True)[:3]
    return {t: 1.0/3.0 for t in top if s[t] > 0 and s[t] > bil}

def buyhold(t):
    return lambda date, rng=None: {t: 1.0}
def static_mix(date, rng=None):
    elig = [t for t in U if ret_months(t, date, 1) is not None]
    return {t: 1.0/len(elig) for t in elig} if elig else {}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CONTROLS = {"SPY": buyhold("SPY"), "AGG": buyhold("AGG"), "IEF": buyhold("IEF"),
            "BIL": buyhold("BIL"), "STATIC_MIX": static_mix}

def main():
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        eq, fin = simulate(st, en, best_rules)
        res["best_rules"] = {"final": round(fin, 2), "periods": period_stats(eq),
                             "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        eq, fin = simulate(st, en, published)
        res["published_rerun"] = {"final": round(fin, 2), "periods": period_stats(eq)}
        res["controls"] = {}
        for name, fn in CONTROLS.items():
            eq, fin = simulate(st, en, fn)
            res["controls"][name] = {"final": round(fin, 2), "max_drawdown_pct": period_stats(eq)["max_drawdown_pct"]}
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            _, fin = simulate(st, en, best_placebo, rng=rng)
            finals.append(round(fin, 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "finals": finals,
                          "best_rules_beats_of_20": int(sum(1 for f in finals if res["best_rules"]["final"] > f))}
        out[road] = res
        print(road, "best", res["best_rules"]["final"], "pub_rerun", res["published_rerun"]["final"],
              "placebo_med", res["placebo"]["median"], "beats", res["placebo"]["best_rules_beats_of_20"],
              "controls", {k: v["final"] for k, v in res["controls"].items()}, flush=True)
    json.dump(out, open(os.path.join(BASE, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
