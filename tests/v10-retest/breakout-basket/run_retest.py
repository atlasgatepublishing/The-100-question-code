#!/usr/bin/env python3
"""THE GREAT RETEST (v10) — breakout-basket cadence sweep.

Strategy (unchanged from v4): 52-week-high breakout BASKET. Entry signal:
close above the highest close of the prior 252 sessions. Up to 5 positions
at 20% of equity each; if more names signal than free slots, slots go to the
largest % gain on the signal day. Exits: close below the 20-day average
(fill next open); -8% intraday stop (stop-first, gaps fill at the open).
Costs: program conventions, identical to the original engine — 0.10%/side
plus $0.01 per sell order. Universe: the original 10 names (SPY QQQ NVDA
TSLA AAPL MSFT AMZN META AMD AVGO), Yahoo daily bars cached by the v2
tournament (split-adjusted, NOT dividend-adjusted), read-only.

CADENCE TREATMENT (per SPEC uniform definition + task instruction):
breakout signals are computed from daily closes, but signal EVALUATION,
MA-exit evaluation, and rotation happen ONLY on cadence dates. A breakout
that fires on a non-cadence day is never acted on. Entries scheduled at a
cadence date's close fill at the next trading day's open (the original
engine's fill convention); MA exits likewise. The -8% intraday stop is a
risk exit, not a signal: it is checked every trading day, as in the
original. The v9 floor is checked on every close (protection, not signal).

PROTECTION (v9, adopted): plain -15% floor from the episode's starting
balance, NO ladder. On a halt: liquidate at the next open, sit in cash 90
calendar days, restart at the next cadence date on/after the sit ends,
under an episode-2 floor of -15% from the restart balance. A second halt
liquidates at the next open and ends the run.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.
PLACEBOS: per cell, 20 seeds — the family's own design (v4): random
(day, symbol) entry attempts matched to the real run's FILLED entries per
calendar year (iterative top-up, max 12 rounds), same exits/costs/v9
protection, evaluated under the same cadence.
"""
import json, os
from datetime import date, timedelta
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v2", "tournament-data")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START, END = date(2016, 11, 21), date(2026, 11, 20)
COST, SELL_FEE, STOP, MAXPOS, FRAC = 0.001, 0.01, 0.08, 5, 0.20
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]

# ---------------- data ----------------
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
POS = {d: i for i, d in enumerate(DATES)}
TIDX = [i for i, d in enumerate(DATES) if START <= d <= END]
TDATES = [DATES[i] for i in TIDX]

def cadence_mask(cad):
    if cad == "daily":
        return set(range(len(TDATES)))
    out, prev_key, wk = set(), None, -1
    for k, d in enumerate(TDATES):
        if cad == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key: out.add(k); prev_key = key
        elif cad == "biweekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key:
                wk += 1; prev_key = key
                if wk % 2 == 0: out.add(k)
        elif cad == "monthly":
            key = (d.year, d.month)
            if key != prev_key: out.add(k); prev_key = key
        elif cad == "quarterly":
            key = (d.year, (d.month - 1) // 3)
            if key != prev_key: out.add(k); prev_key = key
        elif cad == "semiannual":
            key = (d.year, (d.month - 1) // 6)
            if key != prev_key: out.add(k); prev_key = key
        elif cad == "annual":
            if d.year != prev_key: out.add(k); prev_key = d.year
    return out

# ---------------- engine ----------------
def run(cad_set, placebo_sched=None):
    cash, lots = 100.0, {}          # sym -> [shares, entry_price]
    costs, orders = 0.0, 0
    curve, entries_by_year = [], {}
    pend_in, pend_out = [], []      # entries: (sym, gain); exits: sym
    episode, floor = 1, 85.0
    halts, restart_date, state = [], None, "run"   # state: run | sit | done
    sit_until, ep_start_cash = None, 100.0
    last = len(TDATES) - 1
    for k, d in enumerate(TDATES):
        p = TIDX[k]
        omap = {s: F[s]["o"][p] for s in UNIVERSE}
        cmap = {s: F[s]["c"][p] for s in UNIVERSE}
        def equity(mp):
            return cash + sum(sh * mp[s] for s, (sh, _) in lots.items())
        def sell(sym, px, reason):
            nonlocal cash, costs, orders
            sh, _ = lots.pop(sym)
            val = sh * px; cst = COST * val + SELL_FEE
            cash += val - cst; costs += cst; orders += 1
        if state == "sit" and d >= sit_until and k in cad_set:
            state, episode = "run", 2
            ep_start_cash = cash; floor = 0.85 * cash; restart_date = d
        if state == "done":
            curve.append((d, cash)); continue
        halt_pending = False
        # entries at open (scheduled at a prior cadence close / placebo date)
        if state == "run":
            for sym in pend_out:
                if sym in lots: sell(sym, omap[sym], "ma-exit")
            pend_out = []
            cands = [(s, 0.0) for s in placebo_sched.get(d, [])] if placebo_sched is not None else pend_in
            pend_in = []
            for sym, _g in cands:
                if sym in lots or len(lots) >= MAXPOS: continue
                tgt = FRAC * equity(omap)
                val = min(tgt, cash / (1 + COST))
                if val < 1.0: continue
                cst = COST * val; cash -= val + cst; costs += cst; orders += 1
                lots[sym] = [val / omap[sym], omap[sym]]
                entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        # intraday -8% stop, every trading day (risk exit, as original)
        if state == "run":
            for sym in list(lots):
                sh, ep = lots[sym]
                o, lo = F[sym]["o"][p], F[sym]["l"][p]
                sp = ep * (1 - STOP)
                if o <= sp: sell(sym, o, "stop-gap")
                elif lo <= sp: sell(sym, sp, "stop")
        eq = equity(cmap)
        curve.append((d, eq))
        # v9 floor on every close
        if state == "run" and eq <= floor:
            halts.append({"episode": episode, "trigger_date": d.isoformat(),
                          "floor": round(floor, 2), "equity_at_trigger": round(eq, 2)})
            if k < last:
                p2 = TIDX[k + 1]
                for sym in list(lots): sell(sym, F[sym]["o"][p2], "floor-liquidation")
                halts[-1]["liquidation_date"] = TDATES[k + 1].isoformat()
                halts[-1]["cash_after"] = round(cash, 2)
            else:
                halts[-1]["liquidation_date"] = d.isoformat(); halts[-1]["cash_after"] = round(eq, 2)
            if episode == 1:
                state = "sit"; sit_until = d + timedelta(days=90)
                pend_in, pend_out = [], []
                curve[-1] = (d, eq)  # close mark stands; cash period marks cash below
            else:
                state = "done"
            continue
        if state == "sit":
            curve[-1] = (d, cash)
        # cadence-date evaluation: MA exits + breakout signals (close data)
        if state == "run" and k in cad_set and k < last:
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
    yrs = (END - START).days / 365.25
    return dict(final=round(final, 2), cagr_pct=round(((final / 100) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
                max_dd_pct=round(mdd, 2), costs=round(costs, 2), orders=orders,
                halts=halts, restart=restart_date.isoformat() if restart_date else None,
                second_halt=len(halts) >= 2, entries_by_year=entries_by_year,
                curve=[[d.isoformat(), round(e, 4)] for d, e in curve])

def placebo(cad_set, target_by_year, seed):
    rng = np.random.default_rng(seed)
    idx_of = {d: i for i, d in enumerate(TDATES)}
    days_by_year = {}
    for d in TDATES[:-1]: days_by_year.setdefault(d.year, []).append(d)
    sched = {}
    def add(year, n):
        days = days_by_year.get(year, [])
        for _ in range(n):
            d = days[rng.integers(0, len(days))]; i = idx_of[d]
            while len(sched.get(d, [])) >= MAXPOS and i < len(TDATES) - 1:
                i += 1; d = TDATES[i]
            sched.setdefault(d, []).append(UNIVERSE[rng.integers(0, len(UNIVERSE))])
    for y, t in sorted(target_by_year.items()): add(y, t)
    r = None
    for _ in range(12):
        r = run(cad_set, placebo_sched=sched)
        missing = {y: target_by_year.get(y, 0) - r["entries_by_year"].get(y, 0) for y in target_by_year}
        if all(v <= 0 for v in missing.values()): break
        for y, m in missing.items():
            if m > 0: add(y, m)
    return r["final"]

def spy_price_only():
    i0, i1 = POS[TDATES[0]], POS[TDATES[-1]]
    o, c = F["SPY"]["o"][i0], F["SPY"]["c"][i1]
    gross = 100.0 / o * c
    net = (100.0 / (1 + COST)) / o * c * (1 - COST) - SELL_FEE * 0  # sell fee on final value basis below
    net = (100.0 / (1 + COST)) / o * c
    net = net - (COST * net + SELL_FEE)
    return round(gross, 2), round(net, 2)

def main():
    import sys
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    sg, sn = spy_price_only()
    cells, money = {}, []
    todo = [c for c in CADENCES if not sys.argv[1:] or c in sys.argv[1:]]
    for cad in todo:
        cs = cadence_mask(cad)
        r = run(cs)
        twins = [placebo(cs, r["entries_by_year"], 90210 + i) for i in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        cell = {k: r[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "halts", "restart", "second_halt")}
        cell.update(placebo_beaten=f"{beaten}/20", placebo_twin_finals=twins,
                    placebo_note="Family design (v4): random (day,symbol) entries matched to the real run's filled entries per calendar year, iterative top-up (max 12 rounds), same exits/costs/v9 protection, same cadence. Seeds 90210-90229.")
        cj = dict(cell); cj["equity_curve"] = r["curve"]; cj["cadence"] = cad; cj["entries_by_year"] = r["entries_by_year"]
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as fh: json.dump(cj, fh, indent=1)
        cells[cad] = cell
        if r["final"] > 367.80 and beaten >= 11: money.append(cad)
        print(f"{cad:11s} final ${r['final']:8.2f} cagr {r['cagr_pct']:6.2f}% dd {r['max_dd_pct']:5.1f}% "
              f"costs ${r['costs']:6.2f} orders {r['orders']:4d} halts {len(r['halts'])} placebo {beaten}/20", flush=True)
    # merge any cells already on disk (partial re-runs) so results.json is whole
    for cad in CADENCES:
        if cad not in cells:
            p = os.path.join(HERE, "cells", f"{cad}.json")
            if os.path.exists(p):
                cj = json.load(open(p))
                cells[cad] = {k: cj[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                                "halts", "restart", "second_halt", "placebo_beaten", "placebo_twin_finals", "placebo_note")}
                if cj["final"] > 367.80 and int(cj["placebo_beaten"].split("/")[0]) >= 11: money.append(cad)
    results = {
        "slug": "breakout-basket",
        "area": "Basket + monthly/weekly breakout holding (W2) — judged on the DECADE road at every cadence",
        "area_source": "SPEC W2 assignment + CADENCE GRID: breakout basket = daily signals, monthly-era holding",
        "cadence": "daily-signal", "native_cadence": "daily-signal",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original v4 test evaluated breakout signals daily (its native form); the sweep's daily cell is that form under v9 protection. Slower cells act on breakouts only at cadence dates.",
        "integrity": {"status": "reproduced",
                      "original_finals": {"continuous_2016-11-21_to_2026-11-20": 309.85, "validation_2023-01-01_to_2026-11-20": 156.71},
                      "reproduced_finals": {"continuous": 309.8541, "validation": 156.7128},
                      "note": "Reproduced through the untouched v4 engine + v2 tournament Portfolio (integrity.py / integrity.json). Orders also match (589 / 233), no halts in either."},
        "decade_spy_final": 367.80,
        "decade_spy_note": f"Dividend-adjusted SPY per SPEC (verified reference). This family's own data is split-adjusted only: price-only SPY on the same road = gross ${sg}, net ${sn} — the strategy's cells are likewise price-only, so the $367.80 bar is the harder, honest one.",
        "champion_decade_caveat": "Champion (value+momentum) DECADE $65.89 after two halts — its crown rests on the 2010 and 2019 roads (SPEC).",
        "cells": cells, "money_cadences": money,
        "cadence_treatment": "Breakout signals computed from daily closes but evaluated/acted on ONLY on cadence dates (a breakout on a non-cadence day is never acted on); MA-20 exits also evaluated only on cadence dates; entries/exits fill at the next trading day's open; the -8% intraday stop (risk exit) and the v9 floor are checked every trading day, as in the original engine.",
        "verdict_area": "SEE RESULTS.md",
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh: json.dump(results, fh, indent=2)
    print("SPY price-only gross/net:", sg, sn, "| money cadences:", money)

if __name__ == "__main__":
    main()
