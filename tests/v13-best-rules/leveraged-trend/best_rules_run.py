"""V13 BEST RULES — Leveraged Trend (Gayed family).
Spec frozen in BEST-RULES-SPEC.md BEFORE this run:
  Weekly check (last trading day of week, close): SPY adj close vs 200d SMA.
  Above -> UPRO (3x). Below -> SHY (1-3y Treasuries). No floor/stop/ladder.
  Cost 0.10%/side on switches. Signal at close t, effective next trading day
  (same close-to-close lag convention as the v11 native engine).
Placebos: 20-seed two-state Markov random-timing series per road, matched to the
actual series' in-UPRO share and switch count, same return stream and costs.
Data (read-only except SHY, pulled fresh into this folder from Yahoo public chart API):
  SPY/UPRO: v10-retest/leveraged-trend/data/ ; SHY: ./data/SHY.json
"""
import json, math, pathlib, random, datetime

HERE = pathlib.Path(__file__).parent
V10 = pathlib.Path.home() / "workspace/stock-app/backtests/v10-retest/leveraged-trend/data"

def load(path):
    d = json.loads(pathlib.Path(path).read_text())
    r = d["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    rows = []
    for i, t in enumerate(ts):
        c = (adj[i] if adj else q["close"][i])
        if c is None: continue
        rows.append((datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c))
    return rows

spy = load(V10 / "SPY.json")
upro = dict(load(V10 / "UPRO.json"))
shy = dict(load(HERE / "data" / "SHY.json"))
dates = [d for d, _ in spy]; px = [c for _, c in spy]
sma = [None] * len(px)
for i in range(len(px)):
    if i >= 199: sma[i] = sum(px[i-199:i+1]) / 200

# week key: ISO year-week of each date; signal days = last trading day of each week
week_last = {}
for i, d in enumerate(dates):
    dt = datetime.date.fromisoformat(d)
    week_last[(dt.isocalendar()[0], dt.isocalendar()[1])] = i
signal_idx = set(week_last.values())

COST = 0.0010

def simulate(start, end, pos_series=None):
    """pos_series: optional dict date->position(0/1) decided at that date's close
    (for placebos). If None, use the real weekly SMA rule."""
    eq = 100.0; pos = 0; curve = []; switches = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0; started = False
    prev_u = prev_h = None; in_days = 0; tot_days = 0
    new_high_date = start; longest_no_high = 0; last_high_i = 0
    neg_streak = 0; longest_neg_streak = 0; prev_eq = None
    for i, (d, c) in enumerate(spy):
        if d < start or d > end:
            prev_u = upro.get(d); prev_h = shy.get(d); continue
        if started:
            if pos == 1 and prev_u and upro.get(d):
                eq *= upro[d] / prev_u
            elif pos == 0 and prev_h and shy.get(d):
                eq *= shy[d] / prev_h
        started = True; tot_days += 1; in_days += pos
        if eq > peak:
            peak = eq; last_high_i = len(curve)
        maxdd = min(maxdd, eq / peak - 1)
        longest_no_high = max(longest_no_high, len(curve) - last_high_i)
        if prev_eq is not None:
            if eq < prev_eq: neg_streak += 1; longest_neg_streak = max(longest_neg_streak, neg_streak)
            else: neg_streak = 0
        prev_eq = eq
        curve.append([d, round(eq, 4)])
        if pos_series is not None:
            want = pos_series.get(d, pos)
        elif i in signal_idx and sma[i] is not None:
            want = 1 if c > sma[i] else 0
        else:
            want = pos
        if want != pos:
            ch = eq * COST; eq -= ch; costs += ch; switches += 1; pos = want
            curve[-1][1] = round(eq, 4)
        prev_u = upro.get(d); prev_h = shy.get(d)
    yrs = (len(curve) / 252) or 1
    return {"start": start, "end": end, "final": round(eq, 2),
            "cagr_pct": round(((eq / 100) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "switches": switches,
            "costs": round(costs, 2), "in_upro_share": round(in_days / max(tot_days, 1), 3),
            "longest_days_between_highs": longest_no_high,
            "longest_losing_streak_days": longest_neg_streak, "curve": curve}

def spy_bh(start, end):
    seg = [c for d, c in spy if start <= d <= end]
    # SPY max DD on the window
    peak = seg[0]; dd = 0.0
    for c in seg:
        peak = max(peak, c); dd = min(dd, c / peak - 1)
    return {"final": round(100 * seg[-1] / seg[0], 2), "max_dd_pct": round(dd * 100, 2)}

def placebo_series(start, end, in_share, n_switches, seed):
    """Markov chain over trading days in window, decisions only on weekly signal
    days, matched occupancy & switch rate in expectation."""
    rng = random.Random(seed)
    wdays = [dates[i] for i in sorted(signal_idx) if start <= dates[i] <= end]
    if len(wdays) < 2: return {}
    # transition probs: stationary share f, expected switches per week s
    f = min(max(in_share, 0.02), 0.98)
    s = n_switches / len(wdays)
    # s = f*p10 + (1-f)*p01 ; symmetric-ish split: p01 = s/(2*(1-f)) ... solve with p10 = p01*(1-f)/f
    p01 = s / (2 * (1 - f)) if f < 1 else 0.0
    p10 = p01 * (1 - f) / f if f > 0 else 0.0
    p01 = min(p01, 1.0); p10 = min(p10, 1.0)
    pos = 1 if rng.random() < f else 0
    series = {}
    for d in wdays:
        series[d] = pos
        if pos == 0 and rng.random() < p01: pos = 1
        elif pos == 1 and rng.random() < p10: pos = 0
    return series

def year_distribution(r, start, end):
    folds = {}
    seg = [d for d, _ in spy if start <= d <= end]
    for y in sorted(set(d[:4] for d in seg)):
        folds[y] = simulate(f"{y}-01-01", f"{y}-12-31")["final"]
    rets = sorted(v - 100 for v in folds.values())
    n = len(rets)
    median = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    # longest run of negative years
    streak = mx = 0
    for y in sorted(folds):
        streak = streak + 1 if folds[y] < 100 else 0; mx = max(mx, streak)
    return {"year_folds_final_per_100": folds,
            "median_year_pct": round(median, 2),
            "share_years_positive_pct": round(100 * sum(1 for v in rets if v > 0) / n, 1),
            "best_year_pct": round(rets[-1], 2), "worst_year_pct": round(rets[0], 2),
            "longest_losing_year_streak": mx}

windows = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
confirm_windows = {"CONF-A 2010-2018": ("2010-01-04", "2018-12-31"),
                   "CONF-B 2013-2022": ("2013-01-02", "2022-12-30")}

out = {"strategy": "V13 best-rules leveraged trend: WEEKLY SPY vs 200d SMA; above->UPRO 3x, below->SHY; no floor/stop",
       "cost_per_side": COST, "windows": {}, "confirmation_windows": {}}
for k, (s, e) in windows.items():
    r = simulate(s, e); r["spy_buyhold"] = spy_bh(s, e)
    r["distribution"] = year_distribution(r, s, e)
    # placebos
    pl = []
    for seed in range(20):
        ps = placebo_series(s, e, r["in_upro_share"], r["switches"], 1000 + seed)
        pl.append(simulate(s, e, pos_series=ps)["final"])
    pl_sorted = sorted(pl)
    r["placebo_20seed"] = {"finals": [round(x, 2) for x in pl_sorted],
                           "median": round(pl_sorted[10], 2), "max": round(pl_sorted[-1], 2),
                           "actual_beats_n_of_20": sum(1 for x in pl if r["final"] > x)}
    out["windows"][k] = r
    print(k, r["final"], "SPY", r["spy_buyhold"]["final"], "maxDD", r["max_dd_pct"],
          "switches", r["switches"], "placeboMed", r["placebo_20seed"]["median"],
          "beats", r["placebo_20seed"]["actual_beats_n_of_20"], "/20")
for k, (s, e) in confirm_windows.items():
    r = simulate(s, e); r["spy_buyhold"] = spy_bh(s, e)
    out["confirmation_windows"][k] = r
    print(k, r["final"], "SPY", r["spy_buyhold"]["final"], "maxDD", r["max_dd_pct"], "switches", r["switches"])
pathlib.Path(__file__).with_name("results.json").write_text(json.dumps(out, indent=1))
print("written results.json")
