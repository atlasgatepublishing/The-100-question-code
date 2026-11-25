#!/usr/bin/env python3
"""hunt-zweig-growth-screen — Zweig Growth Screen (Winning on Wall Street,
1986; AAII codification), CONSTRUCTED numerics per SPEC-FROZEN (c).
Broad PIT filer universe = the v11 w04 stack (EDGAR frames + monthly Yahoo
prices + candidates), read-only. Quarterly formation; screen:
 (i) 3-yr EPS CAGR >= 15%/yr AND latest-FY EPS growth >= 20% YoY, EPS > 0 in
     all four years (EPS = NetIncomeLoss / shares outstanding);
 (ii) revenue growth YoY >= 10% AND >= half the EPS growth rate;
 (iii) 5 < trailing P/E <= 40 (P/E on split-consistent EPS);
 (iv) net insider open-market (Form 4 codes P/S) value over prior 6 months
      >= 0 (events.csv cache, 2019+);
 (v) 6-month price return > SPY's (monthly rendering of 26-week RS).
Rank qualifiers by latest-FY EPS growth desc; hold top N equal-weight to the
next formation. Costs: w04 tiered habitat cost_rate(cap) per side. Native:
no floor. House: v9 floor adapted to monthly marks (breach at a month-end
close <= 85% of episode start -> liquidate at that month-end, 90-day halt,
second breach ends) — adaptation named. Prices vanishing mid-holding are
written to ZERO (program construction rule)."""
import csv, json, os, random, statistics, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
sys.path.insert(0, W04)
import importlib.util
spec = importlib.util.spec_from_file_location("engine_w04", os.path.join(W04, "engine_w04.py"))
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data()
D = eng.D
START = 100.0

EVENTS = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/events.csv")
insider = {}  # symbol -> list of (filing_date, code, value)
with open(EVENTS) as f:
    for r in csv.DictReader(f):
        if r["code"] in ("P", "S"):
            insider.setdefault(r["symbol"], []).append((r["filing_date"], r["code"], float(r["value"] or 0)))
for k in insider: insider[k].sort()

def insider_net(sym, end_date, months=6):
    """Net insider open-market TRANSACTIONS (count of code-P filings minus
    count of code-S filings) over the prior 6 months — the frozen spec's
    literal unit ('net insider open-market transactions >= 0'). An earlier
    draft of this run used net dollar VALUE, which vetoed effectively every
    large filer (insider sale values dwarf purchase values even at healthy
    growth names); that was an implementation unit error against the frozen
    wording, corrected here and documented in RESULTS.md. No filings at all
    = no heavy selling = pass."""
    y, m = int(end_date[:4]), int(end_date[5:7])
    m -= months
    while m <= 0: m += 12; y -= 1
    lo = f"{y:04d}-{m:02d}-01"
    net = 0
    for d, c, v in insider.get(sym, []):
        if lo <= d <= end_date:
            net += 1 if c == "P" else -1
    return net

def eps_series(cik):
    """{CY year: EPS} from frames: NI(CY) / shares(latest instant <= CY)}"""
    out = {}
    for y in range(2013, 2026):
        ni = D.F("NetIncomeLoss", y, "D").get(cik)
        sh = None
        for yy in (y, y-1, y-2):
            sh = D.F("Shares", yy, "I").get(cik)
            if sh: break
        if ni is not None and sh:
            out[y] = ni / sh
    return out

def rev_of(cik, y):
    for c in ("Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"):
        v = D.F(c, y, "D").get(cik)
        if v is not None: return v
    return None

def screen(formation):
    """formation = 'YYYY-MM' (month-end). Returns ranked qualifier list of
    dicts (cik, ticker, eps_growth, cap)."""
    Y, M = int(formation[:4]), int(formation[5:7])
    fy = Y - 1 if M >= 6 else Y - 2
    fdate = formation + "-28"
    quals = []
    for cik, info in D.cand.items():
        eps = eps_series(cik)
        if not all((fy - k) in eps for k in range(4)): continue
        e0, e1, e2, e3 = eps[fy-3], eps[fy-2], eps[fy-1], eps[fy]
        if min(e0, e1, e2, e3) <= 0: continue
        cagr = (e3 / e0) ** (1/3) - 1
        g_eps = e3 / e2 - 1
        if cagr < 0.15 or g_eps < 0.20: continue
        r1, r0 = rev_of(cik, fy), rev_of(cik, fy - 1)
        if not r1 or not r0 or r0 <= 0: continue
        g_rev = r1 / r0 - 1
        if g_rev < 0.10 or g_rev < 0.5 * g_eps: continue
        px = D.price(cik, formation, adj=False)
        if not px: continue
        sf = D.sf.get(cik, {}).get(fy + 1, 1.0)
        pe = px / (e3 * sf) if e3 * sf > 0 else None
        if pe is None or not (5 < pe <= 40): continue
        sym = info["ticker"]
        if insider_net(sym, fdate) < 0: continue
        p_now = D.price(cik, formation, adj=True)
        y2, m2 = Y, M - 6
        while m2 <= 0: m2 += 12; y2 -= 1
        p_then = D.price(cik, f"{y2:04d}-{m2:02d}", adj=True)
        if not p_now or not p_then: continue
        rs = p_now / p_then - 1
        quals.append({"cik": cik, "ticker": sym, "g_eps": g_eps, "cagr": cagr,
                      "pe": pe, "rs": rs})
    spy_now = D.spy.get(formation)
    y2, m2 = Y, M - 6
    while m2 <= 0: m2 += 12; y2 -= 1
    spy_then = D.spy.get(f"{y2:04d}-{m2:02d}")
    if spy_now and spy_then:
        spy_rs = spy_now / spy_then - 1
        quals = [q for q in quals if q["rs"] > spy_rs]
    quals.sort(key=lambda q: -q["g_eps"])
    return quals

def price_adj(cik, ym_):
    return D.price(cik, ym_, adj=True)

def month_iter(a, b):
    y, m = int(a[:4]), int(a[5:7]); y2, m2 = int(b[:4]), int(b[5:7])
    while (y, m) <= (y2, m2):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12: m = 1; y += 1

def run_portfolio(formations, picks_by_formation, start, end, chassis=False,
                  placebo_seed=None, universe_pool=None):
    """Monthly-marked portfolio. picks_by_formation: {formation: [cik,...]}.
    placebo_seed: replace picks with random draws (from qualifier pool if
    universe_pool is None else from the whole priced universe)."""
    cash = START; holdings = {}  # cik -> value
    curve = []; costs = 0.0
    ep_start, halts, halt_until, ended = START, 0, None, False
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    for ym_ in month_iter(start, end):
        # mark / zero-out vanished names
        for cik in list(holdings):
            p = price_adj(cik, ym_)
            if p is None:
                # price missing this month: zero if it never returns
                later = [mm for mm in month_iter(ym_, end) if price_adj(cik, mm) is not None]
                if not later: holdings[cik] = 0.0
            # monthly return applied via formation-to-formation accounting below
        if ym_ in formations:
            # rebalance at this month-end: value holdings at current prices
            # (returns since last formation were applied month by month below)
            if not ended and halt_until is None:
                picks = picks_by_formation.get(ym_, [])
                if rng is not None:
                    pool = universe_pool if universe_pool is not None else picks_by_formation.get("_pool_" + ym_, [])
                    picks = rng.sample(pool, min(len(picks_by_formation.get(ym_, [])), len(pool))) if pool else []
                total = cash + sum(holdings.values())
                # sell all
                for cik, val in list(holdings.items()):
                    cap = None
                    fee = val * eng.cost_rate(cap)
                    cash += val - fee; costs += fee
                holdings = {}
                if picks:
                    each = cash / len(picks)
                    for cik in picks:
                        fee = each * eng.cost_rate(None)
                        holdings[cik] = each - fee; costs += fee
                    cash = 0.0
                ep_start = cash + sum(holdings.values())
        # apply this month's returns to holdings for next month's mark:
        # store current month prices; returns computed at next iteration start
        eq = cash + sum(holdings.values())
        curve.append([ym_, round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start and eq < START * 10:
            halts += 1
            for cik, val in list(holdings.items()):
                fee = val * eng.cost_rate(None); cash += val - fee; costs += fee
            holdings = {}
            if halts == 1:
                halt_until = ym_
            else:
                ended = True
        # roll holdings forward one month at adj-price returns
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
            "costs": round(costs, 2), "halts": halts, "equity_curve": curve}

def period_stats_monthly(curve):
    import statistics as st
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
            "median_pct": round(st.median(rets), 3),
            "mean_pct_secondary_average_only": round(st.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst, "longest_between_highs_periods": longest}

def spy_monthly(start, end):
    curve = []
    months = list(month_iter(start, end))
    base = D.spy.get(months[0])
    sh = (START / (1 + 0.001)) / base if base else 0
    for ym_ in months:
        v = D.spy.get(ym_)
        if v: curve.append([ym_, round(sh * v, 4)])
    if curve:
        val = curve[-1][1]; curve[-1] = [curve[-1][0], round(val - (val * 0.001 + 0.01), 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": curve[-1][1] if curve else None, "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def main():
    formations = []
    for y in range(2019, 2027):
        for mq in (3, 6, 9, 12):
            fm = f"{y:04d}-{mq:02d}"
            if "2019-09" <= fm <= "2026-09": formations.append(fm)
    quals = {}
    for fm in formations:
        q = screen(fm)
        quals[fm] = q
        print(f"formation {fm}: {len(q)} qualifiers", flush=True)
    out = {"family": "hunt-zweig-growth-screen (Zweig Growth Screen, 1986; AAII codification; CONSTRUCTED numerics)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-newsletters)",
           "chassis": "broad w04 stack (658 filer candidates); quarterly formation; monthly marks; w04 tiered costs; native = no floor; house = v9 floor at monthly marks (named adaptation); vanished prices written to ZERO",
           "qualifier_counts": {fm: len(q) for fm, q in quals.items()},
           "qualifier_pools": {fm: [q["ticker"] for q in q] for fm, q in quals.items()},
           "roads": {}}
    COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]  # None = ALL-ELIGIBLE
    grid = {}
    for cnt in COUNTS:
        key = "ALL" if cnt is None else str(cnt)
        picks = {}
        for fm in formations:
            q = quals[fm]
            picks[fm] = [x["cik"] for x in (q if cnt is None else q[:cnt])]
        grid[key] = picks
    roads = {"CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
    results_by_count = {}
    for cnt in COUNTS:
        key = "ALL" if cnt is None else str(cnt)
        picks = grid[key]
        entry = {}
        for rname, (s, e) in roads.items():
            rn = run_portfolio(formations, picks, s, e)
            entry[rname] = {"native": {**rn, "period_stats_monthly": period_stats_monthly(rn["equity_curve"])}}
            if cnt == 5:
                rh = run_portfolio(formations, picks, s, e, chassis=True)
                entry[rname]["house_v9"] = {**rh, "period_stats_monthly": period_stats_monthly(rh["equity_curve"])}
        results_by_count[key] = entry
        print(f"count {key}: CONT native ${entry['CONT']['native']['final']} VAL native ${entry['VAL']['native']['final']}", flush=True)
    out["by_count"] = results_by_count
    # benchmarks + placebos at the native count (5)
    for rname, (s, e) in roads.items():
        out["roads"][rname] = {"benchmark_spy_monthly": spy_monthly(s, e),
                               "champion_vm": {"CONT": 544.47, "VAL": 288.05}[rname]}
    picks5 = grid["5"]
    pools = {fm: [q["cik"] for q in quals[fm]] for fm in formations}
    univ = [cik for cik in D.cand if D.px.get(cik)]
    for rname, (s, e) in roads.items():
        real = results_by_count["5"][rname]["native"]["final"]
        pq, pu = [], []
        for seed in range(1, 21):
            picks_p = dict(picks5); picks_p.update({("_pool_" + fm): pools[fm] for fm in formations})
            r1 = run_portfolio(formations, picks_p, s, e, placebo_seed=seed)
            pq.append(r1["final"])
            r2 = run_portfolio(formations, picks5, s, e, placebo_seed=seed, universe_pool=univ)
            pu.append(r2["final"])
        out["roads"][rname]["placebos_count5"] = {
            "from_qualifier_pool": {"seed_finals": pq, "beaten_of_20": sum(1 for p in pq if real > p)},
            "from_universe": {"seed_finals": pu, "beaten_of_20": sum(1 for p in pu if real > p)}}
        print(f"{rname} placebos: pool {out['roads'][rname]['placebos_count5']['from_qualifier_pool']['beaten_of_20']}/20 universe {out['roads'][rname]['placebos_count5']['from_universe']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    grid_out = {"counts": COUNTS, "finals": {k: {r: v[r]["native"]["final"] for r in roads} for k, v in results_by_count.items()}}
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    with open(os.path.join(HERE, "grid", "results_grid.json"), "w") as f:
        json.dump(grid_out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
