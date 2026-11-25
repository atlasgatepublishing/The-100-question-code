#!/usr/bin/env python3
"""Precompute shareholder-yield formation snapshots (eligible universe +
SY ranking) once, cache to data/sy_snapshots.json, so sweep chunks stay
small. Usage: build_sy_cache.py F_START F_END"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
import sweep_sy as S

def main():
    f0, f1 = int(sys.argv[1]), int(sys.argv[2])
    S.D = S.Data()
    print('candidates with prices:', sum(1 for c in S.D.cand if c in S.D.px), '/', len(S.D.cand), flush=True)
    for F in range(f0, f1 + 1):
        snap = S.snapshot(F)
        entry = {
            'fence': snap['fence'],
            'universe': {str(c): {'ticker': u['ticker'], 'cap': u['cap'],
                                  'px_adj': u['px_adj'], 'sy': u['sy']}
                         for c, u in snap['universe'].items()},
            'ranked': [str(c) for c in snap['ranked']],
            'n_native': snap['n_native']}
        print('formation', F, 'universe', len(snap['universe']), 'native', snap['n_native'], flush=True)
        path = os.path.join(ROOT, 'data', f'sy_snap_{F}.json')
        import time as _t
        for attempt in range(30):
            try:
                tmp = path + '.tmp'
                with open(tmp, 'w') as f: json.dump(entry, f)
                os.replace(tmp, path)
                break
            except OSError as e:
                print('write retry', F, attempt, e, flush=True); _t.sleep(5)
        else:
            raise RuntimeError('could not write ' + path)
    print('snapshots saved', flush=True)

if __name__ == '__main__':
    main()
