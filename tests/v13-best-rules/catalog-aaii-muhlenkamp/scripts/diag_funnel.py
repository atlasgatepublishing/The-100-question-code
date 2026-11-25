#!/usr/bin/env python3
"""Counts-only funnel diagnostic (NO returns computed). Run BEFORE freezing spec.
Counts per June formation: base pool, each published leg individually,
cumulative published stack, and candidate core constructions."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chassis as ch

def legs(F):
    med_eps = ch.ind_median(F['eps_cagr5'], F['sic2'])
    med_nm = ch.ind_median(F['netm'], F['sic2'])
    med_la = ch.ind_median(F['lia_at'], F['sic2'])
    L = {}
    L['base_nonOTC'] = F['otc'] == 0
    L['roe_cur>12'] = F['roe'] > 0.12
    L['roe5>12'] = F['roe5'] > 0.12
    L['pe<17'] = (F['pe'] > 0) & (F['pe'] < 17)
    L['epsg>0 & >=indmed'] = (F['eps_cagr5'] > 0) & (F['eps_cagr5'] >= med_eps)
    L['salesg>=epsg'] = F['rev_cagr5'] >= F['eps_cagr5']
    L['netm>indmed'] = F['netm'] > med_nm
    L['lia<indmed'] = F['lia_at'] < med_la
    L['fcf-div>0'] = F['fcf'] - F['div'] > 0
    # candidate core pieces
    L['roe_cur>=14'] = F['roe'] >= 0.14
    L['pe<=roe_pct'] = (F['pe'] > 0) & (F['pe'] <= F['roe'] * 100)
    L['fcf>0'] = F['fcf'] > 0
    return L

order = ['roe_cur>12','roe5>12','pe<17','epsg>0 & >=indmed','salesg>=epsg','netm>indmed','lia<indmed','fcf-div>0']
print(f"{'year':<6}{'base':>6}" + ''.join(f"{k:>18}" for k in order) + f"{'FULL':>6}{'CORE14':>8}{'CORE14+F':>9}")
for y in range(2016, 2026):
    F = ch.features(f'{y:04d}-06')
    L = legs(F)
    base = L['base_nonOTC']
    indiv = [int((base & L[k]).sum()) for k in order]
    cum = base.copy()
    for k in order: cum &= L[k]
    core = base & L['roe_cur>=14'] & L['roe5>12'] & L['pe<=roe_pct']
    coref = core & L['fcf-div>0']
    print(f"{y:<6}{int(base.sum()):>6}" + ''.join(f"{v:>18}" for v in indiv) + f"{int(cum.sum()):>6}{int(core.sum()):>8}{int(coref.sum()):>9}")
