#!/usr/bin/env python3
"""Fast numpy twin of run_lowvol_constructed.py — identical semantics
(verified against the pointer engine on VAL/LONG main + placebo seeds),
used only to make the 20-seed placebo batches fit this VM's time limits.
FILL[t,i] = last adjclose bar <= CAL[i]; GAP[t,i] = i - cal-index of that bar.
Vanishing (>10 trading days), rename conversion, rebalance sells/buys and
costs replicate the reference engine line for line in effect."""
import os, sys, json, math, random, bisect
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_lowvol_constructed as R

TICKS = sorted(R.PX)
TIDX = {t: i for i, t in enumerate(TICKS)}
ND = len(R.CAL)
FILL = np.full((len(TICKS), ND), np.nan)
GAP = np.full((len(TICKS), ND), 10 ** 9, dtype=np.int64)
for t, ti in TIDX.items():
    dates, vals, cals = R.PX[t]
    pos = np.searchsorted(np.array(cals), np.arange(ND), side="right") - 1
    ok = pos >= 0
    idx = np.where(ok)[0]
    FILL[ti, idx] = np.array(vals, dtype=float)[pos[idx]]
    GAP[ti, idx] = idx - np.array(cals, dtype=np.int64)[pos[idx]]

def run_fast(start, end, placebo_seed=None):
    rng = random.Random(4000 + placebo_seed) if placebo_seed is not None else None
    sched = [s for s in R.rebalance_schedule(start, end) if s[1] >= start and s[1] <= end]
    sched_by_date = {ex: ref for ref, ex in sched}
    day_idx = [R.CAL_IDX[d] for d in R.CAL if start <= d <= end]
    days = [R.CAL[i] for i in day_idx]
    cash = R.START; shares = np.zeros(len(TICKS))
    zeroed = set(); costs = 0.0; orders = 0; curve = []; elig_counts = []
    for d, ci in zip(days, day_idx):
        col = FILL[:, ci]; gap = GAP[:, ci]
        held = shares > 0
        if held.any():
            stale = held & (gap > 10)
            for ti in np.where(stale)[0]:
                t = TICKS[ti]
                if t in R.RENAMES and R.RENAMES[t] in TIDX:
                    si = TIDX[R.RENAMES[t]]
                    sv = col[si]
                    if sv == sv and col[ti] == col[ti] and sv > 0:
                        shares[si] += shares[ti] * col[ti] / sv
                    else:
                        zeroed.add(t)
                    shares[ti] = 0.0
                else:
                    shares[ti] = 0.0; zeroed.add(t)
            nanheld = held & np.isnan(col)
            for ti in np.where(nanheld)[0]:
                shares[ti] = 0.0; zeroed.add(TICKS[ti])
        if d in sched_by_date:
            ref = sched_by_date[d]
            vols = R.vols_at(ref)
            elig = sorted(vols); elig_counts.append(len(elig))
            if rng is None:
                chosen = sorted(elig, key=lambda t: vols[t])[:100]
            else:
                chosen = rng.sample(elig, min(100, len(elig)))
            inv = {t: 1.0 / vols[t] for t in chosen}
            tot = sum(inv.values())
            target_w = {t: inv[t] / tot for t in chosen}
            live = np.where((gap <= 10) & ~np.isnan(col), col, 0.0)
            cur_val = shares * live
            pv = cash + cur_val.sum()
            for ti in np.where(shares > 0)[0]:
                t = TICKS[ti]; cur = cur_val[ti]; tgt = target_w.get(t, 0.0) * pv
                price = col[ti]
                if tgt <= 0:
                    if cur > 0 and price == price and price > 0:
                        fee = cur * R.COST + R.SELL_FEE; costs += fee; cash += cur - fee; orders += 1
                    shares[ti] = 0.0
                else:
                    if cur > tgt and price == price and price > 0:
                        sell_val = cur - tgt
                        fee = sell_val * R.COST + R.SELL_FEE; costs += fee; cash += sell_val - fee; orders += 1
                        shares[ti] = tgt / price
            live2 = np.where((gap <= 10) & ~np.isnan(col), col, 0.0)
            pv2 = cash + (shares * live2).sum()
            for t in chosen:
                ti = TIDX.get(t)
                if ti is None:
                    continue
                v = col[ti]
                if v != v or gap[ti] != 0:
                    continue
                cur = shares[ti] * v
                tgt = target_w[t] * pv2
                if tgt > cur:
                    buy_val = min(tgt - cur, cash / (1 + R.COST) if cash > 0 else 0.0)
                    if buy_val <= 0:
                        continue
                    fee = buy_val * R.COST; costs += fee; cash -= buy_val + fee; orders += 1
                    shares[ti] += buy_val / v
        live = np.where((gap <= 10) & ~np.isnan(col), col, 0.0)
        eq = cash + float((shares * live).sum())
        curve.append([d, round(eq, 4)])
    peak = -1; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "zeroed": sorted(zeroed), "equity_curve": curve,
            "rebalances": len(elig_counts),
            "eligible_min": min(elig_counts) if elig_counts else None,
            "eligible_median": sorted(elig_counts)[len(elig_counts) // 2] if elig_counts else None}

if __name__ == "__main__":
    # verification mode
    for road, (s, e) in R.ROADS.items():
        a = R.run(s, e); b = run_fast(s, e)
        print(road, "ref", a["final"], a["max_dd_pct"], a["costs"], a["orders"], "| fast", b["final"], b["max_dd_pct"], b["costs"], b["orders"], flush=True)
    for seed in (0, 1):
        a = R.run("2023-01-03", "2026-11-20", placebo_seed=seed); b = run_fast("2023-01-03", "2026-11-20", placebo_seed=seed)
        print("VAL placebo", seed, "ref", a["final"], "| fast", b["final"], flush=True)
