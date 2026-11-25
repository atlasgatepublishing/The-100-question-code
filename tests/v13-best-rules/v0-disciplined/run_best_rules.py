#!/usr/bin/env python3
"""
V13 BEST-RULES - v0-disciplined. Spec: BEST-RULES-SPEC.md (frozen before run).

MY RULES: monthly selection; eligible = prior close above own 200d MA;
hold ALL eligible, EQUAL weight, 100% invested (cash if none eligible);
no ranking, no single-pick quirk, NO floor ladder; DAILY trend exit
(close below 200d MA -> sell next open, cash until next selection).
Costs 0.10%/side + $0.01/sell. $100 pots.

Modes:
  original  - frozen v0 form (top-2 ranked 50/50, 1 pick=50%, ladder
              $85->$100->$125 halt-ends-run) - PLUMBING VALIDATION ONLY:
              must reproduce v12 finals on this identical data.
  best      - my rules above.
  placeboA  - random top-2 from eligible set, 50/50, daily exits, no floor.
  placeboB  - random same-size (as best run) sample of FULL universe,
              ignoring filter, monthly only, no floor.

Data (read-only): v12-completions/v0-disciplined/data/*.csv
(Yahoo, split-adjusted, NOT dividend-adjusted; 2009-01-02..2026-11-20).
"""
import csv, json, os, random, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/v0-disciplined/data")
TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
PUBLISHED = {  # v12 settled record, frozen original form, same data
    "LONG":   {"final": 369.92, "max_dd_pct": 28.67},
    "DECADE": {"final": 248.63, "max_dd_pct": 19.40},
    "CONT":   {"final": 213.18, "max_dd_pct": 19.41},
    "VAL":    {"final": 151.25, "max_dd_pct": 14.35},
}
SIBLING_V13 = {"finals": {"LONG": 328.65, "DECADE": 265.44, "CONT": 227.04, "VAL": 165.60},
               "note": "disciplined-v2 and disciplined-v3 v13 passes (hold-all-eligible, no floor) - scale only, not this family's bar"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

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

def run(start, end, mode="best", seed=None, counts=None):
    rng = random.Random(seed)
    period = [d for d in DATES if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    date_index = {d: i for i, d in enumerate(DATES)}
    selection_days, seen = set(), set()
    for d in period:
        if d == first_day or d[:7] not in seen:
            selection_days.add(d)
        seen.add(d[:7])
    sel_list = [d for d in period if d in selection_days]
    cash, shares = 100.0, {t: 0.0 for t in TICKERS}
    trades, total_costs = [], 0.0
    floor, halted, halt_trigger_date = 85.0, False, None
    pending_exits, liquidate_next_open = set(), False
    daily = []
    elig_counts = []

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
        if mode == "original" and liquidate_next_open:
            for t in TICKERS:
                if shares[t] > 0: do_sell(t, d, opens[t], "floor-liquidation")
            halted = True
            daily.append([d, round(cash, 4)]); break
        if mode != "placeboB":
            for t in sorted(pending_exits):
                if shares[t] > 0: do_sell(t, d, opens[t], "trend-exit")
            pending_exits = set()
        if d in selection_days:
            ref = DATES[date_index[d]-1]
            eligible = [t for t in TICKERS
                        if ma200(t, ref) is not None and by_date[t][ref]["close"] > ma200(t, ref)]
            sel_idx = sel_list.index(d)
            if mode == "best":
                picks = list(eligible); elig_counts.append(len(picks))
                eq_open = equity(opens)
                targets = {t: eq_open/len(picks) for t in picks} if picks else {}
            elif mode == "original":
                ranked = sorted(eligible, key=lambda t: mom63(t, ref), reverse=True)
                picks = ranked[:2]
                targets = {t: 0.5*equity(opens) for t in picks}
            elif mode == "placeboA":
                picks = rng.sample(eligible, min(2, len(eligible))) if eligible else []
                targets = {t: 0.5*equity(opens) for t in picks}
            elif mode == "placeboB":
                k = counts[sel_idx] if counts and sel_idx < len(counts) else 0
                picks = rng.sample(TICKERS, k) if k else []
                eq_open = equity(opens)
                targets = {t: eq_open/len(picks) for t in picks} if picks else {}
            else:
                raise ValueError(mode)
            for t in TICKERS:
                if shares[t] <= 0: continue
                cur, tgt = shares[t]*opens[t], targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    do_sell(t, d, opens[t], "monthly-sell", (cur-tgt)/opens[t])
            wants = {t: targets[t]-shares[t]*opens[t] for t in picks
                     if t in targets and targets[t] > shares[t]*opens[t] + 0.005}
            twc = sum(v*(1+COST_RATE) for v in wants.values())
            scale = max(cash, 0.0)/twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants: do_buy(t, d, opens[t], wants[t]*scale, "monthly-buy")
        eq_close = equity(closes_today)
        daily.append([d, round(eq_close, 4)])
        if mode == "original":
            if eq_close >= 150.0: floor = max(floor, 125.0)
            elif eq_close >= 125.0: floor = max(floor, 100.0)
            if eq_close <= floor:
                if d == last_day:
                    for t in TICKERS:
                        if shares[t] > 0: do_sell(t, d, closes_today[t], "floor-liquidation")
                    halted, halt_trigger_date = True, d
                else:
                    liquidate_next_open, halt_trigger_date = True, d
                if halted: break
                continue
        if mode != "placeboB":
            for t in TICKERS:
                if shares[t] > 1e-9:
                    ma = ma200(t, d)
                    if ma is not None and closes_today[t] < ma: pending_exits.add(t)
    if not halted:
        for t in TICKERS:
            if shares[t] > 0: do_sell(t, last_day, by_date[t][last_day]["close"], "final-liquidation")
        final_balance = cash
        if daily and daily[-1][0] == last_day: daily[-1][1] = round(cash, 4)
    else:
        final_balance = cash
    peak, max_dd = 100.0, 0.0
    for _, eq in daily:
        peak = max(peak, eq); max_dd = max(max_dd, (peak-eq)/peak if peak > 0 else 0.0)
    so, sc = by_date["SPY"][first_day]["open"], by_date["SPY"][last_day]["close"]
    b_sh = 100.0/(so*(1+COST_RATE))
    spy_net = b_sh*sc*(1-COST_RATE) - SELL_FEE
    spy_curve, speak, sdd = [], 100.0, 0.0
    for d in period:
        v = 100.0/so*by_date["SPY"][d]["close"]
        spy_curve.append([d, round(v,4)]); speak = max(speak, v); sdd = max(sdd, (speak-v)/speak)
    yrs = len(period)/252.0
    return {"start": first_day, "end": last_day, "final": round(final_balance, 2),
            "cagr_pct": round(((final_balance/100.0)**(1/yrs)-1)*100, 2) if final_balance > 0 else None,
            "max_dd_pct": round(max_dd*100, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted, "halt_trigger_date": halt_trigger_date,
            "spy_priceonly_net": round(spy_net, 2), "spy_priceonly_max_dd_pct": round(sdd*100, 2),
            "curve": daily, "spy_curve_gross": spy_curve, "trades": trades,
            "eligible_counts": elig_counts}

def period_stats(curve):
    me = {}
    for d, v in curve: me[d[:7]] = v
    keys = sorted(me)
    rets, prev = [], 100.0
    for k in keys:
        rets.append(me[k]/prev - 1); prev = me[k]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    vals = [v for _, v in curve]
    runmax = vals[0]; gap = maxgap = 0
    for v in vals:
        if v >= runmax: runmax = v; gap = 0
        else: gap += 1; maxgap = max(maxgap, gap)
    return {"median_month_pct": round(statistics.median(rets)*100, 2),
            "months": len(rets),
            "months_positive_pct": round(100*pos/len(rets), 1),
            "best_month_pct": round(max(rets)*100, 2),
            "worst_month_pct": round(min(rets)*100, 2),
            "longest_losing_streak_months": streak,
            "longest_stretch_between_new_highs_days": maxgap,
            "mean_month_pct_secondary": round(statistics.mean(rets)*100, 2)}

def year_folds(start, end):
    folds = {}
    for y in range(int(start[:4]), int(end[:4]) + 1):
        s = max(start, f"{y}-01-01"); e = min(end, f"{y}-12-31")
        if s > e: continue
        # first trading day >= s handled by run() via period[0]
        r = run(s, e, mode="best")
        folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                         "window": [r["start"], r["end"]]}
    vals = [v["final"] for v in folds.values()]
    rets = [v - 100.0 for v in vals]
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 100 else 0; streak = max(streak, cur)
    return folds, {"median_year_final": round(statistics.median(vals), 2),
                   "share_years_positive_pct": round(100*sum(1 for v in vals if v > 100)/len(vals), 1),
                   "best_year_final": max(vals), "worst_year_final": min(vals),
                   "longest_losing_streak_years": streak,
                   "mean_year_final_secondary": round(statistics.mean(vals), 2)}

def main():
    out = {"family": "v0-disciplined", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md", "verdict_ceiling": "CANDIDATE",
           "data": "v12-completions/v0-disciplined/data (Yahoo, split-adj, NOT div-adj, 2009-01-02..2026-11-20) - read-only",
           "costs": "0.10%/side + $0.01 per sell order",
           "champion_vm": CHAMP, "spy_program_ref_div_adj": SPY_REF,
           "published_form_v12": PUBLISHED, "sibling_v13_scale": SIBLING_V13,
           "plumbing_validation": {}, "roads": {}}
    # 1) plumbing validation: original mode must reproduce v12 finals
    ok = True
    for name, (s, e) in ROADS.items():
        r = run(s, e, mode="original")
        match = (r["final"] == PUBLISHED[name]["final"])
        ok = ok and match
        out["plumbing_validation"][name] = {"reproduced_final": r["final"],
            "published_final": PUBLISHED[name]["final"], "match": match,
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"], "orders": r["orders"]}
        print(f"VALIDATE {name}: engine-original ${r['final']} vs published ${PUBLISHED[name]['final']} match={match} DD {r['max_dd_pct']}")
    out["plumbing_validation"]["all_match"] = ok
    # 2) my rules + placebos + folds
    for name, (s, e) in ROADS.items():
        r = run(s, e, mode="best")
        twinsA, twinsB = [], []
        for seed in range(1, 21):
            ta = run(s, e, mode="placeboA", seed=seed)
            twinsA.append({"seed": seed, "final": ta["final"], "max_dd_pct": ta["max_dd_pct"]})
            tb = run(s, e, mode="placeboB", seed=seed, counts=r["eligible_counts"])
            twinsB.append({"seed": seed, "final": tb["final"], "max_dd_pct": tb["max_dd_pct"]})
        beatenA = sum(1 for t in twinsA if r["final"] > t["final"])
        beatenB = sum(1 for t in twinsB if r["final"] > t["final"])
        folds, fold_sum = year_folds(s, e)
        out["roads"][name] = {
            "window": [s, e], "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"], "orders": r["orders"],
            "published_form": PUBLISHED[name], "champion_vm": CHAMP[name],
            "spy_program_ref_div_adj": SPY_REF[name],
            "spy_price_basis": {"final": r["spy_priceonly_net"], "max_dd_pct": r["spy_priceonly_max_dd_pct"]},
            "beats_champion": r["final"] > CHAMP[name],
            "placeboA_random_top2_from_eligible": {"beaten": beatenA,
                "median": round(statistics.median([t["final"] for t in twinsA]), 2),
                "max": max(t["final"] for t in twinsA), "finals": twinsA},
            "placeboB_random_samesize_full_universe_no_filter": {"beaten": beatenB,
                "median": round(statistics.median([t["final"] for t in twinsB]), 2),
                "max": max(t["final"] for t in twinsB), "finals": twinsB},
            "monthly_distribution": period_stats(r["curve"]),
            "year_folds": folds, "year_fold_summary": fold_sum,
            "curve": r["curve"], "spy_curve_gross": r["spy_curve_gross"],
            "trades": r["trades"]}
        print(f"{name}: BEST ${r['final']} DD {r['max_dd_pct']}% costs ${r['costs']} orders {r['orders']} "
              f"| published ${PUBLISHED[name]['final']} | champ ${CHAMP[name]} | SPYprice ${r['spy_priceonly_net']} "
              f"| placeboA beaten {beatenA}/20 | placeboB beaten {beatenB}/20")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote results.json; plumbing all_match =", ok)

if __name__ == "__main__":
    main()
