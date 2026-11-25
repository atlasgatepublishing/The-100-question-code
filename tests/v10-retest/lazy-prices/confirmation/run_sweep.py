#!/usr/bin/env python3
"""
W13 — LAZY PRICES CADENCE SWEEP (THE GREAT RETEST v10). Simulation only.

Strategy: Lazy Prices (Cohen-Malloy-Nguyen 2020) — rank the honest
Nov-2016 top-30 pond by most-recent 10-K whole-document cosine
similarity, hold top-5 equal weight. $100/cell, program costs
(0.10%/side + $0.01 per sell order, the original engine's own cost
code), adopted v9 protection (plain -15% floor, 90-day sit-out, one
restart under an episode-2 floor, second halt ends the run).

Road: DECADE 2016-11-21 -> 2026-11-20 for every cell.

Cadence (SPEC uniform definition): signal re-evaluation, re-ranking
and rebalancing happen ONLY on cadence dates:
  daily       = every trading day
  weekly      = first trading day of each ISO week
  biweekly    = first trading day of every second ISO week (anchored
                on the first week of the window)
  monthly     = first trading day of each calendar month
  quarterly   = first trading day of each calendar quarter
  semiannual  = first trading day of each half-year (Jan / Jul)
  annual      = first trading day of each year (January)

QUARTERLY and ANNUAL cells are taken BY REFERENCE from the completed
lazy-quarterly test (backtests/lazy-quarterly/results_lq.json), whose
integrity gate reproduced the original published finals to the cent
(14/14 checks). Their cadence calendars were verified there to match
the SPEC's uniform definition (quarterly = first trading day of
Jan/Apr/Jul/Oct; the annual variant = the identical engine with the
calendar restricted to the first trading day of January). This script
asserts those finals and re-saves their full data (equity curve,
episodes, halts) into cells/. The source test ran NO annual-cadence
placebos, so the annual placebo set is run fresh here in the
identical plumbing (same book, same signals, same v9 wrapper, same
random-rank twin design, seeds 1..20) and labelled as such.

The five remaining cells (daily, weekly, biweekly, monthly,
semiannual) are run fresh here by loading a fresh copy of the
original gap-a5 engine module per cadence and replacing ONLY its
selection-calendar function — the exact technique the lazy-quarterly
test used for its annual variant. Signal, scoring, cost code, floor
mechanics and placebo design are the engine's own, unmodified.

Shared inputs are READ-ONLY: the long-run-2010 plumbing
(lr_common/lr_engines), the lazy-quarterly plumbing (lq_common), the
original gap-a5 module and its cached similarity signals, and the
champion's shared price cache (via the gap-a5 module's get_prices).
All outputs are written only inside this folder.
"""
import json
import os
import random
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LQ = os.path.expanduser("~/workspace/stock-app/backtests/lazy-quarterly")
sys.path.insert(0, LQ)
import lq_common as Q  # noqa: E402

C, E = Q.C, Q.E
DS, DE = "2016-11-21", "2026-11-20"
CELLS_DIR = os.path.join(HERE, "cells")
os.makedirs(CELLS_DIR, exist_ok=True)

# SPEC-verified dividend-adjusted decade SPY (the printed benchmark).
SPY_SPEC = 367.80
# Champion on this road, from the lazy-quarterly test (two halts, run
# ended 2020-03-23). Its crown rests on the 2010 and 2019 roads.
CHAMPION_DECADE = 65.89


# ---------------------------------------------------------------- cadences
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


def cad_semiannual(pb, start, end):
    return _firsts(pb, start, end,
                   lambda d: (d[:4], "H1" if d[5:7] <= "06" else "H2"))


def cad_quarterly(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def cad_annual(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] == "01" and d[:4] not in seen:
            seen.add(d[:4])
            out.append(d)
    return out


FRESH = {"daily": cad_daily, "weekly": cad_weekly,
         "biweekly": cad_biweekly, "monthly": cad_monthly,
         "semiannual": cad_semiannual}


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


def run_cell(mod, book, sims, label):
    """One v9-wrapped ranked run + 20 v9-wrapped random-rank placebo
    twins (the original Lazy placebo design, seeds 1..20)."""
    def run_one(s, e, cash, floor):
        return mod.run_pot(book, sims, s, e, cash, floor,
                           label=label, record_pools=True)
    v9 = C.run_v9(run_one, book.dates, DS, DE)
    spy_plumb = C.champ.spy_net(book, DS, DE, 100.0)[0]
    norm = E._normalize(label, DS, DE, v9, spy_plumb)
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)

        def run_pl(s, e, cash, floor, rng=rng):
            return mod.run_pot(book, sims, s, e, cash, floor,
                               placebo_rng=rng, label=f"{label} PL{seed}")
        v9p = C.run_v9(run_pl, book.dates, DS, DE)
        twins.append({"seed": seed, "final": round(v9p["final"], 2),
                      "costs": round(v9p["costs"], 2),
                      "orders": v9p["orders"],
                      "halts": len(v9p["halts"]),
                      "halt_dates": [h["signal_date"] for h in v9p["halts"]]})
    finals = sorted(t["final"] for t in twins)
    beats = sum(1 for x in finals if norm["final"] > x)
    return norm, twins, finals, beats


def cell_payload(cadence, norm, twins, finals, beats, source, note):
    restart = norm.get("restart")
    return {
        "slug": "lazy-prices", "cadence": cadence,
        "window": [DS, DE], "start_cash": 100.0,
        "final": norm["final"], "cagr_pct": norm["cagr_pct"],
        "max_dd_pct": norm["diag"]["max_drawdown_pct"],
        "max_dd_date": norm["diag"]["max_drawdown_date"],
        "worst_close": norm["diag"]["worst_close"],
        "worst_close_date": norm["diag"]["worst_close_date"],
        "costs": norm["costs"], "orders": norm["orders"],
        "halts": norm["halts"],
        "restart": restart,
        "second_halt": bool(restart and restart.get("second_halt")),
        "episodes": norm["episodes"],
        "turnover": norm.get("turnover"),
        "spy_final_plumbing": norm["spy_final"],
        "spy_final_spec_dividend_adjusted": SPY_SPEC,
        "champion_decade_final": CHAMPION_DECADE,
        "placebo": {
            "beaten": beats, "of": 20,
            "median": round(pct(finals, 0.5), 2) if finals else None,
            "best": finals[-1] if finals else None,
            "worst": finals[0] if finals else None,
            "finals_sorted": finals,
            "twins": twins, "note": note},
        "equity_curve": [[d, round(v, 4)] for d, v in norm["curve"]],
        "source": source}


def save_cell(payload):
    path = os.path.join(CELLS_DIR, f"{payload['cadence']}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=str)
    print(f"saved cells/{payload['cadence']}.json final "
          f"${payload['final']:,.2f} placebo {payload['placebo']['beaten']}/20",
          flush=True)


def main():
    lazy, pb_gap, sims = Q.gap_book()
    pond16 = list(lazy.UNIVERSE)
    book = C.FastPriceBook({t: lazy.get_prices(t)
                            for t in pond16 + ["SPY"]})
    gap5_path = os.path.join(Q.GAPA5, "lazy-prices.py")

    summary_cells = {}

    # ---------- fresh cells: daily, weekly, biweekly, monthly, semiannual
    for cadence, calfn in FRESH.items():
        mod = C.load_module(f"lazy_{cadence}", gap5_path)
        mod.UNIVERSE = pond16
        mod.quarter_selection_dates = calfn
        norm, twins, finals, beats = run_cell(
            mod, book, sims, f"lazy prices {cadence}")
        save_cell(cell_payload(
            cadence, norm, twins, finals, beats,
            source="fresh run in this folder's run_sweep.py (original "
                   "gap-a5 engine, cadence calendar replaced only)",
            note="20 random-rank twins, seeds 1..20, v9-wrapped, same "
                 "cadence calendar and scored pool as the ranked run"))
        summary_cells[cadence] = (norm, beats, None)

    # ---------- quarterly + annual: by reference from lazy-quarterly,
    # verified by fresh ranked re-runs in this identical plumbing
    with open(os.path.join(LQ, "results_lq.json")) as f:
        lq = json.load(f)
    assert lq["decade_lq"]["final"] == 514.77, lq["decade_lq"]["final"]
    assert lq["decade_annual"]["final"] == 456.01, lq["decade_annual"]["final"]
    verify = {}
    for cadence, calfn, ref in (("quarterly", cad_quarterly, 514.77),
                                ("annual", cad_annual, 456.01)):
        mod = C.load_module(f"lazy_verify_{cadence}", gap5_path)
        mod.UNIVERSE = pond16
        mod.quarter_selection_dates = calfn

        def run_one(s, e, cash, floor, mod=mod):
            return mod.run_pot(book, sims, s, e, cash, floor,
                               label=f"VERIFY {cadence}",
                               record_pools=True)
        v9v = C.run_v9(run_one, book.dates, DS, DE)
        got = round(v9v["final"], 2)
        verify[cadence] = {"reference_final": ref, "fresh_rerun_final": got,
                           "match": got == ref}
        print(f"VERIFY {cadence}: fresh re-run ${got:,.2f} vs reference "
              f"${ref:,.2f} match={got == ref}", flush=True)
        assert got == ref, f"{cadence} verification failed: {got} != {ref}"

    # quarterly placebo: the source test's own v9-wrapped decade twins
    qp = lq["decade_placebo"]
    qtwins = [{"seed": t["seed"], "final": t["final"],
               "costs": t["costs"], "orders": t["orders"],
               "halts": t["halts"]} for t in qp["twins"]]
    save_cell(cell_payload(
        "quarterly", lq["decade_lq"], qtwins, qp["finals_sorted"],
        qp["ranked_beats"],
        source="BY REFERENCE from backtests/lazy-quarterly/ "
               "results_lq.json (decade_lq + decade_placebo), saved "
               "verbatim into this cell file; integrity gate 14/14 "
               "there reproduced the original published finals",
        note="20 random-rank twins, seeds 1..20, v9-wrapped — run by "
             "the lazy-quarterly test on this identical window/plumbing"))
    summary_cells["quarterly"] = (lq["decade_lq"], qp["ranked_beats"], None)

    # annual placebo: NOT run by the source test — run fresh here in
    # identical plumbing so the cell carries its anti-luck column.
    ann = C.load_module("lazy_annual_placebo", gap5_path)
    ann.UNIVERSE = pond16
    ann.quarter_selection_dates = cad_annual
    _ann_norm, atwins, afinals, abeats = run_cell(
        ann, book, sims, "lazy prices annual (placebo only)")
    assert _ann_norm["final"] == 456.01, _ann_norm["final"]
    save_cell(cell_payload(
        "annual", lq["decade_annual"], atwins, afinals, abeats,
        source="ranked final BY REFERENCE from backtests/lazy-quarterly/ "
               "results_lq.json (decade_annual), saved verbatim into "
               "this cell file; placebo twins run fresh by this "
               "folder's run_sweep.py in identical plumbing because "
               "the source test ran no annual-cadence placebos",
        note="20 random-rank twins, seeds 1..20, v9-wrapped, annual "
             "calendar — fresh in this sweep (source test had none)"))
    summary_cells["annual"] = (lq["decade_annual"], abeats, None)

    # ---------- summary results.json (SPEC sweep format)
    order = ["daily", "weekly", "biweekly", "monthly", "quarterly",
             "semiannual", "annual"]
    cells, money = {}, []
    for cadence in order:
        norm, beats, _ = summary_cells[cadence]
        restart = norm.get("restart")
        cells[cadence] = {
            "final": norm["final"], "cagr_pct": norm["cagr_pct"],
            "max_dd_pct": norm["diag"]["max_drawdown_pct"],
            "halts": len(norm["halts"]),
            "restart": bool(restart),
            "second_halt": bool(restart and restart.get("second_halt")),
            "costs": norm["costs"], "orders": norm["orders"],
            "placebo_beaten": beats,
            "placebo_note": "20 random-rank twins (seeds 1..20), "
                            "v9-wrapped, same cadence; full twin finals "
                            "in cells/<cadence>.json"}
        if norm["final"] > SPY_SPEC and beats == 20:
            money.append(cadence)
    out = {
        "slug": "lazy-prices",
        "area": "long-horizon 10-K language-similarity (Lazy Prices) "
                "holding on the honest pond — judged in this sweep on "
                "the DECADE road at every cadence",
        "area_source": "SPEC THE CADENCE SWEEP (Terry 2026-11-21 "
                       "~22:09); strategy per Cohen-Malloy-Nguyen 2020 "
                       "and the original gap-a5 test",
        "native_cadence": "quarterly",
        "cadence": "quarterly (portfolio re-pick); the 10-K similarity "
                   "SIGNAL itself only changes on annual filings",
        "original_cadence_foreign": False,
        "original_cadence_note": "Not foreign. The original program "
                                 "test already re-picked quarterly "
                                 "(first trading day of Jan/Apr/Jul/Oct, "
                                 "top-5 by most recent similarity) — "
                                 "proven mechanically and by integrity "
                                 "in backtests/lazy-quarterly/. The "
                                 "'annual' label in the SPEC reference "
                                 "table describes the signal's rhythm, "
                                 "not the portfolio's.",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT": 504.34, "VAL": 324.12,
                                "LONG_2010": 559.69},
            "reproduced_finals": {"CONT": 504.34, "VAL": 324.12,
                                  "LONG_2010": 559.69},
            "detail": "lazy-quarterly integrity gate: 14/14 checks to "
                      "the cent incl. costs/orders (CONT $3.57/184, "
                      "VAL $1.43/89, LONG $7.42/387), LONG halt "
                      "2010-06-30 and restart selection 2010-10-01, "
                      "SPY $313.62/$187.77/$822.94. Cross-checked "
                      "against backtests/v9-muse-rules/lazy-prices/"
                      "v9-results.json (CONT/VAL identical under v9 — "
                      "floor never fired; original placebos 20/20 on "
                      "both windows)."},
        "reference_cell_verification": verify,
        "decade_spy_final": SPY_SPEC,
        "decade_spy_note": "SPEC-verified dividend-adjusted figure. "
                           "This plumbing's own SPY net on the same "
                           "book is $329.76 (saved per cell as "
                           "spy_final_plumbing); money-cadence calls "
                           "below use the stricter $367.80 hurdle.",
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
        "verdict_area": None,  # filled by RESULTS.md author after review
        "verdict_change": None}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved results.json; money_cadences:", money, flush=True)


if __name__ == "__main__":
    main()
