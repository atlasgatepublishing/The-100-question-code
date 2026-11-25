#!/usr/bin/env python3
"""DISCIPLINED-v3 — v10 GREAT RETEST cadence sweep engine.

Chassis = the ORIGINAL v3 BASE config, unchanged (backtests/v3/disciplined-v3.py):
  universe SPY/QQQ/IWM/GLD/TLT; eligible = prior close above 200-day MA;
  rank by trailing 63-day momentum, hold top 2; inverse-20d-vol weights;
  defensive cap (SPY below its 200d MA at a selection -> invested share <= 50%);
  drawdown cap (pot >=7% below peak close at a selection -> share <= 50%);
  single eligible pick -> share 0.5 (original quirk, kept);
  costs 0.10%/side + $0.01 per sell order.

The ONLY thing the sweep varies is CADENCE, under the SPEC's uniform
definition: signal evaluation, selection and trading happen ONLY on
cadence dates (first trading day of each day/week/2nd week/month/
quarter/half/year), signals from the prior trading day's close, trades
at the cadence date's open. The original daily trend-exit is the same
condition as eligibility (close below 200d MA), so at cadence dates it
is subsumed by the rebalance to the eligible set — documented, not patched.

Protection = adopted v9 rules (SPEC): plain -15% floor from the episode's
starting balance, NO ladder; floor checked at every close (protection
overlay, as the original engine checked its floor daily); breach ->
liquidate next open, sit in cash 90 calendar days, restart at the next
cadence date on/after the wait with the remaining cash under an
episode-2 floor of -15% from the restart balance; second halt ends the run.

Placebos: random top-2 twins — at each cadence date, picks are a random
sample of the eligible set (same machinery, caps, weights, costs),
20 seeds (1..20) per cell.

Data: v3 caches read-only (~/workspace/stock-app/backtests/v3/data/*.csv),
split-adjusted, NOT dividend-adjusted — the original test's own data.
Window: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.
"""
import csv, json, math, os, random, statistics
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v3/data")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
START, END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def load():
    series = {}
    for t in UNIVERSE:
        rows = []
        with open(os.path.join(DATA_DIR, f"{t}.csv")) as f:
            for r in csv.DictReader(f):
                rows.append((r["date"], float(r["open"]), float(r["close"])))
        series[t] = rows
    dates = [d for d, _, _ in series["SPY"]]
    for t in UNIVERSE:  # caches are calendar-aligned (original engine relied on it)
        assert [d for d, _, _ in series[t]] == dates, f"{t} calendar mismatch"
    idx = {d: i for i, d in enumerate(dates)}
    O = {t: [r[1] for r in series[t]] for t in UNIVERSE}
    C = {t: [r[2] for r in series[t]] for t in UNIVERSE}

    def ma200(t, i):
        return None if i < 199 else sum(C[t][i - 199:i + 1]) / 200.0

    def mom(t, i, lb=63):
        return None if i < lb else C[t][i] / C[t][i - lb] - 1.0

    def vol20(t, i):
        if i < 20:
            return None
        c = C[t]
        rets = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
        return statistics.stdev(rets) * math.sqrt(252)

    MA = {t: [ma200(t, i) for i in range(len(dates))] for t in UNIVERSE}
    MOM = {t: [mom(t, i) for i in range(len(dates))] for t in UNIVERSE}
    VOL = {t: [vol20(t, i) for i in range(len(dates))] for t in UNIVERSE}
    return dates, idx, O, C, MA, MOM, VOL


DATES, IDX, O, C, MA, MOM, VOL = load()
WIN = [d for d in DATES if START <= d <= END]
WIN_I = [IDX[d] for d in WIN]


def cadence_dates(cadence):
    if cadence == "daily":
        return set(WIN)
    keys, seen, out = [], set(), set()
    for d in WIN:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if cadence == "weekly":
            k = dt.isocalendar()[:2]
        elif cadence == "biweekly":
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


def run(cadence, mode="momentum", seed=None):
    sel_days = cadence_dates(cadence)
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
    halts = []            # [{episode, trigger_date, liquidated_date, balance}]
    restart_date = None
    waiting_until = None  # first date we may restart
    ended = False
    curve = []

    def equity(mp):
        return cash + sum(shares[t] * mp[t] for t in UNIVERSE)

    def do_sell(t, i, price, ):
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

    def do_sell_n(t, i, price, n):
        nonlocal cash, total_costs, orders
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        orders += 1

    def do_buy(t, i, price, value):
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

    for pos, d in enumerate(WIN):
        i = WIN_I[pos]
        opens = {t: O[t][i] for t in UNIVERSE}
        closes = {t: C[t][i] for t in UNIVERSE}

        if liquidate_next_open:
            for t in UNIVERSE:
                if shares[t] > 0:
                    do_sell(t, i, opens[t])
            liquidate_next_open = False
            halts.append({"episode": episode, "trigger_date": halt_trigger,
                          "liquidated_date": d,
                          "balance": round(cash, 2)})
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
                # restart episode 2 at this cadence date, remaining cash
                episode = 2
                ep_start_balance = cash
                floor = 0.85 * cash
                peak_close = cash
                restart_date = d
                waiting_until = None
                # fall through to selection below
            else:
                curve.append((d, cash))
                continue

        if d in sel_days and i > 0:
            ref = i - 1  # prior trading day: all signals from its close
            info = {}
            for t in UNIVERSE:
                ma = MA[t][ref]
                info[t] = {"close": C[t][ref], "ma200": ma,
                           "eligible": ma is not None and C[t][ref] > ma,
                           "mom": MOM[t][ref], "vol20": VOL[t][ref]}
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
                share = min(share, 0.5)  # defensive mode
            ref_equity = curve[-1][1] if curve else ep_start_balance
            dd = ((peak_close - ref_equity) / peak_close
                  if peak_close > 0 else 0.0)
            if dd >= 0.07:
                share = min(share, 0.5)  # drawdown cap
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
                    do_sell_n(t, i, opens[t], (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            twc = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants:
                    do_buy(t, i, opens[t], wants[t] * scale)

        eq_close = equity(closes)
        curve.append((d, eq_close))
        if waiting_until is None and eq_close > peak_close:
            peak_close = eq_close
        if waiting_until is None and eq_close <= floor:
            if d == WIN[-1]:
                for t in UNIVERSE:
                    if shares[t] > 0:
                        do_sell(t, i, closes[t])
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidated_date": d,
                              "balance": round(cash, 2)})
                ended = True
                curve[-1] = (d, cash)
                break
            liquidate_next_open = True
            halt_trigger = d

    if not ended:
        i = WIN_I[-1]
        closes = {t: C[t][i] for t in UNIVERSE}
        for t in UNIVERSE:
            if shares[t] > 0:
                do_sell(t, i, closes[t])
        if curve and curve[-1][0] == WIN[-1]:
            curve[-1] = (WIN[-1], cash)
        else:
            curve.append((WIN[-1], cash))
    else:
        # extend flat cash to window end so every curve spans the decade
        last_d, last_v = curve[-1]
        for d in WIN:
            if d > last_d:
                curve.append((d, last_v))

    final = cash
    peak, max_dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak > 0 else 0.0)
    d0 = datetime.strptime(WIN[0], "%Y-%m-%d")
    d1 = datetime.strptime(WIN[-1], "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr = (final / 100.0) ** (1.0 / years) - 1.0
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(total_costs, 2), "orders": orders,
            "halts": halts, "restart": restart_date is not None,
            "restart_date": restart_date,
            "second_halt": any(h["episode"] == 2 for h in halts),
            "curve": [[d, round(v, 4)] for d, v in curve]}


def main():
    cells = {}
    for cad in CADENCES:
        r = run(cad)
        twins = []
        for seed in range(1, 21):
            pr = run(cad, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": pr["final"],
                          "max_dd_pct": pr["max_dd_pct"],
                          "halts": len(pr["halts"])})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        cell = {"cadence": cad, "final": r["final"],
                "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"],
                "halts": r["halts"], "restart": r["restart"],
                "restart_date": r["restart_date"],
                "second_halt": r["second_halt"],
                "placebo_beaten": beaten,
                "placebo_finals": twins,
                "equity_curve": r["curve"]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in
                      ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                       "halts", "restart", "second_halt", "placebo_beaten")}
        cells[cad]["placebo_note"] = ("20 random top-2 twins (seeds 1-20), "
                                      "same cadence/machinery/costs")
        print(cad, json.dumps(cells[cad]), "placebo finals:",
              [t["final"] for t in twins], flush=True)
    with open(os.path.join(HERE, "sweep_cells.json"), "w") as f:
        json.dump(cells, f, indent=2)


if __name__ == "__main__":
    main()
