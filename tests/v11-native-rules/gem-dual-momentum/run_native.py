import csv, json, random
from datetime import date
DATA="/home/hatch/workspace/stock-app/backtests/v3/tournament2-data"
OUT="/home/hatch/workspace/stock-app/backtests/v11-native-rules/gem-dual-momentum"
def load(s):
    rows=list(csv.DictReader(open(f"{DATA}/{s}.csv")))
    return [(r["date"], float(r["open"]), float(r["close"])) for r in rows]
D={s:load(s) for s in ["SPY","IEFA","AGG","SHY"]}
dates=[r[0] for r in D["SPY"]]; idx={d:i for i,d in enumerate(dates)}
O={s:{r[0]:r[1] for r in D[s]} for s in D}; C={s:{r[0]:r[2] for r in D[s]} for s in D}
def ret252(s,d):
    i=idx[d]; 
    if i<252: return None
    return C[s][dates[i]]/C[s][dates[i-252]]-1
def month_ends(ds):
    out=[]
    for i,d in enumerate(ds):
        if i+1>=len(ds) or ds[i+1][:7]!=d[:7]: out.append(d)
    return out
def run(start,end,seed=None):
    rng=random.Random(seed) if seed is not None else None
    ds=[d for d in dates if start<=d<=end]
    mes=[d for d in month_ends(dates) if start<=d<end]
    cash=100.0; held=None; shares=0.0; costs=0.0; orders=0; curve=[]
    decisions={}
    for me in mes:
        r={s:ret252(s,me) for s in ["SPY","IEFA","SHY"]}
        if r["SPY"] is None: continue
        if rng: pick=rng.choice(["SPY","IEFA","AGG"])
        else: pick=(max(["SPY","IEFA"],key=lambda s:r[s]) if r["SPY"]>r["SHY"] else "AGG")
        decisions[me]=pick
    dec_dates=sorted(decisions)
    di=0; pending=None
    for d in ds:
        # execute pending at open
        if pending is not None:
            if held: 
                v=shares*O[held][d]; c=0.001*v+0.01; cash+=v-c; costs+=c; orders+=1; held=None; shares=0
            v=cash/(1.001); c=0.001*v; shares=v/O[pending][d]; cash-=v+c; costs+=c; orders+=1; held=pending; pending=None
        if d in decisions and decisions[d]!=held: pending=decisions[d]
        eq=cash+(shares*C[held][d] if held else 0)
        curve.append((d,round(eq,4)))
    peak=-1; mdd=0
    for _,v in curve: peak=max(peak,v); mdd=min(mdd,(v/peak-1)*100)
    yrs={}
    for ds_,v in curve: yrs.setdefault(ds_[:4],[]).append(v)
    yr={}
    prev=100.0
    for y in sorted(yrs): yr[y]=round((yrs[y][-1]/prev-1)*100,2); prev=yrs[y][-1]
    return {"start":ds[0],"end":ds[-1],"final":round(curve[-1][1],2),"max_dd_pct":round(mdd,2),"costs":round(costs,2),"orders":orders,"year_returns_pct":yr,"worst_year_pct":min(yr.values()),"equity_curve":curve}
res={"slug":"gem-dual-momentum","spec":"Antonacci GEM: monthly month-end, 12m(252d) lookback, SPY vs SHY absolute, winner of SPY/IEFA relative, else AGG; next-open execution; NO house floor","windows":{}}
for name,(a,b) in {"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20")}.items():
    r=run(a,b); pls=[run(a,b,seed=2000+i)["final"] for i in range(20)]
    r["placebo_beaten"]=sum(1 for p in pls if r["final"]>p); r["placebo_twin_finals"]=[round(p,2) for p in pls]
    res["windows"][name]=r; print(name,r["final"],r["max_dd_pct"],"placebo",r["placebo_beaten"])
json.dump(res,open(f"{OUT}/results.json","w"),indent=1)
