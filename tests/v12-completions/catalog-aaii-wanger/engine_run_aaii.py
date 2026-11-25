import sys, json, numpy as np, pandas as pd, os
HERE=os.path.dirname(os.path.abspath(__file__))
# ---- load frames ----
def frame(concept, year):
    p=f'{HERE}/frames/{concept}_{year}.json'
    if not os.path.exists(p): return {}
    return {int(k):v for k,v in json.load(open(p)).items()}
tk=json.load(open(f'{HERE}/company_tickers.json'))
cik2ticker={int(v['cik_str']):v['ticker'] for v in tk.values()}
def fdict(concept, year):
    return {cik2ticker[c]:v for c,v in frame(concept,year).items() if c in cik2ticker}
def eps_approx(year):
    ni=fdict('NetIncomeLoss',year); sh=fdict('CommonStockSharesOutstanding',year)
    return {t: ni[t]/sh[t] for t in ni if t in sh and sh[t]>0}
def revenue(year):
    a=fdict('SalesRevenueNet',year); b=fdict('RevenueFromContractWithCustomerExcludingAssessedTax',year)
    a.update(b); return a
# ---- stock panels ----
MP=pd.read_csv(f'{HERE}/stock_monthly.csv', index_col=0, parse_dates=True)
MP.index=MP.index.to_period('M').to_timestamp('M')
YR=pd.read_csv(f'{HERE}/stock_yearly.csv')
JUNE={(r.ticker,r.yr):r.june_close for r in YR.itertuples()}
HIGH={(r.ticker,r.yr):r.high for r in YR.itertuples()}
def basket_curve(members_by_form, start_form=2010, end_form=2025, reequal=True):
    """members_by_form: {formation_year: [tickers]}; hold Jul Y..Jun Y+1."""
    eq=100.0; curve={}
    months=[m for m in MP.index if pd.Timestamp(f'{start_form}-07-01')<=m<=pd.Timestamp(f'{end_form+1}-06-30')]
    weights={}
    for m in months:
        curve[m]=eq
        if m.month==7 and m.year in members_by_form:
            mem=members_by_form[m.year]
            weights={t:1/len(mem) for t in mem} if mem else {}
        if not weights: continue
        nxt=MP.index[MP.index.get_loc(m)+1] if MP.index.get_loc(m)+1<len(MP.index) else None
        if nxt is None: break
        tot=0.0; neww={}
        for t,w in weights.items():
            alive=False
            if t in MP.columns and m in MP.index and nxt in MP.index:
                p0=MP.at[m,t]; p1=MP.at[nxt,t]
                if pd.notna(p0) and pd.notna(p1) and p0>0:
                    r=p1/p0-1; tot+=w*r; neww[t]=w*(1+r); alive=True
            if not alive: tot+=w*(-1.0)  # vanished -> written to zero once, then removed
        eq*=(1+tot)
        if reequal and neww:
            tw=sum(neww.values()); weights={t:1/len(neww) for t in neww} if tw>0 else {}
        if not reequal:
            s=sum(neww.values()); weights={t:v/s for t,v in neww.items()} if s>0 else {}
    return pd.Series(curve)

# ---- merge fetched candidate tapes ----
import glob as _glob
for _f in _glob.glob(f'{HERE}/aaii_px/*.json'):
    _t=os.path.basename(_f)[:-5]
    _bars=json.load(open(_f))
    if len(_bars)<100: continue
    _df=pd.DataFrame(_bars, columns=['date','adj','close','high'])
    _df['date']=pd.to_datetime(_df['date'])
    _m=_df.set_index('date')['adj'].resample('M').last()
    _m.index=_m.index.to_period('M').to_timestamp('M')
    if _t in MP.columns: MP[_t]=_m.combine_first(MP[_t])
    else: MP[_t]=_m
    _j=_df[_df['date'].dt.month==6].groupby(_df['date'].dt.year).tail(1)
    for _r in _j.itertuples(): JUNE[(_t,int(_r.date.year))]=_r.close
    for _y,_g in _df.groupby(_df['date'].dt.year): HIGH[(_t,int(_y))]=_g['high'].max()

from common import period_stats
def road_final(curve, road):
    st,en={'LONG':('2010-07-01','2026-06-30'),'DECADE':('2016-07-01','2026-06-30'),'CONT':('2019-07-01','2026-06-30'),'VAL':('2023-07-01','2026-06-30')}[road]
    s=curve[(curve.index>=st)&(curve.index<=en)]
    if len(s)<2: return None, {}
    reb=100*s/s.iloc[0]
    return round(float(reb.iloc[-1]),2), period_stats(reb)
# ================= WANGER =================
def wanger_members(Y):
    rev={y:revenue(y) for y in (Y-1,Y-2,Y-3,Y-4)}
    liab=fdict('Liabilities',Y-1); assets=fdict('Assets',Y-1); shares=fdict('CommonStockSharesOutstanding',Y-1)
    eps={y:eps_approx(y) for y in (Y-1,Y-6)}
    opinc=fdict('OperatingIncomeLoss',Y-1)
    # universe medians
    la=[]; gr=[]
    for t in rev[Y-1]:
        if t in liab and t in assets and assets[t]>0: la.append(liab[t]/assets[t])
        if t in rev[Y-3] and rev[Y-3][t]>0: gr.append(rev[Y-1][t]/rev[Y-3][t]-1)
    med_la=np.median(la) if la else 1.0; med_gr=np.median(gr) if gr else 0.0
    out=[]
    for t in rev[Y-1]:
        if t not in rev[Y-2] or t not in rev[Y-3]: continue
        if not (rev[Y-1][t]>rev[Y-2][t]>rev[Y-3][t]>0): continue
        if rev[Y-1][t]/rev[Y-3][t]-1 <= med_gr: continue
        if t not in liab or t not in assets or assets[t]<=0: continue
        if liab[t]/assets[t] > med_la: continue
        if t not in shares or (t,Y) not in JUNE or pd.isna(JUNE.get((t,Y))): continue
        cap=shares[t]*JUNE[(t,Y)]
        if not (100e6 <= cap <= 2e9): continue
        if t not in eps[Y-1] or t not in eps[Y-6] or eps[Y-6][t] is None or eps[Y-1][t] is None: continue
        if eps[Y-1][t]<=0 or eps[Y-6][t]<=0: continue
        g5=(eps[Y-1][t]/eps[Y-6][t])**(1/5)-1
        if g5<=0: continue
        pe=JUNE[(t,Y)]/eps[Y-1][t]
        if pe/(g5*100) > 1.0: continue
        if t not in opinc or opinc[t]<=0: continue
        out.append(t)
    return out
# ================= WEISS =================
def weiss_members(Y):
    eps={y:eps_approx(y) for y in range(Y-7,Y)}
    pay={y:fdict('PaymentsOfDividendsCommonStock',y) for y in range(Y-7,Y)}
    shares={y:fdict('CommonStockSharesOutstanding',y) for y in range(Y-7,Y)}
    ac=fdict('AssetsCurrent',Y-1); lc=fdict('LiabilitiesCurrent',Y-1)
    ltd=fdict('LongTermDebtNoncurrent',Y-1); dc1=fdict('DebtCurrent',Y-1); dc2=fdict('LongtermBorrowingsCurrent',Y-1)
    eq_=fdict('StockholdersEquity',Y-1); ni=fdict('NetIncomeLoss',Y-1)
    out=[]
    cand=set.intersection(*[set(pay[y]) for y in range(Y-7,Y)])
    for t in cand:
        dps=[]
        ok=True
        for y in range(Y-7,Y):
            if t not in shares[y] or shares[y][t]<=0 or pay[y][t]<=0: ok=False; break
            dps.append(pay[y][t]/shares[y][t])
        if not ok: continue
        inc=sum(1 for i in range(1,7) if dps[i]>dps[i-1])
        dec=any(dps[i]<dps[i-1] for i in range(1,7))
        if inc<3 or dec: continue
        if t not in eps[Y-1]: continue
        einc=sum(1 for y in range(Y-6,Y) if t in eps[y] and t in eps[y-1] and eps[y][t] is not None and eps[y-1][t] is not None and eps[y][t]>eps[y-1][t])
        if einc<4: continue
        if shares[Y-1][t] < 5e6: continue
        if (t,Y) not in JUNE or pd.isna(JUNE.get((t,Y))): continue
        price=JUNE[(t,Y)]
        # avg high yield
        ahy=[]
        for i,y in enumerate(range(Y-7,Y)):
            h=HIGH.get((t,y))
            if h is None or pd.isna(h): ok=False; break
            ahy.append(dps[i]/h)
        if not ok or not ahy: continue
        cur_yield=dps[-1]/price
        if cur_yield < 0.9*np.mean(ahy): continue
        if t not in ac or t not in lc or lc[t]<=0 or ac[t]/lc[t] < 2.0: continue
        if t not in eq_ or eq_[t]<=0: continue
        debt=ltd.get(t,0)+(dc1.get(t,0) or 0)+(dc2.get(t,0) or 0)
        if debt/eq_[t] > 0.5: continue
        if t not in ni or ni[t]<=0 or pay[Y-1][t]/ni[t] > 0.5: continue
        out.append(t)
    return out
def run_screen(members_fn, name):
    mem={Y:members_fn(Y) for Y in range(2010,2026)}
    counts={Y:len(v) for Y,v in mem.items()}
    print(name,'counts',counts,flush=True)
    curve=basket_curve(mem)
    out={'counts':counts,'roads':{},'members_sample':{Y:mem[Y][:10] for Y in range(2010,2026,5)}}
    for road in ('LONG','DECADE','CONT','VAL'):
        f,st=road_final(curve,road); out['roads'][road]={'final':f,'stats':st}
    # placebos: random same-count from tickers with any membership eligibility proxy = tickers in stock_monthly with june price
    rng=np.random.default_rng(0)
    all_t=[t for t in MP.columns if (t,2015) in JUNE]
    for road in ('LONG','CONT'):
        beats=0; finals=[]
        for seed in range(20):
            r=np.random.default_rng(seed)
            pm={}
            for Y in range(2010,2026):
                if counts[Y]==0: pm[Y]=[]; continue
                july=pd.Timestamp(f'{Y}-07-31')
                elig=[t for t in all_t if t in MP.columns and july in MP.index and pd.notna(MP.at[july,t])]
                pm[Y]=list(r.choice(elig,size=min(counts[Y],len(elig)),replace=False)) if elig else []
            pc=basket_curve(pm)
            f,_=road_final(pc,road); finals.append(f)
            if out['roads'][road]['final'] and f and out['roads'][road]['final']>f: beats+=1
        out.setdefault('placebos',{})[road]={'beats':beats,'median_placebo':round(float(np.median([x for x in finals if x])),2)}
    # counts grid: rank by formation-year signal handled outside; here ALL only + topN by june price liquidity proxy skipped
    out['curve']={str(k.date()):round(float(v),4) for k,v in curve.items()}
    return out
if __name__=='__main__':
    which=sys.argv[1]
    res=run_screen(wanger_members,'wanger') if which=='wanger' else run_screen(weiss_members,'weiss')
    json.dump(res, open(f'{HERE}/res_{which}.json','w'), indent=1)
    print(which, res['roads'], res.get('placebos'))
