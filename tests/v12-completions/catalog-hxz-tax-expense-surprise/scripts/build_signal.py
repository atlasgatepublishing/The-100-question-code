
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchmod import fetch_frames, load_frames
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
FR = os.path.join(FAM, 'data', 'frames')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-'); p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
assets = {}; shares_f = {}
for y in range(2009, 2026):
    assets[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Assets_{y}I.json')).items()}
    shares_f[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}
sf = {}
for cik in cand:
    avail = [(y, shares_f[y][cik]) for y in range(2009, 2026) if cik in shares_f[y]]
    d = {}
    for F in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d
def cap_of(cik, F, month=6):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(f'{F:04d}-{month:02d}')
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)
def w04(tag, y, kind):
    return {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'{tag}_{y}{kind}.json')).items()}
def revenue(y):
    out = {}
    for tag in ('SalesRevenueNet', 'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax'):
        src = w04(tag, y, 'D') or load_frames(FR, tag, f'CY{y}')
        for k, v in src.items(): out.setdefault(k, v)
    return out
def save(family, signals):
    json.dump({'family': family, 'signals': signals}, open(os.path.join(FAM, 'signals.json'), 'w'), indent=1)
    for name, s in signals.items():
        print(name, {F: len(p) for F, p in s['pools'].items()})

jobs = [('IncomeTaxExpenseBenefit', f'CY{y}Q1') for y in range(2010, 2026)]
fetch_frames(FR, jobs)
tes = {}
for F in range(2016, 2026):
    p = {}
    tq = load_frames(FR, 'IncomeTaxExpenseBenefit', f'CY{F}Q1')
    tq4 = load_frames(FR, 'IncomeTaxExpenseBenefit', f'CY{F-1}Q1')
    for cik in cand:
        if cik in tq and cik in tq4:
            sh = shares_f.get(F-1, {}).get(cik); sh4 = shares_f.get(F-2, {}).get(cik)
            at4 = assets.get(F-2, {}).get(cik)
            if sh and sh4 and at4:
                p[cik] = (tq[cik] / sh - tq4[cik] / sh4) / (at4 / sh4)
    tes[str(F)] = p
save('catalog-hxz-tax-expense-surprise', {'Tes': {'direction': 1, 'pools': tes}})
