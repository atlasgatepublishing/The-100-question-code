#!/usr/bin/env python3
"""
LAZY PRICES — earliest honest start, measured from the era signals.

Lazy Prices scores a name at a selection date if at least one
consecutive-10-K similarity exists for it by then (the engine's own
scorable definition — no staleness gate). Its earliest honest start
is the first quarterly selection date where >= 25 of the 30 pond names
are scorable — the same 25-of-30 bar the long-hold test used to
certify 2010-01-04 for the champion — with the pond rebuilt
point-in-time at that date. The era signal build fetched 10-Ks from
2007 so that a 2010 start rests on real FY2007/FY2008 document pairs,
exactly as gap-a5's 2016 fetch-back made its first signals real.
Known artifact, documented never patched: GOOG's signal freezes at
the FY2014-vs-FY2013 document pair, because Google Inc (CIK 1288776)
filed its last 10-K for FY2014 and Alphabet files under a different
CIK from FY2015 — the engine has no staleness gate, so the frozen
score simply keeps competing, as it does in the published runs.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

END = C.END
LZ = os.path.join(C.MYDATA, "lazy")
with open(os.path.join(LZ, "similarities_era.json")) as f:
    era = json.load(f)
signals, census = era["signals"], era["census"]
champ = C.champ
_P = E.pool_data()


class _Cal:
    dates = _P["spy_dates"]


CANDIDATES = (champ.quarter_selection_dates(_Cal(), "2010-01-04",
                                            "2010-12-31")
              + champ.quarter_selection_dates(_Cal(), "2011-01-01",
                                              "2012-12-31"))
scan, chosen = [], None
for cand in CANDIDATES:
    pond = E.pond_at(cand)["pond"]
    scorable = [t for t in pond
                if any(a < cand for a, _, _ in signals.get(t, []))]
    scan.append({"date": cand, "pond": pond,
                 "n_scorable": len(scorable),
                 "unscorable": [t for t in pond if t not in scorable]})
    print(f"{cand}: scorable {len(scorable)}/30", flush=True)
    if len(scorable) >= 25:
        chosen = scan[-1]
        break
if chosen is None:
    raise SystemExit("no candidate reached 25/30 — report, do not patch")
start, pond = chosen["date"], chosen["pond"]
print(f"START: {start}; pond={pond}", flush=True)
print(f"GOOG similarities: {len(signals.get('GOOG', []))}, last "
      f"acceptance {signals.get('GOOG', [[None]])[-1][0]}", flush=True)

res = E.lazy_v9(pond, signals, start, END)
print(f"LAZY v9: final ${res['final']:,.2f} halts={res['halts']} "
      f"restart={res['restart']} spy=${res['spy_final']:,.2f}",
      flush=True)
out = {"census": census, "scan": scan, "start": start, "pond": pond,
       "run": res}
with open(os.path.join(HERE, "results_lazy.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("saved results_lazy.json", flush=True)
