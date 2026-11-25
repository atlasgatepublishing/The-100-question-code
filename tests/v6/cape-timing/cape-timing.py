#!/usr/bin/env python3
"""
CAPE VALUATION TIMING (Shiller CAPE market timing) — Terry's AI stock app.
Simulation only.

THE RULE (standard published form, fixed a priori — no tuning, no searched
thresholds):
  * Trade SPY only. Check quarterly, at quarter-end (last trading day of
    Mar / Jun / Sep / Dec); decide at that close, execute at the next
    trading day's open — the champion engine's mechanics.
  * Signal = Shiller CAPE (price / 10-yr average inflation-adjusted EPS).
    - CAPE in its TOP HISTORICAL QUARTILE (>= expanding 75th percentile)
      -> hold CASH.
    - CAPE below its expanding long-run MEDIAN -> hold SPY fully.
    - Between median and top quartile -> hold SPY.
    (Binary published-style form: the only exit trigger is the top
    quartile. Thresholds are the standard median / 75th-percentile pair,
    taken as given — no alternatives were tried.)
  * Expanding statistics: median and 75th percentile (linear
    interpolation, the champion engine's _pct) over ALL monthly CAPE
    values from January 1926 through the value used — never future data.

POINT-IN-TIME DISCIPLINE:
  * CAPE source: multpl.com "Shiller PE Ratio by Month" table (multpl
    republishes Shiller's Yale series; Shiller's own ie_data.xls was
    unreachable from this VM — connection failure, documented in the
    report). Multpl dates each monthly value on the 1st of a month.
  * At a quarter-end decision in month M, the rule uses the multpl value
    dated the 1st of month M — i.e. the CAPE computed from data through
    roughly the end of month M-1, published during month M. That is the
    trailing published value knowable at the decision date (~1-month
    publication lag), NOT the quarter-end month's own CAPE.
  * Limits (stated in the report): multpl carries the CURRENT vintage of
    Shiller's series; historical CAPE values embed later earnings
    revisions, so they are not a true vintage archive. This is the same
    limitation carried by essentially all published CAPE-timing
    backtests, and it is small next to the effect measured here.

MECHANICS (identical to the champion engine, value-momentum-plainfloor):
  * $100 pot. Buy cost 0.10% of value; sell cost 0.10% + $0.01.
  * Plain -15% floor: end-of-day close equity <= $85 (and not the last
    day) -> halt, liquidate at next open, final = cash after costs.
  * End of window: liquidate at final close (sell cost applies), so all
    finals are post-liquidation cash, like the champion's $544.47.
  * SPY prices: Yahoo adjusted (adjclose-ratio) daily bars, the program's
    shared cache — the same series the champion's spy_net uses, so
    identical-window SPY buy-hold nets reconcile against the published
    $313.62 (2019->2026) and $187.77 (2023->2026).
  * Window entry: the pot enters in whatever position the rule dictated
    at the most recent quarter-end check on or before the window start
    (the strategy is always-on; there is no artificial invested stub
    quarter), executed at the window's first open.
"""
import json
import math
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
START_CASH = 100.0
FLOOR0 = 85.0
HIST_START = "1926-01"          # expanding-stats history begins Jan 1926
FULL = ("2017-01-01", "2026-11-20")
CHAMPION = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")


# --------------------------------------------------------------------- data
def load_spy_bars():
    path = os.path.join(HERE, "data", "px_SPY.json")
    with open(path, "rb") as f:
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


def load_cape():
    """Parse the saved multpl by-month table -> [(yyyymm, value)] sorted.
    Also writes cape_monthly.csv alongside for auditability."""
    html = open(os.path.join(HERE, "multpl_by_month.html")).read()
    pat = re.compile(
        r"<td>([A-Z][a-z]{2}) \d{1,2}, (\d{4})</td>\s*<td>\s*(?:&#x2002;)?\s*([0-9]+(?:\.[0-9]+)?)")
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
              "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
              "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    rows = {}
    for mon, yr, val in pat.findall(html):
        rows[f"{yr}-{months[mon]}"] = float(val)
    out = sorted(rows.items())
    with open(os.path.join(HERE, "cape_monthly.csv"), "w") as f:
        f.write("month,cape\n")
        for m, v in out:
            f.write(f"{m},{v}\n")
    return out


def _pct(sorted_vals, q):
    """Percentile with linear interpolation (numpy 'linear') — copied
    verbatim from the champion engine."""
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


# ------------------------------------------------------------------- signal
class CapeSignal:
    def __init__(self, cape_rows):
        self.rows = cape_rows                     # [(yyyymm, value)] sorted
        self.by_month = dict(cape_rows)

    def value_for_decision(self, decision_date):
        """CAPE usable at a decision on decision_date: the value dated the
        1st of the decision month (trailing published value, ~1-month lag).
        Returns (cape_month, cape_value)."""
        m = decision_date[:7]
        if m in self.by_month:
            return m, self.by_month[m]
        # fall back to the latest value dated before the decision month
        prior = [k for k in self.by_month if k < m]
        if not prior:
            return None, None
        k = max(prior)
        return k, self.by_month[k]

    def zone(self, decision_date):
        """Returns dict with cape, median, q3, zone for a decision date.
        Expanding stats use every monthly value from HIST_START through
        the used value's month, inclusive."""
        m, cape = self.value_for_decision(decision_date)
        if cape is None:
            return None
        hist = sorted(v for k, v in self.rows if HIST_START <= k <= m)
        med = _pct(hist, 0.50)
        q3 = _pct(hist, 0.75)
        if cape >= q3:
            zone = "top-quartile"
        elif cape < med:
            zone = "below-median"
        else:
            zone = "middle"
        return {"cape_month": m, "cape": cape, "median": med, "q3": q3,
                "zone": zone, "target": "CASH" if zone == "top-quartile" else "SPY",
                "n_hist": len(hist)}


# ------------------------------------------------------------------- engine
class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date.get(d)

    def close_on_or_before(self, d):
        # bars are daily trading days; walk back via index
        import bisect
        i = bisect.bisect_right(self.dates, d) - 1
        return self.bars[i]["c"] if i >= 0 else None


def quarter_end_days(book, start, end):
    """Last trading day of each Mar/Jun/Sep/Dec within [start, end]."""
    out, seen = [], set()
    for d in book.dates:
        if start <= d <= end and d[5:7] in ("03", "06", "09", "12"):
            seen.add(d[:7])
    for m in sorted(seen):
        days = [d for d in book.dates if d[:7] == m and start <= d <= end]
        if days:
            out.append(days[-1])
    return out


def last_quarter_end_on_or_before(book, date):
    cands = [d for d in quarter_end_days(book, book.dates[0], date)]
    return cands[-1] if cands else None


def run_window(book, sig, start, end, label=""):
    days = [d for d in book.dates if start <= d <= end]
    if not days:
        return None
    cash = START_CASH
    shares = 0.0
    total_costs = 0.0
    trades = []
    curve = []
    decisions = []
    days_invested = 0

    # entry position: rule state from the most recent quarter-end check
    qe = last_quarter_end_on_or_before(book, start)
    z0 = sig.zone(qe) if qe else None
    pending = None
    if z0 is not None:
        decisions.append({"date": qe, "exec": days[0], "entry_check": True, **z0})
        if z0["target"] == "SPY":
            pending = "SPY"

    dec_set = set(quarter_end_days(book, start, end))

    def equity_close(d):
        return cash + shares * book.by_date[d]["c"]

    halted = None
    for di, d in enumerate(days):
        bar = book.bar(d)
        # execute pending switch at today's open
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append((d, "BUY", round(shares, 6), bar["o"], round(buy_val, 2), round(c, 2)))
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, "SELL", round(shares, 6), bar["o"], round(val, 2), round(c, 2)))
                shares = 0.0
            pending = None
        # quarter-end decision at today's close
        if d in dec_set:
            z = sig.zone(d)
            if z is not None:
                cur = "SPY" if shares > 0 else "CASH"
                decisions.append({"date": d, "exec": None, **z})
                if z["target"] != cur:
                    pending = z["target"]
                    decisions[-1]["exec"] = "next-open"
        v = equity_close(d)
        curve.append((d, v))
        if shares > 0:
            days_invested += 1
        # plain floor: halt, liquidate at next open
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, "SELL-HALT", round(shares, 6), book.bar(nd)["o"], round(val, 2), round(c, 2)))
                shares = 0.0
            return finish(label, cash, total_costs, trades, curve, decisions,
                          days_invested, len(days), halted)
    # end of window: liquidate at final close
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, "SELL-END", round(shares, 6), book.by_date[last]["c"], round(val, 2), round(c, 2)))
        shares = 0.0
    return finish(label, cash, total_costs, trades, curve, decisions,
                  days_invested, len(days), None)


def finish(label, cash, costs, trades, curve, decisions, days_inv, n_days, halted):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    in_cash_decisions = sum(1 for x in decisions if x["target"] == "CASH")
    return {"label": label, "final": round(cash, 2),
            "return_pct": round(cash / START_CASH * 100 - 100, 2),
            "costs": round(costs, 2), "orders": len(trades),
            "halted": halted,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "time_in_market_pct": round(100.0 * days_inv / n_days, 1) if n_days else 0.0,
            "days": n_days, "days_invested": days_inv,
            "decisions_total": len(decisions),
            "decisions_cash": in_cash_decisions,
            "trades": trades, "decisions": decisions,
            "curve_tail": curve[-1] if curve else None}


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


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    cape_rows = load_cape()
    sig = CapeSignal(cape_rows)

    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print(f"CAPE months: {cape_rows[0][0]}={cape_rows[0][1]} -> "
          f"{cape_rows[-1][0]}={cape_rows[-1][1]} ({len(cape_rows)})")
    # parse cross-checks vs widely published Shiller values
    for m in ("2020-02", "2021-12", "2022-11", "2025-01"):
        print(f"  CAPE[{m}] = {sig.by_month.get(m)}")
    z = sig.zone("2026-09-30")
    print(f"  Latest decision zone (2026-09-30): {z}")

    out = {"rule": "CAPE top-quartile -> cash, else SPY; quarterly quarter-end "
                   "checks; expanding median/Q3 from Jan 1926; CAPE lagged "
                   "~1 month (multpl value dated the 1st of the decision month)",
           "source": "multpl.com Shiller PE by month (Shiller/Yale series); "
                     "SPY = Yahoo adjusted, program shared cache",
           "pot": START_CASH, "floor": FLOOR0, "windows": {}}

    for name, (ws, we) in (("full_2017_2026", FULL),
                           ("champion_2019_2026", CHAMPION),
                           ("validation_2023_2026", VALIDATION)):
        r = run_window(book, sig, ws, we, label=name)
        spy, spy_costs = spy_net(book, ws, we)
        r["spy_net"] = spy
        r["spy_costs"] = spy_costs
        r["vs_spy"] = round(r["final"] - spy, 2)
        out["windows"][name] = r
        print(f"{name}: CAPE-timing ${r['final']:,.2f} ({r['return_pct']:+.2f}%) "
              f"vs SPY ${spy:,.2f} | in-market {r['time_in_market_pct']}% "
              f"cash decisions {r['decisions_cash']}/{r['decisions_total']} "
              f"maxDD {r['max_drawdown_pct']}% orders {r['orders']} "
              f"costs ${r['costs']} halted={r['halted']}", flush=True)

    folds = []
    for y in range(2017, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_window(book, sig, fs, fe, label=f"FOLD {y}")
        fspy, _ = spy_net(book, fs, fe)
        row = {"year": y, "final": fr["final"], "return_pct": fr["return_pct"],
               "spy_net": fspy, "beat_spy": fr["final"] > fspy,
               "time_in_market_pct": fr["time_in_market_pct"],
               "decisions_cash": fr["decisions_cash"],
               "decisions_total": fr["decisions_total"],
               "halted": fr["halted"], "max_drawdown_pct": fr["max_drawdown_pct"]}
        folds.append(row)
        print(f"FOLD {y}: CAPE ${fr['final']:,.2f} ({fr['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} beat={row['beat_spy']} "
              f"in-market {fr['time_in_market_pct']}%", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    with open(os.path.join(HERE, "cape-timing-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
