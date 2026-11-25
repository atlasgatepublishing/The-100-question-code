#!/usr/bin/env python3
"""
HOLDINGS-COUNT GRID slice for basket-quality-gate (CONSTRUCTED).
Program HOLDINGS-COUNT SWEEP WING + Second-Chance grid: counts
1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE on the gated basket, all roads,
house (v9) rules, program costs, 20-seed placebos per cell.
The frozen CONSTRUCTION-SPEC run (top-5) is untouched in the parent
folder; this slice parameterizes ONLY the holdings count (equal weight
1/N) in a copy of the parent engine. ALL = every gate-passing eligible
name, equal weight.
"""
import json, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
import run_gate_constructed as R

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]


def simulate_n(mkt, start_d, end_d, gate_obs, financial, n,
               placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cad_set = R.month_dates(mkt.cal, start_d, end_d)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash, pos, orders, costs = 100.0, {}, 0, 0.0
    curve, halts = [], []
    episode, floor = 1, 85.0
    pending_liq, trigger_date, sit_until = False, None, None
    second_halt, final = False, None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    def liquidate(i, at_open):
        nonlocal cash, orders, costs
        for t in list(pos):
            px = mkt.open_px(t, i) if at_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            val = pos[t] * px
            fee = val * R.COST_RATE + R.SELL_FEE
            cash += val - fee
            costs += fee
            orders += 1
            del pos[t]

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if pending_liq:
            liquidate(i, at_open=True)
            halts.append({"episode": episode, "trigger_date": trigger_date,
                          "liquidation_date": d, "balance": round(cash, 2)})
            pending_liq = False
            if episode == 2:
                second_halt, final = True, cash
                curve.append((d, cash))
                break
            episode = 2
            sit_until = (date.fromisoformat(d) +
                         timedelta(days=90)).isoformat()
            curve.append((d, cash))
            continue
        if sit_until is not None:
            if d >= sit_until and d in cad_set:
                floor = 0.85 * cash
                sit_until = None
            else:
                curve.append((d, cash))
                continue
        if d in cad_set and i > 0:
            j = i - 1
            elig = []
            for t in R.UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            kept = []
            for t, mom in elig:
                if t in financial:
                    continue
                q = R.quality_at(gate_obs.get(t, []), mkt.cal[j])
                if q is None or q[2] <= 0:
                    continue
                kept.append((t, mom))
            if rng is None:
                kept.sort(key=lambda x: -x[1])
                picks = [t for t, _ in kept] if n == "ALL" else \
                    [t for t, _ in kept[:n]]
            else:
                names = sorted(t for t, _ in kept)
                k = len(names) if n == "ALL" else min(n, len(names))
                picks = rng.sample(names, k) if names else []
            if picks:
                # Chassis convention (frozen spec): each pick is weighted
                # 1/nominal-count; if fewer names pass, the shortfall
                # stays in cash (at N=5 this reproduces the parent run
                # exactly: 20% per pick). ALL = equal-weight all passers.
                w = (1.0 / len(picks)) if n == "ALL" else 1.0 / n
                eq_open = equity_at(i, use_open=True)
                target_val = {t: w * eq_open for t in picks}
                for t in list(pos):
                    px = mkt.open_px(t, i)
                    if px is None:
                        continue
                    cur_val = pos[t] * px
                    want = target_val.get(t, 0.0)
                    if cur_val > want + 0.01:
                        sell_val = cur_val - want
                        fee = sell_val * R.COST_RATE + R.SELL_FEE
                        cash += sell_val - fee
                        costs += fee
                        orders += 1
                        pos[t] -= sell_val / px
                        if want <= 0.0 or pos[t] * px < 0.01:
                            del pos[t]
                for t in picks:
                    px = mkt.open_px(t, i)
                    if px is None:
                        continue
                    cur_val = pos.get(t, 0.0) * px
                    deficit = target_val[t] - cur_val
                    if deficit <= 0.01:
                        continue
                    buy_val = min(deficit, cash / (1.0 + R.COST_RATE))
                    if buy_val <= 0.01:
                        continue
                    fee = buy_val * R.COST_RATE
                    cash -= buy_val + fee
                    costs += fee
                    orders += 1
                    pos[t] = pos.get(t, 0.0) + buy_val / px
        eq_close = equity_at(i, use_open=False)
        curve.append((d, eq_close))
        if sit_until is None and eq_close <= floor:
            pending_liq, trigger_date = True, d
            if i == i1:
                liquidate(i, at_open=False)
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidation_date": d,
                              "balance": round(cash, 2)})
                if episode == 2:
                    second_halt = True
                final = cash
                curve[-1] = (d, cash)
                break
    if final is None:
        final = curve[-1][1]
    peak, max_dd = -1.0, 0.0
    for d, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)
    return {"final": final, "orders": orders, "costs": costs,
            "max_dd": max_dd, "curve": curve, "halts": halts,
            "second_halt": second_halt}


def main():
    gate_obs, financial, info = R.load_gate_obs()
    mkt = R.Market(R.UNIVERSE)
    out = {"slug": "basket-quality-gate", "slice": "holdings-count grid",
           "construction": "CONSTRUCTED", "counts": COUNTS, "roads": {}}
    for road, (sd, ed) in R.ROADS.items():
        cells = {}
        for n in COUNTS:
            g = simulate_n(mkt, sd, ed, gate_obs, set(financial), n)
            pf = []
            for seed in R.PLACEBO_SEEDS:
                pr = simulate_n(mkt, sd, ed, gate_obs, set(financial), n,
                                placebo_seed=seed)
                pf.append(round(pr["final"], 2))
            beaten = sum(1 for v in pf if g["final"] > v)
            key = str(n)
            cells[key] = {
                "final": round(g["final"], 2),
                "max_dd_pct": round(g["max_dd"] * 100, 2),
                "costs": round(g["costs"], 2), "orders": g["orders"],
                "halts": len(g["halts"]),
                "placebo_beaten": f"{beaten}/20",
                "placebo_median": sorted(pf)[10],
                "period_stats_monthly": R.period_stats(g["curve"]),
                "equity_curve": [[d, round(v, 4)] for d, v in g["curve"]],
            }
            print(f"{road} n={key}: final={cells[key]['final']} "
                  f"maxDD={cells[key]['max_dd_pct']} "
                  f"placebo={cells[key]['placebo_beaten']}", flush=True)
        out["roads"][road] = cells
    payload = json.dumps(out, indent=1)
    path = os.path.join(HERE, "grid_results.json")
    with open(path, "w") as f:
        f.write("")
    with open(path, "a") as f:
        for k in range(0, len(payload), 32768):
            f.write(payload[k:k + 32768])
            f.flush()
    print("saved grid_results.json", len(payload), "bytes", flush=True)


if __name__ == "__main__":
    main()
