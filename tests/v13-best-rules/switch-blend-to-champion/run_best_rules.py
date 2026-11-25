#!/usr/bin/env python3
"""
V13 BEST-RULES — SWITCH-BLEND-TO-CHAMPION (dial switch). Spec frozen
in BEST-RULES-SPEC.md before this run. Simulation only.

My rules: champion-form first (V+M top 2, quarterly, no floor), then a
DIAL into the v13 blend: N-F3 target weight ramps 0% -> 35% in four
equal quarterly steps centred on the road's midpoint selection date H
(H-2q: 8.75%, H-1q: 17.5%, H: 26.25%, H+1q+: 35%); V+M weight is the
remainder, terminal 65/35 = the v13 blend. N-F3 leg: top 5, membership
re-picked semiannually (Jan/Jul); off-cycle first activation takes the
current ranking; other non-membership quarters scale holdings to the
restored budget. NO floor. $100 pots, program costs, PIT data only.

Plumbing: imports the v10 combo module read-only (FastPriceBook,
Scorer, Sleeve mechanics, spliced price book, cadence dates) — the
same plumbing whose cross-check reproduced the original combo CONT
$532.39 to the cent. Integrity gate below re-runs that reproduction
before any v13 number is taken.
"""
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/combo-vm-nf3/combo-vm-nf3-v10.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v10 = _load("combo_v10", V10)
champ = v10.champ

NF3_MAX = 0.35
START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
ROADS = {
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT": ("2019-01-02", "2026-11-20"),
    "VAL": ("2023-01-03", "2026-11-20"),
}
HALF_WINDOWS = {
    "DECADE-H1": ("2016-11-21", "2021-11-20"),
    "DECADE-H2": ("2021-11-21", "2026-11-20"),
    "CONT-H1": ("2019-01-02", "2022-12-30"),
    "CONT-H2": ("2023-01-03", "2026-11-20"),
}


def log(*a):
    print(*a, flush=True)


def vm_top2(scorer, d):
    """Champion ranking recomputed from the scorer's score dict,
    truncated to the top 2 (percentile ranks identical to champ)."""
    scores, _picks5 = scorer.vm(d)
    if len(scores) < 5:
        return scores, []
    vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
    mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
    return scores, sorted(combined, key=lambda t: -combined[t])[:2]


def ramp_weights(sel_dates, start, end):
    """N-F3 target weight per quarterly selection date: the dial.
    H = first selection date on/after the window's calendar midpoint.
    Returns (dict date->weight, H)."""
    s = _date(int(start[:4]), int(start[5:7]), int(start[8:10]))
    e = _date(int(end[:4]), int(end[5:7]), int(end[8:10]))
    mid = s + timedelta(days=(e - s).days // 2)
    mid_s = mid.isoformat()
    H = None
    for d in sel_dates:
        if d >= mid_s:
            H = d
            break
    if H is None:
        H = sel_dates[-1]
    hi = sel_dates.index(H)
    w = {}
    for i, d in enumerate(sel_dates):
        step = i - (hi - 2)  # 0 at H-2q, 1 at H-1q, 2 at H, 3 at H+1q
        if step < 0:
            w[d] = 0.0
        elif step >= 3:
            w[d] = NF3_MAX
        else:
            w[d] = NF3_MAX * (step + 1) / 4.0
    return w, H


def run_switch(pb, scorer, start, end, placebo_rng=None, label=""):
    """My-rules dial-switch engine. Sleeve mechanics reuse the v10
    Sleeve helpers verbatim; selection implements the frozen spec."""
    Sleeve = v10.Sleeve
    vm = Sleeve("VM", START_CASH)
    f3 = Sleeve("NF3", 0.0)
    sleeves = [vm, f3]
    q_dates = v10.cadence_dates(pb, start, end, "quarterly")
    vm_sel = set(q_dates)
    nf3_sel = set(v10.cadence_dates(pb, start, end, "semiannual"))
    weights, H = ramp_weights(q_dates, start, end)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    pools = []

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    def liquidate(d, tag):
        for s in sleeves:
            for t in list(s.positions):
                px = pb.close_on_or_before(t, d)
                if px:
                    val = s.positions[t] * px
                    c = val * 0.001 + 0.01
                    s.cash += val - c
                    s.costs += c
                    s.trades.append((d, s.name, tag, s.positions[t],
                                     px, val, c))
            s.positions = {}

    for d in days:
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = v10.sleeve_sells(
                        pb, s, d, targets)
                    budgets[s.name] = budget
            vals = {s.name: s.open_value(pb, d) for s in sleeves}
            excess = {n: vals[n] - budgets.get(n, vals[n]) for n in vals}
            if excess["VM"] > 0.005 and excess["NF3"] < -0.005:
                amt = min(excess["VM"], -excess["NF3"], vm.cash)
                if amt > 0.005:
                    vm.cash -= amt
                    f3.cash += amt
            elif excess["NF3"] > 0.005 and excess["VM"] < -0.005:
                amt = min(excess["NF3"], -excess["VM"], f3.cash)
                if amt > 0.005:
                    f3.cash -= amt
                    vm.cash += amt
            for s in sleeves:
                if s.pending is not None:
                    targets, _ = s.pending
                    v10.sleeve_buys(pb, s, d, targets,
                                    opens_by_sleeve[s.name])
                    s.pending = None
        if d in vm_sel:
            vm_pool, vm_picks = vm_top2(scorer, d)
            f3_pool, f3_picks5 = scorer.nf3(d)
            if placebo_rng is not None and len(vm_pool) >= 5:
                vm_picks = placebo_rng.sample(sorted(vm_pool), 2)
            combined = combined_close(d)
            w_f3 = weights[d]
            vm_budget = combined * (1.0 - w_f3)
            f3_budget = combined * w_f3
            if len(vm_pool) >= 5 and vm_picks:
                vm.pending = ({t: vm_budget / len(vm_picks)
                               for t in vm_picks}, vm_budget)
            if w_f3 > 0.0:
                if d in nf3_sel or not f3.positions:
                    f3_picks = list(f3_picks5)
                    if placebo_rng is not None and len(f3_pool) >= 5:
                        f3_picks = placebo_rng.sample(sorted(f3_pool), 5)
                    if len(f3_pool) >= 5 and f3_picks:
                        f3.pending = ({t: f3_budget / len(f3_picks)
                                       for t in f3_picks}, f3_budget)
                else:
                    cur = sorted(f3.positions)
                    if cur:
                        f3.pending = ({t: f3_budget / len(cur)
                                       for t in cur}, f3_budget)
            pools.append((d, len(vm_pool), list(vm_picks),
                          len(f3_pool), round(w_f3, 4),
                          round(combined, 2)))
        curve.append((d, combined_close(d)))
    last = days[-1]
    liquidate(last, "SELL-END")
    final = vm.cash + f3.cash
    return {"label": label, "final": final,
            "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "orders": len(vm.trades) + len(f3.trades),
            "curve": curve, "pools": pools, "H": H}


def diagnostics(curve):
    return v10.diagnostics(curve)


def period_distribution(curve):
    """Quarterly periods: $ change per calendar quarter from the
    daily curve (quarter-end values; first period starts at $100)."""
    qend = {}
    order = []
    for d, v in curve:
        q = (d[:4], (int(d[5:7]) - 1) // 3)
        if q not in qend:
            order.append(q)
        qend[q] = v
    changes = []
    prev = START_CASH
    ends = []
    for q in order:
        ends.append(qend[q])
        changes.append(round(qend[q] - prev, 2))
        prev = qend[q]
    if not changes:
        return {}
    srt = sorted(changes)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2.0
    streak = best_streak = 0
    for c in changes:
        streak = streak + 1 if c < 0 else 0
        best_streak = max(best_streak, streak)
    peak = -1.0
    since = longest = 0
    for v in [START_CASH] + ends:
        if v > peak:
            peak = v
            since = 0
        else:
            since += 1
            longest = max(longest, since)
    return {
        "periods": n,
        "median_period_usd": round(median, 2),
        "share_positive_pct": round(
            100.0 * sum(1 for c in changes if c > 0) / n, 1),
        "best_period_usd": max(changes),
        "worst_period_usd": min(changes),
        "longest_losing_streak_qtrs": best_streak,
        "longest_stretch_between_new_highs_qtrs": longest,
        "mean_period_usd_secondary": round(sum(changes) / n, 2),
    }


def run_window(pb, scorer, name, win, with_dist=True):
    start, end = win
    r = run_switch(pb, scorer, start, end, label=f"V13 {name}")
    diag = diagnostics(r["curve"])
    spy, _ = champ.spy_net(pb, start, end, START_CASH)
    placebo_finals, beaten = [], 0
    for seed in PLACEBO_SEEDS:
        pr = run_switch(pb, scorer, start, end,
                        placebo_rng=random.Random(seed),
                        label=f"V13 {name} PLACEBO {seed}")
        placebo_finals.append(round(pr["final"], 2))
        beaten += 1 if r["final"] > pr["final"] else 0
    sf = sorted(placebo_finals)
    out = {
        "window": {"start": start, "end": end},
        "switch_midpoint_H": r["H"],
        "final": round(r["final"], 2),
        "cagr_pct": v10.cagr_pct(r["final"], START_CASH, start, end),
        "max_dd_pct": diag["max_drawdown_pct"],
        "max_dd_date": diag["max_drawdown_date"],
        "worst_close": diag["worst_close"],
        "worst_close_date": diag["worst_close_date"],
        "costs": round(r["costs"], 2),
        "orders": r["orders"],
        "spy_final": round(spy, 2),
        "placebo_beaten": beaten,
        "placebo_median": round((sf[9] + sf[10]) / 2.0, 2),
        "placebo_best": sf[-1],
        "placebo_finals": placebo_finals,
    }
    if with_dist:
        out["period_distribution"] = period_distribution(r["curve"])
        out["equity_curve"] = [[d, round(v, 2)] for d, v in r["curve"]]
    log(f"WINDOW {name}: final=${r['final']:,.2f} maxDD="
        f"{diag['max_drawdown_pct']}% costs=${r['costs']:,.2f} "
        f"orders={r['orders']} SPY=${spy:,.2f} placebo beaten={beaten}/20 "
        f"H={r['H']}")
    return out


def confirmation(pb, scorer):
    """Frozen bars (spec): (1) fresh-$100 calendar-year folds
    2017-2026 — >=6/10 beating SPY AND >=6/10 beating placebo median;
    (2) half-windows DECADE-H1/H2, CONT-H1/H2 — beat SPY and placebo
    median in >=3 of 4 halves."""
    folds = {}
    beat_spy = beat_med = 0
    for yr in range(2017, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        r = run_switch(pb, scorer, fs, fe, label=f"CONF FOLD {yr}")
        spy, _ = champ.spy_net(pb, fs, fe, START_CASH)
        pf = []
        for seed in PLACEBO_SEEDS:
            pr = run_switch(pb, scorer, fs, fe,
                            placebo_rng=random.Random(seed),
                            label=f"CONF FOLD {yr} PLACEBO {seed}")
            pf.append(round(pr["final"], 2))
        sf = sorted(pf)
        med = round((sf[9] + sf[10]) / 2.0, 2)
        beaten = sum(1 for x in pf if r["final"] > x)
        bs = r["final"] > spy
        bm = r["final"] > med
        beat_spy += bs
        beat_med += bm
        folds[str(yr)] = {"final": round(r["final"], 2),
                          "spy_final": round(spy, 2),
                          "beat_spy": bs, "placebo_median": med,
                          "placebo_beaten": beaten, "beat_median": bm,
                          "max_dd_pct": diagnostics(r["curve"])[
                              "max_drawdown_pct"]}
        log(f"FOLD {yr}: mine=${r['final']:,.2f} SPY=${spy:,.2f} "
            f"placebo med=${med:,.2f} beaten={beaten}/20")
    halves = {}
    halves_pass = 0
    for name, win in HALF_WINDOWS.items():
        o = run_window(pb, scorer, name, win, with_dist=False)
        ok = o["final"] > o["spy_final"] and o["final"] > o["placebo_median"]
        halves_pass += 1 if ok else 0
        o["pass"] = ok
        halves[name] = o
        log(f"HALF {name}: mine=${o['final']:,.2f} SPY=${o['spy_final']:,.2f} "
            f"placebo med=${o['placebo_median']:,.2f} pass={ok}")
    return {"folds": folds, "beat_spy_count": beat_spy,
            "beat_median_count": beat_med,
            "folds_confirmed": beat_spy >= 6 and beat_med >= 6,
            "half_windows": halves, "halves_pass_count": halves_pass,
            "halves_confirmed": halves_pass >= 3,
            "confirmed": (beat_spy >= 6 and beat_med >= 6
                          and halves_pass >= 3)}


def main():
    t00 = time.time()
    facts, eq, sh = v10.load_facts()
    log(f"facts loaded ({time.time()-t00:.0f}s)")
    bars_spliced, factors = v10.spliced_bars()
    pb = v10.FastPriceBook(bars_spliced)
    scorer = v10.Scorer(pb, eq, sh, facts)
    # INTEGRITY GATE: original published combo, original form
    q_cont = champ.quarter_selection_dates(pb, *ROADS["CONT"])
    ri = v10.run_combo(pb, scorer, ROADS["CONT"][0], ROADS["CONT"][1],
                       q_cont, 100.0, 85.0, label="INTEGRITY CONT")
    integrity = {"target_combo_cont": 532.39,
                 "reproduced_combo_cont": round(ri["final"], 2),
                 "splice_factors": factors}
    log(f"INTEGRITY combo CONT (original form) = ${ri['final']:,.2f} "
        f"(target $532.39)")
    if round(ri["final"], 2) != 532.39:
        log("INTEGRITY GATE FAILED — aborting")
        sys.exit(1)
    roads = {}
    for name in ("DECADE", "CONT", "VAL"):
        roads[name] = run_window(pb, scorer, name, ROADS[name])
    champ_pub = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    beats_champ = [n for n in roads if roads[n]["final"] > champ_pub[n]]
    log(f"Roads beating published champion: {beats_champ}")
    conf = None
    if beats_champ:
        conf = confirmation(pb, scorer)
        log(f"CONFIRMATION: folds beat SPY {conf['beat_spy_count']}/10, "
            f"beat placebo median {conf['beat_median_count']}/10, "
            f"halves passed {conf['halves_pass_count']}/4 -> "
            f"{'CONFIRMED' if conf['confirmed'] else 'NOT CONFIRMED'}")
    out = {"spec": "BEST-RULES-SPEC.md (frozen before run)",
           "rules": {"direction": "champion-form first -> blend-form "
                                  "second, via a 4-step quarterly dial",
                     "nf3_weight_ramp": "0% before H-2q; 8.75% H-2q; "
                                        "17.5% H-1q; 26.25% H; 35% H+1q+",
                     "vm_count": 2, "vm_cadence": "quarterly",
                     "nf3_count": 5,
                     "nf3_cadence": "semiannual membership, quarterly "
                                    "weight reset/scale",
                     "terminal_weights": "65% VM / 35% NF3",
                     "floor": None},
           "integrity": integrity, "roads": roads,
           "roads_beating_published_champion": beats_champ,
           "confirmation": conf,
           "elapsed_s": round(time.time() - t00, 1)}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    log(f"ALL DONE ({time.time()-t00:.0f}s)")


if __name__ == "__main__":
    main()
