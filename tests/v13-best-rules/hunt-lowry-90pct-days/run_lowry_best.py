#!/usr/bin/env python3
"""Lowry 90% Days — v13 BEST RULES (spec frozen in BEST-RULES-SPEC.md before run).
Changes vs v12 construction, and only these:
  (1) DECLINE GATE: a 90% Downside Day arms only if SPY close that day is
      >=10% below its trailing 252-session high close (point-in-time).
  (2) NO floor form only (spec section 7).
Everything else identical to v12: constructed totals from the pond stack
(split-adjusted changes, volume split by sign), both shares required,
arm 90 calendar days, confirmation = 90% Up Day or two consecutive 80% Up
Days while armed, entry SPY next open all-in, exit at open of first session
after the 12-month anniversary, fresh cycles while holding ignored.
Costs 0.10%/side + $0.01 sell fee. Placebos: random-timing, 20 seeds/road,
entry count matched, same 12-month holds and cash default."""
import json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

def dplus(ds, days):
    y, m, d = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    return str(date(y, m, d) + timedelta(days=days))

def build_totals(spy):
    dates = [b["d"] for b in spy]
    series = {}
    for p in sorted(glob.glob(os.path.join(STKDATA, "pxfull_*.json"))):
        t = os.path.basename(p)[7:-5]
        if t == "SPY": continue
        bars = load_stock(t)
        series[t] = {b["d"]: b for b in bars}
    totals = []
    for k in range(1, len(dates)):
        d, prev = dates[k], dates[k-1]
        uv = dv = pg = pl = 0.0; n = 0
        for t, m in series.items():
            if d in m and prev in m:
                chg = m[d]["c"] - m[prev]["c"]; vol = m[d]["v"] or 0
                n += 1
                if chg > 0: uv += vol; pg += chg
                elif chg < 0: dv += vol; pl += -chg
        if uv + dv > 0 and pg + pl > 0:
            totals.append({"d": d, "up_vol_share": uv/(uv+dv), "pts_gain_share": pg/(pg+pl), "n": n})
    return totals

def decline_gate(spy):
    """date -> True if close >=10% below trailing 252-session high close (incl. today)."""
    closes = [b["c"] for b in spy]; out = {}
    for i, b in enumerate(spy):
        hi = max(closes[max(0, i-251):i+1])
        out[b["d"]] = (b["c"] <= 0.90 * hi)
    return out

def find_entries(totals, gate):
    entries = []; arm_dates = []
    arm_until = None; prev80 = False
    for t in totals:
        down90 = t["up_vol_share"] <= 0.10 and t["pts_gain_share"] <= 0.10
        up90 = t["up_vol_share"] >= 0.90 and t["pts_gain_share"] >= 0.90
        up80 = t["up_vol_share"] >= 0.80 and t["pts_gain_share"] >= 0.80
        if down90 and gate.get(t["d"], False):
            arm_until = dplus(t["d"], 90); arm_dates.append(t["d"])
        armed = arm_until is not None and t["d"] <= arm_until
        if armed and (up90 or (up80 and prev80)):
            entries.append(t["d"]); arm_until = None; prev80 = False; continue
        prev80 = up80
    return entries, arm_dates

def simulate(spy, entries):
    idx = {b["d"]: i for i, b in enumerate(spy)}
    execs = sorted({idx[d] + 1 for d in entries if d in idx and idx[d] + 1 < len(spy)})
    eq = START; curve = []; costs = 0.0; orders = 0; trades = []
    pos = None; ei = 0; ex_i = 0; invested = 0
    for i, b in enumerate(spy):
        if pos is not None:
            invested += 1
            if b["d"] > dplus(spy[ei]["d"], 365):
                gross = pos * b["o"]; cst = gross * STK_COST + STK_FEE; costs += cst
                trades.append([spy[ei]["d"], b["d"], round(gross - cst, 2)]); eq = gross - cst; pos = None; orders += 1
        if pos is None:
            while ex_i < len(execs) and execs[ex_i] < i: ex_i += 1
            if ex_i < len(execs) and execs[ex_i] == i:
                cst = eq * STK_COST; costs += cst; pos = (eq - cst) / b["o"]; ei = i; orders += 1
        val = pos * b["c"] if pos else eq
        curve.append([b["d"], round(val, 4)])
    if pos is not None:
        gross = pos * spy[-1]["c"]; cst = gross * STK_COST + STK_FEE; costs += cst
        eq = gross - cst; trades.append([spy[ei]["d"], spy[-1]["d"], round(eq, 2)])
        curve[-1][1] = round(eq, 4)
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    return {"final": round(eq, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "trades": trades, "curve": curve,
            "invested_frac": round(invested / len(spy), 3) if spy else 0.0}

def main():
    spy = load_stock("SPY")
    totals = build_totals(spy)
    gate = decline_gate(spy)
    entries, arm_dates = find_entries(totals, gate)
    n_down90_gated = len(arm_dates)
    res = {"family": "hunt-lowry-90pct-days", "program": "v13-best-rules",
           "n_names_in_stack": totals[0]["n"] if totals else 0,
           "gated_arm_dates_all_history": arm_dates,
           "confirmation_dates_all_history": entries,
           "roads": {}}
    print("gated arms:", arm_dates, flush=True)
    print("confirmations:", entries, flush=True)
    champ_beaten = []
    for road, s0 in ROADS.items():
        rb = slice_road(spy, s0, END)
        ents = [d for d in entries if s0 <= d <= END]
        r = simulate(rb, ents)
        # random-timing placebos, 20 seeds, count matched
        beaten = 0; twins = []
        cand = [b["d"] for b in rb[:-260]]
        for s in range(1, 21):
            rng = random.Random(1300 + s)
            picks = sorted(rng.sample(cand, len(ents))) if ents else []
            rr = simulate(rb, picks)
            twins.append(rr["final"]); beaten += 1 if r["final"] > rr["final"] else 0
        res["roads"][road] = {"best_rules": r, "hold": hold_final(rb),
                              "n_entries": len(ents),
                              "entry_dates": ents,
                              "period_stats_monthly": period_stats(r["curve"]),
                              "placebo_random_timing": {"beaten_of_20": beaten, "twin_finals": twins}}
        print(road, "final", r["final"], "dd", r["max_dd"], "entries", len(ents),
              "placebo beaten", beaten, "/20", flush=True)
        if r["final"] > CHAMP[road]: champ_beaten.append(road)
    res["champion_beaten_roads"] = champ_beaten

    if champ_beaten:
        # Terry confirmation, bars frozen in spec section 10:
        # (a) yearly folds: pot starts Jan 1 of each year OUTSIDE the beaten
        #     road's span, runs 3 calendar years, liquidates at fold end.
        # (b) half-windows: road split at midpoint; each half must beat the
        #     champion final scaled by that half's SPY-hold ratio / full-road
        #     SPY-hold ratio (pro-rata pace as defined in the spec).
        conf = {}
        spans = {"LONG": (2010, 2026), "DECADE": (2016, 2026), "CONT": (2019, 2026), "VAL": (2023, 2026)}
        for road in champ_beaten:
            s0 = ROADS[road]; rb = slice_road(spy, s0, END)
            folds = {}
            y0, y1 = spans[road]
            for Y in range(2010, 2027):
                if y0 <= Y <= y1: continue
                fs, fe = f"{Y}-01-01", f"{Y+2}-12-31"
                fb = slice_road(spy, fs, fe)
                if len(fb) < 500: continue
                fents = [d for d in entries if fs <= d <= fe]
                fr = simulate(fb, fents)
                folds[str(Y)] = {"final": fr["final"], "max_dd": fr["max_dd"],
                                 "spy_hold": hold_final(fb), "n_entries": len(fents)}
            mid = rb[len(rb)//2]["d"]
            halves = {}
            full_spy = hold_final(rb)
            for name, (hs, he) in {"first": (s0, mid), "second": (mid, END)}.items():
                hb = slice_road(spy, hs, he)
                hents = [d for d in entries if hs <= d <= he]
                hr = simulate(hb, hents)
                pace = CHAMP[road] * ((hold_final(hb) or 100.0) / (full_spy or 100.0))
                halves[name] = {"final": hr["final"], "max_dd": hr["max_dd"],
                                "champion_prorata_pace": round(pace, 2),
                                "beats_pace": hr["final"] > pace, "n_entries": len(hents)}
            conf[road] = {"yearly_folds_outside_span": folds, "half_windows": halves}
        res["terry_confirmation"] = conf
        print("CONFIRMATION RUN:", json.dumps(conf, indent=1), flush=True)

    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
