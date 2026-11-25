#!/usr/bin/env python3
"""
FOLKLORE TEST F-9 — PRESIDENTIAL-CYCLE TIMING. Terry's AI stock app.
Simulation only.

THE SPEC (FROZEN — Spec F-9 in
~/workspace/stock-app/research/v7-completeness/folklore-audit.md, implemented
verbatim; do not improve or reinterpret):

  * Universe/data: SPY only. Term calendar frozen to inaugurations: a
    presidential term runs from January 20 of year 1; *term year 3* = the
    calendar year beginning two years after inauguration year, *term year 4*
    = the following calendar year (e.g. for the term inaugurated Jan 2021:
    year 3 = 2023, year 4 = 2024; for Jan 2025: year 3 = 2027, year 4 = 2028).
  * Rule (frozen): hold SPY from the first trading day of term year 3
    through the last trading day of term year 4; hold cash at all other
    times. Switches at the open of the first session of the period.
  * Standing note from the audit: inside the program's judging windows this
    rule changes position rarely (it is long through 2023-2024 and in cash
    2025-2026 under the current term), so its validation verdict will rest
    on few decisions — the report must state the number of switches
    alongside the result.

FORCED READINGS (stated here, before any result — the spec's own text
forces each of these; none is a tuning choice):
  1. Term years are CALENDAR years by the spec's definition ("term year 3 =
     the calendar year beginning two years after inauguration year"), so
     the January 20 inauguration date creates no intra-year boundary:
     positions can only change at calendar-year boundaries. Term map used:
     term inaugurated Jan 2017 -> years 3-4 = 2019, 2020; Jan 2021 ->
     2023, 2024; Jan 2025 -> 2027, 2028. LONG calendar years inside the
     windows: {2019, 2020, 2023, 2024}; all other years are cash years.
  2. "Switches at the open of the first session of the period": a long
     block opens with a BUY at the open of the first session of term
     year 3; the position is held through the CLOSE of the last trading
     day of term year 4 and sold at the OPEN of the first session of the
     following (cash) period. A "switch" = one such executed rule change
     (buy or sell). The program's end-of-window liquidation (SELL-END) is
     accounting, not a rule switch, and is reported separately.
  3. Both judging windows happen to open exactly on a long-block boundary
     (2019 and 2023 are both term years 3), so each window's first action
     is the rule's own scheduled BUY at the first session's open — no
     mid-period entry reading was needed.
  4. The house plain -15% floor applies at pot level exactly as in the
     champion engine: a daily close <= $85 (not the last day) halts the
     run, liquidates at the next open, and the rule never re-enters.

MECHANICS (identical to the champion engine / CAPE test):
  * $100 pot. Buy cost 0.10% of value; sell cost 0.10% + $0.01.
  * Execution at adjusted opens; marking at adjusted closes (Yahoo
    adjclose-ratio bars from the program's shared cache,
    ~/workspace/stock-app/backtests/v4/data/px_SPY.json — the same series
    the champion's spy_net uses).
  * End of window: liquidate at final close (sell cost applies) so finals
    are post-liquidation cash, like the champion's $544.47.
  * Cash earns nothing (program convention).
  * Windows: continuous ("champion") 2019-01-02 -> 2026-11-20;
    validation 2023-01-01 -> 2026-11-20.
  * RECONCILIATION GATE: SPY buy-hold nets computed with the champion
    engine's spy_net semantics must reproduce the published $313.62
    (continuous) and $187.77 (validation) to the cent before any F-9
    number is trusted; the script aborts if they do not.

SAMPLE SIZE (must travel with every number this script produces): the two
windows contain exactly TWO long episodes (2019-2020, 2023-2024) and two
cash episodes (2021-2022, 2025-2026) — about two presidential terms of
evidence (the 2017 and 2021 terms; the 2025 term contributes only its
cash years 1-2). The verdict grades the rule on this window; it is not
statistical proof about presidential cycles in general.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v4/data/px_SPY.json")
START_CASH = 100.0
FLOOR0 = 85.0
CONTINUOUS = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")

# Inauguration years covering the windows (terms begin every 4 years).
INAUGURATIONS = [2013, 2017, 2021, 2025, 2029]


def term_year(cal_year):
    """Term year (1-4) of a calendar year, per the frozen spec: the term
    inaugurated in January of year Y has term year 3 = calendar year Y+2
    and term year 4 = calendar year Y+3."""
    y0 = max(y for y in INAUGURATIONS if y <= cal_year)
    n = cal_year - y0 + 1
    return n if 1 <= n <= 4 else None


def is_long_year(cal_year):
    return term_year(cal_year) in (3, 4)


# --------------------------------------------------------------------- data
def load_spy_bars():
    with open(DATA, "rb") as f:
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


class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date[d]


def spy_net(book, start, end):
    """Champion engine's buy-hold, verbatim semantics."""
    days = [d for d in book.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = book.bar(first)["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * book.by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2), round(buy_cost + sell_cost, 2)


# --------------------------------------------------------------------- rule
def run_window(book, start, end, label=""):
    days = [d for d in book.dates if start <= d <= end]
    if not days:
        return None
    cash = START_CASH
    shares = 0.0
    total_costs = 0.0
    trades = []
    switches = []          # rule switches only (buys/sells at period opens)
    curve = []
    days_invested = 0
    halted = None

    def equity_close(d):
        return cash + shares * book.by_date[d]["c"]

    for di, d in enumerate(days):
        bar = book.bar(d)
        yr = int(d[:4])
        want_long = is_long_year(yr)
        # Switch at today's open if the period starting today wants a
        # different position than the one held. Desired state changes only
        # at calendar-year boundaries, so this fires exactly at the open
        # of the first session of each period, per the frozen spec.
        if want_long and shares == 0.0 and cash > 0:
            buy_val = cash / 1.001
            c = buy_val * 0.001
            shares = buy_val / bar["o"]
            cash -= buy_val + c
            total_costs += c
            trades.append((d, "BUY", round(shares, 6), round(bar["o"], 4),
                           round(buy_val, 2), round(c, 2)))
            switches.append({"date": d, "action": "BUY",
                             "reason": f"term year 3 begins (term "
                                       f"inaugurated Jan {yr - 2})"})
        elif not want_long and shares > 0:
            val = shares * bar["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, "SELL", round(shares, 6), round(bar["o"], 4),
                           round(val, 2), round(c, 2)))
            switches.append({"date": d, "action": "SELL",
                             "reason": f"term year 4 ended (term "
                                       f"inaugurated Jan {yr - 4}); cash "
                                       f"period begins"})
            shares = 0.0
        v = equity_close(d)
        curve.append((d, v))
        if shares > 0:
            days_invested += 1
        # plain -15% floor: halt, liquidate at next open, never re-enter
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, "SELL-HALT", round(shares, 6),
                               round(book.bar(nd)["o"], 4), round(val, 2),
                               round(c, 2)))
                shares = 0.0
            return finish(label, cash, total_costs, trades, switches, curve,
                          days_invested, len(days), halted)
    # end of window: liquidate at final close (program accounting)
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, "SELL-END", round(shares, 6),
                       round(book.by_date[last]["c"], 4), round(val, 2),
                       round(c, 2)))
        shares = 0.0
    return finish(label, cash, total_costs, trades, switches, curve,
                  days_invested, len(days), None)


def finish(label, cash, costs, trades, switches, curve, days_inv, n_days,
           halted):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst, worst_d = None, None
    year_end = {}
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if worst is None or v < worst:
            worst, worst_d = v, d
        year_end[d[:4]] = round(v, 2)   # last mark of each calendar year
    return {"label": label, "final": round(cash, 2),
            "return_pct": round(cash / START_CASH * 100 - 100, 2),
            "costs": round(costs, 2), "orders": len(trades),
            "switches": len(switches), "switch_log": switches,
            "halted": halted,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst, 2) if worst is not None else None,
            "worst_close_date": worst_d,
            "time_in_market_pct": round(100.0 * days_inv / n_days, 1)
            if n_days else 0.0,
            "days": n_days, "days_invested": days_inv,
            "year_end_marks": year_end,
            "trades": trades}


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print("Term map: " + ", ".join(
        f"{y}=term yr {term_year(y)}{' (LONG)' if is_long_year(y) else ''}"
        for y in range(2019, 2027)))

    # ---- reconciliation gate: SPY buy-hold must reproduce the published
    # champion-window nets to the cent before any F-9 number is trusted.
    for (ws, we), expect in ((CONTINUOUS, 313.62), (VALIDATION, 187.77)):
        got, _ = spy_net(book, ws, we)
        ok = abs(got - expect) < 0.005
        print(f"RECONCILIATION {ws}->{we}: SPY net=${got:,.2f} "
              f"expected=${expect:,.2f} match={ok}", flush=True)
        if not ok:
            raise SystemExit("RECONCILIATION FAILED — F-9 numbers untrusted")

    out = {"strategy": "FOLKLORE F-9 PRESIDENTIAL-CYCLE TIMING: hold SPY "
                       "in term years 3-4 only, cash otherwise; switches "
                       "at the open of the first session of each period; "
                       "$100, plain -15% floor",
           "spec_source": "~/workspace/stock-app/research/v7-completeness/"
                          "folklore-audit.md, Spec F-9 (frozen)",
           "long_calendar_years": [y for y in range(2019, 2029)
                                   if is_long_year(y)],
           "pot": START_CASH, "floor": FLOOR0,
           "sample_size_note": "The two windows contain exactly TWO long "
                               "episodes (2019-2020, 2023-2024) and two "
                               "cash episodes (2021-2022, 2025-2026) — "
                               "about two presidential terms of evidence. "
                               "The verdict grades the rule on this "
                               "window only.",
           "champion_reference": {"continuous": 544.47,
                                  "validation": 288.05},
           "windows": {}}

    for name, (ws, we) in (("continuous_2019_2026", CONTINUOUS),
                           ("validation_2023_2026", VALIDATION)):
        r = run_window(book, ws, we, label=name)
        spy, spy_costs = spy_net(book, ws, we)
        r["spy_net"] = spy
        r["spy_costs"] = spy_costs
        r["vs_spy"] = round(r["final"] - spy, 2)
        out["windows"][name] = r
        print(f"{name}: F-9 ${r['final']:,.2f} ({r['return_pct']:+.2f}%) "
              f"vs SPY ${spy:,.2f} | switches={r['switches']} "
              f"in-market {r['time_in_market_pct']}% "
              f"maxDD {r['max_drawdown_pct']}% orders {r['orders']} "
              f"costs ${r['costs']} halted={r['halted']}", flush=True)
        print(f"   worst close ${r['worst_close']} on "
              f"{r['worst_close_date']} | year-end marks: "
              f"{r['year_end_marks']}", flush=True)

    with open(os.path.join(HERE, "presidential-cycle-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
