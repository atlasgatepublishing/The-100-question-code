#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-1 BELLWETHER ECHO (novel-x1-bellwether,
invented rule X1, cross-stock lead-lag, daily native).

Road: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs
(0.10%/side + $0.01/sell order, the engine's own cost code), point-in-
time, v9 protections (plain -15% floor from the episode's starting
balance; first halt -> liquidate as the engine does, sit in cash 90
calendar days, restart at the next decision point under an episode-2
floor of -15% from the restart balance; second halt ends the run).

CADENCE TREATMENT (SPEC uniform definition, stated precisely for this
rule): cadence gates the SIGNAL SCAN — the strategy's decision point.
The bellwether tape is read only on cadence dates (daily = every
trading day; weekly = first trading day of each ISO week; biweekly =
every second such weekly date; monthly/quarterly/semi-annual/annual =
first trading day of the period). A fire can only be declared at a
cadence date's close. When a fire IS declared, the published trade
mechanics execute exactly as designed and are NOT moved onto cadence
dates: entry at the next trading day's open, exit at the close of the
third trading day after the signal (t+3), one basket at a time (a
cadence-date signal arriving while a basket is held is ignored, the
original stacking rule). Reason, stated plainly: the rule's thesis is
a days-long echo of a one-day bellwether spike; stretching entry/exit
to the next cadence date would replace the 3-day echo with holds of a
week to a year — a different strategy, not this one at a slower tempo.
The sweep's question for X1 is how often you need to listen. The v9
floor remains a daily close check (it is the adopted protection, not
the strategy's tempo — the engine's own convention, as in the area
runs). Daily cadence == the native published form, asserted against
the area run's DECADE final ($71.09, costs $25.53, orders 574, halts
2020-03-03 / 2021-01-08).

Placebos: the original design — same fire dates per cell, per fired
cluster the same number of followers as the ranked run picked from
that cluster, drawn at random from that cluster's followers
(bellwether excluded), same mechanics, seeds 1..20, same v9 wrapper.

Data: read-only shared cache backtests/v7/long-hold/data pxfull
payloads (same plumbing as driver.py) + slug-local pxfull_GOOGL.json.
Bellwether/follower designations: the original run's recorded
Nov-2016 designations (unchanged).
"""
import importlib.util, inspect, json, os, random
from collections import Counter
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

src = inspect.getsource(M.run_pot)
src = src.replace('"max_drawdown_pct": round(maxdd * 100, 2), "trades": trades}',
                  '"max_drawdown_pct": round(maxdd * 100, 2), "trades": trades, "curve": curve}')
ns = dict(M.__dict__)
exec(compile(src, "run_pot_curve", "exec"), ns)
RUN = ns["run_pot"]

START, END = "2016-11-21", "2026-11-20"
DAYS = [d for d in SPY_DATES if START <= d <= END]
RANKED = lambda e: [p["ticker"] for p in e["picks"]]

def cadence_dates(name, days):
    if name == "daily":
        return list(days)
    if name == "biweekly":
        wk, seen = [], set()
        for d in days:
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key); wk.append(d)
        return wk[::2]
    firsts, seen = [], set()
    for d in days:
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

def scan_events_cad(days, cad_set):
    """Engine scan_events logic verbatim, plus one gate: a fire may
    only be declared on a cadence date. Entry/exit indices (i+1 open,
    i+3 close) and the stacking rule are the published mechanics."""
    events = []
    busy_until = -1
    for i, d in enumerate(days):
        if i <= busy_until:
            continue
        if d not in cad_set:
            continue
        r_spy = RET("SPY", d)
        if r_spy is None:
            continue
        resid = {}
        for t in M.UNIVERSE:
            r = RET(t, d)
            resid[t] = None if r is None else r - r_spy
        fired = [c for c in M.CLUSTERS
                 if resid[BEL[c]] is not None
                 and resid[BEL[c]] >= M.FIRE_THRESHOLD]
        if not fired:
            continue
        qual = []
        for c in fired:
            for f in FOL[c]:
                if resid[f] is not None and resid[f] <= M.FOLLOWER_MAX_RESID:
                    qual.append((resid[f], f, c))
        if not qual:
            continue
        if i + 1 >= len(days):
            continue
        qual.sort(key=lambda x: (x[0], x[1]))
        picks = qual[:M.MAX_PICKS]
        events.append({
            "signal_date": d, "signal_idx": i,
            "entry_idx": i + 1, "exit_idx": i + 3,
            "entry_date": days[i + 1],
            "exit_date": days[min(i + 3, len(days) - 1)],
            "fired_clusters": fired,
            "bellwether_resid": {c: resid[BEL[c]] for c in fired},
            "picks": [{"ticker": t, "cluster": c, "resid": r} for r, t, c in picks],
            "qualifying_count": len(qual),
            "cluster_counts": dict(Counter(c for _, _, c in picks)),
        })
        busy_until = i + 3
    return events

def run_v9(start, end, pick_fn, cad_set):
    days = [d for d in SPY_DATES if start <= d <= end]
    events = scan_events_cad(days, cad_set)
    r1 = RUN(PB, days, events, pick_fn, label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            days2 = [d for d in SPY_DATES if elig <= d <= end]
            events2 = scan_events_cad(days2, cad_set)
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

YRS = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
out_cells = {}
for cad in ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]:
    cs = set(cadence_dates(cad, DAYS))
    r = run_v9(START, END, RANKED, cs)
    if cad == "daily":
        assert r["final"] == 71.09 and r["costs"] == 25.53 and r["orders"] == 574, r
        assert r["halts"] == ["2020-03-03", "2021-01-08"], r["halts"]
        print("DAILY CELL == AREA DECADE RUN ($71.09) — plumbing check PASSED", flush=True)
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        def placebo_picks(ev, rng=rng):
            picks = []
            for c, k in ev["cluster_counts"].items():
                picks.extend(rng.sample(sorted(FOL[c]), k))
            return picks
        pr = run_v9(START, END, placebo_picks, cs); finals.append(pr["final"])
    beaten = sum(1 for f in finals if f < r["final"])
    sf = sorted(finals)
    curve = [[d, round(v, 4)] for d, v in r.pop("curve")]
    cell = {"slug": "novel-x1-bellwether", "cadence": cad,
            "window": [START, END], "pot": 100,
            "final": r["final"],
            "cagr_pct": round(((r["final"]/100.0)**(1.0/YRS) - 1.0)*100, 2),
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "events_executed": r["events_executed"],
            "halts": r["halts"],
            "restarts": [r["restart_info"]] if r["restart_info"] else [],
            "restart": r["restart"], "second_halt": r["second_halt"],
            "placebo_beaten": beaten,
            "placebo_median": round((sf[9]+sf[10])/2, 2),
            "placebo_finals": finals,
            "placebo_note": "20 seeds (1..20), original design: same fire dates, same per-cluster follower counts, random followers from the same clusters, same v9 wrapper",
            "equity_curve": curve}
    json.dump(cell, open(os.path.join(HERE, "cells", f"{cad}.json"), "w"), indent=1)
    out_cells[cad] = {k: cell[k] for k in
                      ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                       "second_halt", "costs", "orders", "placebo_beaten")}
    out_cells[cad]["placebo_note"] = cell["placebo_note"]
    print(cad, r["final"], "placebo", beaten, "/20 median",
          cell["placebo_median"], "halts", r["halts"], flush=True)
json.dump(out_cells, open(os.path.join(HERE, "sweep_cells.json"), "w"), indent=1)
print("DONE")
