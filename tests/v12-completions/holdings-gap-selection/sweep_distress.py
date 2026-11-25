#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — gap-a4-distress (CHS failure-probability avoidance).
Engine: v10 run_v10.py machinery (imported read-only) — CHS scoring via
O.compute_selection (cached per date, identical pools for every count),
quarterly selection (the native cadence), full-range prices, program
costs 0.10%/side + $0.01/sell. ONLY change vs the v10 cadence engine:
picks = N lowest failure probabilities (placebo: random N from the same
scored pool) and target weight = portfolio value / number of picks
(the v10 engine's hard-coded /5 becomes /len(picks)).
Forms: house = v9 wrapper (plain -15% floor, liquidate next open, 90-day
sit-out, restart at next quarterly date, ep2 floor -15% from restart
balance, 2nd halt ends); native = the published long-only form with NO
floor (single episode, floor disabled). Native count = 5.
Grid: 1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE (all scored names; pond caps
the scored pool at <=30). Roads: LONG 2010 / DECADE / CONT / VAL.
Placebos: 20 seeds on DECADE per cell. Confirmation: CONF_A/CONF_B.
VALIDATION: house count 5 must reproduce v11/v10 DECADE $513.37,
CONT $335.88, VAL $154.25.
"""
import importlib.util, json, os, random, statistics, time
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/gap-a4-distress/run_v10.py")
spec = importlib.util.spec_from_file_location("distress_v10", SRC)
D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
O, E = D.O, D.E

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF_A": ("2020-01-01", "2023-12-31"), "CONF_B": ("2024-01-01", "2026-11-20")}

def run_pot_n(pb, data, spy_me, sel_dates, start, end, start_cash, floor0,
              n_count, placebo_rng=None):
    cash = start_cash; floor = floor0; positions = {}; trades = []
    total_costs = 0.0; halted = None; curve = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days: return None
    pending = None
    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(positions):
            if t not in opens: continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c; total_costs += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005: continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending); pending = None
        if d in sel_set:
            sel = O.compute_selection(pb, d, data, spy_me)
            scored = sel["scored"]
            if len(scored) >= 1:
                ranked = sorted(scored, key=lambda t: (scored[t]["prob"], t))
                if placebo_rng is not None:
                    k = len(ranked) if n_count is None else min(n_count, len(ranked))
                    picks = placebo_rng.sample(sorted(scored), k)
                else:
                    picks = ranked if n_count is None else ranked[:n_count]
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "curve": curve}

def run_house_n(pb, data, spy_me, sel_dates, start, end, n_count, placebo_rng=None):
    ep1 = run_pot_n(pb, data, spy_me, sel_dates, start, end, 100.0, 85.0, n_count, placebo_rng)
    out = {"episodes": 1, "final": ep1["final"], "costs": ep1["costs"],
           "orders": len(ep1["trades"]), "halts": 0, "curve": list(ep1["curve"])}
    if not ep1["halted"]:
        return out
    out["halts"] = 1
    liq = ep1["end"]; cash1 = ep1["final"]
    eligible = (_date.fromisoformat(liq) + timedelta(days=90)).isoformat()
    restart = next((d for d in sel_dates if d >= eligible), None)
    if restart is None:
        return out
    ep2 = run_pot_n(pb, data, spy_me, sel_dates, restart, end, cash1, 0.85 * cash1, n_count, placebo_rng)
    out.update({"episodes": 2, "final": ep2["final"],
                "costs": ep1["costs"] + ep2["costs"],
                "orders": len(ep1["trades"]) + len(ep2["trades"]),
                "curve": list(ep1["curve"]) + list(ep2["curve"])})
    if ep2["halted"]: out["halts"] = 2
    return out

def run_native_n(pb, data, spy_me, sel_dates, start, end, n_count, placebo_rng=None):
    r = run_pot_n(pb, data, spy_me, sel_dates, start, end, 100.0, 0.0, n_count, placebo_rng)
    return {"episodes": 1, "final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "halts": 0, "curve": list(r["curve"])}

def stats_of(r):
    peak, mdd = 100.0, 0.0
    for _, v in r["curve"]:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return {"final": round(r["final"], 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(r["costs"], 2), "orders": r["orders"], "halts": r["halts"]}

def period_stats(curve):
    bym = {}
    for d, v in curve: bym[d[:7]] = v
    keys = sorted(bym); rets = []; prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

def main():
    t0 = time.time()
    D.install_fast_helpers()
    data = D.load_facts()
    bars = D.load_bars_full()
    pb = D.FastPriceBook(bars)
    spy_me = O.month_end_closes(bars["SPY"])
    O.SELECTION_CACHE.clear()
    print("data loaded", round(time.time() - t0), "s", flush=True)
    out = {"family": "gap-a4-distress", "native_count": 5,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "forms": {}}
    sel_cache = {}
    def sel_dates_for(a, b):
        key = (a, b)
        if key not in sel_cache:
            sel_cache[key] = D.cadence_dates(pb, "quarterly", a, b)
        return sel_cache[key]
    # precompute selections for union of all quarterly dates 2010-2026
    all_dates = sel_dates_for("2010-01-04", "2026-11-20")
    for i, d in enumerate(all_dates):
        O.compute_selection(pb, d, data, spy_me)
        if i % 20 == 0: print(f"selections {i}/{len(all_dates)} ({round(time.time()-t0)}s)", flush=True)
    pool_sizes = {}
    for d in all_dates:
        pool_sizes[d] = len(O.SELECTION_CACHE[d]["scored"])
    out["scored_pool_sizes"] = {"min": min(pool_sizes.values()), "max": max(pool_sizes.values()),
                                "median": statistics.median(pool_sizes.values())}
    print("selections done; pool sizes:", out["scored_pool_sizes"], flush=True)
    # validation: house n=5 vs published
    val = {}
    for nm, pub in (("DECADE", 513.37), ("CONT", 335.88), ("VAL", 154.25)):
        a, b = ROADS[nm]
        r = run_house_n(pb, data, spy_me, sel_dates_for(a, b), a, b, 5)
        val[nm] = {"final": round(r["final"], 2), "published": pub, "match": round(r["final"], 2) == pub}
    out["validation_house_n5"] = val
    print("VALIDATION house n5:", val, flush=True)
    for form, runner in (("house_v9", run_house_n), ("native_no_floor", run_native_n)):
        cells = {}
        for n in COUNTS:
            key = "ALL" if n is None else str(n)
            cell = {}
            for w, (a, b) in {**ROADS, **CONF}.items():
                r = runner(pb, data, spy_me, sel_dates_for(a, b), a, b, n)
                cell[w] = stats_of(r)
                if w == "DECADE": cell[w]["curve"] = [[d, round(v, 2)] for d, v in r["curve"]]
            a, b = ROADS["DECADE"]
            pls = []
            for s in range(1, 21):
                rp = runner(pb, data, spy_me, sel_dates_for(a, b), a, b, n, placebo_rng=random.Random(s))
                pls.append(round(rp["final"], 2))
            cell["placebos_DECADE"] = {"finals": pls,
                "beaten": sum(1 for x in pls if cell["DECADE"]["final"] > x),
                "median": round(statistics.median(pls), 2)}
            cells[key] = cell
            print(f"distress {form} n={key}: " + " ".join(f"{w} {cell[w]['final']}" for w in ROADS) +
                  f" placebo {cell['placebos_DECADE']['beaten']}/20 ({round(time.time()-t0)}s)", flush=True)
        finals = {k: c["DECADE"]["final"] for k, c in cells.items()}
        best = max(finals, key=finals.get)
        out["forms"][form + "_best_DECADE"] = best
        for k in {best, "5"}:
            cells[k]["DECADE"]["period_stats_monthly"] = period_stats(cells[k]["DECADE"]["curve"])
        for c in cells.values(): c["DECADE"].pop("curve", None)
        out["forms"][form] = cells
    spy = {}
    for w, (a, b) in ROADS.items():
        f, _ = E.spy_net(pb, a, b, 100.0)
        spy[w] = round(f, 2)
    out["spy"] = spy
    json.dump(out, open(os.path.join(HERE, "results_distress.json"), "w"), indent=1)
    print("distress done", round(time.time() - t0), "s", flush=True)

if __name__ == "__main__":
    main()
