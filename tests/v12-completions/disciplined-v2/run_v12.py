#!/usr/bin/env python3
"""DISCIPLINED-v2 — v12 completions run engine.

Implements the frozen spec (CONSTRUCTION-SPEC.md) in the v10-adopted run
form — the chassis code is the v10 sweep engine (itself the original v2
form, unchanged) generalized to arbitrary windows and datasets:

  universe SPY/QQQ/IWM/GLD/TLT; eligible = prior close above 200-day MA;
  rank by trailing 63-day momentum, hold top 2; inverse-20d-vol weights;
  defensive cap (SPY below its 200d MA at a selection -> share <= 50%);
  drawdown cap (pot >=7% below peak close at a selection -> share <= 50%);
  single eligible pick -> share 0.5 (original quirk, kept);
  costs 0.10%/side + $0.01 per sell order.
  Signals/trades ONLY on cadence dates (signals from prior close, trades
  at the cadence date's open); at monthly cadence the original daily
  trend-exit is subsumed by the eligibility rebalance (same condition).
  Protection = adopted v9 rules: plain -15% floor from the episode start,
  liquidate next open, 90 calendar days cash, restart at the next cadence
  date with remaining cash, episode-2 floor, second halt ends the run.

Runs (frozen in CONSTRUCTION-SPEC (d)):
  - DECADE 2016-11-21 -> 2026-11-20 at ALL 7 cadences (v10 verification),
    on the original v2 cache (read-only).
  - LONG 2010-01-04 -> 2026-11-20, CONT 2019-01-02 -> 2026-11-20,
    VAL 2023-01-03 -> 2026-11-20 at the native MONTHLY cadence.
    DECADE/CONT/VAL on the v2 cache; LONG on the EXTENDED-PULL dataset
    cached in this folder's data/ (same source/basis; overlap audited by
    fetch_extended.py).
  - 20 placebo twins (seeds 1..20, random picks from the eligible set,
    same machinery) per road/cell.
Outputs: cells/<road>_<cadence>.json per run (full curve + twin finals),
results.json (summary + monthly-road curves + year folds + benchmarks).
"""
import csv, json, math, os, random, statistics
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V2_DATA = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
EXT_DATA = os.path.join(HERE, "data")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
ROADS = {  # name: (start, end, data_dir)
    "LONG": ("2010-01-04", "2026-11-20", EXT_DATA),
    "DECADE": ("2016-11-21", "2026-11-20", V2_DATA),
    "CONT": ("2019-01-02", "2026-11-20", V2_DATA),
    "VAL": ("2023-01-03", "2026-11-20", V2_DATA),
}
SPY_PROGRAM_REFS = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62,
                    "VAL": 187.77}  # dividend-adjusted, PROGRAM.md/v10 SPEC


class Dataset:
    def __init__(self, data_dir):
        series = {}
        for t in UNIVERSE:
            rows = []
            with open(os.path.join(data_dir, f"{t}.csv")) as f:
                for r in csv.DictReader(f):
                    rows.append((r["date"], float(r["open"]),
                                 float(r["close"])))
            series[t] = rows
        self.dates = [d for d, _, _ in series["SPY"]]
        for t in UNIVERSE:
            assert [d for d, _, _ in series[t]] == self.dates, \
                f"{t} calendar mismatch in {data_dir}"
        self.idx = {d: i for i, d in enumerate(self.dates)}
        self.O = {t: [r[1] for r in series[t]] for t in UNIVERSE}
        self.C = {t: [r[2] for r in series[t]] for t in UNIVERSE}

        def ma200(t, i):
            return None if i < 199 else sum(self.C[t][i - 199:i + 1]) / 200.0

        def mom(t, i, lb=63):
            return None if i < lb else self.C[t][i] / self.C[t][i - lb] - 1.0

        def vol20(t, i):
            if i < 20:
                return None
            c = self.C[t]
            rets = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
            return statistics.stdev(rets) * math.sqrt(252)

        n = len(self.dates)
        self.MA = {t: [ma200(t, i) for i in range(n)] for t in UNIVERSE}
        self.MOM = {t: [mom(t, i) for i in range(n)] for t in UNIVERSE}
        self.VOL = {t: [vol20(t, i) for i in range(n)] for t in UNIVERSE}


def cadence_dates(win, cadence):
    if cadence == "daily":
        return set(win)
    seen, keys = set(), []
    for d in win:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if cadence in ("weekly", "biweekly"):
            k = dt.isocalendar()[:2]
        elif cadence == "monthly":
            k = (dt.year, dt.month)
        elif cadence == "quarterly":
            k = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            k = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            k = (dt.year,)
        if k not in seen:
            seen.add(k)
            keys.append((k, d))
    if cadence == "biweekly":
        return {d for j, (_, d) in enumerate(keys) if j % 2 == 0}
    return {d for _, d in keys}


def run(ds, start, end, cadence, mode="momentum", seed=None):
    win = [d for d in ds.dates if start <= d <= end]
    win_i = [ds.idx[d] for d in win]
    sel_days = cadence_dates(win, cadence)
    rng = random.Random(seed)
    cash = 100.0
    shares = {t: 0.0 for t in UNIVERSE}
    orders = 0
    total_costs = 0.0
    episode = 1
    ep_start_balance = 100.0
    floor = 85.0
    peak_close = 100.0
    liquidate_next_open = False
    halt_trigger = None
    halts = []
    restart_date = None
    waiting_until = None
    ended = False
    curve = []

    def equity(mp):
        return cash + sum(shares[t] * mp[t] for t in UNIVERSE)

    def do_sell(t, price):
        nonlocal cash, total_costs, orders
        n = shares[t]
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] = 0.0
        orders += 1

    def do_sell_n(t, price, n):
        nonlocal cash, total_costs, orders
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        orders += 1

    def do_buy(t, price, value):
        nonlocal cash, total_costs, orders
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        cash -= value + cost
        total_costs += cost
        shares[t] += value / price
        orders += 1

    for pos, d in enumerate(win):
        i = win_i[pos]
        opens = {t: ds.O[t][i] for t in UNIVERSE}
        closes = {t: ds.C[t][i] for t in UNIVERSE}

        if liquidate_next_open:
            for t in UNIVERSE:
                if shares[t] > 0:
                    do_sell(t, opens[t])
            liquidate_next_open = False
            halts.append({"episode": episode, "trigger_date": halt_trigger,
                          "liquidated_date": d, "balance": round(cash, 2)})
            if episode == 2:
                ended = True
                curve.append((d, cash))
                break
            waiting_until = (datetime.strptime(halt_trigger, "%Y-%m-%d")
                             + timedelta(days=90)).strftime("%Y-%m-%d")
            curve.append((d, cash))
            continue

        if waiting_until is not None:
            if d in sel_days and d >= waiting_until:
                episode = 2
                ep_start_balance = cash
                floor = 0.85 * cash
                peak_close = cash
                restart_date = d
                waiting_until = None
            else:
                curve.append((d, cash))
                continue

        if d in sel_days and i > 0:
            ref = i - 1
            info = {}
            for t in UNIVERSE:
                ma = ds.MA[t][ref]
                info[t] = {"close": ds.C[t][ref], "ma200": ma,
                           "eligible": ma is not None and ds.C[t][ref] > ma,
                           "mom": ds.MOM[t][ref], "vol20": ds.VOL[t][ref]}
            eligible = [t for t in UNIVERSE if info[t]["eligible"]]
            if mode == "placebo":
                k = min(2, len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                ranked = sorted(eligible, key=lambda t: info[t]["mom"],
                                reverse=True)
                picks = ranked[:2]
            if len(picks) == 0:
                share = 0.0
            elif len(picks) == 1:
                share = 0.5
            else:
                share = 1.0
            spy_ma = info["SPY"]["ma200"]
            if spy_ma is not None and info["SPY"]["close"] < spy_ma:
                share = min(share, 0.5)
            ref_equity = curve[-1][1] if curve else ep_start_balance
            dd = ((peak_close - ref_equity) / peak_close
                  if peak_close > 0 else 0.0)
            if dd >= 0.07:
                share = min(share, 0.5)
            weights = {}
            if picks:
                inv = {t: (1.0 / info[t]["vol20"])
                       if info[t]["vol20"] else None for t in picks}
                if any(v is None for v in inv.values()):
                    weights = {t: 1.0 / len(picks) for t in picks}
                else:
                    tot = sum(inv.values())
                    weights = {t: inv[t] / tot for t in picks}
            eq_open = equity(opens)
            targets = {t: share * eq_open * weights.get(t, 0.0)
                       for t in picks}
            for t in UNIVERSE:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    do_sell_n(t, opens[t], (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            twc = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants:
                    do_buy(t, opens[t], wants[t] * scale)

        eq_close = equity(closes)
        curve.append((d, eq_close))
        if waiting_until is None and eq_close > peak_close:
            peak_close = eq_close
        if waiting_until is None and eq_close <= floor:
            if d == win[-1]:
                for t in UNIVERSE:
                    if shares[t] > 0:
                        do_sell(t, closes[t])
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidated_date": d,
                              "balance": round(cash, 2)})
                ended = True
                curve[-1] = (d, cash)
                break
            liquidate_next_open = True
            halt_trigger = d

    if not ended:
        i = win_i[-1]
        closes = {t: ds.C[t][i] for t in UNIVERSE}
        for t in UNIVERSE:
            if shares[t] > 0:
                do_sell(t, closes[t])
        if curve and curve[-1][0] == win[-1]:
            curve[-1] = (win[-1], cash)
        else:
            curve.append((win[-1], cash))
    else:
        last_d, last_v = curve[-1]
        for d in win:
            if d > last_d:
                curve.append((d, last_v))

    final = cash
    peak, max_dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak > 0 else 0.0)
    d0 = datetime.strptime(win[0], "%Y-%m-%d")
    d1 = datetime.strptime(win[-1], "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr = (final / 100.0) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(total_costs, 2), "orders": orders,
            "halts": halts, "restart": restart_date is not None,
            "restart_date": restart_date,
            "second_halt": any(h["episode"] == 2 for h in halts),
            "curve": [[d, round(v, 4)] for d, v in curve]}


def spy_benchmark(ds, start, end):
    """SPY buy-and-hold on the same data/basis, original engine convention:
    buy at the first day's open, sell at the last day's close, program
    costs; plus SPY's own close-basis max drawdown on the window."""
    win = [d for d in ds.dates if start <= d <= end]
    first, last = win[0], win[-1]
    o = ds.O["SPY"][ds.idx[first]]
    c = ds.C["SPY"][ds.idx[last]]
    sh = 100.0 / (o * (1 + COST_RATE))
    net = sh * c * (1 - COST_RATE) - SELL_FEE
    peak, mdd = 0.0, 0.0
    for d in win:
        v = ds.C["SPY"][ds.idx[d]]
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final_net_price_basis": round(net, 2),
            "max_dd_pct": round(mdd * 100, 2)}


def year_folds(curve, ds, start):
    """Per-calendar-year returns: strategy from its equity curve, SPY from
    closes (prior year-end close -> year-end close; first year from the
    close before the window start)."""
    years = {}
    prev_eq = 100.0
    for d, v in curve:
        y = int(d[:4])
        years.setdefault(y, {})["strat_end"] = v
    spy_close = {d: ds.C["SPY"][ds.idx[d]] for d in ds.dates}
    all_dates = ds.dates
    i0 = ds.idx[curve[0][0]]
    prev_spy = spy_close[all_dates[i0 - 1]] if i0 > 0 else None
    out = {}
    for y in sorted(years):
        end_eq = years[y]["strat_end"]
        ydates = [d for d in spy_close if d[:4] == str(y)
                  and curve[0][0] <= d <= curve[-1][0]]
        spy_end = spy_close[ydates[-1]] if ydates else prev_spy
        out[str(y)] = {
            "strategy_return_pct": round((end_eq / prev_eq - 1) * 100, 2)
            if prev_eq else None,
            "spy_return_pct": round((spy_end / prev_spy - 1) * 100, 2)
            if prev_spy else None}
        prev_eq = end_eq
        prev_spy = spy_end
    return out


def run_cell(ds, road, start, end, cadence, save=True):
    r = run(ds, start, end, cadence)
    twins = []
    for seed in range(1, 21):
        pr = run(ds, start, end, cadence, mode="placebo", seed=seed)
        twins.append({"seed": seed, "final": pr["final"],
                      "max_dd_pct": pr["max_dd_pct"],
                      "halts": len(pr["halts"])})
    beaten = sum(1 for t in twins if r["final"] > t["final"])
    cell = {"road": road, "cadence": cadence, "start": start, "end": end,
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "halts": r["halts"],
            "restart": r["restart"], "restart_date": r["restart_date"],
            "second_halt": r["second_halt"], "placebo_beaten": beaten,
            "placebo_finals": twins, "equity_curve": r["curve"]}
    if save:
        with open(os.path.join(HERE, "cells",
                               f"{road.lower()}_{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
    print(road, cadence, "final", r["final"], "DD", r["max_dd_pct"],
          "placebo", beaten, "/20", "halts", len(r["halts"]), flush=True)
    return cell


def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    datasets = {}
    for name, (_, _, ddir) in ROADS.items():
        if ddir not in datasets:
            datasets[ddir] = Dataset(ddir)
    results = {"slug": "disciplined-v2", "program": "v12-completions",
               "form": "frozen program spec (CONSTRUCTION-SPEC.md) in the "
                       "v10-adopted run form: monthly native cadence, v9 "
                       "protection substituted for the v2 ladder",
               "roads": {}, "decade_cadence_sweep": {}}
    for road, (start, end, ddir) in ROADS.items():
        ds = datasets[ddir]
        cell = run_cell(ds, road, start, end, "monthly")
        bench = spy_benchmark(ds, start, end)
        results["roads"][road] = {
            "start": start, "end": end,
            "data": "extended-pull (this folder data/)" if ddir == EXT_DATA
                    else "original v2 cache (read-only)",
            "final": cell["final"], "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": cell["max_dd_pct"], "costs": cell["costs"],
            "orders": cell["orders"], "halts": cell["halts"],
            "restart": cell["restart"], "second_halt": cell["second_halt"],
            "placebo_beaten": cell["placebo_beaten"],
            "placebo_finals": [t["final"] for t in cell["placebo_finals"]],
            "spy_price_basis": bench,
            "spy_program_ref_dividend_adjusted": SPY_PROGRAM_REFS[road],
            "year_folds": year_folds(cell["equity_curve"], ds, start),
            "equity_curve": cell["equity_curve"]}
    ds = datasets[V2_DATA]
    start, end, _ = ROADS["DECADE"]
    for cad in CADENCES:
        if cad == "monthly":
            c = results["roads"]["DECADE"]
            results["decade_cadence_sweep"][cad] = {
                k: c[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                  "costs", "orders", "placebo_beaten")}
            continue
        cell = run_cell(ds, "DECADE", start, end, cad)
        results["decade_cadence_sweep"][cad] = {
            k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                 "costs", "orders", "placebo_beaten")}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
