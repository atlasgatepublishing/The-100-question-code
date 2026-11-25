#!/usr/bin/env python3
"""
DECADE CROSS-CHECK — the lazy-quarterly construction, reproduced.

The program's existing champion DECADE number ($65.89, two halts,
backtests/lazy-quarterly) was built on a FastPriceBook fed by the
Lazy Prices module's get_prices, which reads the v4 shared price
cache (backtests/v4/data/px_*.json) first. Those payloads start
2017-06-01 — there are no bars before that date in that book — so
that run could not actually start on 2016-11-21: it sat in cash
until the data began, first scored a selection in mid-2018, and its
SPY figure ($329.76) is SPY from 2017-06-01, not from 2016-11-21
(the full-data figure is $367.80).

This script re-runs that EXACT construction (same book source, same
fixed Nov-2016 pond, same fact chains as the main run) under both
protection regimes, read-only, to prove the artifact: if the plain
run lands on $65.89 with the published halts, the difference between
$65.89 and the main DECADE cell ($667.35) is fully explained by the
truncated price cache — a data artifact, documented, never patched.

Writes crosscheck_decade.json and merges the result into
runs_raw.json (crosschecks + the DECADE integrity entry).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_ladder_ablation as R  # noqa: E402  (defs only; main guarded)

C = R.C
champ = R.champ


def main():
    lazy = C.load_module("lazy_xchk2", os.path.join(
        C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
    universe = list(lazy.UNIVERSE)
    need = universe + ["SPY"]
    # read-only guard: every payload must already exist in the shared
    # cache, so get_prices can only read, never fetch/write.
    def _cached(t):
        for base in (lazy.SHARED, lazy.HONEST_DATA):
            p = os.path.join(base, f"px_{t}.json")
            if os.path.exists(p) and os.path.getsize(p) > 100:
                return True
        return False
    missing = [t for t in need if not _cached(t)]
    if missing:
        raise SystemExit(f"shared cache missing {missing} — aborting "
                         "rather than fetching into shared folders")
    bars = {t: lazy.get_prices(t) for t in need}
    first_bar = min(b["d"] for bl in bars.values() for b in bl)
    book = lazy.PriceBook(bars)
    ciks = champ.get_ciks()
    eq, so = {}, {}
    for t in universe:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = champ.get_companyfacts(cik)
        eq[t], so[t] = C.equity_chain(facts), C.shares_chain(facts)
        del facts
    plain = R.run_plain(book, eq, so, universe, "2016-11-21", R.END)
    lad = R.run_ladder(book, eq, so, universe, "2016-11-21", R.END)
    out = {
        "construction": "lazy-quarterly decade_champion construction: "
                        "Lazy Prices module PriceBook on v4 shared px "
                        "cache, fixed Nov-2016 pond, champ fact chains",
        "book_first_bar": first_bar,
        "plain": {"final": plain["final"], "halts": plain["halts"],
                  "restart": plain["restart"], "costs": plain["costs"],
                  "orders": plain["orders"],
                  "spy_final": plain["spy_final"]},
        "ladder": {"final": lad["final"], "halts": lad["halts"],
                   "costs": lad["costs"], "orders": lad["orders"],
                   "ladder_rungs_engaged": lad["ladder_rungs_engaged"]},
        "published_decade_champion_plain": 65.89,
        "published_halts": [
            {"signal_date": "2018-12-21", "signal_close": 84.48,
             "floor_in_effect": 85.0, "proceeds": 83.06},
            {"signal_date": "2020-03-20", "signal_close": 67.14,
             "floor_in_effect": 70.60, "proceeds": 65.89}],
        "plain_reproduces_published": abs(plain["final"] - 65.89) <= 0.011,
    }
    with open(os.path.join(HERE, "crosscheck_decade.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1), flush=True)
    # merge into runs_raw.json
    rp = os.path.join(HERE, "runs_raw.json")
    with open(rp) as f:
        raw = json.load(f)
    raw["crosschecks"]["decade_on_lazy_price_cache"] = {
        "plain_final": plain["final"], "plain_halts": plain["halts"],
        "plain_costs": plain["costs"], "plain_orders": plain["orders"],
        "ladder_final": lad["final"], "ladder_halts": lad["halts"],
        "ladder_rungs_engaged": lad["ladder_rungs_engaged"],
        "spy_final_lazy_book": plain["spy_final"],
        "book_first_bar": first_bar,
        "note": "v4 shared px cache starts 2017-06-01; the published "
                "$65.89 decade champion is this truncated-book run, "
                "reproduced in crosscheck_decade.json"}
    ent = raw["integrity"]["DECADE plain final on lazy-quarterly "
                            "construction"]
    ent["reproduced"] = plain["final"]
    ent["match"] = abs(plain["final"] - 65.89) <= 0.011
    ent["note"] = ("reproduced via crosscheck_decade.py on the "
                   "truncated v4-cache book (first bar 2017-06-01); "
                   "the main DECADE cell uses full 2008-> price data "
                   "and the task's SPY reference ($367.80)")
    with open(rp, "w") as f:
        json.dump(raw, f, indent=1)
    print("merged into runs_raw.json", flush=True)


if __name__ == "__main__":
    main()
