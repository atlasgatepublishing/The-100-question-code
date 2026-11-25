#!/usr/bin/env python3
"""V10 AREA RUN — N-PV2 THE LAST SELLER. Simulation only.
Short-cycle event rule (126-day volume climax + down day, 20-bar hold)
cycled over the full road. Data: long-run pxfull payloads (read-only)
fed through the v9 engine's own load_payload slot; GOOGL from the
slug-local pxfull_GOOGL.json (fresh Yahoo pull, same construction).
Protection: v9 two-episode wrapper copied from the v9 engine's main.
Placebos: original design (replay the ranked run's taken slots with
random pond names, seeds 1..20) under the same v9 wrapper, CONT+VAL.
Placebo ep2 replays ep2's taken slots likewise.
"""
import importlib.util, json, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv2", os.path.join(HERE, "integrity", "novel-pv2-last-seller.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def load_payload(ticker):
    if ticker == "GOOGL":
        return json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    return json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
M.load_payload = load_payload

BARS = {t: M.get_bars(t) for t in M.POND + ["SPY"]}
PB = M.PriceBook(BARS)
EVENTS = M.detect_events(PB)
SPYB = {b["d"]: b for b in BARS["SPY"]}
CAL = PB.dates

def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    o = SPYB[days[0]]["o"]; sh = (cash/1.001)/o
    val = sh * PB.close_on_or_before("SPY", days[-1])
    return round(val - (val*0.001 + 0.01), 2)

def run_v9(start, end, plan_fn):
    """plan_fn(start,end) -> entry_plan. Returns run dict + taken slots
    per episode (for placebo replay)."""
    plan = plan_fn(start, end)
    r1 = M.run_pot(PB, start, end, plan, label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            plan2 = plan_fn(elig, end)
            r2 = M.run_pot(PB, elig, end, plan2, label="ep2",
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
            "taken": [e["taken"] for e in eps]}

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

def ranked_plan(s, e):
    plan, _ = M.build_ranked_plan(PB, EVENTS, s, e)
    return plan

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-pv2-last-seller", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, ranked_plan)
    maxdd, worst = diag(r["curve"])
    taken = r.pop("taken"); curve = r.pop("curve")
    r.update({"start": s, "end": e, "max_dd_pct": maxdd,
              "worst_close": round(worst[1], 2), "placebo_beaten": None,
              "entries": sum(len(t) for t in taken)})
    if w == "LONG":
        py, beats = per_year(curve); r["per_year"] = py
        r["years_beat_spy"] = beats
        r["n_years_scored"] = sum(1 for v in py.values() if v["spy_ret_pct"] is not None)
    if w in ("CONT", "VAL"):
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            ep_taken = [list(t) for t in taken]
            def placebo_plan(s2, e2, rng=rng, ep_taken=ep_taken):
                slots = ep_taken.pop(0) if ep_taken else []
                pplan = {}
                for slot in slots:
                    pplan.setdefault(slot["entry_date"], []).append(
                        {"ticker": rng.choice(M.POND),
                         "signal_date": slot["signal_date"]})
                return pplan
            pr = run_v9(s, e, placebo_plan); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
