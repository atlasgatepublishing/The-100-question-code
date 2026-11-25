#!/usr/bin/env python3
"""v12 net-net mapping + prices, threaded/checkpointed (replaces the
sequential map_and_fetch.py run, which was latency-bound; same frozen
mapping order and sources). Submissions cached per-CIK; prices Yahoo
monthly. Writes only into this folder."""
import json, os, re, time, urllib.request, urllib.error, datetime
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
PXD = os.path.join(HERE, 'px'); os.makedirs(PXD, exist_ok=True)
SUBD = os.path.join(HERE, 'subs_cache'); os.makedirs(SUBD, exist_ok=True)

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            return urllib.request.urlopen(r, timeout=60).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(1.5 * (i + 1))

def robust_write(fn, obj):
    data = obj if isinstance(obj, (bytes, str)) else json.dumps(obj)
    mode = 'wb' if isinstance(data, bytes) else 'w'
    for attempt in range(8):
        try:
            tmp = fn + f'.m{os.getpid()}'
            with open(tmp, mode) as fh: fh.write(data)
            os.replace(tmp, fn)
            return True
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return False

def fetch_sub(cik):
    fn = os.path.join(SUBD, f'{cik:010d}.json')
    if os.path.exists(fn): return
    try:
        raw = get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        robust_write(fn, raw)
    except Exception:
        robust_write(fn, b'{}')

def fetch_cover(job):
    cik, cutoff = job
    fn = os.path.join(SUBD, f'{cik:010d}.json')
    if not os.path.exists(fn): return None
    try: s = json.loads(open(fn).read() or '{}')
    except Exception: return None
    rec = s.get('filings', {}).get('recent', {})
    forms = rec.get('form', []); dates = rec.get('filingDate', [])
    docs = rec.get('primaryDocument', []); accs = rec.get('accessionNumber', [])
    cand = [(dates[i], accs[i], docs[i]) for i in range(len(forms))
            if forms[i] in ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F') and dates[i] <= cutoff]
    if not cand: return None
    cand.sort(reverse=True)
    _, acc, doc = cand[0]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
    try: txt = get(url).decode('utf-8', 'replace')
    except Exception: return None
    head = txt[:400000]
    pats = [re.compile(r'Trading\s*Symbol[s]?\s*</?[^>]*>?\s*[:\-]?\s*([A-Z][A-Z0-9\.\-/]{0,9})', re.I),
            re.compile(r'\((?:NASDAQ|Nasdaq|NYSE|NYSE American|OTCQX|OTCQB)?\s*:?\s*([A-Z]{1,5}(?:\.[A-Z])?)\)'),
            re.compile(r'symbol\s+["\']([A-Z]{1,5})["\']', re.I)]
    for p in pats:
        m = p.search(head)
        if m:
            g = m.group(1).strip().upper()
            if 1 <= len(g) <= 6 and g not in ('THE', 'AND', 'FOR', 'USD', 'SEC'):
                return g
    return None

def fetch_px(t):
    fn = os.path.join(PXD, f"px_{t.replace('/', '-')}.json")
    if os.path.exists(fn): return
    yt = urllib.parse.quote(t.replace('/', '-'))
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{yt}'
           f'?period1=1420070400&period2=1784000000&interval=1mo&events=div,split')
    out = {'rows': [], 'meta': {}}
    try:
        d = json.loads(get(url))
        res = d['chart']['result'][0]
        ts = res.get('timestamp', [])
        q = res['indicators']['quote'][0]
        adj = res['indicators'].get('adjclose', [{}])[0].get('adjclose', [])
        rows = []
        for i, epoch in enumerate(ts):
            dt = datetime.datetime.utcfromtimestamp(epoch)
            c = q['close'][i] if i < len(q.get('close', [])) else None
            a = adj[i] if i < len(adj) else None
            if c is not None and a is not None:
                rows.append([f'{dt.year:04d}-{dt.month:02d}', a, c])
        out = {'rows': rows, 'meta': {'firstTrade': res['meta'].get('firstTradeDate'),
                                      'exchange': res['meta'].get('exchangeName')}}
    except Exception:
        pass
    robust_write(fn, out)

def main():
    pool = json.load(open(os.path.join(HERE, 'pool.json')))['pool']
    pool = {int(k): v for k, v in pool.items()}
    last_form = {}
    for F, rows in pool.items():
        for r in rows: last_form[r['cik']] = max(last_form.get(r['cik'], 0), F)
    ciks = sorted(last_form)
    print('unique pool CIKs', len(ciks), flush=True)
    tick = json.loads(get('https://www.sec.gov/files/company_tickers_exchange.json'))
    f = tick['fields']; ci, ti = f.index('cik'), f.index('ticker')
    cur = {}
    for row in tick['data']: cur.setdefault(int(row[ci]), row[ti])
    mapping = {}
    for cik in ciks:
        if cik in cur: mapping[cik] = (cur[cik], 'exchange-file')
    print('step1 mapped', len(mapping), flush=True)
    rest = [c for c in ciks if c not in mapping]
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(fetch_sub, rest))
    for cik in rest:
        fn = os.path.join(SUBD, f'{cik:010d}.json')
        try: s = json.loads(open(fn).read() or '{}')
        except Exception: s = {}
        if s.get('tickers'): mapping[cik] = (s['tickers'][0], 'submissions')
    print('step2 mapped total', len(mapping), flush=True)
    rest2 = [c for c in ciks if c not in mapping]
    jobs = [(c, f'{last_form[c]}-06-30') for c in rest2]
    with ThreadPoolExecutor(max_workers=12) as ex:
        syms = list(ex.map(fetch_cover, jobs))
    for (cik, _), sym in zip(jobs, syms):
        if sym: mapping[cik] = (sym, 'filing-cover')
    print('step3 mapped total', len(mapping), 'of', len(ciks), flush=True)
    robust_write(os.path.join(HERE, 'mapping.json'),
                 {str(k): {'ticker': v[0], 'via': v[1]} for k, v in mapping.items()})
    tickers = sorted({v[0] for v in mapping.values()})
    print('unique tickers', len(tickers), flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, _ in enumerate(ex.map(fetch_px, tickers)):
            if i % 400 == 0: print('px done', i, flush=True)
    have = sum(1 for t in tickers if json.load(open(os.path.join(PXD, f"px_{t.replace('/', '-')}.json")))['rows'])
    print('prices: tickers with data', have, 'of', len(tickers), flush=True)

if __name__ == '__main__':
    main()
