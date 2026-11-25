#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — short-interest, long leg (Form A-broad).

Writes into THIS worker's folder (holdings-breakout-ranked) per the
assignment; the family's own v12 folder stays read-only.

FROZEN COUNT MAPPING (before any run): the v12 CONSTRUCTED-broad form
IS ranked — each month it holds the N least-shorted scored names
(FINRA short interest / EDGAR shares outstanding), equal weight,
monthly rebalance, on the S&P 500 PIT universe (268-357 names scored
per month). Native (constructed) count = 30. The sweep varies exactly
N over the fixed grid 1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE, where
ALL-ELIGIBLE = the whole scored pool that month (count varies by
month). Everything else is byte-identical to run_broad.py in
~/workspace/stock-app/backtests/v12-completions/short-interest/
(pools, prices cached in that folder's data/, costs, publication lag).
Forms: HOUSE = the v12 run's own house form (plain -15% floor at
monthly marks, breach liquidates and ends the run, no restart);
NATIVE = the published form's discipline: no floor at all.
Roads: the only honest FINRA roads — FULL (money Jan 2019->Oct 2026)
and VAL (Jan 2023->Oct 2026); LONG/DECADE do not exist (FINRA cache
starts Dec 2018). Confirmation windows (different years): CONF_A
formations Dec 2019->Nov 2022 (money 2020-2022), CONF_B formations
Dec 2023->Nov 2025 (money 2024-2025) — run only in 'confirm' mode.
Placebos: 20 seeds per cell, random N drawn monthly from the same
scored pool, same engine/costs/form (the v12 design). For
ALL-ELIGIBLE the random draw IS the whole pool, so placebos are
degenerate and reported as n/a.
Reproduction gate: house form, count 30 must equal the v12 finals
FULL $234.11 / VAL $155.34 before any sweep number is trusted.
Simulation only.
"""
import csv, json, os, random, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SI_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/short-interest")
DATA = os.path.join(SI_DIR, "data")
PIT = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a9-frog-pan/data/sp500_pit.csv")
FINRA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v6/short-interest/finra-cache")
FRAMES = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/frames")
TICKERS_JSON = os.path.expanduser("~/workspace/stock-app/backtests/v4/data/company_tickers.json")

START_CASH = 100.0; FLOOR = 85.0
COST_RATE = 0.001; SELL_FEE = 0.01
GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
NATIVE_COUNT = 30

def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]); m += n
    while m > 12: m -= 12; y += 1
    while m < 1: m += 12; y -= 1
    return f"{y:04d}-{m:02d}"

FORMATIONS = []
ym = "2018-12"
while ym <= "2026-09":
    FORMATIONS.append(ym); ym = ym_add(ym, 1)
FINAL_MONTH = "2026-10"

pit_rows = []
with open(PIT) as f:
    for r in csv.DictReader(f):
        pit_rows.append((r["date"], r["tickers"].split(",")))
pit_rows.sort()
def membership(ym):
    target = ym + "-31"; best = None
    for d, tk in pit_rows:
        if d <= target: best = tk
        else: break
    return list(best) if best else []

ALL_TICKERS = sorted({t for fm in FORMATIONS for t in membership(fm)})

PX = {}
for t in ALL_TICKERS + ["SPY"]:
    p = os.path.join(DATA, f"px_{t.replace('/','-')}.json")
    PX[t] = json.load(open(p)) if os.path.exists(p) else {}
print(f"price series loaded: {sum(1 for t in ALL_TICKERS if PX.get(t))}/{len(ALL_TICKERS)}", flush=True)

ct = json.load(open(TICKERS_JSON))
T2CIK = {v["ticker"]: v["cik_str"] for v in ct.values()}
T2CIK["FB"] = 1326801
shares_cache = {}
def shares_frame(year):
    if year not in shares_cache:
        p = os.path.join(FRAMES, f"Shares_{year}I.json")
        shares_cache[year] = {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
    return shares_cache[year]

finra_files = {}
for fn in os.listdir(FINRA_DIR):
    if fn.startswith("shrt") and fn.endswith(".csv"):
        d = fn[4:12]; key = f"{d[:4]}-{d[4:6]}"
        if int(d[6:8]) <= 16:
            finra_files[key] = (f"{d[:4]}-{d[4:6]}-{d[6:8]}", os.path.join(FINRA_DIR, fn))
def finra_symbol(t, settlement):
    if t == "META" and settlement < "2022-06-10": return "FB"
    return t.replace(".", "")
def finra_rows(ym):
    settlement, path = finra_files[ym]
    wanted = {}
    for t in ALL_TICKERS:
        wanted.setdefault(finra_symbol(t, settlement), []).append(t)
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="|"):
            sym = row["symbolCode"]
            if sym in wanted:
                for t in wanted[sym]:
                    out[t] = float(row["currentShortPositionQuantity"])
    return settlement, out

def scored_pool(ym):
    settlement, rows = finra_rows(ym)
    sh = shares_frame(int(settlement[:4]) - 1)
    pool = {}
    for t in membership(ym):
        if t not in rows: continue
        cik = T2CIK.get(t); so = sh.get(cik) if cik else None
        if not so or so <= 0: continue
        if ym not in PX.get(t, {}): continue
        pool[t] = rows[t] / so
    return pool, settlement

POOLS = {}
for fm in FORMATIONS:
    POOLS[fm] = scored_pool(fm)
print(f"pools built: {len(POOLS)} formations, scored {min(len(v[0]) for v in POOLS.values())}-{max(len(v[0]) for v in POOLS.values())}", flush=True)

def run_pot(formations, n_picks, use_floor, seed=None, final_month=None):
    fm_last = final_month or FINAL_MONTH
    cash = START_CASH; positions = {}; curve = []; total_costs = 0.0; orders = 0
    halted = None
    months = list(formations) + [fm_last]
    for i, fm in enumerate(formations):
        pool, settlement = POOLS[fm]
        n = len(pool) if n_picks == "ALL" else min(n_picks, len(pool))
        if seed is None:
            picks = sorted(pool, key=lambda t: (pool[t], t))[:n]
        else:
            rng = random.Random(seed * 10000 + i)
            picks = rng.sample(sorted(pool), n)
        for t, sh in list(positions.items()):
            p = PX.get(t, {}).get(fm)
            val = 0.0 if p is None else sh * p
            c = val * COST_RATE + SELL_FEE if val > 0 else 0.0
            cash += val - c; total_costs += c; orders += 1
        positions = {}
        if cash <= 0:
            # Ruin guard (added after the first ALL-ELIGIBLE pass traded
            # a negative pot into implicit shorts — an artifact, removed):
            # per-order fees can exceed a $100 pot at ~330 names/month;
            # a real pot is then worth $0.00 and the run is over.
            curve.append([fm, 0.0])
            return {"final": 0.0, "costs": round(total_costs, 2), "orders": orders,
                    "max_dd_pct": 100.0, "halted": halted, "ruined": fm, "curve": curve}
        each = cash / len(picks)
        for t in picks:
            p = PX[t][fm]; c = each * COST_RATE; total_costs += c; orders += 1
            positions[t] = (each - c) / p
        cash = 0.0
        nxt = months[i + 1]
        val = sum(sh * (PX.get(t, {}).get(nxt) or 0.0) for t, sh in positions.items())
        curve.append([nxt, round(val, 2)])
        if use_floor and val <= FLOOR and nxt != fm_last:
            halted = nxt
            tc = 0.0
            for t, sh in list(positions.items()):
                p = PX.get(t, {}).get(nxt); v = 0.0 if p is None else sh * p
                cc = v * COST_RATE + SELL_FEE if v > 0 else 0.0
                tc += cc; orders += 1
            total_costs += tc; cash = val - tc; positions = {}
            curve[-1] = [nxt, round(cash, 2)]
            break
    if positions:
        val = sum(sh * (PX.get(t, {}).get(fm_last) or 0.0) for t, sh in positions.items())
        tc = 0.0
        for t, sh in positions.items():
            p = PX.get(t, {}).get(fm_last); v = 0.0 if p is None else sh * p
            tc += (v * COST_RATE + SELL_FEE) if v > 0 else 0.0
        total_costs += tc; cash = max(0.0, val - tc)
    peak = START_CASH; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak > 0 else 0.0
    return {"final": round(cash, 2), "costs": round(total_costs, 2), "orders": orders,
            "max_dd_pct": round(maxdd * 100, 2), "halted": halted, "curve": curve}

def spy_buyhold(start_ym, end_ym):
    a = PX["SPY"].get(start_ym); b = PX["SPY"].get(end_ym)
    return round(100.0 * b / a, 2) if a and b else None

def period_stats(curve):
    rets, prev = [], START_CASH
    for _, v in curve:
        rets.append(v / prev - 1.0); prev = v
    if not rets: return None
    srt = sorted(rets)
    med = srt[len(srt) // 2] if len(srt) % 2 else 0.5 * (srt[len(srt)//2 - 1] + srt[len(srt)//2])
    los, run_l = 0, 0
    for r in rets:
        run_l = run_l + 1 if r < 0 else 0; los = max(los, run_l)
    peak, since, longest = -1.0, 0, 0
    for v in [START_CASH] + [x for _, x in curve]:
        if v >= peak: peak, since = v, 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(med * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2), "longest_losing_run": los,
            "longest_between_highs_months": longest,
            "average_pct_secondary": round(sum(rets) / len(rets) * 100, 2)}

ROADS_MAIN = {
    "FULL": (FORMATIONS, FINAL_MONTH),
    "VAL": ([f for f in FORMATIONS if f >= "2022-12"], FINAL_MONTH),
}
ROADS_CONF = {
    "CONF_A": ([f for f in FORMATIONS if "2019-12" <= f <= "2022-11"], "2022-12"),
    "CONF_B": ([f for f in FORMATIONS if "2023-12" <= f <= "2025-11"], "2025-12"),
}

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "main"
    roads = ROADS_MAIN if which == "main" else ROADS_CONF
    counts = GRID if which == "main" else [1, 2, 3, 5, 8, 10, 15, 20, 30]
    out_path = os.path.join(HERE, "short_interest_results.json" if which == "main" else "short_interest_confirm.json")
    out = {"family": "short-interest (long leg, Form A-broad)", "native_count": NATIVE_COUNT, "cells": {}}
    if which == "main":
        g_full = run_pot(ROADS_MAIN["FULL"][0], 30, True)
        g_val = run_pot(ROADS_MAIN["VAL"][0], 30, True)
        out["reproduction_gate"] = {"house_count30_FULL": g_full["final"], "expected_FULL": 234.11,
                                    "house_count30_VAL": g_val["final"], "expected_VAL": 155.34,
                                    "match": abs(g_full["final"] - 234.11) < 0.005 and abs(g_val["final"] - 155.34) < 0.005}
        print(f"GATE house30 FULL ${g_full['final']} (234.11) VAL ${g_val['final']} (155.34) match={out['reproduction_gate']['match']}", flush=True)
    for form, use_floor in (("house", True), ("native", False)):
        for road, (fs, fm_last) in roads.items():
            out.setdefault("spy_buyhold", {})[road] = spy_buyhold(fs[0], fm_last)
            for n in counts:
                r = run_pot(fs, n, use_floor, final_month=fm_last)
                if n == "ALL":
                    twins, beaten = None, None
                else:
                    twins = [run_pot(fs, n, use_floor, seed=s, final_month=fm_last)["final"] for s in range(1, 21)]
                    beaten = sum(1 for t in twins if r["final"] > t)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                        "orders": r["orders"], "halted": r["halted"], "ruined": r.get("ruined"),
                        "placebo_beaten": beaten, "placebo_twin_finals": twins}
                if road in ("FULL", "VAL"):
                    cell["curve"] = r["curve"]; cell["period_stats_monthly"] = period_stats(r["curve"])
                out["cells"][f"{form}|{road}|{n}"] = cell
                print(f"{form} {road} count={n}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} halted={r['halted']} placebo {beaten}/20", flush=True)
    out["pool_sizes"] = {fm: len(POOLS[fm][0]) for fm in FORMATIONS}
    json.dump(out, open(out_path, "w"), indent=1)
    print("DONE", out_path, flush=True)

if __name__ == "__main__":
    main()
