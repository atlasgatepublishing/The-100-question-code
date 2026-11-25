#!/usr/bin/env python3
"""Slice H3 assembler: split the aggregate holdings sweeps (holdings-blends,
holdings-novel-selection, holdings-vm-variants - all read-only) into the
per-family folders assigned to slice H3. No new runs; numbers copied
verbatim from the aggregate results.json / cells_*.json."""
import json, os
B = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
COUNTS = ["1", "2", "3", "5", "8", "10", "15", "20", "30", "ALL"]
ROADS = ["LONG", "DECADE", "CONT", "VAL"]

def fmt(v):
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"

def write(folder, name, text):
    os.makedirs(os.path.join(B, folder), exist_ok=True)
    with open(os.path.join(B, folder, name), "w") as f:
        f.write(text)

# ---------------- blends: grand-combination, winners-blend ----------------
blends = json.load(open(os.path.join(B, "holdings-blends/results.json")))
CONV = """# SPEC — holdings-count sweep (filed per family, slice H3)

Source run: `holdings-blends/` (aggregate blends worker, v12 holdings wing).
This folder is the per-family filing of that run for slice H3; the numbers
are copied verbatim from `holdings-blends/results.json`.

**Frozen convention (stated in the source run, before its runs):** a
blend's holdings count = the count held in EACH sleeve simultaneously
(lockstep). At grid count N, every sleeve holds its own top-N (its own
ranking, its own pool), sleeve weights stay at the blend's published
split, equal weight inside each sleeve. Grid: 1, 2, 3, 5, 8, 10, 15, 20,
30, ALL-ELIGIBLE, capped by each sleeve's pool (pond sleeves score <=30
names, so 30 and ALL coincide there). Native count = 5 per sleeve.
Cadence = the blend's native cadence (quarterly). Forms: house = v9
protections at pot level; native = the blend's original construction.
Costs: program standard 0.10%/side + $0.01 per sell order, plus the
blend's own transfer-cost convention. Placebos: 20 seeds per cell on
DECADE. Confirmation: Terry's rule - different-years folds + halves,
pre-registered in the source run.
"""
for fam in ("grand-combination", "winners-blend"):
    d = blends["blends"][fam]
    cells = d["cells"]
    folder = f"holdings-{fam}"
    write(folder, "SPEC.md", CONV)
    write(folder, "results.json", json.dumps(
        {"family": fam, "source": "holdings-blends/results.json",
         "native_count_per_sleeve": 5, "cells": cells,
         "house_road_sums": d["house_road_sums"],
         "roads_beating_native_house": d["roads_beating_native_house"],
         "grid_winner_house_sum": d["grid_winner_house_sum"],
         "confirmation": d["confirmation"],
         "period_distributions_house": d["period_distributions_house"]}, indent=1))
    roads = sorted({k.split("|")[0] for k in cells})
    lines = [f"# HOLDINGS-COUNT SWEEP — {fam} — RESULTS (v12, slice H3 filing)",
             "",
             f"Source: aggregate run in `holdings-blends/` (see SPEC.md for the",
             f"frozen lockstep convention). Native count = **5 per sleeve**.",
             "",
             "## Full grid — house form (final $ per $100; placebo beats on DECADE, 20 seeds)",
             "",
             "| Count | " + " | ".join(roads) + " | Placebos beaten (DECADE) |",
             "|" + "---|" * (len(roads) + 2)]
    for c in COUNTS:
        row = []
        pb = "—"
        for r in roads:
            v = cells.get(f"{r}|house|{c}")
            row.append(fmt(v["final"]) if v else "—")
            if r == "DECADE" and v and v.get("placebo_beats") is not None:
                pb = f"{v['placebo_beats']}/20"
        lines.append(f"| {c} | " + " | ".join(row) + f" | {pb} |")
    lines += ["", "## Full grid — native form (final $ per $100)", "",
              "| Count | " + " | ".join(roads) + " |",
              "|" + "---|" * (len(roads) + 1)]
    for c in COUNTS:
        row = []
        for r in roads:
            v = cells.get(f"{r}|native|{c}")
            row.append(fmt(v["final"]) if v else "—")
        lines.append(f"| {c} | " + " | ".join(row) + " |")
    nat = {r: cells.get(f"{r}|house|5", {}).get("final") for r in roads}
    win = d["grid_winner_house_sum"]
    best = {r: cells.get(f"{r}|house|{win}", {}).get("final") for r in roads}
    lines += ["", "## Verdict", "",
              f"Native count 5 (house): " + " · ".join(f"{r} {fmt(nat[r])}" for r in roads),
              f"Best count by house road-sum: **{win}** — " +
              " · ".join(f"{r} {fmt(best[r])}" for r in roads),
              f"Roads beating native (house): {d['roads_beating_native_house']}",
              f"Confirmation: {json.dumps(d['confirmation'])[:1200]}",
              "",
              "Per-period distributions (house, winning + native counts) are in",
              "`results.json` under `period_distributions_house`, computed by the",
              "source run. Practitioner behavior and the full narrative are in",
              "`holdings-blends/RESULTS.md` (the source report).",
              ""]
    write(folder, "RESULTS.md", "\n".join(lines))
    print(folder, "written; winner", win, "native", nat, "best", best)

# ---------------- novel families ----------------
novel = json.load(open(os.path.join(B, "holdings-novel-selection/results.json")))
for fam, cf in (("novel-f4-cash-collected", "cells_f4.json"),
                ("novel-pv2-last-seller", "cells_pv2.json"),
                ("novel-pv4-overnight-confession", "cells_pv4.json")):
    cd = json.load(open(os.path.join(B, "holdings-novel-selection", cf)))
    folder = f"holdings-{fam}"
    verdict = novel["verdicts"][fam]
    write(folder, "SPEC.md", f"""# SPEC — holdings-count sweep (filed per family, slice H3)

Source run: `holdings-novel-selection/` (aggregate novel-selection worker,
v12 holdings wing). Numbers copied verbatim from `{cf}` and the aggregate
`results.json` verdicts.

**Invented family — CANDIDATE ceiling travels with every number.** A count
win makes a VARIANT-CANDIDATE, never a promotion.

Method (frozen in the source run): grid counts 1, 2, 3, 5, 8, 10, 15, 20,
30, ALL-ELIGIBLE, capped by the family's eligible pool; native count 5;
house (v9 protections) and native forms; 20-seed placebos on DECADE;
confirmation rule: a non-native count is a VARIANT-CANDIDATE only if it
beats the native count on every main road and both confirmation windows.
Cadence / count semantics: {cd.get('cadence', 'see source report')};
{cd.get('note', '')}
""")
    write(folder, "results.json", json.dumps(
        {"family": fam, "source": f"holdings-novel-selection/{cf}",
         "cells": cd, "verdict": verdict}, indent=1, default=str))
    lines = [f"# HOLDINGS-COUNT SWEEP — {fam} — RESULTS (v12, slice H3 filing)",
             "",
             "Source: aggregate run in `holdings-novel-selection/` (see SPEC.md).",
             "**Invented family — CANDIDATE ceiling.**",
             "",
             f"## Verdict (from the source run, verbatim fields)",
             "",
             f"- Verdict: **{verdict.get('verdict')}**",
             f"- Status: {verdict.get('status')}",
             f"- Winner count: {verdict.get('winner_count')}",
             f"- Confirmation: {verdict.get('confirmation')}",
             "",
             "Full cell grid (every count, every road, both forms, placebos) is in",
             "`results.json` in this folder, copied verbatim from the source run;",
             "the narrative, per-period distributions and practitioner notes are in",
             "`holdings-novel-selection/RESULTS.md`.",
             ""]
    for k, v in verdict.items():
        if k not in ("verdict", "status", "winner_count", "confirmation", "cells"):
            lines.append(f"- {k}: {v}")
    write(folder, "RESULTS.md", "\n".join(lines))
    print(folder, "written;", verdict.get("verdict"), "winner", verdict.get("winner_count"))

# ---------------- vm-composite ----------------
vmv = json.load(open(os.path.join(B, "holdings-vm-variants/results.json")))
fam_data = vmv["families"]["vm-composite"]
write("holdings-vm-composite", "SPEC.md", """# SPEC — holdings-count sweep (filed per family, slice H3)

Source run: `holdings-vm-variants/` (aggregate champion-variant worker,
v12 holdings wing). Numbers copied verbatim from its `results.json`.
Family: vm-composite, house form on the program pond (quarterly top-N by
the composite ranking; native count 5). Its v12 constructed broad form
could not be swept in the source run (source dataset incomplete at sweep
time — BLOCKED-BY-INCOMPLETE-SOURCE, recorded in the source report).
Grid: 1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE; house and native
rule sets; 20-seed placebos per cell; confirmation on different years
pre-registered in the source run.
""")
write("holdings-vm-composite", "results.json", json.dumps(
    {"family": "vm-composite", "source": "holdings-vm-variants/results.json",
     "native_count": 5, "roads": fam_data,
     "period_distributions": vmv.get("period_distributions", {}).get("vm-composite")},
    indent=1, default=str))
lines = ["# HOLDINGS-COUNT SWEEP — vm-composite — RESULTS (v12, slice H3 filing)",
         "",
         "Source: aggregate run in `holdings-vm-variants/` (see SPEC.md).",
         "Native count = **5**.",
         "",
         "## Verdict (source run)",
         "",
         "**FEWER IS BETTER (mild)** — count **3** is a VARIANT-CANDIDATE: it beats",
         "native 5 on LONG ($2,944.34 vs $2,713.38), CONT ($522.44 vs $511.48) and",
         "the different-years CONFIRM ($428.48 vs $386.57, both 20/20 placebos);",
         "DECADE is a practical tie ($645.10 vs $651.27); VAL sits in a three-way",
         "tie region (n=8 $281.45, n=5 $265.38, n=3 $262.15). Counts 1 and 2 are",
         "floor-death traps on LONG and CONFIRM ($68.39 / $70.06). Full grid in",
         "`results.json`; narrative and per-period distributions in",
         "`holdings-vm-variants/RESULTS.md`.",
         ""]
write("holdings-vm-composite", "RESULTS.md", "\n".join(lines))
print("holdings-vm-composite written")
print("ASSEMBLE DONE")
