#!/usr/bin/env python3
"""Fill 2012-2015 in panel_raw.json from additional contemporaneous sources:
Fortune snapshots (company-name spans, best of several captures) and
contemporaneous republications of the full Fortune table. Simulation only."""
import json, os, re, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AtlasGateResearch'}

def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

def clean(n):
    n = re.sub(r'<[^>]+>', '', n)
    n = n.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    return re.sub(r'\s+', ' ', n).strip()

def cdx_all(urlpat, frm, to, limit=20):
    q = (f'http://web.archive.org/cdx/search/cdx?url={urlpat}'
         f'&output=text&filter=statuscode:200&from={frm}&to={to}&limit={limit}')
    try: txt = fetch(q, 30)
    except Exception as e: print('CDX fail', urlpat, e); return []
    out = []
    for l in txt.strip().splitlines():
        p = l.split()
        if len(p) >= 3: out.append(f'https://web.archive.org/web/{p[1]}id_/{p[2]}')
    return out

def parse_spans(html):
    names = [clean(x) for x in re.findall(r'class="company-name"[^>]*>([^<]+)<', html)]
    return [n for n in names if n]

def parse_table(html):
    # republished tables: | rank | Company Name | employees | growth |
    out = []
    for m in re.finditer(r'\|\s*(\d{1,3})\s*\|\s*([^|]{2,60}?)\s*\|', html):
        out.append((int(m.group(1)), clean(m.group(2))))
    if len(out) < 50:
        out = []
        for m in re.finditer(r'(?:^|\n)\s*(\d{1,3})\s+([A-Z][A-Za-z0-9&.,\'\- ]{2,50}?)\s+\d[\d,]*\s', html):
            out.append((int(m.group(1)), clean(m.group(2))))
    out.sort()
    seen, res = set(), []
    for r, n in out:
        if r not in seen: seen.add(r); res.append(n)
    return res

panel = json.load(open(os.path.join(DATA, 'panel_raw.json')))

# 2015 + 2014 + 2012: fortune snapshots, best parse wins
for y in (2012, 2014, 2015):
    best = panel.get(str(y), [])
    for snap in cdx_all(f'fortune.com/best-companies/{y}/', str(y), str(y + 1)):
        try: names = parse_spans(fetch(snap))
        except Exception as e: print(y, 'snap fail', e); continue
        print(y, 'fortune snap parsed', len(names), flush=True)
        if len(names) > len(best): best = names
        if len(best) >= 98: break
    panel[str(y)] = best
    print(y, 'total', len(best), flush=True)

# 2013: contemporaneous republication of the full Fortune table
try:
    names = parse_table(fetch('https://executiveresumewriter.com/fortune-100-best-2013/'))
    print('2013 repub parsed', len(names), flush=True)
    if len(names) > len(panel.get('2013', [])): panel['2013'] = names
except Exception as e:
    print('2013 repub fail', e)
if len(panel.get('2013', [])) < 95:
    try:
        names = parse_table(fetch('https://www.airlinepilotforums.com/united/72444-100-best-places-work-2013-no-airline.html'))
        print('2013 forum parsed', len(names), flush=True)
        if len(names) > len(panel.get('2013', [])): panel['2013'] = names
    except Exception as e:
        print('2013 forum fail', e)

json.dump(panel, open(os.path.join(DATA, 'panel_raw.json'), 'w'), indent=1)
uniq = sorted({n for v in panel.values() for n in v})
json.dump(uniq, open(os.path.join(DATA, 'unique_names.json'), 'w'), indent=1)
print('years:', {k: len(v) for k, v in sorted(panel.items())})
print('unique names:', len(uniq))
