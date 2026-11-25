#!/usr/bin/env python3
"""
V13 BEST-RULES — BLEND-ETF-CHASSIS. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY BLEND (no capital split anywhere):
  - Chassis: champion Value+Momentum, count 5, quarterly re-pick, equal
    weight, next-open execution (v12 holdings-champion-vm plumbing,
    imported read-only; decisions precomputed by that chassis).
  - Gate: monthly SPY trend (3/6/12-month sign blend, >=2 of 3 positive
    = risk-on), from the v3 ETF cache (read-only).
  - Risk-on: 100% of pot in current top-5. Risk-off: 100% parked in GLD
    if GLD passes the same trend test at the gate date, else cash.
  - Quarterly rankings update on paper while risk-off; re-entry uses the
    freshest top-5. NO floor / ladder / stop. Costs 0.10%/side +
    $0.01/sell order on every trade incl. gate flips and GLD trades.

PARENTS (same roads, for the adoption bar = beat BOTH):
  - Parent 1: V+M count-5 native (no floor), via the v12 chassis.
  - Parent 2: monthly ETF trend sleeve alone, via v4 blend.py's
    in-blend Sleeve A engine (floor-free; the published parent never
    halted, so this reproduces its published finals).

INTEGRITY GATE: chassis house count-5 must reproduce the published
champion finals before any v13 number is taken.

CONFIRMATION (pre-registered in the spec): if the blend beats the
champion house form on any road -> fresh-$100 calendar-year folds
2017..2026 + DECADE half-windows, blend vs published house form
(count 5 + floor chassis); confirmed requires >=6/10 folds AND >=1/2
halves.
"""
import bisect
import importlib.util
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
END = "2026-11-20"
SEEDS = list(range(1, 21))
COUNT = 5
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", os.path.join(
    BT, "v12-completions", "holdings-champion-vm", "run_sweep.py"))
A_MOD = load_module("etf_sleeve_monthly", os.path.join(
    BT, "v3", "etf-trend-sleeve-monthly.py"))
sys.path.insert(0, os.path.join(BT, "v4"))
BLEND = load_module("v4_blend", os.path.join(BT, "v4", "blend.py"))

A_CAL = A_MOD.CAL


def trend_pos(ticker, date):
    """Number of positive trend signs (of 3) for ticker at the last ETF-
    calendar date <= date; None if unavailable."""
    i = bisect.bisect_right(A_CAL, date) - 1
    if i < 0:
        return None
    d = A_CAL[i]
    try:
        tv = A_MOD.trend_and_vol(ticker, d)
    except Exception:
        return None
    if tv is None:
        return None
    return tv[0]


def run_blend(pb, dec, sel_dates, start, end, placebo_seed=None):
    """Clean implementation of the frozen spec (single pending-action
    list executed at each open)."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    days = [d for d in pb.dates if start <= d <= end]
    sel_set = set(sel_dates)
    month_ends = set()
    for j, d in enumerate(days):
        if j == len(days) - 1 or days[j + 1][5:7] != d[5:7]:
            month_ends.add(d)

    cash = START_CASH
    positions = {}
    gld = 0.0
    costs = 0.0
    orders = 0
    trades = []
    curve = []
    picks = []
    mode = None
    actions = []            # list of action tuples for next open
    gate_log = []
    flips = 0

    def gld_price(d, kind):
        i = bisect.bisect_right(A_CAL, d) - 1
        if i < 0:
            return None
        ad = A_CAL[i]
        return A_MOD.open_on("GLD", ad) if kind == "o" else A_MOD.close_on("GLD", ad)

    def total_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        if gld > 0:
            c = gld_price(d, "c")
            if c:
                v += gld * c
        return v

    def sell_stocks(d, reason):
        nonlocal cash, costs, orders
        for t in list(positions):
            b = pb.bar(t, d)
            if not b:
                continue
            val = positions[t] * b["o"]
            c = val * COST_RATE + SELL_FEE
            cash += val - c
            costs += c
            orders += 1
            trades.append((d, t, "SELL", round(val, 2), reason))
            del positions[t]

    def sell_gld(d, reason):
        nonlocal cash, costs, orders, gld
        if gld <= 0:
            return
        p = gld_price(d, "o")
        if not p:
            return
        val = gld * p
        c = val * COST_RATE + SELL_FEE
        cash += val - c
        costs += c
        orders += 1
        trades.append((d, "GLD", "SELL", round(val, 2), reason))
        gld = 0.0

    def buy_gld_all(d, reason):
        nonlocal cash, costs, orders, gld
        if cash <= 0.01:
            return
        p = gld_price(d, "o")
        if not p:
            return
        val = cash / (1 + COST_RATE)
        c = val * COST_RATE
        gld += val / p
        cash -= val + c
        costs += c
        orders += 1
        trades.append((d, "GLD", "BUY", round(val, 2), reason))

    def rebalance_stocks(d, reason):
        nonlocal cash, costs, orders
        if not picks:
            sell_stocks(d, reason + "-nopicks")
            return
        opens = {}
        for t in set(list(positions) + list(picks)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        eq_open = cash + sum(positions[t] * opens[t]
                             for t in positions if t in opens)
        each = eq_open / len(picks)
        targets = {t: each for t in picks}
        for t in list(positions):
            if t not in opens:
                continue
            cur = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt
                c = sv * COST_RATE + SELL_FEE
                cash += sv - c
                costs += c
                orders += 1
                trades.append((d, t, "SELL", round(sv, 2), reason))
                positions[t] -= sv / opens[t]
                if positions[t] < 1e-9:
                    del positions[t]
        for t in picks:
            if t not in opens:
                continue
            cur = positions.get(t, 0.0) * opens[t]
            bv = targets[t] - cur
            if bv > 0.005:
                bv = min(bv, cash / (1 + COST_RATE))
                if bv <= 0.005:
                    continue
                c = bv * COST_RATE
                cash -= bv + c
                costs += c
                orders += 1
                trades.append((d, t, "BUY", round(bv, 2), reason))
                positions[t] = positions.get(t, 0.0) + bv / opens[t]

    for di, d in enumerate(days):
        # ---- open executions
        for act in actions:
            if act[0] == "enter_stocks":
                sell_gld(d, "gate-on")
                rebalance_stocks(d, "gate-on")
            elif act[0] == "park":
                sell_stocks(d, "gate-off")
                if act[1]:
                    buy_gld_all(d, "gate-off-park-gld")
            elif act[0] == "sell_gld_only":
                sell_gld(d, "park-refresh-cash")
            elif act[0] == "buy_gld_only":
                buy_gld_all(d, "park-refresh-gld")
            elif act[0] == "rebalance":
                rebalance_stocks(d, "quarterly")
        actions = []

        # ---- mark to close
        curve.append((d, total_close(d)))

        if di == len(days) - 1:
            break

        # ---- close-time decisions
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = min(COUNT, len(pool))
                if rng is not None:
                    picks = rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                if mode == "on":
                    actions.append(("rebalance",))
        if d in month_ends:
            npos = trend_pos("SPY", d)
            if npos is not None:
                new_mode = "on" if npos >= 2 else "off"
                if mode is None:
                    mode = new_mode
                    if mode == "on":
                        actions.append(("enter_stocks",))
                    else:
                        gpos = trend_pos("GLD", d)
                        actions.append(("park", bool(gpos is not None and gpos >= 2)))
                    gate_log.append((d, "init-" + mode))
                elif new_mode != mode:
                    mode = new_mode
                    flips += 1
                    if mode == "on":
                        actions.append(("enter_stocks",))
                    else:
                        gpos = trend_pos("GLD", d)
                        actions.append(("park", bool(gpos is not None and gpos >= 2)))
                    gate_log.append((d, "flip-" + mode))
                elif mode == "off":
                    gpos = trend_pos("GLD", d)
                    want_gld = bool(gpos is not None and gpos >= 2)
                    if want_gld and gld <= 0:
                        actions.append(("buy_gld_only",))
                    elif not want_gld and gld > 0:
                        actions.append(("sell_gld_only",))

    # ---- final liquidation at last close (parent convention)
    last = days[-1]
    final = cash
    for t, sh in list(positions.items()):
        c = pb.close_on_or_before(t, last)
        if c:
            val = sh * c
            final += val - (val * COST_RATE + SELL_FEE)
            costs += val * COST_RATE + SELL_FEE
            orders += 1
    if gld > 0:
        c = gld_price(last, "c")
        if c:
            val = gld * c
            final += val - (val * COST_RATE + SELL_FEE)
            costs += val * COST_RATE + SELL_FEE
            orders += 1
    return {"final": final, "costs": costs, "orders": orders,
            "curve": curve, "trades": trades, "gate_log": gate_log,
            "flips": flips}


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "blend-etf-chassis",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {
            "chassis": "Value+Momentum champion ranking, count 5, quarterly, equal weight",
            "gate": "monthly SPY 3/6/12 sign blend, >=2 of 3 positive = risk-on",
            "weights": "100% chassis when risk-on; 100% parked when risk-off; no split",
            "parking": "GLD if GLD passes same trend test at gate date, else cash",
            "protections": "gate only; NO floor/ladder/stop",
            "costs": "0.10%/side + $0.01 per sell order",
            "start_cash": 100.0},
        "published_blend_form": {"DECADE": 211.80, "VAL": 132.73, "CONT": 181.23,
                                 "note": "v4/v10 original 50/50 blend; LONG never published"},
        "champion_vm_house": {"LONG": 1415.62, "DECADE": 667.35,
                              "CONT": 544.47, "VAL": 288.05},
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None}

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

    # ---------------- integrity gate
    expect = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    pub_runs = {}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, decx, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - expect[name]) < 0.02
        results["integrity"][name] = {"expected_house_count5": expect[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name} house-5: ${r['final']:,.2f} expected "
              f"${expect[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"
        pub_runs[name] = r

    # ---------------- parents + blend per road
    beat_champion_any = False
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        # Parent 1: V+M count-5 native (no floor), same plumbing
        p1 = S.run_native(pbx, decx, sel, s, e, 5)
        p1d = S.diagnostics(p1["curve"])
        # Parent 2: monthly ETF trend sleeve alone (v4 blend engine)
        p2 = BLEND.run_sleeveA_alone(s, e, 100.0)
        p2_curve = p2["curve"]
        p2d = S.diagnostics(p2_curve)
        # My blend
        r = run_blend(pbx, decx, sel, s, e)
        diag = S.diagnostics(r["curve"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        pfinals = []
        for seed in SEEDS:
            pr = run_blend(pbx, decx, sel, s, e, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        beats_both = (round(r["final"], 2) > round(p1["final"], 2)
                      and round(r["final"], 2) > round(p2["final"], 2))
        beats_champ = round(r["final"], 2) > expect[name]
        beat_champion_any = beat_champion_any or beats_champ
        results["roads"][name] = {
            "window": [s, e],
            "my_blend": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "gate_flips": r["flips"],
                         "gate_log": r["gate_log"],
                         "placebo_beaten": beaten,
                         "placebo_finals": pfinals,
                         "beats_both_parents": beats_both,
                         "beats_champion_house": beats_champ,
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "parent1_vm_count5_native": {
                "final": round(p1["final"], 2), "costs": round(p1["costs"], 2),
                "orders": p1["orders"], "max_dd_pct": p1d["max_dd_pct"],
                "max_dd_date": p1d["max_dd_date"],
                "curve": [[d, round(v, 4)] for d, v in p1["curve"]]},
            "parent2_etf_trend_monthly": {
                "final": round(p2["final"], 2), "costs": round(p2["costs"], 2),
                "orders": p2["orders"], "max_dd_pct": p2d["max_dd_pct"],
                "max_dd_date": p2d["max_dd_date"]},
            "champion_house_count5": {
                "final": round(pub_runs[name]["final"], 2),
                "max_dd_pct": S.diagnostics(pub_runs[name]["curve"])["max_dd_pct"]},
            "spy_final": results["spy_reference"][name]}
        print(f"{name} BLEND: ${r['final']:,.2f} DD {diag['max_dd_pct']}% "
              f"flips={r['flips']} | P1 VM ${p1['final']:,.2f} "
              f"P2 trend ${p2['final']:,.2f} | champ ${expect[name]:,.2f} "
              f"SPY ${results['spy_reference'][name]:,.2f} | "
              f"placebos {beaten}/20 beats_both={beats_both}", flush=True)

    # ---------------- confirmation (pre-registered)
    if beat_champion_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rc = run_blend(pb, dec_fixed, sel, s, e)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            folds[str(yr)] = {"blend_final": round(rc["final"], 2),
                              "published_final": round(rp["final"], 2),
                              "blend_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                              "blend_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rc = run_blend(pb, dec_fixed, sel, s, e)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            halves[hn] = {"blend_final": round(rc["final"], 2),
                          "published_final": round(rp["final"], 2),
                          "blend_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                          "blend_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["blend_win"])
        hwins = sum(1 for v in halves.values() if v["blend_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my blend vs published house form",
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
