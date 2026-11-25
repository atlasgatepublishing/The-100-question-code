#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — GRAND COMBINATION. Simulation only.

Strategy: equal thirds value+momentum / momentum basket / ETF trend
sleeve, January rebalance back to thirds (v5 grand-combination form).

CADENCE TREATMENT (uniform, stated once, binding for this folder):
  Cadence governs ALL THREE sleeves' re-pick / rebalance rhythms.
  Cadence dates = the first trading day of the window (initial
  deployment) plus the first trading day of each cadence period
  (daily = every trading day; weekly = first trading day of each ISO
  week; biweekly = first trading day of every second week, anchored on
  absolute Monday-ordinal parity; monthly / quarterly / semiannual /
  annual = first trading day of each month / calendar quarter /
  half-year / year). On a cadence date each sleeve re-evaluates its
  signal, re-ranks and rebalances, using its own original execution
  convention:
    - VM sleeve: selection at the cadence date's close (PIT EDGAR
      filed-before-date, 12-1 momentum at that close), rebalance at
      the NEXT trading day's open — the original engine's convention.
    - Momentum basket: signal from the prior trading day's close,
      rebalance at the cadence date's OPEN — the original convention.
    - ETF trend sleeve: its internal trend sign checks (3/6/12-month
      sign blend, >=2 of 3 positive, inverse-vol weights, 40% cap,
      20% no-trade band) are evaluated at the cadence date's CLOSE
      instead of the original monthly month-end close, trades at the
      next trading day's open — the original execution convention.
  The January split-rebalance back to thirds is the combination's own
  defining construction (not a sleeve rhythm) and stays annual in
  every cell, charged at the original transfer schedule.
  Sleeve-internal floors/ladders are DISABLED in every cell;
  protection is the adopted v9 rule at pot level only: plain -15%
  floor from the episode start balance; on first halt liquidate as
  the original blend does (next-day sleeve values x (1-0.10%) -
  $0.17 sell fees), sit in cash 90 calendar days, restart at the next
  cadence date on/after day 90 with the remaining cash split in
  thirds, episode-2 floor -15% from the restart balance; second halt
  ends the run.

INTEGRITY (run first): the three parent engines are imported
UNMODIFIED and the original published finals are reproduced in
original form: parents (basket $439.45 full-2016 $100 floor+ladder;
value+momentum plain floor $544.47 CONT / $288.05 VAL; ETF monthly
$194.61 full-2016) and the combination itself (CONT $306.56,
VAL $195.83, original blend, pot floor ends run, no restart).

SWEEP cells use cadence-parameterized copies of the three sleeve
engines (scoring, costs 0.10%/side + $0.01/sell, and execution logic
copied from the parents; the only change is the set of decision
dates, plus precomputed SMA/momentum/PIT lookups proven equivalent
to the parents' loops). Documented data artifact, never patched:
the VM price cache begins 2017-06-01 and 12-1 momentum needs 253
bars, so the VM sleeve holds cash until its first scorable selection
(~2018-06) on the decade road — the same artifact the champion's
published decade run ($65.89) carries. Its curve is carried at cash
from the window start so the pot is complete from 2016-11-21.

PLACEBOS: 20 seeds (1..20) per cell, the original combination's own
design: random picks inside the two stock sleeves (VM: rng.sample of
the scored pool; basket: rng.sample of the eligible names, rng
consumed in chronological order, one Random(seed) per twin carried
across v9 episodes), the deterministic ETF sleeve unchanged, the
identical blend + v9 machinery.

Data: parents' own caches, read-only (v4 EDGAR facts + price
payloads, v4 momentum-basket-honest-data, v3 data_etf).
Writes ONLY inside this folder: cells/<cadence>.json +
sweep_summary.json.
"""

import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from datetime import date as _date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(HERE, "..", "..")
V4 = os.path.join(BT, "v4")
V3 = os.path.join(BT, "v3")
OUT_CELLS = os.path.join(HERE, "cells")
os.makedirs(OUT_CELLS, exist_ok=True)


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load("momentum_basket_honest", os.path.join(V4, "momentum-basket-honest.py"))
vm = _load("value_momentum_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
etf = _load("etf_trend_sleeve_monthly", os.path.join(V3, "etf-trend-sleeve-monthly.py"))

POT = 100.0
THIRD = POT / 3.0
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
SEEDS = list(range(1, 21))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst


def cagr_pct(final, start, sd, ed):
    yrs = (datetime.strptime(ed, "%Y-%m-%d")
           - datetime.strptime(sd, "%Y-%m-%d")).days / 365.25
    if final <= 0:
        return -100.0
    return round(((final / start) ** (1.0 / yrs) - 1.0) * 100, 2)


# --------------------------------------------------------------------------
# Original blend (copied verbatim from v5/v9 grand-combination blend3)
# --------------------------------------------------------------------------
def blend3(curves, pot0=POT, floor=85.0):
    dicts = [dict(c) for c in curves]
    first = max(min(d) for d in dicts)
    last = min(max(d) for d in dicts)
    alldates = set()
    for d in dicts:
        alldates |= set(d)
    dates = sorted(d for d in alldates if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates = set()
    seen_jan = set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)
    scales = [1.0, 1.0, 1.0]
    lasts = [None, None, None]
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        for k in range(3):
            if d in dicts[k]:
                lasts[k] = dicts[k][d]
        vals = [scales[k] * lasts[k] for k in range(3)]
        tot = sum(vals)
        if d in jan_dates:
            target = tot / 3.0
            moved = sum(max(0.0, v - target) for v in vals)
            n_trim = sum(1 for v in vals if v > target)
            cost = moved * 0.002 + 0.05 * n_trim
            tot -= cost
            transfer_costs += cost
            target = tot / 3.0
            for k in range(3):
                scales[k] = target / lasts[k]
            rebalances.append({"date": d,
                               "sleeves_before": [round(v, 2) for v in vals],
                               "moved": round(moved, 2),
                               "cost": round(cost, 2)})
            tot = target * 3.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                nxt = 0.0
                for k in range(3):
                    v = dicts[k].get(nd, lasts[k])
                    nxt += scales[k] * v
                final = nxt * (1 - 0.001) - 0.17
            else:
                final = tot * (1 - 0.001) - 0.17
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# VM data assembly — the parent study's own assembly (v9 copy, verbatim)
# --------------------------------------------------------------------------
def build_vm_book():
    ciks = vm.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in vm.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        equity_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributable"
                          "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            vm.pit_series(facts, "dei",
                          "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap",
                          "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          prio=1))
        time.sleep(0.05)
    bars = {}
    for t in vm.UNIVERSE + ["SPY"]:
        bars[t] = vm.get_prices(t)
    return vm.PriceBook(bars), equity_rows, shares_rows, bars


# --------------------------------------------------------------------------
# Cadence dates (uniform SPEC definition; see module docstring)
# --------------------------------------------------------------------------
def cadence_dates(cal, start, end, cadence):
    days = [d for d in cal if start <= d <= end]
    if cadence == "daily":
        return days
    out = []
    seen = set()
    for d in days:
        dt = _date.fromisoformat(d)
        if cadence == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cadence == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cadence == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cadence == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cadence == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cadence == "annual":
            if d[5:7] != "01":
                continue
            key = ("A", d[:4])
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    if days and (not out or out[0] != days[0]):
        out = [days[0]] + out          # initial deployment date
    return out


# ==========================================================================
# CADENCE VM SLEEVE — scoring/execution copied from value-momentum-
# plainfloor.run_pot; PIT lookups accelerated with an exactly-equivalent
# grouped index (pit_value's sort key is (filed, prio, end): the winner
# is always a row with the maximum filed date inside the freshness
# window, tie-broken by (prio, end) — precomputed per filed date).
# ==========================================================================
class PitIndex:
    def __init__(self, rows):
        by_filed = {}
        for filed, end, val, prio in rows:
            cur = by_filed.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                by_filed[filed] = (prio, end, val)
        self.dates = sorted(by_filed)
        self.ords = [_date.fromisoformat(d).toordinal() for d in self.dates]
        self.best = [by_filed[d] for d in self.dates]

    def value(self, asof):
        ao = _date.fromisoformat(asof).toordinal()
        i = bisect_left(self.ords, ao) - 1     # filed strictly before asof
        if i < 0:
            return None
        if self.ords[i] < ao - 548:            # ~18-month freshness gate
            return None
        prio, end, val = self.best[i]
        return (self.dates[i], end, val)


class VMBook:
    def __init__(self, bars, eq_rows, sh_rows):
        self.bars = bars
        self.dates = {t: [b["d"] for b in bl] for t, bl in bars.items()}
        self.idx = {t: {b["d"]: i for i, b in enumerate(bl)}
                    for t, bl in bars.items()}
        self.eq = {t: PitIndex(r) for t, r in eq_rows.items()}
        self.sh = {t: PitIndex(r) for t, r in sh_rows.items()}
        self._pool_cache = {}

    def close_on_or_before(self, t, d):
        dl = self.dates.get(t)
        if not dl:
            return None
        i = bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

    def bar(self, t, d):
        i = self.idx.get(t, {}).get(d)
        return self.bars[t][i] if i is not None else None

    def pool(self, d):
        """(sorted scored tickers, ranked top-5) at date d, or (pool, [])
        when fewer than 5 names score — the parent engine's rule."""
        if d in self._pool_cache:
            return self._pool_cache[d]
        scores = {}
        for t in vm.UNIVERSE:
            be = self.eq[t].value(d)
            so = self.sh[t].value(d)
            px = self.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            didx = self.idx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            bl = self.bars[t]
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (be[2] / mcap, mom)
        if len(scores) >= 5:
            vr = vm.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = vm.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])[:5]
            out = (sorted(scores), picks)
        else:
            out = (sorted(scores), [])
        self._pool_cache[d] = out
        return out


def vm_sleeve(book, cal, start, end, start_cash, sel_dates,
              mode="ranked", rng=None):
    """Cadence copy of run_pot with floor/ladder disabled. Returns
    (curve, costs, orders). Curve covers every master-calendar day in
    the window (cash before the price cache begins). End-of-window
    liquidation cost is added to costs (parent accounting) but, as in
    the original blend, the curve/final are pre-liquidation closes."""
    sel_set = set(sel_dates)
    days = [d for d in cal if start <= d <= end]
    cash = float(start_cash)
    positions = {}
    trades = 0
    total_costs = 0.0
    curve = []
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = book.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    for d in days:
        if pending is not None:
            targets = pending
            pending = None
            opens = {}
            for t in set(list(positions) + list(targets)):
                b = book.bar(t, d)
                if b:
                    opens[t] = b["o"]
            for t in list(positions):
                if t not in opens:
                    continue
                cur_val = positions[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur_val > tgt + 0.005:
                    sell_val = cur_val - tgt
                    sh = sell_val / opens[t]
                    c = sell_val * 0.001 + 0.01
                    cash += sell_val - c
                    total_costs += c
                    trades += 1
                    positions[t] -= sh
                    if positions[t] < 1e-9:
                        del positions[t]
            for t, tgt in targets.items():
                if t not in opens:
                    continue
                cur_val = positions.get(t, 0.0) * opens[t]
                buy_val = tgt - cur_val
                if buy_val > 0.005:
                    buy_val = min(buy_val, cash / 1.001)
                    if buy_val <= 0.005:
                        continue
                    sh = buy_val / opens[t]
                    c = buy_val * 0.001
                    cash -= buy_val + c
                    total_costs += c
                    trades += 1
                    positions[t] = positions.get(t, 0.0) + sh
        v_close = portfolio_close(d)
        if d in sel_set:
            pool, ranked = book.pool(d)
            if len(pool) >= 5:
                if mode == "placebo":
                    picks = rng.sample(pool, 5)
                else:
                    picks = ranked
                each = v_close / 5.0
                pending = {t: each for t in picks}
        curve.append((d, v_close))
    # end-of-window liquidation cost (parent accounting only)
    if days:
        last = days[-1]
        for t in list(positions):
            c_ = book.close_on_or_before(t, last)
            if c_:
                total_costs += positions[t] * c_ * 0.001 + 0.01
                trades += 1
    return curve, total_costs, trades


# ==========================================================================
# CADENCE MOMENTUM-BASKET SLEEVE — copied from momentum-basket-honest.
# simulate; SMA200 / 12-1 momentum precomputed from the same aligned
# close arrays the parent builds (identical arithmetic).
# ==========================================================================
class MBPre:
    def __init__(self, mkt):
        self.sma200 = {}
        self.mom = {}
        for t in mb.UNIVERSE:
            closes = mkt.closes[t]
            n = len(closes)
            sma = [None] * n
            run = 0.0
            nones = 0
            for i, c in enumerate(closes):
                if c is None:
                    nones += 1
                else:
                    run += c
                if i >= 200:
                    old = closes[i - 200]
                    if old is None:
                        nones -= 1
                    else:
                        run -= old
                if i >= 199 and nones == 0:
                    sma[i] = run / 200.0
            mom = [None] * n
            for i in range(n):
                if i - 252 >= 0:
                    a, b = closes[i - 252], closes[i - 21]
                    if a is not None and b is not None and a > 0:
                        mom[i] = b / a - 1.0
            self.sma200[t] = sma
            self.mom[t] = mom
        self._elig_cache = {}

    def eligible(self, mkt, j):
        """(sorted eligible names, ranked top-5) using signal day j —
        the parent's eligibility (close > SMA200, momentum exists)."""
        if j in self._elig_cache:
            return self._elig_cache[j]
        elig = []
        for t in mb.UNIVERSE:
            s = self.sma200[t][j]
            c = mkt.closes[t][j]
            if s is None or c is None or c <= s:
                continue
            m = self.mom[t][j]
            if m is None:
                continue
            elig.append((t, m))
        ranked = [t for t, _ in sorted(elig, key=lambda x: -x[1])[:5]]
        out = (sorted(t for t, _ in elig), ranked)
        self._elig_cache[j] = out
        return out


def mb_sleeve(mkt, pre, start, end, start_cash, sel_dates,
              mode="ranked", rng=None):
    """Cadence copy of simulate() with floor/ladder disabled (the
    parent's FLOORS entry for a sleeve third is (0.0, []) in the
    original combination). Returns (curve, costs, orders)."""
    sel_set = set(sel_dates)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end)
    cash = float(start_cash)
    pos = {}
    orders = 0
    costs = 0.0
    curve = []

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
        if d in sel_set and i > 0:
            names, ranked = pre.eligible(mkt, i - 1)
            if mode == "placebo":
                picks = rng.sample(names, min(5, len(names))) if names else []
            else:
                picks = ranked
            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * 0.001 + 0.01
                    cash += sell_val - fee
                    costs += fee
                    orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + 0.001))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * 0.001
                cash -= buy_val + fee
                costs += fee
                orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
        curve.append((d, equity_at(i, use_open=False)))
    return curve, costs, orders


# ==========================================================================
# CADENCE ETF TREND SLEEVE — copied from etf-trend-sleeve-monthly.
# simulate; trend/vol computed from forward-filled aligned close
# arrays identical to the parent's closes_window/close_on values.
# Only the evaluation-date set changes (cadence dates, see docstring).
# ==========================================================================
class ETFBook:
    def __init__(self):
        self.cal = etf.CAL
        self.idx = etf.CAL_IDX
        self.close = {}
        self.open = {}
        for t in etf.ASSETS:
            closes, opens = [], []
            last = None
            for d in self.cal:
                if d in etf.SERIES[t]:
                    last = etf.SERIES[t][d][1]
                    opens.append(etf.SERIES[t][d][0])
                else:
                    opens.append(last)
                closes.append(last)
            self.close[t] = closes
            self.open[t] = opens

    def trend_vol(self, t, i):
        if i < 252:
            return None
        closes = self.close[t]
        last = closes[i]
        if last is None:
            return None
        npos = 0
        for lag in (63, 126, 252):
            r = last / closes[i - lag] - 1.0
            if r > 0:
                npos += 1
        rets = [closes[k] / closes[k - 1] - 1.0
                for k in range(i - 19, i + 1)]
        vol = statistics.pstdev(rets) if len(rets) >= 20 else None
        return npos, vol


def etf_sleeve(book, start, end, start_cash, sel_dates):
    days = [d for d in book.cal if start <= d <= end]
    eval_set = set(sel_dates)
    cash = float(start_cash)
    shares = {t: 0.0 for t in etf.ASSETS}
    orders = 0
    total_costs = 0.0
    curve = []
    pending = None

    def equity_at(i, use_open):
        eq = cash
        arr = book.open if use_open else book.close
        for t in etf.ASSETS:
            if shares[t] > 0:
                p = arr[t][i]
                if p:
                    eq += shares[t] * p
        return eq

    for di, d in enumerate(days):
        i = book.idx[d]
        if pending is not None:
            trade_set, targets = pending
            eq_open = equity_at(i, use_open=True)
            for t in sorted(trade_set):
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * book.open[t][i]
                diff = cur_val - tgt_val
                if diff > 0.01 and shares[t] > 0:
                    sell_val = min(diff, cur_val)
                    sh = sell_val / book.open[t][i]
                    cost = sell_val * 0.001 + 0.01
                    cash += sell_val - cost
                    shares[t] -= sh
                    if shares[t] < 1e-9:
                        shares[t] = 0.0
                    orders += 1
                    total_costs += cost
            buy_list = []
            for t in sorted(trade_set):
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * book.open[t][i]
                diff = tgt_val - cur_val
                if diff > 0.01:
                    buy_list.append((t, diff))
            tot_buy = sum(v for _, v in buy_list)
            if tot_buy > 0:
                scale = min(1.0, cash / (tot_buy * 1.001))
                for t, diff in buy_list:
                    buy_val = diff * scale
                    if buy_val < 0.01:
                        continue
                    cost = buy_val * 0.001
                    cash -= buy_val + cost
                    shares[t] += buy_val / book.open[t][i]
                    orders += 1
                    total_costs += cost
            pending = None
        eq_close = equity_at(i, use_open=False)
        curve.append((d, eq_close))
        if d in eval_set and di + 1 < len(days):
            vols = {}
            for t in etf.ASSETS:
                tv = book.trend_vol(t, i)
                if tv is None:
                    continue
                npos, vol = tv
                if npos >= 2 and vol:
                    vols[t] = vol
            targets = etf.capped_inv_vol_weights(vols)
            trade_set = set()
            for t in etf.ASSETS:
                cur_w = (shares[t] * book.close[t][i] / eq_close) \
                    if eq_close > 0 else 0.0
                tgt_w = targets.get(t, 0.0)
                held = shares[t] > 0
                if held and tgt_w == 0.0:
                    trade_set.add(t)
                elif not held and tgt_w > 0.0:
                    trade_set.add(t)
                elif held and tgt_w > 0.0:
                    if abs(tgt_w - cur_w) / tgt_w > 0.20:
                        trade_set.add(t)
            if trade_set:
                pending = (trade_set, targets)
    return curve, total_costs, orders


# ==========================================================================
# v9 combination wrapper (cadence form of the v9 module): episode 1
# blend under plain -15% floor; on halt, cash 90 days, restart at the
# next cadence date on/after day 90; episode-2 floor -15% from the
# restart balance; second halt ends the run.
# ==========================================================================
_ETF_CACHE = {}


def combo_v9(mkt, pre, book, etfbook, cadence, start, end,
             start_cash=100.0, mode="ranked", seed=None):
    rng_vm = random.Random(seed) if mode == "placebo" else None
    rng_mb = random.Random(seed) if mode == "placebo" else None

    def run_episode(sd, ed, cash):
        third = cash / 3.0
        sel_m = cadence_dates(mkt.cal, sd, ed, cadence)
        sel_e = cadence_dates(etfbook.cal, sd, ed, cadence)
        c_vm, co_vm, o_vm = vm_sleeve(book, mkt.cal, sd, ed, third,
                                      sel_m, mode, rng_vm)
        c_mb, co_mb, o_mb = mb_sleeve(mkt, pre, sd, ed, third,
                                      sel_m, mode, rng_mb)
        # the ETF sleeve is deterministic and identical across placebo
        # twins — compute once per (cadence, window, stake)
        key = (cadence, sd, ed, round(third, 4))
        if key not in _ETF_CACHE:
            _ETF_CACHE[key] = etf_sleeve(etfbook, sd, ed, third, sel_e)
        c_et, co_et, o_et = _ETF_CACHE[key]
        curves = [c_vm, c_mb, c_et]
        floor = round(0.85 * cash, 2)
        curve, info = blend3(curves, pot0=cash, floor=floor)
        return curve, info, curves, (co_vm + co_mb + co_et), \
            (o_vm + o_mb + o_et), floor

    curve1, info1, curves1, costs1, orders1, floor1 = \
        run_episode(start, end, start_cash)
    out = {"final": info1["final"], "curve": list(curve1),
           "halts": [], "restarts": [], "second_halt": None,
           "costs": costs1 + info1["transfer_costs"],
           "orders": orders1,
           "transfer_costs": info1["transfer_costs"]}
    if info1["halt"] is None:
        return out
    all_dates = sorted(set(d for c in curves1 for d, _ in c))
    liq_date = next(d for d in all_dates if d > info1["halt"])
    cash = info1["final"]
    out["halts"].append({
        "episode": 1, "signal_date": info1["halt"],
        "signal_close": round(dict(curve1)[info1["halt"]], 2),
        "floor_in_effect": floor1, "liquidation_date": liq_date,
        "liquidation_final": round(cash, 2)})
    day90 = _date.fromisoformat(liq_date).toordinal() + 90
    restart = None
    for cand in cadence_dates(mkt.cal, start, end, cadence):
        if _date.fromisoformat(cand).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in all_dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": info1["halt"], "liquidation_date": liq_date,
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    curve2, info2, _, costs2, orders2, _ = run_episode(restart, end, cash)
    out["final"] = info2["final"]
    out["curve"] += list(curve2)
    out["costs"] += costs2 + info2["transfer_costs"]
    out["orders"] += orders2
    out["transfer_costs"] += info2["transfer_costs"]
    if info2["halt"] is not None:
        out["second_halt"] = {
            "episode": 2, "signal_date": info2["halt"],
            "signal_close": round(dict(curve2)[info2["halt"]], 2),
            "floor_in_effect": floor2,
            "liquidation_final": round(info2["final"], 2)}
        out["halts"].append(dict(out["second_halt"]))
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ==========================================================================
# INTEGRITY — original engines unmodified, original form
# ==========================================================================
def integrity(mkt, pb, eq_rows, sh_rows):
    res = {}
    # parent 1: momentum basket, original floor+ladder, full 2016 window
    r = mb.simulate(mkt, "2016-11-21", "2026-11-20", 100, "ranked")
    res["momentum_basket_full2016"] = round(r.final, 2)
    print(f"INTEGRITY basket original: ${r.final:.2f} (published 439.45)",
          flush=True)
    # parent 2: value+momentum plain floor
    for name, sd, ed, pub in (("continuous", "2019-01-02", "2026-11-20", 544.47),
                              ("validation", "2023-01-03", "2026-11-20", 288.05)):
        r = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, 100.0, 85.0, [],
                       quiet=True)
        res[f"value_momentum_{name}"] = round(r["final"], 2)
        print(f"INTEGRITY VM {name}: ${r['final']:.2f} (published {pub})",
              flush=True)
    # parent 3: ETF trend sleeve monthly, original floor+ladder
    r = etf.simulate("2016-11-21", "2026-11-20")
    res["etf_monthly_full2016"] = round(r["final"], 2)
    print(f"INTEGRITY ETF monthly original: ${r['final']:.2f} "
          f"(published 194.61)", flush=True)
    # the combination in original form (blend3, pot floor ends the run)
    mb.FLOORS[THIRD] = (0.0, [])
    combo = {}
    for name, sd, ed in (("continuous", "2019-01-01", "2026-11-20"),
                         ("validation", "2023-01-01", "2026-11-20")):
        r_vm = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, THIRD, 0.0, [],
                          quiet=True)
        r_mb = mb.simulate(mkt, sd, ed, THIRD, "ranked")
        r_et = etf.simulate(sd, ed, start_cash=THIRD, floor0=0.0, ladder=())
        _, info = blend3([r_vm["curve"], r_mb.equity_curve, r_et["curve"]],
                         pot0=POT, floor=85.0)
        combo[name] = round(info["final"], 2)
        print(f"INTEGRITY combo {name}: ${info['final']:.2f} "
              f"halt={info['halt']}", flush=True)
    res["combination"] = combo
    ok = (abs(res["momentum_basket_full2016"] - 439.45) < 0.02 and
          abs(res["value_momentum_continuous"] - 544.47) < 0.02 and
          abs(res["value_momentum_validation"] - 288.05) < 0.02 and
          abs(res["etf_monthly_full2016"] - 194.61) < 0.02 and
          abs(combo["continuous"] - 306.56) < 0.02 and
          abs(combo["validation"] - 195.83) < 0.02)
    res["all_match"] = ok
    return res


def main():
    t0 = time.time()
    print("loading basket market (cache)...", flush=True)
    mkt = mb.Market(mb.UNIVERSE)
    print("loading VM book (cache)...", flush=True)
    pb, eq_rows, sh_rows, bars = build_vm_book()
    integ = integrity(mkt, pb, eq_rows, sh_rows)
    print(f"INTEGRITY all_match={integ['all_match']}", flush=True)
    if not integ["all_match"]:
        print("INTEGRITY FAILED — sweep still run, flagged in outputs",
              flush=True)

    book = VMBook(bars, eq_rows, sh_rows)
    pre = MBPre(mkt)
    etfbook = ETFBook()
    sd, ed = DECADE
    summary = {"slug": "grand-combination", "integrity_detail": integ,
               "cells": {}}
    for cadence in CADENCES:
        r = combo_v9(mkt, pre, book, etfbook, cadence, sd, ed)
        twins = []
        for seed in SEEDS:
            t = combo_v9(mkt, pre, book, etfbook, cadence, sd, ed,
                         mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": round(t["final"], 2)})
            if seed % 5 == 0:
                print(f"  {cadence} twins {seed}/20 "
                      f"({time.time()-t0:.0f}s)", flush=True)
        beats = sum(1 for t in twins if r["final"] > t["final"])
        cell = {
            "cadence": cadence, "start": sd, "end": ed,
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], POT, sd, ed),
            "max_dd_pct": round(max_dd(r["curve"]) * 100, 2),
            "costs": round(r["costs"], 2),
            "transfer_costs": round(r["transfer_costs"], 2),
            "orders": r["orders"],
            "halts": r["halts"], "restarts": r["restarts"],
            "second_halt": r["second_halt"],
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "placebo_twins": twins,
            "placebo_beaten": beats,
        }
        with open(os.path.join(OUT_CELLS, f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        summary["cells"][cadence] = {
            k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                 "costs", "orders", "placebo_beaten")}
        summary["cells"][cadence]["halts"] = cell["halts"]
        summary["cells"][cadence]["restarts"] = cell["restarts"]
        summary["cells"][cadence]["second_halt"] = cell["second_halt"]
        print(f"CELL {cadence}: final=${r['final']:.2f} "
              f"DD={cell['max_dd_pct']}% costs=${r['costs']:.2f} "
              f"orders={r['orders']} halts={len(r['halts'])} "
              f"placebo {beats}/20  ({time.time()-t0:.0f}s)", flush=True)
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
