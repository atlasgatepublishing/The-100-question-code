#!/usr/bin/env python3
"""
CONFIRMATION — combo-three-way count 3 (Terry's rule: a non-native
count that wins across roads is re-run on DIFFERENT YEARS before
its verdict counts).

Grid result being confirmed (house form): N=3 beat N=5 on all three
roads — DECADE $651 vs $567, CONT $626 vs $537, VAL $393 vs $308.

Confirmation runs (house form, the family's own cached book):
fresh-$100 calendar-year folds 2017..2026, N=3 vs N=5 head-to-head,
plus DECADE half-windows H1 2016-11-21->2021-12-31 and
H2 2022-01-01->2026-11-20. (Folds starting before the book's first
bar, 2017-06-01, hold cash until bars begin — the plumbing's
documented effective-road artifact, identical for both counts.)
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_3way as R  # noqa: E402  (builds FastBook + Scorer helpers)
import engine_3way as E  # noqa: E402

END = "2026-11-20"


def _safe_dump(obj, path):
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            time.sleep(10)
    raise last


def build():
    champ = E.champ
    ciks = champ.get_ciks()
    facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
    for t in E.UNIVERSE:
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
    bars = {t: champ.get_prices(t) for t in E.UNIVERSE + ["SPY"]}
    pb = R.FastBook(bars)
    with open(os.path.expanduser(
            "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/"
            "data/similarities.json")) as f:
        signals = json.load(f)["signals"]
    return pb, E.Scorer(pb, equity_rows, shares_rows, facts_by_ticker,
                        signals)


def main():
    t0 = time.time()
    pb, scorer = build()
    out = {"candidate_count": 3, "native_count": 5, "folds": {},
           "halves": {}}
    wins = 0
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = END if yr == 2026 else f"{yr}-12-31"
        r3 = E.run_combo_v9(pb, scorer, s, e, 100.0, hold_n=3)
        r5 = E.run_combo_v9(pb, scorer, s, e, 100.0, hold_n=5)
        w = r3["final"] > r5["final"]
        wins += 1 if w else 0
        out["folds"][str(yr)] = {"candidate_final": round(r3["final"], 2),
                                 "native5_final": round(r5["final"], 2),
                                 "candidate_wins": w}
        print(f"FOLD {yr}: N=3 ${r3['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w} ({time.time()-t0:.0f}s)",
              flush=True)
    hwins = 0
    for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                       "H2_2022-2026": ("2022-01-01", END)}.items():
        r3 = E.run_combo_v9(pb, scorer, s, e, 100.0, hold_n=3)
        r5 = E.run_combo_v9(pb, scorer, s, e, 100.0, hold_n=5)
        w = r3["final"] > r5["final"]
        hwins += 1 if w else 0
        out["halves"][hn] = {"candidate_final": round(r3["final"], 2),
                             "native5_final": round(r5["final"], 2),
                             "candidate_wins": w}
        print(f"HALF {hn}: N=3 ${r3['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w}", flush=True)
    out["fold_wins"] = f"{wins}/10"
    out["half_wins"] = f"{hwins}/2"
    out["confirmed"] = wins >= 6 and hwins >= 1
    _safe_dump(out, os.path.join(HERE, "confirm_3way.json"))
    print(f"CONFIRMATION DONE folds {wins}/10 halves {hwins}/2 "
          f"confirmed={out['confirmed']} ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
