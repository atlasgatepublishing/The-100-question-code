#!/usr/bin/env python3
"""v12 net-net ticker mapping + Yahoo monthly price fetch (per CONSTRUCTION-SPEC).
Mapping order: (1) EDGAR company_tickers_exchange (current), (2) submissions
tickers, (3) trading symbol on the filer's own latest pre-formation 10-K/10-Q
cover. Prices: Yahoo monthly chart (close + adjclose), reuse guard data kept.
Writes only into this folder. Simulation data only.
"""
import json, os, re, time, urllib.request, urllib.error
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
            time.sleep(1.5 * (i + 1))

def main():
    pool = json.load(open(os.path.join(HERE, 'pool.json')))['pool']
    pool = {int(k): v for k, v in pool.items()}
    last_form = {}
    for F, rows in pool.items():
        for r in rows: last_form[r['cik']] = max(last_form.get(r['cik'], 0), F)
    ciks = sorted(last_form)
    print('unique pool CIKs', len(ciks), flush=True)
    # step 1: current exchange map
    tick = get('https://www.sec.gov/files/company_tickers_exchange.json')
    f = tick['fields']; ci, ti = f.index('cik'), f.index('ticker')
    cur = {}
    for row in tick['data']:
        cur.setdefault(int(row[ci]), row[ti])
    mapping = {}
    for cik in ciks:
        if cik in cur: mapping[cik] = (cur[cik], 'exchange-file')
    print('step1 mapped', len(mapping), flush=True)
    # step 2 + gather submissions for step 3
    subs = {}
    for cik in ciks:
        if cik in mapping: continue
        try:
            s = get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
            subs[cik] = s
            if s.get('tickers'): mapping[cik] = (s['tickers'][0], 'submissions')
        except Exception:
            subs[cik] = None
        time.sleep(0.12)
    print('step2 mapped total', len(mapping), flush=True)
    # step 3: cover symbol from latest 10-K/10-Q filed before last formation
    pat = [re.compile(r'Trading\s*Symbol[s]?\s*</?[^>]*>?\s*[:\-]?\s*([A-Z][A-Z0-9\.\-/]{0,9})', re.I),
           re.compile(r'\((?:NASDAQ|Nasdaq|NYSE|NYSE American|OTCQX|OTCQB)?\s*:?\s*([A-Z]{1,5}(?:\.[A-Z])?)\)'),
           re.compile(r'symbol\s+["\']([A-Z]{1,5})["\']', re.I)]
    for cik in ciks:
        if cik in mapping: continue
        s = subs.get(cik)
        if not s: continue
        rec = s.get('filings', {}).get('recent', {})
        forms = rec.get('form', []); dates = rec.get('filingDate', [])
        docs = rec.get('primaryDocument', []); accs = rec.get('accessionNumber', [])
        cutoff = f'{last_form[cik]}-06-30'
        cand = [(dates[i], accs[i], docs[i]) for i in range(len(forms))
                if forms[i] in ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F') and dates[i] <= cutoff]
        if not cand: continue
        cand.sort(reverse=True)
        _, acc, doc = cand[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
        try:
            txt = get(url, as_json=False)
        except Exception:
            continue
        head = txt[:400000]
        sym = None
        for p in pat:
            m = p.search(head)
            if m:
                g = m.group(1).strip().upper()
                if 1 <= len(g) <= 6 and g not in ('THE', 'AND', 'FOR', 'USD', 'SEC'):
                    sym = g; break
        if sym: mapping[cik] = (sym, 'filing-cover')
        time.sleep(0.12)
    print('step3 mapped total', len(mapping), 'of', len(ciks), flush=True)
    json.dump({str(k): {'ticker': v[0], 'via': v[1]} for k, v in mapping.items()},
              open(os.path.join(HERE, 'mapping.json'), 'w'), indent=1)
    # prices
    tickers = {}
    for cik, (t, via) in mapping.items(): tickers.setdefault(t, []).append(cik)
    print('unique tickers', len(tickers), flush=True)
    p1, p2 = 1420070400, 1784000000  # 2015-01-01 .. 2026-07
    ok = miss = 0
    for t in sorted(tickers):
        fn = os.path.join(PXD, f"px_{t.replace('/', '-')}.json")
        if os.path.exists(fn): ok += 1; continue
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
                import datetime
                dt = datetime.datetime.utcfromtimestamp(epoch)
                ym = f'{dt.year:04d}-{dt.month:02d}'
                c = q['close'][i] if i < len(q.get('close', [])) else None
                a = adj[i] if i < len(adj) else None
                if c is not None and a is not None: rows.append([ym, a, c])
            meta = {'firstTrade': res['meta'].get('firstTradeDate'), 'exchange': res['meta'].get('exchangeName')}
            json.dump({'rows': rows, 'meta': meta}, open(fn, 'w'))
            ok += 1
        except Exception:
            miss += 1
            json.dump({'rows': [], 'meta': {}}, open(fn, 'w'))
        time.sleep(0.1)
    print('prices ok', ok, 'miss', miss, flush=True)

if __name__ == '__main__':
    main()
