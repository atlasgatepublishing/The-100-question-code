#!/usr/bin/env python3
"""hunt-coppock V13 BEST RULES — implements BEST-RULES-SPEC.md exactly.
Published buy (Coppock 1962): monthly SPY closes; curve = WMA(10) of
[ROC(14mo)+ROC(11mo)]; buy when curve < 0 and turns up. Exit: CONSTRUCTED
minimal completion — HOLD TO ROAD END (no Coppock sell rule invented).
No floor. All-in. Costs 0.10%/side + $0.01 sell fee. Decide month-end
close, execute next trading day open. Placebos: (1) circular shift of
monthly in/out state, 20 seeds; (2) random-timing entry, 20 seeds.
"""
import json, os, time, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12_FINAL = 142.36


def load_spy():
    j = json.load(open(PX))
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


def monthly_closes(bars):
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = (b["d"], b["c"])
    return [(d, m, c) for m, (d, c) in sorted(seen.items())]


def coppock_series(months):
    closes = [c for _, _, c in months]
    n = len(closes)
    s = [None] * n
    for t in range(n):
        if t >= 14:
            s[t] = (closes[t] / closes[t - 14] - 1.0) * 100.0 + \
                   (closes[t] / closes[t - 11] - 1.0) * 100.0
    curve = [None] * n
    wts = list(range(1, 11)); wsum = sum(wts)
    for t in range(n):
        if t >= 9 and all(s[t - k] is not None for k in range(10)):
            curve[t] = sum(s[t - 9 + i] * wts[i] for i in range(10)) / wsum
    first = next((i for i, v in enumerate(curve) if v is not None), None)
    return curve, first


def buy_signals(months, curve):
    """Indices t where published buy fires: curve<0 and turns up."""
    out = []
    for t in range(1, len(months)):
        c, cp = curve[t], curve[t - 1]
        if c is not None and cp is not None and c < 0 and c > cp:
            out.append(t)
    return out


def simulate_states(bars, months, targets, start, end):
    """Generic daily engine: targets aligned with months (state after each
    month-end check); executions next trading day open; mark-out at end."""
    by_date = {b["d"]: b for b in bars}
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    checkmap = {months[i][0]: targets[i] for i in range(len(months))}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve_out = [], []
    pending = None
    days_invested = 0
    for d in days:
        bar = by_date[d]
        if pending is not None:
            if pending and shares == 0.0 and cash > 0:
                bv = cash / (1 + COST); cfee = bv * COST
                shares = bv / bar["o"]; cash -= bv + cfee; costs += cfee
                trades.append([d, "BUY", round(bar["o"], 4), round(bv, 2), round(cfee, 2)])
            elif not pending and shares > 0:
                val = shares * bar["o"]; cfee = val * COST + SELL_FEE
                cash += val - cfee; costs += cfee; shares = 0.0
                trades.append([d, "SELL", round(bar["o"], 4), round(val, 2), round(cfee, 2)])
            pending = None
        if d in checkmap and checkmap[d] != (shares > 0):
            pending = checkmap[d]
        eq = cash + shares * bar["c"]
        if shares > 0:
            days_invested += 1
        curve_out.append([d, round(eq, 4)])
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; cfee = val * COST + SELL_FEE
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(cfee, 2)])
        curve_out[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve_out:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(days), 1) if days else 0.0,
            "equity_curve": curve_out}


def buy_hold(bars, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    by_date = {b["d"]: b for b in bars}
    o = by_date[days[0]]["o"]; sh = (START / (1 + COST)) / o
    curve = [[d, round(sh * by_date[d]["c"], 4)] for d in days]
    val = sh * by_date[days[-1]]["c"]
    final = val - (val * COST + SELL_FEE)
    curve[-1] = [days[-1], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}


def period_stats_monthly(curve):
    if not curve:
        return None
    vals, last_key = [], None
    for d, v in curve:
        if d[:7] != last_key:
            vals.append(v); last_key = d[:7]
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst_streak = 0
    for r in rets:
        if r < 0:
            streak += 1; worst_streak = max(worst_streak, streak)
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
            "longest_losing_streak_months": worst_streak,
            "longest_between_highs_months": longest}


def main():
    bars = load_spy()
    months = monthly_closes(bars)
    curve, first_valid = coppock_series(months)
    sig_idx = buy_signals(months, curve)
    sig_events = [[months[t][0], round(curve[t], 3)] for t in sig_idx]
    print("first curve value:", months[first_valid][1], round(curve[first_valid], 3))
    print("all published buy signals (full history):", sig_events)

    out = {"family": "hunt-coppock (Coppock Curve, Barron's 1962)",
           "program": "v13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "form": "published buy (below-zero upturn, monthly SPY) + CONSTRUCTED minimal exit: HOLD TO ROAD END (labelled); no floor; all-in; costs 0.10%/side + $0.01 sell fee; decide month-end close, execute next open; fresh $100 cash pot per road, signals only inside the road",
           "first_curve_value": {"month": months[first_valid][1], "value": round(curve[first_valid], 3)},
           "buy_signals_full_history": sig_events,
           "curve_monthly": [[months[i][0], (round(curve[i], 4) if curve[i] is not None else None)]
                             for i in range(len(months))],
           "roads": {}}
    for name, (s, e) in ROADS.items():
        # my-rules targets: False until first in-road signal month, True after
        inroad = [t for t in sig_idx if s <= months[t][0] <= e]
        entry_t = inroad[0] if inroad else None
        targets = []
        for t in range(len(months)):
            targets.append(entry_t is not None and t >= entry_t)
        r = simulate_states(bars, months, targets, s, e)
        r["period_stats_monthly"] = period_stats_monthly(r["equity_curve"])
        r["entry_signal"] = ([months[entry_t][0], round(curve[entry_t], 3)] if entry_t is not None else None)
        bh = buy_hold(bars, s, e)
        # placebo 1: circular shift of monthly state within road (v12 convention)
        days0 = s
        pre = [i for i in range(len(months)) if months[i][0] < days0]
        rel_idx = (pre[-1:] if pre else []) + [i for i in range(len(months)) if s <= months[i][0] <= e]
        base_vals = [targets[i] for i in rel_idx]
        shift_finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            vals = list(base_vals)
            if len(vals) > 1:
                k = rng.randrange(1, len(vals))
                vals = vals[k:] + vals[:k]
            tmap = dict(zip(rel_idx, vals))
            tt = [tmap.get(i, targets[i]) for i in range(len(months))]
            shift_finals.append(simulate_states(bars, months, tt, s, e)["final"])
        # placebo 2: random-timing entry (uniform random month-end in road, hold to end)
        elig = [i for i in range(len(months)) if s <= months[i][0] < e]
        rand_finals = []
        for seed in range(1, 21):
            rng = random.Random(1000 + seed)
            et = rng.choice(elig)
            tt = [t >= et for t in range(len(months))]
            rand_finals.append(simulate_states(bars, months, tt, s, e)["final"])
        rec = {"best_rules": r,
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)", "final": bh["final"],
                                  "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats_monthly": period_stats_monthly(bh["equity_curve"])},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "v12_published_form_final": V12_FINAL,
               "placebo_shift": {"seed_finals": shift_finals,
                                 "beaten_of_20": sum(1 for p in shift_finals if r["final"] > p),
                                 "design": "circular shift of monthly in/out state within road; preserves invested-month fraction and episode lengths"},
               "placebo_random_timing": {"seed_finals": rand_finals,
                                         "beaten_of_20": sum(1 for p in rand_finals if r["final"] > p),
                                         "design": "uniform random entry month-end inside road, hold to road end, same costs; 20 seeds (1001-1020)"},
               "beats_champion": r["final"] > CHAMP[name]}
        out["roads"][name] = rec
        print(f"{name}: best-rules ${r['final']} (DD {r['max_dd_pct']}%, inv {r['invested_pct']}%, "
              f"orders {r['orders']}, entry {r['entry_signal']}) | hold ${bh['final']} | "
              f"shift placebos {rec['placebo_shift']['beaten_of_20']}/20 | "
              f"random-timing {rec['placebo_random_timing']['beaten_of_20']}/20 | champ ${CHAMP[name]}")
    out["confirmation"] = {"triggered": any(out["roads"][n]["beats_champion"] for n in ROADS),
                           "note": "Confirmation (fresh yearly folds + half-windows, bars frozen in spec) is required BEFORE any BEATS WHAT WE HAVE claim; run only if triggered."}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
