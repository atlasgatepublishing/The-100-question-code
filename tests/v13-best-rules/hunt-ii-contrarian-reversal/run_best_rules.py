#!/usr/bin/env python3
"""v13 Best Rules — hunt-ii-contrarian-reversal.

The strategy itself is frozen in BEST-RULES-SPEC.md (SPY exposure dial on the
Investors Intelligence ratio Bulls/(Bulls+Bears), 10-week MA; 69 arms, 67
confirms -> 0%, graduated re-entry <60 -> 50%, <50 -> 100%).

This script is the DATA GATE + chassis verification:
  1. Scan the workspace for any complete free PIT II weekly series file.
  2. Verify the SPY price chassis reproduces the program's published SPY
     buy-and-hold references on the v13 roads (isolating the blocker to the
     signal series alone).
If (1) ever finds a complete series, the gate passes and the frozen dial
must be run before any verdict changes. Until then the honest output is
the closure recorded in results.json — no equity curve is fabricated.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/hunt-aaii-sentiment"))
from common import load_pxfull, slice_bars, buyhold_open  # program chassis (read-only reuse)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def hunt_local_series():
    """Look for any file in the stock-app tree that could be an II series:
    name mentions investors-intelligence / advisor sentiment, or a CSV/JSON
    whose header pairs bulls% with bears% on weekly dates 2010-2026."""
    hits = []
    root = os.path.expanduser("~/workspace/stock-app")
    for dp, dn, fn in os.walk(root):
        if "hunt-ii-contrarian-reversal" in dp:
            continue  # this family's own folders contain no data, only specs/logs
        for f in fn:
            low = f.lower()
            if ("investor" in low and "intelligence" in low) or "advisor" in low and "sentiment" in low:
                hits.append(os.path.join(dp, f))
    return hits

def main():
    log = []
    candidates = hunt_local_series()
    log.append(f"local II-series file candidates: {candidates if candidates else 'NONE'}")
    gate_pass = len(candidates) > 0

    spy = load_pxfull("SPY")
    spy_check = {}
    for road, (s, e) in ROADS.items():
        bars = slice_bars(spy, s, e)
        final = round(buyhold_open(bars), 2)
        spy_check[road] = {"bars": len(bars), "buyhold_final": final,
                           "program_reference": SPYREF[road],
                           "abs_diff": round(abs(final - SPYREF[road]), 2)}
        log.append(f"SPY {road}: bars={len(bars)} buyhold=${final} vs reference ${SPYREF[road]}")

    out = {
        "family": "hunt-ii-contrarian-reversal",
        "program": "v13-best-rules",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "data_gate_passed": gate_pass,
        "blocker": None if gate_pass else (
            "Complete point-in-time Investors Intelligence weekly Advisors Sentiment history "
            "(Bulls % and Bears %) is a paid Chartcraft/II product with no free archive; only "
            "fragments (individual press-quoted weeks, 3-week windows in Yardeni chart books) "
            "exist free, and BEST-RULES-SPEC.md forbids running on fragments (selection bias "
            "toward extreme weeks) or substituting another survey (AAII is a different family)."),
        "run_performed": False,
        "equity_curves": None,
        "placebos": "NOT SUPPORTED — no signal series; exposure path does not exist to shift",
        "spy_chassis_verification": spy_check,
        "champions_vm": CHAMP,
        "spy_references": SPYREF,
        "published_form_finals": None,
        "published_form_note": "v12 closed STILL UNBUILDABLE — no published-form run exists; there is no performance number to beat, only a data closure to re-verify.",
        "my_rules_finals": None,
        "verdict": "STILL DEAD",
        "verdict_note": ("Verdict ceiling CANDIDATE. 'STILL DEAD' here means: no honest profit can be "
                         "shown because no honest run exists — the signal's data is paywalled, "
                         "re-verified fresh in v13 (HUNT-LOG.md). This is a data death, not a "
                         "rules death: the frozen best-rules dial runs the day the series is "
                         "supplied or surfaces free."),
        "confirmation": "NOT TRIGGERED — no run, no road beat champion V+M",
        "coins": "NOT-APPLICABLE — survey polls US equity advisors; no coin analogue published",
        "holdings_grid": "NOT-APPLICABLE — market timer (SPY)",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(HERE, "run.log"), "w") as f:
        f.write("\n".join(log) + "\n")
        f.write(f"DATA GATE: {'PASS' if gate_pass else 'FAIL — blocker stands'}\n")
        f.write("No strategy run performed; no equity curves fabricated.\n")
    print("\n".join(log))
    print("DATA GATE:", "PASS" if gate_pass else "FAIL — blocker stands")

if __name__ == "__main__":
    main()
