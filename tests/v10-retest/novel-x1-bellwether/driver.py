#!/usr/bin/env python3
"""V10 AREA RUN — N-1 BELLWETHER ECHO (cross-stock lead-lag, daily).
Simulation only. Data: long-run pxfull payloads (read-only) fed through
the champion engine's get_prices slot used by the v9 engine's load_book;
GOOGL from the slug-local pxfull_GOOGL.json. Bellwether/follower
designations: the original run's recorded Nov-2016 designations
(unchanged). Protection: v9 wrapper copied from the v9 engine's main.
Placebos: original design (same cluster counts, random followers from
the same clusters, seeds 1..20) under the same v9 wrapper, CONT+VAL.
run_pot is exec'd from the engine's own source with one plumbing
addition: its internal daily curve is included in the return dict
(logic byte-identical) so per-year scoring is possible.
"""
import importlib.util, inspect, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x1", os.path.join(HERE, "integrity", "novel-x1-bellwether.py"))
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

M.champ.get_prices = pxfull
PB, BARS = M.load_book()
SPY_DATES, RET = M.build_returns(BARS)
_orig = json.load(open(os.path.join(
    BT, "v8", "novel-x1-bellwether", "bellwether-echo-results.json")))
BEL = _orig["bellwethers"]; FOL = _orig["followers"]
SPYB = {b["d"]: b for b in BARS["SPY"]}

src = inspect.getsource(M.run_pot)
src = src.replace('"max_drawdown_pct": round(maxdd * 100, 2), "trades": trades}',
                  '"max_drawdown_pct": round(maxdd * 100, 2), "trades": trades, "curve": curve}')
ns = dict(M.__dict__)
exec(compile(src, "run_pot_curve", "exec"), ns)
RUN = ns["run_pot"]

def spy_net(start, end, cash=100.0):
    s, _ = M.champ.spy_net(PB, start, end, cash)
    return round(s, 2)

RANKED = lambda e: [p["ticker"] for p in e["picks"]]

def run_v9(start, end, pick_fn):
    days = [d for d in SPY_DATES if start <= d <= end]
    events = M.scan_events(days, RET, BEL, FOL)
    r1 = RUN(PB, days, events, pick_fn, label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            days2 = [d for d in SPY_DATES if elig <= d <= end]
            events2 = M.scan_events(days2, RET, BEL, FOL)
            r2 = RUN(PB, days2, events2, pick_fn, label="ep2",
                     start_cash=float(r1["final"]), floor=0.85*float(r1["final"]))
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": r1["final"], "eligibility": elig,
                       "episode2_floor": round(0.85*float(r1["final"]), 2),
                       "second_halt": r2["halted"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        for d in SPY_DATES:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = float(eps[0]["final"])
    last = eps[-1]
    return {"final": last["final"],
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(e["orders"] for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": max(e["max_drawdown_pct"] for e in eps),
            "events_executed": sum(e["events_executed"] for e in eps),
            "curve": sorted(curve.items())}

def per_year(curve):
    ye = {}
    for d, v in curve: ye[d[:4]] = v
    spy_ye = {}
    for d in SPY_DATES: spy_ye[d[:4]] = SPYB[d]["c"]
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
out = {"slug": "novel-x1-bellwether", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, RANKED)
    curve = r.pop("curve")
    r.update({"start": s, "end": e, "placebo_beaten": None})
    if w == "LONG":
        py, beats = per_year(curve); r["per_year"] = py
        r["years_beat_spy"] = beats
        r["n_years_scored"] = sum(1 for v in py.values() if v["spy_ret_pct"] is not None)
    if w in ("CONT", "VAL"):
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            def placebo_picks(ev, rng=rng):
                picks = []
                for c, k in ev["cluster_counts"].items():
                    picks.extend(rng.sample(sorted(FOL[c]), k))
                return picks
            pr = run_v9(s, e, placebo_picks); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
