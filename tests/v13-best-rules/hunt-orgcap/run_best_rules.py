#!/usr/bin/env python3
"""hunt-orgcap v13 BEST RULES — frozen BEST-RULES-SPEC.md.
Published OrgCap construction EXACTLY (OC0=4*xsga first year,
OC_t=0.85*OC_{t-1}+xsga_t/deflator[WB GDP deflator, named approx],
/assets, winsor 1%, FF17 z-scores). ONE deviation, frozen pre-run:
reporters-only eligibility (missing SG&A != zero spending; eligible
only if SG&A reported for signal FY). Long-only top quintile EW,
June formation FY-1 (6m lag), 12m hold, NO floor, tiered program
costs, vanished -> ZERO, 20-seed placebos. Roads DECADE/CONT/VAL
(June windows, as v12); LONG named gap (prices start 2016-01).
Simulation only."""
import json, os, random, statistics as st
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__))
V12=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-orgcap")
W04=os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
FR=os.path.join(V12,"data","frames")
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
sga={y:{int(k):v for k,v in loadj(os.path.join(FR,f"SGandA_{y}D.json")).items()} for y in range(2009,2026)}
assets={y:{int(k):v for k,v in loadj(os.path.join(W04,"frames",f"Assets_{y}I.json")).items()} for y in range(2009,2026)}
shares_f={y:{int(k):v for k,v in loadj(os.path.join(W04,"frames",f"Shares_{y}I.json")).items()} for y in range(2009,2026)}
defl={int(k):v for k,v in loadj(os.path.join(V12,"data","gdp_deflator_wb.json")).items()}
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
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap>=5e9: return 0.0010
    if cap>=1e9: return 0.0025
    return 0.0075
def ff17(sic):
    if 100<=sic<999: return 1
    if 1000<=sic<1299 or 1400<=sic<1499: return 2
    if 1300<=sic<1399: return 3
    if 1500<=sic<1799: return 4
    if 2000<=sic<2799: return 5
    if 2800<=sic<2829 or 2840<=sic<2899: return 6
    if 2830<=sic<2839 or 8000<=sic<8099: return 7
    if 2900<=sic<2999: return 8
    if 3000<=sic<3299: return 9
    if 3300<=sic<3399: return 10
    if 3400<=sic<3499: return 11
    if 3500<=sic<3599: return 12
    if 3600<=sic<3699: return 13
    if 3700<=sic<3799: return 14
    if 3800<=sic<3899: return 15
    if 4800<=sic<4899: return 16
    return 17
OC={}
for cik in cand:
    series={}; prev=None
    for y in range(2009,2026):
        x=sga[y].get(cik, 0.0)
        if x is None: x=0.0
        real=x/defl[y]*100.0
        if prev is None: cur=4.0*real
        else: cur=0.85*prev+real
        series[y]=cur; prev=cur
    OC[cik]=series
def signal(F):
    """FY=F-1. REPORTERS-ONLY: cik must have reported SG&A for FY."""
    y=F-1; raw={}; pool=0; reporters=0
    for cik,info in cand.items():
        sic=int(info.get("sic") or 0) if str(info.get("sic") or "0").isdigit() else 0
        if 6000<=sic<=6999: continue
        a=assets[y].get(cik)
        if not a or a<=0: continue
        pool+=1
        if cik not in sga[y] or sga[y][cik] is None: continue
        reporters+=1
        raw[cik]=OC[cik][y]/a
    if len(raw)<30: return {}, {}
    vals=np.array(list(raw.values()))
    lo,hi=np.percentile(vals,[1,99])
    raw={k:min(max(v,lo),hi) for k,v in raw.items()}
    by={}
    for k,v in raw.items():
        sic=int(cand[k].get("sic") or 0) if str(cand[k].get("sic") or "0").isdigit() else 0
        by.setdefault(ff17(sic),[]).append((k,v))
    z={}
    for ind, lst in by.items():
        if len(lst)<3: continue
        arr=np.array([v for _,v in lst]); mu, sd=arr.mean(), arr.std()
        if sd<=0: continue
        for k,v in lst: z[k]=(v-mu)/sd
    diag=dict(pool_with_assets=pool, reporters=reporters,
              nonreporter_share=round(1-reporters/pool,3) if pool else None, z_names=len(z))
    return z, diag
def ym(y,m): return f"{y:04d}-{m:02d}"
def cap_of(cik,F):
    sh=shares_f.get(F-1,{}).get(cik) or shares_f.get(F-2,{}).get(cik)
    s=px.get(cik)
    if not sh or not s: return None
    e=s.get(ym(F,6))
    if not e: return None
    return sh*e[1]*sf.get(cik,{}).get(F,1.0)
def run_road(form_years, placebo_seed=None):
    eq=100.0; curve=[(ym(form_years[0],6),100.0)]; rng=random.Random(placebo_seed) if placebo_seed is not None else None
    baskets={}
    for F in form_years:
        z,diag=signal(F)
        if not z: continue
        elig=[c for c in z if c in px and ym(F,6) in px[c]]
        elig.sort(key=lambda c:-z[c])
        k=max(1,len(elig)//5)
        basket=rng.sample(elig,k) if rng else elig[:k]
        baskets[str(F)]=k
        hold_months=[ym(F,m) for m in range(6,13)]+[ym(F+1,m) for m in range(1,7)]
        series={}
        for c in basket:
            s=px[c]; row=[]; lastbar=max(s) if s else None
            for mm in hold_months:
                if mm in s: row.append(s[mm][0])
                elif lastbar and mm>lastbar: row.append(0.0)
                else: row.append(None)
            series[c]=row
        basket=[c for c in basket if series[c][0]]
        if not basket: continue
        rates={c: cost_rate(cap_of(c,F)) for c in basket}
        w={c:(eq/len(basket))*(1-rates[c])/series[c][0] for c in basket}
        for j,mm in enumerate(hold_months):
            if j==0: continue
            cur=sum(w[c]*(series[c][j] if series[c][j] is not None else series[c][0]) for c in basket)
            curve.append((mm, round(cur,4)))
        eq=sum(w[c]*(series[c][-1] if series[c][-1] is not None else 0.0)*(1-rates[c]) for c in basket)
        curve[-1]=(hold_months[-1], round(eq,4))
    return round(eq,2), curve, baskets
def stats(curve):
    marks={}
    for d,e in curve: marks[d]=e
    ks=sorted(marks); vals=[marks[k] for k in ks]
    rets=[b/a-1 for a,b in zip(vals,vals[1:]) if a]
    peak=-1; mdd=0.0
    for v in vals:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0.0)
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    pk=-1; last=0; longest=0
    for i,v in enumerate(vals):
        if v>=pk: pk=v; last=i
        longest=max(longest,i-last)
    return dict(periods=len(rets), share_positive=round(sum(1 for r in rets if r>0)/len(rets),3) if rets else None,
        median_period=round(st.median(rets),4) if rets else None, best=round(max(rets),4) if rets else None,
        worst=round(min(rets),4) if rets else None, mean_secondary=round(st.mean(rets),4) if rets else None,
        longest_losing_streak=streak, longest_between_highs_months=longest, max_drawdown=round(mdd,4))
ROADS={"DECADE":list(range(2016,2026)),"CONT":list(range(2019,2026)),"VAL":list(range(2023,2026))}
CHAMP={"DECADE":667.35,"CONT":544.47,"VAL":288.05}
PUB={"DECADE":478.91,"CONT":289.76,"VAL":165.74}
out={"family":"hunt-orgcap","program":"v13-best-rules","spec":"BEST-RULES-SPEC.md (frozen pre-run)",
     "deviation_from_published":"reporters-only eligibility (missing SG&A excluded, not zero-filled)",
     "roads":{},"diagnostics":{},"LONG":"NOT RUN — broad price stack begins 2016-01; honest gap, named in spec"}
for F in range(2016,2026):
    _,dg=signal(F); out["diagnostics"][str(F)]=dg
for rn,fy in ROADS.items():
    f,curve,baskets=run_road(fy)
    pls=[run_road(fy,placebo_seed=8000+s)[0] for s in range(20)]
    a,b=ym(fy[0],6), ym(fy[-1]+1,6)
    sa=[spy[m] for m in months if a<=m<=b]
    bar=round(100*(1-0.001)*(sa[-1]/sa[0])*(1-0.001),2)
    out["roads"][rn]=dict(final=f, published_form_final=PUB[rn], champion_VM_for_scale=CHAMP[rn],
        SPY_same_window=bar, placebo_finals=pls, placebo_beaten=sum(1 for x in pls if f>x),
        placebo_median=round(st.median(pls),2), basket_sizes=baskets, stats=stats(curve), curve=curve,
        beats_champion_scale=f>CHAMP[rn])
    print(rn,"BEST-RULES",f,"PUB",PUB[rn],"SPY",bar,"plbeat",out["roads"][rn]["placebo_beaten"],"/20","maxDD",out["roads"][rn]["stats"]["max_drawdown"], flush=True)
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
print("WROTE results.json")
