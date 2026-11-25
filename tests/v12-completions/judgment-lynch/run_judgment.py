#!/usr/bin/env python3
"""Lynch categorization & story — JUDGMENT-CONSTRUCTED run.
Spec: JUDGMENT-SPEC.md (frozen 2026-11-22, before this run). Simulation only.
Chassis: v11 _w04_broad_data (read-only). Vanished prices -> ZERO.
"""
import json, os, sys, math, random, statistics
sys.path.insert(0, os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'))
import engine_w04 as W

OUT = os.path.dirname(os.path.abspath(__file__))
W.D = W.Data()
D = W.D
ym = W.ym

# ---------- EPS history (NI / shares, split-corrected per formation) ----------
NI = {y: W.load_frame(f'NetIncomeLoss_{y}D.json') for y in range(2014, 2026)}
SH = {y: W.load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}

def eps_series(cik, F):
    """EPS on F-1 share basis for years <= F-1."""
    raw = {}
    for y in range(2014, F):
        ni, sh = NI[y].get(cik), SH[y].get(cik)
        if ni is not None and sh: raw[y] = ni / sh
    if not raw: return {}
    # split factors between consecutive available years
    yrs = sorted(raw)
    adj = {}
    for i, y in enumerate(yrs):
        f = 1.0
        for y0, y1 in zip(yrs[i:], yrs[i+1:]):
            r = SH[y1][cik] / SH[y0][cik]
            if r >= 1.6 or r <= 0.625: f *= r
        adj[y] = raw[y] / f if f else raw[y]
    return adj

def price_adj(cik, month):
    """Adj price at month; last print if gap; 0.0 if series has ENDED before month; None if never started."""
    s = D.px.get(cik)
    if not s: return None
    if month in s: return s[month][0]
    prev = [m for m in s if m < month]
    if not prev: return None
    last = max(s)
    if month > last: return 0.0          # vanished -> ZERO (program rule)
    return s[max(prev)][0]

def last_price_month(cik):
    s = D.px.get(cik)
    return max(s) if s else None

CYCLICAL_SIC4 = set()
for p in ('331','332','333','334','335','336','339'):
    pass
def is_cyclical_sic(sic):
    s4 = f'{sic:04d}'
    if s4[:2] == '33' or s4[:2] == '10': return True
    if s4[:2] == '26': return True
    if s4 in ('2812','2813','2816','2819','2821','2822','2823','2824','2861','2865','2869','2873','2874','2875','2879','2891','2892','2893','2895','2899'): return True
    if s4 == '2911' or s4 == '3011' or s4 == '4512': return True
    if s4[:3] == '371': return True
    return False

_snap_cache = {}
def categorize(F):
    if F in _snap_cache: return _snap_cache[F]
    s = W.snapshot(F)
    out = {}
    for cik, v in s.items():
        eps = eps_series(cik, F)
        yrs = [y for y in range(F-6, F) if y in eps]
        if F-1 not in eps: continue
        eps_last = eps[F-1]
        ni_hist = {y: NI[y].get(cik) for y in range(2014, F)}
        cap, eq, ltd, ltd0, cash = v['cap'], v['equity'], v['ltd'], v['ltd0'], v['cash']
        px_raw = D.price(cik, ym(F, 6), adj=False)
        if not cap or cap < 50e6 or not px_raw: continue
        # growth over longest window <=5y ending F-1, min 3y
        g = None; grower = False
        for span in (5, 4, 3):
            y0 = F - 1 - span
            if y0 in eps and eps[y0] > 0 and eps_last > 0:
                g = (eps_last / eps[y0]) ** (1.0 / span) - 1
                grower = all(y in eps and eps[y] > 0 for y in range(y0, F))
                break
        g1 = None
        if F-2 in eps and eps[F-2] > 0 and eps_last > 0: g1 = eps_last / eps[F-2] - 1
        pe = (px_raw / eps_last) if eps_last > 0 else None
        peg = (pe / (g * 100)) if (pe and g and g > 0) else None
        de = (ltd / eq) if (ltd is not None and eq and eq > 0) else None
        pb = (cap / eq) if (eq and eq > 0) else None
        loss_recent = any((ni_hist.get(y) or 0) < 0 for y in (F-4, F-3, F-2))
        cat = None
        # 1 TURNAROUND
        if (v['ni'] or 0) > 0 and eps_last > 0 and loss_recent:
            months = [ym(y, m) for y in (F-3, F-2, F-1, F) for m in range(1, 13) if ym(y, m) < ym(F, 6)]
            prints = [D.px.get(cik, {}).get(m, (None,))[0] for m in months]
            prints = [p for p in prints if p]
            surv = (ltd is not None and ltd0 is not None and ltd <= ltd0) or (cash is not None and ltd is not None and cash >= 0.5 * ltd)
            if prints and v['px_adj'] and v['px_adj'] <= 0.6 * max(prints) and surv: cat = 'TURNAROUND'
        # 2 CYCLICAL
        if cat is None and is_cyclical_sic(v['sic']) and eps_last > 0 and pe and pe <= 20 and g1 is not None and g1 > 0:
            vals = [eps[y] for y in yrs if y in eps]
            cyc = False
            if vals:
                pos = [x for x in vals if x > 0]
                if len(pos) >= 3 and max(pos) / min(pos) >= 2: cyc = True
                if any(x <= 0 for x in vals): cyc = True
            if cyc: cat = 'CYCLICAL'
        # 3 FAST
        if cat is None and grower and g is not None and 0.20 <= g <= 0.50 and cap <= 10e9 and de is not None and de <= 1.0 and peg is not None and peg <= 1.0: cat = 'FAST'
        # 4 STALWART
        if cat is None and grower and g is not None and 0.10 <= g < 0.20 and cap >= 2e9 and peg is not None and peg <= 1.0: cat = 'STALWART'
        # 5 SLOW
        if cat is None and grower and g is not None and 0 < g < 0.10 and cap >= 1e9 and pe and pe <= 15: cat = 'SLOW'
        # 6 ASSET
        if cat is None and pb is not None and pb < 1.0 and (v['ni'] or 0) > 0 and pe and pe <= 12: cat = 'ASSET'
        if cat is None: continue
        score = peg if (g is not None and g > 0.02 and peg) else (pe / 10 if pe else 99.0)
        out[cik] = dict(cat=cat, score=score, g=g, g1=g1, pe=pe, peg=peg, pb=pb, cap=cap,
                        ltd=ltd, ltd0=ltd0, ni=v['ni'], ticker=v['ticker'], px_adj=v['px_adj'],
                        eps_last=eps_last, loss_recent=loss_recent,
                        eps_high5=(max([eps[y] for y in yrs if y in eps]) if yrs else None))
    _snap_cache[F] = out
    return out

def cost_rate(cap):
    return W.cost_rate(cap)

def run(formations, count, seed=None):
    cash = 100.0; pos = {}; entry = {}; held_cat = {}
    curve = []; total_costs = 0.0; n_orders = 0; floored = None; cat_counts = {}
    def value(month):
        tot = cash
        for c, sh in pos.items():
            p = price_adj(c, month)
            if p: tot += sh * p
        return tot
    for F in formations:
        elig = categorize(F)
        if seed is not None:
            rng = random.Random(seed * 10007 + F)
            keys = list(elig.keys()); rng.shuffle(keys)
            n = len(keys) if count is None else min(count, len(keys))
            target = keys[:n]
        else:
            # exits for incumbents (L7)
            sell = set()
            for c in list(pos):
                if c not in elig: sell.add(c); continue
                hc, nv = held_cat.get(c), elig[c]
                if hc == 'FAST' and (nv['g'] is None or nv['g'] < 0.10 or (nv['peg'] is not None and nv['peg'] >= 2.0)): sell.add(c)
                elif hc == 'TURNAROUND' and (not nv['loss_recent']) and nv['pe'] and nv['pe'] >= 15: sell.add(c)
                elif hc == 'CYCLICAL' and nv['eps_high5'] and nv['eps_last'] >= nv['eps_high5'] and nv['pe'] and nv['pe'] <= 8: sell.add(c)
                elif hc == 'ASSET' and nv['pb'] is not None and nv['pb'] >= 1.2: sell.add(c)
            ranked = sorted(elig, key=lambda c: (elig[c]['score'], elig[c]['ticker']))
            n = len(ranked) if count is None else min(count, len(ranked))
            target = [c for c in ranked[:n] if c not in sell]
            # backfill if exits removed target names
            if len(target) < n:
                for c in ranked[n:]:
                    if c not in sell and c not in target: target.append(c)
                    if len(target) >= n: break
        tset = set(target)
        E = value(ym(F, 6))
        tw = E / len(tset) if tset else 0.0
        # sells first
        for c in list(pos):
            p = price_adj(c, ym(F, 6)) or 0.0
            cur = pos[c] * p
            want = tw if c in tset else 0.0
            if cur > want:
                amt = cur - want; rate = cost_rate(elig.get(c, {}).get('cap') or (categorize(F-1).get(c, {}).get('cap') if F-1 in _snap_cache else None))
                cost = amt * rate; total_costs += cost; n_orders += 1
                cash += amt - cost
                if want <= 0 or p == 0: del pos[c]; entry.pop(c, None); held_cat.pop(c, None)
                else: pos[c] = want / p
        # buys
        for c in target:
            p = price_adj(c, ym(F, 6))
            if not p: continue
            cur = pos.get(c, 0.0) * p
            deficit = tw - cur
            if deficit <= 0: continue
            rate = cost_rate(elig[c]['cap']); amt = min(deficit, cash / (1 + rate)) if cash > 0 else 0.0
            if amt <= 0: continue
            cost = amt * rate; total_costs += cost; n_orders += 1; cash -= amt + cost
            old_sh = pos.get(c, 0.0)
            if old_sh > 0 and c in entry: entry[c] = (entry[c] * old_sh + p * (amt / p)) / (old_sh + amt / p)
            else: entry[c] = p
            pos[c] = old_sh + amt / p
            held_cat[c] = elig[c]['cat']; cat_counts[elig[c]['cat']] = cat_counts.get(elig[c]['cat'], 0) + 1
        for c in pos:
            if c in elig: held_cat[c] = elig[c]['cat']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F+1, m) for m in range(1, 7)]
        for mm in months:
            if seed is None:  # L8 monthly rotation sells
                for c in list(pos):
                    if held_cat.get(c) in ('STALWART', 'SLOW') and c in entry:
                        p = price_adj(c, mm)
                        if p and entry[c] and p >= 1.40 * entry[c]:
                            gross = pos[c] * p; rate = cost_rate(elig.get(c, {}).get('cap') or 1e9)
                            cost = gross * rate; total_costs += cost; n_orders += 1
                            cash += gross - cost; del pos[c]; entry.pop(c, None); held_cat.pop(c, None)
            v = value(mm); curve.append([mm, round(v, 2)])
            if v <= 85.0 and floored is None:
                floored = mm
                # liquidate at current prints (vanished = 0 already in value)
                liq_cost = 0.0
                for c, sh in pos.items():
                    p = price_adj(c, mm) or 0.0; liq_cost += sh * p * 0.0075
                cash = v - liq_cost; total_costs += liq_cost; pos = {}
                curve[-1] = [mm, round(cash, 2)]
                break
        if floored: break
    # final liquidation at last month on curve
    if pos and curve:
        mm = curve[-1][0]; liq = 0.0
        for c, sh in pos.items():
            p = price_adj(c, mm) or 0.0; liq += sh * p * cost_rate(1e9)
        cash = value(mm) - liq; total_costs += liq; pos = {}
        curve[-1] = [mm, round(cash, 2)]
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return dict(final=round(cash, 2), max_dd=round(maxdd, 4), costs=round(total_costs, 2),
                orders=n_orders, floored=floored, curve=curve, cat_counts=cat_counts)

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i+1] / vals[i] - 1 for i in range(len(vals) - 1) if vals[i] > 0]
    if not rets: return {}
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    peak = vals[0]; since = mx_since = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; mx_since = max(mx_since, since)
    return dict(periods=len(rets), pct_positive=round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
                median_period_pct=round(100 * statistics.median(rets), 2),
                best_period_pct=round(100 * max(rets), 2), worst_period_pct=round(100 * min(rets), 2),
                longest_losing_streak=mx, longest_below_high_months=mx_since,
                mean_period_pct_labeled_average=round(100 * statistics.mean(rets), 2))

ROADS = {'DECADE': list(range(2017, 2026)), 'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]
def spy_final(forms):
    a = D.spy.get(ym(forms[0], 6)); b = D.spy.get(ym(forms[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = {'label': 'JUDGMENT-CONSTRUCTED', 'roads': {}}
    for road, forms in ROADS.items():
        if only and road != only: continue
        elig_counts = {F: len(categorize(F)) for F in forms}
        road_out = {'formations': forms, 'eligible_per_year': elig_counts, 'spy_final': spy_final(forms), 'counts': {}}
        for cnt in COUNTS:
            key = 'ALL-ELIGIBLE' if cnt is None else str(cnt)
            r = run(forms, cnt)
            pls = [run(forms, cnt, seed=sd)['final'] for sd in range(1, 21)]
            road_out['counts'][key] = dict(final=r['final'], max_dd=r['max_dd'], costs=r['costs'], orders=r['orders'],
                floored=r['floored'], cat_counts=r['cat_counts'], period_stats=period_stats(r['curve']),
                placebo_median=round(statistics.median(pls), 2), placebo_best=max(pls),
                placebo_seeds_beating_real=sum(1 for x in pls if x > r['final']),
                curve=r['curve'] if key == '5' else None)
            print(road, key, r['final'], 'dd', r['max_dd'], 'plmed', road_out['counts'][key]['placebo_median'], 'floored', r['floored'], flush=True)
        results['roads'][road] = road_out
        print('ROADJSON ' + json.dumps({road: road_out}))
    print('DONE')

if __name__ == '__main__':
    main()
