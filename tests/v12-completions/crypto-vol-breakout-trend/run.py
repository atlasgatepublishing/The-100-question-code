#!/usr/bin/env python3
"""V12 crypto-vol-breakout-trend: Donchian/Turtle breakout forms (S1 20/10,
S2 55/20) as practiced in crypto, run per coin on the v4 PIT universe.
Spec: CONSTRUCTION-SPEC.md (frozen before this run). Shared v4 data READ-ONLY.
"""
import json, os, sys, math
import numpy as np
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE = os.path.join(V4, "crypto-basket-pit-data")
COST = 0.004
POT = 100.0
FLOOR = 85.0
STABLES = {"USDT", "USDC", "DAI", "BUSD", "UST", "USD1", "USDe"}
CREDIBLE_START = {"FIL": "2020-10-15", "ARB": "2023-03-23", "TIA": "2023-10-31"}
FORMS = {"S1_20_10": (20, 10), "S2_55_20": (55, 20)}

def load_coin(info):
    src = info["source"]
    kind, _, tag = src.partition(":")
    fn = {"yahoo": f"y_{tag}.json", "binance": f"b_{tag}.json",
          "kraken": f"k_{tag}.json"}.get(kind)
    if fn is None:
        return None
    with open(os.path.join(CACHE, fn)) as f:
        rows = json.load(f)
    sym = info["symbol"]
    cs = CREDIBLE_START.get(sym)
    out = []
    for r in rows:
        if cs and r["d"] < cs:
            continue
        if r["o"] <= 0 or r["c"] <= 0:
            continue
        out.append(r)
    return out

def roll_extreme(c, n, fn):
    """fn over prior n closes, excluding current bar; NaN until warm."""
    out = np.full(len(c), np.nan)
    if len(c) > n:
        from numpy.lib.stride_tricks import sliding_window_view
        vals = fn(sliding_window_view(c, n), axis=1)  # vals[k] = extreme of c[k:k+n]
        idx = np.arange(n, len(c))
        out[idx] = vals[idx - n]  # bar i uses c[i-n:i]
    return out

def simulate(dates, o, c, entry_n, exit_n, weekly, floor, start_i):
    """Long-only channel system. Decisions at close i (i>=start_i), executed
    at open i+1. Returns dict with final, max_dd, trades, exposure, curve."""
    n = len(c)
    hi = roll_extreme(c, entry_n, np.max)
    lo = roll_extreme(c, exit_n, np.min)
    week_end = np.zeros(n, dtype=bool)
    if weekly:
        wk = np.array([date.fromisoformat(d).isocalendar()[:2] for d in dates])
        week_end[:-1] = (wk[1:] != wk[:-1]).any(axis=1)
        week_end[-1] = True
    cash, shares, inpos = POT, 0.0, False
    trades = 0
    equity = np.full(n, POT)
    invested_days = 0
    halted = False
    halt_date = None
    # segment bookkeeping for equity curve
    seg_start = start_i
    for i in range(start_i, n):
        if inpos:
            equity[i] = shares * c[i]
            invested_days += 1
        else:
            equity[i] = cash
        if halted or i + 1 >= n:
            continue
        if floor and equity[i] <= FLOOR:
            if inpos:
                cash = shares * o[i + 1] * (1 - COST)
                shares, inpos = 0.0, False
                trades += 0  # liquidation not counted as a signal trade
            halted = True
            halt_date = dates[i + 1]
            continue
        if weekly and not week_end[i]:
            continue
        if not inpos and not np.isnan(hi[i]) and c[i] > hi[i]:
            shares = cash * (1 - COST) / o[i + 1]
            cash, inpos = 0.0, True
            trades += 1
        elif inpos and not np.isnan(lo[i]) and c[i] < lo[i]:
            cash = shares * o[i + 1] * (1 - COST)
            shares, inpos = 0.0, False
    if inpos:
        final = shares * c[-1] * (1 - COST)
    else:
        final = cash
    eq = equity[start_i:]
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.min(eq / peak - 1)) if len(eq) else 0.0
    exposure = invested_days / max(len(eq), 1)
    return {"final": float(final), "max_dd_pct": round(max_dd * 100, 2),
            "trades": trades, "exposure": round(exposure, 3),
            "halted": halted, "halt_date": halt_date,
            "curve": equity}

def period_stats(equity, dates, start_i, weekly):
    """Period-by-period record at the strategy's native tempo: daily
    periods for the native rule set, weekly periods for v9. Computed from
    the equity curve. Averages are NOT produced here on purpose."""
    eq = equity[start_i:]
    ds = dates[start_i:]
    if weekly:
        wk = {}
        for d, v in zip(ds, eq):
            iso = date.fromisoformat(d).isocalendar()[:2]
            wk[iso] = v
        vals = np.array(list(wk.values()))
    else:
        vals = eq
    if len(vals) < 2:
        return None
    rets = vals[1:] / vals[:-1] - 1
    pos = int(np.sum(rets > 0))
    # longest run of consecutive losing periods
    longest_loss, cur = 0, 0
    for x in rets:
        cur = cur + 1 if x < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods, incl. tail to end)
    peak = -np.inf
    last_high = 0
    longest_gap = 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, i - last_high)
            last_high = i
    longest_gap = max(longest_gap, len(vals) - 1 - last_high)
    return {"periods": int(len(rets)),
            "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(float(np.median(rets)) * 100, 3),
            "best_pct": round(float(np.max(rets)) * 100, 2),
            "worst_pct": round(float(np.min(rets)) * 100, 2),
            "longest_losing_run": int(longest_loss),
            "longest_between_highs": int(longest_gap),
            "mean_pct_secondary": round(float(np.mean(rets)) * 100, 3)}

def buyhold(o, c, start_i):
    sh = POT * (1 - COST) / o[start_i]
    eq = sh * c[start_i:]
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq / peak - 1))
    return float(sh * c[-1] * (1 - COST)), round(dd * 100, 2)

def placebo_finals(dates, o, c, start_i, exposure, floor, seeds=range(1, 21)):
    """Weekly-step random timing, same average exposure, same costs/floor.
    Close-to-close approximation for the placebo only (v4 convention)."""
    n = len(c)
    wk = np.array([date.fromisoformat(d).isocalendar()[:2] for d in dates])
    step = np.zeros(n, dtype=bool)
    step[start_i] = True
    step[start_i + 1:] = (wk[start_i + 1:] != wk[start_i:-1]).any(axis=1)
    step_idx = np.where(step & (np.arange(n) >= start_i))[0]
    rets = np.zeros(n)
    rets[1:] = c[1:] / c[:-1] - 1
    finals = []
    for s in seeds:
        rng = np.random.default_rng(1000 + s)
        inweek = rng.random(len(step_idx)) < exposure
        pos = np.zeros(n, dtype=bool)
        for k, ix in enumerate(step_idx):
            j = step_idx[k + 1] if k + 1 < len(step_idx) else n
            pos[ix:j] = inweek[k]
        held = pos.copy()
        held[:-1] = pos[1:]  # position decided at prior close earns next ret
        eq = np.ones(n)
        switches = np.zeros(n)
        prev = False
        # switch cost days: where held-position changes (approx at close)
        chg = np.zeros(n, dtype=bool)
        chg[1:] = held[1:] != held[:-1]
        chg[start_i] = held[start_i]
        growth = np.where(held, 1 + rets, 1.0)
        growth = np.where(chg, growth * (1 - COST), growth)
        eq = POT * np.cumprod(growth)
        if floor:
            below = np.where(eq[start_i:] <= FLOOR)[0]
            if len(below):
                finals.append(float(eq[start_i + below[0]] * (1 - COST)))
                continue
        finals.append(float(eq[-1] * (1 - COST) if held[-1] else eq[-1]))
    return finals

def main():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    btc_rows = None
    coins = {}
    excluded, not_applicable = {}, {}
    for cid, info in reg.items():
        sym = info["symbol"]
        if info["source"] == "excluded" or not info["bars"]:
            excluded[sym] = info["reason"]
            continue
        if sym in STABLES:
            not_applicable[sym] = "pegged stablecoin — no trend to break out of"
            continue
        rows = load_coin(info)
        if rows is None or len(rows) < 260:
            excluded[sym] = f"series too short after cleaning ({0 if rows is None else len(rows)} bars)"
            continue
        coins[sym] = rows
        if sym == "BTC":
            btc_rows = rows
    btc_dates = [r["d"] for r in btc_rows]
    btc_o = np.array([r["o"] for r in btc_rows])
    btc_c = np.array([r["c"] for r in btc_rows])

    def btc_hold(d0, d1):
        i0 = next(i for i, d in enumerate(btc_dates) if d >= d0)
        i1 = max(i for i, d in enumerate(btc_dates) if d <= d1)
        f, dd = buyhold(btc_o[i0:i1 + 1], btc_c[i0:i1 + 1], 0)
        return round(f, 2), dd

    results = {"cost_rate": COST, "coins": {}, "excluded": excluded,
               "not_applicable": not_applicable, "curves": {}}
    for sym, rows in sorted(coins.items()):
        dates = [r["d"] for r in rows]
        o = np.array([r["o"] for r in rows], dtype=float)
        c = np.array([r["c"] for r in rows], dtype=float)
        entry = {"symbol": sym, "bars": len(rows), "first": dates[0],
                 "last": dates[-1], "forms": {}}
        bh_full, bh_dd = buyhold(o, c, FORMS["S2_55_20"][0])
        btch_full = btc_hold(dates[FORMS["S2_55_20"][0]], dates[-1])
        i23 = next((i for i, d in enumerate(dates) if d >= "2023-01-01"), None)
        entry["buyhold_full"] = round(bh_full, 2)
        entry["buyhold_dd_pct"] = bh_dd
        entry["btc_hold_same_window"] = btch_full[0]
        entry["btc_hold_dd_pct"] = btch_full[1]
        if i23 is not None and len(rows) - i23 > 60:
            bh_v, _ = buyhold(o, c, i23)
            entry["buyhold_conf"] = round(bh_v, 2)
            entry["btc_hold_conf"] = btc_hold(dates[i23], dates[-1])[0]
        for fname, (en, xn) in FORMS.items():
            for rname, weekly, floor in (("native", False, False),
                                         ("v9", True, True)):
                r = simulate(dates, o, c, en, xn, weekly, floor, en)
                rec = {"final": round(r["final"], 2),
                       "max_dd_pct": r["max_dd_pct"], "trades": r["trades"],
                       "exposure": r["exposure"], "halted": r["halted"],
                       "halt_date": r["halt_date"],
                       "period_stats": period_stats(r["curve"], dates, en, weekly)}
                pf = placebo_finals(dates, o, c, en, r["exposure"], floor)
                pf_sorted = sorted(pf)
                rec["placebo_median"] = round(pf_sorted[len(pf) // 2], 2)
                rec["placebo_beats_n_of_20"] = sum(1 for v in pf if r["final"] > v)
                rec["beats_hold"] = r["final"] > bh_full
                rec["beats_btc_hold"] = r["final"] > btch_full[0]
                if i23 is not None and len(rows) - i23 > 60:
                    rv = simulate(dates, o, c, en, xn, weekly, floor, i23)
                    rec["conf_final"] = round(rv["final"], 2)
                    rec["conf_max_dd_pct"] = rv["max_dd_pct"]
                    rec["conf_beats_hold"] = rv["final"] > entry["buyhold_conf"]
                entry["forms"][f"{fname}|{rname}"] = rec
                if sym in ("BTC", "ETH") and rname == "native":
                    results["curves"][f"{sym}|{fname}"] = [
                        [dates[i], round(float(r["curve"][i]), 2)]
                        for i in range(en, len(dates))]
        results["coins"][sym] = entry
        print(sym, "done", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f)
    print("coins run:", len(results["coins"]))

if __name__ == "__main__":
    main()
