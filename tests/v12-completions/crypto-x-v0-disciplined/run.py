import json, glob, statistics as st
from datetime import date, timedelta
BASE='/home/hatch/workspace/stock-app/backtests'; CACHE=f'{BASE}/v4/crypto-basket-pit-data'; COST=0.006
def load(sym):
    d=json.load(open(f'{CACHE}/y_{sym}-USD.json')); return sorted([(r['d'],r['o'],r['c']) for r in d if r['c']>0 and r['o']>0])
UNIV=['BTC','ETH','XRP','LTC','BCH']  # 5 longest-history non-stable PIT coins (CONSTRUCTED universe translation)
S={s:load(s) for s in UNIV}
dates=sorted(set.intersection(*[set(r[0] for r in S[s]) for s in UNIV]))
dates=[d for d in dates if d>='2017-09-01']
idx={s:{r[0]:i for i,r in enumerate(S[s])} for s in UNIV}
def close(s,d): return S[s][idx[s][d]][2]
def opn(s,d): return S[s][idx[s][d]][1]
def run(mode, start='2018-01-01'):
    ds=[d for d in dates if d>=start]
    cash=100.0; pos={}  # sym->shares
    floor=85.0; ep=100.0; restarts=0; halted=False; cash_until=None; curve=[]; monthly={}
    def equity(d): return cash+sum(sh*close(s,d) for s,sh in pos.items())
    sel_months=sorted(set(d[:7] for d in ds))
    for mi,k in enumerate(sel_months):
        mdays=[d for d in ds if d[:7]==k]; d0=mdays[0]
        # signal from prior day (last date before d0 in full dates list)
        pi=dates.index(d0)-1; sig=dates[pi]
        if not halted and not (cash_until and sig<cash_until):
            elig=[]
            for s in UNIV:
                ii=idx[s][sig]; rows=S[s]
                if ii<200: continue
                ma=sum(r[2] for r in rows[ii-199:ii+1])/200
                if rows[ii][2]>ma: elig.append((rows[ii][2]/rows[ii-63][2]-1, s))
            elig.sort(reverse=True); picks=[s for _,s in elig[:2]]
            eq=equity(sig)
            target={s: eq*0.5 for s in picks}
            # sell non-picks / trim at d0 open approx via close-to-open: sell at open
            for s in list(pos):
                if s not in target:
                    cash+=pos.pop(s)*opn(s,d0)*(1-COST)
            for s in picks:
                cur=pos.get(s,0)*opn(s,d0); want=target[s]
                if cur>want: sh=(cur-want)/opn(s,d0); pos[s]-=sh; cash+=sh*opn(s,d0)*(1-COST)
                elif cur<want:
                    spend=min(want-cur, cash/(1+COST)); pos[s]=pos.get(s,0)+spend*(1-COST)/opn(s,d0); cash-=spend
        for d in mdays:
            # trend exit: held closes below 200d MA -> sell next open (approx: mark flag, execute next day open; simplified: sell at this close*(1-cost) if next day exists handled by flag)
            eq=equity(d); curve.append(eq); monthly[d[:7]]=eq
            if mode=='native':
                if eq>=150: floor=125.0
                elif eq>=125: floor=max(floor,100.0)
                if eq<=floor: halted=True
            else:
                if eq<=0.85*ep and not halted:
                    if restarts>=1: halted=True
                    else: restarts+=1; cash_until=(date.fromisoformat(d)+timedelta(days=90)).isoformat(); ep=eq
            if halted:
                cash=eq; pos={}; break
        if halted: break
    last=ds[-1] if not halted else curve[-1] and None
    final=curve[-1] if curve else 100.0
    pk=-1e18; mdd=0
    for v in curve: pk=max(pk,v); mdd=min(mdd, v/pk-1)
    mk=sorted(monthly); mr=[monthly[mk[i]]/monthly[mk[i-1]]-1 for i in range(1,len(mk))]
    ps={}
    if mr:
        srt=sorted(mr); n=len(srt); med=srt[n//2] if n%2 else (srt[n//2-1]+srt[n//2])/2
        runl=worst=0
        for r in mr: runl=runl+1 if r<0 else 0; worst=max(worst,runl)
        ps=dict(n=n,pct_pos=round(100*sum(1 for r in mr if r>0)/n,1),median_pct=round(med*100,2),best_pct=round(max(mr)*100,2),worst_pct=round(min(mr)*100,2),longest_losing_run=worst)
    return dict(final=round(final,2), maxdd_pct=round(mdd*100,1), halted=halted, periods=ps)
out={}
for mode in ('native','house'):
    out[mode]={}
    for start in ('2018-01-01','2023-01-01'):
        out[mode][start]=run(mode,start)
# BTC hold same windows
for start in ('2018-01-01','2023-01-01'):
    sub=[r for r in S['BTC'] if r[0]>=start]
    out.setdefault('btc_hold',{})[start]=round(100*(1-COST)*sub[-1][2]/sub[0][2],2)
json.dump(out, open('/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-x-v0-disciplined/results.json','w'), indent=1)
print(json.dumps(out,indent=1))
