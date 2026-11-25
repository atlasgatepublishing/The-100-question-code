import sys, json, numpy as np, pandas as pd, os
os.environ.setdefault('PYTHONPATH','/home/hatch/workspace/.pylibs')
HERE=os.path.dirname(os.path.abspath(__file__))
def load_daily():
    cache=f'{HERE}/daily_pivot.csv'
    if os.path.exists(cache):
        d=pd.read_csv(cache, index_col=0, parse_dates=True); return d
    df=pd.read_parquet("/home/hatch/workspace/stock-app/backtests/v12-completions/dividend-growth/data/prices_jb.parquet", columns=['date','ticker','adj_close','volume'])
    df['date']=pd.to_datetime(df['date'])
    df=df[df['date']>='2008-01-01']
    cnt=df.groupby('ticker')['adj_close'].count()
    vol=(df['adj_close']*df['volume']).groupby(df['ticker']).median()
    elig=cnt[(cnt>4200)].index
    top=vol[elig].nlargest(120).index
    piv=df[df.ticker.isin(top)].pivot(index='date',columns='ticker',values='adj_close').sort_index()
    piv.to_csv(cache)
    return piv
PX=load_daily()
def formations(px, start, end):
    # formation dates: every 6 months starting at first Jan/Jul month-end >= start
    dates=px.index
    starts=[d for d in dates if d>=start and d<=end and d.month in (1,7) and (dates[dates<=d][-1]==d)]
    # simpler: use month-end dates in Jan/Jul
    me=px.resample('ME').last().index
    fdates=[d for d in me if d>=pd.Timestamp(start) and d.month in (1,7)]
    return fdates
def run_pairs(start='2010-01-01', end='2026-10-30', n_pairs=5, thresh=2.0, house=False, placebo_seed=None, cost_rate=0.001, borrow=0.01):
    px=PX
    dates=px.index
    rng=np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    start=pd.Timestamp(start); end=pd.Timestamp(end)
    fdates=formations(px, start, end)
    eq=100.0; curve={}
    total_cost=0.0
    halted_until=None; restarts=0; halted_forever=False
    active=[]  # list of dicts {a,b,sd,pos:0/1/-1,end_idx}
    for fi,fd in enumerate(fdates):
        # formation window: 252 trading days ending at fd
        i_fd=dates.get_indexer([fd], method='nearest')[0]
        if i_fd<252: continue
        form=px.iloc[i_fd-252:i_fd+1]
        norm=form/form.iloc[0]
        norm=norm.dropna(axis=1)
        cols=list(norm.columns)
        if len(cols)<10: continue
        arr=norm.values
        # SSD matrix
        # (a-b)^2 sum = sum a^2 + sum b^2 -2 a.b
        sq=(arr**2).sum(axis=0)
        ssd=sq[:,None]+sq[None,:]-2*arr.T@arr
        np.fill_diagonal(ssd, np.inf)
        pairs=[]
        if rng is not None:
            allp=[(i,j) for i in range(len(cols)) for j in range(i+1,len(cols))]
            idxs=rng.choice(len(allp), size=min(n_pairs,len(allp)), replace=False)
            pairs=[allp[k] for k in idxs]
        else:
            flat=np.argsort(ssd, axis=None)
            used=set()
            for f in flat:
                i,j=divmod(int(f), len(cols))
                if i>=j: continue
                pairs.append((i,j))
                if len(pairs)>=n_pairs: break
        # trading window: next 126 trading days
        t_end=min(i_fd+126, len(dates)-1)
        pos={}  # pair idx -> direction (+1 long a short b if diff<0 ...)
        diffs={}
        for (i,j) in pairs:
            a=cols[i]; b=cols[j]
            d=form[a]/form[a].iloc[0]-form[b]/form[b].iloc[0]
            diffs[(a,b)]=d.std()
        open_pairs={}
        for di in range(i_fd+1, t_end+1):
            d=dates[di]
            if house:
                if eq<=85.0 and not halted_forever:
                    if restarts>=1: halted_forever=True
                    else: restarts+=1; halted_until=di+63
                if halted_forever or (halted_until is not None and di<halted_until):
                    # close all
                    for k in list(open_pairs): 
                        total_cost+=eq/n_pairs*cost_rate; del open_pairs[k]
                    curve[d]=eq; continue
            day_ret=0.0
            for (i,j) in pairs:
                a=cols[i]; b=cols[j]
                pa=px[a].iloc[di]/px[a].iloc[i_fd]; pb=px[b].iloc[di]/px[b].iloc[i_fd]
                diff=pa-pb; sd=diffs[(a,b)]
                alloc=eq/n_pairs
                if (a,b) not in open_pairs:
                    if abs(diff)>thresh*sd:
                        open_pairs[(a,b)]= -1 if diff>0 else 1  # +1 = long a/short b (diff negative)
                        total_cost+=alloc*cost_rate; eq-=alloc*cost_rate
                else:
                    dirn=open_pairs[(a,b)]
                    ra=px[a].iloc[di]/px[a].iloc[di-1]-1; rb=px[b].iloc[di]/px[b].iloc[di-1]-1
                    day_ret+= dirn*(ra-rb)*0.5/n_pairs
                    day_ret-= borrow/252*0.5/n_pairs
                    if (dirn==1 and diff>=0) or (dirn==-1 and diff<=0) or di==t_end:
                        total_cost+=alloc*cost_rate; eq-=alloc*cost_rate
                        del open_pairs[(a,b)]
            eq*=(1+day_ret)
            curve[d]=eq
    s=pd.Series(curve).sort_index()
    return s, total_cost
def stats_from_daily(s):
    m=s.resample('ME').last()
    return period_stats(m), round(float(m.iloc[-1]),2)
from common import period_stats
if __name__=='__main__':
    out={'roads':{},'placebos':{},'grid':{}}
    for road,(st,en) in {'LONG':('2010-01-01','2026-10-30'),'DECADE':('2016-01-01','2026-10-30'),'CONT':('2019-01-01','2026-10-30'),'VAL':('2023-01-01','2026-10-30')}.items():
        s,c=run_pairs(st,en,5,2.0)
        stt,fin=stats_from_daily(s)
        out['roads'][road]={'final':fin,'cost':round(c,2),'stats':stt,'curve':{str(k.date()):round(float(v),4) for k,v in s.resample('ME').last().items()}}
        sh,_=run_pairs(st,en,5,2.0,house=True)
        out['roads'][road+'_house']={'final':round(float(sh.resample('ME').last().iloc[-1]),2)}
        print(road, fin, stt, flush=True)
    for road in ('LONG','CONT'):
        st,en={'LONG':('2010-01-01','2026-10-30'),'CONT':('2019-01-01','2026-10-30')}[road]
        beats=0; finals=[]
        for seed in range(20):
            sp,_=run_pairs(st,en,5,2.0,placebo_seed=seed)
            finals.append(float(sp.resample('ME').last().iloc[-1]))
            if out['roads'][road]['final']>finals[-1]: beats+=1
        out['placebos'][road]={'beats':beats,'median_placebo':round(float(np.median(finals)),2)}
        print('placebo',road,beats, flush=True)
    for n in (1,2,3,5,8,10,15,20):
        s,_=run_pairs('2010-01-01','2026-10-30',n,2.0)
        out['grid'][f'pairs_{n}']={'final':round(float(s.resample('ME').last().iloc[-1]),2)}
    for th in (1.5,2.5):
        s,_=run_pairs('2010-01-01','2026-10-30',5,th)
        out['grid'][f'thresh_{th}']={'final':round(float(s.resample('ME').last().iloc[-1]),2)}
    s,_=run_pairs('2010-01-01','2026-10-30',20,2.0)
    out['grid']['pairs_20_top20_published_alt']={'final':round(float(s.resample('ME').last().iloc[-1]),2)}
    json.dump(out, open(f'{HERE}/res_pairs.json','w'), indent=1)
    print('grid', out['grid'])
