#!/usr/bin/env python3
"""Industry Concentration (Herfindahl) sort — Hou & Robinson (2006),
frozen SPEC-FROZEN.md form on the W04 broad stack.
Signal: 3-digit SIC sales Herfindahl, 3-year rolling mean of annual
HHI (snapshots F, F-1, F-2), assigned to every firm in the industry.
Formation June 30 F (stack convention), carried monthly Jul F ->
Jun F+1 (6-month accounting lag per spec). Long-only lowest-HHI
(firm-level) quintile basket, EW, monthly. Program adaptation of the
native long/short quintile spread (labeled). OP regulated-industry
exclusions implemented in simplified CONSTRUCTED form: SIC 401x
railroads, 451x airlines, 481x-484x telecom, 49xx utilities excluded
(the OP's dated deregulation schedule is approximated as a standing
exclusion — printed). Sibling scalings (book-equity HHI, asset HHI)
reported at ALL count. Costs: W04 tiered rates on set changes.
Placebos (spec primary): 20 seeds, HHI values permuted across
industries preserving industry sizes. House: v9 floor at monthly
marks. Roads are the habitat's: FULL Jul2018->Nov2026 (first
formation with a full 3-yr HHI mean), CONT Jan2019->, VAL Jan2023->.
Holdings grid: within the competitive quintile, rank by market cap
descending (CONSTRUCTED tiebreak). Simulation only."""
import json, os, sys, random, statistics, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_engine import run_monthly, month_list, period_stats_monthly

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D

EXCL3 = {401, 451, 481, 482, 483, 484}  # railroads, airlines, telecom (3-digit)
def excluded(sic):
    if sic <= 0: return True
    if 490 <= sic // 10 <= 499: return True  # utilities 49xx
    return (sic // 10) in EXCL3

SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = eng.snapshot(F)
    return SNAPS[F]

def hhi_by_industry(F, field):
    """HHI for data-year of snapshot F, per 3-digit SIC, from `field`
    ('rev' sales headline / 'equity' / 'assets')."""
    s = snap(F); tot = {}; ssq = {}
    for cik, v in s.items():
        sic = v["sic"]
        if excluded(sic): continue
        x = v[field]
        if x is None or x <= 0: continue
        g = sic // 10
        tot[g] = tot.get(g, 0.0) + x; ssq[g] = ssq.get(g, 0.0) + x * x
    return {g: ssq[g] / (tot[g] ** 2) for g in tot if tot[g] > 0}

HHI3 = {}  # F -> {group: 3yr mean HHI} per field
def hhi3(F, field):
    key = (F, field)
    if key not in HHI3:
        hs = [hhi_by_industry(f, field) for f in (F, F - 1, F - 2)]
        groups = set(hs[0]) & set(hs[1]) & set(hs[2])
        HHI3[key] = {g: sum(h[g] for h in hs) / 3 for g in groups}
    return HHI3[key]

def formation_for_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return y if m >= 7 else y - 1

def quintile_picks(ym, field="rev", count="ALL", seed=None, perm=None):
    F = formation_for_month(ym)
    if F < 2018 or F > 2026: return []
    s = snap(F); h = hhi3(F, field)
    firms = []
    for cik, v in s.items():
        g = v["sic"] // 10
        if excluded(v["sic"]) or g not in h: continue
        if not v["px_adj"] or not D.has_price_month(cik, ym): continue
        hv = perm[g] if perm else h[g]
        firms.append((hv, cik, v["cap"] or 0.0))
    if len(firms) < 20: return []
    firms.sort(key=lambda x: x[0])
    n5 = max(1, len(firms) // 5)
    comp = firms[:n5]
    if seed is not None:
        rng = random.Random(seed * 7919 + F)
        pool = [c for _, c, _ in firms]
        rng.shuffle(pool)
        n = len(comp) if count == "ALL" else min(count, len(pool))
        return pool[:n]
    if count == "ALL": return [c for _, c, _ in comp]
    comp.sort(key=lambda x: -x[2])  # cap-desc tiebreak for grid counts
    return [c for _, c, _ in comp[:count]]

ROADS = {"FULL": ("2018-07", "2026-11"), "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
SPY_ROAD = {"FULL": 100.0}  # filled from engine spy marks below

def spy_final(a, b):
    va = D.spy.get(a); vb = D.spy.get(b)
    return round(100 * vb / va, 2) if va and vb else None

def main():
    out = {"family": "hunt-herfindahl-concentration", "roads": {}}
    costf = lambda cik: eng.cost_rate((snap(formation_for_month("2020-01")).get(cik) or {}).get("cap"))
    # cost by snapshot of the formation year of each month is handled inside pick via closure below
    def run(road, form, count="ALL", field="rev", seed=None, perm=None):
        months = month_list(*ROADS[road])
        def pf(ym):
            if seed is not None:
                return quintile_picks(ym, field, count, seed=seed)
            if perm is not None:
                return quintile_picks(ym, field, count, perm=perm)
            return quintile_picks(ym, field, count)
        def cf(cik, _cache={}):
            return eng.cost_rate(None) if False else _cf(cik)
        def _cf(cik):
            return eng.cost_rate(CAPCACHE.get(cik))
        return run_monthly(months, pf, D, _cf, form)
    # cap cache per formation year for costs
    global CAPCACHE
    CAPCACHE = {}
    for F in range(2018, 2027):
        for cik, v in snap(F).items(): CAPCACHE[cik] = v["cap"]
    for road in ROADS:
        ent = {}
        for form in ("native", "house"):
            r = run(road, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = period_stats_monthly(r["monthly_returns"])
            if form == "native": ent["curve_native"] = r["curve"]
        a, b = ROADS[road]
        ent["spy_buy_hold_same_window"] = spy_final(a, b)
        out["roads"][road] = ent
        print(road, "native", ent["native"]["final"], "house", ent["house"]["final"], "spy", ent["spy_buy_hold_same_window"])
    # siblings at ALL
    out["siblings_ALL_native"] = {}
    for field in ("equity", "assets"):
        out["siblings_ALL_native"][field] = {road: run(road, "native", field=field)["final"] for road in ROADS}
    print("siblings", out["siblings_ALL_native"])
    # placebos: permuted industry HHI (FULL + VAL)
    out["placebos"] = {}
    for road in ("FULL", "VAL"):
        finals = []
        for seed in range(1, 21):
            # build a per-formation permutation of HHI across industries
            perms = {}
            def pf(ym, seed=seed):
                F = formation_for_month(ym)
                if F not in perms:
                    h = hhi3(F, "rev")
                    groups = list(h); vals = list(h.values())
                    rng = random.Random(seed * 104729 + F); rng.shuffle(vals)
                    perms[F] = dict(zip(groups, vals))
                return quintile_picks(ym, "rev", "ALL", perm=perms[F])
            months = month_list(*ROADS[road])
            r = run_monthly(months, pf, D, lambda cik: eng.cost_rate(CAPCACHE.get(cik)), "native")
            finals.append(r["final"])
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    # holdings grid
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
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
