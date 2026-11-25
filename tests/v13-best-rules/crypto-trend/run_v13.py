#!/usr/bin/env python3
"""v13 best-rules crypto-trend. Spec: BEST-RULES-SPEC.md (frozen before run).
BTC-only verdict pot; ETH and 50/50 combo as reporting sleeves.
Daily eval; exit on 1 close < SMA200; re-entry needs 2 consecutive closes > SMA200;
signal at close, fill next open; NO floor; cost 0.60%/side.
Placebos: 20 circular time-shifts of the strategy's own in/out signal, same costs.
Data: read-only copies in ../../v10-retest/crypto-trend/data/ (Yahoo daily bars).
"""
import csv, json, math, random
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent.parent / "v10-retest" / "crypto-trend" / "data"
COST = 0.006
START_CASH = 100.0

def load(sym):
    rows = []
    with open(DATA / f"{sym}-USD.csv") as f:
        for r in csv.DictReader(f):
            rows.append({"d": r["date"], "o": float(r["open"]), "c": float(r["close"])})
    rows.sort(key=lambda x: x["d"])
    # SMA200 of closes, point-in-time (uses only bars <= i)
    run = 0.0
    for i, b in enumerate(rows):
        run += b["c"]
        if i >= 200: run -= rows[i-200]["c"]
        b["sma"] = run/200.0 if i >= 199 else None
    return rows

def run_pot(rows, start, end, placebo_shift=None):
    """Returns dict with final, curve [(date, equity)], costs, orders, exposure_frac.
    placebo_shift: if set, the in/out target series is circularly shifted by that many days."""
    idx = [i for i,b in enumerate(rows) if start <= b["d"] <= end]
    if not idx: return None
    # desired state per day (decided at that day's close), from real signal
    desired = []
    state_in = False; above_streak = 0
    for i in idx:
        b = rows[i]
        if b["sma"] is None: desired.append(False); continue
        if state_in:
            if b["c"] < b["sma"]: state_in = False; above_streak = 0
        else:
            if b["c"] > b["sma"]:
                above_streak += 1
                if above_streak >= 2: state_in = True; above_streak = 0
            else: above_streak = 0
        desired.append(state_in)
    if placebo_shift:
        s = placebo_shift % len(desired)
        desired = desired[-s:] + desired[:-s] if s else desired
    cash, units, costs, orders = START_CASH, 0.0, 0.0, 0
    curve = []; in_days = 0
    for k, i in enumerate(idx):
        b = rows[i]
        # execute yesterday's decision at today's open
        if k > 0:
            want = desired[k-1]
            if want and units == 0.0:
                fee = cash*COST; units = (cash-fee)/b["o"]; costs += fee; cash = 0.0; orders += 1
            elif not want and units > 0.0:
                gross = units*b["o"]; fee = gross*COST; cash = gross-fee; costs += fee; units = 0.0; orders += 1
        eq = cash + units*b["c"]
        if units > 0: in_days += 1
        curve.append((b["d"], eq))
    return {"final": round(curve[-1][1],2), "curve": curve, "costs": round(costs,2),
            "orders": orders, "exposure": round(in_days/len(idx),3)}

def hold(rows, start, end):
    idx = [b for b in rows if start <= b["d"] <= end]
    if not idx: return None
    units = START_CASH*(1-COST)/idx[0]["o"]
    curve = [(b["d"], units*b["c"]) for b in idx]
    return {"final": round(curve[-1][1],2), "curve": curve}

def max_dd(curve):
    peak, dd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v); dd = min(dd, v/peak-1.0 if peak>0 else 0.0)
    return round(dd*100,1)

def dist_stats(curve):
    """Per-calendar-year period distribution + time-under-water stats."""
    years = {}
    for d, v in curve: years.setdefault(d[:4], []).append(v)
    yrs = sorted(years)
    rets = []
    prev_end = START_CASH
    for y in yrs:
        # year return measured from prior curve value at year start (first point vs prev year end)
        rets.append((y, years[y][-1]/prev_end - 1.0)); prev_end = years[y][-1]
    vals = sorted(r for _, r in rets)
    n = len(vals)
    median = vals[n//2] if n % 2 else (vals[n//2-1]+vals[n//2])/2
    pos = sum(1 for r in vals if r > 0)
    streak = cur = 0
    for _, r in rets:
        cur = cur+1 if r < 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (days)
    peak, peak_d, longest = -1.0, None, 0
    for d, v in curve:
        if v >= peak: peak, peak_d = v, d
        else:
            dd_ = (date.fromisoformat(d) - date.fromisoformat(peak_d)).days
            longest = max(longest, dd_)
    return {"median_year_pct": round(median*100,1), "share_years_positive": f"{pos}/{n}",
            "best_year": [max(rets, key=lambda t: t[1])[0], round(max(r for _,r in rets)*100,1)],
            "worst_year": [min(rets, key=lambda t: t[1])[0], round(min(r for _,r in rets)*100,1)],
            "longest_losing_streak_years": streak, "longest_days_between_new_highs": longest,
            "mean_year_pct_secondary": round(sum(vals)/n*100,1)}

BTC, ETH = load("BTC"), load("ETH")
ROADS = {"LONG": ("2014-09-17","2026-11-20"), "DECADE": ("2016-11-21","2026-11-20"),
         "CONT": ("2019-01-02","2026-11-20"), "VAL": ("2023-01-03","2026-11-20")}
out = {"family":"crypto-trend","program":"v13-best-rules","cost_per_side":COST,"floor":None,
       "rule":"exit 1 close<SMA200; re-enter after 2 consecutive closes>SMA200; daily; next-open fills",
       "roads":{}, "folds":{}}
rng = random.Random(13013)

for name,(s,e) in ROADS.items():
    btc = run_pot(BTC, s, e); eth = run_pot(ETH, s, e)
    bh_b, bh_e = hold(BTC, s, e), hold(ETH, s, e)
    # combo sleeve: mean of two $50 sleeves -> rerun pots at $100 and average finals/curves
    combo_curve = [(d, (vb+ve)/2) for (d,vb),(_,ve) in zip(btc["curve"], eth["curve"])] \
        if len(btc["curve"])==len(eth["curve"]) else None
    combo_final = round((btc["final"]+eth["final"])/2,2)
    combo_hold = round((bh_b["final"]+bh_e["final"])/2,2) if bh_e else bh_b["final"]
    # placebos on BTC pot: circular shifts, min shift 30 days
    n_days = len(btc["curve"]); beaten = 0; pfin = []
    for _ in range(20):
        sh = rng.randint(30, n_days-30)
        pf = run_pot(BTC, s, e, placebo_shift=sh)["final"]; pfin.append(pf)
        if btc["final"] > pf: beaten += 1
    out["roads"][name] = {
        "window":[s,e],
        "btc_pot":{"final":btc["final"],"max_dd_pct":max_dd(btc["curve"]),"costs":btc["costs"],
                   "orders":btc["orders"],"exposure":btc["exposure"],
                   "distribution":dist_stats(btc["curve"]),
                   "curve":[[d,round(v,2)] for d,v in btc["curve"]]},
        "btc_hold":{"final":bh_b["final"],"max_dd_pct":max_dd(bh_b["curve"])},
        "eth_pot":{"final":eth["final"],"max_dd_pct":max_dd(eth["curve"]),"costs":eth["costs"],"orders":eth["orders"]},
        "eth_hold":{"final":bh_e["final"],"max_dd_pct":max_dd(bh_e["curve"])} if bh_e else None,
        "combo_pot_final":combo_final, "combo_hold_final":combo_hold,
        "placebo_beaten_of_20":beaten, "placebo_finals":pfin,
        "beats_btc_hold": btc["final"] > bh_b["final"]}
    print(name, "BTC pot", btc["final"], "vs hold", bh_b["final"], "DD", max_dd(btc["curve"]),
          "placebos", beaten, "/20 | ETH", eth["final"], "vs", bh_e["final"] if bh_e else None,
          "| combo", combo_final, "vs", combo_hold)

fold_wins = 0
for y in range(2018, 2026):
    s, e = f"{y}-01-01", f"{y}-12-31"
    r = run_pot(BTC, s, e); h = hold(BTC, s, e)
    win = r["final"] > h["final"]; fold_wins += win
    out["folds"][str(y)] = {"btc_pot": r["final"], "btc_hold": h["final"],
                            "max_dd_pct": max_dd(r["curve"]), "beats_hold": win}
    print("fold", y, r["final"], "vs", h["final"], win)
out["folds_beating_hold"] = f"{fold_wins}/8"
(HERE/"results.json").write_text(json.dumps(out, indent=1))
print("folds beating hold:", fold_wins, "/8")
