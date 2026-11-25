#!/usr/bin/env python3
"""V13 best-rules run — Mama Bear. Spec frozen in ../BEST-RULES-SPEC.md.
My rules: published top-3 / 105d momentum / equal thirds, QUARTERLY
cadence, NO floor. Published form re-run on identical data at monthly
cadence for the internal comparison. Placebos: 20-seed random top-3
twins at quarterly cadence. Benchmarks: SPY buy-hold, static equal-
weight mix of all 9 (quarterly rebalanced). Costs: program standard
0.10%/side + $0.01/sell order (engine).
Universe (proxy fence in spec): SPY*=VONE, IWM*=VIOO, TLT*=VGLT,
others are the author's own tickers.
"""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from engine import simulate, period_stats, prices, aligned, ret_td, ROADS

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
U = ["SPY", "IWM", "VEA", "VWO", "VNQ", "PDBC", "IAU", "TLT", "SHV"]
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
V12_NATIVE = {"LONG": 308.94, "DECADE": 183.15, "CONT": 164.22, "VAL": 138.11}

def scores(date):
    out = {}
    for t in U:
        r = ret_td(t, date, 105)
        if r is not None: out[t] = r
    return out

def mama(date, rng=None):
    s = scores(date)
    if not s: return {}
    top = sorted(s, key=s.get, reverse=True)[:3]
    return {t: 1.0 / len(top) for t in top}

def mama_placebo(date, rng=None):
    s = scores(date)
    if not s: return {}
    picks = rng.sample(sorted(s), min(3, len(s)))
    return {t: 1.0 / len(picks) for t in picks}

def static_mix(date, rng=None):
    elig = [t for t in U if ret_td(t, date, 105) is not None]
    if not elig: return {}
    return {t: 1.0 / len(elig) for t in elig}

def spy_final(start, end):
    s = prices("SPY")
    w = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return round(100.0 * float(w.iloc[-1] / w.iloc[0]), 2)

def main():
    out = {"family": "catalog-taa-muscular-mama-bear",
           "spec": "top-3 105d momentum equal-thirds, quarterly cadence, no floor; proxies SPY/IWM/TLT for VONE/VIOO/VGLT",
           "roads": {}, "curves": {}}
    for road, (st, en) in ROADS.items():
        eq_mine, info_mine = simulate(st, en, mama, house=False, rebalance_months=3)
        eq_pub, info_pub = simulate(st, en, mama, house=False, rebalance_months=1)
        eq_mix, info_mix = simulate(st, en, static_mix, house=False, rebalance_months=3)
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            eqp, infop = simulate(st, en, mama_placebo, house=False, rng=rng, rebalance_months=3)
            finals.append(round(infop["final"], 2))
        finals.sort()
        out["roads"][road] = {
            "my_rules": {"final": round(info_mine["final"], 2), "periods": period_stats(eq_mine)},
            "published_form_same_data": {"final": round(info_pub["final"], 2), "periods": period_stats(eq_pub)},
            "v12_published_final_author_tickers": V12_NATIVE[road],
            "static_mix_quarterly": {"final": round(info_mix["final"], 2), "periods": period_stats(eq_mix)},
            "spy_buyhold_same_data": spy_final(st, en),
            "champion_VM": CHAMP[road],
            "placebo_20seed": {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                               "my_rules_beats_of_20": int(sum(1 for f in finals if info_mine["final"] > f)),
                               "finals": finals},
        }
        out["curves"][road] = {str(k.date()): round(float(v), 4) for k, v in eq_mine.items()}
        r = out["roads"][road]
        print(road, "mine", r["my_rules"]["final"], "pub", r["published_form_same_data"]["final"],
              "mix", r["static_mix_quarterly"]["final"], "spy", r["spy_buyhold_same_data"],
              "placebo_med", r["placebo_20seed"]["median"], "beats", r["placebo_20seed"]["my_rules_beats_of_20"], flush=True)
    json.dump(out, open(os.path.join(FOLDER, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
