#!/usr/bin/env python3
"""Diagnostic only: find the names/months driving extreme value-sleeve
monthly returns in the constructed run. Changes nothing."""
import importlib.util, os, json
spec = importlib.util.spec_from_file_location("rt", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_twosleeve_constructed.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
R.D = R.Data()
D = R.D
res = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")))
rets = res["windows"]["FULL"]["sleeve_monthly_returns"]
forms = []
m = "2017-01"
while m <= "2026-09":
    forms.append(m); m = R.ym_next(m)
# sleeve_rets[i] is return from forms[i] to forms[i+1]
idx = sorted(range(len(rets)), key=lambda i: -abs(rets[i][0]))[:8]
for i in idx:
    print("value ret", forms[i], "->", forms[i+1], round(rets[i][0], 3), "mom", round(rets[i][1], 3))
    vp, mp, caps = R.pools(forms[i])
    picks, n = R.tercile_top(vp)
    rows = []
    for c in picks:
        a, b = D.adj(c, forms[i]), D.adj(c, forms[i+1])
        if a and b: rows.append((b / a - 1, D.cand[c]["ticker"], round(a, 4), round(b, 4)))
    rows.sort(reverse=True)
    for r in rows[:5]: print("   ", r)
