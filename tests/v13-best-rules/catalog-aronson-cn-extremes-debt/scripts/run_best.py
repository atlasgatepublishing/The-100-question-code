#!/usr/bin/env python3
"""v13 BEST-RULES run — catalog-aronson-cn-extremes-debt. Simulation only.
Implements BEST-RULES-SPEC.md exactly (frozen before this run):
  signal = CN(205) of 10Y Treasury price (100/DGS10), 4-day LMA smoothing;
  MOM regime form: smoothed CN >= 75 -> long SPY, <= 25 -> cash, stateful;
  weekly sampling (state on last trading day of week, effective next week);
  long/cash only, NO floor; cost 0.10% per unit position change; $100 pots.
Placebos: 20 circular phase-shifts of the position series (seeds 777+s).
Data: SPY via public Yahoo chart API (cached in ../data); DGS10 copied from
the v12 family's FRED download (read-only source). PIT: yield dated day t
first earns return of day t+1 (position series is lagged one day in run()).
"""
import csv, json, os, random, sys, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
DATA = os.path.join(FAM, "data")
os.makedirs(DATA, exist_ok=True)
ET = ZoneInfo("America/New_York")
COST = 0.001
SPAN, HI, LO = 205, 75.0, 25.0

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def fetch_spy():
    cache = os.path.join(DATA, "SPY.csv")
    if os.path.exists(cache):
        rows = list(csv.DictReader(open(cache)))
        return [r["date"] for r in rows], np.array([float(r["close"]) for r in rows])
    p1 = int(datetime(2008, 6, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    payload = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/SPY"
               f"?period1={p1}&period2={p2}&interval=1d&events=history")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode()); break
        except Exception:
            continue
    if payload is None: raise RuntimeError("SPY fetch failed")
    r = payload["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        if q["close"][i] is None: continue
        rows.append((datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d"), q["close"][i]))
    rows.sort()
    with open(cache, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "close"]); w.writerows(rows)
    return [r[0] for r in rows], np.array([r[1] for r in rows], dtype=float)

def load_yield_series(dates):
    src = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/"
                              "catalog-aronson-cn-extremes-debt/data/DGS10.csv")
    dst = os.path.join(DATA, "DGS10.csv")
    if not os.path.exists(dst):
        import shutil; shutil.copy(src, dst)
    obs = {}
    for row in csv.DictReader(open(dst)):
        try: obs[row["observation_date"]] = float(row["DGS10"])
        except Exception: pass
    s = np.full(len(dates), np.nan); last = np.nan
    for i, d in enumerate(dates):
        if d in obs: last = obs[d]
        s[i] = last
    return s

def cn(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i < n - 1: continue
        w = x[i - n + 1:i + 1]; w = w[~np.isnan(w)]
        if len(w) < n // 2: continue
        lo, hi = w.min(), w.max()
        out[i] = 100.0 * (x[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out

def lma4(x):
    out = np.full(len(x), np.nan); w = np.array([1., 2., 3., 4.])
    for i in range(3, len(x)):
        seg = x[i - 3:i + 1]
        if np.isnan(seg).any(): continue
        out[i] = float(np.dot(w, seg) / 10.0)
    return out

def build_positions(dates, yld):
    price = np.where((yld > 0) & ~np.isnan(yld), 100.0 / yld, np.nan)
    s = lma4(cn(price, SPAN))
    daily = np.zeros(len(dates)); cur = 0.0
    for i in range(len(dates)):
        v = s[i]
        if not np.isnan(v):
            if v >= HI: cur = 1.0
            elif v <= LO: cur = 0.0
        daily[i] = cur
    # weekly sampling: state on last trading day of ISO week w governs week w+1
    pos = np.zeros(len(dates))
    week_last = {}
    for i, d in enumerate(dates):
        iso = datetime.fromisoformat(d).isocalendar()
        week_last[(iso[0], iso[1])] = i
    cur_pos = 0.0
    prev_key = None
    for i, d in enumerate(dates):
        iso = datetime.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
        if key != prev_key:
            # new week: adopt state sampled at end of previous week
            if prev_key is not None:
                cur_pos = daily[week_last[prev_key]]
            prev_key = key
        pos[i] = cur_pos
    return pos, daily

def run(pos, dates, C, a, b):
    i0 = next(i for i, d in enumerate(dates) if d >= a)
    i1 = max(i for i, d in enumerate(dates) if d <= b)
    ret = np.zeros(len(C)); ret[1:] = C[1:] / C[:-1] - 1
    eq = 100.0; prev = 0.0; curve = [[dates[i0], 100.0]]; costs = 0.0; changes = 0
    peak = 100.0; mdd = 0.0; days_long = 0
    for i in range(i0 + 1, i1 + 1):
        p = pos[i - 1]
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * COST; eq -= c; costs += c; changes += 1
        eq *= (1 + p * ret[i]); prev = p; days_long += int(p > 0)
        peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        curve.append([dates[i], round(eq, 2)])
    spy = round(100.0 * C[i1] / C[i0], 2)
    return {"final": round(eq, 2), "max_dd": round(mdd, 4), "costs": round(costs, 2),
            "spy_same_window": spy, "state_changes": changes,
            "share_days_long": round(days_long / max(1, i1 - i0), 3), "curve": curve}

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    los = cur = 0
    for r in rets: cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"n_months": len(rets), "share_positive": round(sum(1 for r in rets if r > 0) / len(rets), 3),
            "median_month_pct": round(100 * float(np.median(rets)), 2),
            "best_month_pct": round(100 * max(rets), 2), "worst_month_pct": round(100 * min(rets), 2),
            "longest_losing_streak_months": los, "longest_between_highs_months": longest,
            "avg_month_pct_secondary": round(100 * float(np.mean(rets)), 2)}

def main():
    dates, C = fetch_spy()
    yld = load_yield_series(dates)
    pos, daily = build_positions(dates, yld)
    N = len(dates)
    out = {"family": "catalog-aronson-cn-extremes-debt", "program": "v13-best-rules",
           "spec": "TN10 price CN205 LMA4, MOM 75/25, weekly sample, long/cash, no floor, cost 0.10%/unit",
           "roads": {}}
    for name, (a, b) in ROADS.items():
        r = run(pos, dates, C, a, b)
        twins = []
        for s in range(1, 21):
            rng = random.Random(777 + s)
            off = rng.randint(60, N - 60)
            twins.append(run(np.roll(pos, off), dates, C, a, b)["final"])
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["placebo_finals"] = twins
        r["period_stats_monthly"] = period_stats(r["curve"])
        out["roads"][name] = r
        print(name, r["final"], "dd", r["max_dd"], "spy", r["spy_same_window"],
              "pb", r["placebos_beaten"], "/20", "changes", r["state_changes"], flush=True)
    # confirmation only if a road beats champion V+M (bars frozen in spec)
    conf = {}
    for name, (a, b) in ROADS.items():
        if out["roads"][name]["final"] > CHAMP[name]:
            years = {}
            y0, y1 = int(a[:4]), int(b[:4])
            for y in range(y0, y1 + 1):
                ya = max(a, f"{y}-01-01"); yb = min(b, f"{y}-12-31")
                if ya > yb: continue
                rr = run(pos, dates, C, ya, yb)
                years[str(y)] = {"final": rr["final"], "spy": rr["spy_same_window"],
                                 "beats_spy": rr["final"] > rr["spy_same_window"]}
            mid = dates[(next(i for i, d in enumerate(dates) if d >= a) +
                         max(i for i, d in enumerate(dates) if d <= b)) // 2]
            h1 = run(pos, dates, C, a, mid); h2 = run(pos, dates, C, mid, b)
            conf[name] = {"yearly_folds": years,
                          "majority_years_beat_spy": sum(1 for v in years.values() if v["beats_spy"]) > len(years) / 2,
                          "half1": {"final": h1["final"], "spy": h1["spy_same_window"]},
                          "half2": {"final": h2["final"], "spy": h2["spy_same_window"]},
                          "halves_sum": round(h1["final"] + h2["final"] - 100.0, 2),
                          "both_halves_beat_spy": h1["final"] > h1["spy_same_window"] and h2["final"] > h2["spy_same_window"]}
            print("CONFIRMATION", name, json.dumps(conf[name])[:600], flush=True)
    out["confirmation"] = conf if conf else "NOT TRIGGERED — no road beat champion V+M"
    json.dump(out, open(os.path.join(FAM, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
