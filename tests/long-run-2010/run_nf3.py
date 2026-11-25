#!/usr/bin/env python3
"""
N-F3 "PAYING IN STOCK" (candidate) — earliest honest start, MEASURED.

N-F3's signal needs, per name, two full trailing-twelve-month windows
of share-based-compensation intensity (SBC / revenue) a year apart,
built from as-filed XBRL quarters. Early-2010s SBC tagging was thin,
so the start is not assumed: this script scans quarterly selection
dates from 2010-01-04 forward, rebuilding the point-in-time pond at
each candidate date and counting how many of its 30 names the engine
can actually score there. The start rule (fixed before looking at any
result): the earliest candidate where >= 25 of 30 pond names are
scorable — the same 25-of-30 bar the long-hold test used to certify
2010-01-04 for the champion. If the scorable count plateaus below 25
because some companies never tag SBC at all, the fallback is the
earliest date the count reaches its plateau maximum, with the
never-tagging names listed. Then ONE v9 run from that start.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

END = C.END
nf3 = E._nf3_mod()
champ = C.champ
P = E.pool_data()

class _Cal:
    dates = P["spy_dates"]


CANDIDATES = champ.quarter_selection_dates(_Cal(), "2010-01-04",
                                           "2016-12-31")
scan = []
plateau = 0
for cand in CANDIDATES:
    info = E.pond_at(cand)
    pond = info["pond"]
    facts = E.nf3_facts(pond)
    stats = {"direct": 0, "derived": 0}
    scorable, unscorable = [], []
    for t in pond:
        try:
            s = nf3.signal_at(facts[t], cand, stats)
        except Exception:  # noqa
            s = None
        (scorable if s is not None else unscorable).append(t)
    plateau = max(plateau, len(scorable))
    scan.append({"date": cand, "pond": pond, "n_scorable": len(scorable),
                 "unscorable": unscorable})
    print(f"{cand}: scorable {len(scorable)}/30  unscorable={unscorable}",
          flush=True)
    if len(scorable) >= 25:
        break

chosen = next((s for s in scan if s["n_scorable"] >= 25), None)
rule = "earliest candidate with >=25/30 scorable"
if chosen is None:
    chosen = next(s for s in scan if s["n_scorable"] == plateau)
    rule = ("25/30 never reached; plateau maximum "
            f"{plateau}/30 — earliest date at the plateau")
start = chosen["date"]
pond = chosen["pond"]
print(f"START: {start} ({rule}); pond={pond}", flush=True)

res = E.nf3_v9(pond, start, END)
print(f"NF3 v9: final ${res['final']:,.2f} halts={res['halts']} "
      f"restart={res['restart']} spy=${res['spy_final']:,.2f}",
      flush=True)
out = {"scan": scan, "rule": rule, "start": start, "pond": pond,
       "run": res}
with open(os.path.join(HERE, "results_nf3.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("saved results_nf3.json", flush=True)
