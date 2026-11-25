import csv, json
from datetime import datetime
# PPUT standalone native
rows=list(csv.reader(open("/home/hatch/workspace/stock-app/backtests/v7/re-put-hedge/PPUT_History.csv")))[1:]
P=[(datetime.strptime(r[0],"%m/%d/%Y").date(), float(r[1])) for r in rows]
def win(series,a,b,startcash=100.0):
    pts=[(d,v) for d,v in series if a<=d<=b]
    f=startcash*pts[-1][1]/pts[0][1]
    peak=-1; mdd=0; curve=[]
    for d,v in pts:
        eq=startcash*v/pts[0][1]; curve.append((str(d),round(eq,4))); peak=max(peak,eq); mdd=min(mdd,(eq/peak-1)*100)
    yrs={}
    for ds,v in curve: yrs.setdefault(ds[:4],[]).append(v)
    yr={}; prev=startcash
    for y in sorted(yrs): yr[y]=round((yrs[y][-1]/prev-1)*100,2); prev=yrs[y][-1]
    return {"start":str(pts[0][0]),"end":str(pts[-1][0]),"final":round(f,2),"max_dd_pct":round(mdd,2),"year_returns_pct":yr,"worst_year_pct":min(yr.values()),"equity_curve":curve}
from datetime import date
out={"slug":"re-put-hedge","spec":"CBOE PPUT index standalone 100% (S&P500 + monthly 5% OTM put roll), index embeds option costs, no added costs, NO house floor, NO champion blend","windows":{}}
for n,(a,b) in {"DECADE":(date(2016,11,21),date(2026,11,20)),"CONT":(date(2019,1,2),date(2026,11,20)),"VAL":(date(2023,1,3),date(2026,11,20)),"LONG":(date(2010,1,4),date(2026,11,20))}.items():
    out["windows"][n]=win(P,a,b); print("PPUT",n,out["windows"][n]["final"],out["windows"][n]["max_dd_pct"])
json.dump(out,open("/home/hatch/workspace/stock-app/backtests/v11-native-rules/re-put-hedge/results.json","w"),indent=1)
# FOMC native floor-free: reuse v7 event list + v2 SPY payload
import re
src=open("/home/hatch/workspace/stock-app/backtests/v7/re-fomc-drift/re-fomc-drift.py").read()
ev=re.findall(r'"(20\d\d-\d\d-\d\d)"', src.split("FOMC_ANNOUNCEMENTS")[1].split("]")[0])
spy=json.load(open("/home/hatch/workspace/stock-app/backtests/v2/data/SPY.json"))
# v2 payload format inspect
print(type(spy), str(spy)[:300])
