#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-3 QUARTER-END WINDOW-DRESSING REBOUND
(novel-x3-window-dressing, invented rule X3, EVENT strategy).

Road: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs,
point-in-time, v9 protections (plain -15% floor, 90-day cash sit,
episode-2 floor -15% of restart balance, second halt ends the run).

CADENCE TREATMENT (SPEC uniform definition, event strategies — stated
precisely): the event rules stay exactly as published — entry at the
close of L (last trading day of the quarter) into the 5 lowest
quarter-to-date pond names, equal weight, funded by selling SPY; the
pot holds SPY outside event windows. Cadence governs ONLY the position
review / exit-check rhythm:
  * the scheduled exit (close of the 5th trading day of the new
    quarter) executes on the FIRST CADENCE DATE on/after the scheduled
    exit date (if none exists inside the window, the last window day);
  * the v9 floor is checked only on cadence dates (a halt flagged at a
    cadence-date close liquidates at the next open, engine semantics);
  * entries are NOT cadence-gated — they are the event itself. A later
    event's entry rotation sells whatever is held at that close (the
    published engine's own mechanics), and a pending exit that lands
    after a newer entry therefore exits the newer basket — a mechanical
    consequence of slow review rhythms, documented, never patched.
Cadence dates (SPEC): daily = every trading day; weekly = first
trading day of each ISO week; biweekly = every second such weekly
date; monthly/quarterly/semi-annual/annual = first trading day of the
period. Daily cadence == the published form (asserted against the
area run's DECADE final $356.03).

Placebos: the design's own placebo (uniform 5 names drawn without
replacement from the same quarter's rankable set, seeds 1..20, one RNG
per seed advanced chronologically), run at the SAME cadence under the
same v9 wrapper.

Per-event stats: basket gross % and SPY gross % over L -> ACTUAL exit
(the cadence exit), plus a net excess that deducts a flat 0.21%
round-trip cost drag from the basket leg (0.10% buy + 0.10% sell +
~0.01% flat $0.01/order effect at these position sizes) — an
approximation for the per-event stat only; the cycled finals are exact
engine accounting.

Data: read-only shared cache backtests/v7/long-hold/data pxfull
payloads (same plumbing as driver.py) + slug-local pxfull_GOOGL.json.
"""
import importlib.util, json, os, statistics, time
from datetime import date, timedelta

HERE = "/home/hatch/workspace/stock-app/backtests/v10-retest/novel-x3-window-dressing"
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x3", os.path.join(HERE, "integrity", "novel-x3-window-dressing.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
E = M.E

START, END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
SPY_DECADE = 367.80

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

BARS = {t: pxfull(t) for t in M.UNIVERSE + ["SPY"]}
BX = M.Bars(BARS)
CAL = [b["d"] for b in BARS["SPY"]]
ALL_EVENTS = M.build_events(CAL)
DAYS = [d for d in CAL if START <= d <= END]

def cadence_dates(days, cadence):
    if cadence == "daily": return set(days)
    def first_of(keyfn):
        out, seen = [], set()
        for d in days:
            k = keyfn(d)
            if k not in seen: seen.add(k); out.append(d)
        return out
    if cadence == "weekly":
        return set(first_of(lambda d: date.fromisoformat(d).isocalendar()[:2]))
    if cadence == "biweekly":
        wk = first_of(lambda d: date.fromisoformat(d).isocalendar()[:2])
        return set(wk[::2])
    if cadence == "monthly": return set(first_of(lambda d: d[:7]))
    if cadence == "quarterly":
        return set(first_of(lambda d: (d[:4], (int(d[5:7]) - 1) // 3)))
    if cadence == "semiannual":
        return set(first_of(lambda d: (d[:4], int(d[5:7]) <= 6)))
    if cadence == "annual": return set(first_of(lambda d: d[:4]))
    raise ValueError(cadence)

def simulate_cad(calendar, start, end, events, picker, cadence,
                 cash0, floor0):
    """Engine mechanics copied from integrity/novel-x3-window-dressing.py
    simulate(), with the cadence overlay: effective exits + floor checks
    only on cadence dates. START_CASH/FLOOR0 become parameters."""
    days = [d for d in calendar if start <= d <= end]
    cset = cadence_dates(days, cadence)
    def cad_exit(xd):
        for d in days:
            if d >= xd and d in cset: return d
        return days[-1]
    eff = {id(e): cad_exit(e["exit"]) for e in events}
    ev_by_L = {e["L"]: e for e in events}
    ev_by_exit = {}
    for e in events: ev_by_exit.setdefault(eff[id(e)], []).append(e)

    cash = cash0; positions = {}; trades = []; total_costs = 0.0
    curve = []; halted = None; halt_info = None; event_log = []
    bx = BX

    def value(d):
        v = cash
        for t, sh in positions.items():
            c = bx.close_on_or_before(t, d)
            if c: v += sh * c
        return v

    def sell_all_at_close(d, tag="SELL"):
        nonlocal cash, total_costs
        for t in list(positions):
            c = bx.close_on_or_before(t, d)
            if c is None: continue
            val = positions[t] * c
            cost = val * 0.001 + 0.01
            cash += val - cost; total_costs += cost
            trades.append((d, t, tag, positions[t], c, val, cost))
            del positions[t]

    def buy_value(t, d, price, target):
        nonlocal cash, total_costs
        if price is None or price <= 0: return 0.0
        buy_val = min(target, cash / 1.001)
        if buy_val <= 0.005: return 0.0
        sh = buy_val / price; cost = buy_val * 0.001
        cash -= buy_val + cost; total_costs += cost
        positions[t] = positions.get(t, 0.0) + sh
        trades.append((d, t, "BUY", sh, price, buy_val, cost))
        return buy_val

    def do_entry(ev, d, boundary=False):
        qtd = M.qtd_table(bx, ev)
        picks = picker(ev, qtd)
        v_pre = value(d) if not boundary else cash0
        if not boundary: sell_all_at_close(d)
        for t in picks:
            buy_value(t, d, bx.close_on_or_before(t, d), v_pre / max(len(picks), 1))
        xd = eff[id(ev)]
        spy_c0 = bx.close_on_or_before("SPY", ev["L"])
        spy_c1 = bx.close_on_or_before("SPY", xd)
        basket_rel = None
        if picks:
            rels = []
            for t in picks:
                a = bx.close_on_or_before(t, ev["L"])
                b = bx.close_on_or_before(t, xd)
                if a and b: rels.append(b / a)
            if rels: basket_rel = sum(rels) / len(rels)
        bg = round((basket_rel - 1) * 100, 2) if basket_rel else None
        sg = round((spy_c1 / spy_c0 - 1) * 100, 2) if spy_c0 and spy_c1 else None
        event_log.append({
            "L": ev["L"], "exit_scheduled": ev["exit"], "exit_actual": xd,
            "boundary": boundary, "picks": list(picks),
            "basket_gross_pct": bg, "spy_gross_pct": sg,
            "excess_gross_pct": (round(bg - sg, 2)
                                 if bg is not None and sg is not None else None),
            "excess_net_pct": (round(bg - 0.21 - sg, 2)
                               if bg is not None and sg is not None else None),
            "pot_after_entry": round(value(d), 2) if not boundary else None})
        return picks

    def do_exit(d):
        sell_all_at_close(d)
        buy_value("SPY", d, bx.close_on_or_before("SPY", d), cash)

    first_ev = events[0] if events else None
    if first_ev is not None and first_ev["L"] < start:
        do_entry(first_ev, first_ev["L"], boundary=True)
    else:
        buy_value("SPY", days[0], bx.open_on("SPY", days[0]), cash)

    end_date = days[-1]
    for k, d in enumerate(days):
        v = value(d); curve.append((d, v))
        if d in cset and v <= floor0 and k < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[k + 1]
            for t in list(positions):
                opx = bx.open_on(t, nd)
                if opx is None: opx = bx.close_on_or_before(t, nd)
                val = positions[t] * opx
                cost = val * 0.001 + 0.01
                cash += val - cost; total_costs += cost
                trades.append((nd, t, "SELL-HALT", positions[t], opx, val, cost))
            positions = {}; end_date = nd
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "halt_info": halt_info, "curve": curve,
                    "events": event_log, "end": end_date}
        if d in ev_by_L: do_entry(ev_by_L[d], d)
        if d in ev_by_exit: do_exit(d)
    sell_all_at_close(days[-1], tag="SELL-END")
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "halt_info": None, "curve": curve,
            "events": event_log, "end": end_date}

def run_v9_cad(cadence, picker):
    evs = [e for e in ALL_EVENTS if START <= e["exit"] <= END]
    r1 = simulate_cad(CAL, START, END, evs, picker, cadence, 100.0, 85.0)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= END:
            evs2 = [e for e in ALL_EVENTS if e["L"] >= elig and e["exit"] <= END]
            r2 = simulate_cad(CAL, elig, END, evs2, picker, cadence,
                              r1["final"], 0.85 * r1["final"])
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
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    events = eps[0]["events"]
    traded = [ev for ev in events if ev.get("basket_gross_pct") is not None]
    def agg(key):
        vals = [ev[key] for ev in traded if ev.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else None
    years = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
    final = round(eps[-1]["final"], 2)
    return {
        "final": final,
        "cagr_pct": round(((final / 100.0) ** (1 / years) - 1) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(sum(e["costs"] for e in eps), 2),
        "orders": sum(len(e["trades"]) for e in eps),
        "halts": [e["halted"] for e in eps if e["halted"]],
        "restart": restart is not None, "restart_info": restart,
        "second_halt": bool(restart and restart["second_halt"]),
        "curve": [[d, round(v, 4)] for d, v in curve],
        "events": events,
        "event_stats": {
            "n_events": len(events), "n_events_traded": len(traded),
            "mean_basket_gross_pct": agg("basket_gross_pct"),
            "median_basket_gross_pct": (round(statistics.median(
                [ev["basket_gross_pct"] for ev in traded]), 3) if traded else None),
            "mean_spy_gross_pct": agg("spy_gross_pct"),
            "mean_excess_gross_pct": agg("excess_gross_pct"),
            "mean_excess_net_pct": agg("excess_net_pct"),
            "events_beat_spy": sum(1 for ev in traded
                                   if ev["excess_gross_pct"] is not None
                                   and ev["excess_gross_pct"] > 0),
            "note": "basket/SPY gross over L -> actual (cadence) exit; net excess deducts a flat 0.21% round-trip cost drag from the basket leg (approximation — cycled finals are exact)"}}

