#!/usr/bin/env python3
"""
THE WINNERS' BLEND — Terry's AI stock app, simulation only.

QUESTION: Terry's two promoted strategies — the honest momentum basket
(monthly top-5 by 12-1 momentum among names above their 200-day average,
honest 2016 top-30 universe) and honest value+momentum (quarterly top-5
by average percentile rank of book-to-market and 12-1 momentum, EDGAR
point-in-time) — each made the most money ALONE. Does running them as two
sleeves of ONE $100 pot make MORE than either alone, or do they dilute
each other?

SPEC (frozen):
  - One $100 pot, split 50/50: $50 to the momentum-basket engine,
    $50 to the value+momentum engine. Each sleeve runs its own rules,
    verbatim, on its half (same universes, signals, costs:
    0.10%/side + $0.01/sell inside each engine).
  - Every January (first trading day of the month, at that day's close)
    the SPLIT is rebalanced back to 50/50 of the pot: the overweight
    sleeve is trimmed pro-rata and the proceeds buy into the underweight
    sleeve, charged at the engines' normal cost schedule
    (0.10% on the sale + 0.10% on the purchase + $0.01 x 5 sell orders
    for the trimmed sleeve's positions).
  - Pot-level protection: the PLAIN -15% floor only ($85 on the $100
    pot). No ladder, and NO sleeve-level floor — a sleeve can only be
    stopped by the pot floor. If the pot closes at/below $85 the run
    ends (liquidation approximated at the next day's close less 0.10%
    and $0.10 of sell fees; documented approximation — it never fired
    in these windows, see the report).
  - Windows (both engines have data): CONTINUOUS 2019-01-01 ->
    2026-11-20 and VALIDATION 2023-01-01 -> 2026-11-20, $100 pots.
    (Engines snap to the first trading day: 2019-01-02 / 2023-01-03.)

METHOD — engines verbatim, blended at the equity-curve level:
  Both engines are IMPORTED UNMODIFIED and called with their own data
  loaders (momentum-basket-honest.py; value-momentum-plainfloor.py).
  Each sleeve is run standalone on its $50 half with its internal floor
  disabled (protection lives at pot level only), producing a daily
  close-equity curve. The blend pot is the sum of the two sleeve
  values; at each January rebalance the sleeves are rescaled to 50/50
  of the pot less the transfer cost. This is exact except for two
  documented approximations: (1) after a January rescale a sleeve's
  subsequent path follows its standalone $50 curve, so the $0.01 fixed
  sell fees inside the engines are charged at the standalone trajectory
  rather than the rescaled one — a pennies-level effect over 8 years;
  (2) the January transfer is charged at the engines' cost schedule on
  the transferred value rather than by re-trading every share.
  Parents are RECOMPUTED inside this run over the identical windows
  under the identical protection rule (plain -15% floor) for exact
  comparability; the as-published figures are quoted in the report.

INTEGRITY CHECKS (run first, abort on failure):
  - Momentum basket, original floor+ladder config, full 2016 window,
    $100 -> must reproduce the published $439.45.
  - Value+momentum plain floor, $100 -> must reproduce the published
    $544.47 (2019-01-02 -> 2026-11-20) and $288.05 (validation).

Data: the parent studies' own caches, read-only (Yahoo bars under
./momentum-basket-honest-data and ./value-momentum-honest-data; EDGAR
companyfacts under ./data).
"""

import importlib.util
import json
import math
import os
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(modname, fname):
    spec = importlib.util.spec_from_file_location(modname,
                                                  os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load("momentum_basket_honest", "momentum-basket-honest.py")
vm = _load("value_momentum_plainfloor", "value-momentum-plainfloor.py")

POT = 100.0
FLOOR = 85.0
HALF = 50.0
WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}


# --------------------------------------------------------------------------
# Small helpers (reporting only — no trading logic)
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
    """Month-over-month returns from last close of each calendar month."""
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


# --------------------------------------------------------------------------
# The blend: two sleeve equity curves -> one pot
# --------------------------------------------------------------------------
def blend_curves(curveA, curveB, pot0=POT, floor=FLOOR):
    """curveA/curveB: standalone $50 sleeve daily close-equity curves.
    Returns (pot_curve, info). January split-rebalances at the close of
    the first trading day of each January after the inception January;
    pot-level plain floor checked on every close."""
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
        if d in jan_dates:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05      # 0.10% sell + 0.10% buy
            #                               + $0.01 x 5 sell orders
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
                final = nxt * (1 - 0.001) - 0.10
            else:
                final = tot * (1 - 0.001) - 0.10
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final_mtm": final if halt else pot_curve[-1][1],
            "final": final, "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Value+momentum data assembly — the parent study's own assembly, using
# the parent module's functions verbatim (incl. the XOM CIK override).
# --------------------------------------------------------------------------
def build_vm_book():
    ciks = vm.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in vm.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        equity_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributable"
                          "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            vm.pit_series(facts, "dei",
                          "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap",
                          "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          prio=1))
        time.sleep(0.05)
    bars = {}
    for t in vm.UNIVERSE + ["SPY"]:
        bars[t] = vm.get_prices(t)
    return vm.PriceBook(bars), equity_rows, shares_rows


def main():
    out = {"spec": "50/50 winners blend, January split rebalance, "
                   "plain -15% pot floor, $100 pots",
           "windows": WINDOWS}
    print("loading momentum-basket market (cache)...", flush=True)
    mkt = mb.Market(mb.UNIVERSE)

    # ---------------- integrity checks ----------------------------------
    r = mb.simulate(mkt, "2016-11-21", "2026-11-20", 100, "ranked")
    print(f"CHECK mb original full-2016 $100: ${r.final:.2f} "
          f"(published $439.45)", flush=True)
    assert abs(r.final - 439.45) < 0.05, "momentum engine check failed"

    print("loading value+momentum book (cache)...", flush=True)
    pb, eq_rows, sh_rows = build_vm_book()
    r = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-02", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor full $100: ${r['final']:.2f} "
          f"(published $544.47)", flush=True)
    assert abs(r["final"] - 544.47) < 0.05, "value engine check failed"
    r = vm.run_pot(pb, eq_rows, sh_rows, "2023-01-03", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor validation $100: ${r['final']:.2f} "
          f"(published $288.05)", flush=True)
    assert abs(r["final"] - 288.05) < 0.05, "value engine check failed"
    out["integrity_checks"] = "passed (439.45 / 544.47 / 288.05)"

    # ------------- configure the basket engine: plain floor / none ------
    orig_floors = mb.FLOORS
    mb.FLOORS = {100: (FLOOR, []), 50: (0.0, [])}

    for wname, (sd, ed) in WINDOWS.items():
        # ---- parents alone at $100, plain floor -------------------------
        mbp = mb.simulate(mkt, sd, ed, 100, "ranked")
        vmp = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                         quiet=True)
        spy = mb.spy_net(mkt, sd, ed, 100)

        # ---- sleeves at $50, no sleeve-level floor ----------------------
        mbs = mb.simulate(mkt, sd, ed, 50, "ranked")
        vms = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, HALF, 0.0, [],
                         quiet=True)

        # ---- the blend ---------------------------------------------------
        pot_curve, binfo = blend_curves(mbs.equity_curve, vms["curve"])

        # ---- correlation of sleeve monthly returns ----------------------
        mrA = monthly_returns(mbs.equity_curve)
        mrB = monthly_returns(vms["curve"])
        common = sorted(set(mrA) & set(mrB))
        corr = pearson([mrA[m] for m in common], [mrB[m] for m in common])

        w = {
            "blend_final": round(binfo["final"], 2),
            "blend_final_mtm": round(pot_curve[-1][1], 2),
            "blend_ret_pct": round((binfo["final"] / POT - 1) * 100, 2),
            "blend_cagr_pct": round(cagr(binfo["final"], POT, sd, ed)
                                    * 100, 2),
            "blend_max_dd_pct": round(binfo["max_dd"] * 100, 2),
            "blend_halt": binfo["halt"],
            "blend_costs_sleeves": round(mbs.costs + vms["costs"], 2),
            "blend_costs_transfers": round(binfo["transfer_costs"], 2),
            "blend_rebalances": binfo["rebalances"],
            "mb_parent_final": round(mbp.final, 2),
            "mb_parent_ret_pct": round((mbp.final / POT - 1) * 100, 2),
            "mb_parent_cagr_pct": round(cagr(mbp.final, POT, sd, ed)
                                        * 100, 2),
            "mb_parent_max_dd_pct": round(mbp.max_dd * 100, 2),
            "mb_parent_halt": mbp.halt_date,
            "mb_parent_costs": round(mbp.costs, 2),
            "vm_parent_final_postliq": round(vmp["final"], 2),
            "vm_parent_final_mtm": round(vmp["curve"][-1][1], 2),
            "vm_parent_ret_pct": round((vmp["curve"][-1][1] / POT - 1)
                                       * 100, 2),
            "vm_parent_cagr_pct": round(cagr(vmp["curve"][-1][1], POT,
                                             sd, ed) * 100, 2),
            "vm_parent_max_dd_pct": round(max_dd(vmp["curve"]) * 100, 2),
            "vm_parent_halt": vmp["halted"],
            "vm_parent_costs": round(vmp["costs"], 2),
            "spy_net_final": round(spy, 2),
            "sleeve_corr_monthly": round(corr, 3),
            "sleeve_corr_months": len(common),
            "per_year": {
                "blend": {y: round(v * 100, 2)
                          for y, v in per_year(pot_curve, POT).items()},
                "mb_parent": {y: round(v * 100, 2)
                              for y, v in per_year(mbp.equity_curve,
                                                   POT).items()},
                "vm_parent": {y: round(v * 100, 2)
                              for y, v in per_year(vmp["curve"],
                                                   POT).items()},
            },
        }
        out[wname] = w
        print(f"\n== {wname} {sd} -> {ed} ==", flush=True)
        print(f"BLEND      final=${w['blend_final']:.2f} "
              f"({w['blend_ret_pct']:+.2f}%) maxDD={w['blend_max_dd_pct']:.2f}% "
              f"halt={w['blend_halt']} corr={w['sleeve_corr_monthly']}",
              flush=True)
        print(f"MB parent  final=${w['mb_parent_final']:.2f} "
              f"({w['mb_parent_ret_pct']:+.2f}%) maxDD={w['mb_parent_max_dd_pct']:.2f}% "
              f"halt={w['mb_parent_halt']}", flush=True)
        print(f"VM parent  final=${w['vm_parent_final_mtm']:.2f} MtM "
              f"({w['vm_parent_ret_pct']:+.2f}%) / ${w['vm_parent_final_postliq']:.2f} post-liq "
              f"maxDD={w['vm_parent_max_dd_pct']:.2f}% halt={w['vm_parent_halt']}",
              flush=True)
        print(f"SPY net    final=${w['spy_net_final']:.2f}", flush=True)
        print(f"costs: blend sleeves=${w['blend_costs_sleeves']:.2f} "
              f"+ transfers=${w['blend_costs_transfers']:.2f} | "
              f"MB parent=${w['mb_parent_costs']:.2f} | "
              f"VM parent=${w['vm_parent_costs']:.2f}", flush=True)

    # reference: basket parent under its as-proven ladder config,
    # continuous window (the ladder-ablation showed ladder == plain for
    # this engine over 2016-2026 and 2023-2026; check the 2019 window too)
    mb.FLOORS = orig_floors
    sd, ed = WINDOWS["continuous"]
    r = mb.simulate(mkt, sd, ed, 100, "ranked")
    out["mb_parent_ladder_reference_continuous"] = {
        "final": round(r.final, 2), "halt": r.halt_date,
        "max_dd_pct": round(r.max_dd * 100, 2)}
    print(f"\nreference: MB parent continuous window under original "
          f"ladder: ${r.final:.2f} halt={r.halt_date}", flush=True)

    with open(os.path.join(HERE, "winners-blend-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nsaved winners-blend-results.json")


if __name__ == "__main__":
    main()
