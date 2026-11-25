#!/usr/bin/env python3
"""V13 BEST-RULES RUN — Donchian Weekly Rule, Claude-designed construction.
Frozen spec: BEST-RULES-SPEC.md in this folder. Summary:
- Signal verbatim published: weekly eval; close breaks prior 4 full calendar
  weeks' high/low (dividend/split-adjusted OHLC) -> long / short state; persists.
- Universe: 19 cross-asset ETFs (futures-book analogue), all trading pre-2009.
- Allocation: fixed independent slices — buy equity/19 on flip to long, sell all
  on flip to short-state; no redistribution, no rebalancing between flips.
- Long-only adaptation (short state = cash), labeled. NO pot floor.
- Costs: 0.10%/side + $0.01 per sell order. $100 pots.
- Placebos: per-market circular state shifts, 20 seeds, all roads.
Data (public, cached in ./data): Yahoo daily chart payloads fetched 2026-11-22.
"""
import json, os, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SHELF = ["SPY","QQQ","DIA","IWM","EFA","EEM","VNQ","TLT","IEF","AGG","TIP",
         "LQD","HYG","GLD","SLV","DBC","DBA","USO","UUP"]
N = len(SHELF)
COST = 0.001
SELL_FEE = 0.01
END = "2026-11-20"
ROADS = {"LONG": ("2010-01-04", END), "DECADE": ("2016-11-21", END),
         "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END)}

def load(t):
    d = json.load(open(os.path.join(HERE, "data", f"{t}.json")))
    r = d["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, tsec in enumerate(ts):
        c = q["close"][i]
        if c is None or adj[i] is None: continue
        f = adj[i] / c
        bars.append({"d": date.fromtimestamp(tsec).isoformat(),
                     "h": q["high"][i] * f, "l": q["low"][i] * f, "c": adj[i]})
    return bars

BARS = {t: load(t) for t in SHELF}
DIDX = {t: {b["d"]: i for i, b in enumerate(b)} for t, b in BARS.items()}
DATES = [b["d"] for b in BARS["SPY"]]

def weekly_state(bars):
    """state[i] for each bar index: 1 long, 0 short-state; decided at week ends."""
    weeks = {}
    for i, b in enumerate(bars):
        y, w, _ = date.fromisoformat(b["d"]).isocalendar()
        weeks.setdefault((y, w), []).append(i)
    wk = sorted(weeks)
    state = [0] * len(bars); cur = 0
    for wi, k in enumerate(wk):
        idxs = weeks[k]
        for i in idxs: state[i] = cur
        if wi >= 4:
            prev = [weeks[wk[j]] for j in range(wi - 4, wi)]
            hi = max(bars[i]["h"] for g in prev for i in g)
            lo = min(bars[i]["l"] for g in prev for i in g)
            c = bars[idxs[-1]]["c"]
            if c > hi: cur = 1
            elif c < lo: cur = 0
            state[idxs[-1]] = cur
    return state

STATES = {t: weekly_state(BARS[t]) for t in SHELF}
# eval days: last SPY trading day of each ISO week (global calendar)
EVAL = set()
_seen = {}
for d in DATES:
    y, w, _ = date.fromisoformat(d).isocalendar()
    _seen[(y, w)] = d
EVAL = set(_seen.values())

def run(states, start, end):
    cash = 100.0; pos = {}   # t -> {sh, basis}
    curve = []; trades = 0; costs = 0.0; closed = []
    prev_close = {}
    def price(t, d):
        i = DIDX[t].get(d)
        return BARS[t][i]["c"] if i is not None else prev_close.get(t)
    def equity(d):
        tot = cash
        for t, p in pos.items():
            c = price(t, d)
            if c: tot += p["sh"] * c
        return tot
    started = False
    for d in DATES:
        if d < start or d > end: continue
        for t in list(pos): 
            c = price(t, d)
            if c: prev_close[t] = c
        if not started:
            started = True
            # enter slices for markets already long at road start, at this close
            eq = cash
            for t in SHELF:
                i = DIDX[t].get(d)
                if i is not None and states[t][i] == 1:
                    amt = eq / N; cst = amt * COST
                    pos[t] = {"sh": (amt - cst) / BARS[t][i]["c"], "basis": amt}
                    cash -= amt; trades += 1; costs += cst
            curve.append((d, round(equity(d), 4))); continue
        if d in EVAL:
            # sells first
            for t in list(pos):
                i = DIDX[t].get(d)
                if i is not None and states[t][i] == 0:
                    c = BARS[t][i]["c"]; gross = pos[t]["sh"] * c
                    cst = gross * COST + SELL_FEE
                    cash += gross - cst; trades += 1; costs += cst
                    closed.append(gross - cst - pos[t]["basis"])
                    del pos[t]
            # buys
            eq = equity(d)
            for t in SHELF:
                if t in pos: continue
                i = DIDX[t].get(d)
                if i is not None and states[t][i] == 1:
                    amt = min(eq / N, cash)
                    if amt <= 0: continue
                    cst = amt * COST
                    pos[t] = {"sh": (amt - cst) / BARS[t][i]["c"], "basis": amt}
                    cash -= amt; trades += 1; costs += cst
        curve.append((d, round(equity(d), 4)))
    # liquidate at end for final (with costs), curve last point = post-cost
    if pos:
        d = curve[-1][0]; tot = cash
        for t, p in pos.items():
            c = price(t, d); gross = p["sh"] * c
            tot += gross - gross * COST - SELL_FEE
            costs += gross * COST + SELL_FEE
        curve[-1] = (d, round(tot, 4))
    return {"final": curve[-1][1], "curve": curve, "trades": trades,
            "costs": round(costs, 2), "closed_pnl": closed}

def max_dd(curve):
    peak = -1e18; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return round(mdd * 100, 1)

def period_stats(curve):
    wk = {}
    for d, v in curve:
        y, w, _ = date.fromisoformat(d).isocalendar()
        wk[(y, w)] = v
    vals = [wk[k] for k in sorted(wk)]
    rets = [vals[i] / vals[i-1] - 1 for i in range(1, len(vals))]
    if not rets: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = mx = 0
    for v in vals:
        if v >= peak: peak = v; mx = max(mx, since); since = 0
        else: since += 1
    mx = max(mx, since)
    return {"periods": len(rets), "median_pct": round(statistics.median(rets) * 100, 2),
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak": streak, "longest_stretch_between_highs_periods": mx,
            "mean_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def buyhold(t, start, end):
    bars = [b for b in BARS[t] if start <= b["d"] <= end]
    amt = 100.0 * (1 - COST)
    sh = amt / bars[0]["c"]
    final = sh * bars[-1]["c"] * (1 - COST) - SELL_FEE
    curve = [(b["d"], round(sh * b["c"], 4)) for b in bars]
    return {"final": round(final, 2), "maxdd_pct": max_dd(curve)}

def main():
    res = {"family": "hunt-donchian-weekly-rule", "form": "v13 best rules: verbatim weekly signal, 19-market cross-asset shelf, fixed independent slices (eq/19), long-only adaptation, no floor",
           "shelf": SHELF, "roads": {}}
    for road, (s, e) in ROADS.items():
        r = run(STATES, s, e)
        cl = r.pop("closed_pnl")
        wins = [x for x in cl if x > 0]; losses = [x for x in cl if x <= 0]
        r["periods_weekly"] = period_stats(r["curve"])
        r["maxdd_pct"] = max_dd(r["curve"])
        r["expectancy"] = {"closed_trades": len(cl),
            "win_rate_pct": round(100 * len(wins) / len(cl), 1) if cl else None,
            "avg_win": round(statistics.mean(wins), 2) if wins else None,
            "avg_loss": round(statistics.mean(losses), 2) if losses else None,
            "expectancy_per_trade": round(statistics.mean(cl), 2) if cl else None}
        r["spy_buyhold"] = buyhold("SPY", s, e)
        res["roads"][road] = r
        print(road, r["final"], "dd", r["maxdd_pct"], "trades", r["trades"], "costs", r["costs"])
    # placebos: per-market circular shifts of daily state arrays
    pl = {}
    for road, (s, e) in ROADS.items():
        finals = []
        n_by = {t: len(STATES[t]) for t in SHELF}
        for seed in range(1, 21):
            rng = random.Random(seed * 7919 + len(road))
            sh_states = {}
            for t in SHELF:
                n = n_by[t]; off = rng.randrange(50, n - 50)
                a = STATES[t]; sh_states[t] = a[-off:] + a[:-off]
            finals.append(run(sh_states, s, e)["final"])
        pl[road] = {"median": round(statistics.median(finals), 2),
                    "n_beaten_by_real": sum(1 for f in finals if res["roads"][road]["final"] > f),
                    "finals": [round(f, 2) for f in finals]}
        print("placebo", road, pl[road]["median"], pl[road]["n_beaten_by_real"], "/20")
    res["placebos"] = pl
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done")

if __name__ == "__main__":
    main()
