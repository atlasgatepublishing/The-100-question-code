#!/usr/bin/env python3
"""v11 native-rules engine (W02). Usage: run_native.py <ichimoku|dow|golden>
Native rules only: NO house -15% floor, NO v9 chassis. Costs: 0.10%/side + $0.01 sell fee.
Signals on closes, execution next open. $100/window. Placebos: 20 seeds.
Ichimoku/Dow placebos: circular shift of desired-state series. Dow: spell-matched re-placement.
"""
import json, os, sys, time, random, math

MODE = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
DIA_PX = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/folklore-f4-dowtheory/data/pxfull_DIA.json")
IYT_PX = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/folklore-f4-dowtheory/data/pxfull_IYT.json")
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

def run_state(bars, want, start, end, traded=None):
    """want[i] = desired long state decided at close of bar i (or None). traded bars default=bars."""
    tb = traded or bars
    cash, shares, costs, orders, switches = START, 0.0, 0.0, 0, 0
    curve, invested_days, n_days = [], 0, 0
    pending = None
    idx = [i for i, b in enumerate(tb) if start <= b["d"] <= end]
    for k, i in enumerate(idx):
        b = tb[i]
        # execute pending at today's open (signal from previous bar in signal-series index space)
        if pending is not None:
            if pending and shares == 0:
                shares = cash / (b["o"] * (1 + COST)); costs += cash * COST; cash = 0.0; orders += 1; switches += 1
            elif not pending and shares > 0:
                val = shares * b["o"]; fee = val * COST + SELL_FEE; costs += fee; cash = val - fee; shares = 0.0; orders += 1; switches += 1
            pending = None
        val = cash + shares * b["c"]
        curve.append([b["d"], round(val, 2)])
        n_days += 1; invested_days += 1 if shares > 0 else 0
        # signal at close: want is indexed on signal bars; map by date
        w = want_by_date.get(b["d"])
        if w is not None and k < len(idx) - 1:
            cur_long = shares > 0
            if w != cur_long: pending = w
    final = curve[-1][1] if curve else START
    peak, maxdd = -1.0, 0.0; worst_day = None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > maxdd: maxdd = (peak - v) / peak; worst_day = d
    yrs = (time.mktime(time.strptime(end, "%Y-%m-%d")) - time.mktime(time.strptime(start, "%Y-%m-%d"))) / (365.25 * 86400)
    return {"final": final, "cagr_pct": round(((final/START) ** (1/yrs) - 1) * 100, 2) if final > 0 else -100.0,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": worst_day, "costs": round(costs, 2),
            "orders": orders, "switches": switches,
            "time_in_market_pct": round(100 * invested_days / max(n_days, 1), 1), "equity_curve": curve}

def buy_hold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START / (first["o"] * (1 + COST))
    val = shares * last["c"]; final = val - (val * COST + SELL_FEE)
    peak, maxdd = -1.0, 0.0; curve = []
    for i in idx:
        v = shares * bars[i]["c"]; curve.append([bars[i]["d"], round(v, 2)])
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}

def year_folds(curve):
    folds = {}
    prev = None
    by_year = {}
    for d, v in curve: by_year.setdefault(d[:4], []).append(v)
    for y in sorted(by_year):
        vals = by_year[y]
        base = prev if prev is not None else START
        folds[y] = {"start_val": round(base, 2), "end_val": vals[-1],
                    "return_pct": round((vals[-1] / base - 1) * 100, 2) if base else None}
        prev = vals[-1]
    return folds

def circular_placebos(bars, want_list, start, end, traded=None):
    """Shift the in-window desired-state series (preserves time-in-market & switch structure)."""
    global want_by_date
    tb = traded or bars
    dates = [b["d"] for b in tb]
    # build state series over traded-bar dates
    states = []
    cur = False
    for d in dates:
        w = want_by_date.get(d)
        if w is not None: cur = w
        states.append(cur)
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    series = [states[i] for i in idx]
    n = len(series); beaten = 0; twins = []
    strat_final = None
    for seed in range(1, 21):
        rng = random.Random(seed)
        shift = rng.randrange(1, n)
        shifted = series[shift:] + series[:shift]
        # run with shifted states as want_by_date override
        saved = want_by_date
        want_by_date = {dates[idx[k]]: shifted[k] for k in range(n)}
        r = run_state(tb, None, start, end, traded)
        want_by_date = saved
        twins.append({"seed": seed, "final": r["final"]})
    return twins

# ---------------- signal builders (fill global want_by_date) ----------------
want_by_date = {}

def build_ichimoku(bars):
    H = [b["h"] for b in bars]; L = [b["l"] for b in bars]; C = [b["c"] for b in bars]
    def mid(i, n, src): return (max(src[i-n+1:i+1]) + min(src[i-n+1:i+1])) / 2 if i >= n-1 else None
    tenkan = [None]*len(bars); kijun = [None]*len(bars)
    for i in range(len(bars)):
        if i >= 8: tenkan[i] = (max(H[i-8:i+1]) + min(L[i-8:i+1])) / 2
        if i >= 25: kijun[i] = (max(H[i-25:i+1]) + min(L[i-25:i+1])) / 2
    spanA = [None]*len(bars); spanB = [None]*len(bars)
    for i in range(len(bars)):
        if tenkan[i] is not None and kijun[i] is not None: spanA[i] = (tenkan[i] + kijun[i]) / 2
        if i >= 51: spanB[i] = (max(H[i-51:i+1]) + min(L[i-51:i+1])) / 2
    global want_by_date; want_by_date = {}
    for i in range(len(bars)):
        if i < 26 or spanA[i-26] is None or spanB[i-26] is None or tenkan[i] is None or kijun[i] is None or spanA[i] is None or spanB[i] is None: continue
        cloud_top = max(spanA[i-26], spanB[i-26])
        want_by_date[bars[i]["d"]] = (C[i] > cloud_top and tenkan[i] > kijun[i]
                                      and C[i] > C[i-26] and spanA[i] > spanB[i])

def build_golden(bars):
    C = [b["c"] for b in bars]
    global want_by_date; want_by_date = {}
    s50 = s200 = 0.0
    for i, c in enumerate(C):
        s50 += c; s200 += c
        if i >= 50: s50 -= C[i-50]
        if i >= 200: s200 -= C[i-200]
        if i >= 199: want_by_date[bars[i]["d"]] = (s50/50.0) > (s200/200.0)

def dow_states(bars, thresh=0.05):
    """Rhea swing form on closes: >=5% closing retracement confirms the extreme it retraced from.
    Returns per-bar state: +1 bullish, -1 bearish, 0 unchanged/unknown."""
    C = [b["c"] for b in bars]
    state = 0; extreme = C[0]; extreme_dir = 0  # +1 rising to a peak, -1 falling to a trough
    last_peak = None; last_trough = None
    states = []
    vol_diag = []
    for i, c in enumerate(C):
        if extreme_dir == 0:
            if c >= extreme * (1 + thresh): extreme_dir = 1; extreme = c
            elif c <= extreme * (1 - thresh): extreme_dir = -1; extreme = c
        elif extreme_dir == 1:
            if c > extreme: extreme = c
            elif c <= extreme * (1 - thresh):
                last_peak = extreme; extreme_dir = -1; extreme = c
                if last_trough is not None and state == 0: pass
        else:
            if c < extreme: extreme = c
            elif c >= extreme * (1 + thresh):
                last_trough = extreme; extreme_dir = 1; extreme = c
        if last_peak is not None and c > last_peak: state = 1
        elif last_trough is not None and c < last_trough: state = -1
        states.append(state)
    return states

def build_dow(dia, iyt):
    sd = dow_states(dia); si = dow_states(iyt)
    dates_i = {b["d"]: si[k] for k, b in enumerate(iyt)}
    global want_by_date; want_by_date = {}
    joint = 0; cur_want = None
    for k, b in enumerate(dia):
        s_other = dates_i.get(b["d"])
        if s_other is None: continue
        if sd[k] == 1 and s_other == 1: joint = 1
        elif sd[k] == -1 and s_other == -1: joint = -1
        if joint == 1: cur_want = True
        elif joint == -1: cur_want = False
        if cur_want is not None: want_by_date[b["d"]] = cur_want

def main():
    out = {"slug": None, "mode": MODE, "costs": "0.10%/side + $0.01 sell fee", "floor": "none (native)",
           "windows": {}, "benchmark": {}}
    if MODE in ("ichimoku", "golden"):
        bars = load_bars(SPY_PX)
        (build_ichimoku if MODE == "ichimoku" else build_golden)(bars)
        traded = bars
        out["slug"] = "folklore-f5-ichimoku" if MODE == "ichimoku" else "folklore-f8-goldencross"
        bench_name = "SPY buy-hold"
    else:
        dia = load_bars(DIA_PX); iyt = load_bars(IYT_PX)
        build_dow(dia, iyt)
        bars = dia; traded = dia
        out["slug"] = "folklore-f4-dowtheory"
        bench_name = "DIA buy-hold"
    for wname, (s, e) in WINDOWS.items():
        r = run_state(traded, None, s, e, traded)
        twins = circular_placebos(traded, None, s, e, traded)
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        med = sorted(t["final"] for t in twins)[10]
        r["placebo_beaten"] = f"{beaten}/20"; r["placebo_median"] = med; r["placebo_twins"] = twins
        out["windows"][wname] = r
        out["benchmark"][wname] = buy_hold(traded, s, e)
    # folds from continuous LONG run
    out["year_folds_LONG"] = year_folds(out["windows"]["LONG"]["equity_curve"])
    out["benchmark_name"] = bench_name
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
    for wname in WINDOWS:
        r = out["windows"][wname]
        print(wname, "final", r["final"], "cagr", r["cagr_pct"], "maxDD", r["max_dd_pct"],
              "orders", r["orders"], "inmkt", r["time_in_market_pct"], "placebo", r["placebo_beaten"],
              "| bench", out["benchmark"][wname]["final"], out["benchmark"][wname]["max_dd_pct"])

if __name__ == "__main__": main()
