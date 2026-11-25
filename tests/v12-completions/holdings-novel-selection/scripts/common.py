import statistics
COUNTS=[1,2,3,5,8,10,15,20,30,None]
def ckey(n): return "ALL" if n is None else str(n)
def period_stats(curve, per="month"):
    by={}
    for d,v in curve: by[d[:7] if per=="month" else d[:4]]=v
    keys=sorted(by); rets=[]; prev=100.0
    for k in keys: rets.append(by[k]/prev-1); prev=by[k]
    if not rets: return None
    prof=sum(1 for r in rets if r>0); worst=cur=0
    for r in rets: cur=cur+1 if r<=0 else 0; worst=max(worst,cur)
    peak,since,longest=100.0,0,0
    for k in keys:
        if by[k]>=peak: peak=by[k]; longest=max(longest,since); since=0
        else: since+=1
    longest=max(longest,since)
    return {"period":per,"n_periods":len(rets),"pct_profitable":round(100*prof/len(rets),1),
      "median_pct":round(statistics.median(rets)*100,2),
      "mean_pct_secondary_average":round(statistics.mean(rets)*100,2),
      "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
      "longest_losing_run_periods":worst,"longest_stretch_between_new_highs_periods":longest}
def maxdd(curve):
    peak,m=100.0,0.0
    for _,v in curve: peak=max(peak,v); m=min(m,v/peak-1)
    return round(m*100,2)
