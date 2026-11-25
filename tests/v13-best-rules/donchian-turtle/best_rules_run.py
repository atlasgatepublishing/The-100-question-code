#!/usr/bin/env python3
"""V13 BEST-RULES RUN — Donchian / Turtle breakout, Claude-designed rules.
Frozen spec: BEST-RULES-SPEC.md in this folder. Summary:
- System 2 channels only: enter long on intraday break of prior 55-day high,
  exit on intraday break of prior 20-day low. Long only. No other stop.
- Universe: SPY QQQ IWM IEFA EEM GLD TLT VNQ DBC AGG (shared v3 cache).
- Sizing: vol-parity slice = equity * 20% * (1.5% / N%), clamped [5%, 40%]
  of equity; N = 20-day Wilder ATR through the prior day. Gross notional
  capped at current equity; skip if room < 5% of equity. No pyramiding.
- No pot floor. Costs: 0.10%/side + $0.01 per sell order. $100 pots.
- Placebos: 20 seeds/road, real entry days & counts, random symbols from
  those not held, identical sizing/exits/costs.
Data (read-only): backtests/v3/tournament2-data/*.csv (OHLC from 2015-01-02).
"""
import csv, json, pathlib, random, statistics

DATA = pathlib.Path.home() / "workspace/stock-app/backtests/v3/tournament2-data"
SYMS = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "GLD", "TLT", "VNQ", "DBC", "AGG"]
START = 100.0
COST = 0.001
SELL_FEE = 0.01

def load():
    out = {}
    for s in SYMS:
        rows = list(csv.DictReader(open(DATA / f"{s}.csv")))
        out[s] = {"d": [r["date"] for r in rows],
                  "o": [float(r["open"]) for r in rows],
                  "h": [float(r["high"]) for r in rows],
                  "l": [float(r["low"]) for r in rows],
                  "c": [float(r["close"]) for r in rows]}
    return out

B = load()
DATES = B["SPY"]["d"]
IDX = {d: i for i, d in enumerate(DATES)}
NDAYS = len(DATES)

def wilder_n(s):
    tr = [0.0] * NDAYS
    for i in range(1, NDAYS):
        h, l, pc = B[s]["h"][i], B[s]["l"][i], B[s]["c"][i - 1]
        tr[i] = max(h - l, abs(h - pc), abs(pc - l))
    n = [None] * NDAYS
    n[20] = sum(tr[1:21]) / 20.0
    for i in range(21, NDAYS):
        n[i] = (n[i - 1] * 19 + tr[i]) / 20.0
    return n

NVAL = {s: wilder_n(s) for s in SYMS}

def chan_hi(s, i, days):
    return max(B[s]["h"][i - days:i]) if i >= days else None

def chan_lo(s, i, days):
    return min(B[s]["l"][i - days:i]) if i >= days else None

def run(window_start, window_end, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    s_i, e_i = IDX[window_start], IDX[window_end]
    cash = START
    positions = {}   # sym -> {shares, entry_price, entry_date, entry_cost}
    costs = 0.0; orders = 0
    trades = []      # closed trades
    curve = []

    def equity(i):
        return cash + sum(p["shares"] * B[s]["c"][i] for s, p in positions.items())

    def gross(i):
        return sum(p["shares"] * B[s]["o"][i] for s, p in positions.items())

    for i in range(s_i, e_i + 1):
        exited_today = set()
        # --- exits first ---
        for s in list(positions.keys()):
            ex = chan_lo(s, i, 20)
            if ex is not None and B[s]["l"][i] <= ex:
                fill = min(B[s]["o"][i], ex)
                p = positions.pop(s)
                fee = p["shares"] * fill * COST + SELL_FEE
                proceeds = p["shares"] * fill - fee
                cash += proceeds; costs += fee; orders += 1
                trades.append({"sym": s, "entry_date": p["entry_date"],
                               "exit_date": DATES[i], "entry": round(p["entry_price"], 4),
                               "exit": round(fill, 4),
                               "pnl": round(proceeds - p["basis"], 2),
                               "ret_pct": round((proceeds / p["basis"] - 1) * 100, 2)})
                exited_today.add(s)
        # --- entries ---
        signals = []
        for s in SYMS:
            if s in positions or s in exited_today:
                continue
            lvl = chan_hi(s, i, 55)
            if lvl is not None and B[s]["h"][i] >= lvl:
                signals.append((s, lvl))
        if rng is not None and signals:
            pool = [s for s in SYMS if s not in positions and s not in exited_today]
            rng.shuffle(pool)
            signals = [(pool[k], None) for k in range(min(len(signals), len(pool)))]
        for s, lvl in signals:
            n = NVAL[s][i - 1] if i >= 1 else None
            if not n or n <= 0:
                continue
            eq = equity(i)
            npct = n / B[s]["c"][i - 1]
            target = eq * 0.20 * (0.015 / npct)
            target = max(eq * 0.05, min(eq * 0.40, target))
            room = eq - gross(i)
            if room < eq * 0.05:
                continue
            target = min(target, room)
            fill = B[s]["o"][i] if lvl is None else max(B[s]["o"][i], lvl)
            shares = target / fill
            fee = shares * fill * COST
            if shares * fill + fee > cash:
                shares = cash / (fill * (1 + COST))
                fee = shares * fill * COST
            if shares <= 0:
                continue
            cash -= shares * fill + fee; costs += fee; orders += 1
            positions[s] = {"shares": shares, "entry_price": fill,
                            "entry_date": DATES[i], "basis": shares * fill + fee}
        curve.append({"d": DATES[i], "eq": round(equity(i), 4)})
    # close-out accounting for expectancy: mark open positions at final close
    final = curve[-1]["eq"]
    pk, maxdd = START, 0.0
    for pt in curve:
        pk = max(pk, pt["eq"]); maxdd = max(maxdd, (pk - pt["eq"]) / pk if pk else 0)
    # monthly period stats
    months = {}
    prev = START
    seq = [START] + [pt["eq"] for pt in curve]
    md = [""] + [pt["d"][:7] for pt in curve]
    month_end = {}
    for d, e in zip(md[1:], seq[1:]):
        month_end[d] = e
    keys = sorted(month_end)
    rets = []
    last = START
    for k in keys:
        rets.append(month_end[k] / last - 1)
        last = month_end[k]
    pos_share = sum(1 for r in rets if r > 0) / len(rets) if rets else 0
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        mx = max(mx, streak)
    # longest stretch between new highs (days)
    pkv, since, longest = START, 0, 0
    for pt in curve:
        if pt["eq"] >= pkv:
            pkv, since = pt["eq"], 0
        else:
            since += 1; longest = max(longest, since)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    expectancy = {
        "closed_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(statistics.mean([t["pnl"] for t in wins]), 2) if wins else None,
        "avg_loss": round(statistics.mean([t["pnl"] for t in losses]), 2) if losses else None,
        "expectancy_per_trade": round(statistics.mean([t["pnl"] for t in trades]), 2) if trades else None,
        "best_trade": max((t["pnl"] for t in trades), default=None),
        "worst_trade": min((t["pnl"] for t in trades), default=None),
        "open_positions_end": len(positions),
    }
    yearly = {}
    for pt in curve:
        yearly[pt["d"][:4]] = pt["eq"]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders,
            "periods": {"n_months": len(rets),
                        "median_month_pct": round(statistics.median(rets) * 100, 2) if rets else None,
                        "share_positive_pct": round(pos_share * 100, 1),
                        "best_month_pct": round(max(rets) * 100, 2) if rets else None,
                        "worst_month_pct": round(min(rets) * 100, 2) if rets else None,
                        "longest_losing_streak_months": mx,
                        "longest_days_between_highs": longest,
                        "mean_month_pct_secondary": round(statistics.mean(rets) * 100, 2) if rets else None},
            "expectancy": expectancy, "trades": trades,
            "year_end_equity": yearly, "curve": curve}

def spy_buyhold(a, b):
    i, j = IDX[a], IDX[b]
    return round(START * B["SPY"]["c"][j] / B["SPY"]["c"][i - 1 if a == DATES[0] else i], 2) if False else \
           round(START * B["SPY"]["c"][j] / B["SPY"]["o"][i], 2)

WINDOWS = {"DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF_A": ("2017-01-03", "2020-12-31"), "CONF_B": ("2021-01-04", "2024-12-31")}
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def main():
    out = {"strategy": "v13 best-rules Donchian/Turtle: System-2 55/20 long-only, "
                       "intraday triggers, vol-parity sizing, no floor",
           "markets": SYMS, "windows": {}}
    beat = []
    for name, (a, b) in WINDOWS.items():
        r = run(a, b)
        twins = [run(a, b, placebo_seed=9100 + k)["final"] for k in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        out["windows"][name] = {"window": [a, b], **r,
                                "placebo_beaten": f"{beaten}/20",
                                "placebo_finals": twins,
                                "placebo_median": round(statistics.median(twins), 2),
                                "spy_price_only": spy_buyhold(a, b)}
        print(name, "final", r["final"], "dd", r["max_dd_pct"], "costs", r["costs"],
              "orders", r["orders"], "trades", r["expectancy"]["closed_trades"],
              "| placebo", beaten, "/20 median", round(statistics.median(twins), 2),
              "| SPY(price)", spy_buyhold(a, b))
        if r["final"] > CHAMPION[name]:
            beat.append(name)
    if beat:
        out["confirmation"] = {}
        for name, (a, b) in CONF.items():
            r = run(a, b)
            out["confirmation"][name] = {"window": [a, b], "final": r["final"],
                                         "max_dd_pct": r["max_dd_pct"],
                                         "spy_price_only": spy_buyhold(a, b)}
            print(name, "CONF final", r["final"], "SPY(price)", spy_buyhold(a, b))
    pathlib.Path(__file__).with_name("results.json").write_text(json.dumps(out, indent=1))
    print("saved results.json; champion beats:", beat or "none")

if __name__ == "__main__":
    main()
