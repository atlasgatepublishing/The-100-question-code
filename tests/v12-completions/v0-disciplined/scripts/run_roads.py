#!/usr/bin/env python3
"""
v12 v0-DISCIPLINED — re-run of the FROZEN ORIGINAL v0 spec (year form) on the
standard roads. The engine logic is a faithful port of
backtests/2025-11-21-year/disciplined-year.py, generalised only in window:
  universe SPY/QQQ/IWM/GLD/TLT; monthly selection (window start + first trading
  day of each month) from prior close: eligible = close > 200d MA; rank by
  trailing 63d return; top 2 at 50/50 of equity (1 eligible -> 50%, 0 -> cash);
  rebalance at selection open (sells first, buys scaled to cash);
  trend exit: close below 200d MA -> sell next open, cash waits;
  costs 0.10%/side + $0.01 per sell order;
  ORIGINAL floor ladder: $85 start; close >= $125 -> floor $100; >= $150 ->
  floor $125; close <= floor -> liquidate next open (or final close) and END.
  Survivors liquidate at final close.
Placebos: seeds 1..20, picks = random sample of eligible set, same machinery.
Data: ../data/*.csv (Yahoo, split-adj, not div-adj), lead-in from 2009-01-01.
"""
import csv, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
    "YEAR_VERIFY": ("2025-11-21", "2026-11-20"),
}

bars, by_date, closes, idx_of = {}, {}, {}, {}
for t in TICKERS:
    with open(os.path.join(DATA, f"{t}.csv")) as f:
        rows = [{k: (r[k] if k == "date" else float(r[k])) for k in r} for r in csv.DictReader(f)]
    bars[t] = rows
    by_date[t] = {r["date"]: r for r in rows}
    closes[t] = [r["close"] for r in rows]
    idx_of[t] = {r["date"]: i for i, r in enumerate(rows)}
DATES = [r["date"] for r in bars["SPY"]]
for t in TICKERS:
    assert [r["date"] for r in bars[t]] == DATES, f"{t} calendar mismatch"

def ma200(t, date):
    i = idx_of[t][date]
    return None if i < 199 else sum(closes[t][i-199:i+1]) / 200.0

def mom63(t, date):
    i = idx_of[t][date]
    return None if i < 63 else closes[t][i] / closes[t][i-63] - 1.0

def run(start, end, mode="momentum", seed=None):
    rng = random.Random(seed)
    period = [d for d in DATES if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    prior_day = {d: DATES[DATES.index(d)-1] for d in period}
    selection_days, seen = set(), set()
    for d in period:
        if d == first_day or d[:7] not in seen:
            selection_days.add(d)
        seen.add(d[:7])
    cash, shares = 100.0, {t: 0.0 for t in TICKERS}
    trades, total_costs, floor = [], 0.0, 85.0
    pending_exits, liquidate_next_open = set(), False
    halted, halt_trigger_date, final_balance = False, None, None
    daily = []

    def equity(pm): return cash + sum(shares[t]*pm[t] for t in TICKERS)
    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0: return
        value = n*price; cost = value*COST_RATE + SELL_FEE
        cash += value - cost; total_costs += cost; shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell", "price": round(price,4),
                       "shares": round(n,6), "value": round(value,2), "reason": reason})
    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0: return
        cost = value*COST_RATE
        if value + cost > cash + 1e-9:
            value = cash/(1+COST_RATE); cost = value*COST_RATE
        n = value/price; cash -= value + cost; total_costs += cost; shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy", "price": round(price,4),
                       "shares": round(n,6), "value": round(value,2), "reason": reason})

    for d in period:
        opens = {t: by_date[t][d]["open"] for t in TICKERS}
        closes_today = {t: by_date[t][d]["close"] for t in TICKERS}
        if liquidate_next_open:
            for t in TICKERS:
                if shares[t] > 0: do_sell(t, d, opens[t], "floor-liquidation")
            halted, final_balance = True, cash
            daily.append([d, round(cash, 4)]); break
        for t in sorted(pending_exits):
            if shares[t] > 0: do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()
        if d in selection_days:
            ref = prior_day[d]
            info = {t: {"ma": ma200(t, ref), "mom": mom63(t, ref),
                        "eligible": (ma200(t, ref) is not None and by_date[t][ref]["close"] > ma200(t, ref))}
                    for t in TICKERS}
            eligible = [t for t in TICKERS if info[t]["eligible"]]
            if mode == "momentum":
                eligible.sort(key=lambda t: info[t]["mom"], reverse=True)
                picks = eligible[:2]
            else:
                picks = rng.sample(eligible, min(2, len(eligible)))
            eq_open = equity(opens)
            targets = {t: 0.5*eq_open for t in picks}
            for t in TICKERS:
                if shares[t] <= 0: continue
                cur, tgt = shares[t]*opens[t], targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    do_sell(t, d, opens[t], "monthly-sell-dropout" if t not in targets else "monthly-rebalance-trim", (cur-tgt)/opens[t])
            wants = {t: targets[t]-shares[t]*opens[t] for t in picks if targets[t] > shares[t]*opens[t] + 0.005}
            twc = sum(v*(1+COST_RATE) for v in wants.values())
            scale = max(cash, 0.0)/twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants: do_buy(t, d, opens[t], wants[t]*scale, "monthly-buy")
        eq_close = equity(closes_today)
        daily.append([d, round(eq_close, 4)])
        if eq_close >= 150.0: floor = max(floor, 125.0)
        elif eq_close >= 125.0: floor = max(floor, 100.0)
        if eq_close <= floor:
            if d == last_day:
                for t in TICKERS:
                    if shares[t] > 0: do_sell(t, d, closes_today[t], "floor-liquidation")
                halted, halt_trigger_date, final_balance = True, d, cash
            else:
                liquidate_next_open, halt_trigger_date = True, d
            if halted: break
            continue
        for t in TICKERS:
            if shares[t] > 1e-9:
                ma = ma200(t, d)
                if ma is not None and closes_today[t] < ma: pending_exits.add(t)
    if not halted:
        for t in TICKERS:
            if shares[t] > 0: do_sell(t, last_day, by_date[t][last_day]["close"], "final-liquidation")
        final_balance = cash
        if daily and daily[-1][0] == last_day: daily[-1][1] = round(cash, 4)
    peak, max_dd = 100.0, 0.0
    for _, eq in daily:
        peak = max(peak, eq); max_dd = max(max_dd, (peak-eq)/peak if peak > 0 else 0.0)
    # SPY buy-hold on same price data, same costs
    so, sc = by_date["SPY"][first_day]["open"], by_date["SPY"][last_day]["close"]
    b_sh = 100.0/(so*(1+COST_RATE))
    spy_net = b_sh*sc*(1-COST_RATE) - SELL_FEE
    spy_curve, speak, sdd = [], 100.0, 0.0
    for d in period:
        v = 100.0/(so)*by_date["SPY"][d]["close"]  # gross price curve for DD reference
        spy_curve.append([d, round(v,4)]); speak = max(speak, v); sdd = max(sdd, (speak-v)/speak)
    years = (len(period))/252.0
    return {"start": first_day, "end": last_day, "final": round(final_balance, 2),
            "cagr_pct": round(((final_balance/100.0)**(1/years)-1)*100, 2) if final_balance > 0 else None,
            "max_dd_pct": round(max_dd*100, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted, "halt_trigger_date": halt_trigger_date,
            "final_floor": floor, "days": len(daily),
            "spy_priceonly_net": round(spy_net, 2), "spy_priceonly_gross": round(100.0*sc/so, 2),
            "spy_priceonly_max_dd_pct": round(sdd*100, 2),
            "curve": daily, "spy_curve_gross": spy_curve, "trades": trades}

def main():
    out = {"slug": "v0-disciplined", "form": "frozen original v0 year form, unchanged (monthly selection, daily trend exits, original $85->$100->$125 ladder, halt ends run)",
           "costs": "0.10%/side + $0.01 per sell order (original/program)",
           "data": "Yahoo daily bars fetched 2026-11-22, 2009-01-01..2026-11-20, split-adjusted NOT dividend-adjusted, cached in data/",
           "integrity": {"status": "reproduced",
                         "original_finals": {"WEEK_2026-11-16_to_2026-11-20": 99.08, "YEAR_2025-11-21_to_2026-11-20": 102.75},
                         "reproduced_finals": {"WEEK_2026-11-16_to_2026-11-20": 99.08, "YEAR_2025-11-21_to_2026-11-20": 102.75},
                         "note": "Both original engines copied unmodified to /tmp and re-run on copies of their own caches: week $99.08 (costs $0.11, max DD 1.35%, SPY net $91.82); year $102.75 (35 trades, costs $1.17, max DD 14.36%, SPY net $105.09). Exact to the cent."},
           "spy_program_references_divadjusted": {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77},
           "champions": {"champion_vm": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}},
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = run(s, e)
        twins = []
        for seed in range(1, 21):
            tr = run(s, e, mode="random", seed=seed)
            twins.append({"seed": seed, "final": tr["final"], "max_dd_pct": tr["max_dd_pct"], "halted": tr["halted"]})
        beaten = sum(1 for tw in twins if r["final"] > tw["final"])
        r["placebo_beaten"] = beaten
        r["placebo_twins"] = twins
        out["roads"][name] = r
        print(name, r["final"], "DD", r["max_dd_pct"], "halted", r["halted"], r["halt_trigger_date"],
              "costs", r["costs"], "orders", r["orders"], "placebos", beaten, "/20  SPYnet(price)", r["spy_priceonly_net"])
    with open(os.path.join(HERE, "..", "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
