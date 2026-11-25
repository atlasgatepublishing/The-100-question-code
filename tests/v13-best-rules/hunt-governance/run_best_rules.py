#!/usr/bin/env python3
"""hunt-governance V13 BEST RULES — frozen spec run (see BEST-RULES-SPEC.md).

MY RULES: matched IRRC universe (288 firms, v12 matching); hold every firm
with G strictly below the matched universe's median G (2006 last-published
vintage, carried forward per the OP convention — PIT: no governance data
exists after 2006 in the free stack); CAP-WEIGHTED with point-in-time caps
(shares frame <= pm year-1 x split-adj price at pm x engine-style split
factor); ANNUAL rebalance each January; NO floor; W04 tiered program
costs on traded notional. Roads adapted per the spec's coverage statement
(price stack begins 2016-01): LONG' baseline 2016-01, DECADE baseline
2016-11, CONT baseline 2018-12, VAL baseline 2022-12; returns run through
2026-11. Comparators on identical roads: v12 published-form adaptation
(democracy G<=5, EW, monthly), dictatorship basket (descriptive), SPY
buy-and-hold same window. Placebos: 20 seeds, random names from the
matched universe at the system's holdings count, same cap-weighted
annual runner. Simulation only."""
import json, os, sys, random, statistics, importlib.util
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-governance"))
from monthly_engine import run_monthly, month_list, period_stats_monthly, prev_month
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-governance")
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D

# ---- governance signal: last published vintage per firm (PIT carry) ----
wb = xlrd.open_workbook(os.path.join(V12, "data", "governance.xls"))
sh = wb.sheet_by_index(0)
hdr = next(r for r in range(sh.nrows) if sh.cell_value(r, 0) == "name")
latest = {}
for r in range(hdr + 1, sh.nrows):
    tick = str(sh.cell_value(r, 1)).strip(); yr = sh.cell_value(r, 3); g = sh.cell_value(r, 5)
    if tick and isinstance(yr, (int, float)) and isinstance(g, (int, float)):
        if tick not in latest or int(yr) > latest[tick][0]:
            latest[tick] = (int(yr), int(g))
tick2cik = {}
for cik, info in D.cand.items():
    tick2cik.setdefault(info["ticker"].replace("/", "-"), cik)
matched = {}
for tick, (yr, g) in latest.items():
    cik = tick2cik.get(tick.replace("/", "-"))
    if cik is not None: matched[cik] = g
UNIV = sorted(matched)
MED_G = statistics.median(matched[c] for c in UNIV)
SEL = sorted(c for c in UNIV if matched[c] < MED_G)
DEM = sorted(c for c in UNIV if matched[c] <= 5)
DIC = sorted(c for c in UNIV if matched[c] >= 14)
print(f"matched {len(UNIV)} medianG {MED_G} selected(G<med) {len(SEL)} democracy {len(DEM)} dictatorship {len(DIC)}")

# ---- point-in-time cap at month ym (uses prices/shares as of prev month) ----
def cap_at(cik, ym):
    pm = prev_month(ym); Y = int(pm[:4])
    px = D.price(cik, pm, adj=True)
    if px is None or px <= 0: return None
    shy = None; shares = None
    for y in (Y - 1, Y - 2, Y - 3):
        v = D.sh_series.get(y, {}).get(cik)
        if v: shy, shares = y, v; break
    if shares is None: return None
    avail = [(y, D.sh_series[y][cik]) for y in range(2014, 2026) if D.sh_series.get(y, {}).get(cik)]
    sf = 1.0
    for (y0, a), (y1, b) in zip(avail, avail[1:]):
        if y1 >= shy + 1:
            r = b / a
            if r >= 1.6 or r <= 0.625: sf *= r
    return shares * px * sf

CAPCACHE = {}
def cap_cached(cik, ym):
    k = (cik, ym)
    if k not in CAPCACHE: CAPCACHE[k] = cap_at(cik, ym)
    return CAPCACHE[k]

def name_return(cik, ym):
    pm = prev_month(ym)
    p0 = D.price(cik, pm, adj=True); p1 = D.price(cik, ym, adj=True)
    if p0 is None or p0 <= 0: return None
    series_end = max(D.px.get(cik, {"": 0}).keys()) if cik in D.px else None
    if series_end is not None and series_end < ym and not D.has_price_month(cik, ym):
        return -1.0
    if p1 is None: return None
    return p1 / p0 - 1

def run_capweighted(baseline, end, pool, seed=None):
    """pool: fixed candidate cik list. Formation at first return month and
    every January: cap-weight among pool names with a PIT cap and a price
    at pm. Dollar holdings drift between formations."""
    months = month_list(prev_month(baseline) if False else _next(baseline), end)
    rng = random.Random(seed) if seed is not None else None
    chosen = None
    if rng is not None:
        chosen = sorted(rng.sample(pool, min(len(SEL), len(pool))))
    src = chosen if chosen is not None else pool
    eq = 100.0; holdings = {}; curve = [[baseline, 100.0]]; monthly = []
    trades = 0; costs = 0.0; peak = 100.0; maxdd = 0.0
    for ym in months:
        start_eq = eq
        if ym == months[0] or ym[5:7] == "01":
            caps = {}
            for c in src:
                if D.price(c, prev_month(ym), adj=True):
                    cp = cap_cached(c, ym)
                    if cp: caps[c] = cp
            tot = sum(caps.values())
            targets = {c: eq * cp / tot for c, cp in caps.items()} if tot else {}
            notion = sum(abs(targets.get(c, 0.0) - holdings.get(c, 0.0)) for c in set(targets) | set(holdings))
            cst = sum(abs(targets.get(c, 0.0) - holdings.get(c, 0.0)) *
                      eng.cost_rate(cap_cached(c, ym)) for c in set(targets) | set(holdings))
            trades += sum(1 for c in set(targets) | set(holdings)
                          if abs(targets.get(c, 0.0) - holdings.get(c, 0.0)) > 0.01)
            costs += cst; eq -= cst
            scale = eq / start_eq if start_eq else 1.0
            holdings = {c: v * scale for c, v in targets.items()}
        newh = {}
        for c, dol in holdings.items():
            r = name_return(c, ym)
            if r is None: newh[c] = dol
            elif r <= -1.0: pass  # delisted: written to zero, drops out
            else: newh[c] = dol * (1 + r)
        holdings = newh
        eq = sum(holdings.values()) if holdings else eq
        monthly.append(round(eq / start_eq - 1, 4) if start_eq else 0.0)
        curve.append([ym, round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4),
            "monthly_returns": monthly,
            "period_stats_monthly": period_stats_monthly(monthly)}

def _next(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y+1:04d}-01" if m == 12 else f"{y:04d}-{m+1:02d}"

ROADS = {"LONG'": ("2016-01", "2026-11"), "DECADE": ("2016-11", "2026-11"),
         "CONT": ("2018-12", "2026-11"), "VAL": ("2022-12", "2026-11")}
CHAMP = {"LONG'": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_STD = {"LONG'": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def spy_final(base, end):
    va = D.spy.get(base); vb = D.spy.get(end)
    return round(100 * vb / va, 2) if va and vb else None

def ew_picks(pool):
    def pf(ym):
        return [c for c in pool if D.has_price_month(c, ym) and D.price(c, ym)]
    return pf

CAP_LAST = {}
for F in range(2014, 2027):
    for cik, v in eng.snapshot(F).items():
        if v.get("cap"): CAP_LAST[cik] = v["cap"]

def main():
    out = {"family": "hunt-governance", "program": "v13-best-rules",
           "rules": "G < matched-universe median G; cap-weighted PIT caps; annual Jan rebalance; no floor",
           "median_G_matched_universe": MED_G, "matched_firms": len(UNIV),
           "selected_n": len(SEL), "democracy_n": len(DEM), "dictatorship_n": len(DIC),
           "selected_G_counts": {str(g): sum(1 for c in SEL if matched[c] == g)
                                 for g in sorted(set(matched[c] for c in SEL))},
           "roads": {}}
    for road, (base, end) in ROADS.items():
        r = run_capweighted(base, end, SEL)
        months = month_list(_next(base), end)
        dem = run_monthly(months, ew_picks(DEM), D, lambda cik: eng.cost_rate(CAP_LAST.get(cik)), "native")
        dic = run_monthly(months, ew_picks(DIC), D, lambda cik: eng.cost_rate(CAP_LAST.get(cik)), "native")
        ent = {"my_rules": {k: v for k, v in r.items() if k != "curve"},
               "curve_my_rules": r["curve"],
               "published_form_democracy_EW_monthly": {"final": dem["final"], "max_dd": dem["max_dd"]},
               "dictatorship_descriptive": {"final": dic["final"], "max_dd": dic["max_dd"]},
               "spy_buy_hold_same_window": spy_final(base, end),
               "spy_standard_road_reference": SPY_STD[road],
               "champion_VM": CHAMP[road]}
        out["roads"][road] = ent
        print(road, "mine", r["final"], "dd", r["max_dd"], "| published-form", dem["final"],
              "| dict", dic["final"], "| spy", ent["spy_buy_hold_same_window"], "| champ", CHAMP[road], flush=True)
    out["placebos"] = {}
    for road in ("LONG'", "VAL"):
        base, end = ROADS[road]
        finals = []
        for s in range(1, 21):
            finals.append(run_capweighted(base, end, UNIV, seed=s)["final"])
        sysf = out["roads"][road]["my_rules"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_final": sysf, "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road], flush=True)
    # era split within LONG' (standalone $100 sub-runs, descriptive)
    out["era_split_LONG'"] = {}
    for label, (b, e) in {"2016-2019": ("2016-01", "2019-12"), "2020-2022": ("2019-12", "2022-12"),
                          "2023-2026": ("2022-12", "2026-11")}.items():
        r = run_capweighted(b, e, SEL)
        out["era_split_LONG'"][label] = {"final": r["final"], "max_dd": r["max_dd"],
                                         "spy": spy_final(b, e),
                                         "period_stats_monthly": r["period_stats_monthly"]}
        print("era", label, r["final"], "spy", out["era_split_LONG'"][label]["spy"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
