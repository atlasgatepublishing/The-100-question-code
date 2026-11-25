#!/usr/bin/env python3
"""V13 best-rules run: Novell Bond UI1 — published UNRATE-vs-12m-MA gate EXACT,
graded 50/50 defensive sizing, monthly, NO floor.
Chassis copied from v12 engine (costs 0.10%/side + $0.01/sell, month-end close,
macro lagged 1 month, current revised FRED vintage — fence printed in spec).
Data: this folder's data/ (Yahoo adjclose daily + FRED UNRATE csv)."""
import json, os, random
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

def price_at(t, date):
    a = aligned(t)
    if date not in a.index: return None
    v = a.loc[date]
    return None if pd.isna(v) else float(v)

# ---- macro: UNRATE monthly, current revised vintage (fence in spec) ----
_unrate = None
def unrate_monthly():
    global _unrate
    if _unrate is None:
        df = pd.read_csv(os.path.join(DATA, "UNRATE.csv")); df.columns = ["date", "val"]
        df["date"] = pd.to_datetime(df["date"]); df["val"] = pd.to_numeric(df["val"], errors="coerce")
        _unrate = df.dropna().set_index("date")["val"].resample("M").last().dropna()
    return _unrate

def _lag_idx(series_m, date, lag_months):
    target = (pd.Timestamp(date).to_period("M") - lag_months).to_timestamp("M").normalize()
    return series_m.index[series_m.index <= target + pd.Timedelta(days=1)]

def vs_ma12(series_m, date, lag_months=1):
    cand = _lag_idx(series_m, date, lag_months)
    if len(cand) == 0: return None, None
    v = float(series_m.loc[cand[-1]])
    m = float(series_m.loc[cand[-12:]].mean()) if len(cand) >= 12 else None
    return v, m

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

CREDIT = ["LQD", "HYG", "EMB"]; DEFENSIVE = ["IEF", "GLD"]
def _ew(tickers, date):
    elig = [t for t in tickers if price_at(t, date) is not None]
    return {t: 1.0 / len(elig) for t in elig} if elig else {}

def risk_off(date):
    v, m = vs_ma12(unrate_monthly(), date, 1)
    return v is not None and m is not None and v > m

def published(date, rng=None):
    """V12 constructed form, binary 100% switch."""
    return _ew(DEFENSIVE, date) if risk_off(date) else _ew(CREDIT, date)

def best_rules(date, rng=None):
    """V13: same gate/baskets; risk-off = 50% defensive + 50% credit."""
    if not risk_off(date): return _ew(CREDIT, date)
    w = {}
    for t, wt in _ew(DEFENSIVE, date).items(): w[t] = w.get(t, 0.0) + 0.5 * wt
    for t, wt in _ew(CREDIT, date).items(): w[t] = w.get(t, 0.0) + 0.5 * wt
    return w

def buyhold(t):
    return lambda date, rng=None: {t: 1.0}
def static_mix(date, rng=None):
    w = {}
    for t, wt in _ew(DEFENSIVE, date).items(): w[t] = w.get(t, 0.0) + 0.5 * wt
    for t, wt in _ew(CREDIT, date).items(): w[t] = w.get(t, 0.0) + 0.5 * wt
    return w

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def cal2022(eq):
    y = eq[(eq.index >= "2022-01-01") & (eq.index <= "2022-12-31")]
    if len(y) < 2: return None
    prev = eq[eq.index < "2022-01-01"]
    start = float(prev.iloc[-1]) if len(prev) else float(y.iloc[0])
    return round((float(y.iloc[-1]) / start - 1.0) * 100, 2)

def main():
    # decision stream for placebo shuffling + episode distribution
    mes_all = month_ends("2009-01-01", "2026-11-20")
    dec_best = {d: best_rules(d, None) for d in mes_all}
    off_flags = [risk_off(d) for d in mes_all]
    episodes = 0; run = False
    for f in off_flags:
        if f and not run: episodes += 1
        run = f
    gate_stats = {"months_total": len(mes_all), "months_risk_off": int(sum(off_flags)),
                  "share_risk_off": round(float(np.mean(off_flags)), 3), "episodes": episodes}
    out = {"family": "catalog-taa-novell-bond-ui1",
           "form": "v13-best-rules: published UNRATE>12mMA gate exact; risk-off graded 50% defensive/50% credit; monthly; no floor",
           "gate_stats_full_window": gate_stats, "roads": {}}
    for road, (st, en) in ROADS.items():
        res = {}
        eq, fin = simulate(st, en, best_rules)
        res["best_rules"] = {"final": round(fin, 2), "periods": period_stats(eq),
                             "cal2022_pct": cal2022(eq),
                             "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        eqp, finp = simulate(st, en, published)
        res["published_rerun"] = {"final": round(finp, 2), "periods": period_stats(eqp), "cal2022_pct": cal2022(eqp)}
        res["controls"] = {}
        for name, fn in (("AGG_buyhold", buyhold("AGG")), ("STATIC_MIX", static_mix), ("SPY_buyhold", buyhold("SPY"))):
            eqc, finc = simulate(st, en, fn)
            res["controls"][name] = {"final": round(finc, 2), "max_drawdown_pct": period_stats(eqc)["max_drawdown_pct"],
                                     "cal2022_pct": cal2022(eqc)}
        finals = []
        keys = list(dec_best.keys()); vals = [dec_best[k] for k in keys]
        for seed in range(20):
            rng = random.Random(1000 + seed)
            v = vals[:]; rng.shuffle(v)
            mp = dict(zip(keys, v))
            _, finpl = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}))
            finals.append(round(finpl, 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "finals": finals,
                          "best_rules_beats_of_20": int(sum(1 for f in finals if res["best_rules"]["final"] > f))}
        out["roads"][road] = res
        print(road, "best", res["best_rules"]["final"], "pub_rerun", res["published_rerun"]["final"],
              "placebo_med", res["placebo"]["median"], "beats", res["placebo"]["best_rules_beats_of_20"],
              "controls", {k: v["final"] for k, v in res["controls"].items()}, flush=True)
    print("gate_stats", gate_stats, flush=True)
    json.dump(out, open(os.path.join(BASE, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
