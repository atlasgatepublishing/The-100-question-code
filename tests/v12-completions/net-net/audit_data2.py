#!/usr/bin/env python3
"""DATA AUDIT round 2 (return-blind): identity verification of mappings.
Round 1 fixed acronym false-positives but a tag-boundary error survived:
Atrion Corp (CIK 701288) mapped to 'G' (Genpact's series) because the
regex crossed inline-XBRL tags. Corrections:
 1) Cover extraction redone on TAG-STRIPPED cover text with a strict
    pattern: 'Trading Symbol(s)' + only punctuation/space + symbol.
 2) Identity cross-check: every submissions/cover-derived mapping whose
    ticker appears in Nasdaq Trader's official current symbol files
    (nasdaqlisted.txt / otherlisted.txt, symbol -> security name) must
    share a distinctive name token with the filer's EDGAR entity name;
    failures are printed with cover context for resolution.
Preserves mapping.json as mapping_v2.json. Writes mapping.json (v3),
audit2_log.json. Prices for newly mapped tickers fetched; series screen
from audit round 1 re-applied to new tickers."""
import json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
PXD = os.path.join(HERE, 'px')
SUBD = os.path.join(HERE, 'subs_cache')
BAD = os.path.join(PXD, 'invalid'); os.makedirs(BAD, exist_ok=True)
GENERIC = {'INC', 'CORP', 'CORPORATION', 'CO', 'LTD', 'PLC', 'THE', 'COMPANY',
           'HOLDINGS', 'HOLDING', 'GROUP', 'SA', 'NV', 'AG', 'LLC', 'LP', 'TRUST',
           'FUND', 'ETF', 'COM', 'NEW', 'GLOBAL', 'INTERNATIONAL', 'AMERICAN'}

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            return urllib.request.urlopen(r, timeout=60).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(1.5 * (i + 1))

def strip_tags(html):
    txt = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', txt)

STRICT = re.compile(r'Trading\s+Symbols?\s*(?:\([^)]*\))?\s*[:\-]?\s*([A-Z]{1,6}(?:\.[A-Z])?)\b')

def cover_strict(job):
    cik, cutoff = job
    fn = os.path.join(SUBD, f'{cik:010d}.json')
    if not os.path.exists(fn): return None, None
    try: s = json.loads(open(fn).read() or '{}')
    except Exception: return None, None
    rec = s.get('filings', {}).get('recent', {})
    forms = rec.get('form', []); dates = rec.get('filingDate', [])
    docs = rec.get('primaryDocument', []); accs = rec.get('accessionNumber', [])
    cand = [(dates[i], accs[i], docs[i]) for i in range(len(forms))
            if forms[i] in ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F') and dates[i] <= cutoff]
    if not cand: return None, None
    cand.sort(reverse=True)
    _, acc, doc = cand[0]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
    try: txt = get(url).decode('utf-8', 'replace')
    except Exception: return None, None
    plain = strip_tags(txt[:600000])
    m = STRICT.search(plain)
    if m:
        g = m.group(1).strip().upper()
        if g not in ('THE', 'AND', 'FOR', 'USD', 'SEC'):
            i0 = max(0, m.start() - 80)
            return g, plain[i0:m.end() + 40]
    return None, None

def tokens(name):
    ws = re.findall(r'[A-Z]{3,}', (name or '').upper())
    return {w for w in ws if w not in GENERIC}

def main():
    pool = json.load(open(os.path.join(HERE, 'pool.json')))['pool']
    pool = {int(k): v for k, v in pool.items()}
    last_form = {}
    for F, rows in pool.items():
        for r in rows: last_form[r['cik']] = max(last_form.get(r['cik'], 0), F)
    v2 = json.load(open(os.path.join(HERE, 'mapping.json')))
    v2 = {int(k): v for k, v in v2.items()}
    if not os.path.exists(os.path.join(HERE, 'mapping_v2.json')):
        json.dump({str(k): v for k, v in v2.items()},
                  open(os.path.join(HERE, 'mapping_v2.json'), 'w'), indent=1)
    raw = json.load(open(os.path.join(HERE, 'mapping_raw.json')))
    raw = {int(k): v for k, v in raw.items()}
    # all CIKs that EVER needed step 3 = in raw via filing-cover OR unmapped in raw
    step3_ciks = sorted({c for c, v in raw.items() if v['via'] == 'filing-cover'} |
                        {c for c in last_form if c not in raw})
    print('step3 candidates:', len(step3_ciks), flush=True)
    jobs = [(c, f'{last_form[c]}-06-30') for c in step3_ciks]
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(cover_strict, jobs))
    strict_map = {}
    contexts = {}
    for (cik, _), (sym, ctx) in zip(jobs, res):
        if sym:
            strict_map[cik] = sym
            contexts[cik] = ctx
    print('strict cover mappings:', len(strict_map), flush=True)
    # rebuild: exchange-file + submissions from raw, cover from strict
    final = {c: v for c, v in raw.items() if v['via'] != 'filing-cover'}
    changes = []
    for cik, sym in strict_map.items():
        old = raw.get(cik, {}).get('ticker')
        final[cik] = {'ticker': sym, 'via': 'filing-cover-strict'}
        if old != sym: changes.append({'cik': cik, 'old': old, 'new': sym})
    # identity cross-check vs Nasdaq Trader current files
    names = {}
    for u in ('https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt',
              'https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt'):
        try:
            txt = get(u).decode('utf-8', 'replace')
            for line in txt.splitlines()[1:]:
                parts = line.split('|')
                if len(parts) >= 2 and parts[0].strip():
                    names[parts[0].strip()] = parts[1].strip()
        except Exception as e:
            print('nasdaq file fetch failed', u, e, flush=True)
    print('nasdaq current symbols:', len(names), flush=True)
    flags = []
    for cik, v in sorted(final.items()):
        if v['via'] == 'exchange-file': continue
        t = v['ticker']
        if t not in names: continue
        fn = os.path.join(SUBD, f'{cik:010d}.json')
        ename = ''
        if os.path.exists(fn):
            try: ename = json.loads(open(fn).read() or '{}').get('name', '')
            except Exception: pass
        a, b = tokens(ename), tokens(names[t])
        if a and b and not (a & b):
            flags.append({'cik': cik, 'ticker': t, 'via': v['via'],
                          'edgar_name': ename, 'nasdaq_name': names[t],
                          'cover_context': contexts.get(cik)})
    print('identity flags:', len(flags), flush=True)
    for f in flags: print('FLAG', f, flush=True)
    # flagged -> unmapped (conservative, hurts)
    flagged_ciks = {f['cik'] for f in flags}
    final = {c: v for c, v in final.items() if c not in flagged_ciks}
    # fetch px for new tickers + series screen
    have = {f[3:-5] for f in os.listdir(PXD) if f.startswith('px_') and f.endswith('.json')}
    need = sorted({v['ticker'].replace('/', '-') for v in final.values()} - have)
    print('new tickers to fetch:', len(need), need[:20], flush=True)
    import map_and_fetch2 as MF
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(MF.fetch_px, need))
    invalid = []
    for cik, v in sorted(final.items()):
        t = v['ticker'].replace('/', '-')
        fn = os.path.join(PXD, f'px_{t}.json')
        if not os.path.exists(fn): continue
        d = json.load(open(fn)); adjs = [r[1] for r in d['rows']]
        reason = None
        if any(a < 0.01 for a in adjs): reason = 'sub-cent placeholder values'
        else:
            for i in range(1, len(adjs) - 1):
                if adjs[i - 1] > 0 and adjs[i] >= 8 * adjs[i - 1] and adjs[i + 1] <= 2 * adjs[i - 1]:
                    reason = f'isolated spike at {d["rows"][i][0]}'; break
        if reason: invalid.append({'cik': cik, 'ticker': v['ticker'], 'via': v['via'], 'reason': reason})
    bad_t = {i['ticker'].replace('/', '-') for i in invalid}
    for t in bad_t:
        src = os.path.join(PXD, f'px_{t}.json')
        if os.path.exists(src): os.replace(src, os.path.join(BAD, f'px_{t}.json'))
    final = {c: v for c, v in final.items() if v['ticker'].replace('/', '-') not in bad_t}
    print('invalid series round2:', len(invalid), 'final mapped:', len(final), flush=True)
    json.dump({str(k): v for k, v in final.items()},
              open(os.path.join(HERE, 'mapping.json'), 'w'), indent=1)
    json.dump({'strict_changes': changes, 'identity_flags': flags, 'invalid_series': invalid,
               'contexts': {str(k): v for k, v in contexts.items()}},
              open(os.path.join(HERE, 'audit2_log.json'), 'w'), indent=1)
    print('saved mapping.json (v3) + audit2_log.json', flush=True)

if __name__ == '__main__':
    main()
