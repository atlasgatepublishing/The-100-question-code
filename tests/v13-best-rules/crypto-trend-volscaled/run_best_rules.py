"""V13 BEST-RULES: crypto trend, vol-scaled family — scaling REMOVED.

Single-variable experiment vs the v11 native chassis: identical weekly
Liu & Tsyvinski 4-week-formation TSMOM signal, identical 0.60%/side US
retail fee, identical data (read-only v10 Yahoo cache), identical roads.
The ONLY change: position weight is binary 100%/0% — no MOP vol-scaling,
no vol estimate in the sizing path. See BEST-RULES-SPEC.md (frozen first).

Roads: FULL (BTC 2016-11-21->, ETH 2017-11-09->, both to data end),
DESIGN (start->2022-12-31), VALIDATION (2023-01-01->end, the pre-registered
confirmation road). Fresh $100 pots per window; signals use pre-window
history as lookback only. Buy-hold on the identical road beside every
result. Placebos: 20 seeds, FULL road, exposure-matched random weekly
in/out at FULL weight when in, same fees. No floor (see spec)."""
import csv, math, pathlib, random, json, statistics, datetime

SRC = pathlib.Path.home() / "workspace/stock-app/backtests/v10-retest/crypto-trend-volscaled/data"
FEE = 0.0060

def load(sym):
    rows = []
    with open(SRC / f"{sym}-USD.csv") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["close"])))
    return rows

def weekly(rows):
    out = {}
    for d, c in rows:
        dt = datetime.date.fromisoformat(d)
        out[(dt.isocalendar()[0], dt.isocalendar()[1])] = (d, c)
    return [out[k] for k in sorted(out)]

def run(rows, start, end, placebo_seed=None, p_in=None):
    rows = [(d, c) for d, c in rows if d <= end]
    wk = weekly(rows)
    eq = 100.0; w = 0.0; curve = []; costs = 0.0; trades = 0; expo = []
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    prev_c = None; hist = []
    for d, c in wk:
        hist.append(c)
        if prev_c is not None and w > 0:
            eq *= (1 + w * (c / prev_c - 1))
        prev_c = c
        if d < start:
            continue
        curve.append([d, round(eq, 4)]); expo.append(w)
        if len(hist) >= 5:
            form = hist[-1] / hist[-5] - 1
            if rng is not None:
                inmarket = rng.random() < p_in
            else:
                inmarket = form > 0
            nw = 1.0 if inmarket else 0.0
            if nw != w:
                ch = eq * abs(nw - w) * FEE; eq -= ch; costs += ch; trades += 1; w = nw
    avg_expo = round(statistics.mean(expo), 3) if expo else 0
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = min(maxdd, v / peak - 1)
    return {"final": round(eq, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "trades": trades,
            "avg_weight": avg_expo, "curve": curve}

def buyhold(rows, start, end):
    seg = [c for d, c in rows if start <= d <= end]
    return round(100 * seg[-1] / seg[0], 2)

def monthly_dist(curve):
    """Per-period (monthly) distribution from a weekly equity curve."""
    months = {}
    for d, v in curve:
        months[d[:7]] = v
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        rets.append(months[k] / prev - 1); prev = months[k]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak (consecutive negative months)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (months, on month-end values)
    peak = 100.0; since = 0; longest_gap = 0; open_gap = 0
    for k in keys:
        if months[k] > peak:
            peak = months[k]; longest_gap = max(longest_gap, since); since = 0
        else:
            since += 1
    open_gap = since
    return {"n_months": len(rets),
            "median_month_pct": round(statistics.median(rets) * 100, 2),
            "mean_month_pct_SECONDARY": round(statistics.mean(rets) * 100, 2),
            "share_positive_pct": round(100 * pos / len(rets), 1),
            "best_month_pct": round(max(rets) * 100, 2),
            "worst_month_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_months": longest,
            "longest_stretch_between_new_highs_months": longest_gap,
            "months_since_last_new_high_at_end": open_gap}

WINDOWS = {
    "FULL":       lambda sym, last: ("2016-11-21" if sym == "BTC" else "2017-11-09", last),
    "DESIGN":     lambda sym, last: ("2016-11-21" if sym == "BTC" else "2017-11-09", "2022-12-31"),
    "VALIDATION": lambda sym, last: ("2023-01-01", last),
}

out = {"strategy": "V13 best-rules: LT TSMOM weekly, 4wk formation, BINARY full weight (vol-scaling removed), fee 0.60%/side, no floor",
       "family": "crypto-trend-volscaled", "assets": {}}
for sym in ["BTC", "ETH"]:
    rows = load(sym)
    last = rows[-1][0]
    entry = {}
    for wname, wf in WINDOWS.items():
        start, end = wf(sym, last)
        r = run(rows, start, end)
        r["buyhold"] = buyhold(rows, start, end)
        r["start"], r["end"] = start, end
        entry[wname] = r
        print(sym, wname, r["final"], "BH", r["buyhold"], "DD", r["max_dd_pct"],
              "trades", r["trades"], "avgW", r["avg_weight"])
    # placebos on FULL, exposure-matched to this chassis
    full = entry["FULL"]
    pls = [run(rows, full["start"], full["end"], placebo_seed=s, p_in=full["avg_weight"])["final"]
           for s in range(20)]
    full["placebo_beaten"] = sum(1 for p in pls if full["final"] > p)
    full["placebo_median"] = round(statistics.median(pls), 2)
    full["placebo_finals"] = pls
    full["monthly_distribution"] = monthly_dist(full["curve"])
    print(sym, "placebos beaten", full["placebo_beaten"], "/20, median", full["placebo_median"])
    out["assets"][sym] = entry

for wname in WINDOWS:
    out[f"combo_{wname}"] = round((out["assets"]["BTC"][wname]["final"] +
                                   out["assets"]["ETH"][wname]["final"]) / 2, 2)
    out[f"combo_{wname}_buyhold"] = round((out["assets"]["BTC"][wname]["buyhold"] +
                                           out["assets"]["ETH"][wname]["buyhold"]) / 2, 2)
    print("COMBO", wname, out[f"combo_{wname}"], "BH", out[f"combo_{wname}_buyhold"])

pathlib.Path(__file__).with_name("results.json").write_text(json.dumps(out, indent=1))
print("written results.json")
