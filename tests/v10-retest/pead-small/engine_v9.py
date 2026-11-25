#!/usr/bin/env python3
"""
PEAD IN SMALLER NAMES backtest for Terry's AI stock app (simulation only).

Retry of PEAD-lite (v3, mega-caps: FAILED, validation -8.55% at $50,
placebo-identical) in the universe where the literature says the drift
survives: smaller, less-followed listed names (Martineau 2019; Ali et al.
2020; Cox 2020 — see research/v3-edges.md section 1).

Rule (frozen; identical to pead-lite except universe + cost gate):
  - Seed universe: 45 documented mid/small-leaning listed names (below).
    A name is tradeable on a given event only if it passes the point-in-time
    screen on the filing day:
      * close in [$5, $60]
      * trailing 63-trading-day average daily dollar volume > $5,000,000
      * Corwin-Schultz high-low spread proxy (trailing 20 trading days,
        averaged, floored at 0) <= 1.5%  -> otherwise the entry is SKIPPED
  - Event: SEC EDGAR 8-K / 8-K/A containing Item 2.02 (earnings release).
    Signal date = FILING date (point-in-time; never the period date).
  - Surprise proxy (free): announcement-window excess return = filing-day
    close vs prior close, minus SPY's same-day return. >= +5% -> buy at the
    NEXT trading day's open.
  - Hold 40 trading days; exit earlier on a -8% stop (intraday low,
    stop-first) or if SPY closes below its 200-day average (regime exit at
    next open). Max 3 concurrent positions, equal slices of available cash
    (slice = cash / open slots). One entry per name per 63 trading days.
  - Costs: 0.35% of trade value per side + $0.01 per sell order (smaller
    names have wider spreads - charged honestly). Fractional shares.
    (The SPY benchmark is charged the mega-cap rate, 0.10%/side + $0.01:
    SPY itself is ultra-liquid.)
  - Terry's floor: $50 pot -> floor $42.50, ladder to $50.00 at a $62.50
    close, to $62.50 at a $75.00 close. $100 pot -> floor $85, ladder
    $100 @ $125, $125 @ $150. Close at/below floor -> liquidate next open.

Windows: DESIGN 2019-01-01..2022-12-31, VALIDATION 2023-01-01..2026-11-20.
Placebo (validation only, seed 42): entries on RANDOM non-earnings 8-K
filing dates of the same companies (same screens applied), matched to the
real strategy's entry count, identical machinery.

Data: EDGAR submissions API (free, User-Agent declared, <10 req/s, cached)
and Yahoo Finance chart API daily bars (split-adjusted prices, not
dividend-adjusted; volume as reported by Yahoo).
"""
import json, math, os, random, sys, time
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
# v10 NOTE: cache redirected to the original v4 cache (read-only shared cache;
# identical to the v9 folder cache, which is a symlink to it). SKX has no px
# file there (Yahoo 404 in the original runs too) and returns {} as before.
CACHE = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
os.makedirs(CACHE, exist_ok=True)

UA_EDGAR = {"User-Agent": "StockAppResearch admin@example.com"}
UA_WEB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

# Seed universe: mid/small-leaning listed names (Russell Midcap / Russell
# 2000 / S&P MidCap 400 space). PLUG-type sub-$5 penny names excluded by
# design; the point-in-time screen below does the real filtering.
SEEDS = [
    # growth / software / fintech
    "PLTR", "SOFI", "HOOD", "AFRM", "CVNA", "DKNG", "RBLX", "U", "AI",
    "PATH", "TOST", "APP", "SMCI",
    # biotech / health
    "MRNA", "NTLA", "CRSP", "IONS", "HALO", "EXEL", "TDOC", "HIMS", "CNC",
    # consumer
    "CROX", "SKX", "ANF", "M", "UAA", "GME",
    # media / travel / social
    "AAL", "TRIP", "SNAP", "PINS", "LYFT", "ROKU", "WBD", "PARA",
    # crypto miners
    "MARA", "RIOT",
    # energy / materials
    "DVN", "AA", "CLF",
    # regional banks
    "KEY", "HBAN",
    # semis / storage
    "WDC", "ON",
]
# Tickers that may have rotated off the current company_tickers.json
# (mergers / take-privates during the window) -> known CIKs as fallback.
CIK_FALLBACK = {"PARA": "0000813828", "SKX": "0001060349"}
NAME_CHECK = {"PARA": ("PARAMOUNT", "VIACOM"), "SKX": ("SKECHERS",)}

BUY_COST = 0.0035
SELL_COST = 0.0035
SELL_FEE = 0.01
SPY_COST = 0.0010           # benchmark charged at the ultra-liquid rate
HOLD_DAYS = 40
STOP_PCT = 0.08
MAX_POS = 3
COOLDOWN = 63               # trading days, one entry per name per season
EXCESS_MIN = 0.05           # +5% announcement-window excess return
PRICE_MIN, PRICE_MAX = 5.0, 60.0
ADV_MIN = 5_000_000         # trailing 63d avg daily dollar volume
ADV_DAYS = 63
SPREAD_MAX = 0.015          # Corwin-Schultz spread proxy cap
SPREAD_DAYS = 20
PLACEBO_SEED = 42

DATA_END = date(2026, 11, 21)
EVENT_FROM = date(2018, 12, 1)


def fetch(url, headers, cache_name):
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
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------- EDGAR events
def get_ciks():
    data = fetch("https://www.sec.gov/files/company_tickers.json", UA_EDGAR,
                 "company_tickers.json")
    m = {}
    for row in data.values():
        if row["ticker"] in SEEDS:
            m[row["ticker"]] = str(row["cik_str"]).zfill(10)
    for t, cik in CIK_FALLBACK.items():
        if t in SEEDS and t not in m:
            m[t] = cik
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


def get_events(ciks):
    """Returns (earnings_events, nonearnings_8k_events, per-ticker stats)."""
    cache_file = os.path.join(CACHE, "events.json")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            raw = json.load(f)
        conv = lambda rows: [{"ticker": r["ticker"],
                              "filing_date": date.fromisoformat(r["filing_date"]),
                              "items": r["items"], "form": r["form"]} for r in rows]
        return conv(raw["earnings"]), conv(raw["nonearnings"]), raw["stats"]
    earnings, nonearn, stats = [], [], {}
    for t in SEEDS:
        if t not in ciks:
            stats[t] = {"error": "no CIK found"}
            print(f"  EDGAR {t}: NO CIK - skipped", file=sys.stderr)
            continue
        cik = ciks[t]
        try:
            sub = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json",
                        UA_EDGAR, f"sub_{t}.json")
        except Exception as e:
            stats[t] = {"error": f"submissions fetch failed: {e}"}
            print(f"  EDGAR {t}: fetch failed ({e}) - skipped", file=sys.stderr)
            continue
        if t in NAME_CHECK:
            nm = (sub.get("name") or "").upper()
            if not any(s in nm for s in NAME_CHECK[t]):
                stats[t] = {"error": f"CIK name mismatch: {nm}"}
                print(f"  EDGAR {t}: CIK name mismatch ({nm}) - skipped",
                      file=sys.stderr)
                continue
        rows = []
        filings_from_block(sub["filings"]["recent"], rows, t)
        for extra in sub["filings"].get("files", []):
            if extra["filingTo"] < "2018-12-01" or extra["filingFrom"] > "2026-11-21":
                continue
            block = fetch(f"https://data.sec.gov/submissions/{extra['name']}",
                          UA_EDGAR, f"sub_{t}_{extra['name']}")
            filings_from_block(block, rows, t)
        seen, n_e = set(), 0
        for r in rows:
            key = (r["ticker"], r["filing_date"], r["form"], r["items"])
            if key in seen:
                continue
            seen.add(key)
            if "2.02" in [s.strip() for s in r["items"].split(",")]:
                earnings.append(r)
                n_e += 1
            else:
                nonearn.append(r)
        stats[t] = {"cik": cik, "n_8k": len(seen), "n_earnings": n_e}
        print(f"  EDGAR {t}: {len(seen)} 8-K rows, {n_e} with Item 2.02",
              file=sys.stderr)
    ser = lambda rows: [{"ticker": r["ticker"],
                         "filing_date": r["filing_date"].isoformat(),
                         "items": r["items"], "form": r["form"]} for r in rows]
    with open(cache_file, "w") as f:
        json.dump({"earnings": ser(earnings), "nonearnings": ser(nonearn),
                   "stats": stats}, f)
    return earnings, nonearn, stats


# ---------------------------------------------------------------- Yahoo prices
def get_bars(ticker):
    p1 = int(datetime(2018, 1, 1, tzinfo=ZoneInfo("UTC")).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=ZoneInfo("UTC")).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    try:
        data = fetch(url, UA_WEB, f"px_{ticker}.json")
        res = data["chart"]["result"][0]
    except Exception as e:
        print(f"  Yahoo {ticker}: fetch failed ({e})", file=sys.stderr)
        return {}
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    ny = ZoneInfo("America/New_York")
    bars = {}
    for i, tsec in enumerate(ts):
        c = q["close"][i]
        if c is None or q["open"][i] is None:
            continue
        d = datetime.fromtimestamp(tsec, ny).date()
        vol = q["volume"][i] if i < len(q.get("volume", [])) else None
        bars[d] = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": c, "volume": vol}
    return bars


# ---------------------------------------------------------------- screens
class Screener:
    """Point-in-time universe screens, evaluated on the filing day."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.days = {t: sorted(b.keys()) for t, b in bars_by_ticker.items()}
        self.idx = {t: {d: i for i, d in enumerate(ds)}
                    for t, ds in self.days.items()}
        self.cache = {}

    def cs_spread(self, t, end_i):
        """Corwin-Schultz spread estimate averaged over trailing pairs."""
        ds = self.days[t]
        vals = []
        for i in range(end_i - SPREAD_DAYS + 1, end_i + 1):
            if i - 1 < 0:
                continue
            b1, b2 = self.bars[t][ds[i - 1]], self.bars[t][ds[i]]
            if None in (b1["high"], b1["low"], b2["high"], b2["low"]):
                continue
            if min(b1["high"], b1["low"], b2["high"], b2["low"]) <= 0:
                continue
            beta = (math.log(b1["high"] / b1["low"])) ** 2 + \
                   (math.log(b2["high"] / b2["low"])) ** 2
            gamma = (math.log(max(b1["high"], b2["high"]) /
                              min(b1["low"], b2["low"]))) ** 2
            denom = 3 - 2 * math.sqrt(2)
            alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / denom - \
                math.sqrt(gamma / denom)
            s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
            vals.append(max(s, 0.0))
        return sum(vals) / len(vals) if vals else None

    def check(self, t, day0):
        """Returns (ok, reason). Reasons: ok/price/volume/spread/history."""
        key = (t, day0)
        if key in self.cache:
            return self.cache[key]
        out = self._check(t, day0)
        self.cache[key] = out
        return out

    def _check(self, t, day0):
        b = self.bars.get(t, {}).get(day0)
        if b is None:
            return (False, "nobars")
        if not (PRICE_MIN <= b["close"] <= PRICE_MAX):
            return (False, "price")
        i = self.idx[t][day0]
        if i < ADV_DAYS - 1:
            return (False, "history")
        ds = self.days[t]
        dv, n = 0.0, 0
        for j in range(i - ADV_DAYS + 1, i + 1):
            bar = self.bars[t][ds[j]]
            if bar["volume"]:
                dv += bar["close"] * bar["volume"]
                n += 1
        if n < 40 or dv / n <= ADV_MIN:
            return (False, "volume")
        sp = self.cs_spread(t, i)
        if sp is None or sp > SPREAD_MAX:
            return (False, "spread")
        return (True, "ok")


# ---------------------------------------------------------------- simulation
class Sim:
    def __init__(self, calendar, bars, spy_close, spy_ma200, start_cash,
                 floor, ladder, max_entries=None):
        self.cal = calendar
        self.bars = bars
        self.spy_close = spy_close
        self.spy_ma = spy_ma200
        self.cash = start_cash
        self.floor = floor
        self.ladder = ladder
        self.max_entries = max_entries
        self.positions = []
        self.trades = []
        self.total_costs = 0.0
        self.entries = 0
        self.halted = False
        self.halt_date = None
        self.last_entry_idx = {}
        self.pending_liquidation = False
        self.pending_regime_exit = False
        self.episode = 1
        self.restart_not_before = None
        self.v9_halts = []
        self.v9_restarts = []
        self._restart_logged = False

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
        sig_by_day = {}
        for s in signals:
            sig_by_day.setdefault(s["buy_date"], []).append(s)
        for d in self.cal:
            gi = GLOBAL_IDX[d]
            if self.pending_liquidation:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "floor", d)
                self.pending_liquidation = False
                self.v9_halts.append({"date": d.isoformat(),
                                      "balance": round(self.cash, 2),
                                      "episode": self.episode})
                if self.episode >= 2:
                    self.halted = True
                    self.halt_date = d
                    break
                from datetime import timedelta as _td
                self.restart_not_before = d + _td(days=90)
                self.episode = 2
                self.floor = 0.85 * self.cash
                continue
            if self.pending_regime_exit:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "regime", d)
                self.pending_regime_exit = False
            for pos in list(self.positions):
                bar = self.bars[pos["ticker"]][d]
                if bar["low"] <= pos["stop_price"]:
                    px = bar["open"] if bar["open"] < pos["stop_price"] else pos["stop_price"]
                    self.sell(pos, px, "stop", d)
            if self.restart_not_before is not None and not self._restart_logged and d >= self.restart_not_before:
                self.v9_restarts.append({"date": d.isoformat(),
                                         "balance": round(self.cash, 2),
                                         "episode2_floor": round(self.floor, 2)})
                self._restart_logged = True
            if not self.halted and not (self.restart_not_before is not None and d < self.restart_not_before):
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
            for pos in list(self.positions):
                if gi - pos["entry_gidx"] >= HOLD_DAYS - 1:
                    self.sell(pos, self.bars[pos["ticker"]][d]["close"], "hold_end", d)
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
            "v9_halts": self.v9_halts,
            "v9_restarts": self.v9_restarts,
            "exit_reasons": {r: sum(1 for t in self.trades if t["reason"] == r)
                             for r in ("stop", "hold_end", "regime", "floor", "window_end")},
        }


def spy_benchmark(cal, spy_bars, start_cash):
    first, last = cal[0], cal[-1]
    buy_px = spy_bars[first]["open"]
    shares = start_cash / (buy_px * (1 + SPY_COST))
    proceeds = shares * spy_bars[last]["close"]
    return round(proceeds - (proceeds * SPY_COST + SELL_FEE), 2)


def day0_of(fd):
    return next((d for d in ALL_DAYS if d >= fd), None)


def build_signals(events, bars, spy_bars, screener, win_start, win_end, diag):
    """Real PEAD signals: screen pass + filing-day excess >= +5% -> buy next open."""
    sigs = []
    for e in events:
        fd = e["filing_date"]
        day0 = day0_of(fd)
        if day0 is None:
            continue
        gi = GLOBAL_IDX[day0]
        if gi == 0 or gi + 1 >= len(ALL_DAYS):
            continue
        buy_date = ALL_DAYS[gi + 1]
        if not (win_start <= buy_date <= win_end):
            continue
        t = e["ticker"]
        ok, reason = screener.check(t, day0)
        if not ok:
            diag[f"screen_{reason}"] = diag.get(f"screen_{reason}", 0) + 1
            continue
        prev = ALL_DAYS[gi - 1]
        if day0 not in bars[t] or prev not in bars[t]:
            continue
        r_stock = bars[t][day0]["close"] / bars[t][prev]["close"] - 1
        r_spy = spy_bars[day0]["close"] / spy_bars[prev]["close"] - 1
        excess = r_stock - r_spy
        if excess < EXCESS_MIN:
            diag["excess_below_5pct"] = diag.get("excess_below_5pct", 0) + 1
            continue
        diag["signals"] = diag.get("signals", 0) + 1
        sigs.append({"buy_date": buy_date, "ticker": t, "excess": excess,
                     "filing_date": fd})
    sigs.sort(key=lambda s: (s["buy_date"], -s["excess"]))
    return sigs


def build_placebo_pool(events, bars, screener, win_start, win_end):
    pool = []
    for e in events:
        fd = e["filing_date"]
        day0 = day0_of(fd)
        if day0 is None:
            continue
        gi = GLOBAL_IDX[day0]
        if gi + 1 >= len(ALL_DAYS):
            continue
        buy_date = ALL_DAYS[gi + 1]
        if not (win_start <= buy_date <= win_end):
            continue
        ok, _ = screener.check(e["ticker"], day0)
        if ok and buy_date in bars[e["ticker"]]:
            pool.append({"buy_date": buy_date, "ticker": e["ticker"],
                         "excess": 0.0, "filing_date": fd})
    return pool


WINDOWS = {
    "design": (date(2019, 1, 1), date(2022, 12, 31)),
    "validation": (date(2023, 1, 1), date(2026, 11, 20)),
}
# V9 PROTECTION SPEC (ONLY change vs v4 original): plain -15% floor, NO ladder.
# Episode 1 floor = 85% of start. First halt: liquidate exactly as the original
# engine does, sit in cash 90 calendar days, restart with remaining cash at the
# strategy's next regular decision point (next scheduled PEAD signal on/after
# day 90); episode-2 floor = 85% of restart balance. Second halt ends the run.
# Placebo runs omitted per v9 execution rules (ranked pots only).
POTS = {
    50: {"floor": 42.50, "ladder": []},
    100: {"floor": 85.00, "ladder": []},
}


def main():
    print("Fetching EDGAR events...", file=sys.stderr)
    ciks = get_ciks()
    earnings, nonearn, stats = get_events(ciks)
    print(f"Earnings (Item 2.02) events: {len(earnings)}; "
          f"non-earnings 8-K events: {len(nonearn)}", file=sys.stderr)
    print("Fetching prices...", file=sys.stderr)
    bars = {t: get_bars(t) for t in SEEDS + ["SPY"]}
    empty = [t for t in SEEDS if not bars[t]]
    if empty:
        print(f"  WARNING: no price data for {empty}", file=sys.stderr)
    spy = bars["SPY"]
    global ALL_DAYS, GLOBAL_IDX
    ALL_DAYS = sorted(spy.keys())
    GLOBAL_IDX = {d: i for i, d in enumerate(ALL_DAYS)}
    spy_close = {d: spy[d]["close"] for d in ALL_DAYS}
    spy_ma = {}
    closes = [spy[d]["close"] for d in ALL_DAYS]
    for i, d in enumerate(ALL_DAYS):
        spy_ma[d] = sum(closes[i - 199:i + 1]) / 200 if i >= 199 else None
    screener = Screener(bars)

    results, all_trades, diags = {}, {}, {}
    for wname, (ws, we) in WINDOWS.items():
        cal = [d for d in ALL_DAYS if ws <= d <= we]
        results[wname] = {}
        diag = {}
        sigs = build_signals(earnings, bars, spy, screener, ws, we, diag)
        diags[wname] = diag
        print(f"{wname}: {len(sigs)} PEAD signals after screens {diag}",
              file=sys.stderr)
        for pot, cfg in POTS.items():
            bench = spy_benchmark(cal, spy, pot)
            sim = Sim(cal, bars, spy_close, spy_ma, float(pot),
                      cfg["floor"], cfg["ladder"]).run(sigs)
            results[wname][pot] = sim.summary(float(pot), bench)
            all_trades[f"{wname}_{pot}"] = sim.trades
            print(f"  ${pot}: final ${sim.cash:.2f} (SPY net ${bench}), "
                  f"{sim.entries} entries, halted={sim.halted}", file=sys.stderr)
    # universe accounting: names that produced at least one screened signal
    sig_names = {}
    all_sigs_diag = {}
    sigs_all = build_signals(earnings, bars, spy, screener,
                             date(2019, 1, 1), date(2026, 11, 20), all_sigs_diag)
    for s in sigs_all:
        sig_names[s["ticker"]] = sig_names.get(s["ticker"], 0) + 1

    out = {"universe": {"seeds": SEEDS, "edgar_stats": stats,
                        "names_with_screened_signals": sig_names,
                        "n_names_with_screened_signals": len(sig_names),
                        "full_period_diag": all_sigs_diag},
           "window_diags": diags,
           "results": results,
           "trades": {k: [{**t, "entry_date": t["entry_date"].isoformat(),
                           "exit_date": t["exit_date"].isoformat(),
                           "pnl": round(t["pnl"], 2),
                           "pnl_pct": round(t["pnl_pct"], 2),
                           "entry_price": round(t["entry_price"], 2),
                           "exit_price": round(t["exit_price"], 2)}
                          for t in v] for k, v in all_trades.items()}}
    with open(os.path.join(BASE, "pead-small-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
