#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-TRENDGATE. Simulation only. Spec frozen in
BEST-RULES-SPEC.md BEFORE this run.

MY RULES: v13 ungated host (champion V+M signal, PIT EDGAR B/M + 12-1
momentum ranks averaged, quarterly re-pick, top-2, equal weight, no
floor, program costs 0.10%/side + $0.01/sell) plus a monthly DIAL gate:
exposure from SPY's distance to its 10-month SMA of month-end closes
(>=+5%: 100% | 0..+5%: 75% | -5%..0: 50% | <-5%: 25%; never 0%),
evaluated first trading day of each month, executed next open.

Placebos: (a) 20-seed random-pick through the same dial;
(b) 20-seed random-TIMING: host picks, exposure sequence randomly
permuted (same multiset/mean, timing destroyed).

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
INTEGRITY: house count-5 = published finals AND native count-2 =
v13 host finals, to the cent, before any v13 number counts.

CONFIRMATION (pre-registered): if my form beats the published champion
OR the ungated host on any road -> fresh-$100 calendar-year folds
2017..2026 + DECADE half-windows, my form vs the ungated host;
confirmed requires >=6/10 folds AND >=1/2 halves.
"""
import importlib.util
import json
import os
import random
import time
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
COUNT = 2


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)


# ------------------------------------------------------------------ gate
def month_end_closes(pb):
    """SPY last close per calendar month, ordered."""
    by_month = OrderedDict()
    for b in pb.bars["SPY"]:
        by_month[b["d"][:7]] = b["c"]
    return list(by_month.items())  # [(YYYY-MM, close)]


def monthly_gate_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def exposure_for(distance):
    if distance >= 0.05:
        return 1.00
    if distance >= 0.0:
        return 0.75
    if distance >= -0.05:
        return 0.50
    return 0.25


def exposure_sequence(pb, gate_dates):
    """Dial exposure at each gate date, from SPY month-end closes
    strictly before the gate date's month (needs 10 prior month-ends;
    before that, full exposure — no signal yet, host default)."""
    mec = month_end_closes(pb)
    seq = []
    for d in gate_dates:
        prior = [(m, c) for m, c in mec if m < d[:7]]
        if len(prior) < 10:
            seq.append({"date": d, "exposure": 1.0, "distance_pct": None,
                        "note": "insufficient history -> 100%"})
            continue
        last10 = [c for _, c in prior[-10:]]
        sma = sum(last10) / 10.0
        dist = prior[-1][1] / sma - 1.0
        seq.append({"date": d, "exposure": exposure_for(dist),
                    "distance_pct": round(dist * 100, 2)})
    return seq


# ------------------------------------------------------------------ engine
def run_dial(pb, dec, sel_dates, gate_dates, exposures, start, end,
             placebo_seed=None):
    """Host engine + dial. exposures: {gate_date: exposure}.
    Quarterly dates adopt new picks; gate dates (incl. quarterly dates,
    which are also month starts) set exposure. Targets execute next open.
    Returns final/costs/orders/curve/trades."""
    sel_set = set(sel_dates)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = 100.0
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    pending = None
    picks = []
    exposure = 1.0

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
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
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", round(sh, 6), opens[t],
                               round(sell_val, 2), round(c, 2)))
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
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(sh, 6), opens[t],
                               round(buy_val, 2), round(c, 2)))
        total_costs += cost

    def make_targets(d):
        if not picks:
            return {}
        pv = portfolio_close(d)
        each = exposure * pv / len(picks)
        return {t: each for t in picks}

    for d in days:
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        changed = False
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = min(COUNT, len(pool))
                if rng is not None:
                    picks = rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                changed = True
        if d in exposures:
            exposure = exposures[d]
            changed = True
        if changed and picks:
            pending = make_targets(d)
        curve.append((d, portfolio_close(d)))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6),
                           c_, round(val, 2), round(cst, 2)))
    return {"final": cash, "costs": total_costs, "orders": len(trades),
            "curve": curve, "trades": trades}


def main():
    t0 = time.time()
    HOST = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73, "VAL": 461.20}
    PUB = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    results = {
        "program": "v13-best-rules", "family": "vm-trendgate",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"host": "V+M top-2, no floor, quarterly",
                     "gate": "DIAL monthly: SPY vs 10-mo SMA distance -> "
                             "100/75/50/25% exposure, never 0%",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "host_ungated_v13": HOST, "published_champion": PUB,
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

    # ---------------- integrity: house-5 = published; native-2 = host
    host_runs = {}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r5 = S.run_house(pbx, decx, sel, s, e, 5)
        ok5 = abs(round(r5["final"], 2) - PUB[name]) < 0.02
        r2 = S.run_native(pbx, decx, sel, s, e, COUNT)
        ok2 = abs(round(r2["final"], 2) - HOST[name]) < 0.02
        results["integrity"][name] = {
            "house5_expected": PUB[name], "house5_reproduced": round(r5["final"], 2),
            "house5_match": ok5, "host2_expected": HOST[name],
            "host2_reproduced": round(r2["final"], 2), "host2_match": ok2}
        print(f"INTEGRITY {name}: house5 ${r5['final']:,.2f} (exp {PUB[name]}) "
              f"match={ok5} | host2 ${r2['final']:,.2f} (exp {HOST[name]}) "
              f"match={ok2}", flush=True)
        assert ok5 and ok2, f"integrity failed on {name}"
        host_runs[name] = r2

    # ---------------- my-rules run per road
    beat_any = False
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        gates = monthly_gate_dates(pbx, s, e)
        seq = exposure_sequence(pbx, gates)
        expo = {g["date"]: g["exposure"] for g in seq}
        spy = S.spy_final(pbx, s, e)
        r = run_dial(pbx, decx, sel, gates, expo, s, e)
        diag = S.diagnostics(r["curve"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        hdiag = S.diagnostics(host_runs[name]["curve"])
        hdist = S.period_distribution(
            [(d, v) for d, v in host_runs[name]["curve"]], sel)
        # (a) random-pick placebos through the same dial
        pick_finals = []
        for seed in SEEDS:
            pr = run_dial(pbx, decx, sel, gates, expo, s, e, placebo_seed=seed)
            pick_finals.append(round(pr["final"], 2))
        pick_beaten = sum(1 for f in pick_finals if f < r["final"])
        # (b) random-timing placebos: permuted exposure sequence, real picks
        expo_vals = [expo[g] for g in gates]
        time_finals = []
        for seed in SEEDS:
            rngt = random.Random(1000 + seed)
            perm = expo_vals[:]
            rngt.shuffle(perm)
            pexpo = {g: v for g, v in zip(gates, perm)}
            pr = run_dial(pbx, decx, sel, gates, pexpo, s, e)
            time_finals.append(round(pr["final"], 2))
        time_beaten = sum(1 for f in time_finals if f < r["final"])
        tsrt = sorted(time_finals)
        time_median = tsrt[10] if len(tsrt) % 2 == 0 else tsrt[len(tsrt) // 2]
        if len(tsrt) % 2 == 0:
            time_median = round((tsrt[9] + tsrt[10]) / 2, 2)
        beat = round(r["final"], 2) > PUB[name] or round(r["final"], 2) > HOST[name]
        beat_any = beat_any or beat
        mean_expo = round(sum(expo_vals) / len(expo_vals), 3)
        results["roads"][name] = {
            "window": [s, e], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "mean_exposure": mean_expo,
                         "exposure_sequence": seq,
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "host_ungated": {"final": round(host_runs[name]["final"], 2),
                             "costs": round(host_runs[name]["costs"], 2),
                             "orders": host_runs[name]["orders"],
                             "max_dd_pct": hdiag["max_dd_pct"],
                             "max_dd_date": hdiag["max_dd_date"],
                             "period_distribution": hdist,
                             "curve": [[d, round(v, 4)] for d, v in
                                       host_runs[name]["curve"]]},
            "placebos_random_pick": {"beaten": pick_beaten, "finals": pick_finals},
            "placebos_random_timing": {"beaten": time_beaten,
                                       "median": time_median,
                                       "finals": time_finals},
            "beats_champion": round(r["final"], 2) > PUB[name],
            "beats_host": round(r["final"], 2) > HOST[name],
        }
        print(f"{name} MY-RULES dial: ${r['final']:,.2f} DD {diag['max_dd_pct']}% "
              f"(host ${HOST[name]:,.2f} DD {hdiag['max_dd_pct']}%, champ "
              f"${PUB[name]:,.2f}, SPY ${spy:,.2f}) pick-placebos {pick_beaten}/20 "
              f"timing-placebos {time_beaten}/20 (median ${time_median:,.2f}) "
              f"meanExpo {mean_expo} orders={r['orders']} costs=${r['costs']:,.2f}",
              flush=True)

    # ---------------- confirmation (pre-registered)
    if beat_any:
        folds, halves = {}, {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            gates = monthly_gate_dates(pb, s, e)
            seq = exposure_sequence(pb, gates)
            expo = {g["date"]: g["exposure"] for g in seq}
            rc = run_dial(pb, dec_fixed, sel, gates, expo, s, e)
            rp = S.run_native(pb, dec_fixed, sel, s, e, COUNT)
            folds[str(yr)] = {"my_rules_final": round(rc["final"], 2),
                              "host_final": round(rp["final"], 2),
                              "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                              "my_rules_win": rc["final"] > rp["final"]}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            gates = monthly_gate_dates(pb, s, e)
            seq = exposure_sequence(pb, gates)
            expo = {g["date"]: g["exposure"] for g in seq}
            rc = run_dial(pb, dec_fixed, sel, gates, expo, s, e)
            rp = S.run_native(pb, dec_fixed, sel, s, e, COUNT)
            halves[hn] = {"my_rules_final": round(rc["final"], 2),
                          "host_final": round(rp["final"], 2),
                          "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                          "my_rules_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_rules_win"])
        hwins = sum(1 for v in halves.values() if v["my_rules_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full rule set vs ungated host",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={results['confirmation']['confirmed']}", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
