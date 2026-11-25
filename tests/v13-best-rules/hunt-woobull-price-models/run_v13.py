#!/usr/bin/env python3
"""V13 best-rules: Woobull price models as DIALS (see BEST-RULES-SPEC.md, frozen first).
Leg A: w = clip(1 - Price/TopCap, 0, 1). Leg B (2022-11-22-> only):
w = clip((TopCap-Price)/(TopCap-CVDD), 0, 1); Balanced Price named variant floor.
Monthly rebalance, 5pp no-trade deadband, 0.60%/side on traded notional,
final liquidation 0.60% on held fraction. $100 pots. Data read from the
v12 folder's caches (read-only shared inputs)."""
import json, os, random, statistics, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-woobull-price-models")
exec(open(os.path.join(V12, "engine_core.py")).read())  # period_stats, START
COST = 0.006
DEADBAND = 0.05

cm = json.load(open(os.path.join(V12, "data", "cm_btc_topcap_inputs.json")))
dates = [r[0] for r in cm]; cap = [r[1] for r in cm]; sply = [r[2] for r in cm]; px = [r[3] for r in cm]
topcap, run = [], 0.0
for i in range(len(cm)):
    run += cap[i]; topcap.append(run / (i + 1) * 35.0 / sply[i])
pxd = dict(zip(dates, px))

cvdd_rows = json.load(open(os.path.join(V12, "data", "bgeo_cvdd.json")))
cvdd = dict(cvdd_rows)

def fetch_variant(endpoint):
    cache = os.path.join(HERE, f"cache_{endpoint}.json")
    if os.path.exists(cache):
        return json.load(open(cache))
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
        json.dump(out, open(cache, "w"))
        return out
    except Exception as e:
        return {"error": str(e)}

def clip(x): return max(0.0, min(1.0, x))

weightsA = [clip(1.0 - px[i] / topcap[i]) for i in range(len(dates))]
def band_weights(floor):
    w = []
    for i, d in enumerate(dates):
        f = floor.get(d)
        if f is None or topcap[i] <= f:
            w.append(weightsA[i])  # no floor reading yet: fall back to Leg A coordinate
        else:
            w.append(clip((topcap[i] - px[i]) / (topcap[i] - f)))
    return w
weightsB = band_weights(cvdd)

def simulate_dial(weights, start, end, shift_seed=None):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if len(idx) < 2: return None
    wpath = list(weights)
    if shift_seed is not None:
        seg = [weights[i] for i in idx]
        rng = random.Random(shift_seed)
        k = rng.randrange(1, len(seg))
        seg = seg[k:] + seg[:k]
        for j, i in enumerate(idx): wpath[i] = seg[j]
    # entry weight: last reading before road start
    pre = [i for i, d in enumerate(dates) if d < start]
    w = wpath[pre[-1]] if pre else wpath[idx[0]]
    eq = START * (1 - COST * w)  # initial purchase cost on invested fraction
    curve = []; trades = 0; cost_paid = START * COST * w
    cur_month = None
    for n, i in enumerate(idx):
        # monthly rebalance at this close (first day of a new month in-road), earns after
        m = dates[i][:7]
        if cur_month is not None and m != cur_month:
            tgt = wpath[i]
            dw = tgt - w
            if abs(dw) >= DEADBAND:
                c = abs(dw) * eq * COST; eq -= c; cost_paid += c; w = tgt; trades += 1
        cur_month = m
        if i + 1 < len(dates) and n + 1 < len(idx):
            eq *= (1 - w + w * px[i + 1] / px[i])
        curve.append([dates[i], round(eq, 4)])
    final = eq * (1 - COST * w); cost_paid += eq * COST * w
    curve[-1] = [dates[idx[-1]], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "rebalances": trades, "costs_paid": round(cost_paid, 2),
            "avg_weight_pct": round(100.0 * statistics.mean(wpath[i] for i in idx), 1),
            "equity_curve": curve, "period_stats_monthly": period_stats(curve, "monthly")}

def bh(start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    eq = START * (1 - COST)
    curve = [[dates[i], round(eq * px[i] / px[idx[0]], 4)] for i in idx]
    final = eq * px[idx[-1]] / px[idx[0]] * (1 - COST)
    curve[-1] = [dates[idx[-1]], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve, "period_stats_monthly": period_stats(curve, "monthly")}

PUBLISHED = {"FULL": 69202358.13, "DESIGN": 19114712.09, "CONT": 1559.91, "VAL": 357.71, "BAND": 100.00}
ROADS = {"FULL": ("2010-07-18", "2026-11-20"), "DESIGN": ("2010-07-18", "2022-12-31"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20"),
         "BAND": ("2022-11-22", "2026-11-20")}

out = {"family": "hunt-woobull-price-models — V13 BEST RULES (dial form)",
       "verdict_ceiling": "CANDIDATE",
       "spec": "BEST-RULES-SPEC.md (frozen before run)",
       "data_labels": ["CURRENT-VINTAGE DATA — point-in-time in execution only (CoinMetrics Community + BGeometrics, no published vintage policy)",
                       "Pre-Apr-2019 graded days are IN-SAMPLE for the published 35x / 6,000,000 calibrations"],
       "chassis": "$100; monthly rebalance; 5pp deadband; 0.60%/side on traded notional; no floor",
       "roads": {}}

for name, (s, e) in ROADS.items():
    rec = {}
    legs = {"legA_topcap_dial": weightsA}
    if name == "BAND":
        legs["legB_fullband_cvdd_dial"] = weightsB
    for leg, wts in legs.items():
        r = simulate_dial(wts, s, e)
        pls = [simulate_dial(wts, s, e, shift_seed=sd)["final"] for sd in range(1, 21)]
        rec[leg] = {**r, "placebo_shift_seeds": {"finals": pls,
                      "median": round(statistics.median(pls), 2),
                      "beaten_of_20": sum(1 for p in pls if r["final"] > p)}}
        print(f"{name} {leg}: ${r['final']} dd {r['max_dd_pct']}% avgw {r['avg_weight_pct']}% rebal {r['rebalances']} placebo beaten {rec[leg]['placebo_shift_seeds']['beaten_of_20']}/20 med ${rec[leg]['placebo_shift_seeds']['median']}", flush=True)
    b = bh(s, e)
    rec["bar_btc_hold"] = b
    rec["published_best_v12"] = PUBLISHED[name]
    out["roads"][name] = rec
    print(f"{name} bar: ${b['final']} dd {b['max_dd_pct']}% published-best ${PUBLISHED[name]}", flush=True)

# Balanced Price named variant (Leg B floor swap) on BAND window
bal = fetch_variant("balanced-price")
if isinstance(bal, list) and len(bal) > 100:
    wbal = band_weights(dict(bal))
    r = simulate_dial(wbal, *ROADS["BAND"])
    out["balanced_price_variant"] = {**r, "label": "NAMED VARIANT — Balanced Price as Leg B floor, BAND window only"}
    print(f"BAND balanced-price variant: ${r['final']}", flush=True)
else:
    out["balanced_price_variant"] = {"label": "endpoint failed this run; closes named as in v12", "probe": bal}
    print("balanced-price probe failed:", bal, flush=True)
out["delta_price_cap"] = "CLOSED — no free source (v12 probe: endpoints 404/500; no free transferred-price history)"

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("DONE")
