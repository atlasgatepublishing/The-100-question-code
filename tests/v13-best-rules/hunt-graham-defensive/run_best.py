#!/usr/bin/env python3
"""Graham Defensive — V13 BEST RULES run, per BEST-RULES-SPEC.md
(frozen before this run). Deltas vs the v12 faithful form, and only
these:
 * Test 2 (financial strength) rewritten to intent: current ratio
   >= 1.5 AND long-term debt <= book equity (missing LTD = FAIL).
 * Tests 6+7 replaced by Graham's own combined price gate:
   P/E (3-yr avg EPS) x P/B <= 22.5 as the sole price test.
 * Holdings: ALL qualifiers, equal weight, no ranking.
 * No floor, no stop (the only form run).
Everything else — universe, pool, tests 1/3/4/5, December annual
formation, point-in-time as-filed fundamentals (W04 stack + v12
frames_ext + v12 dividend histories + v12 CPI cache, all read-only),
program tiered costs, delisted-to-zero — is v12's machinery unchanged.
Roads: FULL formations Dec 2020-2025; VAL formations Dec 2023-2025.
(LONG/DECADE formations before Dec 2020 are not computable: the
10-year earnings test needs EDGAR NI frames from 2010.)
Placebos: 20 seeds, random pool names at the qualifier count.
Simulation only."""
import json, os, sys, random, statistics, importlib.util, csv, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-graham-defensive")
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D
W04F = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/frames")
EXTF = os.path.join(V12, "data", "frames_ext")

def loadf(name, year, kind):
    for base in (EXTF, W04F):
        p = os.path.join(base, f"{name}_{year}{kind}.json")
        if os.path.exists(p):
            return {int(k): v for k, v in json.load(open(p)).items()}
    return {}
NI = {y: loadf("NetIncomeLoss", y, "D") for y in range(2010, 2026)}
SH = {y: loadf("Shares", y, "I") for y in range(2010, 2026)}

cpi = {}
with open(os.path.join(V12, "data", "FRED_CPIAUCNS.csv")) as f:
    for row in csv.reader(f):
        if len(row) == 2 and row[0][0].isdigit() and row[1] not in ("", "."):
            cpi.setdefault(row[0][:4], []).append(float(row[1]))
CPI = {y: sum(v) / len(v) for y, v in cpi.items()}
CPI_1973 = 44.4

DIVS = {}
def div_years(ticker):
    if ticker not in DIVS:
        p = os.path.join(V12, "data", "divs", ticker.replace("/", "-") + ".json")
        ev = json.load(open(p)) if os.path.exists(p) else {}
        DIVS[ticker] = sorted(int(k) for k in ev.keys())
    return DIVS[ticker]

def eps(cik, y):
    ni = NI[y].get(cik); sh = SH[y].get(cik)
    if ni is None or not sh: return None
    return ni / sh

def evaluate(F):
    """V13 tests. Returns (qualifier ciks, data-complete pool, per-test
    pass counts, qualifier tickers)."""
    s = eng.snapshot(F)
    thr = 100e6 * CPI[str(F - 1)] / CPI_1973
    quals = []; pool = []
    counts = {i: 0 for i in range(1, 7)}
    for cik, v in s.items():
        sic = v["sic"]
        if eng.is_fin(sic) or eng.is_util(sic) or sic in (0, 9999): continue
        pxr = D.price(cik, f"{F}-12", adj=False)
        if not pxr or not v["equity"] or v["equity"] <= 0: continue
        nis = [NI[y].get(cik) for y in range(F - 10, F)]
        if any(x is None for x in nis): continue
        epss = [eps(cik, y) for y in range(F - 10, F)]
        if any(x is None for x in epss): continue
        pool.append(cik)
        t = [False] * 6
        t[0] = v["rev"] is not None and v["rev"] >= thr
        # V13 test 2: CR >= 1.5 AND LTD <= book equity
        t[1] = (v["ca"] is not None and v["cl"] not in (None, 0) and v["ltd"] is not None
                and v["ca"] >= 1.5 * v["cl"] and v["ltd"] <= v["equity"])
        t[2] = all(x > 0 for x in nis)
        ev = div_years(v["ticker"])
        yrs = {time.gmtime(ts).tm_year for ts in ev}
        t[3] = all(y in yrs for y in range(F - 20, F))
        if t[3]:
            win = [ts for ts in ev if F - 20 <= time.gmtime(ts).tm_year <= F - 1]
            gaps = [b - a for a, b in zip(win, win[1:])]
            if gaps and max(gaps) > 548 * 86400: t[3] = False
        e_first = sum(epss[:3]) / 3; e_last = sum(epss[-3:]) / 3
        t[4] = e_first > 0 and e_last >= (4 / 3) * e_first
        pe = pxr / e_last if e_last > 0 else None
        shares = SH[F - 1].get(cik)
        pb = (pxr * shares / v["equity"]) if shares else None
        # V13 price gate: Graham's combined product, sole price test
        t[5] = pe is not None and pb is not None and pe * pb <= 22.5
        for i in range(6): counts[i + 1] += 1 if t[i] else 0
        if all(t):
            quals.append(cik)
    tickers = {c: s[c]["ticker"] for c in quals}
    return quals, pool, counts, tickers

def annual_run(formations, seed=None):
    cash = 100.0; curve = []; costs = 0.0; trades = 0; yearly = []
    QUALS = {}
    for F in formations:
        q, pool, _, _ = evaluate(F)
        QUALS[F] = (q, pool)
    for F in formations:
        q, pool = QUALS[F]
        if seed is not None:
            rng = random.Random(seed * 7919 + F)
            keys = list(pool); rng.shuffle(keys)
            picks = keys[:len(q)]
        else:
            picks = list(q)
        months = [f"{F}-12"] + [f"{F+1}-{m:02d}" for m in range(1, 13)]
        months = [m for m in months if m <= "2026-11"]
        start_val = cash
        if not picks:
            for m in months[1:]: curve.append([m, round(cash, 4)])
            yearly.append({"formation": F, "n": 0, "ret": 0.0})
            continue
        s = eng.snapshot(F)
        w = cash / len(picks); pos = {}
        for c in picks:
            p0 = D.price(c, f"{F}-12", adj=True)
            if not p0: continue
            rate = eng.cost_rate(s[c]["cap"]); costs += w * rate; trades += 1
            pos[c] = (w - w * rate) / p0
        for m in months[1:]:
            val = 0.0
            for c, shn in pos.items():
                p = D.price(c, m, adj=True)
                if p is None: p = D.price(c, f"{F}-12", adj=True)
                if not D.has_price_month(c, m) and max(D.px.get(c, {"": 0}).keys() or [""]) < m:
                    p = 0.0
                val += shn * (p or 0.0)
            curve.append([m, round(val, 4)])
        end_val = 0.0
        last_m = months[-1]
        for c, shn in pos.items():
            p = D.price(c, last_m, adj=True)
            if p is None: p = D.price(c, f"{F}-12", adj=True)
            if not D.has_price_month(c, last_m) and max(D.px.get(c, {"": 0}).keys() or [""]) < last_m:
                p = 0.0
            gross = shn * (p or 0.0)
            rate = eng.cost_rate(s[c]["cap"]); costs += gross * rate; trades += 1
            end_val += gross - gross * rate
        cash = end_val
        yearly.append({"formation": F, "n": len(picks), "ret": round(cash / start_val - 1, 4)})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(cash, 2), "curve": curve, "costs": round(costs, 2),
            "trades": trades, "max_dd": round(maxdd, 4), "yearly": yearly}

def spy_final(a, b):
    va = D.spy.get(a); vb = D.spy.get(b)
    return round(100 * vb / va, 2) if va and vb else None

def dist_stats(curve):
    """Per-period (monthly) distribution from the equity curve."""
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 if vals[i - 1] > 0 else 0.0 for i in range(1, len(vals))]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = longest = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1
        longest = max(longest, since)
    return {"periods_monthly": len(rets), "share_positive": round(pos / len(rets), 3),
            "median_monthly": round(statistics.median(rets), 4),
            "best_monthly": round(max(rets), 4), "worst_monthly": round(min(rets), 4),
            "longest_losing_streak_months": streak,
            "longest_stretch_between_new_highs_months": longest,
            "average_monthly_secondary": round(sum(rets) / len(rets), 4)}

def astats(yearly):
    rets = [y["ret"] for y in yearly]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {"periods_annual": len(rets), "share_positive": round(pos / len(rets), 3),
            "median_annual": round(statistics.median(rets), 4),
            "best_annual": round(max(rets), 4), "worst_annual": round(min(rets), 4),
            "longest_losing_streak_annual": streak,
            "average_annual_secondary": round(sum(rets) / len(rets), 4)}

def main():
    out = {"family": "hunt-graham-defensive", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)", "roads": {}}
    census = {}
    for F in range(2020, 2026):
        q, pool, counts, tickers = evaluate(F)
        census[F] = {"qualifiers": len(q), "pool": len(pool),
                     "per_test_pass": counts, "tickers": [tickers[c] for c in q]}
        print("formation", F, census[F], flush=True)
    out["census"] = census
    ROADS = {"FULL": list(range(2020, 2026)), "VAL": list(range(2023, 2026))}
    for road, forms_ in ROADS.items():
        r = annual_run(forms_)
        ent = {k: v for k, v in r.items() if k != "curve"}
        ent["curve"] = r["curve"]
        ent["period_stats_monthly"] = dist_stats(r["curve"])
        ent["period_stats_annual"] = astats(r["yearly"])
        a = f"{forms_[0]}-12"; b = "2026-11"
        ent["spy_buy_hold_same_window"] = spy_final(a, b)
        out["roads"][road] = ent
        print(road, "final", ent["final"], "maxdd", ent["max_dd"], "spy", ent["spy_buy_hold_same_window"], flush=True)
    out["placebos"] = {}
    for road, forms_ in ROADS.items():
        finals = [annual_run(forms_, seed=s)["final"] for s in range(1, 21)]
        sysf = out["roads"][road]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
