#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-VOLSCALE. Simulation only. Spec frozen in
BEST-RULES-SPEC.md BEFORE this run.

MY FORM: v13 V+M host chassis unchanged (PIT EDGAR B/M + 12-1 momentum
percentile ranks averaged, honest top-30 pond PIT at road start,
quarterly re-pick, next-open execution, top-2 equal weight, NO floor,
program costs 0.10%/side + $0.01/sell) plus exactly ONE variable:
  COARSE CRISIS DIAL — at each quarterly selection, sigma = trailing
  126-trading-day realized vol of an equal-weight portfolio of the 2
  new picks (annualized). sigma <= 40% -> w=1.00; sigma > 40% ->
  w=0.50 (half in cash until next selection). <60 usable returns ->
  w=1.00 (published house fallback).

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
INTEGRITY GATES (both must pass before any v13 number counts):
  house count-5 == published champion (1415.62/667.35/544.47/288.05)
  host twin (count-2, no floor, dial off) == v13 base pass
  (2923.60/906.90/691.73/461.20)

CONFIRMATION (pre-registered): if my form beats champion OR host on
any road -> fresh-$100 calendar-year folds 2017..2026 + DECADE
half-windows vs BOTH bars; confirmed requires >=6/10 folds AND
>=1/2 halves against the bar that was beaten.
"""
import importlib.util
import json
import math
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
COUNT = 2
THRESH = 0.40
HI_W, LO_W = 1.0, 0.5
START_CASH = 100.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)


# ------------------------------------------------------------------ dial
def picks_vol(pb, picks, sel_date):
    """Trailing 126d annualized vol of an equal-weight portfolio of the
    picks: per-date portfolio return = mean of the picks' own daily
    returns (consecutive adjusted closes) on that date; use the last
    126 such returns on/before sel_date. None if <60 usable."""
    rets = {}
    for t in picks:
        bl = pb.bars.get(t, [])
        for i in range(1, len(bl)):
            if bl[i]["d"] > sel_date:
                break
            prev, cur = bl[i - 1]["c"], bl[i]["c"]
            if prev:
                rets.setdefault(bl[i]["d"], []).append(cur / prev - 1.0)
    dates = sorted(d for d, v in rets.items()
                   if d <= sel_date and len(v) == len(picks))
    port = [sum(rets[d]) / len(rets[d]) for d in dates][-126:]
    if len(port) < 60:
        return None
    return statistics.pstdev(port) * math.sqrt(252)


def dial_weight(pb, picks, sel_date):
    sig = picks_vol(pb, picks, sel_date)
    if sig is None:
        return 1.0, None
    return (HI_W if sig <= THRESH else LO_W), sig


# ------------------------------------------------------------------ engine
def run_dial(pb, dec, sel_dates, start, end, placebo_seed=None):
    """run_episode (floor=None) from the v12 chassis, with the dial
    applied to the rebalance targets. Returns chassis-shaped dict plus
    the dial record."""
    sel_set = set(sel_dates)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    dial_log = []
    days = [d for d in pb.dates if start <= d <= end]
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                total_costs += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))

    for d in days:
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = min(COUNT, len(pool))
                if rng is not None:
                    picks = rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                w, sig = dial_weight(pb, picks, d)
                dial_log.append({"date": d, "picks": picks,
                                 "sigma_pct": round(sig * 100, 2) if sig is not None else None,
                                 "w": w})
                pv = portfolio_close(d)
                each = w * pv / k
                pending = {t: each for t in picks}
        curve.append((d, portfolio_close(d)))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "orders": len(trades),
            "curve": curve, "dial_log": dial_log}


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules", "family": "vm-volscale",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"host": "V+M top-2, quarterly, no floor (v13 base pass)",
                     "dial": "sigma<=40% -> w=1.00; sigma>40% -> w=0.50; "
                             "sigma = trailing 126d ann. vol of equal-weight "
                             "2 picks; <60 returns -> w=1.00",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "published_champion": {"LONG": 1415.62, "DECADE": 667.35,
                               "CONT": 544.47, "VAL": 288.05},
        "unscaled_host_v13": {"LONG": 2923.60, "DECADE": 906.90,
                              "CONT": 691.73, "VAL": 461.20},
        "published_scaled_form_house": {"CONT": 256.05, "VAL": 205.85,
                                        "DECADE_quarterly": 284.32,
                                        "LONG": None},
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    results["long_pond"] = pondL

    road_specs = [
        ("DECADE", pb, dec_fixed, "2016-11-21", END),
        ("CONT", pb, dec_fixed, "2019-01-02", END),
        ("VAL", pb, dec_fixed, "2023-01-03", END),
        ("LONG", pbL, dec_long, "2010-01-04", END),
    ]

    # ---------------- integrity gates
    expect_pub = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    expect_host = {"DECADE": 906.90, "CONT": 691.73, "VAL": 461.20, "LONG": 2923.60}
    pub_runs, host_runs = {}, {}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        rp = S.run_house(pbx, decx, sel, s, e, 5)
        rh = S.run_native(pbx, decx, sel, s, e, COUNT)
        okp = abs(round(rp["final"], 2) - expect_pub[name]) < 0.02
        okh = abs(round(rh["final"], 2) - expect_host[name]) < 0.02
        results["integrity"][name] = {
            "house_count5_expected": expect_pub[name],
            "house_count5_reproduced": round(rp["final"], 2), "match": okp,
            "host_count2_nofloor_expected": expect_host[name],
            "host_count2_nofloor_reproduced": round(rh["final"], 2),
            "host_match": okh}
        print(f"INTEGRITY {name} house-5 ${rp['final']:,.2f} match={okp} | "
              f"host-2 ${rh['final']:,.2f} match={okh}", flush=True)
        assert okp and okh, f"integrity failed on {name}"
        pub_runs[name] = rp
        host_runs[name] = rh

    # ---------------- my-form run per road
    beat_champ, beat_host = False, False
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        r = run_dial(pbx, decx, sel, s, e)
        diag = S.diagnostics(r["curve"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        pfinals = []
        for seed in SEEDS:
            pr = run_dial(pbx, decx, sel, s, e, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        host = host_runs[name]
        hdiag = S.diagnostics(host["curve"])
        hdist = S.period_distribution([(d, v) for d, v in host["curve"]], sel)
        pub = pub_runs[name]
        pdiag = S.diagnostics(pub["curve"])
        pdist = S.period_distribution([(d, v) for d, v in pub["curve"]], sel)
        bc = round(r["final"], 2) > expect_pub[name]
        bh = round(r["final"], 2) > expect_host[name]
        beat_champ = beat_champ or bc
        beat_host = beat_host or bh
        results["roads"][name] = {
            "window": [s, e], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "worst_close_date": diag["worst_close_date"],
                         "placebo_beaten": beaten, "placebo_finals": pfinals,
                         "dial_log": r["dial_log"],
                         "dial_fires": sum(1 for x in r["dial_log"] if x["w"] < 1.0),
                         "dial_evals": len(r["dial_log"]),
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "unscaled_host": {"final": round(host["final"], 2),
                              "costs": round(host["costs"], 2),
                              "orders": host["orders"],
                              "max_dd_pct": hdiag["max_dd_pct"],
                              "max_dd_date": hdiag["max_dd_date"],
                              "period_distribution": hdist,
                              "curve": [[d, round(v, 4)] for d, v in host["curve"]]},
            "published_form_house5": {
                "final": round(pub["final"], 2), "costs": round(pub["costs"], 2),
                "orders": pub["orders"], "halts": pub["halts"],
                "max_dd_pct": pdiag["max_dd_pct"],
                "max_dd_date": pdiag["max_dd_date"],
                "period_distribution": pdist,
                "curve": [[d, round(v, 4)] for d, v in pub["curve"]]},
            "dial_contribution_vs_host": round(r["final"] - host["final"], 2),
            "beats_published_champion": bc, "beats_unscaled_host": bh,
        }
        print(f"{name} MY-FORM ${r['final']:,.2f} (host ${host['final']:,.2f}, "
              f"champion ${expect_pub[name]:,.2f}, SPY ${spy:,.2f}) "
              f"dial {results['roads'][name]['my_rules']['dial_fires']}/"
              f"{len(r['dial_log'])} fires, placebos {beaten}/20, "
              f"maxDD {diag['max_dd_pct']}%", flush=True)

    # ---------------- confirmation (Terry's rule, pre-registered)
    if beat_champ or beat_host:
        folds, halves = {}, {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rm = run_dial(pb, dec_fixed, sel, s, e)
            rh = S.run_native(pb, dec_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            folds[str(yr)] = {
                "my_rules_final": round(rm["final"], 2),
                "host_final": round(rh["final"], 2),
                "published_final": round(rp["final"], 2),
                "my_rules_max_dd_pct": S.diagnostics(rm["curve"])["max_dd_pct"],
                "beats_host": rm["final"] > rh["final"],
                "beats_published": rm["final"] > rp["final"]}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rm = run_dial(pb, dec_fixed, sel, s, e)
            rh = S.run_native(pb, dec_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            halves[hn] = {
                "my_rules_final": round(rm["final"], 2),
                "host_final": round(rh["final"], 2),
                "published_final": round(rp["final"], 2),
                "my_rules_max_dd_pct": S.diagnostics(rm["curve"])["max_dd_pct"],
                "beats_host": rm["final"] > rh["final"],
                "beats_published": rm["final"] > rp["final"]}
        hw = sum(1 for v in folds.values() if v["beats_host"])
        pw = sum(1 for v in folds.values() if v["beats_published"])
        hh = sum(1 for v in halves.values() if v["beats_host"])
        ph = sum(1 for v in halves.values() if v["beats_published"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full rule set vs unscaled host AND "
                      "vs published house form",
            "year_folds": folds, "half_windows": halves,
            "fold_wins_vs_host": f"{hw}/10", "half_wins_vs_host": f"{hh}/2",
            "fold_wins_vs_published": f"{pw}/10",
            "half_wins_vs_published": f"{ph}/2",
            "confirmed_vs_host": hw >= 6 and hh >= 1,
            "confirmed_vs_published": pw >= 6 and ph >= 1}
        print(f"CONFIRMATION vs host: folds {hw}/10 halves {hh}/2 "
              f"confirmed={results['confirmation']['confirmed_vs_host']} | "
              f"vs published: folds {pw}/10 halves {ph}/2 "
              f"confirmed={results['confirmation']['confirmed_vs_published']}",
              flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
