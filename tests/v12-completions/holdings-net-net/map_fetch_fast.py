#!/usr/bin/env python3
"""Holdings-sweep replica of the v12 net-net mapping + price fetch
(CONSTRUCTION-SPEC.md in ../net-net/). Same mapping order: (1) EDGAR
company_tickers_exchange (current), (2) submissions tickers, (3) trading
symbol on the filer's own latest pre-formation 10-K/10-Q cover. Prices:
Yahoo monthly chart (adjclose + close), firstTradeDate kept for the
ticker-reuse guard. Concurrent; writes only into this folder.
"""
import json, os, re, time, urllib.request, urllib.parse, datetime
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
PXD = os.path.join(HERE, 'px')
os.makedirs(PXD, exist_ok=True)

def get(url, tries=3, as_json=True):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            raw = urllib.request.urlopen(r, timeout=60).read()
            return json.loads(raw) if as_json else raw.decode('utf-8', 'replace')
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(1.0 * (i + 1))

def main():
    pool = json.load(open(os.path.join(HERE, 'pool.json')))['pool']
    pool = {int(k): v for k, v in pool.items()}
    last_form = {}
    for F, rows in pool.items():
        for r in rows: last_form[r['cik']] = max(last_form.get(r['cik'], 0), F)
    ciks = sorted(last_form)
    print('unique pool CIKs', len(ciks), flush=True)
    tick = get('https://www.sec.gov/files/company_tickers_exchange.json')
    f = tick['fields']; ci, ti = f.index('cik'), f.index('ticker')
    cur = {}
    for row in tick['data']:
        cur.setdefault(int(row[ci]), row[ti])
    mapping = {}
    for cik in ciks:
        if cik in cur: mapping[cik] = (cur[cik], 'exchange-file')
    print('step1 mapped', len(mapping), flush=True)
    subs = {}
    def fetch_sub(cik):
        try:
            return cik, get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        except Exception:
            return cik, None
    rest = [c for c in ciks if c not in mapping]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for cik, s in ex.map(fetch_sub, rest):
            subs[cik] = s
            if s and s.get('tickers'): mapping[cik] = (s['tickers'][0], 'submissions')
    print('step2 mapped total', len(mapping), flush=True)
    pat = [re.compile(r'Trading\s*Symbol[s]?\s*</?[^>]*>?\s*[:\-]?\s*([A-Z][A-Z0-9\.\-/]{0,9})', re.I),
           re.compile(r'\((?:NASDAQ|Nasdaq|NYSE|NYSE American|OTCQX|OTCQB)?\s*:?\s*([A-Z]{1,5}(?:\.[A-Z])?)\)'),
           re.compile(r'symbol\s+["\']([A-Z]{1,5})["\']', re.I)]
    def cover(cik):
        s = subs.get(cik)
        if not s: return cik, None
        rec = s.get('filings', {}).get('recent', {})
        forms = rec.get('form', []); dates = rec.get('filingDate', [])
        docs = rec.get('primaryDocument', []); accs = rec.get('accessionNumber', [])
        cutoff = f'{last_form[cik]}-06-30'
        cand = [(dates[i], accs[i], docs[i]) for i in range(len(forms))
                if forms[i] in ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F') and dates[i] <= cutoff]
        if not cand: return cik, None
        cand.sort(reverse=True)
        _, acc, doc = cand[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
        try:
            txt = get(url, as_json=False)
        except Exception:
            return cik, None
        head = txt[:400000]
        for p in pat:
            m = p.search(head)
            if m:
                g = m.group(1).strip().upper()
                if 1 <= len(g) <= 6 and g not in ('THE', 'AND', 'FOR', 'USD', 'SEC'):
                    return cik, g
        return cik, None
    rest2 = [c for c in ciks if c not in mapping]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for cik, sym in ex.map(cover, rest2):
            if sym: mapping[cik] = (sym, 'filing-cover')
    print('step3 mapped total', len(mapping), 'of', len(ciks), flush=True)
    json.dump({str(k): {'ticker': v[0], 'via': v[1]} for k, v in mapping.items()},
              open(os.path.join(HERE, 'mapping.json'), 'w'), indent=1)
    tickers = {}
    for cik, (t, via) in mapping.items(): tickers.setdefault(t, []).append(cik)
    print('unique tickers', len(tickers), flush=True)
    p1, p2 = 1420070400, 1784000000
    def fetch_px(t):
        fn = os.path.join(PXD, f"px_{t.replace('/', '-')}.json")
        if os.path.exists(fn): return 'ok'
        yt = t.replace('/', '-')
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yt)}'
               f'?period1={p1}&period2={p2}&interval=1mo&events=div,split')
        try:
            d = get(url)
            res = d['chart']['result'][0]
            ts = res.get('timestamp', [])
            q = res['indicators']['quote'][0]
            adj = res['indicators'].get('adjclose', [{}])[0].get('adjclose', [])
            rows = []
            for i, epoch in enumerate(ts):
                dt = datetime.datetime.utcfromtimestamp(epoch)
                ym = f'{dt.year:04d}-{dt.month:02d}'
                c = q['close'][i] if i < len(q.get('close', [])) else None
                a = adj[i] if i < len(adj) else None
                if c is not None and a is not None: rows.append([ym, a, c])
            meta = {'firstTrade': res['meta'].get('firstTradeDate'), 'exchange': res['meta'].get('exchangeName')}
            json.dump({'rows': rows, 'meta': meta}, open(fn, 'w'))
            return 'ok'
        except Exception:
            json.dump({'rows': [], 'meta': {}}, open(fn, 'w'))
            return 'miss'
    allt = sorted(tickers) + ['SPY']
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(fetch_px, allt))
    print('prices ok', res.count('ok'), 'miss', res.count('miss'), flush=True)

if __name__ == '__main__':
    main()
