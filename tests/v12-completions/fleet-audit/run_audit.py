#!/usr/bin/env python3
"""Fleet integrity audit for v12-completions family folders.
Read-only scan of sibling family folders; writes audit.csv + AUDIT.md
into fleet-audit/ only.
Definitions:
- has_spec: top-level CONSTRUCTION-SPEC.md / SPEC-FROZEN.md /
  JUDGMENT-SPEC.md / SWEEP-SPEC.md present.
- has_hunt_log: top-level file whose name contains HUNT and LOG (e.g. HUNT-LOG.md).
- has_scripts: any .py/.sh/.js file at top level or in a scripts/ subfolder
  (data/ and similar payload dirs are not counted).
- has_results_json: top-level results.json exists, size >= 100 bytes
  (non-trivial), and parses as JSON. 0-byte / unparseable = NOT present,
  flagged in results_json_status.
- has_results_md: top-level RESULTS.md present and non-empty.
- verdict_line: first line of RESULTS.md containing 'verdict' (case-insens.),
  else a line starting with a known verdict token (BEATS/DEAD/ALIVE/etc.),
  else ''.
- completeness: COMPLETE = spec + valid results.json + RESULTS.md.
  SPEC-ONLY = spec is the ONLY audited artifact present (no hunt log,
  no scripts, no valid results.json, no RESULTS.md).
  EMPTY = folder contains no files at all (recursive).
  PARTIAL = everything else (missing column lists exactly what is absent).
"""
import csv, json, os, re
from collections import Counter

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
OUT = os.path.join(BASE, "fleet-audit")
EXCLUDE = {"catalog-sweep", "fleet-audit", "grid-audit"}
SPEC_NAMES = ["CONSTRUCTION-SPEC.md", "SPEC-FROZEN.md", "JUDGMENT-SPEC.md", "SWEEP-SPEC.md"]
VERDICT_TOKENS = ("BEATS", "DEAD", "ALIVE", "REAL BUT SMALLER", "UNBUILDABLE",
                  "CLOSED", "NO EDGE", "FAILS", "PASSES", "SURVIVES", "KILLED")

def verdict_line(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return ""
    for ln in lines:
        low = ln.lower().lstrip("#>* -")
        if low.startswith("verdict") or "**verdict" in low[:40]:
            return ln[:200]
    for ln in lines:
        if "verdict" in ln.lower() and len(ln) > 3:
            return ln[:200]
    for ln in lines:
        up = ln.lstrip("#>* -").upper()
        if any(up.startswith(t) for t in VERDICT_TOKENS):
            return ln[:200]
    return ""

def main():
    folders = sorted(d for d in os.listdir(BASE)
                     if os.path.isdir(os.path.join(BASE, d)) and d not in EXCLUDE)
    rows = []
    for name in folders:
        p = os.path.join(BASE, name)
        top = [f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))]
        spec_files = [s for s in SPEC_NAMES if s in top]
        has_spec = bool(spec_files)
        hunt = [f for f in top if "HUNT" in f.upper() and "LOG" in f.upper()]
        has_hunt = bool(hunt)
        scripts = [f for f in top if f.endswith((".py", ".sh", ".js"))]
        sdir = os.path.join(p, "scripts")
        if os.path.isdir(sdir):
            scripts += ["scripts/" + f for f in os.listdir(sdir)
                        if f.endswith((".py", ".sh", ".js"))]
        has_scripts = bool(scripts)
        # results.json
        rj = os.path.join(p, "results.json")
        rj_status, has_rj, rj_size = "absent", False, 0
        if os.path.isfile(rj):
            rj_size = os.path.getsize(rj)
            if rj_size == 0:
                rj_status = "ZERO-BYTE (counts as absent)"
            elif rj_size < 100:
                rj_status = f"trivial-size {rj_size}B (counts as absent)"
                try:
                    json.load(open(rj, encoding="utf-8", errors="replace"))
                    rj_status += "; parses"
                except Exception as e:
                    rj_status += f"; UNPARSEABLE: {e}"
            else:
                try:
                    with open(rj, encoding="utf-8", errors="replace") as f:
                        json.load(f)
                    rj_status, has_rj = "ok", True
                except Exception as e:
                    rj_status = f"UNPARSEABLE (counts as absent): {e}"
        # RESULTS.md
        rm = os.path.join(p, "RESULTS.md")
        has_rm = os.path.isfile(rm) and os.path.getsize(rm) > 0
        vline = verdict_line(rm) if has_rm else ""
        # total files recursive (for EMPTY)
        nfiles = sum(len(fs) for _, _, fs in os.walk(p))
        missing = []
        if not has_spec: missing.append("spec")
        if not has_rj: missing.append("results.json" + (f" ({rj_status})" if os.path.isfile(rj) else ""))
        if not has_rm: missing.append("RESULTS.md")
        if not has_hunt: missing.append("hunt_log")
        if not has_scripts: missing.append("scripts")
        if has_spec and has_rj and has_rm:
            comp = "COMPLETE"
        elif nfiles == 0:
            comp = "EMPTY"
        elif has_spec and not has_rj and not has_rm and not has_hunt and not has_scripts:
            comp = "SPEC-ONLY"
        else:
            comp = "PARTIAL"
        rows.append({
            "folder": name, "has_spec": has_spec, "spec_file": ";".join(spec_files),
            "has_hunt_log": has_hunt, "hunt_log_file": ";".join(hunt),
            "has_scripts": has_scripts, "script_count": len(scripts),
            "has_results_json": has_rj, "results_json_size": rj_size,
            "results_json_status": rj_status,
            "has_results_md": has_rm, "verdict_line": vline,
            "completeness": comp,
            "missing": "; ".join(missing), "total_files_recursive": nfiles,
        })
    with open(os.path.join(OUT, "audit.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    counts = Counter(r["completeness"] for r in rows)
    bad_json = [r for r in rows if "ZERO-BYTE" in r["results_json_status"]
                or "UNPARSEABLE" in r["results_json_status"]]
    incomplete = [r for r in rows if r["completeness"] != "COMPLETE"]
    with open(os.path.join(OUT, "AUDIT.md"), "w", encoding="utf-8") as f:
        f.write("# Fleet Integrity Audit — v12-completions\n\n")
        f.write(f"Scanned {len(rows)} family folders under `v12-completions/` "
                f"(excluded: catalog-sweep/, fleet-audit/, grid-audit/ and program-level files). "
                f"Method: see header of `run_audit.py` in this folder. "
                f"Full per-folder detail: `audit.csv` in this folder.\n\n")
        f.write("## Counts by completeness class\n\n")
        for k in ("COMPLETE", "PARTIAL", "SPEC-ONLY", "EMPTY"):
            f.write(f"- **{k}: {counts.get(k, 0)}**\n")
        f.write(f"- **Total folders scanned: {len(rows)}**\n\n")
        f.write("## Flagged results.json (0-byte or unparseable)\n\n")
        if bad_json:
            for r in bad_json:
                f.write(f"- `{r['folder']}` — {r['results_json_status']} (size {r['results_json_size']}B)\n")
        else:
            f.write("- None.\n")
        f.write("\n## Re-dispatch queue — every PARTIAL / SPEC-ONLY / EMPTY folder\n\n")
        f.write("Completeness (COMPLETE) requires only spec + valid results.json + RESULTS.md; "
                "the `missing` column below also lists hunt_log / scripts gaps for full context.\n\n")
        f.write("| Folder | Class | Missing |\n|---|---|---|\n")
        for r in incomplete:
            f.write(f"| {r['folder']} | {r['completeness']} | {r['missing']} |\n")
        f.write(f"\nTotal incomplete (re-dispatch queue): {len(incomplete)} of {len(rows)}.\n")
    print(json.dumps({"total": len(rows), "counts": dict(counts),
                      "bad_json": [(r["folder"], r["results_json_status"]) for r in bad_json],
                      "incomplete_count": len(incomplete)}, indent=1))

if __name__ == "__main__":
    main()
