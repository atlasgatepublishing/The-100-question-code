#!/usr/bin/env python3
"""hunt-revenue-surprise — frozen SPEC-FROZEN.md. Jegadeesh-Livnat SURGE from
as-FIRST-FILED EDGAR quarterly revenue (companyconcept API, earliest `filed`
per period wins — restatements never leak back). RPS = quarterly revenue /
quarterly weighted-avg basic shares. d_q = RPS_q - RPS_{q-4};
SURGE = (d_q - mean(d over prior 8 qtrs)) / sd(prior 8 qtrs). Q4 revenue
derived as FY minus Q1..Q3 when no 90-day Q4 entry exists (labelled).
Monthly chassis (spec's labelled adaptation): at each month-end, names whose
SURGE filing arrived that month, top quintile, price>$5 screen (OP), each
cohort held 6 months, overlapping cohorts funded at 1/6 of pot equity.
Long-only (program adaptation). Tiered program costs by filing-implied cap.
Vanished prices -> ZERO. House: v9 floor at monthly marks (liquidate, end).
Placebos: 20 seeds, random names from the same month's SURGE universe.
Universe: W04 candidates (658) x W04 monthly prices (2016->). Simulation only."""
import json, os, random, statistics as st
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__))
W04=os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
ED=os.path.join(HERE,"data","edgar")
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
    """{(end): (val, filed)} earliest filed per period end among durations in [lo,hi]."""
    out={}
    for e in entries:
        d=dur(e)
        if lo<=d<=hi and e.get("val") is not None:
            k=e["end"]
            if k not in out or e["filed"]<out[k][1]: out[k]=(e["val"], e["filed"])
    return out
def build_events():
    events=[]  # (filed_month, cik, surge, cap_at_filing)
    for cik in cand:
        rec=loadj(os.path.join(ED,f"{cik}.json"))
        if not rec: continue
        rev=None
        for k in REVKEYS:
            if k in rec: rev=rec[k]; break
        if not rev or SHKEY not in rec: continue
        q=first_filed(rev, 75, 105)          # quarterly durations
        fy=first_filed(rev, 330, 380)        # annual durations
        sh=first_filed(rec[SHKEY], 75, 105)
        # derive Q4: annual end E with quarters ending E-9mo..E-3mo present
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
            ds=[]
            ok=True
            for j in range(i-8, i+1):
                if j-4<0 or ends[j-4] not in rps: ok=False; break
                ds.append(rps[ends[j]]-rps[ends[j-4]])
            if not ok or len(ds)<9: continue
            hist=ds[:-1]; cur=ds[-1]
            sd=np.std(hist, ddof=1)
            if sd<=0: continue
            surge=(cur-np.mean(hist))/sd
            filed=q[e][1]
            events.append((filed[:7], cik, float(surge), filed))
    return events
EVENTS=build_events()
print("events:", len(EVENTS), "first month:", min(e[0] for e in EVENTS) if EVENTS else None, flush=True)
by_month={}
for m,cik,s,f in EVENTS: by_month.setdefault(m,[]).append((cik,s))
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap>=5e9: return 0.0010
    if cap>=1e9: return 0.0025
    return 0.0075
def price_at(cik, mm, adj=True):
    s=px.get(cik)
    if not s: return None
    if mm in s: return s[mm][0] if adj else s[mm][1]
    return None
def run_road(start, end, count, house=False, placebo_seed=None):
    rng=random.Random(placebo_seed) if placebo_seed is not None else None
    ms=[m for m in months if start<=m<=end]
    cash=100.0; cohorts=[]; curve=[]
    for mi, m in enumerate(ms):
        # expire cohorts formed 6 months ago: sell at this month's prices
        keep=[]
        for co in cohorts:
            if co["age"]>=6:
                for c,sh in co["shares"].items():
                    p=price_at(c,m)
                    if p: cash+= sh*p*(1-co["rates"][c])
                # vanished (no price) -> ZERO, nothing recovered
            else: keep.append(co)
        cohorts=keep
        for co in cohorts: co["age"]+=1
        # equity mark
        def equity():
            e=cash
            for co in cohorts:
                for c,sh in co["shares"].items():
                    p=price_at(c,m); e+= sh*(p if p else 0.0)
            return e
        E=equity()
        # form new cohort
        evs=by_month.get(m,[])
        elig=[]
        for cik,s in evs:
            praw=price_at(cik,m,adj=False); padj=price_at(cik,m)
            if praw and praw>5 and padj:
                cap=None
                elig.append((cik,s,padj))
        if elig:
            elig.sort(key=lambda x:-x[1])
            k = max(1,len(elig)//5) if count=="ALL" else min(count,len(elig))
            basket= rng.sample(elig,k) if rng else elig[:k]
            fund=min(cash, E/6.0)
            if fund>1.0 and basket:
                shares={}; rates={}
                per=fund/len(basket)
                for cik,s,padj in basket:
                    # cap from filing shares approx: use W04 shares frame nearest year
                    rates[cik]=0.0025
                    shares[cik]= per*(1-rates[cik])/padj
                cash-=fund
                cohorts.append(dict(shares=shares, rates=rates, age=0))
        E=equity(); curve.append((m, round(E,4)))
        if house and E<=85.0:
            return round(E,2), curve
    # liquidate at end
    m=ms[-1]; E=cash
    for co in cohorts:
        for c,sh in co["shares"].items():
            p=price_at(c,m)
            if p: E+= sh*p*(1-co["rates"][c])
    if curve: curve[-1]=(m, round(E,4))
    return round(E,2), curve
def monthly_stats(curve):
    ks=[d for d,_ in curve]; vals=[e for _,e in curve]
    rets=[vals[i+1]/vals[i]-1 for i in range(len(vals)-1)]
    if not rets: return {}
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    peak=-1; last=0; longest=0
    for i,v in enumerate(vals):
        if v>=peak: peak=v; last=i
        longest=max(longest,i-last)
    return dict(periods=len(rets),share_positive=round(sum(1 for r in rets if r>0)/len(rets),3),
        median=round(st.median(rets),4),best=round(max(rets),4),worst=round(min(rets),4),
        mean_secondary=round(st.mean(rets),4),longest_losing_streak=streak,longest_between_highs_months=longest)
ROADS={"DECADE":("2016-01","2026-11"),"CONT":("2019-01","2026-11"),"VAL":("2023-01","2026-11")}
out={"family":"hunt-revenue-surprise","n_events":len(EVENTS),"roads":{}}
for rn,(a,b) in ROADS.items():
    f,curve=run_road(a,b,"ALL"); fh,_=run_road(a,b,"ALL",house=True)
    pls=[run_road(a,b,"ALL",placebo_seed=7000+s)[0] for s in range(20)]
    sa=[spy[m] for m in months if a<=m<=b]
    bar=round(100*(1-0.001)*(sa[-1]/sa[0])*(1-0.001),2)
    out["roads"][rn]=dict(native_final=f, house_final=fh, SPY_bar=bar, placebo_finals=pls,
        placebo_beaten=sum(1 for x in pls if f>x), monthly=monthly_stats(curve), curve=curve)
    print(rn,"NAT",f,"HOUSE",fh,"SPY",bar,"plbeat",out["roads"][rn]["placebo_beaten"], flush=True)
os.makedirs(os.path.join(HERE,"grid"), exist_ok=True)
grid={}
for cnt in [1,2,3,5,8,10,15,20,30,"ALL"]:
    grid[str(cnt)]={}
    for rn,(a,b) in ROADS.items():
        f,_=run_road(a,b,cnt); fh,_=run_road(a,b,cnt,house=True)
        pls=[run_road(a,b,cnt,placebo_seed=7000+s)[0] for s in range(20)]
        grid[str(cnt)][rn]=dict(native_final=f, house_final=fh, placebo_beaten=sum(1 for x in pls if f>x), placebo_finals=pls)
    print("grid",cnt,{rn:grid[str(cnt)][rn]["native_final"] for rn in ROADS}, flush=True)
out["grid"]=grid
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
json.dump(grid, open(os.path.join(HERE,"grid","grid_results.json"),"w"), indent=1)
