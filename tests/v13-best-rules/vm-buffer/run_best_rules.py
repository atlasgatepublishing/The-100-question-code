#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-BUFFER (Value+Momentum with a hold band).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: champion V+M signal unchanged (PIT EDGAR book-to-market +
12-1 momentum, percentile ranks averaged, quarterly selection,
next-open execution, equal weight, honest ponds, program costs
0.10%/side + $0.01/sell) on the v13 base-pass host (top-2, NO floor),
with exactly one change — a SLOT-FORM BUFFER:
  - 2 slots. An incumbent keeps its slot while its combined rank <= 4
    (NMV's published 2:1 hold:buy ratio for ValMom, 10%/20%, applied
    to a buy count of 2).
  - A vacated slot is filled by the highest-ranked name not held.
  - An unscored incumbent (no rank that quarter) vacates.
  - First selection fills both slots from the top 2.

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only for
inputs, decisions, diagnostics, distributions, SPY. The buffer runner
below replicates run_episode's execution semantics exactly (pending
rebalance at next open; targets from selection-date close value; same
cost stack; end liquidation at last close net of costs).

INTEGRITY GATES (must pass before any buffered number counts):
  - house count-5 reproduces published champion finals to the cent
  - unbuffered top-2 no-floor reproduces the v13 base-pass finals

CONFIRMATION (pre-registered in the spec): if my rules beat the
published champion V+M on any road -> fresh-$100 calendar-year folds
2017..2026 + DECADE half-windows, my full rule set vs the published
house form (count 5 + floor chassis). Confirmed requires >=6/10 folds
AND >=1/2 halves. Unbuffered top-2 printed on folds as reference only.
"""
import importlib.util
import json
import os
import random
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
BUY_N = 2
HOLD_N = 4
START_CASH = 100.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)


# ------------------------------------------------------------------ buffer runner
def run_buffer(pb, dec, sel_dates, start, end, placebo_seed=None):
    """Slot-form buffer, no floor. Replicates S.run_episode semantics."""
    sel_set = set(sel_dates)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    held = []          # tickers currently targeted (the 2 slots)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
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
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for d in days:
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                if rng is not None:
                    ranked = rng.sample(sorted(dd["pool"]), len(dd["pool"]))
                else:
                    ranked = dd["ranked"]
                rank_of = {t: i + 1 for i, t in enumerate(ranked)}
                kept = [t for t in held if rank_of.get(t, 10 ** 9) <= HOLD_N]
                fills = []
                for t in ranked:
                    if len(kept) + len(fills) >= BUY_N:
                        break
                    if t not in kept:
                        fills.append(t)
                held = kept + fills
                pv = portfolio_close(d)
                each = pv / len(held)
                pending = {t: each for t in held}
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
            "trades": trades, "curve": curve, "halts": 0}


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "vm-buffer (V+M hold band, NMV 2016)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"host": "top-2 V+M, quarterly, equal weight, no floor",
                     "buffer": "slot form; incumbent kept while rank <= 4 "
                               "(NMV 2:1 hold:buy ratio); vacated slot filled "
                               "by highest-ranked non-held name",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "published_form_v12_constructed_ss10_20": {
            "finals": {"LONG": 2286.60, "DECADE": 608.91,
                       "CONT": 543.29, "VAL": 319.24},
            "note": "LONG carries the v12 fence: Nov-2016 pond applied "
                    "backwards to 2010 flatters it; like-for-like LONG "
                    "host control in v12 was $2,745.67."},
        "v13_top2_unbuffered_reference": {"LONG": 2923.60, "DECADE": 906.90,
                                          "CONT": 691.73, "VAL": 461.20},
        "champion_vm_published": {"LONG": 1415.62, "DECADE": 667.35,
                                  "CONT": 544.47, "VAL": 288.05},
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    # ---------------- inputs (v12 chassis builders, read-only caches)
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
    expect5 = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    expect2 = {"DECADE": 906.90, "CONT": 691.73, "VAL": 461.20, "LONG": 2923.60}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r5 = S.run_house(pbx, decx, sel, s, e, 5)
        r2 = S.run_native(pbx, decx, sel, s, e, 2)
        ok5 = abs(round(r5["final"], 2) - expect5[name]) < 0.02
        ok2 = abs(round(r2["final"], 2) - expect2[name]) < 0.02
        results["integrity"][name] = {
            "house_count5_expected": expect5[name],
            "house_count5_reproduced": round(r5["final"], 2), "match5": ok5,
            "top2_nofloor_expected": expect2[name],
            "top2_nofloor_reproduced": round(r2["final"], 2), "match2": ok2}
        print(f"INTEGRITY {name}: house5 ${r5['final']:,.2f} (exp "
              f"${expect5[name]}) match={ok5} | top2 ${r2['final']:,.2f} "
              f"(exp ${expect2[name]}) match={ok2}", flush=True)
        assert ok5 and ok2, f"integrity failed on {name}"

    # ---------------- my-rules run + controls per road
    beat_any = False
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        r = run_buffer(pbx, decx, sel, s, e)
        diag = S.diagnostics(r["curve"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        ctl = S.run_native(pbx, decx, sel, s, e, 2)
        cdiag = S.diagnostics(ctl["curve"])
        cdist = S.period_distribution([(d, v) for d, v in ctl["curve"]], sel)
        pfinals = []
        for seed in SEEDS:
            pr = run_buffer(pbx, decx, sel, s, e, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        beat = round(r["final"], 2) > expect5[name]
        beat_any = beat_any or beat
        results["roads"][name] = {
            "window": [s, e], "spy_final": spy,
            "my_rules_buffered_top2": {
                "final": round(r["final"], 2),
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "max_dd_pct": diag["max_dd_pct"],
                "max_dd_date": diag["max_dd_date"],
                "placebo_beaten": beaten, "placebo_finals": pfinals,
                "beats_published_champion": beat,
                "period_distribution": dist,
                "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "control_unbuffered_top2": {
                "final": round(ctl["final"], 2),
                "costs": round(ctl["costs"], 2), "orders": ctl["orders"],
                "max_dd_pct": cdiag["max_dd_pct"],
                "max_dd_date": cdiag["max_dd_date"],
                "period_distribution": cdist,
                "curve": [[d, round(v, 4)] for d, v in ctl["curve"]]},
            "band_effect_vs_control": round(r["final"] - ctl["final"], 2),
        }
        print(f"{name} BUFFERED top2 (hold<=4): ${r['final']:,.2f} "
              f"(control top2 ${ctl['final']:,.2f}, band effect "
              f"${r['final']-ctl['final']:+,.2f}; champion "
              f"${expect5[name]:,.2f}, SPY ${spy:,.2f}) placebos "
              f"{beaten}/20 maxDD {diag['max_dd_pct']}% orders="
              f"{r['orders']} costs=${r['costs']:,.2f}", flush=True)

    # ---------------- confirmation (Terry's rule, pre-registered)
    if beat_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rb = run_buffer(pb, dec_fixed, sel, s, e)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            rc = S.run_native(pb, dec_fixed, sel, s, e, 2)
            folds[str(yr)] = {
                "my_rules_final": round(rb["final"], 2),
                "published_final": round(rp["final"], 2),
                "my_rules_max_dd_pct": S.diagnostics(rb["curve"])["max_dd_pct"],
                "my_rules_win": rb["final"] > rp["final"],
                "reference_unbuffered_top2_final": round(rc["final"], 2)}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rb = run_buffer(pb, dec_fixed, sel, s, e)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            rc = S.run_native(pb, dec_fixed, sel, s, e, 2)
            halves[hn] = {
                "my_rules_final": round(rb["final"], 2),
                "published_final": round(rp["final"], 2),
                "my_rules_max_dd_pct": S.diagnostics(rb["curve"])["max_dd_pct"],
                "my_rules_win": rb["final"] > rp["final"],
                "reference_unbuffered_top2_final": round(rc["final"], 2)}
        wins = sum(1 for v in folds.values() if v["my_rules_win"])
        hwins = sum(1 for v in halves.values() if v["my_rules_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full rule set (buffered top-2, no "
                      "floor) vs published house form (count 5 + floor)",
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
