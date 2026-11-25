#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — breakout-basket (v12 holdings wing).

FROZEN COUNT MAPPING (written before any run, per PROGRAM.md grid +
the PEAD precedent in holdings-pead):
  The frozen v4/v10 chassis HAS a ranking: when more names signal than
  free slots, slots go to the largest % gain on the signal day
  (run_retest.py: sigs.sort(key=lambda x: -x[1])). Count is therefore a
  genuine sweep variable here: count N -> max N concurrent positions,
  slice = equity/N at entry (native count 5 -> the original 20% slice).
  Grid: 1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE. Universe is only 10 names,
  so counts 15/20/30 are CAPPED at 10 and ALL-ELIGIBLE = 10; capped cells
  are computed once at count 10 and printed as capped duplicates.
  Cadence: daily only (the family's native cadence; the v10 cadence
  sweep already owns the tempo question).
  Forms: HOUSE = v9 protections (plain -15% floor, 90-day sit-out, one
  restart, second halt ends run) — the v10 retest form. NATIVE = the
  original v4 basket form: no floor at all (the basket removed the halt).
  Roads (all the v2 tournament cache honestly supports; it starts
  2016-11-21 with 252-session warmup in-cache): DECADE
  2016-11-21->2026-11-20, DESIGN 2016-11-21->2022-12-31, VAL
  2023-01-01->2026-11-20 (fresh pot). LONG/CONT do not exist on this data.
  Costs: 0.10%/side + $0.01/sell. Placebos: the family's own v4 design —
  random (day,symbol) entries matched to filled entries per calendar
  year, iterative top-up (max 12 rounds), same exits/costs/form,
  20 seeds 90210-90229 per cell.
  Reproduction gate: house form, count 5, DECADE must equal $309.85
  (v10 daily cell) before any sweep number is trusted.
Simulation only. Shared v2/v10 inputs are READ-ONLY.
"""
import json, os, sys
from datetime import date, timedelta
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v2/tournament-data")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
COST, SELL_FEE, STOP = 0.001, 0.01, 0.08
GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
DISTINCT = [1, 2, 3, 5, 8, 10]           # 15/20/30/ALL cap at universe = 10
NATIVE_COUNT = 5
ROADS = {
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "DESIGN": (date(2016, 11, 21), date(2022, 12, 31)),
    "VAL":    (date(2023, 1, 1),  date(2026, 11, 20)),
    "CONF_A": (date(2018, 1, 1),  date(2021, 12, 31)),
    "CONF_B": (date(2022, 1, 1),  date(2025, 12, 31)),
}

def load():
    raw = {}
    for s in UNIVERSE:
        df = pd.read_csv(os.path.join(DATA, f"{s}.csv"))
        df["date"] = pd.to_datetime(df["date"]).dt.date
        raw[s] = df
    spy_dates = list(raw["SPY"]["date"])
    F = {}
    for s, df in raw.items():
        d = df.set_index("date").reindex(spy_dates)
        d[["open", "high", "low", "close"]] = d[["open", "high", "low", "close"]].ffill()
        d = d.reset_index().rename(columns={"index": "date"})
        c = d["close"].astype(float)
        F[s] = dict(o=d["open"].astype(float).values, h=d["high"].astype(float).values,
                    l=d["low"].astype(float).values, c=c.values,
                    sma20=c.rolling(20).mean().values,
                    p252=c.shift(1).rolling(252).max().values)
    return spy_dates, F

DATES, F = load()

def run(tidx, maxpos, house, placebo_sched=None):
    frac = 1.0 / maxpos
    tdates = [DATES[i] for i in tidx]
    cash, lots = 100.0, {}
    costs, orders = 0.0, 0
    curve, entries_by_year = [], {}
    pend_in, pend_out = [], []
    episode, floor = 1, 85.0
    halts, restart_date, state = [], None, "run"
    sit_until = None
    last = len(tdates) - 1
    for k, d in enumerate(tdates):
        p = tidx[k]
        omap = {s: F[s]["o"][p] for s in UNIVERSE}
        cmap = {s: F[s]["c"][p] for s in UNIVERSE}
        def equity(mp):
            return cash + sum(sh * mp[s] for s, (sh, _) in lots.items())
        def sell(sym, px):
            nonlocal cash, costs, orders
            sh, _ = lots.pop(sym)
            val = sh * px; cst = COST * val + SELL_FEE
            cash += val - cst; costs += cst; orders += 1
        if house and state == "sit" and d >= sit_until:
            state, episode = "run", 2
            floor = 0.85 * cash; restart_date = d
        if state == "done":
            curve.append((d, cash)); continue
        if state == "run":
            for sym in pend_out:
                if sym in lots: sell(sym, omap[sym])
            pend_out = []
            cands = [(s, 0.0) for s in placebo_sched.get(d, [])] if placebo_sched is not None else pend_in
            pend_in = []
            for sym, _g in cands:
                if sym in lots or len(lots) >= maxpos: continue
                tgt = frac * equity(omap)
                val = min(tgt, cash / (1 + COST))
                if val < 1.0: continue
                cst = COST * val; cash -= val + cst; costs += cst; orders += 1
                lots[sym] = [val / omap[sym], omap[sym]]
                entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        if state == "run":
            for sym in list(lots):
                sh, ep = lots[sym]
                o, lo = F[sym]["o"][p], F[sym]["l"][p]
                sp = ep * (1 - STOP)
                if o <= sp: sell(sym, o)
                elif lo <= sp: sell(sym, sp)
        eq = equity(cmap)
        curve.append((d, eq))
        if house and state == "run" and eq <= floor:
            halts.append({"episode": episode, "trigger_date": d.isoformat(),
                          "floor": round(floor, 2), "equity_at_trigger": round(eq, 2)})
            if k < last:
                p2 = tidx[k + 1]
                for sym in list(lots): sell(sym, F[sym]["o"][p2])
                halts[-1]["liquidation_date"] = tdates[k + 1].isoformat()
                halts[-1]["cash_after"] = round(cash, 2)
            else:
                halts[-1]["liquidation_date"] = d.isoformat(); halts[-1]["cash_after"] = round(eq, 2)
            if episode == 1:
                state = "sit"; sit_until = d + timedelta(days=90)
                pend_in, pend_out = [], []
            else:
                state = "done"
            continue
        if state == "sit":
            curve[-1] = (d, cash)
        if state == "run" and k < last:
            for sym in list(lots):
                s20 = F[sym]["sma20"][p]
                if not np.isnan(s20) and cmap[sym] < s20: pend_out.append(sym)
            if placebo_sched is None:
                sigs = []
                for sym in UNIVERSE:
                    if sym in lots: continue
                    ph = F[sym]["p252"][p]
                    if p >= 253 and not np.isnan(ph) and cmap[sym] > ph:
                        prev = F[sym]["c"][p - 1]
                        sigs.append((sym, cmap[sym] / prev - 1 if prev > 0 else 0.0))
                sigs.sort(key=lambda x: -x[1]); pend_in = sigs
    final = curve[-1][1]
    peak, mdd = 100.0, 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak * 100 if peak > 0 else 0.0)
    return dict(final=round(final, 2), max_dd_pct=round(mdd, 2), costs=round(costs, 2),
                orders=orders, halts=halts, entries_by_year=entries_by_year,
                curve=[[d.isoformat(), round(e, 4)] for d, e in curve])

def placebo(tidx, maxpos, house, target_by_year, seed):
    rng = np.random.default_rng(seed)
    tdates = [DATES[i] for i in tidx]
    idx_of = {d: i for i, d in enumerate(tdates)}
    days_by_year = {}
    for d in tdates[:-1]: days_by_year.setdefault(d.year, []).append(d)
    sched = {}
    def add(year, n):
        days = days_by_year.get(year, [])
        if not days: return
        for _ in range(n):
            d = days[rng.integers(0, len(days))]; i = idx_of[d]
            while len(sched.get(d, [])) >= maxpos and i < len(tdates) - 1:
                i += 1; d = tdates[i]
            sched.setdefault(d, []).append(UNIVERSE[rng.integers(0, len(UNIVERSE))])
    for y, t in sorted(target_by_year.items()): add(y, t)
    r = None
    for _ in range(12):
        r = run(tidx, maxpos, house, placebo_sched=sched)
        missing = {y: target_by_year.get(y, 0) - r["entries_by_year"].get(y, 0) for y in target_by_year}
        if all(v <= 0 for v in missing.values()): break
        for y, m in missing.items():
            if m > 0: add(y, m)
    return r["final"]

def tidx_for(road):
    s, e = ROADS[road]
    return [i for i, d in enumerate(DATES) if s <= d <= e]

def spy_net(road):
    ti = tidx_for(road)
    o = F["SPY"]["o"][ti[0]]; c = F["SPY"]["c"][ti[-1]]
    v = (100.0 / (1 + COST)) / o * c
    return round(v - (COST * v + SELL_FEE), 2)

def period_stats(curve):
    """Monthly distribution from a daily equity curve (reporting standard)."""
    months = {}
    for dstr, v in curve:
        months[dstr[:7]] = v
    keys = sorted(months)
    rets, prev = [], 100.0
    for k in keys:
        rets.append(months[k] / prev - 1.0); prev = months[k]
    if not rets: return None
    srt = sorted(rets)
    med = srt[len(srt) // 2] if len(srt) % 2 else 0.5 * (srt[len(srt)//2 - 1] + srt[len(srt)//2])
    los, run_l = 0, 0
    for r in rets:
        run_l = run_l + 1 if r < 0 else 0; los = max(los, run_l)
    peak, since, longest = -1.0, 0, 0
    vals = [100.0] + [months[k] for k in keys]
    for v in vals:
        if v >= peak: peak, since = v, 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(med * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2), "longest_losing_run": los,
            "longest_between_highs_months": longest,
            "average_pct_secondary": round(sum(rets) / len(rets) * 100, 2)}

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "main"   # main | confirm
    roads = ["DECADE", "DESIGN", "VAL"] if which == "main" else ["CONF_A", "CONF_B"]
    counts = DISTINCT if which == "main" else [1, 2, 3, 5, 8, 10]
    out_path = os.path.join(HERE, "results.json" if which == "main" else "confirm.json")
    out = {"family": "breakout-basket", "native_count": NATIVE_COUNT, "grid": [str(g) for g in GRID],
           "cap_note": "Universe = 10 names: counts 15/20/30 capped at 10; ALL-ELIGIBLE = 10. Capped cells equal the count-10 cell.",
           "cells": {}}
    if which == "main":
        gate = run(tidx_for("DECADE"), 5, True)
        out["reproduction_gate"] = {"house_count5_DECADE": gate["final"], "expected": 309.85,
                                    "match": abs(gate["final"] - 309.85) < 0.005}
        print(f"GATE house count5 DECADE ${gate['final']} (expect 309.85) match={out['reproduction_gate']['match']}", flush=True)
    for form, house in (("house", True), ("native", False)):
        for road in roads:
            ti = tidx_for(road)
            out.setdefault("spy_price_only_net", {})[road] = spy_net(road)
            for n in counts:
                r = run(ti, n, house)
                twins = [placebo(ti, n, house, r["entries_by_year"], 90210 + i) for i in range(20)]
                beaten = sum(1 for t in twins if r["final"] > t)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                        "orders": r["orders"], "n_halts": len(r["halts"]), "halts": r["halts"],
                        "placebo_beaten": beaten, "placebo_twin_finals": [round(t, 2) for t in twins]}
                if road == "DECADE":
                    cell["curve"] = r["curve"]
                    cell["period_stats_monthly"] = period_stats(r["curve"])
                out["cells"][f"{form}|{road}|{n}"] = cell
                print(f"{form} {road} count={n}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} halts {len(r['halts'])} placebo {beaten}/20", flush=True)
    json.dump(out, open(out_path, "w"), indent=1,
              default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o))
    print("DONE", out_path, flush=True)

def parts_main():
    """Foreground-chunked mode: argv = comma list of form:road:count jobs.
    Each finished cell is saved immediately to part_<form>_<road>_<n>.json
    (or cpart_ for CONF roads) so a killed call loses nothing."""
    jobs = sys.argv[2].split(",")
    for job in jobs:
        form, road, n = job.split(":")
        n = int(n); house = (form == "house")
        ti = tidx_for(road)
        r = run(ti, n, house)
        twins = [placebo(ti, n, house, r["entries_by_year"], 90210 + i) for i in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                "orders": r["orders"], "n_halts": len(r["halts"]), "halts": r["halts"],
                "placebo_beaten": beaten, "placebo_twin_finals": [round(t, 2) for t in twins],
                "spy_price_only_net": spy_net(road)}
        if road == "DECADE":
            cell["curve"] = r["curve"]
            cell["period_stats_monthly"] = period_stats(r["curve"])
        pre = "cpart" if road.startswith("CONF") else "part"
        path = os.path.join(HERE, f"{pre}_{form}_{road}_{n}.json")
        with open(path, "w") as fh:
            json.dump(cell, fh, indent=1, default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o))
        print(f"{form} {road} count={n}: ${r['final']} DD {r['max_dd_pct']}% placebo {beaten}/20 -> {os.path.basename(path)}", flush=True)
    print("PARTS DONE", flush=True)

def emit_main():
    """argv: emit form:road:count — prints ONLY the cell JSON to stdout
    (the caller pipes it through node to write the file; python file
    writes are intermittently EPERM-blocked in this sandbox)."""
    form, road, n = sys.argv[2].split(":")
    n = int(n); house = (form == "house")
    ti = tidx_for(road)
    r = run(ti, n, house)
    twins = [placebo(ti, n, house, r["entries_by_year"], 90210 + i) for i in range(20)]
    beaten = sum(1 for t in twins if r["final"] > t)
    cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "n_halts": len(r["halts"]), "halts": r["halts"],
            "placebo_beaten": beaten, "placebo_twin_finals": [round(t, 2) for t in twins],
            "spy_price_only_net": spy_net(road)}
    if road == "DECADE":
        cell["curve"] = r["curve"]
        cell["period_stats_monthly"] = period_stats(r["curve"])
    print(json.dumps(cell, default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o)))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "parts":
        parts_main()
    elif len(sys.argv) > 1 and sys.argv[1] == "emit":
        emit_main()
    else:
        main()
