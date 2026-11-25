#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — shareholder-yield line.

Universe / ranking / native mechanics: EXACTLY the canonical v12 family's
frozen CONSTRUCTION-SPEC (EDGAR-frames universe, Faber three-leg yield,
June-30 annual formation, largest-1000 eligible, equal weight, vanished
prices -> ZERO). Snapshot logic copied from the canonical engine_sy.py
(read-only source); prices are this folder's own fetch (data/sy_px/),
frames + candidates read from the canonical folder (read-only).

Sweep: counts GRID = 1,2,3,5,8,10,15,20,30, ALL-ELIGIBLE (whole universe),
plus NATIVE = the published decile count (ceil(10% of universe)).
Each count x road x ruleset, 20-seed placebos (random N from same universe).

Rulesets:
- native: tiered costs per canonical spec (>=5B 0.10%, >=1B 0.25%, <1B 0.75%
  per side), no floor.
- house (v9): flat 0.10%/side + $0.01 per sell order; plain -15% floor from
  episode start on monthly marks; first halt -> liquidate, 90-day sit-out,
  restart at next June formation >= halt+90d under episode-2 floor; second
  halt ends the run (cash to road end).
Roads (formations): LONG 2012-2025, DECADE 2017-2025, CONT 2019-2025,
VAL 2023-2025. Road dropped if eligible universe <300 at any formation.
Confirmation folds (run only if triggered): CONF_A 2012-2018, CONF_B 2019-2025.
"""
import json, os, sys, math, random, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
CANON = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')
FR = os.path.join(CANON, 'frames')
PXD = os.path.join(ROOT, 'data', 'sy_px')

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def ym(y, m): return f'{y:04d}-{m:02d}'

def load_px_rows(ticker):
    """Monthly price rows for a ticker: this folder's fetch first, then the
    canonical folder (both validated; corrupt/partial files fall through)."""
    for base in (PXD, CANON):
        p = os.path.join(base, f'px_{ticker}.json')
        if os.path.exists(p):
            try:
                rows = json.load(open(p))
                if len(rows) >= 6: return rows
            except Exception:
                continue
    return None

class Data:
    def __init__(self):
        self.cand = {int(k): v for k, v in json.load(open(os.path.join(CANON, 'candidates.json'))).items()}
        self.px = {}
        for cik, info in self.cand.items():
            t = info['ticker'].replace('/', '-')
            rows = load_px_rows(t)
            if rows:
                self.px[cik] = {r[0]: (r[1], r[2]) for r in rows}
        rows = load_px_rows('SPY')
        self.spy = {r[0]: r[1] for r in rows} if rows else {}
        if len(self.spy) < 100:
            # canonical SPY file caught mid-rewrite once; fetch in-memory
            try:
                import urllib.request, urllib.parse, datetime as _dt
                u = 'https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1=1262304000&period2=1796000000&interval=1mo&events=div,split'
                req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
                d = json.loads(urllib.request.urlopen(req, timeout=60).read())
                res = d['chart']['result'][0]
                ts = res['timestamp']; adj = res['indicators']['adjclose'][0]['adjclose']
                self.spy = {_dt.datetime.fromtimestamp(t_, _dt.UTC).strftime('%Y-%m'): a
                            for t_, a in zip(ts, adj) if a is not None}
            except Exception as e:
                print('SPY in-memory fetch failed:', e, flush=True)
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
        self.frames = {}
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

def tier_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def snapshot(F):
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
        if str(y1) not in info.get('years', {}): continue
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
        elig[cik] = {'ticker': info['ticker'], 'cap': cap, 'px_adj': px_adj, 'sy': sy}
    fence['eligible'] = len(elig)
    uni = dict(sorted(elig.items(), key=lambda kv: -kv[1]['cap'])[:1000])
    ranked = [c for c, _ in sorted(uni.items(), key=lambda kv: -kv[1]['sy'])]
    n_native = max(1, math.ceil(len(uni) * 0.10))
    out = {'fence': fence, 'universe': uni, 'ranked': ranked, 'n_native': n_native}
    _SNAP[F] = out
    return out

def month_add(y, m, k):
    mm = m + k
    return (y + (mm - 1) // 12, (mm - 1) % 12 + 1)

def run(formations, count, rules, seed=None):
    """count: int, 'ALL', or 'NATIVE'. rules: 'native' or 'house'."""
    cash = 100.0; curve = []; total_costs = 0.0; n_orders = 0; vanished = 0
    yearly = []; halts = []; episode_start = 100.0; blocked_until = None  # (y,m) of June formation
    ended = False
    for F in formations:
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if ended or (blocked_until is not None and (F, 6) < blocked_until):
            for mm in months: curve.append([mm, round(cash, 2)])
            yearly.append({'formation': F, 'picks': 0, 'ret': 0.0, 'note': 'cash (sit-out/ended)'})
            continue
        snap = snapshot(F); uni = snap['universe']
        if count == 'ALL': n = len(uni)
        elif count == 'NATIVE': n = snap['n_native']
        else: n = min(count, len(uni))
        if seed is None:
            picks = snap['ranked'][:n]
        else:
            rng = random.Random(seed * 1000 + F)
            keys = list(uni.keys()); rng.shuffle(keys)
            picks = keys[:n]
        start_val = cash; episode_start = cash
        if not picks:
            yearly.append({'formation': F, 'picks': 0, 'ret': 0.0})
            for mm in months: curve.append([mm, round(cash, 2)])
            continue
        w = cash / len(picks); pos = {}
        for c in picks:
            if rules == 'native':
                cost = w * tier_rate(uni[c]['cap'])
            else:
                cost = w * 0.0010
            total_costs += cost; n_orders += 1
            pos[c] = (w - cost) / uni[c]['px_adj']
        sale = ym(F + 1, 6)
        halted_mid = False
        for mi, mm in enumerate(months):
            val = 0.0
            for c, sh in pos.items():
                lb = D.last_bar(c)
                if lb is not None and mm > lb: continue
                p = D.price(c, mm, adj=True)
                if p is None: p = uni[c]['px_adj']
                val += sh * p
            if rules == 'house' and not halted_mid and val <= 0.85 * episode_start:
                # HALT: liquidate at this month-end
                liq = 0.0
                for c, sh in pos.items():
                    lb = D.last_bar(c)
                    if lb is not None and mm > lb: continue
                    p = D.price(c, mm, adj=True)
                    if p is None: p = uni[c]['px_adj']
                    gross = sh * p; cst = gross * 0.0010 + 0.01
                    total_costs += cst; n_orders += 1; liq += gross - cst
                cash = liq; halts.append(mm); halted_mid = True
                curve.append([mm, round(cash, 2)])
                for mm2 in months[mi + 1:]: curve.append([mm2, round(cash, 2)])
                hy, hm = int(mm[:4]), int(mm[5:7])
                by, bm = month_add(hy, hm, 3)  # halt + ~90 days
                # restart at first June formation on/after halt+90d
                blocked_until = (by, 6) if bm <= 6 else (by + 1, 6)
                if len(halts) >= 2: ended = True
                break
            curve.append([mm, round(val, 2)])
        if halted_mid:
            yearly.append({'formation': F, 'picks': len(picks) if seed is None else len(picks),
                           'ret': round(cash / start_val - 1, 4), 'note': f'halt #{len(halts)}'})
            continue
        end_val = 0.0
        for c, sh in pos.items():
            lb = D.last_bar(c)
            if lb is not None and lb < sale:
                vanished += 1; continue
            p = D.price(c, sale, adj=True) or uni[c]['px_adj']
            gross = sh * p
            if rules == 'native':
                cost = gross * tier_rate(uni[c]['cap'])
            else:
                cost = gross * 0.0010 + 0.01
            total_costs += cost; n_orders += 1; end_val += gross - cost
        cash = end_val
        yearly.append({'formation': F, 'picks': len(picks),
                       'ret': round(cash / start_val - 1, 4) if start_val else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_final = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy_final = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2),
            'orders': n_orders, 'vanished_zeroed': vanished, 'halts': halts,
            'curve': curve, 'yearly': yearly, 'spy_final_same_window': spy_final}

def save_json(obj, path):
    import time as _t
    tmp = path + '.tmp'
    for attempt in range(5):
        try:
            with open(tmp, 'w') as f:
                json.dump(obj, f, indent=1)
            os.replace(tmp, path)
            return
        except OSError as e:
            print('save retry', attempt, e, flush=True); _t.sleep(3)
    raise RuntimeError('could not save ' + path)

GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL', 'NATIVE']
ROADS = {'LONG': list(range(2012, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
FOLDS = {'CONF_A_2012_2018': list(range(2012, 2019)), 'CONF_B_2019_2025': list(range(2019, 2026))}

def sweep(roads, with_placebos=True):
    out = {}
    for rname, forms in roads.items():
        bad = [F for F in forms if len(snapshot(F)['universe']) < 300]
        if bad:
            out[rname] = {'dropped': f'eligible universe <300 at formations {bad}'}
            print(rname, 'DROPPED', bad, flush=True); continue
        out[rname] = {}
        for rules in ('native', 'house'):
            out[rname][rules] = {}
            for count in GRID:
                r = run(forms, count, rules)
                cell = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'vanished_zeroed', 'halts', 'spy_final_same_window')}
                cell['detail'] = {'curve': r['curve'], 'yearly': r['yearly']}
                if with_placebos and count != 'ALL':
                    twins = [run(forms, count, rules, seed=s)['final'] for s in range(1, 21)]
                    cell['placebo_finals'] = twins
                    cell['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
                out[rname][rules][str(count)] = cell
                print(rname, rules, count, 'final', cell['final'],
                      'beat', cell.get('placebos_beaten'), '/20', 'halts', cell['halts'], flush=True)
        save_json(out, os.path.join(ROOT, 'results_sy_partial.json'))
    return out

def main():
    global D
    D = Data()
    print('candidates with prices:', sum(1 for c in D.cand if c in D.px), '/', len(D.cand), flush=True)
    res = {'family': 'shareholder-yield', 'line': 'holdings-count sweep',
           'form_swept': 'v12 CONSTRUCTED native decile form (FabER three-leg yield, largest-1000, annual)',
           'fences': {}, 'roads': {}}
    for F in range(2012, 2026):
        snap = snapshot(F)
        res['fences'][F] = {**snap['fence'], 'universe': len(snap['universe']), 'n_native': snap['n_native']}
        print('formation', F, res['fences'][F], flush=True)
    res['roads'] = sweep(ROADS)
    # CONFIRMATION RULE: every non-native count beating NATIVE on >=3 of 4
    # roads (native rules) is re-run on the two disjoint folds.
    try:
        wins = {}; totals = {}
        for count in GRID:
            if count in ('ALL', 'NATIVE'): continue
            w = 0; tot = 0.0
            for rname in ROADS:
                cell = res['roads'].get(rname, {}).get('native', {}).get(str(count))
                nat = res['roads'].get(rname, {}).get('native', {}).get('NATIVE')
                if cell and nat:
                    tot += cell['final']
                    if cell['final'] > nat['final']: w += 1
            wins[count] = w; totals[count] = round(tot, 2)
        print('non-native road-win counts vs NATIVE (native rules):', wins, flush=True)
        print('non-native total finals (native rules):', totals, flush=True)
        res['confirmation'] = {}
        for count in GRID:
            if count in ('ALL', 'NATIVE') or wins.get(count, 0) < 3: continue
            folds = {}
            for fname, forms in FOLDS.items():
                folds[fname] = {'candidate': run(forms, count, 'native')['final'],
                                'native': run(forms, 'NATIVE', 'native')['final']}
            res['confirmation'][str(count)] = folds
            print('CONFIRMATION count', count, folds, flush=True)
    except Exception as e:
        print('confirmation step error:', e, flush=True)
    # curves for native count + every count (finals table needs only finals;
    # curves saved for NATIVE and best-on-LONG per ruleset)
    res['curves'] = {}
    for rules in ('native', 'house'):
        res['curves'][rules] = {}
        for rname, forms in ROADS.items():
            if 'dropped' in res['roads'].get(rname, {}): continue
            res['curves'][rules][rname] = {'NATIVE': run(forms, 'NATIVE', rules)}
    save_json(res, os.path.join(ROOT, 'results_sy.json'))
    print('saved results_sy.json', flush=True)

if __name__ == '__main__':
    main()
