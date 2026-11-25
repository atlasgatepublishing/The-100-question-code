#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — re-put-hedge (Protective-Put Tail Hedge, RE #2).

Strategy (original form, v7 audit spec 4.2): a 50/50 blend — half the
champion (value+momentum, promoted spec, unchanged), half the CBOE S&P 500
5% Protective Put Index (PPUT) — plus PPUT standalone and a 50/50
champion/SPY control blend. Plain -15% floor in the original; v9 protection
in the sweep.

OPTIONS PRICING CONSTRUCTION (the original test's own, used exactly):
there is no free historical SPX options chain. The original test never
prices an option itself. It uses the published CBOE PPUT total-return
index levels (PPUT_History.csv, CBOE free CDN, downloaded 2026-11-21,
stored in the v7 folder, read-only here). PPUT's own published methodology
embeds the option leg: the index holds the S&P 500 plus a monthly 5%
out-of-the-money SPX put, rolled on the 3rd Friday, with the index's own
cost treatment inside the level. No additional option cost is charged on
the put leg (the original spec's stated treatment). PPUT was launched
2015-06-30; levels before that are CBOE back-calculations under the
published methodology (disclosed wherever the 2010 window is used).

CADENCE TREATMENT (stated before results, per SPEC sweep):
cadence governs the hedge review / roll rhythm of the BLEND: the frequency
at which the 50/50 champion/PPUT split is reviewed and rebalanced back to
50/50 (transfer charged at the house schedule: 0.10% sell + 0.10% buy on
the transferred value + $0.01 x 5 sell orders = transfer*0.002 + $0.05).
The PPUT leg's internal monthly put roll is embedded in the published
index and cannot be altered at any cadence; the champion sleeve keeps its
own quarterly selection at every cadence (it is a sleeve, not the hedge).
Native cadence = monthly (SPEC CADENCE GRID: "re-put-hedge — monthly
(PPUT roll)"). The ORIGINAL test rebalanced the blend only each January
(annual) — so the original blend-weight rhythm was annual while the hedge
leg rolled monthly; original_cadence_foreign = true on that point.

v9 PROTECTION (sweep cells): plain -15% floor from the episode's starting
balance at the whole-pot level only (sleeves run unfloored, house blend
method). On a breach close: liquidate at the next date's marked total
x(1-0.10%) - $0.10; sit in cash 90 calendar days; restart 50/50 at the
first cadence date on/after the sit-out ends, under an episode-2 floor of
-15% from the restart balance; a second breach ends the run (final =
liquidation value). During the sit-out the pot curve is flat cash.

Windows: DECADE sweep 2016-11-21 -> 2026-11-20 (all 7 cadences);
supplementary LONG 2010-01-04 -> 2026-11-20 at monthly (native) and
annual (original rhythm). The decade/LONG runs use the long-hold 2010
book (the same book the original 2010 window used), so the champion
sleeve construction is identical to the original 2010 construction.
Integrity windows use the original books and the original blend_curves
verbatim (his rules, annual January rebalance).
"""
import importlib.util
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(HERE, "..", "..", "v7", "re-put-hedge", "re-put-hedge.py")


def _load(path):
    spec = importlib.util.spec_from_file_location("orig_put_hedge", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


O = _load(V7)
E = O.E
POT, HALF = 100.0, 50.0
DEC = ("2016-11-21", "2026-11-20")
LONG = ("2010-01-04", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def max_dd(curve):
    return O.max_dd(curve)


def cagr_pct(final, sd, ed, start=POT):
    return round(O.cagr(final, start, sd, ed) * 100, 2)


def year_ret(curve, year, start_val=None):
    """Calendar-year return of a (date, value) curve. For the first year,
    measured from start_val (pot start) if given."""
    pts = [(d, v) for d, v in curve if d[:4] == str(year)]
    if not pts:
        return None
    prev_pts = [(d, v) for d, v in curve if d[:4] == str(year - 1)]
    base = prev_pts[-1][1] if prev_pts else start_val
    if base is None:
        return None
    return round((pts[-1][1] / base - 1.0) * 100, 2)


def cadence_dates(dates, cadence):
    """Rebalance/review dates per the SPEC uniform definition: first
    trading day of each period. Inception date excluded."""
    if cadence == "daily":
        sel = list(dates)
    elif cadence == "weekly":
        sel, seen = [], set()
        for d in dates:
            k = datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                sel.append(d)
    elif cadence == "biweekly":
        sel, seen, wk = [], set(), []
        for d in dates:
            k = datetime.strptime(d, "%Y-%m-%d").isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                wk.append(d)
        sel = wk[::2]
    elif cadence == "monthly":
        sel, seen = [], set()
        for d in dates:
            if d[:7] not in seen:
                seen.add(d[:7])
                sel.append(d)
    elif cadence == "quarterly":
        sel, seen = [], set()
        for d in dates:
            k = (d[:4], (int(d[5:7]) - 1) // 3)
            if k not in seen:
                seen.add(k)
                sel.append(d)
    elif cadence == "semiannual":
        sel, seen = [], set()
        for d in dates:
            k = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
            if k not in seen:
                seen.add(k)
                sel.append(d)
    elif cadence == "annual":
        sel, seen = [], set()
        for d in dates:
            if d[:4] not in seen:
                seen.add(d[:4])
                sel.append(d)
    return [d for d in sel if d != dates[0]]


def blend_v9(curveA, curveB, dates, cadence, pot0=POT):
    """50/50 blend of sleeve curves A (champion) and B (index leg) with
    cadence rebalances and v9 pot-level protection. Sleeves run unfloored
    standalone (house method); scales carry each sleeve's value."""
    A, B = dict(curveA), dict(curveB)
    reb_dates = set(cadence_dates(dates, cadence))
    # initialise scales from first values
    lastA, lastB = A[dates[0]], B[dates[0]]
    scaleA = (pot0 / 2.0) / lastA
    scaleB = (pot0 / 2.0) / lastB
    curve, rebalances, halts = [], [], []
    transfer_costs = 0.0
    episode = 1
    ep_start_balance = pot0
    floor = 0.85 * pot0
    cash = None            # not None while halted / in sit-out
    restart_after = None   # first date >= this may restart (cadence date)
    final = None
    second_halt = False
    for idx, d in enumerate(dates):
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        if cash is not None:
            # in sit-out: restart only on a cadence date >= restart_after
            if d >= restart_after and d in reb_dates:
                # re-split cash 50/50 at today's sleeve levels
                scaleA = (cash / 2.0) / lastA
                scaleB = (cash / 2.0) / lastB
                ep_start_balance = cash
                floor = 0.85 * cash
                halts[-1]["restart_date"] = d
                halts[-1]["restart_balance"] = round(cash, 2)
                halts[-1]["episode2_floor"] = round(floor, 2)
                cash = None
                tot = scaleA * lastA + scaleB * lastB
                curve.append((d, tot))
                continue
            curve.append((d, cash))
            continue
        va, vb = scaleA * lastA, scaleB * lastB
        tot = va + vb
        if d in reb_dates:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            rebalances.append({"date": d, "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        curve.append((d, tot))
        if tot <= floor:
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                na, nb = A.get(nd, lastA), B.get(nd, lastB)
                liq = (scaleA * na + scaleB * nb) * (1 - 0.001) - 0.10
            else:
                liq = tot * (1 - 0.001) - 0.10
            h = {"episode": episode, "halt_date": d,
                 "signal_close": round(tot, 2),
                 "liquidated": round(liq, 2),
                 "liquidation_date": dates[idx + 1] if idx < len(dates) - 1
                 else d}
            halts.append(h)
            if episode == 1:
                episode = 2
                cash = liq
                sitout_end = (datetime.strptime(d, "%Y-%m-%d")
                              + timedelta(days=90)).strftime("%Y-%m-%d")
                h["sitout_end"] = sitout_end
                restart_after = sitout_end
            else:
                second_halt = True
                final = liq
                break
    if final is None:
        final = curve[-1][1]
    return {"curve": curve, "final": final, "halts": halts,
            "restart": any("restart_date" in h for h in halts),
            "second_halt": second_halt,
            "transfer_costs": transfer_costs,
            "n_rebalances": len(rebalances), "rebalances": rebalances,
            "max_dd_pct": round(max_dd(curve) * 100, 2)}


def sleeve_on_dates(rows, rows_dates, dates, cash):
    curve, _ = O.index_sleeve_curve(rows, rows_dates, dates, cash=cash)
    return curve


def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    pput_rows = O.load_pput()
    pput_dates = [d for d, _ in pput_rows]
    out = {"slug": "re-put-hedge"}

    # ---------------- INTEGRITY (original form, his rules) ----------------
    print("== integrity: honest book ==", flush=True)
    E.DATA = O.HONEST_DATA
    E.UNIVERSE = list(O.HONEST_UNIVERSE)
    pb_h, eq_h, so_h = O.build_vm_book()
    integ = {}
    for name, sd, ed, placebo in [
            ("continuous", "2019-01-01", "2026-11-20", False),
            ("validation", "2023-01-01", "2026-11-20", False),
            ("fold2020", "2020-01-01", "2020-12-31", False)]:
        r = O.run_window(name, pb_h, eq_h, so_h, sd, ed, pput_rows,
                         pput_dates, run_placebo=False)
        integ[name] = {"champion": r["champion_parent"]["final"],
                       "spy_net": r["spy_net_final"],
                       "pput_standalone": r["pput_standalone"]["final"],
                       "pput_blend": r["pput_blend"]["final"],
                       "pput_blend_halt": r["pput_blend"]["halt"],
                       "spy_blend": r["spy_blend"]["final"]}
        print(name, integ[name], flush=True)
    print("== integrity: 2010 book ==", flush=True)
    E.DATA = O.LH_DATA
    pb_l, eq_l, so_l, uni = O.build_2010_book()
    # FIX (completion worker, documented): the v7 original sets
    # E.UNIVERSE = the rebuilt 2010 top-30 before running the 2010 book;
    # the first v10 draft omitted this, so the engine selected from the
    # honest-book universe and LONG did not reproduce (champion $1,153.64
    # unhalted instead of $85.34 halted 2010-08-26). Restoring the v7
    # line exactly; no other change.
    E.UNIVERSE = list(uni)
    r = O.run_window("long2010", pb_l, eq_l, so_l, "2010-01-04",
                     "2026-11-20", pput_rows, pput_dates, run_placebo=False)
    integ["long2010"] = {"champion": r["champion_parent"]["final"],
                         "champion_halted": r["champion_parent"]["halted"],
                         "spy_net": r["spy_net_final"],
                         "pput_standalone": r["pput_standalone"]["final"],
                         "pput_blend": r["pput_blend"]["final"],
                         "pput_blend_halt": r["pput_blend"]["halt"],
                         "spy_blend": r["spy_blend"]["final"]}
    print("long2010", integ["long2010"], flush=True)
    published = {
        "continuous": {"champion": 544.47, "spy_net": 313.62,
                       "pput_standalone": 253.62, "pput_blend": 384.30,
                       "spy_blend": 420.74},
        "validation": {"champion": 288.05, "spy_net": 187.77,
                       "pput_standalone": 165.74, "pput_blend": 221.71,
                       "spy_blend": 236.81},
        "fold2020": {"champion": 83.62, "pput_standalone": 128.11,
                     "pput_blend": 78.98, "spy_blend": 86.83},
        "long2010": {"champion": 85.34, "spy_net": 822.94,
                     "pput_standalone": 501.31, "pput_blend": 1017.61,
                     "spy_blend": 1283.53}}
    ok = True
    for w, pub in published.items():
        for k, v in pub.items():
            got = integ[w].get(k)
            if got is None or abs(got - v) > 0.011:
                ok = False
                print(f"INTEGRITY MISMATCH {w}.{k}: got {got} pub {v}",
                      flush=True)
    out["integrity_check"] = {"all_match": ok, "reproduced": integ,
                              "published": published}
    print("INTEGRITY ALL MATCH:", ok, flush=True)

    # ---------------- DECADE + LONG sweep (2010 book) ----------------
    sd, ed = DEC
    dates = [d for d in pb_l.dates if sd <= d <= ed]
    champ = E.run_pot(pb_l, eq_l, so_l, sd, ed, HALF, 0.0, [], quiet=True)
    champ_full = E.run_pot(pb_l, eq_l, so_l, sd, ed, POT, 85.0, [],
                           quiet=True)
    spy_net, _ = E.spy_net(pb_l, sd, ed, POT)
    pput_sleeve = sleeve_on_dates(pput_rows, pput_dates, dates, HALF)
    spy_sleeve = O.spy_sleeve_curve(pb_l, dates, cash=HALF)
    pput100 = sleeve_on_dates(pput_rows, pput_dates, dates, POT)
    spy100_curve = [(d, v * 2) for d, v in spy_sleeve]
    leg_drag = round(spy100_curve[-1][1] - pput100[-1][1], 2)
    spy_dd = round(max_dd(spy100_curve) * 100, 2)
    print(f"DECADE SPY net ${spy_net:.2f} maxDD {spy_dd}% | leg drag "
          f"${leg_drag} | champ sleeve50 ${champ['curve'][-1][1]:.2f} "
          f"| champ full floored ${champ_full['final']:.2f} "
          f"halt={champ_full['halted']}", flush=True)

    # placebo sleeves (random-rank champion twins), decade
    print("placebo sleeves...", flush=True)
    placebo_sleeves = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        ps = E.run_pot(pb_l, eq_l, so_l, sd, ed, HALF, 0.0, [],
                       placebo_rng=rng, quiet=True)
        placebo_sleeves.append(ps["curve"])
        print(f"  seed {seed} done", flush=True)

    cells = {}
    for cad in CADENCES:
        b = blend_v9(champ["curve"], pput_sleeve, dates, cad)
        ctrl = blend_v9(champ["curve"], spy_sleeve, dates, cad)
        twin_finals = []
        for pc in placebo_sleeves:
            tb = blend_v9(pc, pput_sleeve, dates, cad)
            twin_finals.append(round(tb["final"], 2))
        beaten = sum(1 for f in twin_finals if f < b["final"])
        total_costs = round(champ["costs"] + b["transfer_costs"], 2)
        cell = {
            "final": round(b["final"], 2),
            "cagr_pct": cagr_pct(b["final"], dates[0], dates[-1]),
            "max_dd_pct": b["max_dd_pct"],
            "halts": [{"date": h["halt_date"], "episode": h["episode"],
                       "signal_close": h["signal_close"],
                       "liquidated": h["liquidated"],
                       "liquidation_date": h["liquidation_date"],
                       "sitout_end": h.get("sitout_end"),
                       "restart_date": h.get("restart_date"),
                       "restart_balance": h.get("restart_balance"),
                       "episode2_floor": h.get("episode2_floor")}
                      for h in b["halts"]],
            "restart": b["restart"], "second_halt": b["second_halt"],
            "costs": total_costs,
            "costs_detail": {
                "champion_sleeve_costs": round(champ["costs"], 2),
                "blend_transfer_costs": round(b["transfer_costs"], 2),
                "hedge_premium_leg_drag_decade": leg_drag,
                "note": "leg drag = unhedged SPY $100 mark minus PPUT "
                        "standalone $100 no-floor final over the decade; "
                        "the premium the put leg cost vs holding SPY. "
                        "PPUT's internal option costs are inside the "
                        "published index level (no separate charge)."},
            "orders": len(champ["trades"]) + b["n_rebalances"]
                      + len(b["halts"]),
            "n_rebalances": b["n_rebalances"],
            "placebo_beaten": beaten,
            "placebo_twin_finals": twin_finals,
            "placebo_note": "20 random-rank champion-sleeve twins blended "
                            "with the same PPUT sleeve at the same cadence "
                            "(original test's house placebo design).",
            "defense": {
                "blend_2020_ret_pct": year_ret(b["curve"], 2020),
                "blend_2022_ret_pct": year_ret(b["curve"], 2022),
                "spy_2020_ret_pct": year_ret(spy100_curve, 2020),
                "spy_2022_ret_pct": year_ret(spy100_curve, 2022),
                "unhedged_spy_decade_final": round(spy_net, 2),
                "unhedged_spy_decade_mark": round(spy100_curve[-1][1], 2),
                "unhedged_spy_max_dd_pct": spy_dd,
                "spy_blend_control_final": round(ctrl["final"], 2),
                "spy_blend_control_max_dd_pct": ctrl["max_dd_pct"],
                "champion_full_floored_final": round(champ_full["final"], 2),
                "champion_full_halted": champ_full["halted"]},
            "equity_curve": [[d, round(v, 4)] for d, v in b["curve"]]}
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"slug": "re-put-hedge", "window": "DECADE",
                       "start": sd, "end": ed, "cadence": cad, **cell}, f,
                      indent=1)
        print(f"{cad}: final ${cell['final']} dd {cell['max_dd_pct']}% "
              f"placebo {beaten}/20 ctrl ${cell['defense']['spy_blend_control_final']}",
              flush=True)
    out["decade"] = {"spy_net_final": round(spy_net, 2),
                     "spy_max_dd_pct": spy_dd, "leg_drag": leg_drag,
                     "champion_sleeve50_final": round(champ["curve"][-1][1], 2),
                     "champion_full_floored_final": round(champ_full["final"], 2),
                     "champion_full_halted": champ_full["halted"],
                     "cells": {c: {k: v for k, v in cells[c].items()
                                   if k not in ("equity_curve",
                                                "placebo_twin_finals")}
                               for c in CADENCES}}

    # ---------------- LONG supplementary (monthly native + annual) ----
    lsd, led = LONG
    ldates = [d for d in pb_l.dates if lsd <= d <= led]
    lchamp = E.run_pot(pb_l, eq_l, so_l, lsd, led, HALF, 0.0, [], quiet=True)
    lpput = sleeve_on_dates(pput_rows, pput_dates, ldates, HALF)
    lspy_sleeve = O.spy_sleeve_curve(pb_l, ldates, cash=HALF)
    lspy100 = [(d, v * 2) for d, v in lspy_sleeve]
    lpput100 = sleeve_on_dates(pput_rows, pput_dates, ldates, POT)
    long_cells = {}
    for cad in ("monthly", "annual"):
        b = blend_v9(lchamp["curve"], lpput, ldates, cad)
        ctrl = blend_v9(lchamp["curve"], lspy_sleeve, ldates, cad)
        cell = {"final": round(b["final"], 2),
                "cagr_pct": cagr_pct(b["final"], ldates[0], ldates[-1]),
                "max_dd_pct": b["max_dd_pct"],
                "halts": b["halts"], "restart": b["restart"],
                "second_halt": b["second_halt"],
                "costs": round(lchamp["costs"] + b["transfer_costs"], 2),
                "transfer_costs": round(b["transfer_costs"], 2),
                "orders": len(lchamp["trades"]) + b["n_rebalances"]
                          + len(b["halts"]),
                "spy_blend_control_final": round(ctrl["final"], 2),
                "leg_drag_long": round(lspy100[-1][1] - lpput100[-1][1], 2),
                "blend_2020_ret_pct": year_ret(b["curve"], 2020),
                "blend_2022_ret_pct": year_ret(b["curve"], 2022),
                "spy_2020_ret_pct": year_ret(lspy100, 2020),
                "spy_2022_ret_pct": year_ret(lspy100, 2022),
                "equity_curve": [[d, round(v, 4)] for d, v in b["curve"]]}
        long_cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"long-{cad}.json"), "w") as f:
            json.dump({"slug": "re-put-hedge", "window": "LONG-2010",
                       "start": lsd, "end": led, "cadence": cad, **cell},
                      f, indent=1)
        print(f"LONG {cad}: ${cell['final']} dd {cell['max_dd_pct']}% "
              f"halts {len(b['halts'])}", flush=True)
    out["long_supplementary"] = {c: {k: v for k, v in long_cells[c].items()
                                     if k != "equity_curve"}
                                 for c in long_cells}
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
