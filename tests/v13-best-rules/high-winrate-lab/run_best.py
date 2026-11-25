#!/usr/bin/env python3
"""V13 BEST RULES — high-winrate-lab. Implements BEST-RULES-SPEC.md exactly.
Weekly strength basket: top-3 by 252d-high proximity (>=0.95, close>50d SMA),
1/3 equity each, unfilled slots in SPY, rank/trend exits only, no target/stop/
floor. Costs 0.10%/side + $0.01/sell. 20-seed random-basket placebos.
Data: read-only shared cache backtests/v2/tournament-data (split-adj)."""
import json, os, math
from datetime import date
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "v2", "tournament-data"))
UNIVERSE = ["SPY","QQQ","NVDA","TSLA","AAPL","MSFT","AMZN","META","AMD","AVGO"]
ROADS = {"LONG": (date(2015,1,5), date(2026,11,20)),
         "DECADE": (date(2016,11,21), date(2026,11,20)),
         "CONT": (date(2019,1,1), date(2026,11,20)),
         "VAL": (date(2023,1,1), date(2026,11,20))}
COST = 0.001; SELL_FEE = 0.01; START = 100.0

frames = {}
for s in UNIVERSE:
    df = pd.read_csv(os.path.join(CACHE, s + ".csv"), parse_dates=["date"])
    df["date"] = df["date"].dt.date
    df["prox"] = df["close"] / df["close"].rolling(252, min_periods=252).max()
    df["sma50"] = df["close"].rolling(50, min_periods=50).mean()
    frames[s] = df.reset_index(drop=True)
SPY = frames["SPY"]
all_dates = [d for d in SPY["date"]]
idx_of = {d: i for i, d in enumerate(all_dates)}
row = {s: {d: i for i, d in enumerate(frames[s]["date"])} for s in UNIVERSE}

def px(s, d, col):
    i = row[s].get(d)
    return None if i is None else float(frames[s][col].iloc[i])

def run(start, end, placebo_seed=None):
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    days = [d for d in all_dates if start <= d <= end]
    # rebalance signal days: last trading day of each ISO week within road
    rebal = []
    for i, d in enumerate(days):
        nxt = days[i+1] if i+1 < len(days) else None
        if nxt is None or (nxt.isocalendar()[:2] != d.isocalendar()[:2]):
            rebal.append(d)
    rebal_set = set(rebal)
    cash = START; shares = {}; basis = {}  # sym -> (shares, cost_incl_buy_cost, entry_date)
    trades = []; curve = []; costs = 0.0; orders = 0
    pending = None  # target set decided at close, executed next open
    def equity(d):
        v = cash
        for s, (sh, _, _) in shares.items():
            p = px(s, d, "close")
            if p: v += sh * p
        return v
    for di, d in enumerate(days):
        # execute pending at today's open
        if pending is not None and di > 0:
            target, weights = pending; pending = None
            eq = cash + sum(sh * (px(s, d, "open") or 0) for s, (sh, _, _) in shares.items())
            # exits
            for s in list(shares):
                if s not in target:
                    sh, bas, ed = shares.pop(s)
                    proceeds = sh * px(s, d, "open") * (1 - COST) - SELL_FEE
                    costs += sh * px(s, d, "open") * COST + SELL_FEE; orders += 1
                    cash += proceeds
                    trades.append({"sym": s, "entry": str(ed), "exit": str(d),
                                   "pnl": round(proceeds - bas, 4)})
            # entries: each target name not held gets 1/3 of equity-at-open
            for s in target:
                if s not in shares:
                    p = px(s, d, "open")
                    if p and cash > 0:
                        amt = min(eq * weights[s], cash / (1 + COST))
                        if amt > 1.0:
                            sh = amt * (1 - COST) / p  # buy cost taken from amount
                            # simpler: spend amt total incl cost
                            sh = (amt - amt * COST) / p
                            costs += amt * COST; orders += 1
                            cash -= amt
                            shares[s] = (sh, amt, d)
        curve.append((str(d), round(equity(d), 4)))
        # signal at close on rebalance days (not on last day)
        if d in rebal_set and di < len(days) - 1:
            if rng is not None:
                picks = list(rng.choice(UNIVERSE, size=3, replace=False))
                pending = (set(picks), {s: 1/3.0 for s in picks})
            else:
                scored = []
                for s in UNIVERSE:
                    i = row[s].get(d)
                    if i is None: continue
                    pr = frames[s]["prox"].iloc[i]; sm = frames[s]["sma50"].iloc[i]
                    cl = frames[s]["close"].iloc[i]
                    if pr == pr and sm == sm:
                        scored.append((s, float(pr), float(cl), float(sm)))
                scored.sort(key=lambda x: -x[1])
                qual = [s for s, pr, cl, sm in scored if pr >= 0.95 and cl > sm][:3]
                target = set(qual)
                # exits check for held names failing (b)/(c) even if in top3
                drop = set()
                info = {s: (pr, cl, sm) for s, pr, cl, sm in scored}
                for s in list(shares):
                    if s == "SPY": continue
                    if s in info:
                        pr, cl, sm = info[s]
                        if cl < sm or pr < 0.90: drop.add(s)
                target -= drop
                # filler: SPY takes the combined weight of all unfilled slots
                weights = {s: 1/3.0 for s in target}
                if len(target) < 3:
                    weights["SPY"] = (3 - len(target)) / 3.0
                    target = set(target) | {"SPY"}
                pending = (target, weights)
    final = curve[-1][1]
    # close out open episodes mark-to-market for trade stats (not counted as closed trades)
    wins = [t for t in trades if t["pnl"] > 0]; losses = [t for t in trades if t["pnl"] <= 0]
    eq = np.array([v for _, v in curve], float)
    rets = np.diff(eq) / eq[:-1]
    peak = np.maximum.accumulate(eq); dd = (eq - peak) / peak
    maxdd = float(-dd.min()) * 100 if len(dd) else 0.0
    # period stats on daily returns
    pos = float(np.mean(rets > 0)) * 100 if len(rets) else 0
    med = float(np.median(rets)) * 100 if len(rets) else 0
    # longest losing streak (days) and stretch between new highs
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    hi = eq[0]; since = 0; mxstretch = 0
    for v in eq:
        if v >= hi: hi = v; since = 0
        else: since += 1; mxstretch = max(mxstretch, since)
    stats = {"final": round(final, 2), "max_dd_pct": round(maxdd, 2),
             "trades_closed": len(trades),
             "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
             "avg_win": round(float(np.mean([t["pnl"] for t in wins])), 2) if wins else None,
             "avg_loss": round(float(np.mean([t["pnl"] for t in losses])), 2) if losses else None,
             "expectancy": round(float(np.mean([t["pnl"] for t in trades])), 2) if trades else None,
             "costs": round(costs, 2), "orders": orders,
             "open_at_end": sorted(shares.keys()),
             "periods": {"n_days": len(eq), "median_day_pct": round(med, 4),
                         "pct_days_positive": round(pos, 1),
                         "best_day_pct": round(float(rets.max()) * 100, 2) if len(rets) else None,
                         "worst_day_pct": round(float(rets.min()) * 100, 2) if len(rets) else None,
                         "longest_losing_streak_days": int(mx),
                         "longest_stretch_between_highs_days": int(mxstretch)}}
    return stats, curve, trades

out = {"family": "high-winrate-lab", "form": "v13 best rules: weekly top-3 52w-high-proximity basket, SPY filler, rank/trend exits, no cap/stop/floor",
       "roads": {}}
for name, (s, e) in ROADS.items():
    st, curve, trades = run(s, e)
    twins = []
    for seed in range(20):
        tst, _, _ = run(s, e, placebo_seed=1000 + seed)
        twins.append(tst["final"])
    st["placebos_beaten"] = int(sum(1 for t in twins if st["final"] > t))
    st["placebo_median"] = round(float(np.median(twins)), 2)
    st["placebo_best"] = round(max(twins), 2)
    st["placebo_finals"] = twins
    # in-chassis SPY buy-hold (price only)
    p0 = px("SPY", [d for d in all_dates if d >= s][0], "open"); p1 = px("SPY", e if e in row["SPY"] else max(d for d in all_dates if d <= e), "close")
    st["spy_in_chassis_price_only"] = round(100 * p1 / p0, 2)
    out["roads"][name] = {"stats": st, "equity_curve": curve, "trades": trades}
    print(name, st)

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("done")
