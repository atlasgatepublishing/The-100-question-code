#!/usr/bin/env python3
"""v13 BEST-RULES — F-5 Ichimoku. Spec: BEST-RULES-SPEC.md (frozen before run).
Entry: close > cloud top AND Tenkan > Kijun. Exit: close < cloud bottom ONLY.
Daily, SPY, 9/26/52, no floor. Costs 0.10%/side + $0.01 sell fee. Next-open exec.
Plumbing adapted from v11 native engine (read-only shared input).
"""
import json, os, time, random

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
WINDOWS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}

def load_bars(path):
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c, h, l = q["open"][i], q["close"][i], q["high"][i], q["low"][i]
        if None in (o, c, h, l): continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o*r, "c": a, "h": h*r, "l": l*r, "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"]); return bars

want_by_date = {}

def run_state(bars, start, end):
    cash, shares, costs, orders = START, 0.0, 0.0, 0
    curve, invested_days, n_days = [], 0, 0
    pending = None
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    for k, i in enumerate(idx):
        b = bars[i]
        if pending is not None:
            if pending and shares == 0:
                shares = cash / (b["o"] * (1 + COST)); costs += cash * COST; cash = 0.0; orders += 1
            elif not pending and shares > 0:
                val = shares * b["o"]; fee = val * COST + SELL_FEE; costs += fee; cash = val - fee; shares = 0.0; orders += 1
            pending = None
        val = cash + shares * b["c"]
        curve.append([b["d"], round(val, 2)])
        n_days += 1; invested_days += 1 if shares > 0 else 0
        w = want_by_date.get(b["d"])
        if w is not None and k < len(idx) - 1:
            if w != (shares > 0): pending = w
    final = curve[-1][1] if curve else START
    peak, maxdd, dd_date = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > maxdd: maxdd = (peak - v) / peak; dd_date = d
    yrs = (time.mktime(time.strptime(end, "%Y-%m-%d")) - time.mktime(time.strptime(start, "%Y-%m-%d"))) / (365.25 * 86400)
    return {"final": final, "cagr_pct": round(((final/START) ** (1/yrs) - 1) * 100, 2) if final > 0 else -100.0,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": dd_date, "costs": round(costs, 2),
            "orders": orders, "time_in_market_pct": round(100 * invested_days / max(n_days, 1), 1),
            "equity_curve": curve}

def buy_hold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START / (first["o"] * (1 + COST))
    val = shares * last["c"]; final = val - (val * COST + SELL_FEE)
    peak, maxdd, curve = -1.0, 0.0, []
    for i in idx:
        v = shares * bars[i]["c"]; curve.append([bars[i]["d"], round(v, 2)])
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}

def ichimoku_lines(bars):
    H = [b["h"] for b in bars]; L = [b["l"] for b in bars]; C = [b["c"] for b in bars]
    tenkan = [None]*len(bars); kijun = [None]*len(bars); spanA = [None]*len(bars); spanB = [None]*len(bars)
    for i in range(len(bars)):
        if i >= 8: tenkan[i] = (max(H[i-8:i+1]) + min(L[i-8:i+1])) / 2
        if i >= 25: kijun[i] = (max(H[i-25:i+1]) + min(L[i-25:i+1])) / 2
        if i >= 51: spanB[i] = (max(H[i-51:i+1]) + min(L[i-51:i+1])) / 2
    for i in range(len(bars)):
        if tenkan[i] is not None and kijun[i] is not None: spanA[i] = (tenkan[i] + kijun[i]) / 2
    return tenkan, kijun, spanA, spanB, C

def build_native(bars):
    """v11 four-condition daily boolean (integrity gate)."""
    tenkan, kijun, spanA, spanB, C = ichimoku_lines(bars)
    global want_by_date; want_by_date = {}
    for i in range(len(bars)):
        if i < 26 or spanA[i-26] is None or spanB[i-26] is None or tenkan[i] is None or kijun[i] is None or spanA[i] is None or spanB[i] is None: continue
        want_by_date[bars[i]["d"]] = (C[i] > max(spanA[i-26], spanB[i-26]) and tenkan[i] > kijun[i]
                                      and C[i] > C[i-26] and spanA[i] > spanB[i])

def build_statemachine(bars, mode):
    """mode='house': enter both-cond, exit below-cloud OR T<K.
       mode='best':  enter both-cond, exit below-cloud-bottom ONLY."""
    tenkan, kijun, spanA, spanB, C = ichimoku_lines(bars)
    global want_by_date; want_by_date = {}
    state = False
    for i in range(len(bars)):
        if i < 26 or spanA[i-26] is None or spanB[i-26] is None or tenkan[i] is None or kijun[i] is None: continue
        top = max(spanA[i-26], spanB[i-26]); bot = min(spanA[i-26], spanB[i-26])
        if not state:
            if C[i] > top and tenkan[i] > kijun[i]: state = True
        else:
            if mode == "house":
                if C[i] < bot or tenkan[i] < kijun[i]: state = False
            else:
                if C[i] < bot: state = False
        want_by_date[bars[i]["d"]] = state

def circular_placebos(bars, start, end):
    global want_by_date
    dates = [b["d"] for b in bars]
    states, cur = [], False
    for d in dates:
        w = want_by_date.get(d)
        if w is not None: cur = w
        states.append(cur)
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    series = [states[i] for i in idx]; n = len(series)
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed); shift = rng.randrange(1, n)
        shifted = series[shift:] + series[:shift]
        saved = want_by_date
        want_by_date = {dates[idx[k]]: shifted[k] for k in range(n)}
        r = run_state(bars, start, end)
        want_by_date = saved
        twins.append({"seed": seed, "final": r["final"]})
    return twins

def year_folds(curve):
    folds, prev, by_year = {}, None, {}
    for d, v in curve: by_year.setdefault(d[:4], []).append(v)
    for y in sorted(by_year):
        vals = by_year[y]; base = prev if prev is not None else START
        folds[y] = {"start_val": round(base, 2), "end_val": vals[-1],
                    "return_pct": round((vals[-1] / base - 1) * 100, 2) if base else None}
        prev = vals[-1]
    return folds

def distribution(curve):
    """Monthly distribution + streaks + longest stretch between new highs (trading days)."""
    by_month, prev = {}, None
    for d, v in curve: by_month.setdefault(d[:7], []).append(v)
    rets = []
    for m in sorted(by_month):
        base = prev if prev is not None else START
        rets.append((m, round((by_month[m][-1] / base - 1) * 100, 2))); prev = by_month[m][-1]
    vals = sorted(r for _, r in rets)
    med = vals[len(vals)//2] if len(vals) % 2 else round((vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2, 2)
    streak = longest = 0
    for _, r in rets:
        streak = streak + 1 if r < 0 else 0; longest = max(longest, streak)
    peak, since, max_stretch = -1.0, 0, 0
    for d, v in curve:
        if v >= peak: peak, since = v, 0
        else: since += 1; max_stretch = max(max_stretch, since)
    return {"n_months": len(rets), "median_month_pct": med,
            "share_positive_pct": round(100 * sum(1 for _, r in rets if r > 0) / len(rets), 1),
            "best_month": max(rets, key=lambda x: x[1]), "worst_month": min(rets, key=lambda x: x[1]),
            "longest_losing_streak_months": longest, "longest_stretch_between_new_highs_days": max_stretch,
            "monthly_returns": rets}

def main():
    bars = load_bars(SPY_PX)
    out = {"slug": "folklore-f5-ichimoku", "program": "v13-best-rules",
           "costs": "0.10%/side + $0.01 sell fee", "floor": "none",
           "windows": {}, "benchmark": {}, "integrity": {}}
    # Integrity gate 1: v11 native form
    build_native(bars)
    nat = {w: run_state(bars, s, e)["final"] for w, (s, e) in WINDOWS.items()}
    out["integrity"]["v11_native_finals"] = nat
    out["integrity"]["v11_native_expected"] = {"LONG": 174.02, "DECADE": 170.21, "CONT": 158.07, "VAL": 145.09}
    # Integrity gate 2: house state machine, DECADE $204.47
    build_statemachine(bars, "house")
    house = {w: run_state(bars, s, e)["final"] for w, (s, e) in WINDOWS.items()}
    out["integrity"]["house_finals"] = house
    out["integrity"]["house_expected_DECADE"] = 204.47
    print("INTEGRITY native:", nat, "| house:", house)
    # My rules
    build_statemachine(bars, "best")
    for wname, (s, e) in WINDOWS.items():
        r = run_state(bars, s, e)
        twins = circular_placebos(bars, s, e)
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        r["placebo_beaten"] = f"{beaten}/20"
        r["placebo_median"] = sorted(t["final"] for t in twins)[10]
        r["placebo_twins"] = twins
        out["windows"][wname] = r
        out["benchmark"][wname] = buy_hold(bars, s, e)
        print(wname, "final", r["final"], "maxDD", r["max_dd_pct"], "orders", r["orders"],
              "inmkt", r["time_in_market_pct"], "costs", r["costs"], "placebo", r["placebo_beaten"],
              "| SPY", out["benchmark"][wname]["final"])
    out["year_folds_LONG"] = year_folds(out["windows"]["LONG"]["equity_curve"])
    out["distribution_LONG"] = distribution(out["windows"]["LONG"]["equity_curve"])
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)

if __name__ == "__main__": main()
