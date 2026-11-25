#!/usr/bin/env python3
"""
LONG-HOLD VALUE + MOMENTUM — Terry's AI stock app. Simulation only.

Terry's question (2026-11-21): "Say that they held it for 20 years — can
you run the simulation?" This runs the PROMOTED champion spec (honest
value+momentum, plain -15% floor) continuously for as many years as
honest free point-in-time data allows, and reports whether the pot even
survives that long under the floor.

THE SPEC (identical to the promoted champion; nothing tuned):
  - Universe = top-30 US-listed companies by market cap AS OF the start
    date, COMPUTED point-in-time: EDGAR shares outstanding (most recent
    fact FILED strictly before the start date, the engine's ~18-month
    freshness gate, fallback chain dei cover > us-gaap CommonStock >
    WeightedAverageBasic) x the ACTUAL traded close on the last trading
    day before the start (Yahoo split-adjusted close with post-date
    splits multiplied back in — the vm-broad universe method verbatim).
    Never a modern ranking table, never hindsight.
  - Rank quarterly (first trading day of Jan/Apr/Jul/Oct) by the average
    of the percentile ranks of book-to-market (EDGAR point-in-time book
    equity / market cap) and 12-1 momentum; hold top-5 equal weight;
    rebalance at next open; the ENTIRE pot (gains included) is
    reinvested every quarter.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: Terry's plain -15% floor — $85.00 on the $100 start, for
    the whole run, no ladder, no rungs. A close at/below $85 liquidates
    the pot at the next open and the run ends.
  - Engine: v4's value-momentum-plainfloor.py, imported verbatim
    (pit_series / pit_value / run_pot / spy_net / diagnostics /
    quarter_selection_dates / percentile_ranks). The only local code is
    data loading, universe construction, coverage measurement, and a
    bisect-accelerated PriceBook whose outputs are PROVEN identical to
    the engine's own PriceBook on the baseline windows before use
    (phase 0). Names that cannot be scored point-in-time are excluded
    and named, never patched.

START DATE — chosen by a rule fixed here BEFORE any result was seen:
  Candidate starts: 2010-01-04, 2010-07-01, 2011-01-03, 2011-07-01,
  2012-01-03. For each, build that date's point-in-time top-30 and count
  how many of the 30 are SCORABLE at the first selection date (equity
  filed in time + shares filed in time + >=253 prior price bars — the
  engine's own gates). THE START IS THE EARLIEST CANDIDATE DATE WITH
  >= 25 OF 30 SCORABLE. (XBRL companyfacts begin with the SEC phase-in:
  largest filers from periods ending after 2009-06-15, second tier
  2010, all filers 2011 — that phase-in, not preference, sets the wall.
  Prices are pulled from 2008-01-01 so the 12-1 momentum always has its
  year of history.) If NO candidate reaches 25, the earliest date with
  the highest scorable count is used and the relaxation is flagged.

CANDIDATE POOL for the ranking (~175 names): every US-listed name that
could plausibly sit in the era's top ~75, drawn from era large-cap
membership (S&P 100 / Dow-30 / Nasdaq-100 of the time) — the vm-broad
pool carried back, plus era names it did not need (GOOG as the traded
2011 ticker, ORCL, PM, COP, GM, KFT, WAG, WLP, DTV, NEM, FCX, SBUX,
EMR, NOC, BDX). The pool reaches down to roughly $20-25B of era market
cap, well below the top-30 cut (~$65B+ in 2011), so the computed top-30
cannot be cherry-picked. Foreign ADRs are out (the program's standing
convention). Companies not yet public at the start (META, ABBV, ...)
have no price and no filed facts then and are unrankable by
construction. CIKs are the company AS IT WAS at the start date:
company_tickers.json plus a documented override map for tickers since
acquired / renamed / re-mapped (GOOG -> Google Inc 1288776, DD -> E I
du Pont 30554, DOW -> Dow Chemical 29915, UTX, RTN, TWX, MON, AET,
YHOO, CELG, RAI, PCLN, MDT -> Medtronic Inc 31091, WLP -> WellPoint
1156039, WAG -> Walgreen 104207, KFT -> Kraft Foods 1103982, XOM ->
34088, the engine's own override). Every override's EDGAR entityName
is printed in the log for verification; a mismatch drops the name.

PRICES: one fresh single-vintage Yahoo pull per name, 2008-01-01 ->
2026-11-21, cached in ./data (program caches are read-only inputs and
start in 2017 — too late for this run). Bars are built with the
engine's own transformation (open/close scaled by adjclose/close).
Vintage check: SPY net from these fresh bars over the program's
published windows must land on/near the published $313.62 / $187.77.

RUNS (all $100, plain floor, champion mechanics):
  1. Ranked long-hold run, start -> 2026-11-20, with diagnostics
     (final, halt?, worst close vs floor, max drawdown, year-by-year,
     costs, final holdings) and the x1000 scaling to Terry's $100,000
     frame (linear in this engine except the $0.01/sell-order fee,
     which only shrinks in relative terms as the pot grows).
  2. SPY buy-hold net over the identical window (engine's spy_net).
  3. Placebo: 20 random-pick twins (seeds 1..20, the program's
     convention) from the same point-in-time pool, same mechanics.
  4. Crash table: for each pre-defined stress window overlapping the
     run (2011 euro crisis, 2015-16 selloff, Q4 2018, COVID, 2022
     bear), SPY's trough date in the window and the pot's value then,
     plus the pot's own worst close in the window and its margin over
     the $85 floor.

Run the spec ONCE as specified. No tuning, no friendlier variants.
"""
import importlib.util
import json
import math
import os
import random
import sys
import time
import urllib.request
from bisect import bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, "data")
os.makedirs(MYDATA, exist_ok=True)
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
E.DATA = MYDATA          # engine fetches (facts) land in MY cache only;
                         # E.SHARED stays v4/data (read-only reuse)

UA = "AtlasGateResearch terry-research@example.com"
END = "2026-11-20"
PX_FROM, PX_TO = "2008-01-01", "2026-11-22"
START_CASH, FLOOR0 = 100.0, 85.0
CANDIDATE_STARTS = ["2010-01-04", "2010-07-01", "2011-01-03",
                    "2011-07-01", "2012-01-03"]
MIN_SCORABLE = 25
PLACEBO_SEEDS = list(range(1, 21))

# ------------------------------------------------------------- candidate pool
POOL = [
    # the program's original 30 (2016 list) carried back, GOOG for GOOGL
    "AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
    "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
    "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
    "KO", "PEP", "WFC",
    # vm-broad's candidate pool (2016 large caps, mostly era names too)
    "ABBV", "ABT", "ACN", "ADBE", "AET", "AFL", "AGN", "AIG", "ALL", "ALXN",
    "AMAT", "AMGN", "APC", "APD", "AVGO", "AXP", "BA", "BAX", "BBT",
    "BIIB", "BK", "BLK", "BMY", "BSX", "BX", "C", "CAH", "CAT", "CB",
    "CCI", "CCL", "CELG", "CI", "CL", "CME", "CMCSA", "COF", "COP",
    "COST", "CRM", "CSX", "CTSH", "CVS", "DAL", "DD", "DE", "DHR", "DOW",
    "DUK", "EBAY", "ECL", "EOG", "ESRX", "ETN", "EXC", "F", "FDX", "FE",
    "FISV", "GD", "GILD", "GIS", "GLW", "GM", "GS", "HAL", "HCA",
    "HON", "HPQ", "HUM", "ICE", "INTU", "ITW", "JCI", "K", "KMB", "KMI",
    "KR", "LLY", "LMT", "LOW", "LUV", "LVS", "MCD", "MCK",
    "MDLZ", "MDT", "MET", "MMC", "MO", "MON", "MRK", "MS", "MU", "NEE",
    "NKE", "NSC", "NVDA", "OXY", "PCLN", "PNC", "PRU", "PSA", "PX", "QCOM",
    "RAI", "REGN", "RTN", "SCHW", "SHW", "SLB", "SO", "SPG", "SPGI",
    "STT", "SYK", "TGT", "TJX", "TMO", "TRV", "TSLA", "TXN", "UAL", "UNP",
    "UPS", "USB", "UTX", "VLO", "WM", "WMB", "YHOO", "AAL", "AON", "BDX",
    # era additions (large in 2010-2012, not needed by the 2016 study)
    "ORCL", "PM", "KFT", "WAG", "WLP", "DTV", "NEM", "FCX", "SBUX",
    "EMR", "NOC",
]
POOL = sorted(set(POOL))

# CIK of the company AS IT WAS at the start dates (see header).
CIK_ERA = {
    "XOM": 34088,      # Exxon Mobil Corp (engine's own override)
    "GOOG": 1288776,   # Google Inc (Alphabet holding co dates from 2015)
    "DD": 30554,       # E I du Pont de Nemours (today's DD is the 2019 co)
    "DOW": 29915,      # The Dow Chemical Co (today's DOW = Dow Inc 2019)
    "UTX": 1033796,    # United Technologies (became RTX, Apr 2020)
    "RTN": 1047128,    # Raytheon Co (merged into RTX, Apr 2020)
    "TWX": 1105705,    # Time Warner Inc (acquired by T, Jun 2018)
    "MON": 1110783,    # Monsanto (acquired by Bayer, Jun 2018)
    "AET": 1122304,    # Aetna (acquired by CVS, Nov 2018)
    "YHOO": 1043000,   # Yahoo (sold to Verizon, Jun 2017)
    "CELG": 816284,    # Celgene (acquired by BMY, Nov 2019)
    "RAI": 898173,     # Reynolds American (acquired by BAT, Jul 2017)
    "PCLN": 1075531,   # Priceline Group (renamed Booking/BKNG, 2018)
    "MDT": 31091,      # Medtronic Inc (today's MDT = Medtronic plc 2015)
    "WLP": 1156039,    # WellPoint Inc (renamed Anthem 2014, Elevance 2022)
    "WAG": 104207,     # Walgreen Co (became Walgreens Boots Alliance 2014)
    "KFT": 1103982,    # Kraft Foods Inc (split 2012; remnant became KHC)
    "DTV": 1462231,    # DIRECTV (acquired by T, Jul 2015) — verify name
    "ESRX": 746515,    # Express Scripts Inc (2012 holding co is 1532063)
    "AGN": 850693,     # Allergan Inc (2015 plc is 1578845)
}
# entityName fragments expected for override names (verification, printed)
NAME_HINTS = {"GOOG": "Google", "DD": "Pont", "DOW": "Dow", "UTX": "United",
              "RTN": "Raytheon", "TWX": "Time Warner", "MON": "Monsanto",
              "AET": "Aetna", "YHOO": "Yahoo", "CELG": "Celgene",
              "RAI": "Reynolds", "PCLN": "Priceline", "MDT": "Medtronic",
              "WLP": "WellPoint", "WAG": "Walgreen", "KFT": "Kraft",
              "DTV": "DIRECTV", "ESRX": "Express", "AGN": "Allergan",
              "XOM": "Exxon"}

# stress windows for the crash table (fixed a priori)
CRASH_WINDOWS = [
    ("2011 euro crisis", "2011-04-01", "2011-12-31"),
    ("2015-16 selloff", "2015-05-01", "2016-03-31"),
    ("Q4 2018", "2018-09-01", "2019-01-31"),
    ("COVID crash", "2020-02-01", "2020-04-30"),
    ("2022 bear", "2022-01-01", "2022-12-31"),
]

# ------------------------------------------------------------- fast price book
class FastPriceBook:
    """Same semantics as the engine's PriceBook (bar / close_on_or_before /
    next_open / .bars / .dates), bisect-indexed. Equivalence to the
    engine's PriceBook is proven in phase 0 before this is used."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

    def next_open(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None, None
        i = bisect_right(dl, d)
        if i < len(dl):
            b = self.bars[t][i]
            return b["d"], b["o"]
        return None, None

# ------------------------------------------------------------- data loading
def fetch_cached(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or
                                         {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def yahoo_payload(ticker):
    """Full-range Yahoo chart payload (2008 -> 2026-11-21), cached."""
    import calendar
    path = os.path.join(MYDATA, f"pxfull_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return json.loads(f.read())
    t1 = calendar.timegm(time.strptime(PX_FROM, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(PX_TO, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch_cached(url, path, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(blob)

def bars_from_payload(j):
    """Engine-identical bar construction (from value-momentum-plainfloor
    .get_prices): open/close scaled by adjclose/close, close = adjclose."""
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def actual_close_on_or_before(j, price_date):
    """ACTUAL traded close on/before price_date: Yahoo split-adjusted
    close with every split AFTER price_date multiplied back in
    (vm-broad's yahoo_raw_close_and_splits, verbatim logic). Returns
    (price, bar_date) or (None, None)."""
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    adj_close, adj_date = None, None
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        if d <= price_date and closes[i] is not None:
            adj_close, adj_date = closes[i], d
    if adj_close is None:
        return None, None
    factor = 1.0
    splits = (res.get("events") or {}).get("splits") or {}
    for s in splits.values():
        d = time.strftime("%Y-%m-%d", time.gmtime(s["date"]))
        if d > price_date:
            factor *= s["numerator"] / s["denominator"]
    return adj_close * factor, adj_date

def equity_chain(facts):
    return (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))

def shares_chain(facts):
    return (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))

# ------------------------------------------------------------- phase 0
def phase0_baseline():
    """Reproduce the published champion numbers with the engine's own
    caches, then prove FastPriceBook identical on the FULL window."""
    print("=== PHASE 0: baseline reproduction (engine's own caches) ===",
          flush=True)
    saved_data = E.DATA
    E.DATA = os.path.join(V4, "value-momentum-honest-data")
    ciks = E.get_ciks()
    eq, so, bars = {}, {}, {}
    for t in E.UNIVERSE:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = E.get_companyfacts(cik)
        eq[t], so[t] = equity_chain(facts), shares_chain(facts)
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    out = {}
    pb = E.PriceBook(bars)
    for wname, ws, we, expect in (("FULL", "2019-01-02", END, 544.47),
                                  ("VALIDATION", "2023-01-03", END, 288.05)):
        r = E.run_pot(pb, eq, so, ws, we, START_CASH, FLOOR0, [],
                      label=f"BASE {wname}", quiet=True)
        ok = round(r["final"], 2) == expect
        out[f"baseline_{wname.lower()}"] = {
            "final": round(r["final"], 2), "expected": expect, "match": ok}
        print(f"BASELINE {wname}: ${r['final']:,.2f} expected ${expect:,.2f} "
              f"MATCH={ok}", flush=True)
        if not ok:
            raise SystemExit("BASELINE REPRODUCTION FAILED — stop")
    fpb = FastPriceBook(bars)
    r2 = E.run_pot(fpb, eq, so, "2019-01-02", END, START_CASH, FLOOR0, [],
                   label="BASE FULL FASTBOOK", quiet=True)
    same = abs(r2["final"] - out["baseline_full"]["final"]) < 0.005
    out["fastbook_equivalence_full"] = {"final": round(r2["final"], 2),
                                        "identical": same}
    print(f"FASTBOOK FULL: ${r2['final']:,.2f} identical={same}", flush=True)
    E.DATA = saved_data   # engine fetches from here on land in my cache
    if not same:
        raise SystemExit("FASTBOOK NOT EQUIVALENT — stop")
    return out

# ------------------------------------------------------------- phase 1+2
def load_pool_data():
    """Facts (engine loader: v4 cache read-only, else EDGAR -> my cache)
    and full price payloads for every pool name + SPY."""
    ciks = E.get_ciks()
    facts_by, payload_by, failures = {}, {}, []
    for t in POOL:
        if t in CIK_ERA:
            cik, src = CIK_ERA[t], "era-override"
        elif t in ciks:
            cik, src = ciks[t][0], "company_tickers.json"
        else:
            failures.append((t, "no CIK (not in tickers file, no override)"))
            print(f"{t}: FAIL no CIK", flush=True)
            continue
        try:
            facts = E.get_companyfacts(cik)
        except Exception as e:  # noqa
            failures.append((t, f"companyfacts failed: {e}"))
            print(f"{t}: FAIL facts {e}", flush=True)
            continue
        ename = facts.get("entityName", "?")
        if t in NAME_HINTS and NAME_HINTS[t].lower() not in ename.lower():
            failures.append((t, f"entityName mismatch: {ename!r} "
                                f"(CIK {cik}, {src}) — dropped"))
            print(f"{t}: FAIL entityName {ename!r} != hint "
                  f"{NAME_HINTS[t]!r} — dropped", flush=True)
            continue
        try:
            payload = yahoo_payload(t)
            if not payload["chart"]["result"]:
                raise RuntimeError("empty chart result")
        except Exception as e:  # noqa
            failures.append((t, f"yahoo failed: {e}"))
            print(f"{t}: FAIL yahoo {e}", flush=True)
            continue
        facts_by[t] = facts
        payload_by[t] = payload
        print(f"{t}: cik={cik} ({src}) entity={ename!r} ok", flush=True)
        time.sleep(0.12)
    payload_by["SPY"] = yahoo_payload("SPY")
    return facts_by, payload_by, failures

def rank_and_score(chains_by, payload_by, bars_cache, spy_dates, start):
    """Point-in-time top-30 at `start` + scorable count at the first
    selection date. Mirrors the engine's gates exactly."""
    price_date = max(d for d in spy_dates if d < start)
    rows, unrankable = [], []
    for t in chains_by:
        so = E.pit_value(chains_by[t][1], start)
        if so is None:
            unrankable.append((t, "no PIT shares filed before start "
                                  "within freshness gate"))
            continue
        px, px_d = actual_close_on_or_before(payload_by[t], price_date)
        if px is None:
            unrankable.append((t, f"no Yahoo bar on/before {price_date}"))
            continue
        # staleness guard: the bar used must be within 10 calendar days
        # of the price date (a name not yet listed / long suspended has
        # no business in a point-in-time ranking)
        from datetime import date as _d
        gap = (_d(int(price_date[:4]), int(price_date[5:7]),
                  int(price_date[8:10])) -
               _d(int(px_d[:4]), int(px_d[5:7]), int(px_d[8:10]))).days
        if gap > 10:
            unrankable.append((t, f"last bar {px_d} is {gap}d before "
                                  f"{price_date} — stale/unlisted"))
            continue
        rows.append({"ticker": t, "shares": so[2], "shares_filed": so[0],
                     "price_actual": round(px, 4), "price_bar_date": px_d,
                     "market_cap_usd": so[2] * px})
    rows.sort(key=lambda r: -r["market_cap_usd"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    top30 = [r["ticker"] for r in rows[:30]]
    # first selection date: engine's quarter_selection_dates on SPY dates
    class _PB:  # minimal stand-in carrying .dates for the engine helper
        dates = spy_dates
    sel = E.quarter_selection_dates(_PB, start, END)
    first_sel = sel[0] if sel else None
    # scorable at first selection — the engine's own gates, replicated
    bars_by = {t: bars_cache.setdefault(
        t, bars_from_payload(payload_by[t])) for t in top30}
    scorable, unscorable = [], []
    for t in top30:
        be = E.pit_value(chains_by[t][0], first_sel)
        so = E.pit_value(chains_by[t][1], first_sel)
        bl = bars_by[t]
        didx = next((i for i, b in enumerate(bl) if b["d"] == first_sel),
                    None)
        px = None
        for b in bl:
            if b["d"] <= first_sel:
                px = b["c"]
            else:
                break
        why = []
        if be is None:
            why.append("no PIT book equity")
        if so is None or so[2] <= 0:
            why.append("no PIT shares")
        if px is None:
            why.append("no price")
        if didx is None or didx < 253:
            why.append(f"momentum bars insufficient (idx={didx})")
        (scorable if not why else unscorable).append(
            t if not why else (t, "; ".join(why)))
    return {"start": start, "price_date": price_date,
            "first_selection": first_sel, "ranking": rows,
            "unrankable": unrankable, "top30": top30,
            "n_rankable": len(rows), "scorable": scorable,
            "unscorable": unscorable,
            "n_scorable": len(scorable)}

# ------------------------------------------------------------- phase 3
def spy_curve(pb, start, end, start_cash):
    """Daily mark of a SPY buy-hold bought at the first open (spy_net
    mechanics; liquidation cost applied only in spy_net's final)."""
    days = [d for d in pb.dates if start <= d <= end]
    o = pb.bar("SPY", days[0])["o"]
    sh = (start_cash / 1.001) / o
    return {d: sh * pb.close_on_or_before("SPY", d) for d in days}, sh

def crash_table(ranked, pb, start):
    curve = dict(ranked["curve"])
    halt_date = ranked["halted"]
    final_cash = ranked["final"]
    scurve, _ = spy_curve(pb, start, END, START_CASH)
    out = []
    for name, w0, w1 in CRASH_WINDOWS:
        if w1 < start:
            continue
        w0 = max(w0, start)
        spy_win = {d: v for d, v in scurve.items() if w0 <= d <= w1}
        if not spy_win:
            continue
        trough_d = min(spy_win, key=lambda d: spy_win[d])
        if halt_date and trough_d > halt_date:
            pot_at, note = final_cash, f"pot already halted {halt_date}"
        else:
            pot_at = curve.get(trough_d)
            note = ""
        pot_win = {d: v for d, v in curve.items() if w0 <= d <= w1}
        pot_min = min(pot_win.values()) if pot_win else None
        pot_min_d = (min(pot_win, key=lambda d: pot_win[d])
                     if pot_win else None)
        out.append({
            "window": name, "range": [w0, w1],
            "spy_trough_date": trough_d,
            "spy_value_at_trough": round(spy_win[trough_d], 2),
            "pot_value_on_spy_trough": (round(pot_at, 2)
                                        if pot_at is not None else None),
            "pot_worst_close_in_window": (round(pot_min, 2)
                                          if pot_min is not None else None),
            "pot_worst_date": pot_min_d,
            "pot_margin_above_floor": (round(pot_min - FLOOR0, 2)
                                       if pot_min is not None else None),
            "note": note})
    return out

def main():
    t0 = time.time()
    results = {"spec": "value+momentum champion, plain -15% floor, $100",
               "end": END}
    results["phase0"] = phase0_baseline()

    print("=== PHASE 1: pool data ===", flush=True)
    facts_by, payload_by, failures = load_pool_data()
    spy_bars = bars_from_payload(payload_by["SPY"])
    spy_dates = [b["d"] for b in spy_bars]

    print("=== PHASE 2: coverage / start-date choice ===", flush=True)
    chains_by = {t: (equity_chain(f), shares_chain(f))
                 for t, f in facts_by.items()}
    bars_cache = {}
    coverage = []
    for s in CANDIDATE_STARTS:
        c = rank_and_score(chains_by, payload_by, bars_cache, spy_dates, s)
        coverage.append(c)
        print(f"START {s}: rankable={c['n_rankable']} top30={c['top30']} "
              f"scorable={c['n_scorable']}/30 first_sel={c['first_selection']}",
              flush=True)
        for u in c["unscorable"]:
            print(f"    unscorable: {u}", flush=True)
    chosen, relaxed = None, False
    for c in coverage:
        if c["n_scorable"] >= MIN_SCORABLE:
            chosen = c
            break
    if chosen is None:
        relaxed = True
        best = max(c["n_scorable"] for c in coverage)
        chosen = next(c for c in coverage if c["n_scorable"] == best)
    start = chosen["start"]
    universe = chosen["top30"]
    print(f"CHOSEN START: {start} (scorable {chosen['n_scorable']}/30, "
          f"rule_relaxed={relaxed})", flush=True)
    print(f"UNIVERSE ({len(universe)}): {universe}", flush=True)
    results["start_choice"] = {
        "chosen_start": start, "rule": f"earliest candidate start with "
        f">= {MIN_SCORABLE}/30 scorable at first selection",
        "rule_relaxed": relaxed,
        "coverage": [{k: c[k] for k in ("start", "price_date",
                                         "first_selection", "n_rankable",
                                         "top30", "n_scorable",
                                         "scorable", "unscorable",
                                         "unrankable")}
                      for c in coverage],
        "pool_failures": failures}
    with open(os.path.join(HERE, "universe-build-long.json"), "w") as f:
        json.dump({"chosen_start": start, "universe": universe,
                   "ranking_at_chosen": chosen["ranking"],
                   "coverage": results["start_choice"]["coverage"],
                   "pool_failures": failures}, f, indent=1, default=str)

    print("=== PHASE 3: long-hold runs ===", flush=True)
    E.UNIVERSE = universe
    eq = {t: chains_by[t][0] for t in universe}
    so = {t: chains_by[t][1] for t in universe}
    bars = {t: bars_cache.setdefault(
        t, bars_from_payload(payload_by[t])) for t in universe}
    bars["SPY"] = spy_bars
    pb = FastPriceBook(bars)

    # vintage cross-check: SPY net from the fresh bars vs published
    spyonly = FastPriceBook({"SPY": spy_bars})
    vc = {}
    for wname, ws, expect in (("FULL", "2019-01-02", 313.62),
                              ("VALIDATION", "2023-01-03", 187.77)):
        v, _ = E.spy_net(spyonly, ws, END, START_CASH)
        vc[wname.lower()] = {"spy_net_fresh": round(v, 2),
                             "published": expect,
                             "diff": round(v - expect, 2)}
        print(f"VINTAGE CHECK {wname}: fresh SPY=${v:,.2f} vs published "
              f"${expect:,.2f} (diff {v - expect:+.2f})", flush=True)
    results["vintage_check_spy"] = vc

    ranked = E.run_pot(pb, eq, so, start, END, START_CASH, FLOOR0, [],
                       label="LONG-HOLD RANKED", quiet=True,
                       record_pools=True)
    diag = E.diagnostics(ranked, FLOOR0)
    spy_final, spy_costs = E.spy_net(pb, start, END, START_CASH)
    from datetime import date as _d
    yrs = (_d(int(END[:4]), int(END[5:7]), int(END[8:10])) -
           _d(int(start[:4]), int(start[5:7]), int(start[8:10]))).days / 365.25
    cagr = (ranked["final"] / START_CASH) ** (1.0 / yrs) - 1.0
    spy_cagr = (spy_final / START_CASH) ** (1.0 / yrs) - 1.0
    # final holdings from the closing trades
    close_side = "SELL-HALT" if ranked["halted"] else "SELL-END"
    holdings = [{"ticker": t, "shares": round(sh, 4), "price": px,
                 "value": round(val, 2)}
                for (d, t, sd, sh, px, val, c) in ranked["trades"]
                if sd == close_side]
    pool_sizes = [(d, len(pool), picks) for d, pool, picks in ranked["pools"]]
    results["ranked"] = {
        "start": start, "end": ranked["end"], "years": round(yrs, 2),
        "final": round(ranked["final"], 2),
        "final_x1000_for_100k_pot": round(ranked["final"] * 1000, 2),
        "total_return_pct": round(ranked["final"] / START_CASH * 100 - 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "halted": ranked["halted"], "halt_info": ranked["halt_info"],
        "costs": round(ranked["costs"], 2), "orders": len(ranked["trades"]),
        "diag": diag, "final_holdings": holdings,
        "last_selection_picks": pool_sizes[-1][2] if pool_sizes else None,
        "pool_sizes": [(d, n) for d, n, _ in pool_sizes],
        "spy_net_final": round(spy_final, 2),
        "spy_total_return_pct": round(spy_final / START_CASH * 100 - 100, 2),
        "spy_cagr_pct": round(spy_cagr * 100, 2)}
    print(f"RANKED: final=${ranked['final']:,.2f} "
          f"({results['ranked']['total_return_pct']:+.1f}%, "
          f"CAGR {results['ranked']['cagr_pct']:.2f}%) halted={ranked['halted']} "
          f"costs=${ranked['costs']:,.2f} orders={len(ranked['trades'])} | "
          f"SPY=${spy_final:,.2f}", flush=True)
    print(f"  worst close ${diag['worst_close']} on {diag['worst_close_date']} "
          f"(margin above floor ${diag['worst_close_above_floor']}) | "
          f"maxDD {diag['max_drawdown_pct']}%", flush=True)

    print("=== PHASE 3b: placebos ===", flush=True)
    finals, prows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = E.run_pot(pb, eq, so, start, END, START_CASH, FLOOR0, [],
                       placebo_rng=rng, label=f"PL {seed}", quiet=True)
        finals.append(pr["final"])
        prows.append({"seed": seed, "final": round(pr["final"], 2),
                      "halted": pr["halted"],
                      "orders": len(pr["trades"]),
                      "costs": round(pr["costs"], 2)})
        print(f"  PLACEBO {seed:2d}: ${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked["final"])
    ties = sum(1 for f in finals if f == ranked["final"])
    results["placebo"] = {
        "median": round(E._pct(srt, 0.50), 2),
        "q1": round(E._pct(srt, 0.25), 2), "q3": round(E._pct(srt, 0.75), 2),
        "best": round(srt[-1], 2), "worst": round(srt[0], 2),
        "mean": round(sum(finals) / len(finals), 2),
        "halted_count": sum(1 for p in prows if p["halted"]),
        "ranked_final": round(ranked["final"], 2),
        "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
        "seeds_beaten": below, "rows": prows}
    print(f"PLACEBO: median=${results['placebo']['median']:,.2f} "
          f"best=${results['placebo']['best']:,.2f} "
          f"worst=${results['placebo']['worst']:,.2f} "
          f"halted={results['placebo']['halted_count']}/20 | ranked "
          f"${ranked['final']:,.2f} = {results['placebo']['ranked_percentile']}th "
          f"pctile (beat {below}/20)", flush=True)

    results["crash_table"] = crash_table(ranked, pb, start)
    for row in results["crash_table"]:
        print(f"CRASH {row['window']}: SPY trough {row['spy_trough_date']} "
              f"${row['spy_value_at_trough']} | pot then "
              f"${row['pot_value_on_spy_trough']} | pot worst "
              f"${row['pot_worst_close_in_window']} on {row['pot_worst_date']} "
              f"(margin ${row['pot_margin_above_floor']}) {row['note']}",
              flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "long-hold-results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"DONE in {results['elapsed_sec']}s", flush=True)

if __name__ == "__main__":
    main()
