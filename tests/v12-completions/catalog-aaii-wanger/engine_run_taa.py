import sys, json, numpy as np, pandas as pd, os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from common import *
P=monthly_prices()
def ret(t, tk, m):
    s=P[tk]
    if t not in s.index: return None
    idx=s.index.get_loc(t)
    if idx<m: return None
    return s.iloc[idx]/s.iloc[idx-m]-1
def avg_ret(t, tk, months):
    vals=[ret(t,tk,m) for m in months]
    if any(v is None for v in vals): return None
    return float(np.mean(vals))
def sma_ok(t, tk, m=10):
    s=P[tk]
    if t not in s.index: return None
    idx=s.index.get_loc(t)
    if idx<m-1: return None
    return bool(s.iloc[idx] > s.iloc[idx-m+1:idx+1].mean())
def adm(t, P_, cr):
    a=avg_ret(t,'SPY',[1,3,6]); b=avg_ret(t,'SCZ',[1,3,6])
    if a is None or b is None: return {}
    if max(a,b)<=0:
        r1={k:ret(t,k,1) for k in ('TLT','TIP')}
        if any(v is None for v in r1.values()): return {'TLT':1.0}
        return {max(r1,key=r1.get):1.0}
    return {'SPY':1.0} if a>=b else {'SCZ':1.0}
def carlson(t,P_,cr):
    moms={}
    for a in ['TLT','GLD','DBC','UUP']:
        m=avg_ret(t,a,[1,3,6,12])
        if m is None: return {}
        moms[a]=m
    bm=avg_ret(t,'BIL',[1,3,6,12])
    if bm is None: bm=0.0
    ranked=sorted(moms, key=moms.get, reverse=True)
    w={}
    for a,wt in zip(ranked,[0.4,0.3,0.2,0.1]):
        if moms[a]<bm: w['SPY']=w.get('SPY',0)+wt
        else: w[a]=wt
    return w
SH=shiller(); D10=fred_monthly('DGS10'); D3=fred_monthly('DGS3MO')
SPYDIV=pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),'spy_div.csv'),index_col=0,parse_dates=True).iloc[:,0]
SPYDIV.index=SPYDIV.index.to_period('M').to_timestamp('M')
def choi(t,P_,cr):
    s=P['TIP']
    if t not in s.index: return {}
    idx=s.index.get_loc(t)
    if idx<15: return {}
    risk_on = bool(s.iloc[idx] > s.iloc[idx-12:idx].mean())
    if risk_on:
        spy=P['SPY']; si=spy.index.get_loc(t)
        if si<13: return {}
        div_ttm=SPYDIV.reindex(spy.index).fillna(0).iloc[si-13:si-1].sum()
        if div_ttm/spy.iloc[si-1] < 0.016: risk_on=False
        else:
            for k in range(7,16):
                tt=s.index[idx-k]
                if tt in D10.index and tt in D3.index and D10[tt] < D3[tt]-0.5: risk_on=False
    if risk_on:
        a=avg_ret(t,'QQQ',[1,3,6,9,12]); b=avg_ret(t,'SCHD',[1,3,6,9,12])
        if a is None or b is None: return {}
        return {'QQQ':1.0} if a>=b else {'SCHD':1.0}
    best=None; bestv=0.0
    for a in ['TLT','DBC']:
        s=P[a]
        if t not in s.index: continue
        i2=s.index.get_loc(t)
        if i2<6: continue
        v=s.iloc[i2]/s.iloc[i2-6:i2].mean()-1
        if v>bestv: bestv=v; best=a
    return {best:1.0} if best else {}
def clare(t, assets):
    inv={}
    for a in assets:
        s=P[a]
        if t not in s.index: return {}
        idx=s.index.get_loc(t)
        if idx<12: return {}
        vol=s.iloc[idx-12:idx+1].pct_change().std()
        if vol<=0 or np.isnan(vol): return {}
        inv[a]=1/vol
    tot=sum(inv.values()); w={}
    for a in assets:
        if sma_ok(t,a,10): w[a]=inv[a]/tot
    return w
def clare_us(t,P_,cr): return clare(t,['SPY','IWM','IEF','DBC','VNQ'])
def clare_global(t,P_,cr): return clare(t,['SPY','EFA','EEM','IEF','BWX','DBC','VNQ'])
def _z(series,t,minp=120):
    series=series.dropna()
    if t not in series.index: return None
    i=series.index.get_loc(t)
    if i<minp: return None
    h=series.iloc[i-minp:i]; sd=h.std()
    if sd==0 or np.isnan(sd): return None
    return (series.iloc[i]-h.mean())/sd
def baltussen(t,P_,cr):
    spread=(D10-D3)
    z1=_z(spread,t)
    if z1 is None: return {}
    z1=float(np.clip(z1,-1,1))
    e12=ret(t,'IEF',12); b12=ret(t,'BIL',12)
    if e12 is None or b12 is None: return {}
    s2=1.0 if e12-b12>0 else -1.0
    spy=P['SPY']; bil=P['BIL']
    common=spy.index.intersection(bil.index)
    ex=(spy.reindex(common)/spy.reindex(common).shift(12)-1)-(bil.reindex(common)/bil.reindex(common).shift(12)-1)
    z3=_z(ex,t)
    z4=_z(P['DBC'].pct_change(12),t)
    if z3 is None or z4 is None: return {}
    avg=np.mean([z1,s2,float(np.clip(-z3,-1,1)),float(np.clip(-z4,-1,1))])
    w=float((avg+1)/2)
    return {'IEF':w} if w>0.01 else {}
def sacevs_signals():
    sh=SH.copy(); sh['ey']=(sh['earnings_trailing']/sh['price'])*100
    ey=sh['ey'].shift(4)
    return {'term':(D10-D3),'credit':(fred_monthly('DBAA')-D10),'equity':(ey-D10)}
PREM=sacevs_signals(); ASSET={'term':'TLT','credit':'LQD','equity':'SPY'}
def sacevs(t,P_,cr,mode='best'):
    zs={}
    for k,s in PREM.items():
        s=s.dropna()
        if t not in s.index: return {}
        hist=s[(s.index>=pd.Timestamp('1989-03-31'))&(s.index<=t)]
        if len(hist)<24: return {}
        mu=hist.iloc[:-1].mean(); sd=hist.iloc[:-1].std()
        if sd==0 or np.isnan(sd): return {}
        zs[k]=(s[t]-mu)/sd
    pos={k:v for k,v in zs.items() if v>0}
    if not pos: return {}
    if mode=='best':
        k=max(pos,key=pos.get); return {ASSET[k]:1.0}
    tot=sum(pos.values()); return {ASSET[k]:v/tot for k,v in pos.items()}
def sacevs_best(t,P_,cr): return sacevs(t,P_,cr,'best')
def sacevs_weighted(t,P_,cr): return sacevs(t,P_,cr,'weighted')
SACEMS_UNI=['SPY','EFA','IWM','EEM','TLT','LQD','GLD','DBC','VNQ']
def sacems_topn(t,n):
    sc={}
    for a in SACEMS_UNI:
        v=avg_ret(t,a,[1,3,6,12])
        if v is None: return {}
        sc[a]=v
    top=sorted(sc,key=sc.get,reverse=True)[:n]
    return {a:1/n for a in top}
def sacevs_combined(t,P_,cr):
    a=sacevs_best(t,P_,cr); b=sacems_topn(t,2); w={}
    for k,v in a.items(): w[k]=w.get(k,0)+0.5*v
    for k,v in b.items(): w[k]=w.get(k,0)+0.5*v
    return w
COUNTRIES=['EWA','EWC','EWD','EWG','EWH','EWI','EWJ','EWK','EWL','EWN','EWO','EWP','EWQ','EWS','EWU','EWW','EWY','EWZ','EWT','EZA','FXI']
