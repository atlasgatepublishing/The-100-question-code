#!/usr/bin/env python3
"""
VALUE + MOMENTUM — BREADTH VARIANT: TOP 10 HOLDINGS INSTEAD OF TOP 5.
Terry's AI stock app. Simulation only. Run ONCE as specified — no tuning.

Pre-published rationale (the only reason this variant exists): IMC,
"Power of Many," and Novy-Marx & Velikov's work on factor construction
both find that outcome dispersion in concentrated factor books is
dominated by single-name noise and tightens substantially as holdings
rise. Terry's question: does doubling the holdings of the promoted
value+momentum spec move it toward beating 20/20 placebo seeds and
6-of-7 walk-forward years vs SPY — and what does it cost in final
balance and drawdown?

Engine: imported verbatim from
~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py
(honest point-in-time top-30 universe as of Nov 2016, quarterly ranking
by book-to-market + 12-1 momentum percentile-rank average, equal weight,
$100 start, costs 0.10%/side + $0.01/sell, plain -15% floor at $85,
ladder removed). THE ONLY CHANGE: at each quarterly selection the pot
holds the top 10 ranked names instead of the top 5 (same universe,
equal weight = pot/10), and placebo pots draw 10 random names instead
of 5. The scored-pool gate rises from >=5 to >=10 names (a mechanical
consequence of holding 10).

Implementation guarantee: run_pot10 is produced by taking the baseline
run_pot's source (inspect.getsource) and applying exactly four string
substitutions, each asserted to occur exactly once:
  "if len(scores) >= 5:"                                  -> ">= 10:"
  "picks = placebo_rng.sample(sorted(scores), 5)"         -> ", 10)"
  "picks = sorted(combined, key=lambda t: -combined[t])[:5]" -> "[:10]"
  "each = pv / 5.0"                                       -> "pv / 10.0"
Every other byte of the engine is the baseline's own code, executed in
the baseline module's namespace.

Runs ($100 pots only):
  - Replication check: baseline top-5 must reproduce $544.47 (FULL) and
    $288.05 (VALIDATION) before any variant number is taken.
  - Ranked top-10: FULL continuous 2019-01-02 -> 2026-11-20 and
    VALIDATION 2023-01-03 -> 2026-11-20.
  - Placebo: 20 seeds (1..20) on BOTH windows, top-10 random draws.
  - Walk-forward: fresh $100 pot per calendar year 2020-2026
    (Jan 1 -> Dec 31; 2026 -> Nov 20), scored vs SPY net, same method
    as vm-walkforward.py.

Baseline published numbers judged against (top-5, plain floor):
  FULL final $544.47, costs $5.49, 202 orders, max DD 36.26%
  (2020-03-23), worst close $93.13, SPY net $313.62; placebo median
  $308.81, beat 19/20 (95th pct), 7/20 placebo pots halted.
  VALIDATION final $288.05, max DD 18.07%, SPY net $187.77; placebo
  beat 18/20 (90th pct, published median $201.15).
  Folds 4 wins / 7 vs SPY (wins 2022, 2024, 2025, 2026; 2020 fold
  halted 2020-03-09 at -16.38%).

Data: same read-only caches as the parent studies (SEC EDGAR
companyfacts in v4/data, Yahoo prices in v4/value-momentum-honest-data),
loaded through the baseline module itself. Nothing is written outside
this folder.
"""
import importlib.util
import inspect
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

spec = importlib.util.spec_from_file_location("vm_plainfloor", BASE_PATH)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

START_CASH = 100.0
FLOOR0 = 85.0          # plain -15% floor on $100, no ladder, ever
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))
FULL = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")

# Baseline (top-5) published fold finals, vm-walkforward-results.json
BASELINE_FOLDS = {2020: 83.62, 2021: 118.43, 2022: 108.91, 2023: 118.47,
                  2024: 144.32, 2025: 124.57, 2026: 136.26}
BASELINE = {
    "full": {"final": 544.47, "costs": 5.49, "orders": 202,
             "max_drawdown_pct": 36.26, "worst_close": 93.13,
             "spy_net": 313.62, "placebo_median": 308.81,
             "placebo_q1": 87.55, "placebo_q3": 387.05,
             "placebo_best": 562.03, "placebo_worst": 83.12,
             "placebo_halted": 7, "seeds_beaten": 19,
             "ranked_percentile": 95.0},
    "validation": {"final": 288.05, "max_drawdown_pct": 18.07,
                   "worst_close": 94.08, "spy_net": 187.77,
                   "placebo_median": 201.15, "seeds_beaten": 18,
                   "ranked_percentile": 90.0},
    "fold_record": "4 wins, 3 losses vs SPY",
}


def make_run_pot10():
    """Baseline run_pot with ONLY the holdings count changed 5 -> 10."""
    src = inspect.getsource(E.run_pot)
    subs = [
        ("if len(scores) >= 5:", "if len(scores) >= 10:"),
        ("picks = placebo_rng.sample(sorted(scores), 5)",
         "picks = placebo_rng.sample(sorted(scores), 10)"),
        ("picks = sorted(combined, key=lambda t: -combined[t])[:5]",
         "picks = sorted(combined, key=lambda t: -combined[t])[:10]"),
        ("each = pv / 5.0", "each = pv / 10.0"),
    ]
    for old, new in subs:
        assert src.count(old) == 1, f"expected exactly one occurrence of {old!r}, found {src.count(old)}"
        src = src.replace(old, new)
    ns = dict(E.__dict__)
    exec(compile(src, "<run_pot10 derived from value-momentum-plainfloor.run_pot>", "exec"), ns)
    return ns["run_pot"]


run_pot10 = make_run_pot10()


def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def summarize(r, spy):
    diag = E.diagnostics(r, FLOOR0)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "spy_net": round(spy, 2),
            "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
            "beat_spy": r["final"] > spy,
            "max_drawdown_pct": diag["max_drawdown_pct"],
            "max_drawdown_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "worst_close_above_floor": diag["worst_close_above_floor"],
            "covid_worst_close": diag["covid_worst_close"],
            "covid_worst_date": diag["covid_worst_date"],
            "year_end_closes": diag["year_end_closes"]}


def placebo_block(pb, eq, sh, window, ranked_final):
    ws, we = window
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot10(pb, eq, sh, ws, we, START_CASH, FLOOR0, LADDER,
                       placebo_rng=rng, label=f"PLACEBO10 seed {seed}", quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  PLACEBO10 seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} orders={len(pr['trades'])}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {"seeds": PLACEBO_SEEDS,
            "median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below,
            "ranked_minus_median": round(ranked_final - E._pct(srt, 0.50), 2),
            "rows": rows}


def main():
    pb, equity_rows, shares_rows = build_inputs()
    out = {"variant": "value+momentum breadth: top 10 holdings (baseline top 5)",
           "engine": "value-momentum-plainfloor.run_pot with ONLY holdings count 5->10 "
                     "(4 asserted single-occurrence substitutions)",
           "universe": E.UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "baseline_published": BASELINE}

    # ---- replication check: baseline engine must reproduce its numbers
    rep = {}
    for name, (ws, we), expect in (("full", FULL, 544.47),
                                   ("validation", VALIDATION, 288.05)):
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, LADDER, label=f"REPLICATION top5 {name}", quiet=True)
        rep[name] = {"final": round(r["final"], 2), "expected": expect,
                     "match": abs(r["final"] - expect) < 0.02}
        print(f"REPLICATION top-5 {name}: ${r['final']:,.2f} (expected ${expect}) "
              f"match={rep[name]['match']}", flush=True)
    out["replication_check_top5"] = rep
    assert all(v["match"] for v in rep.values()), "baseline replication FAILED — variant numbers not trustworthy"

    # ---- ranked top-10 on both windows
    ranked = {}
    for name, (ws, we) in (("full", FULL), ("validation", VALIDATION)):
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot10(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, LADDER, label=f"TOP10 {name}", quiet=True)
        ranked[name] = summarize(r, spy)
        ranked[name]["_raw_final"] = r["final"]
        print(f"== TOP10 {name}: final=${r['final']:,.2f} "
              f"({ranked[name]['return_pct']:+.2f}%) costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY=${spy:,.2f} | "
              f"maxDD={ranked[name]['max_drawdown_pct']}% worst close=${ranked[name]['worst_close']}",
              flush=True)
    out["ranked_top10"] = {k: {kk: vv for kk, vv in v.items() if kk != "_raw_final"}
                           for k, v in ranked.items()}

    # ---- placebo on both windows
    for name, window in (("full", FULL), ("validation", VALIDATION)):
        print(f"PLACEBO top-10 {name} ...", flush=True)
        out[f"placebo_top10_{name}"] = placebo_block(
            pb, equity_rows, shares_rows, window, ranked[name]["_raw_final"])
        d = out[f"placebo_top10_{name}"]
        print(f"  DIST {name}: median=${d['median']:,.2f} best=${d['best']:,.2f} "
              f"worst=${d['worst']:,.2f} halted={d['halted_count']}/20 | ranked "
              f"${d['ranked_final']:,.2f} = {d['ranked_percentile']}th pct, "
              f"beat {d['seeds_beaten']}/20", flush=True)

    # ---- walk-forward folds
    folds = []
    comp10, comp5 = 1.0, 1.0
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot10(pb, equity_rows, shares_rows, fs, fe, START_CASH,
                       FLOOR0, LADDER, label=f"FOLD10 {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = summarize(fr, fspy)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": fst["return_pct"], "spy_net_final": fst["spy_net"],
               "spy_return_pct": fst["spy_return_pct"], "beat_spy": fst["beat_spy"],
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"],
               "baseline_top5_final": BASELINE_FOLDS[y]}
        folds.append(row)
        comp10 *= fr["final"] / START_CASH
        comp5 *= BASELINE_FOLDS[y] / START_CASH
        print(f"FOLD10 {y}: ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs SPY "
              f"${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% halted={row['halted']} "
              f"| top-5 baseline ${BASELINE_FOLDS[y]:,.2f}", flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    out["folds_top10"] = folds
    out["fold_record_top10"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    out["fold_compounded_top10"] = round(START_CASH * comp10, 2)
    out["fold_compounded_top5_baseline"] = round(START_CASH * comp5, 2)
    print(f"FOLDS: top-10 record {out['fold_record_top10']} | compounded "
          f"top-10 ${out['fold_compounded_top10']:,.2f} vs top-5 "
          f"${out['fold_compounded_top5_baseline']:,.2f}", flush=True)

    with open(os.path.join(HERE, "vm-breadth10-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


# ============================================================ V9 MODULE
# CLAUDE-RULES PROTECTION SPEC v9 -- the ONLY change vs the original
# script above (kept byte-identical). run_pot_v9 wraps the variant's own
# unchanged run function: episode 1 = the original plain floor (-15%
# from the start balance); on FIRST halt: liquidate exactly as the
# original engine does, sit in cash 90 calendar days (counted from the
# liquidation date, matching the sibling v9 bundles), then RESTART with
# the remaining cash at the next quarterly selection date on or after
# liquidation+90d; episode-2 floor = -15% from the RESTART balance; on
# SECOND halt the run ends permanently. If no quarterly selection date
# remains in-window, the run ends in cash. No signal parameter, cost,
# universe or window was changed. Ranked pots only -- no placebos.
from datetime import date as _v9date


def run_pot_v9(run_ep, pb, start, end, start_cash):
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_ep(start, end, start_cash, floor1)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "ep1_final": r1["final"], "ep1_halted": r1["halted"],
           "ep1_halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]            # original engine liquidates at next open
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _v9date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in E.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _v9date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    entry = {"halt_signal_date": r1["halted"],
             "halt_signal_close": r1["halt_info"]["signal_close"],
             "liquidation_date": liq_date,
             "restart_date": restart,
             "restart_balance": round(cash, 2),
             "episode2_floor": floor2}
    out["restarts"].append(entry)
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    r2 = run_ep(restart, end, cash, floor2)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def _v9_worst(curve, final):
    vals = [v for _, v in curve] + [final]
    return round(min(vals), 2) if vals else None


def _v9_fold_driver(run_ep, pb, his_folds, detail):
    """his_folds: {year: (his_final, his_halted)}. Non-halted folds are
    carried identical (floor never fired); halted folds are re-run
    under v9, with an assertion that episode 1 reproduces his fold
    exactly before the restart logic is trusted."""
    v9_finals, comp_his, comp_v9 = {}, 1.0, 1.0
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        his_final, his_halted = his_folds[y]
        comp_his *= his_final / 100.0
        if his_halted is None:
            v9_finals[y] = his_final
            detail["folds"][str(y)] = {"his_final": his_final,
                                       "his_halted": None,
                                       "v9_final": his_final,
                                       "note": "identical -- floor never fired"}
            print(f"V9 FOLD {y}: his=${his_final:,.2f} halted=None -> "
                  f"identical (not re-run)", flush=True)
            comp_v9 *= his_final / 100.0
            continue
        rv = run_pot_v9(run_ep, pb, fs, fe, 100.0)
        assert rv["ep1_halted"] == his_halted, (
            f"fold {y}: episode-1 halt {rv['ep1_halted']} != his {his_halted}")
        assert abs(rv["ep1_final"] - his_final) < 0.011, (
            f"fold {y}: episode-1 final {rv['ep1_final']} != his {his_final}")
        v9_finals[y] = round(rv["final"], 2)
        comp_v9 *= rv["final"] / 100.0
        detail["folds"][str(y)] = {
            "his_final": his_final, "his_halted": his_halted,
            "v9_final": round(rv["final"], 2),
            "v9_costs": round(rv["costs"], 2),
            "v9_orders": len(rv["trades"]),
            "restarts": rv["restarts"], "second_halt": rv["second_halt"],
            "v9_worst_equity": _v9_worst(rv["curve"], rv["final"])}
        detail["restarts_all"] += [
            dict({"fold": str(y)}, **r) for r in rv["restarts"]]
        if rv["second_halt"]:
            detail["second_halts"].append(
                dict({"fold": str(y)}, **rv["second_halt"]))
        print(f"V9 FOLD {y}: his=${his_final:,.2f} halted={his_halted} | "
              f"v9=${rv['final']:,.2f} restarts={rv['restarts']} "
              f"second_halt={rv['second_halt']}", flush=True)
    detail["his_fold_compounded"] = round(100.0 * comp_his, 2)
    detail["v9_fold_compounded"] = round(100.0 * comp_v9, 2)
    print(f"FOLD-COMPOUNDED: his=${detail['his_fold_compounded']:,.2f} "
          f"v9=${detail['v9_fold_compounded']:,.2f}", flush=True)
    return v9_finals


HIS_FOLDS_V9 = {
    2020: (84.07, '2020-03-09'),
    2021: (118.61, None),
    2022: (84.37, '2022-06-16'),
    2023: (120.74, None),
    2024: (141.22, None),
    2025: (120.2, None),
    2026: (124.76, None)}

def main_v9():
    detail = {"slug": "vm-breadth10", "folds": {}, "restarts_all": [],
              "second_halts": []}
    pb, equity_rows, shares_rows = build_inputs()
    run_ep = lambda s, e, c, f: run_pot10(pb, equity_rows, shares_rows, s, e, c, f, LADDER, label="V9", quiet=True)
    pass  # main windows identical under v9 (floor never fired); folds below
    _v9_fold_driver(run_ep, pb, HIS_FOLDS_V9, detail)
    with open(os.path.join(HERE, "vm-breadth10-v9-detail.json"), "w") as f:
        json.dump(detail, f, indent=1, default=str)
    print("V9 DONE", flush=True)


if __name__ == "__main__":
    main_v9()
