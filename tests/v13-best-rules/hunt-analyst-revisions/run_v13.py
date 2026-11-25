#!/usr/bin/env python3
"""V13 best-rules run: hunt-analyst-revisions (REV6 analyst-revision drift).

Spec: BEST-RULES-SPEC.md (frozen 2026-11-22T19:45:45Z, before any return read).
Chassis: OSAP published portfolio returns (CITATION-GRADE, delisting-complete
CRSP via Chen-Zimmermann), read-only from the v12 sibling folders.
  MY FORM      : Alt_DecilesEW, REV6, port '10' (top decile, EW), monthly.
  PUBLISHED    : Alt_QuintilesEW, REV6, port '05' (top quintile, EW), monthly.
  PLACEBOS     : PlaceboPortsFull, first 20 signals alphabetically, port '05'.
Costs (frozen): monthly drag = (churn_out + churn_in) * 0.25%/side, churn
measured from OSAP firm-level REV6 membership (Predictors.parquet);
first month of a road: one-time 0.25% buy-in. Placebo legs are charged the
quintile churn series (same cost schedule as the published-form book).
Sensitivity: full-replacement bound = 0.50%/month every month.
"""
import json, sys
import numpy as np
import pandas as pd

DS = '/home/hatch/workspace/stock-app/backtests/v12-completions/osap-real-dirty-surplus/data/'
PRED = '/home/hatch/workspace/stock-app/backtests/v12-completions/osap-intangible-return/data/Predictors.parquet'
OUT = '/home/hatch/workspace/stock-app/backtests/v13-best-rules/hunt-analyst-revisions/'
RATE = 0.0025  # program broad-universe per-side rate

ROADS = {  # start month (return month containing road start) -> label
    'LONG':   '2010-01',
    'DECADE': '2016-11',
    'CONT':   '2019-01',
    'VAL':    '2023-01',
}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}
END = '2025-12'  # last month OSAP publishes

# ---------- 1. measured churn from firm-level REV6 ----------
print('computing membership churn from firm-level REV6 ...', flush=True)
sig = pd.read_parquet(PRED, columns=['permno', 'yyyymm', 'REV6'])
sig = sig[(sig.yyyymm >= 200910) & (sig.yyyymm <= 202512)].dropna(subset=['REV6'])
sig['ym'] = (sig.yyyymm // 100).astype(str) + '-' + (sig.yyyymm % 100).astype(str).str.zfill(2)

def top_sets(df, frac):
    q = df.REV6.quantile(1 - frac)
    return set(df.loc[df.REV6 >= q, 'permno'])

books = {'decile': {}, 'quintile': {}}
for ym, g in sig.groupby('ym'):
    books['decile'][ym] = top_sets(g, 0.10)
    books['quintile'][ym] = top_sets(g, 0.20)

def churn_series(kind):
    """drag components indexed by RETURN month m: book for m is formed on
    signal month m-1; churn = membership change vs book formed on m-2."""
    months = sorted(books[kind])
    out = {}
    for i in range(1, len(months)):
        prev, cur = books[kind][months[i - 1]], books[kind][months[i]]
        inter = len(prev & cur)
        # return month = month after the 'cur' signal month
        y, m = map(int, months[i].split('-'))
        m += 1
        if m == 13: y, m = y + 1, 1
        rm = f'{y:04d}-{m:02d}'
        out[rm] = (1 - inter / len(prev), 1 - inter / len(cur), len(cur))
    return out

CH = {k: churn_series(k) for k in books}
churn_stats = {}
for k, s in CH.items():
    vals = [v[0] + v[1] for ym, v in s.items() if '2010-01' <= ym <= END]
    churn_stats[k] = {'mean_total_churn': float(np.mean(vals)),
                      'median_total_churn': float(np.median(vals)),
                      'mean_monthly_drag_pct': float(np.mean(vals) * RATE * 100)}
print('churn stats:', json.dumps(churn_stats, indent=1), flush=True)

# ---------- 2. portfolio return series ----------
def load_series(path, signal, port):
    df = pd.read_parquet(path, columns=['signalname', 'port', 'date', 'ret', 'Nlong', 'signallag'])
    df = df[(df.signalname == signal) & (df.port.astype(str) == port)].copy()
    df['ret'] = df['ret'] / 100.0  # OSAP Alt/placebo files store returns in PERCENT
    df['ym'] = pd.to_datetime(df.date).dt.strftime('%Y-%m')
    df = df.sort_values('ym')
    return df.set_index('ym')

mine_df = load_series(DS + 'Alt_DecilesEW.parquet', 'REV6', '10')
pub_df = load_series(DS + 'Alt_QuintilesEW.parquet', 'REV6', '05')
assert mine_df.ret.abs().max() < 1.5 and pub_df.ret.abs().max() < 1.5, 'return units still wrong'
print('REV6 decile months:', mine_df.index.min(), '->', mine_df.index.max(), flush=True)
print('median Nlong decile: %.0f | quintile: %.0f' % (
    mine_df.Nlong.median(), pub_df.Nlong.median()), flush=True)

pl_names_all = pd.read_parquet(DS + 'PlaceboPortsFull.parquet', columns=['signalname'])
PLACEBOS = sorted(pl_names_all.signalname.unique())[:20]
print('placebo signals (first 20 alphabetical):', PLACEBOS, flush=True)
pl_df = pd.read_parquet(DS + 'PlaceboPortsFull.parquet',
                        columns=['signalname', 'port', 'date', 'ret'])
pl_df = pl_df[pl_df.port.astype(str) == '05']
pl_df['ret'] = pl_df['ret'] / 100.0  # percent -> decimal, as above
pl_df['ym'] = pd.to_datetime(pl_df.date).dt.strftime('%Y-%m')
placebo_series = {s: g.set_index('ym').ret for s, g in pl_df.groupby('signalname')
                  if s in PLACEBOS}

# ---------- 3. engine ----------
def run_pot(ret_series, churn, start, end=END, bound=False):
    """ret_series: Series indexed by 'YYYY-MM' of gross monthly returns.
    churn: dict return-month -> (churn_out, churn_in, n). Returns equity
    Series (month-end values, starting at 100 before first month)."""
    months = [m for m in ret_series.index if start <= m <= end]
    eq = [100.0]
    idx = ['start']
    total_cost = 0.0
    for i, m in enumerate(months):
        if bound:
            drag = RATE if i == 0 else 2 * RATE
        elif i == 0:
            drag = RATE  # full buy-in, one side
        else:
            co, ci, _ = churn.get(m, (np.nan, np.nan, 0))
            if np.isnan(co):  # fallback: trailing mean churn
                past = [v[0] + v[1] for ym, v in churn.items() if ym < m]
                drag = float(np.mean(past)) * RATE
            else:
                drag = (co + ci) * RATE
        total_cost += eq[-1] * drag
        eq.append(eq[-1] * (1 + ret_series[m]) * (1 - drag))
        idx.append(m)
    return pd.Series(eq, index=idx), total_cost

def dist_stats(eq):
    """Per-period (monthly) distribution + drawdown from an equity Series
    whose first entry is the start mark."""
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = (eq / peak - 1).min()
    # longest losing streak (months with ret < 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months)
    highs = eq[eq >= peak - 1e-12]
    gaps = np.diff(eq.index.get_indexer(highs.index)) if len(highs) > 1 else np.array([0])
    # simpler: months since last new high, max
    since = 0; max_since = 0
    runmax = -np.inf
    for v in eq:
        if v >= runmax: runmax = v; since = 0
        else: since += 1; max_since = max(max_since, since)
    return {
        'n_months': int(len(rets)),
        'median_month_pct': float(rets.median() * 100),
        'share_positive_pct': float((rets > 0).mean() * 100),
        'best_month_pct': float(rets.max() * 100),
        'worst_month_pct': float(rets.min() * 100),
        'mean_month_pct_secondary': float(rets.mean() * 100),
        'longest_losing_streak_months': int(streak),
        'longest_stretch_between_highs_months': int(max_since),
        'max_drawdown_pct': float(dd * 100),
    }

results = {'family': 'hunt-analyst-revisions', 'grade': 'CITATION-GRADE chassis (OSAP published portfolio returns; program roads + modeled program costs)',
           'spec_frozen': '2026-11-22T19:45:45Z', 'churn_stats': churn_stats,
           'placebo_signals': PLACEBOS, 'roads': {}, 'equity_curves': {},
           'champions': CHAMP, 'spy_reference': SPYREF}

for road, start in ROADS.items():
    my_eq, my_cost = run_pot(mine_df.ret, CH['decile'], start)
    pub_eq, pub_cost = run_pot(pub_df.ret, CH['quintile'], start)
    bound_eq, _ = run_pot(mine_df.ret, CH['decile'], start, bound=True)
    pl_finals = {}
    for s, ser in placebo_series.items():
        e, _ = run_pot(ser, CH['quintile'], start)
        pl_finals[s] = float(e.iloc[-1])
    beaten = sum(1 for v in pl_finals.values() if my_eq.iloc[-1] > v)
    r = {
        'window': f'{start} -> {END} (OSAP series end; program road tail to 2026-11 unavailable)',
        'my_final': float(my_eq.iloc[-1]), 'my_maxdd_pct': dist_stats(my_eq)['max_drawdown_pct'],
        'my_costs_paid': float(my_cost),
        'published_quintile_final': float(pub_eq.iloc[-1]),
        'published_maxdd_pct': dist_stats(pub_eq)['max_drawdown_pct'],
        'full_replacement_bound_final': float(bound_eq.iloc[-1]),
        'champion': CHAMP[road], 'spy_reference': SPYREF[road],
        'placebos_beaten_of_20': int(beaten),
        'placebo_median_final': float(np.median(list(pl_finals.values()))),
        'placebo_finals': pl_finals,
        'median_Nlong_mine': float(mine_df.loc[start:END].Nlong.median()),
        'median_Nlong_published': float(pub_df.loc[start:END].Nlong.median()),
        'my_distribution': dist_stats(my_eq),
        'published_distribution': dist_stats(pub_eq),
    }
    results['roads'][road] = r
    results['equity_curves'][road] = {
        'months': list(my_eq.index), 'mine': [float(x) for x in my_eq],
        'published': [float(x) for x in pub_eq]}
    print(f"{road}: mine ${r['my_final']:.2f} (DD {r['my_maxdd_pct']:.1f}%) | "
          f"published ${r['published_quintile_final']:.2f} | bound ${r['full_replacement_bound_final']:.2f} | "
          f"placebos beaten {beaten}/20", flush=True)

# ---------- 4. confirmation material (computed for the record) ----------
conf = {}
for road, start in ROADS.items():
    years = list(range(int(start[:4]), 2026))
    folds = {}
    for y in years:
        e, _ = run_pot(mine_df.ret, CH['decile'], f'{y}-01', f'{y}-12')
        p, _ = run_pot(pub_df.ret, CH['quintile'], f'{y}-01', f'{y}-12')
        folds[str(y)] = {'mine': float(e.iloc[-1]), 'published': float(p.iloc[-1])}
    months = [m for m in mine_df.index if start <= m <= END]
    half = months[len(months) // 2]
    h1e, _ = run_pot(mine_df.ret, CH['decile'], start, months[len(months) // 2 - 1])
    h2e, _ = run_pot(mine_df.ret, CH['decile'], half, END)
    h1p, _ = run_pot(pub_df.ret, CH['quintile'], start, months[len(months) // 2 - 1])
    h2p, _ = run_pot(pub_df.ret, CH['quintile'], half, END)
    mv = [f['mine'] for f in folds.values()]
    conf[road] = {
        'yearly_folds': folds,
        'fold_median_mine': float(np.median(mv)),
        'folds_above_100': int(sum(1 for v in mv if v > 100)),
        'folds_beating_published': int(sum(1 for f in folds.values() if f['mine'] > f['published'])),
        'n_folds': len(folds),
        'half_windows': {'first': {'mine': float(h1e.iloc[-1]), 'published': float(h1p.iloc[-1])},
                         'second': {'mine': float(h2e.iloc[-1]), 'published': float(h2p.iloc[-1])}},
        'champion_beaten': bool(results['roads'][road]['my_final'] > CHAMP[road]),
    }
    conf[road]['confirmation_pass'] = bool(
        conf[road]['champion_beaten'] and conf[road]['fold_median_mine'] >= 100
        and conf[road]['folds_above_100'] * 2 >= conf[road]['n_folds']
        and conf[road]['folds_beating_published'] * 2 >= conf[road]['n_folds']
        and conf[road]['half_windows']['first']['mine'] > conf[road]['half_windows']['first']['published']
        and conf[road]['half_windows']['second']['mine'] > conf[road]['half_windows']['second']['published']
        and results['roads'][road]['placebos_beaten_of_20'] >= 16)
results['confirmation'] = conf

with open(OUT + 'results.json', 'w') as f:
    json.dump(results, f, indent=1)
print('WROTE results.json')
