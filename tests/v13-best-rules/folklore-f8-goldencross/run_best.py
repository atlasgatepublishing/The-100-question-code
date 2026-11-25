#!/usr/bin/env python3
"""
V13 BEST-RULES — FOLKLORE F-8 GOLDEN CROSS (single-pair form).
Spec: BEST-RULES-SPEC.md (frozen before this run).
Signal: SPY SMA50 vs SMA200 (adjusted closes) with a +/-0.5% hysteresis band:
enter risk-on only at margin >= +0.5%, exit to defensive only at margin <= -0.5%,
inside the band the prior state persists. Risk-on leg = SPY, defensive leg = GLD
(held unconditionally on the defensive side; no gold signal). Daily evaluation,
signals on closes, switches at next open. Costs 0.10%/side + $0.01/sell order.
No floor. $100 fresh pot/road. Placebos: 20 circular-shift twins of the state
series per road (v11 design). Data (read-only): pxfull SPY (v7 cache), GLD
(v12 value-momentum-ey cache) — both 2008->2026, full warm-up.
"""
import json, os, random, statistics, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
GLD_PX = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/value-momentum-ey/data/pxfull_GLD.json")
COST = 0.001
SELL_FEE = 0.01
START = 100.0
BAND = 0.005
WINDOWS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CONF = {"CONF_A_2010_2018": ("2010-01-04", "2018-12-31"), "CONF_B_2013_2022": ("2013-01-02", "2022-12-30")}

def load_bars(path):
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o * r, "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

SPY = load_bars(SPY_PX)
GLD = load_bars(GLD_PX)
GLD_BY_DATE = {b["d"]: b for b in GLD}
DATES = [b["d"] for b in SPY]
# forward-fill GLD onto SPY calendar (both are NYSE ETFs; calendars should match)
_g = None
for b in SPY:
    if b["d"] in GLD_BY_DATE: _g = GLD_BY_DATE[b["d"]]
    b["g_o"], b["g_c"] = _g["o"], _g["c"]

# ---- band state machine over full history (state decided at each close) ----
def build_states():
    C = [b["c"] for b in SPY]
    states = {}  # date -> True risk-on (SPY) / False defensive (GLD)
    s50 = s200 = 0.0
    state = False  # defensive default before any decisive cross
    for i, c in enumerate(C):
        s50 += c; s200 += c
        if i >= 50: s50 -= C[i - 50]
        if i >= 200: s200 -= C[i - 200]
        if i >= 199:
            margin = (s50 / 50.0) / (s200 / 200.0) - 1.0
            if margin >= BAND: state = True
            elif margin <= -BAND: state = False
            states[SPY[i]["d"]] = state
    return states

STATES = build_states()

def run_window(start, end, state_map):
    """state_map: date -> desired state at that close. Start flat cash; the state
    in force at the close before the window seeds the first open (v11 seeding)."""
    idx = [i for i, b in enumerate(SPY) if start <= b["d"] <= end]
    cash, spy_sh, gld_sh = START, 0.0, 0.0
    costs, orders, switches = 0.0, 0, 0
    curve, invested = [], 0
    pending = None
    # seed: state at last close before window
    prior = [SPY[i]["d"] for i in range(idx[0]) if SPY[i]["d"] in state_map]
    if prior: pending = state_map[prior[-1]]
    for k, i in enumerate(idx):
        b = SPY[i]
        if pending is not None:
            want_spy = pending
            if want_spy and spy_sh == 0:
                if gld_sh > 0:
                    val = gld_sh * b["g_o"]; fee = val * COST + SELL_FEE
                    costs += fee; cash = val - fee; gld_sh = 0.0; orders += 1
                spy_sh = cash / (b["o"] * (1 + COST)); costs += cash * COST; cash = 0.0
                orders += 1; switches += 1
            elif not want_spy and gld_sh == 0:
                if spy_sh > 0:
                    val = spy_sh * b["o"]; fee = val * COST + SELL_FEE
                    costs += fee; cash = val - fee; spy_sh = 0.0; orders += 1
                gld_sh = cash / (b["g_o"] * (1 + COST)); costs += cash * COST; cash = 0.0
                orders += 1; switches += 1
            pending = None
        val = cash + spy_sh * b["c"] + gld_sh * b["g_c"]
        curve.append([b["d"], round(val, 2)])
        invested += 1 if spy_sh > 0 else 0
        if k < len(idx) - 1:
            w = state_map.get(b["d"])
            if w is not None and w != (spy_sh > 0): pending = w
    final = curve[-1][1] if curve else START
    peak, maxdd, dd_date = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > maxdd: maxdd, dd_date = (peak - v) / peak, d
    yrs = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    return {"final": final, "cagr_pct": round(((final / START) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": dd_date, "costs": round(costs, 2),
            "orders": orders, "switches": switches,
            "time_in_spy_pct": round(100 * invested / max(len(idx), 1), 1), "equity_curve": curve}

def buy_hold(start, end):
    idx = [i for i, b in enumerate(SPY) if start <= b["d"] <= end]
    first, last = SPY[idx[0]], SPY[idx[-1]]
    sh = START / (first["o"] * (1 + COST))
    val = sh * last["c"]; final = val - (val * COST + SELL_FEE)
    peak, maxdd, curve = -1.0, 0.0, []
    for i in idx:
        v = sh * SPY[i]["c"]; curve.append([SPY[i]["d"], round(v, 2)])
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

def placebos(start, end):
    idx_dates = [SPY[i]["d"] for i in range(len(SPY)) if start <= SPY[i]["d"] <= end]
    series, cur = [], False
    for d in DATES:
        if d in STATES: cur = STATES[d]
        if start <= d <= end: series.append(cur)
    n = len(series); twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        shift = rng.randrange(1, n)
        shifted = series[shift:] + series[:shift]
        smap = {idx_dates[k]: shifted[k] for k in range(n)}
        # seed for shifted map: state just before window = last shifted value (circular)
        r = run_window(start, end, smap)
        twins.append({"seed": seed, "final": r["final"]})
    return twins

def monthly_dist(curve):
    me = {}
    for d, v in curve: me[d[:7]] = v
    keys = sorted(me)
    rets = [me[keys[i]] / me[keys[i - 1]] - 1 for i in range(1, len(keys))]
    if not rets: return {}
    los, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak, since, longest = -1e18, 0, 0
    for _, v in curve:
        if v >= peak: peak, since = v, 0
        else: since += 1
        longest = max(longest, since)
    return {"median_month_pct": round(statistics.median(rets) * 100, 2),
            "share_months_positive_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "best_month_pct": round(max(rets) * 100, 2), "worst_month_pct": round(min(rets) * 100, 2),
            "longest_losing_month_streak": los, "longest_days_between_highs": longest, "n_months": len(rets)}

def year_folds(curve):
    by_year, folds, prev = {}, {}, None
    for d, v in curve: by_year.setdefault(d[:4], []).append(v)
    for y in sorted(by_year):
        base = prev if prev is not None else START
        folds[y] = {"start_val": round(base, 2), "end_val": by_year[y][-1],
                    "return_pct": round((by_year[y][-1] / base - 1) * 100, 2) if base else None}
        prev = by_year[y][-1]
    return folds

out = {"slug": "folklore-f8-goldencross", "program": "v13-best-rules", "spec": "BEST-RULES-SPEC.md",
       "design": "SPY 50/200 cross, +/-0.5% hysteresis band, risk-on=SPY, defensive=GLD, daily, no floor",
       "champions_vm": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35},
       "spy_reference": {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80},
       "published_form_native_bare_cross": {"LONG": 355.44, "DECADE": 240.15, "CONT": 191.65, "VAL": 152.20},
       "published_placebo_beaten": {"LONG": "1/20", "DECADE": "0/20", "CONT": "1/20", "VAL": "0/20"},
       "windows": {}, "benchmark": {}, "confirmation": {}}

for wname, (s, e) in WINDOWS.items():
    r = run_window(s, e, STATES)
    twins = placebos(s, e)
    beaten = sum(1 for t in twins if r["final"] > t["final"])
    r["placebo_beaten"] = f"{beaten}/20"
    r["placebo_median"] = round(statistics.median([t["final"] for t in twins]), 2)
    r["placebo_twins"] = twins
    r["monthly_distribution"] = monthly_dist(r["equity_curve"])
    out["windows"][wname] = r
    out["benchmark"][wname] = buy_hold(s, e)
    print(wname, "final", r["final"], "cagr", r["cagr_pct"], "maxDD", r["max_dd_pct"], r["max_dd_date"],
          "orders", r["orders"], "inSPY", r["time_in_spy_pct"], "placebo", r["placebo_beaten"],
          "med", r["placebo_median"], "| bench", out["benchmark"][wname]["final"], out["benchmark"][wname]["max_dd_pct"], flush=True)

out["year_folds_LONG"] = year_folds(out["windows"]["LONG"]["equity_curve"])

for name, (s, e) in CONF.items():
    r = run_window(s, e, STATES); spy = buy_hold(s, e)
    out["confirmation"][name] = {"run": {k: r[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders")},
                                 "spy": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]},
                                 "equity_curve": r["equity_curve"]}
    print(name, r["final"], "spy", spy["final"], flush=True)

# fresh-$100 calendar-year folds
folds = {}
for y in range(2010, 2027):
    days = [d for d in DATES if f"{y}-01-01" <= d <= f"{y}-12-31"]
    if len(days) < 20: continue
    r = run_window(days[0], days[-1], STATES)
    folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
out["year_folds_fresh_pot"] = folds
vals = [v["final"] - 100 for v in folds.values()]
out["year_fold_summary"] = {"median_year_pct": round(statistics.median(vals), 2),
    "share_years_positive_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
    "best_year": max(folds, key=lambda k: folds[k]["final"]),
    "worst_year": min(folds, key=lambda k: folds[k]["final"])}
print("folds", folds, flush=True)

with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
print("WROTE results.json")
