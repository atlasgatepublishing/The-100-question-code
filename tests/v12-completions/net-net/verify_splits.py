#!/usr/bin/env python3
"""Split-consistency verification (CONSTRUCTION-SPEC check): for known
splitters, R = shares(F-1) x SF(F) / shares(F) must be ~1 across the split
formation; WITHOUT SF it collapses to ~1/split-factor (the v10/v11 poison).
Shares series: EDGAR frames Shares frames (same series the engine uses)."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data', 'frames')
def load(name):
    p = os.path.join(FR, name)
    return {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
SH = {y: load(f'Shares_{y}I.json') for y in range(2014, 2026)}
def sf(cik, F):
    avail = [(y, SH[y][cik]) for y in range(2014, 2026) if SH[y].get(cik)]
    f = 1.0
    for (y0, a), (y1, b) in zip(avail, avail[1:]):
        if y1 >= F:
            r = b / a
            if r >= 1.6 or r <= 0.625: f *= r
    return f
# (ticker, cik, F, factor, ref_year): F = formation whose YE F-1 shares are
# PRE-split and whose June price is already split-adjusted (first June after
# the split). ref_year = first YE whose share count is on the FINAL split
# basis (after ALL later splits) -- adjusted prices are on that basis, so
# shares(F-1) x SF(F) must reproduce the ref_year count (modulo drift).
CASES = [('AAPL', 320193, 2020, 4.0, 2020),   # 4:1 on 2020-08-31
         ('TSLA', 1318605, 2020, 5.0, 2022),  # 5:1 2020 + 3:1 2022 -> final basis YE2022
         ('TSLA', 1318605, 2022, 3.0, 2022),  # 3:1 on 2022-08-25
         ('AMZN', 1018724, 2022, 20.0, 2022), # 20:1 on 2022-06-03
         ('NVDA', 1045810, 2024, 10.0, 2024)] # 10:1 on 2024-06-07
out = []
for t, cik, F, fac, ref_year in CASES:
    s_prev = SH[F - 1].get(cik); s_cur = SH[ref_year].get(cik)
    if not s_prev or not s_cur:
        out.append({'ticker': t, 'formation': F, 'status': 'shares missing in frames', 's_prev': s_prev, 's_cur': s_cur})
        continue
    sff = sf(cik, F)
    out.append({'ticker': t, 'formation': F, 'split_factor': fac, 'SF_applied': sff,
                'R_with_SF': round(s_prev * sff / s_cur, 3),
                'R_without_SF': round(s_prev / s_cur, 3)})
    print(out[-1], flush=True)
json.dump(out, open(os.path.join(HERE, 'split_check.json'), 'w'), indent=1)
print('saved split_check.json')
