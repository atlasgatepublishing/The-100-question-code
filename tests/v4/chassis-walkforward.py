#!/usr/bin/env python3
"""
DISCIPLINED chassis — WALK-FORWARD test of the frozen v3 "best chassis"
configuration. Simulation only. No broker orders.

WHAT WAS MATCHED (from ../v3/disciplined-v3.md, read before coding):
  The v3 verdict's helpful changes, combined into one frozen config:
    D1  vol_scaling = False   (equal weights; v3: "remove it")
    D3  dd_cap      = False   (drawdown cap REMOVED; biggest design gain)
    D6  top_k       = 3       (hold top 3 eligible)
    D8  rebalance   = quarterly
  Everything else exactly as in the v3 combo as run:
    universe SPY/QQQ/IWM/GLD/TLT; eligible = close above 200-day MA
    (signals from prior trading day's close); rank by trailing 63-day
    momentum; invested-share rule unchanged (0 picks -> 0%, 1 pick -> 50%,
    2+ picks -> 100%); trend exit on close below 200-day MA (sell next
    open); costs 0.10%/side + $0.01/sell; Terry's floor ladder with the
    v2 restart convention (halted pot restarts fresh next Jan 1, chained).
    DEFENSIVE MODE = ON: it was part of the v3 combo as run (D3+D6 kept
    the v2 base's defensive mode; D2 "defensive removed" was a separate
    single, was NOT in the combo, and is NOT in the verdict's list of
    helpful changes), so it stays on: at a selection where SPY's prior
    close is below its 200-day MA, invested share is capped at 50%.
  Note the difference from v3 trial 12/15: the literal v3 "combo" run was
  D3+D6 only (monthly, vol-scaled). This test freezes the verdict's full
  synthesis (D1+D3+D6+D8), which is the configuration the task specified.
  A replication check below re-runs the literal D3+D6 combo on the full
  period and must reproduce v3's published $241.29 / 395 trades.

WALK-FORWARD PROTOCOL (config frozen; nothing is re-tuned per fold):
  - Folds: for each calendar year 2019..2026, a FRESH pot (at $100) runs
    Jan 1 -> Dec 31 (2026: -> 2026-11-20). Per-year config return vs
    SPY's same-calendar-year return (close-to-close).
  - Stitched: one continuous pot 2016-11-21 -> 2026-11-20 at $50 AND
    $100 (v2 restart convention). LABELLED partially in-sample: the
    config was selected on 2016-2022 design data, so 2016-2022 folds
    are in-sample; 2023-2026 are the years the v3 study froze it for,
    themselves now seen once by v3's validation.
  - Placebo stitched: same machinery, random picks from the eligible
    set at each quarterly selection, seed 42 (same seed v3 used).

FLOOR SCALING: start S -> floor 0.85*S; ladder: floor rises to S at a
close >= 1.25*S, and to 1.25*S at a close >= 1.50*S.
  $100: floor $85; $100 @ $125; $125 @ $150 (v2 standard).
  $50:  floor $42.50; $50 @ $62.50; $62.50 @ $75 (Terry's $50 rule).

Data: free Yahoo Finance chart API cache from the v3 study
(../v3/data/*.csv, fetched 2015-01-01 -> 2026-11-20). Split-adjusted,
NOT dividend-adjusted — same caveat as every prior study.
"""
import csv, json, math, os, random, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "v3", "data")

UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
PLACEBO_SEED = 42

# The frozen chassis config (v3 verdict synthesis).
CHASSIS_CFG = {
    "vol_scaling": False,     # D1
    "defensive": True,        # kept ON — part of the v3 combo as run
    "dd_cap": False,          # D3
    "mom_lookback": 63,
    "top_k": 3,               # D6
    "rebalance": "quarterly",  # D8
    "abs_gate": False,
    "universe": list(UNIVERSE),
}

# Literal v3 trial-12/15 combo, for the replication check only.
V3_LITERAL_COMBO = {
    "vol_scaling": True, "defensive": True, "dd_cap": False,
    "mom_lookback": 63, "top_k": 3, "rebalance": "monthly",
    "abs_gate": False, "universe": list(UNIVERSE),
}


def fetch(ticker):
    cache = os.path.join(DATA_DIR, f"{ticker}.csv")
    rows = []
    with open(cache) as f:
        for r in csv.DictReader(f):
            rows.append({k: (r[k] if k == "date" else float(r[k]))
                         for k in r})
    return rows


class Market:
    def __init__(self):
        self.bars = {t: fetch(t) for t in UNIVERSE}
        self.by_date = {t: {r["date"]: r for r in rows}
                        for t, rows in self.bars.items()}
        self.closes = {t: [r["close"] for r in rows]
                       for t, rows in self.bars.items()}
        self.dates_all = [r["date"] for r in self.bars["SPY"]]
        self.idx_of = {t: {r["date"]: i for i, r in enumerate(rows)}
                       for t, rows in self.bars.items()}

    def ma200(self, t, date):
        i = self.idx_of[t][date]
        if i < 199:
            return None
        return sum(self.closes[t][i - 199:i + 1]) / 200.0

    def mom(self, t, date, lookback):
        i = self.idx_of[t][date]
        if i < lookback:
            return None
        return self.closes[t][i] / self.closes[t][i - lookback] - 1.0

    def vol20(self, t, date):
        i = self.idx_of[t][date]
        if i < 20:
            return None
        c = self.closes[t]
        rets = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
        return statistics.stdev(rets) * math.sqrt(252)


def run_segment(mkt, cfg, start, end, start_capital=100.0,
                mode="momentum", seed=PLACEBO_SEED):
    """One fresh pot of `start_capital`, first trading day on/after
    `start` through `end`. Mechanics identical to v3's run_segment,
    generalized only for the starting size / scaled floor ladder."""
    universe = cfg["universe"]
    dates_all = mkt.dates_all
    period = [d for d in dates_all if start <= d <= end]
    if not period:
        return None
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d) - 1] for d in period}

    selection_days = set()
    seen_keys = set()
    for d in period:
        if cfg["rebalance"] == "monthly":
            key = d[:7]
        else:  # quarterly
            key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
        if d == first_day or key not in seen_keys:
            selection_days.add(d)
        seen_keys.add(key)

    rng = random.Random(seed)
    cash = float(start_capital)
    shares = {t: 0.0 for t in universe}
    trades = []
    total_costs = 0.0
    floor = 0.85 * start_capital
    peak_close = float(start_capital)
    pending_exits = set()
    liquidate_next_open = False
    halt_trigger_date = None
    halted = False
    final_balance = None
    daily = []

    def equity(price_map):
        return cash + sum(shares[t] * price_map[t] for t in universe)

    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        n = value / price
        cash -= value + cost
        total_costs += cost
        shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    for d in period:
        opens = {t: mkt.by_date[t][d]["open"] for t in universe}
        closes_today = {t: mkt.by_date[t][d]["close"] for t in universe}

        if liquidate_next_open:
            for t in universe:
                if shares[t] > 0:
                    do_sell(t, d, opens[t], "floor-liquidation")
            halted = True
            final_balance = cash
            daily.append((d, cash))
            break

        for t in sorted(pending_exits):
            if shares[t] > 0:
                do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()

        if d in selection_days:
            ref = prior_day[d]
            info = {}
            for t in universe:
                ma = mkt.ma200(t, ref)
                c = mkt.by_date[t][ref]["close"]
                elig = (ma is not None and c > ma)
                if elig and cfg["abs_gate"]:
                    r252 = mkt.mom(t, ref, 252)
                    elig = (r252 is not None and r252 > 0)
                info[t] = {"close": c, "ma200": ma, "eligible": elig,
                           "mom": mkt.mom(t, ref, cfg["mom_lookback"]),
                           "vol20": mkt.vol20(t, ref)}
            eligible = [t for t in universe if info[t]["eligible"]]
            if mode == "placebo":
                k = min(cfg["top_k"], len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                ranked = sorted(eligible,
                                key=lambda t: info[t]["mom"], reverse=True)
                picks = ranked[:cfg["top_k"]]

            if len(picks) == 0:
                share = 0.0
            elif len(picks) == 1:
                share = 0.5
            else:
                share = 1.0
            if cfg["defensive"]:
                spy_ma = info["SPY"]["ma200"]
                if spy_ma is not None and info["SPY"]["close"] < spy_ma:
                    share = min(share, 0.5)
            if cfg["dd_cap"]:
                ref_equity = daily[-1][1] if daily else float(start_capital)
                dd_from_peak = ((peak_close - ref_equity) / peak_close
                                if peak_close > 0 else 0.0)
                if dd_from_peak >= 0.07:
                    share = min(share, 0.5)

            weights = {}
            if picks:
                if cfg["vol_scaling"]:
                    inv = {}
                    for t in picks:
                        v = info[t]["vol20"]
                        inv[t] = (1.0 / v) if (v and v > 1e-9) else None
                    if any(v is None for v in inv.values()):
                        weights = {t: 1.0 / len(picks) for t in picks}
                    else:
                        tot = sum(inv.values())
                        weights = {t: inv[t] / tot for t in picks}
                else:
                    weights = {t: 1.0 / len(picks) for t in picks}

            eq_open = equity(opens)
            targets = {t: share * eq_open * weights.get(t, 0.0)
                       for t in picks}
            for t in universe:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    reason = ("selection-sell-dropout" if t not in targets
                              else "selection-rebalance-trim")
                    do_sell(t, d, opens[t], reason, (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            total_want_cost = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = 1.0
            if total_want_cost > cash and total_want_cost > 0:
                scale = max(cash, 0.0) / total_want_cost
            for t in picks:
                if t in wants:
                    reason = ("selection-buy" if shares[t] == 0
                              else "selection-rebalance-add")
                    do_buy(t, d, opens[t], wants[t] * scale, reason)

        eq_close = equity(closes_today)
        daily.append((d, eq_close))
        if eq_close > peak_close:
            peak_close = eq_close

        if eq_close >= 1.50 * start_capital:
            floor = max(floor, 1.25 * start_capital)
        elif eq_close >= 1.25 * start_capital:
            floor = max(floor, float(start_capital))
        if eq_close <= floor:
            if d == last_day:
                for t in universe:
                    if shares[t] > 0:
                        do_sell(t, d, closes_today[t], "floor-liquidation")
                halted = True
                halt_trigger_date = d
                final_balance = cash
            else:
                liquidate_next_open = True
                halt_trigger_date = d
            if halted:
                break
            continue

        for t in universe:
            if shares[t] > 1e-9:
                ma = mkt.ma200(t, d)
                if ma is not None and closes_today[t] < ma:
                    pending_exits.add(t)

    if not halted:
        closes_last = {t: mkt.by_date[t][last_day]["close"] for t in universe}
        for t in universe:
            if shares[t] > 0:
                do_sell(t, last_day, closes_last[t], "final-liquidation")
        final_balance = cash

    return {"first_day": first_day, "last_day": last_day, "halted": halted,
            "halt_trigger_date": halt_trigger_date,
            "final_balance": final_balance, "total_trades": len(trades),
            "total_costs": total_costs, "daily": daily, "trades": trades}


def run_window(mkt, cfg, start, end, start_capital=100.0,
               mode="momentum", seed=PLACEBO_SEED):
    """Window with v2's restart convention (halt -> fresh pot next
    Jan 1, chained multiplicatively)."""
    segments = []
    seg_start = start
    while True:
        seg = run_segment(mkt, cfg, seg_start, end,
                          start_capital=start_capital, mode=mode, seed=seed)
        if seg is None:
            break
        segments.append(seg)
        if not seg["halted"]:
            break
        halt_year = int(seg["daily"][-1][0][:4])
        nxt = f"{halt_year + 1}-01-01"
        if nxt > end:
            break
        seg_start = nxt

    chained_daily = []
    factor = 1.0
    for seg in segments:
        for dte, eq in seg["daily"]:
            chained_daily.append((dte, eq * factor))
        factor *= seg["final_balance"] / start_capital
    chained_final = start_capital * factor

    peak, max_dd = float(start_capital), 0.0
    for _, eq in chained_daily:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    d0 = datetime.strptime(chained_daily[0][0], "%Y-%m-%d")
    d1 = datetime.strptime(chained_daily[-1][0], "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr = ((chained_final / start_capital) ** (1.0 / years) - 1.0
            if years > 0 else 0.0)

    return {
        "start_capital": start_capital,
        "final_balance": round(chained_final, 2),
        "return_pct": round((chained_final / start_capital - 1.0) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "total_trades": sum(s["total_trades"] for s in segments),
        "total_costs": round(sum(s["total_costs"] for s in segments), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_segments": len(segments),
        "halts": [s["halt_trigger_date"] for s in segments if s["halted"]],
        "first_day": chained_daily[0][0], "last_day": chained_daily[-1][0],
        "daily": [(d, round(e, 4)) for d, e in chained_daily],
    }


def benchmark(mkt, start, end, start_capital=100.0):
    period = [d for d in mkt.dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    spy_open = mkt.by_date["SPY"][first_day]["open"]
    spy_close = mkt.by_date["SPY"][last_day]["close"]
    gross = start_capital / spy_open * spy_close
    sh = start_capital / (spy_open * (1 + COST_RATE))
    net = sh * spy_close * (1 - COST_RATE) - SELL_FEE
    peak, max_dd = None, 0.0
    for d in period:
        c = mkt.by_date["SPY"][d]["close"]
        if peak is None or c > peak:
            peak = c
        if peak:
            max_dd = max(max_dd, (peak - c) / peak)
    return {"first_day": first_day, "last_day": last_day,
            "gross": round(gross, 2), "net": round(net, 2),
            "net_pct": round((net / start_capital - 1) * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2)}


def spy_year_return(mkt, year, end_override=None):
    """SPY calendar-year return, close-to-close (prior year-end close to
    this year-end close)."""
    dates = mkt.dates_all
    prev = [d for d in dates if d < f"{year}-01-01"]
    inyr = [d for d in dates if d.startswith(f"{year}-")]
    if end_override:
        inyr = [d for d in inyr if d <= end_override]
    c0 = mkt.by_date["SPY"][prev[-1]]["close"]
    c1 = mkt.by_date["SPY"][inyr[-1]]["close"]
    return round((c1 / c0 - 1.0) * 100, 2)


def brief(name, r):
    return {"name": name, "start": r["start_capital"],
            "final": r["final_balance"], "return_pct": r["return_pct"],
            "cagr_pct": r["cagr_pct"], "trades": r["total_trades"],
            "costs": r["total_costs"], "max_dd_pct": r["max_drawdown_pct"],
            "halts": r["halts"], "segments": r["n_segments"]}


def main():
    mkt = Market()
    out = {}
    FULL = ("2016-11-21", "2026-11-20")

    # --- replication check: literal v3 combo (D3+D6) full period @ $100
    # must reproduce v3's published $241.29 / 395 trades / $12.82 costs ---
    rep = run_window(mkt, dict(V3_LITERAL_COMBO), *FULL, start_capital=100.0)
    out["replication_check"] = brief("literal v3 combo D3+D6, full period",
                                     rep)
    print("REPLICATION (expect final 241.29, trades 395, costs 12.82):",
          json.dumps(out["replication_check"]))

    # --- folds: fresh $100 pot per calendar year 2019..2026 ---
    folds = []
    for year in range(2019, 2027):
        end = "2026-11-20" if year == 2026 else f"{year}-12-31"
        r = run_window(mkt, dict(CHASSIS_CFG), f"{year}-01-01", end,
                       start_capital=100.0)
        spy = spy_year_return(mkt, year,
                              end_override="2026-11-20" if year == 2026
                              else None)
        folds.append({"year": year, "config_return_pct": r["return_pct"],
                      "spy_return_pct": spy,
                      "beat_spy": r["return_pct"] > spy,
                      "config_final": r["final_balance"],
                      "trades": r["total_trades"], "costs": r["total_costs"],
                      "max_dd_pct": r["max_drawdown_pct"],
                      "halts": r["halts"]})
        print(f"FOLD {year}:", json.dumps(folds[-1]))
    out["folds"] = folds
    out["fold_record"] = {
        "wins": sum(1 for f in folds if f["beat_spy"]),
        "losses": sum(1 for f in folds if not f["beat_spy"]),
        "n": len(folds)}

    # --- stitched: one continuous pot, full span, $100 and $50 ---
    st100 = run_window(mkt, dict(CHASSIS_CFG), *FULL, start_capital=100.0)
    st50 = run_window(mkt, dict(CHASSIS_CFG), *FULL, start_capital=50.0)
    out["stitched_config_100"] = brief("chassis stitched $100", st100)
    out["stitched_config_50"] = brief("chassis stitched $50", st50)
    print("STITCHED CFG $100:", json.dumps(out["stitched_config_100"]))
    print("STITCHED CFG $50: ", json.dumps(out["stitched_config_50"]))

    # --- placebo stitched, same machinery, seed 42, both sizes ---
    pl100 = run_window(mkt, dict(CHASSIS_CFG), *FULL, start_capital=100.0,
                       mode="placebo", seed=PLACEBO_SEED)
    pl50 = run_window(mkt, dict(CHASSIS_CFG), *FULL, start_capital=50.0,
                      mode="placebo", seed=PLACEBO_SEED)
    out["stitched_placebo_100"] = brief("placebo stitched $100", pl100)
    out["stitched_placebo_50"] = brief("placebo stitched $50", pl50)
    print("STITCHED PLACEBO $100:", json.dumps(out["stitched_placebo_100"]))
    print("STITCHED PLACEBO $50: ", json.dumps(out["stitched_placebo_50"]))

    out["benchmark_full_100"] = benchmark(mkt, *FULL, start_capital=100.0)
    out["benchmark_full_50"] = benchmark(mkt, *FULL, start_capital=50.0)
    print("BENCH full $100:", json.dumps(out["benchmark_full_100"]))
    print("BENCH full $50: ", json.dumps(out["benchmark_full_50"]))

    with open(os.path.join(HERE, "chassis-walkforward-results.json"),
              "w") as f:
        json.dump(out, f, indent=2)
    print("FOLD RECORD:", json.dumps(out["fold_record"]))


if __name__ == "__main__":
    main()
