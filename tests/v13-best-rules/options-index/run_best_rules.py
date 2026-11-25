#!/usr/bin/env python3
"""Options Index — v13 BEST RULES. Implements BEST-RULES-SPEC.md exactly
(frozen before this run):
  MY RULES: 50% CBOE PUT index + 50% SPY (total return), rebalanced to
  50/50 on the first trading day of each calendar year inside the road.
  BXM deleted. No floor, no gate, no vol-scaling, no timing.
  Costs: program standard 0.10%/side + $0.01 per sell order, charged on
  every dollar traded (initial buys + rebalance turnover, both sleeves).
  PUT index levels embed CBOE's own fill conventions (no second spread).
  Cash 0%.
  Validation gate: pure PUT / pure BXM gross on identical plumbing must
  reproduce the settled record (PUT DECADE 207.65, BXM DECADE 192.89,
  PUT LONG 351.98, BXM LONG 303.74).
  Placebos: 20 seeds — annual rebalance shifted to a uniformly random
  trading day within the same calendar year; same weights, same costs.
Simulation only. Read-only inputs: v10 CBOE CSVs, v7 SPY adjusted closes.
"""
import csv, json, os, random, statistics, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/options-index")
SPYJSON = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {  # family's published best per road = PUT (settled record)
    "LONG": {"PUT": 351.98, "BXM": 303.74},
    "DECADE": {"PUT": 207.65, "BXM": 192.89},
}


def load_index(fn, col, drop_before=None):
    rows = []
    with open(os.path.join(V10, fn)) as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.strptime(r["DATE"], "%m/%d/%Y").strftime("%Y-%m-%d")
                rows.append((d, float(r[col])))
            except Exception:
                continue
    rows.sort()
    if drop_before:
        rows = [(d, v) for d, v in rows if d >= drop_before]
    return dict(rows)


def load_spy():
    j = json.load(open(SPYJSON))
    r = j["chart"]["result"][0]
    ts, adj = r["timestamp"], r["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for t, a in zip(ts, adj):
        if a:
            out[time.strftime("%Y-%m-%d", time.gmtime(t))] = float(a)
    return out


PUT = load_index("PUT_History.csv", "PUT", drop_before="2007-01-03")
BXM = load_index("BXM_History.csv", "BXM")
SPY = load_spy()


def pure(levels, start, end):
    days = sorted(d for d in levels if start <= d <= end)
    base = levels[days[0]]
    return round(START * levels[days[-1]] / base, 2), days


def dist_stats(curve):
    """curve: list of (date, equity). Per-calendar-year distribution."""
    by_year = {}
    for d, e in curve:
        by_year.setdefault(d[:4], []).append(e)
    years = sorted(by_year)
    rets = {}
    prev_end = curve[0][1]
    for i, y in enumerate(years):
        end_e = by_year[y][-1]
        start_e = curve[0][1] if i == 0 else prev_end
        rets[y] = round((end_e / start_e - 1) * 100, 2)
        prev_end = end_e
    vals = list(rets.values())
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    peak = curve[0][1]; last_high = 0; longest = 0
    for i, (_, e) in enumerate(curve):
        if e >= peak:
            peak = e; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - 1 - last_high)
    pk = curve[0][1]; mdd = 0.0
    for _, e in curve:
        pk = max(pk, e); mdd = min(mdd, e / pk - 1)
    return {"year_returns_pct": rets, "median_year_pct": round(statistics.median(vals), 2),
            "share_years_positive": round(sum(1 for v in vals if v > 0) / len(vals), 3),
            "best_year_pct": max(vals), "worst_year_pct": min(vals),
            "longest_losing_streak_years": streak,
            "longest_days_between_new_highs": longest,
            "max_dd_pct": round(mdd * 100, 2)}


def run_blend(start, end, seed=None):
    days = sorted(d for d in PUT if start <= d <= end and d in SPY)
    rng = random.Random(seed) if seed is not None else None
    # rebalance dates: first trading day of each year after the start year
    rebal = {}
    seen_years = set()
    for d in days:
        y = d[:4]
        if y not in seen_years:
            seen_years.add(y)
            rebal[y] = d
    if rng is not None:
        by_year = {}
        for d in days:
            by_year.setdefault(d[:4], []).append(d)
        for y in rebal:
            if y != days[0][:4]:
                rebal[y] = rng.choice(by_year[y])
    rebal_dates = {rebal[y] for y in rebal if y != days[0][:4]}

    d0 = days[0]
    half = START / 2
    up = (half - half * COST) / PUT[d0]      # units of PUT index
    us = (half - half * COST) / SPY[d0]      # units of SPY
    costs = half * COST * 2
    orders = 2
    trades = [[d0, "BUY both sleeves 50/50", round(START, 2), round(costs, 2)]]
    curve = []
    for d in days:
        if d in rebal_dates:
            vp, vs = up * PUT[d], us * SPY[d]
            total = vp + vs
            target = total / 2
            turnover = abs(vp - target)
            c = turnover * COST * 2 + (SELLFEE if turnover > 0 else 0)
            costs += c; orders += 2
            net = total - c
            up = (net / 2) / PUT[d]; us = (net / 2) / SPY[d]
            trades.append([d, "REBALANCE to 50/50", round(total, 2), round(c, 2)])
        curve.append((d, up * PUT[d] + us * SPY[d]))
    return curve, round(costs, 2), orders, trades


def main():
    out = {"family": "options-index", "program": "v13-best-rules",
           "form": "MY RULES: 50% CBOE PUT + 50% SPY TR, annual rebalance (first trading day of year), no floor/gate/vol-scaling, costs 0.10%/side + $0.01/sell on traded dollars",
           "published_best": "PUT index alone (native). BXM deleted per spec.",
           "champions_VM": CHAMP, "spy_refs": SPYREF, "roads": {}}
    # validation gate
    val = {}
    for road in ("LONG", "DECADE"):
        s, e = ROADS[road]
        val[f"PUT_{road}"] = pure(PUT, s, e)[0]
        val[f"BXM_{road}"] = pure(BXM, s, e)[0]
        val[f"SPY_{road}"] = pure(SPY, s, e)[0]
    out["validation_gross_replay"] = val
    print("VALIDATION:", json.dumps(val))

    for road, (s, e) in ROADS.items():
        curve, costs, orders, trades = run_blend(s, e)
        final = round(curve[-1][1], 2)
        ds = dist_stats(curve)
        # reference arms, net where applicable: pure PUT gross (settled form)
        put_final, _ = pure(PUT, s, e)
        spy_final, _ = pure(SPY, s, e)
        # placebos: 20 seeds, random rebalance day within year
        pfin = []
        for seed in range(1, 21):
            pc, _, _, _ = run_blend(s, e, seed=seed)
            pfin.append(round(pc[-1][1], 2))
        pfin_sorted = sorted(pfin)
        out["roads"][road] = {
            "final": final, "max_dd_pct": ds["max_dd_pct"], "costs": costs,
            "orders": orders, "trades": trades,
            "distribution": ds,
            "pure_PUT_gross_final": put_final, "pure_SPY_gross_final": spy_final,
            "champion_VM": CHAMP[road], "spy_ref": SPYREF[road],
            "placebo_rebalance_timing_20seeds": {
                "finals": pfin, "median": round(statistics.median(pfin), 2),
                "min": pfin_sorted[0], "max": pfin_sorted[-1],
                "frozen_final_rank": sum(1 for v in pfin if v <= final) + 1},
            "equity_curve": [[d, round(v, 2)] for d, v in curve]}
        print(f"{road}: blend ${final} (DD {ds['max_dd_pct']}%) | PUT gross ${put_final} | SPY gross ${spy_final} | champ ${CHAMP[road]} | placebo median ${statistics.median(pfin):.2f}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote results.json")


if __name__ == "__main__":
    main()
