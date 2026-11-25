#!/usr/bin/env python3
"""
V13 BEST-RULES - aggressive-v3. Simulation only, no broker orders.
Rules frozen in BEST-RULES-SPEC.md before this run:
 20-day breakout only (spike signal deleted), volume >1.2x 20d mean,
 SPY>200d regime, name>50d, candle confirmation, rank by 63-day gain,
 1 entry/day, max 3 positions, risk 1%, stop = max(3%, 2.0xATR),
 NO fixed target, NO prior-day-low exit; exits = hard stop intraday or
 close below prior-10-day low. NO pot floor, no ladder, no risk ladder.
Costs 0.10%/side + $0.01 sell fee. Data: v12 data_long cache (read-only).
Placebos: family design - entry_prob = entries/days, random free name,
 identical sizing/exits/costs, 20 seeds.
"""
import json, os, random
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LONGDATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/aggressive-v3/data_long")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
RISK = 0.01
ATR_MULT = 2.0
MAX_POS = 3
CAP_FRAC = 0.40

def load_data():
    rows = {}
    for s in UNIVERSE:
        d = json.load(open(os.path.join(LONGDATA, f"{s}.json")))
        res = d["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        rr = []
        for i, t in enumerate(res["timestamp"]):
            if q["close"][i] is None or q["open"][i] is None:
                continue
            rr.append({"date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                       "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
                       "close": q["close"][i], "volume": q["volume"][i] or 0})
        rows[s] = rr
    D = {"rows": rows,
         "idx": {s: {r["date"]: i for i, r in enumerate(rows[s])} for s in UNIVERSE},
         "ma50": {}, "ma200": {}, "atr": {}}
    for s in UNIVERSE:
        closes = [r["close"] for r in rows[s]]
        D["ma50"][s] = sma(closes, 50)
        D["ma200"][s] = sma(closes, 200)
        D["atr"][s] = atr_wilder(rows[s], 14)
    return D

def sma(values, n):
    out = [None] * len(values); run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n: run -= values[i - n]
        if i >= n - 1: out[i] = run / n
    return out

def atr_wilder(rows, n=14):
    out = [None] * len(rows); trs = [0.0] * len(rows)
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    if len(rows) > n:
        a = sum(trs[1:n + 1]) / n; out[n] = a
        for i in range(n + 1, len(rows)):
            a = (a * (n - 1) + trs[i]) / n; out[i] = a
    return out

class Sim:
    def __init__(self, D, cal, placebo_rng=None, entry_prob=0.0):
        self.D, self.cal = D, cal
        self.cash = START_CASH
        self.positions = {}
        self.round_trips = []
        self.equity_curve = []
        self.total_costs = 0.0
        self.prev_equity = START_CASH
        self.orders = 0
        self.entries = 0
        self.days_invested = 0
        self.placebo_rng = placebo_rng
        self.entry_prob = entry_prob
        self._signal_date = None

    def bar(self, s, date):
        i = self.D["idx"][s].get(date)
        return self.D["rows"][s][i] if i is not None else None

    def equity_at_close(self, date):
        eq = self.cash
        for s, p in self.positions.items():
            b = self.bar(s, date)
            if b: eq += p["shares"] * b["close"]
        return eq

    def sell(self, sym, date, price, reason):
        p = self.positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        self.total_costs += cost
        self.cash += gross - cost
        self.orders += 1
        self.round_trips.append({"sym": sym, "pnl": (gross - cost) - p["cost_in"],
                                  "entry_date": p["entry_date"], "exit_date": date,
                                  "reason": reason})

    def try_enter(self, sym, date):
        b = self.bar(sym, date)
        if b is None: return False
        si = self.D["idx"][sym].get(self._signal_date)
        if si is None: return False
        atr = self.D["atr"][sym][si]
        if atr is None: return False
        entry = b["open"]
        stop_pct = max(0.03, ATR_MULT * atr / entry)
        value = (RISK * self.prev_equity) / stop_pct
        value = min(value, CAP_FRAC * self.prev_equity, self.cash)
        if value < 1.0: return False
        shares = value / (entry * (1 + COST_RATE))
        cost_in = shares * entry * (1 + COST_RATE)
        self.total_costs += shares * entry * COST_RATE
        self.cash -= cost_in
        self.orders += 1; self.entries += 1
        self.positions[sym] = {"shares": shares, "entry_price": entry,
                               "entry_date": date, "cost_in": cost_in,
                               "stop": entry * (1 - stop_pct), "stop_pct": stop_pct}
        return True

    def candidates(self, prev_date):
        D = self.D
        si = D["idx"]["SPY"].get(prev_date)
        if si is None: return []
        ma200 = D["ma200"]["SPY"][si]
        if ma200 is None or D["rows"]["SPY"][si]["close"] <= ma200: return []
        quals = []
        for s in UNIVERSE:
            if s in self.positions: continue
            rows = D["rows"][s]; i = D["idx"][s].get(prev_date)
            if i is None or i < 63: continue
            b = rows[i]
            if b["close"] < max(r["high"] for r in rows[i - 20:i]): continue
            vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
            if not vol20 or b["volume"] / vol20 <= 1.2: continue
            ma50 = D["ma50"][s][i]
            if ma50 is None or b["close"] <= ma50: continue
            pb = rows[i - 1]; rng_ = b["high"] - b["low"]
            top25 = rng_ > 0 and (b["close"] - b["low"]) >= 0.75 * rng_
            engulf = (pb["close"] < pb["open"] and b["close"] > b["open"]
                      and b["open"] <= pb["close"] and b["close"] >= pb["open"])
            if not (top25 or engulf): continue
            gain63 = b["close"] / rows[i - 63]["close"] - 1
            quals.append((s, gain63))
        quals.sort(key=lambda x: -x[1])
        return [s for s, _ in quals]

    def run(self):
        cal = self.cal
        spy_rows = self.D["rows"]["SPY"]
        for di, date in enumerate(cal):
            last_day = di == len(cal) - 1
            gi = self.D["idx"]["SPY"][date]
            self._signal_date = spy_rows[gi - 1]["date"] if gi > 0 else None
            if self._signal_date and len(self.positions) < MAX_POS:
                if self.placebo_rng is not None:
                    if self.placebo_rng.random() < self.entry_prob:
                        free = [s for s in UNIVERSE if s not in self.positions]
                        if free:
                            self.try_enter(self.placebo_rng.choice(free), date)
                else:
                    for s in self.candidates(self._signal_date):
                        if self.try_enter(s, date): break
            for s in list(self.positions.keys()):
                b = self.bar(s, date)
                if b is None: continue
                p = self.positions[s]
                ci = self.D["idx"][s][date]
                if b["low"] <= p["stop"]:
                    fill = b["open"] if b["open"] < p["stop"] else p["stop"]
                    self.sell(s, date, fill, "hard stop (2.0xATR)")
                elif ci >= 10 and b["close"] < min(r["low"] for r in self.D["rows"][s][ci - 10:ci]):
                    self.sell(s, date, b["close"], "close below prior 10-day low")
            eq = self.equity_at_close(date)
            self.equity_curve.append((date, eq))
            if self.positions: self.days_invested += 1
            self.prev_equity = eq
            if last_day:
                for s in list(self.positions.keys()):
                    b = self.bar(s, date)
                    if b: self.sell(s, date, b["close"], "end of period liquidation")
                self.equity_curve[-1] = (date, self.cash)
        return self

    def stats(self):
        final = self.cash
        wins = [r["pnl"] for r in self.round_trips if r["pnl"] > 0]
        peak, max_dd = START_CASH, 0.0
        for _, e in self.equity_curve:
            peak = max(peak, e); max_dd = max(max_dd, (peak - e) / peak * 100)
        return {"final": round(final, 2),
                "return_pct": round((final / START_CASH - 1) * 100, 2),
                "max_dd_pct": round(max_dd, 2),
                "costs": round(self.total_costs, 2),
                "orders": self.orders, "entries": self.entries,
                "round_trips": len(self.round_trips),
                "win_rate_pct": round(len(wins) / len(self.round_trips) * 100, 1) if self.round_trips else 0,
                "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(r["pnl"] for r in self.round_trips if r["pnl"] <= 0) / max(1, len(self.round_trips) - len(wins)), 2),
                "pct_days_invested": round(self.days_invested / len(self.cal) * 100, 1)}

def monthly_distribution(curve):
    months = {}
    for d, e in curve: months.setdefault(d[:7], []).append(e)
    keys = sorted(months); rets = []; prev = START_CASH
    for k in keys:
        end = months[k][-1]
        rets.append((end / prev - 1) * 100 if prev else 0.0); prev = end
    pos = sum(1 for r in rets if r > 0)
    srt = sorted(rets); n = len(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak, peak_date, longest_under = START_CASH, curve[0][0], 0
    last_high_idx = 0
    for i, (d, e) in enumerate(curve):
        if e >= peak: peak, last_high_idx = e, i
        longest_under = max(longest_under, i - last_high_idx)
    return {"period": "month", "n_periods": n,
            "median_period_pct": round(median, 2),
            "share_positive_pct": round(pos / n * 100, 1) if n else 0,
            "best_period_pct": round(max(rets), 2) if rets else 0,
            "worst_period_pct": round(min(rets), 2) if rets else 0,
            "longest_losing_streak_periods": longest_loss,
            "longest_stretch_between_new_highs_days": longest_under,
            "mean_period_pct_secondary": round(sum(rets) / n, 2) if n else 0}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20"),
         "CONF_A": ("2017-01-03", "2020-12-31"), "CONF_B": ("2021-01-04", "2024-12-31")}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 90.92, "DECADE": 118.56, "CONT": 87.36, "VAL": 88.51}

def main():
    D = load_data()
    out = {"family": "aggressive-v3", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen pre-run)",
           "costs": "0.10%/side + $0.01 sell fee", "roads": {}}
    for rname, (start, end) in ROADS.items():
        cal = [r["date"] for r in D["rows"]["SPY"] if start <= r["date"] <= end]
        sim = Sim(D, cal).run(); st = sim.stats()
        entry_prob = min(1.0, st["entries"] / max(1, len(cal)))
        twins = []
        for seed in range(1, 21):
            twin = Sim(D, cal, placebo_rng=random.Random(seed), entry_prob=entry_prob).run()
            twins.append(round(twin.cash, 2))
        beaten = sum(1 for t in twins if st["final"] > t)
        out["roads"][rname] = {"window": [start, end], "n_days": len(cal),
            **st, "placebo": {"entry_prob": round(entry_prob, 4),
                              "twin_finals": twins, "seeds_beaten": beaten},
            "monthly_distribution": monthly_distribution(sim.equity_curve),
            "spy_ref": SPY_REF.get(rname), "champion_vm": CHAMP.get(rname),
            "published_best_combo": PUBLISHED.get(rname),
            "equity_curve": [[d, round(e, 2)] for d, e in sim.equity_curve]}
        print(f"{rname:7s} final ${st['final']:8.2f} DD {st['max_dd_pct']:6.2f}% "
              f"costs ${st['costs']:6.2f} RT {st['round_trips']:4d} win {st['win_rate_pct']}% "
              f"placebo {beaten}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json")

if __name__ == "__main__":
    main()
