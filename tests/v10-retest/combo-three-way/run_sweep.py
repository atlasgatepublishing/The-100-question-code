#!/usr/bin/env python3
"""
W11 — COMBO-THREE-WAY CADENCE SWEEP (THE GREAT RETEST v10). Simulation only.

Strategy: the three-way blend — champion (value+momentum) + Lazy Prices
+ N-F3 "Paying in Stock" as three equal sleeves of ONE $100 pot, sleeve
weights reset to equal thirds at each selection date, one combined
-15% floor. Engine: the v9 implementation imported verbatim
(backtests/v9-muse-rules/combo-three-way/combo-three-way-v9.py —
run_combo / run_combo_v9 / Scorer, unmodified). $100/cell, program
costs (0.10%/side + $0.01 per sell order, charged inside each sleeve
exactly as in the parent engines), adopted v9 protection (plain -15%
floor, 90-day sit-out, restart at the strategy's next regular decision
point under an episode-2 floor, second halt ends the run).

CADENCE TREATMENT (SPEC uniform definition, stated plainly): the
cadence governs ALL THREE LEGS UNIFORMLY. One shared selection
calendar drives every sleeve at once: on a cadence date all three
sleeves are re-scored, re-ranked and re-picked (top-5 each), sleeve
budgets reset to equal thirds of the combined pot, and trades execute
at the next open. There are no per-leg tempos in this sweep — VM, LZ
and NF3 all move at the cell's cadence, and the v9 restart also lands
on the next cadence date on/after liquidation+90 days (the strategy's
next regular decision point at that tempo). The ONLY code change vs
the v9 engine is the selection-calendar function
(champ.quarter_selection_dates is replaced per cell — the exact
technique the lazy-prices sweep used); signal, scoring, sleeve
machinery, cost code, floor mechanics and placebo design are the
v9 engine's own, unmodified. One speed-only change: share prices are
read through a bisect-indexed wrapper whose close_on_or_before
returns exactly the champion PriceBook's value (last bar on/before
the date) — verified against the original book in the integrity gate.

Road: DECADE 2016-11-21 -> 2026-11-20 for every cell, on the same
book the program's decade runs use (the champion's shared price
cache, first bars 2017-06-01 — the identical book/plumbing family
that produced the champion's decade $65.89 in the lazy-quarterly
test; dates before the first bar simply have no trades).

INTEGRITY (run first, abort on failure): the v9 combo in its
ORIGINAL form (quarterly calendar, CONT 2019-01-02->2026-11-20 and
VAL 2023-01-03->2026-11-20) must reproduce the published finals
CONT $536.53 / VAL $308.16, and the three parents standalone must
reproduce V+M $544.47/$288.05, Lazy $504.34/$324.12, N-F3
$505.43/$289.53, SPY $313.62/$187.77.

Placebos: 20 seeds (1..20) per cell — the v9 engine's own design:
each sleeve draws 5 random names from its OWN eligible pool at each
selection date (draw order VM, LZ, NF3), identical dates/mechanics/
resets and the same v9 protection, one random.Random(seed) per run.

Shared inputs are READ-ONLY (v4/v7/v8 engine modules and their
caches). All outputs are written only inside this folder.
"""
import bisect
import json
import math
import os
import random
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V9 = os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/combo-three-way/"
    "combo-three-way-v9.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib.util


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load("combo_three_way_v9", V9)
champ, lz, nf3 = M.champ, M.lz, M.nf3
UNIVERSE = M.UNIVERSE
DS, DE = "2016-11-21", "2026-11-20"
CELLS_DIR = os.path.join(HERE, "cells")
os.makedirs(CELLS_DIR, exist_ok=True)
SPY_SPEC = 367.80
CHAMPION_DECADE = 65.89


# ------------------------------------------------------------ fast book
class FastBook:
    """Bisect wrapper: bar()/close_on_or_before() return exactly what
    the champion PriceBook returns, in O(log n)."""

    def __init__(self, bars):
        self.bars = bars
        self.dates = sorted({b["d"] for bl in bars.values() for b in bl})
        self._idx = {t: {b["d"]: b for b in bl} for t, bl in bars.items()}
        self._ds = {t: [b["d"] for b in bl] for t, bl in bars.items()}

    def bar(self, t, d):
        return self._idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self._ds.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ------------------------------------------------------------- cadences
def _firsts(pb, start, end, keyfn):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            k = keyfn(d)
            if k not in seen:
                seen.add(k)
                out.append(d)
    return out


def cad_daily(pb, start, end):
    return [d for d in pb.dates if start <= d <= end]


def cad_weekly(pb, start, end):
    def key(d):
        iso = date.fromisoformat(d).isocalendar()
        return (iso[0], iso[1])
    return _firsts(pb, start, end, key)


def cad_biweekly(pb, start, end):
    return cad_weekly(pb, start, end)[::2]


def cad_monthly(pb, start, end):
    return _firsts(pb, start, end, lambda d: (d[:4], d[5:7]))


def cad_quarterly(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def cad_semiannual(pb, start, end):
    return _firsts(pb, start, end,
                   lambda d: (d[:4], "H1" if d[5:7] <= "06" else "H2"))


def cad_annual(pb, start, end):
    return _firsts(pb, start, end, lambda d: d[:4])


CADENCES = {"daily": cad_daily, "weekly": cad_weekly,
            "biweekly": cad_biweekly, "monthly": cad_monthly,
            "quarterly": cad_quarterly, "semiannual": cad_semiannual,
            "annual": cad_annual}
# priority: native (quarterly) first, then cheaper cells, daily last
ORDER = ["quarterly", "monthly", "semiannual", "annual", "biweekly",
         "weekly", "daily"]


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(pos // 1), int(-(-pos // 1))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def diag(curve):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    yrs = (date.fromisoformat(DE) - date.fromisoformat(DS)).days / 365.25
    return maxdd * 100.0, maxdd_d, yrs


def summarize(r, curve_years):
    maxdd, maxdd_d, yrs = diag(r["curve"])
    final = round(r["final"], 2)
    halts = []
    if r["halted"]:
        halts.append({"episode": 1, "signal_date": r["halted"],
                      "signal_close": r["halt_info"]["signal_close"],
                      "floor_in_effect": r["halt_info"]["floor_in_effect"],
                      "liquidation_date": r["restarts"][0][
                          "liquidation_date"] if r["restarts"] else None})
    if r["second_halt"]:
        halts.append({"episode": 2,
                      "signal_date": r["second_halt"]["signal_date"],
                      "signal_close": r["second_halt"]["signal_close"],
                      "floor_in_effect": r["second_halt"]["floor_in_effect"],
                      "liquidation_date": r["second_halt"][
                          "liquidation_date"]})
    return {
        "final": final,
        "cagr_pct": round(((final / 100.0) ** (1.0 / curve_years) - 1.0)
                          * 100.0, 2),
        "max_dd_pct": round(maxdd, 2), "max_dd_date": maxdd_d,
        "costs": round(r["costs"], 2), "orders": len(r["trades"]),
        "halts": halts, "n_halts": len(halts),
        "restart": r["restarts"][0] if r["restarts"] else None,
        "second_halt": bool(r["second_halt"]),
        "episodes": r["episodes"],
        "sleeve_finals": {k: round(v, 2)
                          for k, v in r["sleeve_finals"].items()},
        "curve": [[d, round(v, 4)] for d, v in r["curve"]]}


def main():
    # ---------------- data (read-only shared caches)
    ciks = champ.get_ciks()
    facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3)
            + champ.pit_series(facts, "us-gaap",
                               "CommonStockSharesOutstanding", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {t: champ.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb_orig = champ.PriceBook(bars)
    pb = FastBook(bars)
    # wrapper equivalence spot-check (speed change must not move a cent)
    for t in UNIVERSE[:5] + ["SPY"]:
        for d in pb.dates[::37]:
            assert pb.close_on_or_before(t, d) == \
                pb_orig.close_on_or_before(t, d), (t, d)
    print("FastBook equivalence check passed", flush=True)
    # Lazy signals from the gap-a5 module's own cached output file
    # (the identical signals lz.build_signals() produces and the
    # lazy-quarterly plumbing loads) — loading the cache instead of
    # rebuilding keeps the 20M-token corpus out of RAM (an earlier
    # attempt that rebuilt signals in-process died silently under
    # shared-RAM contention after the build; the integrity gate below
    # validates these signals to the cent via the LZ parent finals).
    with open(os.path.expanduser(
            "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/"
            "data/similarities.json")) as f:
        signals = json.load(f)["signals"]
    scorer = M.Scorer(pb, equity_rows, shares_rows, facts_by_ticker,
                      signals)
    orig_cal = champ.quarter_selection_dates

    # ---------------- INTEGRITY: original v9 form, quarterly calendar
    champ.quarter_selection_dates = orig_cal
    integ = {}
    for wname, ws, we, want_combo in (
            ("CONT", "2019-01-02", "2026-11-20", 536.53),
            ("VAL", "2023-01-03", "2026-11-20", 308.16)):
        vm = champ.run_pot(pb, equity_rows, shares_rows, ws, we, 100.0,
                           85.0, [], label="integ VM", quiet=True)
        print(f"INTEGRITY {wname} VM done ${vm['final']:,.2f}",
              flush=True)
        lzr = lz.run_pot(pb, signals, ws, we)
        print(f"INTEGRITY {wname} LZ done ${lzr['final']:,.2f}",
              flush=True)
        st = {"direct": 0, "derived": 0}
        f3 = nf3.run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                         label="integ NF3", stats=st)
        print(f"INTEGRITY {wname} NF3 done ${f3['final']:,.2f}",
              flush=True)
        spy, _ = champ.spy_net(pb, ws, we, 100.0)
        r = M.run_combo_v9(pb, scorer, ws, we, 100.0,
                           label=f"integ {wname}")
        got = {"VM": round(vm["final"], 2), "LZ": round(lzr["final"], 2),
               "NF3": round(f3["final"], 2), "SPY": round(spy, 2),
               "COMBO": round(r["final"], 2)}
        want = {"VM": M.PUBLISHED["VM"]["FULL" if wname == "CONT" else "VALIDATION"],
                "LZ": M.PUBLISHED["LZ"]["FULL" if wname == "CONT" else "VALIDATION"],
                "NF3": M.PUBLISHED["NF3"]["FULL" if wname == "CONT" else "VALIDATION"],
                "SPY": M.PUBLISHED["SPY"]["FULL" if wname == "CONT" else "VALIDATION"],
                "COMBO": want_combo}
        for k in want:
            print(f"INTEGRITY {wname} {k}: got ${got[k]:,.2f} "
                  f"want ${want[k]:,.2f}", flush=True)
            assert abs(got[k] - want[k]) < 0.05, \
                f"INTEGRITY FAIL {wname} {k}: {got[k]} != {want[k]}"
        integ[wname] = {"got": got, "want": want,
                        "combo_halts": (1 if r["halted"] else 0)
                        + (1 if r["second_halt"] else 0),
                        "combo_costs": round(r["costs"], 2),
                        "combo_orders": len(r["trades"])}
    print("INTEGRITY PASSED: CONT $536.53 / VAL $308.16 reproduced",
          flush=True)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integ, f, indent=1, default=str)

    spy_decade_plumbing, _ = champ.spy_net(pb, DS, DE, 100.0)
    print(f"SPY decade plumbing ${spy_decade_plumbing:,.2f} "
          f"(SPEC dividend-adjusted ${SPY_SPEC})", flush=True)

    # ---------------- SWEEP
    _, _, yrs = diag([(DS, 100.0)])
    summary = {}
    for cadence in ORDER:
        champ.quarter_selection_dates = CADENCES[cadence]
        r = M.run_combo_v9(pb, scorer, DS, DE, 100.0,
                           label=f"decade {cadence}")
        s = summarize(r, yrs)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pr = M.run_combo_v9(pb, scorer, DS, DE, 100.0,
                                placebo_rng=rng,
                                label=f"decade {cadence} PL{seed}")
            ps = summarize(pr, yrs)
            twins.append({"seed": seed, "final": ps["final"],
                          "costs": ps["costs"], "orders": ps["orders"],
                          "halts": ps["n_halts"],
                          "halt_dates": [h["signal_date"]
                                         for h in ps["halts"]]})
            print(f"  {cadence} placebo {seed}: ${ps['final']:,.2f} "
                  f"halts={ps['n_halts']}", flush=True)
        finals = sorted(t["final"] for t in twins)
        beats = sum(1 for x in finals if s["final"] > x)
        payload = {
            "slug": "combo-three-way", "cadence": cadence,
            "window": [DS, DE], "start_cash": 100.0,
            "final": s["final"], "cagr_pct": s["cagr_pct"],
            "max_dd_pct": s["max_dd_pct"], "max_dd_date": s["max_dd_date"],
            "costs": s["costs"], "orders": s["orders"],
            "halts": s["halts"], "n_halts": s["n_halts"],
            "restart": s["restart"], "second_halt": s["second_halt"],
            "episodes": s["episodes"], "sleeve_finals": s["sleeve_finals"],
            "spy_final_plumbing": round(spy_decade_plumbing, 2),
            "spy_final_spec_dividend_adjusted": SPY_SPEC,
            "champion_decade_final": CHAMPION_DECADE,
            "placebo": {"beaten": beats, "of": 20,
                        "median": round(pct(finals, 0.5), 2),
                        "best": finals[-1], "worst": finals[0],
                        "finals_sorted": finals, "twins": twins,
                        "note": "20 random-rank twins (each sleeve draws "
                                "5 random names from its own eligible "
                                "pool), seeds 1..20, v9-wrapped, same "
                                "cadence calendar as the ranked run"},
            "equity_curve": s["curve"],
            "cadence_treatment": "cadence governs ALL THREE legs "
                                 "uniformly: one shared selection "
                                 "calendar re-scores/re-ranks/re-picks "
                                 "VM, LZ and NF3 together and resets "
                                 "sleeve budgets to equal thirds; v9 "
                                 "restart lands on the next cadence "
                                 "date on/after liquidation+90d",
            "source": "fresh run in this folder's run_sweep.py (v9 "
                      "combo engine verbatim, selection calendar "
                      "replaced only)"}
        with open(os.path.join(CELLS_DIR, f"{cadence}.json"), "w") as f:
            json.dump(payload, f, indent=1, default=str)
        summary[cadence] = (s, beats)
        print(f"saved cells/{cadence}.json final ${s['final']:,.2f} "
              f"halts={s['n_halts']} placebo {beats}/20", flush=True)

    champ.quarter_selection_dates = orig_cal
    cells, money = {}, []
    for cadence in ["daily", "weekly", "biweekly", "monthly",
                    "quarterly", "semiannual", "annual"]:
        s, beats = summary[cadence]
        cells[cadence] = {
            "final": s["final"], "cagr_pct": s["cagr_pct"],
            "max_dd_pct": s["max_dd_pct"], "halts": s["n_halts"],
            "restart": bool(s["restart"]),
            "second_halt": s["second_halt"], "costs": s["costs"],
            "orders": s["orders"], "placebo_beaten": beats,
            "placebo_note": "20 random-rank twins (seeds 1..20), "
                            "v9-wrapped, same cadence; full twin "
                            "finals in cells/<cadence>.json"}
        if s["final"] > SPY_SPEC and beats == 20:
            money.append(cadence)
    out = {
        "slug": "combo-three-way",
        "area": "long-horizon three-way blend (champion + Lazy Prices "
                "+ N-F3, equal thirds, quarterly reset) — judged in "
                "this sweep on the DECADE road at every cadence",
        "area_source": "SPEC THE CADENCE SWEEP (Terry 2026-11-21 "
                       "~22:09); W11 assignment: combos = long-horizon "
                       "blends, quarterly native",
        "native_cadence": "quarterly",
        "cadence": "quarterly (with annual January reset per the "
                   "CADENCE GRID's W11 note — in the engine the reset "
                   "is the quarterly equal-thirds reset itself)",
        "original_cadence_foreign": False,
        "original_cadence_note": "Not foreign. The original v8/v9 "
                                 "tests already ran the blend "
                                 "quarterly (first trading day of "
                                 "Jan/Apr/Jul/Oct, all three legs "
                                 "together).",
        "cadence_treatment": "The cadence governs ALL THREE legs "
                             "uniformly: one shared selection calendar "
                             "re-scores, re-ranks and re-picks VM, LZ "
                             "and NF3 together, resets sleeve budgets "
                             "to equal thirds of the combined pot, "
                             "trades at the next open; the v9 restart "
                             "lands on the next cadence date on/after "
                             "liquidation+90 days.",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT": 536.53, "VAL": 308.16},
            "reproduced_finals": {"CONT": integ["CONT"]["got"]["COMBO"],
                                  "VAL": integ["VAL"]["got"]["COMBO"]},
            "detail": "v9 implementation reproduced in original form "
                      "(quarterly calendar, CONT/VAL) in this run; "
                      "parents also reproduced to the cent (VM "
                      "544.47/288.05, LZ 504.34/324.12, NF3 "
                      "505.43/289.53, SPY 313.62/187.77). Original v9 "
                      "main windows had ZERO halts (worst closes "
                      "$97.43 CONT / $99.17 VAL — the floor never "
                      "fired). The v8 his-rules folder's saved "
                      "results (different, curve-sum construction) "
                      "printed CONT $529.31 / VAL $305.76 — noted, "
                      "not the canonical form. (The task brief's "
                      "$537.24/$302.91 v8 figures and 'quarters 9/11, "
                      "halts 7' do not match either saved results "
                      "file; the saved files govern.)",
            "integrity_windows": integ},
        "decade_spy_final": SPY_SPEC,
        "decade_spy_note": "SPEC-verified dividend-adjusted figure. "
                           "This plumbing's own SPY net on the same "
                           "book is saved per cell as "
                           "spy_final_plumbing; money-cadence calls "
                           "use the stricter $367.80 hurdle.",
        "champion_decade": {
            "final": CHAMPION_DECADE,
            "note": "Value+Momentum on this decade road: halted "
                    "2018-12-21, restarted 2019-04-01, second halt "
                    "2020-03-20, run ended at $65.89. Its crown rests "
                    "on the 2010 road ($1,415.62) and the 2019 road "
                    "($544.47 CONT / $288.05 VAL)."},
        "champion_reference": {"LONG": 1415.62, "CONT": 544.47,
                               "VAL": 288.05, "DECADE": CHAMPION_DECADE},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,
        "verdict_change": None}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved results.json; money_cadences:", money, flush=True)


if __name__ == "__main__":
    main()
