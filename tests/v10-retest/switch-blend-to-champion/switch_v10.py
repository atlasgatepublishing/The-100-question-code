#!/usr/bin/env python3
"""
SWITCH-BLEND-TO-CHAMPION folder — THE GREAT RETEST (v10) cadence sweep.
Simulation only.

IDENTITY NOTE (read first — the program's own record contains two
different "midpoint switches", and this folder's assignment mixes
their labels):
  * Switch A (slug in the SPEC: switch-blend-to-champion) = the 50/50
    champion x N-F3 blend FIRST, pure champion SECOND. Original form
    (Terry's rules, CONT 2019-01-02 -> 2026-11-20): $526.68. It FAILED
    its pre-registered bar and was closed ("NOT ADOPTED").
  * Switch B (slug: switch-champion-to-blend) = pure champion FIRST,
    50/50 blend SECOND. Original form (Terry's rules, CONT): $549.43 —
    the first combination test to beat both parents (champion $544.47
    by $4.96, blend $532.39 by $17.04); placebos 18/20 on CONT,
    20/20 on VAL (VAL is the pure blend by construction there);
    status CANDIDATE, promotion only via the forward paper trial;
    LONG (2010-01-04 -> 2026-11-20, v9 rules) $920.77 vs the
    champion's $1,415.62 (backtests/long-run-2010/results_switch.json).
This worker's assigned integrity targets (CONT $549.43, margin over
the champion $4.96, CANDIDATE status, LONG $920.77) are Switch B's
numbers, so the SWEEP below runs Switch B's mechanism. Switch A's
original final is ALSO reproduced in the integrity gate (its
$526.68 is the "his-rules" figure in the assignment) and the naming
collision is reported, not hidden.

SWEEP TREATMENT (precise, frozen before the run):
  * Road: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs
    (0.10%/side + $0.01 per sell order), adopted v9 protections
    (plain -15% floor per episode; first halt -> liquidate at next
    open, 90 calendar days in cash, restart at the cadence's next
    regular decision date under an episode-2 floor of -15% from the
    restart balance; second halt ends the run). Floor monitoring is
    daily (protection, as in the original engines), at every cadence.
  * The handover: the switch trigger is the calendar halfway point
    of the road, 2021-11-21 (given in the assignment; verified:
    2016-11-21 + (2026-11-20 - 2016-11-21).days//2 = 2021-11-21).
    The pot runs the pure champion alone until the first CADENCE
    selection date on or after the trigger, and the 50/50 blend
    (champion sleeve + N-F3 sleeve, budgets reset to 50/50 of the
    combined close at each selection, combo machinery verbatim)
    from that selection on. The trigger is an absolute calendar
    date: it does not move if an episode restarts.
  * Cadence governs BOTH legs: at non-quarterly cadences, both the
    champion leg (phase 1) and both blend sleeves (phase 2)
    re-rank and rebalance ONLY on cadence dates (first trading day
    of each week / second week / month / calendar quarter /
    half-year / year; daily = every trading day), selection at the
    close, execution at the next open — the original engines'
    mechanics with only the selection-date set changed. Native
    cadence: quarterly.
  * Placebos: 20 seeds (1..20) per cell; each sleeve draws 5 random
    names from its own eligible pool on identical dates with the
    identical phase structure, resets and v9 protections (the
    original switch's own placebo design, generalized to cadence).

DATA: read-only reuse of the v4 caches through the original v8
switch module's imports (SEC EDGAR companyfacts + Yahoo prices in
backtests/v4/data and backtests/v4/value-momentum-honest-data).
That price cache begins 2017-06-01 and 12-1 momentum needs 253
prior bars, so on the decade window every cadence sits in cash
until its first scoreable selection date (~mid-2018); the first
such date is reported per cell. Nothing is backfilled. The pond is
the champion's fixed 30-name UNIVERSE (the Nov-2016 pond).

PERFORMANCE NOTES (no logic change): a FastBook returns identical
bars/closes via bisect (the pattern the vm-panicgate v10 worker
cross-validated to the cent); VM and N-F3 pools/picks depend only
on the date, so they are precomputed once per trading day (VM via
an ordinal-bisect equivalent of champ.pit_value — same (filed,
prio, end) max-key rule and 548-day freshness gate) and shared by
the ranked pot and all 20 twins of every cadence. The integrity
gate below proves the generalized engine at quarterly cadence
reproduces the original engines' finals before any sweep number
is taken.
"""
import bisect
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
V8 = os.path.join(ROOT, "v8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("switchB_v8", os.path.join(
    V8, "switch-champion-to-blend", "switch-champion-to-blend.py"))
A = _load("switchA_v8", os.path.join(
    V8, "switch-blend-to-champion", "switch-blend-to-champion.py"))
champ = B.champ
nf3 = B.nf3
combo = A.combo
UNIVERSE = B.UNIVERSE
START_CASH = 100.0
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
TRIGGER_DECADE = "2021-11-21"          # halfway of the decade road
TRIGGER_CONT_ORIG = "2023-01-01"       # the original test's frozen mark
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def _ord(ds):
    return _date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).toordinal()


# ------------------------------------------------------------ fast book
class FastBook:
    """Same bars as champ.PriceBook; close_on_or_before via bisect
    (identical values — last bar with d <= date)."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}
        self._cl = {t: [b["c"] for b in bl]
                    for t, bl in bars_by_ticker.items()}
        self._ix = {t: {d: i for i, d in enumerate(ds)}
                    for t, ds in self._dl.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self._cl[t][i] if i >= 0 else None


# ------------------------------------------------- fast point-in-time
class PitIndex:
    """Ordinal equivalent of champ.pit_value (see module docstring)."""

    def __init__(self, rows):
        keyed = sorted((_ord(f), p, e, v) for f, e, v, p in rows)
        self.keys = [(k[0], k[1], k[2]) for k in keyed]
        self.vals = [k[3] for k in keyed]
        self.fileds = [k[0] for k in keyed]

    def value(self, asof_ord):
        i = bisect.bisect_left(self.fileds, asof_ord) - 1
        if i < 0:
            return None
        if self.fileds[i] < asof_ord - 548:
            return None
        return self.vals[i]


def vm_pool_picks(fb, eq_idx, sh_idx, d):
    """Identical scoring to B.Scorer.vm for one date, fast path.
    Returns (pool_dict ticker->(bm, mom), ranked picks)."""
    asof = _ord(d)
    scores = {}
    for t in UNIVERSE:
        be = eq_idx[t].value(asof)
        so = sh_idx[t].value(asof)
        px = fb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so <= 0:
            continue
        mcap = so * px
        if mcap <= 0:
            continue
        bm = be / mcap
        didx = fb._ix.get(t, {}).get(d)
        if didx is None or didx < 253:
            continue
        bl = fb.bars[t]
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, mom)
    picks = []
    if len(scores) >= 5:
        vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
        combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
        picks = sorted(combined, key=lambda t: -combined[t])[:5]
    return scores, picks


def nf3_pool_picks(facts, d, stats):
    """Identical to B.Scorer.nf3 for one date (original nf3 engine)."""
    scores = {}
    for t in UNIVERSE:
        a = nf3.signal_at(facts[t], d, stats)
        if a is not None:
            scores[t] = a
    picks = []
    if len(scores) >= 5:
        picks = sorted(scores, key=lambda t: (scores[t], t))[:5]
    return scores, picks


# ------------------------------------------------------- cadence dates
def cadence_dates(fb, cadence, start, end):
    days = [d for d in fb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return champ.quarter_selection_dates(fb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            y, w, _ = _date(int(d[:4]), int(d[5:7]),
                            int(d[8:10])).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w))
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks, wseen = [], set()
        for d in days:
            y, w, _ = _date(int(d[:4]), int(d[5:7]),
                            int(d[8:10])).isocalendar()
            if (y, w) not in wseen:
                wseen.add((y, w))
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        keyf = lambda d: (d[:4], d[5:7])
    elif cadence == "semiannual":
        days = [d for d in days if d[5:7] in ("01", "07")]
        keyf = lambda d: (d[:4], d[5:7])
    elif cadence == "annual":
        keyf = lambda d: d[:4]
    else:
        raise ValueError(cadence)
    for d in days:
        k = keyf(d)
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


# ------------------------------------------- generalized switch engine
def run_switch_cadence(pb, vm_scores, nf3_scores, sel_dates, start, end,
                       switch_on_or_after, start_cash=100.0, floor0=85.0,
                       placebo_rng=None):
    """B.run_switch (champion -> blend) with two substitutions ONLY:
    the selection-date set is the cadence's, and per-date pools/picks
    come from the precomputed dicts (identical values). Sleeve,
    transfer, floor and liquidation mechanics are the combo/switch
    machinery verbatim (B.Sleeve / B.sleeve_sells / B.sleeve_buys /
    B._liquidate)."""
    vm = B.Sleeve("VM", start_cash)
    f3 = B.Sleeve("NF3", 0.0)
    sleeves = [vm, f3]
    sel_set = set(sel_dates)
    switch_date = None
    for d in sel_dates:
        if d >= switch_on_or_after:
            switch_date = d
            break
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    transfers = []
    halted = None
    halt_info = None
    switch_close = None
    switch_exec_date = None

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    for di, d in enumerate(days):
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = B.sleeve_sells(
                        pb, s, d, targets)
                    budgets[s.name] = budget
            vals = {s.name: s.open_value(pb, d) for s in sleeves}
            excess = {n: vals[n] - budgets.get(n, vals[n]) for n in vals}
            if excess["VM"] > 0.005 and excess["NF3"] < -0.005:
                amt = min(excess["VM"], -excess["NF3"], vm.cash)
                if amt > 0.005:
                    vm.cash -= amt
                    f3.cash += amt
                    transfers.append((d, "VM->NF3", round(amt, 2)))
            elif excess["NF3"] > 0.005 and excess["VM"] < -0.005:
                amt = min(excess["NF3"], -excess["VM"], f3.cash)
                if amt > 0.005:
                    f3.cash -= amt
                    vm.cash += amt
                    transfers.append((d, "NF3->VM", round(amt, 2)))
            for s in sleeves:
                if s.pending is not None:
                    targets, _ = s.pending
                    B.sleeve_buys(pb, s, d, targets,
                                  opens_by_sleeve[s.name])
                    s.pending = None
            if switch_exec_date is None and switch_close is not None:
                switch_exec_date = d
        if d in sel_set:
            vm_pool, vm_picks = vm_scores.get(d, ({}, []))
            if placebo_rng is not None and len(vm_pool) >= 5:
                vm_picks = placebo_rng.sample(sorted(vm_pool), 5)
            combined = combined_close(d)
            if switch_date is not None and d >= switch_date:
                f3_pool, f3_picks = nf3_scores.get(d, ({}, []))
                if placebo_rng is not None and len(f3_pool) >= 5:
                    f3_picks = placebo_rng.sample(sorted(f3_pool), 5)
                budget = combined / 2.0
                if len(vm_pool) >= 5:
                    vm.pending = ({t: budget / 5.0 for t in vm_picks},
                                  budget)
                if len(f3_pool) >= 5:
                    f3.pending = ({t: budget / 5.0 for t in f3_picks},
                                  budget)
                if d == switch_date and switch_close is None:
                    switch_close = combined
            else:
                if len(vm_pool) >= 5:
                    vm.pending = ({t: combined / 5.0 for t in vm_picks},
                                  combined)
        v = combined_close(d)
        curve.append((d, v))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            B._liquidate(pb, sleeves, nd, "SELL-HALT")
            final = vm.cash + f3.cash
            return {"final": final, "costs": vm.costs + f3.costs,
                    "trades": vm.trades + f3.trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "transfers": transfers,
                    "switch_date": switch_date,
                    "switch_close": switch_close,
                    "switch_exec_date": switch_exec_date}
    last = days[-1]
    B._liquidate(pb, sleeves, last, "SELL-END")
    final = vm.cash + f3.cash
    return {"final": final, "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "transfers": transfers,
            "switch_date": switch_date, "switch_close": switch_close,
            "switch_exec_date": switch_exec_date}


# ------------------------------------------------------------ v9 wrapper
def run_v9_switch(pb, vm_scores, nf3_scores, sel_dates, start, end,
                  switch_on_or_after, start_cash, placebo_rng=None):
    """Adopted v9 protections around run_switch_cadence: episode 1
    under a plain -15% floor; on first halt, 90 calendar days in
    cash, restart at the first cadence selection date on/after
    liquidation+90d under an episode-2 floor of -15% from the
    restart balance; a second halt ends the run."""
    floor1 = round(0.85 * start_cash, 2)

    def run_ep(s, e, cash, floor, rng):
        sel = [d for d in sel_dates if s <= d <= e]
        return run_switch_cadence(pb, vm_scores, nf3_scores, sel, s, e,
                                  switch_on_or_after, cash, floor,
                                  placebo_rng=rng)

    r1 = run_ep(start, end, start_cash, floor1, placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "halts": [], "restarts": [], "second_halt": None,
           "episodes": 1, "switch_date": r1.get("switch_date"),
           "switch_close": r1.get("switch_close"),
           "switch_exec_date": r1.get("switch_exec_date")}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = _ord(liq_date) + 90
    restart = None
    for cand in sel_dates:
        if _ord(cand) >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    entry = {"episode": 1, "halt_signal_date": r1["halted"],
             "halt_signal_close": r1["halt_info"]["signal_close"],
             "floor_in_effect": r1["halt_info"]["floor_in_effect"],
             "liquidation_date": liq_date, "restart_date": restart,
             "restart_balance": round(cash, 2), "episode2_floor": floor2}
    out["halts"].append(entry)
    out["restarts"].append(entry)
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    # episode 2 placebo twin keeps consuming the SAME rng stream
    r2 = run_ep(restart, end, cash, floor2, placebo_rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2.get("switch_date") and out["switch_date"] is None:
        out["switch_date"] = r2["switch_date"]
        out["switch_close"] = r2.get("switch_close")
        out["switch_exec_date"] = r2.get("switch_exec_date")
    if r2["halted"] is not None:
        sh = {"episode": 2, "halt_signal_date": r2["halted"],
              "halt_signal_close": r2["halt_info"]["signal_close"],
              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
              "liquidation_date": r2["end"],
              "final": round(r2["final"], 2)}
        out["second_halt"] = sh
        out["halts"].append(sh)
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ---------------------------------------------------------------- utils
def curve_stats(curve, final, start, end):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (_ord(end) - _ord(start)) / 365.25
    cagr = (final / START_CASH) ** (1.0 / yrs) * 100 - 100 \
        if final > 0 else -100.0
    return round(maxdd * 100, 2), round(cagr, 2)


def finish_curve(pb, run, start, end):
    curve = sorted(run["curve"], key=lambda kv: kv[0])
    if curve and curve[-1][0] < end:
        last_v = run["final"]
        for d in pb.dates:
            if curve[-1][0] < d <= end:
                curve.append((d, last_v))
    return [[d, round(v, 2)] for d, v in curve]


def halfway(start, end):
    d0, d1 = _date.fromisoformat(start), _date.fromisoformat(end)
    from datetime import timedelta
    return (d0 + timedelta(days=(d1 - d0).days // 2)).isoformat()


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    log = []

    def say(msg):
        print(msg, flush=True)
        log.append(msg)

    # ---------------- build inputs (the original switch test's build)
    ciks = champ.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity",
                             prio=2) +
            champ.pit_series(
                facts, "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding",
                             prio=3) +
            champ.pit_series(facts, "us-gaap",
                             "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(
                facts, "us-gaap",
                "WeightedAverageNumberOfSharesOutstandingBasic",
                prio=1))
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
    pb_orig = champ.PriceBook(bars)
    fb = FastBook(bars)
    scorer = B.Scorer(pb_orig, equity_rows, shares_rows,
                      facts_by_ticker)
    say(f"inputs built {time.time()-t0:.0f}s; bars "
        f"{fb.dates[0]}..{fb.dates[-1]} ({len(fb.dates)} days)")

    published = {
        "VM": {"CONT": 544.47, "VAL": 288.05},
        "NF3": {"CONT": 505.43, "VAL": 289.53},
        "BLEND": {"CONT": 532.39, "VAL": 290.45},
        "SPY": {"CONT": 313.62, "VAL": 187.77},
        "SWITCH_B": {"CONT": 549.43, "VAL": 290.45},
        "SWITCH_A": {"CONT": 526.68, "VAL": 288.05},
    }
    windows = {"CONT": CONT, "VAL": VAL}
    integ = {"published": published}

    # ---- integrity 1: parents standalone, original engines verbatim
    say("== INTEGRITY 1: parents (original engines, Terry form) ==")
    integ["parents"] = {}
    for wname, (ws, we) in windows.items():
        vm_r = champ.run_pot(pb_orig, equity_rows, shares_rows, ws, we,
                             100.0, 85.0, [], label=f"INTEG {wname} VM",
                             quiet=True)
        stats = {"direct": 0, "derived": 0}
        f3_r = nf3.run_pot(pb_orig, facts_by_ticker, ws, we, 100.0,
                           85.0, label=f"INTEG {wname} NF3",
                           stats=stats)
        s, _ = champ.spy_net(pb_orig, ws, we, 100.0)
        got = {"VM": round(vm_r["final"], 2),
               "NF3": round(f3_r["final"], 2), "SPY": round(s, 2)}
        integ["parents"][wname] = got
        ok = all(got[k] == published[k][wname]
                 for k in ("VM", "NF3", "SPY"))
        say(f"  {wname}: VM ${got['VM']:,.2f} NF3 ${got['NF3']:,.2f} "
            f"SPY ${got['SPY']:,.2f} -> {'PASS' if ok else 'FAIL'}")
        assert ok, f"parent integrity failed on {wname}"

    # ---- integrity 2: pure blend through the switch script's combo copy
    say("== INTEGRITY 2: pure blend (B.run_combo, Terry form) ==")
    integ["blend"] = {}
    for wname, (ws, we) in windows.items():
        r = B.run_combo(pb_orig, scorer, ws, we, 100.0, 85.0,
                        label=f"INTEG {wname} BLEND")
        integ["blend"][wname] = round(r["final"], 2)
        ok = integ["blend"][wname] == published["BLEND"][wname]
        say(f"  {wname}: blend ${r['final']:,.2f} -> "
            f"{'PASS' if ok else 'FAIL'}")
        assert ok, f"blend integrity failed on {wname}"

    # ---- integrity 3: Switch B ranked + placebos, original form
    say("== INTEGRITY 3: Switch B (B.run_switch, Terry form, "
        "switch on/after 2023-01-01) ==")
    integ["switch_b_terry"] = {}
    for wname, (ws, we) in windows.items():
        r = B.run_switch(pb_orig, scorer, ws, we, TRIGGER_CONT_ORIG,
                         label=f"INTEG {wname} SWITCH B")
        twins, twin_halted = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pr = B.run_switch(pb_orig, scorer, ws, we,
                              TRIGGER_CONT_ORIG, placebo_rng=rng,
                              label=f"INTEG {wname} B PLACEBO {seed}")
            twins.append(round(pr["final"], 2))
            twin_halted.append(pr["halted"])
        beaten = sum(1 for x in twins if r["final"] > x)
        integ["switch_b_terry"][wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "switch_date": r["switch_date"],
            "switch_close": (round(r["switch_close"], 2)
                             if r["switch_close"] is not None else None),
            "placebo_finals": twins, "placebo_halted": twin_halted,
            "placebo_beaten": beaten,
            "placebo_best_twin": max(twins),
            "placebo_median": round(
                (sorted(twins)[9] + sorted(twins)[10]) / 2.0, 2)}
        ok = round(r["final"], 2) == published["SWITCH_B"][wname]
        say(f"  {wname}: Switch B ${r['final']:,.2f} switch="
            f"{r['switch_date']} placebo {beaten}/20 best-twin "
            f"${max(twins):,.2f} median ${integ['switch_b_terry'][wname]['placebo_median']:,.2f}"
            f" -> ranked {'PASS' if ok else 'FAIL'}")
        assert ok, f"Switch B integrity failed on {wname}"

    # ---- integrity 4: Switch A ranked, original form (the slug's own
    # original engine; its $526.68 is the assignment's "his-rules" line)
    say("== INTEGRITY 4: Switch A (A.run_switch, Terry form) ==")
    scorer_a = combo.Scorer(pb_orig, equity_rows, shares_rows,
                            facts_by_ticker)
    integ["switch_a_terry"] = {}
    for wname, (ws, we) in windows.items():
        r = A.run_switch(pb_orig, scorer_a, ws, we, 100.0, 85.0,
                         label=f"INTEG {wname} SWITCH A")
        integ["switch_a_terry"][wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "switch_date": (r["switch_info"]["selection_date"]
                            if r.get("switch_info") else None)}
        ok = integ["switch_a_terry"][wname]["final"] == \
            published["SWITCH_A"][wname]
        say(f"  {wname}: Switch A ${r['final']:,.2f} -> "
            f"{'PASS' if ok else 'FAIL'}")
        assert ok, f"Switch A integrity failed on {wname}"

    # ---- integrity 5: generalized engine == original engine
    # (quarterly, plain floor, CONT) + degenerate never-switch check
    say("== INTEGRITY 5: generalized cadence engine cross-checks ==")
    eq_idx = {t: PitIndex(equity_rows[t]) for t in UNIVERSE}
    sh_idx = {t: PitIndex(shares_rows[t]) for t in UNIVERSE}
    sel_q_cont = cadence_dates(fb, "quarterly", CONT[0], CONT[1])
    vm_q, nf3_q = {}, {}
    stats = {"direct": 0, "derived": 0}
    for d in sel_q_cont:
        vm_q[d] = vm_pool_picks(fb, eq_idx, sh_idx, d)
        nf3_q[d] = nf3_pool_picks(facts_by_ticker, d, stats)
    r = run_switch_cadence(fb, vm_q, nf3_q, sel_q_cont, CONT[0], CONT[1],
                           TRIGGER_CONT_ORIG, 100.0, 85.0)
    x1 = round(r["final"], 2)
    r_never = run_switch_cadence(fb, vm_q, nf3_q, sel_q_cont, CONT[0],
                                 CONT[1], "9999-12-31", 100.0, 85.0)
    x2 = round(r_never["final"], 2)
    integ["crosscheck"] = {
        "generalized_quarterly_terry_CONT": x1, "expected": 549.43,
        "never_switch_quarterly_terry_CONT": x2,
        "never_switch_expected_champion": 544.47}
    say(f"  generalized quarterly CONT ${x1:,.2f} (expect $549.43); "
        f"never-switch ${x2:,.2f} (expect champion $544.47)")
    assert x1 == 549.43 and x2 == 544.47, "cross-check FAILED"
    say("  cross-checks PASS")

    # ---- integrity 6 (context): Switch B under v9 protections at
    # quarterly cadence on CONT/VAL, trigger = each window's halfway
    say("== CONTEXT: Switch B, v9 protections, quarterly, "
        "halfway trigger per window ==")
    integ["switch_b_v9_quarterly"] = {}
    for wname, (ws, we) in windows.items():
        sel = cadence_dates(fb, "quarterly", ws, we)
        trig = halfway(ws, we)
        vm_s, nf3_s = {}, {}
        for d in sel:
            vm_s[d] = vm_pool_picks(fb, eq_idx, sh_idx, d)
            nf3_s[d] = nf3_pool_picks(facts_by_ticker, d, stats)
        run = run_v9_switch(fb, vm_s, nf3_s, sel, ws, we, trig,
                            START_CASH)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            tr = run_v9_switch(fb, vm_s, nf3_s, sel, ws, we, trig,
                               START_CASH, placebo_rng=rng)
            twins.append(round(tr["final"], 2))
        beaten = sum(1 for x in twins if run["final"] > x)
        integ["switch_b_v9_quarterly"][wname] = {
            "final": round(run["final"], 2), "trigger": trig,
            "switch_date": run["switch_date"],
            "halts": run["halts"], "second_halt": bool(run["second_halt"]),
            "placebo_finals": twins, "placebo_beaten": beaten,
            "placebo_best_twin": max(twins)}
        say(f"  {wname} v9: ${run['final']:,.2f} trigger {trig} "
            f"switch {run['switch_date']} halts {len(run['halts'])} "
            f"placebo {beaten}/20 best-twin ${max(twins):,.2f}")

    with open(os.path.join(HERE, "_integrity.json"), "w") as f:
        json.dump(integ, f, indent=1, default=str)
    say(f"integrity saved ({time.time()-t0:.0f}s)")

    # ---------------- precompute decade pools (all trading days)
    say("== PRECOMPUTE decade pools ==")
    days_dec = [d for d in fb.dates if DECADE[0] <= d <= DECADE[1]]
    vm_all, nf3_all = {}, {}
    for d in days_dec:
        vm_all[d] = vm_pool_picks(fb, eq_idx, sh_idx, d)
        nf3_all[d] = nf3_pool_picks(facts_by_ticker, d, stats)
    say(f"  pools for {len(days_dec)} days ({time.time()-t0:.0f}s)")

    spy_local, _ = champ.spy_net(fb, DECADE[0], DECADE[1], START_CASH)
    say(f"  local-cache SPY decade ${spy_local:,.2f} (cache begins "
        f"{fb.dates[0]}; SPEC headline $367.80)")

    # decade cross-check: never-switch quarterly v9 == champion $65.89?
    sel_q_dec = cadence_dates(fb, "quarterly", DECADE[0], DECADE[1])
    chk = run_v9_switch(fb, vm_all, nf3_all, sel_q_dec, DECADE[0],
                        DECADE[1], "9999-12-31", START_CASH)
    champ_decade_check = round(chk["final"], 2)
    say(f"  never-switch quarterly v9 decade ${champ_decade_check:,.2f}"
        f" (champion decade reference $65.89) halts "
        f"{[h['halt_signal_date'] for h in chk['halts']]}")

    # ---------------- SWEEP
    say("== SWEEP: Switch B, DECADE, 7 cadences, v9 protections, "
        f"trigger {TRIGGER_DECADE} ==")
    cells = {}
    for cad in CADENCES:
        sel = cadence_dates(fb, cad, DECADE[0], DECADE[1])
        first_pick = next(
            (d for d in sel if len(vm_all.get(d, ({}, []))[0]) >= 5),
            None)
        ranked = run_v9_switch(fb, vm_all, nf3_all, sel, DECADE[0],
                               DECADE[1], TRIGGER_DECADE, START_CASH)
        curve = finish_curve(fb, ranked, DECADE[0], DECADE[1])
        maxdd, cagr = curve_stats(curve, ranked["final"], *DECADE)
        twins, twin_rows = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)
            tr = run_v9_switch(fb, vm_all, nf3_all, sel, DECADE[0],
                               DECADE[1], TRIGGER_DECADE, START_CASH,
                               placebo_rng=rng)
            twins.append(round(tr["final"], 2))
            twin_rows.append({
                "seed": seed, "final": round(tr["final"], 2),
                "halts": [h["halt_signal_date"] for h in tr["halts"]],
                "second_halt": bool(tr["second_halt"]),
                "orders": len(tr["trades"]),
                "costs": round(tr["costs"], 2)})
        srt = sorted(twins)
        beaten = sum(1 for x in twins if ranked["final"] > x)
        cell = {
            "slug": "switch-blend-to-champion",
            "strategy_run": "Switch B mechanism (champion -> blend) "
                            "per the assignment's integrity targets; "
                            "see RESULTS.md naming note",
            "cadence": cad,
            "window": [DECADE[0], DECADE[1]], "start_cash": START_CASH,
            "switch_trigger_on_or_after": TRIGGER_DECADE,
            "switch_date": ranked["switch_date"],
            "switch_close": (round(ranked["switch_close"], 2)
                             if ranked.get("switch_close") is not None
                             else None),
            "switch_exec_date": ranked.get("switch_exec_date"),
            "data_note": ("v4 price cache begins 2017-06-01; 12-1 "
                          "momentum needs 253 prior bars; pot in cash "
                          "until first scoreable selection"),
            "first_scoreable_selection": first_pick,
            "n_eval_dates": len(sel),
            "final": round(ranked["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": maxdd, "costs": round(ranked["costs"], 2),
            "orders": len(ranked["trades"]),
            "halts": ranked["halts"],
            "restart": bool(ranked["restarts"]),
            "second_halt": bool(ranked["second_halt"]),
            "episodes": ranked["episodes"],
            "champion_decade_reference": 65.89,
            "margin_over_champion_decade": round(
                ranked["final"] - 65.89, 2),
            "placebo_beaten": beaten,
            "placebo_note": ("20 random-rank twins (seeds 1-20), each "
                             "sleeve drawing 5 random names from its "
                             "own eligible pool on identical dates, "
                             "identical phase structure/resets and "
                             "v9 protections."),
            "placebo_distribution": {
                "median": round((srt[9] + srt[10]) / 2.0, 2),
                "best": srt[-1], "worst": srt[0],
                "mean": round(sum(twins) / len(twins), 2),
                "halted_twins": sum(1 for r in twin_rows if r["halts"]),
                "second_halt_twins": sum(
                    1 for r in twin_rows if r["second_halt"])},
            "placebo_twins": twin_rows,
            "placebo_twin_finals": twins,
            "equity_curve": curve,
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        say(f"  {cad:11s} final ${cell['final']:,.2f} CAGR "
            f"{cagr:+.2f}% maxDD {maxdd:.2f}% halts "
            f"{len(ranked['halts'])} 2nd={cell['second_halt']} "
            f"switch={ranked['switch_date']} costs "
            f"${cell['costs']:.2f} orders {cell['orders']} placebo "
            f"{beaten}/20 median-twin "
            f"${cell['placebo_distribution']['median']:,.2f} "
            f"({time.time()-t0:.0f}s)")

    with open(os.path.join(HERE, "_sweep_cells.json"), "w") as f:
        json.dump({"integrity": integ,
                   "spy_local_cache": round(spy_local, 2),
                   "champion_decade_never_switch_check":
                       champ_decade_check,
                   "cells": {c: {k: v for k, v in cell.items()
                                 if k not in ("equity_curve",)}
                             for c, cell in cells.items()}},
                  f, indent=1)
    with open(os.path.join(HERE, "run.log"), "w") as f:
        f.write("\n".join(log) + "\n")
    say("SWEEP DONE")


if __name__ == "__main__":
    main()
