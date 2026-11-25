#!/usr/bin/env python3
"""
BUILD THE TOP-60 UNIVERSE — CORRECTION PASS (v2). Simulation only.

build_universe.py (v1) ranked the candidate pool by computed
point-in-time Nov-2016 market caps, but post-run audit found five
classes of plumbing error in the RANKING step (none in the engine):

  1. Tickers re-mapped or dropped by today's company_tickers.json:
     BLK now points at a 2024-vintage registrant (no 2016 facts);
     BK, K, WBA, PX, MMC are absent entirely (WBA was taken private
     in 2025; PX merged away in 2018). -> use the 2016 entity's CIK.
  2. AVGO in today's file is Broadcom Inc (2018 US redomicile); the
     Nov-2016 company was Broadcom Ltd, CIK 1649338. -> use Ltd.
  3. CI / APC in 2016 were Cigna Corp (701221) / Anadarko (773910).
  4. PCLN's own Yahoo series has been purged to a 277-bar stub, but
     the same company's renamed series (BKNG) is intact back to 2016
     -> PCLN's ranking price comes from BKNG (documented; in the
     backtest itself PCLN keeps its own stub series, baseline rules).
  5. Yahoo has purged the price series of every name delisted before
     ~2020 (TWX, CELG, AGN, RAI, UTX, WBA, MON, AET, ESRX, ANTM,
     ALXN, YHOO). Their EDGAR share counts are exact; their Nov-2016
     prices are taken from documented anchors (year-end 2016 closes
     per 1stock1 / companiesmarketcap year-end caps / dated cap
     observations from marketcaphistory), each with a stated range.
     These names are "ghosts": several belong in the top-60 BY RANK
     and are included — in the backtest they can never be scored
     (no price series), exactly like V and BRK-B in the baseline 30.
     A sensitivity pass re-cuts the list at each ghost's range ends
     to prove which memberships are estimate-sensitive.

Everything else is the v1 method, unchanged: shares = EDGAR
point-in-time (filed < 2016-11-21, 548-day freshness gate, engine's
own pit machinery), price = actual close on 2016-11-18 with splits
un-adjusted. Output: universe-build.json (v2), superseding v1.
"""
import importlib.util
import json
import os
import re
import time
import urllib.parse
import urllib.request

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

with open(os.path.join(HERE, "universe-build.json")) as f:
    V1 = json.load(f)
V1_ROWS = {r["ticker"]: r for r in V1["ranking"]}

# --- corrected 2016-entity CIKs (see docstring) -------------------------
CIK_2016 = {
    "TWX": 1105705, "MON": 1110783, "AET": 1122304, "RAI": 898173,
    "YHOO": 1043000, "CELG": 816284, "ESRX": 1532063, "AGN": 1578845,
    "ANTM": 1156039, "PCLN": 1075531, "FOXA": 1308161, "DOW": 29915,
    "DD": 30554, "ALXN": 939767,
    "WBA": 1618921,   # Walgreens Boots Alliance (taken private 2025)
    "BK": 1390777,    # Bank of New York Mellon
    "K": 55067,       # Kellogg
    "PX": 34479,      # Praxair (merged into Linde, 2018)
    "MMC": 62709,     # Marsh & McLennan
    "CI": 701221,     # Cigna Corp (2016 entity)
    "APC": 773910,    # Anadarko Petroleum
    "AVGO": 1649338,  # Broadcom Ltd (2016 entity; today's file = Broadcom Inc)
    "BLK": 1364742,   # BlackRock (today's file maps a 2024-vintage registrant)
}
# UTX / RTN resolved live from EDGAR's company search (best effort);
# fallbacks are their Q3-2016 10-Q cover share counts, flagged as such.
FALLBACK_SHARES = {"UTX": (836_900_000, "Q3-2016 10-Q cover figure"),
                   "RTN": (301_000_000, "Q3-2016 10-Q cover figure")}

# --- ghost prices: Nov-18-2016 close estimates with ranges --------------
# Anchors: 1stock1 yearly tables (2016 ending closes: TWX $96.53,
# RAI $56.04); companiesmarketcap year-end 2016 cap for AGN ($78.74B at
# the $209.84 year-end close); marketcaphistory dated CELG caps
# ($76.68B on 2016-10-21, $89.96B on 2017-02-03); UTX/WBA year-end
# closes $109.63 / $82.85 with flat Nov->Dec paths. Below-cut ghosts
# need only order-of-magnitude prices (stated, never tuned).
GHOST_PRICES = {   # ticker: (price, low, high, anchor note)
    "UTX": (110.0, 107.0, 112.0, "YE2016 close $109.63; flat Nov-Dec 2016"),
    "WBA": (83.5, 81.0, 86.0, "YE2016 close $82.85"),
    "CELG": (104.0, 100.0, 108.0, "marketcaphistory caps 2016-10-21 $76.68B / 2017-02-03 $89.96B bracket Nov"),
    "AGN": (194.5, 190.0, 199.0, "YE2016 cap $78.74B (companiesmarketcap) at YE close $209.84; Nov close below YE after Nov-2 earnings drop"),
    "RAI": (54.0, 52.5, 55.5, "YE2016 close $56.04 (1stock1); steady Nov climb"),
    "TWX": (94.0, 91.0, 97.0, "YE2016 close $96.53 (1stock1); merger-arb discount to the $107.50 AT&T offer all through Nov 2016"),
    "MON": (112.0, 105.0, 120.0, "Bayer $128 cash offer pending; traded ~$111-113"),
    "AET": (134.0, 125.0, 145.0, "below-cut estimate"),
    "ESRX": (72.0, 65.0, 80.0, "below-cut estimate"),
    "ANTM": (144.0, 135.0, 155.0, "below-cut estimate"),
    "YHOO": (41.5, 38.0, 45.0, "below-cut estimate"),
    "ALXN": (124.0, 110.0, 140.0, "below-cut estimate"),
    "APC": (68.0, 60.0, 75.0, "below-cut estimate; Yahoo series also purged"),
    "DOW": (57.0, 52.0, 62.0, "below-cut estimate (Dow Chemical; today's DOW series starts 2019)"),
    "DD": (70.0, 64.0, 76.0, "below-cut estimate (E I du Pont; today's DD series is the successor's)"),
    "FOXA": (27.9, 26.0, 30.0, "Class A close; per-class dei understates the whole-company cap (~$50B all classes) — below cut either way"),
}
ASOF = "2016-11-21"


def resolve_cik_by_name(name):
    """Best-effort CIK lookup via EDGAR's legacy company search (atom)."""
    q = urllib.parse.quote(name)
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
           f"&company={q}&type=10-K&dateb=&owner=include&count=10&output=atom")
    req = urllib.request.Request(url, headers={"User-Agent": E.UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        txt = r.read().decode("utf8", "ignore")
    ciks = sorted(set(int(c) for c in re.findall(r"CIK=(\d+)", txt)))
    return ciks


def pit_shares(ticker, cik):
    facts = E.get_companyfacts(cik)
    rows = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    so = E.pit_value(rows, ASOF)
    return so


def build_row(ticker, cap, source, extra=None):
    r = {"ticker": ticker, "market_cap_usd": cap, "cap_source": source,
         "in_original30": ticker in ORIGINAL30}
    if extra:
        r.update(extra)
    return r


def main():
    rows = []
    # 1) carry over every v1 computed row untouched — except DD, whose v1
    # row used the successor registrant's data; it is recomputed in step 2.
    for t, r in V1_ROWS.items():
        if t == "DD":
            continue
        rows.append(build_row(t, r["market_cap_usd"], "computed (v1)",
                              {"shares": r["shares"], "shares_filed": r["shares_filed"],
                               "price_2016_11_18_actual": r["price_2016_11_18_actual"]}))
    have = {r["ticker"] for r in rows}
    failures = []

    # 2) CIK-corrected names: exact shares; price from Yahoo if it lives
    from build_universe import yahoo_raw_close_and_splits  # reuse v1 helper
    for t, cik in CIK_2016.items():
        if t in have:
            continue
        try:
            so = pit_shares(t, cik)
        except Exception as e:  # noqa
            failures.append((t, f"facts fetch failed for CIK {cik}: {e}"))
            print(f"{t}: FAIL facts {e}", flush=True)
            continue
        if so is None:
            failures.append((t, f"no pit shares under 2016 CIK {cik}"))
            print(f"{t}: FAIL no pit shares (CIK {cik})", flush=True)
            continue
        px_ticker = "BKNG" if t == "PCLN" else t
        try:
            px, px_date, why = yahoo_raw_close_and_splits(px_ticker)
        except Exception as e:  # noqa
            px, why = None, f"Yahoo fetch failed: {e}"
        if px is not None:
            src = "computed (BKNG series for PCLN)" if t == "PCLN" else "computed (CIK-corrected)"
            rows.append(build_row(t, so[2] * px, src,
                                  {"cik": cik, "shares": so[2], "shares_filed": so[0],
                                   "price_2016_11_18_actual": round(px, 4)}))
            print(f"{t}: shares={so[2]:,.0f} px=${px:,.2f} cap=${so[2]*px/1e9:,.1f}B [{src}]",
                  flush=True)
            have.add(t)
        elif t in GHOST_PRICES:
            p, lo, hi, note = GHOST_PRICES[t]
            rows.append(build_row(t, so[2] * p, "ghost estimate (EDGAR shares x documented Nov-2016 price)",
                                  {"cik": cik, "shares": so[2], "shares_filed": so[0],
                                   "price_estimate": p, "price_range": [lo, hi],
                                   "price_anchor": note}))
            print(f"{t}: GHOST shares={so[2]:,.0f} px~${p} cap~${so[2]*p/1e9:,.1f}B",
                  flush=True)
            have.add(t)
        else:
            failures.append((t, f"no Yahoo price and no ghost anchor ({why})"))
            print(f"{t}: FAIL price {why}", flush=True)
        time.sleep(0.12)

    # 3) UTX / RTN: resolve CIK live; else fallback cover shares (ghosts)
    for t, name in (("UTX", "United Technologies"), ("RTN", "Raytheon")):
        if t in have:
            continue
        cik, so = None, None
        try:
            cands = resolve_cik_by_name(name)
            for c in cands:
                try:
                    s = pit_shares(t, c)
                except Exception:  # noqa
                    s = None
                if s is not None:
                    cik, so = c, s
                    break
        except Exception as e:  # noqa
            print(f"{t}: CIK search failed ({e}); using fallback shares", flush=True)
        p, lo, hi, note = GHOST_PRICES[t] if t in GHOST_PRICES else (None,) * 4
        if t == "RTN":
            p, lo, hi, note = 152.0, 145.0, 160.0, "below-cut estimate (YE2016 close ~$156)"
        if so is not None:
            rows.append(build_row(t, so[2] * p, "ghost estimate (EDGAR shares x documented Nov-2016 price)",
                                  {"cik": cik, "shares": so[2], "shares_filed": so[0],
                                   "price_estimate": p, "price_range": [lo, hi],
                                   "price_anchor": note}))
            print(f"{t}: GHOST cik={cik} shares={so[2]:,.0f} cap~${so[2]*p/1e9:,.1f}B", flush=True)
        else:
            sh, shnote = FALLBACK_SHARES[t]
            rows.append(build_row(t, sh * p, "ghost estimate (fallback share count)",
                                  {"shares": sh, "shares_note": shnote,
                                   "price_estimate": p, "price_range": [lo, hi],
                                   "price_anchor": note}))
            print(f"{t}: GHOST fallback shares={sh:,.0f} cap~${sh*p/1e9:,.1f}B", flush=True)
        have.add(t)

    # 4) rank and cut
    def cut(rows_):
        rows_.sort(key=lambda r: -r["market_cap_usd"])
        for i, r in enumerate(rows_):
            r["rank"] = i + 1
        adds = [r["ticker"] for r in rows_ if not r["in_original30"]][:30]
        return ORIGINAL30 + adds, adds
    universe60, additions = cut(rows)

    # 5) sensitivity: ghosts at range lows / highs
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
        sens[mode] = {"universe60": u, "additions": a,
                      "differs_from_central": u != universe60,
                      "swaps": {"in": sorted(set(u) - set(universe60)),
                                "out": sorted(set(universe60) - set(u))}}
        print(f"SENSITIVITY {mode}: differs={u != universe60} swaps={sens[mode]['swaps']}",
              flush=True)

    out = {"method": "v2 corrected: original 30 + next 30 by Nov-2016 market cap; "
                     "computed caps (EDGAR pit shares x 2016-11-18 actual close) "
                     "where free data survives; documented ghost estimates where "
                     "Yahoo purged the series (see build_universe_fix.py)",
           "asof": ASOF, "price_date": "2016-11-18",
           "universe60": universe60, "additions": [r for r in rows
                                                   if r["ticker"] in additions],
           "ranking": rows, "failures": failures, "sensitivity": sens,
           "v1_note": "supersedes build_universe.py v1 (see vm-broad.md for the "
                      "five plumbing corrections)"}
    with open(os.path.join(HERE, "universe-build.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\n=== TOP 70 (v2) ===", flush=True)
    for r in rows[:70]:
        tag = "ORIG30" if r["in_original30"] else ("ADD" if r["ticker"] in additions else "")
        print(f"{r['rank']:3d} {r['ticker']:6s} ${r['market_cap_usd']/1e9:8,.1f}B "
              f"{tag} [{r['cap_source']}]", flush=True)
    print("\nFAILURES:", failures, flush=True)
    print("UNIVERSE60:", universe60, flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
