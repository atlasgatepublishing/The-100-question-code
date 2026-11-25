"""Gayed & Bilello (2016) Leverage Rotation Strategy, native form.
Daily close: SPY above 200d SMA -> hold UPRO (3x); below -> T-bills (cash, 0%).
No -15% floor (the paper has none; the SMA switch IS the risk rule).
Signal at close t, trade at open t+1. Cost 0.10%/side on switches (program standard;
paper assumed 1%/yr leverage cost, embedded in UPRO's actual price path here).
Data: read-only v10 Yahoo pulls SPY.json / UPRO.json (split/dividend adjusted closes
are in 'close'; opens raw -- we use close-to-close with next-day execution lag via
shifting the position by one day, equivalent for a daily-close signal system)."""
import json, math, pathlib, random
SRC = pathlib.Path.home()/"workspace/stock-app/backtests/v10-retest/leveraged-trend/data"
def load(sym):
    d=json.loads((SRC/f"{sym}.json").read_text())
    r=d["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    adj=r["indicators"].get("adjclose",[{}])[0].get("adjclose")
    import datetime
    rows=[]
    for i,t in enumerate(ts):
        c=(adj[i] if adj else q["close"][i])
        if c is None: continue
        rows.append((datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c))
    return rows
spy=load("SPY"); upro=dict(load("UPRO"))
dates=[d for d,_ in spy]; px=[c for _,c in spy]
sma=[None]*len(px)
for i in range(len(px)):
    if i>=199: sma[i]=sum(px[i-199:i+1])/200
COST=0.0010
def run(start,end,floor_check=False):
    eq=100.0; pos=0; curve=[]; switches=0; costs=0.0; min_eq=100.0; peak=100.0; maxdd=0.0
    started=False; prev_u=None; prev_s=None
    for i,(d,c) in enumerate(spy):
        if d<start or d>end: 
            prev_s=c; prev_u=upro.get(d); continue
        # daily return applied from yesterday's position
        if started and prev_s:
            if pos==1 and prev_u and d in upro and upro[d] and prev_u:
                eq*= upro[d]/prev_u
            # pos==0: cash, no change (T-bill yield omitted, stated)
        started=True
        peak=max(peak,eq); maxdd=min(maxdd, eq/peak-1)
        curve.append([d,round(eq,4)])
        # signal at today's close, effective tomorrow
        if sma[i] is not None:
            want=1 if c>sma[i] else 0
            if want!=pos:
                ch=eq*COST; eq-=ch; costs+=ch; switches+=1; pos=want
        prev_s=c; prev_u=upro.get(d)
    yrs=(len(curve)/252) or 1
    return {"start":start,"end":end,"final":round(eq,2),"cagr_pct":round(((eq/100)**(1/yrs)-1)*100,2),
            "max_dd_pct":round(maxdd*100,2),"switches":switches,"costs":round(costs,2),"curve":curve}
def spy_bh(start,end):
    seg=[c for d,c in spy if start<=d<=end]; return round(100*seg[-1]/seg[0],2)
windows={"LONG":("2010-01-04","2026-11-20"),"CONT":("2019-01-02","2026-11-20"),
         "VAL":("2023-01-03","2026-11-20"),"DECADE":("2016-11-21","2026-11-20")}
out={"strategy":"Gayed-Bilello LRS native: daily, SPY vs 200d SMA, UPRO 3x / cash(T-bill proxy 0%)","cost_per_side":COST,"windows":{}}
for k,(s,e) in windows.items():
    r=run(s,e); r["spy_buyhold"]=spy_bh(s,e)
    # year folds
    folds={}
    seg=[d for d,_ in spy if s<=d<=e]
    for y in sorted(set(d[:4] for d in seg)):
        folds[y]=run(f"{y}-01-01",f"{y}-12-31")["final"]
    r["year_folds_final_per_100"]=folds
    out["windows"][k]=r
    print(k, r["final"], "SPY", r["spy_buyhold"], "maxDD", r["max_dd_pct"], "switches", r["switches"])
pathlib.Path(__file__).with_name("results.json").write_text(json.dumps(out,indent=1))
