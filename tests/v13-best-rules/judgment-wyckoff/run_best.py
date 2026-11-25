#!/usr/bin/env python3
"""
V13 BEST-RULES — Wyckoff, JUDGMENT-CONSTRUCTED (permanently labeled).
Frozen per BEST-RULES-SPEC.md in this folder. Simulation only.
Reads ONLY cached data (read-only shared inputs). Writes only here.
"""
import json, os, sys, random, time
from bisect import bisect_right, insort, bisect_left
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as lr  # POOL only; no network calls used

START_CASH = 100.0
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
POS_FRAC = 0.20
FLOOR = None  # spec: NO portfolio floor — protection is the spring-low stop

def load_bars(ticker):
    path = os.path.join(LH, f"pxfull_{ticker}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        payload = json.load(f)
    try:
        res = payload["chart"]["result"][0]
    except Exception:
        return None
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        o, h, l = q["open"][i], q["high"][i], q["low"][i]
        v = q["volume"][i] or 0
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        bars.append({"d": d, "o": (o * r if o else a), "h": (h * r if h else a),
                     "l": (l * r if l else a), "c": a, "v": float(v)})
    bars.sort(key=lambda b: b["d"])
    out, seen = [], set()
    for b in bars:
        if b["d"] in seen:
            continue
        seen.add(b["d"])
        out.append(b)
    return out

class Series:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.idx = {b["d"]: i for i, b in enumerate(bars)}
        self.c = [b["c"] for b in bars]
        self.h = [b["h"] for b in bars]
        self.l = [b["l"] for b in bars]
        self.v = [b["v"] for b in bars]
        n = len(bars)
        pc = [0.0] * (n + 1)
        pv = [0.0] * (n + 1)
        for i in range(n):
            pc[i + 1] = pc[i] + self.c[i]
            pv[i + 1] = pv[i] + self.v[i]
        self.avg50v = [None] * n
        self.ma200 = [None] * n
        for i in range(n):
            if i >= 50:
                self.avg50v[i] = (pv[i] - pv[i - 50]) / 50
            if i >= 199:
                self.ma200[i] = (pc[i + 1] - pc[i - 199]) / 200
        self.span = [(self.h[i] - self.l[i]) / self.c[i] if self.c[i] > 0
                     else 0.0 for i in range(n)]
        self.span_med = [None] * n
        win = []
        for i in range(n):
            if i >= 50:
                self.span_med[i] = (win[25] if len(win) % 2
                                    else 0.5 * (win[24] + win[25]))
                out = self.span[i - 50]
                del win[bisect_left(win, out)]
            insort(win, self.span[i])
        # rolling stats anchored to a spring bar k:
        #   range window = [k-60, k-1]; pre-range high window = [k-312, k-61]
        self.rng_high = [None] * n
        self.rng_low = [None] * n
        self.pre_high = [None] * n
        dh, dl, dp = deque(), deque(), deque()
        for k in range(n):
            a = k - 1
            if a >= 0:
                while dh and self.h[dh[-1]] <= self.h[a]:
                    dh.pop()
                dh.append(a)
                while dl and self.l[dl[-1]] >= self.l[a]:
                    dl.pop()
                dl.append(a)
            while dh and dh[0] < k - 60:
                dh.popleft()
            while dl and dl[0] < k - 60:
                dl.popleft()
            if k >= 60 and dh and dl:
                self.rng_high[k] = self.h[dh[0]]
                self.rng_low[k] = self.l[dl[0]]
            b = k - 61
            if b >= 0:
                while dp and self.h[dp[-1]] <= self.h[b]:
                    dp.pop()
                dp.append(b)
            while dp and dp[0] < k - 312:
                dp.popleft()
            if k >= 312 and dp:
                self.pre_high[k] = self.h[dp[0]]

def find_candidates(s, spy):
    """BEST-RULES-SPEC: returns {entry_date: candidate} for one ticker."""
    bars = s.bars
    n = len(bars)
    out = {}
    last_spring = -10**9
    for k in range(312, n):
        if k - last_spring < 30:
            continue
        range_low = s.rng_low[k]
        range_high = s.rng_high[k]
        if range_low is None or range_low <= 0:
            continue
        # spring bar: undercut range low by <=5%
        if not (0.95 * range_low <= bars[k]["l"] < range_low):
            continue
        if (range_high - range_low) / range_low > 0.35:
            continue
        pre_high = s.pre_high[k]
        if not pre_high or (pre_high - range_low) / pre_high < 0.25:
            continue
        r_lo = k - 60
        # Phase A: selling climax in first 25 range bars
        climax = None
        for j in range(r_lo, r_lo + 25):
            b = bars[j]
            if s.avg50v[j] is None or s.span_med[j] is None:
                continue
            if (b["v"] >= 1.8 * s.avg50v[j]
                    and s.span[j] >= 2.0 * s.span_med[j]
                    and b["c"] >= 0.5 * (b["h"] + b["l"])):
                climax = j
                break
        if climax is None:
            continue
        # secondary test after climax, inside range
        st = False
        for j in range(climax + 1, k):
            if bars[j]["l"] <= 1.03 * range_low and bars[j]["v"] < bars[climax]["v"]:
                st = True
                break
        if not st:
            continue
        # effort-vs-result: spring effort below climax effort
        if not (bars[k]["v"] < bars[climax]["v"]):
            continue
        # recovery: first close back above range low within 3 bars (k..k+2)
        entry = None
        for m in range(k, min(k + 3, n)):
            if bars[m]["c"] > range_low:
                entry = m
                break
        if entry is None:
            continue
        # market gate at entry day
        j = bisect_right(spy.dates, bars[entry]["d"]) - 1
        if j < 220 or spy.ma200[j] is None or spy.ma200[j - 21] is None:
            continue
        if not (spy.c[j] > spy.ma200[j] > spy.ma200[j - 21]):
            continue
        fill = bars[entry]["c"]
        stop = bars[k]["l"]
        if fill <= stop:
            continue
        target = range_high + (range_high - range_low)
        j0 = bisect_right(spy.dates, bars[r_lo]["d"]) - 1
        rs = 0.0
        if j0 >= 0 and spy.c[j0] > 0 and s.c[r_lo] > 0:
            rs = (fill / s.c[r_lo] - 1) - (spy.c[j] / spy.c[j0] - 1)
        d = bars[entry]["d"]
        if d in out:
            continue
        out[d] = {"stop": stop, "target": target, "range_low": range_low,
                  "range_high": range_high, "spring_low": stop,
                  "spring_date": bars[k]["d"], "rs_margin": rs}
        last_spring = k
    return out

def simulate(days, series_by, cands, start, end,
             placebo_seed=None, real_entries=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    pos = {}
    curve, trades, entries_made = [], [], []
    total_costs = 0.0
    halted = None
    entry_plan = {}
    if rng is not None:
        for (d, sf, tf) in real_entries:
            entry_plan.setdefault(d, []).append((sf, tf))

    def equity(d):
        v = cash
        for t, p in pos.items():
            s = series_by[t]
            ii = s.idx.get(d)
            if ii is None:
                jj = bisect_right(s.dates, d) - 1
                px = s.c[jj] if jj >= 0 else 0.0
            else:
                px = s.c[ii]
            v += p["shares"] * px
        return v

    def buy(t, d, px, stop_px, target_px, range_low, why):
        nonlocal cash, total_costs
        budget = min(POS_FRAC * equity(d), cash / (1 + BUY_COST))
        if budget < 1.0 or px <= 0:
            return False
        sh = budget / px
        cst = budget * BUY_COST
        cash -= budget + cst
        total_costs += cst
        pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                  "stop": stop_px, "target": target_px, "rl": range_low}
        trades.append((d, t, "BUY", px, budget, why))
        entries_made.append((d, (px - stop_px) / px, (target_px - px) / px))
        return True

    for d in days:
        if not (start <= d <= end):
            continue
        for t in list(pos):
            s = series_by[t]
            ii = s.idx.get(d)
            if ii is None or d <= pos[t]["entry_date"]:
                continue
            p = pos[t]
            bar = s.bars[ii]
            sell_px, why = None, None
            if bar["l"] <= p["stop"]:
                sell_px = bar["o"] if bar["o"] < p["stop"] else p["stop"]
                why = "stop-spring-INVALIDATED"
            elif bar["c"] >= p["target"]:
                sell_px, why = bar["c"], "target-measured-move"
            elif (bar["c"] < p["rl"] and s.avg50v[ii] and
                  bar["v"] >= 1.5 * s.avg50v[ii]):
                sell_px, why = bar["c"], "sign-of-weakness-INVALIDATED"
            if sell_px is not None:
                val = p["shares"] * sell_px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", sell_px, val, why))
                del pos[t]
        if rng is None:
            if len(pos) < MAX_POS:
                day_c = []
                for t, cd in cands.items():
                    if d in cd and t not in pos:
                        day_c.append((cd[d]["rs_margin"], t, cd[d]))
                day_c.sort(reverse=True)
                for _m, t, cand in day_c:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    buy(t, d, px, cand["stop"], cand["target"],
                        cand["range_low"],
                        f"spring-recovery rs={round(cand['rs_margin'],3)}")
        else:
            for (sf, tf) in entry_plan.get(d, []):
                if len(pos) >= MAX_POS:
                    break
                pool = [t for t, s in series_by.items()
                        if d in s.idx and s.idx[d] >= 252 and t not in pos]
                if not pool:
                    break
                t = rng.choice(pool)
                s = series_by[t]
                px = s.bars[s.idx[d]]["c"]
                buy(t, d, px, px * (1 - sf), px * (1 + tf), px, "placebo")
        curve.append((d, equity(d)))
    for t in list(pos):
        s = series_by[t]
        if s.dates and s.dates[-1] >= end:
            px = s.c[s.idx[end]] if end in s.idx else s.c[-1]
            val = pos[t]["shares"] * px
            cst = val * SELL_COST + SELL_FEE
            cash += val - cst
            total_costs += cst
            trades.append((end, t, "SELL", px, val, "end"))
        else:
            trades.append((end, t, "SELL", 0.0, 0.0, "vanished-zero"))
        del pos[t]
    if curve:
        curve[-1] = (curve[-1][0], cash)
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted,
            "max_dd_pct": round(mdd * 100, 2),
            "curve": [[d, round(v, 2)] for d, v in curve],
            "trades": trades, "entries": entries_made}

def period_stats(curve):
    if len(curve) < 2:
        return {}
    rets = []
    for i in range(1, len(curve)):
        p = curve[i - 1][1]
        rets.append((curve[i][1] / p - 1) * 100 if p > 0 else 0.0)
    srt = sorted(rets)
    m = len(srt)
    med = srt[m // 2] if m % 2 else 0.5 * (srt[m // 2 - 1] + srt[m // 2])
    pos_share = sum(1 for r in rets if r > 0) / len(rets) * 100
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    peak = curve[0][1]
    last_high = 0
    max_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak = v
            max_gap = max(max_gap, i - last_high)
            last_high = i
    max_gap = max(max_gap, len(curve) - 1 - last_high)
    return {"periods": len(rets), "median_pct": round(med, 4),
            "share_positive_pct": round(pos_share, 1),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "avg_pct_secondary": round(sum(rets) / len(rets), 4),
            "longest_losing_streak_days": longest,
            "longest_stretch_between_new_highs_days": max_gap}

def trade_stats(trades):
    buys = {}
    wins = losses = 0
    stopped = sow = targeted = 0
    for (d, t, side, px, val, why) in trades:
        if side == "BUY":
            buys.setdefault(t, []).append(val + val * 0)  # budget spent approx
            buys[t][-1] = val  # position value at buy (budget)
        else:
            if why.startswith("stop-spring"):
                stopped += 1
            elif why.startswith("sign-of-weakness"):
                sow += 1
            elif why.startswith("target"):
                targeted += 1
    # win/loss by pairing sells with preceding buy value per ticker queue
    from collections import deque as dq
    q = {}
    pnl = []
    for (d, t, side, px, val, why) in trades:
        if side == "BUY":
            q.setdefault(t, dq()).append(val * 1.001)  # incl buy cost
        elif q.get(t):
            cost = q[t].popleft()
            pnl.append(val - 0.0 - cost if why != "vanished-zero" else -cost)
    wins = sum(1 for x in pnl if x > 0)
    losses = sum(1 for x in pnl if x <= 0)
    return {"round_trips": len(pnl), "wins": wins, "losses": losses,
            "win_rate_pct": round(100 * wins / len(pnl), 1) if pnl else None,
            "stopped_at_spring_low": stopped, "sign_of_weakness": sow,
            "target_hits": targeted}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def main():
    series_by, failures = {}, []
    for t in lr.POOL:
        bars = load_bars(t)
        if not bars or len(bars) < 400:
            failures.append((t, "no/short price cache"))
            continue
        series_by[t] = Series(bars)
    spy = series_by.get("SPY") or Series(load_bars("SPY"))
    series_by.setdefault("SPY", spy)
    print(f"universe: {len(series_by) - 1} names; failures: {len(failures)}", flush=True)
    cands = {}
    total = 0
    cand_log = []
    for t, s in series_by.items():
        if t == "SPY":
            continue
        cd = find_candidates(s, spy)
        cands[t] = cd
        total += len(cd)
        for d, c in cd.items():
            cand_log.append({"ticker": t, "entry_date": d, **c})
    print("candidate entry days total:", total, flush=True)
    results = {"label": "JUDGMENT-CONSTRUCTED (V13 best rules): frozen "
                        "reconstruction of Wyckoff's documented method; "
                        "not the author's own trading.",
               "universe_size": len(series_by) - 1, "failures": failures,
               "n_candidate_days": total, "candidates": cand_log,
               "roads": {}}
    for name, (start, end) in ROADS.items():
        days = [d for d in spy.dates if d <= end]
        r = simulate(days, series_by, cands, start, end)
        beaten, pfin = 0, []
        for seed in range(20):
            pr = simulate(days, series_by, cands, start, end,
                          placebo_seed=seed, real_entries=r["entries"])
            pfin.append(pr["final"])
            if r["final"] > pr["final"]:
                beaten += 1
        results["roads"][name] = {
            "start": start, "end": end, "final": r["final"],
            "costs": r["costs"], "orders": r["orders"], "halted": r["halted"],
            "max_dd_pct": r["max_dd_pct"], "n_entries": len(r["entries"]),
            "champion_vm": CHAMPION[name],
            "beats_champion": r["final"] > CHAMPION[name],
            "placebo_beaten": beaten, "placebo_finals": pfin,
            "period_stats_daily": period_stats(r["curve"]),
            "trade_stats": trade_stats(r["trades"]),
            "curve": r["curve"],
            "trades": [[d, t, sd, round(px, 4), round(v, 2), w]
                       for d, t, sd, px, v, w in r["trades"]]}
        print(f"{name}: final ${r['final']} entries {len(r['entries'])} "
              f"DD {r['max_dd_pct']}% placebo {beaten}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done")

if __name__ == "__main__":
    main()
