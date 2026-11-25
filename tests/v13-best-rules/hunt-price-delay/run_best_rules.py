#!/usr/bin/env python3
"""hunt-price-delay V13 BEST RULES — implements BEST-RULES-SPEC.md as frozen.
Residual delay: D1 (Hou-Moskowitz, lags 0..4, trailing 252 trading days,
point-in-time) residualised cross-sectionally on log mean daily dollar volume.
Quarterly formation, top decile of residual D1 (min 12), EW, no floor.
Costs 0.15%/side on actual turnover dollars. 20-seed placebos from the
eligible pool. Universe = program pxfull stack (154 names excl SPY) —
SURVIVORSHIP FENCE: current large caps only, flatters. Simulation only."""
import json, os, time, random, statistics as st
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.0015
WIN = 252

def load(t):
    j = json.load(open(os.path.join(DATA, f"pxfull_{t}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    vol = r["indicators"]["quote"][0]["volume"]
    out = {}
    for i, x in enumerate(ts):
        if adj[i] is None: continue
        out[time.strftime("%Y-%m-%d", time.gmtime(x))] = (adj[i], vol[i] or 0)
    return out

tickers = sorted(f[7:-5] for f in os.listdir(DATA) if f.startswith("pxfull_"))
tickers.remove("SPY")
px = {t: load(t) for t in tickers}; spy = load("SPY")
cal = sorted(spy)                      # trading calendar
ci = {d: i for i, d in enumerate(cal)}
spy_px = np.array([spy[d][0] for d in cal])
spy_ret = np.zeros(len(cal)); spy_ret[1:] = spy_px[1:] / spy_px[:-1] - 1

# per-ticker arrays aligned to calendar
ARR = {}
for t in tickers:
    a = np.full(len(cal), np.nan); v = np.zeros(len(cal))
    for d, (p, vv) in px[t].items():
        a[ci[d]] = p; v[ci[d]] = vv
    ARR[t] = (a, v)

_FI_CACHE = {}
def formation_info(iF):
    if iF in _FI_CACHE: return _FI_CACHE[iF]
    r = _formation_info_raw(iF); _FI_CACHE[iF] = r; return r

def _formation_info_raw(iF):
    """Window = WIN trading days ending at iF-1. Returns eligible list of
    (ticker, resid_D1) and pool of eligible tickers."""
    i1 = iF - 1; i0 = iF - WIN
    if i0 < 1: return [], []
    m = spy_ret[i0:i1 + 1]
    X = np.column_stack([np.ones(len(m))] + [np.roll(m, k) for k in range(5)])
    X[:4, 1:] = 0.0
    Xr = X[:, :2]
    raw = []
    for t in tickers:
        a, v = ARR[t]
        seg = a[i0:i1 + 1]
        if np.isnan(seg).any(): continue
        if len(seg) < 200: continue
        r = np.zeros(len(seg)); r[1:] = seg[1:] / seg[:-1] - 1
        try:
            bu, *_ = np.linalg.lstsq(X, r, rcond=None)
            br, *_ = np.linalg.lstsq(Xr, r, rcond=None)
        except Exception: continue
        def r2(beta, XX):
            res = r - XX @ beta; ss = np.sum(res ** 2); tt = np.sum((r - r.mean()) ** 2)
            return 1 - ss / tt if tt > 0 else 0.0
        r2u = r2(bu, X)
        if r2u <= 0.02: continue
        d1 = 1 - r2(br, Xr) / r2u
        dvol = seg * v[i0:i1 + 1]
        if np.median(dvol) < 5e6: continue
        if seg[-1] < 5.0: continue
        raw.append((t, d1, np.log(np.mean(dvol))))
    if len(raw) < 20: return [], []
    y = np.array([x[1] for x in raw]); lv = np.array([x[2] for x in raw])
    A = np.column_stack([np.ones(len(raw)), lv])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    elig = [(raw[i][0], float(resid[i])) for i in range(len(raw))]
    return elig, [x[0] for x in raw]

def month_ends_between(d0, d1):
    out = []
    seen = set()
    for d in cal:
        if d0 < d <= d1 and d[:7] not in seen:
            pass
    # last trading day of each month in (d0, d1]
    cand = [d for d in cal if d0 < d <= d1]
    bym = {}
    for d in cand: bym[d[:7]] = d
    return [bym[k] for k in sorted(bym)]

def run_road(start, end, placebo_seed=None, force_formations=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    # formation dates: start, then first trading day of Jan/Apr/Jul/Oct
    forms = [start]
    for d in cal:
        if start < d <= end and d[5:7] in ("01", "04", "07", "10"):
            # first trading day of that month
            if ci[d] == 0 or cal[ci[d] - 1][:7] != d[:7]:
                forms.append(d)
    forms = sorted(set(f for f in forms if f <= end))
    if force_formations is not None: forms = force_formations
    V = 100.0; pos = {}   # ticker -> dollars
    curve = [(start, 100.0)]
    marks = {}
    for fi, F in enumerate(forms):
        iF = ci[F]
        elig, pool = formation_info(iF)
        nxt = forms[fi + 1] if fi + 1 < len(forms) else end
        if not pool:
            # stay in cash to next formation
            for me in month_ends_between(F, nxt): marks[me] = V
            continue
        k = min(len(pool), max(12, int(np.ceil(0.10 * len(pool)))))
        if rng: basket = rng.sample(pool, k)
        else:
            basket = [t for t, _ in sorted(elig, key=lambda x: -x[1])[:k]]
        # rebalance at formation close (price = close on F itself; signal used
        # data through F-1). Mark current positions at F close first.
        for t in list(pos):
            p0 = ARR[t][0][iF]
            pos[t] = pos[t]  # dollars already current-value at last mark; adjust by price ratio since last mark handled below
        # NOTE: positions are carried in dollars marked at each month-end /
        # formation via price ratios in the hold loop; at formation they are
        # current as of F close by construction of the loop below.
        target = V / len(basket)
        trades = 0.0
        newpos = {}
        for t in basket:
            cur = pos.get(t, 0.0)
            trades += abs(target - cur)
            newpos[t] = target
        for t in pos:
            if t not in newpos: trades += pos[t]
        V -= COST * trades
        scale = V / (target * len(basket)) if basket else 1.0
        pos = {t: v * scale for t, v in newpos.items()}
        base_px = {t: ARR[t][0][iF] for t in pos}
        # hold to next formation (or road end): monthly marks
        hold_end = nxt
        mes = month_ends_between(F, hold_end)
        if not mes or mes[-1] != hold_end: mes.append(hold_end)
        for me in mes:
            ime = ci[me]; tot = 0.0; newp = {}
            for t, dv in pos.items():
                p = ARR[t][0][ime]
                nv = dv * (p / base_px[t]) if not np.isnan(p) else dv
                newp[t] = nv; tot += nv
            if me == mes[-1]:
                pos = newp; V = tot
            marks[me] = tot
    # liquidate at end
    if pos: V -= COST * sum(pos.values())
    for d in sorted(marks): curve.append((d, round(marks[d], 4)))
    curve.append((end, round(V, 4)))
    return round(V, 2), curve

def stats_and_dd(curve):
    marks = {}
    for d, e in curve: marks[d[:7]] = e
    ks = sorted(marks); vals = [marks[k] for k in ks]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:])]
    peak = -1; mdd = 0.0
    for v in vals:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    if not rets: return {}, round(mdd, 4)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    pk = -1; last = 0; longest = 0
    for i, v in enumerate(vals):
        if v >= pk: pk = v; last = i
        longest = max(longest, i - last)
    return dict(periods=len(rets), share_positive=round(sum(1 for r in rets if r > 0) / len(rets), 3),
                median=round(st.median(rets), 4), best=round(max(rets), 4), worst=round(min(rets), 4),
                mean_secondary=round(st.mean(rets), 4), longest_losing_streak=streak,
                longest_between_highs_months=longest), round(mdd, 4)

def spy_over(start, end):
    a = spy[start][0]; b = spy[end][0]
    return round(100 * (b / a), 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
# snap road bounds to trading days
def snap(d, up=True):
    if d in ci: return d
    cands = [x for x in cal if (x >= d if up else x <= d)]
    return cands[0] if up else cands[-1]

out = {"family": "hunt-price-delay", "program": "v13-best-rules", "universe_n": len(tickers),
       "cost_per_side": COST, "roads": {}}
log = []
for rn, (s, e) in ROADS.items():
    s2, e2 = snap(s), snap(e, up=False)
    f, curve = run_road(s2, e2)
    pls = [run_road(s2, e2, placebo_seed=9000 + i)[0] for i in range(20)]
    ms, mdd = stats_and_dd(curve)
    out["roads"][rn] = dict(start=s2, end=e2, final=f, max_drawdown=mdd,
                            SPY_same_span=spy_over(s2, e2), champion_VM=CHAMP[rn],
                            placebo_finals=pls, placebo_beaten=sum(1 for x in pls if f > x),
                            monthly=ms, curve=curve)
    line = f"{rn}: final {f} maxDD {mdd} SPYspan {out['roads'][rn]['SPY_same_span']} champ {CHAMP[rn]} placebos beaten {out['roads'][rn]['placebo_beaten']}/20"
    print(line, flush=True); log.append(line)

# Confirmation (frozen bars in spec) for any road beating champion
conf = {}
for rn, (s, e) in ROADS.items():
    if out["roads"][rn]["final"] > CHAMP[rn]:
        s2, e2 = snap(s), snap(e, up=False)
        years = sorted(set(d[:4] for d in cal if s2 <= d <= e2))
        folds = {}
        for y in years:
            ys = snap(f"{y}-01-01"); ye = snap(f"{y}-12-31", up=False)
            if ys < s2: ys = s2
            if ye > e2: ye = e2
            if ys >= ye: continue
            ff, _ = run_road(ys, ye)
            folds[y] = dict(strategy=ff, SPY=spy_over(ys, ye), beats_spy=ff > spy_over(ys, ye))
        # half windows
        mid_i = (ci[s2] + ci[e2]) // 2; mid = cal[mid_i]
        h1, _ = run_road(s2, mid); h2, _ = run_road(mid, e2)
        conf[rn] = dict(year_folds=folds,
                        years_beating_spy=sum(1 for v in folds.values() if v["beats_spy"]),
                        n_years=len(folds),
                        half1=dict(strategy=h1, SPY=spy_over(s2, mid)),
                        half2=dict(strategy=h2, SPY=spy_over(mid, e2)))
        c = conf[rn]
        ok = c["years_beating_spy"] > c["n_years"] / 2 and h1 > c["half1"]["SPY"] and h2 > c["half2"]["SPY"]
        conf[rn]["confirmation_passed"] = bool(ok)
        line = f"CONFIRM {rn}: years beating SPY {c['years_beating_spy']}/{c['n_years']} half1 {h1} vs {c['half1']['SPY']} half2 {h2} vs {c['half2']['SPY']} passed={ok}"
        print(line, flush=True); log.append(line)
out["confirmation"] = conf
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
open(os.path.join(HERE, "run.log"), "w").write("\n".join(log) + "\n")
print("DONE")
