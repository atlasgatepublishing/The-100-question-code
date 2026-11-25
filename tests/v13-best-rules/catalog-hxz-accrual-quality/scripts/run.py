#!/usr/bin/env python3
"""V13 best-rules run for catalog-hxz-accrual-quality.
Chassis frozen in BEST-RULES-SPEC.md: Acq, native universe (drop SIC 4/6),
annual June formation, QUINTILE (lowest-AQ), equal weight, NO floor,
tiered program costs, vanished->ZERO, 20-seed same-chassis placebos.
Engine logic reused from the v12 family engine (read-only inputs:
v12 signals.json + W04 broad price stack)."""
import json, os, math, random, statistics
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); FAM=os.path.join(HERE,'..')
V12=os.path.join(FAM,'..','..','v12-completions','catalog-hxz-accrual-quality')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand={int(k):v for k,v in loadj(os.path.join(W04,'candidates.json')).items()}
px={}
for cik,info in cand.items():
    t=info['ticker'].replace('/','-'); p=os.path.join(W04,f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik]={r[0]:(r[1],r[2]) for r in loadj(p)}
        except Exception: pass
spy={r[0]:r[1] for r in loadj(os.path.join(W04,'px_SPY.json'))}
SIG=loadj(os.path.join(V12,'signals.json'))['signals']
shares_f={}
for y in range(2009,2026):
    shares_f[y]={int(k):v for k,v in loadj(os.path.join(W04,'frames',f'Shares_{y}I.json')).items()}
sf={}
for cik in cand:
    avail=[(y,shares_f[y][cik]) for y in range(2009,2026) if cik in shares_f[y]]
    d={}
    for F in range(2016,2027):
        f=1.0
        for (y0,a),(y1,b) in zip(avail,avail[1:]):
            if y1>=F and a:
                r=b/a
                if r>=1.6 or r<=0.625: f*=r
        d[F]=f
    sf[cik]=d
def cap_of(cik,F):
    sh=shares_f.get(F-1,{}).get(cik) or shares_f.get(F-2,{}).get(cik)
    s=px.get(cik)
    if not sh or not s: return None
    e=s.get(f'{F:04d}-06')
    if not e or not e[1]: return None
    return sh*e[1]*sf.get(cik,{}).get(F,1.0)
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap>=5e9: return 0.0010
    if cap>=1e9: return 0.0025
    return 0.0075
def ym(y,m): return f'{y:04d}-{m:02d}'
POOLS={}; MATS={}
FORMS=sorted({int(f) for s in SIG.values() for f in s['values']})
SNAME='Acq'; UNI='native'
for F in FORMS:
    sig=SIG[SNAME]; vals={int(k):v for k,v in sig['values'].get(str(F),{}).items()}
    pool={}
    for cik,score in vals.items():
        if cik not in px: continue
        e=px[cik].get(ym(F,6))
        if not e or not e[0]: continue
        sic=str(cand[cik].get('sic') or '')
        if sic[:1] in ('4','6'): continue
        cap=cap_of(cik,F); pool[cik]={'score':score,'cap':cap,'rate':cost_rate(cap)}
    POOLS[F]=pool
    cols=[ym(F,m) for m in range(6,13)]+[ym(F+1,m) for m in range(1,7)]
    allciks=sorted(pool)
    M=np.full((len(allciks),13),np.nan); idx={c:i for i,c in enumerate(allciks)}
    for i,cik in enumerate(allciks):
        s=px[cik]; last=None; lastbar=max(s) if s else None
        for j,mm in enumerate(cols):
            if mm in s: last=s[mm][0]
            if lastbar is not None and mm>lastbar: M[i,j]=0.0
            elif last is not None: M[i,j]=last
    MATS[F]=(idx,M)
def picks_for(F):
    pool=POOLS[F]
    items=sorted(pool.items(),key=lambda kv: kv[1]['score'])  # dir=low
    n=max(1,math.ceil(len(items)*0.20)); return [c for c,_ in items[:n]]
def run_road(formations,seed=None):
    cash=100.0; curve=[]; total_costs=0.0
    for F in formations:
        idx,M=MATS[F]; pool=POOLS[F]
        if seed is None: picks=picks_for(F)
        else:
            rng=random.Random(seed*100003+F); keys=list(pool.keys()); rng.shuffle(keys)
            n=max(1,math.ceil(len(keys)*0.20)); picks=keys[:n]
        cols=[ym(F,m) for m in range(6,13)]+[ym(F+1,m) for m in range(1,7)]
        rows=np.array([idx[c] for c in picks]); P=M[rows,:]
        rates=np.array([pool[c]['rate'] for c in picks])
        px0=P[:,0].copy(); px0[px0<=0]=np.nan
        w=cash/len(picks)
        shares=np.where(np.isnan(px0),0.0,(w*(1-rates))/np.where(np.isnan(px0),1.0,px0))
        total_costs+=float(np.sum(w*rates))
        for j in range(1,13):
            pj=P[:,j]; vals=shares*np.where(np.isnan(pj),0.0,pj); val=float(np.sum(vals))
            if j==12:
                sell=float(np.sum(vals*rates)); total_costs+=sell; cash=val-sell
            else: cash=val
            curve.append([cols[j],round(cash,2)])
    peak=100.0; maxdd=0.0
    for _,v in curve:
        peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0.0
    return round(cash,2),curve,round(total_costs,2),round(maxdd,4)
def spy_final(formations):
    a=spy.get(ym(formations[0],6)); b=spy.get(ym(formations[-1]+1,6))
    return round(100*b/a,2) if a and b else None
def period_stats(curve):
    # monthly periods from equity curve, starting at 100
    vals=[100.0]+[v for _,v in curve]
    rets=[vals[i]/vals[i-1]-1 for i in range(1,len(vals)) if vals[i-1]>0]
    if not rets: return {}
    med=statistics.median(rets); pos=sum(1 for r in rets if r>0)/len(rets)
    best=max(rets); worst=min(rets)
    streak=longest=0
    for r in rets:
        streak=streak+1 if r<=0 else 0; longest=max(longest,streak)
    peak=vals[0]; since=0; maxgap=0
    for v in vals[1:]:
        if v>=peak: peak=v; since=0
        else: since+=1; maxgap=max(maxgap,since)
    annual={}
    return {'n_periods':len(rets),'median_period_pct':round(med*100,2),
            'share_positive_pct':round(pos*100,1),'best_period_pct':round(best*100,2),
            'worst_period_pct':round(worst*100,2),'longest_losing_streak_months':longest,
            'longest_months_between_new_highs':maxgap,
            'mean_period_pct_secondary':round(statistics.mean(rets)*100,2)}
def annual_stats(formations):
    # per-formation-year returns (each June->June year as its own $100 run is NOT
    # the road; instead slice the road curve at June boundaries)
    return None
ROADS={'LONGEST(2018-, LONG slot)':ALLF if False else FORMS,
       'DECADE-analog(2018-, identical)':FORMS,
       'CONT':[f for f in FORMS if f>=2019],
       'VAL':[f for f in FORMS if f>=2023],
       'FOLD_A_2018-2020':[f for f in FORMS if f<=2020],
       'FOLD_B_2021-2025':[f for f in FORMS if f>=2021]}
out={'family':'catalog-hxz-accrual-quality','spec':'native|annual|QUINTILE|no-floor',
     'pool_sizes':{str(F):len(POOLS[F]) for F in FORMS},'roads':{}}
for rname,forms in ROADS.items():
    fin,curve,costs,maxdd=run_road(forms)
    twins=[]
    for sd in range(1,21):
        tf,_,_,_=run_road(forms,seed=sd); twins.append(tf)
    out['roads'][rname]={'formations':forms,'final':fin,'costs':costs,'max_dd':maxdd,
        'spy_same_window':spy_final(forms),'placebo_finals':twins,
        'placebos_beaten':sum(1 for t in twins if fin>t),
        'placebo_median':round(statistics.median(twins),2),
        'period_distribution_monthly':period_stats(curve),'curve':curve}
    print(rname,fin,'dd',maxdd,'spy',spy_final(forms),'pb',out['roads'][rname]['placebos_beaten'],'/20',flush=True)
with open(os.path.join(FAM,'results.json'),'w') as fh: json.dump(out,fh,indent=1)
print('saved results.json')
