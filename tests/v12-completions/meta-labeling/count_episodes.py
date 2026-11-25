#!/usr/bin/env python3
"""Count QM-weekly primary EPISODES (entry events) from the v10 engine's own
selection logic, read-only imports. An episode = a maximal run of consecutive
weekly selection dates where a name is in the top-5 picks = one primary bet."""
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "qm", "/home/hatch/workspace/stock-app/backtests/v10-retest/quality-momentum/qm_v10.py")
qm = importlib.util.module_from_spec(spec); spec.loader.exec_module(qm)

quality = qm.load_quality()
bars = {t: qm.load_bars_full(t) for t in qm.UNIVERSE + ["SPY"]}
pb = qm.PriceBook(bars)
ws, we = "2013-01-02", "2026-11-20"
sel = qm.cadence_dates(pb, "weekly", ws, we)
print("weekly selection dates:", len(sel), sel[0], "->", sel[-1])

episodes = []  # (ticker, first_sel_date, last_sel_date)
prev = {}
for d in sel:
    scores = {}
    for t in qm.UNIVERSE:
        q = qm.quality_at(quality.get(t, []), d)
        if q is None: continue
        bl = pb.bars.get(t, []); didx = pb.tidx.get(t, {}).get(d)
        if didx is None or didx < 253: continue
        mom = bl[didx-21]["c"]/bl[didx-252]["c"] - 1.0
        scores[t] = (q[2], mom)
    if len(scores) < 5: continue
    qr = qm.percentile_ranks({t: v[0] for t, v in scores.items()})
    mr = qm.percentile_ranks({t: v[1] for t, v in scores.items()})
    combined = {t: (qr[t]+mr[t])/2.0 for t in scores}
    picks = sorted(combined, key=lambda t: -combined[t])[:5]
    cur = {}
    for t in picks:
        if t in prev: cur[t] = prev[t]; cur[t][2] = d
        else: cur[t] = [t, d, d]
    for t, ep in prev.items():
        if t not in cur: episodes.append(tuple(ep))
    prev = cur
for t, ep in prev.items(): episodes.append(tuple(ep))
episodes.sort(key=lambda e: e[1])
print("total episodes (entry events) 2016-11-21..2026-11-20:", len(episodes))
from collections import Counter
by_entry_year = Counter(e[1][:4] for e in episodes)
print("episodes by entry year:", dict(sorted(by_entry_year.items())))
# training pools: episodes whose episode ENDS (label resolves at exit, ~week after last sel) before Jan 1 of OOS year
for oos in ("2021","2022","2023"):
    n = sum(1 for e in episodes if e[2] < oos+"-01-01")
    print(f"episodes fully resolved before {oos}-01-01 (train pool):", n)
print("total name-week picks:", sum(1 for _ in sel)*5)
