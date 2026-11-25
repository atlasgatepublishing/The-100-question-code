#!/usr/bin/env python3
"""V12 VERIFICATION RE-RUN — breakout-basket frozen chassis spec.

The chassis is a program construction (see CONSTRUCTION-SPEC.md): up to 5
positions at 20% of equity each; entry on a close above the highest close
of the prior 252 sessions, filled at the next open, free slots to the
largest % gain on the signal day; exits on a close below the 20-day
average (next open) or a -8% intraday stop (gap-through at the open);
costs 0.10%/side + $0.01 per sell; v9 protection (plain -15% floor, no
ladder; halt -> liquidate next open, 90 days in cash, restart under an
episode-2 -15% floor; second halt ends the run). Daily cadence only —
the chassis's native tempo. Engine semantics copied from the v10 retest
engine (backtests/v10-retest/breakout-basket/run_retest.py), which itself
reproduced the v4 original exactly; the only change here is that the
window is a parameter so the standard roads can be run as fresh pots.

Roads: DECADE 2016-11-21 -> 2026-11-20, CONT 2019-01-02 -> 2026-11-20,
VAL 2023-01-01 -> 2026-11-20. LONG 2010 is not run: the frozen data
begins 2015-01-02 (named closure, CONSTRUCTION-SPEC.md section 3).
Placebos: family design — random (day, symbol) entries matched to the
real run's filled entries per calendar year, iterative top-up (max 12
rounds), same exits/costs/protection; 20 seeds 90210-90229 per road.
Data (read-only): backtests/v2/tournament-data/*.csv (split-adjusted,
NOT dividend-adjusted).
"""
import json, os
from datetime import date, timedelta
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v2", "tournament-data")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
COST, SELL_FEE, STOP, MAXPOS, FRAC = 0.001, 0.01, 0.08, 5, 0.20
ROADS = {"DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
         "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
         "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
SPY_DIV_ADJ = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

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

class Road:
    def __init__(self, start, end):
        self.tidx = [i for i, d in enumerate(DATES) if start <= d <= end]
        self.tdates = [DATES[i] for i in self.tidx]
        self.start, self.end = start, end

def run(road, placebo_sched=None):
    TDATES, TIDX = road.tdates, road.tidx
    cash, lots = 100.0, {}
    costs, orders = 0.0, 0
    curve, entries_by_year = [], {}
    pend_in, pend_out = [], []
    episode, floor = 1, 85.0
    halts, restart_date, state = [], None, "run"
    sit_until = None
    last = len(TDATES) - 1
    for k, d in enumerate(TDATES):
        p = TIDX[k]
        omap = {s: F[s]["o"][p] for s in UNIVERSE}
        cmap = {s: F[s]["c"][p] for s in UNIVERSE}
        def equity(mp):
            return cash + sum(sh * mp[s] for s, (sh, _) in lots.items())
        def sell(sym, px):
            nonlocal cash, costs, orders
            sh, _ = lots.pop(sym)
            val = sh * px; cst = COST * val + SELL_FEE
            cash += val - cst; costs += cst; orders += 1
        if state == "sit" and d >= sit_until:
            state, episode = "run", 2
            floor = 0.85 * cash; restart_date = d
        if state == "done":
            curve.append((d, cash)); continue
        halt_pending = False
        if state == "run":
            for sym in pend_out:
                if sym in lots: sell(sym, omap[sym])
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
        if state == "run":
            for sym in list(lots):
                sh, ep = lots[sym]
                o, lo = F[sym]["o"][p], F[sym]["l"][p]
                sp = ep * (1 - STOP)
                if o <= sp: sell(sym, o)
                elif lo <= sp: sell(sym, sp)
        eq = equity(cmap)
        curve.append((d, eq))
        if state == "run" and eq <= floor:
            halts.append({"episode": episode, "trigger_date": d.isoformat(),
                          "floor": round(floor, 2), "equity_at_trigger": round(eq, 2)})
            if k < last:
                p2 = TIDX[k + 1]
                for sym in list(lots): sell(sym, F[sym]["o"][p2])
                halts[-1]["liquidation_date"] = TDATES[k + 1].isoformat()
                halts[-1]["cash_after"] = round(cash, 2)
            else:
                halts[-1]["liquidation_date"] = d.isoformat(); halts[-1]["cash_after"] = round(eq, 2)
            if episode == 1:
                state = "sit"; sit_until = d + timedelta(days=90)
                pend_in, pend_out = [], []
                curve[-1] = (d, eq)
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
    yrs = (road.end - road.start).days / 365.25
    return dict(final=round(final, 2),
                cagr_pct=round(((final / 100) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
                max_dd_pct=round(mdd, 2), costs=round(costs, 2), orders=orders,
                halts=halts, restart=restart_date.isoformat() if restart_date else None,
                entries_by_year=entries_by_year,
                curve=[[d.isoformat(), round(e, 4)] for d, e in curve])

def placebo(road, target_by_year, seed):
    rng = np.random.default_rng(seed)
    TDATES = road.tdates
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
        r = run(road, placebo_sched=sched)
        missing = {y: target_by_year.get(y, 0) - r["entries_by_year"].get(y, 0) for y in target_by_year}
        if all(v <= 0 for v in missing.values()): break
        for y, m in missing.items():
            if m > 0: add(y, m)
    return r["final"]

def spy_price_only(road):
    i0, i1 = POS[road.tdates[0]], POS[road.tdates[-1]]
    o, c = F["SPY"]["o"][i0], F["SPY"]["c"][i1]
    gross = 100.0 / o * c
    net = (100.0 / (1 + COST)) / o * c
    net = net - (COST * net + SELL_FEE)
    return round(gross, 2), round(net, 2)

def main():
    out = {"family": "breakout-basket", "form": "frozen program chassis (CONSTRUCTED, program) — daily cadence, v9 protection",
           "signal_native_form": "George & Hwang (2004), owned/scored by breakout-validation — cross-reference only",
           "costs": "0.10% of notional per side + $0.01 per sell order",
           "placebo_seeds": "90210-90229 (20 per road)",
           "long_2010": "NOT RUN — named data closure: frozen chassis data begins 2015-01-02",
           "roads": {}}
    for name, (a, b) in ROADS.items():
        road = Road(a, b)
        r = run(road)
        twins = [placebo(road, r["entries_by_year"], 90210 + i) for i in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        sg, sn = spy_price_only(road)
        out["roads"][name] = {
            "window": [a.isoformat(), b.isoformat()],
            "final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"], "halts": r["halts"],
            "restart": r["restart"], "entries_by_year": r["entries_by_year"],
            "placebo_beaten": f"{beaten}/20", "placebo_twin_finals": twins,
            "spy_price_only_gross": sg, "spy_price_only_net": sn,
            "spy_dividend_adjusted_ref": SPY_DIV_ADJ[name],
            "champion_vm": CHAMPION[name],
            "curve": r["curve"]}
        print(f"{name:7s} final ${r['final']:8.2f} cagr {r['cagr_pct']:6.2f}% dd {r['max_dd_pct']:5.1f}% "
              f"costs ${r['costs']:6.2f} orders {r['orders']:4d} halts {len(r['halts'])} "
              f"placebo {beaten}/20 | SPY price-only net ${sn} div-adj ${SPY_DIV_ADJ[name]}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("saved results.json")

if __name__ == "__main__":
    main()
