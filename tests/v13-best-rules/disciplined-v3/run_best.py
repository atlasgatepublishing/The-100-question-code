#!/usr/bin/env python3
"""DISCIPLINED-v3 — v13 BEST-RULES run. Simulation only.

Implements BEST-RULES-SPEC.md exactly (frozen before this run):
  universe SPY/QQQ/IWM/GLD/TLT; monthly selection at the open, signals from
  the prior trading day's close; eligible = prior close above own 200-day MA;
  hold ALL eligible, equal weight, 100% invested (cash if none eligible);
  NO momentum ranking, NO vol scaling, NO defensive cap, NO drawdown cap,
  NO floor; daily trend exit (close below 200d MA -> sell next open);
  costs 0.10%/side + $0.01 per sell order; $100 fresh pot per road.

Placebos (20 seeds/road): identical machinery, but at each selection picks
are a random sample of the FULL universe of the same size as that month's
eligible count, ignoring the filter (and therefore no daily trend exits —
a twin that ignores the filter cannot exit on it).

Data: public Yahoo Finance chart API, daily bars, split-adjusted, NOT
dividend-adjusted (the family's own data basis), fetched 2009-01-01 ->
2026-11-21 for 200-day warmup, cached in this folder's data/.
"""
import csv, json, math, os, random, statistics, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
ET = ZoneInfo("America/New_York")
FETCH_FROM = int(datetime(2009, 1, 1, tzinfo=timezone.utc).timestamp())
FETCH_TO = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21",
         "CONT": "2019-01-02", "VAL": "2023-01-03"}
END = "2026-11-20"


def fetch(ticker):
    cache = os.path.join(DATA_DIR, f"{ticker}.csv")
    if os.path.exists(cache):
        rows = []
        with open(cache) as f:
            for r in csv.DictReader(f):
                rows.append({k: (r[k] if k == "date" else float(r[k]))
                             for k in r})
        return rows
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={FETCH_FROM}&period2={FETCH_TO}&interval=1d"
           f"&events=history")
    payload = None
    for host in ("query1", "query2"):
        req = urllib.request.Request(url.replace("query1", host), headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                          "AppleWebKit/537.36"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            continue
    if payload is None:
        raise RuntimeError(f"could not fetch {ticker}")
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": vals[0], "high": vals[1],
                     "low": vals[2], "close": vals[3],
                     "volume": q["volume"][i] or 0})
    rows.sort(key=lambda r: r["date"])
    with open(cache, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low",
                                          "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    time.sleep(0.3)
    return rows


class Market:
    def __init__(self):
        self.bars = {t: fetch(t) for t in UNIVERSE}
        self.by_date = {t: {r["date"]: r for r in rows}
                        for t, rows in self.bars.items()}
        self.closes = {t: [r["close"] for r in rows]
                       for t, rows in self.bars.items()}
        self.dates_all = [r["date"] for r in self.bars["SPY"]]
        self.idx_of = {t: {r["date"]: i for i, r in enumerate(rows)}
                       for t, rows in self.bars.items()}
        for t in UNIVERSE:  # all five trade on the SPY calendar in practice;
            missing = [d for d in self.dates_all if d not in self.by_date[t]]
            assert not missing, f"{t} missing {len(missing)} SPY dates"

    def ma200(self, t, date):
        i = self.idx_of[t][date]
        if i < 199:
            return None
        return sum(self.closes[t][i - 199:i + 1]) / 200.0


def run_road(mkt, start, end=END, mode="strategy", seed=None):
    dates_all = mkt.dates_all
    period = [d for d in dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d) - 1] for d in period}

    selection_days, seen = set(), set()
    for d in period:
        if d == first_day or d[:7] not in seen:
            selection_days.add(d)
        seen.add(d[:7])

    rng = random.Random(seed)
    cash = 100.0
    shares = {t: 0.0 for t in UNIVERSE}
    trades, total_costs, orders = [], 0.0, 0
    pending_exits = set()
    daily = []

    def equity(mp):
        return cash + sum(shares[t] * mp[t] for t in UNIVERSE)

    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs, orders
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        orders += 1
        trades.append({"date": date, "ticker": t, "side": "sell",
                       "price": round(price, 4), "value": round(value, 2),
                       "reason": reason})

    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs, orders
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        cash -= value + cost
        total_costs += cost
        shares[t] += value / price
        orders += 1
        trades.append({"date": date, "ticker": t, "side": "buy",
                       "price": round(price, 4), "value": round(value, 2),
                       "reason": reason})

    for d in period:
        opens = {t: mkt.by_date[t][d]["open"] for t in UNIVERSE}
        closes_today = {t: mkt.by_date[t][d]["close"] for t in UNIVERSE}

        for t in sorted(pending_exits):
            if shares[t] > 0:
                do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()

        if d in selection_days:
            ref = prior_day[d]
            eligible = []
            for t in UNIVERSE:
                ma = mkt.ma200(t, ref)
                if ma is not None and mkt.by_date[t][ref]["close"] > ma:
                    eligible.append(t)
            if mode == "placebo":
                k = len(eligible)
                picks = sorted(rng.sample(sorted(UNIVERSE), k)) if k else []
            else:
                picks = list(eligible)
            weights = ({t: 1.0 / len(picks) for t in picks} if picks
                       else {})
            eq_open = equity(opens)
            targets = {t: eq_open * weights.get(t, 0.0) for t in picks}
            for t in UNIVERSE:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    do_sell(t, d, opens[t], "rebalance-trim",
                            (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            twc = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants:
                    do_buy(t, d, opens[t], wants[t] * scale, "rebalance-buy")

        eq_close = equity(closes_today)
        daily.append((d, eq_close))

        if mode == "strategy":
            for t in UNIVERSE:
                if shares[t] > 1e-9:
                    ma = mkt.ma200(t, d)
                    if ma is not None and closes_today[t] < ma:
                        pending_exits.add(t)

    closes_last = {t: mkt.by_date[t][last_day]["close"] for t in UNIVERSE}
    for t in UNIVERSE:
        if shares[t] > 0:
            do_sell(t, last_day, closes_last[t], "final-liquidation")
    final = cash
    if daily and daily[-1][0] == last_day:
        daily[-1] = (last_day, final)

    peak, max_dd = 100.0, 0.0
    for _, eq in daily:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)
    d0 = datetime.strptime(first_day, "%Y-%m-%d")
    d1 = datetime.strptime(last_day, "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr = (final / 100.0) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    return {"start": first_day, "end": last_day, "final": round(final, 2),
            "return_pct": round((final / 100.0 - 1) * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(-max_dd * 100, 2),
            "costs": round(total_costs, 2), "orders": orders,
            "equity_curve": [[d, round(v, 4)] for d, v in daily],
            "trades": trades}


def spy_benchmark(mkt, start, end=END):
    period = [d for d in mkt.dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    spy_open = mkt.by_date["SPY"][first_day]["open"]
    spy_close = mkt.by_date["SPY"][last_day]["close"]
    sh = 100.0 / (spy_open * (1 + COST_RATE))
    net = sh * spy_close * (1 - COST_RATE) - SELL_FEE
    peak, max_dd = None, 0.0
    for d in period:
        c = mkt.by_date["SPY"][d]["close"]
        peak = c if peak is None or c > peak else peak
        max_dd = max(max_dd, (peak - c) / peak)
    return {"final": round(net, 2), "max_dd_pct": round(-max_dd * 100, 2),
            "basis": "price-only, same cache, program costs"}


def period_distribution(curve):
    """Calendar-year distribution from a daily equity curve."""
    years = {}
    for d, v in curve:
        years.setdefault(int(d[:4]), []).append((d, v))
    rows, prev = [], 100.0
    for y in sorted(years):
        end_v = years[y][-1][1]
        rows.append({"period": y,
                     "return_pct": round((end_v / prev - 1) * 100, 2),
                     "end": round(end_v, 2)})
        prev = end_v
    rets = [r["return_pct"] for r in rows]
    # longest losing streak (consecutive negative years)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (trading days on the daily curve)
    peak, peak_date, worst_gap, last_high = None, None, 0, None
    for d, v in curve:
        if peak is None or v >= peak:
            if peak_date is not None and last_high is not None:
                gap = (datetime.strptime(d, "%Y-%m-%d")
                       - datetime.strptime(last_high, "%Y-%m-%d")).days
                worst_gap = max(worst_gap, gap)
            peak, peak_date, last_high = v, d, d
    if last_high is not None:
        gap = (datetime.strptime(curve[-1][0], "%Y-%m-%d")
               - datetime.strptime(last_high, "%Y-%m-%d")).days
        worst_gap = max(worst_gap, gap)
    return {
        "periods": rows,
        "median_period_pct": round(statistics.median(rets), 2) if rets else None,
        "share_positive_pct": round(100.0 * sum(1 for r in rets if r > 0)
                                    / len(rets), 1) if rets else None,
        "best_period_pct": max(rets) if rets else None,
        "worst_period_pct": min(rets) if rets else None,
        "longest_losing_streak_periods": longest,
        "longest_stretch_between_new_highs_days": worst_gap,
        "secondary_average_period_pct": (round(statistics.mean(rets), 2)
                                         if rets else None),
    }


def main():
    mkt = Market()
    out = {"slug": "disciplined-v3", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md",
           "champions_vm": {"LONG": 1415.62, "DECADE": 667.35,
                            "CONT": 544.47, "VAL": 288.05},
           "spy_reference_program": {"LONG": 822.94, "DECADE": 367.80,
                                     "CONT": 313.62, "VAL": 187.77},
           "prior_family_best": {
               "DECADE_window_COMBO_D3D6_full": 241.29,
               "DECADE_window_BASE": 194.28,
               "validation_window_BASE": 150.24,
               "validation_window_COMBO": 147.93,
               "validation_window_placebo_seed42": 151.44},
           "roads": {}}
    for road, start in ROADS.items():
        r = run_road(mkt, start)
        twins = []
        for seed in range(1, 21):
            pr = run_road(mkt, start, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": pr["final"],
                          "max_dd_pct": pr["max_dd_pct"]})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        dist = period_distribution(r["equity_curve"])
        out["roads"][road] = {
            "run": {k: r[k] for k in ("start", "end", "final", "return_pct",
                                      "cagr_pct", "max_dd_pct", "costs",
                                      "orders")},
            "spy_price_basis": spy_benchmark(mkt, start),
            "placebo_beaten_of_20": beaten,
            "placebo_finals": twins,
            "placebo_median_final": round(statistics.median(
                [t["final"] for t in twins]), 2),
            "period_distribution": dist,
            "equity_curve": r["equity_curve"],
            "trades": r["trades"]}
        print(road, json.dumps(out["roads"][road]["run"]),
              "placebo beaten", beaten, "/20, median twin",
              out["roads"][road]["placebo_median_final"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE results.json")


if __name__ == "__main__":
    main()
