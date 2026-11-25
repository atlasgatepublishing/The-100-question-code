#!/usr/bin/env python3
"""Governance Index (Gompers-Ishii-Metrick 2003) — frozen SPEC form.
Data: the authors' own governance.xls (Metrick's Wharton page, via the
Wayback Machine; see HUNT-LOG.md) — firm name, ticker, vintage year
(1990/1993/1995/1998/2000/2002/2004/2006), G. Program adaptation
(labeled in spec): long-only democracy basket (G <= 5), EW, monthly,
on the W04 broad stack. Signal = last published vintage (Jan 2006)
carried forward per the OP's own carry convention — the printed fence
is that the signal is 8-20 years stale over the run window; the run
tests whether the 2006 cross-section of shareholder rights predicted
2014-2026 returns, NOT the OP 1990s test (prices for the OP window do
not exist in the free stack). Tickers matched to W04 candidates by
CURRENT ticker (renamed/dead firms unmatched — counted and printed;
survivorship fence). Dictatorship basket (G >= 14) printed
descriptively. Placebos: 20 seeds, random names from the matched
IRRC universe at the democracy count. House: v9 floor at monthly
marks. Holdings grid: democracy names ranked by market cap desc
(CONSTRUCTED tiebreak). Cremers-Nair leg: NOT RUN — needs PIT 13F
institutional-ownership aggregates not in the free stack (grid gap).
Simulation only."""
import json, os, sys, random, statistics, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_engine import run_monthly, month_list, period_stats_monthly
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D

wb = xlrd.open_workbook(os.path.join(HERE, "data", "governance.xls"))
sh = wb.sheet_by_index(0)
hdr = next(r for r in range(sh.nrows) if sh.cell_value(r, 0) == "name")
recs = []
for r in range(hdr + 1, sh.nrows):
    name = str(sh.cell_value(r, 0)).strip(); tick = str(sh.cell_value(r, 1)).strip()
    yr = sh.cell_value(r, 3); g = sh.cell_value(r, 5)
    if name and isinstance(yr, (int, float)) and isinstance(g, (int, float)):
        recs.append({"name": name, "ticker": tick, "year": int(yr), "G": int(g)})
latest = {}
for rec in recs:
    if rec["ticker"] not in latest or rec["year"] > latest[rec["ticker"]]["year"]:
        latest[rec["ticker"]] = rec
tick2cik = {}
for cik, info in D.cand.items():
    tick2cik.setdefault(info["ticker"].replace("/", "-"), cik)
matched = {}; unmatched = 0
for tick, rec in latest.items():
    cik = tick2cik.get(tick.replace("/", "-"))
    if cik is None: unmatched += 1
    else: matched[cik] = rec
print("G tickers", len(latest), "matched to W04", len(matched), "unmatched", unmatched)
DEM = sorted(c for c, r in matched.items() if r["G"] <= 5)
DIC = sorted(c for c, r in matched.items() if r["G"] >= 14)
UNIV = sorted(matched)
print("democracy", len(DEM), "dictatorship", len(DIC), "universe", len(UNIV))
CAP = {}
for F in range(2014, 2027):
    s = eng.snapshot(F)
    for cik, v in s.items(): CAP[cik] = v["cap"]

ROADS = {"FULL": ("2014-07", "2026-11"), "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
def spy_final(a, b):
    va = D.spy.get(a); vb = D.spy.get(b)
    return round(100 * vb / va, 2) if va and vb else None

def picks(count="ALL", seed=None, pool=DEM):
    def pf(ym):
        avail = [c for c in pool if D.has_price_month(c, ym) and D.price(c, ym)]
        if seed is not None:
            rng = random.Random(seed * 7919 + int(ym[:4]) * 100 + int(ym[5:7]))
            rng.shuffle(avail)
            n = len([c for c in DEM if D.has_price_month(c, ym)]) if count == "ALL" else count
            return avail[:max(1, min(n, len(avail)))]
        if count == "ALL": return avail
        avail.sort(key=lambda c: -(CAP.get(c) or 0))
        return avail[:count]
    return pf

def run(road, form, count="ALL", seed=None, pool=DEM):
    months = month_list(*ROADS[road])
    return run_monthly(months, picks(count, seed, pool), D,
                       lambda cik: eng.cost_rate(CAP.get(cik)), form)

def main():
    out = {"family": "hunt-governance",
           "g_vintage_used": "last published vintage per firm (2006 edition for most; carried forward, OP convention)",
           "matched_firms": len(matched), "unmatched_g_tickers": unmatched,
           "democracy_n": len(DEM), "dictatorship_n": len(DIC), "roads": {}}
    for road in ROADS:
        ent = {}
        for form in ("native", "house"):
            r = run(road, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = period_stats_monthly(r["monthly_returns"])
            if form == "native": ent["curve_native"] = r["curve"]
        ent["spy_buy_hold_same_window"] = spy_final(*ROADS[road])
        ent["dictatorship_native_descriptive"] = run(road, "native", pool=DIC)["final"]
        out["roads"][road] = ent
        print(road, "dem native", ent["native"]["final"], "house", ent["house"]["final"],
              "spy", ent["spy_buy_hold_same_window"], "dict", ent["dictatorship_native_descriptive"])
    out["placebos"] = {}
    for road in ("FULL", "VAL"):
        finals = [run(road, "native", seed=s, pool=UNIV)["final"] for s in range(1, 21)]
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    grid = {}
    for count in (1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"):
        grid[str(count)] = {}
        for road in ROADS:
            ent = {}
            for form in ("native", "house"):
                r = run(road, form, count=count)
                ent[form] = {k: v for k, v in r.items() if k != "curve"}
                ent[form]["period_stats_monthly"] = period_stats_monthly(r["monthly_returns"])
                if form == "native": ent["curve_native"] = r["curve"]
            grid[str(count)][road] = ent
        print("grid", count, {r: grid[str(count)][r]["native"]["final"] for r in ROADS})
    out["holdings_grid"] = grid
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
