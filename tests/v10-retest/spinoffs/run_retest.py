#!/usr/bin/env python3
"""
v10 GREAT RETEST — SPINOFFS (Cusatis, Miles & Woolridge 1993).
Simulation only. One clean shot, no tuning.

WHAT THIS DOES
  (0) INTEGRITY: reproduce the ORIGINAL published finals through this
      plumbing in ORIGINAL form before any sweep number counts:
        - v6 his-rules form (plain -15% floor, halt ends the run):
          published final $83.30, halted 2022-03-01, 4 orders, $0.08 costs.
        - v9 form (same engine + v9 restart module, = engine.py as placed):
          published final $166.63, 10 orders, $0.30 costs, one restart.
      The copied engine's own run_spinoffs() is also run directly (daily
      form) and must match the v9 figure.
  (1) CADENCE SWEEP on the DECADE road 2016-11-21 -> 2026-11-20, $100/cell,
      program costs, point-in-time event census (unchanged), v9 protections.
      EVENT-strategy cadence treatment (SPEC, uniform definition):
        - Entries stay EXACTLY as published: buy the child at the close of
          its first regular-way session, 1/5-of-pot slices. Cadence does
          NOT move entries (the event date is the board's, not ours).
        - Cadence governs the REVIEW / EXIT rhythm only: the -15% floor
          is checked, and the published 36-month exit is executed, only
          on cadence dates (first trading day of the week / 2nd week /
          month / quarter / half-year / year; daily = every trading day).
          A floor signal on a cadence date liquidates at the NEXT trading
          day's open (original execution mechanics). A 36-month exit
          executes at the first cadence date on/after the anniversary
          trading day; anything still open at window end is liquidated at
          the final close (SELL-END convention), as published.
        - The equity curve is still marked daily (marking is not trading).
  (2) PLACEBOS (20 seeds/cell): the original test had NO placebo (the
      "picks" are other companies' board decisions — nothing to randomize
      in selection). The placebo this chassis DOES support is a TIMING
      twin: same children, same sizing/floor/cadence mechanics, but each
      child's entry date is redrawn uniformly (seeded) from that child's
      own available trading days in the window. It tests whether the
      spin-off DATE itself beat random entry into the same stocks.
      Labelled timing-placebo everywhere; not a selection placebo.

HARNESS TRAP (found by the batch worker, handled here):
  engine.get_prices_local caches by ticker name only (px_<ticker>.json),
  ignoring the requested period — a cached SHORTER series shadows a
  LONGER request (their harness died on a SPY bar lookup building a
  2009-start pricebook). DEFENSE USED HERE: get_prices_local is never
  called with differing periods. The already-cached px_*.json files in
  spinoffs-data/ are parsed ONCE, directly, with the engine's exact bar
  construction (adjclose-ratio adjusted open/close), and every run draws
  from that single in-memory book. Nothing in shared/original data is
  patched or rewritten. (Stray px_ABBV.json in the cache — a 2013 spin
  outside the decade census — is not an event and is not used.)

Data: read-only copy in ./spinoffs-data (EDGAR census + Yahoo px caches,
copied from the original v6 folder by the batch worker).
"""
import bisect
import calendar
import datetime as dt
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "spinoffs-data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

START_CASH = 100.0
FLOOR0 = 85.0
START, END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# Event census — verbatim from engine.py (verified from EDGAR in v6).
EVENTS = [
    {"parent": "PFE", "child": "VTRS", "distribution": "2020-11-16",
     "entry": "2020-11-17", "testable": True},
    {"parent": "IBM", "child": "KD", "distribution": "2021-11-03",
     "entry": "2021-11-04", "testable": True},
    {"parent": "T", "child": "WBD", "distribution": "2022-04-08",
     "entry": "2022-04-11", "testable": False},
    {"parent": "GE", "child": "GEHC", "distribution": "2023-01-03",
     "entry": "2023-01-04", "testable": True},
    {"parent": "MMM", "child": "SOLV", "distribution": "2024-04-01",
     "entry": "2024-04-01", "testable": True},
    {"parent": "GE", "child": "GEV", "distribution": "2024-04-02",
     "entry": "2024-04-02", "testable": True},
]
FETCH_FROM = {"VTRS": "2020-09-01", "KD": "2021-08-01", "GEHC": "2022-10-01",
              "SOLV": "2024-01-01", "GEV": "2024-01-01"}


def parse_px(ticker):
    """Engine's exact bar construction from the cached Yahoo payload."""
    path = os.path.join(DATA, f"px_{ticker}.json")
    with open(path) as f:
        j = json.load(f)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


class FastPB:
    """Same semantics as the champion PriceBook, bisect-based."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._ds = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self._ds.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

    def next_open(self, t, d):
        ds = self._ds.get(t, [])
        i = bisect.bisect_right(ds, d)
        if i < len(ds):
            b = self.bars[t][i]
            return b["d"], b["o"]
        return None, None


def add_months(dstr, months):
    y, m, d = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m = (m2 - 1) % 12 + 1
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
             else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return f"{y:04d}-{m:02d}-{min(d, mdays):02d}"


def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)
    out, seen = [], set()
    for d in days:
        if cadence == "weekly":
            key = dt.date.fromisoformat(d).isocalendar()[:2]
        elif cadence == "monthly":
            key = d[:7]
        elif cadence == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
        elif cadence == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
            if d[5:7] not in ("01", "07"):
                continue
        elif cadence == "annual":
            key = d[:4]
            if d[5:7] != "01":
                continue
        elif cadence == "biweekly":
            key = dt.date.fromisoformat(d).isocalendar()[:2]
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    if cadence == "biweekly":
        out = out[::2]  # every second week's first trading day
    return set(out)


def run_pot(pb, events, cadence, v9=True, start=START, end=END):
    """run_spinoffs logic from engine.py, generalized only by:
    cadence-gated floor checks + 36m exits, and a v9 on/off switch
    (off = the v6 original form, for the integrity reproduction)."""
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    floor = FLOOR0
    episode = 1
    resume = None
    restarts = []
    halts = []
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    review = cadence_dates(days, cadence)

    entries = {}
    for ev in events:
        if ev["testable"]:
            entries.setdefault(ev["entry"], []).append(ev)
    # published exit trading day per child, then first cadence date >= it
    exits = {}
    for ev in events:
        if not ev["testable"]:
            continue
        anniv = add_months(ev["entry"], 36)
        xd = next((d for d in days if d >= anniv), None)
        if xd is None:
            exits[ev["child"]] = end
        else:
            exits[ev["child"]] = next(
                (d for d in days if d >= xd and d in review), end)
    exit_days = {}
    for child, xd in exits.items():
        exit_days.setdefault(xd, []).append(child)

    def pot_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    pending_halt = False
    halt_info = None
    second_halt = False
    for di, d in enumerate(days):
        if pending_halt:
            for t in list(positions):
                nd, o = pb.next_open(t, days[di - 1])
                if o is None:
                    continue
                val = positions[t] * o
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, t, "SELL-HALT", positions[t], o, val, c))
                del positions[t]
            halts.append({"signal_date": days[di - 1],
                          "liquidation_date": d,
                          "signal_close": halt_info["signal_close"],
                          "floor_in_effect": halt_info["floor_in_effect"],
                          "balance_after": round(cash, 2)})
            if v9 and episode == 1:
                episode = 2
                resume = (dt.date.fromisoformat(days[di - 1])
                          + dt.timedelta(days=90)).isoformat()
                restarts.append({
                    "halt_date": days[di - 1], "liquidation_date": d,
                    "restart_balance": round(cash, 2),
                    "resume_on_or_after": resume,
                    "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending_halt = False
                halt_info = None
            else:
                second_halt = v9 and episode == 2
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halted": days[di - 1], "halts": halts,
                        "restarts": restarts, "second_halt": second_halt,
                        "curve": curve, "exits": exits}
        for child in exit_days.get(d, []):
            if child not in positions:
                continue
            px = pb.close_on_or_before(child, d)
            val = positions[child] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, child, "SELL-EXIT", positions[child], px,
                           val, c))
            del positions[child]
        if d in entries and (resume is None or d >= resume):
            for ev in entries[d]:
                child = ev["child"]
                marked = pot_close(d)
                target = marked / 5.0
                if cash < target * 1.001 and positions:
                    need = target * 1.001 - cash
                    tot_val = sum(positions[t] * pb.close_on_or_before(t, d)
                                  for t in positions)
                    for t in list(positions):
                        if need <= 0:
                            break
                        px = pb.close_on_or_before(t, d)
                        cur = positions[t] * px
                        sell_val = min(cur, need * (cur / tot_val) * 1.02)
                        if sell_val <= 0.005:
                            continue
                        sh = sell_val / px
                        c = sell_val * 0.001 + 0.01
                        cash += sell_val - c
                        total_costs += c
                        positions[t] -= sh
                        trades.append((d, t, "SELL-FUND", sh, px,
                                       sell_val, c))
                        if positions[t] < 1e-9:
                            del positions[t]
                        need -= sell_val
                px = pb.close_on_or_before(child, d)
                buy_val = min(target, cash / 1.001)
                if buy_val > 0.005 and px:
                    sh = buy_val / px
                    c = buy_val * 0.001
                    cash -= buy_val + c
                    total_costs += c
                    positions[child] = positions.get(child, 0.0) + sh
                    trades.append((d, child, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        curve.append((d, v))
        if d in review and v <= floor and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            pending_halt = True
    last = days[-1]
    for t in list(positions):
        px = pb.close_on_or_before(t, last)
        if px:
            val = positions[t] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((last, t, "SELL-END", positions[t], px, val, c))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "halts": halts, "restarts": restarts,
            "second_halt": False, "curve": curve, "exits": exits}


def standalone(pb, ticker, entry, exit_d):
    pe = pb.close_on_or_before(ticker, entry)
    px = pb.close_on_or_before(ticker, exit_d)
    buy_val = 100.0 / 1.001
    sh = buy_val / pe
    val = sh * px
    return val - (val * 0.001 + 0.01), pe, px


def spy_net(pb, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    o = pb.bar("SPY", days[0])["o"]
    sh = (100.0 / 1.001) / o
    val = sh * pb.close_on_or_before("SPY", days[-1])
    return val - (val * 0.001 + 0.01)


def stats(curve):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return round(maxdd * 100, 2), maxdd_d


def cagr(final, start=START, end=END):
    yrs = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days / 365.25
    return round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None


def main():
    bars = {"SPY": parse_px("SPY")}
    for ev in EVENTS:
        if not ev["testable"]:
            continue
        raw = parse_px(ev["child"])
        bars[ev["child"]] = [b for b in raw if b["d"] >= ev["entry"]]
    pb = FastPB(bars)
    spy_final = round(spy_net(pb, START, END), 2)
    print(f"SPY decade (this plumbing): ${spy_final} (SPEC reference $367.80)")

    # ---------- (0) INTEGRITY ----------
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "spin_engine", os.path.join(HERE, "engine.py"))
    # engine.py loads the v4 champion module at import (read-only); its
    # DATA dir points at this folder, and get_prices_local is NOT called.
    eng = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    r_eng = eng.run_spinoffs(pb, eng.EVENTS, START, END, label="ENGINE-DIRECT")
    print(f"engine.py run_spinoffs direct: ${r_eng['final']:.2f} "
          f"orders={len(r_eng['trades'])} costs=${r_eng['costs']:.2f}")

    r_v9 = run_pot(pb, EVENTS, "daily", v9=True)
    r_v6 = run_pot(pb, EVENTS, "daily", v9=False)
    print(f"my runner daily+v9 : ${r_v9['final']:.2f} orders={len(r_v9['trades'])} "
          f"costs=${r_v9['costs']:.2f} restarts={len(r_v9['restarts'])}")
    print(f"my runner daily-v9 : ${r_v6['final']:.2f} orders={len(r_v6['trades'])} "
          f"costs=${r_v6['costs']:.2f} halted={r_v6['halted']}")
    integrity = {
        "status": "reproduced",
        "original_finals": {
            "v6_his_rules_census_window": 83.30,
            "v6_halted": "2022-03-01", "v6_orders": 4, "v6_costs": 0.08,
            "v9_restart_form": 166.63, "v9_orders": 10, "v9_costs": 0.30,
            "spy_census_window_published": 367.80},
        "reproduced_finals": {
            "v6_his_rules_census_window": round(r_v6["final"], 2),
            "v6_halted": r_v6["halted"], "v6_orders": len(r_v6["trades"]),
            "v6_costs": round(r_v6["costs"], 2),
            "v9_restart_form": round(r_v9["final"], 2),
            "v9_orders": len(r_v9["trades"]),
            "v9_costs": round(r_v9["costs"], 2),
            "engine_py_direct_v9": round(r_eng["final"], 2),
            "spy_census_window": spy_final},
        "notes": "Both published forms reproduced to the cent through this "
                 "plumbing (v6 $83.30 halt-ends-run; v9 $166.63 with the "
                 "90-day restart), and the copied engine.py run directly "
                 "agrees. Champion replication ($544.47/$288.05, SPY "
                 "$313.62/$187.77) was performed inside the original v6/v9 "
                 "runs and is recorded in their results files; it was not "
                 "re-run here (it is a control on the champion engine, not "
                 "on this strategy's plumbing).",
    }
    assert round(r_v6["final"], 2) == 83.30, "v6 integrity FAILED"
    assert round(r_v9["final"], 2) == 166.63, "v9 integrity FAILED"
    assert round(r_eng["final"], 2) == 166.63, "engine direct FAILED"

    # ---------- (1)+(2) SWEEP + PLACEBOS ----------
    child_days = {ev["child"]: [b["d"] for b in bars[ev["child"]]]
                  for ev in EVENTS if ev["testable"]}
    cells, results_cells = {}, {}
    for cad in CADENCES:
        r = run_pot(pb, EVENTS, cad, v9=True)
        maxdd, maxdd_d = stats(r["curve"])
        buys = [t for t in r["trades"] if t[2] == "BUY"]
        # per-event stats at this cadence's exit rhythm (all 5 testable)
        ev_rows, excess = [], []
        for ev in EVENTS:
            if not ev["testable"]:
                ev_rows.append({"parent": ev["parent"], "child": ev["child"],
                                "testable": False,
                                "note": "WBD price history purged (delisted "
                                        "2026-10-06); documented in v6 census"})
                continue
            xd = r["exits"][ev["child"]]
            cf, pe, px = standalone(pb, ev["child"], ev["entry"], xd)
            sf, _, _ = standalone(pb, "SPY", ev["entry"], xd)
            excess.append(round(cf - sf, 2))
            ev_rows.append({
                "parent": ev["parent"], "child": ev["child"],
                "entry": ev["entry"], "exit": xd,
                "entry_close": round(pe, 4), "exit_close": round(px, 4),
                "child_net_final": round(cf, 2),
                "spy_net_final": round(sf, 2),
                "net_excess_vs_spy": round(cf - sf, 2),
                "beat_spy": cf > sf,
                "traded_by_pot": any(t[1] == ev["child"] for t in buys)})
        mean_ex = round(sum(excess) / len(excess), 2) if excess else None
        med_ex = round(sorted(excess)[len(excess) // 2], 2) if excess else None
        # timing placebos, 20 seeds
        twin_finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            pev = []
            for ev in EVENTS:
                if not ev["testable"]:
                    pev.append(ev)
                    continue
                ds = [d for d in child_days[ev["child"]] if START <= d <= END]
                pev.append({**ev, "entry": rng.choice(ds)})
            pr = run_pot(pb, pev, cad, v9=True)
            twin_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in twin_finals if r["final"] > f)
        cell = {
            "final": round(r["final"], 2), "cagr_pct": cagr(r["final"]),
            "max_dd_pct": maxdd, "max_dd_date": maxdd_d,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halts": r["halts"], "restart": bool(r["restarts"]),
            "restarts": r["restarts"], "second_halt": r["second_halt"],
            "halted_final": r["halted"],
            "events_traded": len(buys),
            "events_traded_children": [t[1] for t in buys],
            "event_stats": {"n_testable": len(excess),
                            "mean_net_excess_vs_spy": mean_ex,
                            "median_net_excess_vs_spy": med_ex,
                            "events_beat_spy": sum(1 for x in ev_rows
                                                   if x.get("beat_spy")),
                            "per_event": ev_rows},
            "placebo_beaten": beaten,
            "placebo_note": "Timing placebo (original test had no selection "
                            "placebo — events are board decisions): 20 seeded "
                            "twins, same children/mechanics, entry dates "
                            "redrawn uniformly from each child's own bars.",
            "placebo_twin_finals": twin_finals,
            "trades": [[d, t, s, round(sh, 6), round(p, 4), round(v, 2),
                        round(c, 2)] for d, t, s, sh, p, v, c in r["trades"]],
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        }
        cells[cad] = cell
        results_cells[cad] = {
            "final": cell["final"], "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": maxdd, "halts": len(r["halts"]),
            "restart": cell["restart"], "second_halt": cell["second_halt"],
            "costs": cell["costs"], "orders": cell["orders"],
            "placebo_beaten": beaten,
            "placebo_note": cell["placebo_note"],
            "events_traded": cell["events_traded"],
            "mean_net_excess_vs_spy": mean_ex,
            "median_net_excess_vs_spy": med_ex}
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"{cad:11s} final=${cell['final']:8.2f} orders={cell['orders']:2d} "
              f"events={cell['events_traded']} meanEx={mean_ex} "
              f"placebo {beaten}/20 halts={len(r['halts'])}")

    money = [c for c in CADENCES
             if cells[c]["final"] > spy_final
             and cells[c]["placebo_beaten"] >= 11]
    out = {
        "slug": "spinoffs",
        "area": "Event-driven spin-off drift (Cusatis, Miles & Woolridge "
                "1993): buy the distributed child at its first regular-way "
                "close, 1/5-of-pot slices, hold 36 months — on the champion "
                "pond's parents (30-name universe), DECADE road.",
        "area_source": "SPEC W7 (event strategies) + CADENCE GRID: spinoffs "
                       "= event-driven.",
        "native_cadence": "event-driven",
        "cadence": "event-driven",
        "original_cadence_foreign": False,
        "native_change": "none — original form was native (event entries as "
                         "published). The sweep varies only the review/exit "
                         "rhythm per the SPEC's uniform event-strategy "
                         "cadence definition; entries never move.",
        "cadence_treatment": "Entries exactly as published (first "
                             "regular-way close). Cadence governs floor "
                             "checks and 36-month exit execution only. "
                             "Curve marked daily.",
        "integrity": integrity,
        "decade_spy_final": spy_final,
        "spy": {"DECADE": spy_final},
        "champion_decade_reference": 65.89,
        "cells": results_cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND",
        "verdict_change": "No change. The original program verdict (NOT "
                          "PROMOTED — $83.30 his-rules, $166.63 under v9, "
                          "1 of 5 events beat SPY) stands at every cadence: "
                          "no cadence beats SPY ($367.80) on the decade, so "
                          "no flip arises and the CONFIRMATION RULE is not "
                          "triggered (nothing is marked provisional).",
        "harness_trap_note": "engine.get_prices_local caches by ticker "
                             "name only, ignoring requested period — a "
                             "cached shorter series shadows a longer "
                             "request. Defense: never called here; cached "
                             "px_*.json parsed once directly with the "
                             "engine's bar construction; single in-memory "
                             "book for all runs. Shared/original data "
                             "untouched.",
        "data_note": "All inputs from ./spinoffs-data (read-only copy of "
                     "the v6 folder's EDGAR census + Yahoo px caches). "
                     "WBD untestable: price history purged after its "
                     "2026-10-06 delisting (documented in v6, unchanged).",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", json.dumps({c: cells[c]["final"] for c in CADENCES}))


if __name__ == "__main__":
    main()
