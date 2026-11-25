#!/usr/bin/env python3
"""
LONG-RUN 2010 — shared data plumbing. Simulation only.

Everything here is plumbing, no strategy logic. Sources, all read-only:
  - Prices: the v7 long-hold test's fresh Yahoo pulls (2008-01-01 ->
    2026-11-22), cached in backtests/v7/long-hold/data/pxfull_*.json
    (md5-verified identical to the v9 sweep's own copies).
  - Fundamentals: EDGAR companyfacts cached in
    backtests/v7/long-hold/data/facts_*.json (full files, all history).
  - Engines: the original backtest modules, imported verbatim
    (v4 value-momentum-plainfloor, v7 gap-a5 lazy-prices,
    v8 novel-f3, v8 switch-champion-to-blend, v9 momentum-basket
    simulate). Nothing is retuned anywhere in this test.

The candidate pool, era CIK overrides and name hints are copied
verbatim from backtests/v7/long-hold/long-hold.py so the 2010 pond
built here is the same pond the published long-hold run used.
"""
import importlib.util
import json
import os
import time
import urllib.request
from bisect import bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, "data")
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")   # read-only
V4 = os.path.join(BT, "v4")
V7 = os.path.join(BT, "v7")
V8 = os.path.join(BT, "v8")
V9 = os.path.join(BT, "v9-muse-rules")

UA = "AtlasGateResearch terry-research@example.com"
END = "2026-11-20"
START_CASH = 100.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


champ = load_module("champ_lr", os.path.join(
    V4, "value-momentum-plainfloor.py"))

# ------------------------------------------------------------- pool / CIKs
# Verbatim from backtests/v7/long-hold/long-hold.py
POOL = [
    "AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
    "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
    "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
    "KO", "PEP", "WFC",
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
    "ORCL", "PM", "KFT", "WAG", "WLP", "DTV", "NEM", "FCX", "SBUX",
    "EMR", "NOC",
]
POOL = sorted(set(POOL))

CIK_ERA = {
    "XOM": 34088, "GOOG": 1288776, "DD": 30554, "DOW": 29915,
    "UTX": 1033796, "RTN": 1047128, "TWX": 1105705, "MON": 1110783,
    "AET": 1122304, "YHOO": 1043000, "CELG": 816284, "RAI": 898173,
    "PCLN": 1075531, "MDT": 31091, "WLP": 1156039, "WAG": 104207,
    "KFT": 1103982, "DTV": 1462231, "ESRX": 746515, "AGN": 850693,
}
NAME_HINTS = {"GOOG": "Google", "DD": "Pont", "DOW": "Dow", "UTX": "United",
              "RTN": "Raytheon", "TWX": "Time Warner", "MON": "Monsanto",
              "AET": "Aetna", "YHOO": "Yahoo", "CELG": "Celgene",
              "RAI": "Reynolds", "PCLN": "Priceline", "MDT": "Medtronic",
              "WLP": "WellPoint", "WAG": "Walgreen", "KFT": "Kraft",
              "DTV": "DIRECTV", "ESRX": "Express", "AGN": "Allergan",
              "XOM": "Exxon"}

_CIKS = None


def cik_for(ticker):
    global _CIKS
    if ticker in CIK_ERA:
        return CIK_ERA[ticker]
    if _CIKS is None:
        # the CIK source the long-hold script itself used: the champion
        # engine's shared company-tickers cache. Tickers absent from it
        # with no era override (ALXN, BK, ...) failed there with
        # "no CIK" and fail the same way here — see load_pool.
        with open(os.path.join(champ.SHARED,
                               "company_tickers.json")) as f:
            rows = json.load(f)
        _CIKS = {row["ticker"]: (row["cik_str"],)
                 for row in rows.values()}
    return _CIKS[ticker][0]


# ------------------------------------------------------------- fetching
def fetch_cached(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def load_facts(cik):
    """Full EDGAR companyfacts for a CIK: long-hold cache first
    (read-only), else a fresh EDGAR pull into THIS test's data dir.
    The cached files are gzip-compressed (EDGAR served them that way);
    decompressed transparently — the content is identical."""
    import gzip
    path = os.path.join(LH_DATA, f"facts_{cik:010d}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        path2 = os.path.join(MYDATA, f"facts_{cik:010d}.json")
        blob = fetch_cached(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
            path2)
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return json.loads(blob)


def yahoo_payload(ticker):
    """Full-range Yahoo chart payload (2008 -> 2026-11-22): long-hold
    cache first (read-only), else a fresh pull into this test's data."""
    path = os.path.join(LH_DATA, f"pxfull_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return json.loads(f.read())
    import calendar
    path2 = os.path.join(MYDATA, f"pxfull_{ticker}.json")
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch_cached(url, path2, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(blob)


def bars_adj(payload):
    """Champion bar construction (long-hold bars_from_payload verbatim):
    open/close scaled by adjclose/close; close = adjclose."""
    res = payload["chart"]["result"][0]
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


def bars_raw(payload):
    """Momentum-basket bar construction (its fetch() verbatim): raw
    Yahoo open/close, rows with a missing open or close skipped."""
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None:
            continue
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        rows.append({"d": d, "o": float(o), "c": float(c)})
    rows.sort(key=lambda b: b["d"])
    return rows


def actual_close_on_or_before(payload, price_date):
    """Verbatim from long-hold.py (vm-broad method): actual traded
    close with post-date splits multiplied back in."""
    res = payload["chart"]["result"][0]
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


# ------------------------------------------------------------- price book
class FastPriceBook:
    """Bisect-accelerated PriceBook; proven identical to the champion
    engine's PriceBook by the long-hold test's phase 0 (copied from
    long-hold.py)."""

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


# ------------------------------------------------------------- PIT chains
def equity_chain(facts):
    return (champ.pit_series(facts, "us-gaap", "StockholdersEquity",
                             prio=2) +
            champ.pit_series(
                facts, "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                prio=1))


def shares_chain(facts):
    return (champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap",
                             "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "WeightedAverageNumberOfSharesOutstandingBasic",
                             prio=1))


# ------------------------------------------------------------- pond build
def build_pond(chains_by, payload_by, spy_dates, start):
    """Point-in-time top-30 at `start`, the long-hold method verbatim
    (PIT shares x actual close on the last trading day before start;
    10-calendar-day staleness guard). Returns (ranking_rows, top30)."""
    price_date = max(d for d in spy_dates if d < start)
    rows, unrankable = [], []
    for t in chains_by:
        so = champ.pit_value(chains_by[t][1], start)
        if so is None:
            unrankable.append((t, "no PIT shares within freshness gate"))
            continue
        px, px_d = actual_close_on_or_before(payload_by[t], price_date)
        if px is None:
            unrankable.append((t, f"no bar on/before {price_date}"))
            continue
        gap = (date(int(price_date[:4]), int(price_date[5:7]),
                    int(price_date[8:10])) -
               date(int(px_d[:4]), int(px_d[5:7]),
                    int(px_d[8:10]))).days
        if gap > 10:
            unrankable.append((t, f"last bar {px_d} is {gap}d stale"))
            continue
        rows.append({"ticker": t, "shares": so[2],
                     "shares_filed": so[0],
                     "price_actual": round(px, 4), "price_bar_date": px_d,
                     "market_cap_usd": so[2] * px})
    rows.sort(key=lambda r: -r["market_cap_usd"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows, [r["ticker"] for r in rows[:30]], unrankable, price_date


def load_pool():
    """Facts + payloads for the whole candidate pool (long-hold
    load_pool_data, minus its logging): returns (facts_by, payload_by,
    failures) with the era entityName check applied."""
    facts_by, payload_by, failures = {}, {}, []
    for t in POOL:
        try:
            cik = cik_for(t)
        except KeyError:
            # the original run's own documented failure mode
            failures.append(
                (t, "no CIK (not in tickers file, no override)"))
            continue
        try:
            facts = load_facts(cik)
        except Exception as e:  # noqa
            failures.append((t, f"companyfacts failed: {e}"))
            continue
        ename = facts.get("entityName", "?")
        if t in NAME_HINTS and NAME_HINTS[t].lower() not in ename.lower():
            failures.append((t, f"entityName mismatch: {ename!r} — dropped"))
            continue
        try:
            payload = yahoo_payload(t)
            if not payload["chart"]["result"]:
                raise RuntimeError("empty chart result")
        except Exception as e:  # noqa
            failures.append((t, f"yahoo failed: {e}"))
            continue
        facts_by[t] = facts
        payload_by[t] = payload
    payload_by["SPY"] = yahoo_payload("SPY")
    return facts_by, payload_by, failures


# ------------------------------------------------------------- v9 episodes
def run_v9(run_one, trading_days, start, end, start_cash=START_CASH):
    """The adopted v9 protection spec wrapped around any engine whose
    run_one(start, end, cash, floor) -> result dict with keys
    final/halted/halt_info/costs/trades/curve (the champion-chassis
    shape). Episode 1 runs under a plain -15% floor; on a first halt
    the pot sits in cash 90 calendar days and restarts at the engine's
    next regular decision point on/after eligibility (the engine's own
    selection calendar does that, exactly as long-hold-v9.py ran the
    champion) under an episode-2 floor of -15% from the restart
    balance; a second halt ends the run."""
    episodes = []
    ep1 = run_one(start, end, start_cash, 0.85 * start_cash)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(elig, end, ep1["final"], 0.85 * ep1["final"])
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = None
                if ep2.get("pools"):
                    first = ep2["pools"][0]
                    first_sel = first[0] if isinstance(first, (list, tuple)) \
                        else first.get("date")
                restart = {"halt_date": ep1["halted"],
                           "halt_signal_close":
                               ep1["halt_info"]["signal_close"]
                               if ep1.get("halt_info") else None,
                           "liquidation_proceeds": round(ep1["final"], 2),
                           "eligibility_date": elig,
                           "episode2_first_selection": first_sel,
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "second_halt": ep2["halted"]}
    last = episodes[-1]
    # stitched curve: episode curves + a flat cash line across the
    # sit-out gap at the episode-1 final balance.
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        gap_days = [d for d in trading_days
                    if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap_days]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1, "signal_date": ep["halted"],
                          "signal_close":
                              ep["halt_info"]["signal_close"]
                              if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"episodes": episodes, "final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "halts": halts, "restart": restart, "curve": curve}


def curve_diagnostics(curve, start_cash=START_CASH):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, round(v, 2))
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: v for y, (_, v) in
                                sorted(year_end.items())}}


def cagr(final, start_cash, start, end):
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100, 2), \
        round(yrs, 2)
