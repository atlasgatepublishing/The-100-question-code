#!/usr/bin/env python3
"""
Momentum basket — the v9 engine, verbatim, on long-run data plumbing.

simulate(), Result and spy_net() below are copied CHARACTER-FOR-CHARACTER
from backtests/v9-muse-rules/momentum-basket/momentum-basket-honest-v9.py
(the adopted-rules form of backtests/v4/momentum-basket-honest.py),
including its in-engine v9 protection: plain -15% floor per episode, no
ladder; first halt -> liquidate at next open, sit out 90 calendar days,
restart at the next monthly selection day under an episode-2 floor of
-15% from the restart balance; second halt ends the run.

The ONLY changes are plumbing, of the same kind the program's own
scripts make when they change data source:
  - Market is built from bars supplied by the caller (the long-hold
    test's fresh Yahoo pulls, raw open/close — this engine's own bar
    convention) instead of fetch()ing the v4 cache (which starts 2015).
  - UNIVERSE is set by the caller (the point-in-time pond).
Phase 0 (phase0_checks.py) proves this copy reproduces the published
$439.45 / $208.27 on the published windows before any long run is taken.
"""
import random
from datetime import datetime

COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order
UNIVERSE = []                     # set by the caller (the pond)
BENCH = "SPY"


class Market:
    """SPY calendar is the master calendar; per-ticker bars keyed by date.
    Identical construction to the original Market, fed from supplied bars."""

    def __init__(self, bars_by_ticker):
        self.bars = {}          # ticker -> {date: (open, close)}
        self.closes = {}        # ticker -> list of closes aligned to calendar
        spy = bars_by_ticker[BENCH]
        self.cal = [r["d"] for r in spy]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        all_t = list(bars_by_ticker)
        raw = bars_by_ticker
        for t in all_t:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)          # forward-fill closes for valuation
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        """SMA of closes ending at index i (inclusive); None if not enough."""
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        """12-1 month momentum using closes at index i: c[i-21]/c[i-252]-1."""
        if i - 252 < 0:
            return None
        a, b = self.closes[t][i - 252], self.closes[t][i - 21]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0


# --------------------------------------------------------------------------
# Simulation (verbatim from momentum-basket-honest-v9.py)
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.halts = []              # V9: every liquidation date
        self.restarts = []           # V9: {halt_date, restart_date, restart_balance, episode2_floor}
        self.max_dd = 0.0
        self.equity_curve = []       # (date, equity)
        self.sel_total = 0           # name-month selections scored
        self.sel_wins = 0
        self.months = 0
        self.month_wins = 0
        self.month_rets = []


def simulate(mkt, start_d, end_d, pot0, mode, seed=42):
    """mode: 'ranked' (momentum top 5) or 'placebo' (random 5 eligible)."""
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    # V9 PROTECTION: plain -15% floor per episode, no ladder.
    ladder = []
    episode = 1
    floor = 0.85 * float(pot0)
    sitout_restart_idx = None        # calendar index of the restart selection day
    cash = float(pot0)
    pos = {}                       # ticker -> shares
    res = Result()
    pending_liquidation = False
    # per-name mark price at the last rebalance, for name-month win scoring
    mark_px = {}
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

        # --- floor liquidation at the open -------------------------------
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                if t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.halts.append(d)
            res.equity_curve.append((d, cash))
            pending_liquidation = False
            # V9: first halt -> 90 calendar days in cash, restart at the
            # next monthly selection day (first trading day of a month).
            if episode == 1:
                from datetime import date as _date, timedelta as _td
                _y, _m, _dd = (int(x) for x in d.split("-"))
                earliest = (_date(_y, _m, _dd) + _td(days=90)).isoformat()
                ridx = None
                for j in range(i + 1, i1 + 1):
                    if mkt.cal[j] >= earliest and mkt.cal[j][:7] != mkt.cal[j - 1][:7]:
                        ridx = j
                        break
                if ridx is not None:
                    sitout_restart_idx = ridx
                    episode = 2
                    res.restarts.append({
                        "halt_date": d,
                        "restart_date": mkt.cal[ridx],
                        "restart_balance": round(cash, 2),
                        "episode2_floor": round(0.85 * cash, 2),
                    })
                    floor = 0.85 * cash
                    continue
            res.final = cash
            break

        # --- monthly selection / rebalance at the open -------------------
        if sitout_restart_idx is not None and i < sitout_restart_idx:
            eq_close = cash
            res.equity_curve.append((d, eq_close))
            continue
        if sitout_restart_idx is not None and i == sitout_restart_idx:
            sitout_restart_idx = None
            cur_month = None         # force the restart selection today
        if month_key != cur_month and i > 0:
            cur_month = month_key
            # score last month's held names at today's open vs last mark
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1                       # signal day = prior trading day
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:  # placebo: random 5 of the eligible, deterministic order
                names = sorted(t for t, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}

            # sells first: names not picked, then trims
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            # buys
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            # reset marks for everything held after this rebalance
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        # --- close: equity, ladder, floor --------------------------------
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:      # V9: no next open (and no restart day) inside window: liquidate at close, run ends
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    # max drawdown from the equity curve
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    # month-over-month win rate: last equity of each calendar month
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        res.month_rets.append(r)
        if r > 0:
            res.month_wins += 1
    return res


def spy_net(mkt, start_d, end_d, pot0):
    """SPY buy-and-hold net of the same costs."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px(BENCH, i0)
    sell_px = mkt.close_px(BENCH, i1)
    sh = (pot0 * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE
