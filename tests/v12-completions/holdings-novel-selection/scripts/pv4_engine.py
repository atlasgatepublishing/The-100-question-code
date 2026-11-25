#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-PV4 THE OVERNIGHT CONFESSION, DECADE road
2016-11-21 -> 2026-11-20. Simulation only.

Reuses the folder's plumbing: bars via driver.py's pxfull loader
(long-run pxfull payloads, read-only; GOOGL from the slug-local
pxfull_GOOGL.json), events via the integrity engine's scan_events /
window_events, mechanics copied line-for-line from the integrity
engine's run_event_pot with ONE change (the cadence exit rule below),
v9 protection wrapper copied from driver.py's run_v9.

CADENCE TREATMENT (stated precisely, binding for this sweep):
PV4 is an overnight-hold event rule: the "night" is the overnight gap
into the signal day t (Open_t / Close_{t-1} - 1 <= -2%) whose full
reclaim is confirmed at t's close. Cadence governs:
  (a) WHICH NIGHTS COUNT — an event is taken only if its SIGNAL day t
      is a cadence date (SPEC uniform definition: daily = every
      trading day; weekly = first trading day of each week; biweekly =
      first trading day of every second week, weeks enumerated from
      the first week of the road; monthly / quarterly / semi-annual /
      annual = first trading day of each month / calendar quarter /
      half-year / year, on the SPY calendar).
  (b) EXIT CHECKS — the published exit (sell at the open of the 11th
      trading day after the entry day, i.e. 10 full trading days
      held) becomes DUE on that day, but is executed only at the open
      of the first cadence date on or after the due date. A position
      whose due date falls beyond the road end is liquidated at the
      road-end close (program SELL-END convention), as published.
Unchanged published/protection mechanics: entry at the next session's
open after the signal day; slice = 1/5 of pot value marked at the
signal day's close; max 5 concurrent positions, one per name, no
re-trigger while held, same-day triggers filled in gap-rank order;
costs 0.10%/side + $0.01 per sell; the v9 floor is a DAILY close check
(it is the adopted protection, not the strategy's tempo): first halt
liquidates at the next open, 90 calendar days in cash, restart at the
next cadence-eligible event schedule under an episode-2 floor of -15%
from the restart balance; second halt ends the run.
At the DAILY cadence this treatment is exactly the native form, and
the sweep asserts it reproduces the saved area DECADE run to the cent
($83.19, costs $5.51, 244 orders, halt 2020-03-12).

PLACEBOS: the original design — for each seed 1..20, every event in
the cadence-filtered schedule (same date order, same gap-rank order)
is assigned a name drawn uniformly at random from the other pond
names; the placebo pot runs the identical cadence engine and v9
wrapper (episode-2 schedule redraws with the same seed stream, as in
driver.py).
"""
import importlib.util, json, os, random, time
from datetime import date, timedelta

HERE = "/home/hatch/workspace/stock-app/backtests/v10-retest/novel-pv4-overnight-confession"
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv4", os.path.join(HERE, "integrity", "novel-pv4-overnight-confession.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
E = M.E
UNIVERSE = M.UNIVERSE
HOLD_AFTER = M.HOLD_AFTER
MAX_POS = M.MAX_POS

def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

BARS = {t: pxfull(t) for t in UNIVERSE + ["SPY"]}
PB = E.PriceBook(BARS)
EVENTS = M.scan_events(BARS)
CAL = PB.dates
IDX = {t: {b["d"]: i for i, b in enumerate(BARS[t])} for t in UNIVERSE}
BAR = {t: {b["d"]: b for b in BARS[t]} for t in UNIVERSE}
START, END = "2016-11-21", "2026-11-20"
DAYS = [d for d in CAL if START <= d <= END]

def cadence_dates(name):
    if name == "daily":
        return set(DAYS)
    if name == "biweekly":
        wk, seen = [], set()
        for d in DAYS:
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key); wk.append(d)
        return set(wk[::2])
    out, seen = set(), set()
    for d in DAYS:
        if name == "weekly":
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
        elif name == "monthly":
            key = d[:7]
        elif name == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
        elif name == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
        elif name == "annual":
            key = d[:4]
        if key not in seen:
            seen.add(key); out.add(d)
    return out

def close_of(t, d):
    return PB.close_on_or_before(t, d)

def run_event_pot_cad(sched, start, end, names, cad_set,
                      start_cash=100.0, floor=85.0, n_cap=5, slice_n=5):
    """Integrity engine's run_event_pot, verbatim mechanics except the
    exit rule: exit executes at the open of the first cadence date
    on/after the position's due exit day."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halt_info = None
    curve = []
    taken, skipped = [], []
    days = [d for d in CAL if start <= d <= end]
    entries = {}
    for i, ev in enumerate(sched):
        entries.setdefault(ev["entry"], []).append(i)

    def pot_close(d):
        v = cash
        for t, p in positions.items():
            c = close_of(t, d)
            if c: v += p["shares"] * c
        return v

    def sell(t, sh, px, d, kind):
        nonlocal cash, total_costs
        val = sh * px
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, t, kind, sh, px, val, c))
        return val

    pending_halt = False
    for di, d in enumerate(days):
        if pending_halt:
            sig_d = days[di - 1]
            for t in list(positions):
                b = BAR[t].get(d)
                if b: sell(t, positions[t]["shares"], b["o"], d, "SELL-HALT")
                del positions[t]
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": sig_d, "halt_info": halt_info, "curve": curve,
                    "taken": taken, "skipped": skipped}
        # (b) exits due, executed only on cadence dates
        if d in cad_set:
            for t in list(positions):
                xd = positions[t]["exit"]
                if xd is not None and xd <= d:
                    b = BAR[t].get(d)
                    if b: sell(t, positions[t]["shares"], b["o"], d, "SELL-EXIT")
                    del positions[t]
        # (c) entries at this open
        for i in entries.get(d, []):
            ev = sched[i]; t = names[i]
            if t in positions:
                skipped.append({**ev, "bought": t, "why": "name already held"})
                continue
            if len(positions) >= n_cap:
                skipped.append({**ev, "bought": t, "why": "5 positions already open"})
                continue
            sig = ev["signal"]
            v = cash
            for tt, p in positions.items():
                c = close_of(tt, sig)
                if c: v += p["shares"] * c
            target = v / slice_n
            b = BAR[t].get(d)
            if not b or not b["o"]:
                skipped.append({**ev, "bought": t, "why": "no bar on entry day"})
                continue
            buy_val = min(target, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({**ev, "bought": t, "why": "insufficient cash"})
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            ei = IDX[t][d]
            exit_d = (BARS[t][ei + HOLD_AFTER]["d"]
                      if ei + HOLD_AFTER < len(BARS[t]) else None)
            positions[t] = {"shares": sh, "entry": d, "exit": exit_d,
                            "ev": i, "entry_px": b["o"]}
            trades.append((d, t, "BUY", sh, b["o"], buy_val, c))
            taken.append({**ev, "bought": t, "entry": d, "exit": exit_d,
                          "buy_val": round(buy_val, 2)})
        v = pot_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            pending_halt = True
    last = days[-1]
    for t in list(positions):
        px = close_of(t, last)
        if px: sell(t, positions[t]["shares"], px, last, "SELL-END")
        del positions[t]
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "halt_info": halt_info, "curve": curve,
            "taken": taken, "skipped": skipped}

def sched_for(start, cad_set):
    s = M.window_events(EVENTS, PB, start, END)
    return [ev for ev in s if ev["signal"] in cad_set]

def run_v9(cad_set, names_fn):
    sched = sched_for(START, cad_set)
    r1 = run_event_pot_cad(sched, START, END, names_fn(sched), cad_set)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= END:
            sched2 = sched_for(elig, cad_set)
            r2 = run_event_pot_cad(sched2, elig, END, names_fn(sched2), cad_set,
                                   start_cash=r1["final"], floor=0.85 * r1["final"])
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85 * r1["final"], 2),
                       "second_halt": r2["halted"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        for d in DAYS:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    fin = round(eps[-1]["final"], 2)
    yrs = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
    return {"final": fin,
            "cagr_pct": round(((fin / 100.0) ** (1.0 / yrs) - 1.0) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "events_taken": sum(len(e["taken"]) for e in eps),
            "curve": [[d, round(v, 4)] for d, v in curve]}

