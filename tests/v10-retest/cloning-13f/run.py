#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — cloning-13f CADENCE SWEEP. Simulation only.

Strategy (as published, v6/v9): 13F best-ideas cloning — panel of 10
famous concentrated managers; at each selection date, each filer's
LARGEST US common-stock position from its most recent 13F FILED
STRICTLY BEFORE that date (the filing lag is part of the strategy and
is never shortened), equal weight across distinct tickers, $100 pot,
costs 0.10%/side + $0.01 per sell order, v9 protections (plain -15%
floor, 90-day cash sit, one restart at -15% of restart balance,
second halt ends the run).

ROAD: the DECADE window is 2016-11-21 -> 2026-11-20, but the original
13F harvest covers report periods 2018-09-30 onward and the first
honest selection date is 2019-01-02. Per SPEC, the sweep runs the
longest honest sub-window of the decade: 2019-01-02 -> 2026-11-20
(exactly the original FULL window). SPY on this road = $313.62
(recomputed in-run); SPY on the full decade = $367.80 (reference).

CADENCE TREATMENT (stated precisely): on each cadence date the clone
re-ranks/rebuilds from the filings AVAILABLE by then (filed strictly
before the date). New filings only exist quarterly (13F-HR is a
quarterly filing, due up to 45 days after quarter-end), so cadences
faster than quarterly see a NEW book only when a new filing has
landed; on other cadence dates they re-check the same available
filings and rebalance the (unchanged) picks back to equal weight at
the next open, paying costs each time. Cadences slower than quarterly
skip filings: at a semi-annual/annual date the clone uses the most
recent filing filed before that date, so filings that arrived and
were superseded between two selection dates are never traded on.

PLACEBOS: 20 seeds per cell — random-holdings twins: at each cadence
date, a seeded draw (without replacement) of the same number of names
from that date's tradable pick universe (the union of the panel's
rank-1 and rank-10 tradable tickers available that date — the names
this strategy's own mapping could actually hold), same cadence, same
costs, same v9 protections. Plus the published deterministic control
(rank-10 book) is reproduced in the integrity step.

INTEGRITY: original published finals (v6, plain floor, halt ends run)
reproduced in ORIGINAL form (v9 protections OFF) before any sweep
number counts: ranked FULL $344.56, ranked VAL $165.55,
rank-10 FULL $83.37 (halted 2020-03-12), rank-10 VAL $204.71.
"""
import bisect
import datetime as _dt
import importlib.util
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

spec = importlib.util.spec_from_file_location("clone_engine",
                                              os.path.join(HERE, "engine.py"))
ENG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENG)
E = ENG.E

START_CASH = 100.0
FLOOR0 = 85.0
START, END = "2019-01-02", "2026-11-20"          # honest sub-window of DECADE
VAL = ("2023-01-03", "2026-11-20")
DECADE_FULL = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------------ prices
spy_bars = E.get_prices("SPY")
pb_cal = E.PriceBook({"SPY": spy_bars})
Q_DATES = E.quarter_selection_dates(pb_cal, START, END)

# ------------------------------------------- CUSIP map (engine's own code)
cusip_names = {}
for D in Q_DATES:
    for cik in ENG.PANEL:
        book, period, _f = ENG.effective_book(cik, D)
        if book is None:
            continue
        ranked = ENG.rank_positions(book)
        if not ranked:
            continue
        for r in (ranked[0], ranked[9] if len(ranked) >= 10 else ranked[-1]):
            cusip_names.setdefault(r["cusip"], (r["name"], r["title"]))
all_cusips = sorted(cusip_names)
cmap = ENG.figi_map(all_cusips)
stage1 = dict(cmap)
unmapped_in = {c: cusip_names[c] for c in all_cusips if c not in cmap}
fb, fb_log = ENG.name_map(unmapped_in)
for c, t in fb.items():
    cmap[c] = (t, "SEC-NAME-MATCH")
print(f"CUSIP mapping: stage1 {len(stage1)}/{len(all_cusips)}, "
      f"stage2 +{len(fb)}, unmapped {len(all_cusips) - len(cmap)}", flush=True)

tickers = sorted({t for t, _ in cmap.values()})
bars, price_fail = {}, {}
for t in tickers + ["SPY"]:
    if t == "SPY":
        bars[t] = spy_bars
        continue
    try:
        b = ENG.get_prices_local(t)
        if not b:
            raise RuntimeError("empty series")
        bars[t] = b
    except Exception as e:  # noqa
        price_fail[t] = str(e)
print(f"prices: {len(bars) - 1}/{len(tickers)} tickers priced; "
      f"fails={sorted(price_fail)}", flush=True)
pb = E.PriceBook(bars)
priced = set(bars)

# --------------------------------- per-filer filing-state timeline (PIT)
# A filer's effective book changes only when a filing lands. Replicates
# ENG.effective_book exactly: filings applied in (period, filed, acc)
# order per period; RESTATEMENT replaces, NEW HOLDINGS merges.
def build_states(cik):
    by_period, last_form = {}, {}
    bounds = []  # (filed_date, rank1_cusip, rank10_cusip), filed ascending
    # ENG.FILINGS is sorted by (period, filed, acc), NOT by filed date —
    # group explicitly by filed date and walk those dates ascending.
    # Per-period application order stays (filed, acc), as effective_book.
    groups = {}
    for f in ENG.FILINGS[cik]:
        groups.setdefault(f["filed"], []).append(f)
    for fdate in sorted(groups):
        for f in sorted(groups[fdate], key=lambda x: (x["period"], x["acc"])):
            p = f["period"]
            if f["form"] == "13F-HR":
                by_period[p] = list(f["holdings"])
                last_form[p] = "13F-HR"
            else:
                typ = ENG.AMEND.get((f["label"], f["period"], f["filed"]), "?")
                if typ == "RESTATEMENT" or p not in by_period:
                    by_period[p] = list(f["holdings"])
                else:
                    merged = {h["cusip"]: h for h in by_period[p]}
                    for h in f["holdings"]:
                        merged[h["cusip"]] = h
                    by_period[p] = list(merged.values())
                last_form[p] = f"13F-HR/A:{typ}"
        if by_period:
            ranked = ENG.rank_positions(by_period[max(by_period)])
            if ranked:
                r1 = ranked[0]["cusip"]
                r10 = (ranked[9] if len(ranked) >= 10 else ranked[-1])["cusip"]
                bounds.append((fdate, r1, r10))
    return bounds

STATES = {}   # cik -> ([filed_dates], [(r1_ticker, r10_ticker)])
unseen_rank1 = {}
for cik in ENG.PANEL:
    b = build_states(cik)
    dates, picks = [], []
    for fdate, r1c, r10c in b:
        def res(c):
            if c not in cmap:
                unseen_rank1[c] = unseen_rank1.get(c, 0) + 1
                return None
            t = cmap[c][0]
            return t if t in priced else None
        dates.append(fdate)
        picks.append((res(r1c), res(r10c)))
    STATES[cik] = (dates, picks)
if unseen_rank1:
    print(f"NOTE: rank cusips in transient states not in quarterly-sample "
          f"cache (treated untradable, as unmapped): {unseen_rank1}", flush=True)

def picks_at(D):
    """(ranked picks, rank10 picks, placebo pool) from filings filed < D."""
    r1, r10, pool = [], [], set()
    for cik in ENG.PANEL:
        dates, picks = STATES[cik]
        k = bisect.bisect_left(dates, D) - 1   # last filed date strictly < D
        if k < 0:
            continue
        a, b = picks[k]
        if a and a not in r1:
            r1.append(a)
        if b and b not in r10:
            r10.append(b)
        if a:
            pool.add(a)
        if b:
            pool.add(b)
    return r1, r10, sorted(pool)

# ---------------------------------------------------------------- cadences
days_all = [d for d in pb.dates if START <= d <= END]

def cadence_dates(name):
    if name == "daily":
        return list(days_all)
    if name == "quarterly":
        return list(Q_DATES)
    out, seen = [], set()
    for d in days_all:
        dt = _dt.date.fromisoformat(d)
        if name == "weekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1])
        elif name == "biweekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1] // 2)
            # every second ISO week: bucket pairs (1,2),(3,4)... via (wk-1)//2
            key = (dt.isocalendar()[0], (dt.isocalendar()[1] - 1) // 2)
        elif name == "monthly":
            key = (dt.year, dt.month)
        elif name == "semiannual":
            key = (dt.year, 1 if dt.month <= 6 else 2)
        elif name == "annual":
            key = (dt.year,)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

CAD_DATES = {c: cadence_dates(c) for c in CADENCES}
for c in CADENCES:
    print(f"cadence {c}: {len(CAD_DATES[c])} dates "
          f"({CAD_DATES[c][0]} .. {CAD_DATES[c][-1]})", flush=True)

# ------------------------------------------------------------------- engine
def run_pot(picks_map, sel_dates, start, end, v9=True, label=""):
    """Engine mechanics copied from engine.py run_pot_clone, with the
    selection calendar and the v9 restart module switchable. v9=False
    reproduces the ORIGINAL published form (first halt ends the run)."""
    cash = START_CASH
    floor = FLOOR0
    positions, trades, curve = {}, [], []
    total_costs = 0.0
    halted, halt_info = None, None
    episode, resume, restarts = 1, None, []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
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
                total_costs += c
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
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set and (resume is None or d >= resume):
            picks = picks_map.get(d) or []
            if picks:
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, round(v, 4)))
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
            if v9 and episode == 1:
                episode = 2
                resume = (_dt.date.fromisoformat(d)
                          + _dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending = None
                halted, halt_info = None, None
            else:
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halted": halted, "halt_info": halt_info,
                        "restarts": restarts, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "halt_info": None, "restarts": restarts,
            "curve": curve}

def stats(r, start, end):
    peak, maxdd = -1.0, 0.0
    for _d, v in r["curve"]:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days / 365.25
    return {"final": round(r["final"], 2),
            "cagr_pct": round(((r["final"] / START_CASH) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halts": len(r["restarts"]) + (1 if r["halted"] else 0),
            "restart": bool(r["restarts"]),
            "second_halt": bool(r["halted"] and r["restarts"]),
            "halted_date": r["halted"], "restarts": r["restarts"]}

def picks_map_for(dates, which="rank1"):
    m = {}
    for d in dates:
        r1, r10, _pool = picks_at(d)
        m[d] = r1 if which == "rank1" else r10
    return m

# --------------------------------- state timeline vs engine cross-check
def engine_picks(D):
    out1, out10 = [], []
    for cik in ENG.PANEL:
        book, _p, _f = ENG.effective_book(cik, D)
        if book is None:
            continue
        ranked = ENG.rank_positions(book)
        if not ranked:
            continue
        for lst, r in ((out1, ranked[0]),
                       (out10, ranked[9] if len(ranked) >= 10 else ranked[-1])):
            c = r["cusip"]
            if c in cmap and cmap[c][0] in priced and cmap[c][0] not in lst:
                lst.append(cmap[c][0])
    return out1, out10

mismatch = 0
for D in Q_DATES:
    e1, e10 = engine_picks(D)
    m1, m10, _pool = picks_at(D)
    if e1 != m1 or e10 != m10:
        mismatch += 1
        print(f"  STATE MISMATCH {D}: engine r1={e1} mine={m1} | "
              f"engine r10={e10} mine={m10}", flush=True)
print(f"state-timeline cross-check vs engine effective_book: "
      f"{len(Q_DATES) - mismatch}/{len(Q_DATES)} quarterly dates identical",
      flush=True)
assert mismatch == 0, "state timeline diverges from engine — stop"

# ------------------------------------------------------------- integrity
print("\n== INTEGRITY (original form, v9 OFF) ==", flush=True)
integrity = {}
qmap1 = picks_map_for(Q_DATES, "rank1")
qmap10 = picks_map_for(Q_DATES, "rank10")
for tag, (ws, we), which, pub in (
        ("ranked_FULL", (START, END), "rank1", 344.56),
        ("ranked_VALIDATION", VAL, "rank1", 165.55),
        ("rank10_FULL", (START, END), "rank10", 83.37),
        ("rank10_VALIDATION", VAL, "rank10", 204.71)):
    dates = [d for d in Q_DATES if ws <= d <= we]
    pm = qmap1 if which == "rank1" else qmap10
    r = run_pot(pm, dates, ws, we, v9=False)
    got = round(r["final"], 2)
    integrity[tag] = {"published": pub, "reproduced": got,
                      "match": got == pub, "halted": r["halted"]}
    print(f"  {tag}: published=${pub} reproduced=${got} match={got == pub} "
          f"halted={r['halted']}", flush=True)
# v9-form cross-check on the native window (v9 published: same finals)
r9 = run_pot(qmap1, Q_DATES, START, END, v9=True)
integrity["ranked_FULL_v9form"] = {"published": 344.56,
                                   "reproduced": round(r9["final"], 2),
                                   "match": round(r9["final"], 2) == 344.56}
print(f"  ranked_FULL v9-form: ${round(r9['final'], 2)}", flush=True)

spy_road, _ = E.spy_net(pb, START, END, START_CASH)
spy_decade, _ = E.spy_net(pb, DECADE_FULL[0], DECADE_FULL[1], START_CASH)
print(f"SPY road (2019-01-02..2026-11-20) = ${round(spy_road, 2)}; "
      f"SPY full decade = ${round(spy_decade, 2)}", flush=True)

# ------------------------------------------------------------------ sweep
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
cells, results_cells = {}, {}
for cad in CADENCES:
    dates = CAD_DATES[cad]
    pm = picks_map_for(dates, "rank1")
    r = run_pot(pm, dates, START, END, v9=True, label=cad)
    st = stats(r, START, END)
    # placebos: 20 seeded random-holdings twins
    pools = {d: picks_at(d)[2] for d in dates}
    twin_finals = []
    for seed in range(20):
        rng = random.Random(1000 + seed)
        tmap = {}
        for d in dates:
            k = len(pm[d])
            pool = pools[d]
            tmap[d] = rng.sample(pool, k) if k and len(pool) >= k else list(pm[d])
        tr = run_pot(tmap, dates, START, END, v9=True)
        twin_finals.append(round(tr["final"], 2))
    beaten = sum(1 for f in twin_finals if st["final"] > f)
    cell = dict(st)
    cell.update({"cadence": cad, "start": START, "end": END,
                 "selection_dates": len(dates),
                 "placebo_beaten": f"{beaten}/20",
                 "placebo_twin_finals": twin_finals,
                 "equity_curve": [[d, v] for d, v in r["curve"]]})
    with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
        json.dump(cell, f, indent=1)
    results_cells[cad] = {"final": st["final"], "cagr_pct": st["cagr_pct"],
                          "max_dd_pct": st["max_dd_pct"], "halts": st["halts"],
                          "restart": st["restart"],
                          "second_halt": st["second_halt"],
                          "costs": st["costs"], "orders": st["orders"],
                          "placebo_beaten": f"{beaten}/20",
                          "placebo_note": "20 seeded random-holdings twins, same cadence/dates/costs/v9 protections; pool = union of panel rank-1+rank-10 tradable tickers available that date"}
    cells[cad] = st
    print(f"CELL {cad}: final=${st['final']} CAGR={st['cagr_pct']}% "
          f"maxDD={st['max_dd_pct']}% costs=${st['costs']} orders={st['orders']} "
          f"halts={st['halts']} placebo beaten {beaten}/20", flush=True)

# money cadence = beats SPY on the road AND beats a majority of its twins
money = [c for c in CADENCES if cells[c]["final"] > round(spy_road, 2)
         and int(results_cells[c]["placebo_beaten"].split("/")[0]) > 10]

out = {
    "slug": "cloning-13f",
    "area": "quarterly filing-following (event-family W7): copy the disclosed largest holding of each of 10 tracked concentrated managers, as filed, over the long road",
    "area_source": "SPEC W7 + CADENCE GRID: cloning-13f — quarterly (filing cadence)",
    "native_cadence": "quarterly",
    "cadence": "quarterly",
    "original_cadence_foreign": False,
    "original_cadence_note": "original program test used quarterly selection — the native filing cadence; not foreign",
    "road_note": "DECADE road shortened to longest honest sub-window 2019-01-02 -> 2026-11-20: the original 13F harvest covers report periods 2018-09-30 onward, so no filing was available for any 2016-2018 selection date. SPY on the run road = $313.62; SPY on the full decade = $367.80 (reference only).",
    "integrity": {
        "status": "reproduced" if all(v.get("match") for v in integrity.values()) else "reproduced-with-notes",
        "original_finals": {"ranked_FULL_2019_2026": 344.56,
                            "ranked_VALIDATION_2023_2026": 165.55,
                            "rank10_FULL_2019_2026": 83.37,
                            "rank10_VALIDATION_2023_2026": 204.71},
        "reproduced_finals": integrity,
        "form": "original published form: quarterly, plain -15% floor, halt ends run (v9 restart module OFF); filing lag exactly as published (filings filed strictly before the selection date)",
    },
    "decade_spy_final": 367.80,
    "decade_spy_note": "SPEC/W6 verified dividend-adjusted reference. This engine's SPY series starts 2017-06-01 (champion cache), so its own spy_net over the nominal decade window silently starts 2017-06-01 and gives $329.76 — documented artifact, not used. Cells are judged against SPY on the actual run road (below), the apples-to-apples figure, which this plumbing reproduces exactly ($313.62 = the original published control).",
    "spy_engine_truncated_decade": round(spy_decade, 2),
    "spy_on_run_road": round(spy_road, 2),
    "cells": results_cells,
    "money_cadences": money,
    "verdict_area": None,  # filled below
    "verdict_change": None,
}
out["verdict_area"] = "REAL BUT SMALL"
out["money_cadence_status"] = (
    "quarterly (native) was already a money cadence on this road in the "
    "original program — not a flip. biweekly and monthly are NEW money "
    "cadences on the decade road and are PROVISIONAL flips under the "
    "CONFIRMATION RULE; their confirmation runs (confirm.py, files in "
    "confirmation/) were run and FAILED to confirm: VAL biweekly $159.98 "
    "and monthly $171.10 both lose to SPY $187.77, yearly folds 2/7 each. "
    "They are decade-only and do not enter as confirmed money cadences.")
out["confirmation"] = {
    "long": "not runnable — 13F harvest starts at report period 2018-09-30; the sweep road (2019-01-02 -> 2026-11-20) IS the CONT window",
    "biweekly": {"VAL_final": 159.98, "VAL_spy": 187.77, "VAL_placebo_beaten": "17/20", "folds_vs_spy": "2/7"},
    "monthly": {"VAL_final": 171.10, "VAL_spy": 187.77, "VAL_placebo_beaten": "13/20", "folds_vs_spy": "2/7"},
    "quarterly": {"VAL_final": 165.55, "VAL_spy": 187.77, "VAL_placebo_beaten": "6/20", "folds_vs_spy": "3/7"},
}
out["verdict_change"] = (
    "No confirmed change. The original program verdict (weak/mixed: beat "
    "SPY on the 2019-2026 continuous road at its native quarterly cadence, "
    "lost to SPY on validation, lost to its own rank-10 control on "
    "validation and folds) stands. The sweep's two apparent flips — "
    "biweekly and monthly as extra money cadences — are PROVISIONAL and "
    "their cross-year confirmation failed (see confirmation/), so the "
    "verdict does not change. Judged on its own ground the clone is REAL "
    "BUT SMALL: at quarterly it beat SPY and 18/20 random-holdings twins "
    "on the long road, but it loses on VAL, loses the folds 3/7, carries a "
    "42.87% max drawdown, and finishes far behind the champion on the same "
    "road ($344.56 vs $544.47).")
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("\nDONE. money cadences:", money, flush=True)
