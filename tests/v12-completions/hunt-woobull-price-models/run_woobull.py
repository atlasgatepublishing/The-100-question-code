#!/usr/bin/env python3
"""hunt-woobull-price-models — Woobull price-model bands (Woo/Puell, 2019).
TOPCAP-CEILING (price-only, full history): long unless close >= Top Cap
(= expanding mean of market cap x 35 / supply), CoinMetrics Community data.
CVDD-FLOOR (BGeometrics keyless cvdd, verified 2026-11-22, window
2022-11-22 ->): enter long on close <= CVDD, exit on close >= Top Cap.
Chassis per frozen spec: $100, long-or-cash, signal day-t close earns
t->t+1 (close-to-close), costs 0.60%/side. NATIVE no floor; V9 -15% plain
floor on daily closes (breach -> out at next close, 90-day halt, second
breach ends). Bar: BTC buy-and-hold net of one buy + one sell."""
import json, os, random, statistics, urllib.request
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_core.py")).read())

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
COST = 0.006

def fetch_cm():
    cache = os.path.join(DATA, "cm_btc_topcap_inputs.json")
    if os.path.exists(cache): return json.load(open(cache))
    rows = {}
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=CapMrktCurUSD,SplyCur,PriceUSD&page_size=10000"
           "&start_time=2010-01-01T00:00:00Z&end_time=2026-11-21T00:00:00Z")
    while url:
        with urllib.request.urlopen(url, timeout=90) as r:
            j = json.load(r)
        for rec in j["data"]:
            d = rec["time"][:10]
            if all(rec.get(k) for k in ("CapMrktCurUSD", "SplyCur", "PriceUSD")):
                rows[d] = {"cap": float(rec["CapMrktCurUSD"]), "sply": float(rec["SplyCur"]),
                           "px": float(rec["PriceUSD"])}
        url = j.get("next_page_url")
    out = [[d, rows[d]["cap"], rows[d]["sply"], rows[d]["px"]] for d in sorted(rows)]
    json.dump(out, open(cache, "w"))
    return out

def fetch_cvdd():
    cache = os.path.join(DATA, "bgeo_cvdd.json")
    if os.path.exists(cache): return json.load(open(cache))
    with urllib.request.urlopen("https://api.bgeometrics.com/v1/cvdd", timeout=90) as r:
        j = json.load(r)
    out = [[rec["d"], float(rec["v"] if "v" in rec else rec["cvdd"])] for rec in j]
    out.sort()
    json.dump(out, open(cache, "w"))
    return out

def fetch_variant(endpoint):
    try:
        with urllib.request.urlopen(f"https://api.bgeometrics.com/v1/{endpoint}", timeout=60) as r:
            j = json.load(r)
        out = []
        for rec in j:
            v = rec.get("v", rec.get(endpoint.replace("-", "_")))
            if v is None:
                v = [x for k, x in rec.items() if k not in ("d", "unixTs")][0]
            out.append([rec["d"], float(v)])
        out.sort()
        return out
    except Exception as e:
        return {"error": str(e)}

def build_series():
    cm = fetch_cm()
    dates = [r[0] for r in cm]; px = [r[3] for r in cm]
    cap = [r[1] for r in cm]; sply = [r[2] for r in cm]
    topcap = []
    run = 0.0
    for i in range(len(cm)):
        run += cap[i]
        avg = run / (i + 1)
        topcap.append(avg * 35.0 / sply[i])
    return dates, px, topcap

def simulate(dates, px, pos, start, end, chassis=False):
    """pos[t] decided at close t, earns t->t+1. Switch cost at close t."""
    idx = [i for i, d in enumerate(dates) if d >= start and d <= end]
    if len(idx) < 2: return None
    eq = START; curve = []
    cur = pos[idx[0]-1] if idx[0] > 0 else 0
    if cur == 1: eq *= (1 - COST)
    ep_start, halts, halt_until, ended = eq, 0, None, False
    invested = 0
    for n, i in enumerate(idx):
        if halt_until is not None and dates[i] >= halt_until:
            halt_until = None; ep_start = eq
        if i + 1 < len(dates):
            nxt = pos[i]
            if chassis and (halt_until is not None or ended): nxt = 0
            if nxt != cur:
                eq *= (1 - COST); cur = nxt
                if cur == 1: ep_start = eq
            if cur == 1:
                eq *= px[i+1] / px[i]; invested += 1
        curve.append([dates[i], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1
            if cur == 1: eq *= (1 - COST); cur = 0
            if halts == 1:
                halt_until = date.fromordinal(date.fromisoformat(dates[i]).toordinal() + 90).isoformat()
            else: ended = True
    if cur == 1: eq *= (1 - COST)
    curve[-1] = [dates[idx[-1]], round(eq, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(eq, 2), "max_dd_pct": round(maxdd*100, 2),
            "invested_pct": round(100.0*invested/max(len(idx)-1, 1), 1),
            "halts": halts, "equity_curve": curve}

def bh(dates, px, start, end):
    idx = [i for i, d in enumerate(dates) if d >= start and d <= end]
    eq = START * (1 - COST)
    curve = [[dates[i], round(eq * px[i] / px[idx[0]], 4)] for i in idx]
    final = eq * px[idx[-1]] / px[idx[0]] * (1 - COST)
    curve[-1] = [dates[idx[-1]], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def main():
    dates, px, topcap = build_series()
    first_tc = dates[0]
    out = {"family": "hunt-woobull-price-models (Woobull CVDD / Top Cap bands, Woo & Puell 2019)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-crypto)",
           "honesty_label": "Models published; position rules CONSTRUCTED per frozen spec; candidate-grade ceiling",
           "data": {"topcap_inputs": "CoinMetrics Community (CapMrktCurUSD, SplyCur, PriceUSD) — FREE, full history",
                    "cvdd": "BGeometrics keyless cvdd endpoint — VERIFIED answering keyless 2026-11-22; window as returned",
                    "fences": "BTC drawdowns -77% to -94%; -15% floor can gap through in a 24/7 market; wash-trading caveat on reference prices"},
           "holdings_grid": "NOT-APPLICABLE — BTC single-asset band system, no selection",
           "series_range": f"{dates[0]} -> {dates[-1]}", "topcap_first_computable": first_tc}
    # TOPCAP-CEILING positions
    pos_tc = [0 if px[i] >= topcap[i] else 1 for i in range(len(dates))]
    windows = {"FULL": (first_tc, "2026-11-20"), "DESIGN": (first_tc, "2022-12-31"),
               "CONT": ("2019-01-01", "2026-11-20"), "VALIDATION": ("2023-01-01", "2026-11-20")}
    tc = {"rule": "long unless close >= Top Cap (35x expanding-mean market cap / supply); starts long",
          "days_at_or_above_topcap_total": sum(1 for i in range(len(dates)) if px[i] >= topcap[i]),
          "windows": {}}
    for name, (s, e) in windows.items():
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate(dates, px, pos_tc, s, e, chassis=ch)
            rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
        b = bh(dates, px, s, e)
        rec["bar_btc_hold"] = {"final": b["final"], "max_dd_pct": b["max_dd_pct"],
                               "period_stats_monthly": period_stats(b["equity_curve"], "monthly")}
        mults = {}
        for m in (0.7, 0.85, 1.15, 1.3):
            tcx = [t * m for t in topcap]
            posx = [0 if px[i] >= tcx[i] else 1 for i in range(len(dates))]
            mults[str(m)] = simulate(dates, px, posx, s, e)["final"]
        rec["placebo_multiplier_shifts"] = mults
        tc["windows"][name] = rec
        print(f"TOPCAP {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} bar ${b['final']} shifts {mults}", flush=True)
    out["topcap_ceiling"] = tc
    # CVDD-FLOOR
    cvdd = fetch_cvdd()
    cv = {d: v for d, v in cvdd}
    out["cvdd_window"] = f"{cvdd[0][0]} -> {cvdd[-1][0]} ({len(cvdd)} days)"
    print("CVDD window:", out["cvdd_window"], flush=True)
    def cvdd_positions(constant=6_000_000):
        scale = 6_000_000 / constant
        pos = []; state = 0
        for i, d in enumerate(dates):
            if d in cv:
                v = cv[d] * scale
                if state == 0 and px[i] <= v: state = 1
                elif state == 1 and px[i] >= topcap[i]: state = 0
            pos.append(state)
        return pos
    s_cv = max(cvdd[0][0], "2022-11-22"); e_cv = min(cvdd[-1][0], "2026-11-20")
    pos_cv = cvdd_positions()
    rec = {}
    for form, ch in (("native", False), ("house_v9", True)):
        r = simulate(dates, px, pos_cv, s_cv, e_cv, chassis=ch)
        rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
    b = bh(dates, px, s_cv, e_cv)
    rec["bar_btc_hold"] = {"final": b["final"], "max_dd_pct": b["max_dd_pct"],
                           "period_stats_monthly": period_stats(b["equity_curve"], "monthly")}
    seeds = []
    rng = random.Random(20261122)
    for k in range(20):
        K = rng.uniform(4_000_000, 8_000_000)
        seeds.append(simulate(dates, px, cvdd_positions(K), s_cv, e_cv)["final"])
    rec["placebo_constant_seeds"] = {"seed_finals": seeds,
                                     "beaten_of_20": sum(1 for p in seeds if rec["native"]["final"] > p),
                                     "design": "20 seeds, CVDD calibration constant ~ U[4M, 8M]; published 6M is the center"}
    rec["days_long"] = sum(1 for i, d in enumerate(dates) if s_cv <= d <= e_cv and pos_cv[i] == 1)
    out["cvdd_floor"] = {"window": f"{s_cv} -> {e_cv}", **rec}
    print(f"CVDD-FLOOR: native ${rec['native']['final']} house ${rec['house_v9']['final']} bar ${b['final']} placebos {rec['placebo_constant_seeds']['beaten_of_20']}/20 days_long {rec['days_long']}", flush=True)
    # Balanced / Delta variants: probe BGeometrics endpoints
    probes = {}
    for ep in ("balanced-price", "delta-price", "delta-cap"):
        probes[ep] = fetch_variant(ep)
    out["balanced_delta_probe"] = {k: (f"{len(v)} rows {v[0][0]} -> {v[-1][0]}" if isinstance(v, list) else v)
                                   for k, v in probes.items()}
    print("probes:", out["balanced_delta_probe"], flush=True)
    for ep, v in probes.items():
        if isinstance(v, list) and len(v) > 100:
            vv = {d: x for d, x in v}
            pos = []; state = 0
            for i, d in enumerate(dates):
                if d in vv:
                    if state == 0 and px[i] <= vv[d]: state = 1
                    elif state == 1 and px[i] >= topcap[i]: state = 0
                pos.append(state)
            s2 = max(v[0][0], "2022-11-22"); e2 = min(v[-1][0], "2026-11-20")
            r = simulate(dates, px, pos, s2, e2)
            b2 = bh(dates, px, s2, e2)
            out.setdefault("named_variants", {})[ep] = {
                "window": f"{s2} -> {e2}", "native_final": r["final"], "bar_btc_hold": b2["final"],
                "days_long": sum(1 for i, d in enumerate(dates) if s2 <= d <= e2 and pos[i] == 1),
                "label": "NAMED VARIANT (Balanced/Delta leg) — same constructed band-pair chassis"}
            print(f"VARIANT {ep}: native ${r['final']} bar ${b2['final']}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
