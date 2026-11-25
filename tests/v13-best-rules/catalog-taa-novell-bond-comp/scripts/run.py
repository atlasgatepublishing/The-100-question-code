#!/usr/bin/env python3
"""V13 best-rules run — Novell Bond-COMP (constructed).
Forms: published (v12 native, binary) vs mine (graded 50% defensive sizing,
no floor, monthly). Benchmarks: AGG buy-hold (duration-matched bond
control), static 50/50 mix of the two baskets, SPY buy-hold.
Placebos: 20-seed shuffled-decision timing twins of MY form's decisions.
Costs/engine identical to v12 chassis."""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from engine import simulate, period_stats, month_ends, price_at, ROADS
import families as F

OUT = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-novell-bond-comp")

def graded(date, rng=None):
    """My sizing: defensive episodes hold 50% defensive + 50% credit."""
    w = F.bondcomp(date, rng)
    if w and set(w) <= set(F.DEFENSIVE):
        cred = F._ew(F.CREDIT, date)
        return {**{t: 0.5 * x for t, x in w.items()},
                **{t: 0.5 * x for t, x in cred.items()}}
    return w

def static_mix(date, rng=None):
    cred = F._ew(F.CREDIT, date); defe = F._ew(F.DEFENSIVE, date)
    return {**{t: 0.5 * x for t, x in defe.items()},
            **{t: 0.5 * x for t, x in cred.items()}}

def buyhold(ticker):
    return lambda date, rng=None: {ticker: 1.0}

def cal_year_ret(eq, year):
    y = eq[eq.index.year == year]
    if len(y) == 0: return None
    prev = eq[eq.index < y.index[0]]
    if len(prev) == 0: return None
    return round(float(y.iloc[-1] / prev.iloc[-1] - 1.0) * 100, 2)

def main():
    forms = {"mine": graded, "published": F.bondcomp,
             "agg_buyhold": buyhold("AGG"), "static_mix": static_mix,
             "spy_buyhold": buyhold("SPY")}
    dec = {d: graded(d, None) for d in month_ends("2009-01-01", "2026-11-20")}
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        curves = {}
        for name, fn in forms.items():
            eq, info = simulate(st, en, fn, house=False)
            res[name] = {"final": round(info["final"], 2), "periods": period_stats(eq),
                         "ret_2022_pct": cal_year_ret(eq, 2022)}
            curves[name] = {str(k.date()): round(float(v), 4) for k, v in eq.items()}
            print(road, name, res[name]["final"], "dd", res[name]["periods"].get("max_drawdown_pct"), flush=True)
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            keys = list(dec.keys()); vals = [dec[k] for k in keys]
            rng.shuffle(vals)
            mp = dict(zip(keys, vals))
            eq, info = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}), house=False)
            finals.append(round(info["final"], 2))
        finals.sort()
        res["placebo_shuffled_timing"] = {"median": finals[10], "p90": finals[17],
            "max": finals[-1], "min": finals[0],
            "mine_beats_of_20": int(sum(1 for f in finals if res["mine"]["final"] > f)),
            "published_beats_of_20": int(sum(1 for f in finals if res["published"]["final"] > f))}
        res["curves"] = curves
        out[road] = res
    json.dump(out, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
