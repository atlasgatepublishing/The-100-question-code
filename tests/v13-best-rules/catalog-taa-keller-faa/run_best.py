#!/usr/bin/env python3
"""V13 best-rules FAA: pure 84d momentum rank, top3, neg->SHY, monthly, no floor.
Reuses v12 engine plumbing (data, costs, run(), period_stats) read-only."""
import sys, os, json, statistics
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa"))
import engine as E

U = ["SPY","VEA","VWO","AGG","VNQ","DBC","SHY"]
RISKY = ["SPY","VEA","VWO","AGG","VNQ","DBC"]

def w_best(i):
    # rank by 84d return descending only
    order = sorted(U, key=lambda t: -E.ret(t, i, 84))
    picks = order[:3]
    out = {}
    for t in picks:
        k = "SHY" if E.ret(t, i, 84) < 0 else t
        out[k] = out.get(k, 0) + 1.0/3
    return out

def w_static(i):
    return {t: 1.0/7 for t in U}

def static_buyhold(road):
    # equal-weight buy-and-hold: use engine.run with a wfun that is only applied once?
    # engine rebalances at every eval; instead emulate: run monthly but w_static gives
    # rebalanced EW. For true buy-hold, compute directly from ARR.
    import numpy as np
    start, end = E.ROADS[road]
    si = next(i for i,d in enumerate(E.CAL) if d >= start)
    ei = max(i for i,d in enumerate(E.CAL) if d <= end)
    # buy at si close (cost 0.10% on $100), hold to each day
    eq = []
    shares = {t: (100.0/7)*(1-E.COST)/E.ARR[t][si] for t in U}
    for i in range(si, ei+1):
        v = sum(shares[t]*E.ARR[t][i] for t in U)
        eq.append((E.CAL[i], round(float(v),4)))
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    return {"final": round(eq[-1][1],2), "maxDD": round(mdd*100,2), "costs": round(100*E.COST,2), "equity": eq}

def spy_buyhold(road):
    import numpy as np
    start, end = E.ROADS[road]
    si = next(i for i,d in enumerate(E.CAL) if d >= start)
    ei = max(i for i,d in enumerate(E.CAL) if d <= end)
    sh = 100.0*(1-E.COST)/E.ARR["SPY"][si]
    eq = [(E.CAL[i], round(float(sh*E.ARR["SPY"][i]),4)) for i in range(si, ei+1)]
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    return {"final": round(eq[-1][1],2), "maxDD": round(mdd*100,2), "equity": eq}

res = {"family": "catalog-taa-keller-faa", "form": "v13-best-rules: pure-momentum simplification (rankR only), top3, neg->SHY, monthly, no floor", "roads": {}}
pw = E.placebo_wfun(RISKY, 3)
for road in E.ROADS:
    r = E.run(w_best, road, cadence="monthly", house=False)
    finals = [E.run(pw, road, seed=1000+s)["final"] for s in range(20)]
    beaten = sum(1 for f in finals if r["final"] > f)
    st = static_buyhold(road)
    spy = spy_buyhold(road)
    res["roads"][road] = {
        "best": {k: r[k] for k in ("final","maxDD","costs","orders","halts")},
        "best_equity": r["equity"],
        "period_distribution_monthly": E.period_stats(r["equity"]),
        "placebo_finals": finals, "placebos_beaten": beaten,
        "static_mix_EW_buyhold": {k: st[k] for k in ("final","maxDD","costs")},
        "static_mix_equity": st["equity"],
        "spy_buyhold_computed": {k: spy[k] for k in ("final","maxDD")},
    }
    print(road, r["final"], r["maxDD"], "placebos", beaten, "/20", "static", st["final"], "spy", spy["final"], flush=True)

out = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-keller-faa/results.json")
json.dump(res, open(out,"w"), indent=1)
print("WROTE", out)
