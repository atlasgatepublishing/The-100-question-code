#!/usr/bin/env python3
"""hunt-zweig-growth-screen — V13 BEST RULES (spec frozen in BEST-RULES-SPEC.md).
Chassis identical to the v12 run (broad w04 stack, monthly marks, flat
0.75%/side = cost_rate(None), vanished prices written to ZERO, same portfolio
accounting) so the only difference vs the published form is the rules:
 (i) EPS>0 all 4 yrs AND 3-yr EPS CAGR >= 15% AND latest-yr EPS growth >= CAGR
     (Zweig's 'not deteriorating' as a comparison, not a second absolute bar);
 (ii) revenue growth > 0 AND >= half the 3-yr EPS CAGR (repaired indexing);
 (iii) 5 < trailing P/E <= 40 (as published);
 (iv) insider leg CUT (see spec diagnosis 4);
 (v) 6-month price return > SPY's (as published).
Rank by 3-yr CAGR desc; hold ALL qualifiers up to 20 equal-weight; quarterly
formation 2018-06..2026-09 (first with a full 4-yr EPS history on this stack);
NO floor. Roads are independent $100 pots over their full named windows,
cash until the first formation."""
import json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
sys.path.insert(0, W04)
import importlib.util
spec = importlib.util.spec_from_file_location("engine_w04", os.path.join(W04, "engine_w04.py"))
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data()
D = eng.D
START = 100.0
MAXHOLD = 20

_eps_cache, _rev_cache = {}, {}
def eps_series(cik):
    if cik in _eps_cache: return _eps_cache[cik]
    out = {}
    for y in range(2014, 2026):
        ni = D.F("NetIncomeLoss", y, "D").get(cik)
        sh = None
        for yy in (y, y-1, y-2):
            sh = D.F("Shares", yy, "I").get(cik)
            if sh: break
        if ni is not None and sh:
            out[y] = ni / sh
    _eps_cache[cik] = out
    return out

def rev_of(cik, y):
    if (cik, y) in _rev_cache: return _rev_cache[(cik, y)]
    v = None
    for c in ("Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"):
        v = D.F(c, y, "D").get(cik)
        if v is not None: break
    _rev_cache[(cik, y)] = v
    return v

def screen(formation, funnel=None):
    Y, M = int(formation[:4]), int(formation[5:7])
    fy = Y - 1 if M >= 6 else Y - 2
    quals = []
    for cik, info in D.cand.items():
        eps = eps_series(cik)
        if not all((fy - k) in eps for k in range(4)): continue
        if funnel is not None: funnel["has_eps"] += 1
        e0, e1, e2, e3 = eps[fy-3], eps[fy-2], eps[fy-1], eps[fy]
        if min(e0, e1, e2, e3) <= 0: continue
        cagr = (e3 / e0) ** (1/3) - 1
        g_eps = e3 / e2 - 1
        if cagr < 0.15 or g_eps < cagr: continue
        if funnel is not None: funnel["eps_leg"] += 1
        r1, r0 = rev_of(cik, fy), rev_of(cik, fy - 1)
        if not r1 or not r0 or r0 <= 0: continue
        g_rev = r1 / r0 - 1
        if g_rev <= 0 or g_rev < 0.5 * cagr: continue
        if funnel is not None: funnel["rev_leg"] += 1
        px = D.price(cik, formation, adj=False)
        if not px: continue
        sf = D.sf.get(cik, {}).get(fy + 1, 1.0)
        pe = px / (e3 * sf) if e3 * sf > 0 else None
        if pe is None or not (5 < pe <= 40): continue
        if funnel is not None: funnel["pe_leg"] += 1
        p_now = D.price(cik, formation, adj=True)
        y2, m2 = Y, M - 6
        while m2 <= 0: m2 += 12; y2 -= 1
        p_then = D.price(cik, f"{y2:04d}-{m2:02d}", adj=True)
        if not p_now or not p_then: continue
        quals.append({"cik": cik, "ticker": info["ticker"], "g_eps": g_eps,
                      "cagr": cagr, "pe": pe, "rs": p_now / p_then - 1})
    spy_now = D.spy.get(formation)
    y2, m2 = Y, M - 6
    while m2 <= 0: m2 += 12; y2 -= 1
    spy_then = D.spy.get(f"{y2:04d}-{m2:02d}")
    if spy_now and spy_then:
        spy_rs = spy_now / spy_then - 1
        quals = [q for q in quals if q["rs"] > spy_rs]
    if funnel is not None: funnel["all_legs"] += len(quals)
    quals.sort(key=lambda q: -q["cagr"])
    return quals

def price_adj(cik, ym_):
    return D.price(cik, ym_, adj=True)

def month_iter(a, b):
    y, m = int(a[:4]), int(a[5:7]); y2, m2 = int(b[:4]), int(b[5:7])
    while (y, m) <= (y2, m2):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12: m = 1; y += 1

# --- portfolio accounting copied verbatim from the v12 chassis (no floor) ---
def run_portfolio(formations, picks_by_formation, start, end,
                  placebo_seed=None, universe_pool=None):
    cash = START; holdings = {}
    curve = []; costs = 0.0
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    for ym_ in month_iter(start, end):
        for cik in list(holdings):
            p = price_adj(cik, ym_)
            if p is None:
                later = [mm for mm in month_iter(ym_, end) if price_adj(cik, mm) is not None]
                if not later: holdings[cik] = 0.0
        if ym_ in formations:
            if rng is not None or True:
                picks = picks_by_formation.get(ym_, [])
                if rng is not None:
                    pool = universe_pool if universe_pool is not None else picks_by_formation.get("_pool_" + ym_, [])
                    picks = rng.sample(pool, min(len(picks_by_formation.get(ym_, [])), len(pool))) if pool else []
                total = cash + sum(holdings.values())
                for cik, val in list(holdings.items()):
                    fee = val * eng.cost_rate(None)
                    cash += val - fee; costs += fee
                holdings = {}
                if picks:
                    each = cash / len(picks)
                    for cik in picks:
                        fee = each * eng.cost_rate(None)
                        holdings[cik] = each - fee; costs += fee
                    cash = 0.0
        eq = cash + sum(holdings.values())
        curve.append([ym_, round(eq, 4)])
        if holdings:
            nxt = {}
            months = list(month_iter(ym_, end))
            if len(months) > 1:
                nm = months[1]
                for cik, val in holdings.items():
                    p0, p1 = price_adj(cik, ym_), price_adj(cik, nm)
                    if p0 and p1: nxt[cik] = val * p1 / p0
                    elif p0 and p1 is None:
                        later = [mm for mm in month_iter(nm, end) if price_adj(cik, mm) is not None]
                        nxt[cik] = 0.0 if not later else val
                    else: nxt[cik] = val
                holdings = nxt
    final = curve[-1][1] if curve else START
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "equity_curve": curve}

def period_stats_monthly(curve):
    if not curve: return None
    series = [START] + [v for _, v in curve]
    rets = [(series[i]/series[i-1] - 1.0)*100.0 if series[i-1] > 0 else 0.0 for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": "monthly", "periods": len(rets), "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst, "longest_between_highs_periods": longest}

def spy_monthly(start, end):
    months = [m for m in month_iter(start, end) if m in D.spy]
    if not months: return {"final": None, "max_dd_pct": None, "equity_curve": []}
    base = D.spy.get(months[0])
    sh = (START / (1 + 0.001)) / base if base else 0
    curve = [[ym_, round(sh * D.spy[ym_], 4)] for ym_ in months]
    val = curve[-1][1]; curve[-1] = [curve[-1][0], round(val - (val * 0.001 + 0.01), 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": curve[-1][1], "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def main():
    formations = []
    for y in range(2018, 2027):
        for mq in (3, 6, 9, 12):
            fm = f"{y:04d}-{mq:02d}"
            if "2018-06" <= fm <= "2026-09": formations.append(fm)
    quals, funnels = {}, {}
    for fm in formations:
        f = {"has_eps": 0, "eps_leg": 0, "rev_leg": 0, "pe_leg": 0, "all_legs": 0}
        q = screen(fm, funnel=f)
        quals[fm], funnels[fm] = q, f
        print(f"formation {fm}: {len(q)} qualifiers {[x['ticker'] for x in q[:MAXHOLD]]}", flush=True)
    picks = {fm: [x["cik"] for x in quals[fm][:MAXHOLD]] for fm in formations}
    pools = {fm: [x["cik"] for x in quals[fm]] for fm in formations}
    univ = [cik for cik in D.cand if D.px.get(cik)]
    roads = {"LONG": ("2010-01", "2026-11"), "DECADE": ("2016-11", "2026-11"),
             "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
    champion = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    spy_prog = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
    out = {"family": "hunt-zweig-growth-screen — V13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "chassis": "broad w04 stack (658 candidates); quarterly formation 2018-06..2026-09; monthly marks; flat 0.75%/side; NO floor; vanished prices to ZERO; insider leg CUT per spec",
           "qualifier_counts": {fm: len(q) for fm, q in quals.items()},
           "qualifier_pools": {fm: [q["ticker"] for q in q] for fm, q in quals.items()},
           "funnels": funnels, "roads": {}}
    for rname, (s, e) in roads.items():
        r = run_portfolio(formations, picks, s, e)
        entry = {"my_rules": {**r, "period_stats_monthly": period_stats_monthly(r["equity_curve"])},
                 "benchmark_spy_stack": spy_monthly(s, e),
                 "champion_vm_program": champion[rname], "spy_program": spy_prog[rname],
                 "published_form_v12": {"CONT": 130.81, "VAL": 100.00}.get(rname)}
        real = r["final"]
        pq, pu = [], []
        for seed in range(1, 21):
            picks_p = dict(picks); picks_p.update({("_pool_" + fm): pools[fm] for fm in formations})
            pq.append(run_portfolio(formations, picks_p, s, e, placebo_seed=seed)["final"])
            pu.append(run_portfolio(formations, picks, s, e, placebo_seed=seed, universe_pool=univ)["final"])
        entry["placebos"] = {"from_qualifier_pool": {"seed_finals": pq, "beaten_of_20": sum(1 for p in pq if real > p)},
                             "from_universe": {"seed_finals": pu, "beaten_of_20": sum(1 for p in pu if real > p)}}
        out["roads"][rname] = entry
        print(f"{rname}: my rules ${real} (DD {r['max_dd_pct']}%) spy-stack ${entry['benchmark_spy_stack']['final']} placebos pool {entry['placebos']['from_qualifier_pool']['beaten_of_20']}/20 univ {entry['placebos']['from_universe']['beaten_of_20']}/20", flush=True)
    # Confirmation (frozen bars) — only for roads beating the champion
    conf = {}
    for rname, (s, e) in roads.items():
        if out["roads"][rname]["my_rules"]["final"] > champion[rname]:
            months = list(month_iter(s, e)); mid = months[len(months)//2]
            halves = [(s, months[len(months)//2 - 1]), (mid, e)]
            half_res = []
            for hs, he in halves:
                hr = run_portfolio(formations, picks, hs, he)
                hspy = spy_monthly(hs, he)
                half_res.append({"window": [hs, he], "final": hr["final"],
                                 "spy_stack_final": hspy["final"],
                                 "beats_spy": (hr["final"] - 100) > ((hspy["final"] or 100) - 100)})
            years = sorted(set(m[:4] for m in months))
            folds, above, bspy = [], 0, 0
            for yy in years:
                fs, fe = f"{yy}-01", ("2026-11" if yy == "2026" else f"{yy}-12")
                if fs < s: fs = s
                if fe > e: fe = e
                fr = run_portfolio(formations, picks, fs, fe)
                fspy = spy_monthly(fs, fe)
                ok1 = fr["final"] > 100; ok2 = (fr["final"] - 100) > ((fspy["final"] or 100) - 100)
                above += ok1; bspy += ok2
                folds.append({"year": yy, "final": fr["final"], "spy_stack_final": fspy["final"],
                              "above_100": ok1, "beats_spy": ok2})
            n = len(years)
            conf[rname] = {"halves": half_res, "year_folds": folds,
                           "bar_a_both_halves_beat_spy": all(h["beats_spy"] for h in half_res),
                           "bar_b_majority_years_above100_and_beat_spy": (above > n/2) and (bspy > n/2),
                           "confirmed": all(h["beats_spy"] for h in half_res) and (above > n/2) and (bspy > n/2)}
            print(f"CONFIRMATION {rname}: {conf[rname]['confirmed']}", flush=True)
    out["confirmation"] = conf
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
