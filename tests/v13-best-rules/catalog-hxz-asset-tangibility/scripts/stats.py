import json, statistics, os
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
res = json.load(open(os.path.join(FAM, 'results.json')))
cell = res['grid']['Tan|native|nofloor|annual|QUINTILE']

def dist(road):
    curve = cell[road]['curve']
    # annual periods: value at each June mark vs previous June (start 100)
    pts = [('start', 100.0)] + [(m, v) for m, v in curve if m.endswith('-06')]
    rets = []
    for (m0, v0), (m1, v1) in zip(pts, pts[1:]):
        rets.append((m1, v1 / v0 - 1 if v0 else 0.0))
    vals = [r for _, r in rets]
    # longest losing streak
    streak = cur = 0
    for r in vals:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months, from monthly curve incl start)
    series = [('start', 100.0)] + curve
    peak = -1; last_high = 0; longest = 0
    for i, (_, v) in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    med_pl = statistics.median(cell[road]['placebo_finals'])
    return {'periods': len(vals), 'positive': sum(1 for r in vals if r > 0),
            'median_pct': round(statistics.median(vals) * 100, 1),
            'mean_pct': round(statistics.mean(vals) * 100, 1),
            'best_pct': round(max(vals) * 100, 1), 'worst_pct': round(min(vals) * 100, 1),
            'longest_losing_streak': streak, 'longest_between_highs_months': longest,
            'yearly_pct': [round(r * 100, 1) for _, r in rets],
            'placebo_median': round(med_pl, 2)}

out = {}
for road in cell:
    out[road] = dist(road)
    print(road, cell[road]['final'], 'DD', cell[road]['max_dd'], 'costs', cell[road]['costs'], 'pb', cell[road]['placebos_beaten'], out[road])
res['distribution'] = out
json.dump(res, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('saved distribution into results.json')
