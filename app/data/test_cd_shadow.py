"""CD shadow benchmark loader (W6). Run: python3 data/test_cd_shadow.py (from app/)

Covers both states of the CD-benchmark build:
  * ABSENT  -- backtests/cd-benchmark/ has no canonical series yet:
               available() is False, series()/final_value() return None.
  * PRESENT -- the canonical series exists: series()/final_value() are
               checked for self-consistency on the standard windows and,
               where the folder publishes results in a parseable form,
               final_value() is verified against them TO THE CENT.

The math checks use synthetic fixture series written by this test into
temp dirs (never the real benchmark folder) -- no rate is invented for
the real benchmark; the fixtures only prove the loader's step/scaling
arithmetic.
"""
import json, re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import cd_shadow

PASS = []
def ok(n): PASS.append(n); print(f"  PASS {n}")
def note(n): print(f"  NOTE {n}")

STANDARD_WINDOWS = [
    ("2019-01-02", "2026-11-20"),  # SPEC middle road / task window
    ("2023-01-03", "2026-11-20"),  # task window
    ("2023-01-01", "2026-11-20"),  # SPEC judging road
    ("2016-11-21", "2026-11-20"),  # SPEC 10-year road, if published/covered
    ("2010-01-04", "2026-11-20"),  # SPEC 17-year road, if published/covered
]


def test_absent():
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"; empty.mkdir()
        missing = Path(td) / "does-not-exist"
        for root in (empty, missing):
            assert cd_shadow.available(root=root) is False
            assert cd_shadow.series("2020-01-01", "2021-01-01", root=root) is None
            assert cd_shadow.final_value("2020-01-01", "2021-01-01", root=root) is None
        ok("absent folder / empty folder -> available False, series/final None")
        # a corrupt canonical file is 'unavailable', never an exception
        (empty / "cd_series.json").write_text("{not json")
        cd_shadow._clear_cache()
        assert cd_shadow.available(root=empty) is False
        assert cd_shadow.series("2020-01-01", "2021-01-01", root=empty) is None
        ok("corrupt canonical file -> unavailable, no raise")
        # a canonical file with no valid points is also unavailable
        (empty / "cd_series.json").write_text(json.dumps([["not-a-date", 1.0]]))
        cd_shadow._clear_cache()
        assert cd_shadow.available(root=empty) is False
        ok("canonical file with no valid points -> unavailable")
    # the benchmark's RATES table alone is NOT a value series: per
    # SPEC.md / HUNT-LOG.md, cd-rates-monthly.csv holds FDIC prevailing
    # rates (the roller's input) and must never be read as values.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "cd-rates-monthly.csv").write_text(
            "month,rate_12m,rate_6m\n2020-01,0.59,0.52\n2020-02,0.57,0.50\n")
        (root / "SPEC.md").write_text("# spec\n")
        assert cd_shadow.available(root=root) is False
        assert cd_shadow.series("2020-01-01", "2021-01-01", root=root) is None
        ok("rates-only folder (cd-rates-monthly.csv) -> unavailable, rates never read as values")


def test_fixture_json_list():
    pts = [["2020-01-01", 100.0], ["2020-07-01", 102.0],
           ["2021-01-01", 104.04], ["2021-07-01", 106.1208]]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "cd_series.json").write_text(json.dumps(pts))
        assert cd_shadow.available(root=root) is True; ok("fixture: available True")
        s = cd_shadow.series("2020-01-01", "2021-01-01", root=root)
        assert s == [["2020-01-01", 100.0], ["2020-07-01", 102.0],
                     ["2021-01-01", 104.04]], s
        ok("fixture: exact step series on published points")
        assert cd_shadow.final_value("2020-01-01", "2021-01-01", root=root) == 104.04
        ok("fixture: final_value 104.04 (2% then 2% on $100)")
        # step / forward-fill: mid-step start and end hold the last point
        s = cd_shadow.series("2020-03-15", "2020-12-31", root=root)
        assert s == [["2020-03-15", 100.0], ["2020-07-01", 102.0],
                     ["2020-12-31", 102.0]], s
        ok("fixture: forward-fill between/behind step points, no invented accrual")
        # scaling: same ratios, different cash
        assert cd_shadow.final_value("2020-01-01", "2021-01-01", 250.0, root=root) == 260.10
        ok("fixture: start_cash scales by ratio (250 -> 260.10)")
        # mid-series start rebases on the step value in effect that day
        assert cd_shadow.final_value("2020-07-01", "2021-07-01", root=root) == 104.04
        ok("fixture: window starting on a later step rebases correctly")
        # before the canonical start: not covered -> None (no extrapolation)
        assert cd_shadow.series("2019-06-01", "2020-06-01", root=root) is None
        assert cd_shadow.final_value("2019-06-01", "2020-06-01", root=root) is None
        ok("fixture: window before canonical start -> None")


def test_fixture_shapes():
    # dict shape with named keys
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "cd_series.json").write_text(json.dumps(
            {"series": [{"date": "2022-01-03", "value": 50.0},
                        {"date": "2023-01-03", "value": 51.0}]}))
        assert cd_shadow.final_value("2022-01-03", "2023-01-03", root=root) == 102.0
        ok("fixture: dict {'series': [{date, value}]} shape, $50 base cancels")
    # CSV shape, 1.0-based index values
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "cd_series.csv").write_text(
            "date,value\n2022-01-03,1.0\n2023-01-03,1.02\n")
        assert cd_shadow.final_value("2022-01-03", "2023-01-03", root=root) == 102.0
        ok("fixture: CSV shape, 1.0-based index cancels")


def test_bad_args():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "cd_series.json").write_text(json.dumps([["2020-01-01", 100.0]]))
        for args in [("2021-01-01", "2020-01-01"), ("not-a-date", "2020-01-01"),
                     ("2020-02-30", "2021-01-01")]:
            try:
                cd_shadow.series(*args, root=root); raise AssertionError(args)
            except ValueError:
                pass
        for cash in (0, -5, float("nan"), float("inf"), True):
            try:
                cd_shadow.series("2020-01-01", "2020-06-01", cash, root=root)
                raise AssertionError(cash)
            except ValueError:
                pass
        ok("bad dates / reversed window / non-positive cash -> ValueError")


def _published_candidates(root: Path, start: str, end: str) -> set[float]:
    """Hunt the benchmark folder's published results for ONE window's
    final value. Returns the set of distinct candidate dollar values
    found; the caller only asserts when exactly one candidate exists,
    so an unfamiliar results layout degrades to a NOTE, not a failure.
    """
    cands: set[float] = set()
    if not root.is_dir():
        return cands
    num = r"(\d{1,7}(?:\.\d{1,4})?)"

    def walk(node, dates_seen):
        if isinstance(node, dict):
            strs = [v for v in node.values() if isinstance(v, str)]
            here = dates_seen | {s for s in strs if s in (start, end)}
            for k, v in node.items():
                kl = str(k).lower()
                if isinstance(v, (int, float)) and not isinstance(v, bool) \
                        and start in here and end in here \
                        and any(w in kl for w in ("final", "value", "cd", "end")):
                    cands.add(round(float(v), 2))
                walk(v, here)
        elif isinstance(node, list):
            for v in node:
                walk(v, dates_seen)

    for p in sorted(root.iterdir()):
        if not p.is_file() or "result" not in p.name.lower():
            continue
        try:
            text = p.read_text()
        except OSError:
            continue
        if p.suffix.lower() == ".json":
            try:
                walk(json.loads(text), set())
            except Exception:
                pass
        else:
            for line in text.splitlines():
                if start in line and end in line:
                    for m in re.finditer(r"\$?\s*" + num, line):
                        cands.add(round(float(m.group(1)), 2))
    # a candidate equal to a year or the $100 start is not a result
    cands.discard(100.0)
    return cands


def test_real_data_if_present():
    if not cd_shadow.available():
        note("canonical CD data absent at test time -- published-results "
             "verification skipped (absent + fixture checks above cover "
             "the contract); it activates automatically once "
             "backtests/cd-benchmark/ lands.")
        return
    root = cd_shadow._root()
    verified = 0
    for start, end in STANDARD_WINDOWS:
        s = cd_shadow.series(start, end)
        if s is None:
            note(f"window {start}->{end} not covered by canonical series; skipped")
            continue
        assert s[0] == [start, 100.0], s[0]
        assert s[-1][0] == end, s[-1]
        vals = [v for _, v in s]
        assert all(b >= a for a, b in zip(vals, vals[1:])), "CD series must not decrease"
        assert cd_shadow.final_value(start, end) == s[-1][1]
        ok(f"real data {start}->{end}: consistent, non-decreasing, "
           f"final ${s[-1][1]:,.2f}")
        cands = _published_candidates(root, start, end)
        if len(cands) == 1:
            pub = next(iter(cands))
            got = cd_shadow.final_value(start, end)
            assert round(got, 2) == pub, \
                f"{start}->{end}: final_value {got} != published {pub}"
            verified += 1
            ok(f"real data {start}->{end}: final_value matches PUBLISHED "
               f"result ${pub:,.2f} TO THE CENT")
        elif len(cands) > 1:
            note(f"{start}->{end}: multiple published candidates {sorted(cands)}; "
                 "not asserting (layout ambiguity)")
        else:
            note(f"{start}->{end}: no parseable published result found in "
                 f"{root}; self-consistency only")
    if verified == 0:
        note("no standard window had a parseable published result; "
             "to-the-cent verification will engage when the benchmark "
             "folder publishes results alongside its series")


def main():
    test_absent()
    test_fixture_json_list()
    test_fixture_shapes()
    test_bad_args()
    test_real_data_if_present()
    print(f"test_cd_shadow: ALL PASS ({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
