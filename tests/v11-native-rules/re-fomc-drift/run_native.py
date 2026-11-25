import json, re, random, datetime
src=open("/home/hatch/workspace/stock-app/backtests/v7/re-fomc-drift/re-fomc-drift.py").read()
ev=re.findall(r'"(20\d\d-\d\d-\d\d)"', src.split("FOMC_ANNOUNCEMENTS")[1].split("]")[0])
d=json.load(open("/home/hatch/workspace/stock-app/backtests/v2/data/SPY.json"))['chart']['result'][0]
ts=d['timestamp']; adj=d['indicators']['adjclose'][0]['adjclose']
P={str(datetime.date.fromtimestamp(t)):p for t,p in zip(ts,adj) if p}
DATES=sorted(P); IDX={d:i for i,d in enumerate(DATES)}
def run(a,b,events):
    cash=100.0; costs=0.0; curve=[]; evs=[e for e in events if a<=e<=b]
    evset={}
    for e in evs:
        i=IDX[e]; evset[DATES[i-1]]=("buy",e); evset[DATES[i]]=("sell",e)
    shares=0.0
    for dt in [x for x in DATES if a<=x<=b]:
        if dt in evset and evset[dt][0]=="buy":
            v=cash/(1.001); c=0.001*v; shares=v/P[dt]; cash-=v+c; costs+=c
        eq=cash+shares*P[dt]
        if dt in evset and evset[dt][0]=="sell":
            v=shares*P[dt]; c=0.001*v+0.01; cash+=v-c; costs+=c; shares=0.0; eq=cash
        curve.append((dt,round(eq,4)))
    peak=-1;mdd=0
    for _,v in curve: peak=max(peak,v); mdd=min(mdd,(v/peak-1)*100)
    return {"start":a,"end":b,"events":len(evs),"final":round(curve[-1][1],2),"max_dd_pct":round(mdd,2),"costs":round(costs,2),"equity_curve":curve}
res={"slug":"re-fomc-drift","spec":"Lucca-Moench daily-bar form: buy SPY close day before scheduled FOMC announcement, sell announcement-day close, cash otherwise, program costs, NO house floor","windows":{}}
for n,(a,b) in {"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}.items():
    r=run(a,b,ev)
    # placebos: shift each event +5..+25 trading days, 20 seeds, same-year (v7 construction approx)
    pls=[]
    for s in range(20):
        rng=random.Random(1000+s); shifted=[]
        ok=True
        for e in ev:
            i=IDX[e]; j=i+rng.randint(5,25)
            if j>=len(DATES): ok=False; break
            shifted.append(DATES[j])
        if ok: pls.append(run(a,b,shifted)["final"])
    r["placebo_beaten"]=sum(1 for p in pls if r["final"]>p); r["placebo_twin_finals"]=[round(p,2) for p in pls]
    res["windows"][n]=r; print(n,r["final"],r["events"],"placebo",r["placebo_beaten"])
json.dump(res,open("/home/hatch/workspace/stock-app/backtests/v11-native-rules/re-fomc-drift/results.json","w"),indent=1)
