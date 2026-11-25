"""Export the canonical monthly CD VALUE series (cd-value-series.csv).

This is a presentation export of THIS folder's own frozen computation —
no new method. It loads the function definitions from compute_cd.py
verbatim (everything above its "END = date" line: the rate table loader,
add_months, roller_value) and prints the value path of the SPEC.md term
strategy for one customer: a fresh $100 started on the record's first
day, January 4, 2010 (the same start compute_cd.py uses for its window
grid and its 17-year road).

Points: the anchor (2010-01-04, $100.00), every month-end from
2010-01-31 through 2026-10-31, and the record's last day, 2026-11-20
(the final month is partial — the record ends there). Values are the
roller's accrued balance on that date, dollars and cents.
cd12_value = the headline 12-month roller; cd6_value = the 6-month
roller sensitivity line. Run: python3 export_cd_series.py
"""
import calendar
import csv
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / "compute_cd.py").read_text().split("END = date")[0]
ns: dict = {}
exec(src, ns)  # the benchmark build's own rates + roller_value, verbatim
roller_value = ns["roller_value"]

ANCHOR = date(2010, 1, 4)
END = date(2026, 11, 20)


def month_ends():
    out = []
    for y in range(2010, 2027):
        for m in range(1, 13):
            d = date(y, m, calendar.monthrange(y, m)[1])
            if d <= END:
                out.append(d)
    return out


def main():
    rows = [(ANCHOR, 100.0, 100.0)]
    for d in month_ends():
        if d <= ANCHOR:
            continue
        rows.append((d,
                     roller_value(ANCHOR, d, 12, 0),
                     roller_value(ANCHOR, d, 6, 1)))
    rows.append((END,
                 roller_value(ANCHOR, END, 12, 0),
                 roller_value(ANCHOR, END, 6, 1)))
    rows.sort()
    with open(HERE / "cd-value-series.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "cd12_value", "cd6_value"])
        for d, v12, v6 in rows:
            w.writerow([d.isoformat(), f"{v12:.2f}", f"{v6:.2f}"])
    print(f"wrote {len(rows)} points; final row {rows[-1][0]} "
          f"cd12={rows[-1][1]:.2f} cd6={rows[-1][2]:.2f}")


if __name__ == "__main__":
    main()
