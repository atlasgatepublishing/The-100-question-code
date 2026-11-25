#!/usr/bin/env python3
"""
PEAD-LITE backtest for Terry's AI stock app (simulation only).

Rule (from ~/workspace/stock-app/research/v3-edges.md section 1):
  - Universe: 20 liquid listed names (below).
  - Event: SEC EDGAR 8-K (or 8-K/A) filing containing Item 2.02 (earnings release).
    Signal date = the FILING date (point-in-time; never the period date).
  - Announcement-window excess return = (filing-day close / prior trading-day close - 1)
    minus SPY's same-day return. If >= +5%, buy at the NEXT trading day's open.
  - Hold 40 trading days; exit earlier on a -8% stop (intraday low, stop-first)
    or if SPY closes below its 200-day average (regime exit at next open).
  - Max 3 concurrent positions; equal slices of available cash
    (slice = cash / open slots). One entry per name per earnings season
    (63-trading-day cooldown per name).
  - Costs: 0.10% of trade value per side + $0.01 per sell order. Fractional shares.
  - Terry's floor (scaled): $50 pot -> floor $42.50, ladder to $50.00 at a $62.50
    close, to $62.50 at a $75.00 close. $100 pot -> floor $85, ladder $100 @ $125,
    $125 @ $150. Close at/below floor -> liquidate everything at next open, run ends.

Windows: DESIGN 2019-01-01..2022-12-31, VALIDATION 2023-01-01..2026-11-20.
Placebo (validation only): entries on RANDOM 8-K filing dates (any item) of the
same companies, matched to the real strategy's entry count, seed 42, same machinery.

Data: EDGAR submissions API (free, User-Agent declared, <10 req/s, cached) and
Yahoo Finance chart API daily bars (split-adjusted, not dividend-adjusted).
"""
import json, os, random, sys, time
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "pead-cache")
os.makedirs(CACHE, exist_ok=True)

UA_EDGAR = {"User-Agent": "StockAppResearch admin@example.com"}
UA_WEB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

TICKERS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO",
           "GOOGL", "NFLX", "COST", "JPM", "XOM", "UNH", "HD", "MA", "V",
           "LLY", "CRM", "ORCL"]
PRICE_TICKERS = TICKERS + ["SPY"]

BUY_COST = 0.0010
SELL_COST = 0.0010
SELL_FEE = 0.01
HOLD_DAYS = 40
STOP_PCT = 0.08
MAX_POS = 3
COOLDOWN = 63          # trading days, one entry per name per earnings season
EXCESS_MIN = 0.05      # +5% announcement-window excess return
PLACEBO_SEED = 42

DATA_START = date(2018, 1, 1)
DATA_END = date(2026, 11, 21)
EVENT_FROM = date(2018, 12, 1)


def fetch(url, headers, cache_name, binary=False):
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
    else:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        with open(path, "wb") as f:
            f.write(raw)
        time.sleep(0.15)  # EDGAR etiquette: well under 10 req/s
    return raw if binary else json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------- EDGAR events
def get_ciks():
    data = fetch("https://www.sec.gov/files/company_tickers.json", UA_EDGAR,
                 "company_tickers.json")
    m = {}
    for row in data.values():
        if row["ticker"] in TICKERS:
            m[row["ticker"]] = str(row["cik_str"]).zfill(10)
    missing = [t for t in TICKERS if t not in m]
    if missing:
        raise SystemExit(f"CIK not found for {missing}")
    return m


def filings_from_block(block, out, ticker):
    forms = block.get("form", [])
    dates = block.get("filingDate", [])
    items = block.get("items", [])
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        try:
            fd = datetime.strptime(dates[i], "%Y-%m-%d").date()
        except Exception:
            continue
        if fd < EVENT_FROM or fd > DATA_END:
            continue
        out.append({"ticker": ticker, "filing_date": fd,
                    "items": items[i] if i < len(items) else "", "form": form})


def get_events():
    """Returns (earnings_events, all_8k_events)."""
    cache_file = os.path.join(CACHE, "events.json")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            raw = json.load(f)
        conv = lambda rows: [{"ticker": r["ticker"],
                              "filing_date": date.fromisoformat(r["filing_date"]),
                              "items": r["items"], "form": r["form"]} for r in rows]
        return conv(raw["earnings"]), conv(raw["all8k"])
    ciks = get_ciks()
    earnings, all8k = [], []
    for t in TICKERS:
        cik = ciks[t]
        sub = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json", UA_EDGAR,
                    f"sub_{t}.json")
        rows = []
        filings_from_block(sub["filings"]["recent"], rows, t)
        for extra in sub["filings"].get("files", []):
            if extra["filingTo"] < "2018-12-01" or extra["filingFrom"] > "2026-11-21":
                continue
            block = fetch(f"https://data.sec.gov/submissions/{extra['name']}",
                          UA_EDGAR, f"sub_{t}_{extra['name']}")
            filings_from_block(block, rows, t)
        seen = set()
        for r in rows:
            key = (r["ticker"], r["filing_date"], r["form"])
            if key in seen:
                continue
            seen.add(key)
            all8k.append(r)
            if "2.02" in [s.strip() for s in r["items"].split(",")]:
                earnings.append(r)
        print(f"  EDGAR {t}: {len(rows)} 8-K rows, "
              f"{sum(1 for r in rows if '2.02' in [s.strip() for s in r['items'].split(',')])} with Item 2.02",
              file=sys.stderr)
    ser = lambda rows: [{"ticker": r["ticker"], "filing_date": r["filing_date"].isoformat(),
                         "items": r["items"], "form": r["form"]} for r in rows]
    with open(cache_file, "w") as f:
        json.dump({"earnings": ser(earnings), "all8k": ser(all8k)}, f)
    return earnings, all8k


# ---------------------------------------------------------------- Yahoo prices
def get_bars(ticker):
    p1 = int(datetime(2018, 1, 1, tzinfo=ZoneInfo("UTC")).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=ZoneInfo("UTC")).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    data = fetch(url, UA_WEB, f"px_{ticker}.json")
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    ny = ZoneInfo("America/New_York")
    bars = {}
    for i, tsec in enumerate(ts):
        c = q["close"][i]
        if c is None or q["open"][i] is None:
            continue
        d = datetime.fromtimestamp(tsec, ny).date()
        bars[d] = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": c}
    return bars


# ---------------------------------------------------------------- simulation
class Sim:
    def __init__(self, calendar, bars, spy_close, spy_ma200, start_cash,
                 floor, ladder, max_entries=None):
        self.cal = calendar                      # list[date], window only
        self.cal_idx = {d: i for i, d in enumerate(self.cal)}
        self.bars = bars
        self.spy_close = spy_close               # date -> close (full history)
        self.spy_ma = spy_ma200                  # date -> ma200 or None
        self.cash = start_cash
        self.floor = floor
        self.ladder = ladder                     # list[(threshold, new_floor)] asc
        self.max_entries = max_entries
        self.positions = []                      # dicts
        self.trades = []                         # closed round trips
        self.total_costs = 0.0
        self.entries = 0
        self.halted = False
        self.halt_date = None
        self.last_entry_idx = {}                 # ticker -> global day index
        self.pending_liquidation = False
        self.pending_regime_exit = False

    def sell(self, pos, price, reason, d):
        proceeds = pos["shares"] * price
        cost = proceeds * SELL_COST + SELL_FEE
        self.cash += proceeds - cost
        self.total_costs += cost
        pnl = (proceeds - cost) - pos["cost_basis"]
        self.trades.append({"ticker": pos["ticker"], "entry_date": pos["entry_date"],
                            "exit_date": d, "entry_price": pos["entry_price"],
                            "exit_price": price, "pnl": pnl,
                            "pnl_pct": pnl / pos["cost_basis"] * 100,
                            "reason": reason})
        self.positions.remove(pos)

    def run(self, signals):
        """signals: list of dicts {buy_date, ticker, excess} sorted by buy_date."""
        sig_by_day = {}
        for s in signals:
            sig_by_day.setdefault(s["buy_date"], []).append(s)
        for d in self.cal:
            gi = GLOBAL_IDX[d]
            # 1) floor liquidation at open
            if self.pending_liquidation:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "floor", d)
                self.halted = True
                self.halt_date = d
                break
            # 2) regime exit at open (flag set at prior close)
            if self.pending_regime_exit:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "regime", d)
                self.pending_regime_exit = False
            # 3) intraday stops (stop-first)
            for pos in list(self.positions):
                bar = self.bars[pos["ticker"]][d]
                if bar["low"] <= pos["stop_price"]:
                    px = bar["open"] if bar["open"] < pos["stop_price"] else pos["stop_price"]
                    self.sell(pos, px, "stop", d)
            # 4) buys at open
            if not self.halted:
                for s in sig_by_day.get(d, []):
                    if self.max_entries is not None and self.entries >= self.max_entries:
                        break
                    t = s["ticker"]
                    if len(self.positions) >= MAX_POS:
                        continue
                    if any(p["ticker"] == t for p in self.positions):
                        continue
                    if gi - self.last_entry_idx.get(t, -10**9) < COOLDOWN:
                        continue
                    slots = MAX_POS - len(self.positions)
                    spend = self.cash / slots
                    if spend < 2.0:
                        continue
                    px = self.bars[t][d]["open"]
                    if px is None or px <= 0:
                        continue
                    shares = spend / (px * (1 + BUY_COST))
                    cost = spend - shares * px
                    self.cash -= spend
                    self.total_costs += cost
                    self.positions.append({
                        "ticker": t, "shares": shares, "entry_price": px,
                        "entry_date": d, "entry_gidx": gi,
                        "cost_basis": spend, "stop_price": px * (1 - STOP_PCT)})
                    self.entries += 1
                    self.last_entry_idx[t] = gi
            # 5) hold-end exits at close (40 trading days: entry day = day 1)
            for pos in list(self.positions):
                if gi - pos["entry_gidx"] >= HOLD_DAYS - 1:
                    self.sell(pos, self.bars[pos["ticker"]][d]["close"], "hold_end", d)
            # 6) close-of-day: regime flag, ladder, floor check
            ma = self.spy_ma.get(d)
            if self.positions and ma is not None and self.spy_close[d] < ma:
                self.pending_regime_exit = True
            value = self.cash + sum(p["shares"] * self.bars[p["ticker"]][d]["close"]
                                    for p in self.positions)
            for thresh, new_floor in self.ladder:
                if value >= thresh and new_floor > self.floor:
                    self.floor = new_floor
            if value <= self.floor:
                self.pending_liquidation = True
        # end of window: liquidate anything left at final close
        if not self.halted and self.positions:
            d = self.cal[-1]
            for pos in list(self.positions):
                self.sell(pos, self.bars[pos["ticker"]][d]["close"], "window_end", d)
        return self

    def summary(self, start_cash, spy_net_final):
        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        return {
            "start": start_cash, "final": round(self.cash, 2),
            "return_pct": round((self.cash / start_cash - 1) * 100, 2),
            "spy_net_final": spy_net_final,
            "entries": self.entries, "round_trips": len(self.trades),
            "win_rate_pct": round(len(wins) / len(self.trades) * 100, 1) if self.trades else None,
            "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
            "total_costs": round(self.total_costs, 2),
            "halted": self.halted,
            "halt_date": self.halt_date.isoformat() if self.halt_date else None,
            "exit_reasons": {r: sum(1 for t in self.trades if t["reason"] == r)
                             for r in ("stop", "hold_end", "regime", "floor", "window_end")},
        }


def spy_benchmark(cal, spy_bars, start_cash):
    first, last = cal[0], cal[-1]
    buy_px = spy_bars[first]["open"]
    shares = start_cash / (buy_px * (1 + BUY_COST))
    proceeds = shares * spy_bars[last]["close"]
    return round(proceeds - (proceeds * SELL_COST + SELL_FEE), 2)


def build_signals(events, bars, spy_bars, cal_set, win_start, win_end):
    """Real PEAD signals: filing-day excess return >= +5% -> buy next open."""
    sigs = []
    for e in events:
        fd = e["filing_date"]
        # day0 = first trading day on/after the filing date
        day0 = next((d for d in ALL_DAYS if d >= fd), None)
        if day0 is None:
            continue
        gi = GLOBAL_IDX[day0]
        if gi == 0:
            continue
        prev = ALL_DAYS[gi - 1]
        t = e["ticker"]
        if day0 not in bars[t] or prev not in bars[t]:
            continue
        r_stock = bars[t][day0]["close"] / bars[t][prev]["close"] - 1
        r_spy = spy_bars[day0]["close"] / spy_bars[prev]["close"] - 1
        excess = r_stock - r_spy
        if excess < EXCESS_MIN:
            continue
        if gi + 1 >= len(ALL_DAYS):
            continue
        buy_date = ALL_DAYS[gi + 1]
        if win_start <= buy_date <= win_end:
            sigs.append({"buy_date": buy_date, "ticker": t, "excess": excess,
                         "filing_date": fd})
    sigs.sort(key=lambda s: (s["buy_date"], -s["excess"]))
    return sigs


def build_placebo_pool(events, bars, win_start, win_end):
    pool = []
    for e in events:
        fd = e["filing_date"]
        day0 = next((d for d in ALL_DAYS if d >= fd), None)
        if day0 is None:
            continue
        gi = GLOBAL_IDX[day0]
        if gi + 1 >= len(ALL_DAYS):
            continue
        buy_date = ALL_DAYS[gi + 1]
        if win_start <= buy_date <= win_end and buy_date in bars[e["ticker"]]:
            pool.append({"buy_date": buy_date, "ticker": e["ticker"],
                         "excess": 0.0, "filing_date": fd})
    return pool


WINDOWS = {
    "design": (date(2019, 1, 1), date(2022, 12, 31)),
    "validation": (date(2023, 1, 1), date(2026, 11, 20)),
}
POTS = {
    50: {"floor": 42.50, "ladder": [(62.50, 50.00), (75.00, 62.50)]},
    100: {"floor": 85.00, "ladder": [(125.00, 100.00), (150.00, 125.00)]},
}


def main():
    print("Fetching EDGAR events...", file=sys.stderr)
    earnings, all8k = get_events()
    print(f"Earnings (Item 2.02) events: {len(earnings)}; all 8-K events: {len(all8k)}",
          file=sys.stderr)
    print("Fetching prices...", file=sys.stderr)
    bars = {t: get_bars(t) for t in PRICE_TICKERS}
    spy = bars["SPY"]
    global ALL_DAYS, GLOBAL_IDX
    ALL_DAYS = sorted(spy.keys())
    GLOBAL_IDX = {d: i for i, d in enumerate(ALL_DAYS)}
    spy_close = {d: spy[d]["close"] for d in ALL_DAYS}
    spy_ma = {}
    closes = [spy[d]["close"] for d in ALL_DAYS]
    for i, d in enumerate(ALL_DAYS):
        spy_ma[d] = sum(closes[i - 199:i + 1]) / 200 if i >= 199 else None

    results = {}
    all_trades = {}
    for wname, (ws, we) in WINDOWS.items():
        cal = [d for d in ALL_DAYS if ws <= d <= we]
        results[wname] = {}
        sigs = build_signals(earnings, bars, spy, set(cal), ws, we)
        print(f"{wname}: {len(sigs)} PEAD signals", file=sys.stderr)
        for pot, cfg in POTS.items():
            bench = spy_benchmark(cal, spy, pot)
            sim = Sim(cal, bars, spy_close, spy_ma, float(pot),
                      cfg["floor"], cfg["ladder"]).run(sigs)
            results[wname][pot] = sim.summary(float(pot), bench)
            all_trades[f"{wname}_{pot}"] = sim.trades
            print(f"  ${pot}: final ${sim.cash:.2f} (SPY net ${bench}), "
                  f"{sim.entries} entries, halted={sim.halted}", file=sys.stderr)
        # placebo on validation only
        if wname == "validation":
            pool = build_placebo_pool(all8k, bars, ws, we)
            results[wname]["placebo"] = {}
            for pot, cfg in POTS.items():
                target = results[wname][pot]["entries"]
                rng = random.Random(PLACEBO_SEED)
                sampled = rng.sample(pool, min(len(pool), max(target * 6, target)))
                sampled.sort(key=lambda s: s["buy_date"])
                bench = spy_benchmark(cal, spy, pot)
                sim = Sim(cal, bars, spy_close, spy_ma, float(pot),
                          cfg["floor"], cfg["ladder"],
                          max_entries=target).run(sampled)
                s = sim.summary(float(pot), bench)
                s["target_entries"] = target
                s["pool_size"] = len(pool)
                results[wname]["placebo"][pot] = s
                all_trades[f"validation_placebo_{pot}"] = sim.trades
                print(f"  placebo ${pot}: final ${sim.cash:.2f}, "
                      f"{sim.entries}/{target} entries", file=sys.stderr)

    with open(os.path.join(BASE, "pead-results.json"), "w") as f:
        json.dump({"results": results,
                   "trades": {k: [{**t, "entry_date": t["entry_date"].isoformat(),
                                   "exit_date": t["exit_date"].isoformat(),
                                   "pnl": round(t["pnl"], 2),
                                   "pnl_pct": round(t["pnl_pct"], 2),
                                   "entry_price": round(t["entry_price"], 2),
                                   "exit_price": round(t["exit_price"], 2)}
                                  for t in v] for k, v in all_trades.items()}},
                  f, indent=1)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
