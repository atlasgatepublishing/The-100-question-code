#!/usr/bin/env python3
"""V10 AREA RUN — N-3 QUARTER-END WINDOW-DRESSING REBOUND (event-driven,
quarter-end calendar). Simulation only. Event treatment: per-event
mean basket return over the longest window (the engine's own event
record: basket_gross_pct vs spy_gross_pct per event, gross of pot
costs; the net effect lives in the cycled pot) PLUS the cycled
full-road runs. Data: long-run pxfull payloads (read-only) in the
champion bar construction the engine expects; GOOGL from the
slug-local pxfull_GOOGL.json. Protection: v9 via the engine's
START_CASH/FLOOR0 globals; episode 2 takes the first event whose
entry day (close of L) is on/after halt+90 days — the rule's next
regular decision point. Placebos: original design (uniform 5 from the
same quarter's rankable set, seeds 1..20) under the same v9 wrapper,
CONT+VAL.
"""
import importlib.util, json, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x3", os.path.join(HERE, "integrity", "novel-x3-window-dressing.py"))
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
BX = M.Bars(BARS)
CAL = [b["d"] for b in BARS["SPY"]]
ALL_EVENTS = M.build_events(CAL)

def spy_net(start, end, cash=100.0):
    s, _ = E.spy_net(PB, start, end, cash)
    return round(s, 2)

def run_once(start, end, events, picker, cash, floor):
    M.START_CASH = cash; M.FLOOR0 = floor
    r = M.simulate(BX, CAL, start, end, events, picker, label="run")
    M.START_CASH = 100.0; M.FLOOR0 = 85.0
    return r

def run_v9(start, end, picker, ev_filter):
    evs = [e for e in ALL_EVENTS if ev_filter(e, start, end)]
    r1 = run_once(start, end, evs, picker, 100.0, 85.0)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            evs2 = [e for e in ALL_EVENTS if e["L"] >= elig and e["exit"] <= end]
            r2 = run_once(elig, end, evs2, picker, r1["final"], 0.85*r1["final"])
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
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": round(maxdd*100, 2),
            "worst_close": round(worst[1], 2),
            "events": eps[0]["events"], "curve": curve}

def ev_in(e, s, en): return s <= e["exit"] <= en

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-x3-window-dressing", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, M.ranked_picker, ev_in)
    evs = r.pop("events"); r.pop("curve")
    traded = [ev for ev in evs if ev.get("basket_gross_pct") is not None]
    r.update({"start": s, "end": e, "placebo_beaten": None,
              "n_events": len(evs), "n_events_traded": len(traded)})
    if w == "LONG":
        bg = [ev["basket_gross_pct"] for ev in traded]
        sg = [ev["spy_gross_pct"] for ev in traded]
        r["event_stats"] = {
            "n_events": len(traded),
            "mean_basket_gross_pct": round(statistics.mean(bg), 3) if bg else None,
            "median_basket_gross_pct": round(statistics.median(bg), 3) if bg else None,
            "mean_spy_gross_pct": round(statistics.mean(sg), 3) if sg else None,
            "mean_excess_gross_pct": round(statistics.mean(
                [b - s_ for b, s_ in zip(bg, sg)]), 3) if bg else None,
            "events_beat_spy": sum(1 for b, s_ in zip(bg, sg) if b > s_),
            "note": "gross of pot costs per the engine's event record; net effect is in the cycled pot finals"}
    if w in ("CONT", "VAL"):
        finals = []
        for seed in range(1, 21):
            pr = run_v9(s, e, M.make_placebo_picker(seed), ev_in)
            finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "events", r["n_events"],
          "halts", r["halts"], "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
