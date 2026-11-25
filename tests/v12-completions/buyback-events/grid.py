#!/usr/bin/env python3
"""
BUYBACK-EVENTS v12 — SECOND-CHANCE GRID (CONSTRUCTION-SPEC.md section (e),
pre-registered 2026-11-22 before any run).

Axes: holdings count {1,2,3,5,8,10,15,20,30,ALL} x hold {6,12,24,48}mo
x rulebook {native (no protections), v9 protections} x protection-check
cadence {daily, weekly, monthly, quarterly, semiannual, annual} (v9 cells
only). Road: DECADE. Placebos per cell: canonical +6mo shift + seeds 1-3
(same construction as run.py). Any cell beating the DECADE champion
($667.35) is confirmed on CONT + VAL with the full 20-seed battery.

Mechanics are run.py's run_pot, parameterized; everything else (entry,
costs, slice = pot-value/slots, exits before entries, end-of-window
mark-out) is inherited unchanged. Simulation only.
"""
import json
import os
import random
from datetime import date, timedelta

import run as R

HERE = R.HERE
cal = R.cal
add_months = R.add_months
EVENTS = R.EVENTS_NEW
START_CASH = 100.0
CHAMPION_DECADE = 667.35


def check_days_for(days, cadence):
    if cadence == "daily":
        return set(days)
    out = set()
    last = {}
    for d in days:
        dt = date.fromisoformat(d)
        if cadence == "weekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1])
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        last[key] = d
    return set(last.values())


def run_pot_grid(events, start, end, slots, hold_months, protect, cadence):
    """slots=None -> ALL-ELIGIBLE (no cap, slice divisor 20)."""
    days = [d for d in cal.days if start <= d <= end]
    if not days:
        return None
    max_pos = slots if slots is not None else 10 ** 9
    divisor = slots if slots is not None else 20
    check = check_days_for(days, cadence) if protect else set()
    by_entry = {}
    for tk, fd, note in events:
        if not (start <= fd <= end):
            continue
        entry = cal.first_day_after(fd)
        if entry is None or entry > end:
            continue
        by_entry.setdefault(entry, []).append((tk, fd, note))
    cash = START_CASH
    positions = []
    total_costs = 0.0
    curve = []
    episode = 1
    floor = 0.85 * START_CASH
    restart_not_before = None
    restart_logged = False
    halts = 0

    def close_value(d):
        v = cash
        for p in positions:
            c = cal.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for di, d in enumerate(days):
        for p in list(positions):
            if p["exit_day"] == d:
                xp = cal.open_on(p["ticker"], d)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], d)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                positions.remove(p)
        if restart_not_before is not None and not restart_logged \
                and d >= restart_not_before:
            restart_logged = True
        in_cooldown = restart_not_before is not None and d < restart_not_before
        for tk, fd, note in by_entry.get(d, []):
            if in_cooldown:
                continue
            if any(p["ticker"] == tk for p in positions):
                continue
            if len(positions) >= max_pos:
                continue
            o = cal.open_on(tk, d)
            if o is None:
                continue
            pv = cash
            for p in positions:
                po = cal.open_on(p["ticker"], d)
                if po:
                    pv += p["shares"] * po
            buy_val = min(pv / divisor, cash / 1.001)
            if buy_val <= 0.005:
                continue
            sh = buy_val / o
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            exit_day = cal.first_day_on_or_after(add_months(d, hold_months))
            if exit_day is None:
                exit_day = days[-1]
            positions.append({"ticker": tk, "shares": sh,
                              "exit_day": exit_day, "entry": d, "filing": fd})
        v = close_value(d)
        curve.append([d, round(v, 4)])
        if protect and d in check and v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for p in list(positions):
                xp = cal.open_on(p["ticker"], nd)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], nd)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
            positions = []
            halts += 1
            if episode >= 2:
                return {"final": round(cash, 2), "costs": round(total_costs, 2),
                        "halts": halts, "curve": curve, "halted_end": True}
            episode = 2
            floor = 0.85 * cash
            restart_not_before = (
                date.fromisoformat(nd) + timedelta(days=90)).isoformat()
            restart_logged = False
    last = days[-1]
    for p in list(positions):
        xp = cal.close_on_or_before(p["ticker"], last)
        val = p["shares"] * xp
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "halts": halts, "curve": curve, "halted_end": False}


def shifted(events, months=None, seed=None):
    if seed is None:
        return [(tk, add_months(fd, months), note) for tk, fd, note in events]
    rng = random.Random(1000 + seed)
    offs = [rng.choice([m for m in range(-18, 19) if m != 0]) for _ in events]
    return [(tk, add_months(fd, off), note)
            for (tk, fd, note), off in zip(events, offs)]


def run_cell(slots, hold, protect, cadence, start, end, n_seeds):
    real = run_pot_grid(EVENTS, start, end, slots, hold, protect, cadence)
    canon = run_pot_grid(shifted(EVENTS, months=6), start, end,
                         slots, hold, protect, cadence)
    seeds = []
    for s in range(1, n_seeds + 1):
        r = run_pot_grid(shifted(EVENTS, seed=s), start, end,
                         slots, hold, protect, cadence)
        seeds.append(r["final"])
    return {"slots": slots if slots is not None else "ALL",
            "hold_months": hold,
            "rulebook": "v9" if protect else "native",
            "cadence": cadence if protect else None,
            "final": real["final"], "max_dd_pct": R.max_dd(real["curve"]),
            "costs": real["costs"], "halts": real["halts"],
            "canonical_placebo_final": canon["final"],
            "seed_finals": seeds,
            "seeds_beaten": sum(1 for f in seeds if real["final"] > f),
            "beats_champion_decade": real["final"] > CHAMPION_DECADE}


def main():
    DS, DE = "2016-11-21", "2026-11-20"
    slot_grid = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]
    hold_grid = [6, 12, 24, 48]
    cadences = ["daily", "weekly", "monthly", "quarterly",
                "semiannual", "annual"]
    cells = []
    for slots in slot_grid:
        for hold in hold_grid:
            cells.append(run_cell(slots, hold, False, None, DS, DE, 3))
            print(f"native slots={slots} hold={hold}: "
                  f"${cells[-1]['final']} canon ${cells[-1]['canonical_placebo_final']} "
                  f"seeds {cells[-1]['seeds_beaten']}/3", flush=True)
            for cad in cadences:
                cells.append(run_cell(slots, hold, True, cad, DS, DE, 3))
                print(f"v9/{cad} slots={slots} hold={hold}: "
                      f"${cells[-1]['final']} canon ${cells[-1]['canonical_placebo_final']} "
                      f"seeds {cells[-1]['seeds_beaten']}/3", flush=True)
    winners = [c for c in cells if c["beats_champion_decade"]]
    confirmations = []
    for c in winners:
        slots = None if c["slots"] == "ALL" else c["slots"]
        for road, ws, we in [("CONT", "2019-01-02", "2026-11-20"),
                             ("VAL", "2023-01-03", "2026-11-20")]:
            conf = run_cell(slots, c["hold_months"],
                            c["rulebook"] == "v9", c["cadence"], ws, we, 20)
            conf["road"] = road
            confirmations.append(conf)
            print(f"CONFIRM {road} {c}: ${conf['final']} "
                  f"seeds {conf['seeds_beaten']}/20", flush=True)
    out = {"road": "DECADE", "champion_decade": CHAMPION_DECADE,
           "n_cells": len(cells), "cells": cells,
           "confirmations": confirmations}
    with open(os.path.join(HERE, "grid_results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    best = max(cells, key=lambda c: c["final"])
    print(f"GRID DONE: {len(cells)} cells; best cell ${best['final']} "
          f"(slots={best['slots']} hold={best['hold_months']} "
          f"{best['rulebook']}/{best['cadence']}); winners={len(winners)}")


if __name__ == "__main__":
    main()
