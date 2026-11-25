#!/usr/bin/env python3
"""v13 BEST-RULES net-net — frozen spec in BEST-RULES-SPEC.md.
Semiannual formations (Jun + Dec; Dec uses same as-filed YE F-1
fundamentals, Dec prices). All qualifiers, equal-weight new buys.
Exits: +50% month-end; cap>NCAV at BOTH Jun and Dec reviews; 36-month
max; vanish-to-zero. NO floor, NO stop. Canonical v12 data/mapping
reused read-only. Costs: canonical tiers. 20-seed placebos per road.
Simulation only.
"""
import json, os, random, sys
V12 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                   'v12-completions', 'net-net')
sys.path.insert(0, os.path.abspath(V12))
import run_netnet as R

HERE = os.path.dirname(os.path.abspath(__file__))
D = None

def qualifiers_at(F, month):
    out = []
    for r in D.pool.get(F, []):
        cik = r['cik']
        if cik not in D.px: continue
        p = D.price(cik, month)
        if not p: continue
        ft = D.first_trade.get(cik)
        if ft and ft > month: continue
        cap = r['shares'] * p[1] * r['sf']
        if cap <= (2.0 / 3.0) * r['ncav']:
            out.append(cik)
    return out

def pool_at(F, month):
    out = []
    for r in D.pool.get(F, []):
        cik = r['cik']
        if cik not in D.px: continue
        if not D.price(cik, month): continue
        ft = D.first_trade.get(cik)
        if ft and ft > month: continue
        out.append(cik)
    return out

def simulate(form_months, end_ym, seed=None):
    start = form_months[0][1]
    timeline = R.months_between(start, end_ym)
    form_set = {m: F for F, m in form_months}
    cash = 100.0; pos = {}; curve = []; total_costs = 0.0
    n_buys = n_sells = n_zeroed = 0
    bought = {}
    for month in timeline:
        y, m = int(month[:4]), int(month[5:7])
        for cik in list(pos):
            lm = D.last_month(cik)
            if lm is not None and month > lm:
                del pos[cik]; n_zeroed += 1
        if month in form_set:
            F = form_set[month]
            # NCAV-closed review exit at BOTH Jun and Dec reviews:
            # latest as-filed NCAV available at this review is YE F-1
            # (filed <= Jun F), i.e. ncav_now(cik, F).
            for cik in list(pos):
                ncav, sh = D.ncav_now(cik, F)
                p = D.price(cik, month)
                if ncav is not None and sh and p:
                    cap_now = sh * p[1] * D.sf(cik, F)
                    if cap_now > ncav:
                        gross = pos[cik]['shares'] * p[0]
                        c = gross * pos[cik]['rate']; total_costs += c
                        cash += gross - c; del pos[cik]; n_sells += 1
            if seed is None:
                picks = [c for c in qualifiers_at(F, month) if c not in pos]
            else:
                nat = qualifiers_at(F, month)
                n_nat = len([c for c in nat if c not in pos])
                poolp = [c for c in pool_at(F, month)
                         if c not in pos and c not in set(nat)]
                rng = random.Random(seed * 100003 + F * 17 + m)
                rng.shuffle(poolp)
                picks = poolp[:n_nat]
            bought[month] = [D.mapping[c]['ticker'] if c in D.mapping
                             else str(c) for c in picks]
            if picks and cash > 0:
                w = cash / len(picks)
                for cik in picks:
                    row = next(r for r in D.pool[F] if r['cik'] == cik)
                    p = D.price(cik, month)
                    cap = row['shares'] * p[1] * row['sf']
                    rate = R.cost_rate(cap)
                    total_costs += w * rate
                    pos[cik] = {'shares': (w - w * rate) / p[0],
                                'entry': month, 'entry_adj': p[0],
                                'rate': rate}
                    n_buys += 1
                cash = 0.0
        # month-end exits: +50% and 36-month
        for cik in list(pos):
            p = D.price(cik, month)
            if not p: continue
            age = (y - int(pos[cik]['entry'][:4])) * 12 + \
                  (m - int(pos[cik]['entry'][5:7]))
            if p[0] >= 1.5 * pos[cik]['entry_adj'] or age >= 36:
                gross = pos[cik]['shares'] * p[0]
                c = gross * pos[cik]['rate']; total_costs += c
                cash += gross - c; del pos[cik]; n_sells += 1
        val = cash
        for cik, pp in pos.items():
            a = D.adj(cik, month)
            if a is None:
                s = D.px[cik]; prev = [k for k in s if k < month]
                a = s[max(prev)][0] if prev else pp['entry_adj']
            val += pp['shares'] * a
        curve.append([month, round(val, 2)])
    final = cash
    for cik, pp in pos.items():
        lm = D.last_month(cik)
        if lm is None or lm < pp['entry']: continue
        a = D.adj(cik, lm)
        gross = pp['shares'] * a
        final += gross - gross * pp['rate']
        total_costs += gross * pp['rate']
    spy_a = D.spy.get(start); spy_b = D.spy.get(end_ym)
    return {'final': round(final, 2), 'curve': curve, 'buys': n_buys,
            'sells': n_sells, 'zeroed': n_zeroed,
            'costs': round(total_costs, 2), 'bought': bought,
            'spy_final_same_window':
                round(100 * spy_b / spy_a, 2) if spy_a and spy_b else None}

def semiannual(y0, y1):
    ev = []
    for F in range(y0, y1 + 1):
        ev.append((F, R.ym(F, 6)))
        ev.append((F, R.ym(F, 12)))
    return sorted(ev, key=lambda t: t[1])

def main():
    global D
    R.HERE = os.path.abspath(V12)  # Data() reads from canonical folder
    D = R.Data()
    R.D = D
    roads = {
        'FULL': (semiannual(2016, 2025), '2026-06'),
        'CONT': (semiannual(2019, 2025), '2026-06'),
        'VAL': (semiannual(2023, 2025), '2026-06'),
        'FOLD1_2016_2020': (semiannual(2016, 2020), '2021-06'),
        'FOLD2_2021_2025': (semiannual(2021, 2025), '2026-06'),
    }
    res = {'family': 'net-net', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md', 'flatters_fence':
           'EVERY number is an UPPER BOUND: free delisted prices do not '
           'exist; the unpriced population (disproportionately delisted/'
           'bankrupt names) is excluded. FLATTERS.'}
    for name, (forms, end) in roads.items():
        r = simulate(forms, end)
        r['period_stats'] = R.period_stats(r['curve'])
        twins = []
        for seed in range(1, 21):
            twins.append(simulate(forms, end, seed=seed)['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        res[name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'],
              'placebos beaten', r['placebos_beaten'], '/20',
              'maxDD', r['period_stats'].get('max_dd'), flush=True)
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved results.json', flush=True)

if __name__ == '__main__':
    main()
