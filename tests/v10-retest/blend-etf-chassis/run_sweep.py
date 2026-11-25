#!/usr/bin/env python3
"""
BLEND-ETF-CHASSIS — v10 GREAT RETEST cadence sweep.

The strategy (v4 "THE BLEND", frozen): one $100 pot split 50/50.
  Sleeve A = ETF trend sleeve: SPY QQQ TLT IEF GLD DBC UUP; 3/6/12-month
             sign-blend trend (hold assets with >=2 of 3 lookbacks
             positive); inverse-20d-vol weights capped at 40%; 20%
             relative no-trade band; dividend+split-adjusted prices
             (../v3/data_etf via the v3 monthly parent module).
  Sleeve B = Disciplined chassis: SPY QQQ IWM GLD TLT; eligible = prior
             close above 200-day MA; rank by 63-day momentum; top 3
             equal weight; invested share 0/50/100% for 0/1/2+ picks;
             defensive mode ON (share capped at 50% when SPY's prior
             close < its 200-day MA); trend exits on close below the
             200-day MA, sold next open; split-adjusted prices
             (../v3/data via the v4 chassis Market).
  Pot rule: January rebalance back to 50/50 at the open of the first
  trading day of each January (kept in EVERY cell — it is the blend's
  defining pot rule, not a sleeve cadence; stated in RESULTS.md).
  Costs: 0.10% of trade value per side + $0.01 per sell order, each
  sleeve on its own books, exactly as the parents.

CADENCE TREATMENT (SPEC uniform definition, stated): cadence governs
BOTH legs uniformly. Cadence dates = first trading day of each period
(daily = every trading day). On cadence dates ONLY:
  - Sleeve A evaluates its trend signal at the close and rebalances at
    the next open (its published form evaluates monthly);
  - Sleeve B runs its selection at the open (signals from the prior
    close, as published) AND its 200-day trend-exit scan at the close,
    exits sold next open (its published form selects quarterly and
    scans exits daily — both rhythms move to the cadence here; that
    is the point of the sweep).
The January 50/50 rebalance and the v9 floor checks stay daily/annual
as defined (protection and pot rules, not sleeve signals).

PROTECTION (v9, binding): plain -15% floor from the episode's starting
balance, NO ladder. Breach at a close -> liquidate everything at the
next open, sit in cash 90 calendar days, restart at the next cadence
date on/after the sit-out ends, cash re-split 50/50, episode-2 floor
-15% from the restart balance. Second halt ends the run.

PLACEBOS (20 seeds per cell): random twins of BOTH legs, same
machinery/costs/v9 — Sleeve A: at each evaluation, randomly sample
(seeded) the same NUMBER of assets the trend rule selected, from all
assets with vol data, same inv-vol capped weighting and band (the
etf-trend-sleeve worker's design). Sleeve B: at each selection,
randomly sample the same number of picks from the ELIGIBLE set
(above-200d-MA gate and defensive share rule kept — random-RANK twin,
the chassis study's own placebo design).

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.
Data: read-only shared caches via the parent modules (v3 data_etf +
v3 data). Nothing downloaded; nothing written outside this folder.
"""
import importlib.util
import json
import os
import random
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(HERE, "..", "..")
COST_RATE = 0.001
SELL_FEE = 0.01
START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A_MOD = load_module("etf_sleeve_monthly",
                    os.path.join(BT, "v3", "etf-trend-sleeve-monthly.py"))
sys.path.insert(0, os.path.join(BT, "v4"))
B_MOD = load_module("chassis_wf",
                    os.path.join(BT, "v4", "chassis-walkforward.py"))
B_MKT = B_MOD.Market()
B_CFG = dict(B_MOD.CHASSIS_CFG)

A_ASSETS = A_MOD.ASSETS           # SPY QQQ TLT IEF GLD DBC UUP
B_UNIVERSE = B_MOD.UNIVERSE       # SPY QQQ IWM GLD TLT
MASTER_CAL = A_MOD.CAL            # SPY trading days (dividend-adj cache)

# --- memoization (pure functions of the read-only price caches; the
# same values are reused by every run in the sweep, real and placebo) ---
_TV_CACHE = {}


def trend_and_vol_cached(t, date):
    key = (t, date)
    if key not in _TV_CACHE:
        _TV_CACHE[key] = A_MOD.trend_and_vol(t, date)
    return _TV_CACHE[key]


_MA_CACHE = {}
_MOM_CACHE = {}
_b_ma200_raw = B_MKT.ma200
_b_mom_raw = B_MKT.mom


def _ma200_cached(t, date):
    key = (t, date)
    if key not in _MA_CACHE:
        _MA_CACHE[key] = _b_ma200_raw(t, date)
    return _MA_CACHE[key]


def _mom_cached(t, date, lookback):
    key = (t, date, lookback)
    if key not in _MOM_CACHE:
        _MOM_CACHE[key] = _b_mom_raw(t, date, lookback)
    return _MOM_CACHE[key]


B_MKT.ma200 = _ma200_cached
B_MKT.mom = _mom_cached


# =====================================================================
# Sleeve A — blend.py's re-implementation, cadence/placebo parameterized
# =====================================================================
class SleeveA:
    def __init__(self, cash, rng=None):
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in A_ASSETS}
        self.orders = 0
        self.costs = 0.0
        self.pending = None
        self.rng = rng

    def equity(self, date, price_fn):
        eq = self.cash
        for t in A_ASSETS:
            if self.shares[t] > 0:
                p = price_fn(t, date)
                if p:
                    eq += self.shares[t] * p
        return eq

    def equity_open(self, date):
        return self.equity(date, A_MOD.open_on)

    def equity_close(self, date):
        return self.equity(date, A_MOD.close_on)

    def sell_value(self, t, date, sell_val, reason):
        price = A_MOD.open_on(t, date)
        if price is None or price <= 0 or self.shares[t] <= 0:
            return 0.0
        cur_val = self.shares[t] * price
        sell_val = min(sell_val, cur_val)
        if sell_val <= 0:
            return 0.0
        sh = sell_val / price
        cost = sell_val * COST_RATE + SELL_FEE
        self.cash += sell_val - cost
        self.shares[t] -= sh
        if self.shares[t] < 1e-9:
            self.shares[t] = 0.0
        self.orders += 1
        self.costs += cost
        return sell_val - cost

    def sell_all(self, date, reason):
        for t in A_ASSETS:
            if self.shares[t] > 0:
                self.sell_value(t, date,
                                self.shares[t] * A_MOD.open_on(t, date),
                                reason)

    def execute_pending(self, date):
        if self.pending is None:
            return
        trade_set, targets = self.pending
        eq_open = self.equity_open(date)
        for t in sorted(trade_set):
            tgt_val = targets.get(t, 0.0) * eq_open
            cur_val = self.shares[t] * A_MOD.open_on(t, date)
            diff = cur_val - tgt_val
            if diff > 0.01 and self.shares[t] > 0:
                self.sell_value(t, date, min(diff, cur_val), "sleeveA-rebalance")
        buy_list = []
        for t in sorted(trade_set):
            tgt_val = targets.get(t, 0.0) * eq_open
            cur_val = self.shares[t] * A_MOD.open_on(t, date)
            diff = tgt_val - cur_val
            if diff > 0.01:
                buy_list.append((t, diff))
        tot_buy = sum(v for _, v in buy_list)
        if tot_buy > 0:
            scale = min(1.0, self.cash / (tot_buy * (1 + COST_RATE)))
            for t, diff in buy_list:
                buy_val = diff * scale
                if buy_val < 0.01:
                    continue
                cost = buy_val * COST_RATE
                self.cash -= buy_val + cost
                self.shares[t] += buy_val / A_MOD.open_on(t, date)
                self.orders += 1
                self.costs += cost
        self.pending = None

    def evaluate(self, date, eq_close):
        """Trend evaluation at today's close (parent logic; placebo twin
        swaps the trend-chosen set for a seeded random sample of the
        same size from all assets with vol data)."""
        vols_all = {}
        chosen = []
        for t in A_ASSETS:
            tv = trend_and_vol_cached(t, date)
            if tv is None:
                continue
            npos, vol = tv
            if vol:
                vols_all[t] = vol
            if npos >= 2 and vol:
                chosen.append(t)
        if self.rng is not None:
            elig = sorted(vols_all)
            k = min(len(chosen), len(elig))
            chosen = self.rng.sample(elig, k) if k else []
        targets = A_MOD.capped_inv_vol_weights(
            {t: vols_all[t] for t in chosen})
        trade_set = set()
        for t in A_ASSETS:
            cur_w = (self.shares[t] * A_MOD.close_on(t, date) / eq_close) \
                if eq_close > 0 else 0.0
            tgt_w = targets.get(t, 0.0)
            held = self.shares[t] > 0
            if held and tgt_w == 0.0:
                trade_set.add(t)
            elif not held and tgt_w > 0.0:
                trade_set.add(t)
            elif held and tgt_w > 0.0:
                if abs(tgt_w - cur_w) / tgt_w > 0.20:
                    trade_set.add(t)
        if trade_set:
            self.pending = (trade_set, targets)


# =====================================================================
# Sleeve B — blend.py's re-implementation; selection days and exit-scan
# days are the cadence set; placebo = random picks from the eligible set
# =====================================================================
class SleeveB:
    def __init__(self, mkt, cash, selection_days, rng=None):
        self.mkt = mkt
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in B_UNIVERSE}
        self.orders = 0
        self.costs = 0.0
        self.pending_exits = set()
        self.selection_days = set(selection_days)
        self.rng = rng
        self._idx = {d: i for i, d in enumerate(mkt.dates_all)}

    def has_data(self, date):
        return all(date in self.mkt.by_date[t] for t in B_UNIVERSE)

    def _close(self, t, date):
        bd = self.mkt.by_date[t]
        if date in bd:
            return bd[date]["close"]
        dates = self.mkt.dates_all
        i = self._idx.get(date, None)
        if i is None:
            return None
        for j in range(i - 1, -1, -1):
            if dates[j] in bd:
                return bd[dates[j]]["close"]
        return None

    def equity_open(self, date):
        eq = self.cash
        for t in B_UNIVERSE:
            if self.shares[t] > 0:
                eq += self.shares[t] * self.mkt.by_date[t][date]["open"]
        return eq

    def equity_close(self, date):
        eq = self.cash
        for t in B_UNIVERSE:
            if self.shares[t] > 0:
                c = self._close(t, date)
                if c:
                    eq += self.shares[t] * c
        return eq

    def do_sell(self, t, date, price, reason, n=None):
        n = self.shares[t] if n is None else min(n, self.shares[t])
        if n <= 1e-12 or price <= 0:
            return 0.0
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.costs += cost
        self.orders += 1
        self.shares[t] -= n
        return value - cost

    def do_buy(self, t, date, price, value, reason):
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > self.cash + 1e-9:
            value = self.cash / (1 + COST_RATE)
            cost = value * COST_RATE
        n = value / price
        self.cash -= value + cost
        self.costs += cost
        self.orders += 1
        self.shares[t] += n

    def sell_all(self, date, reason):
        for t in B_UNIVERSE:
            if self.shares[t] > 0:
                self.do_sell(t, date, self.mkt.by_date[t][date]["open"],
                             reason)

    def open_executions(self, date):
        """Pending trend exits, then cadence-date selection."""
        opens = {t: self.mkt.by_date[t][date]["open"] for t in B_UNIVERSE}
        for t in sorted(self.pending_exits):
            if self.shares[t] > 0:
                self.do_sell(t, date, opens[t], "trend-exit")
        self.pending_exits = set()

        if date not in self.selection_days:
            return
        ref = self.mkt.dates_all[self._idx[date] - 1]
        info = {}
        for t in B_UNIVERSE:
            ma = self.mkt.ma200(t, ref)
            c = self.mkt.by_date[t][ref]["close"]
            elig = (ma is not None and c > ma)
            info[t] = {"close": c, "ma200": ma, "eligible": elig,
                       "mom": self.mkt.mom(t, ref, B_CFG["mom_lookback"])}
        eligible = [t for t in B_UNIVERSE if info[t]["eligible"]]
        ranked = sorted(eligible, key=lambda t: info[t]["mom"], reverse=True)
        picks = ranked[:B_CFG["top_k"]]
        if self.rng is not None:
            picks = self.rng.sample(eligible, len(picks)) if picks else []

        if len(picks) == 0:
            share = 0.0
        elif len(picks) == 1:
            share = 0.5
        else:
            share = 1.0
        if B_CFG["defensive"]:
            spy_ma = info["SPY"]["ma200"]
            if spy_ma is not None and info["SPY"]["close"] < spy_ma:
                share = min(share, 0.5)

        weights = {t: 1.0 / len(picks) for t in picks} if picks else {}
        eq_open = self.equity_open(date)
        targets = {t: share * eq_open * weights.get(t, 0.0) for t in picks}
        for t in B_UNIVERSE:
            if self.shares[t] <= 0:
                continue
            cur = self.shares[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                reason = ("selection-sell-dropout" if t not in targets
                          else "selection-rebalance-trim")
                self.do_sell(t, date, opens[t], reason,
                             (cur - tgt) / opens[t])
        wants = {}
        for t in picks:
            cur = self.shares[t] * opens[t]
            if targets[t] > cur + 0.005:
                wants[t] = targets[t] - cur
        total_want_cost = sum(v * (1 + COST_RATE) for v in wants.values())
        scale = 1.0
        if total_want_cost > self.cash and total_want_cost > 0:
            scale = max(self.cash, 0.0) / total_want_cost
        for t in picks:
            if t in wants:
                reason = ("selection-buy" if self.shares[t] == 0
                          else "selection-rebalance-add")
                self.do_buy(t, date, opens[t], wants[t] * scale, reason)

    def close_scan(self, date):
        """Trend-exit scan at today's close (cadence dates only)."""
        for t in B_UNIVERSE:
            if self.shares[t] > 1e-9:
                ma = self.mkt.ma200(t, date)
                c = self._close(t, date)
                if ma is not None and c is not None and c < ma:
                    self.pending_exits.add(t)


# =====================================================================
# January rebalance (blend.py verbatim logic)
# =====================================================================
def rebalance_january(date, A, B):
    eqA = A.equity_open(date)
    eqB = B.equity_open(date)
    total = eqA + eqB
    if total <= 0:
        return None
    target = total / 2.0
    event = {"date": date, "pre_A": round(eqA, 2), "pre_B": round(eqB, 2),
             "transferred": 0.0, "from": None}
    if abs(eqA - target) < 0.01:
        return event
    if eqA > target:
        move = eqA - target
        if A.cash < move:
            shortfall = move - A.cash
            pos_vals = {t: A.shares[t] * A_MOD.open_on(t, date)
                        for t in A_ASSETS if A.shares[t] > 0}
            tot_pos = sum(pos_vals.values())
            if tot_pos > 0:
                n_pos = len(pos_vals)
                gross = min(tot_pos,
                            (shortfall + n_pos * SELL_FEE) / (1 - COST_RATE))
                for t, v in pos_vals.items():
                    A.sell_value(t, date, gross * v / tot_pos,
                                 "jan-rebalance-sell")
        amt = min(A.cash, A.equity_open(date) - (A.equity_open(date)
                                                 + B.equity_open(date)) / 2.0)
        amt = max(0.0, amt)
        A.cash -= amt
        B.cash += amt
        event.update({"transferred": round(amt, 2), "from": "A"})
    else:
        move = target - eqA
        if B.cash < move:
            shortfall = move - B.cash
            pos_vals = {t: B.shares[t] * B_MKT.by_date[t][date]["open"]
                        for t in B_UNIVERSE if B.shares[t] > 0}
            tot_pos = sum(pos_vals.values())
            if tot_pos > 0:
                n_pos = len(pos_vals)
                gross = min(tot_pos,
                            (shortfall + n_pos * SELL_FEE) / (1 - COST_RATE))
                for t, v in pos_vals.items():
                    B.do_sell(t, date, B_MKT.by_date[t][date]["open"],
                              "jan-rebalance-sell",
                              (gross * v / tot_pos) / B_MKT.by_date[t][date]["open"])
        amt = min(B.cash, B.equity_open(date) - (A.equity_open(date)
                                                 + B.equity_open(date)) / 2.0)
        amt = max(0.0, amt)
        B.cash -= amt
        A.cash += amt
        event.update({"transferred": round(amt, 2), "from": "B"})
    event["post_A"] = round(A.equity_open(date), 2)
    event["post_B"] = round(B.equity_open(date), 2)
    return event


# =====================================================================
# Cadence date sets (SPEC uniform definition)
# =====================================================================
def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)

    def firsts(keyfn):
        seen = {}
        out = []
        for d in days:
            k = keyfn(d)
            if k not in seen:
                seen[k] = d
                out.append(d)
        return out

    if cadence == "weekly":
        return set(firsts(lambda d: datetime.strptime(d, "%Y-%m-%d")
                          .isocalendar()[:2]))
    if cadence == "biweekly":
        w = firsts(lambda d: datetime.strptime(d, "%Y-%m-%d")
                   .isocalendar()[:2])
        return set(w[::2])
    if cadence == "monthly":
        return set(firsts(lambda d: d[:7]))
    if cadence == "quarterly":
        return set(firsts(lambda d: (d[:4], (int(d[5:7]) - 1) // 3)))
    if cadence == "semiannual":
        return set(firsts(lambda d: (d[:4], int(d[5:7]) <= 6)))
    if cadence == "annual":
        return set(firsts(lambda d: d[:4]))
    raise ValueError(cadence)


# =====================================================================
# Blend runner under v9 protections
# =====================================================================
def run_blend_v9(cadence_set, placebo_seed=None):
    days = [d for d in MASTER_CAL if START <= d <= END]
    rngA = rngB = None
    if placebo_seed is not None:
        rngA = random.Random(2000 + placebo_seed)
        rngB = random.Random(3000 + placebo_seed)
    A = SleeveA(START_CASH / 2.0, rngA)
    B = SleeveB(B_MKT, START_CASH / 2.0, cadence_set, rngB)

    floor = 0.85 * START_CASH
    episode = 1
    curve = []
    halts = []
    restart = False
    second_halt = False
    rebalances = []
    liquidate_next_open = False
    breach_date = None
    inactive_until = None

    for di, d in enumerate(days):
        b_ok = B.has_data(d)

        # --- floor liquidation at the open ---
        if liquidate_next_open:
            A.sell_all(d, "floor-liquidation")
            if b_ok:
                B.sell_all(d, "floor-liquidation")
            bal = A.cash + B.cash
            curve.append((d, bal))
            halts.append({"breach_date": breach_date,
                          "liquidation_date": d, "episode": episode,
                          "balance_after": round(bal, 2)})
            liquidate_next_open = False
            if episode == 2:
                second_halt = True
                break
            episode = 2
            restart = True
            inactive_until = (datetime.strptime(d, "%Y-%m-%d")
                              + timedelta(days=90)).strftime("%Y-%m-%d")
            continue

        # --- sitting in cash after a halt ---
        if inactive_until is not None:
            if d >= inactive_until and d in cadence_set:
                total_cash = A.cash + B.cash
                A = SleeveA(total_cash / 2.0, rngA)
                B = SleeveB(B_MKT, total_cash / 2.0, cadence_set, rngB)
                floor = 0.85 * total_cash
                halts[-1]["restart_date"] = d
                halts[-1]["restart_balance"] = round(total_cash, 2)
                inactive_until = None
                # fall through and trade this cadence date normally
            else:
                curve.append((d, A.cash + B.cash))
                continue

        just_restarted = bool(halts) and halts[-1].get("restart_date") == d

        # --- January rebalance at the open ---
        if (not just_restarted and di > 0 and d[5:7] == "01"
                and days[di - 1][5:7] == "12" and b_ok):
            ev = rebalance_january(d, A, B)
            if ev:
                rebalances.append(ev)

        # --- sleeves' open executions ---
        A.execute_pending(d)
        if b_ok:
            B.open_executions(d)

        # --- mark to close ---
        eqA_c = A.equity_close(d)
        eqB_c = B.equity_close(d)
        total_c = eqA_c + eqB_c
        curve.append((d, total_c))

        # --- v9 plain floor breach check ---
        if total_c <= floor:
            if di + 1 < len(days):
                liquidate_next_open = True
                breach_date = d
                continue
            # breach on the final day: liquidate at today's closes
            for t in A_ASSETS:
                if A.shares[t] > 0:
                    p = A_MOD.close_on(t, d)
                    v = A.shares[t] * p
                    cost = v * COST_RATE + SELL_FEE
                    A.cash += v - cost
                    A.costs += cost
                    A.orders += 1
                    A.shares[t] = 0.0
            if b_ok:
                for t in B_UNIVERSE:
                    if B.shares[t] > 0:
                        B.do_sell(t, d, B_MKT.by_date[t][d]["close"],
                                  "floor-liquidation")
            halts.append({"breach_date": d, "liquidation_date": d,
                          "episode": episode,
                          "balance_after": round(A.cash + B.cash, 2)})
            if episode == 2:
                second_halt = True
            curve[-1] = (d, A.cash + B.cash)
            break

        # --- close-time evaluations on cadence dates only ---
        if d in cadence_set and di + 1 < len(days):
            A.evaluate(d, eqA_c)
            if b_ok:
                B.close_scan(d)

    final = curve[-1][1] if curve else START_CASH
    return {"final": final, "curve": curve,
            "orders": A.orders + B.orders,
            "costs": A.costs + B.costs,
            "halts": halts, "restart": restart,
            "second_halt": second_halt, "rebalances": rebalances,
            "days": days}


def metrics(res):
    days = res["days"]
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d")
           - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    cagr = (res["final"] / START_CASH) ** (1 / yrs) - 1
    peak, maxdd = -1e18, 0.0
    for _, eq in res["curve"]:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    return round(cagr * 100, 2), round(maxdd * 100, 2)


def year_returns(curve):
    by = {}
    for d, eq in curve:
        by[d[:4]] = eq
    out = {}
    prev = None
    for y in sorted(by):
        if prev is not None:
            out[y] = round((by[y] / prev - 1) * 100, 2)
        prev = by[y]
    return out


def spy_decade():
    days = [d for d in MASTER_CAL if START <= d <= END]
    buy_cost = START_CASH * COST_RATE
    sh = (START_CASH - buy_cost) / A_MOD.open_on("SPY", days[0])
    curve = [(d, sh * A_MOD.close_on("SPY", d)) for d in days]
    final = curve[-1][1] - (curve[-1][1] * COST_RATE + SELL_FEE)
    peak, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "year_returns": year_returns(curve)}


CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def main():
    days = [d for d in MASTER_CAL if START <= d <= END]
    cells_dir = os.path.join(HERE, "cells")
    os.makedirs(cells_dir, exist_ok=True)
    spy = spy_decade()
    print("SPY decade:", json.dumps(spy))
    cells = {}
    for cad in CADENCES:
        es = cadence_dates(days, cad)
        res = run_blend_v9(es)
        cagr, maxdd = metrics(res)
        yr = year_returns(res["curve"])
        twins = []
        for seed in range(20):
            pr = run_blend_v9(es, placebo_seed=seed)
            twins.append(round(pr["final"], 2))
        beaten = sum(1 for x in twins if res["final"] > x)
        cell = {"cadence": cad, "start": START, "end": END,
                "start_cash": START_CASH,
                "final": round(res["final"], 2), "cagr_pct": cagr,
                "max_dd_pct": maxdd,
                "costs": round(res["costs"], 2), "orders": res["orders"],
                "halts": res["halts"], "restart": res["restart"],
                "second_halt": res["second_halt"],
                "n_jan_rebalances": len(res["rebalances"]),
                "equity_curve": [[d, round(v, 4)] for d, v in res["curve"]],
                "placebo_twin_finals": twins, "placebo_beaten": beaten,
                "year_returns": yr,
                "ret_2020_pct": yr.get("2020"), "ret_2022_pct": yr.get("2022")}
        with open(os.path.join(cells_dir, f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        print(cad, "final", cell["final"], "cagr", cagr, "maxDD", maxdd,
              "costs", cell["costs"], "orders", cell["orders"],
              "halts", len(res["halts"]), "placebo_beaten", beaten, "/20")
    with open(os.path.join(HERE, "sweep_cells.json"), "w") as f:
        json.dump({"spy": spy, "cells": {
            c: {k: v for k, v in cell.items() if k != "equity_curve"}
            for c, cell in cells.items()}}, f, indent=2)
    print("DONE")


if __name__ == "__main__":
    main()
