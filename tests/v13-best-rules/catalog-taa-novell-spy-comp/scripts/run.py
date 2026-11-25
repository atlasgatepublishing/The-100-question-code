#!/usr/bin/env python3
"""v13 best-rules run — Novell SPY-COMP.
Order: (1) validate plumbing by re-running the v12 any-1 construction;
(2) run MY RULES (>=3 majority trigger), SPY buy-hold, static mix;
(3) 20-seed shuffled-decision timing placebos for MY RULES.
Writes results.json in the family folder. Spec frozen before this ran.
"""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from engine import simulate, period_stats, month_ends, ROADS, SPY_FINALS
import signals as S

FOLDER = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-novell-spy-comp")
V12_FINALS = {"LONG": 539.50, "DECADE": 228.34, "CONT": 192.45, "VAL": 147.62}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


def decisions_of(fn):
    mes = month_ends("2009-01-01", "2026-11-20")
    return {d: fn(d, None) for d in mes}


def exposure(dec, st, en):
    """Share of decision months armed (v13) and share of months in IEF."""
    sel = {d: w for d, w in dec.items() if pd.Timestamp(st) <= d <= pd.Timestamp(en)}
    n = len(sel)
    ief = sum(1 for w in sel.values() if w.get("IEF", 0) > 0.5)
    return {"months": n, "share_months_ief": round(ief / n, 3) if n else None}


def main():
    out = {"validation": {}, "roads": {}}
    dec13 = decisions_of(S.spycomp_v13)
    for road, (st, en) in ROADS.items():
        res = {}
        # validation: v12 any-1 form on identical plumbing
        eq, info = simulate(st, en, S.spycomp_v12, house=False)
        res["v12_form"] = {"final": round(info["final"], 2),
                           "expected_v12": V12_FINALS[road],
                           "match": abs(round(info["final"], 2) - V12_FINALS[road]) < 0.01,
                           "periods": period_stats(eq)}
        # my rules
        eq, info = simulate(st, en, S.spycomp_v13, house=False)
        res["my_rules"] = {"final": round(info["final"], 2), "periods": period_stats(eq),
                           "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()},
                           "exposure": exposure(dec13, st, en)}
        # controls
        eq, info = simulate(st, en, S.spy_hold, house=False)
        res["spy_buyhold"] = {"final": round(info["final"], 2), "expected": SPY_FINALS[road],
                              "periods": period_stats(eq)}
        eq, info = simulate(st, en, S.static_mix, house=False)
        res["static_mix_75_25"] = {"final": round(info["final"], 2), "periods": period_stats(eq)}
        # placebos: shuffled decisions of MY RULES, 20 seeds (v12 method)
        keys = list(dec13.keys()); vals = [dec13[k] for k in keys]
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            v = vals[:]; rng.shuffle(v)
            mp = dict(zip(keys, v))
            eqp, infop = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}), house=False)
            finals.append(round(infop["final"], 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "all_finals": finals,
                          "my_rules_beats_of_20": int(sum(1 for f in finals if res["my_rules"]["final"] > f))}
        res["champion_vm"] = CHAMPION[road]
        out["roads"][road] = res
        out["validation"][road] = res["v12_form"]["match"]
        print(road, "v12form", res["v12_form"]["final"], "match", res["v12_form"]["match"],
              "| my", res["my_rules"]["final"], "dd", res["my_rules"]["periods"].get("max_drawdown_pct"),
              "| spy", res["spy_buyhold"]["final"], "| mix", res["static_mix_75_25"]["final"],
              "| placebo_med", res["placebo"]["median"], "beats", res["placebo"]["my_rules_beats_of_20"],
              "| ief_share", res["my_rules"]["exposure"]["share_months_ief"], flush=True)
    json.dump(out, open(os.path.join(FOLDER, "results.json"), "w"), indent=1)
    print("WROTE results.json; validation:", out["validation"])


if __name__ == "__main__":
    main()
