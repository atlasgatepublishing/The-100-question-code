#!/usr/bin/env python3
"""V12 shareholder-yield CONSTRUCTED engine. Frozen construction per
CONSTRUCTION-SPEC.md: EDGAR-frames universe (all filers), Faber three-leg
yield from as-filed frames, June-30 annual formation, largest-1000 eligible
universe, top-decile equal-weight, tiered program costs, vanished prices
written to ZERO, 20-seed placebos per road. Simulation only."""
import json, os, sys, math, random, time
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
FR = os.path.join(DATA, 'frames')

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def ym(y, m): return f'{y:04d}-{m:02d}'

class Data:
    def __init__(self):
        self.cand = {int(k): v for k, v in json.load(open(os.path.join(DATA, 'candidates.json'))).items()}
        self.frames = {}
        self.px = {}
        for cik, info in self.cand.items():
            t = info['ticker'].replace('/', '-')
            p = os.path.join(DATA, f'px_{t}.json')
            if os.path.exists(p):
                try:
                    rows = json.load(open(p))
                    if len(rows) >= 6:
                        self.px[cik] = {r[0]: (r[1], r[2]) for r in rows}
                except Exception:
                    pass  # corrupt/empty file (intermittent write denials during fetch) -> treated as unpriced fence
        sp = os.path.join(DATA, 'px_SPY.json')
        try:
            self.spy = {r[0]: r[1] for r in json.load(open(sp))} if os.path.exists(sp) else {}
        except Exception:
            self.spy = {}  # SPY file corrupt (fetch write denials); program SPY refs used instead
        # split factors (v11 chassis method): EDGAR shares are as-filed;
        # Yahoo closes are split-adjusted for ALL later splits.
        self.sh_series = {y: load_frame(f'Shares_{y}I.json') for y in range(2009, 2026)}
        self.sf = {}
        for cik in self.cand:
            avail = [(y, self.sh_series[y][cik]) for y in range(2009, 2026) if cik in self.sh_series[y]]
            sf = {}
            for F in range(2011, 2027):
                f = 1.0
                for (y0, a), (y1, b) in zip(avail, avail[1:]):
                    if y1 >= F and a:
                        r = b / a
                        if r >= 1.6 or r <= 0.625: f *= r
                sf[F] = f
            self.sf[cik] = sf
    def F(self, concept, year, kind):
        key = (concept, year, kind)
        if key not in self.frames:
            self.frames[key] = load_frame(f'{concept}_{year}{kind}.json')
        return self.frames[key]
    def price(self, cik, month, adj=True):
        s = self.px.get(cik)
        if not s: return None
        if month in s: return s[month][0] if adj else s[month][1]
        prev = [m for m in s if m <= month]
        if not prev: return None
        return s[max(prev)][0] if adj else s[max(prev)][1]
    def last_bar(self, cik):
        s = self.px.get(cik)
        return max(s) if s else None
    def has_bar_between(self, cik, lo, hi):
        s = self.px.get(cik)
        return bool(s) and any(lo <= m <= hi for m in s)

D = None
_SNAP = {}

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def snapshot(F):
    """Eligible universe + yields at formation June 30 of F (data CY{F-1})."""
    if F in _SNAP: return _SNAP[F]
    y1, y2 = F - 1, F - 2
    div_c = D.F('PaymentsOfDividendsCommonStock', y1, 'D')
    div_a = D.F('PaymentsOfDividends', y1, 'D')
    rep = D.F('PaymentsForRepurchaseOfCommonStock', y1, 'D')
    iss = D.F('ProceedsFromIssuanceOfCommonStock', y1, 'D')
    def debt(y):
        ltc = D.F('LongTermDebtCurrent', y, 'I'); dc = D.F('DebtCurrent', y, 'I')
        ltn = D.F('LongTermDebtNoncurrent', y, 'I'); lt = D.F('LongTermDebt', y, 'I')
        out, present = {}, set()
        for cik in set(ltc) | set(dc) | set(ltn) | set(lt):
            cur = ltc.get(cik, dc.get(cik)); non = ltn.get(cik, lt.get(cik))
            if cur is None and non is None: continue
            out[cik] = (cur or 0) + (non or 0); present.add(cik)
        return out, present
    debt1, debtp1 = debt(y1); debt0, debtp0 = debt(y2)
    sh1 = D.F('Shares', y1, 'I'); sh0 = D.F('Shares', y2, 'I')
    roster = D.F('Assets', y1, 'I')
    fence = {'formation': F, 'roster_filers': len(roster), 'candidates_mapped': 0,
             'no_price': 0, 'reuse_excluded': 0, 'cap_floor': 0, 'no_data': 0, 'eligible': 0}
    elig = {}
    for cik, info in D.cand.items():
        if str(y1) not in info.get('years', {}): continue  # not top-1500 assets that year
        fence['candidates_mapped'] += 1
        if info.get('reuse_risk'):
            fence['reuse_excluded'] += 1; continue
        if not D.has_bar_between(cik, ym(F, 1), ym(F, 6)):
            fence['no_price'] += 1; continue
        shares = sh1.get(cik) or sh0.get(cik)
        px_raw = D.price(cik, ym(F, 6), adj=False); px_adj = D.price(cik, ym(F, 6), adj=True)
        if not shares or not px_raw or not px_adj:
            fence['no_price'] += 1; continue
        cap = shares * px_raw * D.sf.get(cik, {}).get(F, 1.0)
        if cap < 200e6:
            fence['cap_floor'] += 1; continue
        has_pay = cik in div_c or cik in div_a or cik in rep or cik in iss
        has_debt = cik in debtp1 or cik in debtp0
        if not has_pay and not has_debt:
            fence['no_data'] += 1; continue
        div = div_c.get(cik, div_a.get(cik, 0)) or 0
        buyback = (rep.get(cik, 0) or 0) - (iss.get(cik, 0) or 0)
        dpay = -(debt1.get(cik, 0) - debt0.get(cik, 0)) if has_debt else 0
        sy = (div + buyback + dpay) / cap
        elig[cik] = {'ticker': info['ticker'], 'cap': cap, 'px_adj': px_adj,
                     'sy': sy, 'div_y': div / cap, 'bb_y': buyback / cap, 'debt_y': dpay / cap}
    fence['eligible'] = len(elig)
    uni = dict(sorted(elig.items(), key=lambda kv: -kv[1]['cap'])[:1000])
    n_pick = max(1, math.ceil(len(uni) * 0.10))
    picks = [c for c, _ in sorted(uni.items(), key=lambda kv: -kv[1]['sy'])[:n_pick]]
    out = {'fence': fence, 'universe': uni, 'picks': picks, 'n_pick': n_pick}
    _SNAP[F] = out
    return out

def run(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; n_orders = 0; vanished = 0
    yearly = []
    for F in formations:
        snap = snapshot(F)
        uni = snap['universe']
        if seed is None:
            picks = snap['picks']
        else:
            rng = random.Random(seed * 1000 + F)
            keys = list(uni.keys()); rng.shuffle(keys)
            picks = keys[:snap['n_pick']]
        start_val = cash
        if not picks:
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0})
            for m in range(7, 13): curve.append([ym(F, m), round(cash, 2)])
            for m in range(1, 7): curve.append([ym(F + 1, m), round(cash, 2)])
            continue
        w = cash / len(picks); pos = {}
        for c in picks:
            rate = cost_rate(uni[c]['cap']); cost = w * rate
            total_costs += cost; n_orders += 1
            pos[c] = (w - cost) / uni[c]['px_adj']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        sale = ym(F + 1, 6)
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                lb = D.last_bar(c)
                if lb is not None and mm > lb:
                    continue  # vanished -> ZERO
                p = D.price(c, mm, adj=True)
                if p is None: p = uni[c]['px_adj']
                val += sh * p
            curve.append([mm, round(val, 2)])
        end_val = 0.0
        for c, sh in pos.items():
            lb = D.last_bar(c)
            if lb is not None and lb < sale:
                vanished += 1; continue  # sold for ZERO
            p = D.price(c, sale, adj=True) or uni[c]['px_adj']
            gross = sh * p; rate = cost_rate(uni[c]['cap']); cost = gross * rate
            total_costs += cost; n_orders += 1; end_val += gross - cost
        cash = end_val
        yearly.append({'formation': F,
                       'picks': [{'ticker': uni[c]['ticker'], 'sy': round(uni[c]['sy'], 4),
                                  'cap_bn': round(uni[c]['cap'] / 1e9, 2)} for c in picks] if seed is None else len(picks),
                       'ret': round(cash / start_val - 1, 4) if start_val else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_final = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy_final = round(100 * b / a, 2)
    yrs = len(formations)
    return {'final': round(cash, 2), 'cagr': round((cash / 100) ** (1 / yrs) - 1, 4) if cash > 0 else -1,
            'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2), 'orders': n_orders,
            'vanished_zeroed': vanished, 'curve': curve, 'yearly': yearly,
            'spy_final_same_window': spy_final}

def main():
    global D
    D = Data()
    roads = {
        'LONG_2012_2025': list(range(2012, 2026)),
        'DECADE_2017_2025': list(range(2017, 2026)),
        'CONT_2019_2025': list(range(2019, 2026)),
        'VAL_2023_2025': list(range(2023, 2026)),
        'FOLD_2017_2020': list(range(2017, 2021)),
        'FOLD_2021_2025': list(range(2021, 2026)),
    }
    res = {'family': 'shareholder-yield', 'construction': 'CONSTRUCTED per CONSTRUCTION-SPEC.md', 'roads': {}}
    fences = {}
    for F in range(2012, 2026):
        snap = snapshot(F)
        fences[F] = snap['fence']
        print('formation', F, snap['fence'], 'universe', len(snap['universe']), 'picks', snap['n_pick'], flush=True)
    res['fences'] = fences
    for name, forms in roads.items():
        bad = [F for F in forms if len(snapshot(F)['universe']) < 300]
        if bad:
            res['roads'][name] = {'dropped': f'eligible universe <300 at formations {bad}'}
            print(name, 'DROPPED', bad, flush=True); continue
        r = run(forms)
        twins = []
        for seed in range(1, 21):
            t = run(forms, seed=seed); twins.append(t['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        res['roads'][name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'],
              'placebos beaten', r['placebos_beaten'], '/20', 'maxdd', r['max_dd'], flush=True)
    outp = os.path.join(HERE, '..', 'results.json')
    saved = False
    for attempt in range(6):
        try:
            with open(outp, 'w') as fh: json.dump(res, fh, indent=1)
            saved = True; break
        except PermissionError:
            print('results.json write denied, retry', attempt, flush=True); time.sleep(5)
    print('saved results.json' if saved else 'WRITE FAILED - emitting JSON to stdout', flush=True)
    if not saved:
        print('RESULTS_JSON_BEGIN')
        print(json.dumps(res))
        print('RESULTS_JSON_END')

if __name__ == '__main__':
    main()
