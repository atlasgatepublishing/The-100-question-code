#!/usr/bin/env python3
"""V13 Best Rules — catalog-taa-keller-laa (Keller LAA).
Rules per BEST-RULES-SPEC.md (frozen before this run):
  LAA: QQQ/IWM/GLD 25% permanent + 25% timed sleeve (SPY if SPY close >
  210-trading-day mean of SPY closes incl. today, else IEF). Monthly
  month-end check, next-day execution, NO floor/halt. Program costs
  0.10%/side + $0.01/sell order, fractional shares, $100 pots.
Controls on identical chassis: static mix (timed sleeve permanently SPY),
buy-and-hold SPY, 20-seed random-twin placebos.
Data: v12 shared ETF cache (read-only), adjusted Yahoo closes, PIT only.
"""
import json, os, random, statistics, sys
import numpy as np
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
TICKS = ["SPY", "QQQ", "IWM", "GLD", "IEF"]

def load(t):
    d = json.load(open(os.path.join(CACHE, t + ".json")))["chart"]["result"][0]
    ts = d["timestamp"]; q = d["indicators"]["quote"][0]
    adj = d["indicators"].get("adjclose", [{}])[0].get("adjclose")
    out = {}
    for i, x in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        dt = datetime.fromtimestamp(x, tz=timezone.utc).strftime("%Y-%m-%d")
        out[dt] = adj[i] if adj and adj[i] else c
    return out

RAW = {t: load(t) for t in TICKS}
CAL = sorted(RAW["SPY"].keys())
N = len(CAL)
ARR = {}
for t in TICKS:
    a = np.full(N, np.nan); last = np.nan
    for i, d in enumerate(CAL):
        if d in RAW[t]:
            last = RAW[t][d]
        a[i] = last
    ARR[t] = a

COST = 0.0010
SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-01-01", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}

def eval_indices_monthly(start, end):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    idx = [i for i in range(si, ei + 1) if i == ei or CAL[i + 1][:7] != CAL[i][:7]]
    return si, ei, idx

def run(wfun, road, seed=None):
    start, end = ROADS[road]
    si, ei, evals = eval_indices_monthly(start, end)
    evalset = set(evals)
    rng = random.Random(seed) if seed is not None else None
    cash = 100.0; shares = {}; costs = 0.0; fees = 0.0; orders = 0; eq = []
    def value(i):
        v = cash
        for t, sh in shares.items():
            if sh > 0 and not np.isnan(ARR[t][i]):
                v += sh * ARR[t][i]
        return v
    pending = None
    for i in range(si, ei + 1):
        if pending is not None and i == pending[0]:
            target = pending[1]; cur = value(i)
            # Cost semantics replicate the v12 shared engine exactly (its
            # as-run code deducts 0.10%/side on turnover; the $0.01 sell
            # fee named in the v12 spec text was not deducted by that
            # engine). Identical chassis = published finals are directly
            # comparable, which the verdict depends on.
            for t in list(shares.keys()):
                if t not in target:
                    p = ARR[t][i]
                    if shares[t] > 0 and not np.isnan(p):
                        cash += shares[t] * p * (1 - COST)
                        costs += shares[t] * p * COST; orders += 1
                    shares[t] = 0.0
            for t, w in target.items():
                p = ARR[t][i]
                if np.isnan(p) or p <= 0:
                    continue
                want = w * cur; have = shares.get(t, 0.0) * p; dv = want - have
                if abs(dv) < 0.25:
                    continue
                c = abs(dv) * COST; costs += c; orders += 1
                cash -= dv + c
                shares[t] = shares.get(t, 0.0) + dv / p
            pending = None
        eq.append((CAL[i], round(value(i), 4)))
        if i in evalset and i < ei:
            tgt = wfun(i, rng) if rng is not None else wfun(i)
            if tgt is not None:
                pending = (i + 1, tgt)
    final = eq[-1][1] if eq else cash
    peak = -1; mdd = 0.0
    for _, v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1 if peak > 0 else 0)
    return {"final": round(final, 2), "maxDD": round(mdd * 100, 2),
            "costs": round(costs, 2), "sell_fees": round(fees, 2),
            "orders": orders, "equity": eq}

def run_spy_buyhold(road):
    start, end = ROADS[road]
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    p0 = ARR["SPY"][si]
    sh = (100.0 * (1 - COST)) / p0
    eq = [(CAL[i], round(sh * ARR["SPY"][i], 4)) for i in range(si, ei + 1)]
    peak = -1; mdd = 0.0
    for _, v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1 if peak > 0 else 0)
    return {"final": round(eq[-1][1], 2), "maxDD": round(mdd * 100, 2),
            "costs": round(100.0 * COST, 2), "orders": 1, "equity": eq}

def w_laa(i):
    sma = np.nanmean(ARR["SPY"][i - 210:i + 1])
    timed = "SPY" if ARR["SPY"][i] > sma else "IEF"
    return {"QQQ": 0.25, "IWM": 0.25, "GLD": 0.25, timed: 0.25}

def w_static(i):
    return {"QQQ": 0.25, "IWM": 0.25, "GLD": 0.25, "SPY": 0.25}

UNIVERSE = ["SPY", "QQQ", "IWM", "GLD"]
def w_placebo(i, rng):
    picks = rng.sample(UNIVERSE, 2)
    return {t: 0.5 for t in picks}

def period_stats(eq):
    pts = {}
    for d, v in eq:
        pts[d[:7]] = v
    keys = sorted(pts)
    rets = [pts[b] / pts[a] - 1 for a, b in zip(keys, keys[1:])]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    streak = 0; mx = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0; mx = max(mx, streak)
    peak = -1; last = 0; mxnh = 0
    for kix, k in enumerate(keys):
        if pts[k] >= peak:
            peak = pts[k]; last = kix
        mxnh = max(mxnh, kix - last)
    return {"periods": len(rets), "share_pos": round(100 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "avg_pct": round(statistics.mean(rets) * 100, 2),
            "longest_losing_streak": mx,
            "longest_no_new_high_periods": mxnh}

def main():
    res = {"family": "catalog-taa-keller-laa", "program": "v13-best-rules",
           "champion_vm": CHAMP, "spy_reference": SPY_REF, "roads": {}}
    for road in ROADS:
        laa = run(w_laa, road)
        sta = run(w_static, road)
        spy = run_spy_buyhold(road)
        pf = [run(w_placebo, road, seed=1000 + s)["final"] for s in range(20)]
        res["roads"][road] = {
            "laa": laa, "static_control": sta, "spy_buyhold": spy,
            "guard_contribution_vs_static": round(laa["final"] - sta["final"], 2),
            "guard_dd_relief_vs_static_pp": round(sta["maxDD"] - laa["maxDD"], 2),
            "placebo_finals": pf,
            "placebos_beaten": sum(1 for f in pf if laa["final"] > f),
            "period_distribution_laa_monthly": period_stats(laa["equity"]),
            "period_distribution_static_monthly": period_stats(sta["equity"]),
            "beats_champion": bool(laa["final"] > CHAMP[road]),
        }
        print(road, "LAA", laa["final"], "DD", laa["maxDD"],
              "| static", sta["final"], "DD", sta["maxDD"],
              "| SPY", spy["final"], "(ref", SPY_REF[road], ")",
              "| placebos beaten", res["roads"][road]["placebos_beaten"], "/20",
              "| guard $", res["roads"][road]["guard_contribution_vs_static"],
              flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
