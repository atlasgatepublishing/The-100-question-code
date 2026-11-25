#!/usr/bin/env python3
"""V13 best-rules run for hunt-ehlers-sinewave. Spec frozen in
BEST-RULES-SPEC.md BEFORE this run. Reuses the v12 chassis (simulate,
buy_hold, period_stats, hilbert_engine, load_pxfull) read-only from the
v12 folder; only the signal/state machine is new, exactly as spec'd:
cycle mode (period 8-40 for 5 bars) = Sinewave crosses; trend mode =
hold SPY iff close > 200-day SMA; no floor; no 20-bar cap."""
import importlib.util, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-ehlers-sinewave/run_sinewave.py")
spec = importlib.util.spec_from_file_location("v12chassis", V12)
ch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB = {"LONG": 185.77, "DECADE": 170.61, "CONT": 198.71, "VAL": 134.29}  # v12 native finals


def signal_fn(bars):
    n = len(bars)
    eng = ch.hilbert_engine(bars)
    Period, Phase = eng["Period"], eng["Phase"]
    closes = [b["c"] for b in bars]
    sine = [math.sin(math.radians(Phase[i])) for i in range(n)]
    lead = [math.sin(math.radians(Phase[i] + 45.0)) for i in range(n)]
    sma = [None] * n
    run = 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= 200:
            run -= closes[i - 200]
        if i >= 199:
            sma[i] = run / 200.0
    targets = [False] * n
    pos = False
    for i in range(n):
        cyc = i >= 54 and all(8.0 <= Period[j] <= 40.0 for j in range(i - 4, i + 1))
        if cyc:
            if i >= 51:
                cross_up = lead[i] > sine[i] and lead[i - 1] <= sine[i - 1]
                cross_dn = lead[i] < sine[i] and lead[i - 1] >= sine[i - 1]
                if not pos and cross_up:
                    pos = True
                elif pos and cross_dn:
                    pos = False
        else:
            if sma[i] is not None:
                pos = closes[i] > sma[i]
        targets[i] = pos
    return targets


def main():
    spy = ch.load_pxfull("SPY")
    tgt = signal_fn(spy)
    out = {"family": "hunt-ehlers-sinewave (v13 best rules)",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "costs": "stocks 0.10%/side + $0.01 sell fee",
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = ch.simulate(spy, tgt, s, e, ch.STK_COST, ch.STK_SELL_FEE, chassis=False)
        bh = ch.buy_hold(spy, s, e, ch.STK_COST, ch.STK_SELL_FEE)
        finals = []
        for seed in range(1, 21):
            pr = ch.simulate(spy, tgt, s, e, ch.STK_COST, ch.STK_SELL_FEE,
                             chassis=False, shift_seed=seed)
            finals.append(pr["final"])
        rec = {"my_rules": {**r, "period_stats": ch.period_stats(r["equity_curve"], "monthly")},
               "benchmark_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": ch.period_stats(bh["equity_curve"], "monthly")},
               "placebo": {"seed_finals": finals,
                           "beaten_of_20": sum(1 for p in finals if r["final"] > p),
                           "design": "circular shift of the daily in/out state series within the road (20 seeds)"},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "published_v12_native": PUB[name]}
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} (DD {r['max_dd_pct']}%, costs ${r['costs']}, "
              f"orders {r['orders']}, inv {r['invested_pct']}%, placebos {rec['placebo']['beaten_of_20']}/20) "
              f"| published ${PUB[name]} | hold ${bh['final']} | champ ${CHAMP[name]}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
