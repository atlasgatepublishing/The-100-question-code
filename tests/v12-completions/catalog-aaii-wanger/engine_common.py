import pandas as pd, numpy as np, json, os
BASE=os.path.dirname(os.path.abspath(__file__))
def monthly_prices():
    piv=pd.read_csv(f'{BASE}/monthly_parquet.csv', index_col=0, parse_dates=True)
    piv.index=piv.index.to_period('M').to_timestamp('M')
    out={c:piv[c].dropna() for c in piv.columns}
    import glob
    for f in glob.glob(f'{BASE}/px_*.json'):
        t=os.path.basename(f)[3:-5]
        bars=json.load(open(f))
        s=pd.Series({pd.Timestamp(d):v for d,v in bars})
        m=s.resample('M').last().dropna()
        m.index=m.index.to_period('M').to_timestamp('M')
        out[t]=m.combine_first(out[t]) if t in out else m
    return out
def fred_monthly(name):
    p=f'/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-aronson-cn-extremes-debt/data/{name}.csv'
    d=pd.read_csv(p, parse_dates=[0]); d.columns=['date','v']
    d=d.set_index('date')['v']; m=d.resample('M').last(); m.index=m.index.to_period('M').to_timestamp('M'); return m
def shiller():
    d=pd.read_csv('/home/hatch/workspace/stock-app/backtests/v10-retest/cape-timing/data/shiller_monthly_reference.csv')
    d['date']=pd.PeriodIndex(d['month'],freq='M').to_timestamp('M')
    return d.set_index('date')
def cash_ret(prices):
    if 'BIL' in prices:
        r=prices['BIL'].pct_change()
    else: r=None
    y=fred_monthly('DGS3MO')/100/12
    return y if r is None else r.combine_first(y)
ROADS={'LONG':('2010-01-01','2026-10-31'),'DECADE':('2016-01-01','2026-10-31'),'CONT':('2019-01-01','2026-10-31'),'VAL':('2023-01-01','2026-10-31')}
def period_stats(eq):
    r=eq.pct_change().dropna()
    if len(r)==0: return {}
    ls=cur=0
    for x in r:
        cur=cur+1 if x<=0 else 0; ls=max(ls,cur)
    run_max=eq.cummax(); below=(eq<run_max-1e-9)
    lb=cur=0
    for x in below:
        cur=cur+1 if x else 0; lb=max(lb,cur)
    dd=(eq/run_max-1).min()
    return {'n_periods':int(len(r)),'share_positive':round(float((r>0).mean()),3),'median_period':round(float(r.median()),4),
            'mean_period_secondary':round(float(r.mean()),4),'best':round(float(r.max()),4),'worst':round(float(r.min()),4),
            'longest_losing_streak':int(ls),'longest_below_high_months':int(lb),'max_dd':round(float(dd),4)}
def simulate(prices, signal_fn, road, house=False, cost_rate=0.001, placebo_seed=None, rng_assets=None, borrow_rate=0.0):
    start,end=ROADS[road]; start=pd.Timestamp(start); end=pd.Timestamp(end)
    idx=prices['SPY'].index; idx=idx[(idx>=start)&(idx<=end)]
    cr=cash_ret(prices)
    rng=np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq=100.0; curve={}; weights={}; total_cost=0.0
    halted_until=-1; restarts=0; halted_forever=False
    months=list(idx)
    for i,t in enumerate(months):
        curve[t]=eq
        if i==len(months)-1: break
        t1=months[i+1]
        if house and eq<=85.0 and not halted_forever:
            if restarts>=1: halted_forever=True
            else: restarts+=1; halted_until=i+3
        in_halt = house and (i<halted_until or halted_forever)
        if in_halt: new_w={}
        elif rng is not None:
            assets=rng_assets; k=int(rng.integers(1,len(assets)+1))
            pick=rng.choice(assets,size=k,replace=False); w=rng.dirichlet(np.ones(k))
            new_w={a:float(x) for a,x in zip(pick,w)}
        else:
            new_w=signal_fn(t, prices, cr)
            new_w={k:float(v) for k,v in new_w.items() if abs(v)>1e-9}
        allk=set(weights)|set(new_w)
        turn=sum(abs(new_w.get(k,0)-weights.get(k,0)) for k in allk)
        c=eq*turn*cost_rate; total_cost+=c; eq-=c
        crv=cr.get(t1,0.0) if t1 in cr.index else 0.0
        if crv is None or pd.isna(crv): crv=0.0
        ret=(1-sum(new_w.values()))*crv
        for k,w in new_w.items():
            s=prices[k]
            if t in s.index and t1 in s.index: ret+=w*(s[t1]/s[t]-1)
            else: ret+=w*crv
        eq*=(1+ret-borrow_rate/12*sum(abs(v) for v in new_w.values() if v<0)); weights=new_w
    return pd.Series(curve), total_cost
