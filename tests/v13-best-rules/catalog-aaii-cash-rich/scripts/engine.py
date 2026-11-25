#!/usr/bin/env python3
"""V13 BEST-RULES engine — AAII Cash Rich Firms screen.
Frozen by BEST-RULES-SPEC.md: published criteria at full strength; chassis =
wide SY-stack pond + EDGAR frames fetched into this folder; annual June
formations on FY F-1 frames; ALL passers equal weight; no floor; program
tiered costs; vanished->ZERO; 20-seed placebos from the same eligible pond
at the same count. Simulation only. Public data only."""
import json, os, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def ym(y, m): return f'{y:04d}-{m:02d}'

def months_between(a, b):
    y, m = int(a[:4]), int(a[5:7]); out = []
    while ym(y, m) <= b:
        out.append(ym(y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    return out

class Data:
    def __init__(self):
        self.cand = {int(k): v for k, v in loadj(os.path.join(SY, 'candidates.json')).items()}
        self.sic = {int(k): v for k, v in loadj(os.path.join(FAM, 'data', 'sic.json')).items()}
        self.px = {}
        for cik, info in self.cand.items():
            t = info['ticker'].replace('/', '-')
            p = os.path.join(SY, f'px_{t}.json')
            if os.path.exists(p):
                try:
                    rows = loadj(p)
                    if len(rows) >= 6: self.px[cik] = {r[0]: (r[1], r[2]) for r in rows}
                except Exception: pass
        self.spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
        self.myfr = os.path.join(FAM, 'data', 'frames')
        self.syfr = os.path.join(SY, 'frames')
        self._fr = {}
        # split factors, chassis method (SY engine)
        sh = {y: self.frame('Shares', y, 'I', sy=True) for y in range(2009, 2026)}
        self.sh_series = sh
        self.sf = {}
        for cik in self.cand:
            avail = [(y, sh[y][cik]) for y in range(2009, 2026) if cik in sh[y]]
            d = {}
            for F in range(2010, 2027):
                f = 1.0
                for (y0, a), (y1, b) in zip(avail, avail[1:]):
                    if y1 >= F and a:
                        r = b / a
                        if r >= 1.6 or r <= 0.625: f *= r
                d[F] = f
            self.sf[cik] = d
    def frame(self, name, y, kind, sy=False):
        key = (name, y, kind, sy)
        if key not in self._fr:
            base = self.syfr if sy else self.myfr
            self._fr[key] = {int(k): v for k, v in loadj(os.path.join(base, f'{name}_{y}{kind}.json')).items()}
        return self._fr[key]
    def price(self, cik, month, adj=True):
        s = self.px.get(cik)
        if not s: return None
        if month in s: return s[month][0] if adj else s[month][1]
        prev = [m for m in s if m <= month]
        if not prev: return None
        return s[max(prev)][0] if adj else s[max(prev)][1]
    def last_bar(self, cik):
        s = self.px.get(cik)
        return max(s) if s else None
    def has_bar_between(self, cik, lo, hi):
        s = self.px.get(cik)
        return bool(s) and any(lo <= m <= hi for m in s)

D = None

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def median(v):
    v = sorted(v); return v[len(v) // 2] if v else None

_SNAP = {}
def snapshot(F):
    """Formation June of F on FY F-1 frames. Returns base/eligible/passers."""
    if F in _SNAP: return _SNAP[F]
    y = F - 1
    A = D.frame('Assets', y, 'I', sy=True)
    CASH = D.frame('CashAndCashEquivalentsAtCarryingValue', y, 'I')
    STI = D.frame('ShortTermInvestments', y, 'I')
    LIAB = D.frame('Liabilities', y, 'I')
    LCUR = D.frame('LiabilitiesCurrent', y, 'I')
    LTDc = D.frame('LongTermDebtCurrent', y, 'I', sy=True)
    LTDn = D.frame('LongTermDebtNoncurrent', y, 'I', sy=True)
    EQ = D.frame('StockholdersEquity', y, 'I')
    NI = D.frame('NetIncomeLoss', y, 'D')
    SH = D.frame('Shares', y, 'I', sy=True)
    SH0 = D.frame('Shares', y - 1, 'I', sy=True) if y - 1 >= 2009 else {}
    def ltd(cik):
        a, b = LTDc.get(cik), LTDn.get(cik)
        if a is None and b is None: return None
        return (a or 0) + (b or 0)
    base = {}
    fence = {'roster_year': 0, 'reuse_excluded': 0, 'no_price': 0, 'no_sic': 0}
    for cik, info in D.cand.items():
        if str(y) not in info.get('years', {}): continue
        fence['roster_year'] += 1
        if info.get('reuse_risk'):
            fence['reuse_excluded'] += 1; continue
        if not D.has_bar_between(cik, ym(F, 1), ym(F, 6)):
            fence['no_price'] += 1; continue
        sh = SH.get(cik) or SH0.get(cik)   # chassis convention (v12 engines): shares FY F-1, else F-2
        praw = D.price(cik, ym(F, 6), adj=False); padj = D.price(cik, ym(F, 6), adj=True)
        at = A.get(cik); liab = LIAB.get(cik); cash = CASH.get(cik); ni = NI.get(cik)
        if not sh or not praw or not padj or None in (at, liab, cash, ni): continue
        cap = sh * praw * D.sf.get(cik, {}).get(F, 1.0)
        if not cap: continue
        sic = str(D.sic.get(cik) or '')
        base[cik] = {'at': at, 'liab': liab, 'cash': cash + (STI.get(cik) or 0),
                     'ni': ni, 'cap': cap, 'price': praw, 'px_adj': padj,
                     'liab_at': liab / at, 'sic': sic, 'sic2': sic[:2],
                     'ltd': ltd(cik), 'eq': EQ.get(cik), 'lcur': LCUR.get(cik),
                     'ticker': info['ticker'], 'rate': cost_rate(cap)}
    # industry medians over the data-complete base (v12 chassis convention)
    g1, g2 = {}, {}
    for cik, r in base.items():
        if r['sic2']: g1.setdefault(r['sic2'], []).append(r['liab_at'])
        if r['ltd'] is not None and r['eq']:
            g2.setdefault(r['sic2'], []).append(r['ltd'] / (r['ltd'] + r['eq']))
    med1 = {g: median(v) for g, v in g1.items()}
    med2 = {g: median(v) for g, v in g2.items()}
    elig, pas = {}, {}
    for cik, r in base.items():
        if not r['sic']:
            fence['no_sic'] += 1; continue
        if r['sic'][:1] in ('4', '6'): continue          # utilities + financials/RE (published exclusion, v12 approx)
        if r['ni'] <= 0: continue
        if r['cap'] <= 50e6 or r['price'] <= 5: continue
        elig[cik] = r
        if r['liab_at'] >= med1.get(r['sic2'], 1e18): continue
        if r['ltd'] is None or not r['eq']: continue
        if r['ltd'] / (r['ltd'] + r['eq']) >= med2.get(r['sic2'], 1e18): continue
        if r['lcur'] is None: continue
        if r['cash'] / r['cap'] <= 0.20: continue
        if (r['cash'] - r['lcur']) / r['cap'] <= 0.20: continue
        pas[cik] = r
    out = {'base': base, 'elig': elig, 'pass': pas, 'fence': fence,
           'base_n': len(base), 'elig_n': len(elig)}
    _SNAP[F] = out
    return out

def run_road(start_month, formations, seed=None):
    """Monthly curve from start_month to 2026-11. seed=None -> screen picks;
    else placebo: same count drawn from eligible non-passers each formation."""
    cash = 100.0; curve = {}; total_costs = 0.0; vanished = 0; yearly = []
    months_all = months_between(start_month, '2026-11')
    fset = {ym(F, 6): F for F in formations}
    pos = {}          # cik -> shares
    pos_info = {}     # cik -> snapshot row (for rates)
    cur_F = None
    for mm in months_all:
        if mm in fset:
            F = fset[mm]; cur_F = F
            snap = snapshot(F)
            # sell existing positions at this June close (formation roll)
            if pos:
                end = 0.0
                for c, shn in pos.items():
                    lb = D.last_bar(c)
                    if lb is not None and lb < mm: vanished += 1; continue
                    p = D.price(c, mm, adj=True)
                    if p is None: continue
                    gross = shn * p; cst = gross * pos_info[c]['rate']
                    total_costs += cst; end += gross - cst
                cash = end; pos = {}; pos_info = {}
            if seed is None:
                picks = list(snap['pass'].keys()); src = snap['pass']
            else:
                rng = random.Random(seed * 100003 + F)
                pool = [c for c in snap['elig'] if c not in snap['pass']]
                rng.shuffle(pool)
                picks = pool[:min(len(snap['pass']), len(pool))]; src = snap['elig']
            start_val = cash
            if picks:
                w = cash / len(picks)
                for c in picks:
                    r = src[c]; cst = w * r['rate']; total_costs += cst
                    pos[c] = (w - cst) / r['px_adj']; pos_info[c] = r
            yearly.append({'formation': F, 'n_pass': len(snap['pass']),
                           'n_elig': snap['elig_n'], 'n_base': snap['base_n'],
                           'picks': [snap['pass'][c]['ticker'] for c in snap['pass']] if seed is None else len(picks),
                           'ret': None, '_start': start_val})
        # mark
        if pos:
            val = 0.0
            for c, shn in pos.items():
                lb = D.last_bar(c)
                if lb is not None and mm > lb: continue   # vanished -> ZERO
                p = D.price(c, mm, adj=True)
                if p is not None: val += shn * p
            curve[mm] = round(val, 2)
        else:
            curve[mm] = round(cash, 2)
        if pos and mm == ym(cur_F + 1, 6) if cur_F is not None else False:
            pass
    # per-formation-year returns from yearly starts: recompute from curve at June marks
    curve_list = [[m, curve[m]] for m in months_all]
    for i, yr in enumerate(yearly):
        F = yr['formation']
        a = curve.get(ym(F, 6)); b = curve.get(ym(F + 1, 6)) if F < 2026 else curve.get('2026-11')
        yr['ret'] = round(b / yr['_start'] - 1, 4) if a is not None and b and yr['_start'] else None
        del yr['_start']
    peak = 100.0; maxdd = 0.0
    for _, v in curve_list:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    return {'final': curve_list[-1][1], 'curve': curve_list, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'vanished_zeroed': vanished, 'yearly': yearly}

def spy_window(a, b):
    x, y = D.spy.get(a), D.spy.get(b)
    return round(100 * y / x, 2) if x and y else None

def period_stats(curve):
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if not rets: return {}
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    # calendar-year returns
    by_year = {}
    for m, v in curve: by_year.setdefault(m[:4], []).append((m, v))
    yrs = sorted(by_year)
    yrets = []
    prev_end = 100.0
    for yy in yrs:
        end = by_year[yy][-1][1]
        yrets.append(end / prev_end - 1); prev_end = end
    ylos = cur = 0
    for r in yrets:
        cur = cur + 1 if r < 0 else 0; ylos = max(ylos, cur)
    return {'n_months': len(rets), 'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'median_month_pct': round(100 * float(np.median(rets)), 2),
            'best_month_pct': round(100 * max(rets), 2), 'worst_month_pct': round(100 * min(rets), 2),
            'longest_losing_streak_months': los, 'longest_between_highs_months': longest,
            'avg_month_pct_secondary': round(100 * float(np.mean(rets)), 2),
            'annual': {'n_years': len(yrets), 'median_year_pct': round(100 * float(np.median(yrets)), 2),
                       'share_positive': round(sum(1 for r in yrets if r > 0) / len(yrets), 3),
                       'best_year_pct': round(100 * max(yrets), 2), 'worst_year_pct': round(100 * min(yrets), 2),
                       'longest_losing_streak_years': ylos}}

ROADS = {'LONG': ('2010-01', list(range(2010, 2027)), '2010-06', None),
         'DECADE': ('2016-11', list(range(2017, 2027)), '2016-11', '2026-11'),
         'CONT': ('2019-01', list(range(2019, 2027)), '2019-01', '2026-11'),
         'VAL': ('2023-01', list(range(2023, 2027)), '2023-01', '2026-11')}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}

def main():
    global D
    D = Data()
    out = {'family': 'catalog-aaii-cash-rich', 'program': 'v13-best-rules', 'roads': {}}
    for F in range(2010, 2027):
        s = snapshot(F)
        print('formation', F, 'base', s['base_n'], 'elig', s['elig_n'], 'pass', len(s['pass']),
              [s['pass'][c]['ticker'] for c in s['pass']], flush=True)
    out['formations'] = {str(F): {'base': snapshot(F)['base_n'], 'elig': snapshot(F)['elig_n'],
                                  'pass': len(snapshot(F)['pass']),
                                  'tickers': [snapshot(F)['pass'][c]['ticker'] for c in snapshot(F)['pass']],
                                  'fence': snapshot(F)['fence']} for F in range(2010, 2027)}
    for name, (start, forms, sa, sb) in ROADS.items():
        r = run_road(start, forms)
        twins = [run_road(start, forms, seed=s) for s in range(1, 21)]
        tf = sorted(t['final'] for t in twins)
        r['placebos'] = {'beaten': sum(1 for t in twins if r['final'] > t['final']),
                         'median': tf[10], 'best': tf[-1], 'worst': tf[0],
                         'finals': [t['final'] for t in twins]}
        r['period_stats'] = period_stats(r['curve'])
        r['spy_same_window'] = spy_window(sa, sb) if sb else None
        r['champion_vm'] = CHAMP[name]; r['spy_program_ref'] = SPYREF[name]
        r['beats_champion'] = r['final'] > CHAMP[name]
        out['roads'][name] = r
        print(name, r['final'], 'dd', r['max_dd'], 'pb', r['placebos']['beaten'], '/20', flush=True)
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('saved', flush=True)

if __name__ == '__main__':
    main()
