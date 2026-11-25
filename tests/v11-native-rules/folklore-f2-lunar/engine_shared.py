import json, os, math, random
from datetime import date, timedelta

PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
raw = json.load(open(PX))["chart"]["result"][0]
ts = raw["timestamp"]; q = raw["indicators"]["quote"][0]; adj = raw["indicators"]["adjclose"][0]["adjclose"]
bars=[]
for i,t in enumerate(ts):
    c=q["close"][i]; o=q["open"][i]; a=adj[i]
    if c is None or o is None or a is None: continue
    d=date.fromtimestamp(t).isoformat() if False else None
    import datetime as _dt
    d=_dt.datetime.utcfromtimestamp(t).date().isoformat()
    bars.append({"date":d,"open":o*(a/c),"close":a})
bars.sort(key=lambda b:b["date"])
print(bars[0], bars[-1], len(bars))

COST=0.001; FEE=0.01
def run(bars, desired, start, end):
    """desired: dict date->bool long. Execute switches at open of first bar where desired differs (desired known in advance - calendar). $100 start, liquidate at final close."""
    idx=[i for i,b in enumerate(bars) if start<=b["date"]<=end]
    cash=100.0; shares=0.0; orders=0; costs=0.0; curve=[]; in_mkt_days=0
    for j,i in enumerate(idx):
        b=bars[i]; want=desired.get(b["date"], False)
        if want and shares==0:
            amt=cash; c=amt*COST; shares=(amt-c)/b["open"]; costs+=c; cash=0.0; orders+=1
        elif not want and shares>0:
            val=shares*b["open"]; c=val*COST+FEE; cash=val-c; costs+=c; shares=0.0; orders+=1
        eq=cash+shares*b["close"]
        if shares>0: in_mkt_days+=1
        curve.append([b["date"], round(eq,4)])
    if shares>0:
        b=bars[idx[-1]]; val=shares*b["close"]; c=val*COST+FEE; cash=val-c; costs+=c; orders+=1; shares=0.0
        curve[-1][1]=round(cash,4)
    final=curve[-1][1] if curve else 100.0
    peak=100.0; mdd=0.0
    for _,e in curve:
        peak=max(peak,e); mdd=max(mdd,(peak-e)/peak*100)
    yrs=(date.fromisoformat(end)-date.fromisoformat(start)).days/365.25
    return {"final":round(final,2),"cagr_pct":round(((final/100)**(1/yrs)-1)*100,2) if final>0 else -100,
            "max_dd_pct":round(mdd,2),"costs":round(costs,2),"orders":orders,
            "time_in_market_pct":round(in_mkt_days/max(len(idx),1)*100,1),"curve":curve}

def spy_bh(bars,start,end):
    des={b["date"]:True for b in bars}
    return run(bars,des,start,end)

def placebos(bars, desired, start, end, seeds=20):
    dates=[b["date"] for b in bars if start<=b["date"]<=end]
    vals=[desired.get(d,False) for d in dates]; n=len(vals); out=[]
    for s in range(1,seeds+1):
        rng=random.Random(s); sh=rng.randint(60,n-60)
        shifted=vals[-sh:]+vals[:-sh]
        des=dict(zip(dates,shifted))
        r=run(bars,des,start,end); out.append(r["final"])
    out_sorted=sorted(out)
    return {"finals":out,"median":out_sorted[len(out)//2],"p90":out_sorted[int(len(out)*0.9)-1],"max":max(out)}
