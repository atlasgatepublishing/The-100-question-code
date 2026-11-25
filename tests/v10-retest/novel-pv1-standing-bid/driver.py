#!/usr/bin/env python3
"""V10 AREA RUN — N-PV1 THE STANDING BID. Simulation only.
Area: short-cycle (monthly shadow-share rotation) cycled over the full road.
Data: long-run-2010 pxfull payloads (read-only, v7/long-hold cache),
champion ratio construction incl. H/L. Universe = original champion
UNIVERSE (Nov-2016 honest top-30) — unchanged. GOOGL payload = pxfull_GOOG
(class history Yahoo serves under GOOG; documented artifact).
Protection: v9 (plain -15% floor, 90-day sit-out, one restart, ep2 floor
-15% of restart balance). Placebos: original design (random 5 from the
same month's eligible set, seeds 1..20) under the same v9 wrapper,
on CONT and VAL.
"""
import importlib.util, json, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
sys.path.insert(0, os.path.join(HERE, "integrity"))
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
        bars.append({"d": d, "o": o*r, "h": h*r, "l": l*r, "c": a,
                     "v": q["volume"][i]})
    bars.sort(key=lambda b: b["d"]); return bars

BARS = {t: pxfull(t) for t in M.UNIVERSE + ["SPY"]}
CAL = sorted({b["d"] for bl in BARS.values() for b in bl})
SPY = {b["d"]: b for b in BARS["SPY"]}

def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    o = SPY[days[0]]["o"]; sh = (cash/1.001)/o
    val = sh * SPY[days[-1]]["c"]
    return round(val - (val*0.001 + 0.01), 2)

def run_v9(start, end, picker):
    M.START_CASH = 100.0; M.FLOOR0 = 85.0
    r1 = M.run_rotation(BARS, CAL, start, end, picker, label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            M.START_CASH = r1["final"]; M.FLOOR0 = 0.85 * r1["final"]
            r2 = M.run_rotation(BARS, CAL, elig, end, picker, label="ep2")
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85*r1["final"], 2),
                       "second_halt": r2["halted"]}
    M.START_CASH = 100.0; M.FLOOR0 = 85.0
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        f = eps[0]["final"]
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]: curve[d] = f
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "curve": sorted(curve.items())}

def diag(curve):
    peak, maxdd = -1.0, 0.0; worst = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    return round(maxdd*100, 2), worst

def per_year(curve):
    ye = {}
    for d, v in curve: ye[d[:4]] = v
    spy_ye = {}
    for d in CAL: spy_ye[d[:4]] = SPY[d]["c"]
    out = {}; prev = 100.0; prev_spy = None; beats = 0
    for y in sorted(ye):
        spy_prev = spy_ye.get(str(int(y)-1))
        pr = ye[y]/prev - 1 if prev else None
        sr = ye[y] and (spy_ye[y]/spy_prev - 1) if spy_prev else None
        beat = (pr is not None and sr is not None and pr > sr)
        beats += bool(beat)
        out[y] = {"pot_year_end": round(ye[y], 2),
                  "pot_ret_pct": round(pr*100, 2) if pr is not None else None,
                  "spy_ret_pct": round(sr*100, 2) if sr is not None else None,
                  "beat_spy": beat}
        prev = ye[y]
    return out, beats

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-pv1-standing-bid", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, M.ranked_picker)
    maxdd, worst = diag(r["curve"])
    r.update({"start": s, "end": e, "max_dd_pct": maxdd,
              "worst_close": round(worst[1], 2), "placebo_beaten": None})
    if w == "LONG":
        py, beats = per_year(r["curve"]); r["per_year"] = py
        r["years_beat_spy"] = beats; r["n_years_scored"] = \
            sum(1 for v in py.values() if v["spy_ret_pct"] is not None)
    if w in ("CONT", "VAL"):
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            def pp(d, scores, rng=rng):
                elig = sorted(scores)
                return rng.sample(elig, min(M.TOP_N, len(elig)))
            pr = run_v9(s, e, pp); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        r["placebo_median"] = round(sorted(finals)[10], 2)
    r.pop("curve")
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
