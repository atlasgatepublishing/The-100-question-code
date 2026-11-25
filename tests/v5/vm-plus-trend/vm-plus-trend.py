#!/usr/bin/env python3
"""
VALUE+MOMENTUM + ETF TREND SLEEVE — Terry's AI stock app, simulation only.

QUESTION: The program's two stock engines were blended once and diluted
each other (winners-blend: correlation +0.79, blend $400.84 vs V+M
$544.47). The ETF Trend Sleeve (monthly variant) is the one promoted
component that behaves DIFFERENTLY — it rotates out of equities into
bonds/gold/cash proxies in downturns (decade max DD -13.73% monthly vs
V+M's -36.26%). Does giving the flagship a genuinely defensive partner
buy real protection, and what does the insurance cost in final balance
under Terry's most-money-first scoreboard?

SPEC (frozen a priori, no tuning):
  - One $100 pot split 50/50.
    Sleeve A: Value+Momentum exactly as proven
      (../../v4/value-momentum-plainfloor.py — quarterly top-5,
      book-to-market + 12-1 momentum average percentile rank, honest
      2016 top-30 universe, EDGAR point-in-time, costs 0.10%/side +
      $0.01/sell).
    Sleeve B: ETF Trend Sleeve, MONTHLY variant, exactly as proven
      (../../v3/etf-trend-sleeve-monthly.py — SPY/QQQ/TLT/IEF/GLD/DBC/
      UUP, 3/6/12-month sign-blend trend, inverse-vol weights capped
      40%, 20% no-trade band, monthly evaluation, same cost schedule,
      dividend+split adjusted prices).
  - Every January (first trading day, at the close) the split is
    rebalanced back to 50/50, charged at the engines' normal cost
    schedule (0.10% sell + 0.10% buy on the transferred value +
    $0.01 x 5 sell orders) — the identical convention to winners-blend.
  - Protection: the PLAIN -15% floor ($85) at the WHOLE-POT level only.
    No ladder, no sleeve-level floor (each sleeve runs standalone with
    its internal floor/ladder disabled; only the pot floor can stop
    the run — same method as winners-blend).
  - Windows (both engines have data): CONTINUOUS 2019-01-01 ->
    2026-11-20 and VALIDATION 2023-01-01 -> 2026-11-20, $100 pots
    (engines snap to the first trading day: 2019-01-02 / 2023-01-03).
  - Placebo: 20 seeds (1..20); the V+M sleeve draws 5 names RANDOMLY
    from the scored pool each quarter (identical machinery), the trend
    sleeve runs unchanged; same blending, same pot floor.
  - Walk-forward folds: fresh $100 pot per calendar year 2020-2026
    (2026 -> Nov 20), same construction, scored vs SPY net and vs the
    V+M parent fold.

METHOD — engines verbatim, blended at the equity-curve level (the
winners-blend method): each sleeve runs standalone on its $50 half,
producing a daily close-equity curve; the pot is the sum of the two
sleeve values with January rescaling. Two documented approximations,
both pennies-level: (1) after a January rescale a sleeve follows its
standalone $50 path, so its internal $0.01 sell fees are charged at the
standalone trajectory; (2) the January transfer is charged on the
transferred value rather than by re-trading every share. A static-mix
diagnostic (no January rebalancing) separates dilution from rebalancing
cost, so neither approximation can hide the verdict.

INTEGRITY CHECKS (run first, abort on failure):
  - Value+momentum plain floor, $100 -> published $544.47 (continuous)
    and $288.05 (validation).
  - ETF trend sleeve monthly, AS-PROVEN config (floor $85 + ladder),
    $100 over its published decade 2016-11-21 -> 2026-11-20 ->
    published $194.61; $50 as-proven (floor $42.50 + scaled ladder) ->
    published $96.00; validation $100 as-proven -> published $123.18.
  - V+M walk-forward fold finals recomputed in-run must match the
    published vm-walkforward fold finals to the cent.

Data: the parent studies' own caches, read-only (EDGAR companyfacts
under ../../v4/data; Yahoo bars under ../../v4/value-momentum-honest-data
and ../../v3/data_etf).
"""

import importlib.util
import json
import math
import os
import random
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V3 = os.path.join(HERE, "..", "..", "v3")


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))
etf = _load("etf_trend_sleeve_monthly",
            os.path.join(V3, "etf-trend-sleeve-monthly.py"))

POT = 100.0
FLOOR = 85.0
HALF = 50.0
WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))
COVID = ("2020-02-01", "2020-04-30")
PUBLISHED_FOLDS = {2020: 83.62, 2021: 118.43, 2022: 108.91, 2023: 118.47,
                   2024: 144.32, 2025: 124.57, 2026: 136.26}


# --------------------------------------------------------------------------
# Reporting helpers (no trading logic) — same as winners-blend
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


# --------------------------------------------------------------------------
# The blend: two sleeve equity curves -> one pot (winners-blend method)
# --------------------------------------------------------------------------
def blend_curves(curveA, curveB, pot0=POT, floor=FLOOR, rebalance=True):
    """curveA/curveB: standalone $50 sleeve daily close-equity curves.
    January split-rebalances at the close of the first trading day of
    each January after the inception January (skipped when
    rebalance=False — the static-mix diagnostic); pot-level plain
    floor checked on every close."""
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
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Sleeve runners (standalone, internal protection disabled)
# --------------------------------------------------------------------------
def vm_sleeve(pb, eq_rows, sh_rows, sd, ed, cash=HALF, rng=None):
    return vm.run_pot(pb, eq_rows, sh_rows, sd, ed, cash, 0.0, [],
                      placebo_rng=rng, quiet=True)


def etf_sleeve(sd, ed, cash=HALF):
    return etf.simulate(sd, ed, start_cash=cash, floor0=0.0, ladder=())


# --------------------------------------------------------------------------
# Value+momentum data assembly — the parent study's own assembly
# (incl. the XOM CIK override), copied from winners-blend.py.
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


def placebo_block(pb, eq_rows, sh_rows, etf_curve, sd, ed, ranked_final):
    finals = []
    halts = 0
    rows = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        ps = vm_sleeve(pb, eq_rows, sh_rows, sd, ed, HALF, rng=rng)
        _, pinfo = blend_curves(ps["curve"], etf_curve)
        finals.append(pinfo["final"])
        if pinfo["halt"]:
            halts += 1
        rows.append({"seed": seed, "final": round(pinfo["final"], 2),
                     "halt": pinfo["halt"]})
        print(f"  placebo seed {seed:2d}: ${pinfo['final']:,.2f} "
              f"halt={pinfo['halt']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {
        "median": round(pct(srt, 0.50), 2),
        "q1": round(pct(srt, 0.25), 2),
        "q3": round(pct(srt, 0.75), 2),
        "best": round(srt[-1], 2), "worst": round(srt[0], 2),
        "mean": round(sum(finals) / len(finals), 2),
        "halted_count": halts,
        "ranked_final": round(ranked_final, 2),
        "ranked_percentile": round(100.0 * (below + 0.5 * ties)
                                   / len(finals), 1),
        "seeds_beaten": below,
        "rows": rows,
    }


def main():
    out = {"spec": "50/50 V+M + ETF trend sleeve (monthly), January "
                   "split rebalance, plain -15% pot floor, $100 pots",
           "windows": WINDOWS}

    # ---------------- integrity checks ----------------------------------
    print("loading value+momentum book (cache)...", flush=True)
    pb, eq_rows, sh_rows = build_vm_book()

    r = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-02", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor continuous $100: ${r['final']:.2f} "
          f"(published $544.47)", flush=True)
    assert abs(r["final"] - 544.47) < 0.05, "value engine check failed"
    r = vm.run_pot(pb, eq_rows, sh_rows, "2023-01-03", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor validation $100: ${r['final']:.2f} "
          f"(published $288.05)", flush=True)
    assert abs(r["final"] - 288.05) < 0.05, "value engine check failed"

    e = etf.simulate("2016-11-21", "2026-11-20")
    print(f"CHECK etf monthly as-proven decade $100: ${e['final']:.2f} "
          f"(published $194.61)", flush=True)
    assert abs(e["final"] - 194.61) < 0.05, "etf engine check failed"
    e50 = etf.simulate("2016-11-21", "2026-11-20", start_cash=50.0,
                       floor0=42.50, ladder=((62.50, 50.0), (75.0, 62.50)))
    print(f"CHECK etf monthly as-proven decade $50: ${e50['final']:.2f} "
          f"(published $96.00)", flush=True)
    assert abs(e50["final"] - 96.00) < 0.05, "etf $50 check failed"
    eb = etf.simulate("2023-01-01", "2026-11-20")
    print(f"CHECK etf monthly as-proven validation $100: "
          f"${eb['final']:.2f} (published $123.18)", flush=True)
    assert abs(eb["final"] - 123.18) < 0.05, "etf validation check failed"
    out["integrity_checks"] = ("passed (vm 544.47 / 288.05; etf monthly "
                               "194.61 / 96.00 / 123.18)")

    # ---------------- main windows ---------------------------------------
    for wname, (sd, ed) in WINDOWS.items():
        print(f"\n== {wname} {sd} -> {ed} ==", flush=True)
        # parents alone at $100
        vmp = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                         quiet=True)
        etfp = etf.simulate(sd, ed, start_cash=POT, floor0=FLOOR,
                            ladder=())
        spy, _ = vm.spy_net(pb, sd, ed, POT)

        # sleeves at $50, no sleeve-level protection
        vms = vm_sleeve(pb, eq_rows, sh_rows, sd, ed)
        etfs = etf_sleeve(sd, ed)

        # the blend + static-mix diagnostic
        pot_curve, binfo = blend_curves(vms["curve"], etfs["curve"])
        _, sinfo = blend_curves(vms["curve"], etfs["curve"],
                                rebalance=False)

        # sleeve correlation (monthly returns, standalone $50 paths)
        mrA = monthly_returns(vms["curve"])
        mrB = monthly_returns(etfs["curve"])
        common = sorted(set(mrA) & set(mrB))
        corr = pearson([mrA[m] for m in common], [mrB[m] for m in common])

        # COVID worst closes
        blend_covid, blend_covid_d = min_close_in(pot_curve, *COVID)
        vm_covid, vm_covid_d = min_close_in(vmp["curve"], *COVID)
        blend_min = min(e for _, e in pot_curve)
        vm_min = min(e for _, e in vmp["curve"])

        print(f"BLEND  final=${binfo['final']:.2f} "
              f"maxDD={binfo['max_dd']*100:.2f}% halt={binfo['halt']} "
              f"corr={corr:.3f}", flush=True)
        print(f"VM     final=${vmp['final']:.2f} (post-liq) "
              f"maxDD={max_dd(vmp['curve'])*100:.2f}% "
              + (f"covidWorst=${vm_covid:.2f} on {vm_covid_d}"
                 if vm_covid is not None else "covidWorst=n/a (window)"),
              flush=True)
        print(f"ETF    final=${etfp['final']:.2f} "
              f"maxDD={max_dd(etfp['curve'])*100:.2f}%", flush=True)
        print(f"SPY    final=${spy:.2f} | static mix=${sinfo['final']:.2f}",
              flush=True)

        # placebo (V+M sleeve random, trend sleeve unchanged)
        print(f"placebo ({wname})...", flush=True)
        plac = placebo_block(pb, eq_rows, sh_rows, etfs["curve"], sd, ed,
                             binfo["final"])

        out[wname] = {
            "blend_final": round(binfo["final"], 2),
            "blend_ret_pct": round((binfo["final"] / POT - 1) * 100, 2),
            "blend_cagr_pct": round(cagr(binfo["final"], POT, sd, ed)
                                    * 100, 2),
            "blend_max_dd_pct": round(binfo["max_dd"] * 100, 2),
            "blend_halt": binfo["halt"],
            "blend_costs_sleeves": round(vms["costs"] + etfs["costs"], 2),
            "blend_costs_transfers": round(binfo["transfer_costs"], 2),
            "blend_rebalances": binfo["rebalances"],
            "blend_covid_worst_close": (round(blend_covid, 2)
                                        if blend_covid is not None
                                        else None),
            "blend_covid_worst_date": blend_covid_d,
            "blend_min_close": round(blend_min, 2),
            "static_mix_final": round(sinfo["final"], 2),
            "static_mix_max_dd_pct": round(sinfo["max_dd"] * 100, 2),
            "sleeveA_vm_final_50": round(vms["curve"][-1][1], 2),
            "sleeveB_etf_final_50": round(etfs["curve"][-1][1], 2),
            "sleeve_corr_monthly": round(corr, 3),
            "sleeve_corr_months": len(common),
            "vm_parent_final_postliq": round(vmp["final"], 2),
            "vm_parent_final_mtm": round(vmp["curve"][-1][1], 2),
            "vm_parent_max_dd_pct": round(max_dd(vmp["curve"]) * 100, 2),
            "vm_parent_halt": vmp["halted"],
            "vm_parent_costs": round(vmp["costs"], 2),
            "vm_covid_worst_close": (round(vm_covid, 2)
                                     if vm_covid is not None else None),
            "vm_covid_worst_date": vm_covid_d,
            "vm_min_close": round(vm_min, 2),
            "etf_parent_final": round(etfp["final"], 2),
            "etf_parent_max_dd_pct": round(max_dd(etfp["curve"]) * 100, 2),
            "etf_parent_halt": etfp["halted"],
            "etf_parent_costs": round(etfp["costs"], 2),
            "spy_net_final": round(spy, 2),
            "placebo": plac,
            "per_year": {
                "blend": {y: round(v * 100, 2)
                          for y, v in per_year(pot_curve, POT).items()},
                "vm_parent": {y: round(v * 100, 2)
                              for y, v in per_year(vmp["curve"],
                                                   POT).items()},
                "etf_parent": {y: round(v * 100, 2)
                               for y, v in per_year(etfp["curve"],
                                                    POT).items()},
            },
        }

    # ---------------- walk-forward folds ---------------------------------
    print("\n== walk-forward folds ==", flush=True)
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        vmp = vm.run_pot(pb, eq_rows, sh_rows, fs, fe, POT, FLOOR, [],
                         quiet=True)
        assert abs(vmp["final"] - PUBLISHED_FOLDS[y]) < 0.05, \
            f"fold {y} V+M parent check failed: {vmp['final']}"
        spy, _ = vm.spy_net(pb, fs, fe, POT)
        vms = vm_sleeve(pb, eq_rows, sh_rows, fs, fe)
        etfs = etf_sleeve(fs, fe)
        pot_curve, binfo = blend_curves(vms["curve"], etfs["curve"])
        row = {"year": y, "start": fs, "end": fe,
               "blend_final": round(binfo["final"], 2),
               "blend_ret_pct": round((binfo["final"] / POT - 1) * 100, 2),
               "blend_max_dd_pct": round(binfo["max_dd"] * 100, 2),
               "blend_halt": binfo["halt"],
               "vm_final": round(vmp["final"], 2),
               "vm_ret_pct": round((vmp["final"] / POT - 1) * 100, 2),
               "vm_halt": vmp["halted"],
               "spy_net_final": round(spy, 2),
               "spy_ret_pct": round((spy / POT - 1) * 100, 2),
               "beat_spy": binfo["final"] > spy,
               "beat_vm": binfo["final"] > vmp["final"]}
        folds.append(row)
        print(f"FOLD {y}: blend ${row['blend_final']:,.2f} "
              f"({row['blend_ret_pct']:+.2f}%) maxDD="
              f"{row['blend_max_dd_pct']:.2f}% halt={row['blend_halt']} | "
              f"VM ${row['vm_final']:,.2f} ({row['vm_ret_pct']:+.2f}%) "
              f"halt={row['vm_halt']} | SPY ${row['spy_net_final']:,.2f} "
              f"({row['spy_ret_pct']:+.2f}%) beat_spy={row['beat_spy']} "
              f"beat_vm={row['beat_vm']}", flush=True)
    bw = sum(1 for f in folds if f["beat_spy"])
    bv = sum(1 for f in folds if f["beat_vm"])
    out["folds"] = folds
    out["fold_record"] = (f"blend {bw} wins / {len(folds) - bw} losses "
                          f"vs SPY; {bv} wins / {len(folds) - bv} losses "
                          f"vs V+M parent")
    print(out["fold_record"], flush=True)
    fc = 100.0
    for f in folds:
        fc *= 1 + f["blend_ret_pct"] / 100.0
    out["fold_compounded_blend"] = round(fc, 2)
    print(f"fold-compounded blend: ${fc:,.2f} (V+M folds $313.01, "
          f"SPY folds $227.34)", flush=True)

    with open(os.path.join(HERE, "vm-plus-trend-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nsaved vm-plus-trend-results.json")


if __name__ == "__main__":
    main()
