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
DATA = os.path.join(HERE, "insider-data")
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
    50: {"floor0": 42.50, "rungs": [(62.50, 50.00), (75.00, 62.50)]},
    100: {"floor0": 85.00, "rungs": [(125.00, 100.00), (150.00, 125.00)]},
}

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


def simulate(sig, mkt, w_start, w_end, start_cash, pot_cfg, label):
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
            "trades": trades}


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

# ---------------------------------------------------------------- main

def main():
    ev = build_events()
    mkt = Market()
    results = {"funnels": {}, "runs": [], "benchmarks": []}
    all_trades = []

    sig_by_code = {}
    for code in ["P", "S"]:
        cl = build_clusters(ev, mkt, code)
        crange = None
        if code == "S":  # placebo only needs validation-window entries
            crange = (pd.Timestamp("2022-12-20"), pd.Timestamp("2026-11-19"))
        sig, funnel = make_signals(cl, mkt, completion_range=crange)
        results["funnels"][code] = funnel
        sig_by_code[code] = sig
        sig.to_csv(os.path.join(DATA, f"signals_{code}.csv"), index=False)

    windows = {"design": DESIGN, "validation": VALIDATION}
    for wname, (ws, we) in windows.items():
        for size, cfg in POTS.items():
            r = simulate(sig_by_code["P"], mkt, ws, we, size, cfg,
                         f"insider-P {wname} ${size}")
            results["runs"].append({k: v for k, v in r.items()
                                    if k != "trades"})
            for t in r["trades"]:
                all_trades.append({"run": r["label"], **t})
            print(r["label"], "->", r["final"], flush=True)
        for size in POTS:
            results["benchmarks"].append(
                {**spy_benchmark(mkt, ws, we, size), "window": wname})

    # ---- placebo: sales clusters in validation, count-matched, seeded
    val_p = sig_by_code["P"]
    n_val = int(((val_p["entry_date"] >= VALIDATION[0]) &
                 (val_p["entry_date"] <= VALIDATION[1])).sum())
    val_s = sig_by_code["S"]
    val_s = val_s[(val_s["entry_date"] >= VALIDATION[0]) &
                  (val_s["entry_date"] <= VALIDATION[1])]
    rng = np.random.RandomState(PLACEBO_SEED)
    if len(val_s) > n_val:
        idx = np.sort(rng.choice(len(val_s), size=n_val, replace=False))
        placebo_sig = val_s.iloc[idx]
    else:
        placebo_sig = val_s
    results["placebo"] = {"seed": PLACEBO_SEED, "p_signals_validation": n_val,
                          "s_signals_available": int(len(val_s)),
                          "s_signals_used": int(len(placebo_sig))}
    print("placebo:", results["placebo"], flush=True)
    for size, cfg in POTS.items():
        r = simulate(placebo_sig, mkt, VALIDATION[0], VALIDATION[1], size,
                     cfg, f"PLACEBO-S validation ${size}")
        results["runs"].append({k: v for k, v in r.items() if k != "trades"})
        for t in r["trades"]:
            all_trades.append({"run": r["label"], **t})
        print(r["label"], "->", r["final"], flush=True)

    pd.DataFrame(all_trades).to_csv(
        os.path.join(HERE, "insider-cluster-trades.csv"), index=False)
    with open(os.path.join(HERE, "insider-cluster-results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(json.dumps({k: v for k, v in results.items() if k != "runs"},
                     indent=2, default=str))
    for r in results["runs"]:
        print(r)


if __name__ == "__main__":
    main()
