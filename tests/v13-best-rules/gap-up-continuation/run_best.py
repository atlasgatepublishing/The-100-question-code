#!/usr/bin/env python3
"""
V13 BEST-RULES — GAP-UP CONTINUATION (daily-bar shadow of gap-and-go).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (spec): signal on gap day t (all known at close of t):
  gap = open_t/prior close - 1 >= +4%; gap held (low_t > prior close,
  close_t > open_t, close in top third of range); gap-day volume >= 2.0x
  mean of prior 20 sessions; close_t above 50-day MA; eligibility from
  trailing bars only (close >= $5, 20d avg dollar volume >= $20M, >=60
  prior bars). Entry next session open. Max 5 positions, 20% of equity
  each, ranked by gap-day RVOL then gap size. Exits (close-triggered,
  next-open fills): close below gap-day low, or after the 5th trading
  day held. NO profit target. NO pot floor. Costs 0.10%/side + $0.01/sell.
Placebos: 20 seeds, matched attempted-entry counts, random eligible
(day, name) pairs, identical machinery.
Reference: v10 published rules re-run on this pool (labeled REFERENCE).

Data (read-only): v7/long-hold/data/pxfull_*.json Yahoo payloads,
OHLC x adjclose/close ratio, volume raw. Pool = 154 names (SPY = bench).
"""
import json
import os
import time
from datetime import date, datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START_CASH = 100.0
COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
FRAC = 0.20
HOLD_DAYS = 5          # exit at open after the 5th trading day held
END = "2026-11-20"
ROADS = [("LONG", "2010-01-04"), ("DECADE", "2016-11-21"),
         ("CONT", "2019-01-02"), ("VAL", "2023-01-03")]
SEEDS = list(range(1, 21))


# ---------------------------------------------------------------- data
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
        self.rvol = np.full(n, np.nan)      # vol vs prior-20 mean
        self.ma50 = np.full(n, np.nan)
        self.adv20 = np.full(n, np.nan)     # trailing 20d avg $ volume (incl today)
        self.volbase_v10 = np.full(n, np.nan)  # mean vol of 20 sess ending 2 ago
        for i in range(n):
            if i >= 20:
                self.rvol[i] = self.v[i] / self.v[i - 20:i].mean() \
                    if self.v[i - 20:i].mean() > 0 else np.nan
                self.adv20[i] = (self.c[i - 19:i + 1] * self.v[i - 19:i + 1]).mean()
            if i >= 49:
                self.ma50[i] = self.c[i - 49:i + 1].mean()
            if i >= 21:
                self.volbase_v10[i] = self.v[i - 21:i - 1].mean()

    def bar_on(self, dstr):
        i = self.idx.get(dstr)
        return i

    def last_close(self, dstr):
        # last close on or before dstr (binary search on sorted dates)
        import bisect
        j = bisect.bisect_right(self.d, dstr) - 1
        return float(self.c[j]) if j >= 0 else None


def eligible(s, i):
    """Trailing-only eligibility at bar i."""
    return (i >= 60 and s.c[i] >= 5.0 and not np.isnan(s.adv20[i])
            and s.adv20[i] >= 20e6)


def gap_signal(s, i):
    """My-rules signal at bar i (evaluated at close of i). Returns dict or None."""
    if i < 60 or not eligible(s, i):
        return None
    pc = s.c[i - 1]
    if pc <= 0:
        return None
    gap = s.o[i] / pc - 1
    if gap < 0.04:
        return None
    if not (s.l[i] > pc and s.c[i] > s.o[i]):
        return None
    rng = s.h[i] - s.l[i]
    if rng > 0 and (s.c[i] - s.l[i]) / rng < 2.0 / 3.0:
        return None
    if np.isnan(s.rvol[i]) or s.rvol[i] < 2.0:
        return None
    if np.isnan(s.ma50[i]) or s.c[i] <= s.ma50[i]:
        return None
    return {"gap": float(gap), "rvol": float(s.rvol[i]), "gap_low": float(s.l[i])}


# ---------------------------------------------------------------- engine
def simulate(calendar, syms, signals_by_entry_date, start, end):
    """signals_by_entry_date: {entry_date: [ {sym, gap_low, rank keys...} ]}
    Entries fill at the entry-date open of the symbol's own bar that day.
    Exits are close-triggered, filled at the next bar's open.
    Returns dict with curve, trades, round_trips, costs."""
    cash = START_CASH
    pos = {}   # sym -> {shares, entry_price, entry_bar_date, gap_low, bars_held_dates}
    curve = []
    trades = []
    rts = []
    total_costs = 0.0
    pending_exits = {}   # sym -> reason (fill at today's open)
    days = [d for d in calendar if start <= d <= end]

    def equity(price_fn):
        tot = cash
        for sname, p in pos.items():
            px = price_fn(sname)
            if px is not None:
                tot += p["shares"] * px
        return tot

    for di, d in enumerate(days):
        # --- exits pending from yesterday's close fill at today's open
        for sname in list(pending_exits):
            if sname not in pos:
                continue
            s = syms[sname]
            i = s.bar_on(d)
            if i is None:
                continue  # no bar today; try next day
            px = float(s.o[i])
            p = pos.pop(sname)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
            pnl = (val - cost) - (p["shares"] * p["entry_price"] + p["buy_cost"])
            rts.append({"symbol": sname, "entry_date": p["entry_date"],
                        "exit_date": d, "pnl": pnl, "reason": pending_exits[sname]})
            trades.append({"date": d, "symbol": sname, "side": "sell",
                           "price": round(px, 4), "value": round(val, 2),
                           "cost": round(cost, 4), "reason": pending_exits[sname]})
            del pending_exits[sname]
        # --- entries at today's open
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
                                    "gap_low": sig["gap_low"], "buy_cost": cost}
                trades.append({"date": d, "symbol": sig["sym"], "side": "buy",
                               "price": round(px, 4), "value": round(value, 2),
                               "cost": round(cost, 4), "reason": "entry"})
        # --- mark to close; exit triggers
        eq_close = equity(lambda sn: syms[sn].last_close(d))
        curve.append((d, eq_close))
        last_day = (di == len(days) - 1)
        for sname, p in list(pos.items()):
            s = syms[sname]
            i = s.bar_on(d)
            if i is None:
                continue
            held_bars = i - p["entry_i"] + 1
            if float(s.c[i]) < p["gap_low"]:
                pending_exits[sname] = "gap-failure"
            elif held_bars >= HOLD_DAYS:
                pending_exits[sname] = "time-exit"
        if last_day:
            # liquidate everything at final close
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
                            "exit_date": d, "pnl": pnl, "reason": "road-end"})
                trades.append({"date": d, "symbol": sname, "side": "sell",
                               "price": round(px, 4), "value": round(val, 2),
                               "cost": round(cost, 4), "reason": "road-end"})
            curve[-1] = (d, cash)
    return {"curve": curve, "trades": trades, "round_trips": rts,
            "total_costs": total_costs, "final": curve[-1][1] if curve else START_CASH}


def build_signals(syms, calendar, start, end):
    """My-rules signals: signal day t in [start-? , end]; entry = symbol's
    next bar after t, which must be a calendar day within the road."""
    cal_set = set(calendar)
    by_entry = {}
    n_signals = 0
    for name, s in syms.items():
        for i in range(60, len(s.d) - 1):
            sig = gap_signal(s, i)
            if sig is None:
                continue
            entry_date = s.d[i + 1]
            if entry_date not in cal_set or not (start <= entry_date <= end):
                continue
            if s.d[i] < start and entry_date > start:
                pass  # signal just before road start, entry inside: allowed
            by_entry.setdefault(entry_date, []).append(
                {"sym": name, "gap_low": sig["gap_low"], "gap": sig["gap"],
                 "rvol": sig["rvol"], "signal_date": s.d[i]})
            n_signals += 1
    for d in by_entry:
        by_entry[d].sort(key=lambda x: (-x["rvol"], -x["gap"]))
    return by_entry, n_signals


def placebo_signals(syms, calendar, start, end, n_attempts, seed):
    rng = np.random.default_rng(seed)
    days = [d for d in calendar if start <= d <= end]
    # eligible (day, sym) pool built lazily per drawn day
    by_entry = {}
    attempts = 0
    guard = 0
    while attempts < n_attempts and guard < n_attempts * 50:
        guard += 1
        d = days[rng.integers(0, len(days) - 6)]
        names = list(syms.keys())
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
            {"sym": name, "gap_low": float(s.l[i]), "gap": 0.0, "rvol": 0.0,
             "signal_date": d})
        attempts += 1
    return by_entry


# ------------------------------------------------------- v10 reference
def run_v10_reference(syms, calendar, start, end):
    """Published v10 rules on this pool, no floor (REFERENCE ONLY)."""
    cash = START_CASH
    pos = {}
    curve = []
    total_costs = 0.0
    n_entries = 0
    days = [d for d in calendar if start <= d <= end]
    for d in days:
        # entries at open
        cands = []
        for name in sorted(syms.keys()):
            s = syms[name]
            i = s.bar_on(d)
            if i is None or i < 22:
                continue
            pc = s.c[i - 1]
            if pc <= 0 or np.isnan(s.volbase_v10[i]):
                continue
            if s.o[i] / pc - 1 > 0.03 and s.v[i - 1] > 1.5 * s.volbase_v10[i]:
                cands.append(name)
        def open_px(sn):
            s = syms[sn]
            i = s.bar_on(d)
            return float(s.o[i]) if i is not None else s.last_close(d)
        eq_open = cash + sum(p["shares"] * (open_px(sn) or 0) for sn, p in pos.items())
        for name in cands:
            if name in pos or len(pos) >= 2:
                continue
            s = syms[name]
            i = s.bar_on(d)
            px = float(s.o[i])
            value = min(0.5 * eq_open, cash / (1 + COST))
            if value < 1.0 or px <= 0:
                continue
            cost = COST * value
            cash -= value + cost
            total_costs += cost
            pos[name] = {"shares": value / px, "entry_price": px,
                         "entry_i": i, "buy_cost": cost}
            n_entries += 1
        # intraday bracket + time exit
        for name in list(pos):
            s = syms[name]
            i = s.bar_on(d)
            if i is None:
                continue
            p = pos[name]
            e = p["entry_price"]
            stop, tgt = e * 0.96, e * 1.08
            o, h, l = float(s.o[i]), float(s.h[i]), float(s.l[i])
            fill = None
            if o <= stop or o >= tgt:
                fill = o
            elif l <= stop and h >= tgt:
                fill = stop
            elif l <= stop:
                fill = stop
            elif h >= tgt:
                fill = tgt
            if fill is None and i - p["entry_i"] >= 3:
                fill = float(s.c[i])
            if fill is not None:
                val = p["shares"] * fill
                cost = COST * val + SELL_FEE
                cash += val - cost
                total_costs += cost
                del pos[name]
        eq_close = cash + sum(p["shares"] * (syms[sn].last_close(d) or 0)
                              for sn, p in pos.items())
        curve.append((d, eq_close))
    # liquidate at end
    d = days[-1]
    for name in list(pos):
        px = syms[name].last_close(d)
        p = pos.pop(name)
        val = p["shares"] * px
        cost = COST * val + SELL_FEE
        cash += val - cost
        total_costs += cost
    curve[-1] = (d, cash)
    return {"final": cash, "curve": curve, "total_costs": total_costs,
            "entries": n_entries}


# ------------------------------------------------------------- scoring
def diagnostics(curve):
    peak, max_dd = START_CASH, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    # longest stretch between new highs (calendar days)
    peak = START_CASH
    last_high = curve[0][0]
    longest = 0
    from datetime import date as _date
    for d, eq in curve:
        if eq >= peak:
            peak = eq
            gap_days = (_date.fromisoformat(d) - _date.fromisoformat(last_high)).days
            longest = max(longest, gap_days)
            last_high = d
    tail = (_date.fromisoformat(curve[-1][0]) - _date.fromisoformat(last_high)).days
    longest = max(longest, tail)
    return {"max_dd_pct": round(max_dd * 100, 2),
            "longest_between_highs_days": longest}


def period_distribution(curve):
    """Calendar-quarter distribution of returns."""
    q = {}
    order = []
    for d, eq in curve:
        key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3 + 1)
        if key not in q:
            q[key] = [eq, eq]
            order.append(key)
        q[key][1] = eq
    rets = []
    prev_end = START_CASH
    for k in order:
        s_, e_ = q[k]
        base = prev_end
        rets.append(e_ / base - 1)
        prev_end = e_
    rets = np.array(rets)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    return {"period": "calendar quarter", "n_periods": len(rets),
            "median_pct": round(float(np.median(rets)) * 100, 2),
            "share_positive_pct": round(float((rets > 0).mean()) * 100, 1),
            "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2),
            "longest_losing_streak_periods": streak,
            "mean_pct_secondary": round(float(rets.mean()) * 100, 2)}


def spy_final(syms, start, end):
    s = syms["SPY"]
    days = [d for d in s.d if start <= d <= end]
    o = float(s.o[s.idx[days[0]]])
    c = float(s.c[s.idx[days[-1]]])
    buy_val = START_CASH / (1 + COST)
    shares = buy_val / o
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
    print(f"pool: {len(syms)} names, calendar {calendar[0]}..{calendar[-1]}",
          flush=True)

    results = {
        "program": "v13-best-rules", "family": "gap-up-continuation",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"gap_min_pct": 4.0, "gap_must_hold": True,
                     "rvol_min": 2.0, "trend": "close > 50d MA",
                     "entry": "next open after confirmed gap day",
                     "max_positions": 5, "frac_each": 0.20,
                     "exits": "close < gap-day low, or after 5th trading day held; next-open fills",
                     "floor": None, "profit_target": None,
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "pool": {"n_names": len(syms),
                 "source": "v7/long-hold/data pxfull_* (read-only)",
                 "caveat": "large-cap pool assembled by earlier programs; names that died before assembly absent (upper-bound tilt, disclosed in spec)"},
        "published_form_official": {"DECADE": 71.47,
                                    "note": "v10 daily cell, 10-name universe, v9 floor chassis"},
        "champion_vm": {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05},
        "spy_reference_given": {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77},
        "roads": {},
    }

    for road, start in ROADS:
        end = END
        by_entry, n_sig = build_signals(syms, calendar, start, end)
        r = simulate(calendar, all_syms, by_entry, start, end)
        n_entries = sum(1 for t in r["trades"] if t["side"] == "buy")
        diag = diagnostics(r["curve"])
        dist = period_distribution(r["curve"])
        # placebos
        pfinals = []
        for seed in SEEDS:
            pb = placebo_signals(syms, calendar, start, end, n_entries, seed)
            pr = simulate(calendar, all_syms, pb, start, end)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        # v10 reference on this pool
        ref = run_v10_reference(syms, calendar, start, end)
        ref_diag = diagnostics(ref["curve"])
        spy = spy_final(all_syms, start, end)
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
                        "median": round(float(np.median(pfinals)), 2),
                        "beaten": beaten},
            "v10_rules_on_this_pool_reference": {
                "final": round(ref["final"], 2), "max_dd_pct": ref_diag["max_dd_pct"],
                "entries": ref["entries"], "total_costs": round(ref["total_costs"], 2)},
            "spy_in_engine": spy,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "round_trips": rts,
        }
        print(f"{road}: final ${r['final']:,.2f} DD {diag['max_dd_pct']}% "
              f"entries {n_entries} placebo beaten {beaten}/20 "
              f"v10ref ${ref['final']:,.2f} SPY ${spy:,.2f} "
              f"({time.time()-t0:.0f}s)", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json", flush=True)


if __name__ == "__main__":
    main()
