#!/usr/bin/env python3
"""Append full grid tables to the novel-family filings from their own
results.json (cells copied verbatim from holdings-novel-selection)."""
import json, os
B = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
COUNTS = ["1", "2", "3", "5", "8", "10", "15", "20", "30", "ALL"]
for folder in ("holdings-novel-f4-cash-collected", "holdings-novel-pv2-last-seller",
               "holdings-novel-pv4-overnight-confession"):
    p = os.path.join(B, folder, "results.json")
    d = json.load(open(p))
    forms = d["cells"]["forms"]
    roads = [r for r in ("LONG", "DECADE", "CONT", "VAL")
             if any(r in forms["house"].get(c, {}) for c in COUNTS)]
    lines = ["", "## Full grid (final $ per $100, appended from `results.json` cells)",
             ""]
    for form in ("house", "native"):
        if form not in forms:
            continue
        lines += [f"### {form} form", "",
                  "| Count | " + " | ".join(roads) + " | Placebos beaten (DECADE) |",
                  "|" + "---|" * (len(roads) + 2)]
        for c in COUNTS:
            cell = forms[form].get(c)
            if not cell:
                lines.append(f"| {c} | " + " | ".join("—" for _ in roads) + " | — |")
                continue
            row = []
            for r in roads:
                v = cell.get(r)
                row.append(f"${v[0]:,.2f}" if v else "—")
            pb = cell.get("pl_beaten")
            lines.append(f"| {c} | " + " | ".join(row) +
                         f" | {pb}/20 |" if pb is not None else
                         f"| {c} | " + " | ".join(row) + " | — |")
        lines.append("")
    with open(os.path.join(B, folder, "RESULTS.md"), "a") as f:
        f.write("\n".join(lines))
    print(folder, "patched; roads", roads)
print("PATCH DONE")
