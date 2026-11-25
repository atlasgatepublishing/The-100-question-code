import urllib.request, json, os, time
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
def fetch_frames(outdir, jobs):
    """jobs: list of (tag, frame, suffix) -> file {tag}_{frame}.json {cik:val}"""
    os.makedirs(outdir, exist_ok=True)
    for tag, frame in jobs:
        p = os.path.join(outdir, f'{tag}_{frame}.json')
        if os.path.exists(p): continue
        u = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{frame}.json'
        try:
            req = urllib.request.Request(u, headers=H)
            d = json.loads(urllib.request.urlopen(req, timeout=90).read())
            json.dump({int(r['cik']): r['val'] for r in d['data']}, open(p, 'w'))
            print(tag, frame, 'ok', len(d['data']), flush=True)
        except Exception as e:
            json.dump({}, open(p, 'w')); print(tag, frame, 'MISS', e, flush=True)
        time.sleep(0.12)
def load_frames(outdir, tag, frame):
    p = os.path.join(outdir, f'{tag}_{frame}.json')
    return {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
