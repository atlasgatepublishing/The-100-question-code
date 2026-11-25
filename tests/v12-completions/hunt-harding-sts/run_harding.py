#!/usr/bin/env python3
"""Sy Harding Seasonal Timing Strategy (STS) — frozen form.
Signal on DJIA (^DJI) daily closes, MACD 12/26/9; traded on DIA
(CONSTRUCTED mapping, labeled). Exit leg: earliest exit Apr 20 — if
MACD bearish that day, exit; if bullish, stay until the next bearish
flip, then exit. Entry leg: earliest entry Oct 16 — if MACD bullish,
enter; if bearish, wait for the next bullish flip, then enter. All
other MACD signals ignored. MACD state (ChartSchool codification):
bullish when MACD crosses above its signal line OR above zero;
bearish when it crosses below its signal line OR below zero (state
machine on crosses; initial state from levels). Non-trading-day
leg dates move to the next trading day. Trades at close, program
costs. NATIVE no floor; HOUSE v9 floor. Placebos: 20 seeds, circular
day-shift of the state series per road. Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate, buy_hold, period_stats, ROADS, CHAMP, SPYREF

HERE = os.path.dirname(os.path.abspath(__file__))
dji = load_bars(os.path.join(HERE, "data", "DJI.json"))
dia = load_bars(os.path.join(HERE, "data", "DIA.json"))

def ema(xs, n):
    out = [None] * len(xs); k = 2 / (n + 1); prev = None
    for i, x in enumerate(xs):
        prev = x if prev is None else x * k + prev * (1 - k)
        if i >= n - 1: out[i] = prev
    return out

closes = [b["c"] for b in dji]
e12 = ema(closes, 12); e26 = ema(closes, 26)
macd = [None if (a is None or b is None) else a - b for a, b in zip(e12, e26)]
sig_in = [m if m is not None else 0.0 for m in macd]
sig = ema(sig_in, 9)
# MACD bullish/bearish state machine on crosses
bull = [None] * len(dji)
state = None
for i in range(1, len(dji)):
    if macd[i] is None or sig[i] is None: continue
    if state is None:
        state = (macd[i] > sig[i]) or (macd[i] > 0)
    else:
        cross_up = (macd[i-1] <= sig[i-1] and macd[i] > sig[i]) or (macd[i-1] <= 0 and macd[i] > 0)
        cross_dn = (macd[i-1] >= sig[i-1] and macd[i] < sig[i]) or (macd[i-1] >= 0 and macd[i] < 0)
        if cross_up and not cross_dn: state = True
        elif cross_dn and not cross_up: state = False
    bull[i] = state

# map DJI dates -> DIA index (same trading calendar, align by date)
dia_idx = {b["d"]: i for i, b in enumerate(dia)}
def build_state():
    st = [0] * len(dia)
    phase = "out_wait_oct"   # start out; first leg considered is an entry leg
    pos = 0
    for i, b in enumerate(dji):
        d = b["d"]; md = d[5:]
        if bull[i] is None: continue
        if phase == "out_wait_oct" and md >= "10-16":
            phase = "out_wait_entry"
        if phase == "out_wait_entry":
            if bull[i]: pos = 1; phase = "in_wait_apr"
        elif phase == "in_wait_apr" and md >= "04-20" and d[5:7] in ("04", "05", "06", "07", "08", "09"):
            phase = "in_wait_exit"
        if phase == "in_wait_exit":
            if not bull[i]: pos = 0; phase = "out_wait_oct"
        if d in dia_idx: st[dia_idx[d]] = pos
    # forward-fill any DIA days not in DJI map (rare) with previous state
    for i in range(1, len(st)):
        if dia[i]["d"] not in {b["d"] for b in dji}: st[i] = st[i-1]
    return st

def main():
    out = {"family": "hunt-harding-sts", "vehicle": "DIA (signal on ^DJI)", "roads": {}}
    st = build_state()
    for road, (s, e) in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = simulate(dia, st, s, e, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
            ent[form]["period_stats_annual"] = period_stats(r["curve"], "Y")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["dia_buy_hold"] = buy_hold(dia, s, e)
        ent["champion_vm"] = CHAMP[road]; ent["spy_reference_program"] = SPYREF[road]
        out["roads"][road] = ent
        print(road, "native", ent["native"]["final"], "house", ent["house"]["final"], "dia bh", ent["dia_buy_hold"])
    out["placebos"] = {}
    for road in ("LONG", "VAL"):
        s, e = ROADS[road]
        idx = [i for i, b in enumerate(dia) if s <= b["d"] <= e]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); sh = rng.randint(30, 300)
            seg = [st[i] for i in idx]
            seg = seg[sh:] + seg[:sh]
            pst = list(st)
            for j, i in enumerate(idx): pst[i] = seg[j]
            finals.append(simulate(dia, pst, s, e, "native")["final"])
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
