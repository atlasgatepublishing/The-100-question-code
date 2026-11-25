#!/usr/bin/env python3
"""V13 best-rules KAMA — BEST-RULES-SPEC.md exactly.
Daily KAMA(10,2,30) Kaufman constants untouched. WEEKLY decisions at last
trading day of each ISO week: bullish iff Close>KAMA; target weight
w = 0.50+0.50*ER(10) if bullish else 0. Rebalance at that close.
Costs: 0.10%/side on traded fraction + $0.01 fee when a rebalance reduces
position. No floor. Roads per task. Placebos: 20-seed circular shifts of
the weekly target-weight series. Equity = cash + shares*close daily."""
import json, os, sys, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-kaufman-kama"))
from timerlib import load_stock, period_stats, START

COST = 0.001; FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBBEST = {"LONG": 262.83, "DECADE": 201.91, "CONT": 181.46, "VAL": 133.49}

def kama_er(closes):
    c = np.asarray(closes, float); n = len(c)
    kama = np.empty(n); kama[0] = c[0]; er = np.zeros(n)
    adiff = np.abs(np.diff(c)); cs = np.concatenate([[0.0], np.cumsum(adiff)])
    fast, slow = 2/3.0, 2/31.0
    for t in range(1, n):
        if t >= 10:
            vol = cs[t] - cs[t-10]
            e = abs(c[t]-c[t-10])/vol if vol > 0 else 0.0
        else:
            e = 0.0
        er[t] = e
        sc = (e*(fast-slow)+slow)**2
        kama[t] = kama[t-1] + sc*(c[t]-kama[t-1])
    return kama, er

def weekly_targets(bars, kama, er):
    """dict bar-index -> target weight, at last trading day of each ISO week."""
    tgt = {}
    for i, b in enumerate(bars):
        # last trading day of week: next bar is a different ISO week (or none)
        if i == len(bars)-1:
            last = True
        else:
            d0 = b["d"]; d1 = bars[i+1]["d"]
            import datetime
            w0 = datetime.date.fromisoformat(d0).isocalendar()[:2]
            w1 = datetime.date.fromisoformat(d1).isocalendar()[:2]
            last = (w0 != w1)
        if last:
            tgt[i] = (0.5 + 0.5*er[i]) if bars[i]["c"] > kama[i] else 0.0
    return tgt

def simulate_road(bars, tgt_by_idx):
    """bars: road slice; tgt_by_idx: {local_idx: weight}. Daily equity curve."""
    cash = START; shares = 0.0; orders = 0; costs = 0.0; curve = []
    for i, b in enumerate(bars):
        if i in tgt_by_idx:
            px = b["c"]; equity = cash + shares*px; w = tgt_by_idx[i]
            target_val = w*equity; cur_val = shares*px; dv = target_val-cur_val
            if abs(dv) > 1e-9:
                cst = abs(dv)*COST + (FEE if dv < 0 else 0.0)
                costs += cst; orders += 1
                shares = target_val/px
                cash = equity - cst - shares*px
        curve.append([b["d"], round(cash + shares*b["c"], 4)])
    final = curve[-1][1] if curve else START
    peak = START; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1-v/peak)
    return {"final": round(final, 2), "max_dd": round(maxdd, 4),
            "costs": round(costs, 2), "orders": orders, "curve": curve}

def main():
    spy = load_stock("SPY")
    closes = [b["c"] for b in spy]
    kama, er = kama_er(closes)
    full_tgt = weekly_targets(spy, kama, er)
    idx = {b["d"]: i for i, b in enumerate(spy)}
    res = {"family": "hunt-kaufman-kama", "program": "v13-best-rules",
           "spec": "weekly close decisions; bullish iff Close>KAMA; w=0.5+0.5*ER else 0; no floor",
           "roads": {}}
    for road, (s0, s1) in ROADS.items():
        rb = [b for b in spy if s0 <= b["d"] <= s1]
        i0 = idx[rb[0]["d"]]
        # weekly decision indices within road: global weekly targets falling in road
        local_tgt = {}
        for gi, w in full_tgt.items():
            if s0 <= spy[gi]["d"] <= s1:
                local_tgt[gi - i0] = w
        # ensure a decision at road start uses state as of first weekly close in road (spec: decisions weekly only)
        r = simulate_road(rb, local_tgt)
        r["hold"] = SPYREF[road]; r["champion"] = CHAMP[road]; r["published_best"] = PUBBEST[road]
        r["period_stats_monthly"] = period_stats(r["curve"])
        # placebos: circular shifts of this road's weekly weight sequence
        wseq = [local_tgt[k] for k in sorted(local_tgt)]
        keys = sorted(local_tgt)
        beaten = 0; twin_finals = []
        if len(wseq) > 4:
            for s in range(1, 21):
                rng = random.Random(1000+s)
                off = rng.randrange(1, len(wseq))
                sh = wseq[off:] + wseq[:off]
                st = {keys[j]: sh[j] for j in range(len(keys))}
                tr = simulate_road(rb, st)
                twin_finals.append(tr["final"])
                if r["final"] > tr["final"]: beaten += 1
        r["placebo"] = {"beaten_of_20": beaten, "twin_finals": twin_finals}
        r["avg_weight"] = round(statistics.mean(wseq), 3) if wseq else None
        r["weeks_invested_frac"] = round(sum(1 for w in wseq if w > 0)/len(wseq), 3) if wseq else None
        res["roads"][road] = r
        print(road, "final", r["final"], "maxdd", r["max_dd"], "orders", r["orders"],
              "placebo", beaten, "/20", flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
