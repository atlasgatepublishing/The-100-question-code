#!/usr/bin/env python3
"""hunt-tobin-q — numpy timer sim. Signal at close t earns t->t+1 (close-to-close
execution convention for this gauge timer, stated in RESULTS). Simulation only."""
import json, os, sys, random
S7 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S7)
import numpy as np
from engine import period_stats, max_dd, ROADS, CHAMP, SPYREF
from datetime import date, timedelta

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
z = np.load(os.path.join(S7, "prices_cache.npz"))
CAL = list(z["dates"]); TKS = list(z["tks"]); si_ = TKS.index("SPY")
SPYC = z["C"][:, si_].astype(float)
valid = SPYC > 0
dates = [d for d, v in zip(CAL, valid) if v]
px = SPYC[valid]

def timer_sim(dates, px, state, start, end, cost=0.001, fee=0.01, floor=False):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    eq = 100.0; curve = []; pos = 0; costs = 0.0; orders = 0
    halts = 0; halt_until = ""; ended = False; invested = 0
    for k, i in enumerate(idx):
        curve.append((dates[i], eq))
        if pos != 0: invested += 1
        if floor and not ended and dates[i] > halt_until and eq <= 85.0:
            if pos != 0: eq *= (1 - cost); costs += eq * cost; pos = 0; orders += 1
            halts += 1
            if halts >= 2: ended = True
            else: halt_until = (date.fromisoformat(dates[i]) + timedelta(days=90)).isoformat()
            curve[-1] = (dates[i], eq)
        if k + 1 >= len(idx): break
        want = state[i]
        if want != pos and not ended and dates[i] >= halt_until:
            if pos != 0: eq *= (1 - cost); costs += eq * cost + fee; orders += 1
            if want != 0: eq *= (1 - cost); costs += eq * cost; orders += 1
            pos = want
        if pos != 0:
            eq *= px[idx[k+1]] / px[i]
    return {"final": round(eq, 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "orders": orders, "max_dd_pct": max_dd(curve),
            "halts": halts, "invested_share": round(invested / max(1, len(curve)), 3)}

def bh(dates, px, start, end, cost=0.001, fee=0.01):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    sh = 100 * (1 - cost) / px[idx[0]]
    curve = [(dates[i], sh * px[i]) for i in idx]
    return {"final": round(sh * px[idx[-1]] * (1 - cost) - fee, 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "max_dd_pct": max_dd(curve)}

QRAW = """2009-01-01 79.6518807827
2009-04-01 95.4040724950
2009-07-01 104.7156448356
2009-10-01 110.7038681305
2010-01-01 112.4955614000
2010-04-01 100.5084985255
2010-07-01 107.5560579845
2010-10-01 128.0198261596
2011-01-01 131.1260429510
2011-04-01 131.0719726225
2011-07-01 121.4595236187
2011-10-01 128.2355011993
2012-01-01 136.2136925040
2012-04-01 134.2537715040
2012-07-01 138.2119543346
2012-10-01 136.6711895380
2013-01-01 149.5965325693
2013-04-01 150.2097222393
2013-07-01 148.7659583732
2013-10-01 154.7437572230
2014-01-01 159.4818997121
2014-04-01 159.2524983114
2014-07-01 159.2197105852
2014-10-01 165.4368919757
2015-01-01 162.7492803668
2015-04-01 158.5165377889
2015-07-01 151.9977158498
2015-10-01 160.0154746126
2016-01-01 165.5948625837
2016-04-01 164.6546063743
2016-07-01 161.7153966700
2016-10-01 161.6183867868
2017-01-01 167.4941479085
2017-04-01 160.1990464373
2017-07-01 162.1450064744
2017-10-01 164.6621624356
2018-01-01 163.2201929917
2018-04-01 168.2234612571
2018-07-01 176.3717867178
2018-10-01 159.4016119672
2019-01-01 172.2478446511
2019-04-01 168.0743411298
2019-07-01 167.9587647688
2019-10-01 175.1845749993
2020-01-01 143.9665550129
2020-04-01 169.8670287098
2020-07-01 177.7621547615
2020-10-01 189.6081038563
2021-01-01 196.4679869629
2021-04-01 201.3666017001
2021-07-01 190.7166973174
2021-10-01 196.5993731848
2022-01-01 191.7948916727
2022-04-01 167.4595121196
2022-07-01 162.2278160506
2022-10-01 164.9459670081
2023-01-01 171.6998406568
2023-04-01 179.0266055817
2023-07-01 175.5689079838
2023-10-01 191.2681252854
2024-01-01 202.7847413661
2024-04-01 205.5917597811
2024-07-01 215.1969254550
2024-10-01 217.7710907137
2025-01-01 210.5925995460
2025-04-01 221.7263833231
2025-07-01 225.0676437796
2025-10-01 223.8196816833
2026-01-01 214.8279903412
2026-04-01 242.3061150927"""
def qend(qstart):
    y, m = int(qstart[:4]), int(qstart[5:7])
    em = m + 2; ey = y
    if em == 12: nxt = date(ey + 1, 1, 1)
    else: nxt = date(ey, em + 1, 1)
    return nxt - timedelta(days=1)
quarters = []
for line in QRAW.strip().split("\n"):
    d, v = line.split()
    quarters.append(((qend(d) + timedelta(days=75)).isoformat(), float(v) / 100.0))
quarters.sort()
def q_state(dates, thresh=1.0):
    st = [0] * len(dates); qi = 0; cur = 0
    for i, d in enumerate(dates):
        while qi < len(quarters) and quarters[qi][0] <= d:
            cur = 1 if quarters[qi][1] < thresh else 0; qi += 1
        st[i] = cur
    return st
resq = {"family": "hunt-tobin-q", "series": "FRED NCBCEPNW / 100 (Z.1 nonfinancial corporate equities as % of net worth)",
        "execution_note": "quarterly check on first trading day >=75 days after quarter-end (spec); state applied close-to-close (earns t->t+1) in this implementation",
        "roads": {}}
stq = q_state(dates)
for road, (a, b) in ROADS.items():
    nat = timer_sim(dates, px, stq, a, b); hou = timer_sim(dates, px, stq, a, b, floor=True)
    bhh = bh(dates, px, a, b)
    rng = random.Random(13); pb = []
    for s in range(20):
        th = rng.uniform(0.8, 2.2)
        pb.append(timer_sim(dates, px, q_state(dates, th), a, b)["final"])
    resq["roads"][road] = {"native": nat, "house": hou, "spy_buy_hold": bhh, "placebos_20_perturbed_threshold": pb,
                           "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                           "period_stats_monthly_native": period_stats(nat["curve"], "monthly"),
                           "in_market_share": nat["invested_share"], "champion_vm": CHAMP[road], "spy_ref": SPYREF[road]}
    print("TOBINQ", road, nat["final"], "inmkt", nat["invested_share"], "BH", bhh["final"], "beaten", resq["roads"][road]["placebos_beaten"], flush=True)
# BTC external gate
import csv as _csv
brows = []
with open(os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data/BTC-USD.csv")) as f:
    r = _csv.DictReader(f)
    for row in r: brows.append((row["date"], float(row["close"])))
bdates = [x[0] for x in brows]; bpx = np.array([x[1] for x in brows])
stqb = q_state(bdates)
resq["btc_external_gate"] = {}
for road, (a, b) in {"FULL": ("2014-09-17", "2026-11-20"), "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}.items():
    nat = timer_sim(bdates, bpx, stqb, a, b, cost=0.006, fee=0.0)
    bhh = bh(bdates, bpx, a, b, cost=0.006, fee=0.0)
    resq["btc_external_gate"][road] = {"native": nat, "btc_buy_hold": bhh}
    print("TOBINQ-BTC", road, nat["final"], "BH", bhh["final"], flush=True)
json.dump(resq, open(f"{BASE}/hunt-tobin-q/results.json", "w"), indent=1)
print("tobin2 done")
