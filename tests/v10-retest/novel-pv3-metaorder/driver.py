#!/usr/bin/env python3
"""V10 AREA RUN — N-PV3 RIDING THE METAORDER. Simulation only.
Short-cycle rule (monthly rotation into the 5 highest variance-ratio
names with a non-negative 63-day trend gate) cycled over the full road.
Data: long-run pxfull payloads (read-only) via the v9 engine's
load_bars slot; GOOGL from the slug-local pxfull_GOOGL.json.
Protection: v9 — restart at the first monthly rotation on/after
halt+90 days (the v9 engine's own convention). Placebos: original
design (random names from the same eligible set, seeds 1..20) under
the same v9 wrapper, CONT+VAL.
"""
import importlib.util, json, os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv3", os.path.join(HERE, "integrity", "novel-pv3-metaorder.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def load_bars(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    import datetime as _dt
    for i, t in enumerate(ts):
        d = _dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars
M.load_bars = load_bars

MKT = M.Market(M.UNIVERSE)
CAL = MKT.cal
SPY = {d: MKT.bars["SPY"][d] for d in CAL if d in MKT.bars["SPY"]}

def spy_net(start, end, cash=100.0):
    return round(M.spy_net(MKT, start, end), 2) if cash == 100.0 else None

def next_rotation(elig):
    for j in range(1, len(CAL)):
        if CAL[j] >= elig and CAL[j][:7] != CAL[j-1][:7]:
            return CAL[j]
    return None

def run_v9(start, end, mode, seed=42):
    r1 = M.simulate(MKT, start, end, mode, seed=seed)
    eps = [r1]; restart = None
    if r1.halt_date is not None:
        elig = (date.fromisoformat(r1.halt_date) + timedelta(days=90)).isoformat()
        rot = next_rotation(elig)
        if rot and rot <= end:
            r2 = M.simulate(MKT, rot, end, mode, seed=seed,
                            start_cash=r1.final, floor=0.85*r1.final)
            eps.append(r2)
            restart = {"halt_date": r1.halt_date,
                       "liquidation": round(r1.final, 2),
                       "eligibility": elig, "restart_date": rot,
                       "episode2_floor": round(0.85*r1.final, 2),
                       "second_halt": r2.halt_date}
    curve = {}
    for ep in eps:
        for d, v in ep.equity_curve: curve[d] = v
    if len(eps) > 1:
        for d in CAL:
            if eps[0].equity_curve[-1][0] < d < eps[1].equity_curve[0][0]:
                curve[d] = eps[0].final
    return {"final": round(eps[-1].final, 2),
            "costs": round(sum(e.costs for e in eps), 2),
            "orders": sum(e.orders for e in eps),
            "halts": [e.halt_date for e in eps if e.halt_date],
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
    for d in CAL:
        if d in SPY: spy_ye[d[:4]] = SPY[d][1]
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
out = {"slug": "novel-pv3-metaorder", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, "ranked")
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
            pr = run_v9(s, e, "placebo", seed=seed); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
