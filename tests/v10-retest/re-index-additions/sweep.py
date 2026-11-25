#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — re-index-additions CADENCE SWEEP.

Strategy (original, RE test / firm-reverse-engineering spec 4.1): buy every
S&P 500 addition at the OPEN of the first trading day after its S&P DJI
announcement; sell at the CLOSE of the effective date. Equal-split pot,
program costs (0.10%/side + $0.01/sell order), point-in-time event list and
adjusted prices — all inherited verbatim from engine.py (the original
engine copy in this folder).

SWEEP TREATMENT (SPEC, binding): DECADE road 2016-11-21 -> 2026-11-20 for
every cell (the harvested event census begins with announcements in Jan
2019 — the PR Newswire harvest in the original test; the pot sits in cash
2016-11-21 -> first event, documented, never backfilled). Event rules stay
exactly as published: ENTRIES are unchanged at every cadence (buy at the
open of the first trading day after announcement). CADENCE governs the
position review / exit-check rhythm only: a position exits at the CLOSE
of the first cadence date on or after its effective date (cadence dates
per the SPEC's uniform definition: daily = every trading day; weekly =
first trading day of each week; biweekly = first trading day of every
second week anchored on the window's first week; monthly = first trading
day of each month; quarterly = first trading day of each calendar
quarter; semi-annual = first trading day of each half-year; annual =
first trading day of each year). If no cadence date falls on/after the
effective date inside the window, the position is liquidated at the
window's final close (engine convention). The NATIVE form (exit exactly
at the effective-date close, event-driven) is also run on the decade as
the reference row.

PROTECTION (v9, adopted everywhere per SPEC): plain -15% floor from the
episode's starting balance; on first halt: liquidate at the next day's
open, sit in cash 90 calendar days, restart at the next cadence date on
or after halt_date + 90d under an episode-2 floor of -15% from the
restart balance; second halt ends the run. Events whose entry date falls
while the pot is halted/waiting are skipped (counted). The original
engine's halt (run ends at first floor touch) is NOT used here — that
form is preserved only in the integrity reproduction (engine.py main).

PLACEBOS (per cell, 20 seeds): the original chassis's placebo (ii) —
random honest-top-30 names (engine.UNIVERSE), one drawn name per event,
entered on the same announcement schedule (first bar after the real
announcement date), exited under the SAME cadence rule with the target
exit date = the real event's cadence-adjusted exit date (twin exits at
its own last close on or before that date, index >= entry index). Same
pot machinery, costs and v9 protections. placebo_beaten = seeds whose
final the ranked pot beats, /20. Placebo (i) (late entry, +20 trading
days) belongs to the original test and is reproduced in the integrity
run; it is not re-run per cadence cell.

Per-event stats per cell: events traded (entered), per-event mean net
excess vs SPY = mean over traded events of (standalone net return of the
event under this cell's exit rule) - (SPY net return over the same
entry->exit span, same cost convention).
"""
import importlib.util, json, math, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("orig_engine", os.path.join(HERE, "engine.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

START, END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
SEEDS = list(range(1, 21))

# ------------------------------------------------------------------ dates
def cadence_dates(all_days, cadence):
    """SPEC uniform cadence dates within the window (all_days = SPY trading
    days in window, sorted)."""
    if cadence == "daily":
        return set(all_days)
    out = []
    if cadence == "weekly":
        seen = set()
        for d in all_days:
            key = d[:4] + "-W" + str(date.fromisoformat(d).isocalendar()[1]).zfill(2) \
                  + "-" + str(date.fromisoformat(d).isocalendar()[0])
            wk = (date.fromisoformat(d).isocalendar()[0], date.fromisoformat(d).isocalendar()[1])
            if wk not in seen:
                seen.add(wk); out.append(d)
    elif cadence == "biweekly":
        weeks = []
        seen = set()
        for d in all_days:
            wk = (date.fromisoformat(d).isocalendar()[0], date.fromisoformat(d).isocalendar()[1])
            if wk not in seen:
                seen.add(wk); weeks.append(d)
        out = weeks[::2]
    elif cadence == "monthly":
        seen = set()
        for d in all_days:
            if d[:7] not in seen:
                seen.add(d[:7]); out.append(d)
    elif cadence == "quarterly":
        seen = set()
        for d in all_days:
            q = d[:4] + "-Q" + str((int(d[5:7]) - 1) // 3)
            if q not in seen:
                seen.add(q); out.append(d)
    elif cadence == "semiannual":
        seen = set()
        for d in all_days:
            h = d[:4] + "-H" + ("1" if int(d[5:7]) <= 6 else "2")
            if h not in seen:
                seen.add(h); out.append(d)
    elif cadence == "annual":
        seen = set()
        for d in all_days:
            if d[:4] not in seen:
                seen.add(d[:4]); out.append(d)
    return set(out)

# ------------------------------------------------------------- v9 pot run
def run_pot_v9(pb, trades, days, cad_set, start_cash=100.0):
    """Event pot with v9 protections. trades: {key,ticker,entry_date,
    exit_date} (exit_date already cadence-adjusted). Entries rebalance to
    equal weights at the entry day's open (engine forced reading 5);
    exits sell in full at the exit day's close. Floor checked on every
    daily close. Halt: liquidate next day open, cash 90 calendar days,
    restart at first cadence date >= halt+90d (episode 2, floor = 85% of
    restart balance); second halt ends the run."""
    buy_rate, sell_rate, sell_fee = 0.001, 0.001, 0.01
    entries, exits = {}, {}
    for tr in trades:
        entries.setdefault(tr["entry_date"], []).append(tr)
        exits.setdefault(tr["exit_date"], []).append(tr)
    cash = start_cash
    positions, open_keys = {}, []
    fills, total_costs = 0, 0.0
    curve = []
    episode = 1
    floor = 0.85 * start_cash
    state = "active"           # active | waiting | done
    restart_not_before = None
    halts = []
    entered_keys = set()

    def close_value(d):
        v = cash
        for k, (t, sh) in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    for di, d in enumerate(days):
        if state == "waiting" and d in cad_set and d >= restart_not_before:
            state = "active"
            floor = 0.85 * cash
            halts[-1]["restart_date"] = d
            halts[-1]["restart_balance"] = round(cash, 2)
            halts[-1]["episode2_floor"] = round(floor, 2)
        if state == "active":
            new = [tr for tr in entries.get(d, [])
                   if tr["key"] not in open_keys and tr["key"] not in entered_keys]
            if new:
                for tr in new:
                    open_keys.append(tr["key"])
                    entered_keys.add(tr["key"])
                    positions.setdefault(tr["key"], (tr["ticker"], 0.0))
                pv, opens = cash, {}
                for k in open_keys:
                    t, sh = positions[k]
                    b = pb.bar(t, d)
                    if b:
                        opens[k] = b["o"]; pv += sh * b["o"]
                    else:
                        c = pb.close_on_or_before(t, d)
                        if c:
                            pv += sh * c
                target = pv / len(open_keys) if open_keys else 0.0
                for k in list(open_keys):
                    if k not in opens:
                        continue
                    t, sh = positions[k]
                    cur = sh * opens[k]
                    if cur > target + 0.005:
                        sv = cur - target; ssh = sv / opens[k]
                        c = sv * sell_rate + sell_fee
                        cash += sv - c; total_costs += c; fills += 1
                        positions[k] = (t, sh - ssh if sh - ssh > 1e-9 else 0.0)
                for k in list(open_keys):
                    if k not in opens:
                        continue
                    t, sh = positions[k]
                    bv = target - sh * opens[k]
                    if bv > 0.005:
                        bv = min(bv, cash / (1.0 + buy_rate))
                        if bv <= 0.005:
                            continue
                        c = bv * buy_rate
                        cash -= bv + c; total_costs += c; fills += 1
                        positions[k] = (t, sh + bv / opens[k])
            for tr in exits.get(d, []):
                k = tr["key"]
                if k in positions:
                    t, sh = positions[k]
                    if sh > 1e-9:
                        b = pb.bar(t, d)
                        c_ = b["c"] if b else pb.close_on_or_before(t, d)
                        val = sh * c_; cst = val * sell_rate + sell_fee
                        cash += val - cst; total_costs += cst; fills += 1
                    del positions[k]
                if k in open_keys:
                    open_keys.remove(k)
        v = close_value(d) if state == "active" else cash
        curve.append((d, round(v, 2)))
        if state == "active" and v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for k in list(positions):
                t, sh = positions[k]
                b = pb.bar(t, nd)
                if b and sh > 1e-9:
                    val = sh * b["o"]; cst = val * sell_rate + sell_fee
                    cash += val - cst; total_costs += cst; fills += 1
            positions, open_keys = {}, []
            halts.append({"episode": episode, "signal_date": d,
                          "signal_close": round(v, 2), "floor": round(floor, 2),
                          "liquidation_date": nd,
                          "balance_after_liquidation": round(cash, 2)})
            if episode == 1:
                episode = 2
                state = "waiting"
                restart_not_before = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
            else:
                state = "done"
                halts[-1]["second_halt"] = True
                # remaining curve stays at cash
                for d2 in days[di + 1:]:
                    curve.append((d2, round(cash, 2)))
                break
    if state != "done":
        last = days[-1]
        for k in list(positions):
            t, sh = positions[k]
            if sh > 1e-9:
                c_ = pb.close_on_or_before(t, last)
                if c_:
                    val = sh * c_; cst = val * sell_rate + sell_fee
                    cash += val - cst; total_costs += cst; fills += 1
        positions = {}
    # dedupe curve dates (break path may double-append)
    seen, c2 = set(), []
    for d, v in curve:
        if d not in seen:
            seen.add(d); c2.append((d, v))
    return {"final": cash, "costs": total_costs, "orders": fills,
            "halts": halts, "curve": c2, "entered": len(entered_keys)}

# ------------------------------------------------------------ trade build
def cadence_exit(pb, ticker, eff, cad_set, days_set):
    """Close of the first cadence date >= effective date on which the
    ticker has a bar on/before it; returns (exit_date, exit_close)."""
    for d in sorted(cad_set):
        if d >= eff:
            i, b = pb.bar_on_or_before(ticker, d)
            if b is not None:
                return b["d"], b["c"]
    return None, None

def standalone_net(entry_open, exit_close):
    sh = (100.0 / 1.001) / entry_open
    proceeds = sh * exit_close
    return (proceeds - (proceeds * 0.001 + 0.01)) / 100.0 - 1.0

def spy_span_net(pb, entry_date, exit_date):
    ei, eb = pb.first_bar_after("SPY", entry_date)  # not used; direct below
    b_in = pb.bar("SPY", entry_date)
    b_out = pb.bar("SPY", exit_date)
    if b_in is None:
        i, b_in = pb.bar_on_or_before("SPY", entry_date)
    if b_out is None:
        i, b_out = pb.bar_on_or_before("SPY", exit_date)
    if b_in is None or b_out is None:
        return None
    return standalone_net(b_in["o"], b_out["c"])

def main():
    bars, notes = E.load_series()
    pb = E.PriceBook(bars)
    # Performance only: bisect-based lookups with semantics identical to
    # PriceBook.close_on_or_before / bar_on_or_before (last bar with
    # date <= d). The engine's linear scans made the slow-cadence cells
    # (many positions open at once) take tens of minutes under load.
    import bisect as _bisect
    _dlists = {t: [b["d"] for b in bl] for t, bl in pb.bars.items()}

    def _cob(t, d):
        dl = _dlists.get(t, [])
        i = _bisect.bisect_right(dl, d) - 1
        return pb.bars[t][i]["c"] if i >= 0 else None

    def _bob(t, d):
        dl = _dlists.get(t, [])
        i = _bisect.bisect_right(dl, d) - 1
        return (i, pb.bars[t][i]) if i >= 0 else (None, None)

    pb.close_on_or_before = _cob
    pb.bar_on_or_before = _bob
    resolved, excluded = E.build_event_trades(pb)
    days = [d for d in pb.dates if START <= d <= END]
    spy_final, spy_costs = E.spy_net(pb, START, END)
    print(f"SPY decade: ${spy_final:.2f} (costs ${spy_costs:.2f}); "
          f"events resolved {len(resolved)}, excluded {len(excluded)}", flush=True)
    years = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

    def build_trades(cad_set):
        trades, stats = [], []
        for ev in resolved:
            if not (START <= ev["entry_date"] and ev["ann"] <= END):
                continue
            if cad_set is None:      # native: exit at effective close
                xd, xc = ev["exit_date"], ev["exit_close"]
            else:
                xd, xc = cadence_exit(pb, ev["ticker"], ev["eff"], cad_set, set(days))
                if xd is None:
                    continue
            net = standalone_net(ev["entry_open"], xc)
            snet = spy_span_net(pb, ev["entry_date"], xd)
            trades.append({"key": ev["key"], "ticker": ev["ticker"],
                           "ann": ev["ann"], "entry_date": ev["entry_date"],
                           "exit_date": xd})
            stats.append({"ticker": ev["ticker"], "ann": ev["ann"],
                          "entry_date": ev["entry_date"], "exit_date": xd,
                          "net_ret_pct": round(net * 100, 3),
                          "spy_net_ret_pct": round(snet * 100, 3) if snet is not None else None,
                          "excess_pct": round((net - snet) * 100, 3) if snet is not None else None})
        return trades, stats

    def placebo_trades(seed, real_trades_by_key):
        rng = random.Random(seed)
        pool = sorted(E.UNIVERSE)
        trades, skipped = [], 0
        for ev in sorted(resolved, key=lambda e: (e["ann"], e["ticker"])):
            rt = real_trades_by_key.get(ev["key"])
            if rt is None:
                continue
            t = rng.choice(pool)
            ei, eb = pb.first_bar_after(t, ev["ann"])
            if eb is None:
                skipped += 1; continue
            xi, xb = pb.bar_on_or_before(t, rt["exit_date"])
            if xb is None or xi < ei:
                skipped += 1; continue
            trades.append({"key": f"{ev['key']}|s{seed}:{t}", "ticker": t,
                           "ann": ev["ann"], "entry_date": eb["d"],
                           "exit_date": xb["d"]})
        return trades, skipped

    cells_out = {}
    runs = [("native-event", None)] + [(c, cadence_dates(days, c)) for c in CADENCES]
    if len(sys.argv) > 1:   # optional: run only the named cells
        want = set(sys.argv[1:])
        runs = [r for r in runs if r[0] in want]
    for name, cad_set in runs:
        trades, stats = build_trades(cad_set)
        by_key = {t["key"]: t for t in trades}
        res = run_pot_v9(pb, trades, days, cad_set if cad_set is not None else set(days))
        seed_finals, skipped_tot = [], 0
        for s in SEEDS:
            ptr, sk = placebo_trades(s, by_key)
            skipped_tot += sk
            pr = run_pot_v9(pb, ptr, days, cad_set if cad_set is not None else set(days))
            seed_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in seed_finals if res["final"] > f)
        exc = [s["excess_pct"] for s in stats if s["excess_pct"] is not None]
        nets = [s["net_ret_pct"] for s in stats]
        cell = {"final": round(res["final"], 2),
                "cagr_pct": round(((res["final"] / 100.0) ** (1.0 / years) - 1) * 100, 2),
                "max_dd_pct": round(E.max_dd(res["curve"]) * 100, 2),
                "costs": round(res["costs"], 2), "orders": res["orders"],
                "halts": res["halts"],
                "restart": any("restart_date" in h for h in res["halts"]),
                "second_halt": any(h.get("second_halt") for h in res["halts"]),
                "events_traded": res["entered"],
                "events_available": len(trades),
                "event_stats": {
                    "n": len(stats),
                    "mean_net_ret_pct": round(sum(nets) / len(nets), 3) if nets else None,
                    "mean_net_excess_vs_spy_pct": round(sum(exc) / len(exc), 3) if exc else None,
                    "median_net_excess_vs_spy_pct": round(sorted(exc)[len(exc) // 2], 3) if exc else None,
                    "events": stats},
                "placebo_beaten": f"{beaten}/20",
                "placebo_seed_finals": seed_finals,
                "placebo_skipped_trades_total": skipped_tot,
                "equity_curve": [[d, v] for d, v in res["curve"]]}
        fname = "native-event" if name == "native-event" else name
        with open(os.path.join(HERE, "cells", fname + ".json"), "w") as f:
            json.dump(cell, f, indent=1)
        if name != "native-event":
            cells_out[name] = {k: cell[k] for k in
                               ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                                "placebo_beaten", "events_traded")}
            cells_out[name]["halts"] = len(res["halts"])
            cells_out[name]["restart"] = cell["restart"]
            cells_out[name]["second_halt"] = cell["second_halt"]
            cells_out[name]["mean_net_excess_vs_spy_pct"] = \
                cell["event_stats"]["mean_net_excess_vs_spy_pct"]
        print(f"[{name}] final=${res['final']:.2f} events={res['entered']} "
              f"halts={len(res['halts'])} beaten={beaten}/20 "
              f"meanExcess={cell['event_stats']['mean_net_excess_vs_spy_pct']}%", flush=True)

    if len(sys.argv) > 1:
        print("PARTIAL RUN DONE (summary not overwritten)", flush=True)
        return
    with open(os.path.join(HERE, "sweep-summary.json"), "w") as f:
        json.dump({"spy_decade_final": round(spy_final, 2),
                   "spy_decade_costs": round(spy_costs, 2),
                   "cells": cells_out}, f, indent=1)
    print("SWEEP DONE", flush=True)

if __name__ == "__main__":
    main()
