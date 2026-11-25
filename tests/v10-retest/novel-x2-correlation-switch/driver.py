#!/usr/bin/env python3
"""V10 AREA RUN — N-2 CORRELATION-REGIME SWITCH (timer treatment).
Simulation only. Monthly regime check (the frozen spec's own cadence):
mean pairwise 60-day correlation across the pond vs the median of all
prior readings; low correlation -> equal-weight pond, high -> SPY.
Data: long-run pxfull payloads (read-only), champion construction;
GOOGL from the slug-local pxfull_GOOGL.json. The original engine's
readings could only start Dec 2016 (its warm-up pull began Aug 2016);
with the full-road data the same 61-close rule produces readings from
early 2010 — a data extension, not a rule change (documented in
RESULTS.md). Protection: v9 via the engine's START_CASH/FLOOR globals.
Placebos: the original's own design (same initial asset, matched flip
count, random flip dates, seeds 1..20) under the same v9 wrapper,
CONT+VAL. Timer scoring: final vs buy-hold SPY, max drawdown vs SPY's,
time in market (POND/SPY/cash days).
"""
import importlib.util, json, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x2", os.path.join(HERE, "integrity", "novel-x2-correlation-switch.py"))
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
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

POND = M.POND
BARS = {t: pxfull(t) for t in POND + ["SPY"]}
CAL = [b["d"] for b in BARS["SPY"]]
CLOSES = {t: {b["d"]: b["c"] for b in bl} for t, bl in BARS.items()}
BOOK = M.Book(BARS, CAL)

# readings from the first month the 61-close rule allows (data extension)
src_readings = M.compute_readings
def compute_readings2010(cal, closes):
    import types
    # same function, with the month gate moved from 2016-12 to 2010-01
    import inspect
    s = inspect.getsource(src_readings).replace('"2016-12"', '"2010-01"')
    ns = dict(M.__dict__); exec(compile(s, "readings2010", "exec"), ns)
    return ns["compute_readings"](cal, closes)
READINGS = compute_readings2010(CAL, CLOSES)
prior = []; REGIME = {}; SCOREABLE = {}
for r in READINGS:
    if prior:
        REGIME[r["date"]] = "POND" if r["C"] <= statistics.median(prior) else "SPY"
    prior.append(r["C"]); SCOREABLE[r["date"]] = r["scoreable"]

def pond_names(d):
    elig = [x for x in SCOREABLE if x <= d]
    return SCOREABLE[max(elig)] if elig else []

def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    o = BARS["SPY"][0]
    by = {b["d"]: b for b in BARS["SPY"]}
    sh = (cash/1.001)/by[days[0]]["o"]
    val = sh * by[days[-1]]["c"]
    return round(val - (val*0.001 + 0.01), 2)

def spy_maxdd(start, end):
    days = [d for d in CAL if start <= d <= end]
    by = {b["d"]: b for b in BARS["SPY"]}
    peak, maxdd = -1.0, 0.0
    for d in days:
        v = by[d]["c"]; peak = max(peak, v)
        maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    return round(maxdd*100, 2)

def run_once(start, end, switches, cash, floor):
    M.START_CASH = cash; M.FLOOR = floor
    r = M.run_pot(BOOK, start, end, switches, pond_names)
    M.START_CASH = 100.0; M.FLOOR = 85.0
    return r

def run_v9(start, end, switches_fn):
    """switches_fn(start,end) -> {date: target} for that episode span."""
    r1 = run_once(start, end, switches_fn(start, end), 100.0, 85.0)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            r2 = run_once(elig, end, switches_fn(elig, end),
                          r1["final"], 0.85*r1["final"])
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85*r1["final"], 2),
                       "second_halt": r2["halted"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0; worst = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    din = {"POND": 0, "SPY": 0, "CASH": 0}
    for ep in eps:
        for k in din: din[k] += ep["days_in"].get(k, 0)
    tot = sum(din.values()) or 1
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "flips": sum(e["flips"] for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": round(maxdd*100, 2),
            "worst_close": round(worst[1], 2),
            "days_in": din,
            "pct_days_invested": round(100.0*(din["POND"]+din["SPY"])/tot, 1),
            "pct_days_pond": round(100.0*din["POND"]/tot, 1),
            "_r1flips": eps[0]["flips"], "_curve": curve}

def ranked_switches(s, e):
    dec = [r["date"] for r in READINGS if s <= r["date"] <= e and r["date"] in REGIME]
    return {d: REGIME[d] for d in dec}

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-x2-correlation-switch", "spy": {}, "runs": {},
       "readings_first": READINGS[0]["date"], "readings_count": len(READINGS)}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, ranked_switches)
    r1flips = r.pop("_r1flips"); r.pop("_curve")
    r.update({"start": s, "end": e, "placebo_beaten": None,
              "spy_max_dd_pct": spy_maxdd(s, e)})
    if w in ("CONT", "VAL"):
        dec0 = [r_["date"] for r_ in READINGS if s <= r_["date"] <= e and r_["date"] in REGIME][0]
        init_asset = REGIME[dec0]
        days = [d for d in CAL if s <= d <= e]
        cand = [d for d in days if d > dec0]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            fdates = sorted(rng.sample(cand, r1flips)) if r1flips else []
            def pswitch(s2, e2, fdates=fdates, init_asset=init_asset, dec0=dec0):
                sw = {}
                if s2 <= dec0 <= e2: sw[dec0] = init_asset
                cur = init_asset
                for fd in fdates:
                    cur = "SPY" if cur == "POND" else "POND"
                    if s2 <= fd <= e2: sw[fd] = cur
                return sw
            pr = run_v9(s, e, pswitch); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "maxDD", r["max_dd_pct"],
          "vs SPY DD", r["spy_max_dd_pct"], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
