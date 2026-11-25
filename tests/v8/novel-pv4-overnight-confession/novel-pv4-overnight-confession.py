#!/usr/bin/env python3
"""
INVENTED STRATEGY N-PV4 — "THE OVERNIGHT CONFESSION" (gap-down, full
intraday reclaim) — Terry's AI stock app, v8 NOVEL track (invented in
2026; this is 1 of the 12 invented rules). Simulation only. NO
parameter tuning: the frozen spec from
research/v8-novel/novel-price-volume.md (RULE N-PV4) is run ONCE,
exactly as written.

THE RULE AS FROZEN (novel-price-volume.md, N-PV4 (b)):
  - Event: a pond name triggers on day t if (i) the overnight gap
    g = Open_t / Close_{t-1} - 1 is <= -2.0%, AND (ii) Close_t >=
    Close_{t-1} (the gap is fully reclaimed by the close).
  - Entry: buy at the NEXT session's open (t+1) with 1/5 of the pot's
    current value. Maximum 5 concurrent positions; one position per
    name; no re-trigger while held. If more than 5 names trigger on
    the same day, rank by gap size (most negative g first) and take
    the first 5; the rest are logged and skipped.
  - Exit: sell at the open of the 11th trading day after the entry
    day (10 full trading days held). No per-position stop; the
    pot-level -15% floor is the only stop.
  - Costs/floor: program standard (0.10%/side + $0.01/sell; plain
    -15% floor: a close at or below $85.00 liquidates everything at
    the next open and ends the run).

VERDICT VOCABULARY (invented-rule track): the best possible verdict
is CANDIDATE — never "promoted" (only a forward paper trial can
promote an invented rule). CANDIDATE requires ALL of:
  (1) validation final > SPY $187.77,
  (2) validation placebo 20/20 (placebo = same event dates, random
      pond names, matched mechanics),
  (3) continuous final > SPY $313.62,
  (4) no floor halt on either main window.
Anything less = NOT A CANDIDATE, reported plainly.

FORCED READINGS (stated here, before any result):
  1. PRICE BASIS: the champion engine's cached bars — split/dividend-
     adjusted open and close (raw open scaled by the adjclose/close
     ratio, the F-5 precedent). Gap and reclaim are computed on these
     adjusted prices, so a split or an ex-dividend day cannot
     fabricate or erase an event. (On an ex-dividend day the adjusted
     gap differs slightly from the raw gap; this is the program's
     standing price basis.)
  2. SLICE MARKING: "1/5 of the pot's current value" is marked at the
     SIGNAL day's close (cash + holdings at that close) — the reading
     the sibling spec N-PV2 in the same file states explicitly, and
     the last value known when the decision is made. If cash is short
     of the slice, the buy is capped at available cash (buy costs
     aside); the rule states no funding liquidation, so none is
     invented.
  3. SAME-DAY ORDER AT THE OPEN: a pending floor-halt liquidation
     executes first and ends the run; otherwise scheduled exits at
     that open execute before entries at that open (an exiting
     position frees its slot, and its name, for a same-open entry).
  4. SLOT LIMITS: names already held cannot trigger (skipped and
     logged); when fewer than 5 slots are free, same-day triggers
     are filled in gap-rank order up to the free slots and the rest
     are logged and skipped.
  5. WINDOW MEMBERSHIP: an event belongs to a window if its signal
     day t and its entry day t+1 both fall inside the window. A fresh
     pot never carries a position entered before its own start.
  6. EXIT CALENDAR: the 11th trading day after the entry day is
     counted in the held name's own bar series. A position whose exit
     day falls beyond the window end is liquidated at the window-end
     close (the program's SELL-END convention).
  7. PLACEBO: for each seed 1..20, every window event (in the same
     date order, same-day events in the same gap-rank order) is
     assigned a name drawn uniformly at random from the other 29 pond
     names (one draw per event, seeded RNG). The placebo pot runs the
     identical engine: same entry day (t+1 open), same exit rule in
     the drawn name's own calendar, same 1/5 slicing marked at the
     signal-day close, same 5-slot cap and no-retrigger rule applied
     to the drawn names within that seed's pot (a drawn name already
     held, or a full book, skips that event for that seed).

CHASSIS (program standard): $100 pot, honest top-30 pond as of
Nov 2016, windows CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
2023-01-03 -> 2026-11-20. Benchmarks: SPY buy-hold net ($313.62 /
$187.77) and the champion (value + momentum: $544.47 / $288.05),
both replication-checked in-run before any variant number is taken.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
FULL = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
GAP_MIN = -0.02          # frozen: overnight gap <= -2.0%
HOLD_AFTER = 11          # frozen: exit at open of 11th trading day
                         # after the entry day (10 full days held)
MAX_POS = 5              # frozen: max 5 concurrent positions


# ------------------------------------------------------------------ data
def build_champion_inputs():
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributable"
                         "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding",
                         prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding",
                         prio=2) +
            E.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows, bars


# ------------------------------------------------------------- event scan
def scan_events(bars):
    """All N-PV4 events in the full cached series, per name:
    gap = Open_t/Close_{t-1} - 1 <= -2.0% AND Close_t >= Close_{t-1},
    on the champion engine's adjusted open/close bars."""
    events = []
    for t in UNIVERSE:
        bl = bars[t]
        for i in range(1, len(bl)):
            prev, cur = bl[i - 1], bl[i]
            if not prev["c"] or not cur["o"]:
                continue
            g = cur["o"] / prev["c"] - 1.0
            if g <= GAP_MIN and cur["c"] >= prev["c"]:
                events.append({"ticker": t, "signal": cur["d"],
                               "gap_pct": round(g * 100, 3),
                               "prev_close": prev["c"],
                               "open": cur["o"], "close": cur["c"]})
    events.sort(key=lambda e: (e["signal"], e["gap_pct"]))
    return events


def window_events(events, pb, start, end):
    """Events whose signal day AND entry day (next session) are both
    inside the window. Entry/exit dates are trading days of the held
    name's own bar series (exit = 11th trading day after entry)."""
    out = []
    for ev in events:
        if not (start <= ev["signal"] <= end):
            continue
        nd, _o = pb.next_open(ev["ticker"], ev["signal"])
        if nd is None or nd > end:
            continue
        out.append({**ev, "entry": nd})
    return out


# ---------------------------------------------------------------- engine
def run_event_pot(pb, bars, sched, start, end, names, label=""):
    """N-PV4 event pot. `sched` = window event list (signal order,
    same-day gap-rank order); `names[i]` = ticker bought for event i
    (the event's own name ranked; a random pond name for a placebo
    seed). Positions keyed by ticker. Returns the standard result
    dict plus per-event trade records and skip log."""
    cash = START_CASH
    positions = {}          # ticker -> {"shares", "entry", "exit", "ev"}
    trades = []
    total_costs = 0.0
    halt_info = None
    curve = []
    taken, skipped = [], []
    days = [d for d in pb.dates if start <= d <= end]

    idx_of = {t: {b["d"]: i for i, b in enumerate(bars[t])}
              for t in UNIVERSE}
    bar_of = {t: {b["d"]: b for b in bars[t]} for t in UNIVERSE}

    # schedule: entries by entry day (in sched order), exits computed
    # per position at buy time.
    entries = {}
    for i, ev in enumerate(sched):
        entries.setdefault(ev["entry"], []).append(i)

    def close_of(t, d):
        return pb.close_on_or_before(t, d)

    def pot_close(d):
        v = cash
        for t, p in positions.items():
            c = close_of(t, d)
            if c:
                v += p["shares"] * c
        return v

    def sell(t, sh, px, d, kind):
        nonlocal cash, total_costs
        val = sh * px
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, t, kind, sh, px, val, c))
        return val

    pending_halt = False
    for di, d in enumerate(days):
        # (a) pending floor-halt liquidation at this open ends the run
        if pending_halt:
            sig_d = days[di - 1]
            for t in list(positions):
                b = bar_of[t].get(d)
                if b:
                    sell(t, positions[t]["shares"], b["o"], d,
                         "SELL-HALT")
                del positions[t]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": sig_d,
                    "halt_info": halt_info, "curve": curve,
                    "taken": taken, "skipped": skipped}
        # (b) scheduled exits at this open
        for t in list(positions):
            if positions[t]["exit"] == d:
                b = bar_of[t].get(d)
                if b:
                    sell(t, positions[t]["shares"], b["o"], d,
                         "SELL-EXIT")
                del positions[t]
        # (c) entries at this open (signals from the prior session)
        for i in entries.get(d, []):
            ev = sched[i]
            t = names[i]
            if t in positions:
                skipped.append({**ev, "bought": t,
                                "why": "name already held"})
                continue
            if len(positions) >= MAX_POS:
                skipped.append({**ev, "bought": t,
                                "why": "5 positions already open"})
                continue
            marked = None
            # slice marked at the SIGNAL day's close
            sig = ev["signal"]
            v = cash
            for tt, p in positions.items():
                c = close_of(tt, sig)
                if c:
                    v += p["shares"] * c
            marked = v
            target = marked / 5.0
            b = bar_of[t].get(d)
            if not b or not b["o"]:
                skipped.append({**ev, "bought": t,
                                "why": "no bar on entry day"})
                continue
            buy_val = min(target, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({**ev, "bought": t,
                                "why": "insufficient cash"})
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            ei = idx_of[t][d]
            exit_d = (bars[t][ei + HOLD_AFTER]["d"]
                      if ei + HOLD_AFTER < len(bars[t]) else None)
            positions[t] = {"shares": sh, "entry": d, "exit": exit_d,
                            "ev": i, "entry_px": b["o"]}
            trades.append((d, t, "BUY", sh, b["o"], buy_val, c))
            taken.append({**ev, "bought": t, "entry": d,
                          "exit": exit_d, "buy_val": round(buy_val, 2)})
        # end of day: floor check on the close
        v = pot_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            pending_halt = True
    # window end: liquidate at final close (program SELL-END convention)
    last = days[-1]
    for t in list(positions):
        px = close_of(t, last)
        if px:
            sell(t, positions[t]["shares"], px, last, "SELL-END")
        del positions[t]
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "halt_info": halt_info,
            "curve": curve, "taken": taken, "skipped": skipped}


def diagnostics(r):
    curve = r["curve"]
    if not curve:
        return {}
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d}


def spy_over(bars, start, end):
    """SPY net over an arbitrary date span (standalone event check)."""
    bl = [b for b in bars["SPY"] if start <= b["d"] <= end]
    if len(bl) < 2:
        return None
    o = bl[0]["o"]
    sh = (100.0 / 1.001) / o
    val = sh * bl[-1]["c"]
    return val - (val * 0.001 + 0.01)


# ------------------------------------------------------------------- main
def main():
    pb, equity_rows, shares_rows, bars = build_champion_inputs()

    # ---- replication check FIRST (champion + SPY, to the cent) ----
    repl = {}
    for wname, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, LADDER, label=f"REPL {wname}", quiet=True)
        repl[wname] = {"champion": round(r["final"], 2),
                       "spy": round(s, 2)}
        print(f"REPLICATION {wname}: champion=${r['final']:,.2f} "
              f"SPY=${s:,.2f}", flush=True)
    assert repl["FULL"]["champion"] == 544.47, repl
    assert repl["VALIDATION"]["champion"] == 288.05, repl
    assert repl["FULL"]["spy"] == 313.62, repl
    assert repl["VALIDATION"]["spy"] == 187.77, repl
    print("REPLICATION OK: champion $544.47 / $288.05, "
          "SPY $313.62 / $187.77 reproduced exactly.", flush=True)

    # ---- EVENT CENSUS (printed before any pot result) ----
    all_events = scan_events(bars)
    census = {}
    for wname, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        evs = window_events(all_events, pb, ws, we)
        census[wname] = evs
        per_year = {}
        for ev in evs:
            per_year[ev["signal"][:4]] = per_year.get(ev["signal"][:4],
                                                      0) + 1
        print(f"CENSUS {wname} ({ws} -> {we}): {len(evs)} qualifying "
              f"events; per year {per_year}", flush=True)
    print(f"CENSUS full cached series 2017-06 -> 2026-11: "
          f"{len(all_events)} events total.", flush=True)

    out = {"rule": "N-PV4 The Overnight Confession (INVENTED 2026; "
                   "1 of 12 invented rules)",
           "spec_source": "research/v8-novel/novel-price-volume.md "
                          "RULE N-PV4 (frozen)",
           "replication": repl,
           "census": {w: [{"ticker": e["ticker"], "signal": e["signal"],
                           "gap_pct": e["gap_pct"], "entry": e["entry"]}
                          for e in evs]
                      for w, evs in census.items()},
           "census_full_series_events": len(all_events)}

    # ---- ranked pots + placebos, both windows ----
    for wname, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        sched = census[wname]
        ranked = run_event_pot(pb, bars, sched, ws, we,
                               [e["ticker"] for e in sched],
                               label=f"{wname} RANKED")
        diag = diagnostics(ranked)
        print(f"== {wname} RANKED final=${ranked['final']:,.2f} "
              f"costs=${ranked['costs']:,.2f} "
              f"orders={len(ranked['trades'])} "
              f"taken={len(ranked['taken'])} "
              f"skipped={len(ranked['skipped'])} "
              f"halted={ranked['halted']}", flush=True)

        seeds = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            names = []
            for e in sched:
                pool = [t for t in UNIVERSE if t != e["ticker"]]
                names.append(rng.choice(pool))
            pr = run_event_pot(pb, bars, sched, ws, we, names,
                               label=f"{wname} PLACEBO s{seed}")
            seeds.append(round(pr["final"], 2))
        seeds_sorted = sorted(seeds)
        median = (seeds_sorted[9] + seeds_sorted[10]) / 2.0
        beaten = sum(1 for s in seeds if ranked["final"] > s)
        print(f"== {wname} PLACEBO median=${median:,.2f} "
              f"ranked beats {beaten}/20 "
              f"(min ${seeds_sorted[0]:,.2f}, max "
              f"${seeds_sorted[-1]:,.2f})", flush=True)

        # per-event standalone record for the ranked pot's taken events
        ev_rows = []
        for tk in ranked["taken"]:
            bl = [b for b in bars[tk["bought"]]
                  if tk["entry"] <= b["d"] <= (tk["exit"] or we)]
            if len(bl) >= 2:
                o = bl[0]["o"]
                sh = (100.0 / 1.001) / o
                val = sh * bl[-1]["c"]
                net = val - (val * 0.001 + 0.01)
                spy = spy_over(bars, tk["entry"],
                               tk["exit"] or we)
                ev_rows.append({
                    "ticker": tk["bought"], "signal": tk["signal"],
                    "gap_pct": tk["gap_pct"], "entry": tk["entry"],
                    "exit": tk["exit"],
                    "name_net_100": round(net, 2),
                    "spy_net_100": round(spy, 2) if spy else None,
                    "excess": round(net - spy, 2) if spy else None})

        out[wname] = {
            "window": [ws, we],
            "events_in_window": len(sched),
            "final": round(ranked["final"], 2),
            "return_pct": round((ranked["final"] / START_CASH - 1)
                                * 100, 2),
            "costs": round(ranked["costs"], 2),
            "orders": len(ranked["trades"]),
            "events_taken": len(ranked["taken"]),
            "events_skipped": ranked["skipped"],
            "halted": ranked["halted"],
            "halt_info": ranked["halt_info"],
            "diag": diag,
            "spy_net": repl[wname]["spy"],
            "champion": repl[wname]["champion"],
            "placebo_median": round(median, 2),
            "placebo_beaten": beaten,
            "placebo_seeds": seeds,
            "taken_events": ev_rows,
            "trades": ranked["trades"],
        }

    # ---- CANDIDATE gate (all four prongs, frozen) ----
    f, v = out["FULL"], out["VALIDATION"]
    gate = {
        "1_validation_beats_spy": v["final"] > 187.77,
        "2_validation_placebo_20_of_20": v["placebo_beaten"] == 20,
        "3_continuous_beats_spy": f["final"] > 313.62,
        "4_no_floor_halt_either_window": (f["halted"] is None
                                          and v["halted"] is None),
    }
    out["candidate_gate"] = gate
    out["verdict"] = ("CANDIDATE" if all(gate.values())
                      else "NOT A CANDIDATE")
    print(f"CANDIDATE GATE: {gate} -> {out['verdict']}", flush=True)

    with open(os.path.join(
            HERE, "novel-pv4-overnight-confession-results.json"),
            "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
