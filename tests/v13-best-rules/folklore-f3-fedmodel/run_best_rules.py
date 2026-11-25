#!/usr/bin/env python3
"""
F-3 FED MODEL (trailing-earnings PROXY) — v13 BEST-RULES PASS.

Design frozen in BEST-RULES-SPEC.md before this run:
  Quarterly checks (last trading day of Mar/Jun/Sep/Dec, decided at close,
  executed next open). Signal = Shiller trailing E/P - GS10 spread (pp),
  one-month publication lag. Transform = percentile rank of the spread
  within its trailing 120 monthly readings. SPY weight ladder by
  percentile: >=80 -> 100%, 60-80 -> 85%, 40-60 -> 70%, 20-40 -> 55%,
  <20 -> 40%. Cash 0%. Costs 0.10%/side + $0.01 per sell order.
  NO -15% floor (spec Diagnosis 5).

DATA (read-only shared inputs):
  * Shiller monthly series: the v10 folder's cached live-Shiller CSV
    (shillerdata.com source; NOT FRED -- FRED terms prohibit AI
    training/caching, and no FRED series is used anywhere here).
  * SPY bars: program shared cache backtests/v7/long-hold/data/
    pxfull_SPY.json (same series the v10 integrity gate verified).

INTEGRITY GATE: re-runs the v10 house form (month-end binary, his-rules
single-episode -15% floor) through this plumbing; must reproduce
CONT $196.05 / VAL $117.37 to the cent before any v13 number is taken.

PLACEBOS: 20 seeds per road -- circular shifts of the road's realized
quarterly target-weight sequence, same costs.
"""
import csv
import datetime as dt
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SHILLER_CSV = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/folklore-f3-fedmodel/"
    "shiller_monthly.csv")
START_CASH = 100.0
ROADS = {
    "LONG": ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT": ("2019-01-02", "2026-11-20"),
    "VAL": ("2023-01-03", "2026-11-20"),
}
HOUSE_FORM = {"LONG": 514.45, "DECADE": 229.92, "CONT": 196.05, "VAL": 117.37}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PLACEBO_SEEDS = list(range(1, 21))


# --------------------------------------------------------------------- data
def load_spy_bars():
    with open(SPY_PATH, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_shiller_csv():
    """-> {yyyymm: {p, e, gs10}} from the v10 cached live-Shiller CSV."""
    rows = {}
    with open(SHILLER_CSV) as f:
        for r in csv.DictReader(f):
            rows[r["month"]] = {"p": float(r["price"]),
                                "e": float(r["earnings_trailing"]),
                                "gs10": float(r["gs10_pct"])}
    return rows


class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date[d]


# ------------------------------------------------------- spread + percentile
class SpreadSeries:
    """Monthly spread S = trailing E/P - GS10 (pp), keyed by source month.
    Reading for an evaluation in month M is the row for month M-1
    (one-month publication lag, the program's standing PIT guard)."""

    def __init__(self, rows):
        self.rows = rows
        self.months = sorted(rows)
        self.spread = {m: rows[m]["e"] / rows[m]["p"] * 100.0 - rows[m]["gs10"]
                       for m in self.months}

    def reading_month_for(self, date):
        yr, mo = int(date[:4]), int(date[5:7])
        mo -= 1
        if mo == 0:
            yr, mo = yr - 1, 12
        target = f"{yr:04d}-{mo:02d}"
        if target in self.rows:
            return target
        prior = [m for m in self.months if m < target]
        return prior[-1] if prior else None

    def percentile(self, date):
        """Percentile rank of the current spread within the trailing 120
        monthly spread readings ending at the current reading (PIT)."""
        rm = self.reading_month_for(date)
        if rm is None:
            raise SystemExit(f"no Shiller reading usable at {date}")
        idx = self.months.index(rm)
        window = [self.spread[m] for m in self.months[max(0, idx - 119):idx + 1]]
        cur = self.spread[rm]
        pct = 100.0 * sum(1 for v in window if v <= cur) / len(window)
        return pct, cur, rm, len(window)


def weight_for(pct):
    if pct >= 80:
        return 1.00
    if pct >= 60:
        return 0.85
    if pct >= 40:
        return 0.70
    if pct >= 20:
        return 0.55
    return 0.40


# ------------------------------------------------------------- v13 simulator
def simulate_weights(book, start, end, check_dates, weights):
    """check_dates[0] is the entry check (executed at the window's first
    open); later checks are decided at that day's close and executed at
    the next open. Trades only the delta to the target weight.
    Costs 0.10%/side + $0.01 per sell order. End: liquidate at final
    close. No floor."""
    days = [d for d in book.dates if start <= d <= end]
    assert len(check_dates) == len(weights)
    cash, shares = START_CASH, 0.0
    total_costs, trades, curve = 0.0, [], []
    days_invested = 0
    pending = weights[0]
    dec_set = {d: i for i, d in enumerate(check_dates[1:], start=1)}
    for d in days:
        bar = book.bar(d)
        if pending is not None:
            equity_open = cash + shares * bar["o"]
            target_val = pending * equity_open
            cur_val = shares * bar["o"]
            delta = target_val - cur_val
            if delta > 0.01 and cash > 0:
                buy_val = delta
                c = buy_val * 0.001
                if buy_val + c > cash:
                    buy_val = cash / 1.001
                    c = buy_val * 0.001
                shares += buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append([d, "BUY", round(buy_val, 2), round(c, 2)])
            elif delta < -0.01 and shares > 0:
                sell_val = min(-delta, cur_val)
                c = sell_val * 0.001 + 0.01
                shares -= sell_val / bar["o"]
                if shares < 1e-9:
                    shares = 0.0
                cash += sell_val - c
                total_costs += c
                trades.append([d, "SELL", round(sell_val, 2), round(c, 2)])
            pending = None
        if d in dec_set:
            pending = weights[dec_set[d]]
        v = cash + shares * bar["c"]
        curve.append([d, round(v, 4)])
        if shares > 0:
            days_invested += 1
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append([last, "SELL-END", round(val, 2), round(c, 2)])
        shares = 0.0
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(total_costs, 2), "orders": len(trades),
            "trades": trades, "curve": curve,
            "time_in_market_pct": round(100.0 * days_invested / len(days), 1)}


def quarterly_check_dates(book, start, end):
    """Last trading day of each calendar quarter (Mar/Jun/Sep/Dec).
    Returns (entry_check, in_window_checks): entry_check is the last
    quarterly check on/before the window start."""
    all_days = book.dates
    checks = []
    seen = set()
    for d in all_days:
        if d[5:7] in ("03", "06", "09", "12"):
            key = (d[:4], d[5:7])
            seen.add(key)
    for key in sorted(seen):
        dd = [d for d in all_days if d[:4] == key[0] and d[5:7] == key[1]]
        if dd:
            checks.append(dd[-1])
    entry = [d for d in checks if d <= start][-1]
    in_window = [d for d in checks if start < d < end]
    return entry, in_window


def distribution(curve, start):
    """Per-period (calendar-year) distribution + longest stretch between
    new highs, per PROGRAM reporting rule."""
    by_year = {}
    for d, v in curve:
        by_year[d[:4]] = v  # last value of the year wins (iterated in order)
    years = sorted(by_year)
    rets = []
    prev = START_CASH
    for y in years:
        rets.append((y, by_year[y] / prev - 1.0))
        prev = by_year[y]
    vals = sorted(r for _, r in rets)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    pos = sum(1 for r in vals if r > 0)
    streak = longest = 0
    for _, r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    peak, peak_i, longest_gap = -1.0, 0, 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak, peak_i = v, i
        longest_gap = max(longest_gap, i - peak_i)
    return {
        "year_returns_pct": [[y, round(r * 100, 2)] for y, r in rets],
        "median_year_pct": round(median * 100, 2),
        "share_years_positive_pct": round(100.0 * pos / n, 1),
        "best_year_pct": round(max(vals) * 100, 2),
        "worst_year_pct": round(min(vals) * 100, 2),
        "longest_losing_streak_years": longest,
        "longest_stretch_between_new_highs_days": longest_gap,
    }


# ------------------------------------------- integrity: v10 house form clone
def simulate_binary(book, eval_dates, targets, start, end, start_cash,
                    floor_abs):
    """Copied mechanics from the v10 sweep's simulate() (single episode,
    his-rules floor): entry target executed at first open; later evals
    decided at close, executed next open; floor breach at close ->
    liquidate next open; end liquidate at final close."""
    days = [d for d in book.dates if start <= d <= end]
    cash, shares = start_cash, 0.0
    total_costs = 0.0
    pending = "SPY" if targets[0] == "SPY" else None
    dec_set = {d: i for i, d in enumerate(eval_dates[1:], start=1)}
    for di, d in enumerate(days):
        bar = book.bar(d)
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                shares = 0.0
            pending = None
        if d in dec_set:
            tgt = targets[dec_set[d]]
            cur = "SPY" if shares > 0 else "CASH"
            if tgt != cur:
                pending = tgt
        v = cash + shares * bar["c"]
        if v <= floor_abs and di < len(days) - 1:
            nd = days[di + 1]
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                shares = 0.0
            return round(cash, 2)
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
    return round(cash, 2)


def month_end_days(book, start, end):
    seen = set()
    for d in book.dates:
        if start <= d <= end:
            seen.add(d[:7])
    out = []
    for m in sorted(seen):
        dd = [d for d in book.dates if d[:7] == m and start <= d <= end]
        if dd:
            out.append(dd[-1])
    return out


def original_form_run(book, spreads, start, end):
    entry_cands = month_end_days(book, book.dates[0], start)
    entry = entry_cands[-1]
    evals = [entry] + [d for d in month_end_days(book, start, end)
                       if d != entry]

    def target(date):
        rm = spreads.reading_month_for(date)
        return "SPY" if spreads.spread[rm] > 0 else "CASH"

    targets = [target(d) for d in evals]
    return simulate_binary(book, evals, targets, start, end, START_CASH, 85.0)


def spy_buyhold(book, start, end):
    days = [d for d in book.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = book.bar(first)["o"]
    sh = (START_CASH / 1.001) / o
    val = sh * book.by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    peak, maxdd = -1.0, 0.0
    for d in days:
        v = sh * book.bar(d)["c"]
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(val - sell_cost, 2),
            "max_dd_pct": round(maxdd * 100, 2)}


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    rows = load_shiller_csv()
    spreads = SpreadSeries(rows)
    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print(f"Shiller months: {spreads.months[0]} -> {spreads.months[-1]}")

    # ---- integrity gate: house form must reproduce to the cent
    integrity = {"status": "reproduced", "reproduced_finals": {}}
    for name in ("CONT", "VAL"):
        r = original_form_run(book, spreads, *ROADS[name])
        integrity["reproduced_finals"][name] = r
        ok = abs(r - HOUSE_FORM[name]) < 0.005
        print(f"INTEGRITY {name}: reproduced=${r:,.2f} "
              f"published=${HOUSE_FORM[name]:,.2f} match={ok}")
        if not ok:
            integrity["status"] = "FAILED"
    if integrity["status"] == "FAILED":
        raise SystemExit("INTEGRITY FAILED -- v13 run aborted")

    results = {
        "slug": "folklore-f3-fedmodel",
        "program": "v13-best-rules",
        "label": "TRAILING-EARNINGS PROXY under Claude-designed rules; "
                 "NOT Yardeni's native forward-consensus model "
                 "(paywalled, UNBUILDABLE-NATIVE per v11; degenerate "
                 "constant-buy on the free FactSet vintages per v12).",
        "yield_source": "Shiller GS10 from the live Shiller dataset "
                        "(shillerdata.com), cached CSV in the v10 folder "
                        "(read-only). FRED not used (terms prohibit AI "
                        "training/caching).",
        "integrity": integrity,
        "champion": CHAMPION, "spy_reference": SPY_REF,
        "house_form": HOUSE_FORM,
        "roads": {},
    }

    for name, (start, end) in ROADS.items():
        entry, in_window = quarterly_check_dates(book, start, end)
        checks = [entry] + in_window
        sig_log, weights = [], []
        for d in checks:
            pct, cur, rm, nw = spreads.percentile(d)
            w = weight_for(pct)
            weights.append(w)
            sig_log.append({"check_date": d, "reading_month": rm,
                            "spread_pp": round(cur, 3),
                            "percentile": round(pct, 1),
                            "window_n": nw, "weight": w})
        r = simulate_weights(book, start, end, checks, weights)
        spy = spy_buyhold(book, start, end)
        # placebos: circular shifts of the realized weight sequence
        n = len(weights)
        placebo_finals = {}
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            shift = rng.randrange(1, n)
            shifted = [weights[(i + shift) % n] for i in range(n)]
            pr = simulate_weights(book, start, end, checks, shifted)
            placebo_finals[str(seed)] = pr["final"]
        beaten = sum(1 for v in placebo_finals.values() if v < r["final"])
        dist = distribution(r["curve"], start)
        years_span = (dt.date.fromisoformat(end) -
                      dt.date.fromisoformat(start)).days / 365.25
        results["roads"][name] = {
            "window": {"start": start, "end": end},
            "final": r["final"],
            "cagr_pct": round(((r["final"] / START_CASH) **
                               (1 / years_span) - 1) * 100, 2),
            "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"],
            "time_in_market_pct": r["time_in_market_pct"],
            "avg_weight_pct": round(100.0 * sum(weights) / len(weights), 1),
            "spy_final": spy["final"], "spy_max_dd_pct": spy["max_dd_pct"],
            "house_form_final": HOUSE_FORM[name],
            "champion_final": CHAMPION[name],
            "placebo_beaten": beaten, "placebo_finals": placebo_finals,
            "distribution": dist,
            "signal_log": sig_log,
            "trades": r["trades"],
            "equity_curve": r["curve"],
        }
        print(f"{name:7s}: final=${r['final']:,.2f} CAGR "
              f"{results['roads'][name]['cagr_pct']}% maxDD "
              f"{r['max_dd_pct']}% costs ${r['costs']} orders "
              f"{r['orders']} avgW {results['roads'][name]['avg_weight_pct']}% "
              f"SPY=${spy['final']:,.2f} house=${HOUSE_FORM[name]:,.2f} "
              f"champ=${CHAMPION[name]:,.2f} placebo {beaten}/20",
              flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
