#!/usr/bin/env python3
"""
FOLKLORE TEST F-8 — STRICT GOLDEN CROSS / DEATH CROSS (50/200-day), SPY.
Terry's AI stock app program. Simulation only.

Spec source: ~/workspace/stock-app/research/v7-completeness/folklore-audit.md,
Spec F-8, implemented VERBATIM (frozen — no improvements, no reinterpretation):

  - Universe/data: SPY daily closes. SMA50 and SMA200 on closes.
  - Rule (frozen): hold SPY whenever SMA50 > SMA200; hold cash whenever
    SMA50 <= SMA200. Evaluate daily, execute switches at the next open.

House chassis (same as the sibling SPY-timing engine trial, RSI(2) v6):
  - Whole $100 pot in or out; cash earns 0%. Fractional shares.
  - Costs (program schedule): 0.10% of trade value per side + $0.01 per
    sell order.
  - Plain -15% floor at pot level: a close with equity < $85.00 liquidates
    at the next open and halts the window.
  - Any position still open at a window's end is liquidated at the final
    close (sell cost charged).
  - Windows: continuous 2019-01-02 -> 2026-11-20; validation
    2023-01-03 -> 2026-11-20 (fresh $100). Yearly folds 2020-2026 as
    supplementary reporting (fresh $100 each), as in the sibling report.
  - Control: SPY buy-hold on identical windows with identical costs.
    Integrity check: the control must reproduce the program's published
    SPY nets ($313.62 continuous, $187.77 validation) — asserted in main().

Data: program price cache ~/workspace/stock-app/backtests/v4/data/px_SPY.json
(Yahoo daily, 2017-06-01 -> 2026-11-20), same construction as the v4
engines: open scaled by adjclose/close ratio, close = adjclose. SMAs are
computed on the full cached series from 2017-06-01, so both windows open
with a genuine point-in-time 200-day average (~399 bars of warmup before
2019-01-02); no future data is ever used.

DISTINCTNESS NOTE (from the audit): the sibling rule — price vs. its own
200-day average, SPY form — already failed its engine trial in this
program ($95.46 decade, halted 2020-03-23). F-8 is the slower, distinct
50/200 cross and is graded on its own run only.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v4/data/px_SPY.json")

START_CASH = 100.0
FLOOR = 85.0           # plain -15% floor on the $100 pot
COST_RATE = 0.001      # 0.10% per side
SELL_FEE = 0.01        # $0.01 per sell order

END = "2026-11-20"
CHAMPION = {"continuous": 544.47, "validation": 288.05}
SPY_PUBLISHED = {"continuous": 313.62, "validation": 187.77}


# ---------------------------------------------------------------- data
def load_bars():
    with open(PX, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None or o is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def add_indicators(bars):
    """SMA50 and SMA200 on adjusted closes, point-in-time."""
    closes = [b["c"] for b in bars]
    n = len(closes)
    sma50 = [None] * n
    sma200 = [None] * n
    run50 = 0.0
    run200 = 0.0
    for i, c in enumerate(closes):
        run50 += c
        run200 += c
        if i >= 50:
            run50 -= closes[i - 50]
        if i >= 200:
            run200 -= closes[i - 200]
        if i >= 49:
            sma50[i] = run50 / 50.0
        if i >= 199:
            sma200[i] = run200 / 200.0
    for i, b in enumerate(bars):
        b["sma50"] = sma50[i]
        b["sma200"] = sma200[i]
    return bars


# ---------------------------------------------------------------- engine
def run_cross(bars, start, end):
    """Run the strict F-8 cross rule over bars[start..end], fresh $100 pot.
    Returns metrics + round-trip trade log + switch log + equity curve."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash = START_CASH
    shares = 0.0
    entry_cost = None
    entry_date = None
    halted = None
    trades = []
    switches = []
    costs = 0.0
    curve = []
    days_in = 0
    pending = None           # 'buy' or 'sell', executes at next open
    pending_kind = None      # 'golden_cross' | 'death_cross' | 'initial_long' | 'floor'

    for pos, i in enumerate(idx):
        b = bars[i]
        # execute pending order at this open
        if pending == "buy" and shares == 0.0 and halted is None:
            px = b["o"]
            shares = cash / (px * (1.0 + COST_RATE))
            bcost = shares * px * COST_RATE
            costs += bcost
            entry_cost = cash
            entry_date = b["d"]
            cash = 0.0
            switches.append({"signal_date": switches[-1]["signal_date"] if switches else None,
                             "kind": pending_kind, "exec_date": b["d"],
                             "action": "BUY", "price": round(px, 2)})
        elif pending == "sell" and shares > 0.0:
            px = b["o"]
            val = shares * px
            scost = val * COST_RATE + SELL_FEE
            costs += scost
            proceeds = val - scost
            reason = "floor" if pending_kind == "floor" else "signal"
            trades.append({
                "entry": entry_date, "exit": b["d"],
                "pnl": round(proceeds - entry_cost, 2),
                "ret_pct": round((proceeds / entry_cost - 1.0) * 100, 2),
                "exit_reason": reason,
            })
            switches.append({"signal_date": switches[-1]["signal_date"] if switches else None,
                             "kind": pending_kind, "exec_date": b["d"],
                             "action": "SELL", "price": round(px, 2)})
            cash = proceeds
            shares = 0.0
            entry_cost = None
            entry_date = None
        pending = None
        pending_kind = None

        equity = cash + shares * b["c"]
        curve.append((b["d"], equity))
        if shares > 0.0:
            days_in += 1

        is_last = pos == len(idx) - 1
        if is_last:
            break

        # floor check at the close
        if halted is None and equity < FLOOR:
            halted = b["d"]
            if shares > 0.0:
                pending = "sell"
                pending_kind = "floor"
                switches.append({"signal_date": b["d"], "kind": "floor",
                                 "exec_date": None, "action": "SELL_SIGNAL",
                                 "price": None})
            continue
        if halted is not None:
            continue

        # F-8 signal at the close: desired state from SMA50 vs SMA200
        if b["sma50"] is None or b["sma200"] is None:
            continue
        want_long = b["sma50"] > b["sma200"]
        is_long = shares > 0.0
        if want_long and not is_long:
            # a buy switch: golden cross, or the window's opening state
            prev = bars[i - 1] if i > 0 else None
            crossed = (prev is not None and prev["sma50"] is not None
                       and prev["sma200"] is not None
                       and prev["sma50"] <= prev["sma200"])
            kind = "golden_cross" if crossed else "initial_long"
            pending = "buy"
            pending_kind = kind
            switches.append({"signal_date": b["d"], "kind": kind,
                             "exec_date": None, "action": "BUY_SIGNAL",
                             "price": None})
        elif not want_long and is_long:
            pending = "sell"
            pending_kind = "death_cross"
            switches.append({"signal_date": b["d"], "kind": "death_cross",
                             "exec_date": None, "action": "SELL_SIGNAL",
                             "price": None})

    # final liquidation at the last close, if still holding
    if shares > 0.0:
        b = bars[idx[-1]]
        val = shares * b["c"]
        scost = val * COST_RATE + SELL_FEE
        costs += scost
        proceeds = val - scost
        trades.append({
            "entry": entry_date, "exit": b["d"],
            "pnl": round(proceeds - entry_cost, 2),
            "ret_pct": round((proceeds / entry_cost - 1.0) * 100, 2),
            "exit_reason": "window_end",
        })
        cash = proceeds
        shares = 0.0
        curve[-1] = (b["d"], cash)

    final = cash
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst, worst_d = float("inf"), None
    for d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > maxdd:
                maxdd, maxdd_d = dd, d
        if v < worst:
            worst, worst_d = v, d
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    exec_switches = [s for s in switches if s["action"] in ("BUY", "SELL")]
    return {
        "start": start, "end": end,
        "final": round(final, 2),
        "return_pct": round(final / START_CASH * 100 - 100, 2),
        "max_drawdown_pct": round(maxdd * 100, 2),
        "max_drawdown_date": maxdd_d,
        "worst_close": round(worst, 2),
        "worst_close_date": worst_d,
        "trades": len(trades),
        "switches_executed": len(exec_switches),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "expectancy_per_trade": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else None,
        "time_in_market_pct": round(100.0 * days_in / len(idx), 1) if idx else None,
        "costs": round(costs, 2),
        "halted": halted,
        "trade_log": trades,
        "switch_log": switches,
        "curve": curve,
    }


def buy_hold(bars, start, end):
    """SPY buy-hold, fresh $100, same costs, no floor: buy at the first
    open of the window, sell at the final close."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for i in idx:
        v = shares * bars[i]["c"]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2),
            "return_pct": round(final / START_CASH * 100 - 100, 2),
            "max_drawdown_pct": round(maxdd * 100, 2)}


def summarize(r):
    return {k: r[k] for k in ("start", "end", "final", "return_pct",
                              "max_drawdown_pct", "max_drawdown_date",
                              "worst_close", "worst_close_date",
                              "trades", "switches_executed", "win_rate_pct",
                              "avg_win", "avg_loss", "expectancy_per_trade",
                              "time_in_market_pct", "costs", "halted")}


def main():
    bars = add_indicators(load_bars())
    first_dates = {}
    for b in bars:
        first_dates.setdefault(b["d"][:4], b["d"])
    out = {"strategy": "FOLKLORE F-8 strict golden cross / death cross "
                       "(SMA50 vs SMA200), SPY only",
           "instrument": "SPY", "pot": START_CASH, "floor": FLOOR,
           "costs": "0.10%/side + $0.01/sell",
           "data": "Yahoo daily, adjclose-based, v4 cache px_SPY.json "
                   "2017-06-01..2026-11-20",
           "champion_reference": CHAMPION}

    windows = {
        "continuous": ("2019-01-02", END),
        "validation": ("2023-01-03", END),
    }
    for name, (ws, we) in windows.items():
        r = run_cross(bars, ws, we)
        bh = buy_hold(bars, ws, we)
        pub = SPY_PUBLISHED[name]
        match = abs(bh["final"] - pub) < 0.02
        print(f"INTEGRITY {name}: SPY buy-hold ${bh['final']:,.2f} vs "
              f"published ${pub:,.2f} match={match}", flush=True)
        if not match:
            raise SystemExit("SPY control does not reproduce published net "
                             "— results untrusted")
        out[name] = {"f8": summarize(r), "buy_hold": bh,
                     "spy_published": pub, "spy_reproduced": match,
                     "champion": CHAMPION[name],
                     "trade_log": r["trade_log"],
                     "switch_log": r["switch_log"]}
        print(f"{name.upper()} {ws}->{we}: F-8 ${r['final']:,.2f} "
              f"({r['return_pct']:+.2f}%) trades={r['trades']} "
              f"switches={r['switches_executed']} win={r['win_rate_pct']}% "
              f"inMkt={r['time_in_market_pct']}% maxDD={r['max_drawdown_pct']}% "
              f"worst=${r['worst_close']} ({r['worst_close_date']}) "
              f"costs=${r['costs']} halted={r['halted']}", flush=True)
        print(f"   buy-hold SPY ${bh['final']:,.2f} ({bh['return_pct']:+.2f}%) "
              f"maxDD={bh['max_drawdown_pct']}% | champion ${CHAMPION[name]:,.2f}",
              flush=True)

    folds = []
    for y in range(2020, 2027):
        ws = first_dates[str(y)]
        we = END if y == 2026 else f"{y}-12-31"
        r = run_cross(bars, ws, we)
        bh = buy_hold(bars, ws, we)
        row = {"year": y, "start": ws, "end": we,
               "f8_final": r["final"], "f8_return_pct": r["return_pct"],
               "trades": r["trades"], "switches_executed": r["switches_executed"],
               "time_in_market_pct": r["time_in_market_pct"],
               "max_drawdown_pct": r["max_drawdown_pct"],
               "halted": r["halted"],
               "buy_hold_final": bh["final"],
               "buy_hold_return_pct": bh["return_pct"],
               "beat_buy_hold": r["final"] > bh["final"]}
        folds.append(row)
        print(f"FOLD {y}: F-8 ${r['final']:,.2f} ({r['return_pct']:+.2f}%) "
              f"trades={r['trades']} inMkt={r['time_in_market_pct']}% "
              f"halted={r['halted']} | BH ${bh['final']:,.2f} "
              f"({bh['return_pct']:+.2f}%) beat={row['beat_buy_hold']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_buy_hold"])
    out["fold_record"] = (f"{wins} wins, {len(folds) - wins} losses vs SPY "
                          f"buy-hold (folds 2020-2026)")
    print(out["fold_record"])

    with open(os.path.join(HERE, "folklore-f8-goldencross-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
