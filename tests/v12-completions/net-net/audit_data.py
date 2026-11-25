#!/usr/bin/env python3
"""DATA AUDIT (return-blind) for v12 net-net, run after the first engine pass
exposed mapping false-positives (documented in RESULTS.md artifact log):
 - eFuture Holding (CIK 1329365) mapped to 'BVI' (British Virgin Islands
   acronym in filing text; Yahoo's BVI series is itself glitchy);
 - ITEX Corp (CIK 860518) mapped to 'WACC' (flat 1e-5 placeholder series);
 - 'BLA' (Biologics License Application) mapped to two different biotechs.
All three came from heuristic cover patterns 2/3 (parenthetical / quoted
guesses). Correction, applied mechanically and blind to returns:
 1) Step-3 cover mapping re-derived with PATTERN 1 ONLY -- the cover's own
    'Trading Symbol(s)' field, which is what the frozen spec's step 3 means.
    Names matched only by patterns 2/3 revert to UNMAPPED (unpriced fence).
 2) Series-validity screen for every mapped ticker (any source): a ticker
    is INVALID if its Yahoo monthly adj series contains (a) any value
    < $0.01 in 2015-2026 (placeholder/stub signature), or (b) an isolated
    spike: adj[t] >= 8x adj[t-1] with adj[t+1] <= 2x adj[t-1] (bad-print
    signature; a real re-rating persists past one month-end).
 Invalid tickers' px files are moved to px_invalid/ (preserved), their
 CIKs become unpriced. Original mapping.json preserved as mapping_raw.json.
"""
import json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
PXD = os.path.join(HERE, 'px')
SUBD = os.path.join(HERE, 'subs_cache')
BAD = os.path.join(PXD, 'invalid'); os.makedirs(BAD, exist_ok=True)
PAT1 = re.compile(r'Trading\s*Symbol[s]?\s*</?[^>]*>?\s*[:\-]?\s*([A-Z][A-Z0-9\.\-/]{0,9})', re.I)

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            return urllib.request.urlopen(r, timeout=60).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(1.5 * (i + 1))

def cover_pat1(job):
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
    m = PAT1.search(txt[:400000])
    if m:
        g = m.group(1).strip().upper()
        if 1 <= len(g) <= 6 and g not in ('THE', 'AND', 'FOR', 'USD', 'SEC'):
            return g
    return None

def main():
    pool = json.load(open(os.path.join(HERE, 'pool.json')))['pool']
    pool = {int(k): v for k, v in pool.items()}
    last_form = {}
    for F, rows in pool.items():
        for r in rows: last_form[r['cik']] = max(last_form.get(r['cik'], 0), F)
    raw = json.load(open(os.path.join(HERE, 'mapping.json')))
    raw = {int(k): v for k, v in raw.items()}
    if not os.path.exists(os.path.join(HERE, 'mapping_raw.json')):
        json.dump({str(k): v for k, v in raw.items()},
                  open(os.path.join(HERE, 'mapping_raw.json'), 'w'), indent=1)
    # step-3 candidates = raw filing-cover mappings
    step3 = {c: v for c, v in raw.items() if v['via'] == 'filing-cover'}
    print('raw filing-cover mappings:', len(step3), flush=True)
    jobs = [(c, f'{last_form[c]}-06-30') for c in sorted(step3)]
    with ThreadPoolExecutor(max_workers=12) as ex:
        syms = list(ex.map(cover_pat1, jobs))
    corrected = {c: v for c, v in raw.items() if v['via'] != 'filing-cover'}
    changed = []
    for (cik, _), sym in zip(jobs, syms):
        old = step3[cik]['ticker']
        if sym and sym == old:
            corrected[cik] = step3[cik]
        elif sym:
            corrected[cik] = {'ticker': sym, 'via': 'filing-cover-pat1'}
            changed.append({'cik': cik, 'old': old, 'new': sym, 'action': 'symbol-corrected'})
        else:
            changed.append({'cik': cik, 'old': old, 'new': None, 'action': 'unmapped'})
    print('step3 after pat1-only:', sum(1 for v in corrected.values() if v['via'].startswith('filing-cover')),
          'changed/dropped:', len(changed), flush=True)
    # fetch px for any newly corrected tickers not yet fetched
    have = {f[3:-5] for f in os.listdir(PXD) if f.startswith('px_') and f.endswith('.json')}
    need = sorted({v['ticker'].replace('/', '-') for v in corrected.values()} - have)
    print('new tickers to fetch:', len(need), flush=True)
    import map_and_fetch2 as MF
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(MF.fetch_px, need))
    # series-validity screen
    invalid = []
    for cik, v in sorted(corrected.items()):
        t = v['ticker'].replace('/', '-')
        fn = os.path.join(PXD, f'px_{t}.json')
        if not os.path.exists(fn): continue
        d = json.load(open(fn))
        rows = d['rows']
        adjs = [r[1] for r in rows]
        reason = None
        if any(a < 0.01 for a in adjs): reason = 'sub-cent placeholder values'
        else:
            for i in range(1, len(adjs) - 1):
                if adjs[i - 1] > 0 and adjs[i] >= 8 * adjs[i - 1] and adjs[i + 1] <= 2 * adjs[i - 1]:
                    reason = f'isolated spike at {rows[i][0]}'
                    break
        if reason:
            invalid.append({'cik': cik, 'ticker': v['ticker'], 'via': v['via'], 'reason': reason})
    print('invalid series:', len(invalid), flush=True)
    bad_tickers = {i['ticker'].replace('/', '-') for i in invalid}
    for t in bad_tickers:
        src = os.path.join(PXD, f'px_{t}.json')
        if os.path.exists(src): os.replace(src, os.path.join(BAD, f'px_{t}.json'))
    final = {c: v for c, v in corrected.items() if v['ticker'].replace('/', '-') not in bad_tickers}
    json.dump({str(k): v for k, v in final.items()},
              open(os.path.join(HERE, 'mapping.json'), 'w'), indent=1)
    json.dump({'changed_step3': changed, 'invalid_series': invalid},
              open(os.path.join(HERE, 'audit_log.json'), 'w'), indent=1)
    print('final mapped CIKs:', len(final), 'of', len(last_form), flush=True)
    print('saved mapping.json (corrected) + audit_log.json', flush=True)

if __name__ == '__main__':
    main()
