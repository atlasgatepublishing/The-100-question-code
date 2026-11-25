#!/usr/bin/env python3
"""
AGGRESSIVE sprint pot - v3 one-variable-at-a-time ABLATION study.
Simulation only, no broker orders.

Base = v2 exactly as coded in ../v2/aggressive-v2.py (same engine logic,
same signal family, same exits, same costs, same floor/ladder). The only
refactor is that the knobs v2 hardcoded are now config values; with the
base config the code path is identical to v2 (drawdown ladder expressed as
fractions of base risk: 1.0 / 0.5 / 0.25 of 1% = v2's 1% / 0.5% / 0.25%).

PROTOCOL (pre-registered, Terry's "change one thing at a time" instruction):
  DESIGN window:     2016-11-21 -> 2022-12-31
  VALIDATION window: 2023-01-01 -> 2026-11-20 (run ONCE, after design picks)
  Base + 10 single-change ablations on design. The best TWO single changes
  (by design final balance, skipping mutually exclusive pairs) are combined
  and run on design. Then base, best single, and best combo each run ONCE
  on validation. Every run is a logged trial.

Ablations (each is the ONLY change from base):
  A1  ETF-only universe (SPY QQQ IWM GLD TLT XLK SMH) instead of 10 stocks
  A2  candle confirmation REMOVED (top-25% close / bullish engulfing);
      the name-above-its-50-day-average trend condition is KEPT, so A2
      isolates the candle condition itself
  A3  ATR stop multiple 1.0x (base 1.5x)
  A4  ATR stop multiple 2.0x
  A5  risk per trade 0.5% (base 1%)
  A6  risk per trade 2%
  A7  regime filter on SPY 100-day average (base 200-day)
  A8  regime filter REMOVED (drawdown ladder kept)
  A9  profit target 3x stop distance (base 2x)
  A10 max 3 positions (base 2; per-position 50%-of-pot cap unchanged)

Data: free Yahoo Finance chart API daily OHLCV, 2015-06-01 -> 2026-11-20
(10 base symbols cached from the v2 run; IWM GLD TLT XLK SMH fetched fresh).
Yahoo bars are split-adjusted, NOT dividend-adjusted. No look-ahead:
signals from the prior close, entries at the next open, indicators use
only bars up to the signal day.
"""
import csv, json, os, subprocess
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

BASE_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
ETF_UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLK", "SMH"]
ALL_SYMBOLS = sorted(set(BASE_UNIVERSE + ETF_UNIVERSE))

FETCH_START = datetime(2015, 6, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)
START_CASH = 100.0
COST_RATE = 0.001          # 0.10% per side
SELL_FEE = 0.01            # per sell order (as in v0/v2)

DESIGN = ("2016-11-21", "2022-12-31")
VALIDATION = ("2023-01-01", "2026-11-20")

BASE_CFG = {
    "universe": BASE_UNIVERSE,
    "candle": True,          # candle confirmation required (v2 confluence)
    "atr_mult": 1.5,
    "base_risk": 0.01,
    "regime_ma": 200,        # None = regime filter removed
    "target_mult": 2.0,
    "max_positions": 2,
}

ABLATIONS = [
    ("A1", "ETF-only universe", {"universe": ETF_UNIVERSE}),
    ("A2", "candle confirmation removed", {"candle": False}),
    ("A3", "ATR stop multiple 1.0x", {"atr_mult": 1.0}),
    ("A4", "ATR stop multiple 2.0x", {"atr_mult": 2.0}),
    ("A5", "risk per trade 0.5%", {"base_risk": 0.005}),
    ("A6", "risk per trade 2%", {"base_risk": 0.02}),
    ("A7", "regime filter 100-day MA", {"regime_ma": 100}),
    ("A8", "regime filter removed", {"regime_ma": None}),
    ("A9", "profit target 3x stop", {"target_mult": 3.0}),
    ("A10", "max 3 positions", {"max_positions": 3}),
]
# mutually exclusive groups (cannot combine two from the same group)
EXCLUSIVE = [{"A3", "A4"}, {"A5", "A6"}, {"A7", "A8"}]

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
    """One continuous pot run. Identical mechanics to v2's Sim; cfg-driven."""
    def __init__(self, D, cal, cfg):
        self.D = D
        self.cal = cal
        self.cfg = cfg
        self.cash = START_CASH
        self.positions = {}
        self.trades = []
        self.round_trips = []
        self.equity_curve = []
        self.floor = 85.0
        self.peak = START_CASH
        self.total_costs = 0.0
        self.halted = None
        self.prev_equity = START_CASH
        self.no_entry_today = False
        self.days_invested = 0
        self.days_cash = 0
        self.counters = {"base_signals": 0, "blocked_regime": 0,
                         "blocked_confluence": 0, "blocked_candle": 0,
                         "blocked_cost_gate": 0, "entries": 0}

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
        # v2 ladder as fractions of base risk (identical at base risk 1%)
        dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
        br = self.cfg["base_risk"]
        if dd >= 0.10:
            return 0.25 * br, 1
        if dd >= 0.05:
            return 0.5 * br, self.cfg["max_positions"]
        return br, self.cfg["max_positions"]

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
        b = self.bar(sym, date)
        if b is None:
            return False
        _, si = self.row_at(sym, self._signal_date)
        atr = self.D["atr"][sym][si] if si is not None else None
        if atr is None:
            return False
        entry = b["open"]
        atr_pct = atr / entry
        stop_pct = max(0.03, self.cfg["atr_mult"] * atr_pct)
        risk_frac, _ = self.risk_fraction()
        equity = self.prev_equity
        risk_dollars = risk_frac * equity
        value = risk_dollars / stop_pct
        value = min(value, 0.50 * equity, self.cash)
        if value < 1.0:
            return False
        shares = value / (entry * (1 + COST_RATE))
        stop = entry * (1 - stop_pct)
        target = entry * (1 + self.cfg["target_mult"] * stop_pct)
        gain_at_target = shares * (target - entry)
        rt_cost = shares * entry * COST_RATE + shares * target * COST_RATE + SELL_FEE
        if gain_at_target < 10 * rt_cost:
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

    def candidates(self, prev_date):
        """Ranked qualifying symbols from the signal evening (prev_date)."""
        D = self.D
        spi, _ = self.row_at("SPY", prev_date)
        if spi is None:
            return []
        si = D["idx"]["SPY"][prev_date]
        if self.cfg["regime_ma"] is None:
            regime_ok = True
        else:
            ma = D["ma%d" % self.cfg["regime_ma"]]["SPY"][si]
            regime_ok = ma is not None and spi["close"] > ma
        quals = []
        for s in self.cfg["universe"]:
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
            if ma50 is None or b["close"] <= ma50:
                self.counters["blocked_confluence"] += 1
                continue
            if self.cfg["candle"]:
                pb = rows[i - 1]
                rng_ = b["high"] - b["low"]
                top25 = rng_ > 0 and (b["close"] - b["low"]) >= 0.75 * rng_
                engulf = (pb["close"] < pb["open"] and b["close"] > b["open"]
                          and b["open"] <= pb["close"] and b["close"] >= pb["open"])
                if not (top25 or engulf):
                    self.counters["blocked_candle"] += 1
                    continue
            quals.append((s, gain5, vol_ratio,
                          "breakout" if breakout else "momentum"))
        quals.sort(key=lambda x: (-x[1], -x[2]))
        return quals

    def run(self):
        cal = self.cal
        spy_rows = self.D["rows"]["SPY"]
        for di, date in enumerate(cal):
            last_day = di == len(cal) - 1
            gi = self.D["idx"]["SPY"][date]
            self._signal_date = spy_rows[gi - 1]["date"] if gi > 0 else None
            _, max_pos = self.risk_fraction()
            if (self._signal_date and not self.no_entry_today
                    and len(self.positions) < max_pos):
                for s, g5, vr, kind in self.candidates(self._signal_date):
                    if self.try_enter(s, date, f"signal: {kind}"):
                        break          # max 1 new entry per day
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
                    self.sell(s, date, fill,
                              f"target +{self.cfg['target_mult']*p['stop_pct']*100:.1f}%")
                else:
                    _, ci = self.row_at(s, date)
                    pb = self.D["rows"][s][ci - 1] if ci else None
                    if pb and b["close"] < pb["low"]:
                        self.sell(s, date, b["close"], "close below prior day low")
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

    def stats(self):
        final = self.halted[2] if self.halted else self.cash
        wins = [r["pnl"] for r in self.round_trips if r["pnl"] > 0]
        losses = [r["pnl"] for r in self.round_trips if r["pnl"] <= 0]
        peak, max_dd = START_CASH, 0.0
        for _, e in self.equity_curve:
            peak = max(peak, e)
            max_dd = max(max_dd, (peak - e) / peak * 100)
        total_days = self.days_invested + self.days_cash
        return {
            "final_balance": round(final, 2),
            "return_pct": round((final / START_CASH - 1) * 100, 2),
            "halted": self.halted,
            "total_orders": len(self.trades),
            "round_trips": len(self.round_trips),
            "win_rate": round(len(wins) / len(self.round_trips) * 100, 1) if self.round_trips else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown_pct": round(max_dd, 2),
            "total_costs": round(self.total_costs, 2),
            "days_invested": self.days_invested, "days_cash": self.days_cash,
            "pct_days_invested": round(self.days_invested / total_days * 100, 1) if total_days else 0,
            "counters": self.counters,
        }

# ------------------------------------------------------------------ main ----
def load_data():
    rows = {s: bars(s) for s in ALL_SYMBOLS}
    D = {"rows": rows,
         "idx": {s: {r["date"]: i for i, r in enumerate(rows[s])} for s in ALL_SYMBOLS},
         "ma50": {}, "ma100": {}, "ma200": {}, "atr": {}}
    for s in ALL_SYMBOLS:
        closes = [r["close"] for r in rows[s]]
        D["ma50"][s] = sma(closes, 50)
        D["ma100"][s] = sma(closes, 100)
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

def year_table(sim, trades_by_year):
    """Per-calendar-year rows from a continuous run's equity curve."""
    years = {}
    for d, e in sim.equity_curve:
        years.setdefault(d[:4], []).append((d, e))
    rows_out = []
    prev_end = START_CASH
    for y in sorted(years):
        pts = sorted(years[y])
        start_bal = prev_end
        end_bal = pts[-1][1]
        peak, mdd = start_bal, 0.0
        for _, e in pts:
            peak = max(peak, e)
            mdd = max(mdd, (peak - e) / peak * 100)
        rows_out.append({"year": y, "start_balance": round(start_bal, 2),
                         "end_balance": round(end_bal, 2),
                         "return_pct": round((end_bal / start_bal - 1) * 100, 2) if start_bal else 0,
                         "orders": trades_by_year.get(y, 0),
                         "max_drawdown_pct": round(mdd, 2)})
        prev_end = end_bal
    return rows_out

def spy_year_returns(D, start, end):
    spy = D["rows"]["SPY"]
    cal = [r for r in spy if start <= r["date"] <= end]
    out = {}
    prev_close = None
    # first row: use its open as the year-start base for the first year
    for r in cal:
        y = r["date"][:4]
        if y not in out:
            out[y] = {"start_price": prev_close if prev_close is not None else r["open"]}
        out[y]["end_price"] = r["close"]
        prev_close = r["close"]
    return {y: round((v["end_price"] / v["start_price"] - 1) * 100, 2)
            for y, v in out.items()}

def describe_cfg(cfg):
    parts = []
    if cfg["universe"] is ETF_UNIVERSE or cfg["universe"] == ETF_UNIVERSE:
        parts.append("ETF universe")
    if not cfg["candle"]:
        parts.append("no candle confirmation")
    if cfg["atr_mult"] != 1.5:
        parts.append(f"ATR x{cfg['atr_mult']}")
    if cfg["base_risk"] != 0.01:
        parts.append(f"risk {cfg['base_risk']*100:g}%")
    if cfg["regime_ma"] != 200:
        parts.append("regime off" if cfg["regime_ma"] is None else f"regime MA{cfg['regime_ma']}")
    if cfg["target_mult"] != 2.0:
        parts.append(f"target {cfg['target_mult']:g}x")
    if cfg["max_positions"] != 2:
        parts.append(f"max {cfg['max_positions']} positions")
    return "; ".join(parts) if parts else "base v2"

def main():
    D = load_data()
    out = {"trials": []}
    trial_no = [0]

    def run_trial(label, cfg, window, note=""):
        trial_no[0] += 1
        cal = calendar(D, window[0], window[1])
        sim = Sim(D, cal, cfg).run()
        st = sim.stats()
        trades_by_year = {}
        for t in sim.trades:
            trades_by_year[t[0][:4]] = trades_by_year.get(t[0][:4], 0) + 1
        rec = {"trial": trial_no[0], "label": label,
               "config": describe_cfg(cfg), "window": window,
               "note": note, "stats": st,
               "years": year_table(sim, trades_by_year)}
        out["trials"].append(rec)
        print(f"trial {trial_no[0]:2d} | {label:34s} | {window[0]}..{window[1]} | "
              f"final ${st['final_balance']:7.2f} | RT {st['round_trips']:3d} | "
              f"win {st['win_rate']:4.1f}% | DD {st['max_drawdown_pct']:5.2f}% | "
              f"costs ${st['total_costs']:5.2f} | inv {st['pct_days_invested']:4.1f}%")
        return rec, sim

    calD = calendar(D, *DESIGN)
    calV = calendar(D, *VALIDATION)
    out["bench_design"] = benchmark(D, calD[0], calD[-1])
    out["bench_validation"] = benchmark(D, calV[0], calV[-1])
    out["spy_year_returns_validation"] = spy_year_returns(D, *VALIDATION)
    out["spy_year_returns_design"] = spy_year_returns(D, *DESIGN)
    print(f"SPY design net: ${out['bench_design'][1]}  validation net: ${out['bench_validation'][1]}")

    # ---- Phase 1: design window, base + ablations ----
    base_rec, _ = run_trial("BASE (v2 as coded)", dict(BASE_CFG), DESIGN)
    abl_recs = {}
    abl_cfgs = {}
    for aid, desc, override in ABLATIONS:
        cfg = dict(BASE_CFG)
        cfg.update(override)
        rec, _ = run_trial(f"{aid} {desc}", cfg, DESIGN)
        abl_recs[aid] = rec
        abl_cfgs[aid] = cfg

    # ---- Phase 2: best two compatible singles -> combo on design ----
    ranked = sorted(abl_recs.items(),
                    key=lambda kv: kv[1]["stats"]["final_balance"], reverse=True)
    picked = []
    for aid, rec in ranked:
        if any(aid in grp and any(p in grp for p in picked) for grp in EXCLUSIVE):
            continue
        picked.append(aid)
        if len(picked) == 2:
            break
    combo_cfg = dict(BASE_CFG)
    for aid in picked:
        for _, _, override in ABLATIONS:
            pass
        combo_cfg.update({k: v for k, v in abl_cfgs[aid].items()
                          if v != BASE_CFG[k] or k == "universe" and abl_cfgs[aid]["universe"] is not BASE_CFG["universe"]})
    # simpler + exact: rebuild combo from the ablation override dicts
    combo_cfg = dict(BASE_CFG)
    for aid, desc, override in ABLATIONS:
        if aid in picked:
            combo_cfg.update(override)
    combo_label = "COMBO (" + " + ".join(picked) + ")"
    combo_rec, _ = run_trial(combo_label, combo_cfg, DESIGN)
    best_single_id = ranked[0][0]
    best_single_cfg = abl_cfgs[best_single_id]
    out["design_ranking"] = [aid for aid, _ in ranked]
    out["picked_combo"] = picked
    out["best_single"] = best_single_id

    # ---- Phase 3: validation window, run ONCE each ----
    run_trial("BASE (v2 as coded)", dict(BASE_CFG), VALIDATION, note="validation")
    run_trial(f"BEST SINGLE {best_single_id}", best_single_cfg, VALIDATION, note="validation")
    val_combo_rec, val_combo_sim = run_trial(combo_label, combo_cfg, VALIDATION, note="validation")

    # ---- Phase 4: full-period picture (NOT a judge - the split above is) ----
    # One single continuous $100 run across the whole span, per-year table,
    # in the style of the v2 reports. Base first (sanity check vs v2's own
    # 10-year result of $103.80), then the best combo.
    FULL = ("2016-11-21", "2026-11-20")
    calF = calendar(D, *FULL)
    out["bench_full"] = benchmark(D, calF[0], calF[-1])
    out["spy_year_returns_full"] = spy_year_returns(D, *FULL)
    run_trial("BASE (v2 as coded)", dict(BASE_CFG), FULL,
              note="full-period continuous, picture only")
    run_trial(combo_label, combo_cfg, FULL,
              note="full-period continuous, picture only")

    out["total_trials"] = trial_no[0]
    with open(os.path.join(BASE, "aggressive-v3-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nTotal trials logged: {trial_no[0]}")
    print(json.dumps({"design_ranking": out["design_ranking"],
                      "picked_combo": picked,
                      "bench_design": out["bench_design"],
                      "bench_validation": out["bench_validation"]}, indent=1))

if __name__ == "__main__":
    main()
