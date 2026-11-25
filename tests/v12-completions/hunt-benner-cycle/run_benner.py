#!/usr/bin/env python3
"""Benner Cycle calendar — SPEC-FROZEN exact. Published tabulation (standard
reproduction, cross-checked across 3 sources):
Panics: 1927,1945,1965,1981,1999,2019,2035 (no action, frozen).
Good Times (sell): 1926,1935,1945,1953,1962,1972,1980,1989,1999,2007,2016,2026.
Hard Times (buy): 1924,1931,1942,1951,1958,1969,1978,1985,1996,2005,2012,2023.
Rule: enter at first open of a Hard Times year if flat; exit at last close of a
Good Times year if long; gap years hold. SPY program costs; BTC port close-exec 0.60%/side.
House form: v9 -15% plain floor. Placebos: circular shift of the state series (20 seeds).
NOTE: as run, common.py and the CoinMetrics cache lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script."""
import json, os, random, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-benner-cycle")
HARD = {1924,1931,1942,1951,1958,1969,1978,1985,1996,2005,2012,2023}
GOOD = {1926,1935,1945,1953,1962,1972,1980,1989,1999,2007,2016,2026}
PANIC = {1927,1945,1965,1981,1999,2019,2035}

def benner_trades(bars):
    trades = []; pos = None
    years = {}
    for i, b in enumerate(bars): years.setdefault(int(b["d"][:4]), []).append(i)
    for y in sorted(years):
        idxs = years[y]
        if y in HARD and pos is None: pos = idxs[0]
        if y in GOOD and pos is not None:
            trades.append((pos, idxs[-1])); pos = None
    if pos is not None: trades.append((pos, None))
    return trades

def run_stock(bars, house=False):
    cash, shares = START, 0.0; curve = []; costs = 0.0; ntr = 0; halted = False
    tr = benner_trades(bars)
    entries = {t[0]: t for t in tr}; exits = {t[1]: t for t in tr if t[1] is not None}
    for i, b in enumerate(bars):
        if i in entries and shares == 0 and not halted:
            costs += cash * STK_COST; shares = cash * (1 - STK_COST) / b["o"]; cash = 0.0; ntr += 1
        eq = cash + shares * b["c"]
        if i in exits and shares > 0:
            costs += shares * b["c"] * STK_COST + STK_FEE; cash = shares * b["c"] * (1 - STK_COST) - STK_FEE
            shares = 0.0; ntr += 1; eq = cash
        curve.append({"d": b["d"], "eq": round(eq, 4)})
        if house and not halted and eq <= 85.0:
            halted = True
            if shares > 0:
                costs += shares * b["c"] * STK_COST + STK_FEE; cash = shares * b["c"] * (1 - STK_COST) - STK_FEE; shares = 0.0; ntr += 1
            for rb in bars[i+1:]: curve.append({"d": rb["d"], "eq": round(cash, 4)})
            break
    return {"final": curve[-1]["eq"], "curve": curve, "trades": ntr, "costs": round(costs, 2),
            "maxdd": maxdd(curve), "halted": halted,
            "trade_list": [(bars[a]["d"], bars[z]["d"] if z is not None else "open") for a, z in tr]}

def run_btc(bars, house=False):
    eq = START; pos = 0; curve = []; ntr = 0; costs = 0.0; halted = False
    tr = benner_trades(bars)
    entries = {t[0] for t in tr}; exits = {t[1] for t in tr if t[1] is not None}
    prev = None
    for i, b in enumerate(bars):
        if prev is not None and pos == 1 and not halted: eq *= b["c"] / prev
        if not halted:
            if i in entries and pos == 0: costs += eq * CRY_COST; eq *= (1 - CRY_COST); pos = 1; ntr += 1
            if i in exits and pos == 1: costs += eq * CRY_COST; eq *= (1 - CRY_COST); pos = 0; ntr += 1
        curve.append({"d": b["d"], "eq": round(eq, 4)})
        if house and not halted and eq <= 85.0: halted = True; pos = 0
        prev = b["c"]
    return {"final": curve[-1]["eq"], "curve": curve, "trades": ntr, "costs": round(costs, 2),
            "maxdd": maxdd(curve), "halted": halted}

def benner_states(bars):
    st = [0]*len(bars); tr = benner_trades(bars)
    for a, z in tr:
        for i in range(a, (z if z is not None else len(bars)-1) + 1): st[i] = 1
    return st

def placebo_stock(bars, seed):
    st = placebo_shift(benner_states(bars), seed)
    return sim_open_exec(bars, st)["final"]

out = {"family": "hunt-benner-cycle", "tables": {"hard": sorted(HARD), "good": sorted(GOOD), "panic_no_action": sorted(PANIC)},
       "holdings_grid": "NOT-APPLICABLE — market calendar, no selection", "stocks": {}, "btc": {}}
spy = load_pxfull("SPY")
for road, (s, e) in ROADS.items():
    bars = slice_bars(spy, s, e)
    nat = run_stock(bars); hou = run_stock(bars, house=True)
    pls = [placebo_stock(bars, sd) for sd in range(1, 21)]
    out["stocks"][road] = {"native": nat, "house": hou, "spy_buyhold": round(buyhold_open(bars), 2),
                           "champion_vm": CHAMP[road], "placebos_beaten": sum(1 for p in pls if nat["final"] > p),
                           "placebo_finals": pls, "periods_monthly": period_stats(nat["curve"], "monthly")}
btc = load_cm("btc")
for wname, (s, e) in {"FULL": ("2010-07-18", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}.items():
    bars = slice_bars(btc, s, e)
    nat = run_btc(bars); hou = run_btc(bars, house=True)
    out["btc"][wname] = {"native": nat, "house": hou, "btc_buyhold": round(buyhold_close(bars), 2),
                         "periods_monthly": period_stats(nat["curve"], "monthly")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("SPY:", {r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"]) for r, v in out["stocks"].items()})
print("BTC:", {r: (v["native"]["final"], v["btc_buyhold"]) for r, v in out["btc"].items()})
