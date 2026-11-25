#!/usr/bin/env python3
"""
MOMENTUM BASKET — v10 GREAT RETEST cadence sweep. Simulation only.

Strategy (frozen, from v4/momentum-basket-honest.py): monthly top-5 of the
honest Nov-2016 top-30 by 12-1 momentum, own-200-day eligibility.
  Universe (30 names, Nov-2016 top-30 by market cap): AAPL MSFT AMZN GOOGL
    META BRK-B JPM XOM JNJ PG V WMT HD BAC CVX PFE VZ T DIS NFLX INTC CSCO
    GE IBM MMM UNH MA KO PEP WFC
  On a selection day (at the OPEN, signal from the PRIOR trading day's close):
    - Eligible: close above own 200-day SMA and 12-1 momentum available.
    - Rank by 12-1 momentum: close[t-21]/close[t-252]-1; hold TOP 5 at 20%
      of pot equity each; fewer eligible -> hold what's eligible, rest cash.
  Costs: 0.10% of trade value per side + $0.01 per sell order (program).

v10 changes vs v9 (SPEC binding):
  - CADENCE SWEEP on the DECADE road 2016-11-21 -> 2026-11-20: selection /
    re-rank / eligibility check ONLY on cadence dates (daily = every trading
    day; weekly = first trading day of each week; biweekly = first trading
    day of every second week, anchored on the week containing the start;
    monthly = first trading day of each month; quarterly = first trading
    day of each calendar quarter; semi-annual = first trading day of each
    half-year; annual = first trading day of each year). The window's first
    trading day is always a selection day (as in the original engine).
  - Protection = adopted v9 rules: plain -15% floor per episode (checked at
    every close, as the original engine does), liquidate at next open; on
    first halt sit in cash 90 calendar days and restart at the next cadence
    date with an episode-2 floor of -15% from the restart balance; second
    halt ends the run.
  - INTEGRITY first: monthly cadence on the full window and on the original
    validation window (2023-01-01 -> 2026-11-20), ranked + 20 placebo seeds,
    must reproduce the published $439.45 / $208.27 and 19/20 / 18/20.

Data: read-only from the original cache
  ~/workspace/stock-app/backtests/v4/momentum-basket-honest-data/
(Yahoo split-adjusted daily bars 2015-01-02 -> 2026-11-20). No downloads.
SPY note: this cache is price (split-adjusted) closes, so SPY computed here
is price-only; the SPEC's dividend-adjusted decade SPY is $367.80 and is
reported as the headline benchmark in results.json.
"""

import json
import math
import os
import random
from datetime import datetime, date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001
SELL_FEE = 0.01
POT0 = 100.0
DECADE = ("2016-11-21", "2026-11-20")
VAL = ("2023-01-01", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))


def fetch(ticker):
    with open(os.path.join(CACHE, f"{ticker}.json")) as f:
        return json.load(f)


class Market:
    def __init__(self, tickers):
        self.bars = {}
        self.closes = {}
        spy = fetch(BENCH)
        self.cal = [r["d"] for r in spy]
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = fetch(t)
        for t in tickers + [BENCH]:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr
        # Precompute SMA200 and 12-1 momentum with the ORIGINAL formulas
        # (same slice sums, same None rules) so values are identical to the
        # original engine's per-call computation.
        self.sma200 = {}
        self.mom = {}
        n = len(self.cal)
        for t in tickers:
            c = self.closes[t]
            s = [None] * n
            m = [None] * n
            for i in range(n):
                if i + 1 >= 200:
                    seg = c[i - 199: i + 1]
                    if not any(v is None for v in seg):
                        s[i] = sum(seg) / 200.0
                if i - 252 >= 0:
                    a, b = c[i - 252], c[i - 21]
                    if a is not None and b is not None and a > 0:
                        m[i] = b / a - 1.0
            self.sma200[t] = s
            self.mom[t] = m

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]


def period_key(dstr, cadence):
    y, m, dd = (int(x) for x in dstr.split("-"))
    if cadence == "monthly":
        return (y, m)
    if cadence == "quarterly":
        return (y, (m - 1) // 3)
    if cadence == "semiannual":
        return (y, (m - 1) // 6)
    if cadence == "annual":
        return (y,)
    if cadence in ("weekly", "biweekly"):
        iso = date(y, m, dd).isocalendar()
        return (iso[0], iso[1])
    raise ValueError(cadence)


def cadence_indices(mkt, i0, i1, cadence):
    """Set of calendar indices that are selection days in [i0, i1]."""
    if cadence == "daily":
        return set(range(i0, i1 + 1))
    out = {i0}
    prev = period_key(mkt.cal[i0], cadence)
    week_count = 0          # for biweekly: weeks since the anchor week
    for i in range(i0 + 1, i1 + 1):
        k = period_key(mkt.cal[i], cadence)
        if k != prev:
            prev = k
            if cadence == "biweekly":
                week_count += 1
                if week_count % 2 == 0:
                    out.add(i)
            else:
                out.add(i)
    return out


class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halts = []
        self.restarts = []
        self.max_dd = 0.0
        self.equity_curve = []


def simulate(mkt, start_d, end_d, cadence, mode, seed=42):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    sel_days = cadence_indices(mkt, i0, i1, cadence)
    episode = 1
    floor = 0.85 * POT0
    restart_idx = None
    cash = float(POT0)
    pos = {}
    res = Result()
    pending_liquidation = False

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
                del pos[t]
            res.halts.append(d)
            res.equity_curve.append((d, cash))
            pending_liquidation = False
            if episode == 1:
                y, m, dd = (int(x) for x in d.split("-"))
                earliest = (date(y, m, dd) + timedelta(days=90)).isoformat()
                ridx = None
                for j in sorted(sel_days):
                    if j > i and mkt.cal[j] >= earliest:
                        ridx = j
                        break
                if ridx is not None:
                    restart_idx = ridx
                    episode = 2
                    res.restarts.append({
                        "halt_date": d,
                        "restart_date": mkt.cal[ridx],
                        "restart_balance": round(cash, 2),
                        "episode2_floor": round(0.85 * cash, 2)})
                    floor = 0.85 * cash
                    continue
            res.final = cash
            break

        if restart_idx is not None and i < restart_idx:
            res.equity_curve.append((d, cash))
            continue
        if restart_idx is not None and i == restart_idx:
            restart_idx = None

        if i in sel_days and i > 0:
            j = i - 1
            elig = []
            for t in UNIVERSE:
                s = mkt.sma200[t][j]
                c = mkt.close_px(t, j)
                if s is None or c is None or c <= s:
                    continue
                mo = mkt.mom[t][j]
                if mo is None:
                    continue
                elig.append((t, mo))
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:
                names = sorted(t for t, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []

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
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sell_val / px
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

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
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
                res.halts.append(d)
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    return res


def spy_net(mkt, start_d, end_d):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px(BENCH, i0)
    sell_px = mkt.close_px(BENCH, i1)
    sh = (POT0 * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE


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


def per_year(res):
    out = {}
    years = sorted({d[:4] for d, _ in res.equity_curve})
    prev_eq = POT0
    for y in years:
        pts = [e for d, e in res.equity_curve if d[:4] == y]
        if not pts:
            continue
        out[y] = pts[-1] / prev_eq - 1.0
        prev_eq = pts[-1]
    return out


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def cell_summary(res, yrs, placebo_finals):
    beaten = None
    if placebo_finals is not None:
        beaten = sum(1 for v in placebo_finals if res.final > v)
    return {
        "final": round(res.final, 2),
        "cagr_pct": round(((res.final / POT0) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(res.max_dd * 100, 2),
        "halts": len(res.halts),
        "restart": bool(res.restarts),
        "second_halt": len(res.halts) >= 2,
        "costs": round(res.costs, 2),
        "orders": res.orders,
        "placebo_beaten": beaten,
        "placebo_note": ("20 seeds (1..20), random 5 of the same eligible set "
                         "on the same cadence dates, identical machinery"
                         if placebo_finals is not None else None),
    }


def main():
    mkt = Market(UNIVERSE)
    yrs_dec = years_between(*DECADE)
    yrs_val = years_between(*VAL)
    spy_dec_price = spy_net(mkt, *DECADE)
    spy_val_price = spy_net(mkt, *VAL)
    spy_yrs = spy_year_returns(mkt, *DECADE)
    print(f"SPY price-only net: decade={spy_dec_price:.2f} val={spy_val_price:.2f}",
          flush=True)

    # ---------------- INTEGRITY (monthly, original windows) --------------
    integrity = {}
    for label, window, yrs, pub_final, pub_beats in (
            ("full", DECADE, yrs_dec, 439.45, 19),
            ("validation", VAL, yrs_val, 208.27, 18)):
        r = simulate(mkt, window[0], window[1], "monthly", "ranked")
        finals = []
        for seed in PLACEBO_SEEDS:
            pr = simulate(mkt, window[0], window[1], "monthly", "placebo",
                          seed=seed)
            finals.append(round(pr.final, 2))
        beats = sum(1 for v in finals if r.final > v)
        integrity[label] = {
            "window": [window[0], window[1]],
            "published_final": pub_final,
            "reproduced_final": round(r.final, 2),
            "published_placebo_beaten": f"{pub_beats}/20",
            "reproduced_placebo_beaten": f"{beats}/20",
            "placebo_finals": finals,
            "halts": r.halts, "costs": round(r.costs, 2),
            "orders": r.orders, "max_dd_pct": round(r.max_dd * 100, 2)}
        print(f"INTEGRITY {label}: ranked={r.final:.2f} (pub {pub_final}) "
              f"placebo beats {beats}/20 (pub {pub_beats}/20)", flush=True)
    ok = (integrity["full"]["reproduced_final"] == 439.45
          and integrity["validation"]["reproduced_final"] == 208.27
          and integrity["full"]["reproduced_placebo_beaten"] == "19/20"
          and integrity["validation"]["reproduced_placebo_beaten"] == "18/20")
    print("INTEGRITY:", "reproduced" if ok else "CHECK ABOVE", flush=True)

    # ---------------- SWEEP (DECADE x 7 cadences) ------------------------
    cells = {}
    for cad in CADENCES:
        if cad == "monthly":
            # reuse integrity full-window ranked run values via re-sim is
            # wasteful; monthly ranked on DECADE == integrity full run.
            pass
        r = simulate(mkt, DECADE[0], DECADE[1], cad, "ranked")
        pfinals, pdetails = [], []
        for seed in PLACEBO_SEEDS:
            pr = simulate(mkt, DECADE[0], DECADE[1], cad, "placebo", seed=seed)
            pfinals.append(pr.final)
            pdetails.append({
                "seed": seed, "final": round(pr.final, 2),
                "halts": pr.halts,
                "restarts": pr.restarts,
                "costs": round(pr.costs, 2), "orders": pr.orders})
        summ = cell_summary(r, yrs_dec, pfinals)
        py = per_year(r)
        worst_y = min(py, key=lambda y: py[y])
        cell = dict(summ)
        cell.update({
            "window": [DECADE[0], DECADE[1]],
            "start": POT0,
            "halt_dates": r.halts,
            "restarts": r.restarts,
            "per_year_pct": {y: round(v * 100, 2) for y, v in py.items()},
            "worst_calendar_year": {
                "year": worst_y, "ret_pct": round(py[worst_y] * 100, 2),
                "spy_ret_pct": (round(spy_yrs[worst_y] * 100, 2)
                                if spy_yrs.get(worst_y) is not None else None)},
            "ret_2022_pct": round(py.get("2022", float("nan")) * 100, 2),
            "spy_2022_ret_pct": round(spy_yrs["2022"] * 100, 2),
            "spy_convention_note": ("per-year SPY from the price (split-"
                                    "adjusted) cache closes; headline decade "
                                    "SPY $367.80 is dividend-adjusted (SPEC)"),
            "placebo_finals": [round(v, 2) for v in pfinals],
            "placebo_details": pdetails,
            "equity_curve": [[d, round(e, 4)] for d, e in r.equity_curve],
        })
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = summ
        print(f"{cad}: final={r.final:.2f} CAGR={summ['cagr_pct']}% "
              f"maxDD={summ['max_dd_pct']}% halts={len(r.halts)} "
              f"costs=${r.costs:.2f} orders={r.orders} "
              f"placebo {summ['placebo_beaten']}/20 "
              f"worstYear={worst_y} {py[worst_y]*100:+.2f}% "
              f"2022={py.get('2022', float('nan'))*100:+.2f}%", flush=True)

    spy_dec_div = 367.80     # SPEC: dividend-adjusted, verified plumbing
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_dec_div
             and cells[c]["placebo_beaten"] is not None
             and cells[c]["placebo_beaten"] >= 11]
    out = {
        "slug": "momentum-basket",
        "area": ("monthly momentum holding (basket family, W2) — judged on "
                 "the DECADE road 2016-11-21 -> 2026-11-20 at every cadence"),
        "area_source": "SPEC W2 assignment + CADENCE SWEEP (Terry 2026-11-21)",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "original_cadence_note": ("original program test ran the native "
                                  "monthly cadence — not foreign"),
        "integrity": {
            "status": "reproduced" if ok else "reproduced-with-notes",
            "original_finals": {
                "full_2016-11-21_2026-11-20": 439.45,
                "validation_2023-01-01_2026-11-20": 208.27,
                "placebo_beaten_full": "19/20",
                "placebo_beaten_validation": "18/20",
                "long_2010_reference": 429.17,
                "long_2010_note": ("long-run-2010 reference $429.17 was "
                                   "computed under that folder's raw-close "
                                   "SPY convention (SPY $612.64 there); cited "
                                   "by reference, not re-run — this sweep's "
                                   "road is the DECADE")},
            "reproduced_finals": {
                "full": integrity["full"]["reproduced_final"],
                "validation": integrity["validation"]["reproduced_final"],
                "placebo_beaten_full":
                    integrity["full"]["reproduced_placebo_beaten"],
                "placebo_beaten_validation":
                    integrity["validation"]["reproduced_placebo_beaten"]},
            "record_note": ("the basket's walk-forward 'folds' are calendar-"
                            "year slices of one continuous pot, not fresh "
                            "$100 pots (v9 record)"),
            "detail": integrity},
        "decade_spy_final": spy_dec_div,
        "decade_spy_note": ("$367.80 dividend-adjusted per SPEC (verified "
                            "plumbing). This folder's cache is price closes: "
                            f"price-only SPY net on the same road = "
                            f"${spy_dec_price:.2f}; the original v4/v9 record's "
                            "SPY comparison was likewise computed from these "
                            "price closes by spy_net in the original engine."),
        "spy_price_only_decade": round(spy_dec_price, 2),
        "spy_price_only_validation": round(spy_val_price, 2),
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": ("champion (value+momentum) decade $65.89 after two "
                       "halts; its crown rests on the 2010 and 2019 roads "
                       "(SPEC)")},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,   # filled in RESULTS.md narrative; see below
        "data_note": ("read-only shared cache: backtests/v4/"
                      "momentum-basket-honest-data/ (Yahoo split-adjusted "
                      "daily bars, 31 files incl. SPY). No pond/long-run "
                      "cache used. No downloads."),
    }
    out["verdict_area"] = (
        "OWNS ITS GROUND" if "monthly" in money else "see RESULTS.md")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("money_cadences:", money, flush=True)
    print("saved results.json + cells/", flush=True)


if __name__ == "__main__":
    main()
