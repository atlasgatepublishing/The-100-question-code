#!/usr/bin/env python3
"""
DISCIPLINED pot v2 backtest for Terry's AI stock app. Simulation only.

v0 core (unchanged): monthly selection from SPY/QQQ/IWM/GLD/TLT; eligible =
close above 200-day MA (signals from prior trading day's close); rank by
trailing 63-day momentum; trend exit on close below 200-day MA (sell next
open); costs 0.10% per side + $0.01 per sell; Terry's floor ladder ($85;
$100 at a $125 close; $125 at a $150 close; close at/below floor ->
liquidate next open, run ends). Daily bars: free Yahoo Finance chart API,
split-adjusted, NOT dividend-adjusted. Fetch 2015-01-01 -> 2026-11-20.

v2 additions:
1. VOLATILITY SCALING: the two picks are weighted inversely to trailing
   20-day realized volatility (stdev of last 20 daily log returns,
   annualized x sqrt(252), computed at the reference close), normalized so
   the two positions sum to the invested share.
2. DEFENSIVE MODE: if SPY's reference close is below SPY's 200-day MA at a
   monthly selection, the invested share is capped at 50% of the pot.
3. DRAWDOWN LADDER: if the pot's last close is 7%+ below its peak close at
   a monthly selection, the invested share is capped at 50% until the pot
   makes a new peak (checked at each selection from closes through the
   reference day).

Windows:
A) 2025-11-21 -> 2026-11-20 (same as v0) + a random-pick PLACEBO twin.
B) 2016-11-21 -> 2026-11-20 (10 years); a floor halt ends the segment and a
   fresh $100 pot restarts on the first trading day on/after the next Jan 1.
"""
import csv, json, math, os, random, statistics, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
FETCH_FROM = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
FETCH_TO = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
COST_RATE = 0.001
SELL_FEE = 0.01
ET = ZoneInfo("America/New_York")
PLACEBO_SEED = 42


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
        self.bars = {t: fetch(t) for t in TICKERS}
        self.by_date = {t: {r["date"]: r for r in rows}
                        for t, rows in self.bars.items()}
        self.closes = {t: [r["close"] for r in rows]
                       for t, rows in self.bars.items()}
        self.dates_all = [r["date"] for r in self.bars["SPY"]]
        self.idx_of = {t: {r["date"]: i for i, r in enumerate(rows)}
                       for t, rows in self.bars.items()}

    def ma200(self, t, date):
        i = self.idx_of[t][date]
        if i < 199:
            return None
        return sum(self.closes[t][i - 199:i + 1]) / 200.0

    def mom63(self, t, date):
        i = self.idx_of[t][date]
        if i < 63:
            return None
        return self.closes[t][i] / self.closes[t][i - 63] - 1.0

    def vol20(self, t, date):
        """Annualized realized vol from the last 20 daily log returns."""
        i = self.idx_of[t][date]
        if i < 20:
            return None
        c = self.closes[t]
        rets = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
        return statistics.stdev(rets) * math.sqrt(252)


def run_sim(mkt, start, end, mode="v2", seed=PLACEBO_SEED):
    """Run one fresh $100 pot from the first trading day on/after `start`
    through `end` (inclusive). mode: 'v2' (momentum picks) or 'placebo'
    (random picks from the eligible set, same machinery)."""
    dates_all = mkt.dates_all
    period = [d for d in dates_all if start <= d <= end]
    if not period:
        return None
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d) - 1] for d in period}

    selection_days = set()
    seen_months = set()
    for d in period:
        ym = d[:7]
        if d == first_day or ym not in seen_months:
            selection_days.add(d)
        seen_months.add(ym)

    rng = random.Random(seed)
    cash = 100.0
    shares = {t: 0.0 for t in TICKERS}
    trades = []
    total_costs = 0.0
    floor = 85.0
    peak_close = 100.0
    pending_exits = set()
    liquidate_next_open = False
    halt_trigger_date = None
    halted = False
    final_balance = None
    selections = []
    daily = []  # (date, close_equity, n_positions)

    def equity(price_map):
        return cash + sum(shares[t] * price_map[t] for t in TICKERS)

    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        n = value / price
        cash -= value + cost
        total_costs += cost
        shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    for d in period:
        opens = {t: mkt.by_date[t][d]["open"] for t in TICKERS}
        closes_today = {t: mkt.by_date[t][d]["close"] for t in TICKERS}

        # 1) floor liquidation at the open ends the run
        if liquidate_next_open:
            for t in TICKERS:
                if shares[t] > 0:
                    do_sell(t, d, opens[t], "floor-liquidation")
            halted = True
            final_balance = cash
            daily.append((d, cash, 0))
            break

        # 2) scheduled trend exits at the open
        for t in sorted(pending_exits):
            if shares[t] > 0:
                do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()

        # 3) monthly selection / rebalance at the open
        if d in selection_days:
            ref = prior_day[d]
            info = {}
            for t in TICKERS:
                ma = mkt.ma200(t, ref)
                c = mkt.by_date[t][ref]["close"]
                info[t] = {"close": c, "ma200": ma,
                           "eligible": (ma is not None and c > ma),
                           "mom63": mkt.mom63(t, ref),
                           "vol20": mkt.vol20(t, ref)}
            eligible = [t for t in TICKERS if info[t]["eligible"]]
            if mode == "placebo":
                k = min(2, len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                ranked = sorted(eligible,
                                key=lambda t: info[t]["mom63"], reverse=True)
                picks = ranked[:2]

            # invested share: v0 base, then v2 caps
            if len(picks) == 0:
                share = 0.0
            elif len(picks) == 1:
                share = 0.5
            else:
                share = 1.0
            spy_ma = info["SPY"]["ma200"]
            defensive = (spy_ma is not None
                         and info["SPY"]["close"] < spy_ma)
            if defensive:
                share = min(share, 0.5)
            ref_equity = daily[-1][1] if daily else 100.0
            dd_from_peak = ((peak_close - ref_equity) / peak_close
                            if peak_close > 0 else 0.0)
            dd_cap = dd_from_peak >= 0.07
            if dd_cap:
                share = min(share, 0.5)

            # volatility weights (inverse vol, normalized over picks)
            weights = {}
            if picks:
                inv = {}
                for t in picks:
                    v = info[t]["vol20"]
                    inv[t] = (1.0 / v) if (v and v > 1e-9) else None
                if any(v is None for v in inv.values()):
                    weights = {t: 1.0 / len(picks) for t in picks}
                else:
                    tot = sum(inv.values())
                    weights = {t: inv[t] / tot for t in picks}
            selections.append({
                "date": d, "ref": ref, "picks": picks,
                "weights": {t: round(weights.get(t, 0.0), 4) for t in picks},
                "share": share, "defensive": defensive, "dd_cap": dd_cap,
                "dd_from_peak_pct": round(dd_from_peak * 100, 2),
                "info": info})

            eq_open = equity(opens)
            targets = {t: share * eq_open * weights.get(t, 0.0)
                       for t in picks}
            for t in TICKERS:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    reason = ("monthly-sell-dropout" if t not in targets
                              else "monthly-rebalance-trim")
                    do_sell(t, d, opens[t], reason, (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            total_want_cost = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = 1.0
            if total_want_cost > cash and total_want_cost > 0:
                scale = max(cash, 0.0) / total_want_cost
            for t in picks:
                if t in wants:
                    reason = ("monthly-buy" if shares[t] == 0
                              else "monthly-rebalance-add")
                    do_buy(t, d, opens[t], wants[t] * scale, reason)

        n_pos = sum(1 for t in TICKERS if shares[t] > 1e-9)
        eq_close = equity(closes_today)
        daily.append((d, eq_close, n_pos))
        if eq_close > peak_close:
            peak_close = eq_close

        # 4) floor ladder + breach check at the close
        if eq_close >= 150.0:
            floor = max(floor, 125.0)
        elif eq_close >= 125.0:
            floor = max(floor, 100.0)
        if eq_close <= floor:
            if d == last_day:
                for t in TICKERS:
                    if shares[t] > 0:
                        do_sell(t, d, closes_today[t], "floor-liquidation")
                halted = True
                halt_trigger_date = d
                final_balance = cash
            else:
                liquidate_next_open = True
                halt_trigger_date = d
            if halted:
                break
            continue

        # 5) trend-exit check at the close
        for t in TICKERS:
            if shares[t] > 1e-9:
                ma = mkt.ma200(t, d)
                if ma is not None and closes_today[t] < ma:
                    pending_exits.add(t)

    if not halted:
        closes_last = {t: mkt.by_date[t][last_day]["close"] for t in TICKERS}
        for t in TICKERS:
            if shares[t] > 0:
                do_sell(t, last_day, closes_last[t], "final-liquidation")
        final_balance = cash

    # ---- stats ----
    peak, max_dd = 100.0, 0.0
    peak_date, trough_date, run_peak_date = first_day, None, first_day
    for dte, eq, _ in daily:
        if eq > peak:
            peak, run_peak_date = eq, dte
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd, peak_date, trough_date = dd, run_peak_date, dte
    n_days = len(daily)
    full = sum(1 for _, _, n in daily if n == 2)
    half = sum(1 for _, _, n in daily if n == 1)
    zero = sum(1 for _, _, n in daily if n == 0)
    month_end = {}
    for dte, eq, _ in daily:
        month_end[dte[:7]] = (dte, eq)
    buys = sum(1 for t in trades if t["side"] == "buy")
    sells = sum(1 for t in trades if t["side"] == "sell")

    return {
        "mode": mode, "first_day": first_day, "last_day": last_day,
        "halted": halted, "halt_trigger_date": halt_trigger_date,
        "final_balance": round(final_balance, 2),
        "return_pct": round((final_balance / 100.0 - 1.0) * 100, 2),
        "total_trades": len(trades), "buys": buys, "sells": sells,
        "total_costs": round(total_costs, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "dd_peak_date": peak_date, "dd_trough_date": trough_date,
        "peak_close_equity": round(peak, 2), "final_floor": floor,
        "days": n_days,
        "pct_full": round(100 * full / n_days, 1) if n_days else 0.0,
        "pct_half": round(100 * half / n_days, 1) if n_days else 0.0,
        "pct_cash": round(100 * zero / n_days, 1) if n_days else 0.0,
        "n_defensive": sum(1 for s in selections if s["defensive"]),
        "n_dd_cap": sum(1 for s in selections if s["dd_cap"]),
        "month_end": {k: [v[0], round(v[1], 2)]
                      for k, v in month_end.items()},
        "selections": [{
            "date": s["date"], "ref": s["ref"], "picks": s["picks"],
            "weights": s["weights"], "share": s["share"],
            "defensive": s["defensive"], "dd_cap": s["dd_cap"],
            "dd_from_peak_pct": s["dd_from_peak_pct"],
            "info": {t: {"close": round(s["info"][t]["close"], 2),
                         "ma200": (round(s["info"][t]["ma200"], 2)
                                   if s["info"][t]["ma200"] else None),
                         "eligible": s["info"][t]["eligible"],
                         "mom63_pct": (round(s["info"][t]["mom63"] * 100, 2)
                                       if s["info"][t]["mom63"] is not None
                                       else None),
                         "vol20_pct": (round(s["info"][t]["vol20"] * 100, 2)
                                       if s["info"][t]["vol20"] is not None
                                       else None)}
                     for t in TICKERS}} for s in selections],
        "daily": [(dte, round(eq, 4), n) for dte, eq, n in daily],
        "trades": trades,
    }


def benchmark(mkt, start, end):
    period = [d for d in mkt.dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    spy_open = mkt.by_date["SPY"][first_day]["open"]
    spy_close = mkt.by_date["SPY"][last_day]["close"]
    gross = 100.0 / spy_open * spy_close
    sh = 100.0 / (spy_open * (1 + COST_RATE))
    net = sh * spy_close * (1 - COST_RATE) - SELL_FEE
    return {"first_day": first_day, "last_day": last_day,
            "spy_open": round(spy_open, 2), "spy_close": round(spy_close, 2),
            "gross": round(gross, 2), "net": round(net, 2),
            "gross_pct": round((gross / 100 - 1) * 100, 2),
            "net_pct": round((net / 100 - 1) * 100, 2)}


def main():
    mkt = Market()
    out = {}

    # ---- Window A: v2 + placebo + benchmark ----
    a = run_sim(mkt, "2025-11-21", "2026-11-20", mode="v2")
    p = run_sim(mkt, "2025-11-21", "2026-11-20", mode="placebo")
    out["windowA"] = {"v2": a, "placebo": p,
                      "benchmark": benchmark(mkt, "2025-11-21", "2026-11-20")}

    # window A trades CSV (v2 only, per spec)
    with open(os.path.join(HERE, "disciplined-v2-trades.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "price",
                                          "shares", "value", "reason"])
        w.writeheader()
        w.writerows(a["trades"])

    # ---- Window B: 10 years with restarts ----
    segments = []
    seg_start = "2016-11-21"
    while True:
        seg = run_sim(mkt, seg_start, "2026-11-20", mode="v2")
        if seg is None:
            break
        segments.append(seg)
        if not seg["halted"]:
            break
        halt_year = int(seg["daily"][-1][0][:4])
        nxt = f"{halt_year + 1}-01-01"
        if nxt > "2026-11-20":
            break
        seg_start = nxt
    out["windowB"] = {"segments": segments,
                      "benchmark": benchmark(mkt, "2016-11-21", "2026-11-20")}

    # per-year table for window B
    daily_all = []
    for si, seg in enumerate(segments):
        for dte, eq, n in seg["daily"]:
            daily_all.append((dte, eq, si))
    years = {}
    for dte, eq, si in daily_all:
        years.setdefault(int(dte[:4]), []).append((dte, eq, si))
    spy_close = {r["date"]: r["close"] for r in mkt.bars["SPY"]}
    year_rows = []
    prev_year_end_spy = None
    for y in sorted(years):
        rows = years[y]
        first_d, first_eq, first_seg = rows[0]
        last_d, last_eq, _ = rows[-1]
        fresh = any(seg["first_day"][:4] == str(y) and i > 0
                    for i, seg in enumerate(segments))
        if y == sorted(years)[0] and not fresh:
            start_val = 100.0
        elif fresh:
            start_val = 100.0
        else:
            start_val = year_rows[-1]["end_value"]
        # SPY year return: close of last trading day of prior year ->
        # close of last trading day of this year (period-start ref for 2016)
        if prev_year_end_spy is None:
            idx = mkt.dates_all.index(segments[0]["first_day"])
            prev_year_end_spy = spy_close[mkt.dates_all[idx - 1]]
        spy_end = spy_close[last_d]
        year_rows.append({
            "year": y, "start_value": round(start_val, 2),
            "end_value": round(last_eq, 2),
            "return_pct": round((last_eq / start_val - 1) * 100, 2),
            "spy_return_pct": round((spy_end / prev_year_end_spy - 1) * 100, 2),
            "fresh_start": bool(fresh), "first_day": first_d,
            "last_day": last_d})
        prev_year_end_spy = spy_end
    out["windowB"]["year_rows"] = year_rows

    chained = 100.0
    for seg in segments:
        chained *= seg["final_balance"] / 100.0
    out["windowB"]["chained_final"] = round(chained, 2)
    out["windowB"]["chained_pct"] = round((chained / 100 - 1) * 100, 2)

    with open(os.path.join(HERE, "disciplined-v2-results.json"), "w") as f:
        json.dump(out, f, indent=2)

    def brief(r):
        return {k: r[k] for k in ("mode", "first_day", "last_day", "halted",
                                  "halt_trigger_date", "final_balance",
                                  "return_pct", "total_trades",
                                  "total_costs", "max_drawdown_pct",
                                  "peak_close_equity", "days", "pct_full",
                                  "pct_half", "pct_cash", "n_defensive",
                                  "n_dd_cap")}
    print("WINDOW A v2:     ", json.dumps(brief(a)))
    print("WINDOW A placebo:", json.dumps(brief(p)))
    print("BENCH A:         ", json.dumps(out["windowA"]["benchmark"]))
    for i, seg in enumerate(segments):
        print(f"WINDOW B seg {i}:  ", json.dumps(brief(seg)))
    print("BENCH B:         ", json.dumps(out["windowB"]["benchmark"]))
    print("YEAR ROWS:       ", json.dumps(year_rows))
    print("CHAINED B:       ", out["windowB"]["chained_final"],
          out["windowB"]["chained_pct"])


if __name__ == "__main__":
    main()
