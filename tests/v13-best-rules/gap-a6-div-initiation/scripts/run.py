#!/usr/bin/env python3
"""V13 BEST-RULES run — gap-a6-div-initiation. Frozen in BEST-RULES-SPEC.md.
Chassis adapted from v12 scripts/run.py (read-only shared input).
Changes vs v12: FULL DEPLOYMENT equal-weight sizing (no 1/5 slices),
NO floor, HOLD12 only, roads DECADE/CONT/VAL (LONG = named closure).
Prices: v12 folder's validated Yahoo cache, read-only. Cache-only, no network.
Costs 0.10%/side + $0.01/share on sells. Placebos: 20 seeds, same chassis.
"""
import json, os, time, calendar, random, statistics
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a6-div-initiation")
DATA = os.path.join(V12, "data")
END = "2026-11-20"
WINDOWS = {"DECADE": ("2016-11-21", END), "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END)}
HOLD_M = 12

_bars = {}
def bars(ticker):
    if ticker in _bars: return _bars[ticker]
    path = os.path.join(DATA, f"yahoo_{ticker}.json")
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        _bars[ticker] = None; return None
    try:
        j = json.load(open(path))
        res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        out = []
        for i, t in enumerate(ts):
            c = q["close"][i]
            if c is None: continue
            a = adj[i] if adj and adj[i] else c
            out.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "c": a})
        out.sort(key=lambda b: b["d"])
        _bars[ticker] = out; return out
    except Exception:
        _bars[ticker] = None; return None

def idx_on_or_after(bl, d):
    lo, hi = 0, len(bl)
    while lo < hi:
        mid = (lo + hi) // 2
        if bl[mid]["d"] < d: lo = mid + 1
        else: hi = mid
    return lo if lo < len(bl) else None

def add_months(dstr, m):
    d = dt.date.fromisoformat(dstr); y = d.year + (d.month - 1 + m) // 12; mo = (d.month - 1 + m) % 12 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return dt.date(y, mo, day).isoformat()

def spy_final(s, e):
    bl = bars("SPY"); i0 = idx_on_or_after(bl, s); i1 = idx_on_or_after(bl, e)
    if i1 is None: i1 = len(bl) - 1
    return round(100.0 * bl[i1]["c"] / bl[i0]["c"], 2)

def simulate(events, s, e, spybl):
    """Full-deployment equal-weight event book. NO floor."""
    cal = [b["d"] for b in spybl if s <= b["d"] <= e]
    if not cal: return None
    calset = set(cal)
    by_entry = {}
    for ev in events:
        if ev["entry"] in calset: by_entry.setdefault(ev["entry"], []).append(ev)
    cash, positions, costs, orders = 100.0, [], 0.0, 0
    curve = []
    def price(t, d):
        bl = bars(t)
        if bl is None: return None
        i = idx_on_or_after(bl, d)
        if i is None: return None
        if bl[i]["d"] == d: return bl[i]["c"]
        return bl[i - 1]["c"] if i > 0 else None
    for d in cal:
        # exits first
        for p in list(positions):
            if d >= p["exit"]:
                px = price(p["t"], d)
                if px:
                    proceeds = p["sh"] * px; fee = proceeds * 0.001 + 0.01 * p["sh"]
                    cash += proceeds - fee; costs += fee; orders += 1
                positions.remove(p)
        # entries: full deployment, equal weight across post-entry book
        new_evs = by_entry.get(d, [])
        if new_evs:
            marked = cash + sum(p["sh"] * (price(p["t"], d) or 0) for p in positions)
            k = len(positions) + len(new_evs)
            target = marked / k if k else 0.0
            # trim existing positions above target
            for p in list(positions):
                px = price(p["t"], d)
                if not px: continue
                val = p["sh"] * px
                if val > target:
                    sell_val = val - target
                    sh = sell_val / px
                    fee = sell_val * 0.001 + 0.01 * sh
                    cash += sell_val - fee; costs += fee; orders += 1
                    p["sh"] -= sh
                    if p["sh"] <= 1e-9: positions.remove(p)
            remaining = len(new_evs)
            for ev in new_evs:
                px = price(ev["ticker"], d)
                remaining -= 1
                if not px: continue
                buy = min(target, cash / 1.001) if remaining == 0 else min(target, (cash / 1.001))
                if buy <= 0: continue
                fee = buy * 0.001; sh = buy / px
                cash -= buy + fee; costs += fee; orders += 1
                positions.append({"t": ev["ticker"], "sh": sh, "exit": add_months(d, HOLD_M)})
        value = cash + sum(p["sh"] * (price(p["t"], d) or 0) for p in positions)
        curve.append([d, round(value, 2)])
    if positions:
        d = cal[-1]
        for p in list(positions):
            px = price(p["t"], d)
            if px:
                proceeds = p["sh"] * px; fee = proceeds * 0.001 + 0.01 * p["sh"]
                cash += proceeds - fee; costs += fee; orders += 1
            positions.remove(p)
        curve[-1] = [cal[-1], round(cash, 2)]
    final = curve[-1][1] if curve else cash
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    yrs = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days / 365.25
    return {"start": s, "end": e, "final": round(final, 2),
            "cagr_pct": round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None,
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "curve": curve}

def entry_exit(ticker, decl, first_ex, spybl):
    if decl:
        j = idx_on_or_after(spybl, decl)
        while j is not None and j < len(spybl) and spybl[j]["d"] <= decl: j += 1
        if j is None or j >= len(spybl): return None
        entry = spybl[j]["d"]
    else:
        j = idx_on_or_after(spybl, first_ex)
        if j is None or j == 0: return None
        entry = spybl[j - 1]["d"]
    return {"ticker": ticker, "entry": entry, "exit": add_months(entry, HOLD_M)}

def period_stats(curve):
    # monthly distribution from daily curve
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        rets.append((k, months[k] / prev - 1)); prev = months[k]
    vals = [r for _, r in rets]
    pos = sum(1 for r in vals if r > 0)
    # longest losing streak (consecutive months <= 0 counts as non-positive; use <0 for losing)
    streak = cur = 0
    for r in vals:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months)
    peak = -1; since = longest = 0
    for k in keys:
        if months[k] > peak: peak = months[k]; since = 0
        else: since += 1
        longest = max(longest, since)
    return {"months": len(vals), "median_month_pct": round(statistics.median(vals) * 100, 2),
            "share_positive_pct": round(pos / len(vals) * 100, 1) if vals else None,
            "best_month": [max(rets, key=lambda x: x[1])[0], round(max(rets, key=lambda x: x[1])[1] * 100, 2)],
            "worst_month": [min(rets, key=lambda x: x[1])[0], round(min(rets, key=lambda x: x[1])[1] * 100, 2)],
            "longest_losing_streak_months": streak,
            "longest_stretch_between_new_highs_months": longest,
            "mean_month_pct_SECONDARY": round(statistics.mean(vals) * 100, 2) if vals else None}

def main():
    common = json.load(open(os.path.join(V12, "census_events_common.json")))
    classes = json.load(open(os.path.join(V12, "security_classes.json")))
    universe = sorted(t for t, v in classes.items() if v["class"] == "COMMON")
    spybl = bars("SPY")
    raw_events, fenced = [], []
    for ev in common["kept"]:
        if ev["status"] != "QUALIFYING": continue
        bl = bars(ev["ticker"])
        if bl is None:
            fenced.append({**ev, "fence": "no price history"}); continue
        age_days = (dt.date.fromisoformat(ev["first_ex"]) - dt.date.fromisoformat(bl[0]["d"])).days
        if age_days < 730:
            fenced.append({**ev, "fence": f"listed only {age_days}d before event (<24m)"}); continue
        ee = entry_exit(ev["ticker"], ev["decl"], ev["first_ex"], spybl)
        if ee is None:
            fenced.append({**ev, "fence": "no tradable entry"}); continue
        raw_events.append({**ev, "entry": ee["entry"], "exit": ee["exit"],
                           "dating": "declaration" if ev["decl"] else "pre-ex fallback"})
    print(f"qualifying after fences: {len(raw_events)}; fenced out: {len(fenced)}", flush=True)
    event_tickers = {e["ticker"] for e in raw_events}
    results = {"slug": "gap-a6-div-initiation", "program": "v13-best-rules",
               "spec": "full deployment equal-weight, HOLD12, NO floor",
               "long_road": "NAMED CLOSURE: census cannot be built point-in-time before 2016 EDGAR frames",
               "census": {"common_universe_size": len(universe), "n_events": len(raw_events),
                          "fenced_out": fenced, "events": raw_events},
               "spy": {}, "runs": {}, "per_event": []}
    for wname, (s, e) in WINDOWS.items():
        results["spy"][wname] = spy_final(s, e)
    # per-event standalone (DECADE entries)
    for ev in raw_events:
        s0, e0 = WINDOWS["DECADE"]
        if not (s0 <= ev["entry"] <= e0): continue
        run = simulate([{"ticker": ev["ticker"], "entry": ev["entry"], "exit": ev["exit"]}],
                       max(s0, ev["entry"]), min(ev["exit"], END), spybl)
        si0 = idx_on_or_after(spybl, ev["entry"]); si1 = idx_on_or_after(spybl, min(ev["exit"], END))
        if si1 is None: si1 = len(spybl) - 1
        spy_ret = spybl[si1]["c"] / spybl[si0]["c"] - 1
        net = (run["final"] / 100.0 - 1) if run else None
        results["per_event"].append({"ticker": ev["ticker"], "kind": ev["kind"], "first_ex": ev["first_ex"],
            "entry_used": ev["entry"],
            "net_pct": round(net * 100, 2) if net is not None else None,
            "spy_pct": round(spy_ret * 100, 2),
            "excess_pp": round((net - spy_ret) * 100, 2) if net is not None else None})
    pe = [p["excess_pp"] for p in results["per_event"] if p["excess_pp"] is not None]
    if pe:
        results["per_event_stats"] = {"n": len(pe), "mean_excess_pp": round(statistics.mean(pe), 2),
            "median_excess_pp": round(statistics.median(pe), 2),
            "share_beating_spy": round(sum(1 for x in pe if x > 0) / len(pe), 3)}
    pool = [t for t in universe if t not in event_tickers]
    for wname, (s, e) in WINDOWS.items():
        evs = [{"ticker": ev["ticker"], "entry": ev["entry"], "exit": ev["exit"]}
               for ev in raw_events if s <= ev["entry"] <= e]
        run = simulate(evs, s, e, spybl)
        twin_finals = []
        for seed in range(1, 21):
            rng = random.Random(1000 * seed + HOLD_M)
            pev, used, ok = [], set(), True
            for ev in evs:
                cands = [t for t in pool if t not in used]
                rng.shuffle(cands)
                picked = None
                cover_to = min(ev["exit"], e)
                for t in cands[:60]:
                    bl = bars(t)
                    if bl is None: continue
                    i0 = idx_on_or_after(bl, ev["entry"]); i1 = idx_on_or_after(bl, cover_to)
                    if i0 is not None and bl[0]["d"] <= ev["entry"] and (i1 is not None or bl[-1]["d"] >= cover_to):
                        picked = t; break
                if picked is None: ok = False; break
                used.add(picked)
                pev.append({"ticker": picked, "entry": ev["entry"], "exit": ev["exit"]})
            if not ok: twin_finals.append(None); continue
            tr = simulate(pev, s, e, spybl)
            twin_finals.append(tr["final"] if tr else None)
        beaten = sum(1 for f in twin_finals if f is not None and run and run["final"] > f)
        valid = sum(1 for f in twin_finals if f is not None)
        sev = []
        for ev in evs:
            nd = (dt.date.fromisoformat(ev["entry"]) + dt.timedelta(days=182)).isoformat()
            if nd <= e: sev.append({"ticker": ev["ticker"], "entry": nd, "exit": add_months(nd, HOLD_M)})
        srun = simulate(sev, s, e, spybl) if sev else None
        cell = {"events_traded": len(evs), "run": {k: v for k, v in run.items() if k != "curve"},
                "curve": run["curve"], "placebo_beaten": f"{beaten}/{valid}",
                "placebo_finals": twin_finals,
                "placebo_median": round(statistics.median([f for f in twin_finals if f is not None]), 2) if valid else None,
                "shifted_final": srun["final"] if srun else None, "shifted_events": len(sev)}
        if wname == "DECADE": cell["period_stats"] = period_stats(run["curve"])
        results["runs"][wname] = cell
        print(f"{wname}: final={run['final']} maxDD={run['max_dd_pct']} events={len(evs)} "
              f"placebo {beaten}/{valid} shifted={srun['final'] if srun else None}", flush=True)
    json.dump(results, open(os.path.join(ROOT, "results.json"), "w"))
    print("saved results.json")

if __name__ == "__main__":
    main()
