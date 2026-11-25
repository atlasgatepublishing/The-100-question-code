#!/usr/bin/env python3
"""Granville OBV pond basket (companion to run_obv.py).
Frozen construction: per-name OBV timer states (see run_obv.py
obv_states), equal-weight basket, max N names, ranked by fewest days
since entry signal (CONSTRUCTED ranking).
IMPLEMENTATION CONVENTION (documented debugging fix, 2026-11-22): the
ranking is applied at ADMISSION — a name holds its slot until its own
timer exits; vacancies are filled by the freshest waiting signal.
The first implementation re-ranked the whole basket daily, evicting
incumbents for fresher signals; that reading manufactured ~2
trades/day of pure ranking churn and incinerated >99.9% of the pot in
costs at every count — an artifact of the ranking's implementation,
not of Granville's signal. The slot reading is the standard timer-
basket mechanics and is what is reported. Rebalancing to equal
weights happens on membership-change days only; weights drift
between changes. Program costs on all trades. NATIVE no floor;
HOUSE v9 floor (liquidate all, 63-trading-day sit-out, one restart,
second halt ends) at daily closes. Placebos: 20 seeds, each name's
state series circularly shifted by a seeded number of days.
Simulation only."""
import json, os, sys, glob, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, period_stats, ROADS
from run_obv import obv_states

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")

def build():
    spy = load_bars(os.path.join(PXDIR, "pxfull_SPY.json"))
    cal = [b["d"] for b in spy]
    maps = {}
    for p in sorted(glob.glob(os.path.join(PXDIR, "pxfull_*.json"))):
        t = os.path.basename(p)[7:-5]
        if t == "SPY": continue
        bars = load_bars(p)
        if len(bars) < 300: continue
        st, sn = obv_states(bars)
        maps[t] = ({b["d"]: b["c"] for b in bars},
                   {bars[i]["d"]: st[i] for i in range(len(bars))},
                   {bars[i]["d"]: sn[i] for i in range(len(bars))},
                   [b["d"] for b in bars])
    return cal, maps

def shifted_maps(maps, seed):
    rng = random.Random(seed)
    out = {}
    for t, (pxm, stm, snm, dl) in maps.items():
        sh = rng.randint(30, 300)
        n = len(dl)
        st2 = {}; sn2 = {}
        for j, d in enumerate(dl):
            src = dl[j - sh] if j - sh >= 0 else dl[n + (j - sh)]
            st2[d] = stm[src]; sn2[d] = snm[src]
        out[t] = (pxm, st2, sn2, dl)
    return out

def run(cal, maps, maxn, start, end, form="native"):
    days = [d for d in cal if start <= d <= end]
    cash = 100.0; held = {}; lastpx = {}
    curve = []; trades = 0; costs = 0.0
    anchor = 100.0; halts = 0; sitout = 0; ended = False
    for d in days:
        for t in list(held):
            c = maps[t][0].get(d, lastpx.get(t))
            if c is not None and lastpx.get(t): held[t] *= c / lastpx[t]
            if c is not None: lastpx[t] = c
        eq = cash + sum(held.values())
        force = False
        if form == "house":
            if ended or sitout > 0:
                force = True
                if sitout > 0:
                    sitout -= 1
                    if sitout == 0 and not ended: anchor = eq
            elif held and eq <= 0.85 * anchor:
                force = True; halts += 1
                if halts >= 2: ended = True
                else: sitout = 63
        changed = False
        if force:
            for t in list(held):
                dv = held[t]; c = dv * 0.001 + 0.01
                costs += c; trades += 1; cash += dv - c; del held[t]
            changed = True
        else:
            # exits: own timer flipped off
            for t in list(held):
                if maps[t][1].get(d, 0) != 1:
                    dv = held[t]; c = dv * 0.001 + 0.01
                    costs += c; trades += 1; cash += dv - c; del held[t]
                    changed = True
            # admissions: freshest waiting signals fill free slots
            free = maxn - len(held)
            if free > 0:
                cand = []
                for t, (pxm, stm, snm, dl) in maps.items():
                    if t in held or d not in stm: continue
                    if stm[d] == 1:
                        cand.append((snm[d] if snm[d] is not None else 9999, t))
                cand.sort()
                for _, t in cand[:free]:
                    held[t] = 0.0
                    if d in maps[t][0]: lastpx[t] = maps[t][0][d]
                    changed = True
            if changed and held:
                # rebalance to equal weights
                eq = cash + sum(held.values())
                tw = eq / len(held)
                for t in list(held):
                    if held[t] > tw + 0.01:
                        dv = held[t] - tw; c = dv * 0.001 + 0.01
                        costs += c; trades += 1; cash += dv - c; held[t] = tw
                for t in list(held):
                    if tw > held[t] + 0.01:
                        dv = min(tw - held[t], cash)
                        if dv <= 0.01: continue
                        c = dv * 0.001; costs += c; trades += 1
                        cash -= dv; held[t] += dv - c
        eq = cash + sum(held.values())
        curve.append([d, round(eq, 4)])
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "halts": halts, "max_dd": round(maxdd, 4)}

def main():
    cal, maps = build()
    print("names", len(maps), flush=True)
    grid = {}
    for maxn in (1, 2, 3, 5, 8, 10):
        grid[str(maxn)] = {}
        for road, (s, e) in ROADS.items():
            ent = {}
            for form in ("native", "house"):
                r = run(cal, maps, maxn, s, e, form)
                ent[form] = {k: v for k, v in r.items() if k != "curve"}
                ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
                if form == "native" and maxn == 10: ent["curve_native"] = r["curve"]
            grid[str(maxn)][road] = ent
        print("grid", maxn, {r: grid[str(maxn)][r]["native"]["final"] for r in ROADS}, flush=True)
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    pl = {}
    for road in ("LONG", "VAL"):
        s, e = ROADS[road]; fs = []
        for seed in range(1, 21):
            sm = shifted_maps(maps, seed)
            fs.append(run(cal, sm, 10, s, e, "native")["final"])
        sysf = grid["10"][road]["native"]["final"]
        pl[road] = {"finals": fs, "median": round(statistics.median(fs), 2),
                    "system_native_final": sysf,
                    "beats": sum(1 for f in fs if sysf > f)}
        print("placebo", road, pl[road], flush=True)
    json.dump({"basket_grid": grid, "basket_placebos": pl},
              open(os.path.join(HERE, "basket_results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
