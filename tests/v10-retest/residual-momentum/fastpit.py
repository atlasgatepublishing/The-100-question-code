"""Fast drop-in replacement for the champion engine's E.pit_value.

The original scans every row on every call and re-parses dates per row.
Its semantics: among rows with filed < asof and filed_ordinal >=
asof_ordinal - max_age_days, return the (filed, end, val) of the row with
the maximum key (filed, prio, end); ties on the full key keep the FIRST
row in list order (the original uses strict >).

This version pre-sorts each chain once (stable sort by (filed, prio,
end)) and answers each query by bisect: the eligible rows are a prefix
of the sorted list (filed < asof); the winner is the last eligible row,
mapped back to the first row sharing its key (tie rule). Equivalence is
proven in validate_fastpit.py against the original on every chain and
hundreds of dates before any sweep number is taken with it.
"""
import bisect
from datetime import date as _date

_cache = {}


def _prep(rows):
    key = id(rows)
    ent = _cache.get(key)
    if ent is None:
        order = sorted(range(len(rows)),
                       key=lambda i: (rows[i][0], rows[i][3], rows[i][1]))
        srows = [rows[i] for i in order]
        ent = {"rows": srows,
               "fileds": [r[0] for r in srows],
               "keys": [(r[0], r[3], r[1]) for r in srows]}
        _cache[key] = ent
    return ent


def fast_pit_value(rows, asof, max_age_days=548):
    if not rows:
        return None
    ent = _prep(rows)
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    cutoff_ord = _date(ay, am, ad).toordinal() - max_age_days
    n = bisect.bisect_left(ent["fileds"], asof)  # eligible = fileds < asof
    if n == 0:
        return None
    win_key = ent["keys"][n - 1]
    fy, fm, fd = (int(win_key[0][:4]), int(win_key[0][5:7]),
                  int(win_key[0][8:10]))
    if _date(fy, fm, fd).toordinal() < cutoff_ord:
        return None
    i = bisect.bisect_left(ent["keys"], win_key)
    r = ent["rows"][i]
    return (r[0], r[1], r[2])
