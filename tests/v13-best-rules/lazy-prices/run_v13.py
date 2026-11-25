#!/usr/bin/env python3
"""
V13 BEST RULES — Lazy Prices runner. Simulation only.

Runs the frozen spec (BEST-RULES-SPEC.md): monthly selection, top-5,
equal weight, NO floor, program costs, $100 pots, on roads
LONG / DECADE / CONT / VAL, with 20-seed placebos per road, an
integrity gate (the v12 quarterly engine at N=5 must reproduce the
published record before any v13 number is taken), per-period
(monthly) distributions, SPY buy-hold on the same books, and — if any
road beats its champion — fresh-pot calendar-year confirmation folds
on different years under the same frozen spec.

Chunked/resumable: results.json rewritten after every road.
"""
import gc
import json
import os
import random
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/lazy-quarterly"))
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-lazy-prices"))
import lq_common as Q  # noqa: E402
import engine_v13 as V13  # noqa: E402
import engine_n as EN  # noqa: E402

C = Q.C
END = Q.END
OUT_PATH = os.path.join(HERE, "results.json")
CHAMPIONS = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47,
             "VAL": 288.05}
SPY_PUBLISHED = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62,
                 "VAL": 187.77}


def road_setup(road):
    if road == "LONG":
        pond = Q.pond2010()
        bars = {t: C.bars_adj(C.yahoo_payload(t)) for t in pond}
        bars["SPY"] = C.bars_adj(C.yahoo_payload("SPY"))
        return C.FastPriceBook(bars), Q.era_signals(), pond, \
            "2010-01-04", END
    lazy, _pb, sims = Q.gap_book()
    book = C.FastPriceBook({t: lazy.get_prices(t)
                            for t in lazy.UNIVERSE + ["SPY"]})
    starts = {"DECADE": "2016-11-21", "CONT": "2019-01-02",
              "VAL": "2023-01-03"}
    return book, sims, list(lazy.UNIVERSE), starts[road], END


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def spy_net(book, start, end):
    """SPY buy-hold net of program costs on this road's own book."""
    days = [d for d in book.dates if start <= d <= end]
    b0 = book.bar("SPY", days[0])
    if b0 is None:  # first bar on/after start
        for d in days:
            b0 = book.bar("SPY", d)
            if b0:
                break
    sh = (100.0 / 1.001) / b0["o"]
    cl = book.close_on_or_before("SPY", days[-1])
    val = sh * cl
    return round(val - (val * 0.001 + 0.01), 2)


def period_distribution(curve):
    """Monthly periods (the strategy's tempo): month-end to month-end."""
    month_end = {}
    for d, v in curve:
        month_end[d[:7]] = (d, v)
    keys = sorted(month_end)
    rets, highs_gap = [], 0
    peak, cur_gap, max_gap = -1.0, 0, 0
    daily_peak = -1.0
    last_high_i = 0
    for i, (_d, v) in enumerate(curve):
        if v >= daily_peak:
            daily_peak = v
            last_high_i = i
    # longest stretch between new highs, in days, from the daily curve
    peak = curve[0][1]
    peak_date = date.fromisoformat(curve[0][0])
    max_gap = 0
    for d, v in curve:
        if v >= peak:
            gap = (date.fromisoformat(d) - peak_date).days
            max_gap = max(max_gap, gap)
            peak, peak_date = v, date.fromisoformat(d)
    tail_gap = (date.fromisoformat(curve[-1][0]) - peak_date).days
    max_gap = max(max_gap, tail_gap)
    for a, b in zip(keys, keys[1:]):
        rets.append(month_end[b][1] / month_end[a][1] - 1.0)
    if not rets:
        return None
    srt = sorted(rets)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    return {
        "periods": len(rets),
        "pct_positive": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
        "median_pct": round(median * 100, 2),
        "best_pct": round(max(rets) * 100, 2),
        "worst_pct": round(min(rets) * 100, 2),
        "mean_pct_secondary": round(sum(rets) / len(rets) * 100, 2),
        "longest_losing_streak_months": longest,
        "longest_between_new_highs_days": max_gap,
    }


def run_v13(book, sims, uni, s, e, rng=None):
    r = V13.run_pot(book, sims, uni, s, e, placebo_rng=rng,
                    record_pools=True)
    return r


def main():
    t0 = time.time()
    out = {"family": "Lazy Prices (Cohen-Malloy-Nguyen 2020)",
           "program": "v13-best-rules",
           "spec": "monthly selection, top-5 equal weight, NO floor, "
                   "program costs, $100 pots",
           "integrity": [], "roads": {}, "confirmation": None}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            out = json.load(f)

    # ---------- integrity gate: v12 quarterly engine, N=5, published form
    if not out["integrity"]:
        checks = []
        for road, form, expect in (("VAL", "native", 324.12),
                                   ("CONT", "native", 504.34),
                                   ("DECADE", "house", 514.77),
                                   ("LONG", "house", 559.69)):
            book, sims, uni, s, e = road_setup(road)

            def run_one(ss, ee, cash, floor, _b=book, _s=sims, _u=uni):
                return EN.run_pot_n(_b, _s, _u, ss, ee, 5, cash, floor,
                                    record_pools=True)
            if form == "house":
                v9 = C.run_v9(run_one, book.dates, s, e)
                val = round(v9["final"], 2)
            else:
                val = round(run_one(s, e, 100.0, 85.0)["final"], 2)
            checks.append({"check": f"{road} {form} N=5 quarterly == {expect}",
                           "pass": val == expect, "value": val})
            print(f"INTEGRITY {'PASS' if val == expect else 'FAIL'}: "
                  f"{road} -> {val} ({time.time()-t0:.0f}s)", flush=True)
            del book
            gc.collect()
        out["integrity"] = checks
        with open(OUT_PATH, "w") as f:
            json.dump(out, f, indent=1)
        if not all(c["pass"] for c in checks):
            print("INTEGRITY FAILED — no v13 numbers produced", flush=True)
            sys.exit(1)

    # ---------- the one frozen run
    beat_champion = []
    for road in ("LONG", "DECADE", "CONT", "VAL"):
        if road in out["roads"]:
            if out["roads"][road]["final"] > CHAMPIONS[road]:
                beat_champion.append(road)
            continue
        book, sims, uni, s, e = road_setup(road)
        r = run_v13(book, sims, uni, s, e)
        twins = []
        for seed in range(1, 21):
            tr = run_v13(book, sims, uni, s, e, rng=random.Random(seed))
            twins.append(round(tr["final"], 2))
        beats = sum(1 for x in twins if r["final"] > x)
        cell = {
            "window": [s, e],
            "final": round(r["final"], 2),
            "costs": round(r["costs"], 2),
            "orders": len(r["trades"]),
            "halts": 0,
            "max_dd_pct": max_dd(r["curve"]),
            "placebo_beats": beats,
            "placebo_median": round(V13.lazy._pct(sorted(twins), 0.5), 2),
            "placebo_best": max(twins),
            "placebo_worst": min(twins),
            "placebo_finals": sorted(twins),
            "spy_same_book": spy_net(book, s, e),
            "spy_published": SPY_PUBLISHED[road],
            "champion": CHAMPIONS[road],
            "distribution": period_distribution(r["curve"]),
            "curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "pools": r["pools"],
        }
        out["roads"][road] = cell
        with open(OUT_PATH, "w") as f:
            json.dump(out, f, indent=1)
        print(f"{road}: ${cell['final']:,.2f} dd {cell['max_dd_pct']}% "
              f"costs ${cell['costs']} orders {cell['orders']} "
              f"placebo {beats}/20 spy(book) ${cell['spy_same_book']} "
              f"({time.time()-t0:.0f}s)", flush=True)
        if cell["final"] > CHAMPIONS[road]:
            beat_champion.append(road)
        del book
        gc.collect()

    # ---------- confirmation on different years, only if a champion fell
    if beat_champion and not out.get("confirmation"):
        print(f"CONFIRMATION triggered for: {beat_champion}", flush=True)
        book, sims, uni, s, e = road_setup("CONT")  # Nov-2016 pond book
        folds = []
        for yr in range(2017, 2027):
            fs = f"{yr}-01-01"
            fe = f"{yr}-12-31" if yr < 2026 else END
            if yr == 2017:
                fs = "2017-01-03"
            r = run_v13(book, sims, uni, fs, fe)
            twins = []
            for seed in range(1, 21):
                tr = run_v13(book, sims, uni, fs, fe,
                             rng=random.Random(seed))
                twins.append(round(tr["final"], 2))
            beats = sum(1 for x in twins if r["final"] > x)
            folds.append({"year": yr, "window": [fs, fe],
                          "final": round(r["final"], 2),
                          "max_dd_pct": max_dd(r["curve"]),
                          "placebo_beats": beats,
                          "placebo_median": round(
                              V13.lazy._pct(sorted(twins), 0.5), 2),
                          "spy_same_book": spy_net(book, fs, fe)})
            print(f"FOLD {yr}: ${folds[-1]['final']:,.2f} "
                  f"placebo {beats}/20 spy ${folds[-1]['spy_same_book']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        comp = 100.0
        for f_ in folds:
            comp *= f_["final"] / 100.0
        out["confirmation"] = {
            "trigger_roads": beat_champion,
            "method": "fresh $100 pots per calendar year, Nov-2016 pond, "
                      "same frozen v13 spec; years differ from the VAL "
                      "window's start-anchored run",
            "folds": folds,
            "fold_compounded": round(comp, 2),
            "years_beating_spy": sum(
                1 for f_ in folds if f_["final"] > f_["spy_same_book"]),
            "years_placebo_majority": sum(
                1 for f_ in folds if f_["placebo_beats"] >= 11),
        }
        with open(OUT_PATH, "w") as f:
            json.dump(out, f, indent=1)
        del book
        gc.collect()
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
