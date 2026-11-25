#!/usr/bin/env python3
"""
BUILD THE TOP-60 UNIVERSE — point-in-time, as of November 2016.
Simulation only. Part of the vm-broad study (see vm-broad.py / vm-broad.md).

How the original top-30 was built (momentum-basket-honest.py): "the 30
largest US-listed companies by market cap as of November 2016, from 2016
knowledge only". This builder extends THE SAME method to 60:

  UNIVERSE60 = the original 30 (untouched)
             + the 30 next-largest US-listed companies by market cap
               as of November 2016, from a candidate pool ranked by
               computed point-in-time market caps.

Market cap as of Nov 2016, computed — never looked up from a modern
ranking table:
  shares = EDGAR shares outstanding, point-in-time: most recent fact
           FILED strictly before 2016-11-21, ~18-month freshness gate —
           the baseline engine's own pit machinery (imported verbatim
           from value-momentum-plainfloor.py), same fallback chain
           (dei cover page > us-gaap CommonStockSharesOutstanding >
           WeightedAverageNumberOfSharesOutstandingBasic).
  price  = actual traded close on 2016-11-18 (last trading day before
           the 2016-11-21 anchor). Yahoo's chart API returns
           split-adjusted closes, so the cumulative split factor of all
           splits AFTER 2016-11-18 (from the same API's split events)
           is multiplied back in. No dividend adjustment is involved:
           the quote close is split-adjusted only.
  cap    = shares x price.

Candidate pool: the original 30 plus every US-listed name that could
plausibly sit in the Nov-2016 top ~75 — drawn from 2016 large-cap
membership (S&P 100 / Dow-30 / Nasdaq-100 of the era and published
2016 market-cap rankings). The pool is deliberately wider than the
cut (~180 names down to roughly $25B) so the computed top-60 cannot be
accused of cherry-picking: names the hindsight eye would love (TSLA,
~$30B then) and names it would forget (MRK, CMCSA, C, ORCL — all
omitted from the original hand-built 30) are ranked by the same
arithmetic. Multi-class companies are ranked on the traded class the
engine would use — the original list's own convention (Alphabet via
GOOGL, Berkshire via BRK-B). Foreign ADRs (BABA, TSM, AZN, Canadian
banks, etc.) are out, as they were for the original list; NYSE-listed
S&P 500 constituents domiciled abroad (ACN, MDT, AVGO, JCI) stay in
the pool and are flagged in the output.

CIK resolution: SEC company_tickers.json (today's file, cached) plus a
documented override map for tickers that have since been acquired,
renamed or re-mapped to a successor registrant — for those, the CIK of
the company AS IT WAS in Nov 2016 is used for the ranking. (In the
backtest itself, the baseline convention applies: today's ticker file
+ the XOM override only, exactly as the promoted spec ran — see
vm-broad.md for what that does to DIS-style names.)
"""
import importlib.util
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, "data")
os.makedirs(MYDATA, exist_ok=True)

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

CANDIDATES = [
    "ABBV", "ABT", "ACN", "ADBE", "AET", "AFL", "AGN", "AIG", "ALL", "ALXN",
    "AMAT", "AMGN", "ANTM", "APC", "APD", "AVGO", "AXP", "BA", "BAX", "BBT",
    "BIIB", "BK", "BLK", "BMY", "BSX", "BX", "C", "CAH", "CAT", "CB",
    "CCI", "CCL", "CELG", "CHTR", "CI", "CL", "CME", "CMCSA", "COF", "COP",
    "COST", "CRM", "CSX", "CTSH", "CVS", "DAL", "DD", "DE", "DHR", "DOW",
    "DUK", "EBAY", "ECL", "EOG", "ESRX", "ETN", "EXC", "F", "FDX", "FE",
    "FISV", "FOXA", "GD", "GILD", "GIS", "GLW", "GM", "GS", "HAL", "HCA",
    "HON", "HPQ", "HPE", "HUM", "ICE", "INTU", "ITW", "JCI", "K", "KHC",
    "KMB", "KMI", "KR", "LLY", "LMT", "LOW", "LUV", "LVS", "MCD", "MCK",
    "MDLZ", "MDT", "MET", "MMC", "MO", "MON", "MRK", "MS", "MU", "NEE",
    "NKE", "NSC", "NVDA", "OXY", "PCLN", "PNC", "PRU", "PSA", "PX", "PYPL",
    "QCOM", "RAI", "REGN", "RTN", "SCHW", "SHW", "SLB", "SO", "SPG", "SPGI",
    "STT", "SYF", "SYK", "TGT", "TJX", "TMO", "TMUS", "TRV", "TSLA", "TWX",
    "TXN", "UAL", "UNP", "UPS", "USB", "UTX", "VLO", "WBA", "WM", "WMB",
    "YHOO", "AAL", "AON", "BDX",
]

# CIK of the company AS IT WAS in Nov 2016, for tickers whose current
# company_tickers.json entry is missing or points at a successor.
CIK_2016 = {
    "TWX": 1105705,    # Time Warner Inc (acquired by T, Jun 2018)
    "MON": 1110783,    # Monsanto (acquired by Bayer, Jun 2018)
    "AET": 1122304,    # Aetna (acquired by CVS, Nov 2018)
    "RAI": 898173,     # Reynolds American (acquired by BAT, Jul 2017)
    "YHOO": 1043000,   # Yahoo (sold to Verizon, Jun 2017)
    "CELG": 816284,    # Celgene (acquired by BMY, Nov 2019)
    "ESRX": 1532063,   # Express Scripts Holding (acquired by CI, Dec 2018)
    "AGN": 1578845,    # Allergan plc (acquired by ABBV, May 2020)
    "UTX": 1033796,    # United Technologies (became RTX, Apr 2020)
    "RTN": 1047128,    # Raytheon Co (merged into RTX, Apr 2020)
    "ANTM": 1156039,   # Anthem (renamed Elevance/ELV, 2022)
    "PCLN": 1075531,   # Priceline Group (renamed Booking/BKNG, 2018)
    "FOXA": 1308161,   # Twenty-First Century Fox (split, Mar 2019)
    "DOW": 29915,      # The Dow Chemical Co (today's DOW = Dow Inc)
    "DD": 30554,       # E I du Pont de Nemours (today's DD = DuPont de Nemours)
    "ALXN": 939767,    # Alexion (acquired by AZN, Jul 2021)
}
ASOF_FILED_BEFORE = "2016-11-21"
PRICE_DATE = "2016-11-18"          # last trading day before the anchor


def yahoo_raw_close_and_splits(ticker):
    """Return (split-adjusted close on/before PRICE_DATE, cumulative split
    factor after PRICE_DATE, actual price) or (None, None, why)."""
    import calendar
    t1 = calendar.timegm(time.strptime("2016-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    path = os.path.join(MYDATA, f"rank_px_{ticker}.json")
    blob = E.fetch(url, path, headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    adj_close, adj_date = None, None
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        if d <= PRICE_DATE and closes[i] is not None:
            adj_close, adj_date = closes[i], d
    if adj_close is None:
        return None, None, "no Yahoo bar on/before 2016-11-18"
    factor = 1.0
    splits = (res.get("events") or {}).get("splits") or {}
    for s in splits.values():
        d = time.strftime("%Y-%m-%d", time.gmtime(s["date"]))
        if d > PRICE_DATE:
            factor *= s["numerator"] / s["denominator"]
    return adj_close * factor, adj_date, None


def main():
    ciks = E.get_ciks()
    pool = ORIGINAL30 + [t for t in CANDIDATES if t not in ORIGINAL30]
    rows, failures = [], []
    for t in pool:
        cik = CIK_2016.get(t)
        src = "override-2016"
        if cik is None:
            if t in ciks:
                cik = ciks[t][0]
                src = "company_tickers.json"
            else:
                failures.append((t, "ticker not in company_tickers.json, no override"))
                print(f"{t}: FAIL no CIK", flush=True)
                continue
        try:
            facts = E.get_companyfacts(cik)
        except Exception as e:  # noqa
            failures.append((t, f"companyfacts fetch failed: {e}"))
            print(f"{t}: FAIL facts {e}", flush=True)
            continue
        shares_rows = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        so = E.pit_value(shares_rows, ASOF_FILED_BEFORE)
        if so is None:
            failures.append((t, "no shares fact filed before 2016-11-21 within freshness gate"))
            print(f"{t}: FAIL no point-in-time shares", flush=True)
            continue
        try:
            px, px_date, why = yahoo_raw_close_and_splits(t)
        except Exception as e:  # noqa
            px, why = None, f"Yahoo fetch failed: {e}"
        if px is None:
            failures.append((t, why))
            print(f"{t}: FAIL price {why}", flush=True)
            continue
        cap = so[2] * px
        rows.append({"ticker": t, "cik": cik, "cik_source": src,
                     "shares": so[2], "shares_filed": so[0], "shares_end": so[1],
                     "price_2016_11_18_actual": round(px, 4), "price_bar_date": px_date,
                     "market_cap_usd": cap, "in_original30": t in ORIGINAL30})
        print(f"{t}: shares={so[2]:,.0f} (filed {so[0]}) px=${px:,.2f} "
              f"cap=${cap/1e9:,.1f}B", flush=True)
        time.sleep(0.12)
    rows.sort(key=lambda r: -r["market_cap_usd"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    additions = [r for r in rows if not r["in_original30"]][:30]
    universe60 = ORIGINAL30 + [r["ticker"] for r in additions]
    out = {"method": "original 30 + next 30 by computed point-in-time market cap "
                     "as of Nov 2016 (EDGAR shares filed < 2016-11-21 x actual "
                     "close 2016-11-18, splits un-adjusted)",
           "asof": ASOF_FILED_BEFORE, "price_date": PRICE_DATE,
           "universe60": universe60, "additions": additions,
           "ranking": rows, "failures": failures}
    with open(os.path.join(HERE, "universe-build.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\n=== TOP 70 ===", flush=True)
    for r in rows[:70]:
        tag = "ORIG30" if r["in_original30"] else ("ADD" if r in additions else "")
        print(f"{r['rank']:3d} {r['ticker']:6s} ${r['market_cap_usd']/1e9:8,.1f}B {tag}",
              flush=True)
    print("\nFAILURES:", failures, flush=True)
    print("UNIVERSE60:", universe60, flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
