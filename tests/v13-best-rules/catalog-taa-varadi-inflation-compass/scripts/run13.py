#!/usr/bin/env python3
"""V13 Best-Rules run: Varadi Inflation Compass.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Only change vs v12 published form: 'rising' = majority vote (>=2 of 3) over
20/60/120-trading-day lookbacks, for both T5YIE and SIEI. Everything else —
2% gate, OR structure, SPY-vs-200d growth filter, regime map, monthly
cadence, single-sector all-in, program costs, t+1 execution — identical.
No floor (native rulebook)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine
from engine import (Panel, load_sector, load_fred, cadence_days, simulate,
                    period_stats, ROADS, SPY_REF, CHAMP)
from datetime import date

OUT = os.path.dirname(HERE)
T5YIE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/"
    "catalog-taa-varadi-inflation-compass/data/t5yie.csv")

POS = ["XLE", "XLF", "XLI", "XLB"]; NEG = ["XLP", "XLV", "XLU"]
REGIME_MAP = {("u", "u"): "XLE", ("u", "d"): "XLK",
              ("d", "u"): "XLP", ("d", "d"): "XLU"}
HOLDABLE = ["XLK", "XLE", "XLP", "XLU"]
LOOKBACKS = (20, 60, 120)

def build_panel():
    p = Panel(load_sector("SPY"))
    ds, cs = load_sector("SPY"); p.series["SPY"] = cs[:]
    for s in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]:
        p.add(s, load_sector(s))
    p.add("T5YIE", load_fred(T5YIE))
    return p

def siei_ratio(p, i):
    if i < 0: return None
    pos = [p.close(s, i) for s in POS]; neg = [p.close(s, i) for s in NEG]
    if any(v is None for v in pos + neg): return None
    return (sum(pos) / len(pos)) / (sum(neg) / len(neg))

def rising_vote(values_now, values_then):
    """values_then: list aligned with LOOKBACKS; majority strictly-greater."""
    if values_now is None or any(v is None for v in values_then): return None
    return sum(1 for v in values_then if values_now > v) >= 2

def regime_at(p, i):
    t = p.close("T5YIE", i)
    t_then = [p.close("T5YIE", i - n) for n in LOOKBACKS]
    r = siei_ratio(p, i)
    r_then = [siei_ratio(p, i - n) for n in LOOKBACKS]
    tv = rising_vote(t, t_then); rv = rising_vote(r, r_then)
    if t is None or tv is None or rv is None: return None
    infl_up = t > 2.0 and (tv or rv)
    sma = p.sma("SPY", i, 200); c = p.close("SPY", i)
    if sma is None or c is None: return None
    g = "u" if c > sma else "d"
    return (g, "u" if infl_up else "d")

def compass_factory(p):
    def fn(i):
        reg = regime_at(p, i)
        if reg is None: return {}
        return {REGIME_MAP[reg]: 1.0}
    return fn

def static_mix_final(p, idx):
    tot = 0.0
    for s in HOLDABLE:
        a, b = p.close(s, idx[0]), p.close(s, idx[-1])
        if a and b: tot += 25.0 * b / a
    return round(tot, 2)

def spy_price_final(p, idx):
    return round(100.0 * p.close("SPY", idx[-1]) / p.close("SPY", idx[0]), 2)

def occupancy(p, idx, dec):
    counts = {}
    for i in idx:
        if i in dec:
            reg = regime_at(p, i)
            if reg is not None:
                k = f"growth-{reg[0]}/infl-{reg[1]}->{REGIME_MAP[reg]}"
                counts[k] = counts.get(k, 0) + 1
    return counts

def run_window(p, dec, a, b):
    idx = [i for i, d in enumerate(p.dates) if a <= d <= b]
    fn = compass_factory(p)
    r = simulate(p, idx, dec, fn, rulebook="native")
    return idx, r

def main():
    p = build_panel()
    dec = cadence_days(p.dates, "monthly")
    ridx = engine.road_indices(p, ROADS)
    out = {"family": "catalog-taa-varadi-inflation-compass",
           "program": "v13-best-rules",
           "signal_change": "rising = majority vote >=2 of 20/60/120d lookbacks (T5YIE and SIEI); all else published-exact",
           "roads": {}, "curves": {}, "confirmation": None}
    engine._placebo_pool = (HOLDABLE, 1)
    for rname, idx in ridx.items():
        fn = compass_factory(p)
        r = simulate(p, idx, dec, fn, rulebook="native")
        twins = []
        for seed in range(1, 21):
            fn2 = compass_factory(p)
            t = simulate(p, idx, dec, fn2, rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        out["roads"][rname] = {
            "final": r["final"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"], "halts": r["halts"],
            "placebo_finals": twins,
            "placebos_beaten": sum(1 for t in twins if r["final"] > t),
            "spy_ref_div_adj": SPY_REF[rname], "champ_vm": CHAMP[rname],
            "spy_price_only_final": spy_price_final(p, idx),
            "static_mix_final": static_mix_final(p, idx),
            "period_stats_monthly": period_stats(r["curve"], p.dates, "monthly"),
            "regime_occupancy_months": occupancy(p, idx, dec)}
        out["curves"][rname] = r["curve"]
        print(rname, r["final"], "dd", r["max_dd_pct"],
              "placebos", out["roads"][rname]["placebos_beaten"], "/20")
    # Confirmation, only if a road beats the champion (bars frozen in spec)
    beats = [rn for rn in out["roads"]
             if out["roads"][rn]["final"] > CHAMP[rn]]
    if beats:
        conf = {}
        for name, (a, b) in {"CONF-D 2010-2015": (date(2010, 1, 1), date(2015, 12, 31)),
                             "CONF-E 2016-2020": (date(2016, 1, 1), date(2020, 12, 31)),
                             "CONF-F 2021-2026": (date(2021, 1, 1), date(2026, 11, 20))}.items():
            idx, r = run_window(p, dec, a, b)
            conf[name] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                          "spy_price_only_final": spy_price_final(p, idx)}
        for rn in beats:
            a, b = ROADS[rn]
            mid = a + (b - a) / 2
            halves = {}
            for hn, (ha, hb) in {"first_half": (a, mid), "second_half": (mid, b)}.items():
                idx, r = run_window(p, dec, ha, hb)
                halves[hn] = {"window": f"{ha}->{hb}", "final": r["final"],
                              "max_dd_pct": r["max_dd_pct"],
                              "spy_price_only_final": spy_price_final(p, idx)}
            conf[f"halves_of_{rn}"] = halves
        out["confirmation"] = conf
        print("CONFIRMATION", json.dumps(conf, indent=1))
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("WROTE", os.path.join(OUT, "results.json"))

if __name__ == "__main__":
    main()
