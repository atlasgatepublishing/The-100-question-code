import json, os
HERE=os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE,"results.json")) as f: out=json.load(f)
def monthly_stats(curve):
    # month-end equity
    months={}
    for d,e in curve: months[d[:7]]=e
    keys=sorted(months); rets=[]
    prev=100.0
    for k in keys:
        rets.append(months[k]/prev-1); prev=months[k]
    import statistics
    pos=sum(1 for r in rets if r>0)
    # losing streak
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<0 else 0; streak=max(streak,cur)
    # longest stretch between new highs (months)
    peak=-1; last_high=0; longest=0
    for idx,k in enumerate(keys):
        if months[k]>=peak: peak=months[k]; last_high=idx
        longest=max(longest, idx-last_high)
    return {"n_months":len(rets),"median_month_pct":round(statistics.median(rets)*100,2),
      "share_positive_pct":round(100*pos/len(rets),1) if rets else None,
      "best_month_pct":round(max(rets)*100,1) if rets else None,
      "worst_month_pct":round(min(rets)*100,1) if rets else None,
      "longest_losing_streak_months":streak,"longest_months_between_new_highs":longest,
      "avg_month_pct_labeled_secondary":round(statistics.mean(rets)*100,2) if rets else None}
res={}
for w in ("full","design","validation"):
    res[f"basket_{w}"]=monthly_stats(out["runs"][f"quarterly|nofloor|{w}"]["curve"])
    res[f"btc_{w}"]=monthly_stats(out["btc_hold"]["c060"][w]["curve"])
with open(os.path.join(HERE,"period_stats.json"),"w") as f: json.dump(res,f,indent=1)
print(json.dumps(res,indent=1))
for w in ("full","validation"):
    r=out["runs"][f"quarterly|nofloor|{w}"]
    print(w, "events:", r["events"][:5], "avg_elig", r["avg_eligible"], "avg_invested", r["avg_invested_pct"], "orders", r["orders"], "costs", r["costs"])
