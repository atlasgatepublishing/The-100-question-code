#!/usr/bin/env python3
"""Market Profile / Dalton BEST-RULES (v13). Implements BEST-RULES-SPEC.md exactly:
SPY long/cash daily timer on a 20-day volume-profile approximation (volume spread
uniformly across each day's range, 0.25%-of-price bins, POC-outward 70% value area),
v12 day-type / value-migration / initiative-responsive rules, LONG next session on
initiative-buying or trend-up days, cash otherwise, next-open execution, program
costs (0.10%/side + $0.01 sell fee), NO floor. Placebos: 20 seeded random
LONG/CASH calendars matched on long-day count. JUDGMENT-CONSTRUCTED.
True intraday/TPO data is not available in the program stack — see spec fence.
Simulation only."""
import json, os, time, random, statistics
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
WIN = 20; BINPCT = 0.0025; VA_FRAC = 0.70

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["high"][i], q["low"][i], q["open"][i], q["volume"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i] * ratio, "high": q["high"][i] * ratio,
                     "low": q["low"][i] * ratio, "close": adj[i],
                     "volume": float(q["volume"][i])})
    return bars

def value_area(window):
    """Volume-profile approximation over a window of daily bars.
    Returns (POC, VAH, VAL) as bin-center prices."""
    ref = window[-1]["close"]; bw = BINPCT * ref
    lo = min(b["low"] for b in window); hi = max(b["high"] for b in window)
    n0 = int(lo // bw); n1 = int(hi // bw)
    vol = {}
    total = 0.0
    for b in window:
        rng = b["high"] - b["low"]
        if rng <= 0:
            k = int(b["close"] // bw); vol[k] = vol.get(k, 0.0) + b["volume"]; total += b["volume"]; continue
        k = int(b["low"] // bw); kend = int(b["high"] // bw)
        while k <= kend:
            blo, bhi = k * bw, (k + 1) * bw
            overlap = min(b["high"], bhi) - max(b["low"], blo)
            if overlap > 0:
                v = b["volume"] * overlap / rng
                vol[k] = vol.get(k, 0.0) + v; total += v
            k += 1
    if total <= 0: return None
    mid = (lo + hi) / 2.0
    poc = max(vol.items(), key=lambda kv: (kv[1], -abs((kv[0] + 0.5) * bw - mid)))[0]
    inc = {poc}; inc_vol = vol[poc]
    top = bot = poc
    keys = sorted(vol)
    while inc_vol < VA_FRAC * total:
        above = [k for k in (top + 1, top + 2) if k in vol]
        below = [k for k in (bot - 1, bot - 2) if k in vol]
        if not above and not below: break
        sa = sum(vol[k] for k in above); sb = sum(vol[k] for k in below)
        if above and (not below or sa >= sb):
            for k in above: inc.add(k); inc_vol += vol[k]
            top = max(above)
        else:
            for k in below: inc.add(k); inc_vol += vol[k]
            bot = min(below)
    center = lambda k: (k + 0.5) * bw
    return center(poc), center(max(inc)) + bw / 2, center(min(inc)) - bw / 2

def build_profiles(bars):
    """VA per day index i (window ending i), for i >= WIN-1."""
    prof = {}
    for i in range(WIN - 1, len(bars)):
        va = value_area(bars[i - WIN + 1: i + 1])
        if va: prof[i] = va
    return prof

def classify(bars, prof, i):
    """Day type, migration, initiative/responsive for day i (needs prof[i], prof[i-1])."""
    poc, vah, val = prof[i]; ppoc, pvah, pval = prof[i - 1]
    b = bars[i]
    # value migration (v12 R5)
    if val > pvah: mig = "Higher"
    elif vah < pval: mig = "Lower"
    elif vah >= pvah and val <= pval and (vah > pvah or val < pval): mig = "Outside"
    elif poc > ppoc: mig = "Overlap-higher"
    elif poc < ppoc: mig = "Overlap-lower"
    else: mig = "Unchanged"
    # day type vs prior VA (v12 R4 thresholds, prior VA as reference)
    H = pvah - pval
    ext_up = max(0.0, b["high"] - pvah); ext_dn = max(0.0, pval - b["low"])
    rng = b["high"] - b["low"]
    cloc = (b["close"] - b["low"]) / rng if rng > 0 else 0.5
    up_ext = ext_up >= 0.25 * H; dn_ext = ext_dn >= 0.25 * H
    if ext_up >= 1.0 * H and not dn_ext and cloc >= 0.8: dtype = "Trend-up"
    elif ext_dn >= 1.0 * H and not up_ext and cloc <= 0.2: dtype = "Trend-down"
    elif ext_up >= 0.5 * H and not dn_ext: dtype = "Normal-variation-up"
    elif ext_dn >= 0.5 * H and not up_ext: dtype = "Normal-variation-down"
    elif up_ext and dn_ext and (cloc >= 0.8 or cloc <= 0.2): dtype = "Neutral-extreme"
    elif up_ext and dn_ext: dtype = "Neutral"
    else: dtype = "Normal"
    # initiative / responsive (v12 R6)
    if b["open"] > pvah and b["close"] > pvah and mig in ("Higher", "Overlap-higher"):
        act = "Initiative-buying"
    elif b["open"] < pval and b["close"] < pval and mig in ("Lower", "Overlap-lower"):
        act = "Initiative-selling"
    elif (b["open"] > pvah or b["open"] < pval) and pval <= b["close"] <= pvah:
        act = "Responsive"
    else:
        act = "Mixed"
    long_signal = (act == "Initiative-buying") or (dtype == "Trend-up")
    return {"day_type": dtype, "migration": mig, "activity": act, "long": long_signal}

def run(bars, signals, start, end):
    """signals: dict date->bool (position to hold from next open). Executes at opens."""
    days = [b for b in bars if start <= b["date"] <= end]
    cash = START; shares = 0.0; costs = 0.0; trades = 0; long_days = 0
    curve = []
    want = False
    for di, b in enumerate(days):
        if di > 0:
            want = signals.get(days[di - 1]["date"], False)
        if want and shares == 0:
            fee = cash * COST; shares = (cash - fee) / b["open"]; costs += fee; cash = 0.0; trades += 1
        elif not want and shares > 0:
            gross = shares * b["open"]; fee = gross * COST + SELL_FEE
            cash = gross - fee; costs += fee; shares = 0.0; trades += 1
        if shares > 0: long_days += 1
        curve.append({"date": b["date"], "equity": round(cash + shares * b["close"], 4)})
    if shares > 0:
        gross = shares * days[-1]["close"]; fee = gross * COST + SELL_FEE
        cash = gross - fee; costs += fee; trades += 1
        curve[-1] = {"date": days[-1]["date"], "equity": round(cash, 4)}
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak - pt["equity"]) / peak if peak > 0 else 0)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "trades": trades, "long_days": long_days, "equity_curve": curve}

def period_stats(curve):
    ends = OrderedDict()
    for pt in curve: ends[pt["date"][:7]] = pt["equity"]
    keys = list(ends); vals = [START] + [ends[k] for k in keys]
    chg = [(keys[i], round(vals[i + 1] - vals[i], 2)) for i in range(len(keys))]
    if not chg: return {}
    amounts = [c for _, c in chg]
    streak = mx = 0
    for a in amounts:
        streak = streak + 1 if a < 0 else 0; mx = max(mx, streak)
    last_high = vals[0]; gap = mxgap = 0
    for v in vals[1:]:
        if v > last_high: last_high = v; mxgap = max(mxgap, gap); gap = 0
        else: gap += 1
    mxgap = max(mxgap, gap)
    best = max(chg, key=lambda x: x[1]); worst = min(chg, key=lambda x: x[1])
    return {"periods": len(chg), "median_period": round(statistics.median(amounts), 2),
            "share_positive_pct": round(100 * sum(1 for a in amounts if a > 0) / len(amounts), 1),
            "best_period": {"month": best[0], "usd": best[1]}, "worst_period": {"month": worst[0], "usd": worst[1]},
            "longest_losing_streak_months": mx, "longest_stretch_between_new_highs_months": mxgap,
            "mean_period_secondary": round(statistics.mean(amounts), 2)}

def buyhold(bars, start, end):
    days = [b for b in bars if start <= b["date"] <= end]
    sh = (START * (1 - COST)) / days[0]["close"]
    gross = sh * days[-1]["close"]; return round(gross - gross * COST - SELL_FEE, 2)

def placebo(bars, start, end, n_long, seed):
    days = [b for b in bars if start <= b["date"] <= end]
    rng = random.Random(77000 + seed)
    # choose which holding-days (day index >=1, state set by prior close) are long
    idx = list(range(1, len(days)))
    chosen = set(rng.sample(idx, min(n_long, len(idx)))) if n_long > 0 else set()
    signals = {}
    for di in range(len(days) - 1):
        signals[days[di]["date"]] = (di + 1) in chosen
    return run(bars, signals, start, end)

def main():
    bars = load(); prof = build_profiles(bars)
    signals = {}; daytypes = {}
    for i in range(WIN, len(bars)):
        if i in prof and (i - 1) in prof:
            c = classify(bars, prof, i)
            signals[bars[i]["date"]] = c["long"]; daytypes[bars[i]["date"]] = c
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    champ = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    out = {"family": "judgment-market-profile", "label": "JUDGMENT-CONSTRUCTED",
           "form": "BEST-RULES v13: SPY long/cash daily timer, 20-day volume-profile approximation (uniform volume-in-range, 0.25% bins, 70% VA), v12 day-type/migration/initiative rules, next-open execution, program costs, no floor",
           "data_fence": "Daily-bar approximation only: no intraday tape, no TPO brackets, no Initial Balance, no tails/single prints, no time-at-price acceptance test exists in the program data stack.",
           "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, signals, s, e)
        twins = [placebo(bars, s, e, r["long_days"], seed)["final"] for seed in range(20)]
        r["spy_buyhold"] = buyhold(bars, s, e)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["placebo_median"] = round(statistics.median(twins), 2)
        r["exposure_pct_days_long"] = round(100.0 * r["long_days"] / len(r["equity_curve"]), 1)
        r["period_stats"] = period_stats(r["equity_curve"])
        r["beats_champion_vm"] = r["final"] > champ[name]
        out["roads"][name] = r
        print(name, "MINE", r["final"], "DD", r["max_dd_pct"], "BH", r["spy_buyhold"],
              "costs", r["costs"], "trades", r["trades"], "longdays", r["long_days"],
              "placebo", r["placebos_beaten"], "/20 med", r["placebo_median"])
    # signal census over full history
    from collections import Counter
    out["signal_census"] = {"day_types": dict(Counter(c["day_type"] for c in daytypes.values())),
                            "activity": dict(Counter(c["activity"] for c in daytypes.values())),
                            "migration": dict(Counter(c["migration"] for c in daytypes.values())),
                            "long_signal_days": sum(1 for v in signals.values() if v),
                            "total_days": len(signals)}
    print("census", out["signal_census"])
    # yearly folds + half windows (confirmation machinery; verdict invoked only on a champion beat)
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        fr = run(bars, signals, s, e)
        folds[str(y)] = {"final": fr["final"], "spy_buyhold": buyhold(bars, s, e)}
    out["year_folds_mine"] = folds
    print("folds", {k: v["final"] for k, v in folds.items()})
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
