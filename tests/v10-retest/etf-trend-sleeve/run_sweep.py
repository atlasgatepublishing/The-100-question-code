#!/usr/bin/env python3
"""
ETF TREND SLEEVE — v10 GREAT RETEST cadence sweep.
Rule (unchanged from v3 monthly original): universe SPY,QQQ,TLT,IEF,GLD,DBC,UUP;
trend score = signs of trailing 63/126/252d returns; hold assets with >=2 of 3
positive; weights prop. to 1/trailing-20d vol, capped 40%; 20% relative no-trade
band (flips always trade); costs 0.10%/side + $0.01/sell order; long-only,
fractional shares; dividend+split adjusted prices.
Data: read-only shared cache backtests/v3/data_etf/ (Yahoo chart JSON).

Modes:
  integrity — ORIGINAL form: monthly eval on LAST trading day of month,
              trade next open, original floor+ladder ($85; $100 @ $125 close;
              $125 @ $150 close). Windows A 2016-11-21->2026-11-20 and
              B 2023-01-01->2026-11-20, $100. Must reproduce $194.61/$123.18.
  sweep     — DECADE 2016-11-21->2026-11-20, 7 cadences per SPEC uniform
              definition (eval dates = FIRST trading day of each period;
              eval at close, trade next open), v9 protections: plain -15%
              floor from episode start; halt -> liquidate next open, sit in
              cash 90 calendar days, restart at next cadence date under an
              episode-2 -15% floor from restart balance; 2nd halt ends run.
  placebos  — per cadence, 20 seeds: at each eval, randomly sample (seeded)
              the same NUMBER of eligible assets the trend rule selected,
              weighted by the same inv-vol capped scheme, same band/costs/v9.
"""
import json, math, os, random, statistics, sys
from datetime import datetime, timezone, timedelta

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "UUP"]
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "v3", "data_etf")
COST_RATE = 0.0010
SELL_FEE = 0.01
START = "2016-11-21"; END = "2026-11-20"

def load_series(ticker):
    with open(os.path.join(CACHE, f"{ticker}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"] if "adjclose" in res["indicators"] else None
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None: continue
        if adj is not None and adj[i]:
            r = adj[i] / c; out[d] = (o * r, adj[i])
        else: out[d] = (o, c)
    return out

SERIES = {t: load_series(t) for t in ASSETS}
CAL = sorted(SERIES["SPY"].keys())
CAL_IDX = {d: i for i, d in enumerate(CAL)}

def close_on(t, date):
    s = SERIES[t]
    if date in s: return s[date][1]
    i = CAL_IDX[date]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s: return s[CAL[j]][1]
    return None

def open_on(t, date):
    s = SERIES[t]
    return s[date][0] if date in s else close_on(t, date)

# forward-filled adjusted-close arrays aligned to CAL (speed)
ARR = {}
for _t in ASSETS:
    _a = []; _last = None
    for _d in CAL:
        if _d in SERIES[_t]: _last = SERIES[_t][_d][1]
        _a.append(_last)
    ARR[_t] = _a

def closes_window(t, end_date, n):
    i = CAL_IDX[end_date]
    if i + 1 < n: return []
    vals = ARR[t][i + 1 - n: i + 1]
    if any(v is None for v in vals): return []
    return list(vals)

def trend_and_vol(t, date):
    closes = closes_window(t, date, 253)
    if len(closes) < 253: return None
    last = closes[-1]; npos = 0
    for lag in (63, 126, 252):
        if last / closes[-1 - lag] - 1.0 > 0: npos += 1
    rets = [closes[k] / closes[k - 1] - 1.0 for k in range(len(closes) - 20, len(closes))]
    vol = statistics.pstdev(rets) if len(rets) >= 20 else None
    return npos, vol

def capped_weights(vols):
    inv = {t: 1.0 / v for t, v in vols.items() if v and v > 0}
    if not inv: return {}
    weights = {}; remaining = dict(inv); budget = 1.0
    while remaining:
        tot = sum(remaining.values())
        over = [t for t in remaining if budget * remaining[t] / tot > 0.40]
        if not over:
            for t in remaining: weights[t] = budget * remaining[t] / tot
            break
        for t in over:
            weights[t] = 0.40; budget -= 0.40; del remaining[t]
        if budget <= 0: break
    return weights

def eval_dates(days, cadence, original_monthly=False):
    if original_monthly:
        by = {}
        for d in days: by.setdefault(d[:7], []).append(d)
        return {max(v) for v in by.values()}
    if cadence == "daily": return set(days)
    def firsts(keyfn):
        seen = {}; out = []
        for d in days:
            k = keyfn(d)
            if k not in seen: seen[k] = d; out.append(d)
        return out
    if cadence == "weekly":
        return set(firsts(lambda d: datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2]))
    if cadence == "biweekly":
        w = firsts(lambda d: datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2])
        return set(w[::2])
    if cadence == "monthly": return set(firsts(lambda d: d[:7]))
    if cadence == "quarterly": return set(firsts(lambda d: (d[:4], (int(d[5:7]) - 1) // 3)))
    if cadence == "semiannual": return set(firsts(lambda d: (d[:4], int(d[5:7]) <= 6)))
    if cadence == "annual": return set(firsts(lambda d: d[:4]))
    raise ValueError(cadence)

def simulate(start, end, eval_set, mode="v9", placebo_seed=None, start_cash=100.0):
    """mode='original': floor+ladder, halt ends run. mode='v9': plain -15% floor,
    90-day sit-out, one restart, 2nd halt ends run."""
    days = [d for d in CAL if start <= d <= end]
    cash = start_cash; shares = {t: 0.0 for t in ASSETS}
    orders = 0; total_costs = 0.0; curve = []; pending = None
    liquidate_next = False; halts = []; restart = False; second_halt = False
    episode = 1; floor = 85.0 if mode == "original" else 0.85 * start_cash
    ladder = ((125.0, 100.0), (150.0, 125.0)) if mode == "original" else ()
    inactive_until = None  # date string; sitting in cash after halt
    rng = random.Random(1000 + placebo_seed) if placebo_seed is not None else None

    def equity(date, fn):
        eq = cash
        for t in ASSETS:
            if shares[t] > 0:
                p = fn(t, date)
                if p: eq += shares[t] * p
        return eq

    for di, d in enumerate(days):
        if liquidate_next or pending is not None:
            if liquidate_next:
                trade_set = {t for t in ASSETS if shares[t] > 0}; targets = {}
            else:
                trade_set, targets = pending
            eq_open = equity(d, open_on)
            for t in sorted(trade_set):
                tgt = targets.get(t, 0.0) * eq_open; cur = shares[t] * open_on(t, d)
                diff = cur - tgt
                if diff > 0.01 and shares[t] > 0:
                    sv = min(diff, cur); sh = sv / open_on(t, d)
                    cost = sv * COST_RATE + SELL_FEE
                    cash += sv - cost; shares[t] -= sh
                    if shares[t] < 1e-9: shares[t] = 0.0
                    orders += 1; total_costs += cost
            buys = []
            for t in sorted(trade_set):
                tgt = targets.get(t, 0.0) * eq_open; cur = shares[t] * open_on(t, d)
                if tgt - cur > 0.01: buys.append((t, tgt - cur))
            tot = sum(v for _, v in buys)
            if tot > 0:
                scale = min(1.0, cash / (tot * (1 + COST_RATE)))
                for t, diff in buys:
                    bv = diff * scale
                    if bv < 0.01: continue
                    cost = bv * COST_RATE; cash -= bv + cost
                    shares[t] += bv / open_on(t, d); orders += 1; total_costs += cost
            pending = None
            if liquidate_next:
                liquidate_next = False
                bal = equity(d, close_on); curve.append((d, bal))
                if mode == "original" or episode == 2:
                    if mode == "v9" and episode == 2: second_halt = True
                    halts.append({"liquidation_date": d, "episode": episode, "balance_after": round(bal, 2)})
                    break
                halts.append({"liquidation_date": d, "episode": episode, "balance_after": round(bal, 2)})
                episode = 2; restart = True
                inactive_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
                continue
        eq_close = equity(d, close_on); curve.append((d, eq_close))
        if inactive_until is not None:
            if d >= inactive_until and d in eval_set:
                inactive_until = None; floor = 0.85 * cash
            else:
                continue
        for trigger, nf in sorted(ladder, reverse=True):
            if eq_close >= trigger: floor = max(floor, nf); break
        if eq_close <= floor:
            if di + 1 < len(days): liquidate_next = True; continue
            else:
                halts.append({"liquidation_date": d, "episode": episode, "balance_after": round(eq_close, 2)})
                if mode == "v9" and episode == 2: second_halt = True
                break
        if d in eval_set and di + 1 < len(days):
            vols_all = {}; chosen = []
            for t in ASSETS:
                tv = trend_and_vol(t, d)
                if tv is None: continue
                npos, vol = tv
                if vol: vols_all[t] = vol
                if npos >= 2 and vol: chosen.append(t)
            if rng is not None:
                elig = sorted(vols_all)
                k = min(len(chosen), len(elig))
                chosen = rng.sample(elig, k) if k else []
            targets = capped_weights({t: vols_all[t] for t in chosen if t in vols_all})
            trade_set = set()
            for t in ASSETS:
                cur_w = (shares[t] * close_on(t, d) / eq_close) if eq_close > 0 else 0.0
                tgt_w = targets.get(t, 0.0); held = shares[t] > 0
                if held and tgt_w == 0.0: trade_set.add(t)
                elif not held and tgt_w > 0.0: trade_set.add(t)
                elif held and tgt_w > 0.0 and abs(tgt_w - cur_w) / tgt_w > 0.20: trade_set.add(t)
            if trade_set: pending = (trade_set, targets)
    final = curve[-1][1] if curve else start_cash
    return {"final": final, "curve": curve, "orders": orders, "costs": total_costs,
            "halts": halts, "restart": restart, "second_halt": second_halt, "days": days}

def metrics(res):
    days = res["days"]
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d") - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    cagr = (res["final"] / 100.0) ** (1 / yrs) - 1
    peak, maxdd = -1e18, 0.0
    for _, eq in res["curve"]:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return cagr * 100, maxdd * 100

def year_returns(curve):
    by = {}
    for d, eq in curve: by[d[:4]] = eq
    out = {}; prev = None
    for y in sorted(by):
        if prev is not None: out[y] = round((by[y] / prev - 1) * 100, 2)
        prev = by[y]
    return out

def spy_stats():
    days = [d for d in CAL if START <= d <= END]
    sh = (100.0 - 100.0 * COST_RATE) / open_on("SPY", days[0])
    curve = [(d, sh * close_on("SPY", d)) for d in days]
    final = curve[-1][1] - (curve[-1][1] * COST_RATE + SELL_FEE)
    peak, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "year_returns": year_returns(curve)}

def main():
    out_dir = os.path.join(HERE, "cells"); os.makedirs(out_dir, exist_ok=True)
    # ---- INTEGRITY (original form) ----
    daysA = [d for d in CAL if START <= d <= END]
    ia = simulate(START, END, eval_dates(daysA, "monthly", original_monthly=True), mode="original")
    daysB = [d for d in CAL if "2023-01-01" <= d <= END]
    ib = simulate("2023-01-01", END, eval_dates(daysB, "monthly", original_monthly=True), mode="original")
    integrity = {"window_a_final": round(ia["final"], 2), "window_a_orders": ia["orders"],
                 "window_a_costs": round(ia["costs"], 2), "window_b_final": round(ib["final"], 2),
                 "window_b_orders": ib["orders"], "window_b_costs": round(ib["costs"], 2)}
    print("INTEGRITY:", json.dumps(integrity))
    spy = spy_stats(); print("SPY:", json.dumps(spy))
    # ---- SWEEP + PLACEBOS ----
    cells = {}
    for cad in ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]:
        es = eval_dates(daysA, cad)
        res = simulate(START, END, es, mode="v9")
        cagr, maxdd = metrics(res); yr = year_returns(res["curve"])
        twins = []
        for seed in range(20):
            pr = simulate(START, END, es, mode="v9", placebo_seed=seed)
            twins.append(round(pr["final"], 2))
        beaten = sum(1 for x in twins if res["final"] > x)
        cell = {"final": round(res["final"], 2), "cagr_pct": round(cagr, 2), "max_dd_pct": round(maxdd, 2),
                "costs": round(res["costs"], 2), "orders": res["orders"], "halts": res["halts"],
                "restart": res["restart"], "second_halt": res["second_halt"],
                "equity_curve": [[d, round(v, 4)] for d, v in res["curve"]],
                "placebo_twin_finals": twins, "placebo_beaten": beaten,
                "year_returns": yr, "ret_2020_pct": yr.get("2020"), "ret_2022_pct": yr.get("2022")}
        with open(os.path.join(out_dir, f"{cad}.json"), "w") as f: json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                        "placebo_beaten", "ret_2020_pct", "ret_2022_pct")}
        cells[cad]["halts_n"] = len(res["halts"]); cells[cad]["restart"] = res["restart"]
        cells[cad]["second_halt"] = res["second_halt"]
        print(cad, json.dumps(cells[cad]))
    summary = {"integrity": integrity, "spy": spy, "cells": cells}
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f: json.dump(summary, f, indent=2)
    print("DONE")

if __name__ == "__main__":
    main()
