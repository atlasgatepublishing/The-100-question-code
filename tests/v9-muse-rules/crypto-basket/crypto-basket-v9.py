#!/usr/bin/env python3
"""
MOMENTUM BASKET ON CRYPTO — Terry's AI stock app, simulation only.

Literally the same test as the stock program's leading strategy
(momentum-basket-honest.py) with a different market underneath. Terry's
question: same rules, crypto instead of stocks — any difference?

Rule (identical architecture to momentum-basket-honest.py):
  Monthly selection on the first day of each month, using data through
  the PRIOR day's close (no look-ahead):
    - Eligible: coin's close above its own 200-day simple moving average.
    - Rank eligible coins by trailing 12-1 month momentum.
    - Hold the TOP 5, equal weight at 20% of pot equity each.
      Fewer than 5 eligible -> hold what's eligible at 20% each, rest cash.
    - Rebalance at the selection day's OPEN to the target weights.
  Full compounding (positions sized off current pot equity).

Calendar translation (the ONLY mechanical change, documented): stocks
trade ~252 days/yr, crypto trades 365. The stock script measures the
200-day average over 200 bars and 12-1 momentum as close[t-21] /
close[t-252] (trading days ~ 1 and 12 calendar months). Here bars are
calendar days, so the same economic definitions are 200 bars for the
average and close[t-30] / close[t-365] for 12-1 momentum.

Universe (20 coins, finalized from Yahoo data availability — every one
has uninterrupted daily bars through the whole window and enough
history before 2020-06-01 for the 12-1 lookback):
  BTC ETH XRP BNB ADA DOGE LTC BCH LINK XLM TRX ETC XMR EOS DASH ZEC
  NEO XTZ VET ATOM
Excluded, documented: DOT (Yahoo history starts 2020-08-20 — no data at
window start, no lookback; the brief anticipated this), SOL (starts
2020-04-10 — fails the traded-since-2020-01-01 rule and has no 12-1
lookback until 2021), FIL (Yahoo shows pre-2018 bars but Filecoin
mainnet launched Oct 2020 — pre-launch bars are not credible traded
prices), AAVE/UNI/COMP (start late 2020 / no clean series), ALGO/THETA/
MKR/KSM (smaller; cut at 20 names).

*** SURVIVORSHIP WARNING ***
This list was built TODAY of coins that survived 2020 -> 2026. The dead
are not in it: LUNA/UST (a top-5 coin that went to ~zero in May 2022),
FTT, and hundreds of smaller coins that traded in 2020 and are gone.
A trader in June 2020 could not have known these 20 would be the
survivors. Every number from this test is survivorship-flattered by
construction. It answers "do the rules work on surviving major coins,"
NOT "would this have made money starting in 2020."

Costs: 0.25% of trade value per side (no per-order fee).
Pot: $100.
Floor, two variants:
  (a) "ladder": Terry's stock-program floor+ladder — floor $85; ladder
      -> $100 at a $125 close, -> $125 at a $150 close.
  (b) "plain": plain -15% floor — $85 forever.
  Closing equity at/below floor -> liquidate everything at next open.

Runs:
  Ranked: FULL 2020-06-01 -> 2026-11-20, DESIGN 2020-06-01 -> 2022-12-31,
    VALIDATION 2023-01-01 -> 2026-11-20, both floor variants.
  Placebo: 20 seeds (random 5 eligible monthly, identical machinery),
    FULL + VALIDATION, both floor variants; ranked judged against the
    distribution.
  Diagnostic (NOT part of the frozen rule): ranked with the 200-day
    eligibility filter REMOVED (rank everything by momentum, top 5),
    plain floor, FULL + VALIDATION — isolates what the filter does.
Benchmarks: BTC buy-and-hold net of the same costs; equal-weight
buy-and-hold of the whole 20-coin universe, net of the same costs.

Data: Yahoo Finance chart API daily bars (e.g. BTC-USD), fetched
2018-01-01 -> 2026-11-20, cached under ./crypto-basket-data/.
"""

import json
import math
import os
import random
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "v4"))
CACHE = os.path.join(ORIG_DIR, "crypto-basket-data")  # original cache, read-only
os.makedirs(CACHE, exist_ok=True)

UNIVERSE = ["BTC", "ETH", "XRP", "BNB", "ADA", "DOGE", "LTC", "BCH",
            "LINK", "XLM", "TRX", "ETC", "XMR", "EOS", "DASH", "ZEC",
            "NEO", "XTZ", "VET", "ATOM"]
CAL_TICKER = "BTC"
COST_RATE = 0.0025                # 0.25% per side
SELL_FEE = 0.0                    # no per-order fee in the crypto spec

SMA_N = 200
MOM_FAR = 365                     # ~12 months of calendar days
MOM_NEAR = 30                     # skip the most recent ~month

WINDOWS = {
    "full":       ("2020-06-01", "2026-11-20"),
    "design":     ("2020-06-01", "2022-12-31"),
    "validation": ("2023-01-01", "2026-11-20"),
}

FLOOR_VARIANTS = {
    "ladder": (85.0, [(125.0, 100.0), (150.0, 125.0)]),
    "plain":  (85.0, []),
}
POT = 100


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}-USD"
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
    """BTC calendar is the master calendar (crypto trades every day);
    per-coin bars keyed by date, closes forward-filled for valuation."""

    def __init__(self, tickers):
        self.bars = {}
        self.closes = {}
        cal_raw = fetch(CAL_TICKER)
        self.cal = [r["d"] for r in cal_raw]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        raw = {CAL_TICKER: cal_raw}
        for t in tickers:
            if t != CAL_TICKER:
                raw[t] = fetch(t)
        for t in tickers:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        """12-1 momentum at index i: c[i-30]/c[i-365]-1 (calendar days)."""
        if i - MOM_FAR < 0:
            return None
        a, b = self.closes[t][i - MOM_FAR], self.closes[t][i - MOM_NEAR]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0


# --------------------------------------------------------------------------
# Simulation — same engine shape as momentum-basket-honest.py
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.equity_curve = []
        self.sel_total = 0
        self.sel_wins = 0
        self.months = 0
        self.month_wins = 0
        self.month_rets = []
        self.elig_sum = 0            # eligibility diagnostics
        self.elig_months = 0
        self.invested_sum = 0.0      # mean fraction of equity targeted


def simulate(mkt, start_d, end_d, mode, seed=42, floor_variant="ladder",
             use_filter=True, start_cash=None, floor_abs=None):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = FLOOR_VARIANTS[floor_variant]
    if floor_abs is not None:
        floor0 = float(floor_abs)   # v9 episode-2 floor (plain variant only)
        ladder = []
    floor = floor0
    cash = float(POT) if start_cash is None else float(start_cash)
    pos = {}
    res = Result()
    pending_liquidation = False
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

        if month_key != cur_month and i > 0:
            cur_month = month_key
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1
            elig = []
            for t in UNIVERSE:
                c = mkt.close_px(t, j)
                if c is None:
                    continue
                if use_filter:
                    sma200 = mkt.sma(t, j, SMA_N)
                    if sma200 is None or c <= sma200:
                        continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            res.elig_sum += len(elig)
            res.elig_months += 1
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:
                names = sorted(t for t, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            res.invested_sum += 0.20 * len(picks)

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
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
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
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
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
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
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


# --------------------------------------------------------------------------
# Benchmarks
# --------------------------------------------------------------------------
def btc_net(mkt, start_d, end_d):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px("BTC", i0)
    sell_px = mkt.close_px("BTC", i1)
    sh = (POT * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE


def ew_net(mkt, start_d, end_d):
    """Equal-weight buy-hold of the whole universe, net of costs."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    per = POT / len(UNIVERSE)
    tot = 0.0
    for t in UNIVERSE:
        buy_px = mkt.open_px(t, i0)
        sell_px = mkt.close_px(t, i1)
        if buy_px is None or sell_px is None:
            tot += per
            continue
        sh = (per * (1 - COST_RATE)) / buy_px
        tot += sh * sell_px * (1 - COST_RATE) - SELL_FEE
    return tot


def bench_dd(mkt, start_d, end_d, which):
    """Max drawdown of a buy-hold benchmark's daily equity curve."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    if which == "btc":
        sh = (POT * (1 - COST_RATE)) / mkt.open_px("BTC", i0)
        curve = [sh * mkt.close_px("BTC", i) for i in range(i0, i1 + 1)]
    else:
        per = POT / len(UNIVERSE)
        shares = {}
        for t in UNIVERSE:
            px = mkt.open_px(t, i0)
            shares[t] = (per * (1 - COST_RATE)) / px if px else 0.0
        curve = [sum(shares[t] * (mkt.close_px(t, i) or 0)
                     for t in UNIVERSE) for i in range(i0, i1 + 1)]
    peak, dd = -1.0, 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = min(dd, v / peak - 1.0)
    return dd


# --------------------------------------------------------------------------
# Reporting helpers (same as the stock script)
# --------------------------------------------------------------------------
def cagr(final, start, years):
    if final <= 0 or start <= 0:
        return float("nan")
    return (final / start) ** (1.0 / years) - 1.0


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def per_year(res, pot0):
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


def btc_year_returns(mkt, start_d, end_d):
    yrs = {}
    idx = [i for i, d in enumerate(mkt.cal) if start_d <= d <= end_d]
    prev = mkt.close_px("BTC", idx[0] - 1) if idx and idx[0] > 0 else None
    for i in idx:
        y = mkt.cal[i][:4]
        c = mkt.close_px("BTC", i)
        if y not in yrs:
            yrs[y] = [prev, c]
        yrs[y][1] = c
        prev = c
    return {y: (v[1] / v[0] - 1.0 if v[0] else None) for y, v in yrs.items()}


PLACEBO_SEEDS = list(range(1, 21))


def _summ(r, yrs, btc, ew):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / POT - 1) * 100, 2),
        "cagr_pct": round(cagr(r.final, POT, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "halt": r.halt_date,
        "sel_win_pct": (round(100 * r.sel_wins / r.sel_total, 1)
                        if r.sel_total else None),
        "sel_n": r.sel_total,
        "month_win_pct": (round(100 * r.month_wins / r.months, 1)
                          if r.months else None),
        "avg_eligible": (round(r.elig_sum / r.elig_months, 2)
                         if r.elig_months else None),
        "avg_invested_pct": (round(100 * r.invested_sum / r.elig_months, 1)
                             if r.elig_months else None),
        "btc_final": round(btc, 2),
        "btc_ret_pct": round((btc / POT - 1) * 100, 2),
        "ew_final": round(ew, 2),
        "ew_ret_pct": round((ew / POT - 1) * 100, 2),
    }


def _pct(sorted_vals, q):
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
    all_out = {"universe": UNIVERSE, "placebo_seeds": PLACEBO_SEEDS,
               "cost_rate": COST_RATE}
    ranked_final = {}

    # ---- ranked: all windows x both floor variants ----------------------
    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        btc = btc_net(mkt, sd, ed)
        ew = ew_net(mkt, sd, ed)
        for variant in ("ladder", "plain"):
            r = simulate(mkt, sd, ed, "ranked", floor_variant=variant)
            key = f"{wname}|ranked|{variant}"
            all_out[key] = _summ(r, yrs, btc, ew)
            ranked_final[(wname, variant)] = r.final
            print(f"{key}: final={r.final:.2f} "
                  f"ret={(r.final/POT-1)*100:+.2f}% orders={r.orders} "
                  f"costs=${r.costs:.2f} maxDD={r.max_dd*100:.2f}% "
                  f"halt={r.halt_date} avgElig={r.elig_sum/max(r.elig_months,1):.1f} "
                  f"BTC={btc:.2f} EW={ew:.2f}", flush=True)

    # ---- diagnostic: no eligibility filter, plain floor ------------------
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        yrs = years_between(sd, ed)
        btc = btc_net(mkt, sd, ed)
        ew = ew_net(mkt, sd, ed)
        r = simulate(mkt, sd, ed, "ranked", floor_variant="plain",
                     use_filter=False)
        key = f"{wname}|ranked_nofilter|plain"
        all_out[key] = _summ(r, yrs, btc, ew)
        print(f"{key}: final={r.final:.2f} "
              f"ret={(r.final/POT-1)*100:+.2f}% orders={r.orders} "
              f"costs=${r.costs:.2f} maxDD={r.max_dd*100:.2f}% "
              f"halt={r.halt_date}", flush=True)

    # ---- placebo: 20 seeds, full + validation, both variants ------------
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        yrs = years_between(sd, ed)
        btc = btc_net(mkt, sd, ed)
        ew = ew_net(mkt, sd, ed)
        for variant in ("ladder", "plain"):
            finals, rows = [], []
            for seed in PLACEBO_SEEDS:
                r = simulate(mkt, sd, ed, "placebo", seed=seed,
                             floor_variant=variant)
                finals.append(r.final)
                rows.append({
                    "seed": seed,
                    "final": round(r.final, 2),
                    "ret_pct": round((r.final / POT - 1) * 100, 2),
                    "max_dd_pct": round(r.max_dd * 100, 2),
                    "halt": r.halt_date,
                    "orders": r.orders,
                    "costs": round(r.costs, 2),
                })
            sfin = sorted(finals)
            rk = ranked_final[(wname, variant)]
            n_beat = sum(1 for v in finals if rk > v)
            dist = {
                "n_seeds": len(finals),
                "median_final": round(_pct(sfin, 0.50), 2),
                "p25_final": round(_pct(sfin, 0.25), 2),
                "p75_final": round(_pct(sfin, 0.75), 2),
                "best_final": round(sfin[-1], 2),
                "worst_final": round(sfin[0], 2),
                "median_ret_pct": round((_pct(sfin, 0.50) / POT - 1) * 100, 2),
                "n_halted": sum(1 for row in rows if row["halt"]),
                "ranked_final": round(rk, 2),
                "ranked_minus_median": round(rk - _pct(sfin, 0.50), 2),
                "ranked_beats_n_of_20": n_beat,
                "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
                "btc_final": round(btc, 2),
                "ew_final": round(ew, 2),
                "rows": rows,
            }
            all_out[f"{wname}|placebo_dist|{variant}"] = dist
            print(f"{wname}|placebo|{variant}: median={dist['median_final']:.2f} "
                  f"p25={dist['p25_final']:.2f} p75={dist['p75_final']:.2f} "
                  f"best={dist['best_final']:.2f} worst={dist['worst_final']:.2f} "
                  f"ranked={rk:.2f} beats {n_beat}/20 "
                  f"halted={dist['n_halted']}", flush=True)

    # ---- benchmark drawdowns ---------------------------------------------
    dd = {}
    for wname, (sd, ed) in WINDOWS.items():
        dd[wname] = {"btc_dd_pct": round(bench_dd(mkt, sd, ed, "btc") * 100, 2),
                     "ew_dd_pct": round(bench_dd(mkt, sd, ed, "ew") * 100, 2)}
    all_out["benchmark_dd"] = dd

    # ---- per-year table: full-window ranked, both variants + BTC ---------
    yearly = {}
    for variant in ("ladder", "plain"):
        r = simulate(mkt, *WINDOWS["full"], "ranked", floor_variant=variant)
        yearly[variant] = {y: round(v * 100, 2)
                           for y, v in per_year(r, POT).items()}
    btc_yrs = {y: (round(v * 100, 2) if v is not None else None)
               for y, v in btc_year_returns(mkt, *WINDOWS["full"]).items()}
    all_out["per_year_ranked"] = yearly
    all_out["per_year_btc"] = btc_yrs
    with open(os.path.join(HERE, "crypto-basket-results.json"), "w") as f:
        json.dump(all_out, f, indent=1)
    print("saved crypto-basket-results.json")


# ------------------------------------------------------------- v9 ----
# V9 RE-RUN — "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
# Copied verbatim from crypto-basket.py (v4). Changes vs the original:
# (1) CACHE points at the original v4 cache (read-only); (2) simulate()
# gained start_cash / floor_abs parameters (defaults are the original
# behaviour — $100 start, variant floor); (3) the __main__ entry runs
# the v9 driver below instead of the original main() (which is kept,
# unused, above).
# Terry's rule in this test = the PLAIN -15% floor variant (the ladder
# variant is a different protection rule and is out of scope; its
# recorded halts stand as history, untouched). v9: episode 1 = plain
# floor, identical. On FIRST halt: liquidate exactly as the original
# engine does, sit in cash 90 calendar days, restart with the
# remaining cash at the next monthly selection (1st of the month
# on/after day 90). Episode-2 floor = -15% from the restart balance;
# a second halt ends the run permanently. Everything else
# byte-identical: survivor universe of 20, signals, parameters, costs
# 0.25%/side, windows, $100 start. No placebo re-runs (the original
# placebo verdicts stand: ranked 30th pct full / 15th pct validation
# under plain). Simulation only.
from datetime import timedelta as _td
from datetime import datetime as _dt

def _next_month_first(dstr):
    d = _dt.strptime(dstr, "%Y-%m-%d")
    if d.day == 1:
        return dstr
    nxt = (d.replace(day=1) + _td(days=32)).replace(day=1)
    return nxt.strftime("%Y-%m-%d")

def v9_main():
    mkt = Market(UNIVERSE)
    orig = json.load(open(os.path.join(ORIG_DIR, "crypto-basket-results.json")))
    out = {"windows": {}}
    for wname, (sd, ed) in WINDOWS.items():
        rec = orig[f"{wname}|ranked|plain"]
        ep1 = simulate(mkt, sd, ed, "ranked", floor_variant="plain")
        assert abs(ep1.final - rec["final"]) < 0.011, (wname, ep1.final, rec)
        assert ep1.halt_date == rec["halt"], (wname, ep1.halt_date, rec)
        info = {"his_plain_final": rec["final"], "his_halt": rec["halt"],
                "ep1_min_equity": round(min(e for _, e in ep1.equity_curve), 4),
                "restart": None, "second_halt": False, "second_halt_date": None,
                "v9_final": ep1.final,
                "v9_min_equity": round(min(e for _, e in ep1.equity_curve), 4)}
        if ep1.halt_date is None:
            print(f"{wname}: plain floor never fired (final ${ep1.final:.2f}) -> identical, no re-run")
        else:
            restart_cash = ep1.final
            earliest = (_dt.strptime(ep1.halt_date, "%Y-%m-%d") + _td(days=90)).strftime("%Y-%m-%d")
            rdate = _next_month_first(earliest)
            if rdate > ed:
                info["restart"] = {"status": "no_decision_point_in_window",
                                   "earliest": earliest, "restart_cash": restart_cash}
                print(f"{wname}: halted {ep1.halt_date} ${restart_cash:.2f}; no restart point in window")
            else:
                ep2 = simulate(mkt, rdate, ed, "ranked", floor_variant="plain",
                               start_cash=restart_cash, floor_abs=0.85 * restart_cash)
                info["restart"] = {"status": "restarted", "earliest": earliest,
                                   "restart_date": rdate, "restart_cash": restart_cash,
                                   "ep2_floor": round(0.85 * restart_cash, 4),
                                   "ep2_orders": ep2.orders, "ep2_costs": round(ep2.costs, 4)}
                info["second_halt"] = ep2.halt_date is not None
                info["second_halt_date"] = ep2.halt_date
                info["v9_final"] = ep2.final
                info["v9_min_equity"] = min(info["ep1_min_equity"],
                                            round(min(e for _, e in ep2.equity_curve), 4))
                print(f"{wname}: halted {ep1.halt_date} ${restart_cash:.2f}; restart {rdate} -> v9 ${ep2.final:.2f} second_halt={info['second_halt']} {ep2.halt_date}")
        out["windows"][wname] = info
    with open(os.path.join(HERE, "v9-workings.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved v9-workings.json")

if __name__ == "__main__":
    v9_main()
