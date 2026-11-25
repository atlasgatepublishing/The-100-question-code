#!/usr/bin/env python3
"""
V12 - low-volatility-tournament (v3 Tournament Round 2, family F3).
NO-NATIVE-FORM program construction; see CONSTRUCTION-SPEC.md (frozen).

PART A - INTEGRITY: run the original backtests/v3/tournament2.py run_f3
unmodified over the shared cache; compare to the recorded finals
(full $236.63 / design $138.60 / validation $161.60; SPY net $314.10).

PART B - STANDARD ROADS at the native monthly cadence, frozen signal
(calmest 2 of SPY/QQQ/IWM/GLD/TLT by vol20 among close>ma200, equal weight,
$0.25 min delta, next-open execution), program costs (0.10%/side +
$0.01/sell), v9 protections (plain -15% episode floor; first halt ->
liquidate next open, 90 calendar days cash, one restart at next monthly
execution date under a fresh -15% floor; second halt ends the run).
20-seed random-selection placebos per road (same eligible set/mechanics).

Roads: LONG 2010-01-04->2026-11-20 (fresh Yahoo fetch, same convention,
saved in this folder's data_long/; shared cache starts 2015),
DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20 (shared cache). DECADE is also run on the
fetched series as a data-vintage cross-check.

Shared inputs are READ-ONLY. Writes only inside this folder.
"""
import bisect
import importlib.util
import json
import os
import random
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/workspace/stock-app/backtests")
T2_DIR = os.path.join(ROOT, "v3")
T2_DATA = os.path.join(T2_DIR, "tournament2-data")
LONG_DIR = os.path.join(HERE, "data_long")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

ROADS = {
    "LONG":   (date(2010, 1, 4),  date(2026, 11, 20)),
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT":   (date(2019, 1, 2),  date(2026, 11, 20)),
    "VAL":    (date(2023, 1, 3),  date(2026, 11, 20)),
}

# ------------------------------------------------------------------ data ----
def read_csv(path):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "open", "high", "low", "close", "volume"]] \
        .drop_duplicates("date").sort_values("date").reset_index(drop=True)

def prepare(df):
    df = df.copy()
    df["ma200"] = df["close"].rolling(200).mean()
    df["vol20"] = df["close"].pct_change().rolling(20).std()
    df.attrs["pos"] = {d: i for i, d in enumerate(df["date"])}
    df.attrs["dates"] = df["date"].tolist()
    return df

def yahoo_fetch(symbol):
    p1 = int(datetime(2009, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{symbol}?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).date()
        o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i],
                         q["close"][i], q["volume"][i])
        if None in (o, h, l, c) or c <= 0:
            continue
        rows.append((d, o, h, l, c, v or 0))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)

def load_long(symbol):
    os.makedirs(LONG_DIR, exist_ok=True)
    path = os.path.join(LONG_DIR, f"{symbol}.csv")
    if os.path.exists(path):
        return read_csv(path)
    df = None
    for attempt in range(3):
        try:
            df = yahoo_fetch(symbol)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"fetch {symbol} attempt {attempt + 1} failed: {exc}")
            time.sleep(2 * (attempt + 1))
    if df is None or df.empty:
        raise RuntimeError(f"could not fetch {symbol}")
    df.to_csv(path, index=False)
    return df

class Store:
    """One data vintage (shared cache or fetched LONG series)."""
    def __init__(self, loader):
        self.data = {s: prepare(loader(s)) for s in UNIVERSE}
        self.cal = self.data["SPY"]["date"].tolist()

    def bar(self, sym, d, field):
        df = self.data[sym]
        i = df.attrs["pos"].get(d)
        if i is None:
            return None
        v = df[field].iloc[i]
        return None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

    def last_close(self, sym, d):
        df = self.data[sym]
        j = bisect.bisect_right(df.attrs["dates"], d) - 1
        return None if j < 0 else float(df["close"].iloc[j])

# -------------------------------------------------------------- portfolio ---
class Pot:
    def __init__(self, store):
        self.store = store
        self.cash = START_CASH
        self.pos = {}
        self.total_costs = 0.0
        self.orders = 0

    def buy(self, d, sym, price, notional):
        if price is None or price <= 0 or notional <= 0:
            return
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return
        self.cash -= notional + cost
        self.pos[sym] = self.pos.get(sym, 0.0) + notional / price
        self.total_costs += cost
        self.orders += 1

    def sell(self, d, sym, price, shares=None):
        if price is None or price <= 0 or sym not in self.pos:
            return
        sh = self.pos[sym] if shares is None else min(shares, self.pos[sym])
        if sh <= 0:
            return
        value = sh * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.total_costs += cost
        self.orders += 1
        self.pos[sym] -= sh
        if self.pos[sym] <= 1e-9:
            del self.pos[sym]

    def sell_value(self, d, sym, price, value):
        if price:
            self.sell(d, sym, price, shares=value / price)

    def liquidate(self, d, at_open):
        for sym in list(self.pos.keys()):
            px = self.store.bar(sym, d, "open") if at_open else self.store.bar(sym, d, "close")
            if px is None:
                px = self.store.last_close(sym, d)
            self.sell(d, sym, px)

    def equity(self, d, at_open=False):
        eq = self.cash
        for sym, sh in self.pos.items():
            px = self.store.bar(sym, d, "open" if at_open else "close")
            if px is None:
                px = self.store.last_close(sym, d)
            eq += sh * px
        return eq

    def pos_value_open(self, sym, d):
        if sym not in self.pos:
            return 0.0
        px = self.store.bar(sym, d, "open")
        if px is None:
            px = self.store.last_close(sym, d)
        return self.pos[sym] * px

# --------------------------------------------------------------- strategy ---
def eligible_ranked(store, sig_day):
    elig = []
    for s in UNIVERSE:
        c = store.bar(s, sig_day, "close")
        ma = store.bar(s, sig_day, "ma200")
        v = store.bar(s, sig_day, "vol20")
        if c is not None and ma is not None and v is not None and c > ma:
            elig.append((v, s))
    elig.sort()
    return [s for _, s in elig]

def monthly_exec_days(days):
    out, prev = [], None
    for d in days:
        k = (d.year, d.month)
        if k != prev:
            out.append(d)
            prev = k
    return out

def run_road(store, days, placebo_seed=None):
    """Frozen tournament signal at monthly cadence under v9 protections."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    exec_days = monthly_exec_days(days)
    exec_set = set(exec_days)
    day_index = {d: i for i, d in enumerate(days)}
    pot = Pot(store)
    episode = 1
    floor = 0.85 * START_CASH
    halts = []
    halt_trigger = None
    waiting_until = None
    ended = False
    curve = []

    def targets_for(exec_day):
        i = day_index[exec_day]
        if i == 0:
            return []
        elig = eligible_ranked(store, days[i - 1])
        if rng is not None:
            if len(elig) <= 2:
                return list(elig)
            return rng.sample(elig, 2)
        return elig[:2]

    for i, d in enumerate(days):
        if ended:
            curve.append((d, pot.cash))
            continue
        if halt_trigger is not None:
            pot.liquidate(d, at_open=True)
            halts.append({"episode": episode,
                          "trigger_date": halt_trigger.isoformat(),
                          "liquidation_date": d.isoformat(),
                          "floor": round(floor, 2),
                          "balance_after_liquidation": round(pot.cash, 2)})
            halt_trigger = None
            if episode == 2:
                ended = True
                curve.append((d, pot.cash))
                continue
            resume_after = d + timedelta(days=90)
            cands = [e for e in exec_days if e >= resume_after]
            waiting_until = cands[0] if cands else None
            if waiting_until is None:
                ended = True
            curve.append((d, pot.cash))
            continue
        if waiting_until is not None:
            if d == waiting_until:
                episode = 2
                floor = 0.85 * pot.cash
                waiting_until = None
            else:
                curve.append((d, pot.cash))
                continue
        if d in exec_set:
            targets = targets_for(d)
            for s in list(pot.pos.keys()):
                if s not in targets:
                    pot.sell(d, s, store.bar(s, d, "open"))
            if targets:
                eq = pot.equity(d, at_open=True)
                tgt = eq / len(targets)
                for s in targets:
                    o = store.bar(s, d, "open")
                    if o is None:
                        continue
                    delta = tgt - pot.pos_value_open(s, d)
                    if delta > 0.25:
                        pot.buy(d, s, o, delta)
                    elif delta < -0.25:
                        pot.sell_value(d, s, o, -delta)
        eq = pot.equity(d)
        curve.append((d, eq))
        if eq <= floor:
            halt_trigger = d
    if pot.pos:
        pot.liquidate(days[-1], at_open=False)
    final = pot.cash
    if curve and curve[-1][0] == days[-1]:
        curve[-1] = (days[-1], final)
    peak, maxdd = START_CASH, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    years = (days[-1] - days[0]).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100.0, 2),
            "max_dd_pct": round(maxdd * 100.0, 2),
            "costs": round(pot.total_costs, 2), "orders": pot.orders,
            "halts": halts,
            "curve": [[d.isoformat(), round(e, 4)] for d, e in curve]}

def spy_benchmark(store, days):
    o0 = store.bar("SPY", days[0], "open")
    cN = store.bar("SPY", days[-1], "close")
    sh = (START_CASH / (1.0 + COST_RATE)) / o0
    net = sh * cN * (1.0 - COST_RATE) - SELL_FEE
    peak, dd = None, 0.0
    for d in days:
        v = store.bar("SPY", d, "close") / o0 * START_CASH
        peak = v if peak is None else max(peak, v)
        dd = max(dd, (peak - v) / peak)
    return {"net": round(net, 2), "max_dd_pct": round(dd * 100.0, 2)}

# --------------------------------------------------------------- integrity --
def integrity():
    spec = importlib.util.spec_from_file_location(
        "tournament2", os.path.join(T2_DIR, "tournament2.py"))
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    for sym in T.SYMBOLS:
        T.DATA[sym] = T.prepare(T.load_symbol(sym))
    T.CAL = T.DATA["SPY"]["date"].tolist()
    out = {}
    for wname, (ws, we) in T.WINDOWS.items():
        days = T.window_days(ws, we)
        _pf, res = T.run_f3(wname, days)
        g, n = T.spy_benchmark(days)
        out[wname] = {"final": round(res["final"], 2), "orders": res["orders"],
                      "costs": round(res["costs"], 2),
                      "maxdd_pct": round(res["maxdd_pct"], 1),
                      "win_rate_pct": round(res["win_rate"], 1),
                      "halt": res["halt_date"].isoformat() if res["halt_date"] else None,
                      "spy_gross": round(g, 2), "spy_net": round(n, 2)}
    return out

# -------------------------------------------------------------------- main --
def main():
    published = {"full": 236.63, "design": 138.60, "validation": 161.60}
    integ = integrity()
    print("INTEGRITY:", json.dumps(integ, indent=1))
    integ_ok = all(abs(integ[w]["final"] - published[w]) < 0.005 for w in published) \
        and abs(integ["full"]["spy_net"] - 314.10) < 0.005
    print("integrity status:", "reproduced" if integ_ok else "DISCREPANCY")

    cache = Store(lambda s: read_csv(os.path.join(T2_DATA, f"{s}.csv")))
    long_store = Store(load_long)
    for s in UNIVERSE:
        df = long_store.data[s]
        print(f"LONG data {s}: {len(df)} bars {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")

    stores = {"LONG": long_store, "DECADE": cache, "CONT": cache, "VAL": cache}
    roads = {}
    for name, (ws, we) in ROADS.items():
        store = stores[name]
        days = [d for d in store.cal if ws <= d <= we]
        r = run_road(store, days)
        twins = [run_road(store, days, placebo_seed=seed)["final"] for seed in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        bench = spy_benchmark(store, days)
        roads[name] = {
            "window": [days[0].isoformat(), days[-1].isoformat()],
            "trading_days": len(days),
            "data_vintage": "fresh Yahoo fetch 2009->2026 (data_long/, same convention)"
                            if name == "LONG" else "shared cache backtests/v3/tournament2-data/",
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "halts": r["halts"],
            "spy_priceonly_net_same_plumbing": bench["net"],
            "spy_priceonly_max_dd_pct": bench["max_dd_pct"],
            "placebo_beaten": f"{beaten}/20",
            "placebo_finals": twins,
            "placebo_median": round(float(np.median(twins)), 2),
            "equity_curve": r["curve"],
        }
        print(f"{name}: final ${r['final']:.2f} CAGR {r['cagr_pct']:+.2f}% "
              f"DD {r['max_dd_pct']:.2f}% costs ${r['costs']:.2f} orders {r['orders']} "
              f"halts {len(r['halts'])} placebo {beaten}/20 SPYnet ${bench['net']:.2f}")

    # data-vintage cross-check: DECADE on the fetched series
    d0, d1 = ROADS["DECADE"]
    days_x = [d for d in long_store.cal if d0 <= d <= d1]
    rx = run_road(long_store, days_x)
    bench_x = spy_benchmark(long_store, days_x)
    cross = {"decade_on_fetched_series_final": rx["final"],
             "decade_on_shared_cache_final": roads["DECADE"]["final"],
             "recorded_original_final": 236.63,
             "spy_net_fetched": bench_x["net"], "spy_net_cache": roads["DECADE"]["spy_priceonly_net_same_plumbing"]}
    print("CROSS-CHECK:", json.dumps(cross, indent=1))

    results = {
        "slug": "low-volatility-tournament",
        "family": "v3 Tournament Round 2 family F3 - program construction, NO NATIVE FORM (v11 sec.6)",
        "spec": "CONSTRUCTION-SPEC.md (frozen tournament spec reproduced in full; nothing constructed, nothing tuned)",
        "protections_roads": "v9 plain -15% episode floor, 90-day cash sit, one restart (program standard; v10 proved the swap changes nothing on DECADE-monthly: $236.63 under both floors, no halt either way)",
        "costs": "0.10% of trade value per side + $0.01 per sell order (program/tournament standard)",
        "integrity": {
            "status": "reproduced" if integ_ok else "DISCREPANCY - see RESULTS.md",
            "published_finals": {"full": 236.63, "design": 138.60, "validation": 161.60,
                                 "spy_priceonly_net_full": 314.10},
            "reproduced": integ,
            "engine": "backtests/v3/tournament2.py run_f3, unmodified, over shared cache",
        },
        "roads": roads,
        "cross_check": cross,
        "program_references": {
            "spy_dividend_adjusted": {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80},
            "champion_vm": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35},
            "note": "Strategy roads are price-only (tournament data convention); dividend-adjusted references are the real-world bar and are printed beside every road in RESULTS.md.",
        },
        "verdict": "STILL DEAD EVEN CONSTRUCTED (nothing was constructed - the frozen tournament form itself, re-run) - see RESULTS.md",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
