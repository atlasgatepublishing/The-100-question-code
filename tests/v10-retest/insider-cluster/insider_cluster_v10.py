#!/usr/bin/env python3
"""
INSIDER-CLUSTER test — Terry's AI stock app (simulation only, no broker orders).

Signal (per assignment): a cluster of open-market insider PURCHASES (Form 4,
transaction code P, acquired) at one company — 3+ DISTINCT insiders filing
purchases within a 10-trading-day window. Entry at the OPEN of the first
trading day AFTER the cluster's last (completing) filing date — point-in-time:
filing dates only, never transaction dates.

Position rules: equal slices (equity/4), max 4 positions, hold 60 trading
days, stop -10%. Costs 0.10%/side + $0.01/sell; names under $5 are charged
the penny model 2.0%/side and flagged.

Pots: $50 (Terry's new start; floor $42.50, ladder $50 @ $62.50 close,
$62.50 @ $75 close) and $100 (floor $85, ladder $100 @ $125, $125 @ $150).
Close at/below floor -> liquidate next open, run ends.

--- V9 "CLAUDE-RULES PROTECTION SPEC v9" COPY (2026-11-21) ---
This copy changes ONLY the protection module, per spec v9, ranked $100 pot
only, no placebo re-run:
  * Episode-1 floor: plain -15% from the $100 start ($85), NO ladder.
  * On FIRST halt: liquidate exactly as the original engine does, sit in
    cash 90 calendar days, then RESTART with the remaining cash at the
    strategy's next regular decision point (the next signal entry date on
    or after the restart-eligible date). Episode-2 floor: -15% from the
    RESTART balance.
  * On SECOND halt: run ends permanently.
Everything else -- universe, signals, parameters, costs, windows -- is
byte-identical to the original engine. Data is read from the original
run's own cache (read-only): signals are the original's recorded
signals_P.csv, bars/events from the original insider-data/ folder.
A diagnostic-only field (min close equity) is added to the return dict;
it does not affect trading.

Windows: DESIGN 2019-01-01..2022-12-31, VALIDATION 2023-01-01..2026-11-20,
fresh pots. Benchmark: SPY buy-hold net per window.
PLACEBO (validation, decisive): clusters of insider SALES (code S, disposed)
run through identical machinery, subsampled with a fixed seed to match the
number of purchase-cluster signals in the validation window.

Data: SEC Insider Transactions Data Sets (quarterly ZIPs of flattened
Forms 3/4/5), 2019Q1..2026Q1 — the latest quarter the SEC had published
when this ran (2026Q2+ not yet released), so filing data ends 2026-03-31.
Prices: Yahoo Finance chart API daily bars, cached. SEC etiquette: declared
User-Agent, <10 req/sec, everything cached on disk.

Universe funnel (documented in insider-cluster.md): Form 4 code-P/S rows ->
issuers with a trading symbol as filed -> clusters -> Yahoo bars exist ->
60-day average daily dollar volume >= $2M before entry (spread control).
Known bias: Yahoo only returns bars for tickers it still carries, so
delisted names drop out — survivorship tilt FLATTERS the results.
"""

import io
import json
import os
import sys
import time
import zipfile
from collections import deque

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
# v9: read the ORIGINAL run's data cache read-only (never write into v3/)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data")
ZIPS = os.path.join(DATA, "zips")
BARS = os.path.join(DATA, "bars")
os.makedirs(ZIPS, exist_ok=True)
os.makedirs(BARS, exist_ok=True)

SEC_UA = {"User-Agent": "AtlasGatePublishing research@atlasgatepublishing.com"}
YH_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
SEC_BASE = ("https://www.sec.gov/files/structureddata/data/"
            "insider-transactions-data-sets/{}_form345.zip")
QUARTERS = [f"{y}q{q}" for y in range(2019, 2027) for q in range(1, 5)
            if not (y == 2026 and q > 1)]  # 2026Q2+ not published yet

DESIGN = ("2019-01-01", "2022-12-31")
VALIDATION = ("2023-01-01", "2026-11-20")

HOLD_DAYS = 60
STOP_PCT = 0.10
MAX_POS = 4
WINDOW_TDAYS = 10          # cluster window, trading days
COOLDOWN_TDAYS = 20        # min gap between clusters for same issuer
ADV_MIN = 2_000_000        # 60-day avg daily dollar volume floor
ADV_LOOKBACK = 60
STD_RATE = 0.001           # 0.10% per side
PENNY_RATE = 0.02          # 2.0% per side
PENNY_PRICE = 5.00
SELL_FEE = 0.01
PLACEBO_SEED = 20261121

POTS = {
    # v9 spec: ranked $100 pot only; plain -15% episode-1 floor, NO ladder.
    100: {"floor0": 85.00, "rungs": []},
}
RESTART_WAIT_DAYS = 90   # v9: calendar days in cash after the first halt

# ---------------------------------------------------------------- phase A: SEC

def download_zips():
    for q in QUARTERS:
        path = os.path.join(ZIPS, f"{q}.zip")
        if os.path.exists(path) and os.path.getsize(path) > 100_000:
            continue
        r = requests.get(SEC_BASE.format(q), headers=SEC_UA, timeout=300)
        r.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(r.content)
        print(f"downloaded {q}: {len(r.content)/1e6:.1f} MB", flush=True)
        time.sleep(0.15)  # well under SEC's 10 req/sec


def _parse_dates(s):
    return pd.to_datetime(s.astype(str).str.strip().str.title(),
                          format="%d-%b-%Y", errors="coerce")


def build_events():
    cache = os.path.join(DATA, "events.csv")
    if os.path.exists(cache):
        ev = pd.read_csv(cache, parse_dates=["filing_date", "trans_date"])
        print(f"events: loaded cache {len(ev):,} rows")
        return ev
    download_zips()
    frames = []
    for q in QUARTERS:
        zpath = os.path.join(ZIPS, f"{q}.zip")
        with zipfile.ZipFile(zpath) as z:
            names = set(z.namelist())
            def read(name, cols):
                with z.open(name) as fh:
                    return pd.read_csv(fh, sep="\t", usecols=cols, dtype=str,
                                       low_memory=False)
            sub = read("SUBMISSION.tsv",
                       ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE",
                        "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL"])
            sub = sub[sub["DOCUMENT_TYPE"] == "4"]
            own = read("REPORTINGOWNER.tsv",
                       ["ACCESSION_NUMBER", "RPTOWNERCIK"])
            trn = read("NONDERIV_TRANS.tsv",
                       ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE",
                        "TRANS_SHARES", "TRANS_PRICEPERSHARE",
                        "TRANS_ACQUIRED_DISP_CD"])
        trn = trn[((trn["TRANS_CODE"] == "P") &
                    (trn["TRANS_ACQUIRED_DISP_CD"] == "A")) |
                   ((trn["TRANS_CODE"] == "S") &
                    (trn["TRANS_ACQUIRED_DISP_CD"] == "D"))]
        if trn.empty:
            continue
        df = (trn.merge(sub, on="ACCESSION_NUMBER", how="inner")
                 .merge(own, on="ACCESSION_NUMBER", how="inner"))
        df = df.rename(columns={
            "ISSUERCIK": "issuer_cik", "ISSUERNAME": "issuer_name",
            "ISSUERTRADINGSYMBOL": "symbol", "RPTOWNERCIK": "owner_cik",
            "FILING_DATE": "filing_date", "TRANS_DATE": "trans_date",
            "TRANS_CODE": "code", "TRANS_SHARES": "shares",
            "TRANS_PRICEPERSHARE": "price"})
        df["filing_date"] = _parse_dates(df["filing_date"])
        df["trans_date"] = _parse_dates(df["trans_date"])
        df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df["value"] = df["shares"] * df["price"]
        keep = ["filing_date", "trans_date", "issuer_cik", "issuer_name",
                "symbol", "owner_cik", "code", "shares", "price", "value"]
        frames.append(df[keep])
        print(f"{q}: {len(df):,} P/S owner-rows", flush=True)
    ev = pd.concat(frames, ignore_index=True)
    ev = ev.dropna(subset=["filing_date", "owner_cik", "issuer_cik"])
    ev["symbol"] = ev["symbol"].astype(str).str.strip().str.upper()
    ev = ev[(ev["symbol"] != "") & (ev["symbol"] != "NAN")]
    # amendment dedupe: same owner, same transaction, keep earliest filing
    ev = ev.sort_values("filing_date")
    ev = ev.drop_duplicates(subset=["owner_cik", "issuer_cik", "trans_date",
                                    "shares", "price", "code"], keep="first")
    # one row per owner per filing date per issuer (earliest that day)
    ev = ev.drop_duplicates(subset=["owner_cik", "issuer_cik", "filing_date",
                                    "code"], keep="first")
    ev.to_csv(cache, index=False)
    print(f"events: {len(ev):,} rows after dedupe")
    return ev

# ---------------------------------------------------------------- phase B: bars

def fetch_bars(ticker, p1=1527811200, p2=1795651200):
    """Yahoo daily bars 2018-06-01..2026-11-25, cached. None if unavailable."""
    safe = ticker.replace("/", "-").replace(".", "-")
    path = os.path.join(BARS, f"{safe}.json")
    if os.path.exists(path):
        with open(path) as fh:
            raw = json.load(fh)
    else:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}"
               f"?period1={p1}&period2={p2}&interval=1d")
        try:
            r = requests.get(url, headers=YH_UA, timeout=30)
            raw = r.json()
        except Exception:
            raw = {}
        with open(path, "w") as fh:
            json.dump(raw, fh)
        time.sleep(0.12)
    try:
        res = raw["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(
                "America/New_York").normalize().tz_localize(None),
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"]})
        df = df.dropna(subset=["open", "close"]).drop_duplicates("date")
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


class Market:
    """SPY calendar + per-ticker bars aligned to it."""

    def __init__(self):
        spy = fetch_bars("SPY")
        self.cal = list(spy["date"])
        self.cidx = {d: i for i, d in enumerate(self.cal)}
        self.spy = spy.set_index("date")
        self.bars = {}      # ticker -> DataFrame indexed by date
        self.failed = set()

    def load(self, ticker):
        if ticker in self.bars:
            return self.bars[ticker]
        if ticker in self.failed:
            return None
        df = fetch_bars(ticker)
        if df is None or df.empty:
            self.failed.add(ticker)
            return None
        df = df.set_index("date")
        self.bars[ticker] = df
        return df

    def eff_idx(self, d):
        """First trading-day index on/after date d (filing effective day)."""
        i = np.searchsorted(self.cal, np.datetime64(d))
        return int(i) if i < len(self.cal) else None

    def next_idx_after(self, d):
        """First trading-day index whose date is strictly after d."""
        i = np.searchsorted(self.cal, np.datetime64(d), side="right")
        return int(i) if i < len(self.cal) else None

# ---------------------------------------------------------------- phase C: clusters

def build_clusters(ev, mkt, code):
    """Cluster = >=3 distinct owners filing `code` within 10 trading days."""
    sub = ev[ev["code"] == code]
    clusters = []
    per_year = {}
    for (cik, symbol), g in sub.groupby(["issuer_cik", "symbol"]):
        rows = []
        for _, r in g.iterrows():
            ei = mkt.eff_idx(r["filing_date"])
            if ei is not None:
                rows.append((ei, r["filing_date"], str(r["owner_cik"]),
                             float(r["value"]) if pd.notna(r["value"]) else 0.0))
        rows.sort()
        dq = deque()
        last_fire = -10**9
        for ei, fdate, owner, val in rows:
            dq.append((ei, fdate, owner, val))
            while dq and ei - dq[0][0] > WINDOW_TDAYS:
                dq.popleft()
            owners = {o for _, _, o, _ in dq}
            if len(owners) >= 3 and ei - last_fire > COOLDOWN_TDAYS:
                clusters.append({
                    "issuer_cik": cik, "ticker": symbol,
                    "completion_date": fdate, "eff_idx": ei,
                    "n_owners": len(owners),
                    "total_value": float(sum(v for *_, v in dq))})
                per_year[fdate.year] = per_year.get(fdate.year, 0) + 1
                last_fire = ei
                dq.clear()
    cl = pd.DataFrame(clusters)
    print(f"clusters[{code}]: {len(cl)} raw; per year {per_year}")
    return cl


def make_signals(cl, mkt, completion_range=None):
    """Attach entry date / ADV filter. Returns (signals, funnel counts).

    completion_range (optional) skips bar fetches for clusters whose
    completion date falls outside it — used for sales clusters, where only
    validation-window entries are needed for the placebo."""
    funnel = {"raw_clusters": len(cl), "out_of_scope": 0, "no_bars": 0,
              "no_entry_bar": 0, "low_adv": 0, "ok": 0}
    out = []
    for _, c in cl.iterrows():
        if completion_range is not None and not (
                completion_range[0] <= c["completion_date"]
                <= completion_range[1]):
            funnel["out_of_scope"] += 1
            continue
        df = mkt.load(c["ticker"])
        if df is None:
            funnel["no_bars"] += 1
            continue
        ei = mkt.next_idx_after(c["completion_date"])
        if ei is None or mkt.cal[ei] not in df.index:
            funnel["no_entry_bar"] += 1
            continue
        entry_date = mkt.cal[ei]
        hist = df[df.index < entry_date].tail(ADV_LOOKBACK)
        if len(hist) < 40:
            funnel["low_adv"] += 1
            continue
        adv = float((hist["close"] * hist["volume"]).mean())
        if adv < ADV_MIN:
            funnel["low_adv"] += 1
            continue
        out.append({"ticker": c["ticker"], "issuer_cik": c["issuer_cik"],
                    "completion_date": c["completion_date"],
                    "entry_date": entry_date, "entry_idx": ei,
                    "n_owners": int(c["n_owners"]),
                    "total_value": float(c["total_value"]), "adv": adv})
        funnel["ok"] += 1
    sig = pd.DataFrame(out).sort_values("entry_date").reset_index(drop=True)
    print(f"signals funnel: {funnel}")
    return sig, funnel

# ---------------------------------------------------------------- phase D: simulate

def rate_for(price):
    return PENNY_RATE if price < PENNY_PRICE else STD_RATE


def simulate_v9(sig, mkt, w_start, w_end, start_cash, pot_cfg, label):
    floor = pot_cfg["floor0"]
    rungs = pot_cfg["rungs"]
    cash = float(start_cash)
    positions = {}   # ticker -> dict(shares, entry_price, entry_idx, penny)
    trades = []
    equity_curve = []
    halt_date = None
    liquidate_pending = False
    total_costs = 0.0
    # --- v9 protection state ---
    episode = 1
    restarts = []
    resume_date = None       # first date episode 2 may activate
    restart_balance = None

    first_i = mkt.eff_idx(pd.Timestamp(w_start))
    last_i = max(i for i, d in enumerate(mkt.cal) if d <= pd.Timestamp(w_end))
    by_entry = {}
    for _, s in sig.iterrows():
        if w_start <= str(s["entry_date"].date()) <= w_end:
            by_entry.setdefault(int(s["entry_idx"]), []).append(s)

    last_close = {}  # ticker -> last known close for marking

    def mark(ticker, day, use="close"):
        df = mkt.bars.get(ticker)
        if df is not None and day in df.index:
            v = float(df.loc[day, use])
            if use == "close":
                last_close[ticker] = v
            return v
        return last_close.get(ticker)

    for i in range(first_i, last_i + 1):
        day = mkt.cal[i]
        # ---- v9: activate episode 2 on the first trading day on/after the
        # restart-eligible date; entries resume at the next signal entry
        # date from this day on (the strategy's own selection cadence).
        if resume_date is not None and day >= resume_date:
            episode = 2
            floor = restart_balance * 0.85
            restarts[-1]["restart_date"] = str(day.date())
            restarts[-1]["episode2_floor"] = round(floor, 2)
            resume_date = None
        waiting = resume_date is not None
        # ---- open: floor liquidation
        if liquidate_pending:
            for t, p in list(positions.items()):
                px = mark(t, day, "open")
                if px is None:
                    px = p["entry_price"]
                proceeds = p["shares"] * px
                cost = proceeds * rate_for(px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, px, cost, "floor_halt")})
                del positions[t]
            equity_curve.append((day, cash))
            if episode == 1:
                # v9: first halt -> sit in cash 90 calendar days, then restart
                restart_balance = cash
                resume_date = day + pd.Timedelta(days=RESTART_WAIT_DAYS)
                restarts.append({
                    "episode": 1, "halt_date": str(day.date()),
                    "liquidation_balance": round(cash, 2),
                    "restart_eligible_date": str(resume_date.date()),
                    "restart_date": None, "episode2_floor": None})
                liquidate_pending = False
                continue
            halt_date = day
            break
        # ---- open: entries (none while sitting in cash after halt 1)
        for s in (by_entry.get(i, []) if not waiting else []):
            t = s["ticker"]
            if len(positions) >= MAX_POS or t in positions:
                continue
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            open_px = float(df.loc[day, "open"])
            equity_now = cash + sum(
                p["shares"] * (mark(t2, day, "open") or p["entry_price"])
                for t2, p in positions.items())
            slice_val = equity_now / MAX_POS
            rate = rate_for(open_px)
            shares = slice_val / open_px
            debit = slice_val * (1 + rate)
            if debit > cash:
                shares = cash / (open_px * (1 + rate))
                slice_val = shares * open_px
                debit = slice_val * (1 + rate)
            if shares <= 0 or slice_val < 1.0:
                continue
            cash -= debit
            total_costs += slice_val * rate
            positions[t] = {"ticker": t, "shares": shares,
                            "entry_price": open_px, "entry_idx": i,
                            "entry_date": day, "buy_cost": slice_val * rate,
                            "penny": open_px < PENNY_PRICE,
                            "n_owners": int(s["n_owners"])}
            last_close[t] = float(df.loc[day, "close"])
        # ---- intraday stops + close time-exits
        for t, p in list(positions.items()):
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            row = df.loc[day]
            last_close[t] = float(row["close"])
            stop_px = p["entry_price"] * (1 - STOP_PCT)
            exit_px, reason = None, None
            if float(row["low"]) <= stop_px:
                exit_px = (float(row["open"]) if float(row["open"]) < stop_px
                           else stop_px)
                reason = "stop"
            elif i - p["entry_idx"] >= HOLD_DAYS:
                exit_px = float(row["close"])
                reason = "time_exit"
            if exit_px is not None:
                proceeds = p["shares"] * exit_px
                cost = proceeds * rate_for(exit_px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, exit_px, cost, reason)})
                del positions[t]
        # ---- close: mark, floor/ladder
        equity = cash + sum(p["shares"] * (mark(t, day) or p["entry_price"])
                            for t, p in positions.items())
        equity_curve.append((day, equity))
        for thresh, new_floor in rungs:
            if equity >= thresh and new_floor > floor:
                floor = new_floor
        if waiting:
            pass  # in cash between episodes; no floor check until restart
        elif equity <= floor and positions:
            liquidate_pending = True
        elif equity <= floor and not positions:
            if episode == 1:
                # v9: first halt with nothing to liquidate -> wait + restart
                restart_balance = cash
                resume_date = day + pd.Timedelta(days=RESTART_WAIT_DAYS)
                restarts.append({
                    "episode": 1, "halt_date": str(day.date()),
                    "liquidation_balance": round(cash, 2),
                    "restart_eligible_date": str(resume_date.date()),
                    "restart_date": None, "episode2_floor": None})
            else:
                halt_date = day
                break
    else:
        day = mkt.cal[last_i]
    # ---- window end: liquidate anything left at final close
    if positions and halt_date is None:
        day = mkt.cal[last_i]
        for t, p in list(positions.items()):
            px = mark(t, day) or p["entry_price"]
            proceeds = p["shares"] * px
            cost = proceeds * rate_for(px) + SELL_FEE
            cash += proceeds - cost
            total_costs += cost
            trades.append({**_trade(p, day, px, cost, "window_end")})
            del positions[t]
        equity_curve.append((day, cash))

    eq = pd.Series([v for _, v in equity_curve])
    _min_eq = min(equity_curve, key=lambda x: x[1]) if equity_curve else (None, None)
    max_dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    closed = [t for t in trades]
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return {"label": label, "start": start_cash, "final": round(cash, 2),
            "return_pct": round(100 * (cash / start_cash - 1), 2),
            "round_trips": len(closed),
            "win_rate": round(100 * wins / len(closed), 1) if closed else None,
            "total_costs": round(total_costs, 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
            "halt_date": str(halt_date.date()) if halt_date is not None else None,
            "penny_trades": sum(1 for t in closed if t["penny"]),
            "min_close_equity": round(float(_min_eq[1]), 2) if _min_eq[1] is not None else None,
            "min_close_date": str(_min_eq[0].date()) if _min_eq[0] is not None else None,
            "episodes": episode, "restarts": restarts,
            "trades": trades,
            "equity_curve": [(str(d.date()), round(float(v), 4)) for d, v in equity_curve]}


def _trade(p, exit_date, exit_px, sell_cost, reason):
    gross = p["shares"] * exit_px - p["shares"] * p["entry_price"]
    pnl = gross - p["buy_cost"] - sell_cost
    return {"ticker": p["ticker"], "entry_date": str(p["entry_date"].date()),
            "entry_price": round(p["entry_price"], 4),
            "exit_date": str(exit_date.date()), "exit_price": round(exit_px, 4),
            "shares": round(p["shares"], 4), "pnl": round(pnl, 2),
            "exit_reason": reason, "penny": bool(p["penny"]),
            "n_owners": p["n_owners"]}


def spy_benchmark(mkt, w_start, w_end, start_cash):
    first_i = mkt.eff_idx(pd.Timestamp(w_start))
    last_i = max(i for i, d in enumerate(mkt.cal) if d <= pd.Timestamp(w_end))
    buy = float(mkt.spy.loc[mkt.cal[first_i], "open"])
    sell = float(mkt.spy.loc[mkt.cal[last_i], "close"])
    shares = (start_cash * (1 - STD_RATE)) / buy
    final = shares * sell * (1 - STD_RATE) - SELL_FEE
    return {"label": f"SPY buy-hold ${start_cash}", "start": start_cash,
            "final": round(final, 2),
            "return_pct": round(100 * (final / start_cash - 1), 2)}


# ---------------------------------------------------------------- his-rules simulate (v3 verbatim)

def simulate_his(sig, mkt, w_start, w_end, start_cash, pot_cfg, label):
    floor = pot_cfg["floor0"]
    rungs = pot_cfg["rungs"]
    cash = float(start_cash)
    positions = {}   # ticker -> dict(shares, entry_price, entry_idx, penny)
    trades = []
    equity_curve = []
    halt_date = None
    liquidate_pending = False
    total_costs = 0.0

    first_i = mkt.eff_idx(pd.Timestamp(w_start))
    last_i = max(i for i, d in enumerate(mkt.cal) if d <= pd.Timestamp(w_end))
    by_entry = {}
    for _, s in sig.iterrows():
        if w_start <= str(s["entry_date"].date()) <= w_end:
            by_entry.setdefault(int(s["entry_idx"]), []).append(s)

    last_close = {}  # ticker -> last known close for marking

    def mark(ticker, day, use="close"):
        df = mkt.bars.get(ticker)
        if df is not None and day in df.index:
            v = float(df.loc[day, use])
            if use == "close":
                last_close[ticker] = v
            return v
        return last_close.get(ticker)

    for i in range(first_i, last_i + 1):
        day = mkt.cal[i]
        # ---- open: floor liquidation
        if liquidate_pending:
            for t, p in list(positions.items()):
                px = mark(t, day, "open")
                if px is None:
                    px = p["entry_price"]
                proceeds = p["shares"] * px
                cost = proceeds * rate_for(px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, px, cost, "floor_halt")})
                del positions[t]
            halt_date = day
            equity_curve.append((day, cash))
            break
        # ---- open: entries
        for s in by_entry.get(i, []):
            t = s["ticker"]
            if len(positions) >= MAX_POS or t in positions:
                continue
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            open_px = float(df.loc[day, "open"])
            equity_now = cash + sum(
                p["shares"] * (mark(t2, day, "open") or p["entry_price"])
                for t2, p in positions.items())
            slice_val = equity_now / MAX_POS
            rate = rate_for(open_px)
            shares = slice_val / open_px
            debit = slice_val * (1 + rate)
            if debit > cash:
                shares = cash / (open_px * (1 + rate))
                slice_val = shares * open_px
                debit = slice_val * (1 + rate)
            if shares <= 0 or slice_val < 1.0:
                continue
            cash -= debit
            total_costs += slice_val * rate
            positions[t] = {"ticker": t, "shares": shares,
                            "entry_price": open_px, "entry_idx": i,
                            "entry_date": day, "buy_cost": slice_val * rate,
                            "penny": open_px < PENNY_PRICE,
                            "n_owners": int(s["n_owners"])}
            last_close[t] = float(df.loc[day, "close"])
        # ---- intraday stops + close time-exits
        for t, p in list(positions.items()):
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            row = df.loc[day]
            last_close[t] = float(row["close"])
            stop_px = p["entry_price"] * (1 - STOP_PCT)
            exit_px, reason = None, None
            if float(row["low"]) <= stop_px:
                exit_px = (float(row["open"]) if float(row["open"]) < stop_px
                           else stop_px)
                reason = "stop"
            elif i - p["entry_idx"] >= HOLD_DAYS:
                exit_px = float(row["close"])
                reason = "time_exit"
            if exit_px is not None:
                proceeds = p["shares"] * exit_px
                cost = proceeds * rate_for(exit_px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, exit_px, cost, reason)})
                del positions[t]
        # ---- close: mark, floor/ladder
        equity = cash + sum(p["shares"] * (mark(t, day) or p["entry_price"])
                            for t, p in positions.items())
        equity_curve.append((day, equity))
        for thresh, new_floor in rungs:
            if equity >= thresh and new_floor > floor:
                floor = new_floor
        if equity <= floor and positions:
            liquidate_pending = True
        elif equity <= floor and not positions:
            halt_date = day
            break
    else:
        day = mkt.cal[last_i]
    # ---- window end: liquidate anything left at final close
    if positions and halt_date is None:
        day = mkt.cal[last_i]
        for t, p in list(positions.items()):
            px = mark(t, day) or p["entry_price"]
            proceeds = p["shares"] * px
            cost = proceeds * rate_for(px) + SELL_FEE
            cash += proceeds - cost
            total_costs += cost
            trades.append({**_trade(p, day, px, cost, "window_end")})
            del positions[t]
        equity_curve.append((day, cash))

    eq = pd.Series([v for _, v in equity_curve])
    max_dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    closed = [t for t in trades]
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return {"label": label, "start": start_cash, "final": round(cash, 2),
            "return_pct": round(100 * (cash / start_cash - 1), 2),
            "round_trips": len(closed),
            "win_rate": round(100 * wins / len(closed), 1) if closed else None,
            "total_costs": round(total_costs, 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
            "halt_date": str(halt_date.date()) if halt_date is not None else None,
            "penny_trades": sum(1 for t in closed if t["penny"]),
            "trades": trades,
            "equity_curve": [(str(d.date()), round(float(v), 4)) for d, v in equity_curve]}



# ---------------------------------------------------------------- cadence simulate (v9 + cadence gating)

def simulate_cadence(sig, mkt, w_start, w_end, start_cash, pot_cfg, label, cadence_set):
    floor = pot_cfg["floor0"]
    rungs = pot_cfg["rungs"]
    cash = float(start_cash)
    positions = {}   # ticker -> dict(shares, entry_price, entry_idx, penny)
    trades = []
    equity_curve = []
    halt_date = None
    liquidate_pending = False
    total_costs = 0.0
    # --- v9 protection state ---
    episode = 1
    restarts = []
    resume_date = None       # first date episode 2 may activate
    restart_balance = None

    first_i = mkt.eff_idx(pd.Timestamp(w_start))
    last_i = max(i for i, d in enumerate(mkt.cal) if d <= pd.Timestamp(w_end))
    by_entry = {}
    for _, s in sig.iterrows():
        if w_start <= str(s["entry_date"].date()) <= w_end:
            by_entry.setdefault(int(s["entry_idx"]), []).append(s)

    last_close = {}  # ticker -> last known close for marking

    def mark(ticker, day, use="close"):
        df = mkt.bars.get(ticker)
        if df is not None and day in df.index:
            v = float(df.loc[day, use])
            if use == "close":
                last_close[ticker] = v
            return v
        return last_close.get(ticker)

    for i in range(first_i, last_i + 1):
        day = mkt.cal[i]
        # ---- v9: activate episode 2 on the first trading day on/after the
        # restart-eligible date; entries resume at the next signal entry
        # date from this day on (the strategy's own selection cadence).
        if resume_date is not None and day >= resume_date:
            episode = 2
            floor = restart_balance * 0.85
            restarts[-1]["restart_date"] = str(day.date())
            restarts[-1]["episode2_floor"] = round(floor, 2)
            resume_date = None
        waiting = resume_date is not None
        # ---- open: floor liquidation
        if liquidate_pending:
            for t, p in list(positions.items()):
                px = mark(t, day, "open")
                if px is None:
                    px = p["entry_price"]
                proceeds = p["shares"] * px
                cost = proceeds * rate_for(px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, px, cost, "floor_halt")})
                del positions[t]
            equity_curve.append((day, cash))
            if episode == 1:
                # v9: first halt -> sit in cash 90 calendar days, then restart
                restart_balance = cash
                resume_date = day + pd.Timedelta(days=RESTART_WAIT_DAYS)
                restarts.append({
                    "episode": 1, "halt_date": str(day.date()),
                    "liquidation_balance": round(cash, 2),
                    "restart_eligible_date": str(resume_date.date()),
                    "restart_date": None, "episode2_floor": None})
                liquidate_pending = False
                continue
            halt_date = day
            break
        # ---- open: entries (none while sitting in cash after halt 1)
        for s in (by_entry.get(i, []) if not waiting else []):
            t = s["ticker"]
            if len(positions) >= MAX_POS or t in positions:
                continue
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            open_px = float(df.loc[day, "open"])
            equity_now = cash + sum(
                p["shares"] * (mark(t2, day, "open") or p["entry_price"])
                for t2, p in positions.items())
            slice_val = equity_now / MAX_POS
            rate = rate_for(open_px)
            shares = slice_val / open_px
            debit = slice_val * (1 + rate)
            if debit > cash:
                shares = cash / (open_px * (1 + rate))
                slice_val = shares * open_px
                debit = slice_val * (1 + rate)
            if shares <= 0 or slice_val < 1.0:
                continue
            cash -= debit
            total_costs += slice_val * rate
            positions[t] = {"ticker": t, "shares": shares,
                            "entry_price": open_px, "entry_idx": i,
                            "entry_date": day, "buy_cost": slice_val * rate,
                            "penny": open_px < PENNY_PRICE,
                            "n_owners": int(s["n_owners"])}
            last_close[t] = float(df.loc[day, "close"])
        # ---- intraday stops + close time-exits (CADENCE DAYS ONLY)
        for t, p in (list(positions.items()) if i in cadence_set else []):
            df = mkt.bars.get(t)
            if df is None or day not in df.index:
                continue
            row = df.loc[day]
            last_close[t] = float(row["close"])
            stop_px = p["entry_price"] * (1 - STOP_PCT)
            exit_px, reason = None, None
            if float(row["low"]) <= stop_px:
                exit_px = (float(row["open"]) if float(row["open"]) < stop_px
                           else stop_px)
                reason = "stop"
            elif i - p["entry_idx"] >= HOLD_DAYS:
                exit_px = float(row["close"])
                reason = "time_exit"
            if exit_px is not None:
                proceeds = p["shares"] * exit_px
                cost = proceeds * rate_for(exit_px) + SELL_FEE
                cash += proceeds - cost
                total_costs += cost
                trades.append({**_trade(p, day, exit_px, cost, reason)})
                del positions[t]
        # ---- close: mark, floor/ladder
        equity = cash + sum(p["shares"] * (mark(t, day) or p["entry_price"])
                            for t, p in positions.items())
        equity_curve.append((day, equity))
        for thresh, new_floor in rungs:
            if equity >= thresh and new_floor > floor:
                floor = new_floor
        if waiting:
            pass  # in cash between episodes; no floor check until restart
        elif i not in cadence_set:
            pass  # v10 sweep: floor reviewed only on cadence dates
        elif equity <= floor and positions:
            liquidate_pending = True
        elif equity <= floor and not positions:
            if i not in cadence_set:
                pass
            elif episode == 1:
                # v9: first halt with nothing to liquidate -> wait + restart
                restart_balance = cash
                resume_date = day + pd.Timedelta(days=RESTART_WAIT_DAYS)
                restarts.append({
                    "episode": 1, "halt_date": str(day.date()),
                    "liquidation_balance": round(cash, 2),
                    "restart_eligible_date": str(resume_date.date()),
                    "restart_date": None, "episode2_floor": None})
            else:
                halt_date = day
                break
    else:
        day = mkt.cal[last_i]
    # ---- window end: liquidate anything left at final close
    if positions and halt_date is None:
        day = mkt.cal[last_i]
        for t, p in list(positions.items()):
            px = mark(t, day) or p["entry_price"]
            proceeds = p["shares"] * px
            cost = proceeds * rate_for(px) + SELL_FEE
            cash += proceeds - cost
            total_costs += cost
            trades.append({**_trade(p, day, px, cost, "window_end")})
            del positions[t]
        equity_curve.append((day, cash))

    eq = pd.Series([v for _, v in equity_curve])
    _min_eq = min(equity_curve, key=lambda x: x[1]) if equity_curve else (None, None)
    max_dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    closed = [t for t in trades]
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return {"label": label, "start": start_cash, "final": round(cash, 2),
            "return_pct": round(100 * (cash / start_cash - 1), 2),
            "round_trips": len(closed),
            "win_rate": round(100 * wins / len(closed), 1) if closed else None,
            "total_costs": round(total_costs, 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
            "halt_date": str(halt_date.date()) if halt_date is not None else None,
            "penny_trades": sum(1 for t in closed if t["penny"]),
            "min_close_equity": round(float(_min_eq[1]), 2) if _min_eq[1] is not None else None,
            "min_close_date": str(_min_eq[0].date()) if _min_eq[0] is not None else None,
            "episodes": episode, "restarts": restarts,
            "trades": trades,
            "equity_curve": [(str(d.date()), round(float(v), 4)) for d, v in equity_curve]}



# ---------------------------------------------------------------- v10 main

OUT = os.path.dirname(os.path.abspath(__file__))
CELLS = os.path.join(OUT, "cells")
os.makedirs(CELLS, exist_ok=True)

HIS_POTS = {
    50: {"floor0": 42.50, "rungs": [(62.50, 50.00), (75.00, 62.50)]},
    100: {"floor0": 85.00, "rungs": [(125.00, 100.00), (150.00, 125.00)]},
}
V9_CFG = {"floor0": 85.00, "rungs": []}
SUB = ("2019-01-01", "2026-11-20")   # longest honest sub-window of the DECADE:
# SEC insider datasets in the v3 cache begin 2019Q1, so no Form 4 cluster
# signal can exist before 2019-01-01. The full DECADE (2016-11-21 start) is
# NOT coverable; this is documented, never backfilled.
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def cadence_indices(mkt, w_start, w_end, kind):
    idxs = [i for i, d in enumerate(mkt.cal)
            if pd.Timestamp(w_start) <= d <= pd.Timestamp(w_end)]
    if kind == "daily":
        return set(idxs)
    def keyfn(kind, d):
        if kind == "weekly":
            return (d.isocalendar()[0], d.isocalendar()[1])
        if kind == "monthly":
            return (d.year, d.month)
        if kind == "quarterly":
            return (d.year, (d.month - 1) // 3)
        if kind == "semiannual":
            return (d.year, (d.month - 1) // 6)
        if kind == "annual":
            return (d.year,)
    if kind == "biweekly":
        weeks, seen = [], set()
        for i in idxs:
            k = (mkt.cal[i].isocalendar()[0], mkt.cal[i].isocalendar()[1])
            if k not in seen:
                seen.add(k)
                weeks.append(i)
        return set(weeks[0::2])
    out, seen = set(), set()
    for i in idxs:
        k = keyfn(kind, mkt.cal[i])
        if k not in seen:
            seen.add(k)
            out.add(i)
    return out


def spy_tr_final(w_start, w_end, start_cash=100.0):
    """Dividend-adjusted SPY (long-run plumbing convention: adjclose-scaled
    bars from the v7 pxfull_SPY payload), engine cost formula: buy first
    open, sell last close, 0.10%/side + $0.01 sell fee."""
    path = os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    with open(path) as fh:
        payload = json.load(fh)
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    rows = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        rows.append((d, (o * ratio if o else a), a))
    rows.sort()
    inwin = [r for r in rows if w_start <= r[0] <= w_end]
    buy = inwin[0][1]
    sell = inwin[-1][2]
    shares = (start_cash * (1 - STD_RATE)) / buy
    final = shares * sell * (1 - STD_RATE) - SELL_FEE
    return round(final, 2)


def per_event_excess(trades, mkt):
    """Mean/median net excess vs SPY per traded cluster event. Event net
    return = (sell proceeds net of sell cost) / buy debit - 1; SPY leg =
    SPY open on entry date -> SPY close on exit date (price bars, the
    engine's own data convention)."""
    exc = []
    for t in trades:
        ed = pd.Timestamp(t["entry_date"])
        xd = pd.Timestamp(t["exit_date"])
        if ed not in mkt.spy.index or xd not in mkt.spy.index:
            continue
        debit = t["shares"] * t["entry_price"] * (
            1 + rate_for(t["entry_price"]))
        net = (t["pnl"] + t["shares"] * t["entry_price"]) / debit - 1
        spy_ret = float(mkt.spy.loc[xd, "close"]) / float(
            mkt.spy.loc[ed, "open"]) - 1
        exc.append(100 * (net - spy_ret))
    if not exc:
        return {"n": 0, "mean_net_excess_pct": None,
                "median_net_excess_pct": None}
    return {"n": len(exc),
            "mean_net_excess_pct": round(float(np.mean(exc)), 2),
            "median_net_excess_pct": round(float(np.median(exc)), 2)}


def cagr(final, w_start, w_end, start=100.0):
    yrs = (pd.Timestamp(w_end) - pd.Timestamp(w_start)).days / 365.25
    return round(100 * ((final / start) ** (1 / yrs) - 1), 2) if final > 0 else None


def slim(r):
    return {k: v for k, v in r.items() if k not in ("trades", "equity_curve")}


def main():
    mkt = Market()
    sigP = pd.read_csv(os.path.join(DATA, "signals_P.csv"),
                       parse_dates=["completion_date", "entry_date"])
    sigS = pd.read_csv(os.path.join(DATA, "signals_S.csv"),
                       parse_dates=["completion_date", "entry_date"])
    for t in sigP["ticker"].unique():
        mkt.load(t)

    # ---------- (1) INTEGRITY: original published form ----------
    integrity = {"his_runs": [], "v9_runs": [], "placebo_his": []}
    for wname, (ws, we) in {"design": DESIGN, "validation": VALIDATION}.items():
        for size in (50, 100):
            r = simulate_his(sigP, mkt, ws, we, size, HIS_POTS[size],
                             f"insider-P {wname} ${size} [his-rules integrity]")
            integrity["his_runs"].append(slim(r))
            print(r["label"], "->", r["final"], flush=True)
        r = simulate_v9(sigP, mkt, ws, we, 100, V9_CFG,
                        f"insider-P {wname} $100 [v9 integrity]")
        integrity["v9_runs"].append(slim(r))
        print(r["label"], "->", r["final"], flush=True)

    # placebo, original design: S signals in validation, seeded count-match
    val_p = sigP[(sigP["entry_date"] >= VALIDATION[0]) &
                 (sigP["entry_date"] <= VALIDATION[1])]
    n_val = int(len(val_p))
    val_s = sigS[(sigS["entry_date"] >= VALIDATION[0]) &
                 (sigS["entry_date"] <= VALIDATION[1])]
    rng = np.random.RandomState(PLACEBO_SEED)
    if len(val_s) > n_val:
        idx = np.sort(rng.choice(len(val_s), size=n_val, replace=False))
        placebo_sig = val_s.iloc[idx]
    else:
        placebo_sig = val_s
    integrity["placebo_design"] = {
        "seed": PLACEBO_SEED, "p_signals_validation": n_val,
        "s_signals_available": int(len(val_s)),
        "s_signals_used": int(len(placebo_sig)),
        "method": "identical machinery fed on insider SALES clusters (code S), "
                  "seeded random subsample matching the purchase-signal count "
                  "in the validation window one-for-one (original v3 design)"}
    print("placebo design:", integrity["placebo_design"], flush=True)
    for t in placebo_sig["ticker"].unique():
        mkt.load(t)
    for size in (50, 100):
        r = simulate_his(placebo_sig, mkt, VALIDATION[0], VALIDATION[1], size,
                         HIS_POTS[size], f"PLACEBO-S validation ${size} [his-rules integrity]")
        integrity["placebo_his"].append(slim(r))
        print(r["label"], "->", r["final"], flush=True)
    with open(os.path.join(OUT, "integrity.json"), "w") as fh:
        json.dump(integrity, fh, indent=2, default=str)

    # ---------- SPY references ----------
    spy = {
        "decade_full_2016-11-21_2026-11-20_TR": spy_tr_final("2016-11-21", "2026-11-20"),
        "subwindow_2019-01-01_2026-11-20_TR": spy_tr_final(*SUB),
        "validation_2023-01-03_2026-11-20_TR": spy_tr_final("2023-01-03", "2026-11-20"),
        "decade_spec_reference": 367.80,
        "note": "TR = dividend-adjusted, computed in-plumbing from the v7 "
                "pxfull_SPY adjclose payload with the engine cost formula. "
                "Engine-internal SPY legs (per-event excess) use the v3 "
                "cache price bars, the original test's own convention."}
    print("SPY:", spy, flush=True)

    # ---------- (2) SWEEP: DECADE sub-window x 7 cadences ----------
    cells = {}
    for cad in CADENCES:
        cs_sub = cadence_indices(mkt, SUB[0], SUB[1], cad)
        cs_val = cadence_indices(mkt, VALIDATION[0], VALIDATION[1], cad)
        r_sub = simulate_cadence(sigP, mkt, SUB[0], SUB[1], 100, V9_CFG,
                                 f"insider-P decade-sub {cad} [v10]", cs_sub)
        r_val = simulate_cadence(sigP, mkt, VALIDATION[0], VALIDATION[1], 100,
                                 V9_CFG, f"insider-P validation {cad} [v10]",
                                 cs_val)
        r_plc = simulate_cadence(placebo_sig, mkt, VALIDATION[0], VALIDATION[1],
                                 100, V9_CFG, f"PLACEBO-S validation {cad} [v10]",
                                 cs_val)
        exc_sub = per_event_excess(r_sub["trades"], mkt)
        exc_val = per_event_excess(r_val["trades"], mkt)
        exc_plc = per_event_excess(r_plc["trades"], mkt)
        cell = {
            "cadence": cad,
            "treatment": "Event rules exactly as published (entry at the open "
                         "of the first trading day after the cluster's "
                         "completing filing; 4 slots; 60-trading-day hold). "
                         "Cadence governs ONLY the review/exit rhythm: the "
                         "-10% stop check, the 60-day time-exit check and the "
                         "v9 floor check are evaluated on cadence dates only "
                         "(first trading day of the period). A floor breach "
                         "found at a cadence close liquidates at the next "
                         "open, per the engine. Entries are NOT delayed to "
                         "cadence dates.",
            "road": {"start": SUB[0], "end": SUB[1],
                     "note": "longest honest sub-window of the DECADE: SEC "
                             "insider datasets in the v3 cache start 2019Q1; "
                             "no cluster signal can exist before 2019-01-01"},
            "final": r_sub["final"],
            "cagr_pct": cagr(r_sub["final"], SUB[0], SUB[1]),
            "max_dd_pct": r_sub["max_drawdown_pct"],
            "costs": r_sub["total_costs"],
            "orders": 2 * r_sub["round_trips"],
            "round_trips": r_sub["round_trips"],
            "clusters_available_in_road": int(len(sigP)),
            "clusters_traded": r_sub["round_trips"],
            "win_rate_pct": r_sub["win_rate"],
            "halts": ([{"episode": 1, "halt_date": rr["halt_date"],
                        "liquidation_balance": rr["liquidation_balance"]}
                       for rr in r_sub["restarts"]] +
                      ([{"episode": 2, "halt_date": r_sub["halt_date"],
                         "final": r_sub["final"]}]
                       if r_sub["halt_date"] and r_sub["episodes"] == 2 else [])),
            "restart": bool(r_sub["restarts"]),
            "restarts": r_sub["restarts"],
            "second_halt": bool(r_sub["halt_date"] and r_sub["episodes"] == 2),
            "halt_date": r_sub["halt_date"],
            "per_event": exc_sub,
            "equity_curve": r_sub["equity_curve"],
            "placebo": {
                "design": "sales-cluster (code S) twin, original seeded "
                          "count-matched sample (seed 20261121, 1273 signals), "
                          "run on the VALIDATION window at the SAME cadence "
                          "under v9 rules — the only window where recorded S "
                          "signals exist (the v3 run built S signals for "
                          "validation-era completions only). The purchase pot "
                          "is run on the same window/cadence for the twin "
                          "comparison.",
                "p_validation_final": r_val["final"],
                "p_validation_per_event": exc_val,
                "p_validation_round_trips": r_val["round_trips"],
                "s_validation_final": r_plc["final"],
                "s_validation_per_event": exc_plc,
                "s_validation_round_trips": r_plc["round_trips"],
                "s_validation_costs": r_plc["total_costs"],
                "s_validation_max_dd_pct": r_plc["max_drawdown_pct"],
                "s_validation_halts": r_plc["restarts"],
                "s_validation_second_halt": bool(
                    r_plc["halt_date"] and r_plc["episodes"] == 2),
                "twin_gap_pts": round(r_val["return_pct"] - r_plc["return_pct"], 2),
                "p_beats_twin": bool(r_val["final"] > r_plc["final"]),
                "p_validation_equity_curve": r_val["equity_curve"],
                "s_validation_equity_curve": r_plc["equity_curve"]},
            "placebo_beaten": None,
            "placebo_note": "This strategy's placebo is a single structural "
                            "twin (sales clusters), not a 20-seed random "
                            "distribution — placebo_beaten is the twin "
                            "comparison in the placebo block, per the task. "
                            "The bar: a money cadence must beat the SALES "
                            "twin at the same cadence, not just SPY."}
        cells[cad] = cell
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as fh:
            json.dump(cell, fh, indent=2, default=str)
        print(cad, "sub:", r_sub["final"], "val P:", r_val["final"],
              "val S:", r_plc["final"], "exc_sub:", exc_sub, flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > spy["subwindow_2019-01-01_2026-11-20_TR"]
             and cells[c]["placebo"]["p_beats_twin"]]
    results = {
        "slug": "insider-cluster",
        "area": "event-driven (Form 4 open-market purchase clusters: >=3 "
                "distinct insiders filing code-P purchases within 10 trading "
                "days; entry next open; 60-trading-day hold; -10% stop)",
        "area_source": "SPEC W9 + CADENCE GRID: insider-cluster — event-driven",
        "native_cadence": "event-driven",
        "cadence": "event-driven",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original v3 test was event-driven with daily "
                                 "review — its native form. The sweep's daily "
                                 "cell is that rhythm; slower cells delay only "
                                 "review/exit checks.",
        "native_change": "none in signal form — cluster events exactly as "
                         "published; cadence governs review/exit rhythm only "
                         "(stated per cell). Road is the longest honest "
                         "sub-window of the DECADE (2019-01-01 start) because "
                         "the SEC insider cache begins 2019Q1.",
        "integrity": {
            "status": "PENDING — filled by finalize step from integrity.json",
            "original_finals": {
                "his_rules_design_100": 120.06, "his_rules_validation_100": 85.59,
                "v9_design_100": 218.17, "v9_validation_100": 70.95,
                "his_placebo_S_validation_100": 98.17,
                "his_placebo_S_validation_50": 49.06,
                "his_rules_design_50": 59.87, "his_rules_validation_50": 42.74},
            "reproduced_finals": {}},
        "decade_spy_final": spy["decade_full_2016-11-21_2026-11-20_TR"],
        "spy": spy,
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": "Champion (Value+Momentum) DECADE $65.89 after two halts "
                      "(from the lazy-quarterly test, per SPEC) — its crown "
                      "rests on the 2010 and 2019 roads, not the decade."},
        "cells": {c: {k: v for k, v in cells[c].items()
                      if k not in ("equity_curve", "treatment", "road")}
                  | {"placebo_beaten": None,
                     "placebo_note": cells[c]["placebo_note"],
                     "placebo_twin_gap_pts": cells[c]["placebo"]["twin_gap_pts"],
                     "placebo_s_validation_final": cells[c]["placebo"]["s_validation_final"],
                     "p_validation_final_same_cadence": cells[c]["placebo"]["p_validation_final"]}
                  for c in CADENCES},
        "money_cadences": money,
        "verdict_area": "PENDING",
        "verdict_change": "PENDING"}
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print("MONEY CADENCES:", money, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
