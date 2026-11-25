"""Generic v12 catalog engine (adapted from osap-brand-capital chassis).
Signals supplied as {formation_year: {cik: value}}; June formations, 12m holds,
monthly marks, tiered costs, vanished->ZERO, v9 house floor variant, grid +
20-seed placebos. Roads are the honest 2016-start analogs (W04 stack)."""
import json, os, math, random
import numpy as np
W04 = os.path.join(os.path.expanduser('~'),'workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04,'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/','-'); p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04,'px_SPY.json'))}
def w04_frame(concept, year, suffix):
    return {int(k): v for k, v in loadj(os.path.join(W04,'frames',f'{concept}_{year}{suffix}.json')).items()}
def ym(y,m): return f'{y:04d}-{m:02d}'
# shares / split factors / caps
shares_f = {y: w04_frame('Shares', y, 'I') for y in range(2009,2026)}
sf = {}
for cik in cand:
    avail = [(y, shares_f[y][cik]) for y in range(2009,2026) if cik in shares_f[y]]
    d = {}
    for F in range(2016,2027):
        f = 1.0
        for (y0,a),(y1,b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b/a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d
def cap_of(cik, F):
    sh = shares_f.get(F-1,{}).get(cik) or shares_f.get(F-2,{}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ym(F,6))
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik,{}).get(F,1.0)
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

class Family:
    def __init__(self, signals, directions):
        """signals: {signal_name: {F: {cik: value}}}; directions: {name: 'high'|'low'}"""
        self.signals = signals; self.directions = directions; self._pc = {}
        self.POOLS = {}; self.MATS = {}
        for sname, byF in signals.items():
            for F, vals in byF.items():
                for uni in ('broad','nonfin'):
                    pool = {}
                    for cik, v in vals.items():
                        if cik not in px: continue
                        e = px[cik].get(ym(F,6))
                        if not e or not e[0] or v is None or (isinstance(v,float) and math.isnan(v)): continue
                        if uni == 'nonfin':
                            sic = str(cand[cik].get('sic') or '')
                            if sic[:1] == '6': continue
                        cap = cap_of(cik, F)
                        pool[cik] = {'v': float(v), 'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
                    self.POOLS[(sname,F,uni)] = pool
        for (sname,F,uni), pool in list(self.POOLS.items()):
            cols = [ym(F,m) for m in range(6,13)] + [ym(F+1,m) for m in range(1,7)]
            ciks = sorted(pool); M = np.full((len(ciks), len(cols)), np.nan)
            for i,cik in enumerate(ciks):
                s = px[cik]; last = None; lastbar = max(s) if s else None
                for j,mm in enumerate(cols):
                    if mm in s: last = s[mm][0]
                    if lastbar is not None and mm > lastbar: M[i,j] = 0.0
                    elif last is not None: M[i,j] = last
            self.MATS[(sname,F,uni)] = (ciks, M)
    def picks_for(self, sname, F, uni, count):
        key = (sname,F,uni,count)
        if key in self._pc: return self._pc[key]
        pool = self.POOLS[(sname,F,uni)]
        items = sorted(pool.items(), key=lambda kv: kv[1]['v'], reverse=(self.directions[sname]=='high'))
        if count == 'ALL': r = [c for c,_ in items]
        elif count == 'QUINTILE':
            n = max(1, math.ceil(len(items)*0.20)); r = [c for c,_ in items[:n]]
        else: r = [c for c,_ in items[:min(count, len(items))]]
        self._pc[key] = r; return r
    def placebo_picks(self, sname, F, uni, count, seed):
        key = (sname,F,uni,count,seed)
        if key in self._pc: return self._pc[key]
        pool = self.POOLS[(sname,F,uni)]
        rng = random.Random(seed*100003+F); keys = list(pool.keys()); rng.shuffle(keys)
        if count == 'ALL': n = len(keys)
        elif count == 'QUINTILE': n = max(1, math.ceil(len(keys)*0.20))
        else: n = min(count, len(keys))
        r = keys[:n]; self._pc[key] = r; return r
    REBAL = {'annual': {0}, 'quarterly': {0,3,6,9}, 'monthly': set(range(12))}
    def run_road(self, formations, sname, uni, count, cadence, house, seed=None):
        cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0
        for F in formations:
            ciks_all, M = self.MATS[(sname,F,uni)]; idx = {c:i for i,c in enumerate(ciks_all)}
            pool = self.POOLS[(sname,F,uni)]
            if seed is None: picks = self.picks_for(sname,F,uni,count)
            else: picks = self.placebo_picks(sname,F,uni,count,seed)
            cols = [ym(F,m) for m in range(6,13)] + [ym(F+1,m) for m in range(1,7)]
            if not picks:
                for mm in cols[1:]: curve.append([mm, round(cash,2)])
                continue
            rows = np.array([idx[c] for c in picks]); P = M[rows,:]
            rates = np.array([pool[c]['rate'] for c in picks])
            px0 = P[:,0].copy(); px0[px0<=0] = np.nan
            w = cash/len(picks)
            shares = np.where(np.isnan(px0), 0.0, (w*(1-rates))/np.where(np.isnan(px0),1.0,px0))
            total_costs += float(np.sum(w*rates)); in_cash = False
            for j in range(1,13):
                if in_cash: curve.append([cols[j], round(cash,2)]); continue
                pj = P[:,j]; vals = shares*np.where(np.isnan(pj),0.0,pj); val = float(np.sum(vals))
                if j in self.REBAL[cadence] and j < 12:
                    tgt = val/len(picks); trade = np.abs(tgt-vals); cst = float(np.sum(trade*rates))
                    total_costs += cst; scale = (val-cst)/val if val>0 else 0.0; vals = vals*scale
                    tgt = float(np.sum(vals))/len(picks)
                    shares = np.where(np.isnan(pj)|(pj<=0), 0.0, tgt/np.where(np.isnan(pj)|(pj<=0),1.0,pj)); val = float(np.sum(vals))
                if j == 12:
                    sell = float(np.sum(vals*rates)); total_costs += sell; cash = val-sell
                else: cash = val
                curve.append([cols[j], round(cash,2)]); peak = max(peak,cash)
                if house and cash <= 0.85*peak and j < 12:
                    sell = float(np.sum((shares*np.where(np.isnan(P[:,j]),0.0,P[:,j]))*rates))
                    total_costs += sell; cash -= sell; in_cash = True; curve[-1] = [cols[j], round(cash,2)]
            peak = max(peak,cash)
        peak2 = 100.0; maxdd = 0.0
        for _,v in curve:
            peak2 = max(peak2,v); maxdd = max(maxdd, 1-v/peak2) if peak2 else 0.0
        return round(cash,2), curve, round(total_costs,2), round(maxdd,4)

ROADS = {'LONGEST_2016_2025': list(range(2016,2026)), 'DECADE_2017_2025': list(range(2017,2026)),
         'CONT_2019_2025': list(range(2019,2026)), 'VAL_2023_2025': list(range(2023,2026))}
FOLDS = {'FOLD_2016_2020': list(range(2016,2021)), 'FOLD_2021_2025': list(range(2021,2026))}
def spy_final(formations):
    a = spy.get(ym(formations[0],6)); b = spy.get(ym(formations[-1]+1,6))
    return round(100*b/a,2) if a and b else None

def run_grid(fam, primary, secondaries=()):
    counts = [1,2,3,5,8,10,15,20,30,'ALL','QUINTILE']
    grid = {}
    def cell(sname,uni,rb,cad,count,roads):
        house = rb=='house'; out = {}
        for rname, forms in roads.items():
            fin,curve,costs,maxdd = fam.run_road(forms,sname,uni,count,cad,house)
            twins = []
            for s in range(1,21):
                tf,_,_,_ = fam.run_road(forms,sname,uni,count,cad,house,seed=s); twins.append(tf)
            out[rname] = {'final': fin,'costs': costs,'max_dd': maxdd,'spy_same_window': spy_final(forms),
                          'placebo_finals': twins,'placebos_beaten': sum(1 for t in twins if fin>t),'curve': curve}
        return out
    for uni in ('broad','nonfin'):
        for rb in ('native','house'):
            for cad in ('annual','quarterly','monthly'):
                for count in counts:
                    k = f'{primary}|{uni}|{rb}|{cad}|{count}'
                    grid[k] = cell(primary,uni,rb,cad,count,ROADS); print(k, grid[k]['LONGEST_2016_2025']['final'], flush=True)
    for sname in secondaries:
        for uni in ('broad','nonfin'):
            for rb in ('native','house'):
                for count in counts:
                    k = f'{sname}|{uni}|{rb}|annual|{count}'
                    grid[k] = cell(sname,uni,rb,'annual',count,ROADS); print(k, grid[k]['LONGEST_2016_2025']['final'], flush=True)
    # confirmation folds for cells beating SPY on all 4 roads with pb>=15 on LONGEST
    conf = {}
    for k, c in grid.items():
        if all(c[r]['final'] > (c[r]['spy_same_window'] or 1e18) for r in ROADS) and c['LONGEST_2016_2025']['placebos_beaten'] >= 15:
            parts = k.split('|'); sname,uni,rb,cad,count = parts[0],parts[1],parts[2],parts[3],parts[4]
            count = count if count in ('ALL','QUINTILE') else int(count)
            conf[k] = cell(sname,uni,rb,cad,count,FOLDS)
            print('CONFIRM', k, {r: conf[k][r]['final'] for r in FOLDS}, flush=True)
    return grid, conf

def period_stats(fam, sname, uni='broad'):
    """Annual (formation-year) returns for native quintile cell, LONGEST road."""
    rets = []
    for F in range(2016,2026):
        fin,_,_,_ = fam.run_road([F],sname,uni,'QUINTILE','annual',False)
        rets.append(round(fin-100.0,1))
    pos = sum(1 for r in rets if r>0); srt = sorted(rets)
    med = srt[len(srt)//2] if len(srt)%2 else round((srt[len(srt)//2-1]+srt[len(srt)//2])/2,1)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur+1 if r<=0 else 0; longest_loss = max(longest_loss,cur)
    # months between new highs from monthly curve
    _,curve,_,_ = fam.run_road(ROADS['LONGEST_2016_2025'],sname,uni,'QUINTILE','annual',False)
    peak = 100.0; since = 0; longest_gap = 0
    for _,v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest_gap = max(longest_gap,since)
    return {'periods': len(rets),'positive': pos,'median_pct': med,'best_pct': max(rets),'worst_pct': min(rets),
            'longest_losing_streak': longest_loss,'longest_months_between_highs': longest_gap,
            'year_by_year_pct': rets,'avg_pct_secondary': round(sum(rets)/len(rets),1)}
