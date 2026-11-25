#!/usr/bin/env python3
"""v13 BEST-RULES run for catalog-hxz-cashflow-volatility.
Frozen by BEST-RULES-SPEC.md: Vcf signal exactly as catalog (pstdev of
OCF/Assets, prior 5 FY, min 3, PIT June formation, FY<=F-1), native universe
(financials excluded), lowest TERCILE equal-weight, annual cadence, 12-month
hold, NO floor, tiered program costs, vanished->ZERO, 20-seed placebos
sharing the chassis. Simulation only."""
import json, os, sys, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')

UNI, SIG, COUNT, CAD, HOUSE = 'native', 'Vcf', 'TERCILE', 'annual', False

ROADS = {
    'LONGEST': list(range(2016, 2026)),
    'DECADE': list(range(2017, 2026)),
    'CONT': list(range(2019, 2026)),
    'VAL': list(range(2023, 2026)),
    'FOLD_2016_2020': list(range(2016, 2021)),
    'FOLD_2021_2025': list(range(2021, 2026)),
}

def distribution(curve, formations):
    """Annual per-period distribution from the monthly equity curve."""
    junes = {}
    start_ym = f'{formations[0]:04d}-06'
    prev = 100.0
    rets = []
    pts = [('', 100.0)] + [(m, v) for m, v in curve]
    for F in formations:
        end_ym = f'{F + 1:04d}-06'
        vals = [v for m, v in curve if m == end_ym]
        end = vals[-1] if vals else prev
        rets.append(end / prev - 1.0)
        prev = end
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs, in months, over the monthly curve
    peak = -1.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(pts):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(pts) - 1 - last_high)
    return {
        'periods': len(rets),
        'period_returns_pct': [round(100 * r, 1) for r in rets],
        'median_period_pct': round(100 * st.median(rets), 1),
        'share_positive': f'{pos}/{len(rets)}',
        'best_period_pct': round(100 * max(rets), 1),
        'worst_period_pct': round(100 * min(rets), 1),
        'longest_losing_streak': streak,
        'longest_months_between_highs': longest,
        'mean_period_pct_secondary': round(100 * st.mean(rets), 1),
    }

def run(forms):
    fin, curve, costs, maxdd = E.run_road(forms, UNI, SIG, COUNT, CAD, HOUSE)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = E.run_road(forms, UNI, SIG, COUNT, CAD, HOUSE, seed=s)
        twins.append(tf)
    half = len(forms) // 2
    halves = {}
    for name, hf in (('first_half', forms[:half] if half else forms[:1]),
                     ('second_half', forms[half:] if half else forms)):
        hfin, _, _, hdd = E.run_road(hf, UNI, SIG, COUNT, CAD, HOUSE)
        halves[name] = {'formations': hf, 'final': hfin, 'max_dd': hdd,
                        'spy_same_window': E.spy_final(hf)}
    return {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
            'spy_same_window': E.spy_final(forms),
            'placebo_finals': twins,
            'placebos_beaten': sum(1 for t in twins if fin > t),
            'distribution': distribution(curve, forms),
            'half_windows': halves,
            'curve': curve}

def main():
    out = {'family': 'catalog-hxz-cashflow-volatility', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'cell': f'{SIG}|{UNI}|best-rules(no floor)|{CAD}|{COUNT}',
           'pool_sizes_native': {str(F): len(E.POOLS[(F, 'native')]) for F in range(2016, 2026)},
           'roads': {}}
    for name, forms in ROADS.items():
        r = run(forms)
        out['roads'][name] = r
        print(name, 'final', r['final'], 'maxDD', r['max_dd'], 'SPY', r['spy_same_window'],
              'pb', r['placebos_beaten'], '/20', 'costs', r['costs'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
