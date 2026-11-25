#!/usr/bin/env python3
"""V13 BEST-RULES RUN — breakout-basket. Spec: BEST-RULES-SPEC.md (frozen).

Universe: PIT Nov-2016 top-30 pond (honest cache, open/close only).
Entry: daily close > prior 252-session highest close, next open; free
slots ranked by prior 126-session return; new entries only when SPY
close > SPY 200-day average (signal day). Up to 5 positions at 20% of
equity. Exit: close below own 100-day average -> next open. No stop,
no pot floor. Costs 0.10%/side + $0.01/sell. Placebos: random (day,
symbol) entries matched per calendar year, same machinery, seeds
90210-90229.
Data (read-only): backtests/v4/momentum-basket-honest-data/*.json
"""
import json, os
from datetime import date
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v4", "momentum-basket-honest-data")
UNIVERSE = ["AAPL", "AMZN", "BAC", "BRK-B", "CSCO", "CVX", "DIS", "GE", "GOOGL",
            "HD", "IBM", "INTC", "JNJ", "JPM", "KO", "MA", "META", "MMM", "MSFT",
            "NFLX", "PEP", "PFE", "PG", "T", "UNH", "V", "VZ", "WFC", "WMT", "XOM"]
COST, SELL_FEE, MAXPOS, FRAC = 0.001, 0.01, 5, 0.20
ROADS = {"DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
         "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
         "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
SPY_DIV_ADJ = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77, "LONG": 822.94}
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
PUBLISHED_BEST = {"DECADE": 309.85, "CONT": 285.74, "VAL": 156.71}  # v12 chassis

def load():
    raw = {}
    for s in UNIVERSE + ["SPY"]:
        rows = json.loads(open(os.path.join(DATA, f"{s}.json")).read())
        raw[s] = {r["d"]: (r["o"], r["c"]) for r in rows}
    dates = sorted(raw["SPY"])
    F = {}
    for s in UNIVERSE + ["SPY"]:
        o = np.array([raw[s][d][0] for d in dates], float)
        c = np.array([raw[s][d][1] for d in dates], float)
        cs = pd.Series(c)
        F[s] = dict(o=o, c=c,
                    sma100=cs.rolling(100).mean().values,
                    p252=cs.shift(1).rolling(252).max().values,
                    ret126=(cs / cs.shift(126) - 1).values)
    spy = pd.Series(F["SPY"]["c"])
    F["SPY"]["sma200"] = spy.rolling(200).mean().values
    dts = [date.fromisoformat(d) for d in dates]
    return dts, F

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
    last = len(TDATES) - 1
    for k, d in enumerate(TDATES):
        p = TIDX[k]
        omap = {s: F[s]["o"][p] for s in UNIVERSE}
        cmap = {s: F[s]["c"][p] for s in UNIVERSE}
        def equity(mp):
            return cash + sum(sh * mp[s] for s, sh in lots.items())
        def sell(sym, px):
            nonlocal cash, costs, orders
            sh = lots.pop(sym)
            val = sh * px; cst = COST * val + SELL_FEE
            cash += val - cst; costs += cst; orders += 1
        # exits scheduled from prior close fill first at this open
        for sym in pend_out:
            if sym in lots: sell(sym, omap[sym])
        pend_out = []
        # entries at this open
        if placebo_sched is not None:
            cands = [(s, 0.0) for s in placebo_sched.get(d, [])]
            gate_ok = p >= 1 and not np.isnan(F["SPY"]["sma200"][p - 1]) and \
                F["SPY"]["c"][p - 1] > F["SPY"]["sma200"][p - 1]
            if not gate_ok: cands = []
        else:
            cands = pend_in
        pend_in = []
        for sym, _r in cands:
            if sym in lots or len(lots) >= MAXPOS: continue
            tgt = FRAC * equity(omap)
            val = min(tgt, cash / (1 + COST))
            if val < 1.0: continue
            cst = COST * val; cash -= val + cst; costs += cst; orders += 1
            lots[sym] = val / omap[sym]
            entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        eq = equity(cmap)
        curve.append((d, eq))
        if k < last:
            # exits: close below own 100d average
            for sym in list(lots):
                s100 = F[sym]["sma100"][p]
                if not np.isnan(s100) and cmap[sym] < s100: pend_out.append(sym)
            # entries: breakout + regime gate, ranked by 126d return
            if placebo_sched is None:
                gate = not np.isnan(F["SPY"]["sma200"][p]) and F["SPY"]["c"][p] > F["SPY"]["sma200"][p]
                if gate and p >= 253:
                    sigs = []
                    for sym in UNIVERSE:
                        if sym in lots: continue
                        ph = F[sym]["p252"][p]
                        if not np.isnan(ph) and cmap[sym] > ph:
                            r = F[sym]["ret126"][p]
                            sigs.append((sym, r if not np.isnan(r) else -9.0))
                    sigs.sort(key=lambda x: -x[1]); pend_in = sigs
    final = curve[-1][1]
    peak, mdd = 100.0, 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak * 100 if peak > 0 else 0.0)
    yrs = (road.end - road.start).days / 365.25
    return dict(final=round(final, 2),
                cagr_pct=round(((final / 100) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
                max_dd_pct=round(mdd, 2), costs=round(costs, 2), orders=orders,
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
    net = (100.0 / (1 + COST)) / o * c
    net = net - (COST * net + SELL_FEE)
    return round(net, 2)

def period_stats(curve):
    """Monthly distribution + calendar-year finals + streaks (on DECADE)."""
    s = pd.Series({pd.Timestamp(d): e for d, e in curve})
    monthly = s.resample("M").last()
    rets = monthly.pct_change().dropna() * 100
    # longest losing streak (consecutive negative months)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days on daily curve)
    peak, since, longest = -1.0, 0, 0
    for _, e in curve:
        if e >= peak: peak, since = e, 0
        else: since += 1; longest = max(longest, since)
    yearly = {}
    for d, e in curve: yearly[d[:4]] = e
    return dict(monthly_median_pct=round(float(rets.median()), 2),
                monthly_mean_pct=round(float(rets.mean()), 2),
                share_months_positive_pct=round(float((rets > 0).mean() * 100), 1),
                best_month_pct=round(float(rets.max()), 2),
                worst_month_pct=round(float(rets.min()), 2),
                longest_losing_streak_months=int(streak),
                longest_days_between_new_highs=int(longest),
                n_months=int(len(rets)),
                year_end_equity={y: round(v, 2) for y, v in sorted(yearly.items())})

def main():
    out = {"family": "breakout-basket", "program": "v13-best-rules",
           "form": "MY RULES: PIT-30 pond, strict 252d breakout, daily, rank by 126d return, SPY>200d gate for entries, 5x20%, exit close<100d SMA, no stop/floor",
           "costs": "0.10% of notional per side + $0.01 per sell order",
           "placebo_seeds": "90210-90229 (20 per road)",
           "long_2010": "NOT RUN — named data closure: honest pond cache begins 2015-01-02",
           "roads": {}}
    for name, (a, b) in ROADS.items():
        road = Road(a, b)
        r = run(road)
        twins = [placebo(road, r["entries_by_year"], 90210 + i) for i in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        out["roads"][name] = {
            "window": [a.isoformat(), b.isoformat()],
            "final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"],
            "entries_by_year": r["entries_by_year"],
            "placebo_beaten": f"{beaten}/20", "placebo_twin_finals": twins,
            "spy_price_only_net": spy_price_only(road),
            "spy_dividend_adjusted_ref": SPY_DIV_ADJ[name],
            "champion_vm": CHAMPION[name],
            "published_best_v12_chassis": PUBLISHED_BEST[name],
            "period_stats": period_stats(r["curve"]),
            "curve": r["curve"]}
        print(f"{name:7s} final ${r['final']:8.2f} cagr {r['cagr_pct']:6.2f}% dd {r['max_dd_pct']:5.1f}% "
              f"costs ${r['costs']:6.2f} orders {r['orders']:4d} placebo {beaten}/20 | "
              f"SPY div-adj ${SPY_DIV_ADJ[name]} champ ${CHAMPION[name]} pub-best ${PUBLISHED_BEST[name]}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("saved results.json")

if __name__ == "__main__":
    main()
