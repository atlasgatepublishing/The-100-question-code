import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Family, ROADS, spy_final, cand as CAND
CAND_ORDER = {cik: i for i, cik in enumerate(CAND)}

FRAMES = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-earnings-streak/data/frames')

def load_q(y, q):
    p = os.path.join(FRAMES, f'EarningsPerShareDiluted_{y}Q{q}.json')
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

EPS = {}
for y in range(2012, 2022):
    for q in range(1, 5):
        EPS[(y, q)] = load_q(y, q)

def streaks_for(F):
    """EXACT v12 builder (slice11-work/families.py build_streak): seq = all
    quarters present for the cik from 2013 through Q1 of F (missing quarters
    are skipped, not breaks); require len(seq) >= 8; count backwards over
    seq comparing each quarter to the same quarter a year earlier; a
    missing year-ago value or a non-increase breaks the count."""
    out = {}
    ciks = set()
    for y in range(2013, F + 1):
        for q in (1, 2, 3, 4):
            if y == F and q > 1: continue
            ciks |= set(EPS.get((y, q), {}).keys())
    for cik in ciks:
        seq = []
        for y in range(2013, F + 1):
            for q in (1, 2, 3, 4):
                if y == F and q > 1: continue
                if cik in EPS.get((y, q), {}): seq.append((y, q, EPS[(y, q)][cik]))
        if len(seq) < 8: continue
        cnt = 0
        for (y, q, v) in reversed(seq):
            prev = EPS.get((y - 1, q), {}).get(cik)
            if prev is None: break
            if v > prev: cnt += 1
            else: break
        out[cik] = float(cnt)
    # v12 by_year built the dict in candidate order; the engine's stable
    # sort uses that order to break the signal's heavy ties. Match it.
    return {cik: out[cik] for cik in sorted(out, key=lambda c: CAND_ORDER.get(c, 1 << 30))}

signals = {}
for F in range(2016, 2026):
    # frames end at 2021Q1, so seqs for F>=2022 end there automatically —
    # the last computable streak, carried forward exactly as v12 did.
    signals[F] = streaks_for(F)
print('streak pools (pre-price filter):', {F: len(signals[F]) for F in signals}, flush=True)

fam = Family({'Nei': signals}, {'Nei': 'high'})
pools = {F: len(fam.POOLS.get(('Nei', F, 'broad'), {})) for F in range(2016, 2026)}
print('engine broad pools:', pools, flush=True)
V12_POOLS = {2016:369,2017:380,2018:393,2019:417,2020:437,2021:462,2022:472,2023:476,2024:483,2025:500}
print('pool match v12:', pools == V12_POOLS, flush=True)

def monthly_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i-1] - 1) * 100 if vals[i-1] > 0 else 0.0 for i in range(1, len(vals))]
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else (srt[n//2-1] + srt[n//2]) / 2
    pos = sum(1 for r in rets if r > 0)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak = 100.0; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {'months': n, 'median_pct': round(med, 2), 'share_positive_pct': round(100*pos/n, 1),
            'best_pct': round(max(rets), 2), 'worst_pct': round(min(rets), 2),
            'longest_losing_streak_months': longest_loss, 'longest_months_between_highs': gap,
            'avg_pct_secondary': round(sum(rets)/n, 2)}

def run_cell(count, house=False, seed=None, roads=ROADS):
    out = {}
    for rname, forms in roads.items():
        fin, curve, costs, maxdd = fam.run_road(forms, 'Nei', 'broad', count, 'annual', house, seed=seed)
        out[rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'curve': curve}
    return out

# --- Integrity gate: published form must reproduce v12 exactly ---
pub = run_cell('QUINTILE')
V12_PUB = {'LONGEST_2016_2025': 363.04, 'DECADE_2017_2025': 301.93, 'CONT_2019_2025': 242.82, 'VAL_2023_2025': 173.03}
gate = {r: (pub[r]['final'], V12_PUB[r], pub[r]['final'] == V12_PUB[r]) for r in V12_PUB}
print('INTEGRITY GATE (published cell vs v12):', gate, flush=True)

# --- My rules: broad, top 30, annual, no floor ---
mine = run_cell(30)
placebos = {}
for rname, forms in ROADS.items():
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = fam.run_road(forms, 'Nei', 'broad', 30, 'annual', False, seed=s)
        twins.append(tf)
    placebos[rname] = twins
    print(rname, 'mine', mine[rname]['final'], 'placebos beaten', sum(1 for t in twins if mine[rname]['final'] > t), '/20', flush=True)

# picks per formation for the record
picks = {str(F): fam.picks_for('Nei', F, 'broad', 30) for F in range(2016, 2026)}

res = {
    'family': 'catalog-hxz-earnings-streak', 'program': 'v13-best-rules',
    'spec': 'BEST-RULES-SPEC.md',
    'pool_sizes_broad': {str(k): v for k, v in pools.items()},
    'pool_match_v12': pools == V12_POOLS,
    'integrity_gate_published_cell': {r: {'mine_rebuild': gate[r][0], 'v12': gate[r][1], 'match': gate[r][2]} for r in gate},
    'published_form_rebuild': {r: {'final': pub[r]['final'], 'costs': pub[r]['costs'], 'max_dd': pub[r]['max_dd'],
                                   'spy_same_window': spy_final(ROADS[r]), 'curve': pub[r]['curve']} for r in ROADS},
    'my_rules': {r: {'final': mine[r]['final'], 'costs': mine[r]['costs'], 'max_dd': mine[r]['max_dd'],
                     'spy_same_window': spy_final(ROADS[r]), 'curve': mine[r]['curve'],
                     'placebo_finals': placebos[r],
                     'placebos_beaten': sum(1 for t in placebos[r] if mine[r]['final'] > t),
                     'monthly_distribution': monthly_stats(mine[r]['curve'])} for r in ROADS},
    'picks_top30_by_formation': picks,
}
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results.json')
json.dump(res, open(out, 'w'), indent=1)
print('WROTE', out, flush=True)
print('MY RULES FINALS:', {r: mine[r]['final'] for r in ROADS}, flush=True)
