#!/usr/bin/env python3
"""
MOMENTUM BASKET — SURVIVORSHIP-HONEST RE-TEST — Terry's AI stock app,
simulation only.

Identical rule and engine to momentum-basket.py; the ONLY change is the
universe. The original 20 names were chosen with 2026 hindsight. This
universe is the 30 largest US-listed companies by market cap as of
November 2016, from 2016 knowledge only — it deliberately includes names
that later lagged or stumbled (GE, IBM, INTC, XOM's lost years, T, PFE).

Rule (frozen, unchanged from momentum-basket.py):
  Universe (30 names, Nov-2016 top-30 by market cap): AAPL MSFT AMZN GOOGL
    META BRK-B JPM XOM JNJ PG V WMT HD BAC CVX PFE VZ T DIS NFLX INTC CSCO
    GE IBM MMM UNH MA KO PEP WFC
    (META = Facebook, ticker FB in 2016; BRK-B = Berkshire Hathaway B.)
  Monthly selection on the first trading day of each month, using data
  through the PRIOR trading day's close (no look-ahead):
    - Eligible: name's close above its own 200-day simple moving average.
    - Rank eligible names by trailing 12-1 month momentum:
      close[t-21] / close[t-252] - 1  (skip the most recent month).
    - Hold the TOP 5, equal weight at 20% of pot equity each.
      Fewer than 5 eligible -> hold what's eligible at 20% each, rest cash.
    - Rebalance at the selection day's OPEN to the target weights
      (names that drop out or become ineligible are sold in full).
  Costs: 0.10% of trade value per side + $0.01 per sell order.
  Terry's floor, active at both pot sizes:
    $100 pot: floor $85; ladder -> $100 at a $125 close, -> $125 at $150.
    $50  pot: floor $42.50; ladder -> $50 at a $62.50 close, -> $62.50 at $75.
    Closing equity at/below floor -> liquidate everything at next open, run ends.

Runs:
  (A) Full continuous 2016-11-21 -> 2026-11-20, both sizes, per-year table.
  (B) DESIGN 2016-11-21 -> 2022-12-31 vs VALIDATION 2023-01-01 -> 2026-11-20,
      fresh pots, both sizes.
  (C) PLACEBO on validation AND full window: each month pick 5 RANDOM
      eligible names, identical machinery — TWENTY seeds (1..20); the
      ranked basket is judged against the placebo distribution.
Benchmark: SPY buy-and-hold, net of the same costs, per window.

Data: Yahoo Finance chart API daily bars (split-adjusted closes), fetched
2015-01-01 -> 2026-11-20, cached under ./momentum-basket-honest-data/.
"""

import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "momentum-basket-honest-data")
os.makedirs(CACHE, exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
FETCH_START = "2015-01-01"
FETCH_END = "2026-11-21"          # exclusive-ish; last bar wanted 2026-11-20
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order

WINDOWS = {
    "full":       ("2016-11-21", "2026-11-20"),
    "design":     ("2016-11-21", "2022-12-31"),
    "validation": ("2023-01-01", "2026-11-20"),
}

# floor config per starting pot: (floor0, [(close_threshold, new_floor), ...])
FLOORS = {
    100: (85.0,  [(125.0, 100.0), (150.0, 125.0)]),
    50:  (42.50, [(62.50, 50.0),  (75.0, 62.50)]),
}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append({"d": d, "o": float(o), "c": float(c)})
    with open(path, "w") as f:
        json.dump(rows, f)
    time.sleep(0.3)
    return rows


class Market:
    """SPY calendar is the master calendar; per-ticker bars keyed by date."""

    def __init__(self, tickers):
        self.bars = {}          # ticker -> {date: (open, close)}
        self.closes = {}        # ticker -> list of closes aligned to calendar
        spy = fetch(BENCH)
        self.cal = [r["d"] for r in spy]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        all_t = tickers + [BENCH]
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = fetch(t)
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
# Simulation
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
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
    floor0, ladder = FLOORS[pot0]
    floor = floor0
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
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        # --- monthly selection / rebalance at the open -------------------
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
            if i == i1:      # no next open inside window: liquidate at close
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


def cagr(final, start, years):
    if final <= 0 or start <= 0:
        return float("nan")
    return (final / start) ** (1.0 / years) - 1.0


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def per_year(res, pot0):
    """Year-by-year returns from an equity curve; first (stub) year is
    measured from the starting pot."""
    out = {}
    years = sorted({d[:4] for d, _ in res.equity_curve})
    prev_eq = float(pot0)
    for y in years:
        pts = [e for d, e in res.equity_curve if d[:4] == y]
        if not pts:
            continue
        end_eq = pts[-1]
        out[y] = end_eq / prev_eq - 1.0
        prev_eq = end_eq
    return out


def spy_year_returns(mkt, start_d, end_d):
    yrs = {}
    idx = [i for i, d in enumerate(mkt.cal) if start_d <= d <= end_d]
    prev = mkt.close_px(BENCH, idx[0] - 1) if idx and idx[0] > 0 else None
    for i in idx:
        y = mkt.cal[i][:4]
        c = mkt.close_px(BENCH, i)
        if y not in yrs:
            yrs[y] = [prev, c]
        yrs[y][1] = c
        prev = c
    return {y: (v[1] / v[0] - 1.0 if v[0] else None) for y, v in yrs.items()}


PLACEBO_SEEDS = list(range(1, 21))          # twenty seeds: 1..20


def _summ(r, pot, yrs, bench):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / pot - 1) * 100, 2),
        "cagr_pct": round(cagr(r.final, pot, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "halt": r.halt_date,
        "sel_win_pct": (round(100 * r.sel_wins / r.sel_total, 1)
                        if r.sel_total else None),
        "sel_n": r.sel_total,
        "month_win_pct": (round(100 * r.month_wins / r.months, 1)
                          if r.months else None),
        "bench_final": round(bench, 2),
        "bench_ret_pct": round((bench / pot - 1) * 100, 2),
    }


def _pct(sorted_vals, q):
    """Percentile with linear interpolation (numpy 'linear' method)."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def main():
    mkt = Market(UNIVERSE)
    all_out = {"universe": UNIVERSE, "placebo_seeds": PLACEBO_SEEDS}
    ranked_final = {}       # (window, pot) -> final, for percentile placement

    # ---- ranked runs: all three windows, both pots ----------------------
    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        for pot in (100, 50):
            bench = spy_net(mkt, sd, ed, pot)
            r = simulate(mkt, sd, ed, pot, "ranked")
            key = f"{wname}|{pot}|ranked"
            all_out[key] = _summ(r, pot, yrs, bench)
            ranked_final[(wname, pot)] = r.final
            print(f"{key}: final={r.final:.2f} ret={(r.final/pot-1)*100:+.2f}% "
                  f"orders={r.orders} costs=${r.costs:.2f} "
                  f"maxDD={r.max_dd*100:.2f}% halt={r.halt_date} "
                  f"SPYnet={bench:.2f}", flush=True)

    # ---- placebo distribution: 20 seeds, full + validation ------------
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        yrs = years_between(sd, ed)
        for pot in (100, 50):
            bench = spy_net(mkt, sd, ed, pot)
            finals, rows = [], []
            for seed in PLACEBO_SEEDS:
                r = simulate(mkt, sd, ed, pot, "placebo", seed=seed)
                finals.append(r.final)
                rows.append({
                    "seed": seed,
                    "final": round(r.final, 2),
                    "ret_pct": round((r.final / pot - 1) * 100, 2),
                    "max_dd_pct": round(r.max_dd * 100, 2),
                    "halt": r.halt_date,
                    "orders": r.orders,
                    "costs": round(r.costs, 2),
                })
            sfin = sorted(finals)
            rk = ranked_final[(wname, pot)]
            n_beat = sum(1 for v in finals if rk > v)
            dist = {
                "n_seeds": len(finals),
                "median_final": round(_pct(sfin, 0.50), 2),
                "p25_final": round(_pct(sfin, 0.25), 2),
                "p75_final": round(_pct(sfin, 0.75), 2),
                "best_final": round(sfin[-1], 2),
                "worst_final": round(sfin[0], 2),
                "median_ret_pct": round((_pct(sfin, 0.50) / pot - 1) * 100, 2),
                "n_halted": sum(1 for row in rows if row["halt"]),
                "ranked_final": round(rk, 2),
                "ranked_minus_median": round(rk - _pct(sfin, 0.50), 2),
                "ranked_beats_n_of_20": n_beat,
                "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
                "bench_final": round(bench, 2),
                "rows": rows,
            }
            all_out[f"{wname}|{pot}|placebo_dist"] = dist
            print(f"{wname}|{pot}|placebo_dist: median={dist['median_final']:.2f} "
                  f"p25={dist['p25_final']:.2f} p75={dist['p75_final']:.2f} "
                  f"best={dist['best_final']:.2f} worst={dist['worst_final']:.2f} "
                  f"ranked={rk:.2f} beats {n_beat}/20 halted={dist['n_halted']}",
                  flush=True)

    # ---- per-year table for the full-window ranked runs -----------------
    yearly = {}
    for pot in (100, 50):
        r = simulate(mkt, *WINDOWS["full"], pot, "ranked")
        yearly[f"pot{pot}"] = {y: round(v * 100, 2)
                               for y, v in per_year(r, pot).items()}
    spy_yrs = {y: (round(v * 100, 2) if v is not None else None)
               for y, v in spy_year_returns(mkt, *WINDOWS["full"]).items()}
    all_out["per_year_ranked"] = yearly
    all_out["per_year_spy"] = spy_yrs
    with open(os.path.join(HERE, "momentum-basket-honest-results.json"),
              "w") as f:
        json.dump(all_out, f, indent=1)
    print("saved momentum-basket-honest-results.json")


if __name__ == "__main__":
    main()
