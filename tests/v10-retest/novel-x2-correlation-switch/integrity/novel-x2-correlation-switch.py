#!/usr/bin/env python3
"""
NOVEL N-2 — "CORRELATION-REGIME SWITCH" — Terry's AI stock app, v8 novel track.
Simulation only. INVENTED-IN-2026 rule: reported as 1 of 12 invented rules;
the best verdict available is CANDIDATE (only a forward paper trial can
promote an invented rule).

Spec: research/v8-novel/novel-cross-calendar.md, Rule N-2 — implemented
verbatim, run once, no tuning.

THE RULE (frozen):
  - Statistic C: on each decision date (first trading day of each month),
    the simple average of the Pearson correlations of daily returns over
    the trailing 60 trading days across every pair of pond names with a
    complete trailing window. No Fisher transform.
  - Readings of C are accumulated point-in-time from monthly readings
    beginning Dec 2016; no reading uses future data.
  - Regime test: C vs the median of all PRIOR monthly readings (expanding
    window). C <= median -> LOW regime: hold the equal-weight pond.
    C > median -> HIGH regime: hold SPY only.
  - Trading: at the decision open, only if the regime differs from the
    current holding: sell the current holding in full, buy the new leg.
    If unchanged, do nothing — the equal-weight pond is NOT rebalanced
    monthly; weights drift until the next flip.
  - Placebo: the same two assets switched on random flip dates, flip
    count matched to the ranked run's realized flip count per window,
    20 seeds; initial asset matched to the ranked run's initial leg so
    the placebo isolates flip TIMING.

CHASSIS (program standard): $100 pot; costs 0.10% of trade value per
side + $0.01 per sell order; plain -15% floor (close at/below $85.00 ->
liquidate at next open, run ends; champion engine semantics). Windows:
continuous 2019-01-02 -> 2026-11-20, validation 2023-01-03 -> 2026-11-20.
Benchmarks: SPY buy-hold net $313.62 / $187.77; champion V+M $544.47 /
$288.05.

CANDIDATE gates (all four required, per the tasking):
  validation final > $187.77; validation placebo >= 19/20 beaten;
  continuous final > $313.62; no floor halt on either main window.

DATA: program cached split/dividend-adjusted daily bars (Yahoo chart API
payloads, champion engine construction: close = adjclose, open scaled by
adjclose/close), read in the champion engine's own lookup order
(backtests/v4/data/, then backtests/v4/value-momentum-honest-data/).
The caches begin 2017-06-01, but the frozen spec requires statistic
readings beginning Dec 2016. The warm-up gap (bars before 2017-06-01) is
filled from the SAME Yahoo chart API with the IDENTICAL parsing, pulled
into this test's own data/ folder; the pull overlaps June 2017 and is
verified bar-for-bar against the cache before any pre-cache bar is used,
and pre-cache bars feed only the statistic's early readings — every
trade in both windows executes on cached bars.
"""
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE_DIRS = [os.path.join(V4, "data"),
              os.path.join(V4, "value-momentum-honest-data")]
WARM_DIR = os.path.join(HERE, "data")
os.makedirs(WARM_DIR, exist_ok=True)

POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
        "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
        "KO", "PEP", "WFC"]
START_CASH = 100.0
FLOOR = 85.0
WINDOWS = [("FULL", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20")]
PLACEBO_SEEDS = list(range(1, 21))

# ------------------------------------------------------------------ data
def parse_payload(blob):
    """Champion engine's construction, verbatim: close = adjclose,
    open scaled by adjclose/close."""
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

def load_cache_bars(ticker):
    for d in CACHE_DIRS:
        p = os.path.join(d, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return parse_payload(f.read())
    raise RuntimeError(f"no cached bars for {ticker}")

def fetch_warmup(ticker):
    """Yahoo chart API, champion engine's URL form, 2016-08-01 ->
    2017-07-01 (one month of overlap with the cache for verification)."""
    path = os.path.join(WARM_DIR, f"warm_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return parse_payload(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime("2016-08-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2017-07-01", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return parse_payload(blob)
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"warmup fetch failed {ticker}: {last}")

def merged_bars(ticker):
    """Cache bars for 2017-06-01 on; verified warm-up bars before that."""
    cache = load_cache_bars(ticker)
    first = cache[0]["d"]
    warm = fetch_warmup(ticker)
    overlap_cache = {b["d"]: b for b in cache if b["d"] < "2017-07-01"}
    mism = 0
    for b in warm:
        if b["d"] in overlap_cache:
            cb = overlap_cache[b["d"]]
            if (abs(b["c"] / cb["c"] - 1) > 1e-6 or
                    abs(b["o"] / cb["o"] - 1) > 1e-6):
                mism += 1
    if mism:
        raise RuntimeError(f"{ticker}: {mism} warm-up/cache overlap mismatches")
    pre = [b for b in warm if b["d"] < first]
    return pre + cache, len(pre)

# ------------------------------------------------------------- statistic
def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)

def compute_readings(cal, closes):
    """Monthly readings of C from Dec 2016. cal = SPY calendar (list of
    dates); closes = {ticker: {date: close}}. Each reading is taken on
    the first trading day of a month, on data through the prior close:
    the 60 daily returns ending at the prior close (61 closes)."""
    cal_idx = {d: i for i, d in enumerate(cal)}
    months = []
    seen = set()
    for d in cal:
        key = d[:7]
        if key >= "2016-12" and key not in seen:
            seen.add(key)
            months.append(d)
    readings = []
    for d in months:
        i = cal_idx[d]
        if i < 61:
            continue
        win_days = cal[i - 61:i]          # 61 closes ending at prior close
        rets = {}
        complete = []
        for t in POND:
            ct = closes[t]
            if all(day in ct for day in win_days):
                rs = [ct[win_days[k + 1]] / ct[win_days[k]] - 1.0
                      for k in range(60)]
                rets[t] = rs
                complete.append(t)
        corrs = []
        for a in range(len(complete)):
            for b in range(a + 1, len(complete)):
                r = pearson(rets[complete[a]], rets[complete[b]])
                if r is not None:
                    corrs.append(r)
        C = sum(corrs) / len(corrs) if corrs else None
        readings.append({"date": d, "C": C, "n_pairs": len(corrs),
                         "scoreable": complete})
    return readings

# ---------------------------------------------------------------- engine
class Book:
    """Calendar-aligned bars: opens are None on days a name has no bar;
    closes are forward-filled (the engine's close-on-or-before value)."""
    def __init__(self, bars_by_ticker, cal):
        self.cal = cal
        self.cidx = {d: i for i, d in enumerate(cal)}
        self.open_ = {}
        self.close_ = {}
        for t, bl in bars_by_ticker.items():
            m = {b["d"]: b for b in bl}
            opens, closes = [], []
            last = None
            for d in cal:
                b = m.get(d)
                if b:
                    opens.append(b["o"])
                    last = b["c"]
                    closes.append(b["c"])
                else:
                    opens.append(None)
                    closes.append(last)
            self.open_[t] = opens
            self.close_[t] = closes

    def bar(self, t, d):
        i = self.cidx.get(d)
        if i is None or self.open_[t][i] is None:
            return None
        return {"d": d, "o": self.open_[t][i], "c": self.close_[t][i]}

    def close_on_or_before(self, t, d):
        i = self.cidx.get(d)
        if i is None:
            return None
        return self.close_[t][i]

def run_pot(book, start, end, switch_targets, pond_names_on):
    """switch_targets: {date: 'POND'|'SPY'} — at that date's open, if the
    target differs from the current holding, rotate in full.
    pond_names_on: function(date) -> list of names for an EW pond buy.
    Champion mechanics: sells first (0.10% + $0.01/order), then buys
    toward equal targets capped by cash/1.001 (buy cost 0.10%).
    Floor: close <= $85 -> liquidate at next open, run ends.
    End of window: liquidate at final close."""
    days = [d for d in book.cal if start <= d <= end]
    cash = START_CASH
    positions = {}
    holding = None
    trades = []
    total_costs = 0.0
    curve = []
    flips = 0
    days_in = {"POND": 0, "SPY": 0, "CASH": 0}

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = book.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def sell_all(d, tag):
        nonlocal cash, total_costs
        for t in list(positions):
            b = book.bar(t, d)
            if not b:
                continue
            val = positions[t] * b["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, t, tag, positions[t], b["o"], val, c))
            del positions[t]

    def buy_leg(d, target):
        nonlocal cash, total_costs
        if target == "SPY":
            b = book.bar("SPY", d)
            if not b:
                return
            buy_val = cash / 1.001
            if buy_val <= 0.005:
                return
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            positions["SPY"] = positions.get("SPY", 0.0) + sh
            trades.append((d, "SPY", "BUY", sh, b["o"], buy_val, c))
        else:
            names = [t for t in pond_names_on(d) if book.bar(t, d)]
            if not names:
                return
            each = cash / len(names)
            for t in names:
                b = book.bar(t, d)
                buy_val = min(each, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / b["o"]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, b["o"], buy_val, c))

    halted = None
    for di, d in enumerate(days):
        if d in switch_targets:
            target = switch_targets[d]
            if holding is None:
                buy_leg(d, target)
                holding = target
            elif target != holding:
                sell_all(d, "SELL")
                buy_leg(d, target)
                holding = target
                flips += 1
        v = portfolio_close(d)
        curve.append((d, v))
        days_in[holding if holding else "CASH"] += 1
        if v <= FLOOR and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            # liquidate at next open
            for t in list(positions):
                b = book.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "flips": flips, "curve": curve,
                    "days_in": days_in, "end": nd}
    last = days[-1]
    for t in list(positions):
        c_ = book.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "flips": flips, "curve": curve,
            "days_in": days_in, "end": last}

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
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

# ------------------------------------------------------------------ main
def main():
    # integrity: champion engine's own bars + spy_net, before anything
    spec = importlib.util.spec_from_file_location(
        "champ", os.path.join(V4, "value-momentum-plainfloor.py"))
    champ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(champ)
    champ_bars = {}
    for t in POND + ["SPY"]:
        champ_bars[t] = champ.get_prices(t)
    cpb = champ.PriceBook(champ_bars)
    spy_full, _ = champ.spy_net(cpb, "2019-01-02", "2026-11-20", 100.0)
    spy_val, _ = champ.spy_net(cpb, "2023-01-03", "2026-11-20", 100.0)
    print(f"INTEGRITY champion spy_net: FULL=${spy_full:,.2f} "
          f"VALIDATION=${spy_val:,.2f} (published $313.62 / $187.77)",
          flush=True)
    assert round(spy_full, 2) == 313.62 and round(spy_val, 2) == 187.77

    # merged series (cache + verified warm-up) and bar-for-bar check
    bars, closes = {}, {}
    n_pre = {}
    for t in POND + ["SPY"]:
        mb, npre = merged_bars(t)
        bars[t] = mb
        n_pre[t] = npre
        cmap = {b["d"]: b for b in champ_bars[t]}
        mism = sum(1 for b in mb if b["d"] in cmap and
                   (abs(b["c"] / cmap[b["d"]]["c"] - 1) > 1e-6 or
                    abs(b["o"] / cmap[b["d"]]["o"] - 1) > 1e-6))
        assert mism == 0, f"{t}: {mism} merged/cache mismatches"
    print(f"INTEGRITY merged bars match champion bars on all overlaps; "
          f"warm-up bars per name: min={min(n_pre.values())} "
          f"max={max(n_pre.values())}", flush=True)

    cal = [b["d"] for b in bars["SPY"]]
    for t in POND + ["SPY"]:
        closes[t] = {b["d"]: b["c"] for b in bars[t]}
    book = Book(bars, cal)

    readings = compute_readings(cal, closes)
    print(f"READINGS: {len(readings)} monthly readings "
          f"{readings[0]['date']} .. {readings[-1]['date']}", flush=True)
    # regime at each reading: compare to median of all prior readings
    prior = []
    regime = {}
    scoreable_on = {}
    for r in readings:
        if prior:
            med = statistics.median(prior)
            regime[r["date"]] = "POND" if r["C"] <= med else "SPY"
            r["median_prior"] = med
        else:
            r["median_prior"] = None
        prior.append(r["C"])
        scoreable_on[r["date"]] = r["scoreable"]
    last_scoreable = None
    for r in readings:
        last_scoreable = r["scoreable"]

    def pond_names_ranked(d):
        return scoreable_on[d]

    out = {"rule": "N-2 Correlation-Regime Switch (invented 2026, 1 of 12)",
           "integrity": {"spy_net_full": round(spy_full, 2),
                         "spy_net_validation": round(spy_val, 2)},
           "readings": [{k: r[k] for k in ("date", "C", "n_pairs",
                                            "median_prior")}
                         for r in readings],
           "windows": {}}

    for wname, ws, we in WINDOWS:
        days = [d for d in cal if ws <= d <= we]
        dec_dates = [r["date"] for r in readings if ws <= r["date"] <= we]
        switches = {d: regime[d] for d in dec_dates}
        ranked = run_pot(book, ws, we, switches, pond_names_ranked)
        diag = diagnostics(ranked)
        init_asset = regime[dec_dates[0]]
        print(f"== {wname}: ranked final=${ranked['final']:,.2f} "
              f"flips={ranked['flips']} costs=${ranked['costs']:,.2f} "
              f"halted={ranked['halted']} init={init_asset}", flush=True)

        # decomposition legs: static equal-weight buy-hold, static SPY
        ew = run_pot(book, ws, we, {days[0]: "POND"},
                     lambda d: scoreable_on[
                         max(x for x in scoreable_on if x <= d)])
        spy_leg = spy_full if wname == "FULL" else spy_val
        print(f"   decomposition: EW-hold=${ew['final']:,.2f} "
              f"SPY-hold=${spy_leg:,.2f} switch=${ranked['final']:,.2f}",
              flush=True)

        # placebo: same initial asset, matched flip count, random dates
        cand_days = [d for d in days if d > dec_dates[0]]
        pfinals = []
        phalted = 0
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            k = ranked["flips"]
            fdates = sorted(rng.sample(cand_days, k)) if k else []
            pswitch = {dec_dates[0]: init_asset}
            cur = init_asset
            for fd in fdates:
                cur = "SPY" if cur == "POND" else "POND"
                pswitch[fd] = cur
            pr = run_pot(book, ws, we, pswitch,
                         lambda d: scoreable_on[
                             max(x for x in scoreable_on if x <= d)])
            pfinals.append(round(pr["final"], 2))
            if pr["halted"]:
                phalted += 1
        beat = sum(1 for f in pfinals if ranked["final"] > f)
        ps = sorted(pfinals)
        pmed = round(statistics.median(pfinals), 2)
        print(f"   placebo: median=${pmed:,.2f} beat={beat}/20 "
              f"halted={phalted}/20", flush=True)

        out["windows"][wname] = {
            "ranked": {"final": round(ranked["final"], 2),
                       "costs": round(ranked["costs"], 2),
                       "orders": len(ranked["trades"]),
                       "flips": ranked["flips"],
                       "halted": ranked["halted"],
                       "days_in": ranked["days_in"], "diag": diag,
                       "decisions": [{"date": d, "C": next(
                           r["C"] for r in readings if r["date"] == d),
                           "median_prior": next(
                               r["median_prior"] for r in readings
                               if r["date"] == d),
                           "regime": regime[d]} for d in dec_dates]},
            "decomposition": {"ew_buy_hold": round(ew["final"], 2),
                              "ew_costs": round(ew["costs"], 2),
                              "spy_buy_hold": round(spy_leg, 2)},
            "placebo": {"finals": ps, "median": pmed,
                        "best": ps[-1], "worst": ps[0],
                        "halted": phalted, "beat": beat}}

    with open(os.path.join(HERE, "novel-x2-correlation-switch-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
