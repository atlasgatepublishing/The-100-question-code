#!/usr/bin/env python3
"""Print-mode chunk driver for the DG sweep. Usage:
  chunk_dg.py cells ROAD[,ROAD...] RULES[,RULES...]
  chunk_dg.py folds COUNT     (FOLD_A start2010, FOLD_B start2018 vs ALL)
  chunk_dg.py curves COUNT    (full monthly-curve runs, all roads/rules)
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_dg as G

def cells(roads, rules_list, counts=None):
    out = {}
    for rname in roads:
        sy_ = G.ROADS[rname]
        out[rname] = {}
        for rules in rules_list:
            out[rname][rules] = {}
            for count in (counts if counts is not None else G.GRID):
                r = G.run(sy_, count, rules)
                cell = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'vanished_zeroed', 'halts', 'spy_final_same_window')}
                if count != 'ALL':
                    twins = [G.run(sy_, count, rules, seed=s)['final'] for s in range(1, 21)]
                    cell['placebo_finals'] = twins
                    cell['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
                out[rname][rules][str(count)] = cell
    return out

def save_long(obj, path, tries=16, delay=5):
    import time as _t
    tmp = path + '.tmp'
    for i in range(tries):
        try:
            with open(tmp, 'w') as f: json.dump(obj, f)
            os.replace(tmp, path)
            return True
        except OSError:
            _t.sleep(delay)
    return False

def emit(obj, name):
    path = os.path.join(HERE, '..', 'data', name)
    if save_long(obj, path):
        print('SAVED', path)
    else:
        print('SAVE FAILED — JSON FOLLOWS')
        print(json.dumps(obj))

def main():
    G.D = G.Data()
    mode = sys.argv[1]
    if mode == 'cells':
        counts = None
        if len(sys.argv) > 4:
            counts = [int(c) if c.isdigit() else c for c in sys.argv[4].split(',')]
        roads = sys.argv[2].split(','); rules_list = sys.argv[3].split(',')
        obj = {'mode': 'cells', 'roads': cells(roads, rules_list, counts)}
        suffix = ('_' + '-'.join(str(c) for c in counts)) if counts else ''
        emit(obj, 'chunk_dg_cells_%s_%s%s.json' % ('-'.join(roads), '-'.join(rules_list), suffix))
        for rn, rc in obj['roads'].items():
            for rl, cc in rc.items():
                print(rn, rl, {k: v['final'] for k, v in cc.items()})
    elif mode == 'folds':
        count = sys.argv[2]
        count = int(count) if count.isdigit() else count
        out = {'FOLD_A_start2010': {'candidate': G.run(2010, count, 'native')['final'],
                                    'native_ALL': G.run(2010, 'ALL', 'native')['final']},
               'FOLD_B_start2018': {'candidate': G.run(2018, count, 'native')['final'],
                                    'native_ALL': G.run(2018, 'ALL', 'native')['final']}}
        obj = {'mode': 'folds', 'count': str(count), 'folds': out}
        emit(obj, 'chunk_dg_folds_%s.json' % count)
        print(json.dumps(obj))
    elif mode == 'curves':
        count = sys.argv[2]
        count = int(count) if count.isdigit() else count
        out = {}
        for rules in ('native', 'house'):
            out[rules] = {rname: G.run(sy_, count, rules) for rname, sy_ in G.ROADS.items()}
        obj = {'mode': 'curves', 'count': str(count), 'runs': out}
        emit(obj, 'chunk_dg_curves_%s.json' % count)
        print('curves finals', {rl: {rn: rr['final'] for rn, rr in rv.items()} for rl, rv in out.items()})
    else:
        raise SystemExit('unknown mode ' + mode)

if __name__ == '__main__':
    main()
