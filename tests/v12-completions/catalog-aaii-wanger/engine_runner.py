import sys, json, numpy as np, pandas as pd, os
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
from common import *
from run_taa import *
P=monthly_prices()
class Hold:
    def __init__(self, fn, k): self.fn=fn; self.k=k; self.w=None; self.last=None; self.count=0
    def __call__(self, t, P_, cr):
        if self.last is not None and t<self.last: self.w=None; self.count=0
        self.last=t
        if self.w is None or self.count%self.k==0: self.w=self.fn(t,P_,cr)
        self.count+=1
        return self.w
def run_family(fn, placebo_assets, grid_cads=(3,6,12), extra_signals=None):
    out={'roads':{},'placebos':{},'grid':{}}
    for road in ('LONG','DECADE','CONT','VAL'):
        eq,cost=simulate(P, fn, road)
        out['roads'][road]={'final':round(float(eq.iloc[-1]),2),'cost':round(cost,2),'stats':period_stats(eq),'curve':{str(k.date()):round(float(v),4) for k,v in eq.items()}}
        eqh,costh=simulate(P, fn, road, house=True)
        out['roads'][road+'_house']={'final':round(float(eqh.iloc[-1]),2),'cost':round(costh,2),'stats':period_stats(eqh)}
    if placebo_assets:
        for road in ('LONG','CONT'):
            beats=0; finals=[]
            for seed in range(20):
                eqp,_=simulate(P, fn, road, placebo_seed=seed, rng_assets=placebo_assets)
                finals.append(float(eqp.iloc[-1]))
                if out['roads'][road]['final']>finals[-1]: beats+=1
            out['placebos'][road]={'beats':beats,'median_placebo':round(float(np.median(finals)),2)}
    for k in grid_cads:
        eq,_=simulate(P, Hold(fn,k), 'LONG')
        out['grid'][f'cadence_{k}m']={'final':round(float(eq.iloc[-1]),2),'stats':period_stats(eq)}
    if extra_signals:
        for name,gfn in extra_signals.items():
            d={}
            for road in ('LONG','CONT','VAL'):
                eq,_=simulate(P, gfn, road); d[road]=round(float(eq.iloc[-1]),2)
            eq,_=simulate(P, gfn, 'LONG'); d['stats']=period_stats(eq)
            out['grid'][name]=d
    return out
if __name__=='__main__':
    fams={
     'adm': (adm, ['SPY','SCZ','TLT','TIP']),
     'carlson': (carlson, ['TLT','GLD','DBC','UUP','SPY']),
     'choi': (choi, ['QQQ','SCHD','TLT','DBC']),
     'clare_us': (clare_us, ['SPY','IWM','IEF','DBC','VNQ']),
     'clare_global': (clare_global, ['SPY','EFA','EEM','IEF','BWX','DBC','VNQ']),
     'sacevs_best': (sacevs_best, ['TLT','LQD','SPY']),
     'sacevs_weighted': (sacevs_weighted, ['TLT','LQD','SPY']),
    }
    which=sys.argv[1]
    fn,pa=fams[which]
    extra={'combined_constructed': sacevs_combined} if which=='sacevs_best' else None
    res=run_family(fn, pa, extra_signals=extra)
    json.dump(res, open(f'{HERE}/res_{which}.json','w'), indent=1)
    for r in ('LONG','DECADE','CONT','VAL'):
        print(which, r, res['roads'][r]['final'], 'house', res['roads'][r+'_house']['final'], res['roads'][r]['stats'])
    print('placebos', res['placebos']); print('grid', res['grid'])
