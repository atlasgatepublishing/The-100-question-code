#!/usr/bin/env python3
"""V13 Best-Rules run for catalog-aaii-muhlenkamp. Spec: BEST-RULES-SPEC.md (frozen).
One cell only: core linked ROE/P-E construction, annual June formation,
top-20 by ROE, no floor, native universe, program tiered costs, 20-seed placebos
(chassis built-in). Writes ../results.json."""
import sys, os, json, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chassis as ch

def S_best(F, uni):
    m = ch.base_pool(F, uni)
    m &= F['roe'] >= 0.14
    m &= F['roe5'] > 0.12
    m &= (F['pe'] > 0) & (F['pe'] <= F['roe'] * 100.0)
    m &= F['fcf'] - F['div'] > 0
    return m, F['roe']

def dist(curve):
    """Per-period distribution from monthly curve: annual (formation-year) periods
    and monthly periods."""
    pts = [(ym, v) for ym, v in curve]
    out = {}
    for label, step in (('annual', 12), ('monthly', 1)):
        rets = []
        prev = 100.0
        if step > 1:
            seq = [(ym, v) for ym, v in pts if ym.endswith('-06')]
        else:
            seq = pts
        vals = [100.0] + [v for _, v in seq]
        for a, b in zip(vals[:-1], vals[1:]):
            if a > 0: rets.append(b / a - 1)
        if not rets:
            out[label] = None; continue
        pos = sum(1 for r in rets if r > 0)
        # longest losing streak
        streak = cur = 0
        for r in rets:
            cur = cur + 1 if r <= 0 else 0
            streak = max(streak, cur)
        out[label] = {'n': len(rets), 'share_positive': round(pos / len(rets), 4),
                      'median': round(float(np.median(rets)), 4),
                      'best': round(max(rets), 4), 'worst': round(min(rets), 4),
                      'longest_losing_streak': streak,
                      'mean_secondary': round(float(np.mean(rets)), 4)}
    # longest stretch between new highs (months, from monthly curve)
    peak = 100.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(pts):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(pts) - last_high)
    out['months_between_new_highs_longest'] = longest
    return out

def main():
    roads = {}
    pools = {}
    for y in range(2016, 2026):
        F = ch.features(f'{y:04d}-06')
        mask, _ = S_best(F, 'native')
        pools[str(y)] = int(mask.sum())
    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2'):
        cell = ch.run_cell(S_best, 'native', 'native', 'annual', 20, road, 'ALL')
        cell['distribution'] = dist(cell['curve'])
        roads[road] = cell
        print(road, cell['final'], 'DD', cell['max_dd'], 'pb', cell['placebos_beaten'],
              'spy', cell['spy_same_window'], 'costs', cell['costs'], flush=True)
    res = {'family': 'catalog-aaii-muhlenkamp', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'cell': 'native|nofloor|annual|top20-by-ROE|core: roe>=14 & roe5>12 & 0<pe<=roe*100 & fcf-div>0',
           'pool_sizes_june_native': pools, 'roads': roads}
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results.json')
    json.dump(res, open(out, 'w'), indent=1)
    print('saved', out)

if __name__ == '__main__':
    main()
