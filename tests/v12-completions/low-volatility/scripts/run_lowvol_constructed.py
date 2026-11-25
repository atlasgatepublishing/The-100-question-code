#!/usr/bin/env python3
"""Low Volatility CONSTRUCTED form (v12). Implements CONSTRUCTION-SPEC.md
exactly: S&P 500 Low Volatility Index methodology (100 lowest 252-day vol,
inverse-vol weights, quarterly rebalance effective close of 3rd Friday of
Feb/May/Aug/Nov on reference data last business day of Jan/Apr/Jul/Oct) on the
hunted point-in-time membership archive, $100 pot, program costs, NO floor,
vanishing prices written to ZERO after >10 trading days missing (FB->META
rename excepted). Placebos: same machinery, 100 names drawn uniformly at
random from eligible members. Simulation only.
Price access inside the run loop is pointer-based (each held ticker's bar
pointer advances monotonically) — semantically identical to a bisect lookup of
the last bar <= today, just faster."""
import csv, json, os, math, random, bisect, sys, time as _time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
DATA = os.path.join(FAM, "data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
RENAMES = {"FB": "META"}  # documented pure issuer rename, successor symbol

# ---------- data ----------
def load_membership():
    rows = list(csv.reader(open(os.path.join(DATA, "sp500_hist.csv"))))[1:]
    snaps = [(d, t.split(",")) for d, t in rows]
    snaps.sort()
    return snaps

SNAPS = load_membership()
SNAP_DATES = [s[0] for s in SNAPS]

def members_on(dstr):
    i = bisect.bisect_right(SNAP_DATES, dstr) - 1
    return SNAPS[i][1] if i >= 0 else []

PX = {}  # ticker -> (dates list, vals list, cal_idx list aligned with bars)
def _store(t, rows):
    dates = [r[0] for r in rows]; vals = [r[1] for r in rows]
    PX[t] = (dates, vals, None)  # cal_idx filled after CAL is known

def load_prices():
    import glob
    for p in glob.glob(os.path.join(DATA, "px_*.json")):
        t = os.path.basename(p)[3:-5]
        if t == "SPY":
            continue
        try:
            rows = json.load(open(p))
        except Exception:
            continue
        if rows:
            _store(t, rows)
    # fallback: v7 program daily cache (same Yahoo adjusted convention), in-memory only
    v7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
    for p in glob.glob(os.path.join(v7, "pxfull_*.json")):
        t = os.path.basename(p)[7:-5].replace("-", ".")
        if t in PX or t == "SPY":
            continue
        try:
            j = json.load(open(p)); r = j["chart"]["result"][0]
            ts = r["timestamp"]; adj = r["indicators"]["adjclose"][0]["adjclose"]
            rows = [[_time.strftime("%Y-%m-%d", _time.gmtime(x)), adj[i]] for i, x in enumerate(ts) if adj[i] is not None]
            rows = [x for x in rows if x[0] >= "2008-12-01"]
            if len(rows) >= 100:
                _store(t, rows)
        except Exception:
            continue
    j = json.load(open(os.path.join(v7, "pxfull_SPY.json")))
    r = j["chart"]["result"][0]
    spy = {}
    for i, ts in enumerate(r["timestamp"]):
        adj = r["indicators"]["adjclose"][0]["adjclose"][i]
        if adj is not None:
            spy[_time.strftime("%Y-%m-%d", _time.gmtime(ts))] = adj
    return spy

SPY = load_prices()
CAL = sorted(d for d in SPY if "2008-12-01" <= d <= "2026-11-20")
CAL_IDX = {d: i for i, d in enumerate(CAL)}
for t, (dates, vals, _) in list(PX.items()):
    PX[t] = (dates, vals, [CAL_IDX.get(d, -1) for d in dates])

def px_on(t, dstr):
    s = PX.get(t)
    if not s:
        return None, None
    dates, vals, _ = s
    i = bisect.bisect_right(dates, dstr) - 1
    if i < 0:
        return None, None
    return vals[i], dates[i]

def vol_252(t, ref):
    if ref not in CAL_IDX:
        return None
    end_i = CAL_IDX[ref]
    if end_i < 252:
        return None
    s = PX.get(t)
    if not s:
        return None
    dates, vals, _ = s
    lo = bisect.bisect_left(dates, CAL[end_i - 252]); hi = bisect.bisect_right(dates, CAL[end_i])
    seg = vals[lo:hi]; segd = dates[lo:hi]
    if not segd or segd[-1] != CAL[end_i] or len(seg) < 201:
        return None
    rets = [seg[i] / seg[i - 1] - 1 for i in range(1, len(seg))]
    if len(rets) < 200:
        return None
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    v = math.sqrt(var)
    return v if v > 0 else None

VOLCACHE = {}
def vols_at(ref):
    if ref not in VOLCACHE:
        vols = {}
        for t in members_on(ref):
            v = vol_252(t, ref)
            if v is not None:
                vols[t] = v
        VOLCACHE[ref] = vols
    return VOLCACHE[ref]

def third_friday(y, m):
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7 + 14)

def last_business_day(y, m):
    d = date(y, 12, 31) if m == 12 else date(y, m + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

def rebalance_schedule(start, end):
    out = []
    for y in range(2009, 2027):
        for ref_m, exec_m in ((1, 2), (4, 5), (7, 8), (10, 11)):
            ref = last_business_day(y, ref_m).isoformat()
            exs = third_friday(y, exec_m).isoformat()
            if exs not in CAL_IDX:
                cand = [d for d in CAL if d <= exs]
                exs = cand[-1] if cand else exs
            out.append((ref, exs))
    return out

# ---------- engine ----------
class Hold:
    __slots__ = ("shares", "ptr", "val", "bar_cal", "bar_date")
    def __init__(self, shares, start_date):
        self.shares = shares
        self.ptr = -1
        self.val = None; self.bar_cal = -10 ** 9; self.bar_date = None

def run(start, end, placebo_seed=None):
    rng = random.Random(4000 + placebo_seed) if placebo_seed is not None else None
    sched = [s for s in rebalance_schedule(start, end) if s[1] >= start and s[1] <= end]
    sched_by_date = {ex: ref for ref, ex in sched}
    cash = START; holds = {}  # ticker -> Hold
    zeroed = set(); costs = 0.0; orders = 0; curve = []; elig_counts = []
    days = [d for d in CAL if start <= d <= end]

    def advance(t, h, d, ci):
        dates, vals, cals = PX[t]
        p = h.ptr
        while p + 1 < len(dates) and dates[p + 1] <= d:
            p += 1
        h.ptr = p
        if p >= 0:
            h.val = vals[p]; h.bar_cal = cals[p]; h.bar_date = dates[p]

    for d in days:
        ci = CAL_IDX[d]
        # advance pointers, vanishing / rename handling
        for t in list(holds):
            h = holds[t]
            if t not in PX:
                h.shares = 0.0; zeroed.add(t); continue
            advance(t, h, d, ci)
            if h.val is None:
                h.shares = 0.0; zeroed.add(t); continue
            if ci - h.bar_cal > 10:
                if t in RENAMES and RENAMES[t] in PX:
                    succ = RENAMES[t]
                    sv, sbd = px_on(succ, d)
                    if sv and h.val:
                        sh = holds.get(succ)
                        if sh is None:
                            sh = Hold(0.0, d); holds[succ] = sh; advance(succ, sh, d, ci)
                        sh.shares += h.shares * h.val / sv
                    else:
                        zeroed.add(t)
                    del holds[t]
                else:
                    h.shares = 0.0; zeroed.add(t)
        if d in sched_by_date:
            ref = sched_by_date[d]
            vols = vols_at(ref)
            elig = sorted(vols); elig_counts.append(len(elig))
            if rng is None:
                chosen = sorted(elig, key=lambda t: vols[t])[:100]
            else:
                chosen = rng.sample(elig, min(100, len(elig)))
            inv = {t: 1.0 / vols[t] for t in chosen}
            tot = sum(inv.values())
            target_w = {t: inv[t] / tot for t in chosen}
            pv = cash
            cur_val = {}
            for t, h in holds.items():
                v = h.val if (h.val and ci - h.bar_cal <= 10) else 0.0
                cur_val[t] = h.shares * v; pv += cur_val[t]
            new_holds = {}
            for t, h in holds.items():
                cur = cur_val[t]; tgt = target_w.get(t, 0.0) * pv
                price = h.val if h.val else 0.0
                if tgt <= 0:
                    if cur > 0 and price > 0:
                        fee = cur * COST + SELL_FEE; costs += fee; cash += cur - fee; orders += 1
                else:
                    if cur > tgt and price > 0:
                        sell_val = cur - tgt
                        fee = sell_val * COST + SELL_FEE; costs += fee; cash += sell_val - fee; orders += 1
                        h.shares = tgt / price
                    new_holds[t] = h
            holds = new_holds
            pv2 = cash + sum(h.shares * (h.val or 0.0) for h in holds.values())
            for t in chosen:
                v, bd = px_on(t, d)
                if not v or bd != d:
                    continue
                h = holds.get(t)
                cur = h.shares * v if h else 0.0
                tgt = target_w[t] * pv2
                if tgt > cur:
                    buy_val = min(tgt - cur, cash / (1 + COST) if cash > 0 else 0.0)
                    if buy_val <= 0:
                        continue
                    fee = buy_val * COST; costs += fee; cash -= buy_val + fee; orders += 1
                    if h is None:
                        h = Hold(0.0, d); holds[t] = h; advance(t, h, d, ci)
                    h.shares += buy_val / v
        eq = cash
        for t, h in holds.items():
            if h.val and ci - h.bar_cal <= 10:
                eq += h.shares * h.val
        curve.append([d, round(eq, 4)])
    peak = -1; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    final = curve[-1][1] if curve else START
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "zeroed": sorted(zeroed), "equity_curve": curve,
            "rebalances": len(elig_counts),
            "eligible_min": min(elig_counts) if elig_counts else None,
            "eligible_median": sorted(elig_counts)[len(elig_counts) // 2] if elig_counts else None}

def period_stats(curve, sched_exec_dates):
    """Quarterly (native tempo) period record from the daily equity curve."""
    eq = {d: e for d, e in curve}
    marks = [curve[0]]
    for d in sched_exec_dates:
        if d in eq and d != curve[0][0]:
            marks.append([d, eq[d]])
    if curve[-1][0] != marks[-1][0]:
        marks.append(curve[-1])
    rets = [(d1, e1 / e0 - 1) for (d0, e0), (d1, e1) in zip(marks, marks[1:]) if e0 > 0]
    if not rets:
        return None
    vals = sorted(r for _, r in rets); n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    longest_loss = 0; cur = 0
    for _, r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    import datetime as _dt
    peak = -1; peak_date = None; worst_stretch = 0; worst_span = None
    for d, e in curve:
        if e >= peak:
            if peak_date is not None:
                s = (_dt.date.fromisoformat(d) - _dt.date.fromisoformat(peak_date)).days
                if s > worst_stretch:
                    worst_stretch = s; worst_span = (peak_date, d)
            peak = e; peak_date = d
    tail = (_dt.date.fromisoformat(curve[-1][0]) - _dt.date.fromisoformat(peak_date)).days if peak_date else 0
    if tail > worst_stretch:
        worst_stretch = tail; worst_span = (peak_date, curve[-1][0] + " (still open)")
    return {"periods": n, "pct_positive": round(100 * sum(1 for _, r in rets if r > 0) / n, 1),
            "median_pct": round(median * 100, 2),
            "mean_pct_secondary": round(sum(r for _, r in rets) / n * 100, 2),
            "best_pct": round(max(r for _, r in rets) * 100, 2), "best_end": max(rets, key=lambda x: x[1])[0],
            "worst_pct": round(min(r for _, r in rets) * 100, 2), "worst_end": min(rets, key=lambda x: x[1])[0],
            "longest_losing_run_periods": longest_loss,
            "longest_between_highs_days": worst_stretch, "between_highs_span": worst_span}

def buyhold(start, end):
    days = [d for d in CAL if start <= d <= end]
    sh = (START * (1 - COST)) / SPY[days[0]]
    gross = sh * SPY[days[-1]]
    return round(gross - gross * COST - SELL_FEE, 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def road_result(name, seeds):
    s, e = ROADS[name]
    r = run(s, e)
    twins = [run(s, e, placebo_seed=seed)["final"] for seed in seeds]
    r["spy_buyhold"] = buyhold(s, e)
    r["placebo_finals"] = twins
    r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t) if len(twins) == 20 else None
    exec_dates = [ex for _, ex in rebalance_schedule(s, e) if s <= ex <= e]
    r["quarterly_period_stats"] = period_stats(r["equity_curve"], exec_dates)
    print(name, r["final"], "BH", r["spy_buyhold"], "DD", r["max_dd_pct"], "costs", r["costs"],
          "orders", r["orders"], "placebos_run", len(twins), "zeroed", r["zeroed"],
          "elig", r["eligible_min"], r["eligible_median"], "qstats", r["quarterly_period_stats"], flush=True)
    return r

def main():
    # Usage: run_lowvol_constructed.py <ROAD|FOLDS|ALL> [seedspec e.g. 0-9|10-19|0-19]
    # NOTE: this session's python file writes are EPERM-blocked by a sandbox
    # guard; results are emitted on stdout between markers and written to disk
    # through the file tool by the operator.
    which = sys.argv[1] if len(sys.argv) > 1 else "ALL"
    seedspec = sys.argv[2] if len(sys.argv) > 2 else "0-19"
    lo, hi = (int(x) for x in seedspec.split("-"))
    seeds = list(range(lo, hi + 1))
    out = {"family": "low-volatility", "form": "CONSTRUCTED v12: S&P 500 Low Volatility Index methodology on hunted PIT membership, long-only $100 pot, program costs, no floor",
           "roads": {}}
    if which == "FOLDS":
        folds = {}
        for y in range(2010, 2027):
            s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
            folds[str(y)] = run(s, e)["final"]
        out["year_folds"] = folds
        print("folds", folds, flush=True)
    elif which == "ALL":
        for name in ROADS:
            out["roads"][name] = road_result(name, seeds)
    else:
        out["roads"][which] = road_result(which, seeds)
    print("RESULTS_JSON_BEGIN")
    print(json.dumps(out))
    print("RESULTS_JSON_END")

if __name__ == "__main__":
    main()
