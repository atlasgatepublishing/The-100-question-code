#!/usr/bin/env python3
"""v13 best-rules Dow Theory: graded 0/50/100 by per-average Rhea state (3% secondary
threshold), signals DIA+IYT closes, traded SPY, next-open, costs 0.10%/side + $0.01 sell.
Placebos: 20-seed circular shift of graded target series. Monthly distribution stats."""
import json, os, time, random, math
HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
DIA_PX = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/folklore-f4-dowtheory/data/pxfull_DIA.json")
IYT_PX = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/folklore-f4-dowtheory/data/pxfull_IYT.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0; THRESH = 0.03
WINDOWS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}

def load_bars(path):
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if None in (o, c): continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o * r, "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

def dow_states(bars, thresh=THRESH):
    """Identical bookkeeping to v11, threshold per spec."""
    C = [b["c"] for b in bars]
    state = 0; extreme = C[0]; edir = 0; last_peak = None; last_trough = None; states = []
    for c in C:
        if edir == 0:
            if c >= extreme * (1 + thresh): edir = 1; extreme = c
            elif c <= extreme * (1 - thresh): edir = -1; extreme = c
        elif edir == 1:
            if c > extreme: extreme = c
            elif c <= extreme * (1 - thresh): last_peak = extreme; edir = -1; extreme = c
        else:
            if c < extreme: extreme = c
            elif c >= extreme * (1 + thresh): last_trough = extreme; edir = 1; extreme = c
        if last_peak is not None and c > last_peak: state = 1
        elif last_trough is not None and c < last_trough: state = -1
        states.append(state)
    return states

def build_targets(spy, dia, iyt):
    sd = dow_states(dia); si = dow_states(iyt)
    iyt_by_date = {b["d"]: si[k] for k, b in enumerate(iyt)}
    dia_by_date = {b["d"]: sd[k] for k, b in enumerate(dia)}
    # Target fraction = (# averages in bullish state)/2, per spec SS3: both bull=1.0,
    # one bull (other bearish or stateless)=0.5, none bull=0.0. None until any state exists.
    targets = {}
    for b in spy:
        a = dia_by_date.get(b["d"]); t = iyt_by_date.get(b["d"])
        if a is None or t is None: continue
        known = [s for s in (a, t) if s != 0]
        if not known: targets[b["d"]] = None; continue
        bulls = sum(1 for s in known if s == 1)
        targets[b["d"]] = bulls / 2.0  # both bull=1.0, one bull=0.5, none bull=0.0
    return targets

def run_window(spy, targets, start, end):
    cash, shares, costs, orders = START, 0.0, 0.0, 0
    curve = []; pending = None; invested_days = 0; full_days = 0; n = 0
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    for k, i in enumerate(idx):
        b = spy[i]
        if pending is not None:
            val_open = cash + shares * b["o"]
            want_val = pending * val_open
            cur_val = shares * b["o"]
            if want_val > cur_val + 1e-9:
                spend = min(cash, want_val - cur_val)
                shares += spend / (b["o"] * (1 + COST))
                costs += spend - spend / (1 + COST); cash -= spend; orders += 1
            elif want_val < cur_val - 1e-9:
                sell_val = cur_val - want_val
                fee = sell_val * COST + SELL_FEE
                shares -= sell_val / b["o"]; cash += sell_val - fee; costs += fee; orders += 1
            pending = None
        val = cash + shares * b["c"]
        curve.append([b["d"], round(val, 2)])
        n += 1
        if shares > 0: invested_days += 1
        if val > 0 and shares * b["c"] / val > 0.9: full_days += 1
        w = targets.get(b["d"])
        if w is not None and k < len(idx) - 1:
            cur_frac = (shares * b["c"] / val) if val > 0 else 0.0
            if abs(w - cur_frac) > 0.01: pending = w
    final = curve[-1][1] if curve else START
    peak, maxdd, dd_date = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > maxdd: maxdd = (peak - v) / peak; dd_date = d
    yrs = (time.mktime(time.strptime(end, "%Y-%m-%d")) - time.mktime(time.strptime(start, "%Y-%m-%d"))) / (365.25 * 86400)
    return {"final": final, "cagr_pct": round(((final / START) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": dd_date, "costs": round(costs, 2),
            "orders": orders, "time_invested_pct": round(100 * invested_days / max(n, 1), 1),
            "time_full_pct": round(100 * full_days / max(n, 1), 1), "equity_curve": curve}

def buy_hold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START / (first["o"] * (1 + COST))
    val = shares * last["c"]; final = val - (val * COST + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for i in idx:
        v = shares * bars[i]["c"]; peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}

def monthly_stats(curve):
    months = {}
    for d, v in curve: months.setdefault(d[:7], []).append(v)
    keys = sorted(months); rets = []; prev = START
    for k in keys:
        end_v = months[k][-1]
        rets.append((end_v / prev - 1) * 100); prev = end_v
    srt = sorted(rets); med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt)//2-1] + srt[len(srt)//2]) / 2
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak, peak_d, longest, last_peak_d = -1, None, 0, None
    for d, v in curve:
        if v >= peak: peak = v; last_peak_d = d
        else:
            dd_days = (time.mktime(time.strptime(d, "%Y-%m-%d")) - time.mktime(time.strptime(last_peak_d, "%Y-%m-%d"))) / 86400
            longest = max(longest, int(dd_days))
    return {"periods": len(rets), "median_pct": round(med, 2), "pct_positive": round(100 * pos / len(rets), 1),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_months": streak, "longest_between_highs_days": longest,
            "mean_pct_secondary": round(sum(rets) / len(rets), 2)}

def main():
    spy = load_bars(SPY_PX); dia = load_bars(DIA_PX); iyt = load_bars(IYT_PX)
    targets = build_targets(spy, dia, iyt)
    out = {"slug": "folklore-f4-dowtheory", "program": "v13-best-rules",
           "spec": "graded 0/50/100 by per-average Rhea state, 3% secondary threshold, DIA+IYT signals, traded SPY, no floor",
           "costs": "0.10%/side + $0.01 sell fee", "windows": {}, "benchmark_spy": {}, "benchmark_dia": {}}
    spy_dates = [b["d"] for b in spy]
    for wname, (s, e) in WINDOWS.items():
        r = run_window(spy, targets, s, e)
        # placebos: circular shift of in-window target series (carry-forward filled)
        filled = []; cur = None
        for d in spy_dates:
            if targets.get(d) is not None: cur = targets[d]
            filled.append(cur)
        idx = [i for i, d in enumerate(spy_dates) if s <= d <= e]
        series = [filled[i] if filled[i] is not None else 0.0 for i in idx]
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed); n = len(series); shift = rng.randrange(1, n)
            shifted = series[shift:] + series[:shift]
            tt = {spy_dates[idx[k]]: shifted[k] for k in range(n)}
            twins.append({"seed": seed, "final": run_window(spy, tt, s, e)["final"]})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        r["placebo_beaten"] = f"{beaten}/20"
        r["placebo_median"] = sorted(t["final"] for t in twins)[10]
        r["placebo_twins"] = twins
        r["monthly"] = monthly_stats(r["equity_curve"])
        out["windows"][wname] = r
        out["benchmark_spy"][wname] = buy_hold(spy, s, e)
        out["benchmark_dia"][wname] = buy_hold(dia, s, e)
        print(wname, r["final"], "cagr", r["cagr_pct"], "DD", r["max_dd_pct"], "orders", r["orders"],
              "costs", r["costs"], "inv", r["time_invested_pct"], "full", r["time_full_pct"],
              "placebo", r["placebo_beaten"], "med", r["placebo_median"],
              "| SPY", out["benchmark_spy"][wname], "| DIA", out["benchmark_dia"][wname])
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)

if __name__ == "__main__": main()
