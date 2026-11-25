#!/usr/bin/env python3
"""
V13 BEST-RULES — COMBO-THREE-WAY (V+M x Lazy Prices x N-F3).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (from the frozen spec):
  - Three SEPARATE sub-pots of one $100 pot, initial weights
    V+M 50% / N-F3 30% / Lazy 20%. NO resets, NO transfers — weights
    drift; each sleeve compounds its own gains.
  - V+M sleeve: its v13 form verbatim — top-2, quarterly, NO floor —
    run on the v12 holdings-champion-vm chassis (run_episode,
    floor=None, count=2) at the sleeve's cash.
  - Lazy sleeve: published form minus floor — top-5, quarterly,
    floor0=-inf — run on the v12 holdings-lazy-prices engine_n
    (run_pot_n) at the sleeve's cash.
  - N-F3 sleeve: its v13 form verbatim — top-5, semiannual, NO floor —
    run on the v13 nf3 module's own machinery (Window/run_pot,
    floor=-inf) at the sleeve's cash.
  - Program costs inside each sleeve exactly as in the parent engines.
  - Combined final = sum of sleeve finals; combined curve = date-aligned
    sum of sleeve curves (forward-filled; the N-F3 LONG sleeve is cash
    at its $30 until its honest data start 2012-10-01).

INTEGRITY GATE (before any blend number counts): each sleeve at $100
under its sleeve form must reproduce its parent's record — V+M: v13
finals 2923.60/906.90/691.73/461.20; N-F3: v13 finals
430.30/848.79/553.73/291.28; Lazy: CONT 504.34 / VAL 324.12 (published
native finals; the published floor never fired there). Lazy DECADE/LONG
have no floorless published twin — reported, not gated.

PLACEBOS: 20 seeds/road; twin = all three sleeves randomized together
(each sleeve draws its own count from its own pool at its own dates,
random.Random(seed) per sleeve), identical weights/mechanics/costs.

CONFIRMATION (pre-registered): only if the blend beats ALL parents'
best forms on BOTH CONT and VAL — fresh-$100 calendar-year folds
2017-2026, blend vs the V+M v13 form; confirmed requires >=6/10 folds.

Shared inputs READ-ONLY. Writes only inside this folder.
"""
import gc
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
END = "2026-11-20"
SEEDS = list(range(1, 21))
W = {"VM": 50.0, "NF3": 30.0, "LZ": 20.0}
OUT_PATH = os.path.join(HERE, "results.json")

VM_V13 = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73, "VAL": 461.20}
NF3_V13 = {"LONG": 430.30, "DECADE": 848.79, "CONT": 553.73, "VAL": 291.28}
LZ_PUBLISHED = {"CONT": 504.34, "VAL": 324.12, "DECADE": 514.77,
                "LONG": 559.69}
BAR = {"CONT": {"VM": 691.73, "LZ": 504.34, "NF3": 553.73},
       "VAL": {"VM": 461.20, "LZ": 324.12, "NF3": 291.28}}
SPY_PUBLISHED = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62,
                 "VAL": 187.77}
PUBLISHED_COMBO = {"CONT": 536.53, "VAL": 308.16}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", os.path.join(
    BT, "v12-completions/holdings-champion-vm/run_sweep.py"))
sys.path.insert(0, os.path.join(BT, "lazy-quarterly"))
sys.path.insert(0, os.path.join(BT, "v12-completions/holdings-lazy-prices"))
import lq_common as Q  # noqa: E402
import engine_n as EN  # noqa: E402
NF = load_module("nf3_v13", os.path.expanduser(
    "~/workspace/stock-app/backtests/v13-best-rules/"
    "nf3-paying-in-stock/run_v13.py"))
C = Q.C


# ------------------------------------------------------------ sleeves
def vm_run(pb, dec, s, e, cash, seed=None):
    rng = random.Random(seed) if seed is not None else None
    sel = S.quarter_dates(pb, s, e)
    r = S.run_episode(pb, dec, set(sel), s, e, cash, None, 2,
                      placebo_rng=rng)
    return {"final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "curve": r["curve"]}


def lz_run(book, sims, uni, s, e, cash, seed=None):
    rng = random.Random(seed) if seed is not None else None
    r = EN.run_pot_n(book, sims, uni, s, e, 5, start_cash=cash,
                     floor0=-1e18, placebo_rng=rng)
    return {"final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "curve": r["curve"]}


def nf3_scores(caches, pond, sel_dates):
    scores = {}
    for d in sel_dates:
        sc = {}
        for t in pond:
            v, _st = caches[t].get(d)
            if v is not None:
                sc[t] = v
        scores[d] = sc
    return scores


def nf3_run(win, scores, sel_set, cash, seed=None):
    rng = random.Random(seed) if seed is not None else None
    r = NF.run_pot(win, scores, sel_set, 5, cash, float("-inf"),
                   placebo_rng=rng)
    return {"final": r["final"], "costs": r["costs"],
            "orders": r["orders"], "curve": r["curve"]}


# ------------------------------------------------------------ combine
def combine(sleeves):
    """sleeves: list of (start_cash, curve). Returns combined curve over
    the union of dates, each sleeve forward-filled at its last close,
    contributing start_cash before its first curve date."""
    dates = sorted({d for _c, curve in sleeves for d, _v in curve})
    idx = [0] * len(sleeves)
    last = [c for c, _curve in sleeves]
    out = []
    for d in dates:
        tot = 0.0
        for i, (_c, curve) in enumerate(sleeves):
            while idx[i] < len(curve) and curve[idx[i]][0] <= d:
                last[i] = curve[idx[i]][1]
                idx[i] += 1
            tot += last[i]
        out.append((d, tot))
    return out


def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d}


def period_distribution(curve):
    """Quarterly periods (calendar quarters) on the combined curve."""
    q_last = {}
    order = []
    for d, v in curve:
        q = (d[:4], (int(d[5:7]) - 1) // 3)
        if q not in q_last:
            order.append(q)
        q_last[q] = v
    changes = []
    prev = 100.0
    for q in order:
        changes.append(q_last[q] - prev)
        prev = q_last[q]
    n = len(changes)
    srt = sorted(changes)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = longest = 0
    for c in changes:
        streak = streak + 1 if c <= 0 else 0
        longest = max(longest, streak)
    peak = -1.0
    last_high = 0
    gap = 0
    for i, (_d, v) in enumerate(curve):
        if v >= peak:
            peak = v
            gap = max(gap, i - last_high)
            last_high = i
    gap = max(gap, len(curve) - 1 - last_high)
    return {"periods": n,
            "median_period_usd": round(median, 2),
            "share_positive_pct": round(
                100.0 * sum(1 for c in changes if c > 0) / n, 1),
            "best_period_usd": round(max(changes), 2),
            "worst_period_usd": round(min(changes), 2),
            "longest_losing_streak_qtrs": longest,
            "longest_between_new_highs_trading_days": gap,
            "mean_period_usd_secondary": round(sum(changes) / n, 2)}


def blend_run(ctx, road, s, e, seed=None):
    """ctx carries the road's loaded inputs. Returns combined result."""
    vm = vm_run(ctx["vm_pb"], ctx["vm_dec"], s, e, W["VM"], seed)
    lz = lz_run(ctx["lz_book"], ctx["lz_sims"], ctx["lz_uni"], s, e,
                W["LZ"], seed)
    if road == "LONG":
        nf = nf3_run(ctx["nf_win"], ctx["nf_scores"], ctx["nf_selset"],
                     W["NF3"], seed)
        curve = combine([(W["VM"], vm["curve"]), (W["LZ"], lz["curve"]),
                         (W["NF3"], nf["curve"])])
        nf_final = nf["final"]
    else:
        nf = nf3_run(ctx["nf_win"], ctx["nf_scores"], ctx["nf_selset"],
                     W["NF3"], seed)
        curve = combine([(W["VM"], vm["curve"]), (W["NF3"], nf["curve"]),
                         (W["LZ"], lz["curve"])])
        nf_final = nf["final"]
    parts = {"VM": vm, "NF3": nf, "LZ": lz}
    return {"final": round(sum(p["final"] for p in parts.values()), 2),
            "sleeve_finals": {k: round(p["final"], 2)
                              for k, p in parts.items()},
            "costs": round(sum(p["costs"] for p in parts.values()), 2),
            "orders": sum(p["orders"] for p in parts.values()),
            "curve": curve}


def run_road(out, road, ctx, s, e):
    t0 = time.time()
    # ---- integrity: sleeves at $100 under their sleeve forms
    integ = {}
    vm100 = vm_run(ctx["vm_pb"], ctx["vm_dec"], s, e, 100.0)
    integ["VM"] = {"expected_v13": VM_V13[road],
                   "got": round(vm100["final"], 2),
                   "match": abs(round(vm100["final"], 2)
                                - VM_V13[road]) < 0.02}
    nf100 = nf3_run(ctx["nf_win"], ctx["nf_scores"], ctx["nf_selset"],
                    100.0)
    integ["NF3"] = {"expected_v13": NF3_V13[road],
                    "got": round(nf100["final"], 2),
                    "match": abs(round(nf100["final"], 2)
                                 - NF3_V13[road]) < 0.02}
    lz100 = lz_run(ctx["lz_book"], ctx["lz_sims"], ctx["lz_uni"], s, e,
                   100.0)
    lz_entry = {"floorless_final": round(lz100["final"], 2),
                "published_form": LZ_PUBLISHED[road]}
    if road in ("CONT", "VAL"):
        lz_entry["expected"] = LZ_PUBLISHED[road]
        lz_entry["match"] = abs(round(lz100["final"], 2)
                                - LZ_PUBLISHED[road]) < 0.02
    integ["LZ"] = lz_entry
    print(f"INTEGRITY {road}: VM {integ['VM']} NF3 {integ['NF3']} "
          f"LZ {lz_entry}", flush=True)
    assert integ["VM"]["match"], f"VM integrity failed on {road}"
    assert integ["NF3"]["match"], f"NF3 integrity failed on {road}"
    if road in ("CONT", "VAL"):
        assert lz_entry["match"], f"LZ integrity failed on {road}"

    # ---- the one frozen run + 20 placebo twins
    r = blend_run(ctx, road, s, e)
    diag = diagnostics(r["curve"])
    twins = []
    for seed in SEEDS:
        pr = blend_run(ctx, road, s, e, seed=seed)
        twins.append(round(pr["final"], 2))
        print(f"  {road} placebo {seed}: ${pr['final']:,.2f}",
              flush=True)
    beaten = sum(1 for x in twins if r["final"] > x)
    sf = sorted(twins)
    cell = {"road": road, "window": [s, e],
            "weights_initial": W,
            "final": r["final"], "sleeve_finals": r["sleeve_finals"],
            "sleeve_end_shares_pct": {
                k: round(100.0 * v / r["final"], 1)
                for k, v in r["sleeve_finals"].items()},
            "costs": r["costs"], "orders": r["orders"],
            "max_dd_pct": diag["max_dd_pct"],
            "max_dd_date": diag["max_dd_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "spy_published": SPY_PUBLISHED[road],
            "placebo_beaten": beaten, "placebo_finals": sf,
            "placebo_median": round((sf[9] + sf[10]) / 2.0, 2),
            "placebo_best": sf[-1], "placebo_worst": sf[0],
            "integrity": integ,
            "period_distribution_quarterly": period_distribution(
                r["curve"]),
            "curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    out["roads"][road] = cell
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{road}: BLEND ${r['final']:,.2f} (VM ${r['sleeve_finals']['VM']:,.2f}"
          f" / NF3 ${r['sleeve_finals']['NF3']:,.2f}"
          f" / LZ ${r['sleeve_finals']['LZ']:,.2f}) maxDD "
          f"{diag['max_dd_pct']}% placebo {beaten}/20 "
          f"({time.time()-t0:.0f}s)", flush=True)
    return cell


def main():
    t0 = time.time()
    out = {"family": "combo-three-way (V+M x Lazy Prices x N-F3)",
           "program": "v13-best-rules",
           "spec": "separate sub-pots 50/30/20, no resets/transfers; "
                   "VM top-2 quarterly no floor; LZ top-5 quarterly no "
                   "floor (published form); NF3 top-5 semiannual no "
                   "floor; program costs",
           "roads": {}, "confirmation": None}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            out = json.load(f)

    # ================= phase A: DECADE / CONT / VAL (Nov-2016 ponds)
    if not all(r in out["roads"] for r in ("DECADE", "CONT", "VAL")):
        print("loading VM fixed inputs...", flush=True)
        pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
        all_sel = S.quarter_dates(pb, "2016-11-21", END)
        dec = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
        print("loading Lazy gap book...", flush=True)
        lazy, _pb2, sims = Q.gap_book()
        lz_book = C.FastPriceBook({t: lazy.get_prices(t)
                                   for t in lazy.UNIVERSE + ["SPY"]})
        print("loading NF3 2016-pond caches...", flush=True)
        nf_caches = NF.load_caches(NF.UNIVERSE)
        nf_pb = NF.build_book(NF.UNIVERSE)
        ctxA = {"vm_pb": pb, "vm_dec": dec, "lz_book": lz_book,
                "lz_sims": sims, "lz_uni": list(lazy.UNIVERSE)}
        # NF3 windows/scores are road-specific; build per road
        for road, s, e in (("DECADE", "2016-11-21", END),
                           ("CONT", "2019-01-02", END),
                           ("VAL", "2023-01-03", END)):
            if road in out["roads"]:
                continue
            days_all = [d for d in nf_pb.dates if s <= d <= e]
            sel = NF.cadence_dates(days_all, "semiannual")
            ctx = dict(ctxA)
            ctx["nf_win"] = NF.Window(nf_pb, NF.UNIVERSE, s, e)
            ctx["nf_scores"] = nf3_scores(nf_caches, NF.UNIVERSE, sel)
            ctx["nf_selset"] = set(sel)
            run_road(out, road, ctx, s, e)
        # keep phase-A context for a possible confirmation
        globals()["_CTXA"] = (ctxA, nf_caches, nf_pb)
        del pb, dec, lz_book
        gc.collect()

    # ================= phase B: LONG (2010 / 2012 ponds)
    if "LONG" not in out["roads"]:
        print("loading VM long inputs...", flush=True)
        pbL, pit_eqL, pit_shL, pondL, _info = S.build_long_inputs()
        selL = S.quarter_dates(pbL, "2010-01-04", END)
        decL = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL)
        print("loading Lazy 2010 book...", flush=True)
        pond10 = Q.pond2010()
        bars10 = {t: C.bars_adj(C.yahoo_payload(t)) for t in pond10}
        bars10["SPY"] = C.bars_adj(C.yahoo_payload("SPY"))
        lz_bookL = C.FastPriceBook(bars10)
        simsL = Q.era_signals()
        print("loading NF3 2012-pond caches...", flush=True)
        nf_cachesL = NF.load_caches(NF.LONG_POND)
        nf_pbL = NF.build_book(NF.LONG_POND)
        days_nf = [d for d in nf_pbL.dates if "2012-10-01" <= d <= END]
        sel_nf = NF.cadence_dates(days_nf, "semiannual")
        ctxL = {"vm_pb": pbL, "vm_dec": decL, "lz_book": lz_bookL,
                "lz_sims": simsL, "lz_uni": pond10,
                "nf_win": NF.Window(nf_pbL, NF.LONG_POND, "2012-10-01",
                                    END),
                "nf_scores": nf3_scores(nf_cachesL, NF.LONG_POND, sel_nf),
                "nf_selset": set(sel_nf)}
        run_road(out, "LONG", ctxL, "2010-01-04", END)
        del pbL, decL, lz_bookL
        gc.collect()

    # ================= confirmation (only if the bar is met)
    cont = out["roads"].get("CONT")
    val = out["roads"].get("VAL")
    bar_met = bool(cont and val and
                   all(cont["final"] > v for v in BAR["CONT"].values())
                   and all(val["final"] > v for v in BAR["VAL"].values()))
    out["bar_met"] = bar_met
    print(f"ADOPTION BAR MET: {bar_met}", flush=True)
    if bar_met and not out.get("confirmation"):
        ctxA, nf_caches, nf_pb = globals()["_CTXA"]
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            days_all = [d for d in nf_pb.dates if s <= d <= e]
            sel = NF.cadence_dates(days_all, "semiannual")
            ctx = dict(ctxA)
            ctx["nf_win"] = NF.Window(nf_pb, NF.UNIVERSE, s, e)
            ctx["nf_scores"] = nf3_scores(nf_caches, NF.UNIVERSE, sel)
            ctx["nf_selset"] = set(sel)
            br = blend_run(ctx, "CONT", s, e)
            vmf = vm_run(ctxA["vm_pb"], ctxA["vm_dec"], s, e, 100.0)
            folds[str(yr)] = {"blend": br["final"],
                              "vm_v13": round(vmf["final"], 2),
                              "blend_win": br["final"] > vmf["final"]}
            print(f"FOLD {yr}: blend ${br['final']:,.2f} vs VM-v13 "
                  f"${vmf['final']:,.2f} win={folds[str(yr)]['blend_win']}",
                  flush=True)
        wins = sum(1 for v in folds.values() if v["blend_win"])
        out["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026, blend "
                      "vs V+M v13 form head-to-head",
            "folds": folds, "fold_wins": f"{wins}/10",
            "confirmed": wins >= 6}
        print(f"CONFIRMATION: {wins}/10 folds", flush=True)
    out["elapsed_sec"] = round(time.time() - t0, 1)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
