#!/usr/bin/env python3
"""
INTEGRITY GATE — combo-vm-lazyp (THE GREAT RETEST v10). Simulation only.

Reproduces the ORIGINAL published combo finals in ORIGINAL form through
the original plumbing (combo_base.py = verbatim copy of
backtests/v9-muse-rules/combo-vm-lazyp/combo-vm-lazyp-v9.py, whose top
half is the v8 original engine unchanged; it imports the two parent
engines verbatim: v4/value-momentum-plainfloor.py and
v7/gap-a5-lazy-prices/lazy-prices.py, parent studies' own caches
read-only).

Original form: one $100 pot, 50/50 sleeves at $50 each with sleeve
floors disabled, quarterly 50/50 sleeve resets at selection-date closes
(inception excluded), ONE plain -15% floor on the combined pot, no
restart (his-rules form). Windows: CONT 2019-01-02 -> 2026-11-20,
VAL 2023-01-03 -> 2026-11-20.

Published targets (backtests/v8/combo-vm-lazyp/ +
backtests/v9-muse-rules/combo-vm-lazyp/v9-results.json):
  combo CONT $540.72, VAL $312.55 (placebos beaten 20/20 both windows)
  parents CONT: V+M $544.47, Lazy $504.34, SPY $313.62
  parents VAL : V+M $288.05, Lazy $324.12, SPY $187.77
Writes integrity.json in this folder only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import combo_base as B  # noqa: E402

vm, lz = B.vm, B.lz
WINDOWS = B.WINDOWS
PUBLISHED = B.PUBLISHED


def main():
    print("loading value+momentum book (cache)...", flush=True)
    pb_vm, eq_rows, sh_rows = B.build_vm_book()
    print("loading lazy-prices signals + book (cache)...", flush=True)
    pb_lz, signals, _census = B.build_lz_book()

    checks = {}
    ok = True
    for wname, (sd, ed) in WINDOWS.items():
        r = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, 100.0, 85.0, [],
                       quiet=True)
        got = round(r["final"], 2)
        checks[f"vm_{wname}"] = {"published": PUBLISHED["vm"][wname],
                                 "reproduced": got,
                                 "match": abs(got - PUBLISHED["vm"][wname]) < 0.05}
        print(f"CHECK vm {wname}: ${got} vs ${PUBLISHED['vm'][wname]}",
              flush=True)
        r = lz.run_pot(pb_lz, signals, sd, ed)
        got = round(r["final"], 2)
        checks[f"lz_{wname}"] = {"published": PUBLISHED["lz"][wname],
                                 "reproduced": got,
                                 "match": abs(got - PUBLISHED["lz"][wname]) < 0.05}
        print(f"CHECK lazy {wname}: ${got} vs ${PUBLISHED['lz'][wname]}",
              flush=True)
        s, _ = vm.spy_net(pb_vm, sd, ed, 100.0)
        got = round(s, 2)
        checks[f"spy_{wname}"] = {"published": PUBLISHED["spy"][wname],
                                  "reproduced": got,
                                  "match": abs(got - PUBLISHED["spy"][wname]) < 0.05}
        print(f"CHECK spy {wname}: ${got} vs ${PUBLISHED['spy'][wname]}",
              flush=True)

        combo = B.run_combo(pb_vm, eq_rows, sh_rows, pb_lz, signals, sd, ed)
        pub = 540.72 if wname == "continuous" else 312.55
        got = round(combo["final"], 2)
        checks[f"combo_{wname}"] = {
            "published": pub, "reproduced": got,
            "match": abs(got - pub) < 0.05,
            "halt": combo["halt"],
            "final_mtm": round(combo["final_mtm"], 2),
            "costs_total": round(combo["sleeve_costs"]
                                 + combo["transfer_costs"], 2)}
        print(f"CHECK combo {wname}: ${got} vs ${pub} "
              f"halt={combo['halt']}", flush=True)

    ok = all(c["match"] for c in checks.values())
    out = {"slug": "combo-vm-lazyp",
           "status": "reproduced" if ok else "FAILED",
           "form": "original his-rules form: 50/50 sleeves, quarterly "
                   "50/50 resets, plain -15% pot floor, no restart",
           "checks": checks,
           "original_record_note": "Original program record also "
                   "carries a 20-quarter head-to-head line for this "
                   "combo (won 10 / lost 10, 6 quarters with any halt) "
                   "from the six-combination scoreboard; the hard "
                   "finals above are the reproduced integrity targets."}
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("INTEGRITY:", out["status"], flush=True)
    assert ok, "integrity gate FAILED"


if __name__ == "__main__":
    main()
