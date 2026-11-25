#!/usr/bin/env python3
"""v13 BEST RULES — hunt-fosback-nvi. Implements BEST-RULES-SPEC.md exactly
(frozen before this run): Fosback NVI on SPY; regime = NVI vs 255-day EMA
(published), tactical = NVI vs 50-day EMA; exposure dial 100/50/50/0 by
(regime, tactical); daily evaluation, tier changes execute next open;
NO floor; no short side. Costs 0.10%/side + $0.01 sell fee. Placebos:
circular-shift (20 seeds) + random-timing iid from the road's empirical
tier distribution (20 seeds). Confirmation bars per spec, evaluated only
if a road beats champion V+M."""
import json, os, time, random, statistics
from datetime import date

START = 100.0
COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
HERE = os.path.dirname(os.path.abspath(__file__))


def load_pxfull(ticker):
    j = json.load(open(os.path.join(PXDIR, f"pxfull_{ticker}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars


def ema_series(x, n):
    k = 2.0 / (n + 1)
    out = [x[0]] * len(x)
    for i in range(1, len(x)):
        out[i] = k * x[i] + (1 - k) * out[i - 1]
    return out


def targets_fn(bars):
    """Exposure target after close of each bar, per frozen spec."""
    n = len(bars)
    nvi = [100.0] * n
    for i in range(1, n):
        if bars[i]["v"] < bars[i - 1]["v"] and bars[i - 1]["c"] > 0:
            nvi[i] = nvi[i - 1] * (1 + (bars[i]["c"] - bars[i - 1]["c"]) / bars[i - 1]["c"])
        else:
            nvi[i] = nvi[i - 1]
    e255 = ema_series(nvi, 255)
    e50 = ema_series(nvi, 50)
    tgt = []
    for i in range(n):
        if i < 255:
            tgt.append(0.0)  # warm-up: regime average not established
            continue
        regime_up = nvi[i] > e255[i]
        tact_up = nvi[i] > e50[i]
        if regime_up and tact_up:
            tgt.append(1.0)
        elif regime_up or tact_up:
            tgt.append(0.5)
        else:
            tgt.append(0.0)
    return tgt


def simulate(bars, targets, start, end, mode=None, seed=None):
    """Fractional-exposure engine. targets[i] applies after close of
    bars[i]; changes execute at next bar's open. mode: None | 'shift' |
    'random' (placebo target generation within the road)."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if not idx:
        return None
    tgt = list(targets)
    if mode == "shift":
        rng = random.Random(seed)
        seg = [tgt[i] for i in idx]
        if len(seg) > 1:
            k = rng.randrange(1, len(seg))
            seg = seg[k:] + seg[:k]
            for j, i in enumerate(idx):
                tgt[i] = seg[j]
    elif mode == "random":
        rng = random.Random(seed)
        seg = [tgt[i] for i in idx]
        tiers = sorted(set(seg))
        weights = [seg.count(t) for t in tiers]
        for i in idx:
            tgt[i] = rng.choices(tiers, weights=weights)[0]
    # exposure carried into the road = last target before the road
    cur_target = 0.0
    for i in range(idx[0]):
        cur_target = tgt[i]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = cur_target if cur_target > 0 else None
    days_weighted = 0.0
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending is not None:
            eq_o = cash + shares * b["o"]
            desired_val = pending * eq_o
            cur_val = shares * b["o"]
            delta = desired_val - cur_val
            if delta > 0.01 and cash > 0:
                bv = min(delta / (1 + COST), cash / (1 + COST))
                fee = bv * COST
                shares += bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 6), round(bv, 2), round(fee, 2)])
            elif delta < -0.01 and shares > 0:
                val = min(-delta, shares * b["o"])
                fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; shares -= val / b["o"]
                trades.append([b["d"], "SELL", round(b["o"], 6), round(val, 2), round(fee, 2)])
            pending = None
        # rebalance (next open) when the target tier changes
        if tgt[i] != cur_target:
            pending = tgt[i]
            cur_target = tgt[i]
        eq = cash + shares * b["c"]
        if eq > 0:
            days_weighted += (shares * b["c"] / eq)
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        fee = val * COST + SELL_FEE
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 6), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "avg_exposure_pct": round(100.0 * days_weighted / len(idx), 1),
            "equity_curve": curve}


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    if not days:
        return None
    o = days[0]["o"]; sh = (START / (1 + COST)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]
    final = val - (val * COST + SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


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


def yearly_returns(curve):
    yrs = {}
    prev = START; lastv = {}
    order = []
    for d, v in curve:
        y = d[:4]
        if y not in lastv:
            order.append(y)
        lastv[y] = v
    out = {}
    for y in order:
        out[y] = round((lastv[y] / prev - 1.0) * 100.0, 2)
        prev = lastv[y]
    return out


def main():
    spy = load_pxfull("SPY")
    tgt = targets_fn(spy)
    out = {"family": "hunt-fosback-nvi (Fosback Negative Volume Index, 1976)",
           "program": "v13 BEST RULES — spec frozen before run (BEST-RULES-SPEC.md)",
           "form": "NVI vs 255EMA regime cap + NVI vs 50EMA tactical; dial 100/50/50/0; daily, next-open on tier change; NO floor; no short",
           "costs": "stocks 0.10%/side on traded amount + $0.01 sell fee",
           "verdict_ceiling": "CANDIDATE",
           "coins": "EXCLUDED — no volume series in program free coin caches; NVI undefined without volume (as v12)",
           "data_range": f"{spy[0]['d']} -> {spy[-1]['d']}",
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = simulate(spy, tgt, s, e)
        bh = buy_hold(spy, s, e)
        rec = {"best_rules": {**r, "period_stats": period_stats(r["equity_curve"])},
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)",
                                  "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": period_stats(bh["equity_curve"])},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "published_form_final_v12": SPYREF[name]}
        for mode, label in (("shift", "placebo_shift"), ("random", "placebo_random_timing")):
            finals = []
            for seed in range(1, 21):
                pr = simulate(spy, tgt, s, e, mode=mode, seed=seed)
                finals.append(pr["final"])
            rec[label] = {"seed_finals": finals,
                          "median": round(statistics.median(finals), 2),
                          "beaten_of_20": sum(1 for p in finals if r["final"] > p)}
        # confirmation bars — only meaningful if champion beaten
        if r["final"] > CHAMP[name]:
            days = [b["d"] for b in spy if s <= b["d"] <= e]
            mid = days[len(days) // 2]
            conf = {"midpoint": mid, "halves": {}, "yearly": {}}
            for hname, (hs, he) in (("H1", (s, mid)), ("H2", (mid, e))):
                hr = simulate(spy, tgt, hs, he)
                hb = buy_hold(spy, hs, he)
                conf["halves"][hname] = {"system": hr["final"], "hold": hb["final"],
                                         "beats_hold": hr["final"] > hb["final"]}
            ys = yearly_returns(r["equity_curve"]); yh = yearly_returns(bh["equity_curve"])
            wins = sum(1 for y in ys if y in yh and ys[y] > yh[y])
            conf["yearly"] = {"system": ys, "hold": yh,
                              "years_beating_hold": wins, "years_total": len(ys),
                              "majority": wins > len(ys) / 2}
            conf["confirmed"] = all(h["beats_hold"] for h in conf["halves"].values()) and conf["yearly"]["majority"]
            rec["confirmation"] = conf
        out["roads"][name] = rec
        print(f"{name}: best-rules ${r['final']} (DD {r['max_dd_pct']}%, avgExp {r['avg_exposure_pct']}%, "
              f"orders {r['orders']}, costs ${r['costs']}) | hold ${bh['final']} (DD {bh['max_dd_pct']}%) | "
              f"champ ${CHAMP[name]} | shift beaten {rec['placebo_shift']['beaten_of_20']}/20 | "
              f"random beaten {rec['placebo_random_timing']['beaten_of_20']}/20")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
