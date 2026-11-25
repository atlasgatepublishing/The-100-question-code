"""V13 best-rules run: catalog-pairs-trading (long-only SPY-parked translation).
Spec: BEST-RULES-SPEC.md in this folder (frozen before this run).
Data: program price stack (read-only) prices_jb.parquet, same source as v12.
Implementation is numpy-based for speed; logic identical to spec.
"""
import os, sys, json
sys.path.insert(0, '/home/hatch/workspace/.pylibs')
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/home/hatch/workspace/stock-app/backtests/v12-completions/dividend-growth/data/prices_jb.parquet"
COST_SIDE = 0.001          # 0.10% per side
N_PAIRS = 20
THRESH = 2.0
FORM_DAYS = 252
TRADE_DAYS = 126

ROADS = {  # named ends truncated at last available trading day (stack ends 2026-10-30)
    'LONG':   ('2010-01-04', '2026-11-20'),
    'DECADE': ('2016-11-21', '2026-11-20'),
    'CONT':   ('2019-01-02', '2026-11-20'),
    'VAL':    ('2023-01-03', '2026-11-20'),
}
CHAMPION = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPY_REF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}
PUBLISHED = {'LONG': 91.74, 'DECADE': 96.77, 'CONT': 98.24, 'VAL': 98.30}


def load_daily():
    cache = f'{HERE}/daily_pivot.csv'
    if os.path.exists(cache):
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    df = pd.read_parquet(SRC, columns=['date', 'ticker', 'adj_close', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] >= '2008-01-01']
    cnt = df.groupby('ticker')['adj_close'].count()
    vol = (df['adj_close'] * df['volume']).groupby(df['ticker']).median()
    elig = cnt[cnt > 4200].index
    top = vol[elig].nlargest(120).index
    keep = list(top) + (['SPY'] if 'SPY' not in top else [])
    piv = df[df.ticker.isin(keep)].pivot(index='date', columns='ticker', values='adj_close').sort_index()
    piv.to_csv(cache)
    return piv


PX = load_daily()
DATES = PX.index
COLIDX = {c: i for i, c in enumerate(PX.columns)}
PXM = PX.values                      # (T, C) float array, NaN where missing
RETM = np.vstack([np.full((1, PXM.shape[1]), np.nan), PXM[1:] / PXM[:-1] - 1.0])
SPY_J = COLIDX['SPY']
PAIR_COLS = [c for c in PX.columns if c != 'SPY']
MONTH_ENDS = PX.resample('ME').last().index


def period_stats(eq):
    """Program-standard monthly distribution stats (eq = monthly equity series)."""
    r = eq.pct_change().dropna()
    if len(r) == 0:
        return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        ls = max(ls, cur)
    run_max = eq.cummax()
    below = (eq < run_max - 1e-9)
    lb = cur = 0
    for x in below:
        cur = cur + 1 if x else 0
        lb = max(lb, cur)
    dd = (eq / run_max - 1).min()
    return {'n_periods': int(len(r)), 'share_positive': round(float((r > 0).mean()), 3),
            'median_period': round(float(r.median()), 4),
            'mean_period_secondary': round(float(r.mean()), 4),
            'best': round(float(r.max()), 4), 'worst': round(float(r.min()), 4),
            'longest_losing_streak': int(ls), 'longest_below_high_months': int(lb),
            'max_dd': round(float(dd), 4)}


def run_translation(start, end, placebo_seed=None):
    """Long-only SPY-parked pairs translation per frozen spec.
    Returns (daily equity series, total cost, n position switches)."""
    start = pd.Timestamp(start)
    end = min(pd.Timestamp(end), DATES[-1])
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    fdates = [d for d in MONTH_ENDS if start <= d <= end and d.month in (1, 7)]
    eq_slices = None
    held = None               # per-slice: SPY_J or column index of held stock
    total_cost = 0.0
    n_trades = 0
    curve = {}
    for fd in fdates:
        i_fd = int(DATES.get_indexer([fd], method='nearest')[0])
        if i_fd < FORM_DAYS:
            continue
        i0 = i_fd - FORM_DAYS + 1
        form = PXM[i0:i_fd + 1]                       # (252, C)
        ok = ~np.isnan(form).any(axis=0)
        cols = [c for c in PAIR_COLS if ok[COLIDX[c]]]
        if len(cols) < 30:
            continue
        cj = np.array([COLIDX[c] for c in cols])
        base = form[0, cj]                            # formation-start prices (anchor)
        norm = form[:, cj] / base                     # (252, n)
        if rng is not None:
            allp = [(i, j) for i in range(len(cols)) for j in range(i + 1, len(cols))]
            idxs = rng.choice(len(allp), size=min(N_PAIRS, len(allp)), replace=False)
            pairs = [allp[k] for k in idxs]
        else:
            sq = (norm ** 2).sum(axis=0)
            ssd = sq[:, None] + sq[None, :] - 2 * norm.T @ norm
            np.fill_diagonal(ssd, np.inf)
            flat = np.argsort(ssd, axis=None)
            pairs = []
            for f in flat:
                i, j = divmod(int(f), len(cols))
                if i >= j:
                    continue
                pairs.append((i, j))
                if len(pairs) >= N_PAIRS:
                    break
        sig = np.array([np.std(norm[:, i] - norm[:, j], ddof=1) for (i, j) in pairs])
        pa = np.array([cj[i] for (i, j) in pairs])    # global col idx of leg A
        pb = np.array([cj[j] for (i, j) in pairs])    # global col idx of leg B
        ba = base[[i for (i, j) in pairs]]
        bb = base[[j for (i, j) in pairs]]
        # --- window transition ---
        if eq_slices is None:
            total = 100.0
            c = total * COST_SIDE                     # cash -> SPY, one side
            total_cost += c; total -= c
        else:
            total = float(eq_slices.sum())
            for k in range(N_PAIRS):
                if held[k] != SPY_J:
                    c = eq_slices[k] * 2 * COST_SIDE  # stock -> SPY: sell + buy
                    total_cost += c; total -= c
        eq_slices = np.full(N_PAIRS, total / N_PAIRS)
        held = np.full(N_PAIRS, SPY_J)
        t_end = min(i_fd + TRADE_DAYS, len(DATES) - 1)
        for di in range(i_fd + 1, t_end + 1):
            if DATES[di] > end:
                break
            rets = RETM[di, held]                    # held asset return per slice
            rets = np.where(np.isnan(rets), 0.0, rets)
            eq_slices = eq_slices * (1.0 + rets)
            # close-of-day signals
            na = PXM[di, pa] / ba
            nb = PXM[di, pb] / bb
            spread = na - nb
            for k in range(N_PAIRS):
                if np.isnan(spread[k]) or sig[k] <= 0:
                    continue
                h = held[k]
                new = h
                if h == SPY_J:
                    if spread[k] > THRESH * sig[k]:
                        new = pb[k]                   # A rich -> long cheap B
                    elif spread[k] < -THRESH * sig[k]:
                        new = pa[k]                   # A cheap -> long A
                elif h == pa[k] and spread[k] >= 0:
                    new = SPY_J
                elif h == pb[k] and spread[k] <= 0:
                    new = SPY_J
                if new != h:
                    c = eq_slices[k] * 2 * COST_SIDE
                    total_cost += c; eq_slices[k] -= c
                    held[k] = new
                    n_trades += 1
            curve[DATES[di]] = float(eq_slices.sum())
    s = pd.Series(curve).sort_index()
    return s, total_cost, n_trades


def spy_buyhold(start, end):
    start = pd.Timestamp(start); end = min(pd.Timestamp(end), DATES[-1])
    px = PX['SPY'].loc[start:end].dropna()
    return 100.0 * float(px.iloc[-1] / px.iloc[0])


def yearly_folds_and_halves(road):
    """Confirmation machinery (spec: frozen bars). Standalone calendar-year folds + half windows."""
    start, end = ROADS[road]
    start = pd.Timestamp(start); end = min(pd.Timestamp(end), DATES[-1])
    fold_rows = []
    for y in range(start.year, end.year + 1):
        ys = max(start, pd.Timestamp(f'{y}-01-01')); ye = min(end, pd.Timestamp(f'{y}-12-31'))
        if (ye - ys).days < 60:
            continue
        s, _, _ = run_translation(str(ys.date()), str(ye.date()))
        fin = float(s.resample('ME').last().iloc[-1]) if len(s) else 100.0
        spy = spy_buyhold(str(ys.date()), str(ye.date()))
        fold_rows.append({'year': y, 'final': round(fin, 2), 'spy': round(spy, 2)})
    wins = sum(1 for r in fold_rows if r['final'] > r['spy'])
    med_t = float(np.median([r['final'] for r in fold_rows])) if fold_rows else 0
    med_s = float(np.median([r['spy'] for r in fold_rows])) if fold_rows else 0
    folds_pass = bool(fold_rows) and wins > len(fold_rows) / 2 and med_t >= med_s
    mid = start + (end - start) / 2
    halves, halves_pass = [], True
    for hs, he in [(start, mid), (mid + pd.Timedelta(days=1), end)]:
        s, _, _ = run_translation(str(hs.date()), str(he.date()))
        fin = float(s.resample('ME').last().iloc[-1]) if len(s) else 100.0
        spy = spy_buyhold(str(hs.date()), str(he.date()))
        halves.append({'start': str(hs.date()), 'end': str(he.date()), 'final': round(fin, 2), 'spy': round(spy, 2)})
        if fin <= spy:
            halves_pass = False
    return {'folds': fold_rows, 'fold_wins': wins, 'n_folds': len(fold_rows),
            'median_translation': round(med_t, 2), 'median_spy': round(med_s, 2),
            'folds_pass': bool(folds_pass), 'halves': halves, 'halves_pass': bool(halves_pass),
            'confirmed': bool(folds_pass and halves_pass)}


def main():
    out = {'roads': {}, 'placebos': {}, 'confirmation': {},
           'meta': {'spec': 'BEST-RULES-SPEC.md (frozen 2026-11-22, before run)',
                    'translation': 'long-only, SPY-parked, 20 SSD pairs, 2.0 sigma entry, zero-cross exit, no shorts/borrow/leverage',
                    'cost_per_side': COST_SIDE, 'champion': CHAMPION, 'spy_ref': SPY_REF, 'published_ls': PUBLISHED}}
    for road, (st, en) in ROADS.items():
        s, cost, ntr = run_translation(st, en)
        m = s.resample('ME').last()
        stats = period_stats(m)
        fin = round(float(m.iloc[-1]), 2)
        out['roads'][road] = {'final': fin, 'cost': round(float(cost), 2), 'n_trades': int(ntr),
                              'stats': stats,
                              'curve': {str(k.date()): round(float(v), 4) for k, v in m.items()}}
        print(road, 'final', fin, 'cost', round(float(cost), 2), 'trades', ntr, stats, flush=True)
    for road, (st, en) in ROADS.items():
        beats = 0; finals = []
        for seed in range(20):
            sp, _, _ = run_translation(st, en, placebo_seed=seed)
            f = float(sp.resample('ME').last().iloc[-1])
            finals.append(round(f, 2))
            if out['roads'][road]['final'] > f:
                beats += 1
        out['placebos'][road] = {'beats': beats, 'n_seeds': 20,
                                 'median_placebo': round(float(np.median(finals)), 2),
                                 'best_placebo': round(float(np.max(finals)), 2),
                                 'worst_placebo': round(float(np.min(finals)), 2),
                                 'finals': finals}
        print('placebo', road, 'beats', beats, '/20 median', out['placebos'][road]['median_placebo'], flush=True)
    for road in ROADS:
        if out['roads'][road]['final'] > CHAMPION[road]:
            print('CONFIRMATION TRIGGERED on', road, flush=True)
            out['confirmation'][road] = yearly_folds_and_halves(road)
            print('confirmation', road, out['confirmation'][road], flush=True)
    json.dump(out, open(f'{HERE}/results.json', 'w'), indent=1)
    print('DONE')


if __name__ == '__main__':
    main()
