#!/usr/bin/env python3
"""Stage 1: load daily bars, precompute per (ticker, month) trailing-3mo
ILLIQ / vol / Corwin-Schultz cost / last close. Checkpointed pickle, resumable.
Plain arithmetic (no statistics module) for speed."""
import json, os, math, pickle, time
HERE = os.path.dirname(os.path.abspath(__file__))
BROAD = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
DATA = os.path.join(HERE, 'data')
PKL = os.path.join(HERE, 'stats.pkl')
PROG = os.path.join(HERE, 'stage1_progress.log')
def log(*a):
    with open(PROG, 'a') as f: f.write(' '.join(str(x) for x in a) + '\n')

cand = {int(k): v for k, v in json.load(open(os.path.join(BROAD, 'candidates.json'))).items()}
LISTED = {'NYSE', 'NASDAQ', 'TXSE', 'CBOE'}
ticker2cik = {}
for cik, info in cand.items():
    if info.get('exchange') in LISTED and info.get('ticker'):
        ticker2cik[info['ticker'].replace('/', '-')] = cik

done = {}
if os.path.exists(PKL):
    done = pickle.load(open(PKL, 'rb'))
log('stage1 start, already done:', len(done), 'time', time.time())

todo = [t for t in sorted(ticker2cik) if t not in done]
for n, t in enumerate(todo):
    p = os.path.join(DATA, f'px_{t}.json')
    if not os.path.exists(p):
        done[t] = None; continue
    rows = json.load(open(p))
    D, O, H, L, C, RC, V = [], [], [], [], [], [], []
    for d, o, h, l, c, adj, v in rows:
        if adj is None or adj <= 0 or c is None or c <= 0: continue
        f = adj / c
        D.append(d); O.append((o or c) * f); H.append((h or c) * f); L.append((l or c) * f)
        C.append(adj); RC.append(c); V.append(v or 0)
    if len(D) < 60:
        done[t] = None; continue
    mend = {}
    for i, d in enumerate(D):
        mend[d[:7]] = i
    st = {}
    for m, ei in mend.items():
        i0 = max(0, ei - 62)
        cnt = ei - i0
        if cnt < 40: continue
        sdv = srv = srv2 = 0.0; ndv = 0
        bad = False
        for i in range(i0 + 1, ei + 1):
            if C[i - 1] <= 0: bad = True; break
            r = C[i] / C[i - 1] - 1.0
            srv += r; srv2 += r * r
            if V[i] > 0 and RC[i] > 0:
                sdv += abs(r) / (RC[i] * V[i]); ndv += 1
        if bad or ndv < 40: continue
        mean = srv / cnt
        var = srv2 / cnt - mean * mean
        vol = math.sqrt(var) if var > 0 else 0.0
        # Corwin-Schultz
        ests = 0.0; ne = 0
        for i in range(i0, ei):
            ah, al, bh, bl = H[i], L[i], H[i + 1], L[i + 1]
            if ah <= 0 or al <= 0 or bh <= 0 or bl <= 0: continue
            beta = (math.log(ah / al)) ** 2 + (math.log(bh / bl)) ** 2
            h2 = ah if ah > bh else bh; l2 = al if al < bl else bl
            if l2 <= 0: continue
            gamma = (math.log(h2 / l2)) ** 2
            denom = 3 - 2 * math.sqrt(2)
            alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
            ea = math.exp(alpha)
            s = 2 * (ea - 1) / (1 + ea)
            ests += s if s > 0 else 0.0; ne += 1
        cs = ests / ne if ne else 0.01
        cost = min(0.075, max(0.005, cs / 2.0)) + 0.001
        st[m] = ((sdv / ndv) * 1e6, vol, cost, C[ei])
    done[t] = {'bars': (D, O, H, L, C), 'stats': st}
    if n % 40 == 0:
        pickle.dump(done, open(PKL, 'wb'))
        log('checkpoint', n, '/', len(todo), t)
pickle.dump(done, open(PKL, 'wb'))
log('stage1 DONE', len(done))
print('stage1 DONE', len(done), flush=True)
