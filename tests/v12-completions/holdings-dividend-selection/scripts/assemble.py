#!/usr/bin/env python3
"""Assemble final results.json from the chunk files in data/ and compute
per-period distributions (Terry's REPORTING STANDARD) for the winning and
native counts of each line / ruleset.
SY tempo: annual formation-year periods (yearly returns; new-high stretch
in months from the monthly curve). DG tempo: quarterly periods."""
import json, os, sys, glob, statistics, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, HERE)
from period_stats import period_stats

def load(pat):
    out = {}
    for p in sorted(glob.glob(os.path.join(DATA, pat))):
        try:
            out[os.path.basename(p)] = json.load(open(p))
        except Exception as e:
            print('skip unreadable', p, e)
    return out

def merge_cells(files):
    roads = {}; fences = None
    for name, obj in files.items():
        if obj.get('mode') != 'cells': continue
        if fences is None and 'fences' in obj: fences = obj['fences']
        for rname, rc in obj['roads'].items():
            if 'dropped' in rc:
                roads[rname] = rc; continue
            roads.setdefault(rname, {})
            for rules, cc in rc.items():
                roads[rname].setdefault(rules, {}).update(cc)
    return roads, fences

def totals(roads, rules):
    t = {}
    for rname, rc in roads.items():
        if 'dropped' in rc: continue
        for count, c in rc[rules].items():
            t[count] = round(t.get(count, 0.0) + c['final'], 2)
    return t

def sy_dist(run):
    rets = [y['ret'] for y in run['yearly'] if y.get('picks')]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; run_ = 0
    for r in rets:
        run_ = run_ + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, run_)
    peak = 100.0; since = 0; longest_gap = 0
    for _, v in run['curve']:
        if v > peak: peak = v; longest_gap = max(longest_gap, since); since = 0
        else: since += 1
    longest_gap = max(longest_gap, since)
    return {'period': 'annual (formation year, Jul-Jun)', 'n_periods': len(rets),
            'pct_profitable': round(100.0 * prof / len(rets), 1),
            'median_period_pct': round(100.0 * statistics.median(rets), 2),
            'best_period_pct': round(100.0 * max(rets), 2),
            'worst_period_pct': round(100.0 * min(rets), 2),
            'longest_losing_run_periods': longest_loss,
            'longest_stretch_between_new_highs_months': longest_gap,
            'average_period_pct_SECONDARY': round(100.0 * statistics.mean(rets), 2),
            'period_returns_pct': [round(100.0 * r, 2) for r in rets]}

def save_long(obj, path, tries=16, delay=5):
    tmp = path + '.tmp'
    for i in range(tries):
        try:
            with open(tmp, 'w') as f: json.dump(obj, f, indent=1)
            os.replace(tmp, path)
            return True
        except OSError:
            time.sleep(delay)
    return False

def main():
    out = {'wing': 'holdings-count sweep (v12)',
           'note': 'All cells from chunk files in data/; deterministic engines — chunk finals cross-checked across independent re-runs.'}
    # ---- SY ----
    sy_files = load('chunk_sy_cells_*.json')
    sy_roads, fences = merge_cells(sy_files)
    sy = {'form_swept': 'shareholder-yield: v12 CONSTRUCTED Faber three-leg yield, largest-1000-eligible universe (price-coverage-limited to 355-631 eligible per formation at run time — see fences), annual June formation, equal weight; native count = published decile (NATIVE, 36-64 names); house = v9 floor + flat program costs; native rules = tiered costs, no floor',
          'fences': fences, 'roads': sy_roads,
          'totals_native': totals(sy_roads, 'native'), 'totals_house': totals(sy_roads, 'house'),
          'confirmation': {}, 'curves': {}, 'distributions': {}}
    for name, obj in load('chunk_sy_folds_*.json').items():
        sy['confirmation'][obj['count']] = obj['folds']
    for name, obj in load('chunk_sy_curves_*.json').items():
        sy['curves'][obj['count']] = obj['runs']
    for rules in ('native', 'house'):
        sy['distributions'][rules] = {}
        win = max(sy['totals_' + rules], key=lambda k: sy['totals_' + rules][k])
        sy['winning_count_' + rules] = win
        for label, count in (('winning', win), ('native', 'NATIVE')):
            if count in sy['curves']:
                sy['distributions'][rules][label] = {
                    rname: {'count': count, 'stats': sy_dist(sy['curves'][count][rules][rname])}
                    for rname in sy_roads if 'dropped' not in sy_roads[rname]}
    out['shareholder-yield'] = sy
    # ---- DG ----
    dg_files = load('chunk_dg_cells_*.json')
    dg_roads, _ = merge_cells(dg_files)
    dg = {'form_swept': 'dividend-growth: S&P Dividend Aristocrats published rosters (canonical v12 construction); native count = ALL qualifiers (43-71); top-N overlay ranks qualifiers by trailing calendar-year DPS yield (CONSTRUCTED ranking); quarterly EW resets; native rules = no floor; house = v9 floor; costs 0.10%/side + $0.01/sell in both',
          'roads': dg_roads,
          'totals_native': totals(dg_roads, 'native'), 'totals_house': totals(dg_roads, 'house'),
          'confirmation': {}, 'curves': {}, 'distributions': {}}
    for name, obj in load('chunk_dg_folds_*.json').items():
        dg['confirmation'][obj['count']] = obj['folds']
    for name, obj in load('chunk_dg_curves_*.json').items():
        dg['curves'][obj['count']] = obj['runs']
    for rules in ('native', 'house'):
        dg['distributions'][rules] = {}
        win = max(dg['totals_' + rules], key=lambda k: dg['totals_' + rules][k])
        dg['winning_count_' + rules] = win
        for label, count in (('winning', win), ('native', 'ALL')):
            if count in dg['curves']:
                dg['distributions'][rules][label] = {
                    rname: {'count': count,
                            'stats': period_stats(dg['curves'][count][rules][rname]['curve_monthly'], 'quarterly')}
                    for rname in dg_roads}
    out['dividend-growth'] = dg
    if save_long(out, os.path.join(ROOT, 'results.json')):
        print('SAVED results.json')
    else:
        print('SAVE FAILED')
    print('SY totals native', sy['totals_native'])
    print('SY totals house', sy['totals_house'])
    print('DG totals native', dg['totals_native'])
    print('DG totals house', dg['totals_house'])
    print('SY dist sample (native rules, LONG):')
    print(json.dumps(sy['distributions']['native'], indent=1)[:1500])
    print('DG dist sample (native rules, LONG):')
    print(json.dumps(dg['distributions']['native'], indent=1)[:1500])

if __name__ == '__main__':
    main()
