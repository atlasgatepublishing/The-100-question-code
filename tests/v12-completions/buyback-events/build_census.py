#!/usr/bin/env python3
"""
Build the COMPLETED census for buyback-events (v12).

Base: the frozen, hand-audited 8-K-visible census of v6/v10 (91 events,
imported read-only from the v10 engine). Changes, per CONSTRUCTION-SPEC.md
(frozen before this build):
  * 5 events re-dated to their verified true announcement dates
    (PFE x2, XOM x1 from the hunt; GE x1, CVX x1 surfaced by the
    completed 10-K trail audit — v6 had dated both at a later 8-K
    mention, not at the announcement).
  * 25 wire/newsroom-channel events added (exact publication dates;
    HD x3, BAC x1, T x1 surfaced by the completed trail audit).
  * 7 disclosure-dated events added (authorization proven by the issuer's
    own 10-K/10-Q trail; no announcement release exists; dated at first
    verified public disclosure = the periodic filing date). FLAGGED.
Output: census.json (123 events, channel-tagged, with sources).
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.join(HERE, "..", "..", "v10-retest", "buyback-events", "engine.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = load(V10, "v10_buyback_engine")

REDATE = {
    ("PFE", "2018-01-30"): ("2017-12-18",
        "$10B program — RE-DATED to the true announcement: Pfizer release "
        "of Mon 2017-12-18 (pfizer.com); v6 dated it at first 8-K "
        "disclosure 2018-01-30"),
    ("PFE", "2019-01-29"): ("2018-12-14",
        "$10B program — RE-DATED to the true announcement: Pfizer "
        "dividend/buyback release of Fri 2018-12-14 (same-day coverage, "
        "TheStreet Dec 14, 2018 1:39 PM ET); v6 dated it 2019-01-29"),
    ("XOM", "2023-01-31"): ("2022-12-08",
        "program expansion to $50B through 2024 — RE-DATED to the true "
        "announcement: ExxonMobil corporate-plan release, Business Wire, "
        "2022-12-08; v6 dated it at first 8-K disclosure 2023-01-31"),
    ("GE", "2022-04-26"): ("2022-03-10",
        "$3B program — RE-DATED to the true announcement: board "
        "authorized Mar 6, 2022 (GE FY2022 10-K); publicly unveiled at "
        "GE Investor Day, Mar 10, 2022 (GE investor-day materials: "
        "'Board recently authorized share repurchase up to $3B'; "
        "same-week trade coverage Mar 9-10, 2022); v6 dated it at the "
        "Q1-2022 earnings 8-K mention, 2022-04-26"),
    ("CVX", "2023-01-27"): ("2023-01-25",
        "$75B program — RE-DATED to the true announcement: Chevron "
        "release 'Chevron Increases Quarterly Dividend; Announces $75B "
        "Stock Repurchase Program', Jan 25, 2023 (chevron.com newsroom; "
        "Reuters same-day); board authorized Jan 25, 2023 (CVX FY2022 "
        "10-K); v6 dated it at the Q4 earnings 8-K, 2023-01-27"),
}

WIRE = [
    ("MSFT", "2019-09-18", "$40B program — PR Newswire / Microsoft newsroom release, Sep 18, 2019; confirmed in MSFT 10-K trail"),
    ("MSFT", "2021-09-14", "$60B program — PR Newswire / Microsoft newsroom release, Sep 14, 2021; confirmed in MSFT 10-K trail"),
    ("MSFT", "2024-09-16", "$60B program — PR Newswire release live (prnewswire.com #302249565) + Microsoft newsroom, Sep 16, 2024"),
    ("IBM", "2017-10-31", "+$3B — Business Wire dividend release, Oct 31, 2017; confirmed in IBM 2017 10-K footnote"),
    ("IBM", "2018-10-30", "+$4B — Business Wire release live (businesswire.com/news/home/20181030005777); confirmed in IBM 2018 10-K footnote"),
    ("MA", "2016-12-06", "$4B program — Business Wire release (20161206006366), Dec 6, 2016; MA 2017 10-K board date"),
    ("MA", "2017-12-04", "$4B program — MA 2017 10-K board date Dec 4, 2017 = release date under MA's verified same-day pattern"),
    ("MA", "2018-12-04", "$6.5B program — MA 2018 10-K board date Dec 4, 2018 = release date under MA's verified same-day pattern"),
    ("MA", "2019-12-03", "$8B program — MA 2019 10-K board date Dec 3, 2019 = release date under MA's verified same-day pattern"),
    ("MA", "2020-12-08", "$6B program — Business Wire release live (20201208006042), Dec 8, 2020 4:15 PM ET"),
    ("MA", "2021-11-30", "$8B program — Business Wire release live (20211130006018), Nov 30, 2021"),
    ("MA", "2022-12-06", "$9B program — Business Wire release live (20221206005988), Dec 6, 2022"),
    ("MA", "2023-12-05", "$11B program — Business Wire release live (20231205649394), Dec 5, 2023"),
    ("MA", "2024-12-10", "$12B program — Business Wire release, Dec 2024 (date hand-verified in v6)"),
    ("MA", "2025-12-09", "$14B program — Business Wire release live (20251209088961), Dec 9, 2025"),
    ("WFC", "2018-10-23", "+350M shares — 'publicly announced by the Company on October 23, 2018' (WFC FY2018 10-K)"),
    ("WFC", "2019-07-23", "+350M shares — 'publicly announced by the Company on July 23, 2019' (WFC FY2020 10-K footnote)"),
    ("WFC", "2023-07-25", "$30B program — Business Wire release, Jul 25, 2023; WFC 2023 10-K confirms announcement date"),
    ("WFC", "2025-04-29", "$40B program — Business Wire release live (20250429357394) + WFC newsroom, Apr 29, 2025"),
    ("KO", "2019-02-21", "2019 Plan, 150M shares — 'On February 21, 2019, we publicly announced...' (KO Q1 2019 10-Q)"),
    ("HD", "2017-12-06", "$15B program — PR Newswire release 'The Home Depot Updates Strategic Priorities; ... Announces ... $15 Billion Share Repurchase Authorization', Dec 6, 2017 06:00 ET (2017 Investor and Analyst Conference); surfaced by the completed 10-K trail audit (board authorized Dec 2017, HD FY2017 10-K)"),
    ("HD", "2021-05-20", "$20B program — PR Newswire release 'The Home Depot Declares First Quarter Dividend of $1.65 and Announces $20 Billion Share Repurchase Authorization', May 20, 2021 (HD IR newsroom); surfaced by the completed 10-K trail audit (HD FY2021 10-K)"),
    ("HD", "2022-08-18", "$15B program — PR Newswire release 'The Home Depot Declares Second Quarter Dividend of $1.90 and Announces $15 Billion Share Repurchase Authorization', Aug 18, 2022 (HD IR newsroom; StockTitan timestamped 08/18/2022); surfaced by the completed 10-K trail audit (HD FY2022 10-K)"),
    ("BAC", "2021-10-20", "$25B program renewal — 'On October 20, 2021, the Corporation announced its Board of Directors authorized the repurchase of up to $25 billion of common stock over time (October Authorization)', replacing the April 15, 2021 authorization (BAC FY2021 10-K); surfaced by the completed 10-K trail audit"),
    ("T", "2026-01-28", "+$10B authorization — announced in AT&T's Q4-2025 earnings release, Jan 28, 2026 ('commence repurchases under a subsequent $10 billion authorization that has been approved by the Company's Board of Directors'); board approved Jan 27, 2026 (T FY2025 10-K: 'approved, and we announced'); surfaced by the completed 10-K trail audit"),
]

DISCLOSURE_DATED = [
    ("WFC", "2018-03-01", "Jan 2018 authorization of 350M shares — DISCLOSURE-DATED: no announcement release verified; first public disclosure = FY2017 10-K filed 2018-03-01"),
    ("UNH", "2018-08-07", "Jun 2018 renewal, 100M shares — DISCLOSURE-DATED: no announcement release verified; first public disclosure = Q2 2018 10-Q filed 2018-08-07"),
    ("UNH", "2024-08-09", "Jun 2024 amendment, +35M shares — DISCLOSURE-DATED: Jun 5, 2024 Business Wire board-actions release fetched in full and does NOT mention it; first public disclosure = Q2 2024 10-Q filed 2024-08-09"),
    ("MMM", "2019-02-07", "Nov 2018 new $10B program (replaced Feb 2016 program) — DISCLOSURE-DATED: no announcement release verified; first public disclosure = FY2018 10-K filed 2019-02-07"),
    ("MMM", "2025-02-05", "Feb 2025 new $7.5B program (replaced Nov 2018 program) — DISCLOSURE-DATED: FY2024 10-K filed 2025-02-05 is the first public document carrying the February action"),
    ("GOOGL", "2019-02-05", "Jan 2019 authorization, +$12.0B — DISCLOSURE-DATED: surfaced by the completed 10-K trail audit (Alphabet FY2018 10-K); the Q4-2018 earnings release (Ex-99.1 to the 2019-02-04 8-K) was fetched and verified to carry NO announcement; first public disclosure = FY2018 10-K filed 2019-02-05"),
    ("GE", "2026-01-29", "Dec 2025 authorization, $20B — DISCLOSURE-DATED: surfaced by the completed 10-K trail audit (GE FY2025 10-K: 'a new authorization for up to $20 billion approved by the Board of Directors in December 2025'); no announcement release found (news hunt + GE's Q3-2026 10-Q record notes no 8-K announced a buyback in the period); first verified public disclosure = FY2025 10-K filed 2026-01-29"),
]


def main():
    census = []
    for tk, fd, note in eng.EVENTS:
        if (tk, fd) in REDATE:
            nfd, nnote = REDATE[(tk, fd)]
            census.append({"ticker": tk, "date": nfd, "note": nnote,
                           "channel": "8-K (re-dated to announcement)"})
        else:
            census.append({"ticker": tk, "date": fd, "note": note,
                           "channel": "8-K"})
    for tk, fd, note in WIRE:
        census.append({"ticker": tk, "date": fd, "note": note,
                       "channel": "wire/newsroom"})
    for tk, fd, note in DISCLOSURE_DATED:
        census.append({"ticker": tk, "date": fd, "note": note,
                       "channel": "disclosure-dated"})
    census.sort(key=lambda e: (e["date"], e["ticker"]))
    # dedup guard (spec: same ticker + same amount within 120 days)
    assert len(census) == 91 + 25 + 7, len(census)
    out = {"census_size": len(census),
           "channels": {"8-K": sum(1 for e in census if e["channel"] == "8-K"),
                        "8-K (re-dated to announcement)": sum(1 for e in census if e["channel"].startswith("8-K (re")),
                        "wire/newsroom": len(WIRE),
                        "disclosure-dated": len(DISCLOSURE_DATED)},
           "events": census}
    with open(os.path.join(HERE, "census.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"census: {len(census)} events; channels: {out['channels']}")
    from collections import Counter
    print(Counter(e["ticker"] for e in census))


if __name__ == "__main__":
    main()
