#!/usr/bin/env python3
"""
THE BLEND + MILLENNIUM LADDER — Terry's AI stock app, simulation only.

BASE (the plain BLEND, reconstructed exactly — blend.py/blend.md did not
exist yet when this test was written):
  One pot, two sleeves, each starting with 50% of the pot:
    Sleeve A = ETF trend sleeve, MONTHLY version
      (../v3/etf-trend-sleeve-monthly.py: SPY QQQ TLT IEF GLD DBC UUP,
      3/6/12-mo sign blend, >=2 of 3 positive, inverse-20d-vol weights,
      40% cap, 20% no-trade band, monthly eval at close, trades next open,
      adjusted prices).
    Sleeve B = Disciplined chassis, frozen v3-verdict synthesis
      (chassis-walkforward.py CHASSIS_CFG: SPY QQQ IWM GLD TLT, eligible
      above 200-day MA, 63-day momentum rank, top 3, EQUAL weights,
      invested share 0/50/100% for 0/1/2+ picks, DEFENSIVE mode on,
      quarterly selections, daily trend exits, split-adjusted prices).
  January rebalance: on the first trading day of each calendar year, at
  the open, sleeve capitals are reset to 50/50 of total pot equity
  (sell-downs pro-rata at the open, costs charged; cash transfers free).
  Pot-level Terry floor: close at/below floor -> liquidate all next open,
  run ends (no restart). Final balances are mark-to-market (no forced
  final liquidation) for both blend variants, identically.

THIS TEST changes ONE thing vs the plain blend: the MILLENNIUM LADDER
(big-contenders.md section 10.4) applied per sleeve:
  - Each sleeve has its own peak = highest daily close equity since the
    last January rebalance (peak resets to the sleeve's close equity on
    the January rebalance day; benched sleeves keep their peak).
    Drawdown is measured on RETURNS, as Millennium measures pod P&L:
    whenever the ladder or the January rebalance moves capital into or
    out of a sleeve, the peak is rescaled by the same factor as the
    sleeve's equity, so an allocator withdrawal is never counted as a
    trading loss (and a top-up never as a gain).
  - Sleeve down >=5% from its peak (at a close) -> HALVED at next open:
    half the sleeve's capital is moved to the pot's cash reserve
    (pro-rata sell-down at the open if the sleeve's cash is short).
  - Sleeve down >=7.5% from its peak -> BENCHED at next open: all
    holdings sold, all sleeve capital moved to reserve. A SHADOW copy
    of the sleeve (its exact cash/holdings at the bench close) keeps
    paper-trading the sleeve's own rules, costs charged virtually.
  - RESTORE RULE (exact implementation): while benched, when the shadow
    sleeve's close equity recovers to >= 97.5% of the peak in force when
    it was benched, the sleeve is restored at the next open at HALF
    weight: it receives capital = 25% of pot equity (paid from reserve,
    capped at reserve) and adopts the shadow portfolio scaled by
    (capital received / shadow equity at the prior close), in kind, no
    transaction costs on the adoption. Its peak becomes the bench peak.
    A halved sleeve whose real close equity exceeds its peak is
    restored to FULL weight at the next open: topped up from reserve to
    50% of pot equity. Freed cash always sits in the reserve — it is
    never given to the other sleeve. January targets respect the state:
    FULL sleeve -> 50% of pot, HALVED -> 25%, BENCHED -> 0.
Costs everywhere: 0.10% of trade value per side + $0.01 per sell order.
Floors: $100 start -> floor $85, $100 @ $125 close, $125 @ $150 close.
        $50  start -> floor $42.50, $50 @ $62.50 close, $62.50 @ $75.
"""
import importlib.util, json, math, os, statistics
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


ETF = load_module("etf_monthly", os.path.join(V3, "etf-trend-sleeve-monthly.py"))
CHA = load_module("chassis", os.path.join(V4, "chassis-walkforward.py"))
MKT = CHA.Market()
CHASSIS_CFG = dict(CHA.CHASSIS_CFG)
A_ASSETS = ETF.ASSETS

MASTER = [d for d in MKT.dates_all if d in set(ETF.CAL)]
MASTER_IDX = {d: i for i, d in enumerate(MASTER)}


def month_last_days(days):
    out, by = set(), {}
    for d in days:
        by.setdefault(d[:7], []).append(d)
    for ds in by.values():
        out.add(max(ds))
    return out


def quarter_first_days(days):
    out, seen = set(), set()
    for d in days:
        key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
        if key not in seen:
            out.add(d)
        seen.add(key)
    return out


def jan_first_days(days):
    out, seen = set(), set()
    for d in days:
        if d[:4] not in seen:
            out.add(d)
        seen.add(d[:4])
    return out


# ---------------------------------------------------------------- Sleeve A
class SleeveA:
    """ETF trend sleeve (monthly), stepping on its own sub-account."""

    def __init__(self, cash):
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in A_ASSETS}
        self.pending = None
        self.orders = 0
        self.costs = 0.0

    def equity(self, date, price_fn):
        eq = self.cash
        for t in A_ASSETS:
            if self.shares[t] > 0:
                p = price_fn(t, date)
                if p:
                    eq += self.shares[t] * p
        return eq

    def eq_open(self, date):
        return self.equity(date, ETF.open_on)

    def eq_close(self, date):
        return self.equity(date, ETF.close_on)

    def _sell(self, t, date, value):
        price = ETF.open_on(t, date)
        if price <= 0 or value <= 0:
            return
        sh = min(value / price, self.shares[t])
        val = sh * price
        cost = val * COST_RATE + SELL_FEE
        self.cash += val - cost
        self.shares[t] -= sh
        if self.shares[t] < 1e-9:
            self.shares[t] = 0.0
        self.orders += 1
        self.costs += cost

    def _buy(self, t, date, value):
        price = ETF.open_on(t, date)
        if price <= 0 or value <= 0:
            return
        cost = value * COST_RATE
        self.cash -= value + cost
        self.shares[t] += value / price
        self.orders += 1
        self.costs += cost

    def sell_pro_rata(self, date, need_cash):
        """Raise need_cash of cash by selling holdings pro-rata (at open)."""
        if need_cash <= 0:
            return
        total_val = sum(self.shares[t] * ETF.open_on(t, date)
                        for t in A_ASSETS if self.shares[t] > 0)
        if total_val <= 0:
            return
        for t in A_ASSETS:
            if self.shares[t] > 0:
                frac = self.shares[t] * ETF.open_on(t, date) / total_val
                self._sell(t, date, need_cash * frac)

    def sell_all(self, date):
        for t in A_ASSETS:
            if self.shares[t] > 0:
                self._sell(t, date, self.shares[t] * ETF.open_on(t, date))

    def step_open(self, date):
        if self.pending is None:
            return
        trade_set, targets = self.pending
        eq_open = self.eq_open(date)
        for t in sorted(trade_set):
            tgt_val = targets.get(t, 0.0) * eq_open
            cur_val = self.shares[t] * ETF.open_on(t, date)
            diff = cur_val - tgt_val
            if diff > 0.01 and self.shares[t] > 0:
                self._sell(t, date, min(diff, cur_val))
        buy_list = []
        for t in sorted(trade_set):
            tgt_val = targets.get(t, 0.0) * eq_open
            cur_val = self.shares[t] * ETF.open_on(t, date)
            diff = tgt_val - cur_val
            if diff > 0.01:
                buy_list.append((t, diff))
        tot_buy = sum(v for _, v in buy_list)
        if tot_buy > 0:
            scale = min(1.0, self.cash / (tot_buy * (1 + COST_RATE)))
            for t, diff in buy_list:
                if diff * scale >= 0.01:
                    self._buy(t, date, diff * scale)
        self.pending = None

    def step_close(self, date, is_eval, is_last):
        eq_c = self.eq_close(date)
        if is_eval and not is_last:
            vols = {}
            for t in A_ASSETS:
                tv = ETF.trend_and_vol(t, date)
                if tv is None:
                    continue
                npos, vol = tv
                if npos >= 2 and vol:
                    vols[t] = vol
            targets = ETF.capped_inv_vol_weights(vols)
            trade_set = set()
            for t in A_ASSETS:
                cur_w = (self.shares[t] * ETF.close_on(t, date) / eq_c) if eq_c > 0 else 0.0
                tgt_w = targets.get(t, 0.0)
                held = self.shares[t] > 0
                if held and tgt_w == 0.0:
                    trade_set.add(t)
                elif not held and tgt_w > 0.0:
                    trade_set.add(t)
                elif held and tgt_w > 0.0 and abs(tgt_w - cur_w) / tgt_w > 0.20:
                    trade_set.add(t)
            if trade_set:
                self.pending = (trade_set, targets)
        return eq_c

    def clone(self):
        s = SleeveA(self.cash)
        s.shares = dict(self.shares)
        s.pending = self.pending
        return s


# ---------------------------------------------------------------- Sleeve B
class SleeveB:
    """Disciplined chassis (frozen v3 synthesis), on its own sub-account."""

    def __init__(self, mkt, cfg, cash):
        self.mkt = mkt
        self.cfg = cfg
        self.cash = float(cash)
        self.shares = {t: 0.0 for t in cfg["universe"]}
        self.pending_exits = set()
        self.orders = 0
        self.costs = 0.0

    def _open(self, t, date):
        return self.mkt.by_date[t][date]["open"]

    def _close(self, t, date):
        return self.mkt.by_date[t][date]["close"]

    def equity(self, date, which):
        fn = self._open if which == "open" else self._close
        return self.cash + sum(self.shares[t] * fn(t, date)
                               for t in self.cfg["universe"])

    def eq_open(self, date):
        return self.equity(date, "open")

    def eq_close(self, date):
        return self.equity(date, "close")

    def _sell(self, t, date, price, n=None):
        n = self.shares[t] if n is None else min(n, self.shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.costs += cost
        self.shares[t] -= n
        self.orders += 1

    def _buy(self, t, date, price, value):
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > self.cash + 1e-9:
            value = self.cash / (1 + COST_RATE)
            cost = value * COST_RATE
        self.cash -= value + cost
        self.costs += cost
        self.shares[t] += value / price
        self.orders += 1

    def sell_pro_rata(self, date, need_cash):
        if need_cash <= 0:
            return
        total_val = sum(self.shares[t] * self._open(t, date)
                        for t in self.cfg["universe"] if self.shares[t] > 0)
        if total_val <= 0:
            return
        for t in self.cfg["universe"]:
            if self.shares[t] > 0:
                frac = self.shares[t] * self._open(t, date) / total_val
                self._sell(t, date, self._open(t, date),
                           (need_cash * frac) / self._open(t, date))

    def sell_all(self, date):
        for t in self.cfg["universe"]:
            if self.shares[t] > 0:
                self._sell(t, date, self._open(t, date))

    def step_open(self, date, is_selection):
        mkt, cfg = self.mkt, self.cfg
        universe = cfg["universe"]
        for t in sorted(self.pending_exits):
            if self.shares[t] > 0:
                self._sell(t, date, self._open(t, date))
        self.pending_exits = set()
        if not is_selection:
            return
        dates_all = mkt.dates_all
        ref = dates_all[dates_all.index(date) - 1]
        info = {}
        for t in universe:
            ma = mkt.ma200(t, ref)
            c = mkt.by_date[t][ref]["close"]
            elig = (ma is not None and c > ma)
            info[t] = {"close": c, "ma200": ma, "eligible": elig,
                       "mom": mkt.mom(t, ref, cfg["mom_lookback"])}
        eligible = [t for t in universe if info[t]["eligible"]]
        ranked = sorted(eligible, key=lambda t: info[t]["mom"], reverse=True)
        picks = ranked[:cfg["top_k"]]
        if len(picks) == 0:
            share = 0.0
        elif len(picks) == 1:
            share = 0.5
        else:
            share = 1.0
        if cfg["defensive"]:
            spy_ma = info["SPY"]["ma200"]
            if spy_ma is not None and info["SPY"]["close"] < spy_ma:
                share = min(share, 0.5)
        weights = {t: 1.0 / len(picks) for t in picks} if picks else {}
        opens = {t: self._open(t, date) for t in universe}
        eq_open = self.cash + sum(self.shares[t] * opens[t] for t in universe)
        targets = {t: share * eq_open * weights.get(t, 0.0) for t in picks}
        for t in universe:
            if self.shares[t] <= 0:
                continue
            cur = self.shares[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                self._sell(t, date, opens[t], (cur - tgt) / opens[t])
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
                self._buy(t, date, opens[t], wants[t] * scale)

    def step_close(self, date):
        eq_c = self.eq_close(date)
        for t in self.cfg["universe"]:
            if self.shares[t] > 1e-9:
                ma = self.mkt.ma200(t, date)
                if ma is not None and self._close(t, date) < ma:
                    self.pending_exits.add(t)
        return eq_c

    def clone(self):
        s = SleeveB(self.mkt, self.cfg, self.cash)
        s.shares = dict(self.shares)
        s.pending_exits = set(self.pending_exits)
        return s


# ---------------------------------------------------------------- the pot
def run_pot(start, end, start_cash, use_ladder):
    days = [d for d in MASTER if start <= d <= end]
    eval_days = month_last_days(days)
    q_firsts = quarter_first_days(MASTER)
    sel_days = set(q_firsts)
    sel_days.add(days[0])
    jan_days = jan_first_days(days)
    jan_days.discard(days[0])

    floor = 0.85 * start_cash
    A = SleeveA(0.5 * start_cash)
    B = SleeveB(MKT, CHASSIS_CFG, 0.5 * start_cash)
    sleeves = {"A": A, "B": B}
    reserve = 0.0
    state = {"A": "FULL", "B": "FULL"}
    peak = {"A": 0.5 * start_cash, "B": 0.5 * start_cash}
    shadow = {"A": None, "B": None}
    shadow_peak = {"A": None, "B": None}
    shadow_eq = {"A": None, "B": None}
    counts = {"A": {"halved": 0, "benched": 0, "restored_half": 0,
                    "restored_full": 0},
              "B": {"halved": 0, "benched": 0, "restored_half": 0,
                    "restored_full": 0}}
    events = []
    extra_orders = 0
    extra_costs = 0.0
    curve = []
    queued = []          # ladder actions for next open
    liquidate_next = False
    halted = None
    reset_peak_today = False

    def pot_eq_open(date):
        return reserve + A.eq_open(date) + B.eq_open(date)

    for di, d in enumerate(days):
        is_last = (di == len(days) - 1)

        if liquidate_next:
            o0, c0 = A.orders, A.costs
            A.sell_all(d)
            extra_orders += A.orders - o0
            extra_costs += A.costs - c0
            o0, c0 = B.orders, B.costs
            B.sell_all(d)
            extra_orders += B.orders - o0
            extra_costs += B.costs - c0
            halted = d
            curve.append((d, reserve + A.cash + B.cash))
            break

        # ---- ladder actions at the open ----
        if use_ladder and queued:
            pe_open = pot_eq_open(d)
            retry = []
            for action, key in queued:
                s = sleeves[key]
                if action == "halve" and state[key] == "FULL":
                    eq_before = s.eq_open(d)
                    cash_out = 0.5 * eq_before
                    if s.cash < cash_out:
                        o0, c0 = s.orders, s.costs
                        s.sell_pro_rata(d, cash_out - s.cash)
                        extra_orders += s.orders - o0
                        extra_costs += s.costs - c0
                    move = min(cash_out, s.cash)
                    s.cash -= move
                    reserve += move
                    # capital withdrawal is not a loss: rescale the peak
                    # into the sleeve's new capital scale (drawdown is
                    # measured on returns, as Millennium measures pod P&L)
                    eq_after = s.eq_open(d)
                    if eq_before > 0:
                        peak[key] *= eq_after / eq_before
                    state[key] = "HALVED"
                    counts[key]["halved"] += 1
                    events.append((d, key, "halved"))
                elif action == "bench" and state[key] != "BENCHED":
                    sh = s.clone()
                    shadow[key] = sh
                    shadow_peak[key] = peak[key]
                    shadow_eq[key] = sh.eq_close(days[di - 1]) if di > 0 else sh.cash
                    o0, c0 = s.orders, s.costs
                    s.sell_all(d)
                    extra_orders += s.orders - o0
                    extra_costs += s.costs - c0
                    reserve += s.cash
                    s.cash = 0.0
                    state[key] = "BENCHED"
                    counts[key]["benched"] += 1
                    events.append((d, key, "benched"))
                elif action == "restore_half" and state[key] == "BENCHED":
                    sh = shadow[key]
                    target = 0.25 * pe_open
                    give = min(target, reserve)
                    if give > 0 and shadow_eq[key] and shadow_eq[key] > 0:
                        f = give / shadow_eq[key]
                        s.cash = sh.cash * f
                        s.shares = {t: v * f for t, v in sh.shares.items()}
                        if isinstance(s, SleeveA):
                            s.pending = sh.pending
                        else:
                            s.pending_exits = set(sh.pending_exits)
                        reserve -= give
                        state[key] = "HALVED"
                        # peak rescaled into the restored sleeve's new
                        # capital scale by the same adoption factor
                        peak[key] = shadow_peak[key] * f
                        counts[key]["restored_half"] += 1
                        events.append((d, key, "restored_half"))
                        shadow[key] = None
                    else:
                        retry.append((action, key))
                elif action == "restore_full" and state[key] == "HALVED":
                    topup = min(reserve, max(0.0, 0.5 * pe_open - s.eq_open(d)))
                    reserve -= topup
                    s.cash += topup
                    state[key] = "FULL"
                    counts[key]["restored_full"] += 1
                    events.append((d, key, "restored_full"))
            queued = retry

        # ---- January rebalance at the open ----
        if d in jan_days:
            pe_open = pot_eq_open(d)
            targets_cap = {}
            for key, s in sleeves.items():
                if not use_ladder:
                    targets_cap[key] = 0.5 * pe_open
                elif state[key] == "FULL":
                    targets_cap[key] = 0.5 * pe_open
                elif state[key] == "HALVED":
                    targets_cap[key] = 0.25 * pe_open
                else:
                    targets_cap[key] = 0.0
            for key, s in sleeves.items():
                eq_o = s.eq_open(d)
                if eq_o > targets_cap[key] + 0.005:
                    need = eq_o - targets_cap[key] - s.cash
                    if need > 0:
                        o0, c0 = s.orders, s.costs
                        s.sell_pro_rata(d, need)
                        extra_orders += s.orders - o0
                        extra_costs += s.costs - c0
                    move = min(eq_o - targets_cap[key], s.cash)
                    if move > 0:
                        s.cash -= move
                        reserve += move
            for key, s in sleeves.items():
                eq_o = s.eq_open(d)
                deficit = targets_cap[key] - eq_o
                if deficit > 0.005 and reserve > 0:
                    move = min(deficit, reserve)
                    reserve -= move
                    s.cash += move
            reset_peak_today = use_ladder

        # ---- sleeves' own open executions ----
        B.step_open(d, d in sel_days)
        A.step_open(d)
        if use_ladder:
            for key in ("A", "B"):
                if state[key] == "BENCHED" and shadow[key] is not None:
                    sh = shadow[key]
                    if key == "B":
                        sh.step_open(d, d in q_firsts)
                    else:
                        sh.step_open(d)

        # ---- closes ----
        eqA = A.step_close(d, d in eval_days, is_last)
        eqB = B.step_close(d)
        if use_ladder:
            for key in ("A", "B"):
                if state[key] == "BENCHED" and shadow[key] is not None:
                    sh = shadow[key]
                    if key == "A":
                        shadow_eq[key] = sh.step_close(d, d in eval_days, is_last)
                    else:
                        shadow_eq[key] = sh.step_close(d)
        eq_close = reserve + eqA + eqB
        curve.append((d, eq_close))

        # ---- pot floor ----
        if eq_close >= 1.50 * start_cash:
            floor = max(floor, 1.25 * start_cash)
        elif eq_close >= 1.25 * start_cash:
            floor = max(floor, float(start_cash))
        if eq_close <= floor:
            if is_last:
                halted = d
                break
            liquidate_next = True
            continue

        # ---- ladder checks at the close ----
        if use_ladder:
            eqs = {"A": eqA, "B": eqB}
            if reset_peak_today:
                # January rebalance moved capital between sleeves; that
                # is not P&L. Reset peaks to post-rebalance equity
                # BEFORE tonight's drawdown checks.
                for key in ("A", "B"):
                    if state[key] != "BENCHED":
                        peak[key] = eqs[key]
                reset_peak_today = False
            for key in ("A", "B"):
                if state[key] == "BENCHED":
                    if (shadow_eq[key] is not None and shadow_peak[key]
                            and shadow_eq[key] >= 0.975 * shadow_peak[key]):
                        queued.append(("restore_half", key))
                    continue
                eq = eqs[key]
                pk = peak[key]
                dd = eq / pk - 1.0 if pk > 0 else 0.0
                if state[key] == "HALVED" and eq > pk:
                    queued.append(("restore_full", key))
                if dd <= -0.075:
                    queued.append(("bench", key))
                elif state[key] == "FULL" and dd <= -0.05:
                    queued.append(("halve", key))
                peak[key] = max(pk, eq)

    final = curve[-1][1] if curve else start_cash
    peak_v, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak_v = max(peak_v, eq)
        if peak_v > 0:
            maxdd = min(maxdd, eq / peak_v - 1.0)
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d")
           - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    cagr = (final / start_cash) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    yr = {}
    prev = None
    by_year = {}
    for dte, eq in curve:
        by_year[dte[:4]] = eq
    keys = sorted(by_year)
    for i, y in enumerate(keys):
        if i > 0:
            yr[y] = by_year[y] / by_year[keys[i - 1]] - 1.0
    return {
        "final": final, "cagr": cagr, "maxdd": maxdd, "curve": curve,
        "orders": A.orders + B.orders + extra_orders,
        "costs": A.costs + B.costs + extra_costs,
        "halted": halted, "counts": counts, "year_returns": yr,
        "ret_2022": yr.get("2022"), "days": days, "events": events,
    }


# ---------------------------------------------------------------- QA runs
def qa_sleeve_a():
    days = [d for d in ETF.CAL if "2016-11-21" <= d <= "2026-11-20"]
    ev = month_last_days(days)
    a = SleeveA(100.0)
    curve = []
    for di, d in enumerate(days):
        a.step_open(d)
        curve.append((d, a.step_close(d, d in ev, di == len(days) - 1)))
    peak_v, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak_v = max(peak_v, eq)
        maxdd = min(maxdd, eq / peak_v - 1.0)
    return {"final": curve[-1][1], "orders": a.orders,
            "costs": a.costs, "maxdd": maxdd}


def qa_sleeve_b():
    """Replicates chassis run_segment (single segment, $100, full window)."""
    days = [d for d in MASTER if "2016-11-21" <= d <= "2026-11-20"]
    q_firsts = quarter_first_days(MASTER)
    sel = set(q_firsts)
    sel.add(days[0])
    b = SleeveB(MKT, CHASSIS_CFG, 100.0)
    floor = 85.0
    daily = []
    liquidate = False
    halted = False
    final = None
    for di, d in enumerate(days):
        is_last = di == len(days) - 1
        if liquidate:
            b.sell_all(d)
            halted = True
            final = b.cash
            daily.append((d, final))
            break
        b.step_open(d, d in sel)
        eq_c = b.eq_close(d)
        daily.append((d, eq_c))
        if eq_c >= 150.0:
            floor = max(floor, 125.0)
        elif eq_c >= 125.0:
            floor = max(floor, 100.0)
        if eq_c <= floor:
            if is_last:
                for t in CHASSIS_CFG["universe"]:
                    if b.shares[t] > 0:
                        b._sell(t, d, b._close(t, d))
                halted = True
                final = b.cash
            else:
                liquidate = True
            if halted:
                break
            continue
        b.step_close(d)
    if not halted:
        for t in CHASSIS_CFG["universe"]:
            if b.shares[t] > 0:
                b._sell(t, days[-1], b._close(t, days[-1]))
        final = b.cash
    peak_v, maxdd = -1e18, 0.0
    for _, eq in daily:
        peak_v = max(peak_v, eq)
        maxdd = min(maxdd, eq / peak_v - 1.0)
    return {"final": final, "trades": b.orders, "costs": b.costs,
            "maxdd": maxdd}


def main():
    out = {}
    print("QA sleeve A standalone (expect final 194.61, orders 389, "
          "costs 9.17, maxDD -13.73%):")
    qa = qa_sleeve_a()
    print("  ", {k: (round(v, 2) if isinstance(v, float) else v)
                  for k, v in qa.items()})
    out["qa_sleeve_a"] = qa
    print("QA sleeve B standalone (expect final 233.54, trades 152, "
          "costs 6.47, maxDD -13.49%):")
    qb = qa_sleeve_b()
    print("  ", {k: (round(v, 2) if isinstance(v, float) else v)
                  for k, v in qb.items()})
    out["qa_sleeve_b"] = qb

    FULL = ("2016-11-21", "2026-11-20")
    VAL = ("2023-01-01", "2026-11-20")
    LAD50 = 50.0

    for label, window in (("FULL", FULL), ("VAL", VAL)):
        spy = CHA.benchmark(MKT, window[0], window[1], start_capital=100.0)
        spy50 = CHA.benchmark(MKT, window[0], window[1], start_capital=50.0)
        out[f"spy_{label}_100"] = spy
        out[f"spy_{label}_50"] = spy50
        for size in (100.0, 50.0):
            for ladder in (False, True):
                r = run_pot(window[0], window[1], size, ladder)
                key = f"{label}_{int(size)}_{'ladder' if ladder else 'plain'}"
                out[key] = {k: r[k] for k in
                            ("final", "cagr", "maxdd", "orders", "costs",
                             "halted", "counts", "ret_2022", "year_returns",
                             "events")}
                print(f"{key}: final=${r['final']:.2f} "
                      f"ret={r['final']/size-1:+.2%} CAGR={r['cagr']:+.2%} "
                      f"maxDD={r['maxdd']:.2%} orders={r['orders']} "
                      f"costs=${r['costs']:.2f} halted={r['halted']} "
                      f"2022={r['ret_2022']} counts={r['counts']}")
        print(f"SPY net {label}: $100-basis ${spy['net']:.2f} "
              f"({spy['net_pct']:+.2f}%), $50-basis ${spy50['net']:.2f}")

    with open(os.path.join(HERE, "blend-ladder-results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("Saved blend-ladder-results.json")


if __name__ == "__main__":
    main()
