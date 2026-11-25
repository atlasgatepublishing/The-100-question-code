#!/usr/bin/env python3
"""
GAP TEST A-1 — SAME-MONTH SEASONALITY (Heston & Sadka 2008) — Terry's AI
stock app. Simulation only. No broker orders were placed.

SOURCE: Heston & Sadka (2008), "Seasonality in the Cross-Section of Stock
Returns," Journal of Financial Economics 87(2); international companion
(2010), JFQA 45(5). Gap item A-1 in
research/v7-completeness/missing-families.md (Table A). The published claim:
a stock's average return in a given calendar month, measured at annual lags
only (t-12, t-24, ...), predicts its return in that same month for years
afterward; non-annual lags predict negatively.

FROZEN SPEC (from missing-families.md, implemented verbatim):
  - Monthly. For each pond name and the current month m, signal = mean
    return in month m over the prior 10 years (annual lags only; require
    >= 6 observations; Yahoo bars reach back far enough).
  - Hold the top-5 signal names for that month only, equal weight;
    rebalance monthly.
  - Report the long-only pot (judged) and the top-5-minus-bottom-5 spread
    (diagnostic only).
  - House chassis: $100 pot, honest top-30 pond as of Nov 2016 (the
    champion's UNIVERSE verbatim), costs 0.10%/side + $0.01/sell, plain
    -15% floor ($85), windows continuous 2019-01-02 -> 2026-11-20 and
    validation 2023-01-03 -> 2026-11-20, 20-seed placebos on the same
    dates/mechanics, SPY comparison.

FORCED READINGS (stated before results; the spec's prose leaves these
open and the program's house conventions settle them — none was chosen
after seeing any outcome):
  R1. Monthly return for calendar month m of year y = split/dividend-
      adjusted close on the last trading day of m / adjusted close on the
      last trading day of the previous month - 1 (Yahoo adjclose series,
      the program's standard price basis).
  R2. Signal at the decision date for month (Y, m) = mean of that name's
      month-m returns for years Y-10 .. Y-1 (annual lags only, exactly as
      published). A name is eligible only with >= 6 such observations.
      All inputs are completed calendar months strictly before the
      decision month — point-in-time by construction.
  R3. Decision dates = first trading day of each calendar month in the
      window; targets execute at the NEXT session's open (the champion
      engine's convention). The pot therefore holds each month's picks
      from the second trading day until the next rebalance executes.
  R4. Ties in signal: broken by ticker alphabetical order (deterministic;
      signals are floating-point means, exact ties are not expected).
  R5. The diagnostic spread is a PAPER spread, gross of costs and of the
      floor: each decision month, spread return = (mean realized return
      of the top-5 over the holding span) - (mean realized return of the
      bottom-5), where a name's realized return runs from the execution
      open to the next rebalance's execution open (or the window's final
      close for the last month). Compounded across months and reported
      per $100 notional per leg. It is never traded and never judged.
  R6. Placebos: on each decision date, 5 names drawn uniformly at random
      (seeds 1..20) from the SAME eligible pool the ranked rule picks
      from that month, same engine, same costs, same floor.
  R7. Floor mechanics identical to the champion engine: close at/below
      $85 on any day -> liquidate at next open, run ends. End of window:
      liquidate at final close with the standard sell cost.
  R8. META (listed May 2012) reaches 6 January observations only in
      Jan 2019 and fewer for some early months; it is eligible exactly
      when the >=6 rule is met and not before — never patched.

Data: Yahoo Finance chart API daily bars (split/dividend-adjusted, same
method as the champion engine), fetched 2008-01-01 -> 2026-11-21 into
this test's own data/ cache (the champion's shared cache starts
2017-06 and cannot supply 10 years of annual lags; the spec itself
states "Yahoo bars reach back far enough"). Signal history therefore
begins with the Dec-2008 month return; the first decision month with a
full pond is Jan 2019, matching the program's standard window start.
"""
import json, math, os, random, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0

# ---------------------------------------------------------------- fetch utils
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def get_prices(ticker, p1="2008-01-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"px_{ticker}.json")
    import calendar
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch(url, path)
    j = json.loads(blob)
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

# ------------------------------------------------------------------ price book
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

# ------------------------------------------------------------- seasonal signal
def month_end_closes(bars):
    """dict (year, month) -> adjusted close on last trading day of month."""
    out = {}
    for b in bars:
        out[(int(b["d"][:4]), int(b["d"][5:7]))] = b["c"]
    return out

def monthly_returns(bars):
    """dict (year, month) -> that calendar month's return (R1)."""
    me = month_end_closes(bars)
    out = {}
    for (y, m), c in sorted(me.items()):
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        prev = me.get((py, pm))
        if prev:
            out[(y, m)] = c / prev - 1.0
    return out

def seasonal_signal(mrets, year, month):
    """Mean of month-`month` returns over years year-10..year-1 (R2).
    Returns (signal, n_obs) or (None, n_obs) if < 6 observations."""
    vals = [mrets[(y, month)] for y in range(year - 10, year)
            if (y, month) in mrets]
    if len(vals) < 6:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)

def month_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out

# ------------------------------------------------------------------ engine
def run_pot(pb, mrets_by, start, end, placebo_rng=None, label="", quiet=True,
            collect_spread=False):
    """Monthly-rotation pot on the champion chassis (R3, R6, R7)."""
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    spread_months = []   # (decision_date, top5 list, bot5 list, exec_date)
    sel_dates = month_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None       # dict ticker -> target value
    pending_meta = None  # (decision_date, ranked_top5, ranked_bot5)

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            if collect_spread and pending_meta is not None:
                spread_months.append((pending_meta[0], pending_meta[1],
                                      pending_meta[2], d))
            pending = None
            pending_meta = None
        if d in sel_set:
            y, m = int(d[:4]), int(d[5:7])
            signals = {}
            for t in UNIVERSE:
                s, _n = seasonal_signal(mrets_by[t], y, m)
                if s is not None:
                    signals[t] = s
            if len(signals) >= 5:
                ranked = sorted(signals, key=lambda t: (-signals[t], t))
                top5 = ranked[:5]
                bot5 = ranked[-5:]
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(signals), 5)
                else:
                    picks = top5
                picks_log.append({"date": d, "pool": len(signals),
                                  "picks": list(picks),
                                  "signals": {t: round(signals[t], 6) for t in picks}})
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                pending_meta = (d, top5, bot5)
                if not quiet:
                    print(f"  [{label}] {d} pool={len(signals)} picks={picks} pot=${pv:,.2f}", flush=True)
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "picks_log": picks_log, "spread_months": spread_months}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "picks_log": picks_log, "spread_months": spread_months}

def spread_diagnostic(pb, spread_months, end):
    """R5: gross paper spread, top-5 minus bottom-5, per decision month."""
    rows = []
    comp = 1.0
    for i, (dec_d, top5, bot5, exec_d) in enumerate(spread_months):
        if i + 1 < len(spread_months):
            exit_d, exit_kind = spread_months[i + 1][3], "open"
        else:
            exit_d, exit_kind = end, "close"
        def leg_ret(names):
            rs = []
            for t in names:
                b0 = pb.bar(t, exec_d)
                if not b0:
                    continue
                if exit_kind == "open":
                    b1 = pb.bar(t, exit_d)
                    p1 = b1["o"] if b1 else None
                else:
                    p1 = pb.close_on_or_before(t, exit_d)
                if p1:
                    rs.append(p1 / b0["o"] - 1.0)
            return sum(rs) / len(rs) if rs else 0.0
        s = leg_ret(top5) - leg_ret(bot5)
        comp *= (1.0 + s)
        rows.append({"decision": dec_d, "exec": exec_d, "spread_pct": round(s * 100, 3)})
    return {"months": len(rows), "compounded_final_per_100": round(comp * 100, 2),
            "mean_monthly_spread_pct": round(sum(r["spread_pct"] for r in rows) / len(rows), 3) if rows else None,
            "positive_months": sum(1 for r in rows if r["spread_pct"] > 0),
            "rows": rows}

def spy_net(pb, start, end, start_cash=START_CASH):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def diagnostics(r):
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)
    covid = [(d, v) for d, v in curve if "2020-02-01" <= d <= "2020-04-30"]
    covid_worst = min(covid, key=lambda kv: kv[1]) if covid else None
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": FLOOR0,
            "worst_close_above_floor": round(worst_v - FLOOR0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "covid_worst_close": round(covid_worst[1], 2) if covid_worst else None,
            "covid_worst_date": covid_worst[0] if covid_worst else None,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

def _pct(sorted_vals, q):
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

def percentile_of(sorted_vals, x):
    """Share of placebo finals strictly below x, as a percentile rank."""
    if not sorted_vals:
        return None
    below = sum(1 for v in sorted_vals if v < x)
    return round(100.0 * below / len(sorted_vals), 1)

# --------------------------------------------------------------------- main
def main():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = PriceBook(bars)
    mrets_by = {t: monthly_returns(bars[t]) for t in UNIVERSE}

    windows = [
        ("CONTINUOUS", "2019-01-02", "2026-11-20"),
        ("VALIDATION", "2023-01-03", "2026-11-20"),
    ]
    out = {"strategy": "A-1 same-month seasonality (Heston & Sadka 2008)",
           "spec": "signal = mean same-calendar-month return over prior 10 years (annual lags only), >=6 obs; hold top-5 equal weight, monthly rebalance",
           "universe": UNIVERSE, "start_cash": START_CASH, "floor": FLOOR0,
           "costs": "0.10%/side + $0.01/sell"}

    # integrity gate: SPY buy-hold must reproduce the program's published nets
    spy_check = {}
    for wname, ws, we in windows:
        s, _ = spy_net(pb, ws, we)
        spy_check[wname] = round(s, 2)
    print(f"SPY integrity check: {spy_check} (published: CONTINUOUS 313.62, VALIDATION 187.77)", flush=True)
    out["spy_integrity_check"] = spy_check

    for wname, ws, we in windows:
        s, scost = spy_net(pb, ws, we)
        r = run_pot(pb, mrets_by, ws, we, label=f"{wname} RANKED",
                    collect_spread=True)
        diag = diagnostics(r)
        spread = spread_diagnostic(pb, r["spread_months"], we)
        # win rate over closed round trips per name-episode: use trade pairs
        # (approximated from picks turnover: count monthly holding episodes)
        finals = []
        halts = 0
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_pot(pb, mrets_by, ws, we, placebo_rng=rng,
                         label=f"{wname} PLACEBO seed={seed}")
            finals.append(round(pr["final"], 2))
            if pr["halted"]:
                halts += 1
        finals_sorted = sorted(finals)
        median = _pct(finals_sorted, 0.5)
        beats = sum(1 for v in finals if r["final"] > v)
        out[wname] = {
            "window": [ws, we],
            "ranked_final": round(r["final"], 2),
            "ranked_return_pct": round((r["final"] / START_CASH - 1) * 100, 2),
            "costs": round(r["costs"], 2),
            "orders": len(r["trades"]),
            "rebalances": len(r["picks_log"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "spy_net": round(s, 2), "spy_costs": round(scost, 2),
            "champion_reference": 544.47 if wname == "CONTINUOUS" else 288.05,
            "placebo": {"finals": finals, "median": round(median, 2),
                        "min": finals_sorted[0], "max": finals_sorted[-1],
                        "ranked_beats": beats, "of": len(finals),
                        "ranked_percentile": percentile_of(finals_sorted, round(r["final"], 2)),
                        "halts": halts},
            "spread_diagnostic": {k: v for k, v in spread.items() if k != "rows"},
            "spread_rows": spread["rows"],
            "diagnostics": diag,
            "picks_log": r["picks_log"],
            "trades": r["trades"],
        }
        print(f"== {wname}: ranked=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY=${s:,.2f} | "
              f"placebo median=${median:,.2f} beats={beats}/20 | "
              f"spread {spread['months']} months comp=${spread['compounded_final_per_100']:,.2f}",
              flush=True)

    # walk-forward folds: fresh $100 pot per calendar year 2020..2026
    folds = []
    for y in range(2020, 2027):
        ws = f"{y}-01-01"
        we = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot(pb, mrets_by, ws, we, label=f"FOLD {y}")
        fs, _ = spy_net(pb, ws, we)
        folds.append({"year": y, "window": [ws, we],
                      "final": round(fr["final"], 2),
                      "return_pct": round((fr["final"] / START_CASH - 1) * 100, 2),
                      "spy_net": round(fs, 2),
                      "spy_return_pct": round((fs / START_CASH - 1) * 100, 2),
                      "beat_spy": fr["final"] > fs,
                      "halted": fr["halted"], "costs": round(fr["costs"], 2),
                      "orders": len(fr["trades"])})
        print(f"FOLD {y}: final=${fr['final']:,.2f} vs SPY ${fs:,.2f} "
              f"beat={fr['final'] > fs} halted={fr['halted']}", flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    comp = START_CASH
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    scomp = START_CASH
    for f in folds:
        scomp *= 1 + f["spy_return_pct"] / 100.0
    out["folds"] = {"folds": folds, "record": f"{wins} wins, {len(folds) - wins} losses vs SPY",
                    "fold_compounded_final": round(comp, 2),
                    "spy_fold_compounded_final": round(scomp, 2)}

    with open(os.path.join(HERE, "gap-a1-seasonality-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
