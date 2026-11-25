#!/usr/bin/env python3
"""Shared TAA chassis for v12 catalog slice 8. Close-based, signal at day t
close, execution at day t+1 close, program costs 0.10% per side + $0.01 per
sell order. House form = v9: -15% floor per episode, first halt -> 90 days
cash -> one restart, second halt ends run."""
import bisect, csv, json, math, os, random
from datetime import date, timedelta

T2 = os.path.expanduser("~/workspace/stock-app/backtests/v3/tournament2-data")
ETFJ = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
SEC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/sector-rotation/data")
COST = 0.001; SELLFEE = 0.01; POT = 100.0

def _parse(d): return date.fromisoformat(d)

def load_t2(sym):
    ds, cs = [], []
    with open(os.path.join(T2, f"{sym}.csv")) as fh:
        for r in csv.DictReader(fh):
            ds.append(_parse(r["date"])); cs.append(float(r["close"]))
    return ds, cs

def load_sector(sym):
    ds, cs = [], []
    with open(os.path.join(SEC, f"{sym}.csv")) as fh:
        for r in csv.DictReader(fh):
            ds.append(_parse(r["Date"])); cs.append(float(r["Close"]))
    return ds, cs

def load_etf_json(sym):
    import datetime as dt
    d = json.load(open(os.path.join(ETFJ, f"{sym}.json")))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
    ds, cs = [], []
    for t, c in zip(ts, cl):
        if c is None: continue
        ds.append(dt.datetime.utcfromtimestamp(t).date()); cs.append(float(c))
    return ds, cs

def load_fred(path):
    ds, vs = [], []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            keys = list(r.keys())
            v = r[keys[1]]
            if v in (".", "", None): continue
            ds.append(_parse(r[keys[0]])); vs.append(float(v))
    return ds, vs

class Panel:
    def __init__(self, master_sym_loader):
        self.dates, base = master_sym_loader
        self.idx = {d: i for i, d in enumerate(self.dates)}
        self.series = {}
    def add(self, sym, loader):
        ds, cs = loader
        m = dict(zip(ds, cs))
        arr = []
        last = None
        for d in self.dates:
            if d in m: last = m[d]
            arr.append(last)
        self.series[sym] = arr
    def close(self, sym, i):
        return self.series[sym][i]
    def ret(self, sym, i, n):
        if i - n < 0: return None
        a, b = self.series[sym][i - n], self.series[sym][i]
        if a is None or b is None or a <= 0: return None
        return b / a - 1.0
    def sma(self, sym, i, n):
        if i - n + 1 < 0: return None
        w = self.series[sym][i - n + 1:i + 1]
        if any(v is None for v in w): return None
        return sum(w) / n
    def vol(self, sym, i, n):
        if i - n < 0: return None
        w = self.series[sym][i - n:i + 1]
        if any(v is None for v in w): return None
        rets = [w[k + 1] / w[k] - 1 for k in range(n)]
        mu = sum(rets) / n
        return math.sqrt(sum((r - mu) ** 2 for r in rets) / max(n - 1, 1))

def cadence_days(dates, cadence):
    if cadence == "daily": return set(range(len(dates)))
    def key(d, c):
        if c == "monthly": return (d.year, d.month)
        if c == "quarterly": return (d.year, (d.month - 1) // 3)
        if c == "semiannual": return (d.year, (d.month - 1) // 6)
        if c == "annual": return (d.year,)
        iso = d.isocalendar(); return (iso[0], iso[1])
    out = {0}; prev = key(dates[0], cadence); wk = 0
    for i in range(1, len(dates)):
        k = key(dates[i], cadence)
        if k != prev:
            prev = k
            if cadence == "biweekly":
                wk += 1
                if wk % 2 == 0: out.add(i)
            else: out.add(i)
    return out

def simulate(panel, days_idx, decision_idx, signal_fn, rulebook="native",
             placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = POT; shares = {}; costs = 0.0; orders = 0
    curve = []
    episode = 1; floor = 0.85 * POT; halt_pending = False; ended = False
    cash_until = -1; restart_pending = False; halts = []
    pending = None
    syms = list(panel.series.keys())
    def equity(i):
        eq = cash
        for s, sh in shares.items():
            c = panel.close(s, i)
            if c: eq += sh * c
        return eq
    def liquidate(i):
        nonlocal cash, shares, costs, orders
        for s in list(shares.keys()):
            c = panel.close(s, i)
            if c is None or shares[s] <= 0: continue
            v = shares[s] * c; fee = v * COST + SELLFEE
            cash += v - fee; costs += fee; orders += 1
            del shares[s]
    def apply_target(i, target):
        nonlocal cash, shares, costs, orders
        eq = equity(i)
        if eq <= 0: return
        tgt_val = {s: target.get(s, 0.0) * eq for s in syms}
        for s in list(shares.keys()):
            c = panel.close(s, i)
            if c is None: continue
            cur = shares[s] * c
            if cur > tgt_val.get(s, 0.0) + 0.01:
                sell_val = cur - tgt_val.get(s, 0.0)
                fee = sell_val * COST + SELLFEE
                cash += sell_val - fee; costs += fee; orders += 1
                shares[s] -= (sell_val) / c
                if shares[s] * c < 0.01: del shares[s]
        for s, tv in tgt_val.items():
            if tv <= 0.01: continue
            c = panel.close(s, i)
            if c is None: continue
            cur = shares.get(s, 0.0) * c
            if tv > cur + 0.01:
                buy_val = min(tv - cur, cash / (1 + COST))
                if buy_val < 0.01: continue
                fee = buy_val * COST; cash -= buy_val + fee; costs += fee; orders += 1
                shares[s] = shares.get(s, 0.0) + buy_val / c
    for pos, i in enumerate(days_idx):
        if ended:
            curve.append((panel.dates[i], cash)); continue
        if halt_pending:
            halt_pending = False
            liquidate(i)
            halts.append({"episode": episode, "date": str(panel.dates[i]),
                          "proceeds": round(cash, 2)})
            if rulebook == "house" and episode == 1:
                episode = 2; floor = 0.85 * cash
                cash_until = i
                restart_pending = True
                curve.append((panel.dates[i], cash)); continue
            ended = True
            curve.append((panel.dates[i], cash)); continue
        if restart_pending:
            liq_date = panel.dates[cash_until]
            if i in decision_idx and (panel.dates[i] - liq_date).days >= 90:
                restart_pending = False
            else:
                curve.append((panel.dates[i], cash)); continue
        if pending is not None:
            apply_target(i, pending); pending = None
        eq = equity(i)
        curve.append((panel.dates[i], eq))
        if rulebook == "house" and eq <= floor and pos < len(days_idx) - 1:
            halt_pending = True; continue
        if i in decision_idx and pos < len(days_idx) - 1:
            if rng is not None:
                pending = placebo_target(rng, signal_fn, i)
            else:
                pending = signal_fn(i)
    if shares:
        liquidate(days_idx[-1])
        curve[-1] = (panel.dates[days_idx[-1]], cash)
    final = cash
    eqs = [POT] + [e for _, e in curve]
    peak = eqs[0]; maxdd = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0: maxdd = max(maxdd, (peak - e) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "curve": [[str(d), round(e, 2)] for d, e in curve]}

_placebo_pool = None
RISKY_POOL = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG", "IEF"]
def placebo_target(rng, signal_fn, i):
    # v13 patch: match the real signal's risky-asset COUNT at this decision
    # date, pick that many names uniformly from the risky pool, equal weight.
    base = signal_fn(i)
    k = sum(1 for s, v in base.items() if v > 0 and s in RISKY_POOL)
    if k == 0: return {"SHY": 1.0}
    pick = rng.sample(RISKY_POOL, min(k, len(RISKY_POOL)))
    return {s: 1.0 / len(pick) for s in pick}

def period_stats(curve, dates, cadence):
    def key(d):
        if cadence == "daily": return d.toordinal()
        if cadence in ("weekly", "biweekly"):
            iso = d.isocalendar(); return (iso[0], iso[1])
        if cadence == "monthly": return (d.year, d.month)
        if cadence == "quarterly": return (d.year, (d.month - 1) // 3)
        if cadence == "semiannual": return (d.year, (d.month - 1) // 6)
        return (d.year,)
    buckets = {}; order = []
    for d, e in curve:
        dd = date.fromisoformat(d) if isinstance(d, str) else d
        k = key(dd)
        if k not in buckets: order.append(k)
        buckets[k] = e
    vals = [POT] + [buckets[k] for k in order]
    rets = [vals[j + 1] / vals[j] - 1 for j in range(len(vals) - 1) if vals[j] > 0]
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"periods": n, "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / n, 1),
            "median_pct": round(med * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak": streak, "longest_below_high_periods": longest,
            "mean_pct_secondary": round(100 * sum(rets) / n, 2)}

ROADS = {"LONG": (date(2010, 1, 1), date(2026, 11, 20)),
         "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
         "CONT": (date(2019, 1, 1), date(2026, 11, 20)),
         "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
ROADS_2016 = {"LONG": (date(2016, 1, 4), date(2026, 11, 20)),
              "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
              "CONT": (date(2019, 1, 1), date(2026, 11, 20)),
              "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def road_indices(panel, roads):
    out = {}
    for name, (a, b) in roads.items():
        idx = [i for i, d in enumerate(panel.dates) if a <= d <= b]
        if idx: out[name] = idx
    return out
