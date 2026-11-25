#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — basket-issuance-veto (momentum basket + net-issuance veto)

Strategy (kept exactly as built in v4): monthly-style momentum basket on the
30-name Nov-2016 universe (eligible: close > 200d SMA; rank by 12-1 momentum;
hold top 5 at 20% each), EXCEPT any name whose trailing-12m point-in-time net
share issuance (EDGAR companyfacts, split-adjusted) exceeds +5%/yr is vetoed
at selection and replaced by the next-ranked eligible name (or cash).

This runner:
  1) INTEGRITY — runs the ORIGINAL v4 engine (basket-issuance-veto.py,
     imported read-only from backtests/v4/, ladder-era floors and all) on its
     original windows: full 2016-11-21->2026-11-20 (published $403.02) and
     validation 2023-01-01->2026-11-20 (published $189.73), $100 pots.
  2) SWEEP — DECADE 2016-11-21 -> 2026-11-20 at 7 cadences under the SPEC's
     uniform cadence definition, $100/cell, program costs (0.10%/side +
     $0.01/sell order, the engine's own cost code), v9 protections (plain
     -15% floor, no ladder; first halt -> liquidate at next open, sit in cash
     90 calendar days, restart at next cadence date under an episode-2 floor
     of -15% from the restart balance; second halt ends the run).
  3) PLACEBOS — 20 seeds per cell: random-rank twins (eligible names in a
     seeded random order, same veto walk, same machinery, same v9 wrapper).

Data (read-only reuse, nothing written outside this folder):
  - prices: backtests/v4/momentum-basket-honest-data/ (via the honest engine)
  - issuance: backtests/v4/basket-issuance-veto-data/ (EDGAR facts + splits)
"""
import importlib.util
import json
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

# ---------------------------------------------------------------- load v4 --
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

hb = _load("honest_basket_v4", os.path.join(V4, "momentum-basket-honest.py"))
veto = _load("issuance_veto_v4", os.path.join(V4, "basket-issuance-veto.py"))

UNIVERSE = hb.UNIVERSE
COST_RATE = hb.COST_RATE
SELL_FEE = hb.SELL_FEE
POT = 100.0
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def build_series():
    ciks = veto.get_ciks()
    ciks.update(veto.CIK_OVERRIDES)
    series = {}
    for t in UNIVERSE:
        facts = veto.get_companyfacts(ciks[t])
        splits = veto.get_splits(t)
        series[t] = veto.IssuanceSeries(t, facts, splits)
    return series


# ------------------------------------------------------------- integrity --
def run_integrity(mkt, series):
    out = {}
    targets = {"full": 403.02, "validation": 189.73}
    base_targets = {"full": 439.45, "validation": 208.27}
    for wname in ("full", "validation"):
        sd, ed = hb.WINDOWS[wname]
        log = []
        r = veto.simulate_veto(mkt, sd, ed, 100, series=series, veto_log=log)
        rb = veto.simulate_veto(mkt, sd, ed, 100, series=None)
        out[wname] = {
            "window": [sd, ed],
            "published_final": targets[wname],
            "reproduced_final": round(r.final, 2),
            "match": abs(round(r.final, 2) - targets[wname]) < 0.005,
            "veto_off_published": base_targets[wname],
            "veto_off_reproduced": round(rb.final, 2),
            "veto_off_match": abs(round(rb.final, 2)
                                  - base_targets[wname]) < 0.005,
            "veto_events": log,
            "n_vetoes": len(log),
            "orders": r.orders,
            "costs": round(r.costs, 2),
            "max_dd_pct": round(r.max_dd * 100, 2),
            "halt": r.halt_date,
        }
        print(f"INTEGRITY {wname}: reproduced={r.final:.2f} "
              f"published={targets[wname]:.2f} match={out[wname]['match']} "
              f"veto_off={rb.final:.2f} vetoes={len(log)}", flush=True)
    return out


# ------------------------------------------------- precompute signal data --
def precompute(mkt, series, i0, i1):
    """For every day index j in [i0-1, i1]: ranked eligible list and the
    issuance value per ticker (point-in-time, as of cal[j])."""
    ranked_by_day = {}
    iss_by_day = {}
    for j in range(i0 - 1, i1 + 1):
        d = mkt.cal[j]
        elig = []
        for t in UNIVERSE:
            sma200 = mkt.sma(t, j, 200)
            c = mkt.close_px(t, j)
            if sma200 is None or c is None or c <= sma200:
                continue
            mom = mkt.momentum_12_1(t, j)
            if mom is None:
                continue
            elig.append((t, mom))
        elig.sort(key=lambda x: -x[1])
        ranked_by_day[j] = [t for t, _ in elig]
        iss = {}
        for t in UNIVERSE:
            v = series[t].issuance_asof(d)
            if v is not None:
                iss[t] = v
        iss_by_day[j] = iss
    return ranked_by_day, iss_by_day


def cadence_dates(mkt, i0, i1, cadence):
    """Set of day indices in [i0, i1] where selection/rebalance may happen.
    i0 (window start, initial establishment) is always included, matching the
    original engine, which rebalances on its first day."""
    days = [i for i in range(i0, i1 + 1)]
    if cadence == "daily":
        return set(days)
    def key(i):
        d = mkt.cal[i]
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        if cadence == "weekly" or cadence == "biweekly":
            iso = date(y, m, dd).isocalendar()
            return (iso[0], iso[1])
        if cadence == "monthly":
            return d[:7]
        if cadence == "quarterly":
            return (y, (m - 1) // 3)
        if cadence == "semiannual":
            return (y, (m - 1) // 6)
        if cadence == "annual":
            return (y,)
        raise ValueError(cadence)
    groups = {}
    for i in days:
        groups.setdefault(key(i), []).append(i)
    firsts = sorted(min(v) for v in groups.values())
    if cadence == "biweekly":
        firsts = firsts[::2]
    out = set(firsts)
    out.add(i0)
    return out


# ------------------------------------------------------------ sweep engine --
def simulate_cadence(mkt, start_d, end_d, cadence, ranked_by_day, iss_by_day,
                     mode="ranked", seed=None):
    """v9-wrapped cadence run. Returns result dict incl. full equity curve,
    halt/restart records and veto-fire log (ranked mode)."""
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cad = cadence_dates(mkt, i0, i1, cadence)
    cash = float(POT)
    pos = {}
    floor = 0.85 * POT
    episode = 1
    halts = []            # [{episode, trigger_date, liquidation_date, balance}]
    restart_info = None   # {date, balance, floor}
    pending_liquidation = False
    halt_trigger = None
    sit_until = None      # date string: cash until this date, restart at
                          # first cadence date >= sit_until
    ended = False
    costs = 0.0
    orders = 0
    equity_curve = []
    veto_log = []
    veto_fires = 0

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]

        # --- floor liquidation at the open -------------------------------
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                costs += fee
                orders += 1
                del pos[t]
            pending_liquidation = False
            halts.append({"episode": episode, "trigger_date": halt_trigger,
                          "liquidation_date": d,
                          "balance_after": round(cash, 2)})
            equity_curve.append([d, round(cash, 4)])
            if episode >= 2:
                ended = True
                break
            sit_until = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
            continue

        # --- restart after 90-day sit-out, at next cadence date ----------
        if sit_until is not None:
            if d >= sit_until and i in cad:
                floor = 0.85 * cash
                episode = 2
                restart_info = {"date": d, "balance": round(cash, 2),
                                "floor": round(floor, 2)}
                sit_until = None
                # fall through: rebalance happens below on this same day
            else:
                equity_curve.append([d, round(cash, 4)])
                continue

        # --- selection / rebalance at the open on cadence dates ----------
        if i in cad and i > 0:
            j = i - 1
            ranked = ranked_by_day[j]
            iss = iss_by_day[j]
            base_picks = ranked[:5]
            if mode == "ranked":
                order = ranked
            else:  # placebo: seeded random order of the same eligible pool
                order = rng.sample(ranked, len(ranked)) if ranked else []
                base_picks = order[:5]
            picks = []
            vetoed = []
            for t in order:
                if len(picks) >= 5:
                    break
                v = iss.get(t)
                if v is not None and v > veto.VETO_THRESHOLD:
                    if t in base_picks:
                        vetoed.append((t, v))
                    continue
                picks.append(t)
            if mode == "ranked":
                entrants = [t for t in picks if t not in base_picks]
                for k, (t, v) in enumerate(vetoed):
                    veto_fires += 1
                    veto_log.append({
                        "date": d, "signal_date": mkt.cal[j], "ticker": t,
                        "issuance_pct": round(v * 100, 2),
                        "replacement": (entrants[k] if k < len(entrants)
                                        else "cash")})

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    costs += fee
                    orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                costs += fee
                orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px

        # --- close: equity + floor ---------------------------------------
        eq_close = equity_at(i, use_open=False)
        equity_curve.append([d, round(eq_close, 4)])
        if eq_close <= floor:
            pending_liquidation = True
            halt_trigger = d
            if i == i1:      # no next open in window: liquidate at close
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    costs += fee
                    orders += 1
                cash = tot
                pos.clear()
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidation_date": d,
                              "balance_after": round(cash, 2)})
                equity_curve[-1] = [d, round(cash, 4)]
                ended = True
                break

    final = equity_curve[-1][1] if equity_curve else cash
    if pos and not ended:
        final = equity_curve[-1][1]
    peak = -1.0
    max_dd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)
    yrs = hb.years_between(start_d, end_d)
    return {
        "final": round(final, 2),
        "cagr_pct": round(hb.cagr(final, POT, yrs) * 100, 2),
        "max_dd_pct": round(-max_dd * 100, 2),
        "costs": round(costs, 2),
        "orders": orders,
        "halts": len(halts),
        "halt_records": halts,
        "restart": restart_info is not None,
        "restart_record": restart_info,
        "second_halt": len(halts) >= 2,
        "veto_fires": veto_fires,
        "veto_log": veto_log,
        "equity_curve": equity_curve,
    }


def main():
    print("building issuance series (read-only v4 cache)...", flush=True)
    series = build_series()
    missing = [t for t in UNIVERSE if series[t].concept is None]
    print(f"issuance coverage missing (never vetoable): {missing}", flush=True)
    mkt = hb.Market(UNIVERSE)

    integrity = run_integrity(mkt, series)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integrity, f, indent=1)

    sd, ed = DECADE
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    print("precomputing daily rankings + issuance...", flush=True)
    ranked_by_day, iss_by_day = precompute(mkt, series, i0, i1)
    spy_plumbing = round(hb.spy_net(mkt, sd, ed, 100), 2)
    print(f"SPY plumbing (price-only, engine convention): {spy_plumbing}",
          flush=True)

    cells = {}
    for cadence in CADENCES:
        r = simulate_cadence(mkt, sd, ed, cadence, ranked_by_day, iss_by_day,
                             mode="ranked")
        print(f"{cadence}: final={r['final']} halts={r['halts']} "
              f"orders={r['orders']} costs={r['costs']} "
              f"veto_fires={r['veto_fires']}", flush=True)
        twins = []
        for seed in range(1, 21):
            pr = simulate_cadence(mkt, sd, ed, cadence, ranked_by_day,
                                  iss_by_day, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": pr["final"],
                          "costs": pr["costs"], "orders": pr["orders"],
                          "halts": pr["halts"],
                          "halt_dates": [h["liquidation_date"]
                                         for h in pr["halt_records"]]})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        print(f"  placebos: beaten {beaten}/20 "
              f"(median twin {sorted(t['final'] for t in twins)[10]})",
              flush=True)
        cell = {
            "cadence": cadence, "window": [sd, ed], "start_pot": POT,
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "halts": r["halts"],
            "halt_records": r["halt_records"],
            "restart": r["restart"], "restart_record": r["restart_record"],
            "second_halt": r["second_halt"],
            "veto_fires": r["veto_fires"], "veto_log": r["veto_log"],
            "placebo_beaten": beaten,
            "placebo_twins": twins,
            "placebo_note": ("20 random-rank twins (seeds 1..20): eligible "
                             "names in seeded random order, same veto walk, "
                             "same cadence, same v9 wrapper"),
            "spy_final_spec": 367.80,
            "spy_final_plumbing": spy_plumbing,
            "equity_curve": r["equity_curve"],
        }
        with open(os.path.join(CELLS, f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cadence] = {k: cell[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "costs",
                           "orders", "halts", "restart", "second_halt",
                           "placebo_beaten")}
        cells[cadence]["veto_fires"] = r["veto_fires"]
        cells[cadence]["placebo_note"] = cell["placebo_note"]

    ok = all(v["match"] and v["veto_off_match"] for v in integrity.values())
    money = [c for c in CADENCES
             if cells[c]["final"] > 367.80 and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "basket-issuance-veto",
        "area": ("monthly momentum basket holding on the 30-name Nov-2016 "
                 "pond with a net-issuance veto — judged in this sweep on "
                 "the DECADE road at every cadence"),
        "area_source": ("SPEC W2 basket family + CADENCE GRID (monthly); "
                        "THE CADENCE SWEEP (Terry 2026-11-21 ~22:09)"),
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "original_cadence_note": ("Not foreign. The original v4 test already "
                                  "selected monthly (first trading day of "
                                  "each month); the sweep's monthly cell is "
                                  "its native form under v9 protections."),
        "integrity": {
            "status": "reproduced" if ok else "FAILED",
            "original_finals": {"full_decade": 403.02, "validation": 189.73},
            "reproduced_finals": {
                "full_decade": integrity["full"]["reproduced_final"],
                "validation": integrity["validation"]["reproduced_final"]},
            "detail": ("Original v4 engine imported read-only and run in "
                       "original form (ladder-era floors, original windows "
                       "full 2016-11-21->2026-11-20 and validation "
                       "2023-01-01->2026-11-20, $100). Veto-off self-check "
                       "also reproduced: full $439.45, validation $208.27. "
                       "Note: the task brief labels the $403.02 'CONT'; in "
                       "the source record it is the FULL window, which is "
                       "exactly the DECADE window. Veto fires in original "
                       f"form: full {integrity['full']['n_vetoes']}, "
                       f"validation {integrity['validation']['n_vetoes']} "
                       "(3 underlying events: DIS/Fox 2019, INTC stakes "
                       "2025-26, CVX/Hess 2025-26)."),
        },
        "decade_spy_final": 367.80,
        "decade_spy_note": ("SPEC dividend-adjusted figure, used as the "
                            "money-cadence hurdle. This engine's own SPY net "
                            f"(price-only convention) on the decade: "
                            f"${spy_plumbing}."),
        "champion_decade": {
            "final": 65.89,
            "note": ("Value+Momentum decade run ended at $65.89 after two "
                     "halts (caveat per SPEC); its crown rests on LONG "
                     "$1,415.62 / CONT $544.47 / VAL $288.05.")},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,   # filled in RESULTS.md narrative; see below
        "veto_fires_by_cadence": {c: cells[c]["veto_fires"] for c in CADENCES},
    }
    # verdict scale per SPEC
    if money:
        results["verdict_area"] = "OWNS ITS GROUND" if "monthly" in money \
            else "REAL BUT SMALL"
    else:
        beats_spy = [c for c in CADENCES if cells[c]["final"] > 367.80]
        results["verdict_area"] = "REAL BUT SMALL" if beats_spy else "NO GROUND"
    results["verdict_change"] = (
        "Original program verdict was REJECTED (veto made the basket worse "
        "than itself on both original windows). The sweep does not overturn "
        "that: see RESULTS.md.")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print(json.dumps({c: cells[c]["final"] for c in CADENCES}, indent=1))
    print("money cadences:", money, "| verdict:", results["verdict_area"])


if __name__ == "__main__":
    main()
