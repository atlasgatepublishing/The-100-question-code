#!/usr/bin/env python3
"""
MIDPOINT SWITCH B (candidate) — longest honest run.

Switch B is the champion until the halfway point of the run window,
then the champion x N-F3 50/50 sleeve blend. Its inputs are the
champion's and N-F3's, so its earliest honest start is the champion's:
2010-01-04, on the 2010 point-in-time pond. (Its N-F3 sleeve only
begins at the switch — first quarterly selection on/after the window
halfway date, 2018-06-12 -> executed 2018-07-02 — by which time SBC
coverage is the mature coverage phase 0 already validated.) The
halfway trigger is the frozen rule from the original switch test,
applied to this window exactly as the original applied it to its own.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

START, END = "2010-01-04", C.END
TRIGGER = E.halfway_on_or_after(START, END)

pond = E.pond_at(START)["pond"]
print(f"pond: {pond}", flush=True)
print(f"switch trigger (window halfway): {TRIGGER}", flush=True)
res = E.switch_v9(pond, START, END, TRIGGER)
print(f"SWITCH v9: final ${res['final']:,.2f} halts={res['halts']} "
      f"restart={res['restart']} switch={res['switch']} "
      f"spy=${res['spy_final']:,.2f}", flush=True)
out = {"pond": pond, "trigger": TRIGGER, "run": res}
with open(os.path.join(HERE, "results_switch.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("saved results_switch.json", flush=True)
