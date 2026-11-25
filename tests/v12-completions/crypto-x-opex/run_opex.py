#!/usr/bin/env python3
"""crypto-x-opex: N-4 OpEx pinning-release translated to Deribit monthly expiry.
Frozen spec: CONSTRUCTION-SPEC.md. Shared cache READ-ONLY.
"""
import json, math, random, statistics
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CACHE = Path.home() / "workspace/stock-app/backtests/v4/crypto-basket-pit-data"
COST = 0.006
END = date(2026, 11, 20)

def load(sym):
    rows = json.load(open(CACHE / f"y_{sym}-USD.json"))
    rows = [r for r in rows if r["c"] and r["c"] > 0]
    rows.sort(key=lambda r: r["d"])
    return rows

def last_friday(y, m):
    if m == 12: d = date(y, 12, 31)
    else: d = date(y, m + 1, 1) - timedelta(days=1)
    while d.weekday() != 4: d -= timedelta(days=1)
    return d

def events_for(rows, start, end, pseudo_seed=None):
    """Return list of event dicts for months overlapping [start,end].
    Real: E = last Friday. Pseudo: seeded random day of month."""
    idx = {r["d"]: i for i, r in enumerate(rows)}
    dates = [date.fromisoformat(r["d"]) for r in rows]
    rng = random.Random(pseudo_seed) if pseudo_seed is not None else None
    evs = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        if pseudo_seed is None:
            E = last_friday(y, m)
        else:
            import calendar
            nd = calendar.monthrange(y, m)[1]
            E = date(y, m, rng.randint(1, nd))
        if start <= E <= end and E.isoformat() in idx:
            p = idx[E.isoformat()]
            if p - 61 >= 0 and p + 5 < len(rows) and dates[p + 5] <= end:
                closes = [r["c"] for r in rows]
                rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
                # return on day i (i>=1) is rets[i-1]
                A_days = [p - 4, p - 3, p - 2, p - 1]          # returns ending p-1
                A = sum(abs(rets[d - 1]) for d in A_days) / 4
                B = sum(abs(rets[d - 1]) for d in range(p - 60, p)) / 60
                cr = A / B if B > 0 else None
                trend = closes[p - 1] / closes[p - 10] - 1
                elig = cr is not None and cr <= 0.70 and trend > 0
                evs.append(dict(E=E.isoformat(), p=p, cr=cr, trend=trend,
                                eligible=elig,
                                gross=(closes[p + 5] / closes[p] - 1) if elig else None,
                                gross_all=closes[p + 5] / closes[p] - 1))
        m += 1
        if m == 13: y, m = y + 1, 1
    return evs

def run(rows, start, end, cost=COST, floor=False, pseudo_seed=None):
    """Daily equity curve over [start,end]; cash outside eligible windows."""
    idx = {r["d"]: i for i, r in enumerate(rows)}
    evs = events_for(rows, start, end, pseudo_seed)
    by_entry = {e["p"]: e for e in evs if e["eligible"]}
    cash = 100.0; units = 0.0; in_pos = False; exit_p = None
    curve = []
    i0 = idx[start.isoformat()]; i1 = idx[end.isoformat()]
    halted = False
    for i in range(i0, i1 + 1):
        r = rows[i]
        if in_pos and i == exit_p:  # sell at close
            cash = units * r["c"] * (1 - cost); units = 0.0; in_pos = False
        if not in_pos and i in by_entry and not halted:
            units = cash * (1 - cost) / r["c"]; cash = 0.0; in_pos = True
            exit_p = by_entry[i]["p"] + 5
        eq = cash + units * r["c"]
        curve.append((r["d"], round(eq, 4)))
        if floor and eq <= 85.0 and not halted:
            halted = True
            if in_pos and i + 1 <= i1:
                nxt = rows[i + 1]
                cash = units * nxt["o"] * (1 - cost); units = 0.0; in_pos = False
                curve.append((nxt["d"], round(cash, 4)))
            # run ends: freeze remaining curve at final cash
            last = curve[-1][1]
            for j in range(len(curve), i1 - i0 + 1):
                curve.append((rows[i0 + j]["d"], last))
            break
    final = curve[-1][1]
    # max drawdown
    peak = -1; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return dict(final=final, max_dd=mdd, curve=curve, events=evs, halted=halted)

def hold(rows, start, end, cost=COST):
    idx = {r["d"]: i for i, r in enumerate(rows)}
    i0, i1 = idx[start.isoformat()], idx[end.isoformat()]
    units = 100 * (1 - cost) / rows[i0]["c"]
    curve = [(rows[i]["d"], round(units * rows[i]["c"], 4)) for i in range(i0, i1 + 1)]
    return dict(final=round(units * rows[i1]["c"] * (1 - cost), 4), curve=curve)

def period_dist(curve):
    """Monthly distribution at native (monthly event) tempo from equity curve."""
    months = {}
    for d, v in curve: months.setdefault(d[:7], []).append((d, v))
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        v = months[k][-1][1]
        rets.append(v / prev - 1); prev = v
    n = len(rets); prof = sum(1 for r in rets if r > 0)
    med = statistics.median(rets) if rets else 0
    # longest losing run
    ll = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; ll = max(ll, cur)  # strictly losing months only; flat cash months break the run
    # longest stretch between new highs (months)
    peak = -1; since = 0; longest = 0
    vals = [100.0]
    for k in keys: vals.append(months[k][-1][1])
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return dict(n_months=n, pct_profitable=round(100 * prof / n, 1) if n else 0,
                median_pct=round(med * 100, 3), best_pct=round(max(rets) * 100, 2) if rets else 0,
                worst_pct=round(min(rets) * 100, 2) if rets else 0,
                longest_losing_run_months=ll, longest_stretch_between_highs_months=longest,
                mean_pct_secondary=round(statistics.mean(rets) * 100, 3) if rets else 0)

WINDOWS = {
    "BTC": dict(start_full=date(2018, 1, 1)),
    "ETH": dict(start_full=date(2019, 4, 1)),
}
out = {"family": "novel-x4-opex-release / crypto-x-opex", "constructed": True,
       "cost_primary_per_side": COST, "coins": {}}
btc_rows = load("BTC")
for sym in ["BTC", "ETH"]:
    rows = load(sym)
    idx = {r["d"]: i for i, r in enumerate(rows)}
    sf = WINDOWS[sym]["start_full"]
    wins = {"FULL": (sf, END), "DESIGN": (sf, date(2022, 12, 31)),
            "VALIDATION": (date(2023, 1, 1), END)}
    coin = {"windows": {}}
    btc_hold_cache = {}
    for wname, (ws, we) in wins.items():
        # clamp start to an existing bar on/after ws
        cand = [r["d"] for r in rows if date.fromisoformat(r["d"]) >= ws]
        ws2 = date.fromisoformat(cand[0])
        res_c = run(rows, ws2, we, floor=False)
        res_v = run(rows, ws2, we, floor=True)
        sens = {str(c): run(rows, ws2, we, cost=c, floor=False)["final"] for c in (0.004, 0.008)}
        own_hold = hold(rows, ws2, we)
        if sym == "BTC": btc_hold = own_hold
        else:
            bc = [r["d"] for r in btc_rows if date.fromisoformat(r["d"]) >= ws]
            btc_hold = hold(btc_rows, date.fromisoformat(bc[0]), we)
        evs = res_c["events"]; elig = [e for e in evs if e["eligible"]]
        annex = dict(events=len(evs), eligible=len(elig),
                     eligible_gross_mean_pct=round(100 * statistics.mean([e["gross"] for e in elig]), 3) if elig else None,
                     eligible_gross_median_pct=round(100 * statistics.median([e["gross"] for e in elig]), 3) if elig else None,
                     eligible_win_pct=round(100 * sum(1 for e in elig if e["gross"] > 0) / len(elig), 1) if elig else None,
                     all_events_gross_mean_pct=round(100 * statistics.mean([e["gross_all"] for e in evs]), 3) if evs else None)
        w = dict(start=ws2.isoformat(), end=we.isoformat(),
                 constructed_final=res_c["final"], constructed_max_dd=round(res_c["max_dd"], 4),
                 v9_final=res_v["final"], v9_max_dd=round(res_v["max_dd"], 4), v9_halted=res_v["halted"],
                 sens_040_final=sens["0.004"], sens_080_final=sens["0.008"],
                 btc_hold_final=btc_hold["final"], own_hold_final=own_hold["final"],
                 annex=annex,
                 monthly_distribution_constructed=period_dist(res_c["curve"]),
                 monthly_distribution_v9=period_dist(res_v["curve"]),
                 curve_constructed=res_c["curve"], curve_v9=res_v["curve"],
                 curve_btc_hold=btc_hold["curve"], curve_own_hold=own_hold["curve"],
                 events_detail=[{k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items() if k != "p"} for e in evs])
        if wname in ("FULL", "VALIDATION"):
            pls = []
            for seed in range(1, 21):
                pr = run(rows, ws2, we, floor=False, pseudo_seed=seed)
                pls.append(pr["final"])
            pls_sorted = sorted(pls)
            w["placebo"] = dict(finals=[round(x, 2) for x in pls_sorted],
                                median=round(statistics.median(pls), 2),
                                seeds_beaten=sum(1 for x in pls if res_c["final"] > x),
                                percentile=round(100 * sum(1 for x in pls if x < res_c["final"]) / 20, 1))
        coin["windows"][wname] = w
    out["coins"][sym] = coin

json.dump(out, open(HERE / "results.json", "w"), indent=1)
for sym, coin in out["coins"].items():
    for wname, w in coin["windows"].items():
        print(sym, wname, "constr", w["constructed_final"], "v9", w["v9_final"],
              "btchold", w["btc_hold_final"], "ownhold", w["own_hold_final"],
              "ev/elig", w["annex"]["events"], w["annex"]["eligible"],
              "placebo_med", w.get("placebo", {}).get("median"), "beaten", w.get("placebo", {}).get("seeds_beaten"))
print("done")
