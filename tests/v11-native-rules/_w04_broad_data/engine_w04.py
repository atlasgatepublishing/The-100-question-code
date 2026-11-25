#!/usr/bin/env python3
"""W04 v11 native-rules engine: Magic Formula / Piotroski / Quality on the
broad EDGAR-frames universe. Annual June-30 formation, 1-year holds, monthly
marks on Yahoo adjclose, tiered habitat costs, NO floor (native systems have
none), 20-seed placebos, fold sub-runs. Simulation only.
Usage: engine_w04.py <magic-formula|piotroski|quality-standalone|netnet-census> <outdir>
"""
import json, os, sys, math, random
HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, 'frames')

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

class Data:
    def __init__(self):
        self.cand = json.load(open(os.path.join(HERE, 'candidates.json')))
        self.cand = {int(k): v for k, v in self.cand.items()}
        self.frames = {}
        self.px = {}
        for cik, info in self.cand.items():
            t = info['ticker'].replace('/', '-')
            p = os.path.join(HERE, f'px_{t}.json')
            if os.path.exists(p):
                self.px[cik] = {r[0]: (r[1], r[2]) for r in json.load(open(p))}
        # split factors: EDGAR shares are as-filed (pre-later-split); Yahoo closes
        # are split-adjusted for ALL later splits. SF(F) = product of split-like
        # YoY share-count ratios (r>=1.6 or r<=0.625) in frame years >= F, so
        # cap = shares(F-1) x split-adj price x SF(F) approximates true cap.
        self.sh_series = {}
        for y in range(2014, 2026):
            self.sh_series[y] = load_frame(f'Shares_{y}I.json')
        self.sf = {}
        for cik in self.cand:
            series = {y: self.sh_series[y].get(cik) for y in range(2014, 2026)}
            avail = [(y, series[y]) for y in range(2014, 2026) if series.get(y)]
            sf = {}
            for F in range(2017, 2027):
                f = 1.0
                for (y0, a), (y1, b) in zip(avail, avail[1:]):
                    if y1 >= F:
                        r = b / a
                        if r >= 1.6 or r <= 0.625: f *= r
                sf[F] = f
            self.sf[cik] = sf
        sp = os.path.join(HERE, 'px_SPY.json')
        self.spy = {r[0]: r[1] for r in json.load(open(sp))} if os.path.exists(sp) else {}
    def F(self, concept, year, kind):
        key = (concept, year, kind)
        if key not in self.frames:
            self.frames[key] = load_frame(f'{concept}_{year}{kind}.json')
        return self.frames[key]
    def price(self, cik, ym, adj=True):
        s = self.px.get(cik)
        if not s: return None
        if ym in s: return s[ym][0] if adj else s[ym][1]
        # last available month <= ym (delisting freeze / gap)
        prev = [m for m in s if m <= ym]
        if not prev: return None
        return s[max(prev)][0] if adj else s[max(prev)][1]
    def has_price_month(self, cik, ym):
        return cik in self.px and ym in self.px[cik]

D = None
def ym(y, m): return f'{y:04d}-{m:02d}'

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def snapshot(F):
    """All computable fields per cik at formation June 30 of year F.
    BS: instant frames year F-1 (prior F-2). Flows: duration frames CY{F-1}
    (fiscal year beginning F-1) and CY{F-2}."""
    bs1 = {c: D.F(c, F-1, 'I') for c in ['Assets','AssetsCurrent','Liabilities','LiabilitiesCurrent',
        'StockholdersEquity','CashAndCashEquivalentsAtCarryingValue','PropertyPlantAndEquipmentNet',
        'LongTermDebtCurrent','DebtCurrent','LongTermDebtNoncurrent','LongTermDebt']}
    bs0 = {c: D.F(c, F-2, 'I') for c in ['Assets','AssetsCurrent','LiabilitiesCurrent','LongTermDebtCurrent',
        'DebtCurrent','LongTermDebtNoncurrent','LongTermDebt']}
    fl1 = {c: D.F(c, F-1, 'D') for c in ['OperatingIncomeLoss','InterestExpense','InterestAndDebtExpense',
        'NetIncomeLoss','NetCashProvidedByUsedInOperatingActivities','GrossProfit','Revenues',
        'SalesRevenueNet','RevenueFromContractWithCustomerExcludingAssessedTax','CostOfRevenue',
        'CostOfGoodsAndServicesSold','CostOfGoodsSold','WeightedAverageNumberOfDilutedSharesOutstanding']}
    fl0 = {c: D.F(c, F-2, 'D') for c in ['NetIncomeLoss','GrossProfit','Revenues','SalesRevenueNet',
        'RevenueFromContractWithCustomerExcludingAssessedTax','CostOfRevenue','CostOfGoodsAndServicesSold','CostOfGoodsSold']}
    def latest_shares(y):
        for yy in (y, y-1, y-2):
            d = D.F('Shares', yy, 'I')
            if d: return d
        return {}
    sh1 = latest_shares(F-1); sh0 = latest_shares(F-2)
    out = {}
    for cik in D.cand:
        g = lambda dd, c: dd[c].get(cik)
        rev1 = g(fl1,'Revenues') or g(fl1,'SalesRevenueNet') or g(fl1,'RevenueFromContractWithCustomerExcludingAssessedTax')
        rev0 = g(fl0,'Revenues') or g(fl0,'SalesRevenueNet') or g(fl0,'RevenueFromContractWithCustomerExcludingAssessedTax')
        cogs1 = g(fl1,'CostOfRevenue') or g(fl1,'CostOfGoodsAndServicesSold') or g(fl1,'CostOfGoodsSold')
        cogs0 = g(fl0,'CostOfRevenue') or g(fl0,'CostOfGoodsAndServicesSold') or g(fl0,'CostOfGoodsSold')
        gp1 = g(fl1,'GrossProfit');  gp1 = gp1 if gp1 is not None else (rev1 - cogs1 if (rev1 is not None and cogs1 is not None) else None)
        gp0 = g(fl0,'GrossProfit');  gp0 = gp0 if gp0 is not None else (rev0 - cogs0 if (rev0 is not None and cogs0 is not None) else None)
        ltd1 = (g(bs1,'LongTermDebtCurrent') or g(bs1,'DebtCurrent') or 0) + (g(bs1,'LongTermDebtNoncurrent') or g(bs1,'LongTermDebt') or 0)
        has_ltd = (g(bs1,'LongTermDebtCurrent') is not None or g(bs1,'DebtCurrent') is not None or g(bs1,'LongTermDebtNoncurrent') is not None or g(bs1,'LongTermDebt') is not None)
        ltd0 = (g(bs0,'LongTermDebtCurrent') or g(bs0,'DebtCurrent') or 0) + (g(bs0,'LongTermDebtNoncurrent') or g(bs0,'LongTermDebt') or 0)
        px_raw = D.price(cik, ym(F,6), adj=False); px_adj = D.price(cik, ym(F,6), adj=True)
        shares = sh1.get(cik)
        cap = (shares * px_raw * D.sf.get(cik, {}).get(F, 1.0)) if (shares and px_raw) else None
        out[cik] = dict(
            assets=g(bs1,'Assets'), assets0=g(bs0,'Assets'), ca=g(bs1,'AssetsCurrent'), cl=g(bs1,'LiabilitiesCurrent'),
            ca0=g(bs0,'AssetsCurrent'), cl0=g(bs0,'LiabilitiesCurrent'), liab=g(bs1,'Liabilities'),
            equity=g(bs1,'StockholdersEquity'), cash=g(bs1,'CashAndCashEquivalentsAtCarryingValue'),
            ppe=g(bs1,'PropertyPlantAndEquipmentNet'), ltd=ltd1 if has_ltd else None, ltd0=ltd0,
            opinc=g(fl1,'OperatingIncomeLoss'), interest=g(fl1,'InterestExpense') or g(fl1,'InterestAndDebtExpense'),
            ni=g(fl1,'NetIncomeLoss'), ni0=g(fl0,'NetIncomeLoss'), cfo=g(fl1,'NetCashProvidedByUsedInOperatingActivities'),
            rev=rev1, rev0=rev0, gp=gp1, gp0=gp0, shares=shares, shares0=sh0.get(cik),
            diluted=g(fl1,'WeightedAverageNumberOfDilutedSharesOutstanding'),
            cap=cap, px_adj=px_adj, sic=int(D.cand[cik].get('sic') or 0) if str(D.cand[cik].get('sic') or '0').isdigit() else 0, ticker=D.cand[cik]['ticker'])
    return out

def is_fin(sic): return 6000 <= sic <= 6999
def is_util(sic): return 4900 <= sic <= 4999

def eligible_magic(s):
    return {c: v for c, v in s.items() if not is_fin(v['sic']) and not is_util(v['sic']) and v['sic'] != 9999
            and v['cap'] and v['cap'] >= 50e6 and v['opinc'] is not None and v['assets'] and v['ca'] is not None
            and v['cl'] is not None and v['ppe'] is not None and v['px_adj']}

def magic_picks(s):
    pool = eligible_magic(s); scored = {}
    for c, v in pool.items():
        ebit = v['opinc'] + (v['interest'] or 0)
        ev = v['cap'] + (v['ltd'] or 0) - (v['cash'] or 0)
        capital = (v['ca'] - (v['cash'] or 0)) - (v['cl'] - ((v['ltd'] or 0) and 0)) + v['ppe']
        # capital per Greenblatt: (CA - excess cash) - (CL - debt in CL) + net PPE; debt-in-CL approx via current LTD
        capital = (v['ca'] - (v['cash'] or 0)) - (v['cl']) + v['ppe']
        if ev <= 0 or capital <= 0: continue
        scored[c] = (ebit / ev, ebit / capital)
    if len(scored) < 30: return [], pool
    ey = sorted(scored, key=lambda c: -scored[c][0]); rc = sorted(scored, key=lambda c: -scored[c][1])
    rank = {c: ey.index(c) + rc.index(c) for c in scored}
    return sorted(scored, key=lambda c: rank[c])[:30], pool

def eligible_quality(s):
    out = {}; flagged = []
    for c, v in s.items():
        if is_fin(v['sic']) or v['gp'] is None or not v['assets'] or not v['px_adj'] or not v['cap']: continue
        gpa = v['gp'] / v['assets']
        if gpa > 1.0: flagged.append((v['ticker'], round(gpa,2))); continue
        out[c] = gpa
    return out, flagged

def quality_picks(s):
    pool, flagged = eligible_quality(s)
    n = max(1, len(pool) // 5)
    return sorted(pool, key=lambda c: -pool[c])[:n], pool, flagged

def fscore(v):
    if None in (v['ni'], v['cfo'], v['assets'], v['assets0']) or v['assets0'] == 0: return None
    if None in (v['ni0'], v['ca'], v['cl'], v['ca0'], v['cl0']) or v['cl'] == 0 or v['cl0'] == 0: return None
    if v['ltd'] is None or v['ltd0'] is None or v['shares'] is None or v['shares0'] is None: return None
    if v['gp'] is None or v['gp0'] is None or not v['rev'] or not v['rev0']: return None
    roa = v['ni'] / v['assets0']; roa0 = v['ni0'] / v['assets0'] if False else None
    # delta ROA needs NI0 over assets two years back: approximate with assets0 denominator for both (printed approx)
    roa_prev = v['ni0'] / v['assets0']
    sc = 0
    sc += 1 if roa > 0 else 0
    sc += 1 if v['cfo'] > 0 else 0
    sc += 1 if roa > roa_prev else 0
    sc += 1 if v['cfo'] / v['assets0'] > roa else 0
    sc += 1 if v['ltd'] / v['assets'] < v['ltd0'] / v['assets0'] else 0
    sc += 1 if v['ca'] / v['cl'] > v['ca0'] / v['cl0'] else 0
    sc += 1 if v['shares'] <= v['shares0'] else 0
    sc += 1 if v['gp'] / v['rev'] > v['gp0'] / v['rev0'] else 0
    turn = v['rev'] / v['assets0']; turn0 = v['rev0'] / v['assets0']
    sc += 1 if turn > turn0 else 0
    return sc

def piotroski_picks(s):
    pool = {c: v for c, v in s.items() if v['equity'] and v['cap'] and v['equity'] > 0 and v['px_adj']}
    if len(pool) < 20: return [], pool, {}
    bm = {c: v['equity'] / v['cap'] for c, v in pool.items()}
    n5 = max(1, len(bm) // 5)
    quintile = sorted(bm, key=lambda c: -bm[c])[:n5]
    scores = {}
    for c in quintile:
        fs = fscore(pool[c])
        if fs is not None: scores[c] = fs
    picks = [c for c in quintile if scores.get(c, 0) >= 8]
    picks = sorted(picks, key=lambda c: -bm[c])[:30]
    return picks, {c: pool[c] for c in quintile}, scores

def run(pick_fn, formations, seed=None):
    """pick_fn(snapshot, F) -> (picks list, pool dict). Returns result dict."""
    cash = 100.0; curve = []; total_costs = 0.0; n_orders = 0; frozen_ct = 0
    yearly = []
    for F in formations:
        s = snapshot(F)
        if seed is None:
            picks, pool = pick_fn(s, F)
        else:
            _, pool = pick_fn(s, F)
            rng = random.Random(seed * 1000 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:pick_fn.count] if hasattr(pick_fn, 'count') else keys[:30]
        start_val = cash
        if not picks:
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0})
            for m in range(7, 13): curve.append([ym(F, m), round(cash, 2)])
            for m in range(1, 7): curve.append([ym(F+1, m), round(cash, 2)])
            continue
        w = cash / len(picks)
        pos = {}
        for c in picks:
            rate = cost_rate(s[c]['cap']); cost = w * rate
            total_costs += cost; n_orders += 1
            pos[c] = (w - cost) / s[c]['px_adj']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F+1, m) for m in range(1, 7)]
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                p = D.price(c, mm, adj=True)
                if p is None: p = s[c]['px_adj']
                if not D.has_price_month(c, mm): frozen_ct += 0  # freeze is inside price()
                val += sh * p
            curve.append([mm, round(val, 2)])
        # sell at June F+1 close
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, ym(F+1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p; rate = cost_rate(s[c]['cap']); cost = gross * rate
            total_costs += cost; n_orders += 1; end_val += gross - cost
        cash = end_val
        yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks],
                       'ret': round(cash / start_val - 1, 4) if start_val else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_ret = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy_ret = round(100 * b / a, 2)
    yrs = len(formations)
    return {'final': round(cash, 2), 'cagr': round((cash / 100) ** (1 / yrs) - 1, 4) if cash > 0 else -1,
            'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2), 'orders': n_orders,
            'curve': curve, 'yearly': yearly, 'spy_final_same_window': spy_ret}

def main():
    global D
    fam = sys.argv[1]; outdir = sys.argv[2]; os.makedirs(outdir, exist_ok=True)
    D = Data()
    formations = list(range(2017, 2026))
    if fam == 'netnet-census':
        census = []
        for F in formations:
            s = snapshot(F); q = []
            for c, v in s.items():
                if v['ca'] is None or v['liab'] is None or not v['shares'] or not v['px_adj']: continue
                ncav = v['ca'] - v['liab']
                if ncav <= 0: continue
                if v['cap'] and v['cap'] < (2/3) * ncav: q.append({'ticker': v['ticker'], 'cap': round(v['cap']), 'ncav': round(ncav)})
            census.append({'formation': F, 'qualifiers_in_broad_universe': q, 'n_qualifiers': len(q)})
            print(F, len(q), flush=True)
        json.dump(census, open(os.path.join(outdir, 'census.json'), 'w'), indent=1)
        return
    if fam == 'magic-formula':
        def pf(s, F):
            p, pool = magic_picks(s); return p, pool
        pf.count = 30
    elif fam == 'quality-standalone':
        def pf(s, F):
            p, pool, fl = quality_picks(s)
            pf.last_flagged = fl; pf.count = len(p)
            return p, pool
        pf.count = 30
    elif fam == 'piotroski':
        def pf(s, F):
            p, pool, sc = piotroski_picks(s); pf.last_scores = sc; return p, pool
        pf.count = 30
    res = {'family': fam, 'formations': formations}
    res['full'] = run(pf, formations)
    res['fold_2017_2020'] = run(pf, list(range(2017, 2021)))
    res['fold_2021_2025'] = run(pf, list(range(2021, 2026)))
    res['era_2019_2025'] = run(pf, list(range(2019, 2026)))
    res['era_2023_2025'] = run(pf, list(range(2023, 2026)))
    print(fam, 'full final', res['full']['final'], 'spy', res['full']['spy_final_same_window'], flush=True)
    twins = []
    for seed in range(1, 21):
        # placebo count must match native pick count per formation: use native counts via closure
        r = run_placebo(pf, formations, seed)
        twins.append(r['final']); print(' twin', seed, r['final'], flush=True)
    res['placebo_finals'] = twins
    res['placebos_beaten'] = sum(1 for t in twins if res['full']['final'] > t)
    json.dump(res, open(os.path.join(outdir, 'results.json'), 'w'), indent=1)
    print('saved', fam, flush=True)

# placebo needs per-formation native pick counts; recompute them first
_NATIVE_COUNTS = {}
def run_placebo(pf, formations, seed):
    global _NATIVE_COUNTS
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        s = snapshot(F)
        picks_nat, pool = pf(s, F)
        n = len(picks_nat)
        if n == 0: continue
        rng = random.Random(seed * 7919 + F)
        keys = list(pool.keys()); rng.shuffle(keys)
        picks = keys[:n]
        w = cash / len(picks); pos = {}
        for c in picks:
            rate = cost_rate(s[c]['cap']); total_costs += w * rate
            pos[c] = (w - w * rate) / s[c]['px_adj']
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, ym(F+1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p; total_costs += gross * cost_rate(s[c]['cap']); end_val += gross - gross * cost_rate(s[c]['cap'])
        cash = end_val
    return {'final': round(cash, 2), 'costs': round(total_costs, 2)}

if __name__ == '__main__':
    main()
