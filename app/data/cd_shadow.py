"""CD shadow benchmark: what a bank CD would have done with the same cash.

Display benchmark for the dashboard / reports, in the same spirit as
``ReplayLoader.spy_shadow`` (DESIGN.md: "Benchmark on every report"):
for a given start cash and date window, what would that money be worth
if it had sat in bank CDs instead, following the frozen term strategy of
the project's CD benchmark build?

This module INVENTS NOTHING. It contains no rates, no term logic and no
compounding rules of its own. Every number comes from the canonical CD
series published by the separate CD-benchmark build under:

    <project>/backtests/cd-benchmark/

THE BENCHMARK'S OWN FROZEN SPEC (SPEC.md in that folder, frozen
2026-11-23 — this module follows it, never replaces it):
  * Rate: the FDIC national average rate, non-jumbo tier — FRED
    CD12NRNJ (weekly era, to 2021-03-29) chained to NDR12MCD (monthly
    era, from April 2021), with the April 2021 methodology break named
    in the spec. A CD bought on any day of a month locks that month's
    prevailing rate.
  * Headline strategy: the 12-month roller — $100 in a 12-month CD,
    interest accruing DAILY at the locked APY (daily factor
    (1 + APY) ** (1/365)); at each 12-month maturity the whole balance
    rolls into a new 12-month CD at that month's prevailing rate.
    (A 6-month roller, CD6NRNJ + NDR6MCD, is the spec's sensitivity
    line, reported beside the headline by the benchmark build itself.)
  * The folder's ``cd-rates-monthly.csv`` is the frozen RATE table the
    roller runs on. This module deliberately does NOT re-run the
    roller from those rates: re-implementing the simulation here would
    duplicate the frozen build and could silently diverge from its
    published results. This module consumes the build's published
    VALUE series (the roller's output) only, and the loader refuses
    any file whose name marks it as a rates or results file.

CANONICAL LAYOUT (what this loader consumes, in priority order)
---------------------------------------------------------------
Inside ``backtests/cd-benchmark/`` the loader looks for ONE canonical
series file, first match wins:

    1. cd_series.json     4. cd_series.csv
    2. series.json        5. series.csv
    3. cd-benchmark.json  6. cd.csv / benchmark.csv
    fallback: any other ``*.json`` / ``*.csv`` in the folder whose name
    contains "series" (sorted by name) — EXCLUDING any file whose name
    contains "rate" or "result": ``cd-rates-monthly.csv`` is the roller's
    rate input, not a value series, and results files are for the
    benchmark's own verification, not a series source.

Accepted shapes (JSON):
  * a list of points: ``[["2019-01-02", 100.0], ...]`` or
    ``[{"date": "2019-01-02", "value": 100.0}, ...]`` (key aliases:
    date/d/day, value/v/close/balance);
  * a dict with the point list under "series" / "points" / "data";
  * a dict mapping ISO date -> value: ``{"2019-01-02": 100.0, ...}``.
Accepted shape (CSV): a header row naming a date column and a value
column (same aliases), then one point per row.

The canonical values may be stated for ANY base amount (a $100 growth
series, a 1.0-based index, ...): this module only ever uses RATIOS of
canonical values, so the base cancels out. ``start_cash`` is scaled by
``canonical(date) / canonical(value in effect at start_date)``.

POINT SEMANTICS: the published series is the roller's own output
(per SPEC.md it accrues daily, so the published points are expected
to be daily; if the build publishes them step-dated instead, the same
rule applies unchanged). Between published points the last published
value is carried forward unchanged (forward-fill). No interpolation,
no accrual and no rate is ever synthesised here; dates past the last
published point carry that last value forward, and a window starting
before the first published point is NOT covered (returns None)
rather than extrapolated backwards.

ABSENT DATA: if the folder or a usable canonical file is not there yet
(or the file is corrupt / has no valid points), ``available()`` is
False and ``series()`` / ``final_value()`` return None. Nothing raises
for missing data; callers (dashboard) simply omit the CD curve.
Malformed arguments (bad ISO dates, end < start, non-positive or
non-finite start_cash) DO raise ValueError — that is a caller bug, not
a data problem.

No network access. No config.local.json. No broker anything — this
module only reads one local data file.

The benchmark directory can be overridden for tests / relocation with
the ``CD_SHADOW_BENCHMARK_DIR`` environment variable, by assigning to
``cd_shadow.BENCHMARK_DIR``, or per-call via the ``root=`` keyword.
"""
from __future__ import annotations

import bisect
import csv
import io
import json
import logging
import math
import os
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

# app/data/cd_shadow.py -> app/ -> <project>/ -> backtests/cd-benchmark/
APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = APP_DIR.parent
BENCHMARK_DIR = PROJECT_DIR / "backtests" / "cd-benchmark"

# Canonical series file names, in priority order.
_CANDIDATE_NAMES = (
    "cd_series.json", "series.json", "cd-benchmark.json",
    "cd_series.csv", "series.csv", "cd.csv", "benchmark.csv",
)
_DATE_KEYS = ("date", "d", "day")
_VALUE_KEYS = ("value", "v", "close", "balance", "worth")
_LIST_KEYS = ("series", "points", "data")

# Cache: resolved file path -> (mtime_ns, size, [(date_iso, value), ...])
_cache: dict[str, tuple[int, int, list]] = {}


def _clear_cache() -> None:
    """Drop the parsed-series cache (tests that swap fixtures use this)."""
    _cache.clear()


def _root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("CD_SHADOW_BENCHMARK_DIR")
    if env:
        return Path(env)
    return Path(BENCHMARK_DIR)


def _find_canonical_file(root: Path) -> Path | None:
    """Locate the canonical series file inside the benchmark folder."""
    if not root.is_dir():
        return None
    for name in _CANDIDATE_NAMES:
        p = root / name
        if p.is_file():
            return p
    # Fallback: any json/csv whose name mentions "series", name-sorted
    # for determinism. Rates files (cd-rates-monthly.csv — the roller's
    # INPUT) and results files are explicitly excluded: their numbers
    # are not position values and must never be read as a series.
    extras = sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in (".json", ".csv")
        and "series" in p.name.lower()
        and "rate" not in p.name.lower()
        and "result" not in p.name.lower()
    )
    return extras[0] if extras else None


def _num_or_none(v):
    """Coerce to a finite float, or None (bools are not numbers here)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _valid_iso(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _points_from_rows(rows) -> list[tuple[str, float]]:
    """Normalise an iterable of raw rows into sorted (date, value) points.

    Rows may be [date, value] pairs, dicts with date/value keys, or a
    single date->value mapping handled by the caller. Invalid rows are
    dropped with a warning, never silently coerced; duplicate dates keep
    the LAST row (same convention as loaders._clean_bars).
    """
    out: dict[str, float] = {}
    for i, row in enumerate(rows):
        d = v = None
        if isinstance(row, dict):
            for k in _DATE_KEYS:
                if k in row:
                    d = row[k]
                    break
            for k in _VALUE_KEYS:
                if k in row:
                    v = row[k]
                    break
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            d, v = row[0], row[1]
        if not _valid_iso(d):
            log.warning("cd_shadow: dropping row %d — date %r is not a real ISO date", i, d)
            continue
        fv = _num_or_none(v)
        if fv is None or fv <= 0:
            log.warning("cd_shadow: dropping row %d (%s) — value %r is not a positive finite number",
                        i, d, v)
            continue
        if d in out:
            log.warning("cd_shadow: duplicate date %s — keeping last value", d)
        out[d] = fv
    return sorted(out.items())


def _parse_json(path: Path) -> list[tuple[str, float]]:
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return _points_from_rows(raw)
    if isinstance(raw, dict):
        for k in _LIST_KEYS:
            if isinstance(raw.get(k), list):
                return _points_from_rows(raw[k])
        # A bare date -> value mapping (metadata keys are not ISO dates
        # and are ignored by the date check inside _points_from_rows).
        if any(_valid_iso(k) for k in raw):
            return _points_from_rows(sorted(raw.items()))
    raise ValueError(f"{path}: unrecognised canonical series shape "
                     f"({type(raw).__name__})")


def _parse_csv(path: Path) -> list[tuple[str, float]]:
    text = path.read_text()
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        names = {str(f).strip().lower(): f for f in reader.fieldnames if f}
        dkey = next((names[k] for k in _DATE_KEYS if k in names), None)
        vkey = next((names[k] for k in _VALUE_KEYS if k in names), None)
        if dkey is not None and vkey is not None:
            return _points_from_rows(
                [{"date": r.get(dkey), "value": r.get(vkey)} for r in reader])
    # Headerless / unrecognised header: treat each row as [date, value].
    rows = [r for r in csv.reader(io.StringIO(text)) if len(r) >= 2]
    if rows and not _valid_iso(rows[0][0]):
        rows = rows[1:]  # skip a header row we could not map
    return _points_from_rows(rows)


def _load_points(root: Path | None = None) -> list[tuple[str, float]] | None:
    """Parsed canonical points, or None when data is absent/unusable.

    Corrupt data is treated like absent data (None + a logged warning):
    a display benchmark must never take the dashboard down.
    """
    folder = _root(root)
    path = _find_canonical_file(folder)
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _cache.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        points = _parse_csv(path) if path.suffix.lower() == ".csv" else _parse_json(path)
    except Exception as e:  # unreadable/corrupt canonical file == unavailable
        log.warning("cd_shadow: could not parse %s (%s: %s); CD benchmark unavailable",
                    path, type(e).__name__, e)
        return None
    if not points:
        log.warning("cd_shadow: %s contains no valid points; CD benchmark unavailable", path)
        return None
    _cache[key] = (st.st_mtime_ns, st.st_size, points)
    return points


def _check_args(start_date: str, end_date: str, start_cash: float) -> None:
    if not _valid_iso(start_date):
        raise ValueError(f"cd_shadow: start_date {start_date!r} is not a real ISO date")
    if not _valid_iso(end_date):
        raise ValueError(f"cd_shadow: end_date {end_date!r} is not a real ISO date")
    if end_date < start_date:
        raise ValueError(f"cd_shadow: end_date {end_date} is before start_date {start_date}")
    if isinstance(start_cash, bool) or _num_or_none(start_cash) is None or float(start_cash) <= 0:
        raise ValueError(f"cd_shadow: start_cash must be a positive finite number, got {start_cash!r}")


def available(root: Path | None = None) -> bool:
    """True when a usable canonical CD series is present on disk."""
    return _load_points(root) is not None


def series(start_date: str, end_date: str, start_cash: float = 100.0,
           root: Path | None = None) -> list[list] | None:
    """[[date_iso, value], ...] for the CD position over [start, end].

    The first point is exactly ``[start_date, start_cash]`` and the last
    is exactly on ``end_date``; between them, one point per canonical
    step date inside the window. Values are the canonical series scaled
    by ratio (see module docstring), rounded to the cent. Returns None
    when the canonical data is unavailable or the window starts before
    the canonical series begins.
    """
    _check_args(start_date, end_date, start_cash)
    points = _load_points(root)
    if points is None:
        return None
    dates = [d for d, _ in points]
    # Step value in effect at start: last canonical point <= start_date.
    i = bisect.bisect_right(dates, start_date) - 1
    if i < 0:
        log.warning("cd_shadow: window start %s precedes canonical series start %s; "
                    "not covered", start_date, dates[0])
        return None
    base = points[i][1]
    cash = float(start_cash)
    out: list[list] = [[start_date, round(cash, 2)]]
    for d, v in points:
        if start_date < d <= end_date:
            out.append([d, round(cash * v / base, 2)])
    if out[-1][0] != end_date:
        j = bisect.bisect_right(dates, end_date) - 1
        out.append([end_date, round(cash * points[j][1] / base, 2)])
    return out


def final_value(start_date: str, end_date: str, start_cash: float = 100.0,
                root: Path | None = None) -> float | None:
    """Value of the CD position on end_date, to the cent, or None."""
    s = series(start_date, end_date, start_cash, root=root)
    if s is None:
        return None
    return float(s[-1][1])
