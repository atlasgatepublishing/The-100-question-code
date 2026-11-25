#!/usr/bin/env python3
"""
COMMON-WINDOW COMPARISON — all five engines, one shared window.

The window is [latest engine start, 2026-11-20]: the longest window
every engine can run honestly. Each engine gets a FRESH $100 pot and
a pond rebuilt point-in-time at the window start (the program's
convention), runs under the same v9 rules, and is compared against
SPY buy-and-hold over the identical window. Switch B's trigger is the
frozen window-relative rule: the halfway date of THIS window.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

END = C.END


def load(name):
    with open(os.path.join(HERE, f"results_{name}.json")) as f:
        return json.load(f)


starts = {"champion": load("champion")["v9"]["start"],
          "basket": load("basket")["run"]["start"],
          "lazy": load("lazy")["start"],
          "nf3": load("nf3")["start"],
          "switch": load("switch")["run"]["start"]}
START = max(starts.values())
print(f"engine starts: {starts} -> common window starts {START}",
      flush=True)
pond = E.pond_at(START)["pond"]
print(f"pond at {START}: {pond}", flush=True)

with open(os.path.join(C.MYDATA, "lazy", "similarities_era.json")) as f:
    signals = json.load(f)["signals"]
facts = E.nf3_facts(pond)
trigger = E.halfway_on_or_after(START, END)
print(f"switch trigger for common window: {trigger}", flush=True)

runs = {}
runs["champion"] = E.champion_v9(pond, START, END)
print(f"champion: ${runs['champion']['final']:,.2f} "
      f"spy ${runs['champion']['spy_final']:,.2f}", flush=True)
runs["basket"] = E.basket_v9(pond, START, END)
print(f"basket: ${runs['basket']['final']:,.2f} "
      f"spy ${runs['basket']['spy_final']:,.2f}", flush=True)
runs["lazy"] = E.lazy_v9(pond, signals, START, END)
print(f"lazy: ${runs['lazy']['final']:,.2f} "
      f"spy ${runs['lazy']['spy_final']:,.2f}", flush=True)
runs["nf3"] = E.nf3_v9(pond, START, END, facts=facts)
print(f"nf3: ${runs['nf3']['final']:,.2f} "
      f"spy ${runs['nf3']['spy_final']:,.2f}", flush=True)
runs["switch"] = E.switch_v9(pond, START, END, trigger, facts=facts)
print(f"switch: ${runs['switch']['final']:,.2f} "
      f"spy ${runs['switch']['spy_final']:,.2f}", flush=True)

out = {"starts": starts, "common_start": START, "end": END,
       "pond": pond, "switch_trigger": trigger, "runs": runs}
with open(os.path.join(HERE, "results_common.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("saved results_common.json", flush=True)
