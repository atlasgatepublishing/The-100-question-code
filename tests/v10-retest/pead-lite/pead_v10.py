#!/usr/bin/env python3
"""
PEAD-LITE — THE GREAT RETEST (v10) worker script. Simulation only.

Strategy (as published, backtests/v3/pead-lite.py):
  - Universe: 20 liquid mega-caps (below).
  - Event: SEC EDGAR 8-K / 8-K/A containing Item 2.02; signal date = filing date.
  - Surprise proxy: filing-day excess return (stock close/prev close - 1, minus
    SPY same-day return) >= +5% -> buy at NEXT trading day's open.
  - Exits (published): hold 40 trading days; -8% intraday stop (stop-first);
    regime exit at next open if SPY closes below its 200-day average.
  - Sizing: max 3 concurrent, slice = cash / open slots, 63-trading-day
    per-name cooldown. Costs: 0.10%/side + $0.01 per sell order. Fractional.

This script does three things:
  1) INTEGRITY: re-runs the ORIGINAL engine logic verbatim (original
     floor+ladder protection, original windows, $100 pot) against the
     read-only v3 pead-cache and checks the published finals
     (design $127.79, validation $91.59; validation placebo seed-42 $89.10).
  2) CADENCE SWEEP on the DECADE road 2016-11-21 -> 2026-11-20, $100/cell,
     v9 protections (plain -15% floor, no ladder; first halt -> liquidate at
     next open, 90 calendar days in cash, restart at next event entry under an
     episode-2 -15% floor; second halt ends the run).
     CADENCE TREATMENT (SPEC uniform definition, event strategies):
       * The earnings-jump EVENT rule is exactly as published; entries occur
         on events (buy at next trading day's open after a qualifying filing),
         on any trading day, regardless of cadence.
       * Cadence governs ONLY the position review / exit-check rhythm:
         the -8% stop check, the 40-trading-day hold-end exit, the SPY
         200-DMA regime exit, and the v9 floor check are evaluated ONLY on
         cadence dates. Stop fills use the cadence date's own bar (low vs
         stop; fill at stop price, or at the open if the open is below the
         stop — the original fill rule). Hold-end exits execute at the
         cadence date's close once >=40 trading days have elapsed. Regime
         exits (SPY close < MA200 at a cadence review) and floor halts
         execute at the next trading day's open, mirroring the original
         flag-at-close / exit-at-open mechanics.
       * Cadence dates: daily = every trading day; weekly = first trading
         day of each ISO week; biweekly = first trading day of every second
         ISO week (anchored on the first week of the window); monthly =
         first trading day of each month; quarterly = first trading day of
         each calendar quarter; semiannual = first trading day of each
         half-year; annual = first trading day of each year.
     DATA LIMIT: the shared pead cache holds prices from 2018-01-02 and
     EDGAR events from Dec 2018, so on the decade road the pot sits in cash
     from 2016-11-21 until the first possible signal (Dec 2018). The road
     and the $100 start are unchanged; this is documented, not patched.
  3) PLACEBOS per cell: the original's shifted-event design — entries on
     RANDOM 8-K filing dates (any item) of the same companies, pool sampled
     exactly as the original (sample of max(6x target, target), sorted by
     buy date, entries capped at the real run's entry count), identical
     exits/sizing/protection — extended to 20 seeds (42..61; seed 42 is the
     original's own seed). Placebos run on the DECADE road per cell.

Outputs: cells/<cadence>.json (full equity curve, event stats, all 20
placebo finals), integrity.json, results.json. Data is read-only from
~/workspace/stock-app/backtests/v3/pead-cache/ — nothing is written there.
"""
import json, os, random, sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/pead-cache")

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
COOLDOWN = 63
EXCESS_MIN = 0.05

DECADE = (date(2016, 11, 21), date(2026, 11, 20))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = [42 + i for i in range(20)]


# ---------------------------------------------------------------- data
def load_events():
    with open(os.path.join(CACHE, "events.json")) as f:
        raw = json.load(f)
    conv = lambda rows: [{"ticker": r["ticker"],
                          "filing_date": date.fromisoformat(r["filing_date"]),
                          "items": r["items"], "form": r["form"]} for r in rows]
    return conv(raw["earnings"]), conv(raw["all8k"])


def load_bars(ticker):
    """Replicates the original get_bars() parsing of the cached Yahoo JSON."""
    with open(os.path.join(CACHE, f"px_{ticker}.json"), "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
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


# ---------------------------------------------------------------- signals
def build_signals(events, bars, spy_bars, win_start, win_end):
    """Verbatim from the original: filing-day excess >= +5% -> buy next open."""
    sigs = []
    for e in events:
        fd = e["filing_date"]
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
    """Verbatim from the original: any-item 8-K events with in-window buy dates."""
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


def spy_benchmark(cal, spy_bars, start_cash):
    first, last = cal[0], cal[-1]
    buy_px = spy_bars[first]["open"]
    shares = start_cash / (buy_px * (1 + BUY_COST))
    proceeds = shares * spy_bars[last]["close"]
    return round(proceeds - (proceeds * SELL_COST + SELL_FEE), 2)


# ------------------------------------------------- original engine (integrity)
class OrigSim:
    """Byte-for-byte logic port of backtests/v3/pead-lite.py's Sim class."""

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
                self.halted = True
                self.halt_date = d
                break
            if self.pending_regime_exit:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "regime", d)
                self.pending_regime_exit = False
            for pos in list(self.positions):
                bar = self.bars[pos["ticker"]][d]
                if bar["low"] <= pos["stop_price"]:
                    px = bar["open"] if bar["open"] < pos["stop_price"] else pos["stop_price"]
                    self.sell(pos, px, "stop", d)
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


# ------------------------------------------------------- cadence sweep engine
def cadence_dates(cal, cadence):
    """Cadence review dates within the window calendar (list of dates)."""
    if cadence == "daily":
        return set(cal)
    out = set()
    seen = set()
    for d in cal:
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
        elif cadence == "biweekly":
            iso = d.isocalendar()
            # anchor: week index counted from the first week in the window
            key = None  # handled below
        elif cadence == "monthly":
            key = (d.year, d.month)
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
        elif cadence == "annual":
            key = (d.year,)
        if cadence == "biweekly":
            continue
        if key not in seen:
            seen.add(key)
            out.add(d)
    if cadence == "biweekly":
        weeks = []
        seenw = set()
        for d in cal:
            k = (d.isocalendar()[0], d.isocalendar()[1])
            if k not in seenw:
                seenw.add(k)
                weeks.append(d)
        out = set(weeks[::2])
    return out


class SweepSim:
    """PEAD-lite under the v10 cadence sweep + v9 protections.

    Entries: on event buy dates (any trading day), exactly as published.
    Reviews (stop / hold-end / regime / floor): cadence dates only.
    v9 protection: plain -15% floor from the episode start balance; first
    halt -> liquidate at next open, 90 calendar days cash, restart at the
    next event entry on/after the wait under an episode-2 floor; second
    halt ends the run (liquidate, stay in cash).
    """

    def __init__(self, calendar, bars, spy_close, spy_ma200, start_cash,
                 review_dates, max_entries=None):
        self.cal = calendar
        self.bars = bars
        self.spy_close = spy_close
        self.spy_ma = spy_ma200
        self.cash = float(start_cash)
        self.start_cash = float(start_cash)
        self.review = review_dates
        self.max_entries = max_entries
        self.positions = []
        self.trades = []
        self.total_costs = 0.0
        self.entries = 0
        self.orders = 0
        self.last_entry_idx = {}
        self.pending_liquidation = False
        self.pending_regime_exit = False
        # v9 episode state
        self.episode = 1
        self.episode_start_balance = float(start_cash)
        self.floor = 0.85 * float(start_cash)
        self.halts = []            # [{halt_flag_date, liquidation_date, episode}]
        self.ended = False         # second halt: run over
        self.cash_until = None     # date before which no new entries
        self.equity = []           # [[date, value], ...]

    def sell(self, pos, price, reason, d):
        proceeds = pos["shares"] * price
        cost = proceeds * SELL_COST + SELL_FEE
        self.cash += proceeds - cost
        self.total_costs += cost
        self.orders += 1
        pnl = (proceeds - cost) - pos["cost_basis"]
        self.trades.append({"ticker": pos["ticker"],
                            "entry_date": pos["entry_date"].isoformat(),
                            "exit_date": d.isoformat(),
                            "entry_price": round(pos["entry_price"], 4),
                            "exit_price": round(price, 4),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl / pos["cost_basis"] * 100, 2),
                            "reason": reason})
        self.positions.remove(pos)

    def value(self, d):
        return self.cash + sum(p["shares"] * self.bars[p["ticker"]][d]["close"]
                               for p in self.positions)

    def run(self, signals):
        sig_by_day = {}
        for s in signals:
            sig_by_day.setdefault(s["buy_date"], []).append(s)
        for d in self.cal:
            gi = GLOBAL_IDX[d]
            # 1) pending floor liquidation at open (flag set at a prior review)
            if self.pending_liquidation:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "floor", d)
                self.pending_liquidation = False
                self.halts[-1]["liquidation_date"] = d.isoformat()
                if self.episode == 1:
                    self.episode = 2
                    self.episode_start_balance = self.cash
                    self.floor = 0.85 * self.cash
                    self.cash_until = d + timedelta(days=90)
                else:
                    self.ended = True
            # 2) pending regime exit at open (flag set at a prior review close)
            if self.pending_regime_exit and not self.ended:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "regime", d)
                self.pending_regime_exit = False
            is_review = d in self.review
            # 3) stop checks — cadence dates only, cadence day's own bar
            if is_review:
                for pos in list(self.positions):
                    bar = self.bars[pos["ticker"]][d]
                    if bar["low"] <= pos["stop_price"]:
                        px = bar["open"] if bar["open"] < pos["stop_price"] else pos["stop_price"]
                        self.sell(pos, px, "stop", d)
            # 4) entries — on events, any trading day (unless halted/sitting out)
            if not self.ended and not self.pending_liquidation:
                if self.cash_until is None or d >= self.cash_until:
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
                        self.orders += 1
                        self.positions.append({
                            "ticker": t, "shares": shares, "entry_price": px,
                            "entry_date": d, "entry_gidx": gi,
                            "cost_basis": spend, "stop_price": px * (1 - STOP_PCT)})
                        self.entries += 1
                        self.last_entry_idx[t] = gi
            # 5) reviews at close: hold-end, regime flag, floor flag
            if is_review:
                for pos in list(self.positions):
                    if gi - pos["entry_gidx"] >= HOLD_DAYS - 1:
                        self.sell(pos, self.bars[pos["ticker"]][d]["close"], "hold_end", d)
                ma = self.spy_ma.get(d)
                if self.positions and ma is not None and self.spy_close[d] < ma:
                    self.pending_regime_exit = True
                if not self.ended and self.value(d) <= self.floor:
                    self.halts.append({"halt_flag_date": d.isoformat(),
                                       "liquidation_date": None,
                                       "episode": self.episode,
                                       "floor": round(self.floor, 2)})
                    self.pending_liquidation = True
            self.equity.append([d.isoformat(), round(self.value(d), 2)])
        # window end: liquidate anything left at final close
        if self.positions:
            d = self.cal[-1]
            for pos in list(self.positions):
                self.sell(pos, self.bars[pos["ticker"]][d]["close"], "window_end", d)
            self.equity[-1][1] = round(self.cash, 2)
        return self


def stats(sim, start, end):
    eq = [v for _, v in sim.equity]
    peak, max_dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    days = (end - start).days
    cagr = (sim.cash / sim.start_cash) ** (365.25 / days) - 1 if days > 0 else 0.0
    return {"final": round(sim.cash, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(sim.total_costs, 2), "orders": sim.orders,
            "entries": sim.entries}


def per_event_excess(sim, spy_bars):
    """Mean/median net excess vs SPY per traded event: trade pnl_pct (net of
    costs) minus SPY's price return over the same entry->exit dates."""
    exc = []
    for t in sim.trades:
        ed, xd = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
        if ed in spy_bars and xd in spy_bars:
            spy_r = spy_bars[xd]["close"] / spy_bars[ed]["close"] - 1
            exc.append(t["pnl_pct"] / 100 - spy_r)
    if not exc:
        return {"n": 0, "mean_net_excess_pct": None, "median_net_excess_pct": None}
    exc_s = sorted(exc)
    med = exc_s[len(exc_s) // 2] if len(exc_s) % 2 else (exc_s[len(exc_s) // 2 - 1] + exc_s[len(exc_s) // 2]) / 2
    return {"n": len(exc), "mean_net_excess_pct": round(sum(exc) / len(exc) * 100, 2),
            "median_net_excess_pct": round(med * 100, 2)}


# ---------------------------------------------------------------- main
def main():
    global ALL_DAYS, GLOBAL_IDX
    earnings, all8k = load_events()
    bars = {t: load_bars(t) for t in PRICE_TICKERS}
    spy = bars["SPY"]
    ALL_DAYS = sorted(spy.keys())
    GLOBAL_IDX = {d: i for i, d in enumerate(ALL_DAYS)}
    spy_close = {d: spy[d]["close"] for d in ALL_DAYS}
    closes = [spy[d]["close"] for d in ALL_DAYS]
    spy_ma = {}
    for i, d in enumerate(ALL_DAYS):
        spy_ma[d] = sum(closes[i - 199:i + 1]) / 200 if i >= 199 else None

    # ---------------- INTEGRITY: original form, original windows, $100 pot
    integ = {}
    orig_windows = {"design": (date(2019, 1, 1), date(2022, 12, 31)),
                    "validation": (date(2023, 1, 1), date(2026, 11, 20))}
    published = {"design": 127.79, "validation": 91.59}
    for wname, (ws, we) in orig_windows.items():
        cal = [d for d in ALL_DAYS if ws <= d <= we]
        sigs = build_signals(earnings, bars, spy, ws, we)
        sim = OrigSim(cal, bars, spy_close, spy_ma, 100.0, 85.00,
                      [(125.00, 100.00), (150.00, 125.00)]).run(sigs)
        integ[wname] = {"final": round(sim.cash, 2), "published": published[wname],
                        "entries": sim.entries, "costs": round(sim.total_costs, 2),
                        "halted": sim.halted,
                        "match": round(sim.cash, 2) == published[wname]}
        print(f"integrity {wname}: reproduced ${sim.cash:.2f} vs published "
              f"${published[wname]} -> {'MATCH' if integ[wname]['match'] else 'MISMATCH'}",
              file=sys.stderr)
    # original placebo (validation, seed 42, $100) as a second integrity check
    ws, we = orig_windows["validation"]
    cal = [d for d in ALL_DAYS if ws <= d <= we]
    pool = build_placebo_pool(all8k, bars, ws, we)
    rng = random.Random(42)
    sampled = rng.sample(pool, min(len(pool), max(14 * 6, 14)))
    sampled.sort(key=lambda s: s["buy_date"])
    psim = OrigSim(cal, bars, spy_close, spy_ma, 100.0, 85.00,
                   [(125.00, 100.00), (150.00, 125.00)],
                   max_entries=14).run(sampled)
    integ["validation_placebo_seed42"] = {"final": round(psim.cash, 2),
                                          "published": 89.10,
                                          "match": round(psim.cash, 2) == 89.10}
    print(f"integrity placebo42: ${psim.cash:.2f} vs published $89.10", file=sys.stderr)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integ, f, indent=1)

    # ---------------- CADENCE SWEEP on the DECADE road
    ws, we = DECADE
    cal = [d for d in ALL_DAYS if ws <= d <= we]
    sigs = build_signals(earnings, bars, spy, ws, we)
    pool = build_placebo_pool(all8k, bars, ws, we)
    print(f"decade: {len(cal)} trading days in data ({cal[0]}..{cal[-1]}), "
          f"{len(sigs)} PEAD signals, placebo pool {len(pool)}", file=sys.stderr)

    cells = {}
    for cad in CADENCES:
        rev = cadence_dates(cal, cad)
        sim = SweepSim(cal, bars, spy_close, spy_ma, 100.0, rev).run(sigs)
        st = stats(sim, ws, we)
        ev = per_event_excess(sim, spy)
        # placebos: original shifted-event design, 20 seeds
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            r = random.Random(seed)
            samp = r.sample(pool, min(len(pool), max(sim.entries * 6, sim.entries)))
            samp.sort(key=lambda s: s["buy_date"])
            ps = SweepSim(cal, bars, spy_close, spy_ma, 100.0, rev,
                          max_entries=sim.entries).run(samp)
            placebo_finals.append(round(ps.cash, 2))
        beaten = sum(1 for pf in placebo_finals if st["final"] > pf)
        cell = {
            "cadence": cad, "window": [ws.isoformat(), we.isoformat()],
            "data_note": "Prices in the shared pead cache begin 2018-01-02 and EDGAR events Dec 2018; pot sat in cash 2016-11-21 until the first possible signal. Road/start unchanged.",
            **st,
            "halts": len(sim.halts), "restart": len(sim.halts) >= 1 and sim.episode == 2 and not sim.ended,
            "second_halt": sim.ended,
            "halt_records": sim.halts,
            "events_signaled": len(sigs), "events_traded": sim.entries,
            "per_event": ev,
            "exit_reasons": {r: sum(1 for t in sim.trades if t["reason"] == r)
                             for r in ("stop", "hold_end", "regime", "floor", "window_end")},
            "placebo_beaten": beaten, "placebo_seeds": PLACEBO_SEEDS,
            "placebo_finals": placebo_finals,
            "placebo_note": "Original shifted-event design (random any-item 8-K entry dates, same exits/sizing/protection, entries capped at the real run's count), 20 seeds 42..61 on the DECADE road at this cadence.",
            "trades": sim.trades,
            "equity_curve": sim.equity,
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                           "halts", "restart", "second_halt",
                                           "costs", "orders")}
        cells[cad]["placebo_beaten"] = beaten
        cells[cad]["placebo_note"] = cell["placebo_note"]
        cells[cad]["events_traded"] = sim.entries
        cells[cad]["per_event_mean_net_excess_pct"] = ev["mean_net_excess_pct"]
        cells[cad]["per_event_median_net_excess_pct"] = ev["median_net_excess_pct"]
        print(f"{cad}: final ${st['final']} entries={sim.entries} "
              f"mean_excess={ev['mean_net_excess_pct']} placebo beaten {beaten}/20",
              file=sys.stderr)

    spy_decade = 367.80  # SPEC/task reference: dividend-adjusted program convention
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_decade and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "pead-lite",
        "area": "Earnings-event drift (event-to-event, ~40-day holds) on mega-caps — W9 event treatment on the DECADE road",
        "area_source": "SPEC W9: 'PEAD-lite/small = earnings-event drift: event treatment (per-event + cycled)'; CADENCE SWEEP: DECADE road, 7 cadences",
        "cadence": "event-driven",
        "native_cadence": "event-driven",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original test was event-driven with daily exit checks — its native form. The sweep's daily cell is the closest to the original rhythm; slower cadences only delay exit reviews.",
        "integrity": {
            "status": "reproduced" if all(integ[w]["match"] for w in ("design", "validation")) else "FAILED",
            "original_finals": {"design_100": 127.79, "validation_100": 91.59,
                                "validation_placebo_seed42_100": 89.10},
            "reproduced_finals": {"design_100": integ["design"]["final"],
                                  "validation_100": integ["validation"]["final"],
                                  "validation_placebo_seed42_100": integ["validation_placebo_seed42"]["final"]},
            "note": "Original engine logic ported verbatim into this script (OrigSim), original floor+ladder protection, original windows, read-only v3 pead-cache. v9 folder recorded the strategy 'identical — not re-run' (floor never fired); this run actually re-executes it.",
        },
        "decade_spy_final": spy_decade,
        "decade_spy_note": "Dividend-adjusted program convention per SPEC (price-only SPY in the pead cache would read lower; the original study's SPY was also price-only Yahoo bars).",
        "champion_decade_final": 65.89,
        "champion_decade_caveat": "Champion decade $65.89 after two halts (lazy-quarterly test) — its crown rests on the 2010 and 2019 roads, per SPEC.",
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": "No change in substance: FAILED in the original program (design +27.8% but trailed SPY; validation -8.4% vs SPY +79.1%, placebo-tied). The sweep re-tests it on the decade road at every exit-review tempo; see RESULTS.md.",
        "data_sources": "Read-only shared cache: backtests/v3/pead-cache/ (EDGAR events.json + Yahoo px_*.json for the 20 names + SPY). No new downloads; nothing written outside this folder.",
        "cadence_treatment": "Event rule exactly as published; entries occur on events (next-open after qualifying filing) on any trading day. Cadence governs only the position review/exit-check rhythm: -8% stop, 40-trading-day hold-end, SPY-200DMA regime exit and the v9 floor are evaluated only on cadence dates (stop fills on the cadence day's bar; hold-end at cadence-date close; regime/floor execute at next open).",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
