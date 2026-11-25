#!/usr/bin/env python3
"""Run engine — gap-a6-div-initiation v12 (CONSTRUCTED system, frozen in
CONSTRUCTION-SPEC.md). $100 pot, 1/5 slices cap 5, entry close of next
trading day after declaration (fallback: close of day before first ex-date),
holds 12m (primary) / 36m (secondary), costs 0.10%/side + $0.01/share sell,
plain -15% floor + 90d sit-out + episode-2 floor, second halt ends run.
Placebos: 20 seeds random universe names on same dates. Shifted control:
declarations +182 days. Prices: Yahoo daily adj bars cached in ./data.
Listing-age fence (>=24 months of price history before first ex-date,
Boehme-Sorescu) applied here where price history is known.
"""
import json, os, time, calendar, urllib.request, random, statistics
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data"); os.makedirs(DATA, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
END = "2026-11-20"
WINDOWS = {"DECADE": ("2016-11-21", END), "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END)}

_bars = {}
def bars(ticker):
    # CACHE-ONLY (2026-11-22): Yahoo throttled the bulk pull (HTTP error
    # pages were saved by an earlier fetch path before parsing — those
    # poisoned files are detected here by parse failure and treated as
    # 'no tape'). No network calls in the run itself. All event tickers
    # and SPY hold valid tapes; the placebo pool is therefore the common
    # names with a valid cached tape (documented in RESULTS.md).
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
            ratio = a / c if c else 1.0
            o = q["open"][i]
            out.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                        "o": (o * ratio if o else a), "c": a})
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

def spy_curve(s, e):
    bl = bars("SPY"); i0 = idx_on_or_after(bl, s); i1 = idx_on_or_after(bl, e)
    if i1 is None: i1 = len(bl) - 1
    return bl, i0, i1

def spy_final(s, e):
    bl, i0, i1 = spy_curve(s, e)
    return round(100.0 * bl[i1]["c"] / bl[i0]["c"], 2)

def simulate(events, s, e, hold_m, spybl):
    """events: list of {ticker, entry_date}. Returns run dict with curve."""
    cal = [b["d"] for b in spybl if s <= b["d"] <= e]
    if not cal: return None
    calset = {d: i for i, d in enumerate(cal)}
    by_entry = {}
    for ev in events:
        if ev["entry"] in calset: by_entry.setdefault(ev["entry"], []).append(ev)
    cash, positions, costs, orders = 100.0, [], 0.0, 0
    ep_start, halts, halted_until, second = 100.0, 0, None, False
    curve = []
    pending_liq = False
    for d in cal:
        bl_today = {}
        def price(t, field="c"):
            bl = bars(t)
            if bl is None: return None
            i = idx_on_or_after(bl, d)
            if i is None: return None
            if bl[i]["d"] == d: return bl[i][field]
            return bl[i - 1]["c"] if i > 0 and field == "c" else None
        # floor liquidation at open after breach flagged yesterday
        if pending_liq:
            for p in list(positions):
                px = price(p["t"], "o") or price(p["t"])
                if px:
                    proceeds = p["sh"] * px; fee = proceeds * 0.001 + 0.01 * p["sh"]
                    cash += proceeds - fee; costs += fee; orders += 1
                positions.remove(p)
            pending_liq = False
            halts += 1
            if halts >= 2: second = True
            halted_until = (dt.date.fromisoformat(d) + dt.timedelta(days=90)).isoformat()
            ep_start = cash
            curve.append([d, round(cash, 2)])
            if second: break
            continue
        in_sitout = halted_until and d < halted_until
        # exits
        for p in list(positions):
            if d >= p["exit"]:
                px = price(p["t"])
                if px:
                    proceeds = p["sh"] * px; fee = proceeds * 0.001 + 0.01 * p["sh"]
                    cash += proceeds - fee; costs += fee; orders += 1
                positions.remove(p)
        # entries
        if not in_sitout:
            for ev in by_entry.get(d, []):
                if len(positions) >= 5: continue
                marked = cash + sum(p["sh"] * (price(p["t"]) or 0) for p in positions)
                target = marked / 5.0
                if cash < target:
                    need = target - cash
                    tot = sum(p["sh"] * (price(p["t"]) or 0) for p in positions)
                    for p in list(positions):
                        px = price(p["t"])
                        if not px or tot <= 0: continue
                        sell_val = min(p["sh"] * px, need * (p["sh"] * px / tot) * 1.02)
                        sh = sell_val / px
                        fee = sell_val * 0.001 + 0.01 * sh
                        cash += sell_val - fee; costs += fee; orders += 1
                        p["sh"] -= sh
                        if p["sh"] <= 1e-9: positions.remove(p)
                px = price(ev["ticker"])
                if not px: continue
                buy = min(target, cash / 1.001)
                if buy <= 0: continue
                fee = buy * 0.001; sh = buy / px
                cash -= buy + fee; costs += fee; orders += 1
                positions.append({"t": ev["ticker"], "sh": sh,
                                  "exit": add_months(d, hold_m)})
        # window-end liquidation handled after loop
        value = cash + sum(p["sh"] * (price(p["t"]) or 0) for p in positions)
        curve.append([d, round(value, 2)])
        if not in_sitout and value <= 0.85 * ep_start and positions:
            pending_liq = True
        elif not in_sitout and value <= 0.85 * ep_start and not positions and halts == 0:
            pass  # cash-only cannot breach further; floor applies to marked pot only when invested
    # liquidate at end
    if positions and not second:
        d = cal[-1]
        for p in list(positions):
            bl = bars(p["t"]); px = bl[-1]["c"] if bl else None
            i = idx_on_or_after(bl, d) if bl else None
            if bl and i is not None and i > 0 and bl[i]["d"] != d: px = bl[i - 1]["c"]
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
            "halts": halts, "restart": halts == 1, "second_halt": second, "curve": curve}

def entry_exit(ticker, decl, first_ex, hold_m, spybl):
    bl = bars(ticker)
    if bl is None: return None
    if decl:
        i = idx_on_or_after(spybl, decl)
        if i is None or i + 1 >= len(spybl): return None
        entry = spybl[i + 1]["d"] if spybl[i]["d"] > decl else spybl[i]["d"]
        # entry = close of next trading day AFTER declaration date
        j = idx_on_or_after(spybl, decl)
        while j < len(spybl) and spybl[j]["d"] <= decl: j += 1
        if j >= len(spybl): return None
        entry = spybl[j]["d"]
    else:
        j = idx_on_or_after(spybl, first_ex)
        if j is None or j == 0: return None
        entry = spybl[j - 1]["d"]
    return {"ticker": ticker, "entry": entry, "exit": add_months(entry, hold_m)}

def main():
    import sys as _sys
    _emit = "--emit" in _sys.argv
    _real_stdout = _sys.stdout
    if _emit:
        _sys.stdout = _sys.stderr  # progress prints stay off the JSON pipe
    cen = json.load(open(os.path.join(ROOT, "census_events.json")))
    common = json.load(open(os.path.join(ROOT, "census_events_common.json")))
    classes = json.load(open(os.path.join(ROOT, "security_classes.json")))
    universe = sorted(t for t, v in classes.items() if v["class"] == "COMMON")
    cen_events = common["kept"]
    spybl = bars("SPY")
    # listing-age fence + entry construction
    raw_events, fenced = [], []
    for ev in cen_events:
        if ev["status"] != "QUALIFYING": continue
        bl = bars(ev["ticker"])
        if bl is None:
            fenced.append({**ev, "fence": "no price history"}); continue
        age_days = (dt.date.fromisoformat(ev["first_ex"]) - dt.date.fromisoformat(bl[0]["d"])).days
        if age_days < 730:
            fenced.append({**ev, "fence": f"listed only {age_days}d before event (<24m)"}); continue
        ee = entry_exit(ev["ticker"], ev["decl"], ev["first_ex"], 12, spybl)
        if ee is None:
            fenced.append({**ev, "fence": "no tradable entry"}); continue
        raw_events.append({**ev, "entry": ee["entry"], "dating": "declaration" if ev["decl"] else "pre-ex fallback"})
    print(f"qualifying after fences: {len(raw_events)}; fenced out: {len(fenced)}")
    for f in fenced: print("  FENCED:", f["ticker"], f["first_ex"], f["fence"])
    event_tickers = {e["ticker"] for e in raw_events}
    results = {"slug": "gap-a6-div-initiation", "constructed": True,
               "census": {"universe_size": cen["universe_size"],
                          "common_universe_size": len(universe), "n_events": len(raw_events),
                          "fenced_out": fenced, "events": raw_events},
               "spy": {}, "runs": {}, "per_event": []}
    for wname, (s, e) in WINDOWS.items():
        results["spy"][wname] = spy_final(s, e)
    # per-event standalone (DECADE entries, HOLD12)
    for ev in raw_events:
        if not (WINDOWS["DECADE"][0] <= ev["entry"] <= WINDOWS["DECADE"][1]): continue
        ee = entry_exit(ev["ticker"], ev["decl"], ev["first_ex"], 12, spybl)
        run = simulate([ee], max(WINDOWS["DECADE"][0], ee["entry"]), min(ee["exit"], END), 12, spybl)
        bl, i0 = bars(ev["ticker"]), None
        si0 = idx_on_or_after(spybl, ee["entry"]); si1 = idx_on_or_after(spybl, min(ee["exit"], END))
        if si1 is None: si1 = len(spybl) - 1
        spy_ret = spybl[si1]["c"] / spybl[si0]["c"] - 1
        net = (run["final"] / 100.0 - 1) if run else None
        results["per_event"].append({**ev, "entry_used": ee["entry"],
            "net_pct": round(net * 100, 2) if net is not None else None,
            "spy_pct": round(spy_ret * 100, 2),
            "excess_pp": round((net - spy_ret) * 100, 2) if net is not None else None})
    pe = [p["excess_pp"] for p in results["per_event"] if p["excess_pp"] is not None]
    if pe:
        results["per_event_stats"] = {"n": len(pe), "mean_excess_pp": round(statistics.mean(pe), 2),
            "median_excess_pp": round(statistics.median(pe), 2),
            "share_beating_spy": round(sum(1 for x in pe if x > 0) / len(pe), 3)}
    pool = [t for t in universe if t not in event_tickers]
    for hold_m, hname in ((12, "HOLD12"), (36, "HOLD36")):
        results["runs"][hname] = {}
        for wname, (s, e) in WINDOWS.items():
            evs = []
            for ev in raw_events:
                ee = entry_exit(ev["ticker"], ev["decl"], ev["first_ex"], hold_m, spybl)
                if ee and s <= ee["entry"] <= e: evs.append(ee)
            run = simulate(evs, s, e, hold_m, spybl)
            # placebos
            twin_finals = []
            for seed in range(1, 21):
                rng = random.Random(1000 * seed + hold_m)
                pev, used = [], set()
                ok = True
                for ev in evs:
                    cands = [t for t in pool if t not in used]
                    rng.shuffle(cands)
                    picked = None
                    cover_to = min(ev["exit"], e)  # holds truncate at window end; coverage is owed only to there
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
                tr = simulate(pev, s, e, hold_m, spybl)
                twin_finals.append(tr["final"] if tr else None)
            beaten = sum(1 for f in twin_finals if f is not None and run and run["final"] > f)
            valid = sum(1 for f in twin_finals if f is not None)
            # shifted-date control (+182d)
            sev = []
            for ev in evs:
                nd = (dt.date.fromisoformat(ev["entry"]) + dt.timedelta(days=182)).isoformat()
                if nd <= e: sev.append({"ticker": ev["ticker"], "entry": nd, "exit": add_months(nd, hold_m)})
            srun = simulate(sev, s, e, hold_m, spybl) if sev else None
            results["runs"][hname][wname] = {
                "events_traded": len(evs), "run": run,
                "placebo_beaten": f"{beaten}/{valid}", "placebo_finals": twin_finals,
                "shifted_final": srun["final"] if srun else None,
                "shifted_events": len(sev)}
            print(f"{hname} {wname}: final={run['final'] if run else None} events={len(evs)} "
                  f"placebo {beaten}/{valid} shifted={srun['final'] if srun else None}", flush=True)
    # Output split per program convention (summary + per-cell files with
    # curves). --emit NAME prints one output file's JSON to stdout (the
    # caller pipes it through chunkwriter.py — this workspace throttles
    # ordinary writes, see chunkwriter docstring).
    outputs = {}
    for hname, wins in results["runs"].items():
        for wname, cell in wins.items():
            run = dict(cell.get("run") or {})
            curve = run.pop("curve", None)
            outputs[f"cells/{hname}_{wname}.json"] = {
                "hold": hname, "window": wname, "events_traded": cell["events_traded"],
                "run": run, "curve": curve, "placebo_beaten": cell["placebo_beaten"],
                "placebo_finals": cell["placebo_finals"],
                "shifted_final": cell["shifted_final"], "shifted_events": cell["shifted_events"]}
    outputs["results.json"] = results
    if _emit:
        name = _sys.argv[_sys.argv.index("--emit") + 1]
        _sys.stdout = _real_stdout
        _sys.stdout.write(json.dumps(outputs[name]))
        return
    for name, obj in outputs.items():
        path = os.path.join(ROOT, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(obj, open(path, "w"))
    print("saved results.json + cells/")

if __name__ == "__main__":
    main()
