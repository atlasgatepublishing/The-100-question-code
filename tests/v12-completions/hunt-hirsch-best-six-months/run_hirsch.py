#!/usr/bin/env python3
"""Hirsch Best Six Months (Stock Trader's Almanac) — frozen form.
Invested Nov 1 -> Apr 30, cash May 1 -> Oct 31, on DIA (the Almanac's
DJIA record; DIA is its tracker, mapping labeled CONSTRUCTED). Switch
at the close of the prior trading day so the position state matches
the calendar month (frozen micro-convention). Trades at close,
program costs, cash 0%. NATIVE no floor; HOUSE v9 floor chassis.
Placebos: 20 seeds — the same 6-month window rotated by a random
non-zero month offset. Per-period distribution at semiannual tempo
(the system's native tempo) plus monthly. Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate, buy_hold, period_stats, ROADS, CHAMP, SPYREF

HERE = os.path.dirname(os.path.abspath(__file__))
bars = load_bars(os.path.join(HERE, "data", "DIA.json"))

def build_state(offset=0):
    """state[i]=1 iff the return day i+1 falls in an invested month.
    Invested months: Nov..Apr rotated by `offset` months."""
    inv = set()
    for k in range(6):
        m = (11 + offset + k - 1) % 12 + 1
        inv.add(m)
    st = []
    for i, b in enumerate(bars):
        nxt = bars[i + 1]["d"] if i + 1 < len(bars) else b["d"]
        st.append(1 if int(nxt[5:7]) in inv else 0)
    return st

def main():
    out = {"family": "hunt-hirsch-best-six-months", "vehicle": "DIA (DJIA tracker)",
           "roads": {}}
    st = build_state()
    for road, (s, e) in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = simulate(bars, st, s, e, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_semiannual"] = period_stats(r["curve"], "H")
            ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["dia_buy_hold"] = buy_hold(bars, s, e)
        ent["champion_vm"] = CHAMP[road]; ent["spy_reference_program"] = SPYREF[road]
        out["roads"][road] = ent
        print(road, "native", ent["native"]["final"], "house", ent["house"]["final"], "dia bh", ent["dia_buy_hold"])
    out["placebos"] = {}
    for road in ("LONG", "VAL"):
        s, e = ROADS[road]; finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); off = rng.randint(1, 11)
            finals.append(simulate(bars, build_state(off), s, e, "native")["final"])
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
