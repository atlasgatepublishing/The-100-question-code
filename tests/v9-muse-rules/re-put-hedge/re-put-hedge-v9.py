#!/usr/bin/env python3
"""
PROTECTIVE-PUT TAIL HEDGE — Terry's AI stock app, simulation only.

Spec #2 of the 5 new-and-buildable items in
research/v7-completeness/firm-reverse-engineering.md (audit row #14:
Jane Street's documented habit of paying $50-75M a year for index puts
as firm-level catastrophe insurance). This script implements audit
spec section 4.2 EXACTLY as written. The spec is FROZEN; nothing here
improves or reinterprets it. Forced readings are stated here, before
any result (and repeated in the report):

SPEC 4.2 AS WRITTEN:
  - Instruments: the champion engine (value+momentum, promoted spec,
    unchanged) and the CBOE S&P 500 5% Protective Put Index (PPUT)
    daily series — free from CBOE index data, the same data class and
    treatment as the PUT/BXM test (the index's own methodology embeds
    its option costs; no additional option cost is charged).
  - Pots: (i) PPUT standalone, $100; (ii) 50/50 blend — half champion,
    half PPUT, rebalanced each Jan 1 at program costs on the equity
    sleeve.
  - Question (pre-registered): does paying for insurance rescue the
    pots the naked champion lost? Windows: continuous 2019-01-01 ->
    2026-11-20, validation 2023-01-01 -> 2026-11-20, the 2010-start
    long-hold window 2010-01-04 -> 2026-11-20 (the documented floor
    death, Aug 2010), and the 2020 fold start (calendar-2020 fresh
    pot, the program's fold convention).
  - Costs/floor: program standard; plain -15% floor ($85) on each
    pot's total daily value.
  - Placebo/comparison: the honest control is a 50/50 champion/SPY
    blend (insurance-by-dilution), built identically.
  - GATE (pre-registered trade-off bar): the blend is adopted only if
    (a) it survives BOTH floor-death windows (2010 start, 2020 fold)
    UNHALTED, and (b) it surrenders <=25% of the champion's validation
    final balance ($288.05 x 0.75 = $216.04 minimum). Otherwise it is
    rejected, with the premium paid reported in dollars.

FORCED READINGS (stated before results):
  FR1. Spec 4.2's own gate and its named control govern the verdict.
       The audit section-4 preamble's generic bar (beat SPY and a
       20-seed placebo distribution on validation) does not map onto
       an insurance overlay; the house 20-seed placebo for the blend
       (random champion sleeve + the same PPUT sleeve, vm-plus-trend
       method) is still run on continuous + validation and reported,
       but it does not enter the gate.
  FR2. Blend construction is the house winners-blend / vm-plus-trend
       method: each sleeve runs standalone on its $50 half with its
       internal floor disabled; the pot is the sum of the two sleeve
       close-equity curves; every January (first trading day, at the
       close, inception January excluded) the split is rebalanced to
       50/50 at the engines' cost schedule (0.10% sell + 0.10% buy on
       the transferred value + $0.01 x 5 sell orders); the plain -15%
       floor applies at the whole-pot level only; a halt liquidates
       at the next day's marked total x (1 - 0.10%) - $0.10. The
       blend function below is vm-plus-trend's blend_curves with one
       documented parameterization: a cost multiplier (1.0 reproduces
       the house arithmetic exactly) used only by the 2x-cost stress.
  FR3. The PPUT and SPY sleeves are passive replays on the champion
       book's window dates: value = $50 x level(date)/level(first
       window date), using the level on or before the date (fallback
       days counted and reported). No entry commission is charged on
       a passive sleeve and no exit commission except the blend-level
       halt charge in FR2 — the same treatment the program's CBOE
       scorecard gave published index levels. Both passive sleeves
       get identical treatment, so the PPUT-vs-SPY control comparison
       is symmetric.
  FR4. PPUT standalone pot: $100 replayed on the index; the plain
       floor is checked on each close; a breach ends the pot at the
       breaching close (an index has no next open — the PUT/BXM
       scorecard's convention). The no-floor index growth is also
       reported.
  FR5. "Premium paid in dollars" is reported three ways, all defined
       here: (i) gate surrender on validation = champion parent final
       ($288.05) - PPUT blend final; (ii) the same on continuous
       ($544.47 base); (iii) raw leg drag per window = SPY buy-hold
       mark ($100, no costs) - PPUT no-floor replay ($100) — what the
       insurance leg itself cost against the index it insures.
  FR6. PPUT era disclosure: per CBOE's own research paper
       (Bondarenko 2019, Exhibit 1), PPUT was LAUNCHED 2015-06-30
       with price history beginning 1986-06-30. Values before
       2015-06-30 are therefore CBOE back-calculations under the
       published methodology (S&P 500 total return + a monthly 5%
       OTM SPX put rolled on the 3rd Friday), not a live-traded
       index. The 2010 window's PPUT leg is back-calculated for
       2010-01-04 -> 2015-06-29 and live thereafter; continuous,
       validation, and the 2020 fold are entirely live-era. The gate
       is evaluated as pre-registered; the report states separately
       what the live-era windows alone show. PPUT levels are used
       exactly as CBOE publishes them — no approximation of the put
       leg is made anywhere in this test.
  FR7. 2x-cost stress (audit section-4 preamble): the champion sleeve
       is re-run with every cost constant doubled, via a copy of the
       engine's run_pot produced by mechanical source replacement
       (0.001 -> 0.002 in the four cost sites, +0.01 -> +0.02 in the
       three fee sites, cash/1.001 -> cash/1.002 in the buy cap;
       replacement counts asserted). The copy is verified to
       reproduce the verbatim engine at 1x to the cent (final and
       full curve) before any 2x number is taken. January transfer
       and halt-liquidation charges are doubled through FR2's cost
       multiplier. The PPUT leg carries no added cost at any
       multiplier (its costs are inside the index, per the spec).

INTEGRITY CHECKS (abort on failure, before any hedged number):
  - Champion parent, honest book: continuous $544.47, validation
    $288.05, 2020 fold $83.62 (published fold final); SPY net
    $313.62 / $187.77 on continuous / validation.
  - Champion parent, 2010 book: final $85.34, halted 2010-08-26
    (long-hold published); SPY net $822.94.
  - 2010 universe rebuilt by the long-hold module's own ranking must
    equal universe-build-long.json exactly.

Data: champion caches read-only (v4/data, v4/value-momentum-honest-data,
v7/long-hold/data); PPUT_History.csv from the CBOE free CDN
(cdn.cboe.com/api/global/us_indices/daily_prices/PPUT_History.csv),
downloaded 2026-11-21, stored alongside this script.
"""

import csv
import importlib.util
import inspect
import json
import math
import os
import random
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
LH_DIR = os.path.join(HERE, "..", "long-hold")
END = "2026-11-20"
POT, FLOOR, HALF = 100.0, 85.0, 50.0
PLACEBO_SEEDS = list(range(1, 21))
COVID = ("2020-02-01", "2020-04-30")
CHAMPION_VALIDATION_PUBLISHED = 288.05
GATE_B_MIN = round(CHAMPION_VALIDATION_PUBLISHED * 0.75, 2)  # $216.04


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The long-hold module imports the champion engine (v4 plainfloor) as
# its E and points E.DATA at its own cache. Use that single engine
# instance for everything.
LH = _load("long_hold", os.path.join(LH_DIR, "long-hold.py"))
E = LH.E
HONEST_UNIVERSE = list(E.UNIVERSE)
HONEST_DATA = os.path.join(V4, "value-momentum-honest-data")
LH_DATA = LH.MYDATA


# --------------------------------------------------------------------------
# PPUT data
# --------------------------------------------------------------------------
PPUT_URL = ("https://cdn.cboe.com/api/global/us_indices/daily_prices/"
            "PPUT_History.csv")
PPUT_PATH = os.path.join(HERE, "PPUT_History.csv")


def load_pput():
    if not (os.path.exists(PPUT_PATH) and os.path.getsize(PPUT_PATH) > 100):
        req = urllib.request.Request(PPUT_URL,
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            blob = r.read()
        with open(PPUT_PATH, "wb") as f:
            f.write(blob)
    rows = []
    with open(PPUT_PATH) as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["DATE"], "%m/%d/%Y").strftime("%Y-%m-%d")
            rows.append((d, float(r["PPUT"])))
    rows.sort()
    return rows


def level_on_or_before(rows, dates_sorted, d):
    """(level, exact?) — last published level on or before date d."""
    lo, hi = 0, len(dates_sorted) - 1
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates_sorted[mid] <= d:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if ans is None:
        return None, False
    return rows[ans][1], dates_sorted[ans] == d


# --------------------------------------------------------------------------
# Reporting helpers (no trading logic) — copied from vm-plus-trend
# --------------------------------------------------------------------------
def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst


def per_year(curve, start_val):
    out = {}
    prev = float(start_val)
    years = sorted({d[:4] for d, _ in curve})
    for y in years:
        pts = [e for d, e in curve if d[:4] == y]
        if not pts:
            continue
        out[y] = pts[-1] / prev - 1.0
        prev = pts[-1]
    return out


def monthly_returns(curve):
    month_end = {}
    for d, eq in curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    return {b: month_end[b] / month_end[a] - 1.0
            for a, b in zip(keys, keys[1:])}


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return float("nan")
    return cov / math.sqrt(vx * vy)


def cagr(final, start, sd, ed):
    yrs = (datetime.strptime(ed, "%Y-%m-%d")
           - datetime.strptime(sd, "%Y-%m-%d")).days / 365.25
    return (final / start) ** (1.0 / yrs) - 1.0


def min_close_in(curve, sd, ed):
    pts = [(d, e) for d, e in curve if sd <= d <= ed]
    if not pts:
        return None, None
    d, e = min(pts, key=lambda p: p[1])
    return e, d


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    i = q * (len(sorted_vals) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - i) + sorted_vals[hi] * (i - lo)


def curve_stats(curve, start_val=POT):
    worst_v, worst_d = min((e, d) for d, e in curve)
    return {"final_mark": round(curve[-1][1], 2),
            "max_dd_pct": round(max_dd(curve) * 100, 2),
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "margin_above_floor": round(worst_v - FLOOR, 2)}


# --------------------------------------------------------------------------
# The blend — vm-plus-trend's blend_curves, with the FR2 cost multiplier
# (cost_mult=1.0 reproduces the house arithmetic exactly).
# --------------------------------------------------------------------------
def blend_curves(curveA, curveB, pot0=POT, floor=FLOOR, rebalance=True,
                 cost_mult=1.0):
    A = dict(curveA)
    B = dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates = set()
    seen_jan = set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)

    scaleA = scaleB = 1.0
    lastA = lastB = None
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        va = scaleA * lastA
        vb = scaleB * lastB
        tot = va + vb
        if rebalance and d in jan_dates:
            transfer = abs(va - vb) / 2.0
            cost = (transfer * 0.002 + 0.05) * cost_mult
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            rebalances.append({"date": d, "sleeveA_before": round(va, 2),
                               "sleeveB_before": round(vb, 2),
                               "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                na = A.get(nd, lastA)
                nb = B.get(nd, lastB)
                nxt = scaleA * na + scaleB * nb
                final = nxt * (1 - 0.001 * cost_mult) - 0.10 * cost_mult
            else:
                final = tot * (1 - 0.001 * cost_mult) - 0.10 * cost_mult
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Passive sleeves and the standalone index pot (FR3 / FR4)
# --------------------------------------------------------------------------
def index_sleeve_curve(pput_rows, pput_dates, dates, cash=HALF):
    base, exact = level_on_or_before(pput_rows, pput_dates, dates[0])
    assert base is not None
    curve = []
    fallbacks = 0
    for d in dates:
        lev, exact = level_on_or_before(pput_rows, pput_dates, d)
        if not exact:
            fallbacks += 1
        curve.append((d, cash * lev / base))
    return curve, fallbacks


def spy_sleeve_curve(pb, dates, cash=HALF):
    base = pb.close_on_or_before("SPY", dates[0])
    return [(d, cash * pb.close_on_or_before("SPY", d) / base)
            for d in dates]


def standalone_index_pot(pput_rows, pput_dates, dates, cash=POT,
                         floor=FLOOR):
    base, _ = level_on_or_before(pput_rows, pput_dates, dates[0])
    curve = [(d, cash * level_on_or_before(pput_rows, pput_dates, d)[0]
              / base) for d in dates]
    halted, final = None, curve[-1][1]
    for i, (d, v) in enumerate(curve):
        if v <= floor and i < len(curve) - 1:
            halted, final = d, v
            curve = curve[:i + 1]
            break
    st = curve_stats(curve, cash)
    return {"final": round(final, 2), "halted": halted,
            "nofloor_final": round(cash * level_on_or_before(
                pput_rows, pput_dates, dates[-1])[0] / base, 2),
            "max_dd_pct": st["max_dd_pct"],
            "worst_close": st["worst_close"],
            "worst_close_date": st["worst_close_date"],
            "curve": curve}


# --------------------------------------------------------------------------
# 2x-cost sleeve: mechanical source transform of the engine's run_pot
# (FR7). Verified at 1x against the verbatim engine before use.
# --------------------------------------------------------------------------
def make_run_pot_x(mult):
    src = inspect.getsource(E.run_pot)
    if mult != 1.0:
        n1 = src.count("* 0.001")
        n2 = src.count("+ 0.01")
        n3 = src.count("cash / 1.001")
        assert (n1, n2, n3) == (4, 3, 1), \
            f"cost-site counts changed: {(n1, n2, n3)} — stress aborted"
        src = src.replace("* 0.001", "* 0.002")
        src = src.replace("+ 0.01", "+ 0.02")
        src = src.replace("cash / 1.001", "cash / 1.002")
    ns = dict(E.__dict__)
    exec(src, ns)
    return ns["run_pot"]


# --------------------------------------------------------------------------
# Book builders
# --------------------------------------------------------------------------
def build_vm_book():
    """The parent study's own assembly (copied from vm-plus-trend)."""
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributable"
                         "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei",
                         "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        time.sleep(0.05)
    bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def build_2010_book():
    """Rebuild the long-hold 2010 book with the long-hold module's own
    loaders/ranking; verify the universe against the published build."""
    facts_by, payload_by, failures = LH.load_pool_data()
    spy_bars = LH.bars_from_payload(payload_by["SPY"])
    spy_dates = [b["d"] for b in spy_bars]
    chains_by = {t: (LH.equity_chain(f), LH.shares_chain(f))
                 for t, f in facts_by.items()}
    bars_cache = {}
    c = LH.rank_and_score(chains_by, payload_by, bars_cache, spy_dates,
                          "2010-01-04")
    published = json.load(open(os.path.join(
        LH_DIR, "universe-build-long.json")))["universe"]
    assert c["top30"] == published, \
        f"2010 universe mismatch:\n{c['top30']}\nvs\n{published}"
    print(f"CHECK 2010 universe rebuilt == published ({len(published)} "
          f"names, scorable {c['n_scorable']}/30)", flush=True)
    universe = c["top30"]
    eq = {t: chains_by[t][0] for t in universe}
    so = {t: chains_by[t][1] for t in universe}
    bars = {t: bars_cache[t] for t in universe}
    bars["SPY"] = spy_bars
    return LH.FastPriceBook(bars), eq, so, universe


# --------------------------------------------------------------------------
# One window, all pots
# --------------------------------------------------------------------------
def run_window(name, pb, eq, so, sd, ed, pput_rows, pput_dates,
               run_placebo=False):
    print(f"\n== {name} {sd} -> {ed} ==", flush=True)
    dates = [d for d in pb.dates if sd <= d <= ed]

    parent = E.run_pot(pb, eq, so, sd, ed, POT, FLOOR, [], quiet=True)
    spy, _ = E.spy_net(pb, sd, ed, POT)
    sleeve = E.run_pot(pb, eq, so, sd, ed, HALF, 0.0, [], quiet=True)
    pput_curve, fb = index_sleeve_curve(pput_rows, pput_dates, dates)
    spy_curve = spy_sleeve_curve(pb, dates)
    pput_pot = standalone_index_pot(pput_rows, pput_dates, dates)

    pot_pput, info_pput = blend_curves(sleeve["curve"], pput_curve)
    pot_spy, info_spy = blend_curves(sleeve["curve"], spy_curve)

    # 2x-cost stress on the PPUT blend (FR7)
    runx2 = make_run_pot_x(2.0)
    sleeve2x = runx2(pb, eq, so, sd, ed, HALF, 0.0, [], quiet=True)
    _, info_pput_2x = blend_curves(sleeve2x["curve"], pput_curve,
                                   cost_mult=2.0)

    corr_pput = pearson(
        [monthly_returns(sleeve["curve"])[m]
         for m in sorted(set(monthly_returns(sleeve["curve"]))
                         & set(monthly_returns(pput_curve)))],
        [monthly_returns(pput_curve)[m]
         for m in sorted(set(monthly_returns(sleeve["curve"]))
                         & set(monthly_returns(pput_curve)))])
    corr_spy = pearson(
        [monthly_returns(sleeve["curve"])[m]
         for m in sorted(set(monthly_returns(sleeve["curve"]))
                         & set(monthly_returns(spy_curve)))],
        [monthly_returns(spy_curve)[m]
         for m in sorted(set(monthly_returns(sleeve["curve"]))
                         & set(monthly_returns(spy_curve)))])

    res = {
        "window": name, "start": sd, "end": ed,
        "champion_parent": {
            "final": round(parent["final"], 2),
            "final_mark": round(parent["curve"][-1][1], 2),
            "halted": parent["halted"], "halt_info": parent["halt_info"],
            "costs": round(parent["costs"], 2),
            "orders": len(parent["trades"]),
            **curve_stats(parent["curve"])},
        "spy_net_final": round(spy, 2),
        "spy_mark_final": round(spy_curve[-1][1] * 2, 2),
        "pput_standalone": {k: v for k, v in pput_pot.items()
                            if k != "curve"},
        "pput_sleeve_fallback_days": fb,
        "champion_sleeve_50_final_mark": round(sleeve["curve"][-1][1], 2),
        "champion_sleeve_50_costs": round(sleeve["costs"], 2),
        "pput_sleeve_50_final_mark": round(pput_curve[-1][1], 2),
        "spy_sleeve_50_final_mark": round(spy_curve[-1][1], 2),
        "sleeve_corr_monthly_champion_pput": round(corr_pput, 3),
        "sleeve_corr_monthly_champion_spy": round(corr_spy, 3),
        "pput_blend": {
            "final": round(info_pput["final"], 2),
            "ret_pct": round((info_pput["final"] / POT - 1) * 100, 2),
            "cagr_pct": round(cagr(info_pput["final"], POT,
                                   pot_pput[0][0], pot_pput[-1][0])
                              * 100, 2),
            "halt": info_pput["halt"],
            "transfer_costs": round(info_pput["transfer_costs"], 2),
            "rebalances": info_pput["rebalances"],
            **curve_stats(pot_pput)},
        "spy_blend": {
            "final": round(info_spy["final"], 2),
            "ret_pct": round((info_spy["final"] / POT - 1) * 100, 2),
            "halt": info_spy["halt"],
            "transfer_costs": round(info_spy["transfer_costs"], 2),
            **curve_stats(pot_spy)},
        "pput_blend_2x_costs": {
            "final": round(info_pput_2x["final"], 2),
            "halt": info_pput_2x["halt"],
            "transfer_costs": round(info_pput_2x["transfer_costs"], 2),
            "sleeve_costs": round(sleeve2x["costs"], 2)},
        "leg_drag_vs_spy_mark": round(
            spy_curve[-1][1] * 2 - pput_pot["nofloor_final"], 2),
        "per_year": {
            "pput_blend": {y: round(v * 100, 2) for y, v in
                           per_year(pot_pput, POT).items()},
            "spy_blend": {y: round(v * 100, 2) for y, v in
                          per_year(pot_spy, POT).items()},
            "champion_parent": {y: round(v * 100, 2) for y, v in
                                per_year(parent["curve"], POT).items()},
            "pput_standalone": {y: round(v * 100, 2) for y, v in
                                per_year(pput_pot["curve"], POT).items()},
        },
    }
    cw, cwd = min_close_in(pot_pput, *COVID)
    if cw is not None:
        res["pput_blend"]["covid_worst_close"] = round(cw, 2)
        res["pput_blend"]["covid_worst_date"] = cwd
        vw, vwd = min_close_in(parent["curve"], *COVID)
        if vw is not None:  # a floored parent halted before 2020 has none
            res["champion_parent"]["covid_worst_close"] = round(vw, 2)
            res["champion_parent"]["covid_worst_date"] = vwd

    print(f"PARENT champion ${parent['final']:,.2f} halt={parent['halted']}"
          f" | SPY net ${spy:,.2f} | PPUT alone "
          f"${pput_pot['final']:,.2f} halt={pput_pot['halted']}", flush=True)
    print(f"BLEND-PPUT ${info_pput['final']:,.2f} halt={info_pput['halt']} "
          f"maxDD={info_pput['max_dd']*100:.2f}% | BLEND-SPY "
          f"${info_spy['final']:,.2f} halt={info_spy['halt']} | 2x stress "
          f"${info_pput_2x['final']:,.2f} halt={info_pput_2x['halt']}",
          flush=True)

    if run_placebo:
        print(f"placebo ({name})...", flush=True)
        finals, halts, rows = [], 0, []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            ps = E.run_pot(pb, eq, so, sd, ed, HALF, 0.0, [],
                           placebo_rng=rng, quiet=True)
            _, pinfo = blend_curves(ps["curve"], pput_curve)
            finals.append(pinfo["final"])
            if pinfo["halt"]:
                halts += 1
            rows.append({"seed": seed, "final": round(pinfo["final"], 2),
                         "halt": pinfo["halt"]})
            print(f"  placebo seed {seed:2d}: ${pinfo['final']:,.2f} "
                  f"halt={pinfo['halt']}", flush=True)
        srt = sorted(finals)
        ranked = info_pput["final"]
        below = sum(1 for f in finals if f < ranked)
        ties = sum(1 for f in finals if f == ranked)
        res["placebo_pput_blend"] = {
            "median": round(pct(srt, 0.50), 2),
            "q1": round(pct(srt, 0.25), 2), "q3": round(pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": halts,
            "ranked_final": round(ranked, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties)
                                       / len(finals), 1),
            "seeds_beaten": below, "rows": rows}
    return res


def main_original():
    out = {"spec": "Audit 4.2 — protective-put tail hedge (Jane Street "
                   "insurance via CBOE PPUT): PPUT standalone $100; "
                   "50/50 champion/PPUT blend, January rebalances, "
                   "plain -15% pot floor; control = 50/50 champion/SPY "
                   "blend; gate = survive 2010 + 2020-fold unhalted AND "
                   "validation surrender <=25% of $288.05",
           "pput_source": PPUT_URL}

    pput_rows = load_pput()
    pput_dates = [d for d, _ in pput_rows]
    out["pput_data"] = {
        "rows": len(pput_rows), "first": pput_rows[0][0],
        "last": pput_rows[-1][0],
        "live_from": "2015-06-30 (CBOE/Bondarenko 2019, Exhibit 1); "
                     "earlier values are CBOE back-calculations"}
    print(f"PPUT: {len(pput_rows)} rows {pput_rows[0][0]} -> "
          f"{pput_rows[-1][0]}", flush=True)

    # ---------------- honest book: integrity first --------------------
    E.DATA = HONEST_DATA
    E.UNIVERSE = list(HONEST_UNIVERSE)
    print("loading honest value+momentum book (cache)...", flush=True)
    pb, eq, so = build_vm_book()

    checks = {}
    for tag, (sd, ed), expect in (
            ("continuous", ("2019-01-01", END), 544.47),
            ("validation", ("2023-01-01", END), 288.05),
            ("fold2020", ("2020-01-01", "2020-12-31"), 83.62)):
        r = E.run_pot(pb, eq, so, sd, ed, POT, FLOOR, [], quiet=True)
        ok = abs(r["final"] - expect) < 0.05
        checks[f"champion_{tag}"] = {"final": round(r["final"], 2),
                                     "expected": expect, "match": ok}
        print(f"CHECK champion {tag}: ${r['final']:,.2f} "
              f"(published ${expect:,.2f}) match={ok}", flush=True)
        assert ok, f"champion {tag} reproduction failed"
    for tag, (sd, ed), expect in (
            ("continuous", ("2019-01-01", END), 313.62),
            ("validation", ("2023-01-01", END), 187.77)):
        s, _ = E.spy_net(pb, sd, ed, POT)
        ok = abs(s - expect) < 0.05
        checks[f"spy_{tag}"] = {"final": round(s, 2), "expected": expect,
                                "match": ok}
        print(f"CHECK spy {tag}: ${s:,.2f} (published ${expect:,.2f}) "
              f"match={ok}", flush=True)
        assert ok, f"spy {tag} reproduction failed"

    # FR7 verification: the 1x source copy must equal the verbatim engine
    runx1 = make_run_pot_x(1.0)
    a = E.run_pot(pb, eq, so, "2019-01-01", END, HALF, 0.0, [], quiet=True)
    b = runx1(pb, eq, so, "2019-01-01", END, HALF, 0.0, [], quiet=True)
    same = (abs(a["final"] - b["final"]) < 1e-9
            and len(a["curve"]) == len(b["curve"])
            and all(abs(x[1] - y[1]) < 1e-9
                    for x, y in zip(a["curve"], b["curve"])))
    checks["costx_1x_copy_identical"] = same
    print(f"CHECK run_pot 1x source copy identical to engine: {same}",
          flush=True)
    assert same, "cost-transform copy does not reproduce the engine"

    out["integrity_checks"] = checks

    # ---------------- honest-book windows -----------------------------
    out["continuous"] = run_window("continuous", pb, eq, so,
                                    "2019-01-01", END,
                                    pput_rows, pput_dates,
                                    run_placebo=True)
    out["validation"] = run_window("validation", pb, eq, so,
                                   "2023-01-01", END,
                                   pput_rows, pput_dates,
                                   run_placebo=True)
    out["fold2020"] = run_window("fold2020", pb, eq, so,
                                 "2020-01-01", "2020-12-31",
                                 pput_rows, pput_dates)

    # ---------------- 2010 book ---------------------------------------
    E.DATA = LH_DATA
    print("\nloading 2010 long-hold book (cache)...", flush=True)
    pb10, eq10, so10, uni10 = build_2010_book()
    E.UNIVERSE = list(uni10)
    r = E.run_pot(pb10, eq10, so10, "2010-01-04", END, POT, FLOOR, [],
                  quiet=True)
    ok = abs(r["final"] - 85.34) < 0.05 and r["halted"] == "2010-08-26"
    checks["champion_long2010"] = {"final": round(r["final"], 2),
                                    "expected": 85.34,
                                    "halted": r["halted"],
                                    "expected_halt": "2010-08-26",
                                    "match": ok}
    print(f"CHECK champion 2010: ${r['final']:,.2f} halted={r['halted']} "
          f"(published $85.34 / 2010-08-26) match={ok}", flush=True)
    assert ok, "2010 champion reproduction failed"
    s, _ = E.spy_net(pb10, "2010-01-04", END, POT)
    ok = abs(s - 822.94) < 0.10
    checks["spy_long2010"] = {"final": round(s, 2), "expected": 822.94,
                              "match": ok}
    print(f"CHECK spy 2010: ${s:,.2f} (published $822.94) match={ok}",
          flush=True)
    assert ok, "2010 spy reproduction failed"
    out["integrity_checks"] = checks

    out["long2010"] = run_window("long2010", pb10, eq10, so10,
                                 "2010-01-04", END,
                                 pput_rows, pput_dates)

    # ---------------- the pre-registered gate --------------------------
    val_blend = out["validation"]["pput_blend"]["final"]
    surrender_val = round(CHAMPION_VALIDATION_PUBLISHED - val_blend, 2)
    surrender_val_pct = round(surrender_val
                              / CHAMPION_VALIDATION_PUBLISHED * 100, 2)
    cont_blend = out["continuous"]["pput_blend"]["final"]
    gate_a = (out["long2010"]["pput_blend"]["halt"] is None
              and out["fold2020"]["pput_blend"]["halt"] is None)
    gate_b = val_blend >= GATE_B_MIN
    out["gate"] = {
        "a_survives_2010_unhalted":
            out["long2010"]["pput_blend"]["halt"] is None,
        "a_survives_fold2020_unhalted":
            out["fold2020"]["pput_blend"]["halt"] is None,
        "a_pass": gate_a,
        "b_validation_blend_final": val_blend,
        "b_minimum_required": GATE_B_MIN,
        "b_surrender_dollars": surrender_val,
        "b_surrender_pct_of_champion": surrender_val_pct,
        "b_pass": gate_b,
        "premium_continuous_dollars": round(544.47 - cont_blend, 2),
        "premium_continuous_pct_of_champion":
            round((544.47 - cont_blend) / 544.47 * 100, 2),
        "adopted": bool(gate_a and gate_b)}
    print(f"\nGATE: (a) survival 2010={out['gate']['a_survives_2010_unhalted']}"
          f" fold2020={out['gate']['a_survives_fold2020_unhalted']} "
          f"-> {gate_a}; (b) validation blend ${val_blend:,.2f} vs min "
          f"${GATE_B_MIN:,.2f} (surrender ${surrender_val:,.2f} = "
          f"{surrender_val_pct:.2f}%) -> {gate_b}; "
          f"ADOPTED={out['gate']['adopted']}", flush=True)

    with open(os.path.join(HERE, "re-put-hedge-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\nsaved re-put-hedge-results.json", flush=True)




# ---------------------------------------------------------------------------
# V9 PROTECTION MODULE (the ONLY change vs the original script)
# fold2020 only: episode 1 is the original blend run; on its halt the pot
# liquidates exactly as blend_curves does, sits out 90 calendar days, and
# restarts 50/50 (champion sleeve + passive sleeve) at the champion
# sleeve's next quarterly selection date, with floor2 = 85% of the
# restart cash. A second halt ends the run (blend_curves liquidation).
# ---------------------------------------------------------------------------
def v9_blend_episode2(pb, eq, so, ed, passive_kind, pput_rows, pput_dates,
                      ep1_info):
    import datetime as _dt
    restart_cash = ep1_info["final"]
    halt_d = _dt.date.fromisoformat(ep1_info["halt"])
    sitout_end = (halt_d + _dt.timedelta(days=90)).isoformat()
    sel = E.quarter_selection_dates(pb, sitout_end, ed)
    restart_start = sel[0]
    dates = [d for d in pb.dates if restart_start <= d <= ed]
    sleeve = E.run_pot(pb, eq, so, restart_start, ed, restart_cash / 2.0,
                       0.0, [], quiet=True)
    if passive_kind == "pput":
        passive, _fb = index_sleeve_curve(pput_rows, pput_dates, dates,
                                          cash=restart_cash / 2.0)
    else:
        passive = spy_sleeve_curve(pb, dates, cash=restart_cash / 2.0)
    floor2 = 0.85 * restart_cash
    curve2, info2 = blend_curves(sleeve["curve"], passive,
                                 pot0=restart_cash, floor=floor2)
    return {"restart_cash": round(restart_cash, 4),
            "halt_date_ep1": ep1_info["halt"],
            "sitout_end": sitout_end,
            "restart_start_next_quarterly_selection": restart_start,
            "floor2": round(floor2, 4),
            "final": round(info2["final"], 2),
            "halt2": info2["halt"],
            "transfer_costs": round(info2["transfer_costs"], 2),
            "worst_close_ep2": round(min(v for _, v in curve2), 2)}


def v9_main():
    t0 = time.time()
    pput_rows = load_pput()
    pput_dates = [d for d, _ in pput_rows]
    E.DATA = HONEST_DATA
    E.UNIVERSE = list(HONEST_UNIVERSE)
    print("loading honest value+momentum book (cache)...", flush=True)
    pb, eq, so = build_vm_book()
    sd, ed = "2020-01-01", "2020-12-31"
    parent = E.run_pot(pb, eq, so, sd, ed, POT, FLOOR, [], quiet=True)
    ok = abs(parent["final"] - 83.62) < 0.05
    print(f"CHECK champion fold2020 parent: ${parent['final']:,.2f} "
          f"(published $83.62) match={ok}", flush=True)
    assert ok
    dates = [d for d in pb.dates if sd <= d <= ed]
    sleeve = E.run_pot(pb, eq, so, sd, ed, HALF, 0.0, [], quiet=True)
    pput_curve, _fb = index_sleeve_curve(pput_rows, pput_dates, dates)
    spy_curve = spy_sleeve_curve(pb, dates)
    pput_pot = standalone_index_pot(pput_rows, pput_dates, dates)
    print(f"PPUT standalone fold2020: ${pput_pot['final']} "
          f"halted={pput_pot['halted']} worst={pput_pot['worst_close']}",
          flush=True)
    assert pput_pot["halted"] is None
    pot_pput, info_pput = blend_curves(sleeve["curve"], pput_curve)
    pot_spy, info_spy = blend_curves(sleeve["curve"], spy_curve)
    print(f"EP1 PPUT blend ${info_pput['final']:,.4f} halt={info_pput['halt']}"
          f" | SPY blend ${info_spy['final']:,.4f} halt={info_spy['halt']}",
          flush=True)
    assert abs(info_pput["final"] - 78.98) < 0.05 \
        and info_pput["halt"] == "2020-03-20"
    assert abs(info_spy["final"] - 86.83) < 0.05 \
        and info_spy["halt"] == "2020-03-09"
    ep2_pput = v9_blend_episode2(pb, eq, so, ed, "pput", pput_rows,
                                 pput_dates, info_pput)
    ep2_spy = v9_blend_episode2(pb, eq, so, ed, "spy", pput_rows,
                                pput_dates, info_spy)
    print(f"EP2 PPUT blend: {ep2_pput}", flush=True)
    print(f"EP2 SPY blend: {ep2_spy}", flush=True)
    out = {"window": "fold2020 (2020-01-01 -> 2020-12-31)",
           "integrity_parent_final": round(parent["final"], 2),
           "pput_standalone": {k: v for k, v in pput_pot.items()
                               if k != "curve"},
           "pput_blend_ep1": {"final": round(info_pput["final"], 2),
                              "halt": info_pput["halt"],
                              "worst_close": round(
                                  min(v for _, v in pot_pput), 2)},
           "pput_blend_ep2": ep2_pput,
           "spy_blend_ep1": {"final": round(info_spy["final"], 2),
                             "halt": info_spy["halt"],
                             "worst_close": round(
                                 min(v for _, v in pot_spy), 2)},
           "spy_blend_ep2": ep2_spy,
           "elapsed_sec": round(time.time() - t0, 1)}
    with open(os.path.join(HERE, "v9-fold2020-detail.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps(out, indent=1, default=str), flush=True)
    print("DONE v9 put-hedge fold2020", flush=True)


if __name__ == "__main__":
    v9_main()
