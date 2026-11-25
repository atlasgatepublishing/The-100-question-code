#!/usr/bin/env python3
"""V13 BEST RULES — hunt-fosback-hlli. Implements BEST-RULES-SPEC.md EXACTLY
(frozen before this run):
- HLLI weekly from the program PIT stack (155 pxfull names), counts from
  INTRAWEEK extremes (any daily high/low in the ISO week vs the name's
  prior 260 trading days), denominator = eligible names (>=240 prior bars).
- 10-week EMA smoothing (published).
- Bearish trigger: smoothed HLLI >= 90th percentile of its trailing
  260-week history (min 104 weeks history). Default state LONG.
- Re-entry: smoothed < trailing median OR 13 weeks in cash, first hit.
- SPY all-in/all-out, weekly decisions at week close -> next open.
- NO price floor. Program costs 0.10%/side + $0.01 sell fee. $100 pots.
- Placebos: 20-seed circular shift + 20-seed random-timing (same cash
  episode count/lengths, random placement)."""
import json, os, time, random, statistics, glob
from datetime import date
from collections import deque

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
HERE = os.path.dirname(os.path.abspath(__file__))


def load_pxfull(ticker):
    p = os.path.join(PXDIR, f"pxfull_{ticker}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars


def simulate(bars, targets, start, end, cost=STK_COST, sell_fee=STK_SELL_FEE,
             shift_seed=None, override_targets=None):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if not idx:
        return None
    tgt = list(override_targets) if override_targets is not None else list(targets)
    if shift_seed is not None:
        rng = random.Random(shift_seed)
        seg = [tgt[i] for i in idx]
        if len(seg) > 1:
            k = rng.randrange(1, len(seg))
            seg = seg[k:] + seg[:k]
            for j, i in enumerate(idx):
                tgt[i] = seg[j]
    desired = False
    for i in range(idx[0]):
        desired = tgt[i]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired if desired else None
    days_invested = 0
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending is not None:
            if pending and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); cfee = bv * cost
                shares = bv / b["o"]; cash -= bv + cfee; costs += cfee
                trades.append([b["d"], "BUY", round(b["o"], 6), round(bv, 2), round(cfee, 2)])
            elif not pending and shares > 0:
                val = shares * b["o"]; cfee = val * cost + sell_fee
                cash += val - cfee; costs += cfee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 6), round(val, 2), round(cfee, 2)])
            pending = None
        if tgt[i] != (shares > 0):
            pending = tgt[i]
        eq = cash + shares * b["c"]
        if shares > 0:
            days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        cfee = val * cost + sell_fee
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 6), round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(idx), 1),
            "equity_curve": curve}


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    o = days[0]["o"]; sh = (START / (1 + STK_COST)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]
    final = val - (val * STK_COST + STK_SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


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


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos); hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def name_week_extremes(bars):
    """Returns dict weekkey -> (is_new_high, is_new_low) using intraweek
    extremes vs prior 260 trading days; only weeks with >=240 prior bars."""
    n = len(bars)
    # sliding-window max of h / min of l over bars[i-260:i], evaluated at i
    win_max = [None] * n; win_min = [None] * n
    dqmax = deque(); dqmin = deque()
    for i in range(n):
        # window for index i covers [i-260, i-1]; add bar i-1 as we advance
        j = i - 1
        if j >= 0:
            while dqmax and bars[dqmax[-1]]["h"] <= bars[j]["h"]:
                dqmax.pop()
            dqmax.append(j)
            while dqmin and bars[dqmin[-1]]["l"] >= bars[j]["l"]:
                dqmin.pop()
            dqmin.append(j)
        while dqmax and dqmax[0] < i - 260:
            dqmax.popleft()
        while dqmin and dqmin[0] < i - 260:
            dqmin.popleft()
        if i >= 240 and dqmax:
            win_max[i] = bars[dqmax[0]]["h"]; win_min[i] = bars[dqmin[0]]["l"]
    out = {}
    i = 0
    while i < n:
        y, m, d = map(int, bars[i]["d"].split("-"))
        iso = date(y, m, d).isocalendar()
        wk = (iso[0], iso[1])
        j = i
        wh = -1e18; wl = 1e18
        while j < n:
            y2, m2, d2 = map(int, bars[j]["d"].split("-"))
            iso2 = date(y2, m2, d2).isocalendar()
            if (iso2[0], iso2[1]) != wk:
                break
            wh = max(wh, bars[j]["h"]); wl = min(wl, bars[j]["l"])
            j += 1
        if win_max[i] is not None:
            out[wk] = (wh > win_max[i], wl < win_min[i])
        i = j
    return out


def random_timing_targets(bars, targets, start, end, seed):
    """Cash episodes (runs of False) inside the road keep count+lengths;
    placed at uniformly random non-overlapping positions in the road."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    seg = [targets[i] for i in idx]
    lengths = []
    run = 0
    for v in seg:
        if not v:
            run += 1
        elif run:
            lengths.append(run); run = 0
    if run:
        lengths.append(run)
    tgt = list(targets)
    for i in idx:
        tgt[i] = True
    if not lengths:
        return tgt
    rng = random.Random(1000 + seed)
    N = len(idx)
    for _ in range(200):
        placed = []
        ok = True
        order = lengths[:]
        rng.shuffle(order)
        occupied = [False] * N
        for L in order:
            tries = 0
            done = False
            while tries < 500:
                s = rng.randrange(0, N - L + 1)
                if not any(occupied[s:s + L]):
                    for k in range(s, s + L):
                        occupied[k] = True
                    placed.append((s, L)); done = True; break
                tries += 1
            if not done:
                ok = False; break
        if ok:
            for s, L in placed:
                for k in range(s, s + L):
                    tgt[idx[k]] = False
            return tgt
    return tgt  # fallback: all-long (printed if used)


def main():
    out = {"family": "hunt-fosback-hlli (Fosback High-Low Logic Index) — V13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "costs": "stocks 0.10%/side + $0.01 sell fee", "stocks": {}}
    # ---- Build HLLI from intraweek extremes over the PIT stack ----
    counts = {}  # wk -> [highs, lows, total]
    names = 0
    for p in sorted(glob.glob(os.path.join(PXDIR, "pxfull_*.json"))):
        tick = os.path.basename(p)[7:-5]
        try:
            bars = load_pxfull(tick)
        except Exception:
            continue
        names += 1
        for wk, (nh, nl) in name_week_extremes(bars).items():
            c = counts.setdefault(wk, [0, 0, 0])
            c[2] += 1
            if nh:
                c[0] += 1
            if nl:
                c[1] += 1
    weeks_sorted = sorted(w for w, c in counts.items() if c[2] > 0)
    raw = {wk: min(counts[wk][0] / counts[wk][2], counts[wk][1] / counts[wk][2])
           for wk in weeks_sorted}
    k = 2.0 / (10 + 1)
    ema = None; smooth = {}; smooth_list = []
    for wk in weeks_sorted:
        ema = raw[wk] if ema is None else k * raw[wk] + (1 - k) * ema
        smooth[wk] = ema; smooth_list.append(ema)
    out["hlli_series"] = {
        "universe_names": names, "weeks": len(weeks_sorted),
        "first_week": str(weeks_sorted[0]), "last_week": str(weeks_sorted[-1]),
        "raw_max": round(max(raw.values()), 4),
        "smoothed_max": round(max(smooth.values()), 4),
        "smoothed_min": round(min(smooth.values()), 4),
        "construction": "intraweek extremes vs prior 260 trading days; >=240 prior bars"}
    print("HLLI:", out["hlli_series"])
    # ---- State machine (spec rules 2-3) ----
    decisions = {}
    state = True  # default LONG
    cash_weeks = 0
    n_triggers = 0
    for ti, wk in enumerate(weeks_sorted):
        hist = smooth_list[max(0, ti - 260):ti]
        if len(hist) >= 104:
            hs = sorted(hist)
            q90 = quantile(hs, 0.90); med = quantile(hs, 0.50)
            if state and smooth[wk] >= q90:
                state = False; cash_weeks = 0; n_triggers += 1
            elif not state:
                cash_weeks += 1
                if smooth[wk] < med or cash_weeks >= 13:
                    state = True; cash_weeks = 0
        decisions[wk] = state
    out["state_machine"] = {"bearish_triggers_total": n_triggers,
                            "weeks_in_cash_total": sum(1 for v in decisions.values() if not v),
                            "weeks_total": len(decisions)}
    print("STATE:", out["state_machine"])
    # ---- Map weekly decisions onto SPY daily targets ----
    spy = load_pxfull("SPY")
    week_last = {}; week_of = {}
    for i, b in enumerate(spy):
        y, m, d = map(int, b["d"].split("-"))
        iso = date(y, m, d).isocalendar()
        week_last[(iso[0], iso[1])] = i
        week_of[i] = (iso[0], iso[1])
    targets = [True] * len(spy)  # default LONG incl. warmup
    cur = True
    for i in range(len(spy)):
        targets[i] = cur
        wk = week_of[i]
        if week_last.get(wk) == i and wk in decisions:
            cur = decisions[wk]
    # ---- Roads ----
    roads = {}
    for name, (s, e) in ROADS.items():
        r = simulate(spy, targets, s, e)
        bh = buy_hold(spy, s, e)
        shift_finals = []
        for seed in range(1, 21):
            pr = simulate(spy, targets, s, e, shift_seed=seed)
            shift_finals.append(pr["final"])
        rt_finals = []
        for seed in range(1, 21):
            rt = random_timing_targets(spy, targets, s, e, seed)
            pr = simulate(spy, targets, s, e, override_targets=rt)
            rt_finals.append(pr["final"])
        rec = {"best_rules": {**r, "period_stats": period_stats(r["equity_curve"], "weekly")},
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)",
                                  "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": period_stats(bh["equity_curve"], "weekly")},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "placebo_shift": {"seed_finals": shift_finals,
                                 "beaten_of_20": sum(1 for p in shift_finals if r["final"] > p),
                                 "median": round(statistics.median(shift_finals), 2)},
               "placebo_random_timing": {"seed_finals": rt_finals,
                                         "beaten_of_20": sum(1 for p in rt_finals if r["final"] > p),
                                         "median": round(statistics.median(rt_finals), 2),
                                         "design": "same cash-episode count and lengths as the real run in this road, uniformly random non-overlapping placement, 20 seeds"}}
        roads[name] = rec
        print(f"SPY {name}: best ${r['final']} (DD {r['max_dd_pct']}%, inv {r['invested_pct']}%, "
              f"orders {r['orders']}) | hold ${bh['final']} | shift {rec['placebo_shift']['beaten_of_20']}/20 "
              f"(med ${rec['placebo_shift']['median']}) | randtime {rec['placebo_random_timing']['beaten_of_20']}/20 "
              f"(med ${rec['placebo_random_timing']['median']}) | champ ${CHAMP[name]}")
    out["stocks"]["SPY"] = {"data_range": f"{spy[0]['d']} -> {spy[-1]['d']}", "roads": roads}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
