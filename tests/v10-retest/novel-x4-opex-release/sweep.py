#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-4 OPEX-WEEK PINNING RELEASE (novel-x4-opex-release).
Simulation only. DECADE road 2016-11-21 -> 2026-11-20, $100/cell.

TREATMENT (SPEC, THE CADENCE SWEEP, event-driven strategies): the event
rules stay exactly as published — third-Friday (ranked) / second-Friday
(calendar placebo) anchor, compression screen (CR<=0.70, pre-week trend
>0), top-5 by CR ascending, entry at the CLOSE of the anchor day E in
fifths of the pot, unused weight in SPY, SPY held outside windows.
Cadence governs ONLY the position review / exit-check rhythm:
  - the published exit (close of the 5th trading day after E) executes
    on the first cadence date on/after that day (a basket whose exit
    slips past the next event's entry is held as a separate lot and
    exits on its own cadence date);
  - the v9 -15% floor is checked only on cadence dates (liquidation at
    the next trading day's open, as the engine does).
Daily cadence == the original form exactly, and this script ASSERTS
the daily cell reproduces the saved area runs before any sweep number
is taken (DECADE ranked $253.90, DECADE calendar placebo $280.30,
CONT $247.09, VAL $182.30 — from area.json / the integrity gate).

v9 protection wrapper (same as driver.py): plain -15% floor from the
episode start; on halt, cash 90 calendar days, restart at the next
event whose anchor is on/after halt+90d under an episode-2 floor of
-15% from the restart balance; second halt ends the run.

Placebos per cell (both, per the tasking):
  (a) design placebo — 20 seeds, 5 random pond names per event on the
      ranked dates, same cadence mechanics, same v9 wrapper;
  (b) calendar placebo — the identical screen on the SECOND Friday,
      same cadence (single deterministic twin). A cell where the
      ranked run loses to its calendar twin is a cell where the
      calendar, not the rule, did the work.
Data: read-only long-run pxfull payloads (v7 long-hold data) via the
same construction as driver.py; GOOGL from the slug-local payload.
"""
import importlib.util, json, os, random, statistics, sys
from datetime import date, timedelta

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

# ------------------------------------------------------------- cadences
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

CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------- cadence engine
def run_pot_cad(cal, closes, opens, events, start, end, cadence,
                start_cash, floor0):
    """Original X4 engine mechanics (copied from integrity engine) with
    the cadence overlay. events: [{p, picks, n_eligible, detail}].
    Returns result dict incl. full equity curve and per-event rows
    measured over the ACTUAL holding span (entry close -> exit close)."""
    days = [d for d in cal if start <= d <= end]
    pos_of = {d: i for i, d in enumerate(cal)}
    cset = cadence_dates(days, cadence)
    # schedule exits: first cadence date >= anchor+5 trading days
    exit_of = {}   # date -> [event ids]
    sched_exit_idx = {}
    for eid, e in enumerate(events):
        xi = None
        for j in range(e["p"] + 5, len(cal)):
            if cal[j] in cset and cal[j] <= end:
                xi = j; break
        if xi is None:
            xi = pos_of[days[-1]]
        sched_exit_idx[eid] = xi
        exit_of.setdefault(cal[xi], []).append(eid)
    ev_in = {e["p"]: eid for eid, e in enumerate(events)}
    cash = start_cash
    pos = {}       # ticker -> shares (SPY included)
    lots = {}      # (eid, ticker) -> shares
    total_costs = 0.0
    orders = 0
    curve = []
    halted = None
    event_rows = []

    def close_px(t, d):
        i = pos_of[d]
        v = closes[t][i]
        if v is not None: return v
        j = i
        while j >= 0 and closes[t][j] is None: j -= 1
        return closes[t][j] if j >= 0 else None

    def equity_close(d):
        v = cash
        for t, sh in pos.items():
            px = close_px(t, d)
            if px: v += sh * px
        return v

    def sell(t, sh, px, d, tag):
        nonlocal cash, total_costs, orders
        val = sh * px
        c = val * 0.001 + 0.01
        cash += val - c; total_costs += c; orders += 1
        return val

    def buy_value(t, target, px, d, tag):
        nonlocal cash, total_costs, orders
        buy_val = min(target, cash / 1.001)
        if buy_val <= 0.005 or px is None or px <= 0: return 0.0, 0.0
        sh = buy_val / px
        c = buy_val * 0.001
        cash -= buy_val + c; total_costs += c; orders += 1
        pos[t] = pos.get(t, 0.0) + sh
        return buy_val, sh

    def buy_all_in(t, px, d, tag):
        nonlocal cash, total_costs, orders
        if cash <= 0.005 or px is None or px <= 0: return
        buy_val = cash / 1.001
        sh = buy_val / px
        c = cash - buy_val
        cash = 0.0; total_costs += c; orders += 1
        pos[t] = pos.get(t, 0.0) + sh

    def record_row(eid, exit_d):
        e = events[eid]
        # only names that actually received shares count as traded —
        # at slow cadences later events can find the pot fully invested
        # in an earlier, still-held basket and buy ~nothing.
        picks = e.get("funded_picks") or []
        if not picks: return
        p = e["p"]; xi = pos_of[exit_d]
        rets = []
        for t in picks:
            c0, c1 = closes[t][p], close_px(t, exit_d)
            if c0 and c1: rets.append(c1 / c0 - 1.0)
        if not rets: return
        basket = sum(rets) / len(rets)
        s0, s1 = closes["SPY"][p], close_px("SPY", exit_d)
        spy_r = s1 / s0 - 1.0 if s0 and s1 else 0.0
        # net: round-trip proportional costs 0.10% buy + 0.10% sell on
        # the basket weight (the $0.01/sell ticket is in the pot finals,
        # not this per-event approximation)
        basket_net = (1.0 + basket) * 0.999 * 0.999 - 1.0
        event_rows.append({
            "E": cal[p], "exit": exit_d, "picks": picks,
            "basket_gross_pct": round(basket * 100, 3),
            "spy_gross_pct": round(spy_r * 100, 3),
            "excess_gross_pct": round((basket - spy_r) * 100, 3),
            "excess_net_pct": round((basket_net - spy_r) * 100, 3)})

    for di, d in enumerate(days):
        p = pos_of[d]
        if di == 0:
            buy_all_in("SPY", opens["SPY"][p], d, "BUY-START")
        # entry at the close of E (event rule, unchanged by cadence)
        if p in ev_in:
            eid = ev_in[p]; e = events[eid]
            picks = [t for t in e["picks"] if closes[t][p] is not None]
            if picks:
                v = equity_close(d)
                k = len(picks)
                spy_px = closes["SPY"][p]
                if pos.get("SPY", 0.0) > 0 and spy_px:
                    target_val = (k / 5.0) * v
                    sh_sell = min(pos["SPY"], target_val / spy_px)
                    if sh_sell > 1e-9:
                        sell("SPY", sh_sell, spy_px, d, "SELL-ROT")
                        pos["SPY"] -= sh_sell
                        if pos["SPY"] < 1e-9: del pos["SPY"]
                funded = []
                for t in picks:
                    _, sh = buy_value(t, v / 5.0, closes[t][p], d, "BUY")
                    if sh > 1e-9:
                        lots[(eid, t)] = lots.get((eid, t), 0.0) + sh
                        funded.append(t)
                e["traded_picks"] = list(picks)
                e["funded_picks"] = funded
        # exits on cadence dates only
        if d in exit_of:
            sold_any = False
            for eid in exit_of[d]:
                for (le, t), sh in list(lots.items()):
                    if le != eid: continue
                    px = close_px(t, d)
                    if px: sell(t, sh, px, d, "SELL-EXIT")
                    pos[t] -= sh
                    if pos[t] < 1e-9: del pos[t]
                    del lots[(le, t)]
                    sold_any = True
                record_row(eid, d)
            if sold_any:
                buy_all_in("SPY", closes["SPY"][p], d, "BUY-BACK")
        v = equity_close(d)
        curve.append((d, round(v, 4)))
        # floor checked only on cadence dates
        if d in cset and v <= floor0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]; np_ = pos_of[nd]
            for t in list(pos):
                o = opens[t][np_]
                if o: sell(t, pos[t], o, nd, "SELL-HALT")
                del pos[t]
            for (le, t) in list(lots): record_row(le, nd)
            lots.clear()
            break
    if halted is None:
        last = days[-1]
        for t in list(pos):
            px = close_px(t, last)
            if px: sell(t, pos[t], px, last, "SELL-END")
            del pos[t]
        for (le, t) in list(lots): record_row(le, last)
        lots.clear()
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": orders, "halted": halted,
            "max_dd_pct": round(maxdd * 100, 2),
            "worst_close": round(min(v for _, v in curve), 2),
            "curve": curve, "events": event_rows,
            "n_events_listed": len(events),
            "n_with_picks": sum(1 for e in events if e.get("traded_picks"))}

# ------------------------------------------------------------- v9 wrapper
def build(which_friday, s, e, anchor_from=None):
    evs = []
    for p in M.build_events(CAL_INDEX, s, e, which_friday):
        if anchor_from and CAL[p] < anchor_from: continue
        ranked, detail = M.screen(CLOSES, p)
        evs.append({"p": p, "picks": ranked[:M.TOP_N],
                    "n_eligible": len(ranked), "detail": detail})
    return evs

def run_v9(s, e, cadence, ev_fn):
    r1 = run_pot_cad(CAL, CLOSES, OPENS, ev_fn(s, e, None), s, e,
                     cadence, 100.0, 85.0)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= e:
            r2 = run_pot_cad(CAL, CLOSES, OPENS, ev_fn(elig, e, elig),
                             elig, e, cadence, r1["final"], 0.85 * r1["final"])
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85 * r1["final"], 2),
                       "second_halt": r2["halted"]}
    last = eps[-1]
    curve = eps[0]["curve"]
    if restart:
        curve = curve + [[restart["eligibility"], eps[0]["final"]]] + eps[1]["curve"]
    evs_all = [ev for ep in eps for ev in ep["events"]]
    return {"final": last["final"],
            "costs": round(sum(ep["costs"] for ep in eps), 2),
            "orders": sum(ep["orders"] for ep in eps),
            "halts": [ep["halted"] for ep in eps if ep["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": max(ep["max_dd_pct"] for ep in eps),
            "curve": curve, "events": evs_all,
            "n_events_listed": sum(ep["n_events_listed"] for ep in eps),
            "n_with_picks": sum(ep["n_with_picks"] for ep in eps)}

def ev_stats(evs):
    if not evs: return {"n_events_traded": 0, "mean_excess_gross_pct": None,
                        "mean_excess_net_pct": None, "median_excess_net_pct": None,
                        "events_beat_spy_net": 0}
    return {"n_events_traded": len(evs),
            "mean_excess_gross_pct": round(statistics.mean(
                [x["excess_gross_pct"] for x in evs]), 3),
            "mean_excess_net_pct": round(statistics.mean(
                [x["excess_net_pct"] for x in evs]), 3),
            "median_excess_net_pct": round(statistics.median(
                [x["excess_net_pct"] for x in evs]), 3),
            "events_beat_spy_net": sum(1 for x in evs if x["excess_net_pct"] > 0)}

# ------------------------------------------------------------------ main
def main():
    S, E_ = "2016-11-21", "2026-11-20"
    # ---- validation: daily cadence must reproduce the saved area runs
    checks = []
    for (ws, we, want, want_cal) in [
            ("2016-11-21", "2026-11-20", 253.90, 280.30),
            ("2019-01-02", "2026-11-20", 247.09, 260.88),
            ("2023-01-03", "2026-11-20", 182.30, 188.24)]:
        r = run_v9(ws, we, "daily", lambda a, b, af: build(3, a, b, af))
        c = run_v9(ws, we, "daily", lambda a, b, af: build(2, a, b, af))
        ok = (r["final"] == want and c["final"] == want_cal)
        checks.append({"window": [ws, we], "ranked": r["final"],
                       "expected_ranked": want, "calendar": c["final"],
                       "expected_calendar": want_cal, "match": ok})
        print("VALIDATE", ws, r["final"], "vs", want, "| cal",
              c["final"], "vs", want_cal, "->", ok, flush=True)
        if not ok:
            print("VALIDATION FAILED — no sweep numbers taken.", flush=True)
            sys.exit(1)
    spy_dec = spy_net(S, E_)
    print("DECADE SPY:", spy_dec, flush=True)
    years = (date.fromisoformat(E_) - date.fromisoformat(S)).days / 365.25

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    base_events = build(3, S, E_)
    results = {}
    for cad in CADENCES:
        r = run_v9(S, E_, cad, lambda a, b, af: build(3, a, b, af))
        cp = run_v9(S, E_, cad, lambda a, b, af: build(2, a, b, af))
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pev = [{"p": ev["p"],
                    "picks": rng.sample(sorted(M.UNIVERSE), M.TOP_N),
                    "n_eligible": None, "detail": {}} for ev in base_events]
            def pev_fn(a, b, af, pev=pev):
                if af is None: return pev
                return [ev for ev in pev if CAL[ev["p"]] >= af]
            pr = run_v9(S, E_, cad, pev_fn)
            finals.append(pr["final"])
        beaten = sum(1 for f in finals if f < r["final"])
        beaten_cal = sum(1 for f in finals if f < cp["final"])
        st = ev_stats(r["events"])
        st_cal = ev_stats(cp["events"])
        cagr = round(((r["final"] / 100.0) ** (1.0 / years) - 1.0) * 100, 2)
        cell = {"cadence": cad, "window": [S, E_], "final": r["final"],
                "cagr_pct": cagr, "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"],
                "halts": r["halts"], "restart": r["restart"],
                "restart_info": r["restart_info"],
                "second_halt": r["second_halt"],
                "equity_curve": r["curve"],
                "n_events": r["n_events_listed"],
                "n_events_with_picks": r["n_with_picks"],
                "calendar_n_events_with_picks": cp["n_with_picks"],
                "event_stats": st, "events": r["events"],
                "placebo_beaten": beaten,
                "placebo_finals": [round(f, 2) for f in finals],
                "placebo_median": round(statistics.median(finals), 2),
                "calendar_placebo_final": cp["final"],
                "calendar_placebo_costs": cp["costs"],
                "calendar_placebo_orders": cp["orders"],
                "calendar_placebo_halts": cp["halts"],
                "calendar_placebo_event_stats": st_cal,
                "calendar_placebo_equity_curve": cp["curve"],
                "beats_calendar_placebo": r["final"] > cp["final"],
                "calendar_placebo_beats_design_placebo_median": None,
                "design_placebo_beaten_by_calendar": beaten_cal,
                "spy_final": spy_dec}
        json.dump(cell, open(os.path.join(HERE, "cells", f"{cad}.json"), "w"),
                  indent=1)
        results[cad] = cell
        print(cad, "ranked", r["final"], "calPlacebo", cp["final"],
              "placebo", f"{beaten}/20", "events", st["n_events_traded"],
              "meanNetExcess", st["mean_excess_net_pct"],
              "halts", r["halts"], flush=True)
    json.dump({"validation": checks, "decade_spy": spy_dec,
               "cells": {c: {k: v for k, v in cell.items()
                             if k not in ("equity_curve", "events",
                                          "calendar_placebo_equity_curve")}
                         for c, cell in results.items()}},
              open(os.path.join(HERE, "sweep_raw.json"), "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
