#!/usr/bin/env python3
"""hunt-yield-curve-timer — CONSTRUCTED binary timer from Harvey (1986) /
Estrella-Mishkin (1996/98): monthly check at last trading day close;
FRED T10Y3M spread < 0 -> cash for next month; >= 0 -> 100% SPY.
Fill next trading day open. Native no floor; house v9 chassis.
Coins: same monthly spread state applied as an external macro gate on
BTC and per-coin (spec (e)). FRED used as a data input to a backtest;
only the derived signal series is stored (signal_series.csv)."""
import csv, io, json, os, random, statistics, urllib.request
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_core.py")).read())

HERE = os.path.dirname(os.path.abspath(__file__))

def fetch_t10y3m():
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y3M"
    raw = urllib.request.urlopen(url, timeout=60).read().decode()
    rows = []
    for r in csv.DictReader(io.StringIO(raw)):
        try: rows.append((r["observation_date"], float(r["T10Y3M"])))
        except Exception: pass
    rows.sort()
    return rows

def monthly_targets(bars, spread):
    """check dates = last bar of each month; state = 1 if spread>=0 else 0,
    spread = last observation on/before the check date."""
    checks = {}
    for b in bars: checks[b["d"][:7]] = b["d"]
    targets = {}
    si = 0
    for m in sorted(checks):
        d = checks[m]
        while si + 1 < len(spread) and spread[si+1][0] <= d: si += 1
        if spread[si][0] <= d:
            targets[d] = 1 if spread[si][1] >= 0 else 0
    return targets

def shifted_targets(bars, targets, seed):
    dates = sorted(targets)
    vals = [targets[d] for d in dates]
    rng = random.Random(seed)
    k = rng.randrange(1, len(vals))
    vals = vals[k:] + vals[:k]
    return dict(zip(dates, vals))

def run_asset(bars, spread, cost, sell_fee, roads, bench):
    targets = monthly_targets(bars, spread)
    out = {"data_range": f"{bars[0]['d']} -> {bars[-1]['d']}",
           "n_monthly_checks": len(targets),
           "inversion_months_total": sum(1 for v in targets.values() if v == 0),
           "targets": targets, "roads": {}}
    for name, (s, e) in roads.items():
        s0 = s or bars[0]["d"]
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate_targets(bars, targets, s0, e, cost, sell_fee, chassis=ch)
            rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
        bh = buy_hold(bars, s, e, cost, sell_fee)
        rec["benchmark_hold"] = {"name": bench, "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")}
        pf = []
        for seed in range(1, 21):
            st = shifted_targets(bars, targets, seed)
            # restrict shift to road segment is approximated by full-series shift (documented)
            r = simulate_targets(bars, st, s0, e, cost, sell_fee)
            pf.append(r["final"])
        rec["placebo_native"] = {"seed_finals": pf,
                                 "beaten_of_20": sum(1 for p in pf if rec["native"]["final"] > p),
                                 "design": "circular shift of the monthly in/out state series (20 seeds); full-series shift, road read from the shifted series"}
        out["roads"][name] = rec
    return out, targets

def main():
    spread = fetch_t10y3m()
    with open(os.path.join(HERE, "signal_series.csv"), "w") as f:
        f.write("date,t10y3m\n")
        for d, v in spread: f.write(f"{d},{v}\n")
    out = {"family": "hunt-yield-curve-timer (10Y-3M binary timer, CONSTRUCTED from Harvey 1986 / Estrella-Mishkin)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-odd)",
           "honesty_label": "CONSTRUCTED / candidate-grade ceiling — the sources published a recession probability model, never a portfolio",
           "chassis": "$100; stocks 0.10%/side + $0.01 sell fee; crypto 0.60%/side; native = no floor; house = v9 chassis",
           "holdings_grid": "NOT-APPLICABLE — SPY timer, no selection",
           "spread_range": f"{spread[0][0]} -> {spread[-1][0]}"}
    spy = load_stock("SPY")
    st, tg = run_asset(spy, spread, STK_COST, STK_SELL_FEE, ROADS, "SPY buy-and-hold")
    for name, rec in st["roads"].items():
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        print(f"SPY {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    out["stocks_spy"] = st
    # episodes: contiguous cash stretches in the SPY target series
    eps = []
    cur = None
    for d in sorted(tg):
        if tg[d] == 0 and cur is None: cur = d
        if tg[d] == 1 and cur is not None: eps.append([cur, d]); cur = None
    if cur is not None: eps.append([cur, "still inverted at series end"])
    out["inversion_episodes_spy_checks"] = eps
    print("inversion episodes:", eps, flush=True)
    # coins: BTC detail + per-coin summary on FULL/CONT/VAL
    croads = {"FULL": (None, "2026-11-20"), "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
    btc = load_coin("BTC")[0]
    bt, _ = run_asset(btc, spread, CRY_COST, 0.0, croads, "BTC buy-and-hold")
    out["coins_btc"] = bt
    for name, rec in bt["roads"].items():
        print(f"BTC {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    per_coin = {}
    agg = {name: {"native": [], "hold": [], "beat": 0, "n": 0} for name in croads}
    for sym in coin_universe():
        bars, proxy = load_coin(sym)
        if bars is None:
            per_coin[sym] = {"status": "NO FREE DATA in program PIT cache (named closure class)"}; continue
        t2 = monthly_targets(bars, spread)
        rec = {}
        for name, (s, e) in croads.items():
            rn = simulate_targets(bars, t2, s or bars[0]["d"], e, CRY_COST, 0.0)
            bh = buy_hold(bars, s, e, CRY_COST, 0.0)
            if not rn or not bh: continue
            rec[name] = {"native": rn["final"], "hold": bh["final"]}
            a = agg[name]; a["native"].append(rn["final"]); a["hold"].append(bh["final"]); a["n"] += 1
            if rn["final"] > bh["final"]: a["beat"] += 1
        per_coin[sym] = rec
    out["coins_per_coin"] = per_coin
    out["coins_summary"] = {name: {"coins": a["n"], "native_median": round(statistics.median(a["native"]), 2),
                                   "hold_median": round(statistics.median(a["hold"]), 2),
                                   "share_beating_own_hold_pct": round(100.0*a["beat"]/a["n"], 1)}
                            for name, a in agg.items() if a["n"]}
    print("COIN SUMMARY:", out["coins_summary"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
