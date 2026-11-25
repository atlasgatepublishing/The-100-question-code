#!/usr/bin/env python3
"""
V13 BEST RULES — crypto-mayer-200w. SIMULATION ONLY.
Frozen spec: BEST-RULES-SPEC.md in this folder (written before this run).
  BTC only. Mayer Multiple band LADDER (dial): MM<0.8->100%, <1.2->80%,
  <1.8->60%, <2.4->35%, >=2.4->0%. Weekly rebalance to target share of
  equity; signal on check-day close (trailing 200 closes only), execute
  next bar open. Cost 0.60%/side on traded dollars. No floor/stop.
  200WMA printed as diagnostic only. $100 pot.
Data (READ-ONLY): v4 crypto-basket-pit registry + cached daily bars (BTC).
Roads: FULL = v12 Form M window (bar idx 199 -> last bar).
       VAL  = first bar >= 2023-01-01 -> last bar (standalone $100).
Placebos: 20 seeds each — matched random-timing (same level frequencies),
shifted-signal (circular shift >= 4 weekly checks).
"""
import json, os, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE = os.path.join(V4, "crypto-basket-pit-data")
COST = 0.006
START = 100.0
LEVELS = [1.0, 0.8, 0.6, 0.35, 0.0]

def ladder(mm):
    if mm is None: return None
    if mm < 0.80: return 1.0
    if mm < 1.20: return 0.80
    if mm < 1.80: return 0.60
    if mm < 2.40: return 0.35
    return 0.0

def load_btc():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    v = reg["1"]
    src = v["source"]
    assert src.startswith("yahoo:"), src
    with open(os.path.join(CACHE, f"y_{src[6:]}.json")) as f:
        return json.load(f)

def sma_series(closes, w):
    out = [None]*len(closes); s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= w: s -= closes[i-w]
        if i >= w-1: out[i] = s/w
    return out

def run_ladder(rows, mm, targets_by_check):
    """rows: window bars (global-aligned mm list parallel to rows).
    targets_by_check: list of target weights, one per weekly check.
    Checks occur at window-relative indices 0,7,14,...; signal decided on
    that bar's close; rebalance executes at next bar's open.
    Returns final, daily curve, maxdd, trades, avg exposure (equity share)."""
    n = len(rows)
    cash, units = START, 0.0
    curve = []
    trades = 0
    check_idx = set(range(0, n, 7))
    pending = None
    ci = 0
    expo_sum = 0.0
    for i in range(n):
        o, c = rows[i]["o"], rows[i]["c"]
        if pending is not None:
            tgt = pending; pending = None
            eq_open = cash + units*o
            cur_val = units*o
            want_val = tgt*eq_open
            delta = want_val - cur_val
            if abs(delta) > 1e-9:
                if delta > 0:
                    spend = min(delta, cash)
                    units += spend*(1-COST)/o
                    cash -= spend
                else:
                    sell_val = min(-delta, cur_val)
                    units -= sell_val/o
                    cash += sell_val*(1-COST)
                trades += 1
        eq = cash + units*c
        curve.append(eq)
        expo_sum += (units*c/eq) if eq > 0 else 0.0
        if i in check_idx and ci < len(targets_by_check):
            pending = targets_by_check[ci]; ci += 1
    final = cash + units*rows[-1]["c"]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq/peak - 1.0)
    return {"final": round(final, 2), "maxdd_pct": round(maxdd*100, 1),
            "trades": trades, "avg_exposure_pct": round(100*expo_sum/max(n,1), 1),
            "curve": [round(x, 4) for x in curve]}

def buy_hold(rows):
    units = START*(1-COST)/rows[0]["o"]
    curve = [units*r["c"] for r in rows]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq/peak - 1.0)
    return {"final": round(units*rows[-1]["c"], 2), "maxdd_pct": round(maxdd*100, 1),
            "curve": [round(x, 4) for x in curve]}

def weekly_stats(curve):
    pts = [START] + [curve[i] for i in range(6, len(curve), 7)]
    if curve and (len(curve)-1) % 7 != 6: pts.append(curve[-1])
    rets = [pts[i+1]/pts[i]-1.0 for i in range(len(pts)-1) if pts[i] > 0]
    if not rets: return None
    med = statistics.median(rets)
    pos = sum(1 for r in rets if r > 0)/len(rets)
    best, worst = max(rets), min(rets)
    streak = cur = 0
    for r in rets:
        cur = cur+1 if r < 0 else 0
        streak = max(streak, cur)
    peak_i, last_high, gap = 0, 0, 0
    runmax = pts[0]
    since = 0; maxgap = 0
    for p in pts[1:]:
        if p >= runmax: runmax = p; since = 0
        else:
            since += 1; maxgap = max(maxgap, since)
    return {"periods": len(rets), "median_pct": round(med*100, 3),
            "share_positive_pct": round(pos*100, 1),
            "best_pct": round(best*100, 2), "worst_pct": round(worst*100, 2),
            "longest_losing_streak_weeks": streak,
            "longest_stretch_between_new_highs_weeks": maxgap,
            "avg_pct_secondary": round(statistics.mean(rets)*100, 3)}

def real_targets(rows, mm):
    return [ladder(mm[i]) for i in range(0, len(rows), 7)]

def pct_rank(vals, x):
    return round(100.0*sum(1 for y in vals if y < x)/len(vals), 0)

def run_road(rows, mm, label):
    targets = real_targets(rows, mm)
    real = run_ladder(rows, mm, targets)
    hold = buy_hold(rows)
    n = len(targets)
    # placebo 1: matched random timing (same marginal level frequencies)
    freq = {lv: targets.count(lv)/n for lv in LEVELS}
    pool = []
    for lv in LEVELS: pool += [lv]*round(freq[lv]*n)
    while len(pool) < n: pool.append(statistics.mode(targets))
    pool = pool[:n]
    rand_finals, shift_finals = [], []
    for s in range(20):
        rng = random.Random(20261122 + s)
        rt = [rng.choice(pool) for _ in range(n)]
        rand_finals.append(run_ladder(rows, mm, rt)["final"])
        off = rng.randint(4, max(5, n-5))
        st = targets[off:] + targets[:off]
        shift_finals.append(run_ladder(rows, mm, st)["final"])
    return {"label": label, "window": [rows[0]["d"], rows[-1]["d"]], "bars": len(rows),
            "strategy": {k: real[k] for k in ("final", "maxdd_pct", "trades", "avg_exposure_pct")},
            "buy_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]},
            "weekly_stats_strategy": weekly_stats(real["curve"]),
            "weekly_stats_buy_hold": weekly_stats(hold["curve"]),
            "target_level_freq": {str(k): targets.count(k) for k in LEVELS},
            "placebo_random_timing": {"median_final": round(statistics.median(rand_finals), 2),
                "real_pct_rank": pct_rank(rand_finals, real["final"]), "finals": [round(x,2) for x in rand_finals]},
            "placebo_shifted": {"median_final": round(statistics.median(shift_finals), 2),
                "real_pct_rank": pct_rank(shift_finals, real["final"]), "finals": [round(x,2) for x in shift_finals]},
            "curves": {"strategy": real["curve"], "buy_hold": hold["curve"]},
            "curve_dates": [r["d"] for r in rows]}

def main():
    rows_all = load_btc()
    closes = [r["c"] for r in rows_all]
    sma200 = sma_series(closes, 200)
    sma1400 = sma_series(closes, 1400)
    mm_all = [(closes[i]/sma200[i] if sma200[i] else None) for i in range(len(rows_all))]

    out = {"family": "crypto-mayer-200w", "program": "v13-best-rules",
           "spec": "Mayer band ladder (dial), weekly, BTC only, 0.60%/side, no floor",
           "cost_per_side": COST, "roads": {}}

    # FULL road: v12 Form M window = global idx 199 -> end
    fi = 199
    frows = rows_all[fi:]; fmm = mm_all[fi:]
    out["roads"]["FULL"] = run_road(frows, fmm, "FULL full-history (v12 Form M window)")
    # 200WMA diagnostic on FULL window
    diag_days = [i for i in range(fi, len(rows_all)) if sma1400[i] is not None]
    below = sum(1 for i in diag_days if closes[i] <= sma1400[i])
    out["diag_200wma_full_window"] = {"days_with_200wma": len(diag_days),
        "days_price_at_or_below_200wma": below,
        "share_pct": round(100*below/max(len(diag_days),1), 1)}

    # VAL road: first bar >= 2023-01-01
    vi = next(i for i, r in enumerate(rows_all) if r["d"] >= "2023-01-01")
    vrows = rows_all[vi:]; vmm = mm_all[vi:]
    out["roads"]["VAL_2023_2026"] = run_road(vrows, vmm, "VAL 2023-2026 confirmation")

    # Split-half of FULL (secondary confirmation evidence)
    mid = fi + len(frows)//2
    halves = {}
    for name, a, b in (("half1", fi, mid), ("half2", mid, len(rows_all))):
        hr = rows_all[a:b]; hm = mm_all[a:b]
        st = run_ladder(hr, hm, real_targets(hr, hm))
        hd = buy_hold(hr)
        halves[name] = {"window": [hr[0]["d"], hr[-1]["d"]],
                        "strategy_final": st["final"], "strategy_maxdd_pct": st["maxdd_pct"],
                        "buy_hold_final": hd["final"], "buy_hold_maxdd_pct": hd["maxdd_pct"]}
    out["split_half_full"] = halves

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    for k, r in out["roads"].items():
        print(k, r["window"], "strategy", r["strategy"], "hold", r["buy_hold"],
              "rand_rank", r["placebo_random_timing"]["real_pct_rank"],
              "shift_rank", r["placebo_shifted"]["real_pct_rank"])
    print("split_half", json.dumps(halves))
    print("diag", out["diag_200wma_full_window"])

if __name__ == "__main__":
    main()
