#!/usr/bin/env python3
"""V10 CONFIRMATION RUN — N-PV1 THE STANDING BID, ANNUAL cadence.
Terry's confirmation rule (2026-11-21 ~22:19): a flipped verdict is not
crowned until its money cadence is re-run on the OTHER roads.

Adapted from the sweep script (../sweep.py, copied here as
sweep_base.py) with ONLY these changes: the road window is a parameter
instead of the fixed DECADE globals, and the cadence is fixed to
ANNUAL. Strategy mechanics, score, costs (0.10%/side + $0.01/sell),
$100 start, and the v9 two-episode protection wrapper are byte-for-byte
the sweep's logic. Simulation only.

Roads: LONG 2010-01-04->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20, plus a DECADE sanity re-run that must
reproduce the sweep's annual cell ($440.48, placebo 13/20) before any
other number is trusted, plus fresh calendar-year folds 2017-2026
(standalone, fresh $100 each). Placebos: original design — random 5
from the same cadence date's eligible set, seeds 1..20, same v9
wrapper, per road (not per fold).
"""
import importlib.util, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv1", os.path.join(PARENT, "integrity", "novel-pv1-standing-bid.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(PARENT, "pxfull_GOOGL.json")))
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
GIDX = {d: i for i, d in enumerate(CAL)}
SPYBAR = BAR["SPY"]

def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    o = SPYBAR[days[0]]["o"]; sh = (cash/1.001)/o
    val = sh * SPYBAR[days[-1]]["c"]
    return round(val - (val*0.001 + 0.01), 2)

def annual_dates(days):
    firsts, seen = [], set()
    for d in days:
        if d[:4] not in seen:
            seen.add(d[:4]); firsts.append(d)
    return firsts

def close_val(t, d, sh):
    i = IDX[t].get(d)
    if i is None:
        import bisect
        ds = [b["d"] for b in BARS[t]]
        j = bisect.bisect_right(ds, d) - 1
        return sh * BARS[t][j]["c"] if j >= 0 else 0.0
    return sh * BARS[t][i]["c"]

def run_episode(cash0, floor, from_d, end, days_all, cad_set, picker, stats):
    days = [d for d in days_all if from_d <= d <= end]
    cash = cash0; positions = {}; trades = []; costs = 0.0
    curve = []; halted = None
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
            stats["rotations"] += 1
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

def run_v9(start, end, picker):
    days_all = [d for d in CAL if start <= d <= end]
    cad_set = set(annual_dates(days_all))
    stats = {"rotations": 0}
    r1 = run_episode(100.0, 85.0, start, end, days_all, cad_set, picker, stats)
    eps = [r1]; halts = []
    if r1["halted"]: halts.append({"episode": 1, "signal_date": r1["halted"],
                                   "liquidation_date": r1["end"],
                                   "proceeds": r1["final"]})
    restart = None; second_halt = False
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            first = next((d for d in sorted(cad_set) if d >= elig), None)
            if first:
                r2 = run_episode(r1["final"], 0.85*r1["final"], elig, end,
                                 days_all, cad_set, picker, stats)
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
        for d in days_all:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days/365.25
    fin = eps[-1]["final"]
    return {"final": fin,
            "cagr_pct": round(((fin/100.0)**(1.0/yrs) - 1.0)*100, 2),
            "max_dd_pct": round(maxdd*100, 2),
            "halts": halts, "restart": restart, "second_halt": second_halt,
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(e["orders"] for e in eps),
            "rotations": stats["rotations"],
            "curve": [[d, v] for d, v in curve]}

def ranked(scores):
    return sorted(scores, key=lambda t: -scores[t])[:M.TOP_N]

def run_road(name, start, end, with_placebos=True):
    r = run_v9(start, end, ranked)
    spy = spy_net(start, end)
    out = {"road": name, "cadence": "annual", "start": start, "end": end,
           "final": r["final"], "cagr_pct": r["cagr_pct"],
           "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
           "orders": r["orders"], "rotations": r["rotations"],
           "halts": r["halts"], "restart": r["restart"],
           "second_halt": r["second_halt"],
           "spy_final": spy, "beat_spy": r["final"] > spy,
           "equity_curve": r["curve"]}
    if with_placebos:
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            def pp(scores, rng=rng):
                elig = sorted(scores)
                return rng.sample(elig, min(M.TOP_N, len(elig)))
            pr = run_v9(start, end, pp); finals.append(pr["final"])
        out["placebo_finals"] = finals
        out["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        srt = sorted(finals)
        out["placebo_median"] = round(srt[9]*0.5 + srt[10]*0.5, 2)
    print(name, start, "->", end, "final", r["final"], "SPY", spy,
          "orders", r["orders"], "rotations", r["rotations"],
          "halts", len(r["halts"]),
          "placebo", out.get("placebo_beaten"), "/20", flush=True)
    return out

# ---- DECADE sanity: must reproduce the sweep's annual cell exactly
dec = run_road("DECADE_check", "2016-11-21", "2026-11-20")
sweep_cell = json.load(open(os.path.join(PARENT, "cells", "annual.json")))
ok = (dec["final"] == sweep_cell["final"]
      and dec["placebo_finals"] == sweep_cell["placebo_finals"]
      and dec["costs"] == sweep_cell["costs"]
      and dec["orders"] == sweep_cell["orders"])
dec["sweep_annual_cell_final"] = sweep_cell["final"]
dec["reproduces_sweep"] = ok
json.dump(dec, open(os.path.join(HERE, "decade_check.json"), "w"), indent=1)
print("DECADE SANITY reproduces_sweep =", ok, flush=True)
if not ok:
    raise SystemExit("PLUMBING MISMATCH vs sweep annual cell — stopping, "
                     "no confirmation numbers trusted")

# ---- confirmation roads
for name, s, e in [("LONG", "2010-01-04", "2026-11-20"),
                   ("CONT", "2019-01-02", "2026-11-20"),
                   ("VAL", "2023-01-03", "2026-11-20")]:
    out = run_road(name, s, e)
    json.dump(out, open(os.path.join(HERE, f"{name}.json"), "w"), indent=1)

# ---- fresh yearly folds 2017-2026, annual cadence, fresh $100
folds = {}
for y in range(2017, 2027):
    ydays = [d for d in CAL if d[:4] == str(y) and d <= "2026-11-20"]
    s, e = ydays[0], ydays[-1]
    r = run_v9(s, e, ranked)
    spy = spy_net(s, e)
    folds[str(y)] = {"year": y, "start": s, "end": e,
                     "final": r["final"], "cagr_pct": r["cagr_pct"],
                     "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                     "orders": r["orders"], "rotations": r["rotations"],
                     "halts": r["halts"], "restart": r["restart"],
                     "second_halt": r["second_halt"],
                     "spy_final": spy,
                     "beat_spy": r["final"] > spy,
                     "beat_100": r["final"] > 100.0,
                     "equity_curve": r["curve"]}
    print("FOLD", y, s, "->", e, "final", r["final"], "SPY", spy,
          "orders", r["orders"], "rotations", r["rotations"],
          "halts", len(r["halts"]), flush=True)
json.dump(folds, open(os.path.join(HERE, "folds.json"), "w"), indent=1)
print("DONE")
