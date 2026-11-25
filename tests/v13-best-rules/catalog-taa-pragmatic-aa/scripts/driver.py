#!/usr/bin/env python3
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import simulate, period_stats, month_ends, ROADS, SPY_FINALS, PUBLISHED, CHAMPION
from strategy import make_target, static_mix

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-pragmatic-aa")

def decisions_of(fn):
    return {d: fn(d, None) for d in month_ends("2009-01-01", "2026-11-20")}

def run():
    forms = {
        "best": make_target(use_gate=False, use_guard=True),
        "variant_G_gate": make_target(use_gate=True, use_guard=True),
        "variant_T_noguard": make_target(use_gate=False, use_guard=False),
        "static_mix": static_mix,
    }
    dec_best = decisions_of(forms["best"])
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        for name, fn in forms.items():
            eq, info = simulate(st, en, fn)
            e = {"final": round(info["final"], 2), "periods": period_stats(eq)}
            if road == "CONT" and name == "best":
                e["curve"] = {str(k.date()): round(float(v), 4) for k, v in eq.items()}
            res[name] = e
        # 20-seed shuffled-timing placebos on headline decisions
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            keys = list(dec_best.keys()); vals = [dec_best[k] for k in keys]
            rng.shuffle(vals)
            mp = dict(zip(keys, vals))
            eq, info = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}))
            finals.append(round(info["final"], 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "finals_sorted": finals,
                          "best_beats_of_20": int(sum(1 for f in finals if res["best"]["final"] > f))}
        res["spy_final"] = SPY_FINALS[road]
        res["published_final"] = PUBLISHED[road]
        res["champion_final"] = CHAMPION[road]
        out[road] = res
        print(road, "best", res["best"]["final"], "DD", res["best"]["periods"]["max_drawdown_pct"],
              "| G", res["variant_G_gate"]["final"], "| T", res["variant_T_noguard"]["final"],
              "| static", res["static_mix"]["final"], "| placebo_med", res["placebo"]["median"],
              "beats", res["placebo"]["best_beats_of_20"], flush=True)
    json.dump(out, open(os.path.join(BASE, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    run()
