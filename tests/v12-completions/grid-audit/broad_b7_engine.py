#!/usr/bin/env python3
"""B7 broad-universe grid slices. W04 broad stack (READ-ONLY), annual June-30
formation, monthly marks, tiered habitat costs, vanished->ZERO, no floor
(the W04/vm-broad convention). Host ranking = champion combination rule
(average of B/M and 12-1 momentum percentile ranks) on the broad pool.
Overlays (trendgate/panicgate/volscale) applied at monthly granularity —
the only granularity the W04 stack supports; deviations labeled in BROAD.md.
Simulation only."""
import json, os, sys, random, statistics, math
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
sys.path.insert(0, W04)
import engine_w04 as E
E.D = E.Data(); D = E.D
def ym(y,m): return f'{y:04d}-{m:02d}'
def pct_ranks(vals):
    items = sorted(vals.items(), key=lambda kv: kv[1]); n=len(items)
    if n==1: return {items[0][0]:0.5}
    return {c:i/(n-1) for i,(c,_) in enumerate(items)}

POOLS={}
def pool_for(F):
    if F in POOLS: return POOLS[F]
    s=E.snapshot(F); pool={}
    for c,v in s.items():
        if not v['cap'] or v['cap']<50e6: continue
        if not v['equity'] or v['equity']<=0: continue
        if not v['shares'] or not v['px_adj']: continue
        if not (D.has_price_month(c,ym(F,6)) and D.has_price_month(c,ym(F,5)) and D.has_price_month(c,ym(F-1,6))): continue
        pm=D.price(c,ym(F,5)); pp=D.price(c,ym(F-1,6))
        if not pm or not pp: continue
        ebit=(v['opinc']+(v['interest'] or 0)) if v['opinc'] is not None else None
        ev=v['cap']+(v['ltd'] or 0)-(v['cash'] or 0)
        pool[c]=dict(bm=v['equity']/v['cap'], mom=pm/pp-1.0, cap=v['cap'], ticker=v['ticker'],
                     px=v['px_adj'], ey=(ebit/ev if (ebit is not None and ev and ev>0) else None))
    POOLS[F]=pool; return pool

def ranked(F, signal='vm'):
    pool=pool_for(F)
    if signal=='vm':
        vr=pct_ranks({c:v['bm'] for c,v in pool.items()}); mr=pct_ranks({c:v['mom'] for c,v in pool.items()})
        comb={c:(vr[c]+mr[c])/2 for c in pool}
    elif signal=='mom':
        comb={c:v['mom'] for c,v in pool.items()}
    elif signal=='val':
        comb={c:v['bm'] for c,v in pool.items()}
    elif signal=='ey':
        sub={c:v['ey'] for c,v in pool.items() if v['ey'] is not None}
        er=pct_ranks(sub); mr=pct_ranks({c:v['mom'] for c,v in pool.items()})
        comb={c:(er[c]+mr[c])/2 for c in sub}; pool={c:pool[c] for c in sub}
    return sorted(pool, key=lambda c:-comb[c]), pool, comb

def months_of(F): return [ym(F,m) for m in range(7,13)]+[ym(F+1,m) for m in range(1,7)]

def run_picks(formations, pick_fn, seed=None, start_cash=100.0):
    """pick_fn(F, rng_or_None) -> list of ciks. Monthly marks, costs in/out."""
    cash=start_cash; curve=[]; costs=0.0; orders=0; zeroed=0; yearly=[]
    for F in formations:
        pool=pool_for(F)
        picks=pick_fn(F, seed)
        st=cash
        if not picks: yearly.append({'formation':F,'pool':len(pool),'picks':[],'ret':0.0}); continue
        w=cash/len(picks); pos={}
        for c in picks:
            r=E.cost_rate(pool[c]['cap']); costs+=w*r; orders+=1; pos[c]=(w-w*r)/pool[c]['px']
        for mm in months_of(F):
            val=0.0
            for c,sh in pos.items():
                if D.has_price_month(c,mm): val+=sh*D.price(c,mm)
                else: zeroed+=1
            curve.append([mm, round(val,4)])
        end=0.0
        for c,sh in pos.items():
            if D.has_price_month(c,ym(F+1,6)):
                g=sh*D.price(c,ym(F+1,6)); r=E.cost_rate(pool[c]['cap']); costs+=g*r; orders+=1; end+=g-g*r
            else: zeroed+=1
        cash=end
        yearly.append({'formation':F,'pool':len(pool),'picks':[pool[c]['ticker'] for c in picks],'ret':round(cash/st-1,4) if st else 0.0})
    peak=100.0; maxdd=0.0
    for _,v in curve: peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0
    spy=None
    if formations and D.spy:
        a=D.spy.get(ym(formations[0],6)); b=D.spy.get(ym(formations[-1]+1,6))
        if a and b: spy=round(100*b/a,2)
    return {'final':round(cash,2),'max_dd_pct':round(maxdd*100,2),'costs':round(costs,2),'orders':orders,
            'zeroed_name_months':zeroed,'curve':curve,'yearly':yearly,'spy_final_same_window':spy}

def spy_monthly():
    return {k:v for k,v in D.spy.items()}
SPY=spy_monthly()
def spy_ret(mm_prev, mm): 
    a=SPY.get(mm_prev); b=SPY.get(mm)
    return (b/a-1.0) if (a and b) else 0.0
def all_months(formations):
    ms=[]
    for F in formations: ms+=months_of(F)
    return ms

def overlay_run(formations, mode, seed=None):
    """Host top-5 monthly returns, then overlay exposure series. Exposure
    changes charged 0.25% of equity x |delta w| (labeled approximation)."""
    # host monthly gross returns via run_picks curve ratio per formation block
    def pick_fn(F, sd):
        pool=pool_for(F)
        if sd is None:
            r,_,_=ranked(F,'vm'); return r[:5]
        rng=random.Random(sd*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
    base=run_picks(formations, pick_fn, seed=seed)
    curve=base['curve']; months=[m for m,_ in curve]; vals=[v for _,v in curve]
    # SPY closes list aligned: formation June close = start
    spy_series=[]
    prev_ym=ym(formations[0],6); spy_series.append(SPY.get(prev_ym))
    for mm in months: spy_series.append(SPY.get(mm))
    # monthly SPY returns for variance proxy
    spy_rets=[]
    for i in range(1,len(spy_series)):
        spy_rets.append(spy_series[i]/spy_series[i-1]-1.0 if spy_series[i] and spy_series[i-1] else 0.0)
    eq=100.0; w_prev=1.0; out=[]; trans_costs=0.0; gate_off=0
    var_hist=[]
    for i,mm in enumerate(months):
        # host month return
        prev_val = 100.0 if i==0 else vals[i-1]
        # NOTE curve vals are per-formation pot values (reset each formation in run_picks? no - cash chains, curve is continuous equity)
        hr = vals[i]/prev_val-1.0 if prev_val else 0.0
        if mode=='trendgate':
            # SPY month-end closes up to previous month-end vs 10m SMA
            closes=[]
            # build month-end close series ending at previous month
            idx=i  # spy_series[idx] is close at previous month-end (start offset)
            window=spy_series[max(0,idx-9):idx+1]
            w = 1.0 if (len(window)>=1 and spy_series[idx] is not None and spy_series[idx] >= sum(window)/len(window)) else 0.0
            if len(window)<10: w=1.0
        elif mode=='panicgate':
            # IB: SPY cum return trailing 24 months < 0 (monthly closes)
            idx=i
            if idx>=24 and spy_series[idx-24]:
                ib = 1 if spy_series[idx]/spy_series[idx-24]-1.0 < 0 else 0
            else: ib=0
            if ib==0: w=1.0
            else:
                tr=spy_rets[max(0,i-11):i]  # trailing 12 monthly rets (monthly proxy for 126d)
                var=statistics.variance(tr) if len(tr)>=3 else 0.0
                var_hist.append(var)
                ref=statistics.median(var_hist) if var_hist else var
                w=min(1.0, ref/var) if var>0 else 1.0
        elif mode=='volscale':
            tr=[]
            # host trailing 6 monthly returns
            hv=[]
            for j in range(max(0,i-6),i):
                pv = 100.0 if j==0 else vals[j-1]
                hv.append(vals[j]/pv-1.0 if pv else 0.0)
            if len(hv)>=3:
                sig=statistics.pstdev(hv)*math.sqrt(12)
                w=min(1.0, 0.12/sig) if sig>0 else 1.0
            else: w=1.0
        else: w=1.0
        if w<0.5: gate_off+=1
        tc=0.0025*abs(w-w_prev)*eq; trans_costs+=tc; eq-=tc
        eq*= (1+w*hr)
        out.append([mm, round(eq,4)]); w_prev=w
    peak=100.0; maxdd=0.0
    for _,v in out: peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0
    return {'final':round(eq,2),'max_dd_pct':round(maxdd*100,2),'curve':out,'gate_off_months':gate_off,
            'transition_costs_approx':round(trans_costs,2),'host_final_unmodified':base['final'],
            'host_costs':base['costs'],'host_orders':base['orders'],'spy_final_same_window':base['spy_final_same_window']}

def period_stats(curve, start=100.0):
    vals=[start]+[v for _,v in curve]; months=[m for m,_ in curve]
    rets=[vals[i]/vals[i-1]-1.0 for i in range(1,len(vals)) if vals[i-1]]
    if not rets: return {}
    pos=sum(1 for r in rets if r>0)
    best=max(range(len(rets)), key=lambda i: rets[i]); worst=min(range(len(rets)), key=lambda i: rets[i])
    run=longest=0
    for r in rets:
        run=run+1 if r<=0 else 0; longest=max(longest,run)
    peak=vals[0]; stretch=cur=0
    for v in vals:
        if v>=peak: peak=v; cur=0
        else: cur+=1; stretch=max(stretch,cur)
    return {'periods':len(rets),'pct_positive':round(100*pos/len(rets),1),'median_pct':round(statistics.median(rets)*100,2),
            'best':f"{months[best]} {rets[best]*100:+.2f}%",'worst':f"{months[worst]} {rets[worst]*100:+.2f}%",
            'longest_losing_run':longest,'longest_below_high_months':stretch,
            'mean_pct_secondary':round(statistics.mean(rets)*100,2)}

ROADS={'FULL_2017_2025':list(range(2017,2026)),'CONT_era_2019_2025':list(range(2019,2026)),'VAL_era_2023_2025':list(range(2023,2026))}

def with_placebos(run_fn):
    out={}
    for name,forms in ROADS.items():
        r=run_fn(forms,None); twins=[]
        for s in range(1,21):
            t=run_fn(forms,s); twins.append(t['final'])
        out[name]=r; out[name+'_placebo_finals']=twins
        out[name+'_placebos_beaten']=sum(1 for t in twins if r['final']>t)
        out[name+'_placebo_median']=round(statistics.median(twins),2)
        out[name+'_period_stats']=period_stats(r['curve'])
        print(name, r['final'], 'spy', r.get('spy_final_same_window'), 'beaten', out[name+'_placebos_beaten'], flush=True)
    return out

def save(slug, payload):
    d=os.path.expanduser(f'~/workspace/stock-app/backtests/v12-completions/{slug}/grid/broad')
    os.makedirs(d, exist_ok=True)
    json.dump(payload, open(os.path.join(d,'broad_results.json'),'w'), indent=1)
    print('saved', slug, flush=True)

if __name__=='__main__':
    which=sys.argv[1]
    if which=='breadth10':
        def fn(forms,sd):
            def pf(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'vm'); return r[:10]
                rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:10]
            return run_picks(forms,pf,seed=sd)
        save('vm-breadth10', {'family':'vm-breadth10','slice':'broad-universe','host':'W04 annual top-10 of broad V+M ranking', **with_placebos(fn)})
    elif which=='buffer':
        state={'held':[]}
        def make():
            held=[]
            def fn(forms,sd):
                nonlocal held; held=[]
                def pf(F,s):
                    nonlocal held
                    pool=pool_for(F); r,_,comb=ranked(F,'vm'); n=len(pool)
                    buy=set(r[:max(1,int(round(0.10*n)))]); hold=set(r[:max(1,int(round(0.20*n)))])
                    if s is not None:
                        rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks)
                        buy=set(ks[:max(1,int(round(0.10*n)))]); hold=set(ks[:max(1,int(round(0.20*n)))])
                    keep=[c for c in held if c in hold]
                    new=[c for c in r if c in buy and c not in keep] if s is None else [c for c in ks if c in buy and c not in keep]
                    held=keep+new; return held
                return run_picks(forms,pf,seed=sd)
            return fn
        save('vm-buffer', {'family':'vm-buffer','slice':'broad-universe','host':'W04 annual, NMV 10% buy / 20% hold bands on broad V+M ranking (variable count)', **with_placebos(make())})
    elif which in ('trendgate','panicgate','volscale'):
        slug={'trendgate':'vm-trendgate','panicgate':'vm-panicgate','volscale':'vm-volscale'}[which]
        def fn(forms,sd): return overlay_run(forms, which, seed=sd)
        save(slug, {'family':slug,'slice':'broad-universe','host':'W04 annual top-5 V+M host + monthly overlay', **with_placebos(fn)})
    elif which=='winners':
        def fn(forms,sd):
            def pf_vm(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'vm'); return r[:5]
                rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            def pf_mom(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'mom'); return r[:5]
                rng=random.Random(s*7919+F+13); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            a=run_picks(forms,pf_vm,seed=sd,start_cash=50.0); b=run_picks(forms,pf_mom,seed=sd,start_cash=50.0)
            # merge curves month by month (same months)
            curve=[[m, round(va+vb,4)] for (m,va),(_,vb) in zip(a['curve'],b['curve'])]
            peak=100.0; maxdd=0.0
            for _,v in curve: peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0
            return {'final':round(curve[-1][1],2) if curve else 100.0,'max_dd_pct':round(maxdd*100,2),
                    'costs':round(a['costs']+b['costs'],2),'orders':a['orders']+b['orders'],'curve':curve,
                    'sleeve_vm_final':a['final']*2,'sleeve_mom_final':b['final']*2,'spy_final_same_window':a['spy_final_same_window']}
        save('winners-blend', {'family':'winners-blend','slice':'broad-universe','host':'W04 annual: 50/50 broad V+M top-5 + broad momentum-only top-5, split rebalanced at each annual formation (primary rebalances each January)', **with_placebos(fn)})
    elif which=='switch':
        # Switch A: blend first half, champion second half (formations split 2017-2020 / 2021-2025 on FULL; era roads split at midpoint formation)
        def blend_run(forms,sd,start=100.0):
            def pf_vm(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'vm'); return r[:5]
                rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            def pf_mom(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'mom'); return r[:5]
                rng=random.Random(s*7919+F+13); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            a=run_picks(forms,pf_vm,seed=sd,start_cash=start/2); b=run_picks(forms,pf_mom,seed=sd,start_cash=start/2)
            curve=[[m, round(va+vb,4)] for (m,va),(_,vb) in zip(a['curve'],b['curve'])]
            return {'final':curve[-1][1] if curve else start,'curve':curve,'costs':a['costs']+b['costs'],'orders':a['orders']+b['orders'],'spy':a['spy_final_same_window']}
        def fn(forms,sd):
            mid=len(forms)//2; first,second=forms[:mid],forms[mid:]
            b1=blend_run(first,sd,100.0)
            def pf(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'vm'); return r[:5]
                rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            b2=run_picks(second,pf,seed=sd,start_cash=b1['final'])
            curve=b1['curve']+b2['curve']
            peak=100.0; maxdd=0.0
            for _,v in curve: peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0
            return {'final':b2['final'],'max_dd_pct':round(maxdd*100,2),'costs':round(b1['costs']+b2['costs'],2),
                    'orders':b1['orders']+b2['orders'],'curve':curve,'switch_at_formation':second[0] if second else None,
                    'spy_final_same_window':b2['spy_final_same_window']}
        save('switch-blend-to-champion', {'family':'switch-blend-to-champion','slice':'broad-universe','host':'W04 annual: Switch A — broad winners-blend first half of formations, broad champion V+M top-5 second half', **with_placebos(fn)})
    elif which=='plustrend':
        # DBMF monthly returns from primary data file
        raw=json.load(open(os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/vm-plus-trend/data/DBMF.json')))
        res=raw['chart']['result'][0]; ts=res['timestamp']; cl=res['indicators']['quote'][0]['close']
        import datetime
        monthly={}
        for t,c in zip(ts,cl):
            if c is None: continue
            d=datetime.datetime.utcfromtimestamp(t); monthly[ym(d.year,d.month)]=c
        mkeys=sorted(monthly)
        def dbmf_curve(forms):
            ms=all_months(forms); out=[]; prev=None; val=50.0
            start_key=ym(forms[0],6)
            base=monthly.get(start_key)
            last=base
            for mm in ms:
                cur=monthly.get(mm, last)
                if cur and last: val*= cur/last
                last=cur if cur else last
                out.append([mm,round(val,4)])
            return out
        def fn(forms,sd):
            def pf(F,s):
                pool=pool_for(F)
                if s is None: r,_,_=ranked(F,'vm'); return r[:5]
                rng=random.Random(s*7919+F); ks=list(pool.keys()); rng.shuffle(ks); return ks[:5]
            a=run_picks(forms,pf,seed=sd,start_cash=50.0); b=dbmf_curve(forms)
            if sd is not None: b=[[m,50.0] for m,_ in b]  # placebo applies to VM sleeve only; trend sleeve held fixed (labeled)
            curve=[[m, round(va+vb,4)] for (m,va),(_,vb) in zip(a['curve'],b)]
            peak=100.0; maxdd=0.0
            for _,v in curve: peak=max(peak,v); maxdd=max(maxdd,1-v/peak) if peak else 0
            return {'final':round(curve[-1][1],2) if curve else 100.0,'max_dd_pct':round(maxdd*100,2),
                    'costs':a['costs'],'orders':a['orders'],'curve':curve,'sleeve_vm_final':a['final']*2,
                    'sleeve_dbmf_final_x2':round(b[-1][1]*2,2) if b else None,'spy_final_same_window':a['spy_final_same_window']}
        # DBMF inception May 2019: only CONT-era and VAL-era roads are honest
        out={}
        for name,forms in [('CONT_era_2019_2025',ROADS['CONT_era_2019_2025']),('VAL_era_2023_2025',ROADS['VAL_era_2023_2025'])]:
            r=fn(forms,None); twins=[fn(forms,s)['final'] for s in range(1,21)]
            out[name]=r; out[name+'_placebo_finals']=twins; out[name+'_placebos_beaten']=sum(1 for t in twins if r['final']>t)
            out[name+'_placebo_median']=round(statistics.median(twins),2); out[name+'_period_stats']=period_stats(r['curve'])
            print(name, r['final'], 'spy', r.get('spy_final_same_window'), flush=True)
        save('vm-plus-trend', {'family':'vm-plus-trend','slice':'broad-universe','host':'W04 annual broad V+M top-5 sleeve (50) + DBMF sleeve (50), no annual split rebalance beyond formation chaining (labeled)', **out})
