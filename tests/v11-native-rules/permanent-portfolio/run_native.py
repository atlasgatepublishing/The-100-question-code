import json, os, datetime
SRC="/home/hatch/workspace/stock-app/backtests/v10-retest/permanent-portfolio/data"
OUT="/home/hatch/workspace/stock-app/backtests/v11-native-rules/permanent-portfolio"
SYMS=["SPY","TLT","GLD","SHY"]
def load(s):
    d=json.load(open(f"{SRC}/px_{s}.json"))['chart']['result'][0]
    ts=d['timestamp']; q=d['indicators']['adjclose'][0]['adjclose']
    return {datetime.date.fromtimestamp(t):p for t,p in zip(ts,q) if p}
PX={s:load(s) for s in SYMS}
DATES=sorted(PX["SPY"].keys())
def run(start,end):
    dates=[d for d in DATES if start<=d<=end]
    cash=100.0; shares={s:0.0 for s in SYMS}; costs=0.0; orders=0
    # initial buy at first close, cost 0.10%/side
    for s in SYMS:
        v=25.0; c=0.001*v; cash-=v+c; costs+=c; shares[s]=v/PX[s][dates[0]]; orders+=1
    curve=[]; 
    # annual band check: first trading day of each calendar year after start year
    checks=set()
    for d in dates:
        if d.year>start.year and (d.month==1 and d not in checks):
            # first trading day of year: detect by previous date year diff
            pass
    prev=None; checkdates=set()
    for d in dates:
        if prev and d.year!=prev.year: checkdates.add(d)
        prev=d
    for d in dates:
        eq=cash+sum(shares[s]*PX[s][d] for s in SYMS)
        if d in checkdates:
            w={s:shares[s]*PX[s][d]/eq for s in SYMS}
            if any(w[s]<0.15 or w[s]>0.35 for s in SYMS):
                # rebalance all to 25% at this close
                for s in SYMS:
                    target=0.25*eq; cur=shares[s]*PX[s][d]; diff=target-cur
                    c=0.001*abs(diff); costs+=c; cash-=diff+c; shares[s]=target/PX[s][d]; orders+=1
                eq=cash+sum(shares[s]*PX[s][d] for s in SYMS)
        curve.append((str(d),round(eq,4)))
    peak=-1; mdd=0; 
    for _,v in curve:
        peak=max(peak,v); mdd=min(mdd,(v/peak-1)*100)
    yrs={}
    for ds,v in curve: yrs.setdefault(ds[:4],[]).append(v)
    yr={y:round((v[-1]/ (100.0 if y==str(start.year) and False else v0)-1)*100,2) for y,v in [(y,vals) for y,vals in yrs.items()] for v0 in [ ( [x[1] for x in curve if x[0].startswith(str(int(y)-1))][-1] if any(x[0].startswith(str(int(y)-1)) for x in curve) else 100.0) ]}
    return {"start":str(dates[0]),"end":str(dates[-1]),"final":round(curve[-1][1],2),"max_dd_pct":round(mdd,2),"costs":round(costs,2),"orders":orders,"year_returns_pct":yr,"worst_year_pct":min(yr.values()),"equity_curve":curve}
res={"slug":"permanent-portfolio","spec":"Browne 25/25/25/25 SPY/TLT/GLD/SHY(ETF proxies), 15-35% band, annual check, rebalance to 25% on breach, NO house floor","windows":{}}
for name,(a,b) in {"DECADE":(datetime.date(2016,11,21),datetime.date(2026,11,20)),"CONT":(datetime.date(2019,1,2),datetime.date(2026,11,20)),"VAL":(datetime.date(2023,1,3),datetime.date(2026,11,20))}.items():
    res["windows"][name]=run(a,b); print(name,res["windows"][name]["final"],res["windows"][name]["max_dd_pct"],res["windows"][name]["worst_year_pct"])
json.dump(res,open(f"{OUT}/results.json","w"),indent=1)
