#!/usr/bin/env python3
"""Print the full Second-Chance grid from results.json into grid/GRID.md."""
import json, os
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
res = json.load(open(os.path.join(FAM, 'results.json')))
roads = [r for r in ('LONGEST', 'DECADE', 'CONT', 'VAL') if r in next(iter(res['grid'].values()))]
lines = [f"# FULL GRID — {res['family']} (every cell printed, finals in $, placebos /20)", ""]
spy = {r: next(iter(res['grid'].values()))[r]['spy_same_window'] for r in roads}
lines.append("SPY same-window: " + " · ".join(f"{r} ${spy[r]}" for r in roads))
lines.append("")
lines.append("| Cell | " + " | ".join(f"{r} | pb" for r in roads) + " |")
lines.append("|---|" + "---|" * (2 * len(roads)))
for k in sorted(res['grid']):
    c = res['grid'][k]
    row = [k]
    for r in roads:
        v = c[r]
        row.append(f"${v['final']:,.2f}")
        row.append(str(v.get('placebos_beaten', '—')))
    lines.append("| " + " | ".join(row) + " |")
lines.append("")
lines.append("Pool sizes (eligible per formation): " + json.dumps(res['pool_sizes_eligible']))
os.makedirs(os.path.join(FAM, 'grid'), exist_ok=True)
open(os.path.join(FAM, 'grid', 'GRID.md'), 'w').write("\n".join(lines) + "\n")
print('grid/GRID.md written:', len(res['grid']), 'cells')
