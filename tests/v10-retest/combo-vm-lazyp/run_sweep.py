#!/usr/bin/env python3
"""
W11 — COMBO V+M x LAZY PRICES 50/50: CADENCE SWEEP (THE GREAT RETEST
v10). Simulation only.

Strategy: one $100 pot split 50/50 — $50 in the champion
(value+momentum, quarterly top-5 by average percentile rank of
book-to-market and 12-1 momentum, EDGAR point-in-time) and $50 in Lazy
Prices (top-5 by most-recent 10-K whole-document cosine similarity).
Sleeves run standalone at half balance with their own floors disabled;
the pot is combined at the equity-curve level by the ORIGINAL
blend_curves (combo_base.py, verbatim copy of the v8/v9 combo engine):
at each reset date the sleeves are rescaled to 50/50 of the pot less
the transfer cost (0.10% sell + 0.10% buy + $0.01 x 5 sell orders on
the transferred value); the headline final is the end-of-window
post-liquidation value, the parents' basis. Costs inside the sleeves
are the engines' own (0.10%/side + $0.01/sell). Protection: adopted v9
rules AT POT LEVEL ONLY (plain -15% floor from the episode start; on
first halt liquidate as the original blend does, sit in cash 90
calendar days, restart at the next regular decision point under an
episode-2 floor of -15% from the restart balance; second halt ends
the run) — the episode wrapper mirrors combo_base.run_combo_v9 with
only an added placebo-RNG pass-through.

CADENCE TREATMENT (SPEC uniform definition, applied to the BLEND):
cadence governs BOTH legs uniformly. Both parent engines'
quarter_selection_dates are replaced by the SAME cadence calendar
function (the exact functions from the saved Lazy sweep,
backtests/v10-retest/lazy-prices/run_sweep.py, read-only reference),
so on every cadence date BOTH sleeves re-evaluate their signals,
re-rank and re-pick, AND the blend's 50/50 sleeve reset happens on
that same date (inception date excluded — the pot starts 50/50, as
in the original). The v9 restart decision point is likewise the next
cadence date on/after liquidation + 90 days. Native cadence:
quarterly (both legs) with the original's quarterly January reset
rhythm — SPEC CADENCE GRID W11: "combos — quarterly with annual
January reset (classify quarterly)"; not foreign.

Road: DECADE 2016-11-21 -> 2026-11-20, $100/cell.

Placebos: 20 seeds (1..20) per cell — the original combo placebo
design: for each seed BOTH sleeves draw random picks from their own
eligible pools on the identical dates with identical mechanics
(vm_rng = lz_rng = Random(seed)), combined by the identical blend +
v9 machinery.

Phases (argv): ranked | placebo <cadence> | summary. Cells are saved
incrementally to cells/<cadence>.json; the placebo phase merges twin
finals into the existing cell file. Shared inputs READ-ONLY (parent
studies' caches under backtests/v4 and backtests/v7). All outputs
stay in this folder.
"""
import json
import os
import random
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import combo_base as B  # noqa: E402

vm, lz = B.vm, B.lz
DS, DE = "2016-11-21", "2026-11-20"
CELLS_DIR = os.path.join(HERE, "cells")
os.makedirs(CELLS_DIR, exist_ok=True)
SPY_SPEC = 367.80            # SPEC dividend-adjusted decade SPY
CHAMPION_DECADE = 65.89      # champion alone on this road (lazy-quarterly)
LAZY_RESULTS = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/lazy-prices/results.json")
ORDER = ["daily", "weekly", "biweekly", "monthly", "quarterly",
         "semiannual", "annual"]


# ---------------------------------------------------------------- cadences
# (identical definitions to the saved Lazy sweep, run_sweep.py there)
def _firsts(pb, start, end, keyfn):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            k = keyfn(d)
            if k not in seen:
                seen.add(k)
                out.append(d)
    return out


def cad_daily(pb, start, end):
    return [d for d in pb.dates if start <= d <= end]


def cad_weekly(pb, start, end):
    def key(d):
        iso = date.fromisoformat(d).isocalendar()
        return (iso[0], iso[1])
    return _firsts(pb, start, end, key)


def cad_biweekly(pb, start, end):
    return cad_weekly(pb, start, end)[::2]


def cad_monthly(pb, start, end):
    return _firsts(pb, start, end, lambda d: (d[:4], d[5:7]))


def cad_quarterly(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def cad_semiannual(pb, start, end):
    return _firsts(pb, start, end,
                   lambda d: (d[:4], "H1" if d[5:7] <= "06" else "H2"))


def cad_annual(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] == "01" and d[:4] not in seen:
            seen.add(d[:4])
            out.append(d)
    return out


CADENCES = {"daily": cad_daily, "weekly": cad_weekly,
            "biweekly": cad_biweekly, "monthly": cad_monthly,
            "quarterly": cad_quarterly, "semiannual": cad_semiannual,
            "annual": cad_annual}


# ---------------------------------------------------------------- helpers
def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst * 100.0


def cagr_pct(final, start_cash=100.0):
    yrs = (datetime.strptime(DE, "%Y-%m-%d")
           - datetime.strptime(DS, "%Y-%m-%d")).days / 365.25
    return ((final / start_cash) ** (1.0 / yrs) - 1.0) * 100.0


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(pos // 1), int(-(-pos // 1))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ---------------------------------------------------------------- the blend
def run_episode(ctx, sd, ed, start_cash, floor, vm_rng=None, lz_rng=None):
    """One episode: sleeves standalone at half balance, floors off,
    combined by the original blend_curves with resets on the cadence
    dates (first date = inception, skipped by blend_curves)."""
    half = start_cash / 2.0
    vms = vm.run_pot(ctx["pb_vm"], ctx["eq"], ctx["sh"], sd, ed, half,
                     0.0, [], placebo_rng=vm_rng, quiet=True)
    lzs = lz.run_pot(ctx["pb_lz"], ctx["signals"], sd, ed,
                     start_cash=half, floor0=0.0, placebo_rng=lz_rng)
    sel_vm = vm.quarter_selection_dates(ctx["pb_vm"], sd, ed)
    sel_lz = lz.quarter_selection_dates(ctx["pb_lz"], sd, ed)
    assert sel_vm == sel_lz, "cadence calendars diverge between sleeves"
    curve, info = B.blend_curves(vms["curve"], lzs["curve"], sel_vm,
                                 pot0=start_cash, floor=floor)
    info["sleeve_costs"] = vms["costs"] + lzs["costs"]
    info["sleeve_orders"] = len(vms["trades"]) + len(lzs["trades"])
    info["curve"] = curve
    info["sel_dates"] = sel_vm
    return info


def run_blend_v9(ctx, vm_rng=None, lz_rng=None):
    """Full decade run under adopted v9 protection at pot level.
    Mirrors combo_base.run_combo_v9; restart decision point = next
    cadence date on/after liquidation + 90 calendar days."""
    from datetime import date as _d
    start_cash = 100.0
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_episode(ctx, DS, DE, start_cash, floor1, vm_rng, lz_rng)
    out = {"final": r1["final"],
           "costs": r1["sleeve_costs"] + r1["transfer_costs"],
           "orders": r1["sleeve_orders"] + 5 * len(r1["rebalances"]),
           "transfer_costs": r1["transfer_costs"],
           "rebalances": len(r1["rebalances"]),
           "curve": list(r1["curve"]), "halts": [],
           "restart": None, "second_halt": False, "episodes": 1}
    if r1["halt"] is None:
        return out
    liq_date = min(d for d in ctx["pb_vm"].dates
                   if d > r1["halt"] and d <= DE)
    cash = r1["final"]
    signal_close = [v for d, v in r1["curve"] if d == r1["halt"]][-1]
    halt1 = {"signal_date": r1["halt"], "liquidation_date": liq_date,
             "signal_close": round(signal_close, 2),
             "floor_in_effect": floor1, "liquidation_value": round(cash, 2)}
    out["halts"].append(halt1)
    ly, lm, ld = (int(liq_date[:4]), int(liq_date[5:7]),
                  int(liq_date[8:10]))
    day90 = _d(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in r1["sel_dates"]:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _d(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else DE
    for d in ctx["pb_vm"].dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((DE, cash))
        out["restart"] = {"restarted": False,
                          "reason": "no cadence date on/after "
                                    "liquidation + 90 days in window"}
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restart"] = {"restarted": True, "halt_signal_date": r1["halt"],
                      "liquidation_date": liq_date,
                      "restart_date": restart,
                      "restart_balance": round(cash, 2),
                      "episode2_floor": floor2}
    r2 = run_episode(ctx, restart, DE, cash, floor2, vm_rng, lz_rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["sleeve_costs"] + r2["transfer_costs"]
    out["orders"] += r2["sleeve_orders"] + 5 * len(r2["rebalances"])
    out["transfer_costs"] += r2["transfer_costs"]
    out["rebalances"] += len(r2["rebalances"])
    out["curve"] += list(r2["curve"])
    if r2["halt"] is not None:
        liq2 = min(d for d in ctx["pb_vm"].dates
                   if d > r2["halt"] and d <= DE)
        sc2 = [v for d, v in r2["curve"] if d == r2["halt"]][-1]
        out["second_halt"] = True
        out["halts"].append({"signal_date": r2["halt"],
                             "liquidation_date": liq2,
                             "signal_close": round(sc2, 2),
                             "floor_in_effect": floor2,
                             "liquidation_value": round(r2["final"], 2),
                             "second_halt": True})
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def set_cadence(cadence):
    fn = CADENCES[cadence]
    vm.quarter_selection_dates = fn
    lz.quarter_selection_dates = fn


def build_ctx():
    print("loading value+momentum book (cache)...", flush=True)
    pb_vm, eq, sh = B.build_vm_book()
    print("loading lazy-prices signals + book (cache)...", flush=True)
    pb_lz, signals, _ = B.build_lz_book()
    ctx = {"pb_vm": pb_vm, "eq": eq, "sh": sh,
           "pb_lz": pb_lz, "signals": signals}
    install_shims(ctx)
    return ctx


# ------------------------------------------------------- performance shims
# PERFORMANCE-ONLY shims (engine logic untouched): the parents' own
# PriceBook.close_on_or_before / next_open are linear bar scans and
# vm.pit_value re-parses every EDGAR row's dates on every selection
# day — at a daily cadence over a decade that is the whole runtime.
# The replacements below return IDENTICAL values (bisect over the
# same sorted bars; pit_value's winner is provably the row with the
# latest filed date < asof — freshness can only kill that winner, and
# with it every earlier row — tie-broken by (prio, end) exactly as
# the original's max key). Equivalence is PROVEN, not assumed: the
# `verify` phase unit-tests pit_value_fast against the original on
# every series over sampled decade dates and re-runs the integrity
# combo (CONT + VAL) with shims installed, asserting $540.72 /
# $312.55 to the cent before any sweep number is produced. The same
# indexed-book technique is what the saved Lazy sweep used
# (FastPriceBook over the same bars).
_PIT_STRUCTS = {}


def _pit_struct(rows):
    key = id(rows)
    st = _PIT_STRUCTS.get(key)
    if st is None:
        best_by_filed = {}
        for filed, end, val, prio in rows:
            cur = best_by_filed.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best_by_filed[filed] = (prio, end, val)
        fileds = sorted(best_by_filed)
        st = (fileds, best_by_filed,
              {f: date(int(f[:4]), int(f[5:7]), int(f[8:10])).toordinal()
               for f in fileds})
        _PIT_STRUCTS[key] = st
    return st


def pit_value_fast(rows, asof, max_age_days=548):
    fileds, best_by_filed, ords = _pit_struct(rows)
    i = bisect_left(fileds, asof) - 1
    if i < 0:
        return None
    filed = fileds[i]
    a_ord = date(int(asof[:4]), int(asof[5:7]),
                 int(asof[8:10])).toordinal()
    if ords[filed] < a_ord - max_age_days:
        return None
    _prio, end, val = best_by_filed[filed]
    return (filed, end, val)


def _fast_book_methods(pb):
    dates_by_t = {}
    for t, bl in pb.bars.items():
        ds = [b["d"] for b in bl]
        assert ds == sorted(ds), f"bars for {t} not sorted"
        dates_by_t[t] = ds

    def close_on_or_before(t, d, _pb=pb, _dbt=dates_by_t):
        bl = _pb.bars.get(t, [])
        if not bl:
            return None
        i = bisect_right(_dbt[t], d) - 1
        return bl[i]["c"] if i >= 0 else None

    def next_open(t, d, _pb=pb, _dbt=dates_by_t):
        bl = _pb.bars.get(t, [])
        if not bl:
            return None, None
        i = bisect_right(_dbt[t], d)
        if i >= len(bl):
            return None, None
        b = bl[i]
        return b["d"], b["o"]

    pb.close_on_or_before = close_on_or_before
    pb.next_open = next_open


def install_shims(ctx):
    _fast_book_methods(ctx["pb_vm"])
    _fast_book_methods(ctx["pb_lz"])
    vm.pit_value = pit_value_fast


def phase_verify():
    """Equivalence gate for the performance shims (see note above)."""
    print("loading value+momentum book (cache)...", flush=True)
    pb_vm, eq, sh = B.build_vm_book()
    print("loading lazy-prices signals + book (cache)...", flush=True)
    pb_lz, signals, _ = B.build_lz_book()
    orig_pit = vm.pit_value
    # 1) pit_value unit test: every series x sampled decade dates
    days = [d for d in pb_vm.dates if DS <= d <= DE]
    sample = days[::17] + days[-1:]
    n = 0
    for rows_by_t in (eq, sh):
        for t, rows in rows_by_t.items():
            for d in sample:
                a, b = orig_pit(rows, d), pit_value_fast(rows, d)
                assert a == b, f"pit mismatch {t} {d}: {a} vs {b}"
                n += 1
    print(f"pit_value equivalence: {n} comparisons identical",
          flush=True)
    # 2) book-method unit test on random (ticker, date) pairs
    rng = random.Random(7)
    tickers = list(pb_vm.bars)
    for pb in (pb_vm, pb_lz):
        orig_cob = pb.close_on_or_before
        orig_no = getattr(pb, "next_open", None)  # lz book has none
        _fast_book_methods(pb)
        for _ in range(3000):
            t = rng.choice(tickers)
            d = rng.choice(days)
            assert orig_cob(t, d) == pb.close_on_or_before(t, d), (t, d)
            if orig_no is not None:
                assert orig_no(t, d) == pb.next_open(t, d), (t, d)
    print("book-method equivalence: 6000 comparisons identical",
          flush=True)
    # 3) full-combo gate: CONT + VAL with shims == published finals
    vm.pit_value = pit_value_fast
    for wname, pub in (("continuous", 540.72), ("validation", 312.55)):
        sd, ed = B.WINDOWS[wname]
        combo = B.run_combo(pb_vm, eq, sh, pb_lz, signals, sd, ed)
        got = round(combo["final"], 2)
        print(f"SHIM GATE combo {wname}: ${got} vs published ${pub}",
              flush=True)
        assert got == pub, f"shim gate FAILED on {wname}"
    print("SHIM GATE: PASS — sweep numbers use identical-value "
          "lookups only", flush=True)


def lazy_leg_final(cadence):
    with open(LAZY_RESULTS) as f:
        d = json.load(f)
    c = d["cells"][cadence]
    return c["final"] if isinstance(c, dict) else None


def cell_payload(cadence, run, spy_plumb):
    restart = run["restart"]
    return {
        "slug": "combo-vm-lazyp", "cadence": cadence,
        "window": [DS, DE], "start_cash": 100.0,
        "final": round(run["final"], 2),
        "cagr_pct": round(cagr_pct(run["final"]), 2),
        "max_dd_pct": round(max_dd(run["curve"]), 2),
        "costs": round(run["costs"], 2),
        "transfer_costs": round(run["transfer_costs"], 2),
        "orders": run["orders"],
        "rebalances": run["rebalances"],
        "halts": run["halts"],
        "restart": restart,
        "second_halt": run["second_halt"],
        "episodes": run["episodes"],
        "spy_final_plumbing": round(spy_plumb, 2),
        "spy_final_spec_dividend_adjusted": SPY_SPEC,
        "legs_same_decade": {
            "champion_value_momentum": {
                "final": CHAMPION_DECADE,
                "source": "SPEC reference / lazy-quarterly test: the "
                          "champion ALONE on this road, under its OWN "
                          "sleeve-level floor — halted 2018-12-21, "
                          "restarted 2019-04-01, second halt "
                          "2020-03-20, run ended. HALT-WINDOW "
                          "ASYMMETRY: inside this blend the champion "
                          "leg has NO sleeve floor (protection is at "
                          "pot level only), so it kept trading through "
                          "the windows where the standalone champion "
                          "was halted or dead. Blend-vs-$65.89 is "
                          "therefore not apples-to-apples."},
            "lazy_prices": {
                "final": lazy_leg_final(cadence),
                "source": "backtests/v10-retest/lazy-prices/"
                          "results.json cells (read-only), same "
                          "cadence, same decade, $100 standalone pot "
                          "with its own v9 floor"}},
        "placebo": None,
        "equity_curve": [[d, round(v, 4)] for d, v in run["curve"]],
        "source": "fresh run in this folder's run_sweep.py (original "
                  "combo engines verbatim; cadence calendar governs "
                  "both sleeves and the blend resets)"}


def save_cell(payload):
    path = os.path.join(CELLS_DIR, f"{payload['cadence']}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=str)
    print(f"saved cells/{payload['cadence']}.json final "
          f"${payload['final']:,.2f}", flush=True)


def phase_ranked():
    ctx = build_ctx()
    spy_plumb, _ = vm.spy_net(ctx["pb_vm"], DS, DE, 100.0)
    print(f"SPY plumbing decade: ${spy_plumb:.2f} (SPEC ${SPY_SPEC})",
          flush=True)
    for cadence in ORDER:
        set_cadence(cadence)
        run = run_blend_v9(ctx)
        save_cell(cell_payload(cadence, run, spy_plumb))
        print(f"{cadence}: final ${run['final']:,.2f} halts "
              f"{len(run['halts'])} orders {run['orders']} costs "
              f"${run['costs']:,.2f}", flush=True)


def phase_placebo(cadence):
    ctx = build_ctx()
    set_cadence(cadence)
    path = os.path.join(CELLS_DIR, f"{cadence}.json")
    with open(path) as f:
        payload = json.load(f)
    twins = []
    for seed in range(1, 21):
        run = run_blend_v9(ctx, vm_rng=random.Random(seed),
                           lz_rng=random.Random(seed))
        twins.append({"seed": seed, "final": round(run["final"], 2),
                      "costs": round(run["costs"], 2),
                      "orders": run["orders"],
                      "halts": len(run["halts"]),
                      "halt_dates": [h["signal_date"]
                                     for h in run["halts"]]})
        print(f"  {cadence} placebo seed {seed}: "
              f"${run['final']:,.2f} halts {len(run['halts'])}",
              flush=True)
    finals = sorted(t["final"] for t in twins)
    beats = sum(1 for x in finals if payload["final"] > x)
    payload["placebo"] = {
        "beaten": beats, "of": 20,
        "median": round(pct(finals, 0.5), 2),
        "best": finals[-1], "worst": finals[0],
        "finals_sorted": finals, "twins": twins,
        "note": "20 random-pair twins (seeds 1..20): BOTH sleeves draw "
                "random picks from their own eligible pools on the "
                "identical cadence dates, combined by the identical "
                "blend + v9 machinery (original combo placebo design)"}
    save_cell(payload)
    print(f"{cadence}: ranked beats {beats}/20 placebos", flush=True)


def phase_summary():
    with open(os.path.join(HERE, "integrity.json")) as f:
        integ = json.load(f)
    cells, money = {}, []
    for cadence in ORDER:
        with open(os.path.join(CELLS_DIR, f"{cadence}.json")) as f:
            p = json.load(f)
        pl = p.get("placebo") or {}
        cells[cadence] = {
            "final": p["final"], "cagr_pct": p["cagr_pct"],
            "max_dd_pct": p["max_dd_pct"],
            "halts": len(p["halts"]),
            "restart": bool(p["restart"] and p["restart"].get("restarted")),
            "second_halt": p["second_halt"],
            "costs": p["costs"], "orders": p["orders"],
            "placebo_beaten": pl.get("beaten"),
            "placebo_note": pl.get("note", "placebos not run"),
            "lazy_leg_final_same_cadence": p["legs_same_decade"]
                                            ["lazy_prices"]["final"],
            "champion_leg_decade_reference": CHAMPION_DECADE}
        if p["final"] > SPY_SPEC and pl.get("beaten") == 20:
            money.append(cadence)
    out = {
        "slug": "combo-vm-lazyp",
        "area": "long-horizon 50/50 blend of the two promoted engines "
                "(champion value+momentum + Lazy Prices), one pot — "
                "judged in this sweep on the DECADE road at every "
                "cadence",
        "area_source": "SPEC THE CADENCE SWEEP (Terry 2026-11-21 "
                       "~22:09); W11 combinations — long-horizon blends",
        "native_cadence": "quarterly",
        "cadence": "quarterly (both legs re-pick quarterly; blend "
                   "resets 50/50 at the same selection dates, with "
                   "the annual January reset rhythm of the original)",
        "original_cadence_foreign": False,
        "original_cadence_note": "Not foreign. The original program "
                                 "test already ran both legs quarterly "
                                 "with quarterly blend resets — the "
                                 "native form. The sweep varies the "
                                 "tempo uniformly for both legs.",
        "cadence_treatment": "Cadence governs BOTH legs uniformly: "
                             "both engines' selection calendars are "
                             "replaced by the same cadence calendar, "
                             "so both sleeves re-rank/re-pick and the "
                             "blend rebalances to 50/50 on cadence "
                             "dates only; the v9 restart decision "
                             "point is the next cadence date on/after "
                             "liquidation + 90 days.",
        "integrity": {
            "status": integ["status"],
            "original_finals": {"CONT": 540.72, "VAL": 312.55},
            "reproduced_finals": {
                "CONT": integ["checks"]["combo_continuous"]["reproduced"],
                "VAL": integ["checks"]["combo_validation"]["reproduced"]},
            "detail": "run_integrity.py through combo_base.py (the "
                      "original combo engine verbatim): parents also "
                      "reproduced to the cent (V+M CONT $544.47 / VAL "
                      "$288.05; Lazy CONT $504.34 / VAL $324.12; SPY "
                      "$313.62 / $187.77). Original verdict: the best "
                      "of the six-for-six dilutions — 98.7% of the "
                      "champion on CONT with two Lazy-driven halts "
                      "added on the fold road; original record: 20 "
                      "quarters won 10 / lost 10, 6 quarters with any "
                      "halt. Full checks in integrity.json."},
        "decade_spy_final": SPY_SPEC,
        "decade_spy_note": "SPEC-verified dividend-adjusted figure; "
                           "this plumbing's own SPY net on the same "
                           "book is saved per cell as "
                           "spy_final_plumbing; money-cadence calls "
                           "use the stricter $367.80 hurdle.",
        "champion_decade": {
            "final": CHAMPION_DECADE,
            "note": "HALT-WINDOW ASYMMETRY, stated plainly: $65.89 "
                    "is the champion ALONE on this road under its "
                    "OWN sleeve-level floor (halted 2018-12-21, "
                    "restarted 2019-04-01, second halt 2020-03-20, "
                    "run ended). Inside this blend the champion leg "
                    "has NO sleeve floor — protection lives at pot "
                    "level only — so the leg kept trading through "
                    "the windows where the standalone champion was "
                    "halted or dead. Any blend final above $65.89 is "
                    "partly that asymmetry, not pure blend skill. "
                    "The champion's crown rests on the 2010 road "
                    "($1,415.62) and the 2019 road (CONT $544.47 / "
                    "VAL $288.05)."},
        "champion_reference": {"LONG": 1415.62, "CONT": 544.47,
                               "VAL": 288.05, "DECADE": CHAMPION_DECADE},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,   # filled in RESULTS.md after review
        "verdict_change": None}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved results.json; money_cadences:", money, flush=True)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "ranked"
    if phase == "verify":
        phase_verify()
    elif phase == "ranked":
        phase_ranked()
    elif phase == "placebo":
        phase_placebo(sys.argv[2])
    elif phase == "summary":
        phase_summary()
    else:
        raise SystemExit(f"unknown phase {phase}")
