#!/usr/bin/env python3
"""
CONNORS RSI(2) MEAN REVERSION ON SPY — Terry's AI stock app. Simulation only.

Published rule (Connors & Alvarez, "Short Term Trading Strategies That
Work," 2008), run in the program's standard format:

  - Instrument: SPY only. Whole $100 pot in or out; cash earns 0%.
  - BUY signal (at close): SPY close above its 200-day simple moving
    average AND Wilder RSI(2) of the close below the threshold (10 as
    published; 50 for the neutral control) -> buy at NEXT OPEN.
  - EXIT signal (at close): SPY close above its 5-day simple moving
    average -> sell at NEXT OPEN.
  - Costs (program schedule): 0.10% of trade value per side + $0.01 per
    sell order. Fractional shares, as in the program's other engines.
  - Plain -15% floor at pot level: if pot equity at a close falls below
    $85.00, liquidate at next open and halt for the rest of the window.
  - Any position still open at a window's end is liquidated at the final
    close (sell cost charged), as in the program's other engines.

Data: SPY daily bars fetched from Yahoo's chart API with the same
construction the v4 engines use (open scaled by adjclose/close ratio,
close = adjclose), cached read-only in this folder as px_SPY_long.json
(2015-06-01 -> 2026-11-20). Indicators are computed on the full series
from 2015 so every window starts with a genuine point-in-time 200-day
average and RSI state; no future data is ever used.

Windows:
  - Continuous: 2017-01-03 -> 2026-11-20 (first trading day of 2017 to
    the last available bar).
  - Validation: 2023-01-03 -> 2026-11-20, fresh $100.
  - Yearly folds: each calendar year 2017..2026, fresh $100 (2026 fold
    ends 2026-11-20).

Controls (a one-instrument timing system has no cross-section to
randomize, so seed placebos do not apply):
  - SPY buy-hold on identical windows with identical costs: the market
    the system must beat for its timing to be worth anything.
  - The identical system with the RSI threshold at a neutral 50: holds
    every other piece of machinery fixed and varies only the oversold
    signal's strength, isolating what the extreme-oversold entry adds
    over "buy any mild dip in an uptrend." This is the placebo analog
    for a timing rule.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.join(HERE, "px_SPY_long.json")

START_CASH = 100.0
FLOOR = 85.0           # plain -15% floor on the $100 pot
COST_RATE = 0.001      # 0.10% per side
SELL_FEE = 0.01        # $0.01 per sell order

END = "2026-11-20"


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
    """SMA5, SMA200 and Wilder RSI(2) on adjusted closes, point-in-time."""
    closes = [b["c"] for b in bars]
    n = len(closes)
    sma5 = [None] * n
    sma200 = [None] * n
    run5 = 0.0
    run200 = 0.0
    for i, c in enumerate(closes):
        run5 += c
        run200 += c
        if i >= 5:
            run5 -= closes[i - 5]
        if i >= 200:
            run200 -= closes[i - 200]
        if i >= 4:
            sma5[i] = run5 / 5.0
        if i >= 199:
            sma200[i] = run200 / 200.0
    # Wilder RSI(2)
    rsi = [None] * n
    if n > 2:
        gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
        ag = (gains[0] + gains[1]) / 2.0
        al = (losses[0] + losses[1]) / 2.0
        # rsi index i corresponds to gains/losses index i-1; first RSI at i=2
        for i in range(2, n):
            if i > 2:
                ag = (ag * 1.0 + gains[i - 1]) / 2.0
                al = (al * 1.0 + losses[i - 1]) / 2.0
            if al == 0:
                rsi[i] = 100.0 if ag > 0 else 50.0
            else:
                rsi[i] = 100.0 - 100.0 / (1.0 + ag / al)
    for i, b in enumerate(bars):
        b["sma5"] = sma5[i]
        b["sma200"] = sma200[i]
        b["rsi2"] = rsi[i]
    return bars


# ---------------------------------------------------------------- engine
def run_system(bars, start, end, threshold):
    """Run the RSI(2) system over bars[start..end] with a fresh $100 pot.
    bars are the full series (indicators precomputed); trading is limited
    to dates in [start, end]. Returns metrics + trade log + equity curve."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash = START_CASH
    shares = 0.0
    entry_cost = None        # total cash spent on the open position
    entry_date = None
    halted = None
    trades = []
    costs = 0.0
    curve = []
    days_in = 0
    pending = None           # 'buy' or 'sell', executes at next open

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
        elif pending == "sell" and shares > 0.0:
            px = b["o"]
            val = shares * px
            scost = val * COST_RATE + SELL_FEE
            costs += scost
            proceeds = val - scost
            trades.append({
                "entry": entry_date, "exit": b["d"],
                "pnl": round(proceeds - entry_cost, 2),
                "ret_pct": round((proceeds / entry_cost - 1.0) * 100, 2),
                "exit_reason": "floor" if halted else "signal",
            })
            cash = proceeds
            shares = 0.0
            entry_cost = None
            entry_date = None
        pending = None

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
            continue
        if halted is not None:
            continue

        # signals at the close
        if shares == 0.0:
            if (b["sma200"] is not None and b["rsi2"] is not None
                    and b["c"] > b["sma200"] and b["rsi2"] < threshold):
                pending = "buy"
        else:
            if b["sma5"] is not None and b["c"] > b["sma5"]:
                pending = "sell"

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
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    return {
        "start": start, "end": end, "threshold": threshold,
        "final": round(final, 2),
        "return_pct": round(final / START_CASH * 100 - 100, 2),
        "max_drawdown_pct": round(maxdd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "expectancy_per_trade": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else None,
        "time_in_market_pct": round(100.0 * days_in / len(idx), 1) if idx else None,
        "costs": round(costs, 2),
        "halted": halted,
        "trade_log": trades,
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
                              "max_drawdown_pct", "trades", "win_rate_pct",
                              "avg_win", "avg_loss", "expectancy_per_trade",
                              "time_in_market_pct", "costs", "halted")}


def main():
    bars = add_indicators(load_bars())
    first_dates = {}
    for b in bars:
        first_dates.setdefault(b["d"][:4], b["d"])
    out = {"instrument": "SPY", "pot": START_CASH, "floor": FLOOR,
           "costs": "0.10%/side + $0.01/sell", "data": "Yahoo daily, adjclose-based, 2015-06-01..2026-11-20"}

    windows = {
        "continuous": ("2017-01-03", END),
        "validation": ("2023-01-03", END),
    }
    for name, (ws, we) in windows.items():
        r10 = run_system(bars, ws, we, 10)
        r50 = run_system(bars, ws, we, 50)
        bh = buy_hold(bars, ws, we)
        out[name] = {"rsi10": summarize(r10), "rsi50": summarize(r50),
                     "buy_hold": bh, "rsi10_trade_log": r10["trade_log"]}
        print(f"{name.upper()} {ws}->{we}: RSI(2)<10 ${r10['final']:,.2f} "
              f"({r10['return_pct']:+.2f}%) trades={r10['trades']} "
              f"win={r10['win_rate_pct']}% avgW={r10['avg_win']} avgL={r10['avg_loss']} "
              f"exp={r10['expectancy_per_trade']} inMkt={r10['time_in_market_pct']}% "
              f"maxDD={r10['max_drawdown_pct']}% costs=${r10['costs']} halted={r10['halted']}")
        print(f"   control RSI(2)<50 ${r50['final']:,.2f} ({r50['return_pct']:+.2f}%) "
              f"trades={r50['trades']} win={r50['win_rate_pct']}% inMkt={r50['time_in_market_pct']}% "
              f"maxDD={r50['max_drawdown_pct']}% costs=${r50['costs']} halted={r50['halted']}")
        print(f"   buy-hold SPY ${bh['final']:,.2f} ({bh['return_pct']:+.2f}%) maxDD={bh['max_drawdown_pct']}%")

    folds = []
    for y in range(2017, 2027):
        ws = first_dates[str(y)]
        we = END if y == 2026 else f"{y}-12-31"
        r10 = run_system(bars, ws, we, 10)
        bh = buy_hold(bars, ws, we)
        row = {"year": y, "start": ws, "end": we,
               "rsi10_final": r10["final"], "rsi10_return_pct": r10["return_pct"],
               "trades": r10["trades"], "win_rate_pct": r10["win_rate_pct"],
               "max_drawdown_pct": r10["max_drawdown_pct"],
               "time_in_market_pct": r10["time_in_market_pct"],
               "halted": r10["halted"],
               "buy_hold_final": bh["final"], "buy_hold_return_pct": bh["return_pct"],
               "beat_buy_hold": r10["final"] > bh["final"]}
        folds.append(row)
        print(f"FOLD {y}: RSI10 ${r10['final']:,.2f} ({r10['return_pct']:+.2f}%) "
              f"trades={r10['trades']} win={r10['win_rate_pct']}% inMkt={r10['time_in_market_pct']}% "
              f"halted={r10['halted']} | BH ${bh['final']:,.2f} ({bh['return_pct']:+.2f}%) "
              f"beat={row['beat_buy_hold']}")
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_buy_hold"])
    out["fold_record_all"] = f"{wins} wins, {len(folds) - wins} losses vs SPY buy-hold (2017-2026)"
    sub = [f for f in folds if f["year"] >= 2020]
    swins = sum(1 for f in sub if f["beat_buy_hold"])
    out["fold_record_2020_2026"] = f"{swins} wins, {len(sub) - swins} losses vs SPY buy-hold (2020-2026, champion's fold window)"
    print(out["fold_record_all"])
    print(out["fold_record_2020_2026"])

    with open(os.path.join(HERE, "rsi2-mean-reversion-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
