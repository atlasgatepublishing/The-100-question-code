#!/usr/bin/env python3
"""
VALUE + MOMENTUM — BROADER UNIVERSE (TOP-60) — Terry's AI stock app.
Simulation only.

ONE pre-published variant of the promoted spec, run once as specified,
no tuning. The engine is imported VERBATIM from
backtests/v4/value-momentum-plainfloor.py (itself the honest engine
with the ladder removed): quarterly top-5 by the average of the
book-to-market and 12-1 momentum percentile ranks, equal weight,
point-in-time EDGAR (facts filed strictly before the selection date,
~18-month freshness gate), costs 0.10%/side + $0.01/sell, plain -15%
floor ($85 on the $100 pot), $100 pots throughout.

THE ONLY CHANGE: the universe. Baseline = the 30 largest US companies
by market cap as of Nov 2016. This run = the top-60: the original 30
untouched + the 30 next-largest by computed point-in-time Nov-2016
market cap (see build_universe.py / universe-build.json for the full
ranking, method and data-forced exclusions).

Runs (mirroring the baseline judgments one for one):
  (0) REPLICATION — the same harness with the original 30 must
      reproduce the published $544.47 (continuous) and $288.05
      (validation) to the cent before any variant number is taken.
  (1) Ranked: continuous 2019-01-02 -> 2026-11-20 and validation
      2023-01-03 -> 2026-11-20, vs SPY net.
  (2) Placebo: 20 seeds (1..20), random 5 from the scored pool each
      quarter, identical machinery, BOTH windows.
  (3) Walk-forward: fresh $100 pot per calendar year 2020-2026 vs SPY
      net (the vm-walkforward.py fold protocol).

Baseline published numbers judged against (plain floor, $100):
  validation $288.05 | continuous $544.47 | placebo beats 18/20
  validation, 19/20 continuous | folds 4 wins / 3 losses vs SPY.

Data plumbing notes (no rule changes): EDGAR CIKs come from today's
company_tickers.json + the baseline's XOM override; additions that no
longer exist as registrants (acquired/delisted before 2026) are absent
from that file, so their own historical CIKs are used (documented in
the report) — the only possible reading of "their EDGAR facts".
Tickers whose Yahoo price series no longer exists get an empty bar
list: the engine then never scores them (documented per name).
All caches live in this study's own ./data (seeded with byte copies
of the baseline caches, which the replication check verifies).
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = "/home/hatch/workspace/stock-app/backtests/v5/vm-broad/data"  # V9 COPY: read-only original cache (path-only fix)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor",
    os.path.join(HERE, "..", "..", "v4", "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
E.DATA = MYDATA
E.SHARED = MYDATA

ORIGINAL30 = list(E.UNIVERSE)  # the module's own list, before override

with open("/home/hatch/workspace/stock-app/backtests/v5/vm-broad/universe-build.json") as f:  # V9 COPY: read-only original build file (path-only fix)
    BUILD = json.load(f)
UNIVERSE60 = BUILD["universe60"]
assert len(UNIVERSE60) == 60 and set(ORIGINAL30) <= set(UNIVERSE60)

# Historical CIKs for additions absent from today's ticker file.
CIK_GONE = {
    "TWX": 1105705, "MON": 1110783, "AET": 1122304, "RAI": 898173,
    "YHOO": 1043000, "CELG": 816284, "ESRX": 1532063, "AGN": 1578845,
    "UTX": 101829, "ANTM": 1156039, "PCLN": 1075531,
    "ALXN": 939767, "WBA": 1618921,
}
CIK_OVERRIDES = {"XOM": 34088}   # baseline's own override, unchanged

START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))
FULL = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")


def build_inputs(universe):
    ciks = E.get_ciks()
    equity_rows, shares_rows, data_notes = {}, {}, {}
    for t in universe:
        cik = CIK_OVERRIDES.get(t) or CIK_GONE.get(t) or ciks[t][0]
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
        if not equity_rows[t] or not shares_rows[t]:
            data_notes[t] = (f"thin EDGAR: equity facts={len(equity_rows[t])} "
                             f"shares facts={len(shares_rows[t])}")
        time.sleep(0.12)
    bars = {}
    for t in universe + ["SPY"]:
        try:
            bars[t] = E.get_prices(t)
        except Exception as e:  # noqa — delisted series purged by Yahoo
            bars[t] = []
            data_notes[t] = f"no Yahoo price series ({type(e).__name__})"
            print(f"{t}: NO PRICE SERIES — engine will never score it", flush=True)
    return E.PriceBook(bars), equity_rows, shares_rows, data_notes


def placebo_block(pb, equity_rows, shares_rows, window):
    ws, we = window
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, placebo_rng=rng,
                       label=f"PLACEBO s{seed}", quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  placebo seed {seed:2d}: ${pr['final']:,.2f} halted={pr['halted']}",
              flush=True)
    return finals, rows


def dist_stats(finals, ranked_final):
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "ranked_final": round(ranked_final, 2),
            "ranked_minus_median": round(ranked_final - E._pct(srt, 0.50), 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below}


def ranked_block(pb, equity_rows, shares_rows, window, label):
    ws, we = window
    r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                  FLOOR0, LADDER, label=label, quiet=True, record_pools=True)
    spy, _ = E.spy_net(pb, ws, we, START_CASH)
    diag = E.diagnostics(r, FLOOR0)
    pools = [{"date": d, "pool_size": len(pool), "pool": pool, "picks": picks}
             for d, pool, picks in r["pools"]]
    out = {"final": round(r["final"], 2),
           "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
           "costs": round(r["costs"], 2), "orders": len(r["trades"]),
           "halted": r["halted"], "halt_info": r["halt_info"],
           "spy_net_final": round(spy, 2),
           "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
           "diag": diag, "pools": pools,
           "trades": r["trades"]}
    print(f"{label}: final=${r['final']:,.2f} ({out['return_pct']:+.2f}%) "
          f"vs SPY ${spy:,.2f} | costs=${r['costs']:,.2f} orders={len(r['trades'])} "
          f"halted={r['halted']} maxDD={diag['max_drawdown_pct']}%", flush=True)
    return out


def main():
    out = {"variant": "value+momentum, top-60 universe (original 30 + next 30 "
                      "by point-in-time Nov-2016 market cap)",
           "engine": "value-momentum-plainfloor.py imported verbatim",
           "pot": START_CASH, "floor": FLOOR0,
           "universe60": UNIVERSE60,
           "baseline_published": {"validation_final": 288.05,
                                  "continuous_final": 544.47,
                                  "placebo_validation_beats": "18/20",
                                  "placebo_continuous_beats": "19/20",
                                  "folds": "4 wins, 3 losses vs SPY"}}

    # ---- (0) replication with the original 30 through this harness
    E.UNIVERSE = ORIGINAL30
    pb30, eq30, sh30, _ = build_inputs(ORIGINAL30)
    rep = {}
    for name, window in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        ws, we = window
        r = E.run_pot(pb30, eq30, sh30, ws, we, START_CASH, FLOOR0, LADDER,
                      label=f"REPLICATION {name}", quiet=True)
        rep[name] = round(r["final"], 2)
        print(f"REPLICATION {name}: ${r['final']:,.2f}", flush=True)
    out["replication_original30"] = rep
    assert rep["FULL"] == 544.47 and rep["VALIDATION"] == 288.05, \
        f"replication failed: {rep}"
    print("REPLICATION OK — harness reproduces the published baseline "
          "to the cent.", flush=True)

    # ---- variant inputs
    E.UNIVERSE = UNIVERSE60
    pb, equity_rows, shares_rows, data_notes = build_inputs(UNIVERSE60)
    out["data_notes"] = data_notes

    # ---- (1) ranked runs
    out["continuous"] = ranked_block(pb, equity_rows, shares_rows, FULL,
                                     "BROAD FULL")
    out["validation"] = ranked_block(pb, equity_rows, shares_rows, VALIDATION,
                                     "BROAD VALIDATION")

    # ---- (2) placebos, both windows
    for name, window, ranked in (("continuous", FULL, out["continuous"]["final"]),
                                 ("validation", VALIDATION, out["validation"]["final"])):
        print(f"PLACEBO {name}:", flush=True)
        finals, rows = placebo_block(pb, equity_rows, shares_rows, window)
        d = dist_stats(finals, ranked)
        d["rows"] = rows
        d["halted_count"] = sum(1 for x in rows if x["halted"])
        out[f"placebo_{name}"] = d
        print(f"  -> median=${d['median']:,.2f} ranked=${d['ranked_final']:,.2f} "
              f"= {d['ranked_percentile']}th pct, beats {d['seeds_beaten']}/20, "
              f"halted {d['halted_count']}/20", flush=True)

    # ---- (3) walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs, fe = f"{y}-01-01", ("2026-11-20" if y == 2026 else f"{y}-12-31")
        fr = E.run_pot(pb, equity_rows, shares_rows, fs, fe, START_CASH,
                       FLOOR0, LADDER, label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        diag = E.diagnostics(fr, FLOOR0)
        row = {"year": y, "final": round(fr["final"], 2),
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": diag["max_drawdown_pct"],
               "orders": len(fr["trades"]), "costs": round(fr["costs"], 2),
               "halted": fr["halted"]}
        folds.append(row)
        print(f"FOLD {y}: ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs SPY "
              f"${fspy:,.2f} beat={row['beat_spy']} halted={fr['halted']}", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    # ---- never-scored analysis
    scored = set()
    for blk in ("continuous", "validation"):
        for p in out[blk]["pools"]:
            scored.update(p["pool"])
    out["never_scored"] = [t for t in UNIVERSE60 if t not in scored]
    print(f"NEVER SCORED: {out['never_scored']}", flush=True)

    with open(os.path.join(HERE, "vm-broad-results.json"), "w") as f:
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
    2020: (80.18, '2020-03-09'),
    2021: (120.76, None),
    2022: (85.46, '2022-07-14'),
    2023: (117.02, None),
    2024: (152.53, None),
    2025: (126.74, None),
    2026: (134.49, None)}

def main_v9():
    detail = {"slug": "vm-broad", "folds": {}, "restarts_all": [],
              "second_halts": []}
    E.UNIVERSE = UNIVERSE60
    pb, equity_rows, shares_rows, _notes = build_inputs(UNIVERSE60)
    run_ep = lambda s, e, c, f: E.run_pot(pb, equity_rows, shares_rows, s, e, c, f, LADDER, label="V9", quiet=True)
    # continuous window: his run HALTED 2020-03-18 at $82.24 -> re-run v9
    rc = run_pot_v9(run_ep, pb, "2019-01-02", "2026-11-20", 100.0)
    assert rc["ep1_halted"] == "2020-03-18" and abs(rc["ep1_final"] - 82.24) < 0.011, (
        f"continuous episode-1 mismatch: {rc['ep1_halted']} {rc['ep1_final']}")
    detail["continuous"] = {"his_final": 82.24, "his_halted": "2020-03-18",
                            "v9_final": round(rc["final"], 2),
                            "v9_costs": round(rc["costs"], 2),
                            "v9_orders": len(rc["trades"]),
                            "restarts": rc["restarts"],
                            "second_halt": rc["second_halt"],
                            "v9_worst_equity": _v9_worst(rc["curve"], rc["final"])}
    detail["restarts_all"] += [dict({"window": "continuous"}, **r)
                                for r in rc["restarts"]]
    if rc["second_halt"]:
        detail["second_halts"].append(dict({"window": "continuous"},
                                           **rc["second_halt"]))
    print(f"V9 CONTINUOUS: his=$82.24 halted=2020-03-18 | "
          f"v9=${rc['final']:,.2f} restarts={rc['restarts']} "
          f"second_halt={rc['second_halt']}", flush=True)
    _v9_fold_driver(run_ep, pb, HIS_FOLDS_V9, detail)
    with open(os.path.join(HERE, "vm-broad-v9-detail.json"), "w") as f:
        json.dump(detail, f, indent=1, default=str)
    print("V9 DONE", flush=True)


if __name__ == "__main__":
    main_v9()
