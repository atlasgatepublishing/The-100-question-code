#!/usr/bin/env python3
"""Low Volatility — v13 BEST RULES. Spec: BEST-RULES-SPEC.md (frozen before runs).
Design: PIT S&P 500 universe (v12 caches, read-only), 252-day vol as published,
MY addition = per-name trend filter (close at reference date above its trailing
200-trading-day mean adjusted close), 30 lowest-vol among passers, inverse-vol
weights, quarterly index calendar, program costs, NO floor.
Comparator: published index form (100 lowest-vol, no filter) run on the SAME
imported v12 engine for identical plumbing.
Placebos: 20 seeds, random 30 from the same trend-passing pool, same machinery.
Simulation only."""
import importlib.util, json, math, os, random, sys, time
from datetime import date
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/holdings-low-volatility/run_sweep.py")
spec = importlib.util.spec_from_file_location("v12sweep", V12)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)   # loads prices/membership/calendar; prints tapes line

PX, CAL, CAL_IDX = M.PX, M.CAL, M.CAL_IDX
T_IDX, PY, PL, LB = M.T_IDX, M.PY, M.PL, M.LB
SCHED, COST, SELL_FEE, START_CASH, RENAMES = M.SCHED, M.COST, M.SELL_FEE, M.START_CASH, M.RENAMES
COUNT = 30

def trend_pass(t, ref):
    i = T_IDX[t]; end_i = CAL_IDX[ref]
    price = PX[i, end_i]
    if np.isnan(price) or end_i < 199:
        return False
    seg = PX[i, end_i - 199:end_i + 1]
    seg = seg[~np.isnan(seg)]
    if len(seg) < 150:
        return False
    return bool(price > float(np.mean(seg)))

POOL_CACHE = {}
def pool_at(ref):
    if ref in POOL_CACHE:
        return POOL_CACHE[ref]
    vols = M.vols_at(ref)
    out = {t: v for t, v in vols.items() if trend_pass(t, ref)}
    POOL_CACHE[ref] = out
    return out

def run(start, end, seed=None):
    """My form: quarterly, trend-filtered pool, 30 lowest-vol (or random 30 for
    placebos), inverse-vol weights, no floor. Engine body mirrors v12 run()."""
    rng = random.Random(4000 + seed) if seed is not None else None
    sched = {ex: ref for ref, ex in SCHED if start <= ex <= end}
    days = [d for d in CAL if start <= d <= end]
    cash = START_CASH; pos = {}; zeroed = []; costs = 0.0; orders = 0; curve = []
    for d in days:
        gi = CAL_IDX[d]
        for t in list(pos):
            i = T_IDX[t]
            if gi - LB[i] > 10:
                if t in RENAMES and RENAMES[t] in T_IDX:
                    j = T_IDX[RENAMES[t]]
                    bv = PY[i][LB[i]]; sv = PY[j][gi]
                    if sv > 0 and bv > 0:
                        pos[RENAMES[t]] = pos.get(RENAMES[t], 0.0) + pos[t] * bv / sv
                    else:
                        zeroed.append(t)
                    del pos[t]
                else:
                    del pos[t]; zeroed.append(t)
        if d in sched:
            ref = sched[d]
            pool = pool_at(ref)
            elig = sorted(pool)
            if elig:
                n = min(COUNT, len(elig))
                if rng is None:
                    chosen = sorted(elig, key=lambda t: pool[t])[:n]
                else:
                    chosen = rng.sample(elig, n)
                inv_sum = sum(1.0 / pool[t] for t in chosen)
                target_w = {t: (1.0 / pool[t]) / inv_sum for t in chosen}
                pv = cash + sum(sh * PY[T_IDX[t]][gi] for t, sh in pos.items())
                for t in list(pos):
                    i = T_IDX[t]; p = PL[i][gi]
                    price = 0.0 if p != p else p
                    cur = pos[t] * price
                    tgt = target_w.get(t, 0.0) * pv
                    if tgt <= 0:
                        if cur > 0:
                            fee = cur * COST + SELL_FEE
                            costs += fee; cash += cur - fee; orders += 1
                        del pos[t]
                    elif cur > tgt and price > 0:
                        sell_val = cur - tgt
                        fee = sell_val * COST + SELL_FEE
                        costs += fee; cash += sell_val - fee; orders += 1
                        pos[t] = tgt / price
                pv2 = cash + sum(sh * PY[T_IDX[t]][gi] for t, sh in pos.items())
                for t in chosen:
                    i = T_IDX[t]; p = PL[i][gi]
                    if p != p or p <= 0:
                        continue
                    cur = pos.get(t, 0.0) * p
                    tgt = target_w[t] * pv2
                    if tgt > cur and cash > 0:
                        buy_val = min(tgt - cur, cash / (1 + COST))
                        if buy_val <= 0:
                            continue
                        fee = buy_val * COST
                        costs += fee; cash -= buy_val + fee; orders += 1
                        pos[t] = pos.get(t, 0.0) + buy_val / p
        eq = cash + sum(sh * PY[T_IDX[t]][gi] for t, sh in pos.items())
        curve.append((d, round(eq, 4)))
    peak = -1.0; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": [],
            "zeroed": sorted(set(zeroed)), "curve": curve}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
CONF = {"CONF-A_2012-2019": ("2012-01-03", "2019-12-31"),
        "CONF-B_2020-2026": ("2020-01-02", "2026-11-20")}

def cell(start, end):
    r = run(start, end)
    twins = [run(start, end, seed=s)["final"] for s in range(20)]
    out = {k: v for k, v in r.items() if k != "curve"}
    out["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
    out["placebo_median"] = round(sorted(twins)[10], 2)
    out["placebo_finals"] = twins
    out["distribution"] = M.period_distribution(r["curve"])
    return r, out

def main():
    t0 = time.time()
    result = {"family": "low-volatility", "program": "v13-best-rules",
              "spec": "BEST-RULES-SPEC.md (frozen before runs)",
              "design": "PIT S&P500; 252d vol; trend filter close>200d mean at ref; 30 lowest-vol passers; inverse-vol; quarterly; no floor",
              "roads": ROADS, "champion_bars": CHAMP, "spy": {}, "mine": {},
              "published_form_same_plumbing": {}, "curves": {}, "confirmation": {},
              "pool_sizes_sample": {}}
    for road, (s, e) in ROADS.items():
        result["spy"][road] = M.buyhold(s, e)
    for ref, ex in SCHED:
        if ex in ("2010-02-19", "2016-11-18", "2019-02-15", "2023-02-17", "2026-02-20"):
            result["pool_sizes_sample"][ex] = {"eligible": len(M.vols_at(ref)),
                                               "trend_passing": len(pool_at(ref))}
    for road, (s, e) in ROADS.items():
        r, c = cell(s, e)
        result["mine"][road] = c
        result["curves"][road] = r["curve"]
        pub = M.run(s, e, 100, "native")
        result["published_form_same_plumbing"][road] = {k: v for k, v in pub.items() if k != "curve"}
        print(f"{road}: mine {c['final']} (DD {c['max_dd_pct']}%, pb {c['placebo_beaten']}/20) "
              f"published100 {pub['final']} spy {result['spy'][road]} ({time.time()-t0:.0f}s)", flush=True)
    # confirmation rule: any champion beat -> re-run on different years
    beaten = [rd for rd in ROADS if result["mine"][rd]["final"] > CHAMP[rd]]
    if beaten:
        for cname, (s, e) in CONF.items():
            result["confirmation"][cname] = run(s, e)["final"]
        print("CONFIRMATION (champion beaten on", beaten, "):", result["confirmation"], flush=True)
    else:
        print("No champion beat -> no confirmation run owed.", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
