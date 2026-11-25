#!/usr/bin/env python3
"""Dividend Seasonality (Hartzmark & Solomon DivSeason) — frozen form.
Universe: program pond-30 names that paid a dividend in the last 12 months
(program-stack adaptation of the CRSP payer universe — NAMED approximation,
bias: survivor mega-cap payers only, flatters stability, printed).
Signal (frozen convention): a name is an EXPECTED payer in calendar month
m of year y if it paid a dividend with ex-date in month m of year y-1
(OSAP expected-month assignment from own payment history, PIT: only
payments dated <= formation are used to build later years' patterns by
construction of the y-1 rule). Formation: first trading day of the month;
hold the expected-payer basket equal-weight for the month (long-only
program adaptation; the published form is long-short). Native = ALL
expected payers. Grid ranking (CONSTRUCTED for the count grid): trailing
12-month dividend yield (sum of payments / price at formation).
Costs: program 0.10%/side + $0.01/sell order, charged on turnover.
House pair: v9 floor at portfolio level (restart after first halt).
Placebos (frozen primary): same names, each name's expected-month pattern
shifted by a random 1-11 months, 20 seeds. Coins NOT-APPLICABLE."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]

def build_data():
    data = {}
    for t in POND:
        bars, divs = load_bars(t)
        data[t] = {"bars": bars, "divs": divs,
                   "close": {b["d"]: b["c"] for b in bars},
                   "pay_months": {}, "pay_amt": {}}
        for dv in divs:
            y, m = int(dv["d"][:4]), int(dv["d"][5:7])
            data[t]["pay_months"].setdefault(y, set()).add(m)
            data[t]["pay_amt"][dv["d"]] = dv["amt"]
    return data

def expected(data, t, y, m, shift=0):
    pm = data[t]["pay_months"].get(y - 1, set())
    mm = ((m - 1 + shift) % 12) + 1
    return mm in pm

def paid_last_12m(data, t, asof):
    return any(asof[:4] != dv["d"][:4] or True for dv in data[t]["divs"] if dv["d"] <= asof and dv["d"] > (date.fromisoformat(asof) - timedelta(days=365)).isoformat())

def trail_yield(data, t, asof, price):
    lo = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    tot = sum(dv["amt"] for dv in data[t]["divs"] if lo < dv["d"] <= asof)
    return tot / price if price else 0.0

def run_basket(data, start, end, count="ALL", floor=False, shifts=None):
    # month formations
    dates, _ft = form_table(data, start, end)
    formations = {}
    for d in dates:
        ym = d[:7]
        if ym not in formations: formations[ym] = d
    cash = 100.0; pos = {}; curve = []; ep = 100.0; halts = 0; halt_until = None; dead = False; ntr = 0
    last_close = {}
    form_days = set(formations.values())
    for d in dates:
        eq = cash + sum(p["shares"] * data[t]["close"].get(d, last_close.get(t, 0)) for t, p in pos.items())
        for t in pos: last_close[t] = data[t]["close"].get(d, last_close.get(t, 0))
        if halt_until and d >= halt_until: halt_until = None; ep = eq
        if d in form_days and not dead and halt_until is None:
            y, m = int(d[:4]), int(d[5:7])
            _, _, payers = _ft[d]
            cands = []
            for t, yld in payers:
                sh = (shifts or {}).get(t, 0)
                if expected(data, t, y, m, sh): cands.append((t, yld))
            cands.sort(key=lambda x: -x[1])
            keep = cands if count == "ALL" else cands[:count]
            keep_t = {t for t, _ in keep}
            # sell leavers
            for t in list(pos):
                if t not in keep_t:
                    cash += pos[t]["shares"] * data[t]["close"].get(d, last_close.get(t, 0)) * (1 - STOCK_COST) - SELL_FEE
                    del pos[t]; ntr += 1
            eq = cash + sum(p["shares"] * data[t]["close"].get(d, last_close.get(t, 0)) for t, p in pos.items())
            # rebalance to equal weight
            if keep_t:
                target = eq / len(keep_t)
                newpos = {}
                for t in keep_t:
                    px = data[t]["close"][d]
                    cur_val = pos.get(t, {"shares": 0})["shares"] * px
                    if cur_val < target: cash -= (target - cur_val) * (1 + STOCK_COST) if t not in pos else (target - cur_val)
                    elif cur_val > target: cash += (cur_val - target) * (1 - STOCK_COST) - (SELL_FEE if t in pos else 0)
                    newpos[t] = {"shares": target / px}
                    if t not in pos: ntr += 1
                pos = newpos
                cash = eq - sum(p["shares"] * data[t]["close"][d] for t, p in pos.items()) if False else cash
            eq = cash + sum(p["shares"] * data[t]["close"].get(d, last_close.get(t, 0)) for t, p in pos.items())
        if floor and pos and eq < 0.85 * ep:
            for t in list(pos):
                cash += pos[t]["shares"] * data[t]["close"].get(d, last_close.get(t, 0)) * (1 - STOCK_COST) - SELL_FEE
                del pos[t]; ntr += 1
            eq = cash; halts += 1
            if halts == 1: halt_until = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
            else: dead = True
        curve.append((d, round(eq, 4)))
    if pos:
        eq = cash + sum(p["shares"] * data[t]["close"].get(curve[-1][0], last_close.get(t, 0)) for t, p in pos.items())
        eq -= (eq - cash) * STOCK_COST + SELL_FEE * len(pos)
        curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(curve[-1][1], 2), "curve": curve, "trades": ntr}

FORM_TABLE = {}
def form_table(data, start, end):
    key = (start, end)
    if key in FORM_TABLE: return FORM_TABLE[key]
    dates = sorted({b["d"] for t in data for b in data[t]["bars"] if start <= b["d"] <= end})
    formations = {}
    for d in dates:
        if d[:7] not in formations: formations[d[:7]] = d
    table = {}
    for ym, d in formations.items():
        y, m = int(d[:4]), int(d[5:7])
        payers = []
        for t in data:
            if paid_last_12m(data, t, d):
                px = data[t]["close"].get(d)
                if px: payers.append((t, trail_yield(data, t, d, px)))
        table[d] = (y, m, payers)
    FORM_TABLE[key] = (dates, table)
    return FORM_TABLE[key]

def main():
    data = build_data()
    res = {"family": "hunt-dividend-seasonality"}
    spy, _ = load_bars("SPY")
    out = {}
    for road, (s, e) in ROADS.items():
        nat = run_basket(data, s, e, "ALL", floor=False)
        hou = run_basket(data, s, e, "ALL", floor=True)
        bh = buyhold(spy, s, e)
        out[road] = {"native_final": nat["final"], "house_final": hou["final"], "buyhold_spy": bh["final"],
                     "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                     "periods_monthly_native": period_stats(nat["curve"], "monthly"), "curve_native": nat["curve"]}
    res["native_all"] = out
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    grid = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]; grid[road] = {}
        for cnt in COUNTS:
            nat = run_basket(data, s, e, cnt, floor=False)
            hou = run_basket(data, s, e, cnt, floor=True)
            grid[road][str(cnt)] = {"native": nat["final"], "house": hou["final"]}
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    res["grid"] = grid
    finals = []
    s, e = ROADS["DECADE"]
    for seed in range(1, 21):
        rng = random.Random(seed * 23)
        shifts = {t: rng.randrange(1, 12) for t in POND}
        finals.append(run_basket(data, s, e, "ALL", floor=False, shifts=shifts)["final"])
    res["placebos_DECADE_shifted_months"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if out["DECADE"]["native_final"] > f), "finals": finals}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("native ALL:", {r: out[r]["native_final"] for r in ROADS})
    print("grid DECADE:", grid["DECADE"]); print("placebo:", res["placebos_DECADE_shifted_months"]["median"], res["placebos_DECADE_shifted_months"]["n_beaten_by_native"])

if __name__ == "__main__": main()
