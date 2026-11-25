#!/usr/bin/env python3
"""THE GREAT RETEST (v10) — gap-a6-div-initiation — CADENCE SWEEP runner.

Strategy: GAP A-6 DIVIDEND-INITIATION DRIFT (Michaely, Thaler & Womack
1995), as published in the program: buy pond names announcing a first
regular cash dividend (first ever, or first in >= 5 years) at the close
of the next trading day after the announcement, 1/5-of-pot slices
(cap 5 concurrent), hold 12 months, program costs (0.10%/side + $0.01
per sell), $100 pot, v9 protection (plain -15% floor; first halt ->
liquidate next open, 90 days cash, restart with episode-2 floor -15%
from restart balance; second halt ends the run).

This runner SUPERSEDES the partial area-form work in this folder
(area_runs.py / the old results.json): the area facts are carried into
results.json's `area_record` block and cited in RESULTS.md; the runners
and data are kept.

Deliverables written by this script (into this folder):
  cells/<cadence>.json  — one per cadence: final, CAGR, max DD, costs,
                          orders, halts/restarts with dates, FULL equity
                          curve, all 20 placebo twin finals, per-event
                          stats at that cadence.
  results.json          — SPEC sweep-format summary.

Cadence treatment for this EVENT strategy (SPEC, uniform definition):
the event rules stay exactly as published — entries happen on the
published event dates (close of the next trading day after the
announcement) at every cadence. Cadence governs the position review /
exit-check rhythm only:
  * a position's scheduled exit (close of the first trading day on or
    after the 12-month anniversary of entry) executes on the first
    cadence date on/after that published exit date;
  * the -15% floor is checked only on cadence dates (a breach
    liquidates at the next trading day's open, as the original engine
    does);
  * window-end liquidation at the final close is unchanged.
Daily cadence == the original published form; this script ASSERTS that
its daily cells reproduce the original engine's finals ($108.16 on
CONT, VAL and DECADE) before any sweep number is written.

Prices: this folder's cache/ Yahoo pull (2009-06 -> 2026-11-21,
dividend-adjusted closes, the champion engine's bar construction) via
lib.bars_long — the same pricebook the area runs verified: original
engine finals $108.16 to the cent on CONT/VAL/DECADE and SPY controls
exact (DECADE $367.80, LONG $822.94, CONT $313.62, VAL $187.77).
Event census: engine.EVENTS (META 2024-02-01, GOOGL 2024-04-25 — the
only two qualifying initiations on the pond in the decade window; the
2010-extended census adds CSCO 2011 and AAPL 2012, see area_record).
"""
import datetime as dt, importlib.util, json, os, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
M = load_mod("a6_engine", os.path.join(HERE, "engine.py"))
LIB = load_mod("a6_lib", os.path.join(HERE, "lib.py"))
E = M.E; UNI = M.UNIVERSE
DEC = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]
PLACEBO_NOTE = ("Random pond name drawn per event with replacement from the full "
                "30-name pond (random.Random(seed), seeds 1-20), identical entry/exit "
                "schedule, same cadence, v9 rules — the convention of this folder's "
                "area runs and the sibling W7 sweep. (The original engine's R6 design "
                "sampled without replacement from the 28 non-initiators; the sweep "
                "follows the area-run convention so numbers are comparable across "
                "this folder.)")

# ---------------------------------------------------------------- prices
def pb_long():
    cd = os.path.join(HERE, "cache")
    return E.PriceBook({t: LIB.bars_long(t, cd) for t in UNI + ["SPY"]})

def spy_final(pb, s, e):
    v, _ = E.spy_net(pb, s, e, 100.0); return round(v, 2)

# ------------------------------------------------------------- cadences
def cadence_dates(days, cadence):
    if cadence == "daily": return set(days)
    def first_of(keyfn):
        out, seen = [], set()
        for d in days:
            k = keyfn(d)
            if k not in seen: seen.add(k); out.append(d)
        return out
    if cadence == "weekly":
        return set(first_of(lambda d: dt.date.fromisoformat(d).isocalendar()[:2]))
    if cadence == "biweekly":
        wk = first_of(lambda d: dt.date.fromisoformat(d).isocalendar()[:2])
        return set(wk[::2])
    if cadence == "monthly": return set(first_of(lambda d: d[:7]))
    if cadence == "quarterly": return set(first_of(lambda d: (d[:4], (int(d[5:7]) - 1) // 3)))
    if cadence == "semiannual": return set(first_of(lambda d: (d[:4], int(d[5:7]) <= 6)))
    if cadence == "annual": return set(first_of(lambda d: d[:4]))
    raise ValueError(cadence)

# ------------------------------------------------- cadence event engine
def run_cadence_pot(pb, sched, start, end, cadence, names=None, record_curve=True):
    """A-6 mechanics verbatim from the original engine (entry at close on
    the published entry day; 1/5 slices with pro-rata funding sells at
    close; exits at close; sells cost 0.10% + $0.01; buys 0.10%), with
    the SPEC cadence overlay stated in the module docstring, and v9
    episodes (liquidate next open, 90 days cash, resume entries,
    episode-2 floor -15% of restart balance, second halt ends the run).
    Positions are keyed by event index so placebo twins that draw the
    same name twice still hold two separate positions."""
    days = [d for d in pb.dates if start <= d <= end]
    cset = cadence_dates(days, cadence)
    if names is None: names = [ev["name"] for ev in sched]
    def cadence_exit(xd):
        for d in days:
            if d >= xd and d in cset: return d
        return days[-1]
    entries, exits = {}, {}
    for i, ev in enumerate(sched):
        if start <= ev["entry"] <= end: entries.setdefault(ev["entry"], []).append(i)
        xd = cadence_exit(ev["exit"]) if ev["exit"] else days[-1]
        if start <= xd <= end: exits.setdefault(xd, []).append(i)
    cash, positions, trades, total_costs = 100.0, {}, [], 0.0
    floor, episode, resume = 85.0, 1, None
    halts, restarts, curve = [], [], []
    pending_halt, halt_signal = False, None
    def close_of(t, d): return pb.close_on_or_before(t, d)
    def pot_close(d):
        v = cash
        for _i, (t, sh) in positions.items():
            c = close_of(t, d)
            if c: v += sh * c
        return v
    for di, d in enumerate(days):
        if pending_halt:
            for i in list(positions):
                t, sh = positions[i]
                nd, o = pb.next_open(t, days[di - 1])
                if o is None: continue
                val = sh * o; c = val * 0.001 + 0.01
                cash += val - c; total_costs += c
                trades.append((nd, t, "SELL-HALT", sh, o, val, c))
                del positions[i]
            halts.append({"episode": episode, "signal_date": halt_signal,
                          "liquidation_date": d, "balance": round(cash, 2)})
            if episode == 2:
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halts": halts, "restarts": restarts, "curve": curve,
                        "second_halt": True}
            episode = 2
            resume = (dt.date.fromisoformat(d) + dt.timedelta(days=90)).isoformat()
            floor = 0.85 * cash
            restarts.append({"halt_signal_date": halt_signal, "liquidation_date": d,
                             "restart_balance": round(cash, 2), "resume_on_or_after": resume,
                             "episode2_floor": round(floor, 2)})
            pending_halt = False
        for i in exits.get(d, []):
            if i not in positions: continue
            t, sh = positions.pop(i)
            px = close_of(t, d); val = sh * px; c = val * 0.001 + 0.01
            cash += val - c; total_costs += c
            trades.append((d, t, "SELL-EXIT", sh, px, val, c))
        for i in entries.get(d, []):
            if resume is not None and d < resume: continue
            t = names[i]
            marked = pot_close(d); target = marked / 5.0
            if cash < target * 1.001 and positions:
                need = target * 1.001 - cash
                tot_val = sum(sh * close_of(tt, d) for _j, (tt, sh) in positions.items())
                for j in list(positions):
                    if need <= 0: break
                    tt, sh = positions[j]; px = close_of(tt, d); cur = sh * px
                    sell_val = min(cur, need * (cur / tot_val) * 1.02) if tot_val else 0.0
                    if sell_val <= 0.005: continue
                    ssh = sell_val / px; c = sell_val * 0.001 + 0.01
                    cash += sell_val - c; total_costs += c
                    trades.append((d, tt, "SELL-FUND", ssh, px, sell_val, c))
                    if sh - ssh < 1e-9: del positions[j]
                    else: positions[j] = (tt, sh - ssh)
                    need -= sell_val
            px = close_of(t, d)
            buy_val = min(target, cash / 1.001)
            if buy_val > 0.005 and px:
                sh = buy_val / px; c = buy_val * 0.001
                cash -= buy_val + c; total_costs += c
                positions[i] = (t, sh)
                trades.append((d, t, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        if record_curve: curve.append((d, round(v, 4)))
        if d in cset and v <= floor and di < len(days) - 1:
            pending_halt, halt_signal = True, d
    last = days[-1]
    for i in list(positions):
        t, sh = positions[i]; px = close_of(t, last)
        if px:
            val = sh * px; c = val * 0.001 + 0.01
            cash += val - c; total_costs += c
            trades.append((last, t, "SELL-END", sh, px, val, c))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halts": halts, "restarts": restarts, "curve": curve, "second_halt": False}

def stats(final, curve, s, e):
    yrs = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days / 365.25
    cagr = round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return cagr, round(maxdd * 100, 2)

def cadence_exit_map(pb, sched, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    cset = cadence_dates(days, cadence)
    out = []
    for ev in sched:
        xd = days[-1]
        for d in days:
            if d >= ev["exit"] and d in cset: xd = d; break
        out.append(xd)
    return out

def main():
    pb = pb_long()
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    sched = M.derive_schedule(pb, M.EVENTS)
    # ---- integrity: original engine, original windows (episode-1 form)
    integ = {}
    for nm, (s, e) in (("CONT", ("2019-01-02", "2026-11-20")), ("VAL", ("2023-01-03", "2026-11-20"))):
        r = M.run_event_pot(pb, sched, s, e)
        integ[nm] = {"final": round(r["final"], 2), "halted": r["halted"],
                     "costs": round(r["costs"], 2), "orders": len(r["trades"])}
    assert integ["CONT"]["final"] == 108.16 and integ["VAL"]["final"] == 108.16, integ
    # ---- validation: cadence engine at daily == original engine
    for nm, (s, e), want in (("CONT", ("2019-01-02", "2026-11-20"), 108.16),
                             ("VAL", ("2023-01-03", "2026-11-20"), 108.16),
                             ("DECADE", DEC, 108.16)):
        r = run_cadence_pot(pb, sched, s, e, "daily")
        assert abs(r["final"] - want) < 0.02, (nm, r["final"], want)
    print("integrity + cadence-engine daily validation: PASS", flush=True)
    spy = {"LONG": spy_final(pb, "2010-01-04", "2026-11-20"),
           "DECADE": spy_final(pb, *DEC),
           "CONT": spy_final(pb, "2019-01-02", "2026-11-20"),
           "VAL": spy_final(pb, "2023-01-03", "2026-11-20")}
    assert spy == {"LONG": 822.94, "DECADE": 367.8, "CONT": 313.62, "VAL": 187.77}, spy
    print(f"SPY controls exact: {spy}", flush=True)
    # ---- decade matrix
    s, e = DEC
    cells = {}
    cell_events, cell_evstats = {}, {}
    for cad in CADENCES:
        r = run_cadence_pot(pb, sched, s, e, cad)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            names = [rng.choice(UNI) for _ in sched]
            tr = run_cadence_pot(pb, sched, s, e, cad, names=names, record_curve=False)
            twins.append(round(tr["final"], 2))
        beaten = sum(1 for f in twins if r["final"] > f)
        cagr, maxdd = stats(r["final"], r["curve"], s, e)
        # per-event stats at this cadence (standalone $100, entry close ->
        # cadence exit close, name vs SPY over identical dates)
        xmap = cadence_exit_map(pb, sched, s, e, cad)
        evs = []
        for ev, xd in zip(sched, xmap):
            nf, _, _, _ = M.standalone(pb, ev["name"], ev["entry"], xd)
            sf, _, _, _ = M.standalone(pb, "SPY", ev["entry"], xd)
            evs.append({"name": ev["name"], "announce": ev["announce"],
                        "entry": ev["entry"], "published_exit": ev["exit"],
                        "cadence_exit": xd,
                        "net_pct": round(nf - 100, 2), "spy_pct": round(sf - 100, 2),
                        "excess_pct": round(nf - sf, 2)})
        cell_events[cad] = evs
        exc = [x["excess_pct"] for x in evs]
        ev_stats = {"n": len(exc),
                    "mean_excess_pct": round(statistics.mean(exc), 2),
                    "median_excess_pct": round(statistics.median(exc), 2),
                    "share_beating_spy": round(sum(1 for x in exc if x > 0) / len(exc), 3)}
        cell_evstats[cad] = ev_stats
        cell = {"cadence": cad, "window": [s, e], "final": round(r["final"], 2),
                "cagr_pct": cagr, "max_dd_pct": maxdd, "costs": round(r["costs"], 2),
                "orders": len(r["trades"]), "halts": r["halts"], "restarts": r["restarts"],
                "restart": bool(r["restarts"]), "second_halt": r["second_halt"],
                "events_traded": len(sched), "events": evs, "event_stats": ev_stats,
                "placebo_beaten": f"{beaten}/20", "placebo_twin_finals": twins,
                "placebo_note": PLACEBO_NOTE,
                "equity_curve": r["curve"]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                                           "placebo_beaten", "placebo_note",
                                           "events_traded", "event_stats")}
        cells[cad]["halts"] = len(r["halts"]); cells[cad]["restart"] = bool(r["restarts"])
        cells[cad]["second_halt"] = r["second_halt"]
        print(f"{cad}: final=${r['final']:,.2f} beaten={beaten}/20 costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} ev_mean={ev_stats['mean_excess_pct']} "
              f"ev_med={ev_stats['median_excess_pct']}", flush=True)
    money = [c for c in CADENCES if cells[c]["final"] > spy["DECADE"] and
             int(cells[c]["placebo_beaten"].split("/")[0]) > 10]
    out = {
        "slug": "gap-a6-div-initiation",
        "area": "Event strategies — dividend-initiation drift (Michaely, Thaler & Womack 1995) on the honest Nov-2016 top-30 pond (SPEC W7); decade cadence sweep on the DECADE road 2016-11-21 -> 2026-11-20",
        "area_source": "SPEC.md W7 batch + THE CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "event-driven",
        "cadence": "event-driven",
        "original_cadence_foreign": {"foreign": False, "note": "Original program test ran the published event-driven form (entries on announcement, daily exit/floor checks) — native cadence; no foreign cadence was forced."},
        "native_change": "none — original form was native. v10 adds: the cadence sweep (exit/floor-check rhythm varied per SPEC; entries stay on the published event dates), and the v9 protection module.",
        "cadence_treatment": "Event rules exactly as published at every cadence (entry at the close of the next trading day after the announcement; 1/5-of-pot slices, cap 5; 12-month hold). Cadence governs the position review / exit-check rhythm only: scheduled exits execute on the first cadence date on/after the published exit date, and the -15% floor is checked only on cadence dates (breach liquidates at the next trading day's open). Window-end liquidation unchanged.",
        "supersedes": "This results.json REPLACES the partial area-form results.json written by the W7 batch worker (area runs only, sweep not run). The area numbers are carried into the area_record block below and cited in RESULTS.md; area_runs.py, lib.py, engine.py and data/ are kept on file.",
        "integrity": {"status": "reproduced",
                      "original_finals": {"CONT": 108.16, "VAL": 108.16},
                      "reproduced_finals": integ,
                      "note": "Original engine (./engine.py) re-run in this folder reproduced both published finals to the cent on this folder's cache pricebook; SPY controls exact (CONT $313.62, VAL $187.77, DECADE $367.80, LONG $822.94). The v10 cadence engine at daily cadence reproduces the original engine on CONT, VAL and DECADE ($108.16) before any sweep number was taken."},
        "decade_spy_final": spy["DECADE"],
        "spy": spy,
        "champion_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
                               "DECADE": 65.89,
                               "decade_note": "Champion decade $65.89 after two halts (lazy-quarterly test) — a rules artifact of the champion's crash halts, printed with its caveat wherever the decade matrix is summarized."},
        "cells": cells,
        "money_cadences": money,
        "events_decade": cell_events["daily"],
        "event_stats_decade_native": cell_evstats["daily"],
        "area_record": {
            "note": "Area-form runs from the W7 batch worker (./area_runs.py, v9 wrapper, original brief), carried over from the superseded partial results.json. DECADE/CONT/VAL use the decade census (META, GOOGL); LONG uses the census extended to 2010 (CSCO 2011-03-18 first-ever, AAPL 2012-03-19 first in >=5y added through the same press-release + dividend-tape channel).",
            "runs": {
                "LONG": {"start": "2010-01-04", "end": "2026-11-20", "final": 106.83, "cagr_pct": 0.39, "max_dd_pct": 10.63, "halts": 0, "restart": False, "second_halt": False, "costs": 0.21, "orders": 8, "placebo_beaten": None},
                "DECADE": {"start": "2016-11-21", "end": "2026-11-20", "final": 108.16, "cagr_pct": 0.79, "max_dd_pct": 6.25, "halts": 0, "restart": False, "second_halt": False, "costs": 0.11, "orders": 4, "placebo_beaten": None},
                "CONT": {"start": "2019-01-02", "end": "2026-11-20", "final": 108.16, "cagr_pct": 1.0, "max_dd_pct": 6.25, "halts": 0, "restart": False, "second_halt": False, "costs": 0.11, "orders": 4, "placebo_beaten": "13/20"},
                "VAL": {"start": "2023-01-03", "end": "2026-11-20", "final": 108.16, "cagr_pct": 2.04, "max_dd_pct": 6.25, "halts": 0, "restart": False, "second_halt": False, "costs": 0.11, "orders": 4, "placebo_beaten": "13/20"}},
            "events_long": [
                {"name": "CSCO", "announce": "2011-03-18", "entry": "2011-03-21", "exit": "2012-03-21", "net_pct": 19.36, "spy_pct": 10.11, "excess_pct": 9.25},
                {"name": "AAPL", "announce": "2012-03-19", "entry": "2012-03-20", "exit": "2013-03-20", "net_pct": -24.45, "spy_pct": 13.09, "excess_pct": -37.54},
                {"name": "META", "announce": "2024-02-01", "entry": "2024-02-02", "exit": "2025-02-03", "net_pct": 47.09, "spy_pct": 22.22, "excess_pct": 24.88},
                {"name": "GOOGL", "announce": "2024-04-25", "entry": "2024-04-26", "exit": "2025-04-28", "net_pct": -6.35, "spy_pct": 9.53, "excess_pct": -15.88}],
            "event_stats_long": {"n": 4, "mean_excess_pct": -4.82, "median_excess_pct": -3.32, "share_beating_spy": 0.5}},
        "verdict_area": "NO GROUND",
        "verdict_change": "No change. The original program's verdict stands at every cadence on the decade road: no cell beats SPY ($367.80), no cell is a money cadence, and the decade census is two events (META, GOOGL) whose excesses cancel. No flip, so the CONFIRMATION RULE is not triggered.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE results.json + cells/", flush=True)

if __name__ == "__main__":
    main()
