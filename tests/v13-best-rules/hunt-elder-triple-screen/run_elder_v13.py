#!/usr/bin/env python3
"""v13 BEST RULES — Elder Triple Screen, per BEST-RULES-SPEC.md (frozen pre-run).
Kept: Screen 1 weekly MACD(12,26,9) histogram RISING permits longs;
Screen 2 2-day EMA Force Index < 0 fires entry.
Cut: Screen 3 buy-stop (enter NEXT OPEN after fire), tight per-trade stop,
30-session cap, any-week hist-decline exit.
Exit: next open after last completed weekly histogram goes BELOW ZERO.
No floor. Costs 0.10%/side + $0.01 sell fee. Placebos: 20-seed circular
shift of the Screen-2 fire series within the road."""
import json, os, time, random, statistics
from datetime import date

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB = {"LONG": 188.46, "DECADE": 146.94, "CONT": 153.36, "VAL": 119.42}
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
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": adj[i], "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars


def ema_series(vals, n):
    out = [None] * len(vals); k = 2.0 / (n + 1); s = None
    for i, v in enumerate(vals):
        s = v if s is None else k * v + (1 - k) * s
        out[i] = s
    return out


def weekly_signals(bars):
    """Per-day (hist_rising, hist_negative) from last COMPLETED weekly bar."""
    weeks = {}; order = []
    for i, b in enumerate(bars):
        y, m, d = map(int, b["d"].split("-"))
        iso = date(y, m, d).isocalendar(); key = (iso[0], iso[1])
        if key not in weeks:
            weeks[key] = {"last_i": i, "close": b["c"]}; order.append(key)
        weeks[key]["last_i"] = i; weeks[key]["close"] = b["c"]
    closes = [weeks[k]["close"] for k in order]
    e12 = ema_series(closes, 12); e26 = ema_series(closes, 26)
    macd = [(a - b) if a is not None and b is not None else None for a, b in zip(e12, e26)]
    sig = ema_series([m if m is not None else 0.0 for m in macd], 9)
    hist = [(macd[i] - sig[i]) if macd[i] is not None else None for i in range(len(closes))]
    rising = [False] * len(bars); neg = [False] * len(bars)
    for wi, key in enumerate(order):
        if wi < 34 or hist[wi] is None or hist[wi - 1] is None:
            continue
        start_i = weeks[key]["last_i"] + 1
        end_i = (weeks[order[wi + 1]]["last_i"] + 1) if wi + 1 < len(order) else len(bars)
        for i in range(start_i, min(end_i, len(bars))):
            rising[i] = hist[wi] > hist[wi - 1]
            neg[i] = hist[wi] < 0
    return rising, neg


def sim(bars, start, end, shift_seed=None):
    n = len(bars)
    rising, neg = weekly_signals(bars)
    fi = [0.0] * n
    for i in range(1, n):
        fi[i] = (bars[i]["c"] - bars[i - 1]["c"]) * bars[i]["v"]
    fi2 = ema_series(fi, 2)
    fire = [rising[i] and (fi2[i] is not None and fi2[i] < 0) for i in range(n)]
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not idx:
        return None
    if shift_seed is not None:
        rng = random.Random(shift_seed)
        seg = [fire[i] for i in idx]
        if len(seg) > 1:
            k = rng.randrange(1, len(seg)); seg = seg[k:] + seg[:k]
            for j, i in enumerate(idx):
                fire[i] = seg[j]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = None  # True=buy, False=sell at next open
    days_invested = 0
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending is True and shares == 0.0:
            bv = cash / (1 + STK_COST); cfee = bv * STK_COST
            shares = bv / b["o"]; cash -= bv + cfee; costs += cfee
            trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(cfee, 2)])
            pending = None
        elif pending is False and shares > 0:
            val = shares * b["o"]; cfee = val * STK_COST + STK_SELL_FEE
            cash += val - cfee; costs += cfee; shares = 0.0
            trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(cfee, 2)])
            pending = None
        # decisions at close
        if shares == 0.0 and fire[i]:
            pending = True
        elif shares > 0 and neg[i]:
            pending = False
        eq = cash + shares * b["c"]
        if shares > 0:
            days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        cfee = val * STK_COST + STK_SELL_FEE
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(idx), 1), "equity_curve": curve}


def buy_hold(bars, start, end):
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    o = days[0]["o"]; sh = (START / (1 + STK_COST)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * STK_COST + STK_SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}


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


def main():
    spy = load_pxfull("SPY")
    out = {"family": "hunt-elder-triple-screen (Elder Triple Screen) — v13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "rules": "Screen1 weekly MACD hist rising + Screen2 FI(2EMA)<0 -> buy next open; exit next open when weekly hist < 0; Screen 3 cut; no stop, no cap, no floor",
           "costs": "stocks 0.10%/side + $0.01 sell fee",
           "champions_vm": CHAMP, "spy_program_ref": SPYREF, "published_v12_native": PUB,
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = sim(spy, s, e)
        bh = buy_hold(spy, s, e)
        finals = [sim(spy, s, e, shift_seed=sd)["final"] for sd in range(1, 21)]
        rec = {"mine": {**r, "period_stats": period_stats(r["equity_curve"])},
               "benchmark_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": period_stats(bh["equity_curve"])},
               "placebo": {"seed_finals": finals,
                           "beaten_of_20": sum(1 for p in finals if r["final"] > p),
                           "design": "circular shift of daily Screen-2 fire series within road (20 seeds)"},
               "champion_vm": CHAMP[name], "published_v12": PUB[name], "spy_ref": SPYREF[name]}
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} (DD {r['max_dd_pct']}%, inv {r['invested_pct']}%, orders {r['orders']}, costs ${r['costs']}, placebos {rec['placebo']['beaten_of_20']}/20) | published ${PUB[name]} | SPY ${bh['final']} | champ ${CHAMP[name]}")
    # confirmation trigger check
    beats = [n for n in ROADS if out["roads"][n]["mine"]["final"] > CHAMP[n]]
    out["beats_champion_roads"] = beats
    if beats:
        conf = {}
        for name in beats:
            s, e = ROADS[name]
            yrs = sorted(set(d[:4] for d, _ in out["roads"][name]["mine"]["equity_curve"]))
            folds = {}
            for y in yrs:
                fr = sim(spy, f"{y}-01-01", f"{y}-12-31")
                folds[y] = fr["final"] if fr else None
            curve = out["roads"][name]["mine"]["equity_curve"]
            mid = curve[len(curve) // 2][0]
            h1 = sim(spy, s, mid); h2 = sim(spy, mid, e)
            b1 = buy_hold(spy, s, mid); b2 = buy_hold(spy, mid, e)
            fold_vals = [v for v in folds.values() if v is not None]
            conf[name] = {"yearly_folds": folds,
                          "median_fold": round(statistics.median(fold_vals), 2),
                          "folds_pass_median_gt_100": statistics.median(fold_vals) > 100,
                          "half1": {"mine": h1["final"], "spy": b1["final"]},
                          "half2": {"mine": h2["final"], "spy": b2["final"]},
                          "halves_pass": h1["final"] > 100 and h2["final"] > 100 and h1["final"] > b1["final"] and h2["final"] > b2["final"]}
        out["confirmation"] = conf
        print("CONFIRMATION:", json.dumps(conf, indent=1))
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE beats_champion:", beats)


if __name__ == "__main__":
    main()
