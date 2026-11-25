#!/usr/bin/env python3
"""
PIOTROSKI F-SCORE — THE GREAT RETEST (v10), CADENCE SWEEP.

Strategy (unchanged from v6/v9): within the champion's point-in-time
pond, take the cheapest third by book-to-market, rank by Piotroski
F-score (0-9, >=7 of 9 signals computable, missing input = 0), hold
top 5 equal-weight. Engine mechanics are the v9 module's
run_pot_piotroski BYTE-IDENTICAL — the only change is the selection-date
source: E.quarter_selection_dates is patched per cell to return the
cell's cadence dates (SPEC uniform cadence definition), which also
drives the v9 restart point (next cadence date >= halt + 90 days).

Phases:
  (0) INTEGRITY — original cache prices, original quarterly form,
      his-rules plain floor (no restart): CONT must reproduce $88.10
      (halted 2020-03-12), VAL must reproduce $293.24.
  (1) SWEEP — DECADE 2016-11-21 -> 2026-11-20 (full-decade Yahoo prices
      fetched with the original engine's own method into ./data;
      SPY decade on this plumbing = $367.80, the SPEC reference),
      7 cadences x (ranked + 20 placebo seeds), v9 protections per pot.
      $100/cell, program costs (0.10%/side + $0.01/share sell charge).

Native cadence: ANNUAL (Piotroski 2000: score after annual filings,
hold one year). The original program test ran QUARTERLY — a foreign
cadence, flagged.

Documented artifacts (never patched): F-scores bunch on mega-caps;
JPM (long-term debt untagged after 2013 -> <7 computable signals) and
BRK-B (unclassified balance sheet) are unscorable whenever they enter
the cheapest third.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "piotroski_engine", os.path.join(HERE, "piotroski_engine.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
E = M.E

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


class FastPB(E.PriceBook):
    """PriceBook with bisect close_on_or_before — identical results to
    the engine's linear scan, faster on the decade's 2,738 bars."""

    def __init__(self, bars_by_ticker):
        super().__init__(bars_by_ticker)
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ------------------------------------------- exact-semantics fast paths
# The engine's pit_value / _at_end are linear scans with per-row date
# parsing; at daily cadence over a decade they dominate the runtime.
# The indexed versions below return IDENTICAL results (same winner
# under the same (filed, prio, end) key, same freshness gate, same
# strict-> tie handling) via precomputed per-series indexes. They are
# installed ONLY after (a) the integrity gate passes on the original
# code path and (b) an exact-equality check of compute_selection
# (pool, third, candidate scores, picks) on sampled decade dates.
_PIT_IDX = {}
_AE_IDX = {}


def _pit_index(rows):
    idx = _PIT_IDX.get(id(rows))
    if idx is None:
        by_filed = {}
        for filed, end, val, prio in rows:
            cur = by_filed.get(filed)
            if cur is None or (prio, end) > cur[:2]:
                by_filed[filed] = (prio, end, val)
        dates = sorted(by_filed)
        idx = (dates, [_ord(d) for d in dates], by_filed)
        _PIT_IDX[id(rows)] = idx
    return idx


def pit_value_fast(rows, asof, max_age_days=548):
    dates, ords, by_filed = _pit_index(rows)
    i = bisect.bisect_left(dates, asof) - 1
    if i < 0 or ords[i] < _ord(asof) - max_age_days:
        return None
    filed = dates[i]
    prio, end, val = by_filed[filed]
    return (filed, end, val)


def _ae_steps(rows, e_ord, tol=20):
    per = _AE_IDX.setdefault(id(rows), {})
    sub = per.get(e_ord)
    if sub is None:
        cands = [r for r in rows if abs(_ord(r[1]) - e_ord) <= tol]
        cands.sort(key=lambda r: r[0])  # stable: same-filed order preserved
        steps, best = [], None
        for filed, end, val, prio in cands:
            k = (filed, prio, end)
            if best is None or k > best[0]:
                best = (k, val)
            steps.append((filed, best[1]))
        sub = ([s[0] for s in steps], [s[1] for s in steps])
        per[e_ord] = sub
    return sub


def at_end_fast(rows, e_ord, asof, tol=20):
    filed_list, vals = _ae_steps(rows, e_ord, tol)
    i = bisect.bisect_left(filed_list, asof) - 1
    return vals[i] if i >= 0 else None


# ------------------------------------------------------------ cadences
def cadence_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        # E.quarter_selection_dates verbatim (inlined: during the sweep
        # that attribute is patched per-cell, so it cannot be called here)
        out = []
        seen_q = set()
        for d in days:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen_q:
                seen_q.add(key)
                out.append(d)
        return out
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        for d in days:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "semiannual":
        for d in days:
            if d[5:7] in ("01", "07"):
                key = (d[:4], d[5:7])
                if key not in seen:
                    seen.add(key)
                    out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            key = d[:4]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(cadence)


# ------------------------------------------------- v9 episode wrapper
def run_cell(pb, data, start, end, cad_dates, placebo_rng=None):
    """M.run_v9 mirrored, with the restart point = next CADENCE date
    >= halt + 90 calendar days (patched selection-date source makes the
    engine itself use cadence dates). Returns merged result."""
    floor1 = round(0.85 * START_CASH, 2)
    r1 = M.run_pot_piotroski(pb, data, start, end, START_CASH, floor1,
                             [], placebo_rng=placebo_rng, quiet=True)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halts": [], "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        return out
    out["halts"].append({"episode": 1, "signal_date": r1["halted"],
                         "signal_close": r1["halt_info"]["signal_close"],
                         "floor_in_effect": r1["halt_info"]["floor_in_effect"],
                         "liquidation_date": r1["end"],
                         "episode_final": round(r1["final"], 2)})
    liq, cash = r1["end"], r1["final"]
    day90 = _ord(r1["halted"]) + 90
    restart = next((c for c in cad_dates if _ord(c) >= day90), None)
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"], "liquidation_date": liq,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = M.run_pot_piotroski(pb, data, restart, end, cash, floor2,
                             [], placebo_rng=placebo_rng, quiet=True)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        sh = {"episode": 2, "signal_date": r2["halted"],
              "signal_close": r2["halt_info"]["signal_close"],
              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
              "liquidation_date": r2["end"],
              "final": round(r2["final"], 2)}
        out["second_halt"] = sh
        out["halts"].append(sh)
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def cell_stats(res, start, end):
    curve = res["curve"]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (_ord(end) - _ord(start)) / 365.25
    cagr = (res["final"] / START_CASH) ** (1.0 / years) - 1.0
    return {"final": round(res["final"], 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(res["costs"], 2),
            "orders": res["orders"],
            "halts": res["halts"], "restarts": res["restarts"],
            "second_halt": res["second_halt"],
            "curve": [[d, round(v, 2)] for d, v in curve]}


# ---------------------------------------------------------------- main
def main():
    t_start = time.time()
    # ---- load fundamentals once (EDGAR cache, read-only via engine)
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows, concepts = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                          E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        concepts[t] = M.build_concept_rows(facts)
        time.sleep(0.05)
    data = {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}
    print("fundamentals loaded", flush=True)

    # ================= (0) INTEGRITY — original cache, original form
    bars0 = {t: E.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb0 = FastPB(bars0)
    integ = {}
    for tag, (ws, we), published in (("CONT", CONT, 88.10), ("VAL", VAL, 293.24)):
        r = M.run_pot_piotroski(pb0, data, ws, we, START_CASH, 85.0, [],
                                label=f"INTEGRITY {tag}", quiet=True)
        spy, _ = E.spy_net(pb0, ws, we, START_CASH)
        integ[tag] = {"final": round(r["final"], 2), "published": published,
                      "match": round(r["final"], 2) == published,
                      "halted": r["halted"], "orders": len(r["trades"]),
                      "costs": round(r["costs"], 2), "spy_net": round(spy, 2)}
        print(f"INTEGRITY {tag}: final=${r['final']:,.2f} published=${published} "
              f"match={integ[tag]['match']} halted={r['halted']} SPY=${spy:,.2f}",
              flush=True)
    M.SELECTION_CACHE.clear()
    assert integ["CONT"]["match"] and integ["VAL"]["match"], \
        "INTEGRITY GATE FAILED — sweep does not count"

    # ================= (1) SWEEP — decade prices fetched in ./data
    bars = json.load(open(os.path.join(HERE, "data", "decade_bars.json")))
    pb = FastPB(bars)

    # ---- equivalence check: original vs indexed selection, exact
    sample = ["2016-11-21", "2017-03-01", "2017-06-15", "2018-02-01",
              "2018-09-04", "2019-01-02", "2019-07-01", "2020-03-12",
              "2020-11-02", "2021-05-03", "2022-01-03", "2022-10-03",
              "2023-01-03", "2023-08-01", "2024-04-01", "2025-01-02",
              "2025-09-02", "2026-01-02", "2026-06-01", "2026-11-02"]
    ref = {}
    for d in sample:
        M.SELECTION_CACHE.clear()
        s = M.compute_selection(pb, d, data)
        ref[d] = (dict(s["pool"]), list(s["third"]),
                  {t: (v[0], v[1]) for t, v in s["cand"].items()},
                  list(s["picks"]))
    orig_pit, orig_ae = E.pit_value, M._at_end
    E.pit_value, M._at_end = pit_value_fast, at_end_fast
    for d in sample:
        M.SELECTION_CACHE.clear()
        s = M.compute_selection(pb, d, data)
        got = (dict(s["pool"]), list(s["third"]),
               {t: (v[0], v[1]) for t, v in s["cand"].items()},
               list(s["picks"]))
        assert got == ref[d], f"FAST-PATH MISMATCH at {d}"
    M.SELECTION_CACHE.clear()
    print(f"FAST-PATH EQUIVALENCE: exact on {len(sample)} sampled dates",
          flush=True)
    spy_dec, _ = E.spy_net(pb, DEC_START, DEC_END, START_CASH)
    print(f"SPY DECADE (this plumbing): ${spy_dec:,.2f}", flush=True)

    orig_qsd = E.quarter_selection_dates
    cells = {}
    try:
        for cad in CADENCES:
            dates = cadence_dates(pb, DEC_START, DEC_END, cad)
            # patch the engine's selection-date source for this cell
            E.quarter_selection_dates = (
                lambda pb_, s, e, _d=dates: [d for d in _d if s <= d <= e])
            t0 = time.time()
            ranked = run_cell(pb, data, DEC_START, DEC_END, dates)
            rst = cell_stats(ranked, DEC_START, DEC_END)
            twins = []
            for seed in range(1, 21):
                rng = random.Random(seed)
                tw = run_cell(pb, data, DEC_START, DEC_END, dates,
                              placebo_rng=rng)
                tst = cell_stats(tw, DEC_START, DEC_END)
                twins.append({"seed": seed, "final": tst["final"],
                              "cagr_pct": tst["cagr_pct"],
                              "max_dd_pct": tst["max_dd_pct"],
                              "costs": tst["costs"], "orders": tst["orders"],
                              "halts": tst["halts"],
                              "restarts": tst["restarts"],
                              "second_halt": tst["second_halt"]})
                print(f"  [{cad}] twin s{seed}: ${tst['final']:,.2f}", flush=True)
            tfin = sorted(tw["final"] for tw in twins)
            n_beat = sum(1 for v in tfin if rst["final"] > v)
            median = E._pct(tfin, 0.50)
            cell = dict(rst)
            cell.update({
                "cadence": cad, "window": [DEC_START, DEC_END],
                "n_selection_dates": len(dates),
                "placebo_beaten": n_beat,
                "placebo_median_twin": round(median, 2),
                "placebo_twin_finals": tfin,
                "placebo_twins": twins,
                "spy_final": round(spy_dec, 2),
                "beats_spy": rst["final"] > spy_dec})
            with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
                json.dump(cell, f, indent=1, default=str)
            cells[cad] = {k: cell[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                           "placebo_beaten", "placebo_median_twin", "beats_spy")}
            cells[cad]["halts"] = len(cell["halts"])
            cells[cad]["restart"] = bool(cell["restarts"])
            cells[cad]["second_halt"] = bool(cell["second_halt"])
            print(f"== CELL {cad}: final=${rst['final']:,.2f} CAGR={rst['cagr_pct']}% "
                  f"maxDD={rst['max_dd_pct']}% costs=${rst['costs']:,.2f} "
                  f"orders={rst['orders']} halts={len(cell['halts'])} "
                  f"placebo {n_beat}/20 median twin=${median:,.2f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    finally:
        E.quarter_selection_dates = orig_qsd

    # ---- coverage / artifact stats from the cached selections
    pick_scores, cand_scores = [], []
    jpm = {"in_third": 0, "scorable": 0}
    brk = {"in_third": 0, "scorable": 0}
    for d, sel in M.SELECTION_CACHE.items():
        for t, fs in sel["cand"].items():
            cand_scores.append(fs[0])
        for t in sel["picks"]:
            if t in sel["cand"]:
                pick_scores.append(sel["cand"][t][0])
        td = sel["third_detail"]
        if "JPM" in td:
            jpm["in_third"] += 1
            jpm["scorable"] += 1 if td["JPM"] is not None and td["JPM"][1] >= 7 else 0
        if "BRK-B" in td:
            brk["in_third"] += 1
            brk["scorable"] += 1 if td["BRK-B"] is not None and td["BRK-B"][1] >= 7 else 0
    cand_scores.sort()
    coverage = {
        "n_selection_dates_cached": len(M.SELECTION_CACHE),
        "candidate_fscore_median": cand_scores[len(cand_scores) // 2] if cand_scores else None,
        "candidate_fscore_max": cand_scores[-1] if cand_scores else None,
        "candidate_fscore_n9": sum(1 for s in cand_scores if s == 9),
        "candidate_count": len(cand_scores),
        "pick_fscores": pick_scores,
        "JPM": jpm, "BRK-B": brk}
    print("COVERAGE:", json.dumps(coverage), flush=True)

    out = {"slug": "piotroski", "integrity": integ,
           "decade_spy_final": round(spy_dec, 2), "cells": cells,
           "coverage": coverage,
           "runtime_s": round(time.time() - t_start, 1)}
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
