#!/usr/bin/env python3
"""V13 Best Rules — Golden Ratio Multiplier LADDER (spec frozen before run).
Target weight by r=close/350DMA: <1.6:1.00, <2:0.75, <3:0.50, <5:0.25, >=5:0.
Daily eval, trade only on zone change, 0.60%/side on traded fraction, no floor.
BTC only, CoinMetrics PriceUSD (read-only v12 cache). Placebos 20 seeds:
(a) band perturbation U[0.85,1.15]; (b) random-timing on system's zone-change dates.
Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_chassis import buy_hold, period_stats, sma

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-golden-ratio-multiplier/data/cm_btc_hash.json")
raw = json.load(open(SRC))
days = []
for r in raw:
    if r.get("PriceUSD"):
        days.append({"d": r["time"][:10], "c": float(r["PriceUSD"])})
days.sort(key=lambda x: x["d"])
px = [d["c"] for d in days]
ma350 = sma(px, 350)
FIRST = next(days[i]["d"] for i in range(len(days)) if ma350[i] is not None)
COST = 0.006
WINDOWS = {"FULL": (FIRST, "2026-11-20"), "DESIGN": (FIRST, "2022-12-31"),
           "VALIDATION": ("2023-01-01", "2026-11-20")}
WEIGHTS = [1.0, 0.75, 0.50, 0.25, 0.0]

def ladder_weight(ratio, scale=1.0):
    t = [1.6*scale, 2*scale, 3*scale, 5*scale]
    for i, th in enumerate(t):
        if ratio < th: return WEIGHTS[i]
    return 0.0

def target_series(scale=1.0):
    """Desired weight at each day close (None before warmup)."""
    out = [None]*len(days)
    for i in range(len(days)):
        if ma350[i] is None: continue
        out[i] = ladder_weight(px[i]/ma350[i], scale)
    return out

def simulate_frac(start, end, targets):
    """targets: per-day desired weight (or callable list). Rebalance at close
    only when desired != current target; cost on traded fraction."""
    idx = [i for i,b in enumerate(days) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; w = 0.0; cur_target = None; curve = []; trades = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0; traded_frac = 0.0
    for k, i in enumerate(idx):
        if k > 0 and w > 0:
            eq *= (1 - w) + w * (days[i]["c"]/days[idx[k-1]]["c"])
        desired = targets[i]
        if desired is not None and desired != cur_target:
            delta = abs(desired - w)
            if delta > 1e-12:
                c = eq * delta * COST; eq -= c; costs += c; trades += 1; traded_frac += delta
            w = desired; cur_target = desired
        curve.append([days[i]["d"], round(eq,4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq/peak)
    return {"final": round(eq,2), "curve": curve, "trades": trades,
            "costs": round(costs,2), "max_dd": round(maxdd,4),
            "traded_fraction_total": round(traded_frac,3),
            "avg_weight_note": None}

def bh_curve(start, end):
    idx = [i for i,b in enumerate(days) if start <= b["d"] <= end]
    eq0 = 100.0*(1-COST)
    return [[days[i]["d"], round(eq0*days[i]["c"]/days[idx[0]]["c"],4)] for i in idx]

def main():
    log = []
    out = {"family": "hunt-golden-ratio-multiplier", "form": "V13 ladder (dial), no floor",
           "asset": "BTC", "first_computable": FIRST, "windows": {}}
    targets = target_series(1.0)
    # zone-change dates (global) for random-timing placebo
    change_idx = []
    prev = None
    for i,t in enumerate(targets):
        if t is not None and t != prev:
            change_idx.append(i); prev = t
    for wname,(s,e) in WINDOWS.items():
        r = simulate_frac(s,e,targets)
        ent = {k:v for k,v in r.items() if k != "curve"}
        ent["period_stats_monthly"] = period_stats(r["curve"],"M")
        ent["curve"] = r["curve"]
        ent["btc_buy_hold_bar"] = buy_hold(days,s,e)
        bc = bh_curve(s,e)
        ent["buy_hold_curve"] = bc
        # buy-hold max dd + period stats
        ent["buy_hold_period_stats_monthly"] = period_stats(bc,"M")
        pk=bc[0][1]; mdd=0.0
        for _,v in bc:
            pk=max(pk,v); mdd=max(mdd,1-v/pk)
        ent["buy_hold_max_dd"] = round(mdd,4)
        out["windows"][wname] = ent
        log.append(f"{wname}: ladder final={ent['final']} max_dd={ent['max_dd']} trades={ent['trades']} costs={ent['costs']} bar={ent['btc_buy_hold_bar']} bh_max_dd={ent['buy_hold_max_dd']}")
        print(log[-1])
    out["placebos"] = {}
    for wname in ("FULL","VALIDATION"):
        s,e = WINDOWS[wname]
        sys_final = out["windows"][wname]["final"]
        band_finals, timing_finals = [], []
        for seed in range(1,21):
            rng = random.Random(1000+seed)
            scale = rng.uniform(0.85,1.15)
            band_finals.append(simulate_frac(s,e,target_series(scale))["final"])
            rng2 = random.Random(2000+seed)
            tt = [None]*len(days); cur=None
            chset = set(change_idx)
            curw = None
            for i in range(len(days)):
                if i in chset:
                    curw = rng2.choice(WEIGHTS)
                tt[i] = curw
            timing_finals.append(simulate_frac(s,e,tt)["final"])
        for name, finals in (("band_perturbation",band_finals),("random_timing",timing_finals)):
            out["placebos"].setdefault(wname,{})[name] = {
                "finals": finals, "median": round(statistics.median(finals),2),
                "system_final": sys_final,
                "beats": sum(1 for f in finals if sys_final > f)}
            log.append(f"placebo {wname} {name}: median={statistics.median(finals):.2f} system={sys_final} beats={sum(1 for f in finals if sys_final>f)}/20")
            print(log[-1])
    json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
    open(os.path.join(HERE,"run.log"),"w").write("\n".join(log)+"\n")

if __name__ == "__main__":
    main()
