#!/usr/bin/env python3
"""Print-mode chunk driver for the SY sweep (python file writes are
intermittently blocked in this environment; results go to stdout and are
persisted by the caller). Usage:
  chunk_sy.py cells ROAD[,ROAD...] RULES[,RULES...]   -> finals+placebos
  chunk_sy.py folds COUNT                              -> confirmation folds
  chunk_sy.py curves COUNT                             -> full runs, all roads/rules
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_sy as S

def cells(roads, rules_list, counts=None):
    out = {}
    for rname in roads:
        forms = S.ROADS[rname]
        bad = [F for F in forms if len(S.snapshot(F)['universe']) < 300]
        if bad:
            out[rname] = {'dropped': f'eligible universe <300 at formations {bad}'}
            continue
        out[rname] = {}
        for rules in rules_list:
            out[rname][rules] = {}
            for count in (counts if counts is not None else S.GRID):
                r = S.run(forms, count, rules)
                cell = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'vanished_zeroed', 'halts', 'spy_final_same_window')}
                if count != 'ALL':
                    twins = [S.run(forms, count, rules, seed=s)['final'] for s in range(1, 21)]
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
    S.D = S.Data()
    fences = {}
    for F in range(2012, 2026):
        snap = S.snapshot(F)
        fences[F] = {**snap['fence'], 'universe': len(snap['universe']), 'n_native': snap['n_native']}
    mode = sys.argv[1]
    if mode == 'cells':
        roads = sys.argv[2].split(',')
        rules_list = sys.argv[3].split(',')
        counts = None
        if len(sys.argv) > 4:
            counts = [int(c) if c.isdigit() else c for c in sys.argv[4].split(',')]
        obj = {'mode': 'cells', 'fences': fences, 'roads': cells(roads, rules_list, counts)}
        suffix = ('_' + '-'.join(str(c) for c in counts)) if counts else ''
        emit(obj, 'chunk_sy_cells_%s_%s%s.json' % ('-'.join(roads), '-'.join(rules_list), suffix))
        for rn, rc in obj['roads'].items():
            if 'dropped' in rc: print(rn, 'DROPPED'); continue
            for rl, cc in rc.items():
                print(rn, rl, {k: v['final'] for k, v in cc.items()})
    elif mode == 'folds':
        count = sys.argv[2]
        count = int(count) if count.isdigit() else count
        out = {}
        for fname, forms in S.FOLDS.items():
            out[fname] = {'candidate': S.run(forms, count, 'native')['final'],
                          'native': S.run(forms, 'NATIVE', 'native')['final']}
        obj = {'mode': 'folds', 'count': str(count), 'folds': out}
        emit(obj, 'chunk_sy_folds_%s.json' % count)
        print(json.dumps(obj))
    elif mode == 'curves':
        count = sys.argv[2]
        count = int(count) if count.isdigit() else count
        out = {}
        for rules in ('native', 'house'):
            out[rules] = {}
            for rname, forms in S.ROADS.items():
                r = S.run(forms, count, rules)
                out[rules][rname] = {'final': r['final'], 'curve': r['curve'], 'yearly': r['yearly']}
        obj = {'mode': 'curves', 'count': str(count), 'runs': out}
        emit(obj, 'chunk_sy_curves_%s.json' % count)
        print('curves finals', {rl: {rn: rr['final'] for rn, rr in rv.items()} for rl, rv in out.items()})
    else:
        raise SystemExit('unknown mode ' + mode)

if __name__ == '__main__':
    main()
