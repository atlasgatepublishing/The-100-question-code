#!/usr/bin/env python3
"""V13 Best Rules — Appel Breadth-Continuation as a DIAL.
Implements BEST-RULES-SPEC.md exactly (frozen before this run):
  E(t) = 10-day EMA of advance ratio on the program PIT constructed breadth
  stack (154 non-SPY pxfull series, unchanged excluded) — same as v12.
  w(E) = clip((E-0.50)/0.115, 0, 1). Weekly decision (last trading day of
  week, at close) -> next open. Deadband 0.10. Program costs on traded
  amount. No floor. $100 pots.
Placebos (20 seeds/road): (a) circular shift of daily target-weight series;
(b) random weekly targets rescaled to the strategy's mean weight.
"""
import glob, json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import *  # noqa

ROADS_V13 = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
PUBLISHED = {"LONG": 107.86, "DECADE": 97.58, "CONT": 101.69, "VAL": 99.71}

# ---------- breadth (identical construction to v12 run_breadth.py) ----------
spy = load_pxfull("SPY")
spy_dates = [b["d"] for b in spy]
closes = {}
for p in sorted(glob.glob(os.path.join(V7, "pxfull_*.json"))):
    sym = os.path.basename(p)[7:-5]
    if sym == "SPY":
        continue
    try:
        bars = load_pxfull(sym)
    except Exception:
        continue
    closes[sym] = {b["d"]: b["c"] for b in bars}
ratio = []
for i, d in enumerate(spy_dates):
    if i == 0:
        ratio.append(0.5)
        continue
    adv = dec = 0
    pd = spy_dates[i - 1]
    for m in closes.values():
        if d in m and pd in m:
            if m[d] > m[pd]:
                adv += 1
            elif m[d] < m[pd]:
                dec += 1
    ratio.append(adv / (adv + dec) if adv + dec > 0 else 0.5)
E = ema_series(ratio, 10)

def dial(e):
    return min(1.0, max(0.0, (e - 0.50) / 0.115))

W = [dial(e) for e in E]  # daily target weight from close t

# weekly decision days: last trading index of each ISO week
from datetime import date as _date
def iso_week(ds):
    y, m, dd = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    iso = _date(y, m, dd).isocalendar()
    return (iso[0], iso[1])
DECISION = set()
for i, d in enumerate(spy_dates):
    if i + 1 == len(spy_dates) or iso_week(spy_dates[i + 1]) != iso_week(d):
        DECISION.add(i)

def sim_dial(bars, targets_by_bar):
    """targets_by_bar: dict bar_index_in_slice -> target weight to execute at
    that bar's open. Deadband 0.10 vs current weight at open. Program costs."""
    cash, shares = START, 0.0
    curve, trades, costs = [], 0, 0.0
    wsum = 0.0
    for i, b in enumerate(bars):
        if i in targets_by_bar:
            eq_open = cash + shares * b["o"]
            if eq_open > 0:
                cur_w = shares * b["o"] / eq_open
                tgt = targets_by_bar[i]
                if abs(tgt - cur_w) >= 0.10 or (shares == 0 and tgt >= 0.10):
                    est_cost = STK_COST * abs(tgt - cur_w) * eq_open + (STK_FEE if tgt < cur_w else 0.0)
                    eq_net = eq_open - est_cost
                    tgt_shares = tgt * eq_net / b["o"]
                    trade_val = (tgt_shares - shares) * b["o"]
                    act_cost = STK_COST * abs(trade_val) + (STK_FEE if trade_val < 0 else 0.0)
                    cash = eq_open - act_cost - tgt_shares * b["o"]
                    shares = tgt_shares
                    costs += act_cost
                    trades += 1
        eq = cash + shares * b["c"]
        wsum += (shares * b["c"] / eq) if eq > 0 else 0.0
        curve.append({"d": b["d"], "eq": round(eq, 4)})
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve,
            "trades": trades, "costs": round(costs, 2), "maxdd": maxdd(curve),
            "mean_weight": round(wsum / max(1, len(bars)), 4)}

def weekly_targets(idx):
    """Given global SPY indices of a road, return {slice_i: target} executing
    each weekly decision at the next bar inside the road, plus the carried-in
    target executed at the road's first bar."""
    out = {}
    # carried-in: last decision day strictly before road start
    prev_dec = None
    j = idx[0] - 1
    while j >= 0:
        if j in DECISION:
            prev_dec = j
            break
        j -= 1
    if prev_dec is not None:
        out[0] = W[prev_dec]
    pos = {g: k for k, g in enumerate(idx)}
    for g in idx:
        if g in DECISION and g + 1 in pos:
            out[pos[g + 1]] = W[g]
    return out

def weekly_slots(idx):
    """Slice indices at which a weekly execution lands (for placebos)."""
    return sorted(weekly_targets(idx).keys())

out = {"family": "hunt-appel-breadth-continuation", "program": "v13-best-rules",
       "breadth_series_n": len(closes), "spec": "BEST-RULES-SPEC.md (frozen pre-run)",
       "holdings_grid": "NOT-APPLICABLE — market timer, no selection",
       "coins": "NOT-APPLICABLE — NYSE breadth, no published coin analogue",
       "roads": {}}
for road, (s, e) in ROADS_V13.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]
    tg = weekly_targets(idx)
    strat = sim_dial(bars, tg)
    slots = weekly_slots(idx)
    slot_targets = [tg[k] for k in slots]
    w_road = [W[i] for i in idx]
    mean_w = sum(w_road) / len(w_road)
    # (a) circular-shift placebos on the daily target-weight series
    shift_finals = []
    for seed in range(1, 21):
        rng = random.Random(1000 + seed)
        k = rng.randrange(1, len(w_road))
        shifted = w_road[k:] + w_road[:k]
        # carried-in = shifted[0]; weekly decisions read the shifted series
        # at each decision day's position within the road.
        pos = {g: n for n, g in enumerate(idx)}
        ptg = {0: shifted[0]}
        for g in idx:
            if g in DECISION and g + 1 in pos:
                ptg[pos[g + 1]] = shifted[pos[g]]
        shift_finals.append(sim_dial(bars, ptg)["final"])
    # (b) random-timing placebos: weekly targets, rescaled to strategy mean
    rand_finals = []
    for seed in range(1, 21):
        rng = random.Random(5000 + seed)
        raw = [rng.random() for _ in slots]
        m = sum(raw) / len(raw) if raw else 0
        scale = (mean_w / m) if m > 0 else 0.0
        rt = [min(1.0, max(0.0, r * scale)) for r in raw]
        ptg = {slots[n]: rt[n] for n in range(len(slots))}
        rand_finals.append(sim_dial(bars, ptg)["final"])
    out["roads"][road] = {
        "strategy": strat,
        "published_form_final": PUBLISHED[road],
        "spy_buyhold": round(buyhold_open(bars), 2),
        "spy_reference": SPYREF[road],
        "champion_vm": CHAMP[road],
        "mean_target_weight": round(mean_w, 4),
        "placebo_shift_beaten": sum(1 for p in shift_finals if strat["final"] > p),
        "placebo_shift_finals": [round(p, 2) for p in shift_finals],
        "placebo_random_beaten": sum(1 for p in rand_finals if strat["final"] > p),
        "placebo_random_finals": [round(p, 2) for p in rand_finals],
        "periods_monthly": period_stats(strat["curve"], "monthly"),
        "periods_daily": period_stats(strat["curve"], "daily"),
    }
    print(road, "final", strat["final"], "maxdd", strat["maxdd"], "trades", strat["trades"],
          "meanW", strat["mean_weight"], "shift beaten", out["roads"][road]["placebo_shift_beaten"],
          "rand beaten", out["roads"][road]["placebo_random_beaten"],
          "SPY", out["roads"][road]["spy_buyhold"], "pub", PUBLISHED[road])

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("WROTE results.json")
