#!/usr/bin/env python3
"""V13 Best-Rules run for TrendYCMacro. Spec frozen in BEST-RULES-SPEC.md
before this script was run. Reuses the v12 chassis (engine.py, copied).
Panel: sector SPY (1998+) + FRED from the v12 family data/ (read-only) +
IEF from the program ETF cache."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import (Panel, load_sector, load_etf_json, load_fred,
                    cadence_days, simulate, period_stats, ROADS, SPY_REF, CHAMP)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)
V12DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/catalog-taa-trendyieldcurve-macro/data")

def build_panel():
    p = Panel(load_sector("SPY"))
    ds, cs = load_sector("SPY"); p.series["SPY"] = cs[:]
    p.add("IEF", load_etf_json("IEF"))
    for name in ["DGS10", "DGS3MO", "INDPRO", "HOUST", "RRSFS"]:
        p.add(name, load_fred(os.path.join(V12DATA, f"{name}.csv")))
    return p

def rachev(p, i):
    if i - 200 < 0: return None
    closes = p.series["SPY"][i - 200:i + 1]
    if any(v is None for v in closes): return None
    rets = [closes[k + 1] / closes[k] - 1 for k in range(200)]
    med = sorted(rets)[100]
    above = [r for r in rets if r > med]; below = [r for r in rets if r < med]
    if not above or not below: return None
    ab = sum(above) / len(above); be = sum(below) / len(below)
    if be == 0: return None
    return ab / be * -1

def trend_on(p, i):
    sma = p.sma("SPY", i, 200); c = p.close("SPY", i)
    return sma is not None and c is not None and c > sma

def curve_pos(p, i):
    y10 = p.close("DGS10", i); y3 = p.close("DGS3MO", i)
    if y10 is None or y3 is None: return None
    return y10 > y3

# ---- headline: trend hard gate, curve soft sizing, IEF defensive, no floor
def headline_factory(p):
    def fn(i):
        if not trend_on(p, i): return {"IEF": 1.0}
        cp = curve_pos(p, i)
        if cp is None or cp: return {"SPY": 1.0}
        return {"SPY": 0.5, "IEF": 0.5}
    return fn

# ---- diagnostics
def published_factory(p):
    state = {"long": False}
    def fn(i):
        lag = i - 21
        macro = True
        for s in ["RRSFS", "INDPRO", "HOUST"]:
            r = p.ret(s, lag, 252) if lag >= 0 else None
            if r is None or r <= 0: macro = False
        if macro and state["long"]:
            return {"SPY": 1.0}
        rv = rachev(p, i)
        cp = curve_pos(p, i)
        ok = trend_on(p, i) and rv is not None and rv > 1 and cp is True
        state["long"] = bool(ok)
        return {"SPY": 1.0} if ok else {}
    return fn

def trend_only_factory(p):
    def fn(i):
        return {"SPY": 1.0} if trend_on(p, i) else {"IEF": 1.0}
    return fn

def trend_curve_hard_factory(p):
    def fn(i):
        return {"SPY": 1.0} if (trend_on(p, i) and curve_pos(p, i) is True) else {"IEF": 1.0}
    return fn

def trend_rachev_factory(p):
    def fn(i):
        rv = rachev(p, i)
        return {"SPY": 1.0} if (trend_on(p, i) and rv is not None and rv > 1) else {"IEF": 1.0}
    return fn

def buyhold_factory(p):
    return lambda i: {"SPY": 1.0}

def static_mix_factory(p):
    return lambda i: {"SPY": 0.6, "IEF": 0.4}

FORMS = {
    "headline_trend_curve_soft": headline_factory,
    "diag_published_exact": published_factory,
    "diag_trend_only": trend_only_factory,
    "diag_trend_curve_hard": trend_curve_hard_factory,
    "diag_trend_rachev_hard": trend_rachev_factory,
    "bench_buyhold_spy": buyhold_factory,
    "bench_static_60spy_40ief": static_mix_factory,
}

def state_at(p, i):
    if not trend_on(p, i): return "trend_off_IEF"
    cp = curve_pos(p, i)
    if cp is None: return "trend_on_curve_unknown_SPY"
    return "trend_on_curve_pos_SPY" if cp else "trend_on_curve_INVERTED_soft50"

def main():
    p = build_panel()
    ridx = engine.road_indices(p, ROADS)
    dec = cadence_days(p.dates, "monthly")
    out = {"family": "catalog-taa-trendyieldcurve-macro", "program": "v13-best-rules",
           "roads": {}, "curves": {}, "period_stats": {}, "state_analysis": {}}
    for rname, idx in ridx.items():
        out["roads"][rname] = {}
        for form, fac in FORMS.items():
            r = simulate(p, idx, dec, fac(p), rulebook="native")
            out["roads"][rname][form] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
            if form in ("headline_trend_curve_soft", "diag_published_exact",
                        "bench_buyhold_spy", "bench_static_60spy_40ief"):
                out["curves"][f"{rname}|{form}"] = r["curve"]
                out["period_stats"][f"{rname}|{form}"] = period_stats(r["curve"], p.dates, "monthly")
        # placebos for headline: v12 SWITCH random SPY/cash timing, monthly
        engine._placebo_pool = ("SWITCH", "SPY")
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec, headline_factory(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        real = out["roads"][rname]["headline_trend_curve_soft"]["final"]
        out["roads"][rname]["headline_trend_curve_soft"]["placebo_finals"] = twins
        out["roads"][rname]["headline_trend_curve_soft"]["placebos_beaten"] = \
            sum(1 for t in twins if real > t)
        # state occupancy over this road's decision days
        counts = {}
        for i in idx:
            if i in dec:
                s = state_at(p, i); counts[s] = counts.get(s, 0) + 1
        out["state_analysis"][rname] = counts
    # curve-inversion episodes on LONG decision days (for the false-positive record)
    inv_months = []
    for i in ridx["LONG"]:
        if i in dec:
            cp = curve_pos(p, i)
            if cp is False:
                inv_months.append(str(p.dates[i])[:7])
    out["inverted_decision_months_LONG"] = inv_months
    out["spy_ref_program"] = SPY_REF; out["champion_vm"] = CHAMP
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    for rname in ridx:
        print(rname, {f: round(v["final"], 2) for f, v in out["roads"][rname].items()},
              "placebos_beaten", out["roads"][rname]["headline_trend_curve_soft"]["placebos_beaten"])
    print("states LONG:", out["state_analysis"]["LONG"])
    print("inverted months LONG:", len(inv_months), inv_months[:50])

if __name__ == "__main__":
    main()
