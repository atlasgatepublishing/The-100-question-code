#!/usr/bin/env python3
"""V13 Best Rules — Renko. Implements BEST-RULES-SPEC.md exactly.
Log-percentage bricks B=2% of last brick level; reversal = 2 bricks;
state from close t trades at open t+1; SPY only; no floor; $100 pots;
costs 0.10%/side + $0.01 sell fee. 20-seed circular-shift placebos.
Simulation only, public data (program v7 cache, read-only)."""
import json, os, time, random, statistics, math
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
COST = 0.001; SELL_FEE = 0.01
BRICK = math.log(1.02)
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def ord_of(s): return date.fromisoformat(s).toordinal()

def load_stock(tkr):
    p = os.path.join(PXDIR, f"pxfull_{tkr}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        dstr = time.strftime("%Y-%m-%d", time.gmtime(t))
        bars.append({"d": dstr, "ord": date.fromisoformat(dstr).toordinal(),
                     "o": o * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def renko_states_logpct(closes):
    """Point-in-time log-% Renko. states[i]=1 if last brick after close i is white."""
    n = len(closes); states = [0]*n; bricks = 0
    level = math.log(closes[0]); direction = 0
    for i, c in enumerate(closes):
        lp = math.log(c)
        if direction == 0:
            while lp >= level + BRICK: level += BRICK; direction = 1; bricks += 1
            while lp <= level - BRICK: level -= BRICK; direction = -1; bricks += 1
        elif direction == 1:
            while lp >= level + BRICK: level += BRICK; bricks += 1
            if lp <= level - 2*BRICK:
                level -= 2*BRICK; direction = -1; bricks += 1
                while lp <= level - BRICK: level -= BRICK; bricks += 1
        else:
            while lp <= level - BRICK: level -= BRICK; bricks += 1
            if lp >= level + 2*BRICK:
                level += 2*BRICK; direction = 1; bricks += 1
                while lp >= level + BRICK: level += BRICK; bricks += 1
        states[i] = 1 if direction == 1 else 0
    return states, bricks

def simulate(bars, states, start_ord, end_ord, shift_seed=None):
    """State after close of previous bar -> trade at this bar's open.
    For the first bar in the window, previous state is states[idx0-1] (warm-up)."""
    idx = [i for i, b in enumerate(bars) if start_ord <= b["ord"] <= end_ord]
    if not idx: return None
    seg = []
    for pos, i in enumerate(idx):
        prev = states[i-1] if i > 0 else 0
        seg.append(prev)
    if shift_seed is not None and len(seg) > 1:
        rng = random.Random(shift_seed); k = rng.randrange(1, len(seg))
        seg = seg[k:] + seg[:k]
    cash, shares, costs, orders, invested = START, 0.0, 0.0, 0, 0
    curve = []
    for pos, i in enumerate(idx):
        b = bars[i]; want = seg[pos]
        if want == 1 and shares == 0.0 and cash > 0:
            bv = cash/(1+COST); fee = bv*COST; shares = bv/b["o"]; cash -= bv+fee; costs += fee; orders += 1
        elif want == 0 and shares > 0:
            val = shares*b["o"]; fee = val*COST+SELL_FEE; cash += val-fee; costs += fee; shares = 0.0; orders += 1
        eq = cash + shares*b["c"]
        if shares > 0: invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        val = shares*bars[idx[-1]]["c"]; fee = val*COST+SELL_FEE
        cash += val-fee; costs += fee; shares = 0.0; orders += 1
        curve[-1] = [curve[-1][0], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak-v)/peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": orders,
            "invested_pct": round(100.0*invested/len(idx), 1), "curve": curve}

def buy_hold(bars, start_ord, end_ord):
    idx = [i for i, b in enumerate(bars) if start_ord <= b["ord"] <= end_ord]
    if not idx: return None
    sh = (START/(1+COST))/bars[idx[0]]["o"]
    curve = [[bars[i]["d"], round(sh*bars[i]["c"], 4)] for i in idx]
    val = sh*bars[idx[-1]]["c"]; final = val-(val*COST+SELL_FEE)
    curve[-1] = [curve[-1][0], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak-v)/peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "curve": curve}

def period_stats(curve, freq="daily"):
    """Cut curve into calendar-year or daily periods; return distribution."""
    if freq == "daily":
        series = [START] + [v for _, v in curve]
        labels = ["start"] + [d for d, _ in curve]
        rets = [(series[i]/series[i-1]-1.0)*100.0 if series[i-1] > 0 else 0.0 for i in range(1, len(series))]
    else:  # yearly: return within each calendar year from curve values
        by_year = {}
        for d, v in curve: by_year.setdefault(d[:4], []).append(v)
        years = sorted(by_year)
        rets = []; prev_end = START
        for y in years:
            end = by_year[y][-1]
            rets.append((end/prev_end-1.0)*100.0 if prev_end > 0 else 0.0)
            prev_end = end
    if not rets: return None
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    # longest between new highs on the underlying curve (days)
    series = [START] + [v for _, v in curve]
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i-last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"periods": len(rets), "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_days": longest}

def main():
    bars = load_stock("SPY")
    states, bricks = renko_states_logpct([b["c"] for b in bars])
    out = {"family": "hunt-renko v13 best-rules", "spec": "BEST-RULES-SPEC.md — log-% bricks 2%, reversal 2 bricks, next-open execution, SPY only, no floor",
           "costs": "0.10%/side + $0.01 sell fee", "bricks_total_full_history": bricks,
           "bars": len(bars), "range": f"{bars[0]['d']} -> {bars[-1]['d']}", "roads": {}}
    for road, (s, e) in ROADS.items():
        so, eo = ord_of(s), ord_of(e)
        r = simulate(bars, states, so, eo)
        bh = buy_hold(bars, so, eo)
        twins = [simulate(bars, states, so, eo, shift_seed=sd)["final"] for sd in range(1, 21)]
        rec = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
               "orders": r["orders"], "invested_pct": r["invested_pct"],
               "spy_hold_same_plumbing": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]},
               "spy_program_ref": SPYREF[road], "champion_vm": CHAMP[road],
               "beats_champion": r["final"] > CHAMP[road],
               "placebo_seed_finals": twins,
               "placebo_beaten_of_20": sum(1 for x in twins if r["final"] > x),
               "period_stats_daily": period_stats(r["curve"], "daily"),
               "period_stats_yearly": period_stats(r["curve"], "yearly"),
               "curve": r["curve"]}
        out["roads"][road] = rec
        print(f"{road}: final ${r['final']} maxDD {r['max_dd_pct']}% orders {r['orders']} "
              f"invested {r['invested_pct']}% | SPY hold ${bh['final']} | champ ${CHAMP[road]} | placebo {rec['placebo_beaten_of_20']}/20")
    # Confirmation material (frozen bars in spec): yearly folds + half-windows for any champ-beating road;
    # compute folds/halves for all roads regardless, print only used if triggered.
    folds = {}
    for y in range(2010, 2027):
        s = ord_of(f"{y}-01-01"); e = ord_of("2026-11-20") if y == 2026 else ord_of(f"{y}-12-31")
        rn = simulate(bars, states, s, e); bh = buy_hold(bars, s, e)
        if rn and bh: folds[str(y)] = {"renko": rn["final"], "spy_hold": bh["final"], "beat_hold": rn["final"] > bh["final"]}
    out["year_folds_fresh100"] = folds
    out["year_folds_beat_hold_count"] = sum(1 for v in folds.values() if v["beat_hold"])
    halves = {}
    for road, (s, e) in ROADS.items():
        so, eo = ord_of(s), ord_of(e)
        idx = [b for b in bars if so <= b["ord"] <= eo]
        mid = idx[len(idx)//2]["ord"]
        h = []
        for (hs, he) in ((so, mid), (mid+1, eo)):
            rn = simulate(bars, states, hs, he); bh = buy_hold(bars, hs, he)
            h.append({"renko": rn["final"], "spy_hold": bh["final"], "beat_hold": rn["final"] > bh["final"]})
        halves[road] = h
    out["half_windows"] = halves
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE folds beat hold:", out["year_folds_beat_hold_count"], "/", len(folds))

if __name__ == "__main__":
    main()
