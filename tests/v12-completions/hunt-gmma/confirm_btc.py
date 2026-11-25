#!/usr/bin/env python3
"""Confirmation splits for GMMA Form A on BTC (CONFIRMATION RULE):
FULL window split into two different-year halves; plus ETH and pooled
coin summary pulled from results.json. Simulation only."""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_gmma import load_coin, form_a_state, form_b_state, simulate, buy_hold, CCOST
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(HERE, "results.json")))

out = {}
for sym in ("BTC", "ETH", "LTC"):
    s = load_coin(sym)
    states = {"A": form_a_state(s["c"]), "B": form_b_state(s)}
    i1 = len(s["c"]) - 1
    halves = {}
    # split at 2021-01-01
    split = next(i for i, dv in enumerate(s["d"]) if dv >= date(2021, 1, 1).toordinal())
    for name, (a, b) in {"2015-2020": (60, split - 1), "2021-2026": (split, i1)}.items():
        bh = buy_hold(s, a, b, CCOST, 0.0)
        cell = {"hold_final": bh["final"]}
        for f in ("A", "B"):
            r = simulate(s, states[f], a, b, False, CCOST, 0.0)
            cell[f] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "orders": r["orders"]}
        halves[name] = cell
    out[sym] = halves
    print(sym, json.dumps(halves))

# pooled coin summary from results.json
coins = res["coins"]
for w in ("FULL", "RECENT2023"):
    for form in ("A", "B"):
        for rs in ("native", "house"):
            finals, holds, beats = [], [], 0
            for sym, rec in coins.items():
                if w in rec:
                    finals.append(rec[w][f"{form}_{rs}"]["final"])
                    holds.append(rec[w]["hold_final"])
                    beats += 1 if rec[w][f"{form}_{rs}"]["beat_hold"] else 0
            if finals:
                print(f"coins {w} {form}/{rs}: n={len(finals)} median={statistics.median(finals):.2f} "
                      f"mean={statistics.mean(finals):.2f} median_hold={statistics.median(holds):.2f} "
                      f"beat_hold={beats}/{len(finals)}")
for form in ("A", "B"):
    pl = res["coin_placebos_FULL_pooled"].get(form, [])
    if pl:
        print(f"coin placebo {form}: median={statistics.median(pl):.2f} min={min(pl)} max={max(pl)} "
              f"real_pooled_mean_needed")
    finals = [rec["FULL"][f"{form}_native"]["final"] for rec in coins.values() if "FULL" in rec]
    print(f"coin {form} native FULL pooled mean={statistics.mean(finals):.2f} median={statistics.median(finals):.2f}")

# pooled stock summary
stocks = res["stocks"]
for rname in ("LONG", "DECADE", "CONT", "VAL"):
    for form in ("A", "B"):
        for rs in ("native", "house"):
            finals, beats = [], 0
            for sym, rec in stocks.items():
                if rname in rec:
                    finals.append(rec[rname][f"{form}_{rs}"]["final"])
                    beats += 1 if rec[rname][f"{form}_{rs}"]["beat_hold"] else 0
            if finals:
                print(f"stocks {rname} {form}/{rs}: n={len(finals)} median={statistics.median(finals):.2f} "
                      f"mean={statistics.mean(finals):.2f} beat_own_hold={beats}/{len(finals)}")
for form in ("A", "B"):
    pl = res["stock_placebos_LONG_pooled"].get(form, [])
    finals = [rec["LONG"][f"{form}_native"]["final"] for rec in stocks.values() if "LONG" in rec]
    if pl and finals:
        print(f"stock placebo LONG {form}: median={statistics.median(pl):.2f} min={min(pl)} max={max(pl)} "
              f"real_pooled_mean={statistics.mean(finals):.2f} beats={sum(1 for x in pl if statistics.mean(finals) > x)}/20")

json.dump(out, open(os.path.join(HERE, "confirmation.json"), "w"), indent=1)
print("wrote confirmation.json")
