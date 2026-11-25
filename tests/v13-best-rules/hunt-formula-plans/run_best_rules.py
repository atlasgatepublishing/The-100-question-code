#!/usr/bin/env python3
"""V13 BEST RULES — hunt-formula-plans. Frozen spec: BEST-RULES-SPEC.md.
CONSTANT-RATIO 80% SPY / 20% IEF; monthly check at month-end close;
rebalance to exactly 80/20 at next open ONLY if stock weight drifted
>= 5pp from target. No floor. Program costs 0.10%/side + $0.01 sell fee
on every transfer, both legs. Controls: static 80/20 never rebalanced;
SPY buy-and-hold. Placebos: 20-seed random-month rebalancing twins with
matched rebalance counts. Point-in-time: signal at close, execution at
next open."""
import json, os, time, random, statistics
from datetime import date

START = 100.0
COST = 0.001; SELL_FEE = 0.01
TARGET_W = 0.80; BAND = 0.05
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB_BEST = {"LONG": 217.07, "DECADE": 172.53, "CONT": 164.00, "VAL": 134.53}  # FD-1 native
HERE = os.path.dirname(os.path.abspath(__file__))
SPY_P = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
IEF_P = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf/IEF.json")


def load_pxfull(path):
    j = json.load(open(path))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def align(a, b):
    bd = {x["d"]: x for x in b}
    return [(x, bd[x["d"]]) for x in a if x["d"] in bd]


def period_stats(curve, freq="monthly"):
    if not curve:
        return None
    def key(d):
        return d[:7] if freq == "monthly" else d[:4]
    vals, last = [], None
    for d, v in curve:
        k = key(d)
        if k != last:
            vals.append(v); last = k
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0:
            streak += 1; worst = max(worst, streak)
        else:
            streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst, "longest_between_highs": longest}


def maxdd(curve):
    peak, m = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            m = max(m, (peak - v) / peak)
    return round(m * 100, 2)


def simulate(pairs, start, end, mode, twin_seed=None, twin_count=0):
    """mode: 'plan' (band-triggered), 'static' (never), 'twin' (random months)."""
    idx = [i for i, (a, _) in enumerate(pairs) if start <= a["d"] <= end]
    if not idx:
        return None
    month_end = {}
    for i in idx:
        month_end[pairs[i][0]["d"][:7]] = i
    me_set = set(month_end.values())
    twin_months = None
    if mode == "twin":
        rng = random.Random(twin_seed)
        cand = sorted(me_set - {idx[-1]})
        twin_months = set(rng.sample(cand, min(twin_count, len(cand)))) if cand else set()
    cash, sh_s, sh_b, costs = START, 0.0, 0.0, 0.0
    trades, curve = [], []
    pending = True  # initial allocation at first open
    n_rebal = 0

    def rebalance(i, tag):
        nonlocal cash, sh_s, sh_b, costs, n_rebal
        a, b = pairs[i]
        eq_o = cash + sh_s * a["o"] + sh_b * b["o"]
        want_s, want_b = TARGET_W * eq_o, (1 - TARGET_W) * eq_o
        have_s, have_b = sh_s * a["o"], sh_b * b["o"]
        # sell overweight legs first
        for leg, have, want, px in (("SPY", have_s, want_s, a["o"]), ("IEF", have_b, want_b, b["o"])):
            if have > want + 0.01:
                val = have - want; fee = val * COST + SELL_FEE
                if leg == "SPY":
                    sh_s -= val / px
                else:
                    sh_b -= val / px
                cash += val - fee; costs += fee
                trades.append([a["d"], f"SELL-{tag}", leg, round(px, 4), round(val, 2), round(fee, 2)])
        for leg, have, want, px in (("SPY", have_s, want_s, a["o"]), ("IEF", have_b, want_b, b["o"])):
            cur = (sh_s * a["o"]) if leg == "SPY" else (sh_b * b["o"])
            if want > cur + 0.01:
                diff = min(want - cur, cash)
                bv = diff / (1 + COST); fee = bv * COST
                if leg == "SPY":
                    sh_s += bv / px
                else:
                    sh_b += bv / px
                cash -= bv + fee; costs += fee
                trades.append([a["d"], f"BUY-{tag}", leg, round(px, 4), round(bv, 2), round(fee, 2)])
        if tag == "REBAL":
            n_rebal += 1

    for pos, i in enumerate(idx):
        a, b = pairs[i]
        if pending:
            rebalance(i, "INIT" if pos == 0 else "REBAL")
            pending = False
        eq = cash + sh_s * a["c"] + sh_b * b["c"]
        curve.append([a["d"], round(eq, 4)])
        if i in me_set and i != idx[-1]:
            if mode == "plan":
                w = (sh_s * a["c"] / eq) if eq > 0 else 0.0
                if abs(w - TARGET_W) >= BAND:
                    pending = True
            elif mode == "twin" and i in twin_months:
                pending = True
    # liquidate at last close
    a, b = pairs[idx[-1]]
    for leg, sh, px in (("SPY", sh_s, a["c"]), ("IEF", sh_b, b["c"])):
        if sh > 0:
            val = sh * px; fee = val * COST + SELL_FEE
            cash += val - fee; costs += fee
            trades.append([a["d"], "SELL-END", leg, round(px, 4), round(val, 2), round(fee, 2)])
    sh_s = sh_b = 0.0
    curve[-1] = [a["d"], round(cash, 4)]
    return {"final": round(cash, 2), "max_dd_pct": maxdd(curve), "costs": round(costs, 2),
            "orders": len(trades), "rebalances": n_rebal, "trades": trades,
            "equity_curve": curve, "period_stats": period_stats(curve, "monthly")}


def spy_hold(pairs, start, end):
    idx = [i for i, (a, _) in enumerate(pairs) if start <= a["d"] <= end]
    a0 = pairs[idx[0]][0]
    bv = START / (1 + COST); sh = bv / a0["o"]
    curve = [[pairs[i][0]["d"], round(sh * pairs[i][0]["c"], 4)] for i in idx]
    last = pairs[idx[-1]][0]; val = sh * last["c"]
    final = val - (val * COST + SELL_FEE)
    curve[-1] = [last["d"], round(final, 4)]
    return {"final": round(final, 2), "max_dd_pct": maxdd(curve),
            "equity_curve": curve, "period_stats": period_stats(curve, "monthly")}


def main():
    spy, ief = load_pxfull(SPY_P), load_pxfull(IEF_P)
    pairs = align(spy, ief)
    print(f"aligned bars {pairs[0][0]['d']} -> {pairs[-1][0]['d']} n={len(pairs)}")
    out = {"family": "hunt-formula-plans", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "plan": "CONSTANT-RATIO 80% SPY / 20% IEF; monthly check; rebalance to 80/20 at next open only if stock weight drift >= 5pp; NO floor",
           "costs": "0.10%/side + $0.01 sell fee, both legs, every transfer",
           "verdict_ceiling": "CANDIDATE", "roads": {}}
    for name, (s, e) in ROADS.items():
        plan = simulate(pairs, s, e, "plan")
        static = simulate(pairs, s, e, "static")
        hold = spy_hold(pairs, s, e)
        finals = []
        for seed in range(1, 21):
            tw = simulate(pairs, s, e, "twin", twin_seed=seed, twin_count=plan["rebalances"])
            finals.append(tw["final"])
        rec = {"plan": plan, "static_control": static, "spy_hold": hold,
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "published_best_fd1_native": PUB_BEST[name],
               "rebalancing_contribution_vs_static": round(plan["final"] - static["final"], 2),
               "placebo_twins": {"seed_finals": finals,
                                 "beaten_of_20": sum(1 for p in finals if plan["final"] > p),
                                 "design": f"random-month rebalancing twins: {plan['rebalances']} rebalances (matched count) at random month-ends to 80/20, 20 seeds"}}
        out["roads"][name] = rec
        print(f"{name}: plan ${plan['final']} (DD {plan['max_dd_pct']}%, rebal {plan['rebalances']}, costs ${plan['costs']}) "
              f"| static ${static['final']} (DD {static['max_dd_pct']}%) | rebal contrib ${rec['rebalancing_contribution_vs_static']} "
              f"| SPY hold ${hold['final']} (DD {hold['max_dd_pct']}%) | placebos beaten {rec['placebo_twins']['beaten_of_20']}/20 "
              f"| pub best ${PUB_BEST[name]} | champ ${CHAMP[name]}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
