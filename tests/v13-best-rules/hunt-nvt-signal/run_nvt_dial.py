#!/usr/bin/env python3
"""hunt-nvt-signal v13 Best Rules — frozen BEST-RULES-SPEC.md.
NVTS = CapMrktCurUSD / SMA90(blockchain.com estimated tx volume USD),
v12 frozen series reused read-only. My form: trailing-1460d percentile
dial — exposure 1.0 at pct<=0.90, linear 1->0 over (0.90,0.99], 0 above
0.99; warmup (<365 obs) exposure 1.0; weekly rebalance; 0.60% charged
on turnover fraction; NO floor. BTC only, $100 pots. Simulation only."""
import json, os, random, statistics as st, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-nvt-signal/data")
COST = 0.006
END = "2026-11-20"

cm = json.load(open(f"{SRC}/cm_btc.json"))
bc = json.load(open(f"{SRC}/bc_volume.json"))
vol = {}
for v in bc["values"]:
    d = datetime.datetime.utcfromtimestamp(v["x"]).strftime("%Y-%m-%d")
    vol[d] = v["y"]
rows = []
for r in cm:
    d = r["time"][:10]
    if d in vol and float(r["PriceUSD"]) > 0:
        rows.append((d, float(r["PriceUSD"]), float(r["CapMrktCurUSD"]), vol[d]))
rows.sort()
dates = [r[0] for r in rows]
prices = [r[1] for r in rows]
sma = [None] * len(rows); s = 0.0
for i, r in enumerate(rows):
    s += r[3]
    if i >= 90: s -= rows[i - 90][3]
    if i >= 89: sma[i] = s / 90
nvts = [None if sma[i] is None else rows[i][2] / sma[i] for i in range(len(rows))]

def percentiles(series, lookback=1460, minobs=365):
    """Trailing percentile rank of series[i] among trailing window incl i."""
    out = [None] * len(series)
    vals = [v for v in series]  # may contain None at head
    for i, v in enumerate(series):
        if v is None: continue
        lo = max(0, i - lookback + 1)
        win = [x for x in vals[lo:i + 1] if x is not None]
        if len(win) < minobs: continue
        out[i] = sum(1 for x in win if x <= v) / len(win)
    return out

def target(pct):
    if pct is None: return 1.0          # warmup: gauge uninformative -> hold
    if pct <= 0.90: return 1.0
    if pct >= 0.99: return 0.0
    return 1.0 - (pct - 0.90) / 0.09

def run_dial(dd, pp, pcts):
    eq = 100.0; exp = 0.0; curve = []; rebal = 0; turn = 0.0; exp_days = []
    for i in range(len(dd)):
        if i > 0:
            eq *= (1.0 + exp * (pp[i] / pp[i - 1] - 1.0))
        if i % 7 == 0:
            t = target(pcts[i])
            if t != exp:
                eq -= COST * abs(t - exp) * eq
                turn += abs(t - exp); rebal += 1; exp = t
        exp_days.append(exp)
        curve.append((dd[i], eq))
    if exp > 0:
        eq -= COST * exp * eq
        curve[-1] = (dd[-1], eq)
    return eq, curve, rebal, turn, (sum(exp_days) / len(exp_days) if exp_days else 0.0)

def run_bh(dd, pp):
    eq = 100.0 * (1 - COST); curve = [(dd[0], eq)]
    for i in range(1, len(dd)):
        eq *= pp[i] / pp[i - 1]
        curve.append((dd[i], eq))
    eq *= (1 - COST); curve[-1] = (dd[-1], eq)
    return eq, curve

def max_dd(curve):
    peak = -1e18; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = min(mdd, e / peak - 1.0)
    return mdd

def monthly_stats(curve):
    months = {}
    for d, e in curve: months[d[:7]] = e
    ks = sorted(months); rets = []
    prev = 100.0
    for k in ks:
        rets.append(months[k] / prev - 1.0); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    run_high = -1e18; since = mx = 0
    for k in ks:
        if months[k] > run_high: run_high = months[k]; since = 0
        else: since += 1
        mx = max(mx, since)
    return dict(n_months=len(rets), median=round(st.median(rets), 4),
                share_positive=round(pos / len(rets), 4), best=round(max(rets), 4),
                worst=round(min(rets), 4), longest_losing_streak=streak,
                longest_between_highs=mx, average_secondary=round(sum(rets) / len(rets), 4))

WIN = {"FULL": (None, END), "DESIGN": (None, "2022-12-31"),
       "VALIDATION": ("2023-01-01", END), "CONFIRM": ("2019-01-01", "2022-12-31")}
pct_full = percentiles(nvts)

out = {"family": "hunt-nvt-signal", "program": "v13-best-rules",
       "form": "NVTS trailing-1460d percentile dial (1.0 <=p90, linear to 0 at p99), weekly, no floor, 0.60%/side on turnover",
       "series_caveat": "ESTIMATOR-METHODOLOGY RISK: blockchain.com estimated tx volume; change heuristics changed over years; NVTS level drifts up vs adjusted-volume construction.",
       "windows": {}}
for w, (a, b) in WIN.items():
    idx = [i for i, d in enumerate(dates) if (a is None or d >= a) and d <= b]
    dd = [dates[i] for i in idx]; pp = [prices[i] for i in idx]; pc = [pct_full[i] for i in idx]
    f, curve, rebal, turn, meanexp = run_dial(dd, pp, pc)
    bf, bcurve = run_bh(dd, pp)
    out["windows"][w] = dict(
        start=dd[0], end=dd[-1], days=len(dd),
        dial=dict(final=round(f, 2), max_dd=round(max_dd(curve), 4), rebalances=rebal,
                  turnover=round(turn, 3), mean_exposure=round(meanexp, 4),
                  curve=[[d, round(e, 4)] for d, e in curve], monthly=monthly_stats(curve)),
        bh=dict(final=round(bf, 2), max_dd=round(max_dd(bcurve), 4),
                curve=[[d, round(e, 4)] for d, e in bcurve], monthly=monthly_stats(bcurve)))
    print(w, dd[0], "->", dd[-1], "DIAL", round(f, 2), "DD", round(max_dd(curve), 4),
          "BH", round(bf, 2), "meanexp", round(meanexp, 3), "rebal", rebal)

# Placebos: 20 seeds — permute the GLOBAL NVTS series (timing destroyed
# everywhere, history/warmup structure preserved), percentiles recomputed
# globally, same dial run on the window.
pl = {}
defined = [i for i, v in enumerate(nvts) if v is not None]
base_vals = [nvts[i] for i in defined]
for w in ["FULL", "VALIDATION"]:
    a, b = WIN[w]
    idx = [i for i, d in enumerate(dates) if (a is None or d >= a) and d <= b]
    dd = [dates[i] for i in idx]; pp = [prices[i] for i in idx]
    finals = []
    for seed in range(20):
        rng = random.Random(20261122 + seed)
        sh = base_vals[:]; rng.shuffle(sh)
        g = [None] * len(nvts)
        for j, i in enumerate(defined): g[i] = sh[j]
        gp = percentiles(g)
        f, _, _, _, _ = run_dial(dd, pp, [gp[i] for i in idx])
        finals.append(round(f, 2))
    real = out["windows"][w]["dial"]["final"]
    pl[w] = dict(finals=finals, median=round(st.median(finals), 2),
                 beats=sum(1 for x in finals if real > x), real=real)
    print("PLACEBO", w, "real", real, "median", pl[w]["median"], "beats", pl[w]["beats"], "/20")
out["placebos"] = pl
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
