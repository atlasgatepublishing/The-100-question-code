#!/usr/bin/env python3
"""
V13 BEST-RULES — JEFF COOPER EXPANSION BREAKOUT. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (spec): setup day t (known at close of t): high above highest high
of prior 40 sessions; range widest of last 10 sessions incl. today; close in
top 25% of range. Eligibility trailing-only (close >= $5, 20d avg dollar
volume >= $20M, >=60 prior bars). Entry next session open (no 1/8 trigger).
Max 5 positions, 20% of equity each, ranked by expansion multiple (setup
range / mean range of prior 9 sessions). Exits (close-triggered, next-open
fills): close below setup-day low, or after the 5th trading day held.
NO profit target. NO pot floor. Costs 0.10%/side + $0.01/sell.
Placebos: 20 seeds, matched attempted-entry counts, random eligible
(day, name) pairs, identical machinery (setup low = low of day before entry).

Data (read-only): v7/long-hold/data/pxfull_*.json Yahoo payloads,
OHLC x adjclose/close ratio, volume raw. Pool = 154 names (SPY = bench).
"""
import bisect
import json
import os
import time
from datetime import date as _date, datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START_CASH = 100.0
COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
FRAC = 0.20
HOLD_DAYS = 5
END = "2026-11-20"
ROADS = [("LONG", "2010-01-04"), ("DECADE", "2016-11-21"),
         ("CONT", "2019-01-02"), ("VAL", "2023-01-03")]
SEEDS = list(range(1, 21))
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 88.20, "DECADE": 94.00, "CONT": 93.91, "VAL": 97.18}  # v12 SPY per-asset native


def load_payload(sym):
    with open(os.path.join(DATA, f"pxfull_{sym}.json"), "rb") as f:
        d = json.loads(f.read())
    r = d["chart"]["result"][0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None or adj[i] is None:
            continue
        ratio = adj[i] / c if c else 1.0
        rows.append({
            "d": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
            "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
            "l": q["low"][i] * ratio, "c": adj[i],
            "v": float(q["volume"][i] or 0),
        })
    rows.sort(key=lambda b: b["d"])
    return rows


class Sym:
    def __init__(self, name, rows):
        self.name = name
        self.d = [r["d"] for r in rows]
        self.o = np.array([r["o"] for r in rows])
        self.h = np.array([r["h"] for r in rows])
        self.l = np.array([r["l"] for r in rows])
        self.c = np.array([r["c"] for r in rows])
        self.v = np.array([r["v"] for r in rows])
        self.idx = {d: i for i, d in enumerate(self.d)}
        n = len(rows)
        self.adv20 = np.full(n, np.nan)
        for i in range(n):
            if i >= 20:
                self.adv20[i] = (self.c[i - 19:i + 1] * self.v[i - 19:i + 1]).mean()
        self.rng = self.h - self.l

    def bar_on(self, dstr):
        return self.idx.get(dstr)

    def last_close(self, dstr):
        j = bisect.bisect_right(self.d, dstr) - 1
        return float(self.c[j]) if j >= 0 else None


def eligible(s, i):
    return (i >= 60 and s.c[i] >= 5.0 and not np.isnan(s.adv20[i])
            and s.adv20[i] >= 20e6)


def cooper_signal(s, i):
    if i < 60 or not eligible(s, i):
        return None
    if not (s.h[i] > s.h[i - 40:i].max()):
        return None
    rng = s.rng[i]
    if rng <= 0 or rng < s.rng[i - 9:i + 1].max():
        return None
    if (s.c[i] - s.l[i]) / rng < 0.75:
        return None
    prior9 = s.rng[i - 9:i].mean()
    expansion = float(rng / prior9) if prior9 > 0 else 0.0
    return {"setup_low": float(s.l[i]), "expansion": expansion}


def simulate(calendar, syms, signals_by_entry_date, start, end):
    cash = START_CASH
    pos = {}
    curve = []
    trades = []
    rts = []
    total_costs = 0.0
    pending_exits = {}
    days = [d for d in calendar if start <= d <= end]

    def equity(price_fn):
        tot = cash
        for sname, p in pos.items():
            px = price_fn(sname)
            if px is not None:
                tot += p["shares"] * px
        return tot

    for di, d in enumerate(days):
        for sname in list(pending_exits):
            if sname not in pos:
                continue
            s = syms[sname]
            i = s.bar_on(d)
            if i is None:
                continue
            px = float(s.o[i])
            p = pos.pop(sname)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
            pnl = (val - cost) - (p["shares"] * p["entry_price"] + p["buy_cost"])
            rts.append({"symbol": sname, "entry_date": p["entry_date"],
                        "exit_date": d, "pnl": round(pnl, 4), "reason": pending_exits[sname]})
            trades.append({"date": d, "symbol": sname, "side": "sell",
                           "price": round(px, 4), "value": round(val, 2),
                           "cost": round(cost, 4), "reason": pending_exits[sname]})
            del pending_exits[sname]
        todays = signals_by_entry_date.get(d, [])
        if todays:
            def open_px(sname):
                s = syms[sname]
                i = s.bar_on(d)
                return float(s.o[i]) if i is not None else s.last_close(d)
            eq_open = equity(open_px)
            for sig in todays:
                if len(pos) >= MAX_POS or sig["sym"] in pos:
                    continue
                s = syms[sig["sym"]]
                i = s.bar_on(d)
                if i is None:
                    continue
                px = float(s.o[i])
                if px <= 0:
                    continue
                target = FRAC * eq_open
                value = min(target, cash / (1 + COST))
                if value < 1.0:
                    continue
                cost = COST * value
                shares = value / px
                cash -= value + cost
                total_costs += cost
                pos[sig["sym"]] = {"shares": shares, "entry_price": px,
                                   "entry_date": d, "entry_i": i,
                                   "setup_low": sig["setup_low"], "buy_cost": cost}
                trades.append({"date": d, "symbol": sig["sym"], "side": "buy",
                               "price": round(px, 4), "value": round(value, 2),
                               "cost": round(cost, 4), "reason": "entry"})
        eq_close = equity(lambda sn: syms[sn].last_close(d))
        curve.append((d, eq_close))
        last_day = (di == len(days) - 1)
        for sname, p in list(pos.items()):
            s = syms[sname]
            i = s.bar_on(d)
            if i is None:
                continue
            held_bars = i - p["entry_i"] + 1
            if float(s.c[i]) < p["setup_low"]:
                pending_exits[sname] = "setup-failure"
            elif held_bars >= HOLD_DAYS:
                pending_exits[sname] = "time-exit"
        if last_day:
            for sname in list(pos):
                s = syms[sname]
                px = s.last_close(d)
                p = pos.pop(sname)
                val = p["shares"] * px
                cost = COST * val + SELL_FEE
                cash += val - cost
                total_costs += cost
                pnl = (val - cost) - (p["shares"] * p["entry_price"] + p["buy_cost"])
                rts.append({"symbol": sname, "entry_date": p["entry_date"],
                            "exit_date": d, "pnl": round(pnl, 4), "reason": "road-end"})
                trades.append({"date": d, "symbol": sname, "side": "sell",
                               "price": round(px, 4), "value": round(val, 2),
                               "cost": round(cost, 4), "reason": "road-end"})
            curve[-1] = (d, cash)
    return {"curve": curve, "trades": trades, "round_trips": rts,
            "total_costs": total_costs, "final": curve[-1][1] if curve else START_CASH}


def build_signals(syms, calendar, start, end):
    cal_set = set(calendar)
    by_entry = {}
    n_signals = 0
    for name, s in syms.items():
        for i in range(60, len(s.d) - 1):
            sig = cooper_signal(s, i)
            if sig is None:
                continue
            entry_date = s.d[i + 1]
            if entry_date not in cal_set or not (start <= entry_date <= end):
                continue
            by_entry.setdefault(entry_date, []).append(
                {"sym": name, "setup_low": sig["setup_low"],
                 "expansion": sig["expansion"], "signal_date": s.d[i]})
            n_signals += 1
    for d in by_entry:
        by_entry[d].sort(key=lambda x: -x["expansion"])
    return by_entry, n_signals


def placebo_signals(syms, calendar, start, end, n_attempts, seed):
    rng = np.random.default_rng(seed)
    days = [d for d in calendar if start <= d <= end]
    names = list(syms.keys())
    by_entry = {}
    attempts = 0
    guard = 0
    while attempts < n_attempts and guard < n_attempts * 50:
        guard += 1
        d = days[rng.integers(0, len(days) - 6)]
        name = names[rng.integers(0, len(names))]
        s = syms[name]
        i = s.bar_on(d)
        if i is None or i < 60 or i + 1 >= len(s.d):
            continue
        if not eligible(s, i):
            continue
        entry_date = s.d[i + 1]
        if not (start <= entry_date <= end):
            continue
        by_entry.setdefault(entry_date, []).append(
            {"sym": name, "setup_low": float(s.l[i]), "expansion": 0.0,
             "signal_date": d})
        attempts += 1
    return by_entry


def diagnostics(curve):
    peak, max_dd = START_CASH, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    peak = START_CASH
    last_high = curve[0][0]
    longest = 0
    for d, eq in curve:
        if eq >= peak:
            peak = eq
            longest = max(longest, (_date.fromisoformat(d) - _date.fromisoformat(last_high)).days)
            last_high = d
    longest = max(longest, (_date.fromisoformat(curve[-1][0]) - _date.fromisoformat(last_high)).days)
    return {"max_dd_pct": round(max_dd * 100, 2),
            "longest_between_highs_days": longest}


def period_distribution(curve):
    months = {}
    for d, eq in curve:
        months[d[:7]] = eq
    ks = sorted(months)
    rets = []
    prev = START_CASH
    for k in ks:
        rets.append(months[k] / prev - 1 if prev > 0 else 0.0)
        prev = months[k]
    rets = np.array(rets)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    return {"period": "calendar month", "n_periods": len(rets),
            "median_pct": round(float(np.median(rets)) * 100, 2),
            "share_positive_pct": round(float((rets > 0).mean()) * 100, 1),
            "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2),
            "longest_losing_streak_periods": int(streak),
            "mean_pct_secondary": round(float(rets.mean()) * 100, 2)}


def spy_final(syms, start, end):
    s = syms["SPY"]
    days = [d for d in s.d if start <= d <= end]
    o = float(s.o[s.idx[days[0]]])
    c = float(s.c[s.idx[days[-1]]])
    shares = (START_CASH / (1 + COST)) / o
    sell_val = shares * c
    return round(sell_val - (COST * sell_val + SELL_FEE), 2)


def main():
    t0 = time.time()
    files = sorted(f for f in os.listdir(DATA)
                   if f.startswith("pxfull_") and f.endswith(".json"))
    names = [f[7:-5] for f in files]
    syms = {}
    for n in names:
        if n == "SPY":
            continue
        syms[n] = Sym(n, load_payload(n))
    spy = Sym("SPY", load_payload("SPY"))
    all_syms = dict(syms)
    all_syms["SPY"] = spy
    calendar = spy.d
    print(f"pool: {len(syms)} names, calendar {calendar[0]}..{calendar[-1]}", flush=True)

    results = {
        "program": "v13-best-rules", "family": "hunt-cooper-expansion-breakout",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"setup": "new 40-session high + widest range of last 10 + close in top 25%",
                     "entry": "next session open (1/8 trigger dropped)",
                     "max_positions": 5, "frac_each": 0.20,
                     "rank": "expansion multiple (setup range / mean prior-9 range)",
                     "exits": "close < setup-day low, or after 5th trading day held; next-open fills",
                     "floor": None, "profit_target": None,
                     "costs": "0.10%/side + $0.01 per sell order", "start_cash": 100.0},
        "pool": {"n_names": len(syms), "source": "v7/long-hold/data pxfull_* (read-only)",
                 "caveat": "large-cap pool assembled by earlier programs; names that died before assembly absent (upper-bound tilt, disclosed in spec)"},
        "published_form_v12_spy_per_asset": PUBLISHED,
        "champion_vm": CHAMP, "spy_reference_given": SPYREF,
        "roads": {},
    }

    for road, start in ROADS:
        end = END
        by_entry, n_sig = build_signals(syms, calendar, start, end)
        r = simulate(calendar, all_syms, by_entry, start, end)
        n_entries = sum(1 for t in r["trades"] if t["side"] == "buy")
        diag = diagnostics(r["curve"])
        dist = period_distribution(r["curve"])
        pfinals = []
        for seed in SEEDS:
            pb = placebo_signals(syms, calendar, start, end, n_entries, seed)
            pr = simulate(calendar, all_syms, pb, start, end)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        spyf = spy_final(all_syms, start, end)
        rts = r["round_trips"]
        wins = [x for x in rts if x["pnl"] > 0]
        results["roads"][road] = {
            "window": [start, end],
            "final": round(r["final"], 2),
            "max_dd_pct": diag["max_dd_pct"],
            "longest_between_highs_days": diag["longest_between_highs_days"],
            "signals": n_sig, "entries": n_entries,
            "closed_trades": len(rts),
            "win_rate_pct": round(100 * len(wins) / len(rts), 1) if rts else None,
            "total_costs": round(r["total_costs"], 2),
            "period_distribution": dist,
            "placebo": {"seeds": 20, "finals": pfinals,
                        "median": round(float(np.median(pfinals)), 2), "beaten": beaten},
            "spy_in_engine": spyf,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "round_trips": rts,
        }
        print(f"{road}: final ${r['final']:,.2f} DD {diag['max_dd_pct']}% entries {n_entries} "
              f"signals {n_sig} placebo beaten {beaten}/20 SPY ${spyf:,.2f} ({time.time()-t0:.0f}s)", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json", flush=True)


if __name__ == "__main__":
    main()
