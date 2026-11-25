#!/usr/bin/env python3
"""Period-by-period record at the strategy's native tempo (monthly),
computed from the saved equity curves in results.json (coordinator update
2026-11-22 ~07:32). Median is the headline per-period number; any average
is a secondary, labeled line."""
import json, os, statistics
from datetime import datetime
HERE=os.path.dirname(os.path.abspath(__file__))
res=json.load(open(os.path.join(HERE,"results.json")))

def monthly_closes(curve):
    out={}
    for d,e in curve: out[d[:7]]=e
    return [out[k] for k in sorted(out)]

def stats(curve, start=100.0):
    mc=monthly_closes(curve)
    rets=[(mc[i]/mc[i-1]-1)*100 for i in range(1,len(mc))]
    # include first partial month vs start
    rets=[(mc[0]/start-1)*100]+rets
    pos=sum(1 for r in rets if r>0)
    streak=longest=0
    for r in rets:
        streak=streak+1 if r<=0 else 0
        longest=max(longest,streak)
    # longest stretch between new highs: daily curve, days from a peak until exceeded
    peak=-1; peak_d=None; worst=0; worst_span=None
    for d,e in curve:
        if e>peak: peak,peak_d=e,d
        else:
            days=(datetime.strptime(d,"%Y-%m-%d")-datetime.strptime(peak_d,"%Y-%m-%d")).days
            if days>worst: worst,worst_span=days,(peak_d,d)
    return {"n_periods":len(rets),"pct_periods_profitable":round(100*pos/len(rets),1),
            "median_period_pct":round(statistics.median(rets),2),
            "best_period_pct":round(max(rets),2),"worst_period_pct":round(min(rets),2),
            "longest_losing_streak_periods":longest,
            "longest_between_new_highs_days":worst,"longest_between_new_highs_span":worst_span,
            "average_period_pct_SECONDARY_LABELED_AVERAGE":round(sum(rets)/len(rets),2)}

out={}
out["rotation_native_full"]=stats(res["runs"]["nofloor|full"]["curve"])
out["rotation_native_validation"]=stats(res["runs"]["nofloor|validation"]["curve"])
out["rotation_v9_full"]=stats(res["runs"]["v9|full"]["curve"])
out["btc_full"]=stats(res["btc_hold"]["full"]["curve"])
out["ew_full"]=stats(res["ew_hold"]["full"]["curve"])
res["period_stats_monthly"]=out
json.dump(res,open(os.path.join(HERE,"results.json"),"w"),indent=1)
print(json.dumps(out,indent=1))
print("per_year:", json.dumps(res["per_year"],indent=1))
for k in ("nofloor|full","nofloor|validation","v9|full"):
    r=res["runs"][k]; print(k,"events:",r["events"][:6],"halts:",r["halts"],"costs:",r["costs"])
