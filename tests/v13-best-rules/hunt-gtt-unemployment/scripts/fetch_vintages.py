#!/usr/bin/env python3
"""Fetch ALFRED month-end vintages of UNRATE (public, no key) and build the
FIRST-PUBLISHED series per BEST-RULES-SPEC.md section 1:
FP(M) = value of reference month M in the ALFRED vintage dated the last day
of month M+1; if missing there (delayed release), earliest later month-end
vintage containing M, flagged."""
import calendar, csv, io, json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
os.makedirs(OUT, exist_ok=True)
CACHE = os.path.join(OUT, "alfred_vintages.json")

def month_ends(y0, m0, y1, m1):
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}")
        m += 1
        if m == 13: y, m = y + 1, 1
    return out

def fetch(vdate):
    import subprocess
    url = f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=UNRATE&vintage_date={vdate}"
    txt = subprocess.run(["curl", "-s", "--max-time", "25", url],
                         capture_output=True, text=True, check=True).stdout
    d = {}
    for row in csv.reader(io.StringIO(txt)):
        if len(row) == 2 and row[0][:1].isdigit() and row[1] not in ("", "."):
            d[row[0][:7]] = float(row[1])
    return d

def main():
    vintages = {}
    if os.path.exists(CACHE):
        vintages = json.load(open(CACHE))
    dates = month_ends(2008, 12, 2026, 11)
    for vd in dates:
        if vd in vintages: continue
        for attempt in range(3):
            try:
                vintages[vd] = fetch(vd); break
            except Exception as e:
                print("retry", vd, e); time.sleep(2)
        else:
            print("FAILED", vd); continue
        if len(vintages) % 10 == 0:
            json.dump(vintages, open(CACHE, "w")); print("fetched through", vd, flush=True)
        time.sleep(0.15)
    json.dump(vintages, open(CACHE, "w"))
    # Build first-published series for reference months 2009-01 .. 2026-10
    def next_month(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return (y + 1, 1) if m == 12 else (y, m + 1)
    refs = []
    y, m = 2009, 1
    while (y, m) <= (2026, 10):
        refs.append(f"{y:04d}-{m:02d}")
        y, m = next_month(f"{y:04d}-{m:02d}")
    fp, flags = {}, {}
    sorted_v = sorted(vintages)
    for ref in refs:
        ny, nm = next_month(ref)
        target = f"{ny:04d}-{nm:02d}-{calendar.monthrange(ny, nm)[1]:02d}"
        if target in vintages and ref in vintages[target]:
            fp[ref] = vintages[target][ref]
        else:
            for vd in sorted_v:
                if vd > target and ref in vintages[vd]:
                    fp[ref] = vintages[vd][ref]; flags[ref] = f"delayed: first seen in vintage {vd} (target {target})"
                    break
            else:
                flags[ref] = "NOT FOUND in any vintage"
    json.dump({"fp": fp, "flags": flags}, open(os.path.join(OUT, "unrate_first_published.json"), "w"), indent=1)
    print("refs:", len(fp), "flagged:", flags)

if __name__ == "__main__":
    main()
