import json, glob, os, math, random, statistics as st
from datetime import date, timedelta
BASE='/home/hatch/workspace/stock-app/backtests'
CACHE=f'{BASE}/v4/crypto-basket-pit-data'
COST=0.006  # 0.60%/side crypto-realistic midpoint
STABLE={'USDT','USDC','DAI','BUSD','TUSD','USDP','USDe','USD1','FDUSD','GUSD','FRAX','LUSD','USTC'}
def load(sym):
    for pat in (f'{CACHE}/y_{sym}-USD.json', f'{CACHE}/b_{sym}USDT.json', f'{CACHE}/k_{sym}USD.json'):
        fs=glob.glob(pat)
        if fs:
            d=json.load(open(fs[0])); rows=[(r['d'],r['o'],r['c']) for r in d if r['c'] and r['c']>0 and r['o'] and r['o']>0]
            rows.sort(); return rows
    return None
MAP={'LUNA':'LUNC','UST':'USTC','MATIC':'MATIC','MIOTA':'IOTA','TON':'TON'}
snaps=json.load(open(f'{CACHE}/snapshots.json'))
syms=set()
for s in snaps.values():
    for t in s['top20']: syms.add(t['symbol'])
series={}
for s in sorted(syms):
    rows=load(MAP.get(s,s)) or load(s)
    if rows and len(rows)>=400: series[s]=rows
print('coins with >=400 bars:',len(series), sorted(series)[:10])

def windows(rows):
    d={r[0]:i for i,r in enumerate(rows)}
    return d
def maxdd(curve):
    pk=-1e18; m=0
    for v in curve:
        pk=max(pk,v); m=min(m, v/pk-1 if pk>0 else 0)
    return m
def period_stats(monthly_rets):
    if not monthly_rets: return {}
    s=sorted(monthly_rets); n=len(s)
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    run=worst=0
    for r in monthly_rets:
        run=run+1 if r<0 else 0; worst=max(worst,run)
    return dict(n=n, pct_pos=round(100*sum(1 for r in monthly_rets if r>0)/n,1), median_pct=round(med*100,2),
                best_pct=round(max(monthly_rets)*100,2), worst_pct=round(min(monthly_rets)*100,2), longest_losing_run=worst)

# ---------- TURN OF MONTH ----------
# Native window (L&S 1988): earn days -1,+1,+2,+3 around month turn. 24/7 translation:
# buy at close of 2nd-last calendar day of month, sell at close of 3rd calendar day of next month.
def tom_run(rows, house=False, shift=0):
    # build set of invested return-days (indices i where return from i-1 close to i close is earned)
    inv=set()
    months={}
    for i,(dt,o,c) in enumerate(rows): months.setdefault(dt[:7],[]).append(i)
    keys=sorted(months)
    for k in keys:
        idx=months[k]
        if len(idx)<25: continue
        win=[idx[-1]]  # day -1 return is earned holding from close of idx[-2]
        nxt=keys[keys.index(k)+1] if keys.index(k)+1<len(keys) else None
        if nxt: win+=months[nxt][:3]
        for j in win: inv.add(j+shift)
    eq=100.0; curve=[]; monthly={}; halted=False; cash_until=None; ep_start=100.0; restarts=0; trades=0
    holding=False
    for i,(dt,o,c) in enumerate(rows):
        if i==0: curve.append(eq); continue
        ret=c/rows[i-1][2]-1
        want=(i in inv)
        if house and cash_until and dt<cash_until: want=False
        if want and not holding:
            eq*= (1-COST); holding=True; trades+=1
        if holding and not want:
            eq*= (1-COST); holding=False; trades+=1
        if holding: eq*= (1+ret)
        if house and eq<=0.85*ep_start and not halted:
            if holding: eq*=(1-COST); holding=False
            if restarts>=1: halted=True; cash_until='9999'
            else:
                restarts+=1; cash_until=(date.fromisoformat(dt)+timedelta(days=90)).isoformat(); ep_start=eq
        curve.append(eq)
        monthly[dt[:7]]=eq
    mk=sorted(monthly); mrets=[monthly[mk[i]]/monthly[mk[i-1]]-1 for i in range(1,len(mk))]
    return eq, maxdd(curve), curve, period_stats(mrets), trades
def hold_run(rows, start=None):
    sub=[r for r in rows if not start or r[0]>=start]
    if len(sub)<10: return None
    return 100*(1-COST)*sub[-1][2]/sub[0][2]
tom={}
for s,rows in series.items():
    if s in STABLE: continue
    f,dd,_,ps,tr=tom_run(rows); fh,ddh,_,psh,_=tom_run(rows,house=True)
    recent=[r for r in rows if r[0]>='2022-01-01']  # warmup incl in inv calc on full rows; slice curve approx via rerun on rows from 2022 with pre-data
    tom[s]=dict(final_native=round(f,2), dd_native=round(dd*100,1), final_house=round(fh,2), dd_house=round(ddh*100,1),
                hold=round(hold_run(rows),2), trades=tr, periods=ps)
# shifted twin + 20-seed random-shift placebos (pooled median final)
shifts={'twin+10':10}
for name,sh in shifts.items():
    vals=[tom_run(r,shift=sh)[0] for s,r in series.items() if s not in STABLE]
    tom.setdefault('_placebo',{})[name]=round(st.median(vals),2)
seedmed=[]
for seed in range(20):
    rng=random.Random(seed+1); vals=[]
    for s,r in series.items():
        if s in STABLE: continue
        vals.append(tom_run(r,shift=rng.randint(5,25))[0])
    seedmed.append(st.median(vals))
realmed=st.median(v['final_native'] for v in tom.values() if isinstance(v,dict) and 'final_native' in v)
tom['_summary']=dict(n_coins=len([k for k in tom if not k.startswith('_')]), median_native=round(realmed,2),
    median_house=round(st.median(v['final_house'] for v in tom.values() if isinstance(v,dict) and 'final_house' in v),2),
    median_hold=round(st.median(v['hold'] for v in tom.values() if isinstance(v,dict) and 'hold' in v),2),
    coins_beat_hold=sum(1 for v in tom.values() if isinstance(v,dict) and 'hold' in v and v['final_native']>v['hold']),
    placebo_seeds_beaten=sum(1 for x in seedmed if realmed>x), placebo_median=round(st.median(seedmed),2),
    btc=tom.get('BTC'))
json.dump(tom, open('/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-x-turn-of-month/results.json','w'), indent=1)
print('TOM summary', tom['_summary'])

# ---------- VM-PLUS-TREND: TSMOM sleeve cross-form ----------
# MOP 2012: monthly, sign of trailing 12m return; long-only cross-form (negative -> cash), unscaled.
def tsmom_run(rows, house=False):
    closes=[r[2] for r in rows]; dates=[r[0] for r in rows]
    # monthly decision points: first bar of each month, signal = close 12 months ago vs decision close (prior bar)
    eq=100.0; holding=False; curve=[]; monthly={}; halted=False; cash_until=None; ep=100.0; restarts=0
    dec={}
    for i,dt in enumerate(dates): dec.setdefault(dt[:7], i)
    dkeys=sorted(dec)
    state={}
    for k in dkeys:
        i=dec[k]
        # find bar ~12 months earlier
        target=(date.fromisoformat(dates[i])-timedelta(days=365)).isoformat()
        j=max([x for x in range(i) if dates[x]<=target], default=None)
        state[k]= (j is not None and closes[i-1 if i>0 else i]>closes[j]) if j is not None else False
    for i,dt in enumerate(dates):
        want=state.get(dt[:7], False)
        if house and cash_until and dt<cash_until: want=False
        if i>0:
            if want and not holding: eq*=(1-COST); holding=True
            if holding and not want: eq*=(1-COST); holding=False
            if holding: eq*= closes[i]/closes[i-1]
        if house and eq<=0.85*ep and not halted:
            if holding: eq*=(1-COST); holding=False
            if restarts>=1: halted=True; cash_until='9999'
            else: restarts+=1; cash_until=(date.fromisoformat(dt)+timedelta(days=90)).isoformat(); ep=eq
        curve.append(eq); monthly[dt[:7]]=eq
    mk=sorted(monthly); mrets=[monthly[mk[i]]/monthly[mk[i-1]]-1 for i in range(1,len(mk))]
    return eq, maxdd(curve), period_stats(mrets)
ts={}
for s,rows in series.items():
    if s in STABLE: continue
    if rows[-1][0]<'2026-01-01' or rows[0][0]>'2019-06-01': continue
    f,dd,ps=tsmom_run(rows); fh,ddh,_=tsmom_run(rows,house=True)
    ts[s]=dict(final_native=round(f,2), dd_native=round(dd*100,1), final_house=round(fh,2), dd_house=round(ddh*100,1),
               hold=round(hold_run(rows),2), periods=ps)
ts['_summary']=dict(n_coins=len(ts), median_native=round(st.median(v['final_native'] for v in ts.values()),2),
    median_house=round(st.median(v['final_house'] for v in ts.values()),2),
    median_hold=round(st.median(v['hold'] for v in ts.values()),2),
    coins_beat_hold=sum(1 for v in ts.values() if v['final_native']>v['hold']), btc=ts.get('BTC'), eth=ts.get('ETH'))
json.dump(ts, open('/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-x-vm-plus-trend/results.json','w'), indent=1)
print('TSMOM summary', ts['_summary'])
