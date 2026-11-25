#!/usr/bin/env python3
"""
AGGRESSIVE sprint pot - v2 backtest (simulation only, no broker orders).

v2 keeps the v0 signal family and adds:
  1. REGIME FILTER: no new buys when SPY's prior close < its 200-day MA.
  2. CONFLUENCE: name's close > its own 50-day MA, and the signal day's candle
     confirms (close in top 25% of the day's range OR bullish engulfing).
  3. ATR SIZING: stop distance = max(3% of entry, 1.5 x ATR(14) as % of entry);
     target = 2 x stop distance; position sized so loss at stop = risk% of pot,
     capped at 50% of pot per position, max 2 positions, max 1 new entry/day.
  4. COST GATE: skip unless $ gain at target >= 10x round-trip cost
     (cost = 0.10% of position value per side, + $0.01 sell fee as in v0).
  5. DRAWDOWN LADDER: pot -5%+ from peak close -> risk 0.5%; -10%+ -> 0.25%
     and max 1 position.
  6. Terry's floor/ladder unchanged: floor $85; close >= $125 -> floor $100;
     close >= $150 -> floor $125; close at/below floor -> liquidate at next
     open and the run ends.
Also carried from v0: no new entries the day after a -4% pot day.
Exits (daily bars, stop fills first if both touched): stop / target intraday;
exit at close if the name closes below the prior day's low. Entries at the
open following the signal evening. All indicators use only bars up to the
signal day - no look-ahead.

Windows:
  A: 2025-11-21 -> 2026-11-20 (same as v0 year test)
  B: 2016-11-21 -> 2026-11-20 (10 years; on a floor halt, a fresh $100 pot
     restarts the next Jan 1 so every year is covered)
  Placebo: window A, random entries (seed 20261121) at v2's trade frequency,
     same exits/sizing/costs/floor, no entry filters.

Data: free Yahoo Finance chart API daily OHLCV, fetched 2015-06-01 ->
2026-11-20. Yahoo bars are split-adjusted, NOT dividend-adjusted.
"""
import csv, json, os, random, subprocess
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
FETCH_START = datetime(2015, 6, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)
START_CASH = 100.0
COST_RATE = 0.001          # 0.10% per side
SELL_FEE = 0.01            # per sell order (as in v0)
BASE_RISK = 0.01           # 1% of pot risked per trade
PLACEBO_SEED = 20261121

# ---------------------------------------------------------------- data ----
def fetch(sym):
    path = os.path.join(DATA, f"{sym}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={int(FETCH_START.timestamp())}"
           f"&period2={int(FETCH_END.timestamp())}&interval=1d")
    out = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", url],
                         capture_output=True, text=True)
    data = json.loads(out.stdout)
    with open(path, "w") as f:
        json.dump(data, f)
    return data

def bars(sym):
    res = fetch(sym)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(res["timestamp"]):
        if q["close"][i] is None or q["open"][i] is None:
            continue
        rows.append({"date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                     "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
                     "close": q["close"][i], "volume": q["volume"][i] or 0})
    return rows

# ------------------------------------------------------------ indicators ----
def sma(values, n):
    out = [None] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out

def atr_wilder(rows, n=14):
    out = [None] * len(rows)
    trs = [0.0] * len(rows)
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    if len(rows) > n:
        a = sum(trs[1:n + 1]) / n
        out[n] = a
        for i in range(n + 1, len(rows)):
            a = (a * (n - 1) + trs[i]) / n
            out[i] = a
    return out

# ------------------------------------------------------------- engine -------
class Sim:
    """One continuous pot run over a slice of the global SPY calendar."""
    def __init__(self, D, cal, mode="v2", rng=None, entry_prob=None):
        self.D = D                  # data dict
        self.cal = cal              # list of dates for this run
        self.mode = mode            # "v2" or "placebo"
        self.rng = rng
        self.entry_prob = entry_prob
        self.cash = START_CASH
        self.positions = {}         # sym -> dict
        self.trades = []
        self.round_trips = []
        self.equity_curve = []      # (date, equity)
        self.floor = 85.0
        self.peak = START_CASH
        self.total_costs = 0.0
        self.halted = None          # (trigger_date, liquidation_date, final_balance)
        self.prev_equity = START_CASH
        self.no_entry_today = False
        self.days_invested = 0
        self.days_cash = 0
        self.counters = {"base_signals": 0, "blocked_regime": 0,
                         "blocked_confluence": 0, "blocked_cost_gate": 0,
                         "entries": 0}

    # helpers -------------------------------------------------------------
    def bar(self, s, date):
        i = self.D["idx"][s].get(date)
        return self.D["rows"][s][i] if i is not None else None

    def row_at(self, s, date):
        i = self.D["idx"][s].get(date)
        return (self.D["rows"][s][i], i) if i is not None else (None, None)

    def equity_at_close(self, date):
        eq = self.cash
        for s, p in self.positions.items():
            b = self.bar(s, date)
            if b:
                eq += p["shares"] * b["close"]
        return eq

    def risk_fraction(self):
        dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
        if dd >= 0.10:
            return 0.0025, 1
        if dd >= 0.05:
            return 0.005, 2
        return BASE_RISK, 2

    def sell(self, sym, date, price, reason):
        p = self.positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        self.total_costs += cost
        self.cash += gross - cost
        pnl = (gross - cost) - p["cost_in"]
        self.round_trips.append({"sym": sym, "pnl": pnl})
        self.trades.append([date, sym, "SELL", f"{price:.4f}", f"{p['shares']:.6f}",
                            f"{gross:.2f}", reason])

    def try_enter(self, sym, date, signal_note):
        """Size and place an entry at today's open. Returns True if filled."""
        b = self.bar(sym, date)
        if b is None:
            return False
        _, si = self.row_at(sym, self._signal_date)
        atr = self.D["atr"][sym][si] if si is not None else None
        if atr is None:
            return False
        entry = b["open"]
        atr_pct = atr / entry
        stop_pct = max(0.03, 1.5 * atr_pct)
        risk_frac, _ = self.risk_fraction()
        equity = self.prev_equity
        risk_dollars = risk_frac * equity
        value = risk_dollars / stop_pct
        value = min(value, 0.50 * equity, self.cash)
        if value < 1.0:
            return False
        shares = value / (entry * (1 + COST_RATE))
        stop = entry * (1 - stop_pct)
        target = entry * (1 + 2 * stop_pct)
        gain_at_target = shares * (target - entry)
        rt_cost = shares * entry * COST_RATE + shares * target * COST_RATE + SELL_FEE
        if self.mode == "v2" and gain_at_target < 10 * rt_cost:
            self.counters["blocked_cost_gate"] += 1
            return False
        cost_in = shares * entry * (1 + COST_RATE)
        self.total_costs += shares * entry * COST_RATE
        self.cash -= cost_in
        self.positions[sym] = {"shares": shares, "entry_price": entry,
                               "entry_date": date, "cost_in": cost_in,
                               "stop": stop, "target": target,
                               "stop_pct": stop_pct}
        self.counters["entries"] += 1
        self.trades.append([date, sym, "BUY", f"{entry:.4f}", f"{shares:.6f}",
                            f"{shares * entry:.2f}", signal_note])
        return True

    # signal logic ----------------------------------------------------------
    def v2_candidates(self, prev_date):
        """Ranked qualifying symbols from the signal evening (prev_date)."""
        D = self.D
        spi, _ = self.row_at("SPY", prev_date)
        if spi is None:
            return []
        si = D["idx"]["SPY"][prev_date]
        spy_ma200 = D["ma200"]["SPY"][si]
        regime_ok = spy_ma200 is not None and spi["close"] > spy_ma200
        quals = []
        for s in UNIVERSE:
            if s in self.positions:
                continue
            rows = D["rows"][s]
            i = D["idx"][s].get(prev_date)
            if i is None or i < 50:
                continue
            b = rows[i]
            prior10_high = max(r["high"] for r in rows[i - 10:i])
            gain5 = (b["close"] / rows[i - 5]["close"] - 1) * 100
            day_gain = (b["close"] / rows[i - 1]["close"] - 1) * 100
            vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
            vol_ratio = (b["volume"] / vol20) if vol20 else 0
            breakout = b["close"] >= prior10_high
            momentum = day_gain > 2.0 and vol_ratio > 1.5
            if not (breakout or momentum):
                continue
            self.counters["base_signals"] += 1
            if not regime_ok:
                self.counters["blocked_regime"] += 1
                continue
            ma50 = D["ma50"][s][i]
            pb = rows[i - 1]
            rng_ = b["high"] - b["low"]
            top25 = rng_ > 0 and (b["close"] - b["low"]) >= 0.75 * rng_
            engulf = (pb["close"] < pb["open"] and b["close"] > b["open"]
                      and b["open"] <= pb["close"] and b["close"] >= pb["open"])
            if ma50 is None or b["close"] <= ma50 or not (top25 or engulf):
                self.counters["blocked_confluence"] += 1
                continue
            quals.append((s, gain5, vol_ratio,
                          "breakout" if breakout else "momentum"))
        quals.sort(key=lambda x: (-x[1], -x[2]))
        return quals

    # main loop -------------------------------------------------------------
    def run(self):
        cal = self.cal
        spy_rows = self.D["rows"]["SPY"]
        for di, date in enumerate(cal):
            last_day = di == len(cal) - 1
            # signal date = previous trading day on the GLOBAL calendar
            gi = self.D["idx"]["SPY"][date]
            self._signal_date = spy_rows[gi - 1]["date"] if gi > 0 else None
            # ---- entries at open ----
            _, max_pos = self.risk_fraction()
            if (self._signal_date and not self.no_entry_today
                    and len(self.positions) < max_pos):
                if self.mode == "v2":
                    for s, g5, vr, kind in self.v2_candidates(self._signal_date):
                        if self.try_enter(s, date, f"v2 signal: {kind}"):
                            break          # max 1 new entry per day
                else:  # placebo: random entry at v2's frequency
                    if self.rng.random() < self.entry_prob:
                        free = [s for s in UNIVERSE if s not in self.positions]
                        if free:
                            self.try_enter(self.rng.choice(free), date,
                                           "placebo random entry")
            # ---- exits ----
            for s in list(self.positions.keys()):
                b = self.bar(s, date)
                if b is None:
                    continue
                p = self.positions[s]
                if b["low"] <= p["stop"]:
                    fill = b["open"] if b["open"] < p["stop"] else p["stop"]
                    self.sell(s, date, fill, f"stop -{p['stop_pct']*100:.1f}% (ATR)")
                elif b["high"] >= p["target"]:
                    fill = b["open"] if b["open"] > p["target"] else p["target"]
                    self.sell(s, date, fill, f"target +{2*p['stop_pct']*100:.1f}% (2x stop)")
                else:
                    _, ci = self.row_at(s, date)
                    pb = self.D["rows"][s][ci - 1] if ci else None
                    if pb and b["close"] < pb["low"]:
                        self.sell(s, date, b["close"], "close below prior day low")
            # ---- end of day ----
            eq = self.equity_at_close(date)
            self.equity_curve.append((date, eq))
            if self.positions:
                self.days_invested += 1
            else:
                self.days_cash += 1
            self.peak = max(self.peak, eq)
            if eq >= 150:
                self.floor = max(self.floor, 125.0)
            elif eq >= 125:
                self.floor = max(self.floor, 100.0)
            if eq <= self.floor and not last_day:
                nxt = cal[di + 1]
                for s in list(self.positions.keys()):
                    nb = self.bar(s, nxt)
                    if nb:
                        self.sell(s, nxt, nb["open"], "FLOOR breach liquidation")
                self.halted = (date, nxt, round(self.cash, 2))
                self.equity_curve.append((nxt, self.cash))
                break
            self.no_entry_today = (self.prev_equity > 0
                                   and (eq / self.prev_equity - 1) <= -0.04)
            self.prev_equity = eq
            if last_day:
                for s in list(self.positions.keys()):
                    b = self.bar(s, date)
                    if b:
                        self.sell(s, date, b["close"], "end of period liquidation")
                self.equity_curve[-1] = (date, self.cash)
        return self

    # stats -------------------------------------------------------------------
    def stats(self):
        final = self.halted[2] if self.halted else self.cash
        wins = [r["pnl"] for r in self.round_trips if r["pnl"] > 0]
        losses = [r["pnl"] for r in self.round_trips if r["pnl"] <= 0]
        peak, max_dd = START_CASH, 0.0
        for _, e in self.equity_curve:
            peak = max(peak, e)
            max_dd = max(max_dd, (peak - e) / peak * 100)
        monthly = {}
        for d, e in self.equity_curve:
            monthly[d[:7]] = e
        return {
            "final_balance": round(final, 2),
            "return_pct": round((final / START_CASH - 1) * 100, 2),
            "halted": self.halted,
            "total_orders": len(self.trades),
            "round_trips": len(self.round_trips),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(self.round_trips) * 100, 1) if self.round_trips else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "biggest_win": round(max(wins), 2) if wins else 0,
            "biggest_loss": round(min(losses), 2) if losses else 0,
            "max_drawdown_pct": round(max_dd, 2),
            "total_costs": round(self.total_costs, 2),
            "days_invested": self.days_invested, "days_cash": self.days_cash,
            "final_floor": self.floor,
            "counters": self.counters,
            "monthly": {k: round(v, 2) for k, v in monthly.items()},
        }

# ------------------------------------------------------------------ main ----
def load_data():
    rows = {s: bars(s) for s in UNIVERSE}
    D = {"rows": rows,
         "idx": {s: {r["date"]: i for i, r in enumerate(rows[s])} for s in UNIVERSE},
         "ma50": {}, "ma200": {}, "atr": {}}
    for s in UNIVERSE:
        closes = [r["close"] for r in rows[s]]
        D["ma50"][s] = sma(closes, 50)
        D["ma200"][s] = sma(closes, 200)
        D["atr"][s] = atr_wilder(rows[s], 14)
    return D

def calendar(D, start, end):
    return [r["date"] for r in D["rows"]["SPY"] if start <= r["date"] <= end]

def benchmark(D, start_date, end_date):
    spy = D["rows"]["SPY"]
    o = spy[D["idx"]["SPY"][start_date]]["open"]
    c = spy[D["idx"]["SPY"][end_date]]["close"]
    gross = START_CASH / o * c
    sh = START_CASH / (o * (1 + COST_RATE))
    net = sh * c * (1 - COST_RATE) - SELL_FEE
    return round(gross, 2), round(net, 2)

def main():
    D = load_data()
    out = {}

    # ---- Window A: v2 ----
    calA = calendar(D, "2025-11-21", "2026-11-20")
    simA = Sim(D, calA, mode="v2").run()
    stA = simA.stats()
    out["windowA_v2"] = stA
    with open(os.path.join(BASE, "aggressive-v2-trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "side", "price", "shares", "value", "reason"])
        w.writerows(simA.trades)
    out["benchA"] = benchmark(D, calA[0], calA[-1])

    # ---- Placebo on window A (same trade frequency as v2) ----
    n_days = len(calA)
    entry_prob = stA["counters"]["entries"] / n_days if n_days else 0
    rng = random.Random(PLACEBO_SEED)
    simP = Sim(D, calA, mode="placebo", rng=rng, entry_prob=entry_prob).run()
    stP = simP.stats()
    stP["entry_prob_per_day"] = round(entry_prob, 4)
    stP["seed"] = PLACEBO_SEED
    out["placeboA"] = stP
    with open(os.path.join(BASE, "aggressive-v2-placebo-trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "side", "price", "shares", "value", "reason"])
        w.writerows(simP.trades)

    # ---- Window B: 10 years with Jan-1 restarts after a halt ----
    calB = calendar(D, "2016-11-21", "2026-11-20")
    out["benchB"] = benchmark(D, calB[0], calB[-1])
    segments = []
    remaining = calB
    while remaining:
        sim = Sim(D, remaining, mode="v2").run()
        st = sim.stats()
        seg = {"start": remaining[0],
               "end": sim.equity_curve[-1][0] if sim.equity_curve else remaining[0],
               "halted": sim.halted, "stats": st,
               "equity_curve": sim.equity_curve,
               "trades_by_year": {}}
        for t in sim.trades:
            seg["trades_by_year"][t[0][:4]] = seg["trades_by_year"].get(t[0][:4], 0) + 1
        segments.append(seg)
        if not sim.halted:
            break
        halt_year = int(sim.halted[0][:4])
        nxt_jan1 = f"{halt_year + 1}-01-01"
        remaining = [d for d in calB if d >= nxt_jan1 and d > sim.halted[1]]
        if not remaining:
            break
    out["segments"] = [{k: v for k, v in s.items() if k != "equity_curve"}
                       for s in segments]

    # per-year table from segments
    years = {}
    for seg in segments:
        curve = seg["equity_curve"]
        by_year = {}
        for d, e in curve:
            by_year.setdefault(d[:4], []).append((d, e))
        for y, pts in by_year.items():
            start_bal = pts[0][1] if pts[0][0] == seg["start"] else None
            # year start balance: equity at prior segment/year end if same segment
            years.setdefault(y, {"points": [], "trades": 0})
            years[y]["points"].extend(pts)
            years[y]["trades"] += seg["trades_by_year"].get(y, 0)
            if seg["start"][:4] == y:
                years[y]["seg_start"] = seg["start"]
                years[y]["seg_start_bal"] = START_CASH
            if seg["halted"] and seg["halted"][0][:4] == y:
                years[y]["halted"] = seg["halted"]
    prev_end = None
    year_rows = []
    for y in sorted(years):
        pts = sorted(years[y]["points"])
        start_bal = years[y].get("seg_start_bal", prev_end)
        if start_bal is None:
            start_bal = pts[0][1]
        end_bal = pts[-1][1]
        peak, mdd = start_bal, 0.0
        for _, e in pts:
            peak = max(peak, e)
            mdd = max(mdd, (peak - e) / peak * 100)
        year_rows.append({"year": y, "start_balance": round(start_bal, 2),
                          "end_balance": round(end_bal, 2),
                          "return_pct": round((end_bal / start_bal - 1) * 100, 2) if start_bal else 0,
                          "orders": years[y]["trades"],
                          "max_drawdown_pct": round(mdd, 2),
                          "halted": years[y].get("halted")})
        prev_end = end_bal
    out["years"] = year_rows
    out["continuous_first_segment"] = segments[0]["stats"] if segments else None
    out["segment_count"] = len(segments)
    out["segment_pnl_sum"] = round(sum(s["stats"]["final_balance"] - START_CASH
                                       for s in out["segments"]), 2)

    with open(os.path.join(BASE, "aggressive-v2-stats.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))

if __name__ == "__main__":
    main()
