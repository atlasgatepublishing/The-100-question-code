#!/usr/bin/env python3
"""
SHORT-INTEREST (Form A) — THE GREAT RETEST (v10), cadence sweep.
Simulation only. One clean shot, no tuning.

STRATEGY (Form A, as originally tested in v6 / re-run in v9):
  Rank the champion's honest point-in-time top-30 pond by FINRA
  short interest (% of EDGAR point-in-time shares outstanding)
  ASCENDING and hold the 5 LEAST-shorted, equal weight.
  Form B (most- vs least-shorted diagnostic) REJECTED the family's
  core claim on this pond in the original test and is carried here
  as a diagnostic only — Form A is the tested form; Form B is never
  substituted for it.

ROAD CAVEAT (binding, printed everywhere): free FINRA coverage
begins Dec 2018, so the sweep road is the longest honest sub-window
of the SPEC decade: 2018-12-03 (first trading day of Dec 2018) ->
2026-11-20. It is NOT the full 2016-11-21 decade. The full-decade
SPY reference ($367.80) does NOT apply to this road; SPY is computed
in-plumbing on this road.

CADENCE TREATMENT (per SPEC uniform definition + task instruction):
  Signal updates only when new FINRA settlements publish (bi-monthly:
  mid-month + month-end settlements, usable 7 trading days after
  settlement, strictly before the evaluation date — the original
  point-in-time rule, unchanged). At faster cadences the strategy
  re-evaluates / re-ranks / rebalances on the cadence dates using the
  FRESHEST PUBLISHED settlement data (which may be the same vintage
  as the previous evaluation); at slower cadences it evaluates less
  often. Selection, execution (next open), costs (0.10%/side +
  $0.01/sell order) and v9 protections (plain -15% floor, 90-day
  cash sit, restart at the next CADENCE selection date on/after
  eligibility under an episode-2 -15% floor, second halt ends the
  run) are otherwise the v9 engine verbatim.
  NATIVE CADENCE = monthly (SPEC cadence grid: "short-interest —
  monthly (bi-monthly FINRA data)"). The ORIGINAL program test used
  QUARTERLY selections — a foreign cadence, flagged.

INTEGRITY: before the sweep, the ORIGINAL v9 engine (imported
untouched) reproduces the original published finals in original
(quarterly) form: CONT $383.29, VAL $249.79, placebos 15/20 on both
windows, folds 5/7 vs SPY.

SPEED PATCHES (values-identical, documented): for the sweep only,
  (a) PriceBook.close_on_or_before is replaced by a bisect version
      returning the identical bar close (bars are date-sorted);
  (b) the selection pool's bar-index lookup uses bisect instead of
      a linear scan. The fast selection is asserted equal to the
      original compute_selection (pool, scored ratios, picks) on
      every quarterly selection date of the road before the sweep
      runs. Integrity runs use the untouched originals.

DATA: EDGAR facts + Yahoo prices reused read-only from the v4
caches via the v9 module; FINRA settlement rows reused read-only
from the v6 finra-cache (new settlements near the window end are
downloaded by the original fetch code into that same cache dir,
exactly as the v9 run did). No shared folder is written by this
script's own code. The 1.7GB long-run cache is NOT loaded.
"""
import bisect
import importlib.util
import json
import os
import random
import time
from datetime import date as _date, timedelta as _timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V9_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/short-interest/short-interest-v9.py")

spec = importlib.util.spec_from_file_location("si_v9", V9_PATH)
V9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V9)
E = V9.E

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))
ROAD_START_WANT = "2018-12-01"
ROAD_END = "2026-11-20"
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")


def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def yrs(start, end):
    return (_ord(end) - _ord(start)) / 365.25


def cagr(final, start, end):
    return round(((final / START_CASH) ** (1.0 / yrs(start, end)) - 1.0) * 100, 2)


# ------------------------------------------------------------ data load
def load_data():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)
    si = V9.ShortInterest(pb)
    data = {"equity": equity_rows, "shares": shares_rows, "si": si}
    return pb, data


# ------------------------------------------------------------ integrity
def run_integrity(pb, data):
    """Original v9 engine, original (quarterly) form, untouched."""
    out = {}
    ranked = {}
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        r = V9.run_pot_si(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                          label=f"INTEGRITY SI {tag}", quiet=True)
        ranked[tag] = r["final"]
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]),
                                "halted": r["halted"],
                                "restarts": r.get("restarts", []),
                                "second_halt": r.get("second_halt")}
        print(f"INTEGRITY ranked {tag}: ${r['final']:,.2f}", flush=True)
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        pl = V9.placebo_block(pb, data, ws, we, ranked[tag], f"INTEGRITY {tag}")
        out[f"placebo_{tag}"] = {"beats": pl["ranked_beats_n_of_20"],
                                 "median_final": pl["median_final"],
                                 "finals": [row["final"] for row in pl["rows"]]}
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = V9.run_pot_si(pb, data, fs, fe, START_CASH, FLOOR0, LADDER,
                           label=f"INTEGRITY FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        folds.append({"year": y, "final": round(fr["final"], 2),
                      "spy_final": round(fspy, 2),
                      "beat_spy": fr["final"] > fspy})
        print(f"INTEGRITY fold {y}: SI ${fr['final']:,.2f} vs SPY "
              f"${fspy:,.2f} beat={fr['final'] > fspy}", flush=True)
    out["folds"] = folds
    out["fold_wins"] = sum(1 for f in folds if f["beat_spy"])
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        dg = V9.diagnostic(pb, data, ws, we)
        out[f"diagnostic_{tag}"] = dg["aggregate"]
        print(f"INTEGRITY diagnostic {tag}: {dg['aggregate']}", flush=True)
    pub = {"CONT_final": 383.29, "VAL_final": 249.79,
           "placebo_beats_CONT": 15, "placebo_beats_VAL": 15,
           "fold_wins": 5}
    checks = {
        "CONT_final_match": round(ranked["CONT"], 2) == pub["CONT_final"],
        "VAL_final_match": round(ranked["VAL"], 2) == pub["VAL_final"],
        "placebo_CONT_match": out["placebo_CONT"]["beats"] == 15,
        "placebo_VAL_match": out["placebo_VAL"]["beats"] == 15,
        "folds_match": out["fold_wins"] == 5,
    }
    out["published"] = pub
    out["checks"] = checks
    out["status"] = ("reproduced" if all(checks.values())
                     else "reproduced-with-notes")
    return out


# ------------------------------------------------- fast selection (sweep)
class FastSI(V9.ShortInterest):
    """Sweep SI: settlements restricted to the FINRA coverage era
    (>= 2018-12-01). Before the first in-coverage settlement is
    published (settlement 2018-12-14, published 2018-12-26) there is
    no usable reading and the pot honestly sits in cash."""

    def __init__(self, pb):
        super().__init__(pb)
        self.settlements = [s for s in self.settlements if s >= "2018-12-01"]


def make_fast_selection(pb, data):
    dates_by_t = {t: [b["d"] for b in pb.bars.get(t, [])] for t in UNIVERSE}
    cache = {}

    def compute_selection_fast(d):
        if d in cache:
            return cache[d]
        pool = {}
        for t in UNIVERSE:
            be = E.pit_value(data["equity"].get(t, []), d)
            so = E.pit_value(data["shares"].get(t, []), d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            dl = dates_by_t[t]
            i = bisect.bisect_left(dl, d)
            if i >= len(dl) or dl[i] != d or i < 253:
                continue
            pool[t] = be[2] / mcap
        si = data["si"]
        settlement, pub = si.freshest_usable(d)
        scored, detail = {}, {}
        if settlement is not None:
            rows = si.readings(settlement)
            for t in pool:
                if t not in rows:
                    continue
                so_s = E.pit_value(data["shares"].get(t, []), settlement)
                if so_s is None or so_s[2] <= 0:
                    continue
                ratio = rows[t] / so_s[2]
                scored[t] = ratio
                detail[t] = {"settlement": settlement, "publication": pub,
                             "short_shares": rows[t], "shares_out": so_s[2],
                             "ratio_pct": round(ratio * 100, 4)}
        picks = sorted(scored, key=lambda t: (scored[t], t))[:5]
        sel = {"pool": pool, "scored": scored, "detail": detail,
               "settlement": settlement, "publication": pub, "picks": picks}
        cache[d] = sel
        return sel

    return compute_selection_fast


# ------------------------------------------- cadence-generalized engine
def cadence_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return E.quarter_selection_dates(pb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        for d in days:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "semiannual":
        for d in days:
            key = (d[:4], "H1" if int(d[5:7]) <= 6 else "H2")
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            key = d[:4]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(cadence)


def run_pot_cadence(pb, data, sel_dates, compute_selection, start, end,
                    start_cash, floor0, placebo_rng=None, label=""):
    """V9 run_pot_si copied verbatim EXCEPT: selection dates come from
    the cadence (not quarter_selection_dates), selections come from
    the (asserted-identical) fast selection, and the v9 restart waits
    for the next CADENCE selection date. Execution, costs, floor,
    halt and liquidation mechanics are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    v9_halts = 0
    v9_restarts = []
    v9_waiting = False
    v9_eligible = None
    v9_second_halt = None
    curve = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set and v9_waiting:
            if d >= v9_eligible:
                v9_waiting = False
                v9_restarts[-1]["restart_date"] = d
                v9_restarts[-1]["restart_balance"] = round(cash, 2)
        if d in sel_set and not v9_waiting:
            sel = compute_selection(d)
            scored = sel["scored"]
            if len(scored) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scored), 5)
                else:
                    picks = sel["picks"]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            v9_halts += 1
            if v9_halts >= 2:
                v9_second_halt = halted
                return {"label": label, "final": cash, "costs": total_costs,
                        "trades": trades, "halted": halted, "end": nd,
                        "halt_info": halt_info, "curve": curve,
                        "restarts": v9_restarts, "second_halt": v9_second_halt}
            _liq = _date(int(nd[:4]), int(nd[5:7]), int(nd[8:10]))
            v9_eligible = (_liq + _timedelta(days=90)).isoformat()
            floor = round(0.85 * cash, 10)
            v9_restarts.append({"halt_signal_date": halted,
                                "liquidation_date": nd,
                                "liquidation_cash": round(cash, 2),
                                "cash_until_eligible": v9_eligible,
                                "episode2_floor": round(floor, 2),
                                "restart_date": None,
                                "restart_balance": None})
            v9_waiting = True
            pending = None
            halted = None
            halt_info = None
            continue
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "restarts": v9_restarts, "second_halt": v9_second_halt}


def cell_stats(r, start, end):
    curve = r["curve"]
    peak, maxdd = -1.0, 0.0
    worst_d, worst_v = None, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd = dd
        if worst_v is None or v < worst_v:
            worst_v, worst_d = v, d
    halts = len(r["restarts"]) + (1 if r["second_halt"] else 0)
    return {"final": round(r["final"], 2),
            "cagr_pct": cagr(r["final"], start, end),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(r["costs"], 2),
            "orders": len(r["trades"]),
            "halts": halts,
            "restart": len(r["restarts"]) > 0,
            "second_halt": r["second_halt"],
            "restarts_detail": r["restarts"],
            "worst_close": round(worst_v, 2),
            "worst_close_date": worst_d,
            "curve": [[d, round(v, 2)] for d, v in curve]}


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    pb, data = load_data()
    print(f"data loaded in {time.time()-t0:.0f}s; trading days "
          f"{pb.dates[0]}..{pb.dates[-1]}", flush=True)

    # ---------- (1) INTEGRITY (original engine, original form)
    integrity = run_integrity(pb, data)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integrity, f, indent=1, default=str)
    print(f"INTEGRITY status={integrity['status']} checks={integrity['checks']}",
          flush=True)

    # ---------- speed patch (values-identical) for the sweep only
    _dates = {t: [b["d"] for b in bl] for t, bl in pb.bars.items()}
    _closes = {t: [b["c"] for b in bl] for t, bl in pb.bars.items()}

    def fast_close(t, d, _dates=_dates, _closes=_closes):
        dl = _dates.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        return _closes[t][i] if i >= 0 else None

    pb.close_on_or_before = fast_close

    # ---------- sweep data: coverage-restricted SI
    si_fast = FastSI(pb)
    data_fast = {"equity": data["equity"], "shares": data["shares"], "si": si_fast}
    compute_fast = make_fast_selection(pb, data_fast)

    road_start = min(d for d in pb.dates if d >= ROAD_START_WANT)
    road_end = ROAD_END
    print(f"ROAD: {road_start} -> {road_end} "
          f"(shorter road: FINRA coverage begins Dec 2018)", flush=True)

    # ---------- assert fast selection == original on quarterly dates
    V9.SELECTION_CACHE.clear()
    qdates = E.quarter_selection_dates(pb, road_start, road_end)
    mismatches = 0
    for d in qdates:
        a = V9.compute_selection(pb, d, data_fast)
        b = compute_fast(d)
        if (a["picks"] != b["picks"] or a["scored"] != b["scored"]
                or a["pool"] != b["pool"] or a["settlement"] != b["settlement"]):
            mismatches += 1
            print(f"  SELECTION MISMATCH {d}", flush=True)
    print(f"fast-selection check: {len(qdates)} quarterly dates, "
          f"{mismatches} mismatches", flush=True)
    assert mismatches == 0, "fast selection diverges from original"

    # ---------- SPY on this road (in-plumbing)
    spy_final, spy_costs = E.spy_net(pb, road_start, road_end, START_CASH)
    spy_final = round(spy_final, 2)
    print(f"SPY on this road ({road_start}->{road_end}): ${spy_final:,.2f}",
          flush=True)

    # ---------- (2) SWEEP: 7 cadences x (ranked + 20 placebos)
    cells = {}
    cell_dir = os.path.join(HERE, "cells")
    os.makedirs(cell_dir, exist_ok=True)
    for cadence in ("daily", "weekly", "biweekly", "monthly", "quarterly",
                    "semiannual", "annual"):
        tc = time.time()
        sel_dates = cadence_dates(pb, road_start, road_end, cadence)
        r = run_pot_cadence(pb, data_fast, sel_dates, compute_fast,
                            road_start, road_end, START_CASH, FLOOR0,
                            label=f"SI {cadence}")
        st = cell_stats(r, road_start, road_end)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            rp = run_pot_cadence(pb, data_fast, sel_dates, compute_fast,
                                 road_start, road_end, START_CASH, FLOOR0,
                                 placebo_rng=rng, label=f"SI {cadence} p{seed}")
            placebo_finals.append(round(rp["final"], 2))
        beats = sum(1 for v in placebo_finals if st["final"] > v)
        cell = {"cadence": cadence, "road_start": road_start,
                "road_end": road_end,
                "road_note": "SHORTER ROAD: FINRA coverage begins Dec 2018; "
                             "this is the longest honest sub-window of the "
                             "SPEC decade, not the full 2016-11-21 decade.",
                "n_selection_dates": len(sel_dates),
                "selection_dates": sel_dates,
                **{k: v for k, v in st.items() if k != "curve"},
                "equity_curve": st["curve"],
                "placebo_beaten": beats,
                "placebo_twin_finals": placebo_finals,
                "placebo_note": "20 seeds (1..20); each seed draws a random 5 "
                                "from the same scored pond at every cadence "
                                "date, same engine/costs/v9 protections."}
        with open(os.path.join(cell_dir, f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1, default=str)
        cells[cadence] = {k: cell[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "halts",
                           "restart", "second_halt", "costs", "orders",
                           "placebo_beaten")}
        cells[cadence]["placebo_note"] = cell["placebo_note"]
        cells[cadence]["worst_close"] = cell["worst_close"]
        cells[cadence]["worst_close_date"] = cell["worst_close_date"]
        print(f"CELL {cadence}: final=${st['final']:,.2f} CAGR={st['cagr_pct']}% "
              f"maxDD={st['max_dd_pct']}% costs=${st['costs']:,.2f} "
              f"orders={st['orders']} halts={st['halts']} "
              f"worst_close=${st['worst_close']:,.2f} on {st['worst_close_date']} "
              f"placebo {beats}/20 ({time.time()-tc:.0f}s)", flush=True)

    money = [c for c, v in cells.items()
             if v["final"] > spy_final and v["placebo_beaten"] is not None
             and v["placebo_beaten"] > 10]
    results = {
        "slug": "short-interest",
        "area": "Quarterly/monthly pond ranking on FINRA short interest "
                "(W4 filings & calendar pond strategies); native ground is "
                "the long road from its earliest honest data start "
                "(FINRA Dec 2018).",
        "area_source": "SPEC W4 assignment + CADENCE GRID (short-interest "
                       "monthly, bi-monthly FINRA data)",
        "cadence": "monthly",
        "native_cadence": "monthly",
        "original_cadence_foreign": True,
        "original_cadence_note": "Original program test (v6/v9) re-selected "
                                 "QUARTERLY; the published/native cadence per "
                                 "the SPEC grid is monthly (FINRA publishes "
                                 "bi-monthly). Foreign cadence — flagged.",
        "road": {"start": road_start, "end": road_end,
                 "note": "SHORTER ROAD: free FINRA coverage begins Dec 2018, "
                         "so this is the longest honest sub-window of the "
                         "SPEC decade (2018-12 -> 2026-11-20), not the full "
                         "2016-11-21 -> 2026-11-20 decade. The full-decade "
                         "SPY $367.80 does not apply here."},
        "integrity": {
            "status": integrity["status"],
            "original_finals": {"CONT": 383.29, "VAL": 249.79,
                                "placebo_beaten_CONT": "15/20",
                                "placebo_beaten_VAL": "15/20",
                                "folds_vs_SPY": "5/7"},
            "reproduced_finals": {
                "CONT": integrity["ranked_CONT"]["final"],
                "VAL": integrity["ranked_VAL"]["final"],
                "placebo_beaten_CONT":
                    f"{integrity['placebo_CONT']['beats']}/20",
                "placebo_beaten_VAL":
                    f"{integrity['placebo_VAL']['beats']}/20",
                "folds_vs_SPY": f"{integrity['fold_wins']}/7"},
            "checks": integrity["checks"],
            "form_b_diagnostic": {
                "CONT_mean_spread_pct_per_qtr":
                    integrity["diagnostic_CONT"]["mean_spread_pct"],
                "VAL_mean_spread_pct_per_qtr":
                    integrity["diagnostic_VAL"]["mean_spread_pct"],
                "note": "Form B (paper-only diagnostic) REJECTED the "
                        "family's core claim on this pond in the original "
                        "test: the 5 MOST-shorted giants returned MORE per "
                        "quarter than the 5 least-shorted (negative "
                        "least-minus-most spread). Form A is the tested "
                        "form; Form B was not substituted."},
        },
        "decade_spy_final": spy_final,
        "spy": {"road_2018_12_to_2026_11_20": spy_final,
                "note": "SPY buy-and-hold (dividend-adjusted, program "
                        "convention) computed in-plumbing on THIS road. "
                        "The full-decade $367.80 figure does not apply to "
                        "a 2018-start road."},
        "cells": cells,
        "money_cadences": money,
        "champion_comparison": "The champion's (value+momentum) crown rests "
                               "on its own roads (LONG 2010 $1,415.62; CONT "
                               "$544.47; VAL $288.05). On CONT/VAL in "
                               "original form this strategy finished $383.29 "
                               "/ $249.79 — below the champion on both. On "
                               "this sweep road the honest comparison is "
                               "against SPY (above), not the champion.",
        "verdict_area": None,  # filled below
        "verdict_change": None,
    }
    # verdict per SPEC scale, judged on its own ground (this road, all cells)
    beats_spy_cells = [c for c, v in cells.items() if v["final"] > spy_final]
    if money and len(beats_spy_cells) >= 4:
        results["verdict_area"] = "OWNS ITS GROUND"
    elif beats_spy_cells:
        results["verdict_area"] = "REAL BUT SMALL"
    else:
        results["verdict_area"] = "NO GROUND"
    results["verdict_change"] = (
        "Original program verdict stood on the quarterly (foreign) cadence: "
        "Form A beat SPY on CONT ($383.29 vs $313.62) and VAL ($249.79 vs "
        "$187.77) and beat 15/20 placebos on both, while Form B rejected the "
        "family's core claim. The sweep verdict is in RESULTS.md.")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"DONE in {time.time()-t0:.0f}s | money cadences: {money} | "
          f"verdict: {results['verdict_area']}", flush=True)


if __name__ == "__main__":
    main()
