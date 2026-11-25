#!/usr/bin/env python3
"""V13 BEST RULES — Cabot timing as a graded-exposure DIAL (see BEST-RULES-SPEC.md, frozen first).
Weekly (Friday-close) decisions, next-open trades:
  target = 0.50 * TrendLines_state + 0.10 * Tides_breadth_count(0..5)
  TrendLines: SPX & IXIC vs 35-week SMA, 2-straight-weeks confirm, prior state persists.
  Tides count (weekly evaluation): # of 5 indexes closing above advancing 50d SMA (SMA50[t]>SMA50[t-5]).
Rebalance only when |target - current_frac| >= 0.20 (deadband). No floor. Program costs.
Also re-runs the v12 published AND-gate form in this chassis as a consistency check.
Placebos (20 seeds/road): (a) circular shift of daily target path; (b) random-timing = seeded
permutation of the weekly target values (same exposure amounts, destroyed timing).
Two-Second Indicator: diagnostic only, never trades (constructed new-lows count, as v12)."""
import glob, json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROADS_V13 = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
PUBLISHED = {"LONG": 171.05, "DECADE": 163.43, "CONT": 142.64, "VAL": 129.08}

def closes_of(path):
    bars = load_yahoo_file(path); return {b["d"]: b["c"] for b in bars}

spy = load_pxfull("SPY"); dates = [b["d"] for b in spy]
gspc = closes_of(os.path.join(DATA, "y_GSPC.json")); ixic = closes_of(os.path.join(DATA, "y_IXIC.json"))
nya = closes_of(os.path.join(DATA, "y_NYA.json")); mid = closes_of(os.path.join(DATA, "y_MID.json"))
sml = closes_of(os.path.join(DATA, "y_SP600.json"))
idx_maps = [ixic, nya, gspc, mid, sml]

def aligned(m):
    last = None; out = []
    for d in dates:
        if d in m: last = m[d]
        out.append(last)
    return out

G = aligned(gspc); X = aligned(ixic)
AL = [aligned(m) for m in idx_maps]
SMAS = []
for s in AL:
    filled = [v if v is not None else 0.0 for v in s]
    SMAS.append(sma_series(filled, 50))

fridays = [i for i, d in enumerate(dates) if date.fromisoformat(d).weekday() == 4]

# --- Trend Lines weekly state (per Friday index into fridays list) ---
gw = [G[i] for i in fridays]; xw = [X[i] for i in fridays]
gsma = sma_series([v if v is not None else 0.0 for v in gw], 35)
xsma = sma_series([v if v is not None else 0.0 for v in xw], 35)
tl_w = []; state = 0; ar = br = 0
for i in range(len(fridays)):
    if gw[i] is not None and xw[i] is not None and gsma[i] is not None and xsma[i] is not None:
        if gw[i] > gsma[i] and xw[i] > xsma[i]: ar += 1; br = 0
        elif gw[i] < gsma[i] and xw[i] < xsma[i]: br += 1; ar = 0
        else: ar = br = 0
        if ar >= 2: state = 1
        elif br >= 2: state = 0
    tl_w.append(state)

# --- Tides breadth count at each Friday (daily SMAs, Friday reading) ---
def tides_count(i):
    cnt = 0
    for k in range(5):
        s = AL[k]; sm = SMAS[k]
        if s[i] is not None and sm[i] is not None and i >= 5 and sm[i-5] is not None:
            if s[i] > sm[i] and sm[i] > sm[i-5]: cnt += 1
    return cnt

weekly_targets = [0.5 * tl_w[j] + 0.1 * tides_count(fridays[j]) for j in range(len(fridays))]

# daily target path: decision at Friday close j applies to sessions after fridays[j]
daily_target = [0.0] * len(dates)
cur = 0.0
fj = 0
for i in range(len(dates)):
    while fj < len(fridays) and fridays[fj] < i:
        cur = weekly_targets[fj]; fj += 1
    daily_target[i] = cur

# --- v12 published form states (daily Tides AND-gate), for consistency check ---
tl_daily = [0] * len(dates); fi = 0
for i in range(len(dates)):
    while fi < len(fridays) and fridays[fi] < i: fi += 1
    tl_daily[i] = tl_w[fi-1] if fi >= 1 else 0
pub_states = [1 if (tl_daily[i] == 1 and tides_count(i) >= 3) else 0 for i in range(len(dates))]

def sim_dial(bars, targets, deadband=0.20, cost=STK_COST, fee=STK_FEE):
    """targets[i]: desired exposure decided before session i (decided at a prior close);
    rebalance at open i toward targets[i] when |target-current_frac|>=deadband (or target==0 exit
    only under same deadband rule). Fractional shares, costs on traded notional."""
    cash, shares = START, 0.0; curve = []; trades = 0; costs = 0.0; inv_days = 0
    for i, b in enumerate(bars):
        if i > 0:
            tgt = targets[i]
            eq_o = cash + shares * b["o"]
            cur_frac = (shares * b["o"] / eq_o) if eq_o > 0 else 0.0
            if abs(tgt - cur_frac) >= deadband or (tgt == 0.0 and cur_frac > 0 and abs(tgt - cur_frac) >= deadband):
                delta_val = (tgt - cur_frac) * eq_o
                c = abs(delta_val) * cost + fee; costs += c
                if delta_val > 0:
                    buy_val = delta_val - abs(delta_val) * cost - fee
                    shares += max(0.0, buy_val) / b["o"]; cash -= (buy_val + abs(delta_val) * cost + fee)
                else:
                    sell_val = -delta_val
                    shares -= sell_val / b["o"]
                    if shares < 1e-12: shares = 0.0
                    cash += sell_val - abs(delta_val) * cost - fee
                trades += 1
        eq = cash + shares * b["c"]
        if shares > 0: inv_days += 1
        curve.append({"d": b["d"], "eq": round(eq, 4)})
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve, "trades": trades,
            "costs": round(costs, 2), "maxdd": maxdd(curve),
            "invested_frac": round(inv_days / max(1, len(bars)), 4),
            "avg_exposure": None}

def avg_exposure(bars, targets):
    idx = [i for i, b in enumerate(spy) if bars[0]["d"] <= b["d"] <= bars[-1]["d"]]
    return round(sum(targets[i] for i in idx) / max(1, len(idx)), 4)

# --- Two-Second diagnostic (constructed, never trades) ---
closes = {}
for p in sorted(glob.glob(os.path.join(V7, "pxfull_*.json"))):
    sym = os.path.basename(p)[7:-5]
    if sym == "SPY": continue
    try: closes[sym] = {b["d"]: b["c"] for b in load_pxfull(sym)}
    except Exception: continue
hist = {s: [] for s in closes}; nl_max = 0; nl_days40 = 0
for d in dates:
    cnt = 0
    for sym, m in closes.items():
        if d in m:
            h = hist[sym]
            if len(h) >= 60 and m[d] <= min(h[-252:]): cnt += 1
            h.append(m[d])
    nl_max = max(nl_max, cnt)
    if cnt > 40: nl_days40 += 1

out = {"family": "hunt-cabot-timing", "program": "v13-best-rules",
       "spec": "BEST-RULES-SPEC.md (frozen before run)",
       "two_second_diagnostic": {"max_new_lows_constructed": nl_max, "days_over_40": nl_days40,
                                 "note": "CONSTRUCTED count from survivor stack; understates true NYSE count; diagnostic only"},
       "stocks": {}}
for road, (s, e) in ROADS_V13.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; tg = [daily_target[i] for i in idx]
    mine = sim_dial(bars, tg); mine["avg_target_exposure"] = avg_exposure(bars, daily_target)
    pub = sim_open_exec(bars, [pub_states[i] for i in idx])
    sh = [sim_dial(bars, placebo_shift(tg, sd))["final"] for sd in range(1, 21)]
    # random-timing: permute this road's weekly target values, rebuild daily path within road
    wk_pos = [j for j, fi_ in enumerate(fridays) if idx[0] <= fi_ <= idx[-1]]
    wk_vals = [weekly_targets[j] for j in wk_pos]
    rt = []
    for sd in range(1, 21):
        rng = random.Random(1000 + sd); perm = wk_vals[:]; rng.shuffle(perm)
        pmap = {fridays[j]: perm[k] for k, j in enumerate(wk_pos)}
        t2 = []; c2 = tg[0]
        pos_of = {v: k for k, v in enumerate(idx)}
        for k, i in enumerate(idx):
            if i in pmap: c2 = pmap[i]
            t2.append(c2)
        rt.append(sim_dial(bars, t2)["final"])
    out["stocks"][road] = {
        "best_rules": mine, "published_form_rerun": {"final": pub["final"], "maxdd": pub["maxdd"], "trades": pub["trades"]},
        "published_form_v12_record": PUBLISHED[road],
        "spy_buyhold": round(buyhold_open(bars), 2), "spy_ref": SPYREF[road], "champion_vm": CHAMP[road],
        "shift_placebos_beaten": sum(1 for p in sh if mine["final"] > p), "shift_placebo_finals": [round(p, 2) for p in sh],
        "random_timing_beaten": sum(1 for p in rt if mine["final"] > p), "random_timing_finals": [round(p, 2) for p in rt],
        "random_timing_median": round(sorted(rt)[10], 2),
        "periods_monthly": period_stats(mine["curve"], "monthly"),
        "periods_daily": period_stats(mine["curve"], "daily")}
    print(road, "mine", mine["final"], "DD", mine["maxdd"], "trades", mine["trades"],
          "| pub rerun", pub["final"], "| spy", out["stocks"][road]["spy_buyhold"],
          "| shift", out["stocks"][road]["shift_placebos_beaten"], "/20 | randtime",
          out["stocks"][road]["random_timing_beaten"], "/20 med", out["stocks"][road]["random_timing_median"])
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("two-second:", out["two_second_diagnostic"])
