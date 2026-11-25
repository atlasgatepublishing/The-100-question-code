#!/usr/bin/env python3
"""Assemble the PIT Fortune/GPTW '100 Best Companies to Work For' panel.
Sources (public, contemporaneous):
  2016-2026: greatplacetowork.com/best-workplaces/100-best/<year> (JSON-LD ItemList)
  2010-2015: Wayback Machine captures of fortune.com / money.cnn.com list pages.
Writes data/panel_raw.json {year: [names in rank order]}. Simulation only."""
import json, os, re, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
os.makedirs(DATA, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AtlasGateResearch'}

def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

def clean_name(n):
    n = re.sub(r'<[^>]+>', '', n)
    n = n.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"').replace('&rsquo;', "'")
    return re.sub(r'\s+', ' ', n).strip()

def parse_gptw(html):
    i = html.find('ItemList')
    if i < 0: return []
    seg = html[i:html.find('</script>', i)]
    out = []
    for chunk in seg.split('ListItem')[1:]:
        mp = re.search(r'"position":\s*"?(\d+)', chunk)
        mn = re.search(r'"name":\s*"([^"]+)"', chunk)
        if mp and mn: out.append((int(mp.group(1)), clean_name(mn.group(1))))
    out.sort()
    return [n for _, n in out]

def parse_cnn(html):
    rows = re.findall(r'<td class="cnncol1">\s*(\d+)\s*</td>\s*<td class="cnncol2">(?:<a[^>]*>)?\s*([^<]+)', html)
    out = [(int(r), clean_name(n)) for r, n in rows]
    out.sort()
    return [n for _, n in out]

def parse_fortune(html):
    got = parse_gptw(html)
    if len(got) >= 50: return got
    names = []
    for pat in (r'"companyName"\s*:\s*"([^"]+)"', r'data-company="([^"]+)"',
                r'class="[^"]*company-name[^"]*"[^>]*>([^<]{2,60})<'):
        g = [clean_name(x) for x in re.findall(pat, html)]
        if len(g) > len(names): names = g
    return names

def cdx_first(urlpat, frm, to):
    q = (f'http://web.archive.org/cdx/search/cdx?url={urlpat}'
         f'&output=text&filter=statuscode:200&from={frm}&to={to}&limit=8')
    try: txt = fetch(q, 30)
    except Exception as e:
        print('CDX fail', urlpat, e); return None
    lines = [l.split() for l in txt.strip().splitlines() if l.strip()]
    if not lines: return None
    ts, orig = lines[0][1], lines[0][2]
    return f'https://web.archive.org/web/{ts}id_/{orig}'

panel = {}
for y in range(2016, 2027):
    try: names = parse_gptw(fetch(f'https://www.greatplacetowork.com/best-workplaces/100-best/{y}'))
    except Exception as e: names = []; print(y, 'GPTW fail', e)
    panel[str(y)] = names; print(y, 'GPTW', len(names), flush=True); time.sleep(1)

for y in range(2010, 2016):
    got = []
    tries = [
        (f'money.cnn.com/magazines/fortune/bestcompanies/{y}/full_list/', parse_cnn),
        (f'money.cnn.com/magazines/fortune/bestcompanies/{y}/full_list/index.html', parse_cnn),
        (f'fortune.com/best-companies/{y}/', parse_fortune),
        (f'fortune.com/ranking/best-companies/{y}/', parse_fortune),
        (f'greatplacetowork.com/best-workplaces/100-best/{y}', parse_gptw),
    ]
    for pat, parser in tries:
        snap = cdx_first(pat, str(y), str(y + 2))
        if not snap: continue
        try: names = parser(fetch(snap))
        except Exception as e: print(y, pat, 'fetch fail', e); continue
        print(y, pat, 'parsed', len(names), flush=True)
        if len(names) > len(got): got = names
        if len(got) >= 95: break
    panel[str(y)] = got; print(y, 'WAYBACK total', len(got), flush=True)

json.dump(panel, open(os.path.join(DATA, 'panel_raw.json'), 'w'), indent=1)
uniq = sorted({n for v in panel.values() for n in v})
print('years:', {k: len(v) for k, v in panel.items()})
print('unique names:', len(uniq))
json.dump(uniq, open(os.path.join(DATA, 'unique_names.json'), 'w'), indent=1)
