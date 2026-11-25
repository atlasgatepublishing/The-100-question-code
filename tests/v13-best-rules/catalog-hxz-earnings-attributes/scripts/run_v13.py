#!/usr/bin/env python3
"""V13 best-rules run for catalog-hxz-earnings-attributes.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Reuses the v12 chassis by importing engine_base with patched paths:
composite signal = equal-weight mean of percentile ranks (published
directions) over Eper/Eprd/Esm/Evr, >=3 attributes incl. Eper required.
Native (ex-financials) universe, annual June formation, top quintile,
equal weight, NO floor, program tiered costs, vanished->ZERO.
20-seed placebos on every road. Simulation only."""
import json, os, sys, math, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.abspath(os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-earnings-attributes'))

# Load the v12 engine as a module but redirect its local-frames dir to v12's data.
sys.path.insert(0, HERE)
import importlib.util
spec = importlib.util.spec_from_file_location('engine_base', os.path.join(HERE, 'engine_base.py'))
E = importlib.util.module_from_spec(spec)
# engine_base resolves LFR relative to its own location (now v13/scripts/..) -> wrong.
# Patch after load is too late (frames load at import). Instead monkeypatch os.path.join? Simpler:
# temporarily symlink: v13/data -> v12/data is NOT allowed (write only in v13 folder is fine: a symlink inside v13 pointing to v12 read-only data).
link = os.path.join(FAM, 'data')
if not os.path.exists(link):
    os.symlink(os.path.join(V12, 'data'), link)
spec.loader.exec_module(E)

SIG = E.SIG  # {F: {cik: {attr: val}}}

def composite(F):
    """Percentile ranks in published direction, averaged. Returns {cik: score}."""
    pool = SIG.get(F, {})
    attrs = [('Eper', 1), ('Eprd', -1), ('Esm', -1), ('Evr', -1)]
    ranks = {}  # attr -> {cik: pct in [0,1], higher = better}
    for name, direction in attrs:
        items = [(c, s[name]) for c, s in pool.items() if name in s]
        items.sort(key=lambda kv: kv[1])  # ascending value
        n = len(items)
        r = {}
        for i, (c, v) in enumerate(items):
            pct = (i + 0.5) / n if n else 0.5
            r[c] = pct if direction < 0 else 1.0 - pct + (0.5 / n if n else 0)
            # direction<0: low value is good -> low value gets pct small... fix below
        # Recompute cleanly: goodness percentile = fraction of firms strictly worse.
        r = {}
        vals = [v for _, v in items]
        for c, v in items:
            if direction > 0:  # high good: worse = values below v
                worse = sum(1 for x in vals if x < v)
            else:              # low good: worse = values above v
                worse = sum(1 for x in vals if x > v)
            r[c] = (worse + 0.5) / n if n else 0.5
        ranks[name] = r
    out = {}
    for c, s in pool.items():
        if 'Eper' not in s: continue
        have = [ranks[a][c] for a, _ in attrs if a in ranks and c in ranks[a]]
        if len(have) >= 3:
            out[c] = sum(have) / len(have)
    return out

COMP = {F: composite(F) for F in range(2016, 2026)}

# Register composite into the engine's signal machinery: inject as a pseudo-signal
# by monkeypatching picks_for / pool_for_signal equivalents — simplest: build a
# parallel run using E.run_road with a hacked SIG view. Instead, replicate the
# pick logic: temporarily overwrite SIG entries with {'COMP': score} and meta.
E.SIGNALS_META['COMP'] = 1
for F in range(2016, 2026):
    for cik, sc in COMP[F].items():
        SIG[F][cik]['COMP'] = sc

ROADS = E.ROADS

def dist_stats(curve, formations):
    """Annual formation-period distribution from monthly curve."""
    # period return per formation year: value at June(F+1) vs June(F) start.
    vals = {m: v for m, v in curve}
    rets = []
    prev = 100.0
    # reconstruct start-of-road value: curve starts July of first formation year at post-first-month value;
    # use formation boundaries: value at each June close = last curve point <= that June.
    pts = [('START', 100.0)]
    for F in formations:
        key = f'{F+1:04d}-06'
        if key in vals: pts.append((key, vals[key]))
    for i in range(1, len(pts)):
        if pts[i-1][1] > 0: rets.append(pts[i][1] / pts[i-1][1] - 1.0)
    if not rets: return {}
    med = statistics.median(rets)
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months) from curve
    peak = 100.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - last_high)
    return {'n_periods': len(rets), 'median_period_pct': round(med * 100, 1),
            'share_positive': f'{pos}/{len(rets)}', 'best_pct': round(max(rets) * 100, 1),
            'worst_pct': round(min(rets) * 100, 1), 'longest_losing_streak': streak,
            'longest_months_between_highs': longest,
            'period_pcts': [round(r * 100, 1) for r in rets],
            'avg_period_pct_secondary': round(sum(rets) / len(rets) * 100, 1)}

def main():
    results = {'family': 'catalog-hxz-earnings-attributes', 'program': 'v13-best-rules',
               'spec': 'BEST-RULES-SPEC.md', 'cell': 'COMP|native|native(no floor)|annual|QUINTILE',
               'pool_sizes_composite': {str(F): len(COMP[F]) for F in range(2016, 2026)}, 'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = E.run_road(forms, 'native', 'COMP', 'QUINTILE', 'annual', False)
        twins = []
        for s in range(1, 21):
            tf, _, _, _ = E.run_road(forms, 'native', 'COMP', 'QUINTILE', 'annual', False, seed=s)
            twins.append(tf)
        beaten = sum(1 for t in twins if fin > t)
        results['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                                   'spy_same_window': E.spy_final(forms),
                                   'placebo_finals': twins, 'placebos_beaten': beaten,
                                   'curve': curve, 'distribution': dist_stats(curve, forms)}
        print(rname, fin, 'costs', costs, 'maxdd', maxdd, 'spy', E.spy_final(forms), 'pb', beaten, '/20', flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(results, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
