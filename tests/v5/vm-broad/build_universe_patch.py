#!/usr/bin/env python3
"""
BUILD THE TOP-60 UNIVERSE — PATCH PASS (v3, final). Simulation only.

Three documented corrections to the v2 ranking (universe-build.json):

  RTN — v2's live CIK search matched United Technologies' CIK (101829)
        for "Raytheon" as well, so RTN inherited UTX's share count and
        a fictitious $125.2B cap. Raytheon Company's own CIK is
        1047122; recomputed below (~$45B, far below the cut).
  RAI — Reynolds American's XBRL share facts under CIK 898173 are
        mis-scaled at the source: every concept reports ~94-100M
        shares, while RAI's own 10-Q covers report 1,426,125,631
        shares (Q2-2017 10-Q, as of 2017-07-24; the count moved <0.2%
        across 2016-2017). The cover count governs: 1,426,125,631 x
        $54.00 = ~$77.0B -> RAI belongs in the additions.
  DD  — v2's "computed" DD cap ($46.3B) used the successor series'
        split-distorted price ($53.23 vs the ~$70 DuPont actually
        traded at in Nov 2016). Replaced with the ghost estimate
        (EDGAR shares 869,342,000 x $70). Immaterial: below cut either
        way.

Sensitivity is re-run with an added check that matters: whether the
TRADABLE set (members with a live Yahoo price series — the only names
the engine can ever score) changes across ghost price ranges. Ghost
members (UTX, WBA, CELG, RAI, TWX, AGN, PCLN-by-stub) can never be
scored in the backtest whatever their exact Nov-2016 cap, so wobble
among them cannot move any backtest number; wobble that displaces a
tradable name (ACN, the marginal one) is reported explicitly.
"""
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, "data")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor",
    os.path.join(HERE, "..", "..", "v4", "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
E.DATA = MYDATA
E.SHARED = MYDATA

ORIGINAL30 = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
              "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
              "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
              "KO", "PEP", "WFC"]
# members whose Yahoo series is purged or a stub: can never be scored
NEVER_TRADABLE = {"TWX", "CELG", "AGN", "RAI", "UTX", "WBA", "PCLN",
                  "MON", "AET", "ESRX", "ANTM", "ALXN", "YHOO", "RTN"}


def cut(rows_):
    rows_.sort(key=lambda r: -r["market_cap_usd"])
    for i, r in enumerate(rows_):
        r["rank"] = i + 1
    adds = [r["ticker"] for r in rows_ if not r["in_original30"]][:30]
    return ORIGINAL30 + adds, adds


def main():
    with open(os.path.join(HERE, "universe-build.json")) as f:
        build = json.load(f)
    rows = [dict(r) for r in build["ranking"]]
    by_t = {r["ticker"]: r for r in rows}
    corrections = []

    # --- RTN: correct CIK 1047122, recompute shares, ghost price $152
    facts = E.get_companyfacts(1047122)
    srows = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
             E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
             E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    so = E.pit_value(srows, "2016-11-21")
    assert so is not None, "RTN pit shares missing"
    by_t["RTN"].update({"cik": 1047122, "shares": so[2], "shares_filed": so[0],
                        "price_estimate": 152.0, "price_range": [145.0, 160.0],
                        "price_anchor": "YE2016 close ~$156; Nov-2016 ~$150-155",
                        "market_cap_usd": so[2] * 152.0,
                        "cap_source": "ghost estimate (corrected CIK 1047122)"})
    corrections.append(f"RTN: v2 used UTX's CIK/shares ($125.2B, fictitious); "
                         f"corrected CIK 1047122, shares {so[2]:,.0f} -> ${so[2]*152/1e9:,.1f}B")
    print(corrections[-1], flush=True)

    # --- RAI: cover-count shares override
    rai_shares = 1_426_125_631
    by_t["RAI"].update({"shares": rai_shares,
                        "shares_note": "10-Q cover count (as of 2017-07-24); EDGAR XBRL "
                                       "share facts for CIK 898173 are mis-scaled at the "
                                       "source (~94M) and were NOT used",
                        "market_cap_usd": rai_shares * 54.0,
                        "cap_source": "ghost estimate (10-Q cover share count x documented Nov-2016 price)"})
    corrections.append(f"RAI: XBRL shares mis-scaled (~94M); cover count "
                         f"{rai_shares:,} -> ${rai_shares*54/1e9:,.1f}B")
    print(corrections[-1], flush=True)

    # --- DD: ghost estimate replaces successor-distorted computed cap
    dd = by_t["DD"]
    dd.update({"price_estimate": 70.0, "price_range": [64.0, 76.0],
               "price_anchor": "DuPont traded ~$70 in Nov 2016; successor series price is split-distorted",
               "market_cap_usd": dd["shares"] * 70.0,
               "cap_source": "ghost estimate (EDGAR shares x documented Nov-2016 price)"})
    corrections.append(f"DD: successor-series price $53.23 replaced by Nov-2016 ~$70 "
                         f"-> ${dd['shares']*70/1e9:,.1f}B (below cut either way)")
    print(corrections[-1], flush=True)

    universe60, additions = cut(rows)

    # --- sensitivity with tradable-set check
    sens = {}
    for mode in ("low", "high"):
        alt = []
        for r in rows:
            r2 = dict(r)
            if "price_range" in r and "shares" in r:
                p = r["price_range"][0 if mode == "low" else 1]
                r2["market_cap_usd"] = r["shares"] * p
            alt.append(r2)
        u, a = cut(alt)
        tradable_central = {t for t in universe60 if t not in NEVER_TRADABLE}
        tradable_alt = {t for t in u if t not in NEVER_TRADABLE}
        sens[mode] = {"universe60": u,
                      "swaps": {"in": sorted(set(u) - set(universe60)),
                                "out": sorted(set(universe60) - set(u))},
                      "tradable_set_changes": tradable_alt != tradable_central,
                      "tradable_swaps": {"in": sorted(tradable_alt - tradable_central),
                                         "out": sorted(tradable_central - tradable_alt)}}
        print(f"SENSITIVITY {mode}: swaps={sens[mode]['swaps']} "
              f"tradable_set_changes={sens[mode]['tradable_set_changes']} "
              f"{sens[mode]['tradable_swaps']}", flush=True)

    build["ranking"] = rows
    build["universe60"] = universe60
    build["additions"] = [r for r in rows if r["ticker"] in additions]
    build["sensitivity"] = sens
    build["corrections_v3"] = corrections
    build["method"] = ("v3 final: original 30 + next 30 by Nov-2016 market cap. "
                       "Computed caps (EDGAR pit shares x 2016-11-18 actual close) "
                       "where free data survives; documented ghost estimates where "
                       "Yahoo purged the series. See build_universe.py, "
                       "build_universe_fix.py, build_universe_patch.py, vm-broad.md.")
    with open(os.path.join(HERE, "universe-build.json"), "w") as f:
        json.dump(build, f, indent=1, default=str)
    print("\n=== TOP 70 (v3 FINAL) ===", flush=True)
    for r in rows[:70]:
        tag = "ORIG30" if r["in_original30"] else ("ADD" if r["ticker"] in additions else "")
        print(f"{r['rank']:3d} {r['ticker']:6s} ${r['market_cap_usd']/1e9:8,.1f}B {tag} "
              f"[{r['cap_source']}]", flush=True)
    print("\nUNIVERSE60:", universe60, flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
