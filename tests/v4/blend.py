#!/usr/bin/env python3
"""
THE BLEND — two proven defensive machines in ONE pot. Terry's AI stock
app, simulation only. No broker orders.

  Sleeve A = multi-asset ETF trend sleeve, MONTHLY implementation, exactly
             as in ../v3/etf-trend-sleeve-monthly.py (assets SPY QQQ TLT
             IEF GLD DBC UUP; 3/6/12-month sign-blend trend, hold >=2 of 3
             positive; inverse-20d-vol weights capped at 40%; 20% relative
             no-trade band; monthly eval at month-end close, trades next
             open; dividend+split-adjusted prices from ../v3/data_etf).
  Sleeve B = Disciplined chassis combo, exactly as frozen in
             chassis-walkforward.py (universe SPY QQQ IWM GLD TLT; quarterly
             selection; eligible = prior close above 200-day MA; rank by
             trailing 63-day momentum; top 3, equal weights; invested share
             0/50/100% for 0/1/2+ picks; DEFENSIVE mode ON — share capped at
             50% when SPY's prior close is below its 200-day MA; daily trend
             exits on close below 200-day MA, sold next open; split-adjusted
             prices from ../v3/data).

BLEND RULES (frozen by the task):
  - ONE pot split 50/50. Each sleeve trades only its own half; all of its
    internal percentages apply to its own sub-account.
  - Rebalanced back to 50/50 every January: at the open of the first
    trading day of January, the overweight sleeve sells positions
    pro-rata (normal sell costs) if it must raise cash, then transfers
    cash to the underweight sleeve so both hold half the (post-cost)
    total. The transfer happens BEFORE the sleeves' own trades that day,
    so sleeve orders sized off that day's open equity use post-transfer
    balances.
  - Costs per sleeve as in their reports: 0.10% of trade value per side
    + $0.01 per sell order. January-rebalance sales pay the same costs.
  - Terry's floor applies to the WHOLE pot only (sleeves carry no floor
    of their own): start S -> floor 0.85*S; floor rises to S at a pot
    close >= 1.25*S, and to 1.25*S at a close >= 1.50*S. A pot close at
    or below the floor liquidates EVERYTHING at the next open and the
    run ends (no restart — the parents never halted; if the blend does,
    that is the result).
    $100: floor $85 / $100 @ $125 / $125 @ $150.
    $50:  floor $42.50 / $50 @ $62.50 / $62.50 @ $75.

Each sleeve keeps its own books on its own price basis, exactly as in
its own report (A: dividend-adjusted; B: split-adjusted only). The pot
total is the sum of the two sleeve equities. This basis difference is
inherited from the parent studies and disclosed in blend.md.

REPLICATION CHECKS (run first, must match the published parents):
  - Sleeve A standalone (its own simulate(), floor active): full window
    $100 -> $194.61, 389 orders, $9.17 costs.
  - Sleeve B standalone (chassis run_window, frozen config): full window
    $100 -> $233.54, 152 trades, $6.47 costs.
  The in-blend sleeve engines below are separate re-implementations with
  the floor removed; standalone no-floor runs of those engines are also
  checked against the same published numbers (neither parent ever
  halted, so floor-free must reproduce them to the cent).
"""
import importlib.util
import json
import math
import os
import statistics
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.join(HERE, "..", "v3")
V4 = HERE

COST_RATE = 0.001
SELL_FEE = 0.01


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- parent modules (data + reference engines, used read-only) ---
A_MOD = load_module("etf_sleeve_monthly",
                    os.path.join(V3, "etf-trend-sleeve-monthly.py"))
sys.path.insert(0, V4)
B_MOD = load_module("chassis_wf", os.path.join(V4, "chassis-walkforward.py"))
B_MKT = B_MOD.Market()
B_CFG = dict(B_MOD.CHASSIS_CFG)

A_ASSETS = A_MOD.ASSETS           # SPY QQQ TLT IEF GLD DBC UUP
B_UNIVERSE = B_MOD.UNIVERSE       # SPY QQQ IWM GLD TLT
MASTER_CAL = A_MOD.CAL            # SPY trading days (dividend-adj cache)


# =====================================================================
# Sleeve A — stateful re-implementation of etf-trend-sleeve-monthly.py
# simulate(), minus the floor (the blend's floor is pot-level).
# =====================================================================
class SleeveA:
    def __init__(self, cash):
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in A_ASSETS}
        self.orders = 0
        self.costs = 0.0
        self.pending = None       # (trade_set, target_weights)
        self.log = []

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
        """Sell `sell_val` dollars of t at today's open (A basis)."""
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
        self.log.append((date, "SELL", t, round(sell_val, 2), reason))
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
                self.log.append((date, "BUY", t, round(buy_val, 2),
                                 "sleeveA-rebalance"))
        self.pending = None

    def evaluate(self, date, eq_close):
        """Monthly evaluation at today's close (parent logic verbatim)."""
        vols = {}
        for t in A_ASSETS:
            tv = A_MOD.trend_and_vol(t, date)
            if tv is None:
                continue
            npos, vol = tv
            if npos >= 2 and vol:
                vols[t] = vol
        targets = A_MOD.capped_inv_vol_weights(vols)
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
# Sleeve B — stateful re-implementation of chassis-walkforward.py
# run_segment() with CHASSIS_CFG, minus floor/restarts.
# =====================================================================
class SleeveB:
    def __init__(self, mkt, cash, period_dates):
        self.mkt = mkt
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in B_UNIVERSE}
        self.orders = 0
        self.costs = 0.0
        self.pending_exits = set()
        self.log = []
        # selection days over this sleeve's own period dates (parent logic)
        self.selection_days = set()
        seen = set()
        for d in period_dates:
            key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
            if d == period_dates[0] or key not in seen:
                self.selection_days.add(d)
            seen.add(key)
        self._idx = {d: i for i, d in enumerate(mkt.dates_all)}

    def has_data(self, date):
        return all(date in self.mkt.by_date[t] for t in B_UNIVERSE)

    def _close(self, t, date):
        bd = self.mkt.by_date[t]
        if date in bd:
            return bd[date]["close"]
        # forward-fill from this ticker's own history
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
        self.log.append((date, "SELL", t, round(value, 2), reason))
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
        self.log.append((date, "BUY", t, round(value, 2), reason))

    def sell_all(self, date, reason):
        for t in B_UNIVERSE:
            if self.shares[t] > 0:
                self.do_sell(t, date, self.mkt.by_date[t][date]["open"],
                             reason)

    def open_executions(self, date):
        """Pending trend exits, then quarterly selection — parent order."""
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
        """Trend-exit scan at today's close (parent logic)."""
        for t in B_UNIVERSE:
            if self.shares[t] > 1e-9:
                ma = self.mkt.ma200(t, date)
                c = self._close(t, date)
                if ma is not None and c is not None and c < ma:
                    self.pending_exits.add(t)


# =====================================================================
# January rebalance helpers
# =====================================================================
def rebalance_january(date, A, B):
    """Restore 50/50 at today's open. Returns event dict or None."""
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
# Blend runner
# =====================================================================
def run_blend(start, end, start_cash):
    days = [d for d in MASTER_CAL if start <= d <= end]
    b_days = [d for d in B_MKT.dates_all if start <= d <= end]
    A = SleeveA(start_cash / 2.0)
    B = SleeveB(B_MKT, start_cash / 2.0, b_days)

    # Sleeve A monthly eval days within the run (parent: last trading
    # day of each calendar month among the run's days)
    by_month = {}
    for d in days:
        by_month.setdefault(d[:7], []).append(d)
    a_eval_days = {max(ds) for ds in by_month.values()}

    floor = 0.85 * start_cash
    curve = []            # (date, total_close_equity)
    sleeve_curve = []     # (date, eqA_close, eqB_close)
    rebalances = []
    halted = None
    liquidate_next_open = False
    b_mismatch = 0

    for di, d in enumerate(days):
        b_ok = B.has_data(d)
        if not b_ok:
            b_mismatch += 1

        # --- pot-level floor liquidation at the open ---
        if liquidate_next_open:
            A.sell_all(d, "floor-liquidation")
            if b_ok:
                B.sell_all(d, "floor-liquidation")
            halted = d
            total = A.cash + B.cash
            curve.append((d, total))
            sleeve_curve.append((d, A.cash, B.cash))
            break

        # --- January rebalance at the open (not on the run's first day) ---
        if di > 0 and d[5:7] == "01" and (di == 0 or days[di - 1][5:7] == "12"):
            if b_ok:
                ev = rebalance_january(d, A, B)
                if ev:
                    rebalances.append(ev)

        # --- sleeves' own open executions ---
        A.execute_pending(d)
        if b_ok:
            B.open_executions(d)

        # --- mark to close ---
        eqA_c = A.equity_close(d)
        eqB_c = B.equity_close(d)
        total_c = eqA_c + eqB_c
        curve.append((d, total_c))
        sleeve_curve.append((d, eqA_c, eqB_c))

        # --- pot floor: ladder, then breach check ---
        if total_c >= 1.50 * start_cash:
            floor = max(floor, 1.25 * start_cash)
        elif total_c >= 1.25 * start_cash:
            floor = max(floor, float(start_cash))
        if total_c <= floor:
            if di + 1 < len(days):
                liquidate_next_open = True
                continue
            else:
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
                halted = d
                curve[-1] = (d, A.cash + B.cash)
                sleeve_curve[-1] = (d, A.cash, B.cash)
                break

        # --- close-time evaluations ---
        if d in a_eval_days and di + 1 < len(days):
            A.evaluate(d, eqA_c)
        if b_ok:
            B.close_scan(d)

    final = curve[-1][1] if curve else start_cash
    return {"final": final, "curve": curve, "sleeve_curve": sleeve_curve,
            "orders": A.orders + B.orders,
            "orders_A": A.orders, "orders_B": B.orders,
            "costs": A.costs + B.costs,
            "costs_A": A.costs, "costs_B": B.costs,
            "halted": halted, "rebalances": rebalances,
            "start_cash": start_cash, "days": days,
            "b_mismatch_days": b_mismatch}


# =====================================================================
# Standalone sleeve runners (in-blend engines, floor-free) for the
# replication check and the monthly-return correlation.
# =====================================================================
def run_sleeveA_alone(start, end, start_cash):
    days = [d for d in MASTER_CAL if start <= d <= end]
    A = SleeveA(start_cash)
    by_month = {}
    for d in days:
        by_month.setdefault(d[:7], []).append(d)
    eval_days = {max(ds) for ds in by_month.values()}
    curve = []
    for di, d in enumerate(days):
        A.execute_pending(d)
        eq_c = A.equity_close(d)
        curve.append((d, eq_c))
        if d in eval_days and di + 1 < len(days):
            A.evaluate(d, eq_c)
    return {"final": curve[-1][1], "curve": curve, "orders": A.orders,
            "costs": A.costs}


def run_sleeveB_alone(start, end, start_cash):
    b_days = [d for d in B_MKT.dates_all if start <= d <= end]
    B = SleeveB(B_MKT, start_cash, b_days)
    curve = []
    for di, d in enumerate(b_days):
        B.open_executions(d)
        eq_c = B.equity_close(d)
        curve.append((d, eq_c))
        B.close_scan(d)
    return {"final": curve[-1][1], "curve": curve, "orders": B.orders,
            "costs": B.costs}


# =====================================================================
# Metrics helpers
# =====================================================================
def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd


def cagr_of(final, start_cash, days):
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d")
           - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    return (final / start_cash) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def year_table(curve):
    """{year: (year_end_equity, calendar-year return or None)}"""
    by_year = {}
    for d, eq in curve:
        by_year.setdefault(d[:4], []).append((d, eq))
    out = {}
    prev = None
    for y in sorted(by_year):
        last = by_year[y][-1][1]
        out[y] = (last, (last / prev - 1.0) if prev is not None else None)
        prev = last
    return out


def monthly_returns(curve):
    """{YYYY-MM: return} from month-end equities (first partial month
    measured from the curve's first value)."""
    by_month = {}
    for d, eq in curve:
        by_month.setdefault(d[:7], []).append((d, eq))
    out = {}
    prev = None
    for mo in sorted(by_month):
        last = by_month[mo][-1][1]
        if prev is not None:
            out[mo] = last / prev - 1.0
        prev = last
    return out


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spy_buy_hold(start, end, amount):
    """SPY buy-hold net of costs on sleeve A's adjusted basis."""
    days = [d for d in MASTER_CAL if start <= d <= end]
    d0, d1 = days[0], days[-1]
    buy_cost = amount * COST_RATE
    sh = (amount - buy_cost) / A_MOD.open_on("SPY", d0)
    val = sh * A_MOD.close_on("SPY", d1)
    return val - (val * COST_RATE + SELL_FEE)


def spy_year_ret(year):
    days = [d for d in MASTER_CAL if d[:4] == str(year)]
    prev = [d for d in MASTER_CAL if d[:4] == str(year - 1)]
    if not days or not prev:
        return None
    return A_MOD.close_on("SPY", days[-1]) / A_MOD.close_on("SPY", prev[-1]) - 1.0


def summarize(name, res, start_cash, days):
    m = {"name": name, "final": round(res["final"], 2),
         "return_pct": round((res["final"] / start_cash - 1) * 100, 2),
         "cagr_pct": round(cagr_of(res["final"], start_cash, days) * 100, 2),
         "maxdd_pct": round(max_dd(res["curve"]) * 100, 2),
         "orders": res["orders"], "costs": round(res["costs"], 2),
         "halted": res.get("halted")}
    print(f"{name}: final=${m['final']} ret={m['return_pct']:+.2f}% "
          f"CAGR={m['cagr_pct']:+.2f}% maxDD={m['maxdd_pct']:.2f}% "
          f"orders={m['orders']} costs=${m['costs']} halted={m['halted']}")
    return m


def main():
    FULL = ("2016-11-21", "2026-11-20")
    VAL = ("2023-01-01", "2026-11-20")
    out = {}

    # ---------- replication checks ----------
    print("== REPLICATION CHECKS ==")
    a_pub = A_MOD.simulate(*FULL)  # published monthly sleeve, floor active
    print(f"Sleeve A parent engine: final=${a_pub['final']:.2f} "
          f"orders={a_pub['orders']} costs=${a_pub['costs']:.2f} "
          f"(expect 194.61 / 389 / 9.17)")
    out["repl_A_parent"] = {"final": round(a_pub["final"], 2),
                            "orders": a_pub["orders"],
                            "costs": round(a_pub["costs"], 2)}
    a_alone = run_sleeveA_alone(*FULL, 100.0)
    print(f"Sleeve A in-blend engine (no floor): final=${a_alone['final']:.2f} "
          f"orders={a_alone['orders']} costs=${a_alone['costs']:.2f}")
    out["repl_A_engine"] = {"final": round(a_alone["final"], 2),
                            "orders": a_alone["orders"],
                            "costs": round(a_alone["costs"], 2)}

    b_pub = B_MOD.run_window(B_MKT, dict(B_CFG), *FULL, start_capital=100.0)
    print(f"Sleeve B parent engine: final=${b_pub['final_balance']} "
          f"trades={b_pub['total_trades']} costs=${b_pub['total_costs']} "
          f"(expect 233.54 / 152 / 6.47)")
    out["repl_B_parent"] = {"final": b_pub["final_balance"],
                            "orders": b_pub["total_trades"],
                            "costs": b_pub["total_costs"]}
    b_alone = run_sleeveB_alone(*FULL, 100.0)
    print(f"Sleeve B in-blend engine (no floor): final=${b_alone['final']:.2f} "
          f"orders={b_alone['orders']} costs=${b_alone['costs']:.2f}")
    out["repl_B_engine"] = {"final": round(b_alone["final"], 2),
                            "orders": b_alone["orders"],
                            "costs": round(b_alone["costs"], 2)}

    # ---------- standalone sleeves on both windows (in-blend engines) ----
    print("\n== STANDALONE SLEEVES (in-blend engines, no sleeve floor) ==")
    days_full = [d for d in MASTER_CAL if FULL[0] <= d <= FULL[1]]
    days_val = [d for d in MASTER_CAL if VAL[0] <= d <= VAL[1]]
    sa = {}
    for label, (s, e), days in (("full", FULL, days_full),
                                ("val", VAL, days_val)):
        for size in (100.0, 50.0):
            ra = run_sleeveA_alone(s, e, size)
            rb = run_sleeveB_alone(s, e, size)
            sa[f"A_{label}_{int(size)}"] = summarize(
                f"SleeveA {label} ${int(size)}", ra, size, days)
            sa[f"B_{label}_{int(size)}"] = summarize(
                f"SleeveB {label} ${int(size)}", rb, size, days)
            sa[f"A_{label}_{int(size)}"]["curve"] = ra["curve"]
            sa[f"B_{label}_{int(size)}"]["curve"] = rb["curve"]
    out["standalone"] = {k: {kk: vv for kk, vv in v.items() if kk != "curve"}
                         for k, v in sa.items()}

    # Sleeve B standalone via its parent engine on validation (published
    # chassis report has no continuous validation run; this is the re-run
    # the task allows).
    bv100 = B_MOD.run_window(B_MKT, dict(B_CFG), *VAL, start_capital=100.0)
    bv50 = B_MOD.run_window(B_MKT, dict(B_CFG), *VAL, start_capital=50.0)
    out["B_parent_validation"] = {
        "100": {"final": bv100["final_balance"],
                "maxdd_pct": bv100["max_drawdown_pct"],
                "trades": bv100["total_trades"],
                "costs": bv100["total_costs"]},
        "50": {"final": bv50["final_balance"],
               "maxdd_pct": bv50["max_drawdown_pct"],
               "trades": bv50["total_trades"],
               "costs": bv50["total_costs"]}}
    print(f"Sleeve B parent engine validation: $100 -> "
          f"${bv100['final_balance']} (DD {bv100['max_drawdown_pct']}%), "
          f"$50 -> ${bv50['final_balance']} (DD {bv50['max_drawdown_pct']}%)")

    # ---------- correlation of sleeve monthly returns (standalone) ------
    ma = monthly_returns(sa["A_full_100"]["curve"])
    mb = monthly_returns(sa["B_full_100"]["curve"])
    common = sorted(set(ma) & set(mb))
    r = pearson([ma[m] for m in common], [mb[m] for m in common])
    out["sleeve_monthly_corr"] = {"r": round(r, 3) if r is not None else None,
                                  "n_months": len(common)}
    print(f"\nSleeve monthly-return correlation (standalone, full window): "
          f"r={r:.3f} over {len(common)} months")

    # ---------- the blend ----------
    print("\n== THE BLEND ==")
    blends = {}
    for label, (s, e), days in (("full", FULL, days_full),
                                ("val", VAL, days_val)):
        for size in (100.0, 50.0):
            res = run_blend(s, e, size)
            key = f"blend_{label}_{int(size)}"
            m = summarize(f"BLEND {label} ${int(size)}", res, size, days)
            m["orders_A"] = res["orders_A"]
            m["orders_B"] = res["orders_B"]
            m["costs_A"] = round(res["costs_A"], 2)
            m["costs_B"] = round(res["costs_B"], 2)
            m["n_rebalances"] = len(res["rebalances"])
            m["b_mismatch_days"] = res["b_mismatch_days"]
            yt = year_table(res["curve"])
            m["year_table"] = {y: {"end": round(v[0], 2),
                                   "ret_pct": (round(v[1] * 100, 2)
                                               if v[1] is not None else None)}
                               for y, v in yt.items()}
            m["ret_2022"] = (round(yt["2022"][1] * 100, 2)
                             if "2022" in yt and yt["2022"][1] is not None
                             else None)
            m["rebalances"] = res["rebalances"]
            blends[key] = m
            print(f"  rebalances={len(res['rebalances'])} "
                  f"2022={m['ret_2022']} B-mismatch-days={res['b_mismatch_days']}")
    out["blend"] = blends

    # ---------- benchmarks ----------
    out["spy"] = {
        "full_100": round(spy_buy_hold(*FULL, 100.0), 2),
        "full_50": round(spy_buy_hold(*FULL, 50.0), 2),
        "val_100": round(spy_buy_hold(*VAL, 100.0), 2),
        "val_50": round(spy_buy_hold(*VAL, 50.0), 2),
        "ret_2022_pct": round(spy_year_ret(2022) * 100, 2),
    }
    print(f"\nSPY buy-hold net: full $100 -> ${out['spy']['full_100']}, "
          f"$50 -> ${out['spy']['full_50']}; val $100 -> "
          f"${out['spy']['val_100']}, $50 -> ${out['spy']['val_50']}; "
          f"2022 {out['spy']['ret_2022_pct']:+.2f}%")

    with open(os.path.join(HERE, "blend-results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved blend-results.json")


if __name__ == "__main__":
    main()
