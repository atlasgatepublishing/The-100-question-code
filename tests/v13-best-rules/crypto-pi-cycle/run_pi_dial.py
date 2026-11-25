#!/usr/bin/env python3
"""
V13 BEST RULES — crypto-pi-cycle: the PI-DIAL form.

Spec frozen in BEST-RULES-SPEC.md BEFORE this run:
  - BTC only. Published indicators unchanged: Top = SMA111 cross UP through
    2*SMA350; Bottom = EMA150 cross DOWN through 0.745*SMA471.
  - DIAL exit: top cross while FULL -> sell HALF at next bar's open.
    Top cross while HALF -> ignored. Bottom cross-down while HALF -> buy
    back to FULL at next bar's open. Bottom cross while FULL -> ignored.
  - NO floor. Costs 0.60%/side. Pot $100 fresh per road. START-LONG.
  - Point-in-time: cross knowable at its close; orders at NEXT bar's open.
    EMA150 seeded with SMA of first 150 closes, k=2/151; signals only from
    bar index 470 onward (WARMUP-471).
  - Roads (v12 exact): FULL = bar 470 (2015-12-31) -> 2026-11-20;
    DESIGN 2017-01-01 -> 2022-12-31; VALIDATION 2023-01-01 -> 2026-11-20.
  - Bar: BTC buy-hold net same costs, same window, beside every number.
  - Comparison: v12 constructed native best (100% switch, reentry-down,
    0.745, no floor) re-run in this chassis.
  - Placebos: 20 seeds, shifted-MA controls (u~U(0.70,1.40) on all four
    lengths) on the SAME dial chassis, FULL + VALIDATION.
Shared data READ-ONLY; writes only inside this folder.
"""

import csv
import json
import os
import random
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BTC_CSV = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/crypto-trend-data/BTC-USD.csv")

COST = 0.006
POT = 100.0
END = "2026-11-20"
WARMUP = 471

WINDOWS = {
    "full": (None, END),
    "design": ("2017-01-01", "2022-12-31"),
    "validation": ("2023-01-01", END),
}


def load_btc():
    rows = []
    with open(BTC_CSV) as f:
        for r in csv.DictReader(f):
            rows.append({"d": r["date"], "o": float(r["open"]),
                         "c": float(r["close"])})
    return rows


def sma_series(closes, n):
    out = [None] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema_series(closes, n):
    out = [None] * len(closes)
    if len(closes) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    out[n - 1] = e
    for i in range(n, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def compute_events(rows, fast_top=111, slow_top=350, fast_bot=150,
                   slow_bot=471, bot_mult=0.745):
    closes = [r["c"] for r in rows]
    s_fast = sma_series(closes, fast_top)
    s_slow = sma_series(closes, slow_top)
    e_fast = ema_series(closes, fast_bot)
    s_bot = sma_series(closes, slow_bot)
    warm = max(slow_bot, slow_top) - 1
    ev = []
    prev_top = None
    prev_bot = None
    for i in range(len(rows)):
        top_above = None
        bot_below = None
        if i >= warm and s_fast[i] is not None and s_slow[i] is not None \
                and e_fast[i] is not None and s_bot[i] is not None:
            top_above = s_fast[i] > 2.0 * s_slow[i]
            bot_below = e_fast[i] < bot_mult * s_bot[i]
        e = {"top_up": False, "bot_down": False}
        if top_above is not None and prev_top is not None:
            e["top_up"] = top_above and not prev_top
        if bot_below is not None and prev_bot is not None:
            e["bot_down"] = bot_below and not prev_bot
        if top_above is not None:
            prev_top = top_above
        if bot_below is not None:
            prev_bot = bot_below
        ev.append(e)
    return ev


def run_dial(rows, events, wstart, wend):
    """PI-DIAL: states FULL / HALF. Top cross FULL->sell half; HALF->ignore.
    Bottom cross-down HALF->buy to full; FULL->ignore. No floor."""
    idx = [i for i, r in enumerate(rows)
           if (wstart is None or r["d"] >= wstart) and r["d"] <= wend]
    if not idx:
        return None
    cash = 0.0
    units = POT * (1 - COST) / rows[idx[0]]["o"]
    costs = POT * COST
    trades = 1
    state = "FULL"
    curve = []
    peak = POT
    maxdd = 0.0
    days_in = 0
    pending = None  # "sell_half" | "buy_full"
    trade_log = [{"date": rows[idx[0]]["d"], "action": "buy_start_long",
                  "price": rows[idx[0]]["o"]}]
    for pos, i in enumerate(idx):
        r = rows[i]
        if pending is not None and pos > 0:
            if pending == "sell_half" and state == "FULL":
                sell_units = units / 2.0
                proceeds = sell_units * r["o"]
                costs += proceeds * COST
                cash = proceeds * (1 - COST)
                units -= sell_units
                state = "HALF"
                trades += 1
                trade_log.append({"date": r["d"], "action": "sell_half",
                                  "price": r["o"]})
            elif pending == "buy_full" and state == "HALF":
                spend = cash
                units += spend * (1 - COST) / r["o"]
                costs += spend * COST
                cash = 0.0
                state = "FULL"
                trades += 1
                trade_log.append({"date": r["d"], "action": "buy_full",
                                  "price": r["o"]})
            pending = None
        eq = units * r["c"] + cash
        if units > 0:
            days_in += 1
        curve.append([r["d"], round(eq, 4)])
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak)
        e = events[i]
        if e["top_up"] and state == "FULL":
            pending = "sell_half"
        elif e["bot_down"] and state == "HALF":
            pending = "buy_full"
    return {"final": round(curve[-1][1], 2),
            "max_dd_pct": round(maxdd * 100, 1), "trades": trades,
            "costs": round(costs, 2), "days_in_market": days_in,
            "days": len(curve), "end_state": state,
            "trade_log": trade_log, "curve": curve}


def run_switch(rows, events, wstart, wend):
    """v12 PI-FULL native: 100% out on top cross, 100% back on bottom
    cross-down. Re-run here for apples-to-apples comparison."""
    idx = [i for i, r in enumerate(rows)
           if (wstart is None or r["d"] >= wstart) and r["d"] <= wend]
    if not idx:
        return None
    cash = 0.0
    units = POT * (1 - COST) / rows[idx[0]]["o"]
    costs = POT * COST
    trades = 1
    in_market = True
    curve = []
    peak = POT
    maxdd = 0.0
    days_in = 0
    pending = None
    for pos, i in enumerate(idx):
        r = rows[i]
        if pending is not None and pos > 0:
            if pending == "sell" and in_market:
                proceeds = units * r["o"]
                costs += proceeds * COST
                cash = proceeds * (1 - COST)
                units = 0.0
                in_market = False
                trades += 1
            elif pending == "buy" and not in_market:
                units = cash * (1 - COST) / r["o"]
                costs += cash * COST
                cash = 0.0
                in_market = True
                trades += 1
            pending = None
        eq = units * r["c"] if in_market else cash
        if in_market:
            days_in += 1
        curve.append([r["d"], round(eq, 4)])
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak)
        e = events[i]
        if e["top_up"] and in_market:
            pending = "sell"
        elif e["bot_down"] and not in_market:
            pending = "buy"
    return {"final": round(curve[-1][1], 2),
            "max_dd_pct": round(maxdd * 100, 1), "trades": trades,
            "costs": round(costs, 2), "days_in_market": days_in,
            "days": len(curve), "curve": curve}


def buy_hold(rows, wstart, wend):
    idx = [i for i, r in enumerate(rows)
           if (wstart is None or r["d"] >= wstart) and r["d"] <= wend]
    if len(idx) < 2:
        return None
    units = POT * (1 - COST) / rows[idx[0]]["o"]
    peak = 0.0
    maxdd = 0.0
    curve = []
    for i in idx:
        eq = units * rows[i]["c"]
        curve.append([rows[i]["d"], round(eq, 4)])
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak)
    final = units * rows[idx[-1]]["c"] * (1 - COST)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 1),
            "start": rows[idx[0]]["d"], "end": rows[idx[-1]]["d"],
            "curve": curve}


def dparse(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def period_stats(curve):
    """Calendar-year distribution + longest stretch between new highs."""
    years = {}
    order = []
    for d, eq in curve:
        y = d[:4]
        if y not in years:
            years[y] = {"first": eq, "last": eq, "n": 0}
            order.append(y)
        years[y]["last"] = eq
        years[y]["n"] += 1
    # reporting hygiene: a stub year with <30 bars (FULL road opens
    # 2015-12-31, a single day) is not a period; drop it. Trading results
    # are unaffected — this touches only the distribution table.
    order = [y for y in order if years[y]["n"] >= 30]
    rets = []
    prev_last = None
    for y in order:
        base = prev_last if prev_last is not None else years[y]["first"]
        # first period measured from pot start (curve begins at ~$100 mark)
        r = (years[y]["last"] / base - 1) * 100 if base else 0.0
        rets.append((y, round(r, 1)))
        prev_last = years[y]["last"]
    vals = sorted(r for _, r in rets)
    median = vals[len(vals) // 2] if len(vals) % 2 == 1 else \
        (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
    pos = sum(1 for _, r in rets if r > 0)
    streak = 0
    worst_streak = 0
    for _, r in rets:
        streak = streak + 1 if r <= 0 else 0
        worst_streak = max(worst_streak, streak)
    peak = 0.0
    peak_date = None
    longest_gap = 0
    for d, eq in curve:
        if eq >= peak:
            if peak_date is not None:
                longest_gap = max(longest_gap, (dparse(d) - dparse(peak_date)).days)
            peak = eq
            peak_date = d
    tail_gap = (dparse(curve[-1][0]) - dparse(peak_date)).days if peak_date else 0
    mean = sum(r for _, r in rets) / len(rets) if rets else 0.0
    return {"periods": [{"year": y, "return_pct": r} for y, r in rets],
            "n_periods": len(rets), "median_period_pct": round(median, 1),
            "share_positive_pct": round(100 * pos / len(rets), 1) if rets else None,
            "best_period_pct": max(r for _, r in rets),
            "worst_period_pct": min(r for _, r in rets),
            "longest_losing_streak": worst_streak,
            "longest_stretch_between_new_highs_days": longest_gap,
            "days_below_last_high_at_end": tail_gap,
            "mean_period_pct_secondary": round(mean, 1)}


def main():
    btc = load_btc()
    ev = compute_events(btc)
    census = {"top_crosses": [], "bottom_crosses_down": []}
    for i, e in enumerate(ev):
        if e["top_up"]:
            census["top_crosses"].append(
                {"date": btc[i]["d"], "close": btc[i]["c"]})
        if e["bot_down"]:
            census["bottom_crosses_down"].append(
                {"date": btc[i]["d"], "close": btc[i]["c"]})

    results = {
        "family": "crypto-pi-cycle — V13 BEST RULES (PI-DIAL)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "cost_rate_per_side": COST, "pot": POT,
        "tiny_sample_fence": "Published record = 4 top crosses + 3 bottom "
                             "crosses in BTC history; 2 + 2 print in this "
                             "data. A story, not a statistic.",
        "series": {"first": btc[0]["d"], "last": btc[-1]["d"],
                   "bars": len(btc),
                   "source": "v4 crypto-trend-data/BTC-USD.csv (Yahoo)"},
        "signal_census": census,
        "roads": {},
        "placebos_shifted_ma_dial": {},
    }

    for wname, (ws, we) in WINDOWS.items():
        wstart = ws if ws else btc[WARMUP - 1]["d"]
        dial = run_dial(btc, ev, wstart, we)
        switch = run_switch(btc, ev, wstart, we)
        bh = buy_hold(btc, wstart, we)
        results["roads"][wname] = {
            "window": [wstart, we],
            "pi_dial_v13": dial,
            "pi_switch_v12_native_rerun": {k: v for k, v in switch.items()
                                           if k != "curve"},
            "btc_buy_hold": {k: v for k, v in bh.items() if k != "curve"},
            "dial_period_distribution": period_stats(dial["curve"]),
            "buy_hold_period_distribution": period_stats(bh["curve"]),
        }

    # placebos: shifted-MA on the dial chassis
    for wname in ("full", "validation"):
        ws, we = WINDOWS[wname]
        runs = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            u = rng.uniform(0.70, 1.40)
            ft, st = max(20, round(111 * u)), max(40, round(350 * u))
            fb, sbn = max(20, round(150 * u)), max(50, round(471 * u))
            evp = compute_events(btc, fast_top=ft, slow_top=st,
                                 fast_bot=fb, slow_bot=sbn)
            start_i = max(sbn, st) - 1
            if wname == "full":
                wstart = btc[start_i]["d"] if start_i < len(btc) else btc[470]["d"]
            else:
                wstart = ws
            r = run_dial(btc, evp, wstart, we)
            runs.append({"seed": seed, "u": round(u, 3),
                         "lengths": [ft, st, fb, sbn],
                         "final": r["final"] if r else None,
                         "max_dd_pct": r["max_dd_pct"] if r else None,
                         "trades": r["trades"] if r else None})
        finals = sorted(x["final"] for x in runs if x["final"] is not None)
        med = finals[len(finals) // 2] if len(finals) % 2 == 1 else \
            (finals[len(finals) // 2 - 1] + finals[len(finals) // 2]) / 2
        results["placebos_shifted_ma_dial"][wname] = {
            "runs": runs, "median_final": round(med, 2),
            "min_final": finals[0], "max_final": finals[-1]}

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)

    for wname in ("full", "design", "validation"):
        rd = results["roads"][wname]
        print(wname, rd["window"],
              "| DIAL", rd["pi_dial_v13"]["final"],
              "dd", rd["pi_dial_v13"]["max_dd_pct"],
              "trades", rd["pi_dial_v13"]["trades"],
              "| SWITCH", rd["pi_switch_v12_native_rerun"]["final"],
              "| HOLD", rd["btc_buy_hold"]["final"],
              "dd", rd["btc_buy_hold"]["max_dd_pct"])
    for wname in ("full", "validation"):
        p = results["placebos_shifted_ma_dial"][wname]
        print("placebo", wname, "median", p["median_final"],
              "min", p["min_final"], "max", p["max_final"])
    print("census", json.dumps(census))
    print("dial FULL periods:",
          json.dumps(results["roads"]["full"]["dial_period_distribution"]))


if __name__ == "__main__":
    main()
