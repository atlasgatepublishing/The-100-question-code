#!/usr/bin/env python3
"""Residual Momentum — v12 CONSTRUCTED run. Implements CONSTRUCTION-SPEC.md
exactly as frozen: FF3 (French library) 36-month OLS residuals, score =
mean/sd of residuals over months M-12..M-1, PIT S&P 500 universe, price>$1,
long-only top decile equal weight, vanished tapes -> ZERO, program costs
(0.10%/side + $0.01/sell order), no floor. Cadence = rebalance dates only;
scores are monthly objects. 20-seed placebos per cell.
Outputs: cells/<road>-<cadence>.json + results.json."""
import bisect, csv, json, math, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells"); os.makedirs(CELLS, exist_ok=True)
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

# ---------------- load factors ----------------
ff = {}  # yyyymm -> (mktrf, smb, hml, rf) in decimals
with open(os.path.join(DATA, "ff3_monthly.csv")) as f:
    for row in csv.DictReader(f):
        ff[row["yyyymm"]] = tuple(float(row[k]) / 100.0 for k in ("mktrf", "smb", "hml", "rf"))

def ym(d):  # 'YYYY-MM-DD' -> 'YYYYMM'
    return d[:4] + d[5:7]

def month_add(yyyymm, k):
    y, m = int(yyyymm[:4]), int(yyyymm[4:6]) + k
    y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f"{y:04d}{m:02d}"

# ---------------- load roster ----------------
snaps = []  # (date, set(tickers))
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
snaps.sort()
snap_dates = [d for d, _ in snaps]

def members_on(date_str):
    i = bisect.bisect_right(snap_dates, date_str) - 1
    return set(snaps[i][1]) if i >= 0 else set()

# ---------------- load prices ----------------
def write_json(path, obj):
    """Resilient write: the sandbox intermittently EPERM-blocks writes for
    minutes at a time; ride it out (up to ~40 min per file)."""
    import time as _t
    for attempt in range(120):
        try:
            with open(path, "w") as f:
                json.dump(obj, f)
            return
        except PermissionError:
            _t.sleep(20)
    raise RuntimeError(f"could not write {path}")

px = {}       # ticker -> (dates list, adjclose np.array)
px_files = sorted(fn for fn in os.listdir(DATA) if fn.startswith("px_") and fn.endswith(".json"))
for fn in px_files:
    t = fn[3:-5]
    try:
        bars = json.load(open(os.path.join(DATA, fn)))["bars"]
    except Exception:
        continue  # corrupt/partial tape = no tape (named in RESULTS)
    if len(bars) < 50:
        continue
    px[t] = ([b[0] for b in bars], np.array([b[1] for b in bars], dtype=float))
print(f"price tapes loaded: {len(px)}", flush=True)

# trading calendar = SPY dates
cal = px["SPY"][0]
cal_idx = {d: i for i, d in enumerate(cal)}
n_days = len(cal)

def close_on(t, d):
    """adjclose on or before d; None if no bar <= d or first bar > d."""
    dates, arr = px[t]
    i = bisect.bisect_right(dates, d) - 1
    return None if i < 0 else float(arr[i])

def close_idx_on(t, gi):
    """(value, global-cal index of that bar) using calendar alignment by date."""
    dates, arr = px[t]
    d = cal[gi]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0:
        return None, -1
    return float(arr[i]), cal_idx.get(dates[i], -1)

# month-end adjclose per ticker: dict yyyymm -> close
month_end = {}
all_months = sorted({ym(d) for d in cal})
for t, (dates, arr) in px.items():
    me = {}
    last_ym = None; last_v = None
    for d, v in zip(dates, arr):
        m = ym(d)
        me[m] = float(v)  # last bar in month wins (dates sorted)
    month_end[t] = me

# monthly returns per ticker: yyyymm -> return
mon_ret = {}
for t, me in month_end.items():
    r = {}
    ms = sorted(me)
    for a, b in zip(ms, ms[1:]):
        if month_add(a, 1) == b and me[a] > 0:
            r[b] = me[b] / me[a] - 1.0
    mon_ret[t] = r

# ---------------- scores per formation month-end ----------------
# formation keyed by month M (yyyymm of month-end). Eligible pool + scores.
def compute_scores(M):
    """Return (scores dict ticker->score, eligible list). Uses months M-35..M
    regression, score window M-12..M-1."""
    reg_months = [month_add(M, -k) for k in range(35, -1, -1)]  # M-35..M
    if any(m not in ff for m in reg_months):
        return {}, []
    X = np.array([[1.0, ff[m][0], ff[m][1], ff[m][2]] for m in reg_months])
    XtX_inv = np.linalg.pinv(X.T @ X)
    form_date = None  # last trading day of month M
    cand = [d for d in cal if ym(d) == M]
    if not cand:
        return {}, []
    form_date = cand[-1]
    members = members_on(form_date)
    win_idx = [reg_months.index(month_add(M, -k)) for k in range(12, 0, -1)]  # M-12..M-1 positions
    scores = {}
    for t in members:
        if t not in mon_ret:
            continue
        r = mon_ret[t]
        if any(m not in r for m in reg_months):
            continue
        me = month_end[t]
        if me.get(M, 0) <= 1.0:
            continue
        y = np.array([r[m] - ff[m][3] for m in reg_months])
        beta = XtX_inv @ (X.T @ y)
        resid = y - X @ beta
        w = resid[win_idx]
        sd = float(w.std(ddof=1))
        if sd <= 1e-12:
            continue
        scores[t] = float(w.mean() / sd)
    return scores, sorted(scores)

FORM_MONTHS = [m for m in all_months if "200912" <= m <= "202610"]
SCORES = {}
for M in FORM_MONTHS:
    s, elig = compute_scores(M)
    if elig:
        SCORES[M] = (s, elig)
print(f"formation months with scores: {len(SCORES)}; "
      f"eligible counts min/med/max: {min(len(v[1]) for v in SCORES.values())}/"
      f"{sorted(len(v[1]) for v in SCORES.values())[len(SCORES)//2]}/{max(len(v[1]) for v in SCORES.values())}", flush=True)

def latest_score_month(d):
    """Latest formation month M whose month-end is < d (score known at d)."""
    m = ym(d)
    prev = month_add(m, -1)
    # score for month M is usable on dates after M's month-end
    for cand in (prev, month_add(m, -2)):
        if cand in SCORES:
            return cand
    # find any earlier
    ks = [k for k in SCORES if k <= prev]
    return max(ks) if ks else None

# ---------------- cadence calendars ----------------
def cadence_dates(cadence, start, end):
    days = [d for d in cal if start <= d <= end]
    if cadence == "daily":
        return days
    out = []
    if cadence == "weekly":
        seen = set()
        for d in days:
            wk = d[:4] + str(int(d[5:7]) * 100 + int(d[8:10]))  # placeholder replaced below
        # ISO week key
        import datetime as _dt
        seen = set()
        for d in days:
            dt = _dt.date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            key = dt.isocalendar()[:2]
            if key not in seen:
                seen.add(key); out.append(d)
        return out
    if cadence == "biweekly":
        w = cadence_dates("weekly", start, end)
        return w[::2]
    if cadence == "monthly":
        seen = set()
        for d in days:
            if d[:7] not in seen:
                seen.add(d[:7]); out.append(d)
        return out
    if cadence == "quarterly":
        seen = set()
        for d in days:
            key = (d[:4], (int(d[5:7]) - 1) // 3)
            if key not in seen:
                seen.add(key); out.append(d)
        return out
    if cadence == "semiannual":
        seen = set()
        for d in days:
            key = (d[:4], (int(d[5:7]) - 1) // 6)
            if key not in seen:
                seen.add(key); out.append(d)
        return out
    if cadence == "annual":
        seen = set()
        for d in days:
            if d[:4] not in seen:
                seen.add(d[:4]); out.append(d)
        return out
    raise ValueError(cadence)

# ---------------- portfolio engine ----------------
def run_pot(start, end, cadence, placebo_seed=None):
    rebal = set(cadence_dates(cadence, start, end))
    days = [d for d in cal if start <= d <= end]
    cash = START_CASH
    pos = {}  # ticker -> shares
    total_costs = 0.0
    orders = 0
    curve = []
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cur_target = []
    cur_score_month = None
    vanish_logged = set()

    def value_on(d, gi):
        v = cash
        for t, sh in pos.items():
            c, bar_gi = close_idx_on(t, gi)
            if c is None:
                continue
            if gi - bar_gi >= 10:  # tape ended >=10 trading days ago -> ZERO
                continue
            v += sh * c
        return v

    for gi_d, d in enumerate(days):
        gi = cal_idx[d]
        if d in rebal:
            M = latest_score_month(d)
            if M is not None and M != cur_score_month:
                scores, elig = SCORES[M]
                k = max(1, len(elig) // 10)
                if rng is None:
                    cur_target = sorted(elig, key=lambda t: -scores[t])[:k]
                else:
                    cur_target = rng.sample(elig, k)
                cur_score_month = M
            if cur_target:
                # current values at today's close (zero rule applied)
                vals = {}
                tot = cash
                for t, sh in list(pos.items()):
                    c, bar_gi = close_idx_on(t, gi)
                    if c is None or gi - bar_gi >= 10:
                        vals[t] = 0.0
                        if c is not None and gi - bar_gi >= 10:
                            vanish_logged.add(t)
                    else:
                        vals[t] = sh * c
                    tot += vals[t]
                tgt_each = tot / len(cur_target)
                tgt = {t: tgt_each for t in cur_target}
                # sells first
                for t in list(pos):
                    c, bar_gi = close_idx_on(t, gi)
                    if c is None or gi - bar_gi >= 10:
                        if vals.get(t, 0.0) == 0.0 and (c is None or gi - bar_gi >= 10):
                            del pos[t]  # zeroed out, no proceeds, no order
                        continue
                    cur = vals[t]
                    want = tgt.get(t, 0.0)
                    if cur > want + 0.005:
                        sv = cur - want
                        cost = sv * COST_RATE + SELL_FEE
                        cash += sv - cost; total_costs += cost; orders += 1
                        pos[t] -= sv / c
                        if pos[t] < 1e-9:
                            del pos[t]
                # buys
                for t in cur_target:
                    c, bar_gi = close_idx_on(t, gi)
                    if c is None or gi - bar_gi >= 10 or c <= 0:
                        continue
                    cur = pos.get(t, 0.0) * c
                    bv = tgt[t] - cur
                    if bv > 0.005:
                        bv = min(bv, cash / (1 + COST_RATE))
                        if bv <= 0.005:
                            continue
                        cost = bv * COST_RATE
                        cash -= bv + cost; total_costs += cost; orders += 1
                        pos[t] = pos.get(t, 0.0) + bv / c
        curve.append([d, round(value_on(d, gi), 4)])
    # final liquidation at last close (zero rule; unsellable names pay nothing)
    d = days[-1]; gi = cal_idx[d]
    for t in list(pos):
        c, bar_gi = close_idx_on(t, gi)
        if c is None or gi - bar_gi >= 10:
            continue
        sv = pos[t] * c
        if sv > 0.005:
            cost = sv * COST_RATE + SELL_FEE
            cash += sv - cost; total_costs += cost; orders += 1
    final = cash
    peak = -1e18; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak * 100.0)
    yrs = (np.busday_count(np.datetime64(start), np.datetime64(end)) / 252.0) or 1
    cagr = ((final / START_CASH) ** (1 / yrs) - 1) * 100 if final > 0 else -100.0
    return {"final": round(final, 2), "cagr_pct": round(cagr, 2), "max_dd_pct": round(maxdd, 2),
            "costs": round(total_costs, 2), "orders": orders, "curve": curve,
            "vanished_held": sorted(vanish_logged)}

def spy_final(start, end):
    days = [d for d in cal if start <= d <= end]
    c0 = close_on("SPY", days[0]); c1 = close_on("SPY", days[-1])
    # buy at first close with cost, sell at last close with cost+fee (program conv, approx)
    sh = (START_CASH / (1 + COST_RATE)) / c0
    proceeds = sh * c1
    return round(proceeds - (proceeds * COST_RATE + SELL_FEE), 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]

plan = []
for c in CADENCES:
    plan.append(("DECADE", c))
for road in ("LONG", "CONT", "VAL"):
    for c in ("monthly", "weekly"):
        plan.append((road, c))

results = {"family": "residual-momentum", "label": "CONSTRUCTED",
           "roads": {}, "spy": {}, "plan": [f"{r}-{c}" for r, c in plan]}
for road, (s, e) in ROADS.items():
    results["spy"][road] = spy_final(s, e)

for road, cad in plan:
    s, e = ROADS[road]
    cell_path = os.path.join(CELLS, f"{road}-{cad}.json")
    if os.path.exists(cell_path):
        try:
            prev = json.load(open(cell_path))
            results["roads"].setdefault(road, {})[cad] = {k: prev[k] for k in
                ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "placebo_beaten", "placebo_median", "vanished_held")}
            print(f"{road} {cad}: CACHED final ${prev['final']}", flush=True)
            continue
        except Exception:
            pass
    r = run_pot(s, e, cad)
    pfin = []
    for seed in range(1, 21):
        pr = run_pot(s, e, cad, placebo_seed=seed)
        pfin.append(pr["final"])
    beaten = sum(1 for x in pfin if r["final"] > x)
    cell = {"road": road, "cadence": cad, "start": s, "end": e,
            "final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"], "halts": 0,
            "placebo_beaten": beaten, "placebo_finals": pfin,
            "placebo_median": round(float(np.median(pfin)), 2),
            "vanished_held": r["vanished_held"], "equity_curve": r["curve"]}
    write_json(os.path.join(CELLS, f"{road}-{cad}.json"), cell)
    results["roads"].setdefault(road, {})[cad] = {k: cell[k] for k in
        ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "placebo_beaten", "placebo_median", "vanished_held")}
    print(f"{road} {cad}: final ${r['final']} cagr {r['cagr_pct']}% dd {r['max_dd_pct']}% "
          f"costs ${r['costs']} orders {r['orders']} placebos {beaten}/20", flush=True)

write_json(os.path.join(HERE, "results.json"), results)
print("done", flush=True)
