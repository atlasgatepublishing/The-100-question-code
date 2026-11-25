#!/usr/bin/env python3
"""
VM + TREND, CONSTRUCTED (v12) — champion value+momentum blended 50/50
with a documented managed-futures ETF that holds/replicates the
MOP/Hurst levered long-short futures book inside an ETF wrapper.

Frozen spec: CONSTRUCTION-SPEC.md in this folder (written before runs).
  Construction 1 (PRIMARY): DBMF (iMGP DBi Managed Futures Strategy
    ETF, inception 2019-05-07) — CTA-replication form.
    Windows: CONT* 2019-05-08 -> 2026-11-20 (fund's first trading day;
    champion + SPY recomputed over the identical window), VAL
    2023-01-01 -> 2026-11-20.
  Construction 2 (LONG-ROAD): WTMF (WisdomTree Managed Futures
    Strategy Fund, inception 2011-01-05) — rules-based form; strategy
    changed 2021-06-04 (fence printed in spec and results).
    Window: DECADE 2016-11-21 -> 2026-11-20.
  Blend mechanics verbatim from v5 vm-plus-trend.py: $100 pot 50/50,
  January split-rebalance (0.10% sell + 0.10% buy on transferred value
  + $0.01 x 5), plain -15% pot-level floor only, sleeves run standalone
  on $50 with internal protection disabled, blended at curve level.
  Trend sleeve here = buy-and-hold the wrapper ETF on $50: initial buy
  charged 0.10%; fund expense ratio (DBMF 0.85% / WTMF 0.66%) is inside
  the adjusted price, charged exactly once by construction.
  Placebos: 20 seeds, random picks in the V+M sleeve, trend sleeve
  unchanged (v5 method). Folds: fresh $100 pot per calendar year.
Integrity checks (abort on failure): champion V+M plain floor $100 ->
$544.47 (program CONT) and $288.05 (VAL), as in v5.
Data: parents' read-only caches for V+M; Yahoo adjusted closes for
DBMF/WTMF fetched into this folder's data/ only.
"""
import importlib.util
import json
import math
import os
import random
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))

POT = 100.0
FLOOR = 85.0
HALF = 50.0
PLACEBO_SEEDS = list(range(1, 21))
PUBLISHED_FOLDS = {2020: 83.62, 2021: 118.43, 2022: 108.91, 2023: 118.47,
                   2024: 144.32, 2025: 124.57, 2026: 136.26}

CONSTRUCTIONS = {
    "DBMF": {"windows": {"cont_star": ("2019-05-08", "2026-11-20"),
                         "validation": ("2023-01-01", "2026-11-20")},
             "fold_years": list(range(2020, 2027))},
    "WTMF": {"windows": {"decade": ("2016-11-21", "2026-11-20")},
             "fold_years": list(range(2017, 2027))},
}


# ---------------- reporting helpers (verbatim from v5) -------------------
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
    for y in sorted({d[:4] for d, _ in curve}):
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


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    i = q * (len(sorted_vals) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - i) + sorted_vals[hi] * (i - lo)


# ---------------- blend (verbatim from v5) -------------------------------
def blend_curves(curveA, curveB, pot0=POT, floor=FLOOR, rebalance=True):
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
            cost = transfer * 0.002 + 0.05
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


# ---------------- wrapper-ETF sleeve --------------------------------------
def load_adj_series(ticker):
    data = json.load(open(os.path.join(HERE, "data", f"{ticker}.json")))
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        c = q["close"][i]
        if c is None or adj[i] is None:
            continue
        out[d] = adj[i]
    return out


def etf_sleeve(series, sd, ed, cash=HALF):
    """Buy-and-hold wrapper sleeve: buy at first close >= sd (0.10% buy
    cost), hold to last close <= ed. Returns curve + costs, v5 shape."""
    dates = sorted(d for d in series if sd <= d <= ed)
    p0 = series[dates[0]]
    start_val = cash * (1 - 0.001)
    curve = [(d, start_val * series[d] / p0) for d in dates]
    return {"curve": curve, "costs": round(cash * 0.001, 2),
            "final": curve[-1][1]}


def etf_buyhold_100(series, sd, ed):
    r = etf_sleeve(series, sd, ed, cash=POT)
    return r["final"], r["curve"]


# ---------------- V+M book (copied from v5) -------------------------------
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


def vm_sleeve(pb, eq_rows, sh_rows, sd, ed, cash=HALF, rng=None):
    return vm.run_pot(pb, eq_rows, sh_rows, sd, ed, cash, 0.0, [],
                      placebo_rng=rng, quiet=True)


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
    return {"median": round(pct(srt, 0.50), 2),
            "q1": round(pct(srt, 0.25), 2),
            "q3": round(pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": halts,
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties)
                                       / len(finals), 1),
            "seeds_beaten": below, "rows": rows}


def main():
    out = {"spec": "CONSTRUCTED 50/50 champion V+M + managed-futures "
                   "wrapper ETF sleeve (DBMF primary / WTMF decade), "
                   "January split rebalance, plain -15% pot floor, "
                   "$100 pots",
           "constructions": {}}

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
    out["integrity_checks"] = "passed (vm 544.47 / 288.05)"

    curves = {}
    for ticker, cfg in CONSTRUCTIONS.items():
        series = load_adj_series(ticker)
        cout = {"windows": {}, "folds": []}
        for wname, (sd, ed) in cfg["windows"].items():
            print(f"\n== {ticker} {wname} {sd} -> {ed} ==", flush=True)
            vmp = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, POT, FLOOR,
                             [], quiet=True)
            spy, _ = vm.spy_net(pb, sd, ed, POT)
            vms = vm_sleeve(pb, eq_rows, sh_rows, sd, ed)
            es = etf_sleeve(series, sd, ed)
            e100, e100_curve = etf_buyhold_100(series, sd, ed)
            pot_curve, binfo = blend_curves(vms["curve"], es["curve"])
            _, sinfo = blend_curves(vms["curve"], es["curve"],
                                    rebalance=False)
            mrA = monthly_returns(vms["curve"])
            mrB = monthly_returns(es["curve"])
            common = sorted(set(mrA) & set(mrB))
            corr = pearson([mrA[m] for m in common],
                           [mrB[m] for m in common])
            print(f"BLEND final=${binfo['final']:.2f} "
                  f"maxDD={binfo['max_dd']*100:.2f}% "
                  f"halt={binfo['halt']} corr={corr:.3f}", flush=True)
            print(f"VM same-window final=${vmp['final']:.2f} "
                  f"maxDD={max_dd(vmp['curve'])*100:.2f}% | "
                  f"{ticker} alone $100=${e100:.2f} "
                  f"maxDD={max_dd(e100_curve)*100:.2f}% | "
                  f"SPY=${spy:.2f} | static=${sinfo['final']:.2f}",
                  flush=True)
            print(f"placebo ({ticker} {wname})...", flush=True)
            plac = placebo_block(pb, eq_rows, sh_rows, es["curve"],
                                 sd, ed, binfo["final"])
            w = {"window": [sd, ed],
                 "blend_final": round(binfo["final"], 2),
                 "blend_ret_pct": round((binfo["final"] / POT - 1)
                                        * 100, 2),
                 "blend_cagr_pct": round(cagr(binfo["final"], POT, sd,
                                              ed) * 100, 2),
                 "blend_max_dd_pct": round(binfo["max_dd"] * 100, 2),
                 "blend_halt": binfo["halt"],
                 "blend_min_close": round(min(e for _, e in pot_curve),
                                          2),
                 "blend_costs_sleeves": round(vms["costs"]
                                              + es["costs"], 2),
                 "blend_costs_transfers": round(binfo["transfer_costs"],
                                                2),
                 "blend_rebalances": binfo["rebalances"],
                 "static_mix_final": round(sinfo["final"], 2),
                 "static_mix_max_dd_pct": round(sinfo["max_dd"] * 100,
                                                2),
                 "sleeveA_vm_final_50": round(vms["curve"][-1][1], 2),
                 "sleeveB_etf_final_50": round(es["curve"][-1][1], 2),
                 "sleeve_corr_monthly": round(corr, 3),
                 "sleeve_corr_months": len(common),
                 "vm_parent_final_postliq": round(vmp["final"], 2),
                 "vm_parent_max_dd_pct": round(max_dd(vmp["curve"])
                                               * 100, 2),
                 "vm_parent_halt": vmp["halted"],
                 "etf_alone_final_100": round(e100, 2),
                 "etf_alone_max_dd_pct": round(max_dd(e100_curve)
                                               * 100, 2),
                 "spy_net_final": round(spy, 2),
                 "placebo": plac,
                 "per_year": {
                     "blend": {y: round(v * 100, 2) for y, v in
                               per_year(pot_curve, POT).items()},
                     "vm_parent": {y: round(v * 100, 2) for y, v in
                                   per_year(vmp["curve"], POT).items()},
                     "etf_alone": {y: round(v * 100, 2) for y, v in
                                   per_year(e100_curve, POT).items()}}}
            cout["windows"][wname] = w
            curves[f"{ticker}:{wname}"] = {
                "blend": [[d, round(e, 4)] for d, e in pot_curve],
                "vm_parent": [[d, round(e, 4)] for d, e in
                              vmp["curve"]],
                "etf_alone": [[d, round(e, 4)] for d, e in e100_curve]}

        print(f"\n== {ticker} walk-forward folds ==", flush=True)
        for y in cfg["fold_years"]:
            fs = f"{y}-01-01"
            fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
            vmp = vm.run_pot(pb, eq_rows, sh_rows, fs, fe, POT, FLOOR,
                             [], quiet=True)
            if y in PUBLISHED_FOLDS:
                assert abs(vmp["final"] - PUBLISHED_FOLDS[y]) < 0.05, \
                    f"fold {y} V+M parent check failed: {vmp['final']}"
            spy, _ = vm.spy_net(pb, fs, fe, POT)
            vms = vm_sleeve(pb, eq_rows, sh_rows, fs, fe)
            es = etf_sleeve(series, fs, fe)
            pot_curve, binfo = blend_curves(vms["curve"], es["curve"])
            row = {"year": y, "start": fs, "end": fe,
                   "blend_final": round(binfo["final"], 2),
                   "blend_ret_pct": round((binfo["final"] / POT - 1)
                                          * 100, 2),
                   "blend_max_dd_pct": round(binfo["max_dd"] * 100, 2),
                   "blend_halt": binfo["halt"],
                   "vm_final": round(vmp["final"], 2),
                   "vm_ret_pct": round((vmp["final"] / POT - 1) * 100,
                                       2),
                   "vm_halt": vmp["halted"],
                   "spy_net_final": round(spy, 2),
                   "beat_spy": binfo["final"] > spy,
                   "beat_vm": binfo["final"] > vmp["final"]}
            cout["folds"].append(row)
            print(f"FOLD {y}: blend ${row['blend_final']:,.2f} "
                  f"maxDD={row['blend_max_dd_pct']:.2f}% "
                  f"halt={row['blend_halt']} | VM ${row['vm_final']:,.2f}"
                  f" | SPY ${row['spy_net_final']:,.2f} "
                  f"beat_vm={row['beat_vm']}", flush=True)
        bw = sum(1 for f in cout["folds"] if f["beat_spy"])
        bv = sum(1 for f in cout["folds"] if f["beat_vm"])
        cout["fold_record"] = (f"blend {bw}/{len(cout['folds'])} vs SPY; "
                               f"{bv}/{len(cout['folds'])} vs V+M parent")
        fc = 100.0
        for f in cout["folds"]:
            fc *= 1 + f["blend_ret_pct"] / 100.0
        cout["fold_compounded_blend"] = round(fc, 2)
        print(f"{ticker}: {cout['fold_record']}; "
              f"fold-compounded ${fc:,.2f}", flush=True)
        out["constructions"][ticker] = cout

    out["curves"] = curves
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nsaved results.json")


if __name__ == "__main__":
    main()
