import os, re, json
base = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules')
CATS = [('BEATS WHAT WE HAVE','BEATS WHAT WE HAVE'),('BEATS ITS OWN PUBLISHED FORM','BEATS ITS OWN PUBLISHED FORM'),('BEATS ITS OWN','BEATS ITS OWN PUBLISHED FORM'),('STILL UNBUILDABLE','STILL UNBUILDABLE'),('STILL LESS','STILL LESS THAN ITS PUBLISHED FORM'),('STILL DEAD','STILL DEAD')]
def verdict_cat(txt):
    lines = txt.splitlines()
    # pass 1: explicit verdict lines (not ceiling lines)
    for ln in lines[:80]:
        u = ln.upper()
        if 'CEILING' in u: continue
        if 'VERDICT' in u or u.strip().startswith('#') or '**' in ln:
            for kw, cat in CATS:
                if kw in u: return cat
    # pass 2: first 80 lines any mention
    head = '\n'.join(lines[:80]).upper()
    for kw, cat in CATS:
        if kw in head: return cat
    return 'SEE FILE'
def roads(txt):
    out = {}
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith('|'): continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if not cells: continue
        lab = cells[0].upper().replace('*','').strip()
        key = None
        for k in ['LONG','DECADE','CONT','VAL','FULL']:
            if lab == k or lab.startswith(k+' ') or lab.startswith(k+'('): key = k; break
        if not key or key in out: continue
        moneys = re.findall(r'\$([\d,]+\.\d{2})', ' | '.join(cells[1:]))
        if moneys: out[key] = moneys[0]
    return out
rows = []
for d in sorted(os.listdir(base)):
    if d == 'hidden': continue
    p = os.path.join(base, d, 'RESULTS.md')
    if not os.path.isfile(p): continue
    txt = open(p, errors='replace').read()
    rows.append({'family': d, 'verdict': verdict_cat(txt), 'roads': roads(txt)})
json.dump(rows, open(os.path.join(base,'hidden','v13_table.json'),'w'), indent=1)
from collections import Counter
print(Counter(r['verdict'] for r in rows)); print('rows:', len(rows))
print('SEE FILE:', [r['family'] for r in rows if r['verdict']=='SEE FILE'])
