#!/usr/bin/env python3
"""hunt-price-delay — frozen SPEC-FROZEN.md. Hou-Moskowitz D1 (primary),
D2/D3 siblings. Annual July formation on trailing-year daily returns vs SPY:
D1 = 1 - R2(restricted: contemporaneous only)/R2(unrestricted: lags 0..4).
Long-only top-decile basket (program adaptation), EW, held 12 months,
monthly marks. Universe = program daily-bar stack (154 pxfull names excl.
SPY) — SURVIVORSHIP FENCE: current large-cap list, flatters, printed.
Costs 0.10%/side, full-turnover each July (documented). House = v9 floor at
monthly marks (breach -> cash to next formation, one restart; 2nd -> end).
Placebos: 20 seeds random eligible names per July, same count. Simulation only."""
import json, os, time, random, statistics as st
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__))
DATA=os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST=0.001

def load(t):
    j=json.load(open(os.path.join(DATA,f"pxfull_{t}.json")))
    r=j["chart"]["result"][0]; ts=r["timestamp"]; adj=r["indicators"]["adjclose"][0]["adjclose"]
    out={}
    for i,x in enumerate(ts):
        if adj[i] is None: continue
        out[time.strftime("%Y-%m-%d", time.gmtime(x))]=adj[i]
    return out
tickers=sorted(f[7:-5] for f in os.listdir(DATA) if f.startswith("pxfull_"))
tickers.remove("SPY")
px={t: load(t) for t in tickers}; spy=load("SPY")
all_dates=sorted(spy)
didx={d:i for i,d in enumerate(all_dates)}
spy_ret=np.zeros(len(all_dates))
sp=np.array([spy[d] for d in all_dates])
spy_ret[1:]=sp[1:]/sp[:-1]-1

def measures(F):
    """Formation July F: trailing window Jul(F-1)..Jun(F). Returns {t:(D1,D2,D3)}."""
    lo=didx.get(f"{F-1}-07-01"); 
    cand=[d for d in all_dates if f"{F-1}-07-01"<=d<=f"{F}-06-30"]
    if not cand: return {}
    i0=didx[cand[0]]; i1=didx[cand[-1]]
    m=spy_ret[i0:i1+1]
    X=np.column_stack([np.ones(len(m))]+[np.roll(m,k) for k in range(5)])
    X[:4,1:]=0.0  # lags unavailable at window head: zero-fill (documented)
    Xr=X[:,:2]
    out={}
    for t in tickers:
        s=px[t]
        ys=[]; ok=True
        prev=None
        # build returns aligned to cand dates
        closes=[]
        for d in cand:
            if d not in s: ok=False; break
            closes.append(s[d])
        if not ok or len(closes)<200: continue
        closes=np.array(closes); r=np.zeros(len(closes)); r[1:]=closes[1:]/closes[:-1]-1
        y=r
        try:
            bu, *_ = np.linalg.lstsq(X, y, rcond=None)
            br, *_ = np.linalg.lstsq(Xr, y, rcond=None)
        except Exception: continue
        def r2(beta):
            res=y-X@beta if len(beta)==6 else y-Xr@beta
            ss=np.sum(res**2); tt=np.sum((y-y.mean())**2)
            return 1-ss/tt if tt>0 else 0.0
        r2u=r2(bu); r2r=r2(br)
        if r2u<=0.02: continue
        d1=1-r2r/r2u
        betas=bu[1:]; denom=np.sum(betas)
        d2= np.sum([k*betas[k+1] for k in range(4)])/denom if denom!=0 else None
        # D3: t-stats of lagged betas
        res=y-X@bu; dof=len(y)-6
        if dof<=0: continue
        s2=np.sum(res**2)/dof
        try: cov=s2*np.linalg.inv(X.T@X)
        except Exception: continue
        se=np.sqrt(np.diag(cov)); tst=bu/se
        den3=np.sum(tst[1:])
        d3= np.sum([k*tst[k+1] for k in range(4)])/den3 if den3!=0 else None
        out[t]=(d1,d2,d3)
    return out

# precomputed month-end closes: ME[t][ym] = adjclose on last trading day of month
ME={}
for t,s in px.items():
    d={}
    for dt,v in s.items(): d[dt[:7]]=v
    ME[t]=d

def month_marks(basket, F):
    months=[]
    y,m=F,7
    while (y,m)<(F+1,7):
        months.append(f"{y:04d}-{m:02d}"); m+=1
        if m>12: y,m=y+1,1
    marks=[]
    for mm in months:
        vals=[]
        for t in basket:
            v=ME[t].get(mm)
            if v is None:
                prev=[x for x in ME[t] if x<=mm]
                v=ME[t][max(prev)] if prev else None
            vals.append(v)
        marks.append((mm+"-01", vals))
    return marks

def run_road(form_years, sig_idx, count, house=False, placebo_seed=None):
    eq=100.0; curve=[]; restarts=0; dead=False; halt_until=None
    rng=random.Random(placebo_seed) if placebo_seed is not None else None
    for F in form_years:
        meas=measures(F)
        if not meas: continue
        elig=sorted(meas, key=lambda t:-meas[t][sig_idx])
        k = max(1,len(elig)//10) if count=="ALL" else min(count,len(elig))
        if rng: basket=rng.sample(elig, k)
        else: basket=elig[:k]
        marks=month_marks(basket, F)
        if not marks: continue
        base={t: marks[0][1][i] for i,t in enumerate(basket) if marks[0][1][i]>0}
        basket=[t for t in basket if t in base]
        if not basket: continue
        eq*= (1-COST)  # buy side
        start_eq=eq
        frozen=False
        for d, vals in marks[1:]:
            v=np.mean([vals[i]/base[t] for i,t in enumerate(basket)])
            cur=start_eq*v
            curve.append((d, round(cur,4)))
            if house and not dead and cur<=85.0:
                eq=cur*(1-COST); dead=True; frozen=True
                curve[-1]=(d, round(eq,4)); break
        if frozen: 
            # cash to road end
            for F2 in form_years:
                pass
            break
        eq=curve[-1][1]*(1-COST) if curve else eq
    return round(eq,2), curve

def monthly_stats(curve):
    marks={}
    for d,e in curve: marks[d[:7]]=e
    ks=sorted(marks); rets=[marks[b]/marks[a]-1 for a,b in zip(ks,ks[1:])]
    if not rets: return {}
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    peak=-1; last=0; longest=0
    for i,k in enumerate(ks):
        if marks[k]>=peak: peak=marks[k]; last=i
        longest=max(longest,i-last)
    return dict(periods=len(rets),share_positive=round(sum(1 for r in rets if r>0)/len(rets),3),
        median=round(st.median(rets),4),best=round(max(rets),4),worst=round(min(rets),4),
        mean_secondary=round(st.mean(rets),4),longest_losing_streak=streak,longest_between_highs_months=longest)

ROADS={"LONG":list(range(2010,2026)),"DECADE":list(range(2016,2026)),"CONT":list(range(2019,2026)),"VAL":list(range(2023,2026))}
out={"family":"hunt-price-delay","universe_n":len(tickers),"roads":{},"grid":{}}
meas_cache={F: measures(F) for F in range(2010,2026)}
def run_road2(form_years, sig_idx, count, house=False, placebo_seed=None):
    global measures
    _m=measures; 
    return run_road(form_years, sig_idx, count, house, placebo_seed)
# monkeypatch measures to cache
_orig=measures
measures=lambda F: meas_cache[F]
for rn, fy in ROADS.items():
    f,curve=run_road(fy,0,"ALL")
    fh,_=run_road(fy,0,"ALL",house=True)
    pls=[]
    for s in range(20):
        pf,_=run_road(fy,0,"ALL",placebo_seed=9000+s); pls.append(pf)
    # SPY bar over same span: Jul of first formation to Jun of last+1
    a=f"{fy[0]}-07-01"; b=f"{fy[-1]+1}-06-30"
    sa=[spy[d] for d in all_dates if a<=d<=b]
    bar=round(100*(1-COST)*(sa[-1]/sa[0])*(1-COST),2)
    out["roads"][rn]=dict(native_final=f, house_final=fh, SPY_bar=bar, placebo_finals=pls,
        placebo_beaten=sum(1 for x in pls if f>x), monthly=monthly_stats(curve), curve=curve)
    print(rn,"D1 decile NAT",f,"HOUSE",fh,"SPY",bar,"plbeat",out["roads"][rn]["placebo_beaten"])
for si, nm in [(1,"D2"),(2,"D3")]:
    out[f"sibling_{nm}"]={}
    for rn, fy in ROADS.items():
        f,_=run_road(fy,si,"ALL"); out[f"sibling_{nm}"][rn]=f
    print(nm, out[f"sibling_{nm}"])
# holdings grid on D1
os.makedirs(os.path.join(HERE,"grid"), exist_ok=True)
grid={}
for cnt in [1,2,3,5,8,10,15,20,30,"ALL"]:
    grid[str(cnt)]={}
    for rn, fy in ROADS.items():
        f,_=run_road(fy,0,cnt); fh,_=run_road(fy,0,cnt,house=True)
        pls=[run_road(fy,0,cnt,placebo_seed=9000+s)[0] for s in range(20)]
        grid[str(cnt)][rn]=dict(native_final=f, house_final=fh, placebo_beaten=sum(1 for x in pls if f>x), placebo_finals=pls)
    print("grid",cnt, {rn: grid[str(cnt)][rn]["native_final"] for rn in ROADS})
out["grid"]=grid
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
json.dump(grid, open(os.path.join(HERE,"grid","grid_results.json"),"w"), indent=1)
