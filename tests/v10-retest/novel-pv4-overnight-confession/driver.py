#!/usr/bin/env python3
"""V10 AREA RUN — N-PV4 THE OVERNIGHT CONFESSION. Simulation only.
Short-cycle event rule (overnight gap <= -2% with same-day reclaim,
10-trading-day hold) cycled over the full road. Data: long-run pxfull
payloads (read-only) fed through the champion engine's get_prices slot
(the v9 engine's build path); GOOGL from the slug-local
pxfull_GOOGL.json. Protection: v9 wrapper copied from the v9 engine's
main. Placebos: original design (one random non-event pond name per
event, seeds 1..20) under the same v9 wrapper, CONT+VAL — the ep2
placebo redraws names for the ep2 schedule with the same seed stream.
"""
import importlib.util, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv4", os.path.join(HERE, "integrity", "novel-pv4-overnight-confession.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
E = M.E

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

BARS = {t: pxfull(t) for t in M.UNIVERSE + ["SPY"]}
PB = E.PriceBook(BARS)
EVENTS = M.scan_events(BARS)
CAL = PB.dates
SPYB = {b["d"]: b for b in BARS["SPY"]}

def spy_net(start, end, cash=100.0):
    s, _ = E.spy_net(PB, start, end, cash)
    return round(s, 2)

def run_v9(start, end, names_fn):
    """names_fn(sched, rng_stream) -> names list per schedule build."""
    sched = M.window_events(EVENTS, PB, start, end)
    r1 = M.run_event_pot(PB, BARS, sched, start, end,
                         names_fn(sched), label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            sched2 = M.window_events(EVENTS, PB, elig, end)
            r2 = M.run_event_pot(PB, BARS, sched2, elig, end,
                                 names_fn(sched2), label="ep2",
                                 start_cash=r1["final"], floor=0.85*r1["final"])
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
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "curve": sorted(curve.items()),
            "events_taken": sum(len(e["taken"]) for e in eps)}

def diag(curve):
    peak, maxdd = -1.0, 0.0; worst = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak-v)/peak if peak > 0 else 0)
    return round(maxdd*100, 2), worst

def per_year(curve):
    ye = {}
    for d, v in curve: ye[d[:4]] = v
    spy_ye = {}
    for d in CAL: spy_ye[d[:4]] = SPYB[d]["c"]
    out = {}; prev = 100.0; beats = 0
    for y in sorted(ye):
        spy_prev = spy_ye.get(str(int(y)-1))
        pr = ye[y]/prev - 1
        sr = (spy_ye[y]/spy_prev - 1) if spy_prev else None
        beat = sr is not None and pr > sr; beats += bool(beat)
        out[y] = {"pot_year_end": round(ye[y], 2), "pot_ret_pct": round(pr*100, 2),
                  "spy_ret_pct": round(sr*100, 2) if sr is not None else None,
                  "beat_spy": beat}
        prev = ye[y]
    return out, beats

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-pv4-overnight-confession", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, lambda sched: [ev["ticker"] for ev in sched])
    maxdd, worst = diag(r["curve"])
    curve = r.pop("curve")
    r.update({"start": s, "end": e, "max_dd_pct": maxdd,
              "worst_close": round(worst[1], 2), "placebo_beaten": None})
    if w == "LONG":
        py, beats = per_year(curve); r["per_year"] = py
        r["years_beat_spy"] = beats
        r["n_years_scored"] = sum(1 for v in py.values() if v["spy_ret_pct"] is not None)
    if w in ("CONT", "VAL"):
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            def placebo_names(sched, rng=rng):
                return [rng.choice([t for t in M.UNIVERSE if t != ev["ticker"]])
                        for ev in sched]
            pr = run_v9(s, e, placebo_names); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
