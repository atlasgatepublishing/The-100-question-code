#!/usr/bin/env python3
"""
VALUE + MOMENTUM (HONEST, PLAIN FLOOR) — WALK-FORWARD + FULL-WINDOW PLACEBO
Terry's AI stock app. Simulation only.

The missing judgment on the program's biggest honest number. The
plain-floor continuous run (value-momentum-plainfloor.py) finished at
$544.47 on $100 over 2019-01-02 -> 2026-11-20, but that window was never
placebo-judged under the plain floor and never year-tested. This study
supplies both, using the chassis-walkforward methodology
(chassis-walkforward.md):

  (1) WALK-FORWARD BY YEAR — frozen engine, fresh $100 pot each calendar
      year 2020-2026 (Jan 1 -> Dec 31; 2026 -> Nov 20), scored against
      SPY's net return over the same calendar window. Plus the
      continuous stitched run 2019 -> 2026 at $100.
  (2) PLACEBO ON THE CONTINUOUS WINDOW — identical machinery, plain
      -15% floor, but at each quarterly selection 5 names are drawn
      RANDOMLY from the scored pool (20 seeds: 1..20, the PLACEBO_SEEDS
      set defined in value-momentum-plainfloor.py). Distribution of
      finals (median, quartiles, best, worst), halt count, and the
      ranked strategy's percentile.

Engine: imported verbatim from value-momentum-plainfloor.py, which is
itself value-momentum-honest.py with ONLY the protection rule changed
(ladder removed, plain -15% floor: $85 on the $100 pot). Nothing here
re-tunes anything: honest 30-name universe (value-momentum-honest
UNIVERSE), book-to-market + 12-1 momentum percentile-rank average,
quarterly top-5 equal weight, point-in-time EDGAR with the ~18-month
filed-freshness gate, XOM CIK override 34088, costs 0.10%/side +
$0.01/sell.

Data: same caches as the parent studies (SEC EDGAR companyfacts in
./data, Yahoo prices in ./value-momentum-honest-data), read-only.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(HERE, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

FULL = ("2019-01-02", "2026-11-20")
START_CASH = 100.0
FLOOR0 = 85.0          # plain -15% floor on $100, no ladder, ever
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))


def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "final": round(r["final"], 2)}


def main():
    pb, equity_rows, shares_rows = build_inputs()
    out = {"engine": "value-momentum-honest + plain -15% floor (ladder removed)",
           "universe": E.UNIVERSE, "pot": START_CASH, "floor": FLOOR0}

    # ---- (0) continuous stitched run — must reproduce $544.47
    ws, we = FULL
    r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                  FLOOR0, LADDER, label="STITCHED $100 PLAINFLOOR", quiet=True)
    spy_st, _ = E.spy_net(pb, ws, we, START_CASH)
    stitched = curve_stats(r)
    stitched.update({"start": ws, "end": we, "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
                     "spy_net_final": round(spy_st, 2),
                     "spy_return_pct": round(spy_st / START_CASH * 100 - 100, 2)})
    out["stitched"] = stitched
    print(f"STITCHED {ws}->{we}: final=${r['final']:,.2f} ({stitched['return_pct']:+.2f}%) "
          f"maxDD={stitched['max_drawdown_pct']}% orders={stitched['orders']} "
          f"costs=${stitched['costs']} halted={r['halted']} | SPY net=${spy_st:,.2f}", flush=True)

    # ---- (1) walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = E.run_pot(pb, equity_rows, shares_rows, fs, fe, START_CASH,
                       FLOOR0, LADDER, label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe,
               "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: V+M ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) "
              f"beat={row['beat_spy']} maxDD={row['max_drawdown_pct']}% "
              f"orders={row['orders']} halted={row['halted']}", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    # ---- (2) placebo distribution on the continuous window, plain floor
    finals = []
    placebo_rows = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, placebo_rng=rng,
                       label=f"PLACEBO seed {seed}", quiet=True)
        finals.append(pr["final"])
        placebo_rows.append({"seed": seed, "final": round(pr["final"], 2),
                             "halted": pr["halted"], "orders": len(pr["trades"]),
                             "costs": round(pr["costs"], 2)})
        print(f"PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} halted={pr['halted']} "
              f"orders={len(pr['trades'])}", flush=True)
    srt = sorted(finals)
    ranked = r["final"]
    below = sum(1 for f in finals if f < ranked)
    ties = sum(1 for f in finals if f == ranked)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    dist = {"seeds": PLACEBO_SEEDS,
            "median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in placebo_rows if p["halted"]),
            "ranked_final": round(ranked, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below,
            "rows": placebo_rows}
    out["placebo_full_window"] = dist
    print(f"PLACEBO DIST: median=${dist['median']:,.2f} Q1=${dist['q1']:,.2f} "
          f"Q3=${dist['q3']:,.2f} best=${dist['best']:,.2f} worst=${dist['worst']:,.2f} "
          f"halted={dist['halted_count']}/20 | RANKED ${ranked:,.2f} = "
          f"{dist['ranked_percentile']}th percentile (beat {below}/20 seeds)", flush=True)

    with open(os.path.join(HERE, "vm-walkforward-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
