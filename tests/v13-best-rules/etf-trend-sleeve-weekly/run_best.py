#!/usr/bin/env python3
"""
V13 BEST RULES — etf-trend-sleeve-weekly. Frozen spec: BEST-RULES-SPEC.md.

MY RULES: 7-ETF universe (SPY QQQ TLT IEF GLD DBC UUP); WEEKLY cadence (first
trading day of each ISO week, signals from prior close, trades at open);
trend = BOTH 126d and 252d adjusted-close returns > 0 (63d leg dropped);
weights = capped (40%) inverse trailing-60d vol, remainder cash; 20% relative
no-trade band (entries/exits always trade); costs 0.10%/side + $0.01/sell;
NO floor, no ladder. $100 pots. Data: read-only shared cache v3/data_etf.
Placebos (20 seeds/road): random-selection twins (same k, same weighting) and
random-timing twins (real targets, rebalance day randomized within the week).
"""
import json, os, random, statistics
from datetime import datetime

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "UUP"]
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
COST_RATE = 0.0010
SELL_FEE = 0.01
START_CASH = 100.0

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}

# ---------------------------------------------------------------- data layer
def _load_raw(ticker):
    with open(os.path.join(SRC_CACHE, f"{ticker}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    return out

RAW = {t: _load_raw(t) for t in ASSETS}
CAL = sorted(RAW["SPY"].keys())
CIDX = {d: i for i, d in enumerate(CAL)}
N = len(CAL)

CLOSE, OPENP = {}, {}
for t in ASSETS:
    s = RAW[t]
    closes, opens, last = [], [], None
    for d in CAL:
        if d in s:
            last = s[d][1]
            closes.append(last)
            opens.append(s[d][0])
        else:
            closes.append(last)
            opens.append(last)
    CLOSE[t] = closes
    OPENP[t] = opens

# signals: PASS[i] = both 126d & 252d returns > 0 at close index i; VOL60[i]
PASS, VOL = {}, {}
for t in ASSETS:
    cl = CLOSE[t]
    ps, vol = [None] * N, [None] * N
    for i in range(N):
        if i < 252 or cl[i] is None or cl[i - 252] is None or cl[i - 126] is None:
            continue
        ps[i] = (cl[i] / cl[i - 126] - 1.0 > 0) and (cl[i] / cl[i - 252] - 1.0 > 0)
        rets = [cl[j] / cl[j - 1] - 1.0 for j in range(i - 59, i + 1)]
        vol[i] = statistics.pstdev(rets)
    PASS[t] = ps
    VOL[t] = vol

def capped_inv_vol_weights(vols):
    inv = {t: 1.0 / v for t, v in vols.items() if v and v > 0}
    if not inv:
        return {}
    weights, remaining, budget = {}, dict(inv), 1.0
    while remaining:
        tot = sum(remaining.values())
        over = [t for t in remaining if budget * remaining[t] / tot > 0.40]
        if not over:
            for t in remaining:
                weights[t] = budget * remaining[t] / tot
            break
        for t in over:
            weights[t] = 0.40
            budget -= 0.40
            del remaining[t]
        if budget <= 0:
            break
    return weights

def targets_at(sig_i, placebo_rng=None):
    passing = [t for t in ASSETS if PASS[t][sig_i] and VOL[t][sig_i]]
    if placebo_rng is None:
        return capped_inv_vol_weights({t: VOL[t][sig_i] for t in passing})
    if not passing:
        return {}
    chosen = placebo_rng.sample(ASSETS, len(passing))
    return capped_inv_vol_weights({t: VOL[t][sig_i] for t in chosen if VOL[t][sig_i]})

# ---------------------------------------------------------------- execution
def execute(cash, shares, trade_set, targets, i):
    orders, costs = 0, 0.0
    eq_open = cash + sum(shares[t] * OPENP[t][i] for t in ASSETS if shares[t] > 0)
    for t in sorted(trade_set):
        tgt_val = targets.get(t, 0.0) * eq_open
        cur_val = shares[t] * OPENP[t][i]
        diff = cur_val - tgt_val
        if diff > 0.01 and shares[t] > 0:
            sell_val = min(diff, cur_val)
            cost = sell_val * COST_RATE + SELL_FEE
            cash += sell_val - cost
            shares[t] -= sell_val / OPENP[t][i]
            if shares[t] < 1e-9:
                shares[t] = 0.0
            orders += 1
            costs += cost
    buy_list = []
    for t in sorted(trade_set):
        tgt_val = targets.get(t, 0.0) * eq_open
        diff = tgt_val - shares[t] * OPENP[t][i]
        if diff > 0.01:
            buy_list.append((t, diff))
    tot_buy = sum(v for _, v in buy_list)
    if tot_buy > 0:
        scale = min(1.0, cash / (tot_buy * (1 + COST_RATE)))
        for t, diff in buy_list:
            buy_val = diff * scale
            if buy_val < 0.01:
                continue
            cost = buy_val * COST_RATE
            cash -= buy_val + cost
            shares[t] += buy_val / OPENP[t][i]
            orders += 1
            costs += cost
    return cash, orders, costs

def trade_set_for_open(cash, shares, targets, i):
    j = i - 1
    eq_c = cash + sum(shares[t] * CLOSE[t][j] for t in ASSETS if shares[t] > 0)
    ts = set()
    for t in ASSETS:
        cur_w = (shares[t] * CLOSE[t][j] / eq_c) if eq_c > 0 else 0.0
        tgt_w = targets.get(t, 0.0)
        held = shares[t] > 0
        if held and tgt_w == 0.0:
            ts.add(t)
        elif not held and tgt_w > 0.0:
            ts.add(t)
        elif held and tgt_w > 0.0 and abs(tgt_w - cur_w) / tgt_w > 0.20:
            ts.add(t)
    return ts

def equity(cash, shares, i):
    return cash + sum(shares[t] * CLOSE[t][i] for t in ASSETS if shares[t] > 0)

def week_key(d):
    return datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2]

def simulate(start, end, sel_seed=None, timing_seed=None):
    """Weekly run. sel_seed -> random-selection placebo. timing_seed ->
    random-timing placebo (real targets, random day within each week)."""
    days = [d for d in CAL if start <= d <= end]
    sel_rng = random.Random(sel_seed) if sel_seed is not None else None
    tim_rng = random.Random(timing_seed) if timing_seed is not None else None
    # rebalance day per week
    by_week = {}
    for d in days:
        by_week.setdefault(week_key(d), []).append(d)
    rebal = set()
    for wk, ds in by_week.items():
        rebal.add(tim_rng.choice(ds) if tim_rng is not None else ds[0])
    cash, shares = START_CASH, {t: 0.0 for t in ASSETS}
    orders, total_costs, curve = 0, 0.0, []
    for d in days:
        i = CIDX[d]
        if d in rebal and i >= 1:
            targets = targets_at(i - 1, placebo_rng=sel_rng)
            ts = trade_set_for_open(cash, shares, targets, i)
            if ts:
                cash, o, c = execute(cash, shares, ts, targets, i)
                orders += o
                total_costs += c
        curve.append((d, equity(cash, shares, i)))
    return {"final": curve[-1][1], "curve": curve, "orders": orders,
            "costs": total_costs, "days": days}

# ------------------------------------------------------------------ metrics
def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd * 100

def monthly_distribution(curve):
    """Monthly period stats from a daily (date, equity) curve."""
    months, order = {}, []
    for d, eq in curve:
        k = d[:7]
        if k not in months:
            months[k] = []
            order.append(k)
        months[k].append(eq)
    rets = []
    prev_end = None
    for k in order:
        end_eq = months[k][-1]
        base = prev_end if prev_end is not None else months[k][0]
        # first month: base is the start-of-run equity (curve starts at 100
        # pre-trade close of day 1); use first day equity as base proxy only
        # for month 1 by comparing to START via prev_end=None handling below
        rets.append(end_eq / base - 1.0 if base else 0.0)
        prev_end = end_eq
    # longest losing streak (consecutive negative months)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (trading days)
    peak, since, worst = -1e18, 0, 0
    for _, eq in curve:
        if eq >= peak:
            peak, since = eq, 0
        else:
            since += 1
            worst = max(worst, since)
    pos = sum(1 for r in rets if r > 0)
    return {"n_months": len(rets),
            "median_month_pct": round(statistics.median(rets) * 100, 2),
            "share_positive_pct": round(100.0 * pos / len(rets), 1) if rets else None,
            "best_month_pct": round(max(rets) * 100, 2) if rets else None,
            "worst_month_pct": round(min(rets) * 100, 2) if rets else None,
            "longest_losing_streak_months": longest,
            "longest_stretch_between_new_highs_days": worst}

def spy_buy_hold(start, end):
    days = [d for d in CAL if start <= d <= end]
    i0, i1 = CIDX[days[0]], CIDX[days[-1]]
    sh = (START_CASH - START_CASH * COST_RATE) / OPENP["SPY"][i0]
    val = sh * CLOSE["SPY"][i1]
    return val - (val * COST_RATE + SELL_FEE)

def spy_curve(start, end):
    days = [d for d in CAL if start <= d <= end]
    i0 = CIDX[days[0]]
    sh = (START_CASH - START_CASH * COST_RATE) / OPENP["SPY"][i0]
    return [(d, sh * CLOSE["SPY"][CIDX[d]]) for d in days]

def year_return(curve, year):
    this = [eq for d, eq in curve if d[:4] == str(year)]
    prev = [eq for d, eq in curve if d[:4] == str(year - 1)]
    if not this or not prev:
        return None
    return round((this[-1] / prev[-1] - 1.0) * 100, 2)

# ---------------------------------------------------------------------- main
def main():
    out = {"family": "etf-trend-sleeve-weekly", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen pre-run)", "roads": {}}
    # plumbing validation: SPY buy-hold must reproduce settled record
    spy_check = {name: round(spy_buy_hold(s, e), 2) for name, (s, e) in ROADS.items()}
    out["spy_plumbing_check"] = spy_check
    print("SPY plumbing check:", spy_check)
    for name, (s, e) in ROADS.items():
        r = simulate(s, e)
        yrs = (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(s, "%Y-%m-%d")).days / 365.25
        cagr = (r["final"] / START_CASH) ** (1 / yrs) - 1
        sel_twins, tim_twins = [], []
        for seed in range(20):
            sel_twins.append(round(simulate(s, e, sel_seed=seed)["final"], 2))
            tim_twins.append(round(simulate(s, e, timing_seed=seed)["final"], 2))
        sc = spy_curve(s, e)
        road = {"window": [s, e], "final": round(r["final"], 2),
                "cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(max_dd(r["curve"]), 2),
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "spy_final": round(spy_buy_hold(s, e), 2),
                "spy_max_dd_pct": round(max_dd(sc), 2),
                "ret_2020_pct": year_return(r["curve"], 2020),
                "ret_2022_pct": year_return(r["curve"], 2022),
                "monthly_distribution": monthly_distribution(r["curve"]),
                "placebo_selection_finals": sel_twins,
                "placebo_selection_beaten": sum(1 for x in sel_twins if r["final"] > x),
                "placebo_selection_median": round(statistics.median(sel_twins), 2),
                "placebo_timing_finals": tim_twins,
                "placebo_timing_beaten": sum(1 for x in tim_twins if r["final"] > x),
                "placebo_timing_median": round(statistics.median(tim_twins), 2),
                "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
        out["roads"][name] = road
        print(f"{name}: final ${r['final']:.2f} CAGR {cagr*100:+.2f}% "
              f"maxDD {road['max_dd_pct']:.2f}% costs ${r['costs']:.2f} orders {r['orders']} "
              f"SPY ${road['spy_final']:.2f} | sel placebo {road['placebo_selection_beaten']}/20 "
              f"(med ${road['placebo_selection_median']}) | timing placebo "
              f"{road['placebo_timing_beaten']}/20 (med ${road['placebo_timing_median']})")
    # standalone yearly folds (record; confirmation bars frozen in spec)
    folds = {}
    for y in range(2010, 2027):
        s, e = f"{y}-01-01", f"{y}-12-31"
        days = [d for d in CAL if s <= d <= e]
        if len(days) < 200:
            continue
        r = simulate(days[0], days[-1])
        folds[str(y)] = {"final": round(r["final"], 2), "max_dd_pct": round(max_dd(r["curve"]), 2)}
    out["year_folds_standalone"] = folds
    med_fold = statistics.median(v["final"] for v in folds.values())
    out["year_folds_median_final"] = round(med_fold, 2)
    out["year_folds_share_positive"] = round(
        100.0 * sum(1 for v in folds.values() if v["final"] > 100) / len(folds), 1)
    print("Year folds:", folds, "median", round(med_fold, 2))
    # half-windows on different years (frozen in spec)
    hw = {}
    for nm, (s, e) in {"2010-2018": ("2010-01-04", "2018-12-31"),
                       "2013-2022": ("2013-01-02", "2022-12-30")}.items():
        r = simulate(s, e)
        hw[nm] = {"final": round(r["final"], 2), "max_dd_pct": round(max_dd(r["curve"]), 2),
                  "spy_final": round(spy_buy_hold(s, e), 2)}
    out["half_windows"] = hw
    print("Half windows:", hw)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
