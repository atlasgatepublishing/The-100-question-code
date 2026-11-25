"""Shared native-rules engine (v11 W07). No house floor, no stops unless the spec says so."""
import json, os, time, math, random
import requests
import pandas as pd

V3BARS = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")
CACHE = {}  # ticker -> DataFrame(date, open, close) split/div adjusted

def _parse_yahoo(raw):
    try:
        res = raw["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        import numpy as np
        dates = pd.to_datetime(pd.Series(ts), unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        c = pd.Series(q["close"], dtype="float64"); o = pd.Series(q["open"], dtype="float64")
        a = pd.Series(adj, dtype="float64") if adj else c.copy()
        v = pd.Series(q["volume"], dtype="float64").fillna(0)
        ratio = a / c
        df0 = pd.DataFrame({"date": dates, "open": o * ratio, "close": a, "volume": v})
        df0 = df0[(df0["close"] > 0) & (df0["open"] > 0)].dropna()
        return df0.drop_duplicates("date").set_index("date").sort_index()
    except Exception:
        return None

def fetch_yahoo(ticker, dest_dir):
    safe = ticker.replace("/", "-")
    path = os.path.join(dest_dir, f"yh_{safe}.json")
    if os.path.exists(path):
        try: return _parse_yahoo(json.load(open(path)))
        except Exception: return None
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ticker, safe='')}"
           f"?period1=1262304000&period2=1796000000&interval=1d&events=div,splits")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        if r.status_code == 200 and r.json().get("chart", {}).get("result"):
            json.dump(r.json(), open(path, "w"))
            return _parse_yahoo(r.json())
    except Exception:
        pass
    return None

def get_bars(ticker, dest_dir):
    if ticker in CACHE: return CACHE[ticker]
    safe = ticker.replace("/", "-")
    df = None
    p = os.path.join(V3BARS, f"{safe}.json")
    if os.path.exists(p):
        try: df = _parse_yahoo(json.load(open(p)))
        except Exception: df = None
    if df is None or len(df) == 0:
        df = fetch_yahoo(ticker, dest_dir)
    CACHE[ticker] = df
    return df

def spy_calendar(dest_dir):
    spy = get_bars("SPY", dest_dir)
    return spy

def cost_rate(price, base, penny=0.02):
    return penny if price < 5 else base

def run_event_pot(events, spy, start, end, slots=20, base_cost=0.0025, start_cash=100.0):
    """events: dicts with entry_date(Timestamp), ticker, entry_price, exit_idx_date(Timestamp), exit_price, plus bars df.
    Sizing: slice = marked equity / slots at entry; max `slots` concurrent. Entry at given price (already chosen open/close)."""
    cal = spy.loc[start:end].index
    cal_list = list(cal)
    pos = []  # dicts: ticker, shares, exit_date, df
    cash = start_cash; curve = []; costs = 0.0; orders = 0; taken = 0; skipped = 0
    ev_by_date = {}
    for e in events: ev_by_date.setdefault(e["entry_date"], []).append(e)
    peak = start_cash; maxdd = 0.0
    for d in cal_list:
        # exits at close
        still = []
        for p in pos:
            if d >= p["exit_date"]:
                px = p["exit_price"] if d == p["exit_date"] else None
                if px is None:
                    df = p["df"]; px = df["close"].asof(d)
                cr = cost_rate(px, base_cost)
                proceeds = p["shares"] * px * (1 - cr); costs += p["shares"] * px * cr; orders += 1
                cash += proceeds
            else: still.append(p)
        pos = still
        # entries
        if d in ev_by_date:
            marked = cash + sum(p["shares"] * (p["df"]["close"].asof(d) if p["df"]["close"].asof(d) == p["df"]["close"].asof(d) else p["entry_price"]) for p in pos)
            for e in ev_by_date[d]:
                if len(pos) >= slots: skipped += 1; continue
                slice_amt = marked / slots
                if slice_amt > cash: slice_amt = cash
                if slice_amt <= 0: skipped += 1; continue
                cr = cost_rate(e["entry_price"], base_cost)
                shares = slice_amt * (1 - cr) / e["entry_price"]; costs += slice_amt * cr; orders += 1; taken += 1
                cash -= slice_amt
                pos.append({"ticker": e["ticker"], "shares": shares, "exit_date": e["exit_date"],
                            "exit_price": e["exit_price"], "df": e["df"], "entry_price": e["entry_price"]})
        eq = cash
        for p in pos:
            v = p["df"]["close"].asof(d)
            eq += p["shares"] * (v if v == v and v else p["entry_price"])
        curve.append((d, round(eq, 4)))
        peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak else 0)
    final = curve[-1][1] if curve else start_cash
    return {"final": final, "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "taken": taken, "skipped": skipped,
            "curve": [(str(d.date()), v) for d, v in curve]}

def spy_final(spy, start, end, start_cash=100.0):
    s = spy.loc[start:end]
    return round(start_cash * s["close"].iloc[-1] / s["close"].iloc[0], 2)
