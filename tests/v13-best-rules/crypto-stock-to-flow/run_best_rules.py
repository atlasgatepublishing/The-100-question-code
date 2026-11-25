#!/usr/bin/env python3
"""V13 BEST RULES — crypto-stock-to-flow.
Frozen spec: BEST-RULES-SPEC.md. S2F multiple M identical to v12 (frozen published
params, calendar-block supply, adj-stock basis). Signal: R = M / trailing-48-month-end
median of M; monthly dial to target weight at next open; 0.60%/side on traded amount.
Placebos: 20 seeds, random weights from same levels, same average exposure.
"""
import json, math, random, statistics
import pandas as pd
import numpy as np

DATA = "/home/hatch/workspace/stock-app/backtests/v4/crypto-trend-data/BTC-USD.csv"
OUT = "/home/hatch/workspace/stock-app/backtests/v13-best-rules/crypto-stock-to-flow/results.json"
COST = 0.006
START = 100.0
SLOPE, INTERCEPT = 3.31954, 14.6227
ERAS = [("2009-01-03", 0.0, 50.0), ("2012-11-28", 10_500_000.0, 25.0),
        ("2016-07-09", 15_750_000.0, 12.5), ("2020-05-11", 18_375_000.0, 6.25),
        ("2024-04-20", 19_687_500.0, 3.125)]
LEVELS = [1.00, 0.85, 0.65, 0.40, 0.15]

df = pd.read_csv(DATA, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
era_starts = [(pd.Timestamp(d), s, r) for d, s, r in ERAS]

def stock_flow(date):
    for i in range(len(era_starts) - 1, -1, -1):
        d0, s0, r = era_starts[i]
        if date >= d0:
            days = (date - d0).days
            return s0 + r * 144 * days, r * 144 * 365
    raise ValueError(date)

stocks, flows = zip(*[stock_flow(d) for d in df["date"]])
df["stock"] = stocks; df["flow"] = flows
df["adj_stock"] = df["stock"] - 1_000_000.0
df["sf"] = df["adj_stock"] / df["flow"]
df["model_price"] = math.exp(INTERCEPT) * df["sf"] ** SLOPE / df["adj_stock"]
df["multiple"] = df["close"] / df["model_price"]

full_idx = df.set_index("date")
month_last = sorted(full_idx.groupby([full_idx.index.year, full_idx.index.month]).apply(lambda g: g.index.max()))
month_last_set = set(month_last)

# month-end M series and trailing-48 median -> target weight per month-end date
me_M = {d: float(df.loc[df["date"] == d, "multiple"].iloc[0]) for d in month_last}
me_dates = sorted(me_M)
def target_weight(signal_date):
    hist = [me_M[d] for d in me_dates if d <= signal_date][-48:]
    if len(hist) < 48:
        return 1.00, None
    med = statistics.median(hist)
    R = me_M[signal_date] / med
    if R < 0.50: w = 1.00
    elif R < 1.00: w = 0.85
    elif R < 2.00: w = 0.65
    elif R < 4.00: w = 0.40
    else: w = 0.15
    return w, round(R, 4)

def max_dd(curve):
    c = np.array(curve, dtype=float); peak = np.maximum.accumulate(c)
    return float(((c - peak) / peak).min()) if len(c) else 0.0

def run_dial(wdf, weight_fn):
    """weight_fn(signal_date)->target weight or None. Initial target from last
    pre-window month-end (or window's first month-end logic handled by caller
    passing init_weight)."""
    wdf = wdf.reset_index(drop=True)
    cash, btc = START, 0.0
    trades = 0; costs = 0.0
    curve_dates, curve = [], []
    exp_sum, tot = 0.0, 0
    pending = weight_fn("INIT")
    signals = []
    for i, row in wdf.iterrows():
        d = row["date"]
        if pending is not None:
            eq_open = cash + btc * row["open"]
            target_val = pending * eq_open
            cur_val = btc * row["open"]
            delta = target_val - cur_val
            if abs(delta) > 1e-9:
                fee = abs(delta) * COST
                if delta > 0:
                    buy = delta - fee if delta - fee > 0 else 0.0
                    # spend delta incl fee from cash
                    spend = min(delta, cash)
                    fee = spend * COST / (1 + COST) * 1.0  # fee carved from spend
                    # simpler consistent convention: fee = |delta|*COST paid from pot
                    fee = abs(delta) * COST
                    btc += (delta) / row["open"]
                    cash -= delta + (fee if delta > 0 else -fee) * 0  # placeholder replaced below
                    cash = eq_open - fee - btc * row["open"]
                else:
                    btc += delta / row["open"]
                    fee = abs(delta) * COST
                    cash = eq_open - fee - btc * row["open"]
                trades += 1; costs += fee
            pending = None
        eq = cash + btc * row["close"]
        curve_dates.append(str(d.date())); curve.append(round(eq, 4))
        tot += 1; exp_sum += (btc * row["close"] / eq) if eq > 0 else 0.0
        if d in month_last_set:
            w = weight_fn(d)
            if w is not None:
                pending = w
                signals.append({"date": str(d.date()), "weight": w})
    return {"final": round(curve[-1], 2), "max_dd_pct": round(max_dd(curve) * 100, 1),
            "trades": trades, "costs": round(costs, 2),
            "avg_exposure_pct": round(100 * exp_sum / max(tot, 1), 1),
            "curve_dates": curve_dates, "curve": curve, "signals": signals}

def buy_hold(wdf):
    wdf = wdf.reset_index(drop=True)
    fee = START * COST; btc = (START - fee) / wdf.iloc[0]["open"]
    curve = [round(btc * c, 4) for c in wdf["close"]]
    return {"final": round(curve[-1], 2), "max_dd_pct": round(max_dd(curve) * 100, 1),
            "costs": round(fee, 2), "curve": curve}

def period_stats(dates, curve):
    s = pd.Series(curve, index=pd.to_datetime(dates))
    m = s.resample("M").last().dropna()
    rets = m.pct_change().dropna()
    if len(rets) == 0: return {}
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak_date = s.idxmax()
    # longest stretch between new highs (days)
    runmax = s.cummax(); last_high = s.index[0]; longest = 0
    prev_high_val = -1
    for dt, v in s.items():
        if v >= runmax.loc[dt] - 1e-12 and v > prev_high_val:
            longest = max(longest, (dt - last_high).days); last_high = dt; prev_high_val = v
    longest = max(longest, (s.index[-1] - last_high).days)
    return {"periods": int(len(rets)), "share_positive_pct": round(100 * float((rets > 0).mean()), 1),
            "median_pct": round(100 * float(rets.median()), 2),
            "mean_pct_secondary": round(100 * float(rets.mean()), 2),
            "best_pct": round(100 * float(rets.max()), 2), "best_period": str(rets.idxmax().date()),
            "worst_pct": round(100 * float(rets.min()), 2), "worst_period": str(rets.idxmin().date()),
            "longest_losing_streak": int(los), "longest_between_highs_days": int(longest)}

WINDOWS = {"FULL_insample_contaminated": ("2014-09-17", "2026-11-20"),
           "POSTPUB": ("2019-03-22", "2026-11-20"),
           "CONT": ("2019-01-01", "2026-11-20"),
           "VAL": ("2023-01-01", "2026-11-20")}

def init_weight_for(a):
    pre = [d for d in me_dates if d < pd.Timestamp(a)]
    if not pre: return 1.00
    return target_weight(pre[-1])[0]

results = {"family": "crypto-stock-to-flow", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "model_params_frozen": {"slope": SLOPE, "intercept": INTERCEPT,
                                   "fit_window": "Dec 2009-Feb 2019 monthly, 111 pts"},
           "cost_per_side": COST, "windows": {}}
log = []
for name, (a, b) in WINDOWS.items():
    sub = df[(df["date"] >= a) & (df["date"] <= b)].copy()
    iw = init_weight_for(a)
    state = {"init_done": False}
    def wf(d, iw=iw, state=state):
        if d == "INIT":
            return iw
        return target_weight(d)[0]
    mine = run_dial(sub, wf)
    bh = buy_hold(sub)
    results["windows"][name] = {"my_rules": mine, "btc_buy_hold": bh,
                                "period_distribution_my_rules": period_stats(mine["curve_dates"], mine["curve"]),
                                "period_distribution_buy_hold": period_stats(mine["curve_dates"], bh["curve"])}
    log.append(f"{name}: my={mine['final']} dd={mine['max_dd_pct']} trades={mine['trades']} avgexp={mine['avg_exposure_pct']} | hold={bh['final']} dd={bh['max_dd_pct']}")
    if name in ("POSTPUB", "VAL"):
        avg_exp = mine["avg_exposure_pct"] / 100.0
        # choose level probabilities to match avg exposure: sample weights with
        # probabilities proportional to closeness — use empirical approach:
        # draw from levels with probs solved simply: mix of nearest two levels.
        lo = max([L for L in LEVELS if L <= avg_exp], default=0.15)
        hi = min([L for L in LEVELS if L >= avg_exp], default=1.00)
        p_hi = 0.0 if hi == lo else (avg_exp - lo) / (hi - lo)
        finals = []
        rng_master = random.Random(20261122)
        mls = [d for d in month_last if pd.Timestamp(a) <= d <= pd.Timestamp(b)]
        for seed in range(20):
            rng = random.Random(rng_master.random())
            iw_p = hi if rng.random() < p_hi else lo
            def wf_p(d, rng=rng, iw_p=iw_p, p_hi=p_hi, hi=hi, lo=lo):
                if d == "INIT": return iw_p
                return hi if rng.random() < p_hi else lo
            r = run_dial(sub, wf_p)
            finals.append(r["final"])
        fs = sorted(finals)
        pct = round(100 * sum(1 for f in finals if f < mine["final"]) / len(finals), 0)
        results["windows"][name]["placebo_20seed"] = {
            "median": float(np.median(finals)), "min": fs[0], "max": fs[-1],
            "strategy_percentile": pct, "finals": fs,
            "note": "random monthly weights from the two dial levels bracketing the strategy's average exposure, same costs/timing"}
        log.append(f"  placebo {name}: median={np.median(finals):.2f} range={fs[0]}-{fs[-1]} strat_pctile={pct}")

# Confirmation folds frozen in spec
FOLDS = {"FOLD_2019_2022": ("2019-01-01", "2022-12-31")}
# halves of POSTPUB
pp = df[(df["date"] >= "2019-03-22") & (df["date"] <= "2026-11-20")]
mid = pp.iloc[len(pp) // 2]["date"]
FOLDS["POSTPUB_H1"] = ("2019-03-22", str(mid.date()))
FOLDS["POSTPUB_H2"] = (str(mid.date()), "2026-11-20")
results["confirmation_folds"] = {}
for name, (a, b) in FOLDS.items():
    sub = df[(df["date"] >= a) & (df["date"] <= b)].copy()
    iw = init_weight_for(a)
    def wf(d, iw=iw):
        if d == "INIT": return iw
        return target_weight(d)[0]
    mine = run_dial(sub, wf); bh = buy_hold(sub)
    results["confirmation_folds"][name] = {
        "my_rules_final": mine["final"], "my_rules_max_dd_pct": mine["max_dd_pct"],
        "btc_buy_hold_final": bh["final"], "btc_buy_hold_max_dd_pct": bh["max_dd_pct"],
        "trades": mine["trades"], "curve_dates": mine["curve_dates"], "curve": mine["curve"],
        "buy_hold_curve": bh["curve"]}
    log.append(f"FOLD {name} ({a}->{b}): my={mine['final']} dd={mine['max_dd_pct']} | hold={bh['final']}")

with open(OUT, "w") as f:
    json.dump(results, f, indent=1)
print("\n".join(log))
