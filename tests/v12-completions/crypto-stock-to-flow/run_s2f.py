#!/usr/bin/env python3
"""crypto-stock-to-flow — frozen as-published S2F (PlanB 2019) + S2FX prediction check
+ CONSTRUCTED deviation-multiple trading form. No re-fitting anywhere.
Spec: CONSTRUCTION-SPEC.md (frozen before this run). Data: shared v4 BTC-USD.csv (read-only).
"""
import json, math, random
import pandas as pd
import numpy as np

DATA = "/home/hatch/workspace/stock-app/backtests/v4/crypto-trend-data/BTC-USD.csv"
OUT = "/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-stock-to-flow/results.json"
COST = 0.006  # 0.60%/side, v12 crypto-wing standard
START = 100.0

# Frozen published parameters (2019 S2F, fit Dec 2009-Feb 2019, 111 monthly pts)
SLOPE, INTERCEPT = 3.31954, 14.6227
# S2FX (2020): MV = exp(12.7598) * SF^4.1167 ; phase prediction $288k avg 2020-2024
S2FX_SLOPE, S2FX_INT = 4.1167, 12.7598

ERAS = [  # (era_start, stock_at_start, subsidy)
    ("2009-01-03", 0.0, 50.0),
    ("2012-11-28", 10_500_000.0, 25.0),
    ("2016-07-09", 15_750_000.0, 12.5),
    ("2020-05-11", 18_375_000.0, 6.25),
    ("2024-04-20", 19_687_500.0, 3.125),
]

df = pd.read_csv(DATA, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
era_starts = [(pd.Timestamp(d), s, r) for d, s, r in ERAS]

def stock_flow(date):
    for i in range(len(era_starts) - 1, -1, -1):
        d0, s0, r = era_starts[i]
        if date >= d0:
            days = (date - d0).days
            stock = s0 + r * 144 * days
            flow = r * 144 * 365
            return stock, flow
    raise ValueError(date)

stocks, flows = zip(*[stock_flow(d) for d in df["date"]])
df["stock"] = stocks; df["flow"] = flows
df["adj_stock"] = df["stock"] - 1_000_000.0
df["sf"] = df["adj_stock"] / df["flow"]
df["model_mv"] = math.exp(INTERCEPT) * df["sf"] ** SLOPE
df["model_price"] = df["model_mv"] / df["adj_stock"]
df["multiple"] = df["close"] / df["model_price"]
df["s2fx_mv"] = math.exp(S2FX_INT) * df["sf"] ** S2FX_SLOPE
df["s2fx_price"] = df["s2fx_mv"] / df["adj_stock"]

def max_dd(curve):
    c = np.array(curve, dtype=float); peak = np.maximum.accumulate(c)
    return float(((c - peak) / peak).min()) if len(c) else 0.0

def run_window(wdf, floor=False):
    """Monthly rebalance: signal on last close of month, trade next day open.
    wdf must start the day before the window for the first signal; we handle by
    requiring wdf includes a pre-window signal row flagged separately."""
    cash, btc = START, 0.0
    invested = False
    trades = 0; costs = 0.0
    curve_dates, curve = [], []
    exposure_days, total_days = 0, 0
    halted = None
    # month-end signal dates within wdf (using full df calendar for signal correctness)
    wdf = wdf.reset_index(drop=True)
    # signals: for each row that is last trading day of its month in the FULL df
    full = df.set_index("date")
    month_last = set(full.groupby([full.index.year, full.index.month]).apply(lambda g: g.index.max()))
    pending = None  # target invested bool to execute at today's open
    for i, row in wdf.iterrows():
        d = row["date"]
        if pending is not None:
            if pending and not invested:
                spend = cash; fee = spend * COST; btc = (spend - fee) / row["open"]
                cash = 0.0; invested = True; trades += 1; costs += fee
            elif not pending and invested:
                gross = btc * row["open"]; fee = gross * COST; cash = gross - fee
                btc = 0.0; invested = False; trades += 1; costs += fee
            pending = None
        eq = cash + btc * row["close"]
        curve_dates.append(str(d.date())); curve.append(round(eq, 4))
        total_days += 1; exposure_days += 1 if invested else 0
        if floor and eq <= 85.0 and halted is None:
            # liquidate at next open: emulate by selling at next row open if exists
            if i + 1 < len(wdf):
                nxt = wdf.iloc[i + 1]
                if invested:
                    gross = btc * nxt["open"]; fee = gross * COST; cash = gross - fee
                    btc = 0.0; invested = False; trades += 1; costs += fee
                eq2 = cash
                curve_dates.append(str(nxt["date"].date())); curve.append(round(eq2, 4))
            halted = str(d.date()); break
        if d in month_last:
            pending = bool(row["multiple"] < 1.0)
    final = curve[-1] if curve else START
    return {"final": round(final, 2), "max_dd_pct": round(max_dd(curve) * 100, 1),
            "trades": trades, "costs": round(costs, 2),
            "exposure_pct": round(100 * exposure_days / max(total_days, 1), 1),
            "halted": halted, "curve_dates": curve_dates, "curve": curve}

def buy_hold(wdf):
    wdf = wdf.reset_index(drop=True)
    fee = START * COST; btc = (START - fee) / wdf.iloc[0]["open"]
    curve = [round(btc * c, 4) for c in wdf["close"]]
    return {"final": round(curve[-1], 2), "max_dd_pct": round(max_dd(curve) * 100, 1),
            "costs": round(fee, 2), "curve": curve}

WINDOWS = {
    "FULL_insample_contaminated": ("2014-09-17", "2026-11-20"),
    "POSTPUB": ("2019-03-22", "2026-11-20"),
    "CONT": ("2019-01-01", "2026-11-20"),
    "VAL": ("2023-01-01", "2026-11-20"),
}

results = {"family": "crypto-stock-to-flow", "constructed_label": "CONSTRUCTED",
           "model_params_frozen": {"slope": SLOPE, "intercept": INTERCEPT, "fit_window": "Dec 2009-Feb 2019 monthly, 111 pts"},
           "cost_per_side": COST, "windows": {}}

for name, (a, b) in WINDOWS.items():
    # include one pre-window day so a month-end signal just before start can execute
    sub_all = df[(df["date"] >= pd.Timestamp(a) - pd.Timedelta(days=35)) & (df["date"] <= b)].copy()
    sub = df[(df["date"] >= a) & (df["date"] <= b)].copy()
    # run strategy on sub_all but trim curve to window: simpler—run on sub with signal
    # generated from sub's own month-ends plus initial position from last pre-window signal:
    pre = sub_all[sub_all["date"] < pd.Timestamp(a)]
    init_long = bool(pre.iloc[-1]["multiple"] < 1.0) if len(pre) else False
    # monkey-run: temporarily set first pending by prepending a synthetic signal row
    nat = run_window(sub, floor=False)
    # adjust: if init_long, the strategy should have entered at window open. Re-run properly:
    def run2(wdf, floor=False, init_long=False):
        cash, btc = START, 0.0; invested = False; trades = 0; costs = 0.0
        curve_dates, curve = [], []; exp_d, tot = 0, 0; halted = None
        full = df.set_index("date")
        month_last = set(full.groupby([full.index.year, full.index.month]).apply(lambda g: g.index.max()))
        wdf = wdf.reset_index(drop=True)
        pending = init_long
        for i, row in wdf.iterrows():
            d = row["date"]
            if pending is not None:
                if pending and not invested:
                    fee = cash * COST; btc = (cash - fee) / row["open"]; cash = 0.0
                    invested = True; trades += 1; costs += fee
                elif not pending and invested:
                    gross = btc * row["open"]; fee = gross * COST; cash = gross - fee
                    btc = 0.0; invested = False; trades += 1; costs += fee
                pending = None
            eq = cash + btc * row["close"]
            curve_dates.append(str(d.date())); curve.append(round(eq, 4))
            tot += 1; exp_d += 1 if invested else 0
            if floor and eq <= 85.0 and halted is None:
                if i + 1 < len(wdf):
                    nxt = wdf.iloc[i + 1]
                    if invested:
                        gross = btc * nxt["open"]; fee = gross * COST; cash = gross - fee
                        btc = 0.0; invested = False; trades += 1; costs += fee
                    curve_dates.append(str(nxt["date"].date())); curve.append(round(cash, 4))
                halted = str(d.date()); break
            if d in month_last:
                pending = bool(row["multiple"] < 1.0)
        return {"final": round(curve[-1], 2), "max_dd_pct": round(max_dd(curve) * 100, 1),
                "trades": trades, "costs": round(costs, 2),
                "exposure_pct": round(100 * exp_d / max(tot, 1), 1), "halted": halted,
                "curve_dates": curve_dates, "curve": curve}
    nat = run2(sub, False, init_long)
    v9 = run2(sub, True, init_long)
    bh = buy_hold(sub)
    results["windows"][name] = {"native_constructed": {k: v for k, v in nat.items()},
                                "v9_floor_constructed": {k: v for k, v in v9.items()},
                                "btc_buy_hold": bh}
    # placebos on POSTPUB and VAL (native)
    if name in ("POSTPUB", "VAL"):
        rng_master = random.Random(20261122)
        finals = []
        exp_frac = nat["exposure_pct"] / 100.0
        months = sub.copy()
        full = df.set_index("date")
        month_last = sorted([d for d in full.groupby([full.index.year, full.index.month]).apply(lambda g: g.index.max()) if pd.Timestamp(a) <= d <= pd.Timestamp(b)])
        for seed in range(20):
            rng = random.Random(rng_master.random())
            cash, btc, invested = START, 0.0, False; curve = []
            sub_r = sub.reset_index(drop=True)
            pending = rng.random() < exp_frac
            for i, row in sub_r.iterrows():
                if pending is not None:
                    if pending and not invested:
                        fee = cash * COST; btc = (cash - fee) / row["open"]; cash = 0.0; invested = True
                    elif not pending and invested:
                        gross = btc * row["open"]; fee = gross * COST; cash = gross - fee; btc = 0.0; invested = False
                    pending = None
                curve.append(cash + btc * row["close"])
                if row["date"] in set(month_last):
                    pending = rng.random() < exp_frac
            finals.append(round(curve[-1], 2))
        finals_sorted = sorted(finals)
        strat = nat["final"]
        pct = round(100 * sum(1 for f in finals if f < strat) / len(finals), 0)
        results["windows"][name]["placebo_20seed"] = {
            "median": float(np.median(finals)), "min": finals_sorted[0], "max": finals_sorted[-1],
            "strategy_percentile": pct, "finals": finals_sorted}
    # confirmation halves if constructed beats hold
    if nat["final"] > bh["final"]:
        mid = sub.iloc[len(sub) // 2]["date"]
        halves = {}
        for hn, (ha, hb) in {"H1": (a, str(mid.date())), "H2": (str(mid.date()), b)}.items():
            hsub = df[(df["date"] >= ha) & (df["date"] <= hb)]
            hpre = df[(df["date"] >= pd.Timestamp(ha) - pd.Timedelta(days=35)) & (df["date"] < pd.Timestamp(ha))]
            hil = bool(hpre.iloc[-1]["multiple"] < 1.0) if len(hpre) else False
            hn_ = run2(hsub, False, hil); hb_ = buy_hold(hsub)
            halves[hn] = {"constructed": hn_["final"], "btc_hold": hb_["final"]}
        results["windows"][name]["confirmation_halves"] = halves

# ---------- Finding A: predictions vs reality ----------
post = df[df["date"] >= "2019-03-22"].copy()
def era_stats(dsub):
    if len(dsub) == 0: return {}
    m = dsub["multiple"]
    return {"days": int(len(dsub)), "median_multiple": round(float(m.median()), 3),
            "share_within_2x": round(float(((m >= 0.5) & (m <= 2.0)).mean()), 3),
            "share_below_model": round(float((m < 1.0).mean()), 3)}
findingA = {
    "postpub_overall": era_stats(post),
    "era_pre2020halving": era_stats(df[(df["date"] >= "2019-03-22") & (df["date"] < "2020-05-11")]),
    "era_2020_2024_phase": era_stats(df[(df["date"] >= "2020-05-11") & (df["date"] < "2024-04-20")]),
    "era_post2024halving": era_stats(df[df["date"] >= "2024-04-20"]),
}
# F1: first close >= 55000 and model checkpoints
d55 = df[df["close"] >= 55000]
findingA["F1_55k"] = {"first_close_ge_55k": str(d55.iloc[0]["date"].date()) if len(d55) else None,
                      "halving_2020": "2020-05-11", "verdict": "REACHED within 1-2y window"}
# F2/F3 dated closes
def close_on(d):
    r = df[df["date"] == d]
    return round(float(r.iloc[0]["close"]), 2) if len(r) else None
findingA["F2_dec2021_100k"] = {"close_2021-12-31": close_on("2021-12-31"), "target": 100000, "verdict": "MISSED (author withdrew test 2021-12-24)"}
findingA["F3_floor_model"] = {"close_2021-11-30": close_on("2021-11-30"), "floor_nov": 98000,
                              "close_2021-12-31": close_on("2021-12-31"), "floor_dec": 135000,
                              "verdict": "MISSED both (author: 'floor model fail')"}
r_20220618 = df[df["date"] == "2022-06-18"].iloc[0]
findingA["F4_band"] = {"close_2022-06-18": round(float(r_20220618["close"]), 2),
                       "author_band_described": "$50K-$200K", "model_price_that_day": round(float(r_20220618["model_price"]), 2),
                       "multiple_that_day": round(float(r_20220618["multiple"]), 3),
                       "verdict": "BREACHED below band Jun 2022, ~6 months into the 2.5y window"}
phase = df[(df["date"] >= "2020-05-11") & (df["date"] < "2024-04-20")]
findingA["F5_s2fx_288k"] = {"phase_avg_close": round(float(phase["close"].mean()), 2),
                            "phase_max_close": round(float(phase["close"].max()), 2),
                            "s2fx_prediction_avg": 288000,
                            "s2fx_implied_price_at_sf56_check": round(float(df[df["date"] == "2020-05-11"].iloc[0]["s2fx_price"]), 2),
                            "verdict": "MISSED — phase never averaged or even peaked near $288K"}
last = df.iloc[-1]
findingA["endpoint_2026-11-20"] = {"close": round(float(last["close"]), 2),
                                   "model_price": round(float(last["model_price"]), 2),
                                   "multiple": round(float(last["multiple"]), 3),
                                   "sf": round(float(last["sf"]), 1)}
# last date price was above model
above = post[post["multiple"] >= 1.0]
findingA["last_day_at_or_above_model_postpub"] = str(above.iloc[-1]["date"].date()) if len(above) else None
# band-breach log: contiguous stretches M<0.5 lasting >=30 days
breaches = []
in_b = None
for i, row in post.iterrows():
    if row["multiple"] < 0.5 and in_b is None:
        in_b = {"start": str(row["date"].date()), "min_multiple": float(row["multiple"]), "days": 1}
    elif row["multiple"] < 0.5 and in_b is not None:
        in_b["days"] += 1; in_b["min_multiple"] = min(in_b["min_multiple"], float(row["multiple"]))
    elif row["multiple"] >= 0.5 and in_b is not None:
        in_b["end"] = str(post.loc[i - 1, "date"].date()) if i > 0 else in_b["start"]
        if in_b["days"] >= 30: breaches.append({k: (round(v, 3) if isinstance(v, float) else v) for k, v in in_b.items()})
        in_b = None
if in_b is not None:
    in_b["end"] = str(post.iloc[-1]["date"].date()) + " (still breached at data end)"
    if in_b["days"] >= 30: breaches.append({k: (round(v, 3) if isinstance(v, float) else v) for k, v in in_b.items()})
findingA["band_breach_log_M_below_0.5_ge30d"] = breaches
results["finding_A_predictions_vs_reality"] = findingA

# daily curve for charting: date, close, model_price, multiple (postpub)
results["daily_model_series_postpub"] = [
    {"date": str(r["date"].date()), "close": round(float(r["close"]), 2),
     "model_price": round(float(r["model_price"]), 2), "multiple": round(float(r["multiple"]), 4)}
    for _, r in post.iterrows()]

with open(OUT, "w") as f:
    json.dump(results, f, indent=1)
print(json.dumps({k: {kk: {kkk: vvv for kkk, vvv in vv.items() if kkk not in ("curve", "curve_dates")} if isinstance(vv, dict) else vv
                      for kk, vv in v.items()} if isinstance(v, dict) else v
                  for k, v in results["windows"].items()}, indent=1))
print(json.dumps(findingA, indent=1))
