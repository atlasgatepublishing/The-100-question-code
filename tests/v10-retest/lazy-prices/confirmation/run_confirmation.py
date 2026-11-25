#!/usr/bin/env python3
"""
LAZY PRICES — MONTHLY-CADENCE CONFIRMATION RUN (THE GREAT RETEST v10).

Terry's confirmation rule (SPEC.md, 2026-11-21 ~22:19): a new money
cadence crowned in the sweep is NOT crowned until it is re-run on the
other roads. The completed cadence sweep (../) found MONTHLY a money
cadence on the DECADE road ($503.19, placebo 20/20), matching the
native quarterly ($514.77, 18/20). This script re-runs Lazy Prices at
MONTHLY cadence, identical plumbing to the sweep (original gap-a5
engine, ONLY its selection-calendar function replaced; $100 start,
program costs 0.10%/side + $0.01 per sell order, point-in-time,
adopted v9 protections), on:

  LONG  2010-01-04 -> 2026-11-20   (2010 pond + era 10-K signals,
                                    the long-run construction)
  CONT  2019-01-02 -> 2026-11-20   (Nov-2016 pond + gap-a5 signals)
  VAL   2023-01-03 -> 2026-11-20   (Nov-2016 pond + gap-a5 signals)

plus 20-seed random-rank placebo twins (seeds 1..20, the sweep's twin
design) at monthly cadence on each road, and fresh yearly folds at
monthly cadence: every calendar year 2010-2026 standalone with a
fresh $100 start (2010-2016 folds on the 2010 pond / era signals;
2017-2026 folds on the Nov-2016 pond / gap-a5 signals — each fold on
the chassis that natively covers its years).

INTEGRITY CHECKS run first, in-process, and abort the run if either
fails:
  (a) monthly DECADE on the gap book must reproduce the sweep's
      $503.19 exactly (proves this plumbing == the sweep's);
  (b) quarterly LONG on the narrow 2010 book must reproduce the
      published $559.69 exactly (proves the narrow book == the
      long-run book). The narrow book is built per-ticker from the
      read-only long-run price cache (C.yahoo_payload + C.bars_adj,
      exactly lr_engines._book's construction) — the bulk pool
      loader (load_pool / the 1.7GB facts cache) is NEVER called.

Shared inputs are READ-ONLY. All outputs are written only inside
this confirmation/ folder.
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
END = "2026-11-20"
GAP5_PATH = os.path.join(Q.GAPA5, "lazy-prices.py")

# Saved-record references (SPEC / lazy-quarterly results_lq.json /
# sweep results.json) — printed beside the fresh monthly numbers.
REF = {
    "long": {"start": "2010-01-04", "spy": 822.94, "quarterly": 559.69},
    "cont": {"start": "2019-01-02", "spy": 313.62, "quarterly": 504.34},
    "val": {"start": "2023-01-03", "spy": 187.77, "quarterly": 324.12},
}


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


def fresh_module(name, universe, calfn):
    mod = C.load_module(name, GAP5_PATH)
    mod.UNIVERSE = list(universe)
    mod.quarter_selection_dates = calfn
    return mod


def run_ranked(mod, book, sims, s, e, label):
    def run_one(s_, e_, cash, floor):
        return mod.run_pot(book, sims, s_, e_, cash, floor,
                           label=label, record_pools=True)
    v9 = C.run_v9(run_one, book.dates, s, e)
    spy = C.champ.spy_net(book, s, e, 100.0)[0]
    return E._normalize(label, s, e, v9, spy)


def run_twins(mod, book, sims, s, e, label, ranked_final):
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)

        def run_pl(s_, e_, cash, floor, rng=rng, seed=seed):
            return mod.run_pot(book, sims, s_, e_, cash, floor,
                               placebo_rng=rng,
                               label=f"{label} PL{seed}")
        v9p = C.run_v9(run_pl, book.dates, s, e)
        twins.append({"seed": seed, "final": round(v9p["final"], 2),
                      "costs": round(v9p["costs"], 2),
                      "orders": v9p["orders"],
                      "halts": len(v9p["halts"]),
                      "halt_dates": [h["signal_date"]
                                     for h in v9p["halts"]]})
    finals = sorted(t["final"] for t in twins)
    beats = sum(1 for x in finals if ranked_final > x)
    return twins, finals, beats


def slim_episodes(norm):
    eps = []
    for ep in norm["episodes"]:
        eps.append({k: v for k, v in ep.items() if k != "pools"})
    return eps


def road_payload(road, norm, twins, finals, beats):
    restart = norm.get("restart")
    ref = REF[road]
    return {
        "slug": "lazy-prices", "cadence": "monthly",
        "confirmation_of": "v10 cadence sweep DECADE monthly cell "
                           "($503.19, placebo 20/20)",
        "road": road.upper(), "window": [norm["start"], norm["end"]],
        "start_cash": 100.0,
        "final": norm["final"], "cagr_pct": norm["cagr_pct"],
        "max_dd_pct": norm["diag"]["max_drawdown_pct"],
        "max_dd_date": norm["diag"]["max_drawdown_date"],
        "worst_close": norm["diag"]["worst_close"],
        "worst_close_date": norm["diag"]["worst_close_date"],
        "costs": norm["costs"], "orders": norm["orders"],
        "halts": norm["halts"],
        "restart": restart,
        "second_halt": bool(restart and restart.get("second_halt")),
        "episodes": slim_episodes(norm),
        "spy_final_plumbing": norm["spy_final"],
        "spy_final_reference": ref["spy"],
        "quarterly_reference": {
            "final": ref["quarterly"],
            "source": "saved record (SPEC reference results / "
                      "backtests/lazy-quarterly/results_lq.json), "
                      "integrity-reproduced; not re-run here"},
        "placebo": {
            "beaten": beats, "of": 20,
            "median": round(pct(finals, 0.5), 2) if finals else None,
            "best": finals[-1] if finals else None,
            "worst": finals[0] if finals else None,
            "finals_sorted": finals,
            "twins": twins,
            "note": "20 random-rank twins, seeds 1..20, v9-wrapped, "
                    "same monthly calendar and scored pool as the "
                    "ranked run (the sweep's twin design)"},
        "equity_curve": [[d, round(v, 4)] for d, v in norm["curve"]],
        "source": "fresh run in this folder's run_confirmation.py "
                  "(original gap-a5 engine, monthly calendar only)"}


def save_json(name, payload):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=str)
    print(f"saved {name}", flush=True)


def main():
    # ---------------- books (narrow loads only)
    lazy, _pb, gap_sims = Q.gap_book()
    pond16 = list(lazy.UNIVERSE)
    gap_book = C.FastPriceBook({t: lazy.get_prices(t)
                                for t in pond16 + ["SPY"]})
    print(f"gap book ready: {len(pond16)} names, "
          f"{len(gap_book.dates)} dates", flush=True)

    pond10 = Q.pond2010()
    era_sims = Q.era_signals()
    bars10 = {t: C.bars_adj(C.yahoo_payload(t)) for t in pond10}
    bars10["SPY"] = C.bars_adj(C.yahoo_payload("SPY"))
    book10 = C.FastPriceBook(bars10)
    print(f"2010 book ready (narrow per-ticker load): {len(pond10)} "
          f"names, {len(book10.dates)} dates", flush=True)

    # ---------------- integrity checks
    mod_dec = fresh_module("lazy_conf_decade", pond16, cad_monthly)
    dec = run_ranked(mod_dec, gap_book, gap_sims,
                     "2016-11-21", END, "CONF DECADE monthly")
    assert dec["final"] == 503.19, \
        f"integrity (a) FAILED: monthly DECADE ${dec['final']} != $503.19"
    print("integrity (a) PASS: monthly DECADE reproduces $503.19",
          flush=True)

    mod_lq = fresh_module("lazy_conf_long_q", pond10, cad_quarterly)
    lq = run_ranked(mod_lq, book10, era_sims,
                    "2010-01-04", END, "CONF LONG quarterly check")
    assert lq["final"] == 559.69, \
        f"integrity (b) FAILED: quarterly LONG ${lq['final']} != $559.69"
    assert lq["spy_final"] == 822.94, lq["spy_final"]
    print("integrity (b) PASS: quarterly LONG on the narrow book "
          "reproduces $559.69 (SPY $822.94)", flush=True)

    # ---------------- confirmation roads at MONTHLY
    roads = [
        ("long", book10, era_sims, pond10, "CONF LONG monthly"),
        ("cont", gap_book, gap_sims, pond16, "CONF CONT monthly"),
        ("val", gap_book, gap_sims, pond16, "CONF VAL monthly"),
    ]
    summary = {}
    for road, book, sims, pond, label in roads:
        s, e = REF[road]["start"], END
        mod = fresh_module(f"lazy_conf_{road}", pond, cad_monthly)
        norm = run_ranked(mod, book, sims, s, e, label)
        twins, finals, beats = run_twins(mod, book, sims, s, e,
                                         label, norm["final"])
        save_json(f"{road}-monthly.json",
                  road_payload(road, norm, twins, finals, beats))
        summary[road] = {"final": norm["final"], "beats": beats,
                         "spy": norm["spy_final"]}
        print(f"{road.upper()} monthly: ${norm['final']:,.2f} "
              f"(SPY ${norm['spy_final']:,.2f}, quarterly "
              f"${REF[road]['quarterly']:,.2f}) placebo {beats}/20",
              flush=True)

    # ---------------- fresh yearly folds at MONTHLY
    folds = []
    fold_specs = ([(y, book10, era_sims, pond10, "2010 pond / era "
                    "signals") for y in range(2010, 2017)] +
                  [(y, gap_book, gap_sims, pond16, "Nov-2016 pond / "
                    "gap-a5 signals") for y in range(2017, 2027)])
    for year, book, sims, pond, chassis in fold_specs:
        days = [d for d in book.dates if d[:4] == str(year)]
        s, e = days[0], days[-1]
        mod = fresh_module(f"lazy_fold_{year}", pond, cad_monthly)
        norm = run_ranked(mod, book, sims, s, e, f"FOLD {year}")
        restart = norm.get("restart")
        folds.append({
            "year": year, "window": [s, e], "chassis": chassis,
            "start_cash": 100.0, "final": norm["final"],
            "cagr_pct": norm["cagr_pct"],
            "max_dd_pct": norm["diag"]["max_drawdown_pct"],
            "max_dd_date": norm["diag"]["max_drawdown_date"],
            "costs": norm["costs"], "orders": norm["orders"],
            "halts": norm["halts"], "restart": restart,
            "second_halt": bool(restart and restart.get("second_halt")),
            "episodes": slim_episodes(norm),
            "spy_final": norm["spy_final"],
            "beat_spy": norm["final"] > norm["spy_final"],
            "beat_100": norm["final"] > 100.0,
            "equity_curve": [[d, round(v, 4)]
                             for d, v in norm["curve"]]})
        f_ = folds[-1]
        print(f"FOLD {year}: ${f_['final']:,.2f} vs SPY "
              f"${f_['spy_final']:,.2f} beat_spy={f_['beat_spy']} "
              f"beat_100={f_['beat_100']}", flush=True)
    save_json("folds.json", {
        "slug": "lazy-prices", "cadence": "monthly",
        "design": "each calendar year standalone, fresh $100 start, "
                  "monthly cadence, program costs, v9 protections; "
                  "2010-2016 on the 2010 pond / era signals, "
                  "2017-2026 on the Nov-2016 pond / gap-a5 signals; "
                  "2026 fold ends 2026-11-20 (end of data)",
        "folds": folds,
        "record_vs_spy": [sum(1 for f in folds if f["beat_spy"]),
                          len(folds)],
        "record_vs_100": [sum(1 for f in folds if f["beat_100"]),
                          len(folds)],
        "record_vs_spy_2017_2026": [
            sum(1 for f in folds if f["year"] >= 2017 and f["beat_spy"]),
            sum(1 for f in folds if f["year"] >= 2017)],
        "record_vs_100_2017_2026": [
            sum(1 for f in folds if f["year"] >= 2017 and f["beat_100"]),
            sum(1 for f in folds if f["year"] >= 2017)]})

    print("ROADS:", json.dumps(summary), flush=True)
    print("confirmation run complete", flush=True)


if __name__ == "__main__":
    main()
