#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-PV1 THE STANDING BID, DECADE road
2016-11-21 -> 2026-11-20. Simulation only.

Uniform operational cadence (SPEC): signal evaluation, selection and
trading happen ONLY on cadence dates. Adaptation for this rotation
rule, stated plainly: on each cadence date the shadow-share score is
computed from the trailing 20 trading days through the PRIOR close
(no lookahead), the pot fully rotates at that date's open toward
1/5-of-prior-close-value targets — exactly the native mechanics with
the month-end signal day replaced by the cadence date. At the monthly
cadence this is the native form (first-of-month open = the open after
the prior month-end signal). The v9 floor stays a daily close check
(it is the adopted protection, not the strategy's tempo).
Costs 0.10%/side + $0.01/sell, $100 start, v9 two-episode protection.
Placebos: original design — random 5 from the same cadence date's
eligible set, seeds 1..20, same v9 wrapper, per cell.
"""
import importlib.util, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv1", os.path.join(HERE, "integrity", "novel-pv1-standing-bid.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    import time
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None or o is None or h is None or l is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o*r, "h": h*r, "l": l*r, "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

BARS = {t: pxfull(t) for t in M.UNIVERSE + ["SPY"]}
CAL = sorted({b["d"] for bl in BARS.values() for b in bl})
IDX = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in BARS.items()}
BAR = {t: {b["d"]: b for b in bl} for t, bl in BARS.items()}
START, END = "2016-11-21", "2026-11-20"
DAYS = [d for d in CAL if START <= d <= END]
GIDX = {d: i for i, d in enumerate(CAL)}

def cadence_dates(name):
    if name == "daily":
        return list(DAYS)
    if name == "biweekly":
        wk = []
        seen = set()
        for d in DAYS:
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key); wk.append(d)
        return wk[::2]
    firsts = []
    seen = set()
    for d in DAYS:
        if name == "weekly":
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
        elif name == "monthly":
            key = d[:7]
        elif name == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1)//3)
        elif name == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
        elif name == "annual":
            key = d[:4]
        if key not in seen:
            seen.add(key); firsts.append(d)
    return firsts

def close_val(t, d, sh):
    i = IDX[t].get(d)
    if i is None:
        import bisect
        ds = [b["d"] for b in BARS[t]]
        j = bisect.bisect_right(ds, d) - 1
        return sh * BARS[t][j]["c"] if j >= 0 else 0.0
    return sh * BARS[t][i]["c"]

def run_episode(cash0, floor, from_d, cad_set, picker):
    days = [d for d in DAYS if from_d <= d <= END]
    cash = cash0; positions = {}; trades = []; costs = 0.0
    curve = []; halted = None
    prev_close_val = cash0
    for k, d in enumerate(days):
        gi = GIDX[d]
        if d in cad_set and gi > 0:
            prev_d = CAL[gi - 1]
            pv = cash + sum(close_val(t, prev_d, sh) for t, sh in positions.items())
            scores = {}
            for t in M.UNIVERSE:
                i = IDX[t].get(prev_d)
                if i is None: continue
                s, nv = M.shadow_score(BARS[t], i)
                if s is not None: scores[t] = s
            picks = picker(scores)
            each = pv / M.TOP_N
            for t in list(positions):
                b = BAR[t].get(d)
                if not b: continue
                val = positions[t] * b["o"]; c = val*0.001 + 0.01
                cash += val - c; costs += c
                trades.append((d, t, "SELL", b["o"], val, c))
                del positions[t]
            for t in picks:
                b = BAR[t].get(d)
                if not b: continue
                buy_val = min(each, cash/1.001)
                if buy_val <= 0.005: continue
                sh = buy_val / b["o"]; c = buy_val*0.001
                cash -= buy_val + c; costs += c
                positions[t] = sh
                trades.append((d, t, "BUY", b["o"], buy_val, c))
        v = cash + sum(close_val(t, d, sh) for t, sh in positions.items())
        curve.append((d, round(v, 4)))
        if v <= floor and k < len(days) - 1:
            halted = d
            nd = days[k + 1]
            for t in list(positions):
                b = BAR[t].get(nd)
                if b:
                    val = positions[t] * b["o"]; c = val*0.001 + 0.01
                    cash += val - c; costs += c
                    trades.append((nd, t, "SELL-HALT", b["o"], val, c))
            positions = {}
            curve.append((nd, round(cash, 4)))
            return {"final": round(cash, 2), "costs": round(costs, 2),
                    "orders": len(trades), "halted": halted, "curve": curve,
                    "end": nd}
    last = days[-1]
    for t in list(positions):
        b = BAR[t].get(last)
        if b:
            val = positions[t] * b["c"]; c = val*0.001 + 0.01
            cash += val - c; costs += c
            trades.append((last, t, "SELL-END", b["c"], val, c))
    return {"final": round(cash, 2), "costs": round(costs, 2),
            "orders": len(trades), "halted": None, "curve": curve,
            "end": last}

def run_v9(cad_set, picker):
    r1 = run_episode(100.0, 85.0, START, cad_set, picker)
    eps = [r1]; halts = []
    if r1["halted"]: halts.append({"episode": 1, "signal_date": r1["halted"],
                                   "liquidation_date": r1["end"],
                                   "proceeds": r1["final"]})
    restart = None; second_halt = False
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= END:
            first = next((d for d in cad_set if d >= elig), None)
            if first:
                r2 = run_episode(r1["final"], 0.85*r1["final"], elig,
                                 cad_set, picker)
                eps.append(r2)
                restart = {"halt_date": r1["halted"], "eligibility": elig,
                           "restart_balance": r1["final"],
                           "episode2_floor": round(0.85*r1["final"], 2),
                           "episode2_first_curve_date": r2["curve"][0][0] if r2["curve"] else None}
                if r2["halted"]:
                    second_halt = True
                    halts.append({"episode": 2, "signal_date": r2["halted"],
                                  "liquidation_date": r2["end"],
                                  "proceeds": r2["final"]})
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        for d in DAYS:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    yrs = (date.fromisoformat(END) - date.fromisoformat(START)).days/365.25
    fin = eps[-1]["final"]
    return {"final": fin,
            "cagr_pct": round(((fin/100.0)**(1.0/yrs) - 1.0)*100, 2),
            "max_dd_pct": round(maxdd*100, 2),
            "halts": halts, "restart": restart, "second_halt": second_halt,
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(e["orders"] for e in eps),
            "curve": [[d, v] for d, v in curve]}

def ranked(scores):
    return sorted(scores, key=lambda t: -scores[t])[:M.TOP_N]

os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
out_cells = {}
for cad in ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]:
    cs = set(cadence_dates(cad))
    r = run_v9(cs, ranked)
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        def pp(scores, rng=rng):
            elig = sorted(scores)
            return rng.sample(elig, min(M.TOP_N, len(elig)))
        pr = run_v9(cs, pp); finals.append(pr["final"])
    beaten = sum(1 for f in finals if f < r["final"])
    cell = {"cadence": cad, "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "halts": r["halts"],
            "restart": r["restart"], "second_halt": r["second_halt"],
            "costs": r["costs"], "orders": r["orders"],
            "placebo_beaten": beaten,
            "placebo_median": round(sorted(finals)[9]*0.5 + sorted(finals)[10]*0.5, 2),
            "placebo_finals": finals,
            "equity_curve": r["curve"]}
    json.dump(cell, open(os.path.join(HERE, "cells", f"{cad}.json"), "w"), indent=1)
    out_cells[cad] = {k: cell[k] for k in
                      ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                       "second_halt", "costs", "orders", "placebo_beaten")}
    out_cells[cad]["placebo_note"] = "20 seeds, original design (random 5 from same cadence date's eligible set), v9 wrapper"
    print(cad, r["final"], "placebo", beaten, "/20", "halts",
          len(r["halts"]), flush=True)
json.dump(out_cells, open(os.path.join(HERE, "sweep_cells.json"), "w"), indent=1)
print("DONE")
