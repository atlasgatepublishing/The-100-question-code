#!/usr/bin/env python3
"""V13 panel builder for osap-intangible-return (CONSTRUCTED grade).

Implements the Daniel-Titman (2006) / OSAP construction exactly as
documented in the v12 SPEC-FROZEN + SPEC-ADDENDUM text:
  - EDGAR as-filed frames (this family's data/frames, JSON) for
    StockholdersEquity / NetIncomeLoss / Depreciation / Sales.
  - Program EDGAR chassis (shareholder-yield family's saved JSON data,
    read-only): CIK->current-ticker roster, monthly Yahoo prices
    2010-01..2026-11, Shares frames, split-factor correction.
  - Fiscal year Y fundamentals usable only in months >= July of Y+1.
  - IntanX = residual of monthly cross-sectional OLS of the 5-year log
    return on [1, log X lagged 5y, (dlog X over 5y + 5y log return)],
    requiring X > 0 at both ends and >= 100 firms per cross-section.
  - ZERO-on-vanish baked into the monthly return matrix.
Reads JSON data files only. Writes data/panel.npz + data/signals.json.
"""
import json, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, '..', 'data')
V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/osap-intangible-return/data')
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')

MONTHS = []
for y in range(2010, 2027):
    for m in range(1, 13):
        if y == 2026 and m > 11:
            break
        MONTHS.append(f'{y:04d}-{m:02d}')
NM = len(MONTHS)
MIDX = {s: i for i, s in enumerate(MONTHS)}
YEARS = list(range(2009, 2026))

def load_frame(base, concept, year, kind):
    p = os.path.join(base, 'frames', f'{concept}_{year}{kind}.json')
    if not os.path.exists(p):
        return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def main():
    cand = {int(k): v for k, v in json.load(open(os.path.join(SY, 'candidates.json'))).items()}
    ceq = {y: load_frame(V12, 'StockholdersEquity', y, 'I') for y in YEARS}
    ni = {y: load_frame(V12, 'NetIncomeLoss', y, 'D') for y in YEARS}
    dep = {y: load_frame(V12, 'DepreciationDepletionAndAmortization', y, 'D') for y in YEARS}
    sale = {}
    for y in YEARS:
        d = {}
        # addendum: Sales = first available of Revenues, SalesRevenueNet,
        # RevenueFromContractWithCustomerExcludingAssessedTax
        for c in ('Revenues', 'SalesRevenueNet',
                  'RevenueFromContractWithCustomerExcludingAssessedTax'):
            for k, v in load_frame(V12, c, y, 'D').items():
                d.setdefault(k, v)
        sale[y] = d
    shares_f = {y: load_frame(SY, 'Shares', y, 'I') for y in YEARS}

    ciks = sorted(cand)
    n = len(ciks)
    cidx = {c: i for i, c in enumerate(ciks)}

    # split factors per cik per formation year (documented chassis method:
    # cumulative product of year-over-year share-count jumps >= 1.6x or
    # <= 0.625x for share-years >= the formation year)
    sf = {}
    for cik in ciks:
        avail = [(y, shares_f[y][cik]) for y in YEARS if cik in shares_f[y]]
        d = {}
        for F in range(2010, 2027):
            f = 1.0
            for (y0, a), (y1, b) in zip(avail, avail[1:]):
                if y1 >= F and a:
                    r = b / a
                    if r >= 1.6 or r <= 0.625:
                        f *= r
            d[F] = f
        sf[cik] = d

    adj = np.full((n, NM), np.nan)
    raw = np.full((n, NM), np.nan)
    for cik in ciks:
        t = cand[cik]['ticker'].replace('/', '-')
        p = os.path.join(SY, f'px_{t}.json')
        if not os.path.exists(p):
            continue
        try:
            rows = json.load(open(p))
        except Exception:
            continue
        if len(rows) < 6:
            continue
        i = cidx[cik]
        for r in rows:
            j = MIDX.get(r[0])
            if j is not None:
                adj[i, j] = r[1]
                raw[i, j] = r[2]

    # monthly returns; ZERO-on-vanish: -100% in the first month after the
    # last bar if the series never resumes
    ret = np.zeros((n, NM))
    for i in range(n):
        bars = np.where(~np.isnan(adj[i]))[0]
        if len(bars) == 0:
            continue
        last = bars[0]
        for j in bars[1:]:
            if adj[i, last] > 0:
                ret[i, j] = adj[i, j] / adj[i, last] - 1.0
            last = j
        lb = bars[-1]
        if lb + 1 < NM:
            ret[i, lb + 1] = -1.0

    def Yof(j):
        y = int(MONTHS[j][:4]); m = int(MONTHS[j][5:7])
        return y - 1 if m >= 7 else y - 2

    fund = {k: np.full((n, 2026), np.nan) for k in ('ceq', 'ni', 'dep', 'sale')}
    tables = {'ceq': ceq, 'ni': ni, 'dep': dep, 'sale': sale}
    for cik in ciks:
        i = cidx[cik]
        for k, tab in tables.items():
            for y in YEARS:
                v = tab[y].get(cik)
                if v is not None:
                    fund[k][i, y] = v

    cap = np.full((n, NM), np.nan)
    for j in range(NM):
        Y = Yof(j)
        if Y < 2009 or Y > 2025:
            continue
        sh = shares_f[Y]
        for cik in ciks:
            s = sh.get(cik)
            if s:
                i = cidx[cik]
                if np.isfinite(raw[i, j]) and raw[i, j] > 0:
                    cap[i, j] = s * raw[i, j] * sf[cik][Y + 1]

    yidx = [Yof(j) for j in range(NM)]
    cf = fund['ni'] + np.where(np.isnan(fund['dep']), 0.0, fund['dep'])
    cf = np.where(np.isnan(fund['ni']), np.nan, cf)
    ratios = {
        'BM': fund['ceq'][:, yidx] / cap,
        'EP': fund['ni'][:, yidx] / cap,
        'CFP': cf[:, yidx] / cap,
        'SP': fund['sale'][:, yidx] / cap,
    }

    with np.errstate(divide='ignore', invalid='ignore'):
        logadj = np.where(adj > 0, np.log(adj), np.nan)
    r5 = logadj[:, 60:] - logadj[:, :-60]

    signals = {}
    sig_stats = {}
    for name, R in ratios.items():
        sig = {}
        stats = []
        for jj in range(60, NM):
            mstr = MONTHS[jj]
            if mstr < '2015-01':
                continue
            x_now = R[:, jj]; x_lag = R[:, jj - 60]; y5 = r5[:, jj - 60]
            ok = (np.isfinite(x_now) & np.isfinite(x_lag) & np.isfinite(y5)
                  & (x_now > 0) & (x_lag > 0))
            idx = np.where(ok)[0]
            if len(idx) < 100:
                stats.append([mstr, int(len(idx)), None])
                continue
            lx_now = np.log(x_now[idx]); lx_lag = np.log(x_lag[idx]); yy = y5[idx]
            z = (lx_now - lx_lag) + yy
            X = np.column_stack([np.ones(len(idx)), lx_lag, z])
            try:
                beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
            except np.linalg.LinAlgError:
                stats.append([mstr, int(len(idx)), None])
                continue
            resid = yy - X @ beta
            sig[mstr] = [idx.astype(int).tolist(), resid.tolist()]
            stats.append([mstr, int(len(idx)), float(np.std(resid))])
        signals['Intan' + name] = sig
        sig_stats['Intan' + name] = stats
        print('Intan' + name, 'months:', len(sig),
              'avg cross-section:',
              round(float(np.mean([len(v[0]) for v in sig.values()])), 1) if sig else 0,
              flush=True)

    np.savez_compressed(os.path.join(MYDATA, 'panel.npz'),
                        months=np.array(MONTHS), ret=ret, cap=cap,
                        tickers=np.array([cand[c].get('ticker') for c in ciks]))
    with open(os.path.join(MYDATA, 'signals.json'), 'w') as f:
        json.dump({'signals': signals, 'sig_stats': sig_stats}, f)
    print('panel saved; firms', n, 'months', NM)

if __name__ == '__main__':
    main()
