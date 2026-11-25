#!/usr/bin/env python3
"""catalog-hxz-market-beta v13 BEST RULES run.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
My rules: BetaLow exactly as catalogued (60m rolling OLS beta on SPY,
min 24 obs, trailing only), MONTHLY formation/rebalance, lowest-beta
QUINTILE equal-weight, NO floor. Tiered program costs, vanished->ZERO.
Comparator: v12 published form (June-annual quintile) on identical
plumbing must reproduce the v12 LONGEST record ($161.41).
Placebos: 20 seeds/road, same chassis, random quintile from same pool.
"""
import json, os, math, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
months_all = sorted(spy)
midx = {m: i for i, m in enumerate(months_all)}
NM = len(months_all)

# ---- shares / split factors / cap (v12 plumbing, for cost tiers) ----
def frame(concept, unit):
    out = {}
    for y in range(2014, 2026):
        out[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json')).items()}
    return out
SH = frame('Shares', 'I')
sf = {}
for cik in cand:
    avail = [(y, SH[y][cik]) for y in range(2014, 2026) if cik in SH.get(y, {})]
    d = {}
    for F in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d

def cap_at(cik, ym_str):
    """Market cap at formation month: latest filed shares x price then."""
    F = int(ym_str[:4])
    sh = None
    for y in (F - 1, F - 2):
        if cik in SH.get(y, {}): sh = SH[y][cik]; break
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ym_str)
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

# ---- price matrix (adjclose), last-price carried, ZERO after last bar ----
ciks = sorted(px)
cidx = {c: i for i, c in enumerate(ciks)}
P = np.full((len(ciks), NM), np.nan)
for cik in ciks:
    s = px[cik]; last = None; lastbar = max(s) if s else None
    for j, mm in enumerate(months_all):
        if mm in s: last = s[mm][0]
        if lastbar is not None and mm > lastbar: P[cidx[cik], j] = 0.0
        elif last is not None: P[cidx[cik], j] = last
SPYV = np.array([spy[m] for m in months_all], dtype=float)

# monthly returns (index j = return during month j, from j-1)
with np.errstate(invalid='ignore', divide='ignore'):
    R = P[:, 1:] / P[:, :-1] - 1.0
R = np.where(np.isfinite(R), R, np.nan)          # shape (n, NM-1); col k <-> months_all[k+1]
SR = SPYV[1:] / SPYV[:-1] - 1.0                   # length NM-1

# ---- rolling beta at formation month index j (returns with col <= j-1, last 60, min 24) ----
def betas_at(j):
    """j = index in months_all of formation month. Uses returns cols max(0,j-60)..j-1."""
    lo = max(0, j - 60); hi = j  # cols lo..hi-1
    if hi - lo < 24: return {}
    Y = R[:, lo:hi]                                # (n, w)
    X = SR[lo:hi]
    mask = np.isfinite(Y)
    cnt = mask.sum(axis=1)
    Yf = np.where(mask, Y, 0.0)
    Xf = np.where(mask, X[None, :], 0.0)
    sx = Xf.sum(axis=1); sy = Yf.sum(axis=1)
    sxx = (Xf * Xf).sum(axis=1); sxy = (Xf * Yf).sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        denom = cnt * sxx - sx * sx
        beta = np.where((cnt >= 24) & (denom > 0), (cnt * sxy - sx * sy) / np.where(denom == 0, np.nan, denom), np.nan)
    out = {}
    prow = P[:, j]
    for i, cik in enumerate(ciks):
        if np.isfinite(beta[i]) and np.isfinite(prow[i]) and prow[i] > 0:
            out[cik] = float(beta[i])
    return out

def ym(y, m): return f'{y:04d}-{m:02d}'

RATE_CACHE = {}
def rate_of(cik, ym_str):
    k = (cik, ym_str)
    if k not in RATE_CACHE: RATE_CACHE[k] = cost_rate(cap_at(cik, ym_str))
    return RATE_CACHE[k]

def run_monthly(first_form_idx, seed=None):
    """Formations from months_all[first_form_idx] through Oct 2026; final
    liquidation at Nov 2026 close. Returns final, curve, costs, pool sizes."""
    cash = 100.0; shares = {}; total_costs = 0.0; curve = []; pools = {}
    last_j = midx['2026-10']
    for j in range(first_form_idx, last_j + 1):
        mm = months_all[j]
        # mark current holdings at formation close
        vals = {}
        for cik, sh in shares.items():
            v = P[cidx[cik], j]
            vals[cik] = sh * (v if np.isfinite(v) else 0.0)
        eq_gross = cash + sum(vals.values())
        pool = betas_at(j)
        pools[mm] = len(pool)
        if not pool:
            cash = eq_gross; shares = {}; curve.append([mm, round(eq_gross, 2)]); continue
        if seed is None:
            ranked = sorted(pool, key=lambda c: pool[c])
        else:
            rng = random.Random(seed * 100003 + j)
            ranked = list(pool); rng.shuffle(ranked)
        n = max(1, math.ceil(len(ranked) * 0.20))
        picks = ranked[:n]
        # honest rebalance: trade only the DELTA to equal-weight targets,
        # cost on |delta| per name (exits sell in full, entries buy in full,
        # continuing names trade only their weight drift)
        tgt_gross = eq_gross / n
        trade_cost = 0.0
        for cik in set(list(vals) + picks):
            cur = vals.get(cik, 0.0)
            tgt = tgt_gross if cik in picks else 0.0
            trade_cost += abs(tgt - cur) * rate_of(cik, mm)
        total_costs += trade_cost
        eq_net = eq_gross - trade_cost
        tgt = eq_net / n
        shares = {cik: tgt / P[cidx[cik], j] for cik in picks}
        cash = 0.0
        curve.append([mm, round(eq_net, 2)])
    # final liquidation at Nov 2026
    j = midx['2026-11']; mm = months_all[j]; eq = cash
    for cik, sh in shares.items():
        v = P[cidx[cik], j]
        val = sh * (v if np.isfinite(v) else 0.0)
        cst = val * rate_of(cik, mm); total_costs += cst; eq += val - cst
    curve.append([mm, round(eq, 2)])
    return round(eq, 2), curve, round(total_costs, 2), pools

def max_dd(curve):
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak) if peak else 0.0
    return round(mdd * 100, 2)

def distribution(curve):
    vals = [v for _, v in curve]
    rets = [vals[i + 1] / vals[i] - 1 for i in range(len(vals) - 1) if vals[i] > 0]
    if not rets: return {}
    med = float(np.median(rets)); pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (months, by curve dates)
    dates = [d for d, _ in curve]
    def mnum(d): return int(d[:4]) * 12 + int(d[5:7])
    peak = -1; last_high = 0; longest = 0
    for i, v in enumerate(vals):
        if v >= peak: peak = v; longest = max(longest, mnum(dates[i]) - mnum(dates[last_high])); last_high = i
    longest = max(longest, mnum(dates[-1]) - mnum(dates[last_high]))
    return {'periods': len(rets), 'share_positive_pct': round(100 * pos / len(rets), 1),
            'median_period_pct': round(med * 100, 2), 'best_period_pct': round(max(rets) * 100, 2),
            'worst_period_pct': round(min(rets) * 100, 2), 'longest_losing_streak': streak,
            'longest_months_between_new_highs': longest,
            'average_period_pct_secondary': round(float(np.mean(rets)) * 100, 2),
            'period_returns_pct': [round(r * 100, 2) for r in rets]}

def spy_same(first_form_idx):
    a = SPYV[first_form_idx]; b = SPYV[midx['2026-11']]
    return round(100 * b / a, 2)

ROADS = {'LONG': midx['2018-01'], 'DECADE': midx['2018-01'],
         'CONT': midx['2018-12'], 'VAL': midx['2022-12']}

# ================= annual comparator (v12 published form, same plumbing) =========
def sig_beta_annual(F):
    j = midx[ym(F, 5)]  # window ending May F: formation at June close uses betas thru May
    pool = betas_at(j + 1) if False else None
    # v12: returns keys <= May F, formation price at June F. betas_at uses formation
    # month index = May index, prices checked there; re-check price at June below.
    b = betas_at(midx[ym(F, 5)])
    out = {}
    jj = midx[ym(F, 6)]
    for cik, v in b.items():
        p = P[cidx[cik], jj]
        if np.isfinite(p) and p > 0: out[cik] = v
    return out

def run_annual(formations):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        pool = sig_beta_annual(F)
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not pool:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        ranked = sorted(pool, key=lambda c: pool[c])
        n = max(1, math.ceil(len(ranked) * 0.20)); picks = ranked[:n]
        j0 = midx[ym(F, 6)]; w = cash / len(picks); shares = {}
        for cik in picks:
            r = rate_of(cik, ym(F, 6)); total_costs += w * r
            shares[cik] = (w * (1 - r)) / P[cidx[cik], j0]
        for k in range(1, 13):
            mm = cols[k]; j = midx[mm]
            val = sum(sh * (P[cidx[c], j] if np.isfinite(P[cidx[c], j]) else 0.0) for c, sh in shares.items())
            if k == 12:
                sell = sum(sh * (P[cidx[c], j] if np.isfinite(P[cidx[c], j]) else 0.0) * rate_of(c, mm) for c, sh in shares.items())
                total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([mm, round(cash, 2)])
    return round(cash, 2), curve, round(total_costs, 2)

def main():
    out = {'family': 'catalog-hxz-market-beta', 'spec': 'BEST-RULES-SPEC.md'}
    # integrity gate: annual comparator vs v12 record
    fin, curve, costs = run_annual(list(range(2016, 2026)))
    out['integrity_annual_comparator'] = {'LONGEST_final': fin, 'costs': costs,
        'max_dd_pct': max_dd(curve), 'v12_record_final': 161.41, 'v12_record_costs': 7.59}
    print('ANNUAL COMPARATOR (v12 published form):', fin, 'costs', costs, 'v12 record: 161.41 / 7.59', flush=True)
    pub = {}
    for name, forms in {'LONGEST': list(range(2016, 2026)), 'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}.items():
        f2, c2, co2 = run_annual(forms)
        a = spy[ym(forms[0], 6)]; b = spy[ym(forms[-1] + 1, 6)]
        pub[name] = {'final': f2, 'costs': co2, 'max_dd_pct': max_dd(c2), 'spy_same_window': round(100 * b / a, 2), 'curve': c2}
        print('published annual', name, f2, flush=True)
    out['published_form_annual'] = pub
    roads = {}
    for rname, fi in ROADS.items():
        fin, curve, costs, pools = run_monthly(fi)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _ = run_monthly(fi, seed=sd); twins.append(tf)
        roads[rname] = {'final': fin, 'costs': costs, 'max_dd_pct': max_dd(curve),
                        'spy_same_window': spy_same(fi), 'placebo_finals': twins,
                        'placebos_beaten': sum(1 for t in twins if fin > t),
                        'placebo_median': round(float(np.median(twins)), 2),
                        'pool_first': next(iter(pools.values())), 'pool_last': list(pools.values())[-1],
                        'distribution': distribution(curve), 'curve': curve}
        print(rname, fin, 'DD', roads[rname]['max_dd_pct'], 'SPY', roads[rname]['spy_same_window'],
              'pb', roads[rname]['placebos_beaten'], flush=True)
    out['my_rules_monthly'] = roads
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
