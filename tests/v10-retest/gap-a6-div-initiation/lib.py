import importlib.util, json, os, time, calendar, urllib.request, statistics, datetime as dt

V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")
def load_E():
    spec = importlib.util.spec_from_file_location("vm_pf", V4)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def fetch_cached(url, path, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return open(path,'rb').read()
    last=None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r: blob=r.read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path,'wb').write(blob); return blob
        except Exception as e: last=e; time.sleep(2*(i+1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def bars_long(ticker, cachedir, p1="2009-06-01", p2="2026-11-21"):
    path = os.path.join(cachedir, f"pxlong_{ticker}.json")
    t1 = calendar.timegm(time.strptime(p1,"%Y-%m-%d")); t2 = calendar.timegm(time.strptime(p2,"%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    j = json.loads(fetch_cached(url, path))
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose",[{}])[0].get("adjclose")
    bars=[]
    for i,t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o,h,l,c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a/c if c else 1.0
        bars.append({"d":d, "o":(o*ratio if o else a), "c":a})
    bars.sort(key=lambda b:b["d"]); return bars

def spy_final(E, pb, s, e):
    v,_ = E.spy_net(pb, s, e, 100.0); return round(v,2)

def curve_stats(curve, final, start_cash=100.0):
    if not curve: return {"max_dd_pct": None}
    peak=-1; maxdd=0.0
    for _d,v in curve:
        peak=max(peak,v); 
        if peak>0: maxdd=max(maxdd,(peak-v)/peak)
    return {"max_dd_pct": round(maxdd*100,2)}

def cagr(final, s, e, start=100.0):
    yrs=(dt.date.fromisoformat(e)-dt.date.fromisoformat(s)).days/365.25
    if final<=0 or yrs<=0: return None
    return round(((final/start)**(1/yrs)-1)*100,2)

def run_block(final, s, e, costs, orders, halts, restart, second_halt, placebo_beaten, curve=None):
    d={"start":s,"end":e,"final":round(final,2),"cagr_pct":cagr(final,s,e),
       "halts":halts,"restart":restart,"second_halt":second_halt,
       "costs":round(costs,2) if costs is not None else None,"orders":orders,
       "placebo_beaten":placebo_beaten}
    if curve: d.update(curve_stats(curve, final))
    else: d["max_dd_pct"]=None
    return d

def ev_stats(rows):
    """rows: list of excess_pct values"""
    if not rows: return {"n":0,"mean_excess_pct":None,"median_excess_pct":None}
    return {"n":len(rows),"mean_excess_pct":round(statistics.mean(rows),2),
            "median_excess_pct":round(statistics.median(rows),2),
            "share_beating_spy":round(sum(1 for x in rows if x>0)/len(rows),3)}
