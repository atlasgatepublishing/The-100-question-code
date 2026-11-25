#!/usr/bin/env python3
"""
V13 BEST-RULES - N-PV2 "The Last Seller" (confirmed-exhaustion form).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (spec): broad pxfull pool, trailing-only eligibility
(>=140 prior bars, close >= $5, 20d avg $ volume >= $20M).
Stage 1 climax: volume strictly greater than each of prior 126 sessions
AND close-to-close return <= -1.5%. Stage 2 confirmation within 10
sessions: no close below climax low, a session with volume <= 50% of
climax volume AND close above climax close -> enter next open.
Disarm on any close below climax low. Max 5 positions, 20% of equity
(at confirmation-day close) each. Exits (close-triggered, next-open
fills): close >= climax-day open (recovery), close < climax-day low
(invalidated), or open after 63rd trading day held. NO pot floor.
Costs 0.10%/side + $0.01/sell. Placebos: 20 seeds replaying taken entry
dates with random eligible names, same exit machinery (references from
the drawn name's bar immediately before entry).
Data (read-only): v7/long-hold/data/pxfull_*.json Yahoo payloads,
OHLC x adjclose/close ratio, volume raw.
"""
import bisect
import glob
import json
import os
import random
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START_CASH = 100.0
COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
FRAC = 0.20
TIME_CAP = 63
CONFIRM_WINDOW = 10
END = "2026-11-20"
ROADS = [("LONG", "2010-01-04"), ("DECADE", "2016-11-21"),
         ("CONT", "2019-01-02"), ("VAL", "2023-01-03")]
SEEDS = list(range(1, 21))


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
        self.climax = np.zeros(n, dtype=bool)
        self.climax_rank = np.full(n, np.nan)
        for i in range(n):
            if i >= 20:
                self.adv20[i] = (self.c[i - 19:i + 1] * self.v[i - 19:i + 1]).mean()
            if i >= 127:
                if self.v[i] > self.v[i - 126:i].max() and self.c[i - 1] > 0 \
                        and self.c[i] / self.c[i - 1] - 1 <= -0.015:
                    self.climax[i] = True
                    med = np.median(self.v[i - 20:i])
                    self.climax_rank[i] = self.v[i] / med if med > 0 else np.nan

    def bar_on(self, dstr):
        return self.idx.get(dstr)

    def last_close(self, dstr):
        j = bisect.bisect_right(self.d, dstr) - 1
        return float(self.c[j]) if j >= 0 else None

    def eligible(self, i):
        return (i >= 140 and self.c[i] >= 5.0 and not np.isnan(self.adv20[i])
                and self.adv20[i] >= 20e6)


def confirm_scan(s, i):
    """Climax at bar i. Returns (confirm_bar_idx or None). Pure bar logic."""
    low = s.l[i]
    for j in range(i + 1, min(i + 1 + CONFIRM_WINDOW, len(s.d))):
        if s.c[j] < low:
            return None                      # disarmed: second leg
        if s.v[j] <= 0.5 * s.v[i] and s.c[j] > s.c[i]:
            return j                         # confirmed exhaustion
    return None


def simulate_main(syms, calendar, start, end):
    """Dynamic watch/confirm simulation. Returns result dict."""
    cash = START_CASH
    pos = {}        # sym -> dict(shares, entry_price, buy_cost, climax_open, climax_low, bars_held, entry_date)
    watch = {}      # sym -> dict(climax_idx, climax_low, climax_close, climax_vol, climax_open, rank)
    pending_entries = {}   # entry_date -> [entry dicts]
    pending_exits = {}     # sym -> reason
    curve, trades, rts = [], [], []
    total_costs = 0.0
    taken = []      # (entry_date, sym) actually entered
    census = {"climaxes": 0, "confirmed": 0, "disarmed": 0, "expired": 0,
              "entered": 0, "skipped_slots": 0, "skipped_held": 0}
    days = [d for d in calendar if start <= d <= end]

    def equity_close(d):
        tot = cash
        for sn, p in pos.items():
            px = syms[sn].last_close(d)
            if px is not None:
                tot += p["shares"] * px
        return tot

    for d in days:
        # --- pending exits fill at today's open
        for sn in list(pending_exits):
            if sn not in pos:
                del pending_exits[sn]
                continue
            s = syms[sn]
            i = s.bar_on(d)
            if i is None:
                continue
            px = float(s.o[i])
            p = pos.pop(sn)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
            pnl = (val - cost) - (p["shares"] * p["entry_price"] + p["buy_cost"])
            rts.append({"symbol": sn, "entry_date": p["entry_date"], "exit_date": d,
                        "pnl": round(pnl, 2), "reason": pending_exits[sn]})
            trades.append({"date": d, "symbol": sn, "side": "sell", "price": round(px, 4),
                           "value": round(val, 2), "cost": round(cost, 4),
                           "reason": pending_exits[sn]})
            del pending_exits[sn]
        # --- pending entries fill at today's open
        todays = pending_entries.pop(d, [])
        if todays:
            eq_ref = todays[0]["eq_ref"]
            for e in sorted(todays, key=lambda x: (-x["rank"], x["sym"])):
                sn = e["sym"]
                if len(pos) >= MAX_POS or sn in pos:
                    census["skipped_slots" if len(pos) >= MAX_POS else "skipped_held"] += 1
                    continue
                s = syms[sn]
                i = s.bar_on(d)
                if i is None:
                    continue
                px = float(s.o[i])
                if px <= 0:
                    continue
                value = min(FRAC * eq_ref, cash / (1 + COST))
                if value < 1.0:
                    continue
                cost = COST * value
                shares = value / px
                cash -= value + cost
                total_costs += cost
                pos[sn] = {"shares": shares, "entry_price": px, "buy_cost": cost,
                           "climax_open": e["climax_open"], "climax_low": e["climax_low"],
                           "bars_held": 0, "entry_date": d}
                census["entered"] += 1
                taken.append((d, sn))
                trades.append({"date": d, "symbol": sn, "side": "buy", "price": round(px, 4),
                               "value": round(value, 2), "cost": round(cost, 4),
                               "reason": "confirmed_climax"})
        # --- close-of-day processing: exits, watches, new climaxes
        eq_close = equity_close(d)
        for sn in list(pos):
            s = syms[sn]
            i = s.bar_on(d)
            if i is None:
                continue
            p = pos[sn]
            p["bars_held"] += 1
            if float(s.c[i]) >= p["climax_open"]:
                pending_exits[sn] = "recovery"
            elif float(s.c[i]) < p["climax_low"]:
                pending_exits[sn] = "invalidated"
            elif p["bars_held"] >= TIME_CAP:
                pending_exits[sn] = "time_cap"
        for sn in list(watch):
            s = syms[sn]
            i = s.bar_on(d)
            if i is None:
                continue
            w = watch[sn]
            if i <= w["climax_idx"]:
                continue
            if float(s.c[i]) < w["climax_low"]:
                census["disarmed"] += 1
                del watch[sn]
            elif float(s.v[i]) <= 0.5 * w["climax_vol"] and float(s.c[i]) > w["climax_close"]:
                census["confirmed"] += 1
                del watch[sn]
                if i + 1 < len(s.d):
                    ed = s.d[i + 1]
                    if ed <= end:
                        pending_entries.setdefault(ed, []).append(
                            {"sym": sn, "climax_open": w["climax_open"],
                             "climax_low": w["climax_low"], "rank": w["rank"],
                             "eq_ref": eq_close})
            elif i - w["climax_idx"] >= CONFIRM_WINDOW:
                census["expired"] += 1
                del watch[sn]
        for sn, s in syms.items():
            if sn in pos or sn in watch:
                continue
            i = s.bar_on(d)
            if i is None or not s.climax[i] or not s.eligible(i):
                continue
            census["climaxes"] += 1
            watch[sn] = {"climax_idx": i, "climax_low": float(s.l[i]),
                         "climax_close": float(s.c[i]), "climax_vol": float(s.v[i]),
                         "climax_open": float(s.o[i]),
                         "rank": float(s.climax_rank[i]) if not np.isnan(s.climax_rank[i]) else 0.0}
        curve.append({"date": d, "equity": round(equity_close(d), 4)})
    # --- window-end liquidation at last close
    if pos:
        d = days[-1]
        for sn in list(pos):
            s = syms[sn]
            px = s.last_close(d)
            p = pos.pop(sn)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
            pnl = (val - cost) - (p["shares"] * p["entry_price"] + p["buy_cost"])
            rts.append({"symbol": sn, "entry_date": p["entry_date"], "exit_date": d,
                        "pnl": round(pnl, 2), "reason": "window_end"})
        if curve:
            curve[-1] = {"date": d, "equity": round(cash, 4)}
    return {"final": round(cash, 2), "curve": curve, "trades": trades,
            "round_trips": rts, "costs": round(total_costs, 2),
            "taken": taken, "census": census}


def simulate_placebo(syms, calendar, start, end, taken, seed):
    """Replay taken entry dates with random eligible names; refs from the
    drawn name's bar immediately before its entry bar."""
    rng = random.Random(seed)
    entries = {}
    names = sorted(syms)
    for (ed, orig) in taken:
        for _ in range(50):
            sn = rng.choice(names)
            if sn == orig:
                continue
            s = syms[sn]
            i = s.bar_on(ed)
            if i is None or i < 1 or not s.eligible(i):
                continue
            entries.setdefault(ed, []).append(
                {"sym": sn, "ref_open": float(s.o[i - 1]), "ref_low": float(s.l[i - 1])})
            break
    cash = START_CASH
    pos = {}
    pending_exits = {}
    total_costs = 0.0
    days = [d for d in calendar if start <= d <= end]

    def equity_at(d, use_open=False):
        tot = cash
        for sn, p in pos.items():
            s = syms[sn]
            i = s.bar_on(d)
            px = float(s.o[i]) if (use_open and i is not None) else s.last_close(d)
            if px is not None:
                tot += p["shares"] * px
        return tot

    curve = []
    for d in days:
        for sn in list(pending_exits):
            if sn not in pos:
                del pending_exits[sn]
                continue
            s = syms[sn]
            i = s.bar_on(d)
            if i is None:
                continue
            px = float(s.o[i])
            p = pos.pop(sn)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
            del pending_exits[sn]
        todays = entries.get(d, [])
        if todays:
            eq_open = equity_at(d, use_open=True)
            for e in todays:
                sn = e["sym"]
                if len(pos) >= MAX_POS or sn in pos:
                    continue
                s = syms[sn]
                i = s.bar_on(d)
                if i is None:
                    continue
                px = float(s.o[i])
                if px <= 0:
                    continue
                value = min(FRAC * eq_open, cash / (1 + COST))
                if value < 1.0:
                    continue
                cost = COST * value
                cash -= value + cost
                total_costs += cost
                pos[sn] = {"shares": value / px, "ref_open": e["ref_open"],
                           "ref_low": e["ref_low"], "bars_held": 0}
        for sn in list(pos):
            s = syms[sn]
            i = s.bar_on(d)
            if i is None:
                continue
            p = pos[sn]
            p["bars_held"] += 1
            if float(s.c[i]) >= p["ref_open"]:
                pending_exits[sn] = "recovery"
            elif float(s.c[i]) < p["ref_low"]:
                pending_exits[sn] = "invalidated"
            elif p["bars_held"] >= TIME_CAP:
                pending_exits[sn] = "time_cap"
        curve.append({"date": d, "equity": round(equity_at(d), 4)})
    if pos:
        d = days[-1]
        for sn in list(pos):
            s = syms[sn]
            px = s.last_close(d)
            p = pos.pop(sn)
            val = p["shares"] * px
            cost = COST * val + SELL_FEE
            cash += val - cost
            total_costs += cost
    return {"final": round(cash, 2), "costs": round(total_costs, 2)}


def spy_buyhold(spy, start, end):
    days = [d for d in spy.d if start <= d <= end]
    i0 = spy.bar_on(days[0])
    px0 = float(spy.o[i0])
    shares = (START_CASH / (1 + COST)) / px0
    buy_cost = COST * shares * px0
    px1 = spy.last_close(days[-1])
    val = shares * px1
    sell_cost = COST * val + SELL_FEE
    return round(val - sell_cost, 2)


def period_stats(curve):
    """Calendar-year distribution from the equity curve."""
    years = {}
    prev = START_CASH
    series = []
    for pt in curve:
        series.append((pt["date"], pt["equity"]))
    by_year = {}
    for d, e in series:
        by_year.setdefault(d[:4], []).append(e)
    yr_rets = []
    last = START_CASH
    for y in sorted(by_year):
        e_end = by_year[y][-1]
        yr_rets.append({"year": y, "ret_pct": round((e_end / last - 1) * 100, 2),
                        "end_equity": round(e_end, 2)})
        last = e_end
    rets = [r["ret_pct"] for r in yr_rets]
    # max drawdown + longest stretch between new highs
    peak, maxdd, peak_date, longest_under, cur_under = START_CASH, 0.0, series[0][0] if series else None, 0, 0
    from datetime import date as _date
    last_high = series[0][0] if series else None
    max_gap_days = 0
    for d, e in series:
        if e >= peak:
            if last_high:
                gap = (_date.fromisoformat(d) - _date.fromisoformat(last_high)).days
                max_gap_days = max(max_gap_days, gap)
            peak, last_high = e, d
        maxdd = min(maxdd, e / peak - 1)
    streak, worst_streak = 0, 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {
        "years": yr_rets,
        "median_year_pct": round(float(np.median(rets)), 2) if rets else None,
        "share_years_positive": f"{sum(1 for r in rets if r > 0)}/{len(rets)}" if rets else None,
        "best_year_pct": max(rets) if rets else None,
        "worst_year_pct": min(rets) if rets else None,
        "longest_losing_year_streak": worst_streak,
        "max_drawdown_pct": round(maxdd * 100, 2),
        "longest_stretch_between_new_highs_days": max_gap_days,
    }


def main():
    t0 = time.time()
    files = sorted(glob.glob(os.path.join(DATA, "pxfull_*.json")))
    syms, spy = {}, None
    for f in files:
        name = os.path.basename(f)[len("pxfull_"):-len(".json")]
        s = Sym(name, load_payload(name))
        if name == "SPY":
            spy = s
        else:
            syms[name] = s
    calendar = spy.d
    out = {"family": "novel-pv2-last-seller", "program": "v13-best-rules",
           "roads": {}}
    for road, start in ROADS:
        res = simulate_main(syms, calendar, start, END)
        spy_final = spy_buyhold(spy, start, END)
        placebo_finals = []
        for seed in SEEDS:
            pb = simulate_placebo(syms, calendar, start, END, res["taken"], seed)
            placebo_finals.append(pb["final"])
        placebo_finals_sorted = sorted(placebo_finals)
        beaten = sum(1 for x in placebo_finals if res["final"] > x)
        wins = sum(1 for r in res["round_trips"] if r["pnl"] > 0)
        out["roads"][road] = {
            "window": f"{start}..{END}",
            "final": res["final"],
            "max_drawdown_pct": period_stats(res["curve"])["max_drawdown_pct"],
            "costs": res["costs"],
            "n_round_trips": len(res["round_trips"]),
            "win_rate": f"{wins}/{len(res['round_trips'])}" if res["round_trips"] else "0/0",
            "spy_final": spy_final,
            "placebo_median": float(np.median(placebo_finals)),
            "placebo_beaten": f"{beaten}/20",
            "placebo_finals": placebo_finals_sorted,
            "census": res["census"],
            "period": period_stats(res["curve"]),
            "curve": res["curve"],
            "round_trips": res["round_trips"],
        }
        print(f"{road}: final=${res['final']} SPY=${spy_final} "
              f"placebo_med=${float(np.median(placebo_finals))} beaten={beaten}/20 "
              f"trips={len(res['round_trips'])} census={res['census']}", flush=True)
    out["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("done", out["elapsed_sec"], "s")


if __name__ == "__main__":
    main()
