#!/usr/bin/env python3
"""Final panel fills:
- 2013 from the contemporaneous CNN Money list page (Wayback, Jan 2013).
- 2014 reconstructed from the PTAB exhibit PDF (Ex. 2001, CBM2014-00008)
  that reproduces Fortune's 'Best Companies to Work For 2014: Full List':
  membership = candidate names (from all other years' lists) found in the
  exhibit text. Labeled a reconstruction in RESULTS.md.
2012 and 2015 lists could not be recovered from any free contemporaneous
source tried; those years have NO formation in the run (disclosed).
Simulation only."""
import json, os, re, subprocess, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AtlasGateResearch'}

def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

def clean(n):
    n = re.sub(r'<[^>]+>', '', n).replace('&amp;', '&').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', n).strip()

panel = json.load(open(os.path.join(DATA, 'panel_raw.json')))

h = fetch('https://web.archive.org/web/20130120110737id_/http://money.cnn.com/magazines/fortune/best-companies/2013/list/')
names, seen = [], set()
for raw in re.findall(r'best-companies/2013/[^"]*"[^>]*>([^<]{2,60})<', h):
    n = clean(raw)
    if len(n) > 1 and n.lower() not in seen:
        seen.add(n.lower()); names.append(n)
print('2013 CNN parsed', len(names))
if len(names) >= 95: panel['2013'] = names

pdf = '/tmp/ptab2014.pdf'
if not os.path.exists(pdf):
    urllib.request.urlretrieve('https://s3-us-west-1.amazonaws.com/ptab-filings%2FCBM2014-00008%2F2001', pdf)
subprocess.run(['pdftotext', '-layout', pdf, '/tmp/ptab2014.txt'], check=True)
txt = open('/tmp/ptab2014.txt', encoding='utf-8', errors='ignore').read()
norm = lambda s: re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()
t = norm(txt)
cands = set()
for y, v in panel.items():
    if y != '2014': cands.update(v)
found = [c for c in sorted(cands) if norm(c) and norm(c) in t]
print('2014 PTAB matched', len(found))
if len(found) >= 70: panel['2014'] = found

panel.setdefault('2012', []); panel.setdefault('2015', [])
json.dump(panel, open(os.path.join(DATA, 'panel_raw.json'), 'w'), indent=1)
uniq = sorted({n for v in panel.values() for n in v})
json.dump(uniq, open(os.path.join(DATA, 'unique_names.json'), 'w'), indent=1)
print('years:', {k: len(v) for k, v in sorted(panel.items())})
print('unique names:', len(uniq))
