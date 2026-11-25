#!/usr/bin/env python3
"""Livermore Pivotal Points — v13 BEST RULES (spec frozen in
BEST-RULES-SPEC.md before this run). Changes vs v12 construction ONLY:
(1) NO confirmation wait — entry at the first close above an armed
pivot; (2) NO pyramid — full target weight (current equity/5) at
entry, no adds. Kept verbatim: pivot definition (max close t-252..t-21),
arming (>=20 closes in [0.85*pivot, pivot]), SPY>200d entry gate,
exit on close below original pivot or <=0.90x entry, max 5 concurrent,
rank by breakout strength, costs 0.10%/side + $0.01/sell, NO pot floor.
Placebo: 20-seed circular shift of entry dates (pivots carried), LONG.
Confirmation (yearly folds + half-windows) runs only if a road beats
champion V+M, per the frozen bars in the spec."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *

HERE = os.path.dirname(os.path.abspath(__file__))

def name_events(bars):
    """Breakout events: date -> (pivot, armed_days, strength).
    Armed: last 20 closes in [0.85*piv, piv], piv = max close t-252..t-21.
    Event: first close > pivot while armed. Void if close < 0.85*piv."""
    closes = [b["c"] for b in bars]; n = len(bars)
    ev = {}
    state = "idle"; pivot = None; arm_start = None
    for t in range(n):
        if t < 252: continue
        if state == "idle":
            piv = max(closes[t-252:t-20])
            win = closes[t-20:t]
            if max(win) <= piv and min(win) >= 0.85 * piv:
                state = "armed"; pivot = piv; arm_start = t - 20
        elif state == "armed":
            if closes[t] > pivot:
                ev[bars[t]["d"]] = (pivot, t - arm_start, closes[t] / pivot - 1)
                state = "idle"; pivot = None
            elif closes[t] < 0.85 * pivot:
                state = "idle"; pivot = None
    return ev

def simulate(dates, closes_by, events_by, spy_sma, spy_c, road_start, road_end, ev_shift=0):
    idx = {d: i for i, d in enumerate(dates)}
    days = [d for d in dates if road_start <= d <= road_end]
    ev_by_date = {}
    for sym, ev in events_by.items():
        for d, v in ev.items():
            if ev_shift:
                j = (idx[d] + ev_shift) % len(dates); d = dates[j]
            ev_by_date.setdefault(d, []).append((sym, v))
    cash = START; pos = {}  # sym -> {shares, pivot, entry, cost_basis}
    curve = []; costs = 0.0; orders = 0; entries = 0
    trade_pnls = []  # per closed position, net of its buy+sell costs approx (sell cost exact, buy cost in basis)
    for d in days:
        # exits first
        for sym in list(pos):
            p = pos[sym]; c = closes_by[sym].get(d)
            if c is None: continue
            if c < p["pivot"] or c <= 0.90 * p["entry"]:
                gross = p["shares"] * c; cst = gross * STK_COST + STK_FEE; costs += cst
                cash += gross - cst; orders += 1
                trade_pnls.append(gross - cst - p["basis"]); del pos[sym]
        # entries (full size, no adds)
        if len(pos) < 5:
            gate = spy_sma.get(d) is not None and spy_c.get(d, 0) > spy_sma[d]
            if gate and d in ev_by_date:
                equity = cash + sum(p["shares"] * closes_by[s].get(d, 0) for s, p in pos.items())
                target = equity / 5.0
                cands = sorted(ev_by_date[d], key=lambda x: -x[1][2])
                for sym, (piv, armed_days, strength) in cands:
                    if len(pos) >= 5 or sym in pos: break
                    c = closes_by[sym].get(d)
                    if c is None: continue
                    spend = min(cash, target)
                    if spend < 1.0: break
                    cst = spend * STK_COST; costs += cst
                    cash -= spend  # v13 accounting fix: v12 chassis never debited cash on buys
                    pos[sym] = {"shares": (spend - cst) / c, "pivot": piv, "entry": c,
                                "basis": spend}
                    orders += 1; entries += 1
        val = cash + sum(p["shares"] * closes_by[s].get(d, 0) for s, p in pos.items()
                         if closes_by[s].get(d) is not None)
        curve.append([d, round(val, 4)])
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    wins = sum(1 for x in trade_pnls if x > 0)
    end_open = sum(p["shares"] * closes_by[s].get(days[-1], 0) for s, p in pos.items()) if days else 0.0
    return {"final": round(curve[-1][1], 2) if curve else START, "max_dd": round(maxdd, 4),
            "end_cash": round(cash, 2), "end_open_positions_value": round(end_open, 2),
            "end_open_names": sorted(pos.keys()),
            "costs": round(costs, 2), "orders": orders, "entries": entries,
            "closed_trades": len(trade_pnls),
            "trade_win_rate_secondary": round(wins / len(trade_pnls), 3) if trade_pnls else None,
            "expectancy_per_closed_trade": round(statistics.mean(trade_pnls), 2) if trade_pnls else None,
            "curve": curve}

def main():
    spy = load_stock("SPY")
    dates = [b["d"] for b in spy]
    spy_c = {b["d"]: b["c"] for b in spy}
    sc = [b["c"] for b in spy]; sma200 = {}
    for i, b in enumerate(spy):
        if i >= 199: sma200[b["d"]] = sum(sc[i-199:i+1]) / 200
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    closes_by = {}; events_by = {}
    for t in pond:
        bars = load_stock(t)
        if len(bars) < 400: continue
        m = {}; last = None; bd = {b["d"]: b["c"] for b in bars}
        for d in dates:
            if d in bd: last = bd[d]
            if last is not None: m[d] = last
        closes_by[t] = m; events_by[t] = name_events(bars)
    res = {"family": "hunt-livermore-pivotal", "program": "v13-best-rules",
           "n_names": len(closes_by),
           "n_breakout_events": sum(len(v) for v in events_by.values()), "roads": {}}
    for road, s0 in ROADS.items():
        rn = simulate(dates, closes_by, events_by, sma200, spy_c, s0, END)
        rb = slice_road(spy, s0, END)
        res["roads"][road] = {"best_rules": rn, "spy_hold": hold_final(rb),
                              "champion_vm": CHAMP[road], "spy_ref_program": SPYREF[road],
                              "period_stats_monthly": period_stats(rn["curve"])}
        print(road, "best-rules", rn["final"], "dd", rn["max_dd"], "entries", rn["entries"], flush=True)
    beaten = 0; twins = []
    for s in range(1, 21):
        rng = random.Random(3100 + s); off = rng.randrange(120, 3000)
        rr = simulate(dates, closes_by, events_by, sma200, spy_c, ROADS["LONG"], END, ev_shift=off)
        twins.append(rr["final"]); beaten += 1 if res["roads"]["LONG"]["best_rules"]["final"] > rr["final"] else 0
    res["placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins,
                           "twin_median": round(statistics.median(twins), 2)}
    print("placebo LONG beaten", beaten, "twin median", res["placebo_LONG"]["twin_median"], flush=True)
    # Confirmation, only for champion-beating roads (frozen bars in spec)
    res["confirmation"] = {}
    for road, s0 in ROADS.items():
        fin = res["roads"][road]["best_rules"]["final"]
        if fin <= CHAMP[road]: continue
        days = [d for d in dates if s0 <= d <= END]
        years = sorted(set(d[:4] for d in days))
        folds = []
        for y in years:
            r = simulate(dates, closes_by, events_by, sma200, spy_c, f"{y}-01-01", f"{y}-12-31")
            folds.append({"year": y, "final": r["final"]})
        half = len(days) // 2
        halves = []
        for a, b in ((days[0], days[half-1]), (days[half], days[-1])):
            r = simulate(dates, closes_by, events_by, sma200, spy_c, a, b)
            rb = slice_road(spy, a, b)
            halves.append({"start": a, "end": b, "final": r["final"], "spy_hold": hold_final(rb)})
        med = statistics.median([f["final"] for f in folds])
        pos_share = sum(1 for f in folds if f["final"] > 100) / len(folds)
        passed = (res["placebo_LONG"]["beaten_of_20"] >= 15 if road == "LONG" else True) \
            and med > 100 and pos_share >= 0.6 \
            and all(h["final"] > (h["spy_hold"] or 0) for h in halves)
        res["confirmation"][road] = {"yearly_folds": folds, "fold_median": round(med, 2),
            "share_positive_folds": round(pos_share, 3), "half_windows": halves,
            "confirmed": passed}
        print("confirmation", road, res["confirmation"][road], flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
