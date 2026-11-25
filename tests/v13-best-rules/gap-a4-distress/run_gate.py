#!/usr/bin/env python3
"""
V13 BEST-RULES — GAP-A4 DISTRESS (CHS): the distress VETO GATE on the
champion value+momentum. Implements BEST-RULES-SPEC.md exactly as frozen.
Simulation only.

Design: champion V+M (book-to-market form) run VERBATIM via the v12
holdings chassis (read-only import), with exactly one change at each
quarterly selection: a name in the highest-CHS-failure-probability
QUINTILE of that date's scored pool is ineligible; the book walks the
host ranking top-down and takes the first 5 ungated names (fallback:
fill in host-rank order from gated names, logged). CHS probabilities
come from the v10 byte-copy of the v7/v9 engine (read-only import),
point-in-time, published coefficients and procedures verbatim.

Blocks: (0) integrity — chassis must reproduce published champion
finals LONG $1,415.62 / DECADE $667.35 / CONT $544.47 / VAL $288.05;
(1) gated + host runs on all four roads, 20-seed placebos per road;
(2) gate log; (3) per-period distributions; (4) confirmation folds if
the gated book beats the host on any road (pre-registered in spec:
>=60% of folds AND fold-compounded ahead).
"""
import importlib.util
import json
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
END = "2026-11-20"
SEEDS = list(range(1, 21))
START_CASH = 100.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", os.path.join(
    BT, "v12-completions", "holdings-champion-vm", "run_sweep.py"))
V10 = load_module("v10_distress", os.path.join(
    BT, "v10-retest", "gap-a4-distress", "run_v10.py"))
O = V10.O          # the CHS engine (byte copy of the v9 engine)
E = O.E            # the v4 champion engine (EDGAR loaders)


# ------------------------------------------------------------ CHS data
def load_chs_data(tickers):
    """V10.load_facts generalized over an arbitrary ticker list."""
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows, concepts = {}, {}, {}
    for t in tickers:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        concepts[t] = O.build_concept_rows(facts, eq)
        del facts
    return {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}


def chs_probabilities(pb, pond, sel_dates, data):
    """{date: {ticker: prob}} for one pond. Sets the engine's UNIVERSE
    global to the pond and clears its per-date cache (cache is keyed by
    date only, and the two ponds share dates)."""
    O.UNIVERSE = list(pond)
    O.SELECTION_CACHE.clear()
    spy_me = O.month_end_closes(pb.bars["SPY"])
    out = {}
    for d in sel_dates:
        sel = O.compute_selection(pb, d, data, spy_me)
        out[d] = {t: s["prob"] for t, s in sel["scored"].items()}
    return out


# ------------------------------------------------------------ the gate
def gated_decisions(dec_host, chs):
    """Returns (gated_dec, gate_log). Gate set per date = highest-prob
    quintile of the CHS scored pool (ceil(0.2*n), ties broken by ticker
    for determinism). New ranking = ungated names in host order, then
    gated names in host order (the spec's fallback fill)."""
    gated = {}
    log = []
    for d, dd in dec_host.items():
        ranked = dd["ranked"]
        probs = chs.get(d) or {}
        if not ranked or not probs:
            gated[d] = {"ranked": list(ranked), "pool": dd["pool"]}
            continue
        n_gate = math.ceil(0.20 * len(probs))
        gate_sorted = sorted(probs, key=lambda t: (-probs[t], t))
        gate_set = set(gate_sorted[:n_gate])
        cut = probs[gate_sorted[n_gate - 1]] if n_gate else None
        ungated = [t for t in ranked if t not in gate_set]
        gated_names = [t for t in ranked if t in gate_set]
        new_ranked = ungated + gated_names
        host_top5 = ranked[:5]
        new_top5 = new_ranked[:5]
        if set(host_top5) != set(new_top5):
            log.append({
                "date": d,
                "pool_scored": len(probs),
                "gate_count": n_gate,
                "quintile_cut_prob_pct": round(cut * 100, 4) if cut is not None else None,
                "gated_out": [{"ticker": t, "prob_pct": round(probs[t] * 100, 4)}
                              for t in host_top5 if t in gate_set],
                "replacements": [t for t in new_top5 if t not in host_top5],
                "fallback_used": len(ungated) < 5,
                "host_top5": host_top5, "gated_top5": new_top5})
        gated[d] = {"ranked": new_ranked, "pool": dd["pool"]}
    return gated, log


def unscored_host_picks(dec_host, chs):
    """Count of host top-5 picks with no CHS score (never gated)."""
    n = 0
    detail = {}
    for d, dd in dec_host.items():
        probs = chs.get(d) or {}
        for t in dd["ranked"][:5]:
            if t not in probs:
                n += 1
                detail[t] = detail.get(t, 0) + 1
    return {"count": n, "by_ticker": detail}


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "gap-a4-distress (CHS failure probability)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {
            "form": "CHS distress veto gate on champion V+M (host verbatim)",
            "gate": "highest-CHS-probability quintile of the date's scored "
                    "pool ineligible; walk host ranking, first 5 ungated; "
                    "fallback fill in host-rank order (logged)",
            "host": "champion V+M book-to-market, quarterly, top-5 equal "
                    "weight, house -15% floor chassis, program costs",
            "start_cash": 100.0},
        "published_standalone": {"DECADE": 513.37, "CONT": 335.88,
                                 "VAL": 154.25, "LONG": None},
        "champion_bars": {"LONG": 1415.62, "DECADE": 667.35,
                          "CONT": 544.47, "VAL": 288.05},
        "spy_bars": {"LONG": 822.94, "DECADE": 367.80,
                     "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    # ---------------- inputs
    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    print(f"fixed inputs+decisions {time.time()-t0:.0f}s", flush=True)

    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    results["long_pond"] = pondL
    print(f"long inputs+decisions {time.time()-t0:.0f}s", flush=True)

    # ---------------- CHS probabilities (both ponds)
    V10.install_fast_helpers()
    tickers = sorted(set(universe) | set(pondL))
    data = load_chs_data(tickers)
    print(f"CHS facts loaded {time.time()-t0:.0f}s", flush=True)
    chs_fixed = chs_probabilities(pb, universe, all_sel, data)
    print(f"CHS fixed pond scored {time.time()-t0:.0f}s", flush=True)
    chs_long = chs_probabilities(pbL, pondL, selL_all, data)
    print(f"CHS long pond scored {time.time()-t0:.0f}s", flush=True)

    dec_fixed_g, log_fixed = gated_decisions(dec_fixed, chs_fixed)
    dec_long_g, log_long = gated_decisions(dec_long, chs_long)
    results["gate_log"] = {"fixed_pond": log_fixed, "long_pond": log_long}
    results["unscored_host_picks"] = {
        "fixed_pond": unscored_host_picks(dec_fixed, chs_fixed),
        "long_pond": unscored_host_picks(dec_long, chs_long)}
    print(f"gate events: fixed={len(log_fixed)} long={len(log_long)} "
          f"({time.time()-t0:.0f}s)", flush=True)

    road_specs = [
        ("DECADE", pb, dec_fixed, dec_fixed_g, "2016-11-21", END, "fixed"),
        ("CONT", pb, dec_fixed, dec_fixed_g, "2019-01-02", END, "fixed"),
        ("VAL", pb, dec_fixed, dec_fixed_g, "2023-01-03", END, "fixed"),
        ("LONG", pbL, dec_long, dec_long_g, "2010-01-04", END, "long"),
    ]

    # ---------------- integrity: host count-5 = published champion
    expect = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    host_runs = {}
    for name, pbx, decx, decg, s, e, pond_tag in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, decx, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - expect[name]) < 0.02
        results["integrity"][name] = {"expected": expect[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name}: ${r['final']:,.2f} vs ${expect[name]} "
              f"match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"
        host_runs[name] = r

    # ---------------- gated runs + placebos per road
    beat_roads = []
    for name, pbx, decx, decg, s, e, pond_tag in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        g = S.run_house(pbx, decg, sel, s, e, 5)
        h = host_runs[name]
        gdiag = S.diagnostics(g["curve"])
        hdiag = S.diagnostics(h["curve"])
        pfinals = []
        for seed in SEEDS:
            pr = S.run_house(pbx, decx, sel, s, e, 5, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < g["final"])
        events = [ev for ev in results["gate_log"][
            "fixed_pond" if pond_tag == "fixed" else "long_pond"]
            if s <= ev["date"] <= e]
        beat = round(g["final"], 2) > round(h["final"], 2)
        if beat:
            beat_roads.append((name, pond_tag))
        results["roads"][name] = {
            "window": [s, e], "pond": pond_tag, "spy_final": spy,
            "gated": {"final": round(g["final"], 2),
                      "costs": round(g["costs"], 2), "orders": g["orders"],
                      "halts": g["halts"],
                      "max_dd_pct": gdiag["max_dd_pct"],
                      "max_dd_date": gdiag["max_dd_date"],
                      "worst_close": gdiag["worst_close"],
                      "worst_close_date": gdiag["worst_close_date"],
                      "placebo_beaten": beaten, "placebo_finals": pfinals,
                      "period_distribution": S.period_distribution(
                          [(d, v) for d, v in g["curve"]], sel),
                      "curve": [[d, round(v, 4)] for d, v in g["curve"]]},
            "host": {"final": round(h["final"], 2),
                     "costs": round(h["costs"], 2), "orders": h["orders"],
                     "halts": h["halts"],
                     "max_dd_pct": hdiag["max_dd_pct"],
                     "max_dd_date": hdiag["max_dd_date"],
                     "period_distribution": S.period_distribution(
                         [(d, v) for d, v in h["curve"]], sel),
                     "curve": [[d, round(v, 4)] for d, v in h["curve"]]},
            "gate_contribution": round(g["final"] - h["final"], 2),
            "gate_events_in_window": events,
            "beats_host": beat}
        print(f"{name} GATED ${g['final']:,.2f} vs HOST ${h['final']:,.2f} "
              f"(gate {g['final']-h['final']:+,.2f}) SPY ${spy:,.2f} "
              f"placebos {beaten}/20 maxDD {gdiag['max_dd_pct']}% "
              f"events={len(events)} ({time.time()-t0:.0f}s)", flush=True)

    # ---------------- confirmation (pre-registered in the spec)
    if beat_roads:
        conf = {"design": "fresh-$100 calendar-year folds on the pond "
                          "that produced the beat; gated vs host, full "
                          "rule set; confirmed requires >=60% of folds "
                          "(rounded up) AND fold-compounded gated ahead",
                "ponds": {}}
        ponds_done = set()
        for name, pond_tag in beat_roads:
            if pond_tag in ponds_done:
                continue
            ponds_done.add(pond_tag)
            if pond_tag == "fixed":
                pbx, decx, decg = pb, dec_fixed, dec_fixed_g
                years = range(2017, 2027)
            else:
                pbx, decx, decg = pbL, dec_long, dec_long_g
                years = range(2011, 2027)
            folds = {}
            gcomp = hcomp = 1.0
            wins = 0
            for yr in years:
                s = f"{yr}-01-01"
                e = END if yr == 2026 else f"{yr}-12-31"
                sel = S.quarter_dates(pbx, s, e)
                rg = S.run_house(pbx, decg, sel, s, e, 5)
                rh = S.run_house(pbx, decx, sel, s, e, 5)
                win = rg["final"] > rh["final"]
                wins += 1 if win else 0
                gcomp *= rg["final"] / START_CASH
                hcomp *= rh["final"] / START_CASH
                folds[str(yr)] = {
                    "gated_final": round(rg["final"], 2),
                    "host_final": round(rh["final"], 2),
                    "gated_max_dd_pct": S.diagnostics(rg["curve"])["max_dd_pct"],
                    "gated_win": win}
            n = len(folds)
            need = math.ceil(0.60 * n)
            conf["ponds"][pond_tag] = {
                "folds": folds, "fold_wins": f"{wins}/{n}",
                "folds_needed": need,
                "gated_fold_compounded": round(START_CASH * gcomp, 2),
                "host_fold_compounded": round(START_CASH * hcomp, 2),
                "confirmed": wins >= need and gcomp > hcomp}
            print(f"CONFIRMATION {pond_tag}: folds {wins}/{n} (need "
                  f"{need}), compounded gated ${START_CASH*gcomp:,.2f} vs "
                  f"host ${START_CASH*hcomp:,.2f} confirmed="
                  f"{conf['ponds'][pond_tag]['confirmed']}", flush=True)
        results["confirmation"] = conf

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
