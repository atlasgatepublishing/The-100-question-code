#!/usr/bin/env python3
"""V13 best-rules Granville OBV per BEST-RULES-SPEC.md (frozen pre-run).
Engine: SPY price trend (close > 200d SMA) is the ONLY entry condition.
OBV (exact published formula) is an exit-only VETO: distribution state
(OBV < its own 50d SMA) exits to cash; re-entry on price alone.
Weekly evaluation: state changes only on the last trading day of a week.
No floor. Program costs via shared chassis simulate(). Placebos: 20
circular shifts of the desired-state series. Simulation only."""
import json, os, sys, statistics, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate, buy_hold, period_stats

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12_SPY = {"LONG": 140.84, "DECADE": 160.63, "CONT": 149.26, "VAL": 127.21}

def sma(xs, m):
    n = len(xs); out = [None] * n; s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= m: s -= xs[i - m]
        if i >= m - 1: out[i] = s / m
    return out

def build_states(bars):
    n = len(bars); obv = [0.0] * n
    for i in range(1, n):
        if bars[i]["c"] > bars[i-1]["c"]: obv[i] = obv[i-1] + bars[i].get("v", 0)
        elif bars[i]["c"] < bars[i-1]["c"]: obv[i] = obv[i-1] - bars[i].get("v", 0)
        else: obv[i] = obv[i-1]
    o50 = sma(obv, 50); p200 = sma([b["c"] for b in bars], 200)
    # last trading day of each ISO week
    lastwk = [False] * n
    for i in range(n):
        wk = datetime.date.fromisoformat(bars[i]["d"]).isocalendar()[:2]
        if i == n - 1: lastwk[i] = True
        else:
            wk2 = datetime.date.fromisoformat(bars[i+1]["d"]).isocalendar()[:2]
            lastwk[i] = wk2 != wk
    st = [0] * n; pos = 0
    for i in range(n):
        if lastwk[i] and o50[i] is not None and p200[i] is not None:
            if pos == 0 and bars[i]["c"] > p200[i]:
                pos = 1                      # entry: price alone, no OBV condition
            elif pos == 1 and (bars[i]["c"] < p200[i] or obv[i] < o50[i]):
                pos = 0                      # exit: price break OR OBV veto
        st[i] = pos
    return st

def main():
    spy = load_bars(os.path.join(PXDIR, "pxfull_SPY.json"))
    st = build_states(spy)
    out = {"family": "hunt-granville-obv", "program": "v13-best-rules",
           "design": "price-trend engine; OBV exit-only veto; weekly eval; no floor",
           "roads": {}}
    for road, (s, e) in ROADS.items():
        r = simulate(spy, st, s, e, "native")
        idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
        expo = round(sum(st[i] for i in idx) / max(len(idx), 1), 3)
        ent = {"final": r["final"], "max_dd": r["max_dd"], "trades": r["trades"],
               "costs": r["costs"], "exposure_share": expo,
               "period_stats_monthly": period_stats(r["curve"], "M"),
               "curve": r["curve"], "spy_buy_hold_chassis": buy_hold(spy, s, e),
               "champion_vm": CHAMP[road], "spy_reference_program": SPYREF[road],
               "v12_spy_timer_native": V12_SPY[road]}
        out["roads"][road] = ent
        print(road, "final", r["final"], "maxdd", r["max_dd"], "trades", r["trades"],
              "expo", expo, flush=True)
    # placebos: 20 circular shifts of the state series, LONG road
    finals = []
    for seed in range(1, 21):
        import random
        rng = random.Random(seed); sh = rng.randint(30, 300)
        pst = st[sh:] + st[:sh]
        finals.append(simulate(spy, pst, *ROADS["LONG"], "native")["final"])
    sysf = out["roads"]["LONG"]["final"]
    out["placebos_LONG"] = {"finals": finals, "median": round(statistics.median(finals), 2),
                            "system_final": sysf,
                            "beats": sum(1 for f in finals if sysf > f)}
    print("placebos LONG", out["placebos_LONG"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
