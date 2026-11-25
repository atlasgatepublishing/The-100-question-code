#!/usr/bin/env python3
"""AAII Sentiment contrarian event timer — SPEC-FROZEN exact (CONSTRUCTED).
Event: weekly AAII print with BEARISH >= 50.0%. Week ends Wednesday (CSV date);
published Thursday; buy SPY at the next trading day's open AFTER the Thursday
publication. Hold exactly 26 weeks; exit at open of first trading day after the
26-week anniversary. No stacking / no extension. Data: AAII's own spreadsheet as
mirrored in the psinopoli/AAII-Sentiment GitHub repo (AAII.com direct file is
bot-walled; the mirror is a copy of AAII's file, values never revised; ends
2024-06-27). Native no floor; house v9. BTC: same events, external, close-exec.
NOTE: as run, common.py and the data caches lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script. See HUNT-LOG.md."""
import csv, json, os, random, sys
from datetime import datetime, timedelta
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-aaii-sentiment")
rows = []
for r in csv.reader(open("/tmp/hunt1/aaii.csv")):
    if not r or not r[0] or not r[0][0].isdigit(): continue
    try:
        dt = datetime.strptime(r[0].strip(), "%m-%d-%y")
        rows.append((dt.strftime("%Y-%m-%d"), float(r[1]) * 100, float(r[3]) * 100))
    except Exception: continue
rows.sort()
DATA_END = rows[-1][0]
events = [d for d, bull, bear in rows if bear >= 50.0]

spy = load_pxfull("SPY"); dates = [b["d"] for b in spy]

def build_states(ev_list, bars_dates):
    st = [0] * len(bars_dates)
    holds = []
    for ev in ev_list:
        pub = (datetime.fromisoformat(ev) + timedelta(days=1)).strftime("%Y-%m-%d")  # Thursday
        cand = [d for d in bars_dates if d > pub]
        if not cand: continue
        entry = cand[0]
        if any(h[0] <= entry and (h[1] is None or entry < h[1]) for h in holds): continue
        anniv = (datetime.fromisoformat(entry) + timedelta(weeks=26)).strftime("%Y-%m-%d")
        exc = [d for d in bars_dates if d > anniv]
        exitd = exc[0] if exc else None
        holds.append((entry, exitd))
    for entry, exitd in holds:
        for i, d in enumerate(bars_dates):
            if entry <= d and (exitd is None or d < exitd): st[i] = 1
    return st, holds

out = {"family": "hunt-aaii-sentiment", "data_end": DATA_END, "events_all": events,
       "holdings_grid": "NOT-APPLICABLE — event timer, no selection", "stocks": {}, "btc_external": {}}
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; bd = [b["d"] for b in bars]
    ev_road = [ev for ev in events if ev < e]
    st, holds = build_states(ev_road, bd)
    nat = sim_open_exec(bars, st); hou = sim_open_exec(bars, st, house=True)
    nev = len(holds)
    pls = []
    for sd in range(1, 21):
        rng = random.Random(1000 + sd)
        pool = [d for d in dates if s <= d <= e]
        fake = sorted(rng.choice(pool) for _ in range(nev)) if nev else []
        fst, _ = build_states(fake, bd)
        pls.append(sim_open_exec(bars, fst)["final"])
    out["stocks"][road] = {"native": nat, "house": hou, "spy_buyhold": round(buyhold_open(bars), 2),
                           "champion_vm": CHAMP[road], "events_in_road": nev, "holds": holds,
                           "placebos_beaten": sum(1 for p in pls if nat["final"] > p),
                           "placebo_finals": [round(p, 2) for p in pls],
                           "periods_monthly": period_stats(nat["curve"], "monthly")}
btc = load_cm("btc"); bd_all = [b["d"] for b in btc]
st_all, holds_all = build_states(events, bd_all)
for wname, (s, e) in {"FULL": ("2010-07-18", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}.items():
    idx = [i for i, b in enumerate(btc) if s <= b["d"] <= e]
    bars = [btc[i] for i in idx]; st = [st_all[i] for i in idx]
    nat = sim_close_exec(bars, st)
    out["btc_external"][wname] = {"native": nat, "btc_buyhold": round(buyhold_close(bars), 2),
                                  "periods_monthly": period_stats(nat["curve"], "monthly")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print({r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"], v["events_in_road"]) for r, v in out["stocks"].items()})
