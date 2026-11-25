#!/usr/bin/env python3
"""
V13 BEST-RULES — N-F2 "QUIET CORRECTIONS". Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: decay-weighted amendment burden over trailing 1,825 days
(half-life 730 days), SCORE = sum_amend w / sum_orig w, w = 0.5^(age/730);
eligibility = >=16 raw original filings in window; top 10 equal weight;
quarterly re-rank, next-open execution; NO floor/halt; program costs
0.10%/side + $0.01 per sell order; $100 pots; PIT acceptance dates only.

Chassis: trade mechanics / price plumbing imported READ-ONLY from the
v10/v12 f2 engine (holdings-novel-selection/scripts/f2_engine.py), which
is itself the v8 engine's mechanics verbatim. Signal data: the v8 run's
cached EDGAR submissions rows (read-only).

INTEGRITY GATE: the imported native engine must reproduce the frozen
published form (raw 1,095-day rate, top 5, frozen tie-breaks, $85 floor)
to the cent — DECADE $555.08 / CONT $389.55 / VAL $233.34 — before any
v13 number is taken.

CONFIRMATION (pre-registered): if my form beats champion V+M on any
road, fresh-$100 calendar-year folds 2017..2026 run automatically, each
vs SPY and a 20-seed placebo median; confirmed requires >=6/10 folds
beating SPY AND >=6/10 beating their placebo median.
"""
import importlib.util
import json
import os
import random
import statistics
import time
from bisect import bisect_left
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/"
    "holdings-novel-selection/scripts/f2_engine.py")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


E = load_module("f2_engine", ENGINE_PATH)
UNIVERSE = E.UNIVERSE
START_CASH = 100.0
SEEDS = list(range(1, 21))

# ---- my rules (frozen in BEST-RULES-SPEC.md)
WINDOW_DAYS = 1825
HALF_LIFE = 730.0
MIN_DENOM_RAW = 16
N_HOLD = 10

ROADS = [("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"DECADE": 555.08, "CONT": 389.55, "VAL": 233.34}


def to_ord(s):
    return date.fromisoformat(s).toordinal()


def decay_score(orig_ords, amend_ords, sel_ord):
    """(score, raw_amend, raw_denom, decayed_num, decayed_den) for
    filings with ordinal in [sel_ord - WINDOW_DAYS, sel_ord)."""
    lo = sel_ord - WINDOW_DAYS
    o_lo = bisect_left(orig_ords, lo)
    o_hi = bisect_left(orig_ords, sel_ord)
    a_lo = bisect_left(amend_ords, lo)
    a_hi = bisect_left(amend_ords, sel_ord)
    raw_denom = o_hi - o_lo
    raw_amend = a_hi - a_lo
    if raw_denom < MIN_DENOM_RAW:
        return None
    den = sum(0.5 ** ((sel_ord - x) / HALF_LIFE)
              for x in orig_ords[o_lo:o_hi])
    num = sum(0.5 ** ((sel_ord - x) / HALF_LIFE)
              for x in amend_ords[a_lo:a_hi])
    return (num / den if den > 0 else 0.0), raw_amend, raw_denom, num, den


def run_pot_v13(pb, orig_o, amend_o, start, end, placebo_rng=None,
                record=False):
    """Trade mechanics copied from the v8/v10 f2 engine's run_pot
    (sell dropouts in full, keep survivors, equal-weight targets,
    execute pending at next open, end-of-window liquidation at final
    close, same cost math). Scoring replaced by the frozen v13 decay
    score; NO floor. Returns result dict with curve/selections/census."""
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    selections = []
    census = {"ranked_rows": 0, "zero_raw_amend_rows": 0,
              "boundary_exact_ties": 0, "selections": 0,
              "pick_counts": {}, "eligible_min": None,
              "eligible_max": None}
    sel_dates = E.cadence_dates(pb, "quarterly", start, end)
    sel_set = set(sel_dates)
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
            sel_ord = to_ord(d)
            scores = {}
            for t in UNIVERSE:
                r = decay_score(orig_o[t], amend_o[t], sel_ord)
                if r is not None:
                    scores[t] = r
            if len(scores) >= N_HOLD:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), N_HOLD)
                else:
                    ranked = sorted(scores.items(),
                                    key=lambda kv: (kv[1][0], kv[0]))
                    picks = [t for t, _ in ranked[:N_HOLD]]
                    census["selections"] += 1
                    census["ranked_rows"] += len(ranked)
                    census["zero_raw_amend_rows"] += sum(
                        1 for _, v in ranked if v[1] == 0)
                    if len(ranked) > N_HOLD and \
                            ranked[N_HOLD - 1][1][0] == ranked[N_HOLD][1][0]:
                        census["boundary_exact_ties"] += 1
                    for p in picks:
                        census["pick_counts"][p] = \
                            census["pick_counts"].get(p, 0) + 1
                    n_el = len(scores)
                    census["eligible_min"] = n_el if census["eligible_min"] is None else min(census["eligible_min"], n_el)
                    census["eligible_max"] = n_el if census["eligible_max"] is None else max(census["eligible_max"], n_el)
                    if record:
                        selections.append({
                            "date": d, "eligible": len(scores),
                            "ranked": [[t, round(v[0], 8), v[1], v[2],
                                        round(v[3], 4), round(v[4], 4)]
                                       for t, v in ranked],
                            "picks": list(picks)})
                pv = portfolio_close(d)
                each = pv / len(picks)
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
    return {"final": cash, "costs": total_costs, "trades": trades,
            "curve": curve, "selections": selections, "census": census}


def period_distribution(curve, sel_dates, start_cash=START_CASH):
    """Quarterly periods (the strategy's tempo): $ change between
    consecutive selection-date closes; first period from start_cash to
    the first selection close, last from the final selection close to
    the curve end."""
    close_on = {}
    for d, v in curve:
        close_on[d] = v
    pts = [(None, start_cash)]
    for d in sel_dates:
        if d in close_on:
            pts.append((d, close_on[d]))
    pts.append((curve[-1][0], curve[-1][1]))
    changes = [round(pts[i + 1][1] - pts[i][1], 2)
               for i in range(len(pts) - 1)]
    if not changes:
        return None
    pos = sum(1 for c in changes if c > 0)
    worst = cur = 0
    for c in changes:
        cur = cur + 1 if c <= 0 else 0
        worst = max(worst, cur)
    # longest stretch between new highs, in trading days, from curve
    peak, since, longest = -1.0, 0, 0
    for _, v in curve:
        if v >= peak:
            peak = v
            longest = max(longest, since)
            since = 0
        else:
            since += 1
    longest = max(longest, since)
    return {"period": "quarter", "n_periods": len(changes),
            "pct_positive": round(100 * pos / len(changes), 1),
            "median_change_usd": round(statistics.median(changes), 2),
            "mean_change_usd_secondary_average":
                round(statistics.mean(changes), 2),
            "best_change_usd": max(changes),
            "worst_change_usd": min(changes),
            "longest_losing_streak_periods": worst,
            "longest_stretch_between_new_highs_trading_days": longest}


def main():
    t0 = time.time()
    bars = {t: E.bars_adj(E.load_payload(t)) for t in UNIVERSE + ["SPY"]}
    pb = E.FastPriceBook(bars)
    orig, amend = E.load_signal()
    orig_o = {t: [to_ord(s) for s in orig[t]] for t in UNIVERSE}
    amend_o = {t: [to_ord(s) for s in amend[t]] for t in UNIVERSE}

    results = {
        "program": "v13-best-rules",
        "family": "novel-f2-quiet-corrections (invented rule N-F2)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"signal": "decay-weighted amendment burden, "
                                 "1825d window, 730d half-life",
                     "eligibility_min_raw_originals": MIN_DENOM_RAW,
                     "count": N_HOLD, "cadence": "quarterly",
                     "floor": None, "weighting": "equal",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": START_CASH},
        "published_form": {"finals": PUBLISHED,
                           "rules": "raw 1095d rate, top 5, frozen "
                                    "tie-breaks, plain -15% floor"},
        "champion_vm": CHAMPION, "spy_reference": SPY_REF,
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    # ---------------- integrity gate: native form via imported engine
    for name, s, e in ROADS:
        r = E.run_pot_cadence(pb, orig, amend, "quarterly", s, e,
                              START_CASH, 85.0, n_hold=5)
        ok = abs(round(r["final"], 2) - PUBLISHED[name]) < 0.02
        results["integrity"][name] = {
            "expected_published": PUBLISHED[name],
            "reproduced": round(r["final"], 2), "match": ok}
        print(f"INTEGRITY {name} native-5: ${r['final']:,.2f} expected "
              f"${PUBLISHED[name]:,.2f} match={ok}", flush=True)
        assert ok, f"integrity gate failed on {name}"

    # ---------------- my-rules roads + placebos
    beat_champion_roads = []
    for name, s, e in ROADS:
        spy, spy_costs = E.spy_net(pb, s, e, START_CASH)
        r = run_pot_v13(pb, orig_o, amend_o, s, e, record=True)
        diag = E.curve_diagnostics(r["curve"])
        sel = E.cadence_dates(pb, "quarterly", s, e)
        dist = period_distribution(r["curve"], sel)
        pfinals = []
        for seed in SEEDS:
            pr = run_pot_v13(pb, orig_o, amend_o, s, e,
                             placebo_rng=random.Random(seed))
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        med = round(statistics.median(pfinals), 2)
        if round(r["final"], 2) > CHAMPION[name]:
            beat_champion_roads.append(name)
        results["roads"][name] = {
            "window": [s, e], "final": round(r["final"], 2),
            "cagr_pct": E.cagr(r["final"], START_CASH, s, e),
            "max_drawdown_pct": diag["max_drawdown_pct"],
            "max_drawdown_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "year_end_closes": diag["year_end_closes"],
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "spy_final": round(spy, 2),
            "published_form_final": PUBLISHED[name],
            "champion_vm_final": CHAMPION[name],
            "placebo": {"finals": pfinals, "median": med,
                        "best": max(pfinals), "worst": min(pfinals),
                        "seeds_beaten": beaten},
            "census": r["census"],
            "period_distribution": dist,
            "selections": r["selections"],
            "curve": [[d, round(v, 2)] for d, v in r["curve"]],
        }
        print(f"{name}: MY RULES ${r['final']:,.2f} (DD "
              f"{diag['max_drawdown_pct']}%) | published "
              f"${PUBLISHED[name]:,.2f} | champion ${CHAMPION[name]:,.2f} "
              f"| SPY ${spy:,.2f} | placebo median ${med:,.2f} beats "
              f"{beaten}/20", flush=True)

    # ---------------- confirmation folds (only if a champion road fell)
    if beat_champion_roads:
        print(f"CONFIRMATION TRIGGERED on {beat_champion_roads}",
              flush=True)
        folds = []
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
            r = run_pot_v13(pb, orig_o, amend_o, s, e)
            spy, _ = E.spy_net(pb, s, e, START_CASH)
            pf = []
            for seed in SEEDS:
                pr = run_pot_v13(pb, orig_o, amend_o, s, e,
                                 placebo_rng=random.Random(seed))
                pf.append(round(pr["final"], 2))
            med = round(statistics.median(pf), 2)
            folds.append({"year": yr, "window": [s, e],
                          "final": round(r["final"], 2),
                          "spy_final": round(spy, 2),
                          "placebo_median": med,
                          "placebo_finals": pf,
                          "beat_spy": r["final"] > spy,
                          "beat_placebo_median": r["final"] > med})
            print(f"  fold {yr}: ${r['final']:,.2f} vs SPY ${spy:,.2f} "
                  f"vs placebo median ${med:,.2f}", flush=True)
        n_spy = sum(1 for f in folds if f["beat_spy"])
        n_pl = sum(1 for f in folds if f["beat_placebo_median"])
        results["confirmation"] = {
            "triggered_by_roads": beat_champion_roads, "folds": folds,
            "folds_beat_spy": n_spy, "folds_beat_placebo_median": n_pl,
            "confirmed": n_spy >= 6 and n_pl >= 6}
        print(f"CONFIRMATION: beat SPY {n_spy}/10, beat placebo median "
              f"{n_pl}/10, confirmed={results['confirmation']['confirmed']}",
              flush=True)

    results["runtime_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
