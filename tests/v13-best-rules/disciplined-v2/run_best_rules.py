#!/usr/bin/env python3
"""
V13 BEST-RULES — disciplined-v2. Spec: BEST-RULES-SPEC.md (frozen before run).

MY RULES: monthly selection; eligible = prior close above own 200d MA;
hold ALL eligible, EQUAL weight, 100% invested (100% cash if none eligible);
no defensive cap, no drawdown cap, no single-pick quirk; DAILY trend exit
(held asset closes below its 200d MA -> sell next open, cash until next
monthly selection); NO floor. Costs 0.10%/side + $0.01/sell. $100 pots.

Placebos (20 seeds/road): same number of names as the real pot each month,
random from eligible set, equal weight, same exits/costs.

Data (read-only, same basis as the family's whole record):
  DECADE/CONT/VAL: backtests/v2/data/*.csv
  LONG: backtests/v12-completions/disciplined-v2/data/*.csv (extended pull,
        overlap-audited zero-mismatch vs v2 cache)
Split-adjusted, NOT dividend-adjusted.
"""
import csv, json, math, os, random, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V2_DATA = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
EXT_DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/disciplined-v2/data")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20", EXT_DATA),
    "DECADE": ("2016-11-21", "2026-11-20", V2_DATA),
    "CONT":   ("2019-01-02", "2026-11-20", V2_DATA),
    "VAL":    ("2023-01-03", "2026-11-20", V2_DATA),
}
CONFIRM = ("2010-01-04", "2018-12-31", EXT_DATA)
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {  # v12 settled record, monthly, v9 floor
    "LONG":   {"final": 304.62, "max_dd_pct": 17.92},
    "DECADE": {"final": 202.03, "max_dd_pct": 17.94},
    "CONT":   {"final": 192.35, "max_dd_pct": 17.94},
    "VAL":    {"final": 148.96, "max_dd_pct": 13.26},
}


class Dataset:
    def __init__(self, data_dir):
        series = {}
        for t in UNIVERSE:
            rows = []
            with open(os.path.join(data_dir, f"{t}.csv")) as f:
                for r in csv.DictReader(f):
                    rows.append((r["date"], float(r["open"]), float(r["close"])))
            series[t] = rows
        self.dates = [d for d, _, _ in series["SPY"]]
        for t in UNIVERSE:
            assert [d for d, _, _ in series[t]] == self.dates, f"{t} calendar mismatch"
        self.idx = {d: i for i, d in enumerate(self.dates)}
        self.O = {t: [r[1] for r in series[t]] for t in UNIVERSE}
        self.C = {t: [r[2] for r in series[t]] for t in UNIVERSE}
        n = len(self.dates)
        self.MA = {t: [None if i < 199 else sum(self.C[t][i-199:i+1]) / 200.0
                       for i in range(n)] for t in UNIVERSE}


DATASETS = {}


def get_ds(data_dir):
    if data_dir not in DATASETS:
        DATASETS[data_dir] = Dataset(data_dir)
    return DATASETS[data_dir]


def run(ds, start, end, mode="best", seed=None):
    win = [d for d in ds.dates if start <= d <= end]
    win_i = [ds.idx[d] for d in win]
    # monthly selection days: first trading day of each month in window
    sel_days, seen = set(), set()
    for d in win:
        k = d[:7]
        if k not in seen:
            seen.add(k); sel_days.add(d)
    rng = random.Random(seed)
    cash = 100.0
    shares = {t: 0.0 for t in UNIVERSE}
    orders = 0; total_costs = 0.0
    pending_exits = set()
    curve = []
    counts = []  # eligible count each selection (placebo matches real count)

    def equity(mp):
        return cash + sum(shares[t] * mp[t] for t in UNIVERSE)

    def sell_n(t, price, n):
        nonlocal cash, total_costs, orders
        if n <= 1e-12 or price <= 0: return
        v = n * price; cost = v * COST_RATE + SELL_FEE
        cash += v - cost; total_costs += cost; shares[t] -= n; orders += 1

    def buy(t, price, value):
        nonlocal cash, total_costs, orders
        if value <= 0.005 or price <= 0: return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE); cost = value * COST_RATE
        cash -= value + cost; total_costs += cost
        shares[t] += value / price; orders += 1

    for pos, d in enumerate(win):
        i = win_i[pos]
        opens = {t: ds.O[t][i] for t in UNIVERSE}
        closes = {t: ds.C[t][i] for t in UNIVERSE}
        # 1) pending daily trend exits at open
        for t in sorted(pending_exits):
            if shares[t] > 0: sell_n(t, opens[t], shares[t])
        pending_exits = set()
        # 2) monthly selection / rebalance at open
        if d in sel_days and i > 0:
            ref = i - 1
            eligible = [t for t in UNIVERSE
                        if ds.MA[t][ref] is not None and ds.C[t][ref] > ds.MA[t][ref]]
            if mode == "placebo":
                k = counts[len([s for s in sel_days if s <= d]) - 1] if counts else len(eligible)
                k = min(k, len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                picks = list(eligible)
                counts.append(len(picks))
            targets = {}
            if picks:
                eq_open = equity(opens)
                targets = {t: eq_open / len(picks) for t in picks}
            for t in UNIVERSE:
                if shares[t] <= 0: continue
                cur = shares[t] * opens[t]; tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005: sell_n(t, opens[t], (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005: wants[t] = targets[t] - cur
            twc = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants: buy(t, opens[t], wants[t] * scale)
        eq_close = equity(closes)
        curve.append((d, eq_close))
        # 3) daily trend-exit check at close
        for t in UNIVERSE:
            if shares[t] > 1e-9 and ds.MA[t][i] is not None and closes[t] < ds.MA[t][i]:
                pending_exits.add(t)
    # final liquidation at last close
    i = win_i[-1]
    for t in UNIVERSE:
        if shares[t] > 0: sell_n(t, ds.C[t][i], shares[t])
    if curve: curve[-1] = (win[-1], cash)
    final = cash
    peak, max_dd, pk_d, tr_d, run_pk = curve[0][1], 0.0, curve[0][0], None, curve[0][0]
    for dte, v in curve:
        if v > peak: peak, run_pk = v, dte
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd: max_dd, pk_d, tr_d = dd, run_pk, dte
    yrs = (datetime.strptime(win[-1], "%Y-%m-%d") - datetime.strptime(win[0], "%Y-%m-%d")).days / 365.25
    return {"final": round(final, 2),
            "cagr_pct": round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(max_dd * 100, 2), "dd_peak": pk_d, "dd_trough": tr_d,
            "costs": round(total_costs, 2), "orders": orders,
            "curve": [[d, round(v, 4)] for d, v in curve],
            "counts": counts}


def period_stats(curve):
    """Monthly distribution from an equity curve."""
    me = {}
    for d, v in curve: me[d[:7]] = v
    keys = sorted(me)
    rets, prev = [], 100.0
    for k in keys:
        rets.append(me[k] / prev - 1); prev = me[k]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak, longest, cur_run, last_high_idx = -1, 0, 0, 0
    vals = [v for _, v in curve]
    runmax = vals[0]; gap = 0; maxgap = 0
    for v in vals:
        if v >= runmax: runmax = v; gap = 0
        else:
            gap += 1; maxgap = max(maxgap, gap)
    return {"median_month_pct": round(statistics.median(rets) * 100, 2) if rets else None,
            "months": len(rets), "months_positive_pct": round(100 * pos / len(rets), 1) if rets else None,
            "best_month_pct": round(max(rets) * 100, 2) if rets else None,
            "worst_month_pct": round(min(rets) * 100, 2) if rets else None,
            "longest_losing_streak_months": streak,
            "longest_stretch_between_new_highs_days": maxgap,
            "mean_month_pct_secondary": round(statistics.mean(rets) * 100, 2) if rets else None}


def year_folds(ds, start, end):
    folds = {}
    for y in range(int(start[:4]), int(end[:4]) + 1):
        s = max(start, f"{y}-01-01"); e = min(end, f"{y}-12-31")
        if s > e: continue
        r = run(ds, s, e)
        folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
    vals = [v["final"] for v in folds.values()]
    return folds, {"median_year_final": round(statistics.median(vals), 2),
                   "share_years_positive_pct": round(100 * sum(1 for v in vals if v > 100) / len(vals), 1),
                   "best_year_final": max(vals), "worst_year_final": min(vals)}


def spy_bh(ds, start, end):
    win = [d for d in ds.dates if start <= d <= end]
    i0, i1 = ds.idx[win[0]], ds.idx[win[-1]]
    sh = 100.0 / (ds.O["SPY"][i0] * (1 + COST_RATE))
    net = sh * ds.C["SPY"][i1] * (1 - COST_RATE) - SELL_FEE
    peak, mdd = 0.0, 0.0
    for d in win:
        v = ds.C["SPY"][ds.idx[d]]; peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak else 0)
    return {"final_price_basis_net": round(net, 2), "max_dd_pct": round(mdd * 100, 2)}


def main():
    out = {"family": "disciplined-v2", "spec": "BEST-RULES-SPEC.md",
           "verdict_ceiling": "CANDIDATE", "roads": {}}
    for name, (s, e, dd_) in ROADS.items():
        ds = get_ds(dd_)
        r = run(ds, s, e)
        # placebo counts must match real run's per-month holding counts:
        # re-run placebo machinery with counts from the real run
        twins = []
        for seed in range(1, 21):
            # monkey-seed approach: run placebo with counts injected
            pr = run_placebo(ds, s, e, r["counts"], seed)
            twins.append({"seed": seed, "final": pr["final"], "max_dd_pct": pr["max_dd_pct"]})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        folds, fold_sum = year_folds(ds, s, e)
        out["roads"][name] = {
            "window": [s, e], "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "dd_peak": r["dd_peak"], "dd_trough": r["dd_trough"],
            "costs": r["costs"], "orders": r["orders"],
            "published_form": PUBLISHED[name], "champion_vm": CHAMP[name],
            "spy_program_ref_div_adj": SPY_REF[name], "spy_price_basis": spy_bh(ds, s, e),
            "placebo_beaten": beaten,
            "placebo_median": round(statistics.median([t["final"] for t in twins]), 2),
            "placebo_max": max(t["final"] for t in twins),
            "placebo_finals": twins,
            "period_distribution": period_stats(r["curve"]),
            "year_folds": folds, "year_fold_summary": fold_sum,
            "equity_curve": r["curve"]}
        print(name, r["final"], "DD", r["max_dd_pct"], "placebo", beaten, "/20", flush=True)
    # confirmation window (frozen in spec; run for the record regardless)
    ds = get_ds(CONFIRM[2])
    cr = run(ds, CONFIRM[0], CONFIRM[1])
    out["confirmation_window_2010_2018"] = {
        "final": cr["final"], "max_dd_pct": cr["max_dd_pct"],
        "spy_price_basis": spy_bh(ds, CONFIRM[0], CONFIRM[1])}
    print("CONFIRM 2010-2018", cr["final"], "DD", cr["max_dd_pct"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE results.json")


def run_placebo(ds, start, end, counts, seed):
    """Placebo twin: each month hold len==counts[m] random eligible names."""
    win = [d for d in ds.dates if start <= d <= end]
    win_i = [ds.idx[d] for d in win]
    sel_days, seen = set(), set()
    for d in win:
        k = d[:7]
        if k not in seen: seen.add(k); sel_days.add(d)
    rng = random.Random(seed)
    cash = 100.0; shares = {t: 0.0 for t in UNIVERSE}
    total_costs = 0.0; orders = 0; pending = set(); curve = []; m_idx = 0

    def equity(mp): return cash + sum(shares[t] * mp[t] for t in UNIVERSE)
    def sell_n(t, price, n):
        nonlocal cash, total_costs, orders
        if n <= 1e-12 or price <= 0: return
        v = n * price; cost = v * COST_RATE + SELL_FEE
        cash += v - cost; total_costs += cost; shares[t] -= n; orders += 1
    def buy(t, price, value):
        nonlocal cash, total_costs, orders
        if value <= 0.005 or price <= 0: return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE); cost = value * COST_RATE
        cash -= value + cost; total_costs += cost; shares[t] += value / price; orders += 1

    for pos, d in enumerate(win):
        i = win_i[pos]
        opens = {t: ds.O[t][i] for t in UNIVERSE}; closes = {t: ds.C[t][i] for t in UNIVERSE}
        for t in sorted(pending):
            if shares[t] > 0: sell_n(t, opens[t], shares[t])
        pending = set()
        if d in sel_days and i > 0:
            ref = i - 1
            eligible = [t for t in UNIVERSE if ds.MA[t][ref] is not None and ds.C[t][ref] > ds.MA[t][ref]]
            k = min(counts[m_idx] if m_idx < len(counts) else len(eligible), len(eligible)); m_idx += 1
            picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            targets = {t: equity(opens) / len(picks) for t in picks} if picks else {}
            for t in UNIVERSE:
                if shares[t] <= 0: continue
                cur = shares[t] * opens[t]; tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005: sell_n(t, opens[t], (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005: wants[t] = targets[t] - cur
            twc = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants: buy(t, opens[t], wants[t] * scale)
        curve.append((d, equity(closes)))
        for t in UNIVERSE:
            if shares[t] > 1e-9 and ds.MA[t][i] is not None and closes[t] < ds.MA[t][i]:
                pending.add(t)
    i = win_i[-1]
    for t in UNIVERSE:
        if shares[t] > 0: sell_n(t, ds.C[t][i], shares[t])
    peak, max_dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v); max_dd = max(max_dd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(cash, 2), "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(total_costs, 2), "orders": orders}


if __name__ == "__main__":
    main()
