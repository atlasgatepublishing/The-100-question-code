#!/usr/bin/env python3
"""Build the monthly panel + reconstructed Intan signals (CONSTRUCTED).
Chassis: shareholder-yield family's saved EDGAR roster/prices/Shares
(read-only). Fundamentals: this folder's data/frames (EDGAR frames).
Formula: OSAP Detailed Definition of Daniel-Titman (2006) — monthly
cross-sectional OLS of 5y log return on lagged log ratio and the
constructed regressor (dlog ratio + 5y return); residual = IntanX.
Availability lag: fiscal year Y usable from July of Y+1.
Writes data/panel.pkl. Simulation data prep only; no backtest here."""
import json, os, pickle, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MY = os.path.join(HERE, '..', 'data')
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')

def load_frame(path):
    if not os.path.exists(path): return {}
    return {int(k): v for k, v in json.load(open(path)).items()}

def ym_idx(y, m): return (y - 2010) * 12 + (m - 1)  # 2010-01 = 0
MONTHS = []
for y in range(2010, 2027):
    for m in range(1, 13):
        if y == 2026 and m > 11: break
        MONTHS.append(f'{y:04d}-{m:02d}')
NM = len(MONTHS)
MIDX = {s: i for i, s in enumerate(MONTHS)}

def main():
    cand = {int(k): v for k, v in json.load(open(os.path.join(SY, 'candidates.json'))).items()}
    myframes = {}
    def MF(concept, year, kind):
        key = (concept, year)
        if key not in myframes:
            base = MY if kind == 'mine' else SY
        return myframes.get(key)
    def my_frame(concept, year, kind):
        p = os.path.join(MY, 'frames', f'{concept}_{year}{kind}.json')
        return load_frame(p)
    def sy_frame(concept, year, kind):
        p = os.path.join(SY, 'frames', f'{concept}_{year}{kind}.json')
        return load_frame(p)

    years = list(range(2009, 2026))
    ceq = {y: my_frame('StockholdersEquity', y, 'I') for y in years}
    ni = {y: my_frame('NetIncomeLoss', y, 'D') for y in years}
    dep = {y: my_frame('DepreciationDepletionAndAmortization', y, 'D') for y in years}
    sale_frames = {}
    for y in years:
        d = {}
        for c in ('RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet', 'Revenues'):
            for k, v in my_frame(c, y, 'D').items():
                d.setdefault(k, v)
        sale_frames[y] = d
    shares_f = {y: sy_frame('Shares', y, 'I') for y in years}

    ciks = sorted(cand)
    # split factors per cik per formation-year F (engine_sy method)
    sf = {}
    for cik in ciks:
        avail = [(y, shares_f[y][cik]) for y in years if cik in shares_f[y]]
        d = {}
        for F in range(2010, 2027):
            f = 1.0
            for (y0, a), (y1, b) in zip(avail, avail[1:]):
                if y1 >= F and a:
                    r = b / a
                    if r >= 1.6 or r <= 0.625: f *= r
            d[F] = f
        sf[cik] = d

    n = len(ciks)
    cidx = {c: i for i, c in enumerate(ciks)}
    adj = np.full((n, NM), np.nan); raw = np.full((n, NM), np.nan)
    for cik in ciks:
        info = cand[cik]
        t = info['ticker'].replace('/', '-')
        p = os.path.join(SY, f'px_{t}.json')
        if not os.path.exists(p): continue
        try: rows = json.load(open(p))
        except Exception: continue
        if len(rows) < 6: continue
        i = cidx[cik]
        for r in rows:
            j = MIDX.get(r[0])
            if j is not None:
                adj[i, j] = r[1]; raw[i, j] = r[2]

    # monthly returns with ZERO-on-vanish baked in (for engine):
    # ret[:,j] = return from month j-1 to j. Gap months: 0 until resumption
    # (marked at last price); first month after last bar with no resumption: -1.
    ret = np.zeros((n, NM))
    lastbar = np.full(n, -1)
    for i in range(n):
        bars = np.where(~np.isnan(adj[i]))[0]
        if len(bars) == 0: continue
        lastbar[i] = bars[-1]
        last = bars[0]
        for j in bars[1:]:
            if j == last + 1:
                if adj[i, last] > 0: ret[i, j] = adj[i, j] / adj[i, last] - 1
            else:
                if adj[i, last] > 0: ret[i, j] = adj[i, j] / adj[i, last] - 1
            last = j
        lb = bars[-1]
        if lb + 1 < NM: ret[i, lb + 1] = -1.0  # vanished -> ZERO at first month-end after last bar

    # fundamentals per cik per fiscal year
    def fval(table, cik, y):
        return table.get(y, {}).get(cik)
    # market cap at month j: shares[Y] * raw[j] * sf[Y+1]; Y = lagged fiscal year
    def Yof(j):
        y = int(MONTHS[j][:4]); m = int(MONTHS[j][5:7])
        return y - 1 if m >= 7 else y - 2
    cap = np.full((n, NM), np.nan)
    fund = {k: np.full((n, 2026), np.nan) for k in ('ceq', 'ni', 'dep', 'sale')}
    for cik in ciks:
        i = cidx[cik]
        for y in years:
            v = fval(ceq, cik, y)
            if v is not None: fund['ceq'][i, y] = v
            v = fval(ni, cik, y)
            if v is not None: fund['ni'][i, y] = v
            v = fval(dep, cik, y)
            if v is not None: fund['dep'][i, y] = v
            v = fval(sale_frames, cik, y)
            if v is not None: fund['sale'][i, y] = v
    for j in range(NM):
        Y = Yof(j)
        if Y < 2009 or Y > 2025: continue
        sh = shares_f[Y]
        for cik in ciks:
            i = cidx[cik]
            s = sh.get(cik)
            if s and not np.isnan(raw[i, j]) and raw[i, j] > 0:
                cap[i, j] = s * raw[i, j] * sf[cik][Y + 1]

    ratios = {}
    ratios['BM'] = fund['ceq'][:, [Yof(j) for j in range(NM)]] / cap
    ratios['EP'] = fund['ni'][:, [Yof(j) for j in range(NM)]] / cap
    cf = fund['ni'] + np.where(np.isnan(fund['dep']), 0.0, fund['dep'])
    cf = np.where(np.isnan(fund['ni']), np.nan, cf)
    ratios['CFP'] = cf[:, [Yof(j) for j in range(NM)]] / cap
    ratios['SP'] = fund['sale'][:, [Yof(j) for j in range(NM)]] / cap

    with np.errstate(divide='ignore', invalid='ignore'):
        logadj = np.where(adj > 0, np.log(adj), np.nan)
    r5 = logadj[:, 60:] - logadj[:, :-60]  # r5 at month j (cols offset 60)

    signals = {}   # signal -> {month_str: (cik_array, intan_array)}
    sig_stats = {}
    for name, R in ratios.items():
        sig = {}
        stats = []
        for jj in range(60, NM):
            mstr = MONTHS[jj]
            if mstr < '2015-01': continue
            x_now = R[:, jj]; x_lag = R[:, jj - 60]; y5 = r5[:, jj - 60]
            ok = (np.isfinite(x_now)) & (np.isfinite(x_lag)) & (np.isfinite(y5)) & (x_now > 0) & (x_lag > 0)
            idx = np.where(ok)[0]
            if len(idx) < 100:
                stats.append((mstr, len(idx), None)); continue
            lx_now = np.log(x_now[idx]); lx_lag = np.log(x_lag[idx]); yy = y5[idx]
            z = (lx_now - lx_lag) + yy
            X = np.column_stack([np.ones(len(idx)), lx_lag, z])
            try:
                beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
            except np.linalg.LinAlgError:
                stats.append((mstr, len(idx), None)); continue
            resid = yy - X @ beta
            sig[mstr] = (idx.astype(np.int32), resid.astype(np.float64))
            stats.append((mstr, len(idx), float(np.std(resid))))
        signals['Intan' + name] = sig
        sig_stats['Intan' + name] = stats
        print('Intan' + name, 'months:', len(sig), 'avg cross-section:',
              round(float(np.mean([len(v[0]) for v in sig.values()])), 1) if sig else 0)

    out = {'ciks': ciks, 'tickers': [cand[c].get('ticker') for c in ciks],
           'months': MONTHS, 'ret': ret, 'cap': cap, 'adj': adj,
           'lastbar': lastbar, 'signals': signals, 'sig_stats': sig_stats}
    with open(os.path.join(MY, 'panel.pkl'), 'wb') as f:
        pickle.dump(out, f)
    print('panel saved; firms', n, 'months', NM)

if __name__ == '__main__':
    main()
