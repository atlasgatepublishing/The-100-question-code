#!/usr/bin/env python3
"""V13 BEST RULES — Deemer Breakaway Momentum. Spec: BEST-RULES-SPEC.md (frozen).
Trigger unchanged: 10d A/D totals ratio >1.97 OR 20d >1.72 (pond-30 constructed
series, same as v12). Entry: cluster start (first trigger after >=10 non-trigger
days), next open, flat-only, SPY all-in. Exit: next open after first SPY close
below its 200d SMA. No floor. Costs 0.10%/side + $0.01/sell.
Placebo: 20 seeds/road, same entry count, random entry days, same trend exit."""
import json, os, random, statistics, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST, FEE, START = 0.001, 0.01, 100.0
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]

def load_bars(sym):
    fn = "GOOG" if sym == "GOOGL" else sym  # v7 stack carries GOOG only; same-direction A/D input
    j = json.load(open(os.path.join(V7, f"pxfull_{fn}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": q["open"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def build_signals(spy):
    adv, dec = {}, {}
    for t in POND:
        bars = load_bars(t)
        for i in range(1, len(bars)):
            d = bars[i]["d"]
            if bars[i]["c"] > bars[i-1]["c"]: adv[d] = adv.get(d, 0) + 1
            elif bars[i]["c"] < bars[i-1]["c"]: dec[d] = dec.get(d, 0) + 1
    dates = [b["d"] for b in spy]
    A = [adv.get(d, 0) for d in dates]; D = [dec.get(d, 0) for d in dates]
    sig = []
    for i in range(len(dates)):
        fire = False
        if i >= 9:
            sa, sd = sum(A[i-9:i+1]), sum(D[i-9:i+1])
            if sd > 0 and sa/sd > 1.97: fire = True
        if i >= 19:
            sa, sd = sum(A[i-19:i+1]), sum(D[i-19:i+1])
            if sd > 0 and sa/sd > 1.72: fire = True
        sig.append(fire)
    # cluster starts: trigger after >=10 consecutive non-trigger days
    clusters, run = [], 99
    for i, f in enumerate(sig):
        if f and run >= 10: clusters.append(i)
        run = 0 if f else run + 1
    closes = [b["c"] for b in spy]
    sma = [None]*len(closes)
    for i in range(len(closes)):
        if i >= 199: sma[i] = sum(closes[i-199:i+1]) / 200
    return sig, clusters, sma

def simulate(seg, sma_seg, entry_idxs):
    """entry_idxs: indices into seg whose CLOSE carries the signal; buy next open.
    Exit: next open after first close below SMA while holding."""
    entry_set = set(entry_idxs)
    cash, shares, curve, trades, log = START, 0.0, [], 0, []
    invested = 0; pending_buy = False; pending_sell = False; buy_date = None
    for i, b in enumerate(seg):
        if pending_sell and shares > 0:
            cash = shares * b["o"] * (1 - COST) - FEE; shares = 0.0; trades += 1
            log.append({"exit": b["d"], "reason": "close_below_200d_sma"}); pending_sell = False
        if pending_buy and shares == 0:
            shares = cash * (1 - COST) / b["o"]; cash = 0.0; trades += 1
            buy_date = b["d"]; log.append({"entry": b["d"]}); pending_buy = False
        if shares > 0: invested += 1
        curve.append([b["d"], round(cash + shares * b["c"], 4)])
        if shares > 0 and sma_seg[i] is not None and b["c"] < sma_seg[i]:
            pending_sell = True
        if shares == 0 and not pending_buy and i in entry_set:
            pending_buy = True
    if shares > 0:
        cash = shares * seg[-1]["c"] * (1 - COST) - FEE; trades += 1
        curve[-1][1] = round(cash, 4)
    return {"final": round(curve[-1][1], 2), "curve": curve, "trades": trades,
            "entries_taken": sum(1 for x in log if "entry" in x),
            "invested_frac": round(invested / max(1, len(seg)), 4), "log": log}

def maxdd(curve):
    peak, dd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq); dd = min(dd, eq/peak - 1 if peak > 0 else 0.0)
    return round(dd*100, 2)

def period_stats(curve):
    months = {}
    for d, eq in curve: months[d[:7]] = eq
    ks = sorted(months); rets, prev = [], START
    for k in ks:
        rets.append(months[k]/prev - 1); prev = months[k]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        streak = streak+1 if r < 0 else 0; worst = max(worst, streak)
    vals = [START] + [months[k] for k in ks]
    peak, since, longest = vals[0], 0, 0
    for v in vals:
        if v >= peak: peak, since = v, 0
        else: since += 1; longest = max(longest, since)
    return {"n_periods": len(rets), "share_positive_pct": round(100*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets)*100, 2), "best_pct": round(max(rets)*100, 2),
            "worst_pct": round(min(rets)*100, 2), "longest_losing_streak": worst,
            "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets)*100, 2)}

def main():
    spy = load_bars("SPY")
    sig, clusters, sma = build_signals(spy)
    res = {"family": "hunt-deemer-breakaway-momentum", "variant": "v13-best-rules: trend exit (200d SMA), no floor",
           "signal_clusters_total": len(clusters), "signal_dates": [spy[i]["d"] for i in clusters], "roads": {}}
    for road, (s, e) in ROADS.items():
        i0 = next(i for i, b in enumerate(spy) if b["d"] >= s)
        i1 = max(i for i, b in enumerate(spy) if b["d"] <= e)
        seg, sma_seg = spy[i0:i1+1], sma[i0:i1+1]
        ent = [i - i0 for i in clusters if i0 <= i < i1]
        r = simulate(seg, sma_seg, ent)
        bh_shares = START * (1 - COST) / seg[0]["o"]
        bh_final = round(bh_shares * seg[-1]["c"] * (1 - COST) - FEE, 2)
        bh_curve = [[b["d"], round(bh_shares * b["c"], 4)] for b in seg]
        # placebo: same number of entries actually taken, random days, same exit
        k = r["entries_taken"]; finals = []
        for seed in range(20):
            rng = random.Random(7000 + seed*13 + len(road))
            cand = sorted(rng.sample(range(len(seg)-1), min(k, len(seg)-1))) if k else []
            finals.append(simulate(seg, sma_seg, cand)["final"])
        # yearly folds (for confirmation readiness / honest grading)
        folds = {}
        for y in sorted(set(b["d"][:4] for b in seg)):
            j0 = next(i for i, b in enumerate(seg) if b["d"][:4] == y)
            j1 = max(i for i, b in enumerate(seg) if b["d"][:4] == y)
            sub_ent = [i - j0 for i in ent if j0 <= i < j1]
            folds[y] = simulate(seg[j0:j1+1], sma_seg[j0:j1+1], sub_ent)["final"]
        res["roads"][road] = {"final": r["final"], "maxdd_pct": maxdd(r["curve"]), "trades": r["trades"],
            "entries_taken": k, "entries_offered": len(ent), "invested_frac": r["invested_frac"],
            "buyhold_final": bh_final, "buyhold_maxdd_pct": maxdd(bh_curve),
            "periods_monthly": period_stats(r["curve"]), "trade_log": r["log"],
            "placebo_random_timing_20seed": {"median": round(statistics.median(finals), 2),
                "n_beaten_by_actual": sum(1 for f in finals if r["final"] > f), "finals": sorted(finals)},
            "yearly_folds_final_per_100": folds, "curve": r["curve"]}
        print(road, r["final"], "BH", bh_final, "DD", maxdd(r["curve"]), "trades", r["trades"],
              "inMkt", r["invested_frac"], "placeboMed", round(statistics.median(finals), 2),
              "beats", sum(1 for f in finals if r["final"] > f), "/20")
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("clusters:", len(clusters))

if __name__ == "__main__": main()
