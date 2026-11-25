#!/usr/bin/env python3
"""Zakamulin-Giner optimal trend (CONSTRUCTED) — monthly timers.
SPY: W04 monthly adj closes 2016-2026. BTC: v4 daily closes -> monthly.
Rules MOM(n), P-MA(n) n=2..12, COMBI-VOTE majority of MOM10/P-MA10/MAC(5,10).
Native cost 0.25%/side (paper); house 0.10%/side + -15% peak floor
(halt to cash 3 months). Placebos: 20 random-timing seeds, same long share."""
import json, os, random, csv
import statistics
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
BASE=os.path.join(FAM,'..','..')
W04=os.path.join(BASE,'v11-native-rules','_w04_broad_data')
spy={r[0]:r[1] for r in json.load(open(os.path.join(W04,'px_SPY.json')))}
months=sorted(spy); SP=[spy[m] for m in months]
# BTC monthly closes from daily csv
btc={}
with open(os.path.join(BASE,'v4','crypto-trend-data','BTC-USD.csv')) as fh:
    rd=csv.DictReader(fh)
    cols=rd.fieldnames
    for row in rd:
        d=row[cols[0]]; v=row.get('Close') or row.get('close') or row[cols[1]]
        try: btc[d[:7]]=float(v)
        except Exception: pass
bm=sorted(btc); BT=[btc[m] for m in bm]
def sma(s,i,n): return sum(s[i-n+1:i+1])/n if i>=n-1 else None
def signals(s,rule,n):
    out=[]
    for i in range(len(s)):
        if rule=='MOM': out.append(1 if i>=n and s[i]>s[i-n] else 0)
        elif rule=='P-MA':
            m=sma(s,i,n); out.append(1 if m is not None and s[i]>m else 0)
        elif rule=='MAC':
            a=sma(s,i,5); b=sma(s,i,10); out.append(1 if a is not None and b is not None and a>b else 0)
    return out
def combi(s):
    a=signals(s,'MOM',10); b=signals(s,'P-MA',10); c=signals(s,'MAC',0)
    return [1 if x+y+z>=2 else 0 for x,y,z in zip(a,b,c)]
def run(s,sig,cost,house=False,seed=None):
    cash=100.0; peak=100.0; curve=[]; invested=False; halt=0; costs=0.0
    if seed is not None:
        rng=random.Random(seed); share=sum(sig)/max(1,len(sig))
        sig=[1 if rng.random()<share else 0 for _ in sig]
    for i in range(1,len(s)):
        want=bool(sig[i-1])
        if house and halt>0:
            want=False; halt-=1
        if want!=invested:
            c=cash*cost; costs+=c; cash-=c; invested=want
        if invested: cash*=s[i]/s[i-1]
        curve.append(round(cash,2)); peak=max(peak,cash)
        if house and cash<=0.85*peak and invested:
            c=cash*cost; costs+=c; cash-=c; invested=False; halt=3; curve[-1]=round(cash,2)
    dd=0.0; pk=100.0
    for v in curve: pk=max(pk,v); dd=max(dd,1-v/pk)
    return round(cash,2),curve,round(costs,2),round(dd,4)
def period_stats(curve,months_list):
    vals=[100.0]+curve; rets=[]
    for i in range(12,len(vals),12): rets.append(vals[i]/vals[i-12]-1)
    if not rets: return None
    pos=sum(1 for r in rets if r>0); run=0; worst=0
    for r in rets: run=run+1 if r<=0 else 0; worst=max(worst,run)
    pk=vals[0]; cur=0; nohigh=0
    for v in vals:
        if v>=pk: pk=v; cur=0
        else: cur+=1; nohigh=max(nohigh,cur)
    return {'periods':len(rets),'positive':pos,'median_pct':round(statistics.median(rets)*100,1),
            'mean_pct_secondary':round(statistics.mean(rets)*100,1),'best_pct':round(max(rets)*100,1),
            'worst_pct':round(min(rets)*100,1),'longest_losing_run':worst,'longest_months_between_highs':nohigh}
def roads(months_list):
    idx={m:i for i,m in enumerate(months_list)}
    out={}
    def seg(a,b):
        i=idx.get(a); j=idx.get(b)
        return (i,j) if i is not None and j is not None and j>i else None
    for name,(a,b) in {'DECADE':('2017-01','2026-06'),'CONT':('2019-07','2026-06'),'VAL':('2023-07','2026-06'),'LONGEST':('2016-07','2026-06')}.items():
        s=seg(a,b)
        if s: out[name]=s
    return out
res={'family':'catalog-taa-zakamulin-optimal-trend','assets':{}}
for label,series,mlist,cost_native,cost_house in (('SPY',SP,months,0.0025,0.0010),('BTC',BT,bm,0.0050,0.0050)):
    cells={}
    bh={}
    for rname,(i0,i1) in roads(mlist).items():
        bh[rname]=round(100*series[i1]/series[i0],2)
    rules=[(f'MOM{n}','MOM',n) for n in range(2,13)]+[(f'PMA{n}','P-MA',n) for n in range(2,13)]+[('COMBI-VOTE','COMBI',0)]
    for cname,rule,n in rules:
        sig=signals(series,rule,n) if rule!='COMBI' else combi(series)
        for rb,cost in (('native',cost_native),('house',cost_house)):
            cell={}
            for rname,(i0,i1) in roads(mlist).items():
                sub=series[i0:i1+1]; ssig=sig[i0:i1+1]
                fin,curve,costs,dd=run(sub,ssig,cost,house=(rb=='house'))
                twins=[run(sub,ssig,cost,house=(rb=='house'),seed=sd)[0] for sd in range(1,21)]
                cell[rname]={'final':fin,'costs':costs,'max_dd':dd,'buyhold_same_window':bh[rname],
                             'placebo_finals':twins,'placebos_beaten':sum(1 for t in twins if fin>t),
                             'long_share':round(sum(ssig)/len(ssig),3),'curve':curve}
            cells[f'{cname}|{rb}']=cell
            print(label,cname,rb,'LONGEST/DECADE',cell.get('LONGEST',cell.get('DECADE',{})).get('final'),flush=True)
    res['assets'][label]={'months':[mlist[0],mlist[-1]],'buyhold_roads':bh,'cells':cells}
    # period stats for headline cell
    key='PMA10|native'
    if key in cells and 'DECADE' in cells[key]:
        res['assets'][label]['period_stats_PMA10_native_DECADE']=period_stats(cells[key]['DECADE']['curve'],mlist)
json.dump(res,open(os.path.join(FAM,'results.json'),'w'),indent=1)
print('saved')
