#!/usr/bin/env python3
"""v12 net-net SECOND-CHANCE GRID (pre-registered in this header before runs).
Dimensions that mechanically apply to this family:
  - formation cadence: ANNUAL (June, native) | SEMIANNUAL (June + December;
    December uses the same YE F-1 as-filed fundamentals, December prices)
  - holdings: ALL qualifiers (native) | TOP-10 by discount depth (cap/NCAV)
  - exit rulebook: NATIVE (+50% / June-review cap>NCAV / 36m / vanish-zero)
    | ANNUAL-ONLY (exits only at June reviews when cap>NCAV; vanish-zero and
    final liquidation unchanged) | HOUSE-FLOOR (native exits + Terry's -15%
    portfolio floor: liquidate everything and stop at a month-end value
    <= 85% of the road's starting $100 -- the v9 house rulebook dimension)
Cells (FULL road, formations 2016-2025, $100 -> Jun 2026, 20-seed placebos
from the same priced pool, same costs as the frozen main run):
  A1 annual x all x native      = the frozen main run (reference cell, rerun
                                  here through this engine for comparability)
  A2 annual x top10 x native
  A3 semiannual x all x native
  A4 annual x all x annual-only
  A5 annual x all x house-floor
NOT run (named, in RESULTS.md GRID GAPS): daily/weekly/monthly formation
cadences (net-net signals change on filing dates, not on price ticks -- a
daily "cadence" is the same annual screen re-read; the semiannual cell is
the honest sub-annual step), pond universe (v11 census: 0-1 qualifiers in
the top-600 pond -- no basket exists to run), crypto cross-run (coins have
no balance sheets; NCAV is undefined -- not mechanical).
Simulation only.
"""
import json, os, random
import run_netnet as R

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
            out.append((cik, cap / r['ncav']))
    out.sort(key=lambda t: t[1])
    return [c for c, _ in out]

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

def simulate(form_months, topn=None, exits='native', floor=False, seed=None):
    """form_months: list of (F, 'YYYY-MM') formation events."""
    start = form_months[0][1]
    timeline = R.months_between(start, '2026-06')
    form_set = {m: F for F, m in form_months}
    cash = 100.0; pos = {}; curve = []; total_costs = 0.0; halted = False
    for month in timeline:
        y, m = int(month[:4]), int(month[5:7])
        for cik in list(pos):
            lm = D.last_month(cik)
            if lm is not None and month > lm: del pos[cik]
        if month in form_set:
            F = form_set[month]
            if m == 6:
                for cik in list(pos):
                    ncav, sh = D.ncav_now(cik, y)
                    p = D.price(cik, month)
                    if ncav is not None and sh and p and sh * p[1] * D.sf(cik, y) > ncav:
                        gross = pos[cik]['shares'] * p[0]
                        total_costs += gross * pos[cik]['rate']
                        cash += gross - gross * pos[cik]['rate']; del pos[cik]
            if seed is None:
                picks = [c for c in qualifiers_at(F, month) if c not in pos]
                if topn: picks = picks[:topn]
            else:
                nat = qualifiers_at(F, month)
                n_nat = len([c for c in nat if c not in pos])
                if topn: n_nat = min(n_nat, topn)
                poolp = [c for c in pool_at(F, month) if c not in pos and c not in set(nat)]
                rng = random.Random(seed * 100003 + F * 17 + m)
                rng.shuffle(poolp)
                picks = poolp[:n_nat]
            if picks and cash > 0:
                w = cash / len(picks)
                for cik in picks:
                    row = next(r for r in D.pool[F] if r['cik'] == cik)
                    p = D.price(cik, month)
                    cap = row['shares'] * p[1] * row['sf']
                    rate = R.cost_rate(cap)
                    total_costs += w * rate
                    pos[cik] = {'shares': (w - w * rate) / p[0], 'entry': month,
                                'entry_adj': p[0], 'rate': rate}
                cash = 0.0
        if exits == 'native' or floor:
            for cik in list(pos):
                p = D.price(cik, month)
                if not p: continue
                age = (y - int(pos[cik]['entry'][:4])) * 12 + (m - int(pos[cik]['entry'][5:7]))
                if p[0] >= 1.5 * pos[cik]['entry_adj'] or age >= 36:
                    gross = pos[cik]['shares'] * p[0]
                    total_costs += gross * pos[cik]['rate']
                    cash += gross - gross * pos[cik]['rate']; del pos[cik]
        val = cash
        for cik, pp in pos.items():
            a = D.adj(cik, month)
            if a is None:
                s = D.px[cik]; prev = [k for k in s if k < month]
                a = s[max(prev)][0] if prev else pp['entry_adj']
            val += pp['shares'] * a
        curve.append([month, round(val, 2)])
        if floor and val <= 85.0:
            halted = True
            cash = val; pos = {}
            curve[-1][1] = round(cash, 2)
            # stay in cash to the end
            for mm in timeline[timeline.index(month) + 1:]:
                curve.append([mm, round(cash, 2)])
            break
    final = cash
    for cik, pp in pos.items():
        lm = D.last_month(cik)
        if lm is None: continue
        a = D.adj(cik, lm)
        gross = pp['shares'] * a
        final += gross - gross * pp['rate']
        total_costs += gross * pp['rate']
    spy_a = D.spy.get(start); spy_b = D.spy.get('2026-06')
    return {'final': round(final, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'halted': halted,
            'spy_final_same_window': round(100 * spy_b / spy_a, 2) if spy_a and spy_b else None}

def main():
    global D
    R.D = R.Data()
    D = R.D
    annual = [(F, R.ym(F, 6)) for F in range(2016, 2026)]
    semiannual = []
    for F in range(2016, 2026):
        semiannual.append((F, R.ym(F, 6)))
        if F <= 2025: semiannual.append((F, R.ym(F, 12)))
    semiannual.sort(key=lambda t: t[1])
    cells = {
        'A1_annual_all_native': dict(form_months=annual),
        'A2_annual_top10_native': dict(form_months=annual, topn=10),
        'A3_semiannual_all_native': dict(form_months=semiannual),
        'A4_annual_all_annualonly': dict(form_months=annual, exits='annual'),
        'A5_annual_all_housefloor': dict(form_months=annual, floor=True),
    }
    out = {}
    for name, kw in cells.items():
        r = simulate(**kw)
        r['period_stats'] = R.period_stats(r['curve'])
        twins = []
        for seed in range(1, 21):
            twins.append(simulate(seed=seed, **kw)['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        out[name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'],
              'placebos', r['placebos_beaten'], '/20', 'halted', r['halted'], flush=True)
    os.makedirs(os.path.join(R.HERE, 'grid'), exist_ok=True)
    json.dump(out, open(os.path.join(R.HERE, 'grid', 'grid_results.json'), 'w'), indent=1)
    print('saved grid/grid_results.json', flush=True)

if __name__ == '__main__':
    main()
