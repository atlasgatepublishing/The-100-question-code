#!/usr/bin/env python3
"""V13 BEST-RULES — hunt-fabian-maverick. Spec: BEST-RULES-SPEC.md (frozen
before this run). Fabian's three indexes (SPY/DIA/XLU-as-^DJU-fallback),
each vs its own 39-week weekly SMA; target exposure = (#above)/3, stateless,
weekly Friday-close decisions, next-session-open execution, SPY traded,
NO floor. Costs: 0.10%/side + $0.01 per sell order. $100 pot.
Placebos: 20-seed circular shift of the daily target-exposure series."""
import json, os, random, statistics, time
from datetime import date

START = 100.0
COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB = {"LONG": 317.56, "DECADE": 193.18, "CONT": 164.71, "VAL": 139.30}
HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
XLU_CSV = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/sector-rotation/data/XLU.csv")


def load_pxfull(ticker, path=None):
    p = path or os.path.join(PXDIR, f"pxfull_{ticker}.json")
    j = json.load(open(p))
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


def weekly_closes(bars):
    seen = {}
    for b in bars:
        y, m, d = map(int, b["d"].split("-"))
        iso = date(y, m, d).isocalendar()
        seen[(iso[0], iso[1])] = (b["d"], b["c"])
    return [seen[k] for k in sorted(seen)]


def weekly_closes_csv(path):
    import csv
    seen = {}
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            if len(row) < 2:
                continue
            y, m, d = map(int, row[0].split("-"))
            iso = date(y, m, d).isocalendar()
            seen[(iso[0], iso[1])] = (row[0], float(row[1]))
    return [seen[k] for k in sorted(seen)]


def sma_states(weekly, n=39):
    closes = [c for _, c in weekly]
    out = {}
    for i in range(len(weekly)):
        if i >= n - 1:
            sma = sum(closes[i - n + 1:i + 1]) / n
            y, m, d = map(int, weekly[i][0].split("-"))
            iso = date(y, m, d).isocalendar()
            out[(iso[0], iso[1])] = closes[i] > sma
    return out


def build_targets(spy):
    """Daily target-exposure series: after each week's close, target =
    count(above)/3 from that week's three states; applies from that close
    forward (execution handled by engine at next open)."""
    dia = load_pxfull("DIA", path=os.path.expanduser(
        "~/workspace/stock-app/backtests/v10-retest/folklore-f4-dowtheory/data/pxfull_DIA.json"))
    s_spy = sma_states(weekly_closes(spy))
    s_dia = sma_states(weekly_closes(dia))
    s_xlu = sma_states(weekly_closes_csv(XLU_CSV))
    week_last = {}
    week_of = []
    for i, b in enumerate(spy):
        y, m, d = map(int, b["d"].split("-"))
        iso = date(y, m, d).isocalendar()
        wk = (iso[0], iso[1])
        week_of.append(wk); week_last[wk] = i
    targets = [0.0] * len(spy)
    cur = 0.0
    for i in range(len(spy)):
        targets[i] = cur
        if week_last.get(week_of[i]) == i:
            wk = week_of[i]
            a, b_, c_ = s_spy.get(wk), s_dia.get(wk), s_xlu.get(wk)
            if a is not None and b_ is not None and c_ is not None:
                cur = (int(a) + int(b_) + int(c_)) / 3.0
    return targets


def simulate(bars, targets, start, end, shift_seed=None):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    tgt = list(targets)
    if shift_seed is not None:
        rng = random.Random(shift_seed)
        seg = [tgt[i] for i in idx]
        if len(seg) > 1:
            k = rng.randrange(1, len(seg))
            seg = seg[k:] + seg[:k]
            for j, i in enumerate(idx):
                tgt[i] = seg[j]
    # tgt[i] = exposure decided at the last completed weekly close before
    # bar i (build_targets changes the series only at week boundaries), so
    # the spec's "next session's open" execution = rebalance to tgt[i] at
    # bar i's open whenever it differs from the current position.
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    exp_days = 0.0
    last_tier = None  # rebalance ONLY on a tier change (spec: "only the
    # delta needed to reach the new target"); price drift within a tier
    # is not a trade. First bar always establishes the position.
    for pos, i in enumerate(idx):
        b = bars[i]
        eq_open = cash + shares * b["o"]
        want = tgt[i] * eq_open if tgt[i] != last_tier else shares * b["o"]
        have = shares * b["o"]
        last_tier = tgt[i]
        if want > have + 1e-9 and cash > 0:  # buy delta
            spend = min(want - have, cash)
            bv = spend / (1 + COST); fee = bv * COST
            shares += bv / b["o"]; cash -= bv + fee; costs += fee
            trades.append([b["d"], "BUY", round(b["o"], 6), round(bv, 2), round(fee, 2)])
        elif want < have - 1e-9:  # sell delta
            sell_val = have - want
            fee = sell_val * COST + SELL_FEE
            shares -= sell_val / b["o"]; cash += sell_val - fee; costs += fee
            if shares < 1e-12:
                shares = 0.0
            trades.append([b["d"], "SELL", round(b["o"], 6), round(sell_val, 2), round(fee, 2)])
        eq = cash + shares * b["c"]
        if eq > 0:
            exp_days += (shares * b["c"]) / eq
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
            "avg_exposure_pct": round(100.0 * exp_days / len(idx), 1) if idx else 0.0,
            "equity_curve": curve}


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    o = days[0]["o"]; sh = (START / (1 + COST)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * COST + SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}


def period_stats(curve, freq="weekly"):
    if not curve:
        return None
    def key(d):
        if freq == "monthly":
            return d[:7]
        if freq == "annual":
            return d[:4]
        y, m, dd = map(int, d.split("-"))
        iso = date(y, m, dd).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
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
    targets = build_targets(spy)
    out = {"family": "hunt-fabian-maverick", "program": "v13-best-rules",
           "form": "BEST-RULES: exposure = count(SPY,DIA,XLU above own 39wk SMA)/3, stateless weekly dial, SPY traded, no floor",
           "costs": "stocks 0.10%/side + $0.01 sell fee per sell order",
           "utility_series": "XLU weekly closes (printed fallback for ^DJU)",
           "coins": "NOT-APPLICABLE per spec",
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = simulate(spy, targets, s, e)
        bh = buy_hold(spy, s, e)
        finals = []
        for seed in range(1, 21):
            finals.append(simulate(spy, targets, s, e, shift_seed=seed)["final"])
        rec = {"best_rules": {**r, "period_stats": period_stats(r["equity_curve"], "weekly")},
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)",
                                  "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": period_stats(bh["equity_curve"], "weekly")},
               "placebo": {"seed_finals": finals,
                           "beaten_of_20": sum(1 for p in finals if r["final"] > p),
                           "design": "circular shift of daily target-exposure series within road (20 seeds)"},
               "published_v12_native_final": PUB[name],
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name]}
        out["roads"][name] = rec
        print(f"{name}: best ${r['final']} (DD {r['max_dd_pct']}%, avgExp {r['avg_exposure_pct']}%, orders {r['orders']}, placebos {rec['placebo']['beaten_of_20']}/20) | published ${PUB[name]} | hold ${bh['final']} | champ ${CHAMP[name]}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
