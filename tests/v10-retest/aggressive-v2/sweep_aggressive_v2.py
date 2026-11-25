#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — aggressive-v2 CADENCE SWEEP.
Simulation only, no broker orders.

Strategy: aggressive-v2 — Terry's fast style in its v2 form (the direct
ancestor of aggressive-v3, before the v3 guardrails/ablations). The v2
engine exactly as published in backtests/v2/aggressive-v2.py: breakout /
momentum signals on SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO, SPY
200-day regime filter, close-above-50-day-MA + candle confluence, ATR
sizing (stop = max(3%, 1.5 x ATR(14)%), target = 2 x stop distance, risk
1% of pot, cap 50% of pot, max 2 positions, max 1 entry/day), cost gate
(skip unless gain at target >= 10x round-trip cost), drawdown
risk-sizing ladder (pot -5% from peak -> risk 0.5%; -10% -> 0.25% and
max 1 position), no entries the day after a -4% pot day. Program costs:
0.10%/side + $0.01 sell fee (the engine's own cost code, unchanged).

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100/pot.

CADENCE (SPEC uniform definition): signal evaluation, selection and
trading happen ONLY on cadence dates — daily = every trading day;
weekly = first trading day of each week; biweekly = first trading day
of every second week (anchored on the window's first week); monthly =
first trading day of each month; quarterly = first trading day of each
calendar quarter; semi-annual = first trading day of each half-year;
annual = first trading day of each year. This is a DAILY-SIGNAL
chassis, so the treatment is: on a cadence date, entries use the
previous trading day's signal evening exactly as the daily engine does
(entry at the cadence date's open), and the engine's definitional exits
(ATR stop, 2x-stop-distance target, close-below-prior-day-low) are
evaluated ONLY on cadence dates, using that date's bar exactly as the
daily engine evaluates one day. On non-cadence days nothing is
evaluated and positions simply ride (equity is still marked to market
daily for the curve / drawdown / floor). The day-after-a->4%-down-day
entry pause and the drawdown risk-sizing ladder are engine state,
updated daily as in the original; they only bite on cadence dates,
when entries can occur.

PROTECTION: adopted v9 rules — plain -15% floor from the episode's
starting balance, NO profit ladder (the original $125/$150 ladder is
removed — the stated substitution). The floor is checked on every
day's close (as the original checked its floor daily — protection is
not a trading decision). On a breach: liquidate all positions at the
next trading day's open (the original engine's liquidation mechanics),
sit in cash 90 calendar days, restart at the next cadence date
on/after breach+90d under an episode-2 floor of -15% from the restart
balance; a second breach liquidates the same way and ends the run
(cash to window end).

PLACEBOS (v2's own design, from aggressive-v2.py): v2's placebo mode
entered a RANDOM free symbol from the universe at v2's trade frequency
(entry_prob = entries / days), with identical sizing and exits and —
as coded in v2 — WITHOUT the entry filters and WITHOUT the cost gate
(the gate check is mode=="v2" only in the original code; the v2 report
notes the gate never bound for real entries either). Here, per cell:
entry_prob = the real run's entries / the number of cadence dates
(capped at 1.0); on each cadence date the twin draws
rng.random() < entry_prob and, if so, tries to enter a uniformly
random free symbol through the identical try_enter path; exits and v9
protection are the identical cadence machinery. 20 seeds (1..20) per
cell. (v2's original placebo was a single seed, 20261121, on its
Window A: placebo $94.82 vs strategy $96.56 — folded in as history;
the integrity re-run in this folder reproduced both to the cent.)

DATA: read-only from the v2 cache (backtests/v2/data — Yahoo daily
OHLCV JSON, split-adjusted, not dividend-adjusted — the original
engine's own data; symlinked as ./data by the integrity run and read
here via the original module). SPY decade benchmark: the v2 era used
price-only bars, so BOTH benchmarks are printed, labeled: price-only
$314.10 net (the original engine's own benchmark function, reproduced
in the integrity run) and dividend-adjusted $367.80 computed from the
read-only v7 long-hold cache (buy at 2016-11-21 open scaled by
adjclose/close, sell at 2026-11-20 adjclose, program costs), matching
the SPEC reference.
"""
import json, os, random, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import original_aggressive_v2 as m   # byte-identical copy of the v2 engine

m.DATA = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
UNIVERSE = m.UNIVERSE
COST_RATE, SELL_FEE, START = m.COST_RATE, m.SELL_FEE, m.START_CASH
BASE_RISK = m.BASE_RISK
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- cadences ----
def cadence_dates(cal, kind):
    if kind == "daily":
        return set(cal)
    out, seen = [], set()
    for d in cal:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if kind in ("weekly", "biweekly"):
            key = dt.strftime("%G-W%V")
        elif kind == "monthly":
            key = d[:7]
        elif kind == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
        elif kind == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
        elif kind == "annual":
            key = d[:4]
        if key not in seen:
            seen.add(key); out.append(d)
    if kind == "biweekly":
        out = out[::2]
    return set(out)

# ---------------------------------------------------------------- engine ---
class CadenceSim:
    """v2 Sim mechanics (copied semantics from aggressive-v2.py) +
    cadence gating + v9 protection + optional v2-design placebo entries."""
    def __init__(self, D, cal, cad_dates, placebo_rng=None, entry_prob=0.0):
        self.D, self.cal = D, cal
        self.cad = cad_dates
        self.rng, self.entry_prob = placebo_rng, entry_prob
        self.mode = "placebo" if placebo_rng is not None else "v2"
        self.cash = START
        self.positions = {}
        self.trades = []
        self.round_trips = []
        self.equity_curve = []
        self.total_costs = 0.0
        self.prev_equity = START
        self.peak = START
        self.no_entry_today = False
        self.counters = {"base_signals": 0, "blocked_regime": 0,
                         "blocked_confluence": 0, "blocked_cost_gate": 0,
                         "entries": 0}
        # v9 protection state
        self.episode = 1
        self.floor = 0.85 * START
        self.halts = []            # [{breach_date, liquidation_date, cash, episode}]
        self.restart_date = None
        self.second_halt = False
        self.sit_out_until = None
        self.ended = False

    # -- borrowed mechanics (identical formulas to v2 Sim) --
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
        self.round_trips.append({"sym": sym, "pnl": (gross - cost) - p["cost_in"]})
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

    def v2_candidates(self, prev_date):
        # identical to v2 Sim.v2_candidates
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

    # -- main loop --
    def run(self):
        cal = self.cal
        spy_rows = self.D["rows"]["SPY"]
        for di, date in enumerate(cal):
            last_day = di == len(cal) - 1
            gi = self.D["idx"]["SPY"][date]
            self._signal_date = spy_rows[gi - 1]["date"] if gi > 0 else None
            trading_day = (not self.ended and self.sit_out_until is None
                           and date in self.cad)
            if self.sit_out_until is not None and date >= self.sit_out_until \
                    and date in self.cad and self.restart_date is None:
                # restart episode 2 at this cadence date
                self.restart_date = date
                self.episode = 2
                self.floor = 0.85 * self.cash
                self.peak = self.cash
                self.prev_equity = self.cash
                self.sit_out_until = None
                trading_day = True
            if trading_day:
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
            # end of day: mark, floor check (daily, as original)
            eq = self.equity_at_close(date)
            self.equity_curve.append((date, eq))
            self.peak = max(self.peak, eq)
            if not self.ended and self.sit_out_until is None and eq <= self.floor \
                    and not last_day:
                nxt = cal[di + 1]
                for s in list(self.positions.keys()):
                    nb = self.bar(s, nxt)
                    if nb:
                        self.sell(s, nxt, nb["open"], "FLOOR breach liquidation")
                self.halts.append({"breach_date": date, "liquidation_date": nxt,
                                   "cash_after": round(self.cash, 2),
                                   "episode": self.episode})
                if self.episode == 1:
                    resume = (datetime.strptime(date, "%Y-%m-%d")
                              + timedelta(days=90)).strftime("%Y-%m-%d")
                    self.sit_out_until = resume
                else:
                    self.second_halt = True
                    self.ended = True
                self.equity_curve.append((nxt, self.cash))
                self.prev_equity = self.cash
                continue
            self.no_entry_today = (self.prev_equity > 0
                                   and (eq / self.prev_equity - 1) <= -0.04)
            self.prev_equity = eq
            if last_day and not self.ended:
                for s in list(self.positions.keys()):
                    b = self.bar(s, date)
                    if b:
                        self.sell(s, date, b["close"], "end of period liquidation")
                self.equity_curve[-1] = (date, self.cash)
        # de-duplicate curve dates (halt appends next date early), keep last
        seen = {}
        for d, e in self.equity_curve:
            seen[d] = e
        self.equity_curve = sorted(seen.items())
        return self

    def stats(self):
        final = round(self.cash, 2)
        peak, max_dd = START, 0.0
        for _, e in self.equity_curve:
            peak = max(peak, e)
            max_dd = max(max_dd, (peak - e) / peak * 100)
        yrs = (datetime.strptime(self.cal[-1], "%Y-%m-%d")
               - datetime.strptime(self.cal[0], "%Y-%m-%d")).days / 365.25
        wins = sum(1 for r in self.round_trips if r["pnl"] > 0)
        return {"final": final,
                "cagr_pct": round(((final / START) ** (1 / yrs) - 1) * 100, 2),
                "max_dd_pct": round(max_dd, 2),
                "costs": round(self.total_costs, 2),
                "orders": len(self.trades),
                "round_trips": len(self.round_trips),
                "win_rate_pct": round(100 * wins / len(self.round_trips), 1)
                                if self.round_trips else 0,
                "halts": self.halts,
                "restart": self.restart_date is not None,
                "restart_date": self.restart_date,
                "second_halt": self.second_halt,
                "counters": self.counters}

# ------------------------------------------------------------------- SPY ----
def spy_decade_divadj():
    path = os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    d = json.load(open(path))
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, t in enumerate(res["timestamp"]):
        if q["close"][i] is None:
            continue
        rows.append((datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                     q["open"][i], q["close"][i], adj[i]))
    rows = [r for r in rows if DECADE[0] <= r[0] <= DECADE[1]]
    o0, c0, a0 = rows[0][1], rows[0][2], rows[0][3]
    scaled_open = o0 * a0 / c0
    sh = START / (scaled_open * (1 + COST_RATE))
    net = sh * rows[-1][3] * (1 - COST_RATE) - SELL_FEE
    peak, mdd = 0.0, 0.0
    for r in rows:
        peak = max(peak, r[3]); mdd = max(mdd, (peak - r[3]) / peak * 100)
    return round(net, 2), round(mdd, 2)

# ------------------------------------------------------------------ main ----
def main():
    D = m.load_data()
    cal = m.calendar(D, *DECADE)
    spy_div, spy_dd = spy_decade_divadj()
    print(f"SPY DECADE dividend-adjusted (program costs): ${spy_div} maxDD {spy_dd}%")
    summary = {}
    for cad_name in CADENCES:
        cad = cadence_dates(cal, cad_name)
        sim = CadenceSim(D, cal, cad).run()
        st = sim.stats()
        entry_prob = min(1.0, st["counters"]["entries"] / max(1, len(cad)))
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            twin = CadenceSim(D, cal, cad,
                              placebo_rng=rng, entry_prob=entry_prob).run()
            twins.append(round(twin.cash, 2))
        beaten = sum(1 for t in twins if st["final"] > t)
        cell = {"cadence": cad_name, "window": list(DECADE),
                "n_cadence_dates": len(cad),
                "stats": st,
                "equity_curve": [[d, round(e, 4)] for d, e in sim.equity_curve],
                "placebo": {"design": "v2 random-entry placebo (the original "
                                      "engine's own placebo mode): per cadence "
                                      "date, rng draw < entry_prob (real entries "
                                      "/ cadence dates) enters a uniformly random "
                                      "free universe symbol via the identical "
                                      "sizing path (no entry filters, no cost "
                                      "gate — as coded in v2); identical cadence "
                                      "exits and v9 protection",
                            "entry_prob": round(entry_prob, 4),
                            "seeds": list(range(1, 21)),
                            "twin_finals": twins,
                            "seeds_beaten": beaten}}
        with open(os.path.join(HERE, "cells", f"{cad_name}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        summary[cad_name] = {
            "final": st["final"], "cagr_pct": st["cagr_pct"],
            "max_dd_pct": st["max_dd_pct"], "halts": st["halts"],
            "restart": st["restart"], "second_halt": st["second_halt"],
            "costs": st["costs"], "orders": st["orders"],
            "round_trips": st["round_trips"],
            "placebo_beaten": beaten,
            "placebo_note": "20 v2-design random-entry twins, seeds 1-20; "
                            f"entry_prob={round(entry_prob,4)}"}
        print(f"{cad_name:11s} final ${st['final']:7.2f} DD {st['max_dd_pct']:5.2f}% "
              f"costs ${st['costs']:6.2f} orders {st['orders']:4d} "
              f"halts {len(st['halts'])} placebo beaten {beaten}/20")
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump({"decade_spy_final_divadj": spy_div,
                   "decade_spy_max_dd_pct": spy_dd,
                   "decade_spy_final_price_only_net": 314.10,
                   "summary": summary}, f, indent=1)
    print("saved cells/*.json + sweep_raw.json")

if __name__ == "__main__":
    main()
