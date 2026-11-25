#!/usr/bin/env python3
"""
INDEX ADDITIONS (S&P 500) — spec 4.1 of the firm reverse-engineering audit
(~/workspace/stock-app/research/v7-completeness/firm-reverse-engineering.md).
Simulation only. Terry's AI stock app — census family: index-rebalance flow
trading (ingredient #18, Millennium's documented pod specialty), long-only.

THE FROZEN SPEC (section 4.1, implemented exactly as written):
  - Universe: every S&P 500 ADDITION announced between 2016-11-21 and
    2026-11-20. Event list built from S&P Dow Jones Indices press releases
    (free PR Newswire archive); the Wikipedia-derived change log is used
    only as a cross-check and is flagged as current-vintage. Deletions
    excluded.
  - Signal/timing: buy at the OPEN of the first trading day after the
    announcement date; sell at the CLOSE of the effective date.
  - Portfolio: $100 pot; if several events are open simultaneously, split
    the pot equally among open events; otherwise fully in the single
    event; cash between events. No leverage, no other holdings.
  - Costs/floor: program standard (0.10% of trade value per side +
    $0.01 per sell order); plain -15% floor on the daily close of total
    pot value (close at/below $85 halts the pot; the halt is the result).
    A 2x-cost stress is reported alongside (section 4 preamble).
  - Judging: continuous 2019-01-02 -> 2026-11-20 and validation
    2023-01-03 -> 2026-11-20 (the champion's coded window bounds; events
    bucketed by announcement date). Design-period events (announced
    2016-11-21 -> 2018-12-31) reported for count only.
  - Placebo: (i) the same names bought at the open 20 trading days AFTER
    their effective date, held the same number of days; (ii) 20 seeds of
    random honest-top-30 names entered on the same announcement dates
    with the same hold lengths.
  - PRE-REGISTERED GATE: validation mean event return net of costs > 0
    AND the pot beats >= 18/20 placebos on validation. Section 4
    promotion bar: beat SPY and the placebo distribution on validation.

FORCED READINGS (stated here, before any results — the spec's ambiguous
points, resolved mechanically; see the .md report for the full list):
  1. Announcement date = the PR Newswire transmission date (ET) of the
     S&P DJI release that names the addition AND its effective date
     (releases transmit ~17:30-19:00 ET, after the close). Where a
     conditional announcement was followed by a definitive release
     (KVUE), the definitive release governs.
  2. Entry = the open of the first trading day strictly after the
     announcement date ON WHICH THE TICKER HAS A PRICE BAR (spin-offs
     often have no bar until their first regular-way trading day;
     when-issued bars count if present). If that first available bar
     falls AFTER the effective date, the event is untradeable under the
     spec and is excluded, with the reason stated.
  3. Exit = the close on the effective date; if the ticker has no bar
     on the effective date, the last close on or before it, flagged.
  4. Prices = the champion's adjusted bars (open x adjclose/close;
     close = adjclose), so splits/dividends inside a window are handled
     exactly as in every other program test.
  5. Equal-split mechanics: at each entry day's open the pot rebalances
     to equal dollar weights across ALL currently open events (new
     entrant included), valuing the pot at that day's opens; sells
     before buys; program costs on every fill; buys capped by available
     cash / 1.001 (the champion's execute_rebalance pattern). An event
     that exits at today's close still counts as open at today's open.
     Weights drift with prices between entry days; cash is held
     whenever no event is open.
  6. Per-event net return (for the gate): a standalone $100 single-event
     pot — shares = (100/1.001)/entry_open; proceeds = shares x
     exit_close; net = proceeds - (proceeds x 0.001 + 0.01);
     return = net/100 - 1. Gross return (exit/entry - 1) also reported.
  7. Hold length = trading-day steps in the ticker's own bar series:
     bar_index(exit) - bar_index(entry). Placebo (i): entry = open of
     the bar 20 trading days after the effective-date bar; exit = entry
     index + hold length, at close. Placebo (ii): per seed (1..20,
     random.Random(seed)), each event draws one name from the champion's
     honest-top-30 UNIVERSE; entry on the first bar after the real
     event's announcement date in the drawn name's series; exit = entry
     index + the real event's hold length in the drawn name's series.
     Both placebos run through the SAME pot machinery (equal split,
     costs, floor). The gate's ">=18/20 placebos" reads on placebo (ii).
  8. Placebo trades that cannot complete by the last available bar
     (2026-11-20) are excluded from that placebo pot and counted.
  9. Renamed continuations of existing constituents (same legal issuer,
     shares simply continued under a new name/ticker — incl. the
     Wikipedia log's Pattern-3 add+remove pairs) are NOT additions and
     are excluded; decided by S&P DJI's own "surviving entity" language
     where available. Spin-offs and new-issuer merger successors whose
     predecessor was not a constituent ARE additions and are kept.
 10. SW (Smurfit Westrock, effective 2024-07-08) is EXCLUDED: no S&P DJI
     announcement release exists in the free PR Newswire archive and no
     announcement date could be verified from any free source (the
     addition was effective on the successor's first trading day; the
     company's own first mention of its S&P 500 inclusion is its
     2024-07-30 earnings release, after the fact). The spec's entry rule
     cannot be applied without inventing a date, so the event is
     excluded rather than guessed.
 11. Winning-years table (house format): a fresh $100 pot per calendar
     year trading that year's announced events vs SPY net for the same
     span — reporting only, not part of the gate.
 12. Design-period count: derived from the point-in-time baseline file
     "S&P 500 Historical Components & Changes.csv" (fja05680/sp500) by
     diffing consecutive daily constituent snapshots; a ticker's first
     appearance is counted as an addition with the snapshot date as its
     effective date. FRC (announced 2018-12-27, effective 2019-01-02) is
     added manually (+1) because bucketing is by announcement date.
     Rename pairs inflate the raw diff count; both counts are reported.

Data sources:
  - Event list: S&P DJI press releases via the PR Newswire company
    archive (pages 1-26 swept, Nov 2018 -> Nov 2026; individual release
    bodies give effective dates; transmission IDs give exact dates).
    Cross-check: fja05680/sp500 sp500_changes_since_2019.csv
    (Wikipedia-derived, CURRENT-VINTAGE — flagged; nine discrepancies
    were caught and the press releases won every time; see report).
  - Prices: Yahoo Finance chart API, the champion's method/format,
    reusing the v4/data and v5 caches read-only where present and
    fetching the rest into ./data.
"""
import csv, json, math, os, random, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
V4DATA = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")
V5CACHE = os.path.expanduser("~/workspace/stock-app/research/v5/cache")
os.makedirs(DATA, exist_ok=True)

START_CASH = 100.0
FLOOR = 85.0
PLACEBO_SEEDS = list(range(1, 21))
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]   # champion's honest top-30 (placebo pool)

# ------------------------------------------------------------- event list
# (ticker, announcement date, effective date, note) — every date verified
# against the S&P DJI press release itself during the harvest.
EVENTS = [
    # ---- 2019 (continuous bucket) ----
    ("TFX", "2019-01-15", "2019-01-18", ""),
    ("ATO", "2019-02-08", "2019-02-15", ""),
    ("WAB", "2019-02-21", "2019-02-27", ""),
    ("DOW", "2019-03-26", "2019-04-02", "spin-off (DowDuPont)"),
    ("CTVA", "2019-05-28", "2019-06-03", "spin-off (DowDuPont)"),
    ("DD", "2019-05-28", "2019-06-03", "spin-off successor (DowDuPont)"),
    ("BMS", "2019-06-03", "2019-06-07", "added as Bemis; renamed Amcor (AMCR) at merger close 2019-06-11, after exit"),
    ("MKTX", "2019-06-24", "2019-07-01", ""),
    ("TMUS", "2019-07-09", "2019-07-15", ""),
    ("LDOS", "2019-08-01", "2019-08-09", ""),
    ("IEX", "2019-08-01", "2019-08-09", ""),
    ("CDW", "2019-09-17", "2019-09-23", ""),
    ("NVR", "2019-09-20", "2019-09-26", ""),
    ("LVS", "2019-09-26", "2019-10-03", ""),
    ("NOW", "2019-11-18", "2019-11-21", "announcement date from the S&P Global release itself, cited in Wikipedia's historical-components references"),
    ("WRB", "2019-11-27", "2019-12-05", ""),
    ("ODFL", "2019-12-02", "2019-12-09", ""),
    ("STE", "2019-12-13", "2019-12-23", ""),
    ("ZBRA", "2019-12-13", "2019-12-23", ""),
    ("LYV", "2019-12-13", "2019-12-23", ""),
    # ---- 2020 ----
    ("PAYC", "2020-01-22", "2020-01-28", ""),
    ("IR", "2020-02-27", "2020-03-03", "announced as Gardner Denver (GDI); GDI renamed itself Ingersoll Rand Inc. (IR) on 2020-03-02 — same listing, 1:1"),
    ("OTIS", "2020-03-31", "2020-04-03", "spin-off (United Technologies)"),
    ("CARR", "2020-03-31", "2020-04-03", "spin-off (United Technologies)"),
    ("DXCM", "2020-05-06", "2020-05-12", ""),
    ("DPZ", "2020-05-06", "2020-05-12", ""),
    ("WST", "2020-05-18", "2020-05-22", ""),
    ("TYL", "2020-06-12", "2020-06-22", ""),
    ("BIO", "2020-06-12", "2020-06-22", ""),
    ("TDY", "2020-06-12", "2020-06-22", ""),
    ("ETSY", "2020-09-04", "2020-09-21", ""),
    ("TER", "2020-09-04", "2020-09-21", ""),
    ("CTLT", "2020-09-04", "2020-09-21", ""),
    ("POOL", "2020-10-01", "2020-10-07", ""),
    ("VNT", "2020-10-05", "2020-10-09", "spin-off (Arconic)"),
    ("TSLA", "2020-11-16", "2020-12-21", ""),
    ("ENPH", "2020-12-30", "2021-01-07", ""),
    # ---- 2021 ----
    ("TRMB", "2021-01-15", "2021-01-21", ""),
    ("MPWR", "2021-02-08", "2021-02-12", ""),
    ("CZR", "2021-03-12", "2021-03-22", ""),
    ("GNRC", "2021-03-12", "2021-03-22", ""),
    ("PENN", "2021-03-12", "2021-03-22", ""),
    ("NXPI", "2021-03-12", "2021-03-22", ""),
    ("PTC", "2021-04-15", "2021-04-20", ""),
    ("CRL", "2021-05-10", "2021-05-14", ""),
    ("OGN", "2021-05-27", "2021-06-03", "spin-off (Merck)"),
    ("MRNA", "2021-07-15", "2021-07-21", ""),
    ("TECH", "2021-08-24", "2021-08-30", ""),
    ("BRO", "2021-09-03", "2021-09-20", ""),
    ("CDAY", "2021-09-03", "2021-09-20", ""),
    ("MTCH", "2021-09-03", "2021-09-20", ""),
    ("SBNY", "2021-12-03", "2021-12-20", ""),
    ("SEDG", "2021-12-03", "2021-12-20", ""),
    ("FDS", "2021-12-03", "2021-12-20", ""),
    ("EPAM", "2021-12-07", "2021-12-14", ""),
    # ---- 2022 ----
    ("CEG", "2022-01-26", "2022-02-02", "spin-off (Exelon)"),
    ("NDSN", "2022-02-10", "2022-02-15", ""),
    ("MOH", "2022-02-25", "2022-03-02", ""),
    ("CPT", "2022-03-29", "2022-04-04", ""),
    ("WBD", "2022-04-07", "2022-04-11", "new-issuer merger successor; Discovery was not a constituent"),
    ("VICI", "2022-06-03", "2022-06-08", ""),
    ("ON", "2022-06-03", "2022-06-21", ""),
    ("KDP", "2022-06-03", "2022-06-21", ""),
    ("CSGP", "2022-09-02", "2022-09-19", ""),
    ("INVH", "2022-09-02", "2022-09-19", ""),
    ("EQT", "2022-09-23", "2022-10-03", ""),
    ("PCG", "2022-09-23", "2022-10-03", ""),
    ("TRGP", "2022-10-06", "2022-10-12", ""),
    ("ACGL", "2022-10-27", "2022-11-01", ""),
    ("FSLR", "2022-12-12", "2022-12-19", ""),
    ("STLD", "2022-12-19", "2022-12-22", ""),
    ("GEHC", "2022-12-28", "2023-01-04", "spin-off (GE); continuous bucket only — announced 2022"),
    # ---- 2023 (validation bucket) ----
    ("FICO", "2023-03-03", "2023-03-20", ""),
    ("PODD", "2023-03-10", "2023-03-15", ""),
    ("BG", "2023-03-13", "2023-03-15", ""),
    ("AXON", "2023-05-01", "2023-05-04", ""),
    ("PANW", "2023-06-02", "2023-06-20", ""),
    ("KVUE", "2023-08-21", "2023-08-25", "spin-off (J&J); Aug 21 release is the operative one (Aug 9 release was conditional, no date)"),
    ("BX", "2023-09-01", "2023-09-18", ""),
    ("ABNB", "2023-09-01", "2023-09-18", ""),
    ("VLTO", "2023-09-28", "2023-10-02", "spin-off (Danaher)"),
    ("LULU", "2023-10-13", "2023-10-18", ""),
    ("HUBB", "2023-10-13", "2023-10-18", ""),
    ("UBER", "2023-12-01", "2023-12-18", ""),
    ("JBL", "2023-12-01", "2023-12-18", ""),
    ("BLDR", "2023-12-01", "2023-12-18", ""),
    # ---- 2024 ----
    ("SMCI", "2024-03-01", "2024-03-18", ""),
    ("DECK", "2024-03-01", "2024-03-18", ""),
    ("SOLV", "2024-03-27", "2024-04-01", "spin-off (3M)"),
    ("GEV", "2024-03-27", "2024-04-02", "spin-off (GE)"),
    ("VST", "2024-05-03", "2024-05-08", ""),
    ("KKR", "2024-06-07", "2024-06-24", ""),
    ("CRWD", "2024-06-07", "2024-06-24", ""),
    ("GDDY", "2024-06-07", "2024-06-24", ""),
    ("PLTR", "2024-09-06", "2024-09-23", ""),
    ("DELL", "2024-09-06", "2024-09-23", ""),
    ("ERIE", "2024-09-06", "2024-09-23", ""),
    ("AMTM", "2024-09-24", "2024-09-30", "spin-off (Jacobs)"),
    ("TPL", "2024-11-21", "2024-11-26", ""),
    ("APO", "2024-12-06", "2024-12-23", ""),
    ("WDAY", "2024-12-06", "2024-12-23", ""),
    ("LII", "2024-12-18", "2024-12-23", ""),
    # ---- 2025 ----
    ("DASH", "2025-03-07", "2025-03-24", ""),
    ("TKO", "2025-03-07", "2025-03-24", ""),
    ("WSM", "2025-03-07", "2025-03-24", ""),
    ("EXE", "2025-03-07", "2025-03-24", ""),
    ("COIN", "2025-05-12", "2025-05-19", ""),
    ("DDOG", "2025-07-02", "2025-07-09", ""),
    ("TTD", "2025-07-14", "2025-07-18", ""),
    ("XYZ", "2025-07-18", "2025-07-23", ""),
    ("IBKR", "2025-08-25", "2025-08-28", ""),
    ("APP", "2025-09-05", "2025-09-22", ""),
    ("HOOD", "2025-09-05", "2025-09-22", ""),
    ("EME", "2025-09-05", "2025-09-22", ""),
    ("SOLS", "2025-10-27", "2025-10-30", "spin-off (DuPont)"),
    ("Q", "2025-10-27", "2025-11-03", "spin-off (DuPont); ticker is Q per the release"),
    ("SNDK", "2025-11-24", "2025-11-28", "spin-off (Western Digital)"),
    ("CRH", "2025-12-05", "2025-12-22", ""),
    ("CVNA", "2025-12-05", "2025-12-22", ""),
    ("FIX", "2025-12-05", "2025-12-22", ""),
    ("ARES", "2025-12-08", "2025-12-11", ""),
    # ---- 2026 ----
    ("CIEN", "2026-02-04", "2026-02-09", ""),
    ("VRT", "2026-03-06", "2026-03-23", ""),
    ("LITE", "2026-03-06", "2026-03-23", ""),
    ("COHR", "2026-03-06", "2026-03-23", ""),
    ("SATS", "2026-03-06", "2026-03-23", ""),
    ("CASY", "2026-04-06", "2026-04-09", ""),
    ("VEEV", "2026-04-30", "2026-05-07", ""),
    ("FDXF", "2026-05-27", "2026-06-01", "spin-off (FedEx)"),
    ("MRVL", "2026-06-05", "2026-06-22", ""),
    ("FLEX", "2026-06-05", "2026-06-22", ""),
    ("HONA", "2026-06-23", "2026-06-29", "spin-off (Honeywell)"),
    ("FERG", "2026-07-31", "2026-08-05", ""),
    ("RDDT", "2026-08-13", "2026-08-18", ""),
    ("BE", "2026-09-04", "2026-09-21", ""),
    ("ILMN", "2026-09-04", "2026-09-21", ""),
    ("P", "2026-09-04", "2026-09-21", "announced as Pure Storage (PSTG); renamed Everpure, ticker P, with the rebalance"),
    ("TWLO", "2026-10-01", "2026-10-06", ""),
    ("OKTA", "2026-10-30", "2026-11-04", ""),
]

# Excluded after verification (documented, never traded):
EXCLUDED_EVENTS = [
    ("SW", "2024-07-08 effective", "No S&P DJI announcement release exists in the free PR Newswire archive and no announcement date is verifiable from any free source; addition was effective on the successor's first trading day. Excluded rather than assigned an invented date (forced reading 10)."),
    ("VYLR", "2026-10-01", "Excluded on two grounds: (1) the only S&P DJI release is dated 2026-10-01 and describes the addition in the past tense, so the announcement did not precede the effective date and the spec's trade is impossible; (2) VYLR is the accounting successor carrying Corteva's membership forward — a continuation, not an addition."),
]
# Renamed continuations excluded by forced reading 9 (same legal issuer):
RENAMES_EXCLUDED = ["BKR (BHGE)", "PEAK (HCP)", "NLOK (SYMC)", "HWM (Arconic)",
                    "LUMN (CTL)", "BBWI (LB)", "WTW (WLTW)", "PARA (VIAC)",
                    "BALL (BLL)", "META (FB)", "ELV (ANTM)", "FI (FISV)",
                    "EG (RE)", "COR (ABC)", "DAY (CDAY)", "DOC (PEAK)",
                    "CPAY (FLT)", "GEN (NLOK)", "RVTY (PKI)", "J (JEC)",
                    "TFC (BBT)", "GL (TMK)", "LHX (HRS)", "VTRS (MYL)",
                    "RTX (UTX)", "CTRA (COG)", "FOXA (Fox Corp continuation)"]

# ------------------------------------------------------------ price loading
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def parse_yahoo(blob):
    """Champion's bar construction: open scaled by adjclose/close, close =
    adjclose. Returns list of {d, o, c} sorted by date."""
    j = json.loads(blob)
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

def get_prices(ticker, p1="2018-06-01", p2="2026-11-21"):
    """Cache order: ./data (fresh fetches land here), then v4/data, then the
    v5 cache — the older caches are read-only and reused verbatim."""
    for base in (DATA, V4DATA, V5CACHE):
        path = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                return parse_yahoo(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch(url, os.path.join(DATA, f"px_{ticker}.json"),
                 headers={"User-Agent": "Mozilla/5.0"})
    time.sleep(0.3)
    return parse_yahoo(blob)

class PriceBook:
    """Champion's PriceBook, verbatim semantics."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

    def first_bar_after(self, t, d):
        """(index, bar) of first bar strictly after date d, else (None, None)."""
        for i, b in enumerate(self.bars.get(t, [])):
            if b["d"] > d:
                return i, b
        return None, None

    def bar_on_or_before(self, t, d):
        """(index, bar) of last bar on or before d, else (None, None)."""
        best_i, best = None, None
        for i, b in enumerate(self.bars.get(t, [])):
            if b["d"] <= d:
                best_i, best = i, b
            else:
                break
        return best_i, best

# ------------------------------------------------------------ pot engine
def run_event_pot(pb, trades, start, end, start_cash=START_CASH,
                  floor=FLOOR, cost_mult=1.0, label=""):
    """Generic event pot. trades: list of dicts {key, ticker, entry_date,
    exit_date} where entry/exit dates are actual bar dates of the ticker.
    Mechanics per forced reading 5: entries rebalance the whole pot to
    equal weights across open events at that day's open (sells first,
    then buys; champion's cost model x cost_mult); exits sell the full
    position at the exit day's close; floor check on the daily close;
    halt liquidates at the next day's open (champion semantics); any
    position still open at the window end is liquidated at the final
    close with the standard sell cost."""
    buy_rate = 0.001 * cost_mult
    sell_rate = 0.001 * cost_mult
    sell_fee = 0.01 * cost_mult
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    entries = {}
    exits = {}
    for tr in trades:
        entries.setdefault(tr["entry_date"], []).append(tr)
        exits.setdefault(tr["exit_date"], []).append(tr)
    cash = start_cash
    positions = {}          # key -> (ticker, shares)
    open_keys = []          # keys currently open (entered, not yet exited)
    fills = []
    total_costs = 0.0
    curve = []
    halted = None
    halt_info = None

    def close_value(d):
        v = cash
        for k, (t, sh) in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    for di, d in enumerate(days):
        # ---- entries at the open: rebalance to equal weights
        new = [tr for tr in entries.get(d, []) if tr["key"] not in open_keys]
        if new:
            for tr in new:
                open_keys.append(tr["key"])
                positions.setdefault(tr["key"], (tr["ticker"], 0.0))
            # pot value at today's opens (no-bar names at last close)
            pv = cash
            opens = {}
            for k in open_keys:
                t, sh = positions[k]
                b = pb.bar(t, d)
                if b:
                    opens[k] = b["o"]
                    pv += sh * b["o"]
                else:
                    c = pb.close_on_or_before(t, d)
                    if c:
                        pv += sh * c
            n = len(open_keys)
            target = pv / n if n else 0.0
            # sells / trims first
            for k in list(open_keys):
                if k not in opens:
                    continue
                t, sh = positions[k]
                cur = sh * opens[k]
                if cur > target + 0.005:
                    sell_val = cur - target
                    ssh = sell_val / opens[k]
                    c = sell_val * sell_rate + sell_fee
                    cash += sell_val - c
                    total_costs += c
                    sh -= ssh
                    fills.append((d, t, "SELL", ssh, opens[k], sell_val, c))
                    if sh < 1e-9:
                        positions[k] = (t, 0.0)
                    else:
                        positions[k] = (t, sh)
            # then buys
            for k in list(open_keys):
                if k not in opens:
                    continue
                t, sh = positions[k]
                cur = sh * opens[k]
                buy_val = target - cur
                if buy_val > 0.005:
                    buy_val = min(buy_val, cash / (1.0 + buy_rate))
                    if buy_val <= 0.005:
                        continue
                    bsh = buy_val / opens[k]
                    c = buy_val * buy_rate
                    cash -= buy_val + c
                    total_costs += c
                    positions[k] = (t, sh + bsh)
                    fills.append((d, t, "BUY", bsh, opens[k], buy_val, c))
        # ---- exits at the close
        for tr in exits.get(d, []):
            k = tr["key"]
            if k in positions:
                t, sh = positions[k]
                if sh > 1e-9:
                    c_ = pb.bar(t, d)["c"] if pb.bar(t, d) else pb.close_on_or_before(t, d)
                    val = sh * c_
                    cst = val * sell_rate + sell_fee
                    cash += val - cst
                    total_costs += cst
                    fills.append((d, t, "SELL-EXIT", sh, c_, val, cst))
                del positions[k]
            if k in open_keys:
                open_keys.remove(k)
        # ---- floor check on the close
        v = close_value(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for k in list(positions):
                t, sh = positions[k]
                b = pb.bar(t, nd)
                if b and sh > 1e-9:
                    val = sh * b["o"]
                    cst = val * sell_rate + sell_fee
                    cash += val - cst
                    total_costs += cst
                    fills.append((nd, t, "SELL-HALT", sh, b["o"], val, cst))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "fills": fills, "n_fills": len(fills), "halted": halted,
                    "end": nd, "halt_info": halt_info, "curve": curve}
    # ---- end of window: liquidate at final close
    last = days[-1]
    for k in list(positions):
        t, sh = positions[k]
        if sh > 1e-9:
            c_ = pb.close_on_or_before(t, last)
            if c_:
                val = sh * c_
                cst = val * sell_rate + sell_fee
                cash += val - cst
                total_costs += cst
                fills.append((last, t, "SELL-END", sh, c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "fills": fills, "n_fills": len(fills), "halted": None,
            "end": last, "halt_info": None, "curve": curve}

def spy_net(pb, start, end, start_cash=START_CASH):
    """Champion's spy_net, verbatim."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd

def year_end_closes(curve):
    out = {}
    for d, v in curve:
        out[d[:4]] = round(v, 2)
    return out

def _pct(sorted_vals, q):
    """Champion's percentile (linear interpolation)."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)

# ------------------------------------------------------- trade building
def build_event_trades(pb):
    """Resolve every harvested event into an actual trade (or an exclusion
    with a stated reason) under forced readings 2-3."""
    resolved, excluded = [], []
    for ticker, ann, eff, note in EVENTS:
        key = f"{ticker}@{ann}"
        bars = pb.bars.get(ticker, [])
        if not bars:
            excluded.append({"ticker": ticker, "ann": ann, "eff": eff,
                             "reason": "no usable Yahoo price series"})
            continue
        ei, eb = pb.first_bar_after(ticker, ann)
        if eb is None:
            excluded.append({"ticker": ticker, "ann": ann, "eff": eff,
                             "reason": "no price bar after the announcement date"})
            continue
        if eb["d"] > eff:
            excluded.append({"ticker": ticker, "ann": ann, "eff": eff,
                             "reason": f"first available bar {eb['d']} falls after the effective date — untradeable under the spec (forced reading 2)"})
            continue
        xi, xb = pb.bar_on_or_before(ticker, eff)
        if xb is None or xi < ei:
            excluded.append({"ticker": ticker, "ann": ann, "eff": eff,
                             "reason": "no price bar on or before the effective date"})
            continue
        entry_o, exit_c = eb["o"], xb["c"]
        gross = exit_c / entry_o - 1.0
        sh = (100.0 / 1.001) / entry_o
        proceeds = sh * exit_c
        net_final = proceeds - (proceeds * 0.001 + 0.01)
        net = net_final / 100.0 - 1.0
        resolved.append({
            "key": key, "ticker": ticker, "ann": ann, "eff": eff,
            "note": note, "entry_date": eb["d"], "entry_open": entry_o,
            "exit_date": xb["d"], "exit_close": exit_c,
            "exit_on_effective": xb["d"] == eff,
            "hold_len": xi - ei, "gross_ret": gross, "net_ret": net,
        })
    return resolved, excluded

def placebo_late_trades(pb, resolved):
    """Placebo (i): same names, entry 20 trading days after the effective-
    date bar, held the same number of days (forced reading 7)."""
    trades, skipped = [], 0
    for ev in resolved:
        bars = pb.bars.get(ev["ticker"], [])
        xi, _ = pb.bar_on_or_before(ev["ticker"], ev["eff"])
        ei2 = xi + 20
        xi2 = ei2 + ev["hold_len"]
        if ei2 >= len(bars) or xi2 >= len(bars):
            skipped += 1
            continue
        trades.append({"key": ev["key"] + "|late", "ticker": ev["ticker"],
                       "ann": ev["ann"],
                       "entry_date": bars[ei2]["d"], "exit_date": bars[xi2]["d"]})
    return trades, skipped

def placebo_random_trades(pb, resolved, seed):
    """Placebo (ii): one random honest-top-30 name per event, entered on
    the same announcement schedule with the same hold length."""
    rng = random.Random(seed)
    pool = sorted(UNIVERSE)
    trades, skipped = [], 0
    for ev in sorted(resolved, key=lambda e: (e["ann"], e["ticker"])):
        t = rng.choice(pool)
        bars = pb.bars.get(t, [])
        ei, eb = pb.first_bar_after(t, ev["ann"])
        if eb is None:
            skipped += 1
            continue
        xi = ei + ev["hold_len"]
        if xi >= len(bars):
            skipped += 1
            continue
        trades.append({"key": f"{ev['key']}|s{seed}:{t}", "ticker": t,
                       "ann": ev["ann"],
                       "entry_date": eb["d"], "exit_date": bars[xi]["d"]})
    return trades, skipped

# --------------------------------------------------------- design count
def design_period_count():
    """Count additions announced 2016-11-21 -> 2018-12-31 from the
    point-in-time baseline snapshots (forced reading 12)."""
    path = os.path.join(DATA, "sp500_historical_baseline.csv")
    rows = []
    with open(path, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        for row in rdr:
            if not row:
                continue
            d = row[0].strip()
            ticks = set()
            for cell in row[1:]:
                for t in cell.split(","):
                    t = t.strip().strip('"')
                    if t:
                        ticks.add(re.sub(r"-\d{6}$", "", t))
            rows.append((d, ticks))
    rows.sort()
    additions = []
    for i in range(1, len(rows)):
        d, cur = rows[i]
        prev = rows[i - 1][1]
        for t in sorted(cur - prev):
            additions.append((d, t))
    lo, hi = "2016-11-21", "2018-12-31"
    in_window = [(d, t) for d, t in additions if lo <= d <= hi]
    return {"snapshot_diff_count": len(in_window),
            "with_frc_announcement_adjustment": len(in_window) + 1,
            "additions": [{"snapshot_date": d, "ticker": t} for d, t in in_window],
            "method": "First appearance in consecutive daily constituent snapshots "
                      "(fja05680/sp500 'S&P 500 Historical Components & Changes.csv'); "
                      "snapshot date ~= effective date. +1 manual adjustment for FRC "
                      "(announced 2018-12-27, effective 2019-01-02 — design bucket by "
                      "announcement date). Rename pairs (a constituent continuing under "
                      "a new ticker) appear as add+remove pairs in raw diffs and inflate "
                      "the raw count; count only, per spec."}

# ------------------------------------------------------------------ main
def load_series():
    notes = {}
    tickers = sorted({t for t, _, _, _ in EVENTS} | set(UNIVERSE) | {"SPY"})
    bars = {}
    for t in tickers:
        if t in ("IR", "P"):
            continue  # special handling below
        try:
            bars[t] = get_prices(t)
        except Exception as e:  # noqa
            print(f"  [load] {t}: FAILED ({e})", flush=True)
            bars[t] = []
    # --- IR: announced as GDI; GDI renamed itself IR on 2020-03-02 (1:1).
    try:
        gdi = get_prices("GDI")
    except Exception:  # noqa
        gdi = []
    try:
        ir = get_prices("IR")
    except Exception:  # noqa
        ir = []
    if gdi and ir:
        gmap = {b["d"]: b["c"] for b in gdi}
        overlap = [(d, c) for d, c in ((b["d"], b["c"]) for b in ir) if d in gmap]
        maxrel = 0.0
        for d, c in overlap:
            if gmap[d]:
                maxrel = max(maxrel, abs(c - gmap[d]) / gmap[d])
        if overlap and maxrel < 0.005:
            bars["IR"] = ir
            notes["IR"] = (f"Yahoo's IR series carries the pre-rename GDI history "
                           f"(rename backfill): {len(overlap)} overlapping bars, max "
                           f"close difference {maxrel:.4%}. IR series used alone.")
        else:
            merged = {b["d"]: b for b in gdi if b["d"] <= "2020-03-02"}
            for b in ir:
                if b["d"] >= "2020-03-03":
                    merged[b["d"]] = b
            bars["IR"] = sorted(merged.values(), key=lambda b: b["d"])
            notes["IR"] = (f"IR and GDI series stitched at the 2020-03-02 rename "
                           f"(GDI bars through 2020-03-02, IR bars from 2020-03-03; "
                           f"overlap max close difference {maxrel:.4%} over "
                           f"{len(overlap)} bars). 1:1 rename — no ratio applied.")
    elif ir:
        bars["IR"] = ir
        notes["IR"] = "GDI series unavailable; IR series used alone."
    elif gdi:
        bars["IR"] = gdi
        notes["IR"] = "IR series unavailable; GDI series used alone (exit will fail if no bar covers 2020-03-03)."
    else:
        bars["IR"] = []
        notes["IR"] = "Neither IR nor GDI series available."
    # --- P: announced as Pure Storage (PSTG), renamed Everpure (P) with the
    # rebalance. Use whichever series actually trades in the event window.
    try:
        p_bars = get_prices("P")
    except Exception:  # noqa
        p_bars = []
    p_in_window = [b for b in p_bars if "2026-09-04" <= b["d"] <= "2026-10-06"]
    if p_in_window:
        bars["P"] = p_bars
        notes["P"] = "Yahoo's P series trades in the event window (Everpure); used directly."
    else:
        try:
            pstg = get_prices("PSTG")
        except Exception:  # noqa
            pstg = []
        if [b for b in pstg if "2026-09-04" <= b["d"] <= "2026-10-06"]:
            bars["P"] = pstg
            notes["P"] = "Yahoo's P series has no bars in the event window; PSTG series used (same listing, pre-rename ticker)."
        else:
            bars["P"] = p_bars
            notes["P"] = "Neither P nor PSTG has bars in the event window; P series kept (event will be excluded by the machinery if untradeable)."
    return bars, notes

def pot_summary(res):
    if res is None:
        return None
    return {"final": round(res["final"], 2), "costs": round(res["costs"], 2),
            "n_fills": res["n_fills"], "halted": res["halted"],
            "halt_info": res["halt_info"],
            "max_drawdown_pct": round(max_dd(res["curve"]) * 100, 2),
            "worst_close": round(min(v for _, v in res["curve"]), 2),
            "year_end_closes": year_end_closes(res["curve"])}

def event_stats(evs):
    if not evs:
        return {"n": 0}
    nets = sorted(e["net_ret"] for e in evs)
    gross = sorted(e["gross_ret"] for e in evs)
    return {"n": len(evs),
            "mean_net_ret_pct": round(sum(nets) / len(nets) * 100, 3),
            "median_net_ret_pct": round(nets[len(nets) // 2] * 100, 3),
            "mean_gross_ret_pct": round(sum(gross) / len(gross) * 100, 3),
            "median_gross_ret_pct": round(gross[len(gross) // 2] * 100, 3),
            "net_wins": sum(1 for x in nets if x > 0),
            "best_net_pct": round(nets[-1] * 100, 2),
            "worst_net_pct": round(nets[0] * 100, 2),
            "mean_hold_days": round(sum(e["hold_len"] for e in evs) / len(evs), 1)}

def main():
    print("INDEX ADDITIONS — spec 4.1 — simulation only", flush=True)
    bars, series_notes = load_series()
    for k, v in series_notes.items():
        print(f"  [series] {k}: {v}", flush=True)
    empty = [t for t, bl in bars.items() if not bl]
    if empty:
        print(f"  [load] tickers with NO usable series: {empty}", flush=True)
    pb = PriceBook(bars)
    resolved, excluded = build_event_trades(pb)
    print(f"  events harvested: {len(EVENTS)}; resolved: {len(resolved)}; "
          f"excluded: {len(excluded)}", flush=True)
    for ex in excluded:
        print(f"  [excluded] {ex['ticker']} ann {ex['ann']}: {ex['reason']}", flush=True)

    windows = {"continuous": ("2019-01-02", "2026-11-20"),
               "validation": ("2023-01-03", "2026-11-20")}
    out = {"spec": "firm-reverse-engineering.md section 4.1 (index additions)",
           "series_notes": series_notes,
           "events_harvested": len(EVENTS),
           "events_resolved": len(resolved),
           "excluded_after_harvest": excluded,
           "excluded_documented": [{"ticker": t, "when": w, "reason": r}
                                   for t, w, r in EXCLUDED_EVENTS],
           "renames_excluded": RENAMES_EXCLUDED,
           "windows": {}}
    for wname, (ws, we) in windows.items():
        if wname == "continuous":
            evs = [e for e in resolved if e["ann"] >= "2019-01-01"]
        else:
            evs = [e for e in resolved if e["ann"] >= "2023-01-01"]
        trades = [{"key": e["key"], "ticker": e["ticker"], "ann": e["ann"],
                   "entry_date": e["entry_date"], "exit_date": e["exit_date"]}
                  for e in evs]
        ranked = run_event_pot(pb, trades, ws, we, label=f"{wname}-ranked")
        stress = run_event_pot(pb, trades, ws, we, cost_mult=2.0,
                               label=f"{wname}-ranked-2x")
        spy_final, spy_costs = spy_net(pb, ws, we)
        late_trades_all, late_skipped = placebo_late_trades(pb, resolved)
        late_trades = [t for t in late_trades_all
                       if (t["ann"] >= "2019-01-01" if wname == "continuous"
                           else t["ann"] >= "2023-01-01")]
        late = run_event_pot(pb, late_trades, ws, we, label=f"{wname}-placebo-late")
        seed_finals, seed_runs, seed_skipped = [], [], 0
        for s in PLACEBO_SEEDS:
            strades_all, sk = placebo_random_trades(pb, resolved, s)
            seed_skipped += sk
            strades = [t for t in strades_all
                       if (t["ann"] >= "2019-01-01" if wname == "continuous"
                           else t["ann"] >= "2023-01-01")]
            r = run_event_pot(pb, strades, ws, we, label=f"{wname}-placebo-s{s}")
            seed_finals.append(round(r["final"], 2))
            seed_runs.append(pot_summary(r))
        beaten = sum(1 for f in seed_finals if ranked["final"] > f)
        srt = sorted(seed_finals)
        w = {"window": [ws, we], "n_events": len(evs),
             "event_stats": event_stats(evs),
             "ranked": pot_summary(ranked),
             "ranked_curve": [[d, round(v, 2)] for d, v in ranked["curve"]],
             "ranked_2x_costs": pot_summary(stress),
             "spy_net": {"final": round(spy_final, 2),
                         "costs": round(spy_costs, 2)},
             "placebo_late": pot_summary(late),
             "placebo_late_skipped_trades": late_skipped,
             "placebo_random": {
                 "seed_finals": seed_finals,
                 "median": round(srt[len(srt) // 2], 2),
                 "p25": round(_pct(srt, 0.25), 2),
                 "p75": round(_pct(srt, 0.75), 2),
                 "best": srt[-1], "worst": srt[0],
                 "ranked_beats": beaten,
                 "skipped_trades_total": seed_skipped,
                 "runs": seed_runs},
             "events": evs}
        # percentile of ranked among the 20 seeds (share of seeds below it)
        w["placebo_random"]["ranked_percentile"] = round(beaten / 20 * 100, 1)
        out["windows"][wname] = w
        print(f"  [{wname}] events={len(evs)} ranked=${ranked['final']:.2f} "
              f"(2x ${stress['final']:.2f}) SPY=${spy_final:.2f} "
              f"placebo-late=${late['final']:.2f} placebo-random median="
              f"${srt[len(srt)//2]:.2f} beaten={beaten}/20 "
              f"mean-net={w['event_stats'].get('mean_net_ret_pct')}%", flush=True)

    # ---- winning years (reporting only): fresh $100 pot per calendar year
    years = {}
    for y in range(2019, 2027):
        ydays = [d for d in pb.dates if f"{y}-01-01" <= d <= f"{y}-12-31"]
        if not ydays:
            continue
        ys, ye = ydays[0], ydays[-1]
        evs = [e for e in resolved if e["ann"][:4] == str(y)]
        trades = [{"key": e["key"], "ticker": e["ticker"], "ann": e["ann"],
                   "entry_date": e["entry_date"], "exit_date": e["exit_date"]}
                  for e in evs]
        r = run_event_pot(pb, trades, ys, ye, label=f"year-{y}")
        sf, _ = spy_net(pb, ys, ye)
        years[str(y)] = {"window": [ys, ye], "n_events": len(evs),
                         "ranked_final": round(r["final"], 2),
                         "halted": r["halted"],
                         "spy_net_final": round(sf, 2),
                         "beat_spy": r["final"] > sf}
        print(f"  [year {y}] events={len(evs)} ranked=${r['final']:.2f} "
              f"SPY=${sf:.2f} {'WIN' if r['final'] > sf else 'loss'}", flush=True)
    out["winning_years"] = years
    wins = sum(1 for v in years.values() if v["beat_spy"])
    out["winning_years_score"] = f"{wins}/{len(years)}"

    out["design_period"] = design_period_count()
    print(f"  [design] snapshot-diff additions 2016-11-21..2018-12-31: "
          f"{out['design_period']['snapshot_diff_count']} "
          f"(+FRC = {out['design_period']['with_frc_announcement_adjustment']})",
          flush=True)

    # ---- the pre-registered gate, judged on validation
    v = out["windows"]["validation"]
    gate = {"mean_event_net_positive": v["event_stats"]["mean_net_ret_pct"] > 0,
            "beats_18_of_20_placebos": v["placebo_random"]["ranked_beats"] >= 18,
            "beats_spy": v["ranked"]["final"] > v["spy_net"]["final"]}
    gate["spec_gate_passed"] = (gate["mean_event_net_positive"]
                                and gate["beats_18_of_20_placebos"])
    gate["promotion_bar_passed"] = (gate["spec_gate_passed"] and gate["beats_spy"])
    out["gate_validation"] = gate
    print(f"  [GATE] {gate}", flush=True)

    with open(os.path.join(HERE, "re-index-additions-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE re-index-additions-results.json", flush=True)

if __name__ == "__main__":
    main()
