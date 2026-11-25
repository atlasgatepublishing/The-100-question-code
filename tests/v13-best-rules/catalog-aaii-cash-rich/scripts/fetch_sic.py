#!/usr/bin/env python3
"""SIC fetch with a hard per-request deadline (SIGALRM interrupts a
trickling socket read, which a plain socket timeout cannot).
Usage: fetch_sic.py <max_new>  — resumes from data/sic.json, saves often."""
import urllib.request, json, os, re, signal, sys, time
H = {'User-Agent': 'AtlasGate v13 research research@atlasgate.example'}
HERE = os.path.dirname(os.path.abspath(__file__))
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')
SICP = os.path.join(HERE, '..', 'data', 'sic.json')

class TO(Exception): pass
def handler(sig, frm): raise TO()
signal.signal(signal.SIGALRM, handler)

def get_sic(cik):
    u = f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
    signal.setitimer(signal.ITIMER_REAL, 6)
    try:
        r = urllib.request.Request(u, headers=H)
        with urllib.request.urlopen(r, timeout=5) as resp:
            head = resp.read(16384).decode('utf-8', 'replace')
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    m = re.search(r'"sic":\s*"?(\d{0,4})"?', head)
    return m.group(1) if m else ''

cand = {int(k): v for k, v in json.load(open(os.path.join(SY, 'candidates.json'))).items()}
sic = {int(k): v for k, v in json.load(open(SICP)).items()} if os.path.exists(SICP) else {}
todo = [c for c in cand if c not in sic]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(todo)
done = 0
for cik in todo[:limit]:
    try: sic[cik] = get_sic(cik)
    except Exception: sic[cik] = ''
    done += 1
    if done % 50 == 0:
        json.dump(sic, open(SICP, 'w')); print('progress', len(sic), flush=True)
    time.sleep(0.12)
json.dump(sic, open(SICP, 'w'))
print('done chunk; total entries', len(sic), 'remaining', len(cand) - len(sic), flush=True)
