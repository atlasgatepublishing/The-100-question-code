#!/usr/bin/env python3
"""Assemble the wing's combined results.json from results_etf5.json and
results_sector.json: adds per-period distributions (Terry's reporting
standard — monthly periods, DECADE road, frozen form; no-floor form too
where it differs) for each family's winning count (highest DECADE final,
frozen form — basis stated) and native count, and the confirmation-rule
audit (no non-native count beat its native count on ALL roads of any
rule set in this wing, so no confirmation re-runs were triggered; the
near-misses are recorded)."""
import json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_etf5 import period_stats  # monthly resample of a daily curve
from run_sector import period_stats_monthly  # curve already monthly


def main():
    etf = json.load(open(os.path.join(HERE, "results_etf5.json")))
    sec = json.load(open(os.path.join(HERE, "results_sector.json")))
    out = {"wing": "holdings-rotation-selectors",
           "spec": "SWEEP-SPEC.md (frozen before runs)",
           "grid": [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL-ELIGIBLE"],
           "integrity": {"etf5": etf["integrity"], "sector_faber": sec["faber_integrity"],
                         "sector_house": sec["house_integrity"]},
           "families": {}, "confirmation": {}}

    for slug, fam in etf["families"].items():
        nat = str(fam["native_count"])
        frozen = fam["forms"]["frozen"]
        win = max(frozen, key=lambda c: frozen[c]["DECADE"]["final"])
        dist = {}
        for label, c in (("winning", win), ("native", nat)):
            entry = {"count": c,
                     "frozen": period_stats(frozen[c]["DECADE"]["curve"])}
            nf = fam["forms"]["nofloor"][c]["DECADE"]
            if nf["final"] != frozen[c]["DECADE"]["final"]:
                entry["nofloor"] = period_stats(nf["curve"])
            dist[label] = entry
        fam["period_distributions_decade"] = dist
        out["families"][slug] = fam
        # confirmation audit
        triggers = []
        for form, cells in fam["forms"].items():
            base = {r: cells[nat][r]["final"] for r in ("LONG", "DECADE", "CONT", "VAL")}
            for c, rc in cells.items():
                if c == nat: continue
                if all(rc[r]["final"] > base[r] for r in base):
                    triggers.append({"form": form, "count": c})
        out["confirmation"][slug] = {"triggered_by": triggers,
                                     "note": "no candidate" if not triggers else "see RESULTS.md"}

    # sector-rotation: two families in one (house + Faber A/B)
    sr = {"house": {}, "faber": {}}
    for form, cells in sec["forms"]["house"].items():
        sr["house"][form] = cells
    for form, cells in sec["forms"]["faber"].items():
        sr["faber"][form] = cells
    # distributions: house (daily curve -> monthly resample), Faber (monthly)
    dist = {}
    hfr = sec["forms"]["house"]["frozen"]
    hwin = max(hfr, key=lambda c: hfr[c]["DECADE"]["final"])
    dist["house"] = {
        "winning": {"count": hwin, "frozen": period_stats(hfr[hwin]["DECADE"]["curve"])},
        "native": {"count": "2", "frozen": period_stats(hfr["2"]["DECADE"]["curve"])}}
    for form in ("A", "B"):
        cells = sec["forms"]["faber"][form]
        win = max(cells, key=lambda c: cells[c]["DECADE"]["final"])
        dist[f"faber_{form}"] = {
            "winning": {"count": win, "stats": period_stats_monthly(cells[win]["DECADE"]["curve"])},
            "native": {"count": "3", "stats": period_stats_monthly(cells["3"]["DECADE"]["curve"])}}
    sr["period_distributions_decade"] = dist
    out["families"]["sector-rotation"] = sr
    trig = []
    hbase = {r: hfr["2"][r]["final"] for r in ("DECADE", "CONT", "VAL")}
    for form, cells in sec["forms"]["house"].items():
        for c, rc in cells.items():
            if c != "2" and all(rc[r]["final"] > {rr: cells["2"][rr]["final"] for rr in hbase}[r] for r in hbase):
                trig.append({"form": f"house-{form}", "count": c})
    for form in ("A", "B"):
        cells = sec["forms"]["faber"][form]
        base = {r: cells["3"][r]["final"] for r in ("LONG", "DECADE", "CONT", "VAL")}
        for c, rc in cells.items():
            if c != "3" and all(rc[r]["final"] > base[r] for r in base):
                trig.append({"form": f"faber-{form}", "count": c})
    out["confirmation"]["sector-rotation"] = {"triggered_by": trig,
                                              "note": "no candidate" if not trig else "see RESULTS.md"}
    tmp = os.path.join(HERE, "results.json.tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(out, indent=1))
    os.replace(tmp, os.path.join(HERE, "results.json"))
    print("wrote results.json")
    for slug, d in out["families"].items():
        if slug == "sector-rotation":
            print(slug, "house win", dist["house"]["winning"]["count"],
                  "| faberA win", dist["faber_A"]["winning"]["count"],
                  "| faberB win", dist["faber_B"]["winning"]["count"])
        else:
            print(slug, "winning(DECADE,frozen)", d["period_distributions_decade"]["winning"]["count"],
                  "native", d["native_count"])
    print("confirmation triggers:", out["confirmation"])


if __name__ == "__main__":
    main()
