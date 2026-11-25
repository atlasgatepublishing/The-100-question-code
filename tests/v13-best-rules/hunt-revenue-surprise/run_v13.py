#!/usr/bin/env python3
"""hunt-revenue-surprise — V13 BEST RULES (see BEST-RULES-SPEC.md, frozen first).
Same plumbing as v12 (as-FIRST-FILED EDGAR SURGE, W04 monthly prices, vanished
-> ZERO, 0.25%/side). My rules: top DECILE, 2-month hold, 2 overlapping cohorts
funded at 1/2 equity, no floor. Published-form comparator in the same engine:
top quintile, 6-month hold, 1/6 funding. Placebos: 20 seeds, random names from
the same month's eligible universe, same count/chassis as my form."""
import json, os, random, statistics as st
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-revenue-surprise")
W04=os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
ED=os.path.join(SRC,"data","edgar")
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand={int(k):v for k,v in loadj(os.path.join(W04,"candidates.json")).items()}
px={}
for cik,info in cand.items():
    t=info["ticker"].replace("/","-"); p=os.path.join(W04,f"px_{t}.json")
    if os.path.exists(p):
        try: px[cik]={r[0]:(r[1],r[2]) for r in loadj(p)}
        except Exception: pass
spy={r[0]:r[1] for r in loadj(os.path.join(W04,"px_SPY.json"))}
months=sorted(spy)
REVKEYS=["Revenues","SalesRevenueNet","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueGoodsNet","SalesRevenueServicesNet"]
SHKEY="WeightedAverageNumberOfSharesOutstandingBasic"
def dur(e):
    from datetime import date
    try:
        a=date.fromisoformat(e["start"]); b=date.fromisoformat(e["end"]); return (b-a).days
    except Exception: return -1
def first_filed(entries, lo, hi):
    out={}
    for e in entries:
        d=dur(e)
        if lo<=d<=hi and e.get("val") is not None:
            k=e["end"]
            if k not in out or e["filed"]<out[k][1]: out[k]=(e["val"], e["filed"])
    return out
def build_events():
    events=[]
    for cik in cand:
        rec=loadj(os.path.join(ED,f"{cik}.json"))
        if not rec: continue
        rev=None
        for k in REVKEYS:
            if k in rec: rev=rec[k]; break
        if not rev or SHKEY not in rec: continue
        q=first_filed(rev, 75, 105); fy=first_filed(rev, 330, 380); sh=first_filed(rec[SHKEY], 75, 105)
        ends=sorted(q)
        for E,(av,af) in list(fy.items()):
            qs=[e for e in ends if e<E and (np.datetime64(E)-np.datetime64(e)).astype(int)<=300]
            if len(qs)>=3:
                qs=sorted(qs)[-3:]
                if all(e in q for e in qs) and E not in q:
                    q[E]=(av-sum(q[e][0] for e in qs), af)
        rps={}
        for e,(v,f) in q.items():
            if e in sh and sh[e][0]>0: rps[e]=v/sh[e][0]
        ends=sorted(rps)
        if len(ends)<13: continue
        for i in range(12, len(ends)):
            e=ends[i]
            if ends[i-4] not in rps: continue
            ds=[]; ok=True
            for j in range(i-8, i+1):
                if j-4<0 or ends[j-4] not in rps: ok=False; break
                ds.append(rps[ends[j]]-rps[ends[j-4]])
            if not ok or len(ds)<9: continue
            hist=ds[:-1]; cur=ds[-1]; sd=np.std(hist, ddof=1)
            if sd<=0: continue
            surge=(cur-np.mean(hist))/sd
            filed=q[e][1]
            events.append((filed[:7], cik, float(surge), filed))
    return events
EVENTS=build_events()
print("events:", len(EVENTS), "first month:", min(e[0] for e in EVENTS) if EVENTS else None, flush=True)
by_month={}
for m,cik,s,f in EVENTS: by_month.setdefault(m,[]).append((cik,s))
COST=0.0025
def price_at(cik, mm, adj=True):
    s=px.get(cik)
    if not s: return None
    if mm in s: return s[mm][0] if adj else s[mm][1]
    return None
def run_road(start, end, hold, frac_div, placebo_seed=None):
    """frac_div: basket = top 1/frac_div of month's eligible filers.
    Cohort funded at equity/hold; held `hold` months."""
    rng=random.Random(placebo_seed) if placebo_seed is not None else None
    ms=[m for m in months if start<=m<=end]
    cash=100.0; cohorts=[]; curve=[]; n_trades=0; costs_paid=0.0
    for mi, m in enumerate(ms):
        keep=[]
        for co in cohorts:
            if co["age"]>=hold:
                for c,sh in co["shares"].items():
                    p=price_at(c,m)
                    if p: cash+= sh*p*(1-COST); costs_paid+= sh*p*COST
            else: keep.append(co)
        cohorts=keep
        for co in cohorts: co["age"]+=1
        def equity():
            e=cash
            for co in cohorts:
                for c,sh in co["shares"].items():
                    p=price_at(c,m); e+= sh*(p if p else 0.0)
            return e
        E=equity()
        evs=by_month.get(m,[])
        elig=[]
        for cik,s in evs:
            praw=price_at(cik,m,adj=False); padj=price_at(cik,m)
            if praw and praw>5 and padj: elig.append((cik,s,padj))
        if elig:
            elig.sort(key=lambda x:-x[1])
            k=max(1,len(elig)//frac_div)
            basket= rng.sample(elig,k) if rng else elig[:k]
            fund=min(cash, E/float(hold))
            if fund>1.0 and basket:
                shares={}; per=fund/len(basket)
                for cik,s,padj in basket:
                    shares[cik]= per*(1-COST)/padj; costs_paid+= per*COST
                cash-=fund; cohorts.append(dict(shares=shares, age=0)); n_trades+=len(basket)
        E=equity(); curve.append((m, round(E,4)))
    m=ms[-1]; E=cash
    for co in cohorts:
        for c,sh in co["shares"].items():
            p=price_at(c,m)
            if p: E+= sh*p*(1-COST); costs_paid+= sh*p*COST
    if curve: curve[-1]=(m, round(E,4))
    return round(E,2), curve, n_trades, round(costs_paid,2)
def monthly_stats(curve):
    vals=[e for _,e in curve]
    rets=[vals[i+1]/vals[i]-1 for i in range(len(vals)-1)]
    if not rets: return {}
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    peak=-1; last=0; longest=0; mdd=0.0; run_peak=vals[0]
    for i,v in enumerate(vals):
        if v>=peak: peak=v; last=i
        longest=max(longest,i-last)
        run_peak=max(run_peak,v); mdd=min(mdd, v/run_peak-1)
    return dict(periods=len(rets),share_positive=round(sum(1 for r in rets if r>0)/len(rets),3),
        median=round(st.median(rets),4),best=round(max(rets),4),worst=round(min(rets),4),
        mean_secondary=round(st.mean(rets),4),longest_losing_streak=streak,
        longest_between_highs_months=longest,max_drawdown=round(mdd,4))
ROADS={"DECADE":("2016-11","2026-11"),"CONT":("2019-01","2026-11"),"VAL":("2023-01","2026-11")}
CHAMP={"DECADE":667.35,"CONT":544.47,"VAL":288.05}
V12PUB={"DECADE":270.70,"CONT":164.11,"VAL":124.27}
out={"family":"hunt-revenue-surprise","program":"v13-best-rules","n_events":len(EVENTS),
     "spec":"top decile, 2mo hold, cohorts at 1/2 equity, no floor, 0.25%/side",
     "roads":{},"champions":CHAMP}
for rn,(a,b) in ROADS.items():
    f,curve,nt,cp=run_road(a,b,hold=2,frac_div=10)
    pf,pcurve,_,_=run_road(a,b,hold=6,frac_div=5)
    pls=[run_road(a,b,hold=2,frac_div=10,placebo_seed=7000+s)[0] for s in range(20)]
    sa=[spy[m] for m in months if a<=m<=b]
    bar=round(100*(1-0.001)*(sa[-1]/sa[0])*(1-0.001),2)
    out["roads"][rn]=dict(my_final=f, my_curve=curve, my_monthly=monthly_stats(curve),
        my_trades=nt, my_costs_paid=cp,
        published_form_same_window_final=pf, published_form_curve=pcurve,
        published_form_monthly=monthly_stats(pcurve), v12_published_final=V12PUB[rn],
        SPY_same_window=bar, champion=CHAMP[rn], placebo_finals=pls,
        placebo_beaten=sum(1 for x in pls if f>x),
        placebo_median=round(st.median(pls),2))
    print(rn,"MINE",f,"PUB(same win)",pf,"SPY",bar,"plbeat",out["roads"][rn]["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
print("done")
