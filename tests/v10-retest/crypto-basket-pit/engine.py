#!/usr/bin/env python3
"""
MOMENTUM BASKET ON CRYPTO, UN-RIGGED (point-in-time universe) — Terry's
AI stock app, simulation only.

The first crypto basket test (crypto-basket.py) used a universe of 20
coins chosen TODAY that survived 2020 -> 2026 — survivorship-flattered
by construction, and Terry has banned rigged tests. This re-test builds
the universe the honest way, per the crypto evidence audit
(~/workspace/stock-app/research/crypto-evidence.md §5):

  UNIVERSE = the top 20 coins by market cap from CoinMarketCap's free
  WEEKLY HISTORICAL SNAPSHOTS (published since Apr 2013), using the
  most recent snapshot on/before each monthly selection date. Coins
  that later died (LUNA, UST, BitConnect-era names) are IN the universe
  for the months they were actually top-20. Snapshots were scraped
  2026-11-21 into crypto-basket-pit-data/snapshots.json (119 monthly
  selections, 97 distinct coins ever in a monthly top-20).

RULE — identical architecture to the stock basket
(momentum-basket-honest.py) and the first crypto test:
  Monthly selection on the 1st of the month, signals from the prior
  day's close (no look-ahead):
    - Universe: that month's snapshot top-20 (point-in-time).
    - Eligible: close above its own 200-day simple moving average,
      with a computable 12-1 momentum (calendar-day translation as in
      the first crypto test: close[t-30]/close[t-365]-1), fresh data
      (a real bar within the last 7 days), and >=300 real bars of
      history.
    - Rank eligible by 12-1 momentum; hold TOP 5 at 20% of pot equity
      each; fewer eligible -> hold what's eligible, rest cash.
    - Rebalance at the selection day's open. Full compounding.
  Pot $100. Costs 0.40%/side (documented US retail, per the audit —
  the first crypto test used 0.25%; this brief mandates 0.40%).

DEATH RULE (the point of this test): prices come from free sources
(Yahoo Finance; Binance Vision archives for coins Yahoo lacks or
delisted). When a held coin's price series ENDS (collapse/delisting),
the position is valued at its last close for a 30-calendar-day grace
period, then written to ZERO while the shares remain on the books
(if the series ever resumes, value returns — a documented
"resurrection"; none are expected). A coin with no tradeable price at
a rebalance cannot be sold; a written-off position exits at $0.
Every write-off, and every exit at >=90% below its entry price, is
logged as a death/collapse event with its dollar cost to the pot.

PROTECTION: primary runs carry NO -15% floor (the first crypto test
and the audit both showed a -15% floor is incompatible with crypto —
it liquidates in ordinary corrections). One diagnostic run (ranked,
full window) applies the plain $85 floor for the record.

WINDOWS: FULL 2017-01-01 -> 2026-11-20; DESIGN 2017-01-01 ->
2022-12-31; VALIDATION 2023-01-01 -> 2026-11-20 (fresh $100 pots).
DATA REALITY (stated, not hidden): Yahoo's altcoin history begins
2017-11-09 for nearly every alt (BTC: Sep 2014), so until late 2018
the only coin that can satisfy the 365-day momentum lookback is BTC —
the pot is BTC/cash-only in 2017-18 by data necessity, and the
diversified basket effectively starts Nov 2018.

BENCHMARK: BTC buy-and-hold, net of the same 0.40%/side costs.
PLACEBO: random 5 eligible from the same point-in-time universe, same
machinery, 20 seeds, FULL + VALIDATION, no floor.

COIN -> PRICE SOURCE MAP (keyed by CoinMarketCap id, the stable key;
symbol collisions make symbol-keying unsafe — e.g. Yahoo's TON-USD is
a dead unrelated token, Yahoo's SKY-USD is Skycoin not Maker's SKY,
Yahoo's M-USD is not MemeCore):
  4172 LUNA (original Terra) -> Yahoo LUNC-USD (carries the full
       original history incl. the May 2022 collapse to ~$0.0001).
  7129 UST -> Yahoo USTC-USD (full history incl. depeg).
  1720 MIOTA -> Binance IOTAUSDT (Yahoo IOTA-USD history only starts
       Sep 2023 — wrong era).
  3890 MATIC -> Binance MATICUSDT; 28321 POL -> Binance POLUSDT
       (Yahoo delisted both tickers).
  24478 PEPE -> Binance PEPEUSDT; 29470 USDe -> Binance USDEUSDT;
  36148 USD1 -> Binance USD1USDT (none exist on Yahoo).
  7083 UNI -> Binance UNIUSDT; 20947 SUI -> Binance SUIUSDT (the
       Yahoo chart API returns no data for UNI-USD / SUI-USD).
  11419 TON (Toncoin) -> Kraken TONUSD REST (Dec 2024 -> now; Binance
       Vision's TONUSDT monthly files stop after 2026-06, and Yahoo
       TON-USD is a different, dead token — NOT used). TON's 2023-24
       top-20 months are therefore data-unreachable; it can only
       become eligible from Dec 2025.
  32196 HYPE -> Bybit HYPEUSDT if retrievable, else excluded.
  2280 FIL -> Yahoo FIL-USD with credible start 2020-10-15 (Yahoo
       carries pre-mainnet phantom bars from Dec 2017; not credible
       traded prices — same call as the first crypto test).
  EXCLUDED as unobtainable on free sources, logged in the report:
       1513 BCC BitConnect (no Yahoo/Binance/Kraken series exists),
       291 MAID, 1408 ICN, 1087 FCT, 576 GAME, 1229 DGD, 1343 STRAT
       (Yahoo carries only 1-bar stubs), 1904 VEN (no series; and it
       could never be eligible — launched Aug 2017, swapped to VET
       Jul 2018, inside its own 365-day lookback), 1455 GNT (Yahoo
       series is a corrupted wrong-era stub), 35491 M MemeCore
       (Yahoo M-USD is a different token), 37263 CC Canton (no free
       series; launched Nov 2025, could not be eligible before the
       final month anyway), plus any tail coin whose generic
       {symbol}-USD Yahoo series has <60 bars.
  Everything else -> Yahoo {symbol}-USD.

Token migrations handled by the data itself: Yahoo continued EOS-USD
through the Vaulta rebrand and RENDER-USD carries Render's full
history; MATIC->POL and the LUNA/LUNC split are separate CMC ids and
are treated as the separate assets the market treated them as (a held
MATIC position whose Binance series ends at the Sep 2024 migration is
subject to the death rule — flagged in the report if it occurs; in
practice MATIC must still be snapshot-top-20 AND selected that month
for this to bind).
"""

import csv
import io
import json
import math
import os
import random
import time
import zipfile
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "v4"))
CACHE = os.path.join(ORIG_DIR, "crypto-basket-pit-data")  # original cache, read-only
os.makedirs(CACHE, exist_ok=True)

COST_RATE = 0.004                 # 0.40% per side (US retail, per audit)
SELL_FEE = 0.0
SMA_N = 200
MOM_FAR = 365
MOM_NEAR = 30
GRACE_DAYS = 30                   # death rule: last close held 30d, then $0
POT = 100

WINDOWS = {
    "full":       ("2017-01-01", "2026-11-20"),
    "design":     ("2017-01-01", "2022-12-31"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))

# ---------------------------------------------------------------------------
# Coin registry: cmc_id -> price source
#   ("yahoo", ticker) | ("binance", pair, first_month) |
#   ("bybit", symbol)   | ("excluded", reason)
# ---------------------------------------------------------------------------
BINANCE_MAP = {
    1720:  ("IOTAUSDT", "2017-11"),
    3890:  ("MATICUSDT", "2019-04"),
    28321: ("POLUSDT", "2024-09"),
    24478: ("PEPEUSDT", "2023-05"),
    29470: ("USDEUSDT", "2023-12"),
    36148: ("USD1USDT", "2025-05"),
    7083:  ("UNIUSDT", "2020-09"),    # Yahoo chart API returns no UNI-USD
    20947: ("SUIUSDT", "2023-05"),    # Yahoo chart API returns no SUI-USD
}
KRAKEN_MAP = {
    11419: "TONUSD",   # Toncoin: Binance Vision monthly files stop after
                       # 2026-06; Kraken REST gives Dec 2024 -> now (720
                       # daily candles). Yahoo TON-USD is a different,
                       # dead token and is NOT used.
}
YAHOO_MAP = {
    4172: "LUNC-USD",     # original Terra — full history incl. collapse
    7129: "USTC-USD",     # TerraUSD — full history incl. depeg
    2280: "FIL-USD",      # credible start applied below
}
EXCLUDED = {
    1513: "BitConnect: no price series on any free source (Yahoo BCC-USD delisted/absent; never on Binance/Kraken)",
    291:  "MaidSafeCoin: Yahoo carries a 1-bar stub only",
    1408: "Iconomi: Yahoo carries a 1-bar stub only",
    1087: "Factom: Yahoo carries a 1-bar stub only",
    576:  "GameCredits: Yahoo carries a 1-bar stub only",
    1229: "DigixDAO: Yahoo carries a 1-bar stub only",
    1343: "Stratis: Yahoo carries a 1-bar stub only",
    1904: "VeChain (VEN): no free series; also never eligible (launched Aug 2017, swapped to VET Jul 2018, inside its 365d lookback)",
    1455: "Golem (GNT): Yahoo series is a corrupted wrong-era stub (starts 2021 at ~$0.0001)",
    35491: "MemeCore (M): Yahoo M-USD is a different, dead token",
    37263: "Canton (CC): no free series; launched Nov 2025, could not satisfy the 365d lookback before the final month anyway",
    32196: "Hyperliquid (HYPE): no Yahoo/Binance spot series (see bybit attempt in code)",
}
CREDIBLE_START = {
    2280: "2020-10-15",    # FIL mainnet launch (Yahoo has 2017 phantom bars)
    11841: "2023-03-23",   # ARB token launch (Yahoo ARB-USD carries a
                           # different asset's history back to 2017)
    22861: "2023-10-31",   # TIA (Celestia) launch (Yahoo TIA-USD carries
                           # a different asset's history back to 2022)
}

UA = {"User-Agent": "Mozilla/5.0"}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_yahoo(ticker):
    path = os.path.join(CACHE, f"y_{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    rows = []
    try:
        r = requests.get(url, headers=UA, timeout=30)
        res = r.json()["chart"]["result"]
        if res:
            ts = res[0]["timestamp"]
            q = res[0]["indicators"]["quote"][0]
            for i, t in enumerate(ts):
                o, c = q["open"][i], q["close"][i]
                if o is None or c is None or c <= 0:
                    continue
                d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({"d": d, "o": float(o), "c": float(c)})
    except Exception:
        rows = []
    with open(path, "w") as f:
        json.dump(rows, f)
    time.sleep(0.2)
    return rows


def fetch_binance(pair, first_month):
    path = os.path.join(CACHE, f"b_{pair}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows_by_date = {}
    y, m = int(first_month[:4]), int(first_month[5:7])
    while (y, m) <= (2026, 11):
        ym = f"{y:04d}-{m:02d}"
        url = (f"https://data.binance.vision/data/spot/monthly/klines/"
               f"{pair}/1d/{pair}-1d-{ym}.zip")
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                for name in z.namelist():
                    if not name.endswith(".csv"):
                        continue
                    rd = csv.reader(io.TextIOWrapper(z.open(name)))
                    for parts in rd:
                        if not parts or not parts[0].strip().isdigit():
                            continue        # header row in newer files
                        tms = int(parts[0])
                        if tms > 10**14:    # microseconds in newer files
                            tms //= 1000
                        d = datetime.fromtimestamp(
                            tms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                        o, c = float(parts[1]), float(parts[4])
                        if c > 0:
                            rows_by_date[d] = {"d": d, "o": o, "c": c}
        except Exception:
            pass
        m += 1
        if m == 13:
            y, m = y + 1, 1
        time.sleep(0.05)
    rows = [rows_by_date[d] for d in sorted(rows_by_date)]
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_kraken(pair):
    path = os.path.join(CACHE, f"k_{pair}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows = []
    try:
        r = requests.get("https://api.kraken.com/0/public/OHLC"
                         f"?pair={pair}&interval=1440",
                         headers=UA, timeout=30)
        j = r.json()
        if not j.get("error"):
            key = [x for x in j["result"] if x != "last"][0]
            for x in j["result"][key]:
                d = datetime.fromtimestamp(int(x[0]),
                                           tz=timezone.utc).strftime("%Y-%m-%d")
                o, c = float(x[1]), float(x[4])
                if c > 0:
                    rows.append({"d": d, "o": o, "c": c})
            rows.sort(key=lambda r: r["d"])
    except Exception:
        rows = []
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_bybit(symbol):
    path = os.path.join(CACHE, f"bb_{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows = []
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/kline"
            f"?category=spot&symbol={symbol}&interval=D&limit=1000",
            headers=UA, timeout=30)
        lst = r.json()["result"]["list"]
        for x in lst:
            d = datetime.fromtimestamp(int(x[0]) / 1000,
                                       tz=timezone.utc).strftime("%Y-%m-%d")
            o, c = float(x[1]), float(x[4])
            if c > 0:
                rows.append({"d": d, "o": o, "c": c})
        rows.sort(key=lambda r: r["d"])
    except Exception:
        rows = []
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def load_snapshots():
    with open(os.path.join(CACHE, "snapshots.json")) as f:
        return json.load(f)


def build_registry(snaps):
    """cmc_id -> {symbol, slug, source, rows} for every coin that ever
    appeared in a monthly top-20. Excluded coins get source='excluded'
    and a reason (from EXCLUDED or auto-detected)."""
    coins = {}
    for month, info in snaps.items():
        for c in info["top20"]:
            coins.setdefault(c["cmc_id"],
                             {"symbol": c["symbol"], "slug": c["slug"]})
    reg = {}
    for cid, meta in coins.items():
        if cid in EXCLUDED:
            reg[cid] = {**meta, "source": "excluded",
                        "reason": EXCLUDED[cid], "rows": []}
            continue
        if cid in BINANCE_MAP:
            pair, fm = BINANCE_MAP[cid]
            rows = fetch_binance(pair, fm)
            src = f"binance:{pair}"
        elif cid in KRAKEN_MAP:
            rows = fetch_kraken(KRAKEN_MAP[cid])
            src = f"kraken:{KRAKEN_MAP[cid]}"
        elif cid == 32196:
            rows = fetch_bybit("HYPEUSDT")
            src = "bybit:HYPEUSDT"
        else:
            ticker = YAHOO_MAP.get(cid, f"{meta['symbol']}-USD")
            rows = fetch_yahoo(ticker)
            src = f"yahoo:{ticker}"
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        if len(rows) < 60:
            reg[cid] = {**meta, "source": "excluded",
                        "reason": f"price series too short/absent "
                                  f"({len(rows)} bars via {src})",
                        "rows": []}
        else:
            reg[cid] = {**meta, "source": src, "reason": None, "rows": rows}
    return reg


# ---------------------------------------------------------------------------
# Market: BTC calendar; per-coin real bars, forward-filled closes for
# signals, and death-rule valuation (last close for GRACE_DAYS, then $0).
# ---------------------------------------------------------------------------
class Market:
    def __init__(self, reg):
        self.reg = reg
        btc_rows = reg[1]["rows"]
        self.cal = [r["d"] for r in btc_rows]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        self.bars = {}        # cid -> {date: (open, close)}
        self.closes_ff = {}   # cid -> [close or None] forward-filled real closes
        self.last_bar = {}    # cid -> [index of most recent real bar <= i, or -1]
        self.bar_count = {}   # cid -> [cumulative real bars <= i]
        self.first_idx = {}
        self.last_idx = {}
        for cid, info in reg.items():
            if info["source"] == "excluded":
                continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, cnt = [], [], []
            last_close, last_i, n = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars:
                    last_close = bars[d][1]
                    last_i = i
                    n += 1
                ff.append(last_close)
                lb.append(last_i)
                cnt.append(n)
            self.closes_ff[cid] = ff
            self.last_bar[cid] = lb
            self.bar_count[cid] = cnt
            idxs = [self.cal_index[r["d"]] for r in info["rows"]
                    if r["d"] in self.cal_index]
            self.first_idx[cid] = min(idxs) if idxs else None
            self.last_idx[cid] = max(idxs) if idxs else None

    def trade_open(self, cid, i):
        """A price you could actually trade at on day i: today's real
        open, else yesterday's real close, else None (no trading)."""
        d = self.cal[i]
        if d in self.bars[cid]:
            return self.bars[cid][d][0]
        if i > 0 and self.cal[i - 1] in self.bars[cid]:
            return self.bars[cid][self.cal[i - 1]][1]
        return None

    def value_close(self, cid, i):
        """Death-rule valuation: last real close during the 30-day
        grace period after the series ends, then $0."""
        lb = self.last_bar[cid][i]
        if lb < 0:
            return None
        if i - lb <= GRACE_DAYS:
            return self.closes_ff[cid][i]
        return 0.0

    def sma(self, cid, i, n):
        if i + 1 < n:
            return None
        seg = self.closes_ff[cid][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def eligible(self, cid, j):
        """Eligibility + 12-1 momentum at signal index j (prior close).
        Returns momentum or None."""
        if cid not in self.bars:
            return None
        lb = self.last_bar[cid]
        if lb[j] < 0 or j - lb[j] > 7:            # fresh data required
            return None
        if self.bar_count[cid][j] < 300:          # real history required
            return None
        c = self.closes_ff[cid][j]
        if c is None:
            return None
        sma200 = self.sma(cid, j, SMA_N)
        if sma200 is None or c <= sma200:
            return None
        a_i, b_i = lb[j - MOM_FAR], lb[j - MOM_NEAR]
        if a_i < 0 or b_i < 0:
            return None
        if (j - MOM_FAR) - a_i > 7 or (j - MOM_NEAR) - b_i > 7:
            return None                           # lookback bars must be real
        a, b = self.closes_ff[cid][a_i], self.closes_ff[cid][b_i]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.equity_curve = []
        self.events = []          # death / collapse log
        self.resurrections = 0
        self.elig_sum = 0
        self.elig_months = 0
        self.invested_sum = 0.0
        self.months = 0
        self.month_wins = 0
        self.picks_log = []       # per selection: month, picks, n_eligible


def simulate(mkt, snaps, start_d, end_d, mode, seed=42, floor_variant="none",
             start_cash=None, floor_abs=None):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    floor = (85.0 if floor_abs is None else float(floor_abs)) if floor_variant == "plain" else None
    cash = float(POT) if start_cash is None else float(start_cash)
    pos = {}                      # cid -> shares
    entry_avg = {}                # cid -> weighted avg buy price
    wo_flag = {}                  # cid -> True once write-off logged for this spell
    res = Result()
    pending_liquidation = False
    cur_month = None

    def equity_at(i):
        tot = cash
        for cid, sh in pos.items():
            v = mkt.value_close(cid, i)
            if v:
                tot += sh * v
        return tot

    def note_exit(cid, exit_px, when):
        """Log a >=90% collapse when a position fully exits."""
        if cid in entry_avg and entry_avg[cid] > 0:
            sh = pos.get(cid, 0.0)
            if exit_px <= 0.10 * entry_avg[cid]:
                res.events.append({
                    "type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                    "cmc_id": cid, "date": when,
                    "entry_px": entry_avg[cid], "exit_px": exit_px,
                    "loss_pct": round((exit_px / entry_avg[cid] - 1) * 100, 2),
                })

    for i in range(i0, i1 + 1):
        d = cal[i]
        month_key = d[:7] + "-01"

        # ---- death-rule write-off detection (daily) -------------------
        for cid in list(pos):
            lb = mkt.last_bar[cid][i]
            if lb >= 0 and i - lb == GRACE_DAYS + 1 and not wo_flag.get(cid):
                last_px = mkt.closes_ff[cid][lb]
                res.events.append({
                    "type": "write_off", "coin": mkt.reg[cid]["symbol"],
                    "cmc_id": cid, "date": d,
                    "last_bar_date": cal[lb], "last_px": last_px,
                    "shares": pos[cid],
                    "written_off_value": round(pos[cid] * last_px, 2),
                })
                wo_flag[cid] = True
            if lb >= 0 and i - lb <= GRACE_DAYS and wo_flag.get(cid):
                wo_flag[cid] = False
                res.resurrections += 1

        # ---- floor liquidation -----------------------------------------
        if pending_liquidation:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d)      # untradeable: exits at $0
                    del pos[cid]
                    entry_avg.pop(cid, None)
                    continue
                val = pos[cid] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                note_exit(cid, px, d)
                del pos[cid]
                entry_avg.pop(cid, None)
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        # ---- monthly selection ------------------------------------------
        if month_key != cur_month and i > 0:
            cur_month = month_key
            snap = snaps.get(month_key)
            if snap is None:      # fall back to the most recent known month
                keys = sorted(k for k in snaps if k < month_key)
                snap = snaps[keys[-1]] if keys else {"top20": []}
            universe = [c["cmc_id"] for c in snap["top20"]]
            j = i - 1
            elig = []
            for cid in universe:
                mom = mkt.eligible(cid, j)
                if mom is not None:
                    elig.append((cid, mom))
            res.elig_sum += len(elig)
            res.elig_months += 1
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [cid for cid, _ in elig[:5]]
            else:
                names = sorted(cid for cid, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            res.invested_sum += 0.20 * len(picks)
            res.picks_log.append({
                "month": month_key,
                "picks": [mkt.reg[c]["symbol"] for c in picks],
                "n_eligible": len(elig),
            })

            eq_open = equity_at(i)
            target_val = {cid: 0.20 * eq_open for cid in picks}

            # sells first
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    # cannot trade: if past grace the position is a
                    # $0 write-off already logged — clear the books.
                    lb = mkt.last_bar[cid][i]
                    if lb >= 0 and i - lb > GRACE_DAYS:
                        note_exit(cid, 0.0, d)
                        del pos[cid]
                        entry_avg.pop(cid, None)
                    continue
                cur_val = pos[cid] * px
                want = target_val.get(cid, 0.0)
                if want <= 0.0 and cur_val <= 0.01:
                    # dust exit: an unwanted position worth <1 cent
                    # (e.g. a collapsed coin) — clear it and log the
                    # exit so collapses are recorded, not zombified.
                    note_exit(cid, px, d)
                    del pos[cid]
                    entry_avg.pop(cid, None)
                    continue
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[cid] -= sh
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        note_exit(cid, px, d)
                        del pos[cid]
                        entry_avg.pop(cid, None)
            # buys
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None:
                    continue
                cur_val = pos.get(cid, 0.0) * px
                deficit = target_val[cid] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                sh_new = buy_val / px
                old_sh = pos.get(cid, 0.0)
                if old_sh > 0 and cid in entry_avg:
                    entry_avg[cid] = (entry_avg[cid] * old_sh
                                      + px * sh_new) / (old_sh + sh_new)
                else:
                    entry_avg[cid] = px
                pos[cid] = old_sh + sh_new

        # ---- daily close -------------------------------------------------
        eq_close = equity_at(i)
        res.equity_curve.append((d, eq_close))
        if floor is not None and eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v:
                        fee = sh * v * COST_RATE + SELL_FEE
                        tot += sh * v - fee
                        res.costs += fee
                        res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        if r > 0:
            res.month_wins += 1
    return res


# ---------------------------------------------------------------------------
# Benchmarks / reporting helpers
# ---------------------------------------------------------------------------
def btc_bars(mkt):
    return mkt.bars[1]


def btc_net(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    buy_px = mkt.trade_open(1, i0)
    sell_px = mkt.closes_ff[1][i1]
    sh = (POT * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE)


def btc_dd(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT * (1 - COST_RATE)) / mkt.trade_open(1, i0)
    peak, dd = -1.0, 0.0
    for i in range(i0, i1 + 1):
        v = sh * mkt.closes_ff[1][i]
        peak = max(peak, v)
        if peak > 0:
            dd = min(dd, v / peak - 1.0)
    return dd


def cagr(final, start, years):
    if final <= 0 or start <= 0:
        return float("nan")
    return (final / start) ** (1.0 / years) - 1.0


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def per_year(res, pot0):
    out = {}
    years = sorted({d[:4] for d, _ in res.equity_curve})
    prev_eq = float(pot0)
    for y in years:
        pts = [e for d, e in res.equity_curve if d[:4] == y]
        if not pts:
            continue
        end_eq = pts[-1]
        out[y] = end_eq / prev_eq - 1.0
        prev_eq = end_eq
    return out


def btc_year_returns(mkt, start_d, end_d):
    cal = mkt.cal
    yrs = {}
    idx = [i for i, d in enumerate(cal) if start_d <= d <= end_d]
    prev = mkt.closes_ff[1][idx[0] - 1] if idx and idx[0] > 0 else None
    for i in idx:
        y = cal[i][:4]
        c = mkt.closes_ff[1][i]
        if y not in yrs:
            yrs[y] = [prev, c]
        yrs[y][1] = c
        prev = c
    return {y: (v[1] / v[0] - 1.0 if v[0] else None) for y, v in yrs.items()}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _summ(r, yrs, btc):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / POT - 1) * 100, 2),
        "cagr_pct": round(cagr(r.final, POT, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "halt": r.halt_date,
        "month_win_pct": (round(100 * r.month_wins / r.months, 1)
                          if r.months else None),
        "avg_eligible": (round(r.elig_sum / r.elig_months, 2)
                         if r.elig_months else None),
        "avg_invested_pct": (round(100 * r.invested_sum / r.elig_months, 1)
                            if r.elig_months else None),
        "n_events": len(r.events),
        "events": r.events,
        "resurrections": r.resurrections,
        "btc_final": round(btc, 2),
        "btc_ret_pct": round((btc / POT - 1) * 100, 2),
    }


def main():
    snaps = load_snapshots()
    reg = build_registry(snaps)
    mkt = Market(reg)

    reg_summary = {}
    for cid, info in sorted(reg.items()):
        rows = info["rows"]
        reg_summary[str(cid)] = {
            "symbol": info["symbol"], "slug": info["slug"],
            "source": info["source"], "reason": info["reason"],
            "bars": len(rows),
            "first": rows[0]["d"] if rows else None,
            "last": rows[-1]["d"] if rows else None,
        }
        print(f"reg {cid} {info['symbol']}: {info['source']} "
              f"bars={len(rows)} "
              f"{rows[0]['d'] if rows else '-'} -> "
              f"{rows[-1]['d'] if rows else '-'}", flush=True)

    all_out = {"cost_rate": COST_RATE, "registry": reg_summary}
    ranked_final = {}

    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        btc = btc_net(mkt, sd, ed)
        r = simulate(mkt, snaps, sd, ed, "ranked", floor_variant="none")
        key = f"{wname}|ranked|none"
        all_out[key] = _summ(r, yrs, btc)
        all_out[f"{wname}|picks_log"] = r.picks_log
        all_out[key]["btc_dd_pct"] = round(btc_dd(mkt, sd, ed) * 100, 2)
        ranked_final[wname] = r.final
        print(f"{key}: final={r.final:.2f} ret={(r.final/POT-1)*100:+.2f}% "
              f"orders={r.orders} costs=${r.costs:.2f} "
              f"maxDD={r.max_dd*100:.2f}% events={len(r.events)} "
              f"avgElig={r.elig_sum/max(r.elig_months,1):.1f} BTC={btc:.2f}",
              flush=True)

    # diagnostic: plain floor, ranked, full window
    sd, ed = WINDOWS["full"]
    r = simulate(mkt, snaps, sd, ed, "ranked", floor_variant="plain")
    all_out["full|ranked|plainfloor"] = _summ(r, years_between(sd, ed),
                                              btc_net(mkt, sd, ed))
    print(f"full|ranked|plainfloor: final={r.final:.2f} halt={r.halt_date} "
          f"maxDD={r.max_dd*100:.2f}%", flush=True)

    # placebo: 20 seeds, full + validation, no floor
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        yrs = years_between(sd, ed)
        btc = btc_net(mkt, sd, ed)
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            r = simulate(mkt, snaps, sd, ed, "placebo", seed=seed,
                         floor_variant="none")
            finals.append(r.final)
            rows.append({"seed": seed, "final": round(r.final, 2),
                         "ret_pct": round((r.final / POT - 1) * 100, 2),
                         "max_dd_pct": round(r.max_dd * 100, 2),
                         "orders": r.orders, "costs": round(r.costs, 2),
                         "n_events": len(r.events)})
        sfin = sorted(finals)
        rk = ranked_final[wname]
        n_beat = sum(1 for v in finals if rk > v)
        dist = {
            "n_seeds": len(finals),
            "median_final": round(_pct(sfin, 0.50), 2),
            "p25_final": round(_pct(sfin, 0.25), 2),
            "p75_final": round(_pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "median_ret_pct": round((_pct(sfin, 0.50) / POT - 1) * 100, 2),
            "ranked_final": round(rk, 2),
            "ranked_minus_median": round(rk - _pct(sfin, 0.50), 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
            "btc_final": round(btc, 2),
            "rows": rows,
        }
        all_out[f"{wname}|placebo_dist|none"] = dist
        print(f"{wname}|placebo|none: median={dist['median_final']:.2f} "
              f"p25={dist['p25_final']:.2f} p75={dist['p75_final']:.2f} "
              f"best={dist['best_final']:.2f} worst={dist['worst_final']:.2f} "
              f"ranked={rk:.2f} beats {n_beat}/20", flush=True)

    # per-year: full-window ranked (no floor) + BTC
    r = simulate(mkt, snaps, *WINDOWS["full"], "ranked", floor_variant="none")
    all_out["per_year_ranked"] = {y: round(v * 100, 2)
                                  for y, v in per_year(r, POT).items()}
    with open(os.path.join(HERE, "crypto-basket-pit-equity.csv"), "w") as f:
        f.write("date,equity\n")
        for d, eq in r.equity_curve:
            f.write(f"{d},{eq:.4f}\n")
    all_out["per_year_btc"] = {
        y: (round(v * 100, 2) if v is not None else None)
        for y, v in btc_year_returns(mkt, *WINDOWS["full"]).items()}

    # universe coins whose series ended before the window did (the dead)
    dead = {}
    for cid, info in reg.items():
        if info["source"] == "excluded" or not info["rows"]:
            continue
        last = info["rows"][-1]["d"]
        if last < "2026-10-01":   # Binance monthly files end 2026-10-31
                                  # for live pairs — not a death
            dead[str(cid)] = {"symbol": info["symbol"], "last_bar": last,
                              "source": info["source"]}
    all_out["series_ended_before_window_end"] = dead

    with open(os.path.join(HERE, "crypto-basket-pit-results.json"), "w") as f:
        json.dump(all_out, f, indent=1)
    print("saved crypto-basket-pit-results.json")


# ------------------------------------------------------------- v9 ----
# V9 RE-RUN — "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
# Copied verbatim from crypto-basket-pit.py (v4). Changes vs the
# original: (1) CACHE points at the original v4 cache (read-only);
# (2) simulate() gained start_cash / floor_abs parameters (defaults
# are the original behaviour — $100 start, $85 plain floor); (3) the
# __main__ entry runs the v9 driver below instead of the original
# main() (which is kept, unused, above).
# INTEGRITY CONTEXT (flagged, not hidden): the original primary runs
# carried NO floor. Its only floored run was a FULL-window diagnostic
# (plain $85), which never fired. The DESIGN and VALIDATION windows
# were never floor-tested in the original — the validation pot
# finished at $61.11, i.e. it crossed $85 and kept trading, because no
# floor was applied there. Under v9 the episode-1 floor IS Terry's
# plain -15% floor, so applying it to every window is the specified
# protection swap; the driver runs episode 1 with the plain floor on
# all three windows to establish where it fires, then applies the v9
# restart rule (liquidate as the original engine does, 90 calendar
# days in cash, restart at the next monthly selection — 1st of the
# month on/after day 90 — with the remaining cash; episode-2 floor
# -15% from the restart balance; second halt ends the run).
# Everything else byte-identical: CoinMarketCap weekly-snapshot
# point-in-time universe, signals, death rule, parameters, costs
# 0.40%/side, windows, $100 start. No placebo re-runs (the original
# placebo verdicts stand: 95th pct full / 40th pct validation, no
# floor). Simulation only.
from datetime import timedelta as _td
from datetime import datetime as _dt

def _next_month_first(dstr):
    d = _dt.strptime(dstr, "%Y-%m-%d")
    if d.day == 1:
        return dstr
    nxt = (d.replace(day=1) + _td(days=32)).replace(day=1)
    return nxt.strftime("%Y-%m-%d")

def v9_main():
    snaps = load_snapshots()
    reg = build_registry(snaps)
    mkt = Market(reg)
    orig = json.load(open(os.path.join(ORIG_DIR, "crypto-basket-pit-results.json")))
    out = {"windows": {}}
    for wname, (sd, ed) in WINDOWS.items():
        rec_none = orig[f"{wname}|ranked|none"]
        ep1 = simulate(mkt, snaps, sd, ed, "ranked", floor_variant="plain")
        if wname == "full":
            rec_pf = orig["full|ranked|plainfloor"]
            assert abs(ep1.final - rec_pf["final"]) < 0.011, (ep1.final, rec_pf)
            assert ep1.halt_date == rec_pf["halt"], (ep1.halt_date, rec_pf)
        info = {"his_no_floor_final": rec_none["final"],
                "ep1_plain_final": round(ep1.final, 4),
                "ep1_halt": ep1.halt_date,
                "ep1_min_equity": round(min(e for _, e in ep1.equity_curve), 4),
                "ep1_events": ep1.events,
                "restart": None, "second_halt": False, "second_halt_date": None,
                "v9_final": None,
                "v9_min_equity": round(min(e for _, e in ep1.equity_curve), 4)}
        if ep1.halt_date is None:
            assert abs(ep1.final - rec_none["final"]) < 0.011, (wname, ep1.final, rec_none)
            info["v9_final"] = rec_none["final"]
            print(f"{wname}: plain floor never fired (final ${ep1.final:.2f} == his no-floor) -> identical, no re-run")
        else:
            restart_cash = ep1.final
            earliest = (_dt.strptime(ep1.halt_date, "%Y-%m-%d") + _td(days=90)).strftime("%Y-%m-%d")
            rdate = _next_month_first(earliest)
            if rdate > ed:
                info["restart"] = {"status": "no_decision_point_in_window",
                                   "earliest": earliest, "restart_cash": restart_cash}
                info["v9_final"] = restart_cash
                print(f"{wname}: ep1 halted {ep1.halt_date} ${restart_cash:.2f}; no restart point in window")
            else:
                ep2 = simulate(mkt, snaps, rdate, ed, "ranked", floor_variant="plain",
                               start_cash=restart_cash, floor_abs=0.85 * restart_cash)
                info["restart"] = {"status": "restarted", "earliest": earliest,
                                   "restart_date": rdate, "restart_cash": restart_cash,
                                   "ep2_floor": round(0.85 * restart_cash, 4),
                                   "ep2_orders": ep2.orders, "ep2_costs": round(ep2.costs, 4),
                                   "ep2_events": ep2.events}
                info["second_halt"] = ep2.halt_date is not None
                info["second_halt_date"] = ep2.halt_date
                info["v9_final"] = round(ep2.final, 4)
                info["v9_min_equity"] = min(info["ep1_min_equity"],
                                            round(min(e for _, e in ep2.equity_curve), 4))
                print(f"{wname}: his no-floor ${rec_none['final']:.2f}; ep1 halted {ep1.halt_date} ${restart_cash:.2f}; restart {rdate} -> v9 ${ep2.final:.2f} second_halt={info['second_halt']} {ep2.halt_date}")
        out["windows"][wname] = info
    with open(os.path.join(HERE, "v9-workings.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved v9-workings.json")

if __name__ == "__main__":
    v9_main()
