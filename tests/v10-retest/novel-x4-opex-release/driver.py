#!/usr/bin/env python3
"""V10 AREA RUN — N-4 OPEX-WEEK PINNING RELEASE (event-driven, monthly
OpEx calendar). Simulation only. Event treatment: per-event mean
basket return over the longest window (the engine's own event record:
basket_ret_pct vs spy_ret_pct per event, gross of pot costs; the net
effect lives in the cycled pot) PLUS the cycled full-road runs, and
the original's second-Friday calendar placebo on every window.
Data: long-run pxfull payloads (read-only) via the engine's load_bars
slot; GOOGL from the slug-local pxfull_GOOGL.json.
Protection: v9 via the engine's START_CASH/FLOOR0 globals; episode 2
takes events whose anchor day is on/after halt+90 days (the next
regular monthly decision point). Random placebos: original design
(5 random pond names per event on the ranked dates, seeds 1..20)
under the same v9 wrapper, CONT+VAL.
"""
import importlib.util, json, os, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x4", os.path.join(HERE, "integrity", "novel-x4-opex-release.py"))
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
CAL = [b["d"] for b in BARS["SPY"]]
CAL_INDEX = {d: i for i, d in enumerate(CAL)}
CLOSES, OPENS = {}, {}
for t in M.UNIVERSE + ["SPY"]:
    by = {b["d"]: b for b in BARS[t]}
    CLOSES[t] = [by[d]["c"] if d in by else None for d in CAL]
    OPENS[t] = [by[d]["o"] if d in by else None for d in CAL]

def spy_net(start, end, cash=100.0):
    s, _ = E.spy_net(PB, start, end, cash)
    return round(s, 2)

def build(which_friday, s, e, anchor_from=None):
    evs = []
    for p in M.build_events(CAL_INDEX, s, e, which_friday):
        if anchor_from and CAL[p] < anchor_from: continue
        ranked, detail = M.screen(CLOSES, p)
        evs.append({"p": p, "picks": ranked[:M.TOP_N],
                    "n_eligible": len(ranked), "detail": detail})
    return evs

def run_once(s, e, evs, cash, floor):
    M.START_CASH = cash; M.FLOOR0 = floor
    r = M.run_pot(CAL, CLOSES, OPENS, evs, s, e, label="run")
    M.START_CASH = 100.0; M.FLOOR0 = 85.0
    return r

from datetime import date, timedelta
def run_v9(s, e, ev_fn):
    r1 = run_once(s, e, ev_fn(s, e, None), 100.0, 85.0)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= e:
            r2 = run_once(elig, e, ev_fn(elig, e, elig),
                          r1["final"], 0.85*r1["final"])
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85*r1["final"], 2),
                       "second_halt": r2["halted"]}
    last = eps[-1]
    return {"final": last["final"],
            "costs": round(sum(ep["costs"] for ep in eps), 2),
            "orders": sum(ep["orders"] for ep in eps),
            "halts": [ep["halted"] for ep in eps if ep["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": max(ep["max_drawdown_pct"] for ep in eps),
            "worst_close": min(ep["worst_close"] for ep in eps),
            "events": eps[0]["events"]}

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
out = {"slug": "novel-x4-opex-release", "spy": {}, "runs": {}}
for w, (s, e) in WINDOWS.items():
    out["spy"][w] = spy_net(s, e)
    r = run_v9(s, e, lambda s2, e2, af: build(3, s2, e2, af))
    evs = r.pop("events")
    cp = run_v9(s, e, lambda s2, e2, af: build(2, s2, e2, af))
    traded = [ev for ev in evs if ev.get("basket_ret_pct") is not None]
    r.update({"start": s, "end": e, "placebo_beaten": None,
              "calendar_placebo_final": cp["final"],
              "n_events": len(evs), "n_events_traded": len(traded)})
    if w == "LONG":
        bg = [ev["basket_ret_pct"] for ev in traded]
        sg = [ev["spy_ret_pct"] for ev in traded]
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
        base_events = build(3, s, e)
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pev = [{"p": ev["p"],
                    "picks": rng.sample(sorted(M.UNIVERSE), M.TOP_N),
                    "n_eligible": None, "detail": {}} for ev in base_events]
            def pev_fn(s2, e2, af, pev=pev):
                if af is None: return pev
                return [ev for ev in pev if CAL[ev["p"]] >= af]
            pr = run_v9(s, e, pev_fn); finals.append(pr["final"])
        r["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        sf = sorted(finals); r["placebo_median"] = round((sf[9]+sf[10])/2, 2)
    out["runs"][w] = r
    print(w, r["final"], "SPY", out["spy"][w], "calPlacebo", cp["final"],
          "events", r["n_events"], "halts", r["halts"],
          "placebo", r["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE, "area.json"), "w"), indent=1)
print("DONE")
