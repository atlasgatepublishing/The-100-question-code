#!/usr/bin/env python3
"""
V12 JUDGMENT-CONSTRUCTED WYCKOFF — frozen per JUDGMENT-SPEC.md.
JUDGMENT-CONSTRUCTED: our frozen reconstruction of the author's documented
decision-making; not the author's own trading.
Simulation only. Reads ONLY cached data (read-only). Writes only here.
"""
import json, os, sys, random, time
from bisect import bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as lr  # POOL only; no network calls used

START_CASH = 100.0
FLOOR = 85.0
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
POS_FRAC = 0.20

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
        # prefix sums for O(1) window means
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
        # intraday span and its rolling 50-bar median (for the climax test)
        self.span = [(self.h[i] - self.l[i]) / self.c[i] if self.c[i] > 0
                     else 0.0 for i in range(n)]
        from bisect import insort, bisect_left
        self.span_med = [None] * n
        win = []
        for i in range(n):
            if i >= 50:
                self.span_med[i] = (win[25] if len(win) % 2
                                    else 0.5 * (win[24] + win[25]))
                out = self.span[i - 50]
                del win[bisect_left(win, out)]
            insort(win, self.span[i])
        # rolling range stats for a candidate entry index i: range window
        # [i-89, i-30]; pre-range 252-bar high window [i-341, i-90]
        from collections import deque
        self.rng_high = [None] * n
        self.rng_low = [None] * n
        self.pre_high = [None] * n
        dh, dl, dp = deque(), deque(), deque()
        for i in range(n):
            a = i - 30
            if a >= 0:
                while dh and self.h[dh[-1]] <= self.h[a]:
                    dh.pop()
                dh.append(a)
                while dl and self.l[dl[-1]] >= self.l[a]:
                    dl.pop()
                dl.append(a)
            while dh and dh[0] < i - 89:
                dh.popleft()
            while dl and dl[0] < i - 89:
                dl.popleft()
            if i >= 89 and dh and dl:
                self.rng_high[i] = self.h[dh[0]]
                self.rng_low[i] = self.l[dl[0]]
            b = i - 90
            if b >= 0:
                while dp and self.h[dp[-1]] <= self.h[b]:
                    dp.pop()
                dp.append(b)
            while dp and dp[0] < i - 341:
                dp.popleft()
            if i >= 341 and dp:
                self.pre_high[i] = self.h[dp[0]]
        # fractal swing lows (5-bar), value at center index
        self.swing_lows = []  # (idx, low)
        for j in range(2, n - 2):
            if self.l[j] <= min(self.l[k] for k in range(j - 2, j + 3)):
                self.swing_lows.append((j, self.l[j]))

def median(xs):
    xs = sorted(xs)
    m = len(xs)
    return xs[m // 2] if m % 2 else 0.5 * (xs[m // 2 - 1] + xs[m // 2])

def pf_columns(s, lo_i, hi_i, base):
    """Mechanical 3-box P&F column count over closes[lo_i:hi_i+1],
    box = 1% of base (JUDGMENT-SPEC B5/T9, documented count formula)."""
    box = 0.01 * base
    if box <= 0:
        return 0
    cols = 1
    direction = 0  # +1 X column, -1 O column
    extreme = s.c[lo_i]
    anchor = s.c[lo_i]
    for k in range(lo_i + 1, hi_i + 1):
        px = s.c[k]
        if direction == 0:
            if px >= anchor + box:
                direction = 1
                extreme = px
            elif px <= anchor - box:
                direction = -1
                extreme = px
        elif direction == 1:
            if px > extreme:
                extreme = px
            elif px <= extreme - 3 * box:
                cols += 1
                direction = -1
                extreme = px
        else:
            if px < extreme:
                extreme = px
            elif px >= extreme + 3 * box:
                cols += 1
                direction = 1
                extreme = px
    return cols

def find_candidate(s, spy, i):
    """JUDGMENT-SPEC B0-B6 at entry day index i. Returns dict or None."""
    bars = s.bars
    if i < 320 or s.avg50v[i] is None:
        return None
    # B0 market gate: SPY above rising 200d (prior SPY bar <= today)
    j = bisect_right(spy.dates, bars[i]["d"]) - 1
    if j < 220 or spy.ma200[j] is None or spy.ma200[j - 21] is None:
        return None
    if not (spy.c[j] > spy.ma200[j] > spy.ma200[j - 21]):
        return None
    # Phase C construction (spec amendment #2): range anchored to the
    # entry (test) day; spring + test in the 30 bars after the range.
    r_lo_i, r_hi_i = i - 89, i - 30
    if r_lo_i < 252:
        return None
    range_high = s.rng_high[i]
    range_low = s.rng_low[i]
    if range_high is None:
        return None
    if range_low <= 0 or (range_high - range_low) / range_low > 0.35:
        return None
    # B1 prior decline >=25% from 252-bar high before range to range low
    pre_high = s.pre_high[i] or range_high
    if pre_high <= 0 or (pre_high - range_low) / pre_high < 0.25:
        return None
    if True:
        sos = i  # anchor retained for candidate identity (test day)
        # B2 climax + secondary test in range
        climax = None
        for k in range(r_lo_i, r_lo_i + 25):
            b = bars[k]
            if s.avg50v[k] is None or b["v"] < 1.8 * s.avg50v[k]:
                continue
            if s.span_med[k] is None:
                continue
            span = (b["h"] - b["l"]) / b["c"] if b["c"] > 0 else 0
            if span >= 2.0 * s.span_med[k] and b["c"] >= 0.5 * (b["h"] + b["l"]):
                climax = k
                break
        if climax is None:
            return None
        st_low = None
        for k in range(climax + 1, r_hi_i + 1):
            if bars[k]["l"] <= 1.03 * range_low and bars[k]["v"] < bars[climax]["v"]:
                st_low = bars[k]["l"]
                break
        if st_low is None:
            return None
        # B3 spring in (range_end, entry day); recovery within 3 bars
        spring_low = None
        spring_idx = None
        spring_vol = None
        for k in range(r_hi_i + 1, i - 1):
            if bars[k]["l"] < range_low and bars[k]["l"] >= 0.95 * range_low:
                for m in range(k, min(k + 3, i)):
                    if bars[m]["c"] > range_low:
                        spring_low = bars[k]["l"]
                        spring_idx = k
                        spring_vol = bars[k]["v"]
                        break
                if spring_low is not None:
                    break
        if spring_low is None:
            return None
        # B4 the test: today retests the spring area quietly
        tb = bars[i]
        if not (tb["l"] >= spring_low and tb["l"] <= 1.02 * range_low and
                tb["v"] < spring_vol and tb["c"] > spring_low and
                i > spring_idx + 1):
            return None
        fill = tb["c"]
        stop = spring_low
        cols = pf_columns(s, r_lo_i, r_hi_i, range_low)
        target = range_low + cols * (0.01 * range_low) * 3
        if fill <= stop:
            return None
        # B5 T9 mandatory 3:1
        if (target - fill) / (fill - stop) < 3.0:
            return None
        # T3 bullish activity, last 30 bars
        up_v, dn_v = [], []
        for m in range(i - 30, i):
            if s.c[m] > s.c[m - 1]:
                up_v.append(s.v[m])
            elif s.c[m] < s.c[m - 1]:
                dn_v.append(s.v[m])
        t3 = bool(up_v and dn_v and
                  sum(up_v) / len(up_v) > sum(dn_v) / len(dn_v))
        # T5 higher lows (spec B5): test low >= secondary-test low
        t5 = tb["l"] >= st_low
        # T7 stronger than market over the range window
        j0 = bisect_right(spy.dates, bars[r_lo_i]["d"]) - 1
        t7 = False
        t7_margin = None
        if j0 >= 0 and spy.c[j0] > 0 and s.c[r_lo_i] > 0:
            t7_margin = (fill / s.c[r_lo_i] - 1) - (spy.c[j] / spy.c[j0] - 1)
            t7 = t7_margin > 0
        if sum([t3, t5, t7]) < 2:
            return None
        return {"sos_idx": sos, "range_high": range_high,
                "range_low": range_low, "stop": stop,
                "target": target, "t7_margin": t7_margin or 0.0,
                "tests": {"T3": t3, "T5": t5, "T7": t7}}
    return None

def simulate(days, series_by, cands, start, end, spy,
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

    def buy(t, d, px, stop_px, target_px, range_high, why):
        nonlocal cash, total_costs
        budget = min(POS_FRAC * equity(d), cash / (1 + BUY_COST))
        if budget < 1.0 or px <= 0:
            return False
        sh = budget / px
        cst = budget * BUY_COST
        cash -= budget + cst
        total_costs += cst
        pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                  "stop": stop_px, "target": target_px, "rh": range_high}
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
                why = "stop-spring"
            elif bar["c"] >= p["target"]:
                sell_px, why = bar["c"], "target-pf-count"
            elif (bar["c"] < p["rh"] and s.avg50v[ii] and
                  bar["v"] >= 1.5 * s.avg50v[ii]):
                sell_px, why = bar["c"], "sign-of-weakness"
            if sell_px is not None:
                val = p["shares"] * sell_px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", sell_px, val, why))
                del pos[t]
        eq = equity(d)
        if eq <= FLOOR:
            for t in list(pos):
                s = series_by[t]
                jj = bisect_right(s.dates, d) - 1
                px = s.c[jj] if jj >= 0 else 0.0
                val = pos[t]["shares"] * px
                cst = val * SELL_COST + SELL_FEE if val > 0 else 0.0
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", px, val, "floor"))
                del pos[t]
            halted = d
            curve.append((d, cash))
            break
        if rng is None:
            if len(pos) < MAX_POS:
                day_c = []
                for t, cd in cands.items():
                    if d in cd and t not in pos:
                        day_c.append((cd[d]["t7_margin"], t, cd[d]))
                day_c.sort(reverse=True)
                for _m, t, cand in day_c:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    buy(t, d, px, cand["stop"], cand["target"],
                        cand["range_low"], f"spring-test t7={round(cand['t7_margin'],3)}")
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
    if halted is None:
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

ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}

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
    used_sos = {}
    for t, s in series_by.items():
        if t == "SPY":
            continue
        cd = {}
        for i in range(len(s.bars)):
            c = find_candidate(s, spy, i)
            if c is not None:
                key = (t, c["sos_idx"])
                if used_sos.get(key):
                    continue
                # one candidate per SOS: first LPS day only
                used_sos[key] = True
                cd[s.bars[i]["d"]] = c
        cands[t] = cd
        total += len(cd)
    print("candidate LPS entry days total:", total, flush=True)
    results = {"label": "JUDGMENT-CONSTRUCTED: our frozen reconstruction of "
                        "the author's documented decision-making; not the "
                        "author's own trading.",
               "universe_size": len(series_by) - 1, "failures": failures,
               "roads": {}}
    for name, (start, end) in ROADS.items():
        days = [d for d in spy.dates if d <= end]
        r = simulate(days, series_by, cands, start, end, spy)
        spy_days = [d for d in spy.dates if start <= d <= end]
        s0 = spy.c[spy.idx[spy_days[0]]]
        s1 = spy.c[spy.idx[spy_days[-1]]]
        spy_final = round(100 * (s1 / s0) * (1 - 0.001) - 0.01 * (s1 / s0), 2)
        beaten, pfin = 0, []
        for seed in range(20):
            pr = simulate(days, series_by, cands, start, end, spy,
                          placebo_seed=seed, real_entries=r["entries"])
            pfin.append(pr["final"])
            if r["final"] > pr["final"]:
                beaten += 1
        results["roads"][name] = {
            "start": start, "end": end, "final": r["final"],
            "costs": r["costs"], "orders": r["orders"], "halted": r["halted"],
            "max_dd_pct": r["max_dd_pct"], "n_entries": len(r["entries"]),
            "spy_final_same_chassis": spy_final,
            "placebo_beaten": beaten, "placebo_finals": pfin,
            "curve": r["curve"],
            "trades": [[d, t, sd, round(px, 4), round(v, 2), w]
                       for d, t, sd, px, v, w in r["trades"]]}
        print(f"{name}: final ${r['final']} entries {len(r['entries'])} "
              f"halted {r['halted']} DD {r['max_dd_pct']}% placebo "
              f"{beaten}/20 SPY {spy_final}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done")

if __name__ == "__main__":
    main()
