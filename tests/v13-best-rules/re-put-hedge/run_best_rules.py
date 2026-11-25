#!/usr/bin/env python3
"""
V13 BEST RULES — re-put-hedge (Protective-Put Hedge via CBOE PPUT).

Frozen spec: BEST-RULES-SPEC.md in this folder (written before this run).
MY RULES: 75% champion V+M sleeve (native quarterly selection, unchanged) +
25% CBOE PPUT index sleeve; rebalanced to 75/25 each January (first trading
day) at the house transfer schedule (0.10% sell + 0.10% buy on transferred
value + $0.05); NO floor, no stop, no sit-out. $100 pots.

Comparators in the same script/engine/data:
  (i)   unhedged host — 100% champion, no floor (the premium reference);
  (ii)  published-weight blend — 50/50, annual, no floor (v7 blend_curves
        verbatim, floor disabled) — isolates the weight choice;
  (iii) PPUT standalone, no floor (native form);
  (iv)  SPY buy-and-hold net (scale).
Placebos: 20 random-rank champion-sleeve twins (engine placebo_rng, the
family's house design since v7), each blended 75/25 with the same PPUT
sleeve, annual rebalance, no floor.

Plumbing is reused READ-ONLY from v7 (books, engine, PPUT CSV, sleeve
builders). Before any v13 number is taken, each stage reproduces the
published v7/v11 finals to the cent through O.run_window (his-rules 50/50
floored blend + PPUT standalone) for its book.

Option pricing: none is done here. PPUT is the published Cboe total-return
index; its methodology embeds the put's costs inside the level (v7 FR3/FR4
treatment, unchanged). PPUT launched 2015-06-30; earlier levels are Cboe
back-calculations (disclosed on LONG/DECADE).

Chassis (as v7/v10): LONG + DECADE on the long-hold 2010 book; CONT + VAL
on the honest book.

Staging (memory discipline on a shared cell): run one stage per process;
each stage writes its own JSON immediately.
  python3 run_best_rules.py honest   -> stage_honest.json (integrity+CONT+VAL)
  python3 run_best_rules.py lh       -> stage_lh.json     (integrity+LONG+DECADE)
  python3 run_best_rules.py merge    -> results.json (+ confirmation if any
                                        road beat the champion; folds then
                                        run inside the merge process)
"""
import importlib.util
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(HERE, "..", "..", "v7", "re-put-hedge", "re-put-hedge.py")


def _load(path):
    spec = importlib.util.spec_from_file_location("orig_put_hedge", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


O = _load(V7)
E = O.E
POT = 100.0
W_CHAMP, W_PPUT = 0.75, 0.25

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20", "lh"),
    "DECADE": ("2016-11-21", "2026-11-20", "lh"),
    "CONT":   ("2019-01-02", "2026-11-20", "honest"),
    "VAL":    ("2023-01-03", "2026-11-20", "honest"),
}
CHAMP_BAR = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED_FLOORED_BLEND = {"LONG": 1017.61, "DECADE": 493.87,
                           "CONT": 384.30, "VAL": 221.71}
PUBLISHED_NATIVE_PPUT = {"LONG": 501.31, "DECADE": 294.89,
                         "CONT": 253.62, "VAL": 165.74}
PUBLISHED_INTEG = {
    "continuous": {"champion": 544.47, "pput_standalone": 253.62,
                   "pput_blend": 384.30, "spy_blend": 420.74},
    "validation": {"champion": 288.05, "pput_standalone": 165.74,
                   "pput_blend": 221.71, "spy_blend": 236.81},
    "long2010": {"champion": 85.34, "pput_standalone": 501.31,
                 "pput_blend": 1017.61, "spy_blend": 1283.53}}


# --------------------------------------------------------------------------
# Weighted blend — mirrors v7 blend_curves arithmetic exactly (January
# first-trading-day rebalance; transfer cost = transfer*0.002 + $0.05),
# generalized to target weights and with NO floor.
# --------------------------------------------------------------------------
def blend_weighted(curveA, curveB, wA):
    A, B = dict(curveA), dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates, seen_jan = set(), set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)
    scaleA = scaleB = 1.0
    lastA = lastB = None
    curve, rebalances, transfer_costs = [], [], 0.0
    for d in dates:
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        va, vb = scaleA * lastA, scaleB * lastB
        tot = va + vb
        if d in jan_dates:
            targetA = wA * tot
            transfer = abs(va - targetA)
            cost = transfer * 0.002 + 0.05
            tot -= cost
            transfer_costs += cost
            scaleA = (wA * tot) / lastA
            scaleB = ((1.0 - wA) * tot) / lastB
            rebalances.append({"date": d, "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
        curve.append((d, tot))
    return curve, {"final": curve[-1][1], "transfer_costs": transfer_costs,
                   "rebalances": rebalances, "n_rebalances": len(rebalances),
                   "max_dd": O.max_dd(curve)}


def distribution(curve, start_val=POT):
    """Per-period (calendar-year) distribution + new-high stretch."""
    years = {}
    prev_close = start_val
    prev_year = None
    for d, v in curve:
        y = d[:4]
        if prev_year is not None and y != prev_year:
            years[prev_year] = prev_close
        prev_close, prev_year = v, y
    years[prev_year] = prev_close
    rets, base = [], start_val
    for y in sorted(years):
        rets.append((y, years[y] / base - 1.0))
        base = years[y]
    vals = [r for _, r in rets]
    med = statistics.median(vals) if vals else 0.0
    pos = sum(1 for r in vals if r > 0)
    best = max(rets, key=lambda t: t[1]) if rets else (None, 0.0)
    worst = min(rets, key=lambda t: t[1]) if rets else (None, 0.0)
    streak = longest = 0
    for r in vals:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    peak, last_high_idx, max_gap = -1.0, 0, 0
    for i, (_, v) in enumerate(curve):
        if v > peak:
            peak = v
            max_gap = max(max_gap, i - last_high_idx)
            last_high_idx = i
    max_gap = max(max_gap, len(curve) - 1 - last_high_idx)
    return {
        "median_year_pct": round(med * 100, 2),
        "mean_year_pct_secondary": round(statistics.mean(vals) * 100, 2)
        if vals else 0.0,
        "share_positive": f"{pos}/{len(vals)}",
        "share_positive_pct": round(100.0 * pos / len(vals), 1) if vals else 0.0,
        "best_year": [best[0], round(best[1] * 100, 2)],
        "worst_year": [worst[0], round(worst[1] * 100, 2)],
        "longest_losing_year_streak": longest,
        "longest_stretch_between_new_highs_days": max_gap,
        "year_returns_pct": {y: round(r * 100, 2) for y, r in rets},
    }


def road_run(pb, eq, so, sd, ed, pput_rows, pput_dates):
    dates = [d for d in pb.dates if sd <= d <= ed]
    champ75 = E.run_pot(pb, eq, so, sd, ed, W_CHAMP * POT, 0.0, [],
                        quiet=True)
    champ50 = E.run_pot(pb, eq, so, sd, ed, 50.0, 0.0, [], quiet=True)
    host100 = E.run_pot(pb, eq, so, sd, ed, POT, 0.0, [], quiet=True)
    pput25, fb25 = O.index_sleeve_curve(pput_rows, pput_dates, dates,
                                        cash=W_PPUT * POT)
    pput50, _ = O.index_sleeve_curve(pput_rows, pput_dates, dates, cash=50.0)
    pput100, _ = O.index_sleeve_curve(pput_rows, pput_dates, dates, cash=POT)
    spy100_curve = O.spy_sleeve_curve(pb, dates, cash=POT)
    spy_net, _ = E.spy_net(pb, sd, ed, POT)

    mine_curve, mine_info = blend_weighted(champ75["curve"], pput25, W_CHAMP)
    pub_curve, pub_info = O.blend_curves(champ50["curve"], pput50, pot0=POT,
                                         floor=0.0, rebalance=True)
    out = {
        "window": [sd, ed], "n_dates": len(dates),
        "pput_fallback_days": fb25,
        "mine": {
            "final": round(mine_info["final"], 2),
            "max_dd_pct": round(mine_info["max_dd"] * 100, 2),
            "transfer_costs": round(mine_info["transfer_costs"], 2),
            "champ_sleeve_costs": round(champ75["costs"], 2),
            "total_costs": round(champ75["costs"]
                                 + mine_info["transfer_costs"], 2),
            "n_rebalances": mine_info["n_rebalances"],
            "orders": len(champ75["trades"]) + mine_info["n_rebalances"],
            "distribution": distribution(mine_curve),
            "curve": [[d, round(v, 4)] for d, v in mine_curve],
        },
        "unhedged_host": {
            "final": round(host100["final"], 2),
            "max_dd_pct": round(O.max_dd(host100["curve"]) * 100, 2),
            "costs": round(host100["costs"], 2),
            "orders": len(host100["trades"]),
            "distribution": distribution(host100["curve"]),
            "curve": [[d, round(v, 4)] for d, v in host100["curve"]],
        },
        "published_weight_blend_nofloor": {
            "final": round(pub_info["final"], 2),
            "max_dd_pct": round(pub_info["max_dd"] * 100, 2),
            "transfer_costs": round(pub_info["transfer_costs"], 2),
            "curve": [[d, round(v, 4)] for d, v in pub_curve],
        },
        "pput_standalone_nofloor": {
            "final": round(pput100[-1][1], 2),
            "max_dd_pct": round(O.max_dd(pput100) * 100, 2),
            "curve": [[d, round(v, 4)] for d, v in pput100],
        },
        "spy": {
            "net_final": round(spy_net, 2),
            "mark_final": round(spy100_curve[-1][1], 2),
            "max_dd_pct": round(O.max_dd(spy100_curve) * 100, 2),
            "curve": [[d, round(v, 4)] for d, v in spy100_curve],
        },
        "premium_vs_host_dollars": round(host100["final"]
                                         - mine_info["final"], 2),
        "leg_drag_vs_spy_dollars": round(spy100_curve[-1][1]
                                         - pput100[-1][1], 2),
    }
    twin_finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        ps = E.run_pot(pb, eq, so, sd, ed, W_CHAMP * POT, 0.0, [],
                       placebo_rng=rng, quiet=True)
        tc, _ = blend_weighted(ps["curve"], pput25, W_CHAMP)
        twin_finals.append(round(tc[-1][1], 2))
        print(f"    placebo seed {seed}: ${twin_finals[-1]}", flush=True)
    beaten = sum(1 for f in twin_finals if f < mine_info["final"])
    out["placebo"] = {"beaten": beaten, "of": 20,
                      "twin_finals": twin_finals,
                      "median": round(statistics.median(twin_finals), 2),
                      "max": max(twin_finals)}
    return out


def fold_run(pb, eq, so, sd, ed, pput_rows, pput_dates):
    dates = [d for d in pb.dates if sd <= d <= ed]
    if len(dates) < 20:
        return None
    champ75 = E.run_pot(pb, eq, so, sd, ed, W_CHAMP * POT, 0.0, [],
                        quiet=True)
    host = E.run_pot(pb, eq, so, sd, ed, POT, 0.0, [], quiet=True)
    pput25, _ = O.index_sleeve_curve(pput_rows, pput_dates, dates,
                                     cash=W_PPUT * POT)
    mc, _ = blend_weighted(champ75["curve"], pput25, W_CHAMP)
    spy_net, _ = E.spy_net(pb, sd, ed, POT)
    return {"window": [sd, ed], "hedged": round(mc[-1][1], 2),
            "host": round(host["final"], 2), "spy": round(spy_net, 2)}


def check_integ(integ):
    ok = True
    for w, pub in PUBLISHED_INTEG.items():
        if w not in integ:
            continue
        for k, v in pub.items():
            got = integ[w].get(k)
            if got is None or abs(got - v) > 0.011:
                ok = False
                print(f"INTEGRITY MISMATCH {w}.{k}: got {got} pub {v}",
                      flush=True)
    return ok


def stage(which):
    pput_rows = O.load_pput()
    pput_dates = [d for d, _ in pput_rows]
    stage_out = {"book": which, "roads": {}}
    if which == "honest":
        E.DATA = O.HONEST_DATA
        E.UNIVERSE = list(O.HONEST_UNIVERSE)
        pb, eq, so = O.build_vm_book()
        integ = {}
        for name, sd, ed in [("continuous", "2019-01-01", "2026-11-20"),
                             ("validation", "2023-01-01", "2026-11-20")]:
            r = O.run_window(name, pb, eq, so, sd, ed, pput_rows,
                             pput_dates, run_placebo=False)
            integ[name] = {"champion": r["champion_parent"]["final"],
                           "pput_standalone": r["pput_standalone"]["final"],
                           "pput_blend": r["pput_blend"]["final"],
                           "spy_blend": r["spy_blend"]["final"]}
            print(name, integ[name], flush=True)
        road_names = ["CONT", "VAL"]
    else:
        E.DATA = O.LH_DATA
        pb, eq, so, uni = O.build_2010_book()
        E.UNIVERSE = list(uni)
        r = O.run_window("long2010", pb, eq, so, "2010-01-04",
                         "2026-11-20", pput_rows, pput_dates,
                         run_placebo=False)
        integ = {"long2010": {"champion": r["champion_parent"]["final"],
                              "pput_standalone":
                              r["pput_standalone"]["final"],
                              "pput_blend": r["pput_blend"]["final"],
                              "spy_blend": r["spy_blend"]["final"]}}
        print("long2010", integ["long2010"], flush=True)
        road_names = ["LONG", "DECADE"]
    ok = check_integ(integ)
    stage_out["integrity_check"] = {"all_match": ok, "reproduced": integ}
    print("INTEGRITY ALL MATCH:", ok, flush=True)
    if not ok:
        with open(os.path.join(HERE, f"stage_{which}.json"), "w") as f:
            json.dump(stage_out, f, indent=1)
        sys.exit(1)
    for road in road_names:
        sd, ed, _ = ROADS[road]
        print(f"== road {road} {sd} -> {ed} ==", flush=True)
        rr = road_run(pb, eq, so, sd, ed, pput_rows, pput_dates)
        stage_out["roads"][road] = rr
        print(f"  mine ${rr['mine']['final']} (dd {rr['mine']['max_dd_pct']}%)"
              f" | host ${rr['unhedged_host']['final']} "
              f"(dd {rr['unhedged_host']['max_dd_pct']}%)"
              f" | pub50 ${rr['published_weight_blend_nofloor']['final']}"
              f" | pput ${rr['pput_standalone_nofloor']['final']}"
              f" | spy ${rr['spy']['net_final']}"
              f" | placebo {rr['placebo']['beaten']}/20", flush=True)
        with open(os.path.join(HERE, f"stage_{which}.json"), "w") as f:
            json.dump(stage_out, f, indent=1)
    print(f"STAGE {which} DONE", flush=True)


def merge():
    out = {"slug": "re-put-hedge", "program": "v13-best-rules",
           "spec": "75% champion V+M + 25% PPUT, annual rebalance, no floor",
           "champion_bar": CHAMP_BAR, "spy_reference": SPY_REF,
           "published_floored_blend": PUBLISHED_FLOORED_BLEND,
           "published_native_pput": PUBLISHED_NATIVE_PPUT,
           "roads": {}, "integrity_check": {}}
    for which in ("honest", "lh"):
        s = json.load(open(os.path.join(HERE, f"stage_{which}.json")))
        out["roads"].update(s["roads"])
        out["integrity_check"][which] = s["integrity_check"]
    beaten = [r for r in ROADS
              if out["roads"][r]["mine"]["final"] > CHAMP_BAR[r]]
    out["champion_roads_beaten_unconfirmed"] = beaten
    print("champion roads beaten (unconfirmed):", beaten, flush=True)
    if beaten:
        pput_rows = O.load_pput()
        pput_dates = [d for d, _ in pput_rows]
        books = {}
        conf = {}
        for road in beaten:
            sd, ed, which = ROADS[road]
            if which not in books:
                if which == "honest":
                    E.DATA = O.HONEST_DATA
                    E.UNIVERSE = list(O.HONEST_UNIVERSE)
                    books[which] = O.build_vm_book()
                else:
                    E.DATA = O.LH_DATA
                    pb_, eq_, so_, uni = O.build_2010_book()
                    E.UNIVERSE = list(uni)
                    books[which] = (pb_, eq_, so_)
            pb, eq, so = books[which]
            folds = []
            for y in range(int(sd[:4]), int(ed[:4]) + 1):
                fr = fold_run(pb, eq, so, max(sd, f"{y}-01-01"),
                              min(ed, f"{y}-12-31"), pput_rows, pput_dates)
                if fr:
                    fr["kind"] = "yearly"
                    folds.append(fr)
                    print(f"  fold {y}: {fr}", flush=True)
            dates = [d for d in pb.dates if sd <= d <= ed]
            mid = dates[len(dates) // 2]
            for label, fsd, fed in [("first_half", sd, mid),
                                    ("second_half", mid, ed)]:
                fr = fold_run(pb, eq, so, fsd, fed, pput_rows, pput_dates)
                if fr:
                    fr["kind"] = label
                    folds.append(fr)
                    print(f"  fold {label}: {fr}", flush=True)
            agg_h = sum(f["hedged"] for f in folds)
            agg_host = sum(f["host"] for f in folds)
            agg_spy = sum(f["spy"] for f in folds)
            wins = sum(1 for f in folds if f["hedged"] > f["host"])
            bar_pass = (agg_h > agg_host and wins > len(folds) / 2
                        and agg_h > agg_spy)
            conf[road] = {"folds": folds, "agg_hedged": round(agg_h, 2),
                          "agg_host": round(agg_host, 2),
                          "agg_spy": round(agg_spy, 2),
                          "folds_beating_host": wins,
                          "n_folds": len(folds), "frozen_bar_pass": bar_pass}
            print(f"  {road}: bar_pass={bar_pass}", flush=True)
        out["confirmation"] = conf
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("MERGE DONE", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("honest", "lh"):
        stage(cmd)
    elif cmd == "merge":
        merge()
    else:
        stage("honest")
        stage("lh")
        merge()
