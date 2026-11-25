#!/usr/bin/env python3
"""V13 best-rules run: Varadi MCA, construction exactly as catalogued in v12,
chassis = QUARTERLY cadence, NO FLOOR (see BEST-RULES-SPEC.md, frozen first).
Controls: static equal-weight mix (mandatory), buy-hold SPY, 20-seed placebos.
Crisis windows at full size. Writes results.json in the family folder."""
import json, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import (Panel, load_t2, load_etf_json, cadence_days, simulate,
                    period_stats, ROADS_2016, SPY_REF, CHAMP)
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
U = ["SPY", "IWM", "QQQ", "VNQ", "TLT", "EEM", "IEFA", "GLD"]

def etf_panel():
    p = Panel(load_t2("SPY"))
    ds, cs = load_t2("SPY"); p.series["SPY"] = cs[:]
    for s in ["QQQ", "IWM", "IEFA", "EEM", "VNQ", "GLD", "TLT"]:
        p.add(s, load_t2(s))
    return p

_corr_cache = {}
def corr_matrix(p, i, syms, n=126):
    key = (p.dates[i].year, p.dates[i].month, p.dates[i].day, tuple(syms))
    if key in _corr_cache: return _corr_cache[key]
    if i - n < 0: return None
    arr = []
    for s in syms:
        w = p.series[s][i - n:i + 1]
        if any(v is None for v in w): return None
        arr.append([w[k + 1] / w[k] - 1 for k in range(n)])
    m = np.corrcoef(np.array(arr))
    _corr_cache[key] = m
    return m

def mca_fn(p):
    def fn(i):
        m = corr_matrix(p, i, U)
        if m is None: return {}
        pen = []
        for a in range(len(U)):
            vals = [(m[a][b] + 1) / 2 for b in range(len(U)) if b != a]
            pen.append(sum(vals) / len(vals))
        raw = [1.0 / max(x, 0.05) for x in pen]
        tot = sum(raw)
        return {U[a]: raw[a] / tot for a in range(len(U))}
    return fn

def ew_fn(p):
    return lambda i: {s: 1.0 / len(U) for s in U}

def spy_fn(p):
    return lambda i: {"SPY": 1.0}

def slim(r):
    return {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}

def main():
    p = etf_panel()
    out = {"family": "catalog-taa-varadi-mincorr", "program": "v13-best-rules",
           "chassis": "MCA as catalogued; quarterly cadence; no floor",
           "roads": {}, "crisis_windows": {}, "spy_ref_program": SPY_REF,
           "champion_vm": CHAMP}
    dec_q = cadence_days(p.dates, "quarterly")
    dec_m = cadence_days(p.dates, "monthly")
    ridx = engine.road_indices(p, ROADS_2016)

    for rname, idx in ridx.items():
        entry = {}
        # my rules: quarterly, no floor (engine 'native' rulebook = no floor)
        r = simulate(p, idx, dec_q, mca_fn(p), rulebook="native")
        entry["mine"] = slim(r)
        out.setdefault("curves", {})[f"{rname}|mine"] = r["curve"]
        out.setdefault("period_stats", {})[f"{rname}|mine"] = period_stats(r["curve"], p.dates, "monthly")
        # published form, same basis: monthly, no floor
        rp = simulate(p, idx, dec_m, mca_fn(p), rulebook="native")
        entry["published_monthly"] = slim(rp)
        out.setdefault("period_stats", {})[f"{rname}|published"] = period_stats(rp["curve"], p.dates, "monthly")
        # mandatory control: static EW (decide once at road start, never again)
        rs = simulate(p, idx, {idx[0]}, ew_fn(p), rulebook="native")
        entry["static_ew"] = slim(rs)
        out.setdefault("curves", {})[f"{rname}|static_ew"] = rs["curve"]
        out.setdefault("period_stats", {})[f"{rname}|static_ew"] = period_stats(rs["curve"], p.dates, "monthly")
        # buy-hold SPY through same machinery
        ry = simulate(p, idx, {idx[0]}, spy_fn(p), rulebook="native")
        entry["spy_buyhold"] = slim(ry)
        # 20-seed placebos: identical chassis, random EW rotation among same 8
        engine._placebo_pool = (U, 8)
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec_q, mca_fn(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        entry["placebo_finals"] = twins
        entry["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["roads"][rname] = entry
        print(rname, "mine", r["final"], "pub", rp["final"], "staticEW", rs["final"],
              "spy", ry["final"], "placebos_beaten", entry["placebos_beaten"], flush=True)

    # crisis windows: WARM START — each leg is invested well before the window
    # (run begins ~200 days earlier, on a quarterly decision day, so the 126d
    # correlation window is live and the book is fully invested); the window is
    # then measured standalone: $100 at window start -> window-end value, max DD
    # inside the window. A cold start would leave the quarterly leg in cash
    # until the next decision day and fake "protection" it never earned.
    from datetime import timedelta
    def window_stats(curve, a, b):
        seg = [(date.fromisoformat(d), e) for d, e in curve]
        base = None; vals = []
        for d, e in seg:
            if d < a: base = e
            elif d <= b: vals.append(e)
        if base is None: base = seg[0][1]
        peak = base; maxdd = 0.0
        for e in vals:
            peak = max(peak, e)
            if peak > 0: maxdd = max(maxdd, (peak - e) / peak)
        return {"final": round(100.0 * vals[-1] / base, 2) if vals and base else None,
                "max_dd_pct": round(maxdd * 100, 2)}
    windows = {"COVID_2020-02_to_2020-06": (date(2020, 2, 1), date(2020, 6, 30)),
               "BEAR_2022": (date(2022, 1, 1), date(2022, 12, 31)),
               "Q4_2018": (date(2018, 10, 1), date(2019, 3, 31))}
    for wname, (a, b) in windows.items():
        warm = a - timedelta(days=200)
        ext = [i for i, d in enumerate(p.dates) if warm <= d <= b]
        start = next(i for i in ext if i in dec_q)
        ext = [i for i in ext if i >= start]
        w = {}
        for leg, fn, dec in (("mine", mca_fn(p), dec_q),
                             ("static_ew", ew_fn(p), {ext[0]}),
                             ("spy_buyhold", spy_fn(p), {ext[0]})):
            r = simulate(p, ext, dec, fn, rulebook="native")
            w[leg] = window_stats(r["curve"], a, b)
        out["crisis_windows"][wname] = w
        print(wname, {k: (v["final"], v["max_dd_pct"]) for k, v in w.items()}, flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
