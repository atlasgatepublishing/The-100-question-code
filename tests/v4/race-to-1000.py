#!/usr/bin/env python3
"""
RACE TO $1,000 — speed scoreboard for Terry's AI stock app. Simulation only.

Reuses the two honest engines verbatim (imports them; no strategy changes):
  1. momentum-basket-honest.py  — honest 30-name (Nov-2016) momentum basket,
     full continuous 2016-11-21 -> 2026-11-20, Terry's floor+ladder as run.
  2. value-momentum-plainfloor.py — honest value+momentum, PLAIN -15% floor
     (no ladder), continuous 2019-01-02 -> 2026-11-20.
  3. SPY buy-and-hold net baseline over both windows.

For each run: first close reaching $100 / $250 / $500 / $1,000, the speed
table (years to 2x / 5x / 10x / 20x of the starting pot), total return,
CAGR, max drawdown, and the naive CAGR-extrapolation years-to-$1,000.
Outputs race-to-1000-results.json.
"""
import importlib.util
import json
import math
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def load_mod(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def first_reach(curve, threshold):
    """First (date, equity) with close >= threshold, else None."""
    for d, eq in curve:
        if eq >= threshold:
            return d, eq
    return None


def analyze(name, curve, start_pot, start_d, end_d, final_net):
    yrs = years_between(start_d, end_d)
    total_ret = final_net / start_pot - 1.0
    cagr = (final_net / start_pot) ** (1.0 / yrs) - 1.0
    peak, peak_d, max_dd = -1.0, None, 0.0
    for d, eq in curve:
        if eq > peak:
            peak, peak_d = eq, d
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)
    milestones = {}
    for m in (100, 250, 500, 1000):
        hit = first_reach(curve, float(m))
        milestones[str(m)] = (
            {"date": hit[0], "close": round(hit[1], 2),
             "years_elapsed": round(years_between(start_d, hit[0]), 2)}
            if hit else None)
    speed = {}
    for mult in (2, 5, 10, 20):
        hit = first_reach(curve, mult * start_pot)
        speed[f"{mult}x"] = (
            {"date": hit[0], "years": round(years_between(start_d, hit[0]), 2)}
            if hit else None)
    # naive extrapolation: years from start for CAGR to carry start_pot -> $1,000
    if cagr > 0:
        yrs_to_1000 = math.log(1000.0 / start_pot) / math.log(1.0 + cagr)
    else:
        yrs_to_1000 = None
    return {
        "candidate": name, "start": start_pot, "window": [start_d, end_d],
        "window_years": round(yrs, 2), "final": round(final_net, 2),
        "total_return_pct": round(total_ret * 100, 1),
        "cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(max_dd * 100, 1),
        "peak_close": round(peak, 2), "peak_date": peak_d,
        "milestones": milestones, "speed": speed,
        "implied_years_to_1000_at_cagr": (round(yrs_to_1000, 1)
                                          if yrs_to_1000 else None),
    }


def spy_curve_from_closes(dates, closes, opens, i0, i1, pot):
    """Buy at open of day i0 net of 0.10% buy cost; daily close equity =
    shares x close (mark-to-market, before the final sell cost)."""
    sh = (pot * (1 - 0.001)) / opens[i0]
    return [(dates[i], sh * closes[i]) for i in range(i0, i1 + 1)]


def main():
    out = {}

    # ---- 1. Honest momentum basket (full window) -------------------------
    mb = load_mod("mbh", "momentum-basket-honest.py")
    mkt = mb.Market(mb.UNIVERSE)
    sd, ed = mb.WINDOWS["full"]
    for pot in (50, 100):
        r = mb.simulate(mkt, sd, ed, pot, "ranked")
        a = analyze(f"Momentum basket (honest 2016 list)", r.equity_curve,
                    pot, r.equity_curve[0][0], ed, r.final)
        out[f"momentum|{pot}"] = a
        print(f"momentum ${pot}: final={r.final:.2f} peak={a['peak_close']} "
              f"on {a['peak_date']} milestones={a['milestones']}", flush=True)
    # SPY over the momentum window
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    spy_opens = [mkt.open_px("SPY", i) or mkt.close_px("SPY", i)
                 for i in range(len(mkt.cal))]
    for pot in (50, 100):
        curve = spy_curve_from_closes(mkt.cal, mkt.closes["SPY"], spy_opens,
                                      i0, i1, pot)
        fin = mb.spy_net(mkt, sd, ed, pot)
        a = analyze("SPY buy-and-hold net (2016 window)", curve, pot,
                    mkt.cal[i0], ed, fin)
        out[f"spy2016|{pot}"] = a
        print(f"spy2016 ${pot}: final={fin:.2f} peak={a['peak_close']} "
              f"milestones={a['milestones']}", flush=True)

    # ---- 2. Honest value+momentum, plain floor (full window) -------------
    vm = load_mod("vmpf", "value-momentum-plainfloor.py")
    ciks = vm.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in vm.UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        equity_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                          prio=1))
        shares_rows[t] = (
            vm.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {t: vm.get_prices(t) for t in vm.UNIVERSE + ["SPY"]}
    pb = vm.PriceBook(bars)
    vsd, ved = "2019-01-02", "2026-11-20"
    for pot, floor0 in ((50, 42.50), (100, 85.0)):
        r = vm.run_pot(pb, equity_rows, shares_rows, vsd, ved, float(pot),
                       floor0, [], label=f"race VM ${pot}", quiet=True)
        a = analyze("Value+momentum (honest, plain floor)", r["curve"],
                    pot, r["curve"][0][0], ved, r["final"])
        out[f"valuemom|{pot}"] = a
        print(f"valuemom ${pot}: final={r['final']:.2f} peak={a['peak_close']} "
              f"on {a['peak_date']} milestones={a['milestones']}", flush=True)
    # SPY over the value+momentum window
    spy_bars = bars["SPY"]
    sdates = [b["d"] for b in spy_bars if vsd <= b["d"] <= ved]
    sidx = {b["d"]: b for b in spy_bars}
    for pot in (50, 100):
        fin, _ = vm.spy_net(pb, vsd, ved, float(pot))
        sh = (pot / 1.001) / sidx[sdates[0]]["o"]
        curve = [(d, sh * sidx[d]["c"]) for d in sdates]
        a = analyze("SPY buy-and-hold net (2019 window)", curve, pot,
                    sdates[0], ved, fin)
        out[f"spy2019|{pot}"] = a
        print(f"spy2019 ${pot}: final={fin:.2f} peak={a['peak_close']} "
              f"milestones={a['milestones']}", flush=True)

    with open(os.path.join(HERE, "race-to-1000-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved race-to-1000-results.json")


if __name__ == "__main__":
    main()
