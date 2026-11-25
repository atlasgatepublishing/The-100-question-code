#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — crypto-basket-pit cadence sweep.

Strategy: point-in-time crypto momentum basket (CoinMarketCap weekly-
snapshot top-20 universe, rebuilt monthly in the original; 12-1
momentum, price > 200d SMA, >=300 bars, fresh <=7d; top 5 at 20% each;
0.40%/side costs; death rule: last close held 30d then $0).

This runner:
  1) INTEGRITY — re-runs the ORIGINAL engine (engine.py = the v9 copy
     of the v4 original, simulate() verbatim) in ORIGINAL form
     (no floor) on FULL / DESIGN / VALIDATION + the FULL plain-floor
     diagnostic, and checks the published finals to the cent.
     KNOWN DIVERGENCE (documented, never silently fixed): the original
     validation run never enforced a floor — it crossed $85 and kept
     trading to $61.11. Reproduced as-is.
  2) SWEEP — DECADE road 2016-11-21 -> 2026-11-20 at 7 cadences
     (daily/weekly/biweekly/monthly/quarterly/semi-annual/annual).
     Cadence governs the PIT re-rank / rebalance dates ONLY: on each
     cadence date the universe is the most recent stored monthly PIT
     snapshot on/before that date (snapshots.json holds one snapshot
     per month, Jan 2017 -> Nov 2026 — the stored PIT record's own
     granularity; before 2017-01-01 no snapshot exists, so the pot
     sits in cash). Signals from the prior close, identical
     eligibility/ranking/costs/death rule. v9 protections per cell:
     plain -15% floor ($85) on daily closes; on halt, liquidate at
     next open (engine behaviour), 90 calendar days in cash, restart
     at the next cadence decision date with episode-2 floor -15%
     from the restart balance; second halt ends the run.
  3) PLACEBOS — 20 seeds per cell (random 5 eligible from the same
     PIT universe at the same cadence dates, same v9 wrapper).

Data: read-only shared cache backtests/v4/crypto-basket-pit-data/
(snapshots.json + per-coin price files). Nothing is written there.
Simulation only.
"""
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E   # original engine (v9 copy of v4), simulate() verbatim

OUT = HERE
CELLS = os.path.join(OUT, "cells")
os.makedirs(CELLS, exist_ok=True)

POT = 100.0
COST_RATE = E.COST_RATE
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
SPY_DECADE = 367.80          # SPEC reference, dividend-adjusted
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ---------------------------------------------------------------------------
# Fast SMA200 (the original Market.sma is O(200) per call; the daily
# cadence x 21 runs needs O(1). Values are identical: mean of the same
# forward-filled closes, None wherever the original returns None.)
# ---------------------------------------------------------------------------
def install_fast_sma(mkt):
    sma200 = {}
    for cid, ff in mkt.closes_ff.items():
        arr = [None] * len(ff)
        run, nones = 0.0, 0
        for i, v in enumerate(ff):
            if v is None:
                nones += 1
            else:
                run += v
            if i >= 200:
                old = ff[i - 200]
                if old is None:
                    nones -= 1
                else:
                    run -= old
            if i >= 199 and nones == 0:
                arr[i] = run / 200.0
        sma200[cid] = arr
    orig_sma = mkt.sma

    def fast_sma(cid, i, n):
        if n == 200:
            return sma200[cid][i]
        return orig_sma(cid, i, n)
    mkt.sma = fast_sma


# ---------------------------------------------------------------------------
# Cadence decision dates
# ---------------------------------------------------------------------------
def decision_indices(cal, i0, i1, cadence):
    idx = []
    if cadence == "daily":
        return list(range(i0, i1 + 1))
    seen = {}
    order = []
    for i in range(i0, i1 + 1):
        d = cal[i]
        dt = datetime.strptime(d, "%Y-%m-%d")
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        if key not in seen:
            seen[key] = i
            order.append(key)
    if cadence == "biweekly":
        return [seen[k] for n, k in enumerate(order) if n % 2 == 0]
    return [seen[k] for k in order]


def snap_for(snaps_keys, snaps, d):
    """Most recent stored monthly PIT snapshot on/before date d."""
    cand = None
    for k in snaps_keys:
        if k <= d:
            cand = k
        else:
            break
    if cand is None:
        return []
    return [c["cmc_id"] for c in snaps[cand]["top20"]]


# ---------------------------------------------------------------------------
# Cadence simulation — the original simulate() body with the monthly
# trigger replaced by the cadence decision set and the universe taken
# from the most recent stored snapshot. Everything else (signals,
# eligibility, ranking, 20% targets, sells-then-buys, costs, death
# rule, daily floor check with next-open liquidation) is the
# original engine's logic.
# ---------------------------------------------------------------------------
class CResult:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.equity_curve = []
        self.events = []
        self.resurrections = 0
        self.picks_log = []


def sim_cadence(mkt, snaps, snaps_keys, start_d, end_d, cadence,
                mode="ranked", seed=42, start_cash=None, floor_abs=None):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    dec = set(decision_indices(cal, i0, i1, cadence))
    floor = float(floor_abs) if floor_abs is not None else None
    cash = float(POT) if start_cash is None else float(start_cash)
    pos, entry_avg, wo_flag = {}, {}, {}
    res = CResult()
    pending_liquidation = False

    def equity_at(i):
        tot = cash
        for cid, sh in pos.items():
            v = mkt.value_close(cid, i)
            if v:
                tot += sh * v
        return tot

    def note_exit(cid, exit_px, when):
        if cid in entry_avg and entry_avg[cid] > 0:
            if exit_px <= 0.10 * entry_avg[cid]:
                res.events.append({
                    "type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                    "cmc_id": cid, "date": when,
                    "entry_px": entry_avg[cid], "exit_px": exit_px,
                    "loss_pct": round((exit_px / entry_avg[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        for cid in list(pos):
            lb = mkt.last_bar[cid][i]
            if lb >= 0 and i - lb == E.GRACE_DAYS + 1 and not wo_flag.get(cid):
                last_px = mkt.closes_ff[cid][lb]
                res.events.append({
                    "type": "write_off", "coin": mkt.reg[cid]["symbol"],
                    "cmc_id": cid, "date": d, "last_bar_date": cal[lb],
                    "last_px": last_px, "shares": pos[cid],
                    "written_off_value": round(pos[cid] * last_px, 2)})
                wo_flag[cid] = True
            if lb >= 0 and i - lb <= E.GRACE_DAYS and wo_flag.get(cid):
                wo_flag[cid] = False
                res.resurrections += 1

        if pending_liquidation:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d)
                    del pos[cid]
                    entry_avg.pop(cid, None)
                    continue
                val = pos[cid] * px
                fee = val * COST_RATE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                note_exit(cid, px, d)
                del pos[cid]
                entry_avg.pop(cid, None)
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        if i in dec and i > 0:
            universe = snap_for(snaps_keys, snaps, d)
            j = i - 1
            elig = []
            for cid in universe:
                mom = mkt.eligible(cid, j)
                if mom is not None:
                    elig.append((cid, mom))
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [cid for cid, _ in elig[:5]]
            else:
                names = sorted(cid for cid, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            res.picks_log.append({
                "date": d,
                "picks": [mkt.reg[c]["symbol"] for c in picks],
                "n_eligible": len(elig)})
            eq_open = equity_at(i)
            target_val = {cid: 0.20 * eq_open for cid in picks}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.last_bar[cid][i]
                    if lb >= 0 and i - lb > E.GRACE_DAYS:
                        note_exit(cid, 0.0, d)
                        del pos[cid]
                        entry_avg.pop(cid, None)
                    continue
                cur_val = pos[cid] * px
                want = target_val.get(cid, 0.0)
                if want <= 0.0 and cur_val <= 0.01:
                    note_exit(cid, px, d)
                    del pos[cid]
                    entry_avg.pop(cid, None)
                    continue
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[cid] -= sh
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        note_exit(cid, px, d)
                        del pos[cid]
                        entry_avg.pop(cid, None)
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None:
                    continue
                cur_val = pos.get(cid, 0.0) * px
                deficit = target_val[cid] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                sh_new = buy_val / px
                old_sh = pos.get(cid, 0.0)
                if old_sh > 0 and cid in entry_avg:
                    entry_avg[cid] = (entry_avg[cid] * old_sh
                                      + px * sh_new) / (old_sh + sh_new)
                else:
                    entry_avg[cid] = px
                pos[cid] = old_sh + sh_new

        eq_close = equity_at(i)
        res.equity_curve.append((d, eq_close))
        if floor is not None and eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v:
                        fee = sh * v * COST_RATE
                        tot += sh * v - fee
                        res.costs += fee
                        res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break
    if res.final is None:
        res.final = res.equity_curve[-1][1]
    return res


# ---------------------------------------------------------------------------
# v9 wrapper: episode 1 plain floor -> 90d cash -> restart at next
# cadence decision date -> episode 2 floor -15% from restart balance
# -> second halt ends the run.
# ---------------------------------------------------------------------------
def run_v9(mkt, snaps, snaps_keys, start_d, end_d, cadence,
           mode="ranked", seed=42):
    cal = mkt.cal
    ep1 = sim_cadence(mkt, snaps, snaps_keys, start_d, end_d, cadence,
                      mode, seed, floor_abs=85.0)
    out = {"ep1": ep1, "ep2": None, "halt_dates": [], "restart": False,
           "restart_date": None, "restart_cash": None, "second_halt": False,
           "final": ep1.final, "orders": ep1.orders, "costs": ep1.costs,
           "curve": list(ep1.equity_curve)}
    if ep1.halt_date is None:
        return out
    out["halt_dates"].append(ep1.halt_date)
    earliest = (datetime.strptime(ep1.halt_date, "%Y-%m-%d")
                + timedelta(days=90)).strftime("%Y-%m-%d")
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    dec_dates = [cal[i] for i in decision_indices(cal, i0, i1, cadence)]
    rdate = next((x for x in dec_dates if x >= earliest), None)
    if rdate is None or rdate > end_d:
        return out
    ep2 = sim_cadence(mkt, snaps, snaps_keys, rdate, end_d, cadence,
                      mode, seed, start_cash=ep1.final,
                      floor_abs=0.85 * ep1.final)
    out["ep2"] = ep2
    out["restart"] = True
    out["restart_date"] = rdate
    out["restart_cash"] = round(ep1.final, 2)
    out["final"] = ep2.final
    out["orders"] += ep2.orders
    out["costs"] += ep2.costs
    if ep2.halt_date is not None:
        out["second_halt"] = True
        out["halt_dates"].append(ep2.halt_date)
    # stitch: ep1 curve, flat cash across the 90d sit-out, ep2 curve
    curve = list(ep1.equity_curve)
    hd = ep1.halt_date
    for d in cal:
        if hd < d < rdate:
            curve.append((d, ep1.final))
    curve.extend(ep2.equity_curve)
    curve.sort(key=lambda x: x[0])
    out["curve"] = curve
    return out


def stats(curve, final, start_d, end_d):
    yrs = (datetime.strptime(end_d, "%Y-%m-%d")
           - datetime.strptime(start_d, "%Y-%m-%d")).days / 365.25
    peak, dd = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = min(dd, eq / peak - 1.0)
    cagr = (final / POT) ** (1.0 / yrs) - 1.0 if final > 0 else float("nan")
    return round(cagr * 100, 2), round(dd * 100, 2)


def main():
    snaps = E.load_snapshots()
    snaps_keys = sorted(snaps)
    reg = E.build_registry(snaps)
    mkt = E.Market(reg)
    install_fast_sma(mkt)
    published = json.load(open(os.path.join(
        E.ORIG_DIR, "crypto-basket-pit-results.json")))

    # ---------------- INTEGRITY (original form, original engine) ----
    integrity = {"status": None, "original_finals": {}, "reproduced_finals": {}}
    ok = True
    for wname, (sd, ed) in E.WINDOWS.items():
        r = E.simulate(mkt, snaps, sd, ed, "ranked", floor_variant="none")
        pub = published[f"{wname}|ranked|none"]["final"]
        integrity["original_finals"][wname.upper()] = pub
        integrity["reproduced_finals"][wname.upper()] = round(r.final, 2)
        match = abs(round(r.final, 2) - pub) < 0.011
        ok = ok and match
        print(f"integrity {wname} no-floor: published {pub} "
              f"reproduced {r.final:.2f} match={match}", flush=True)
    rpf = E.simulate(mkt, snaps, *E.WINDOWS["full"], "ranked",
                     floor_variant="plain")
    pub_pf = published["full|ranked|plainfloor"]["final"]
    integrity["original_finals"]["FULL_plainfloor_diagnostic"] = pub_pf
    integrity["reproduced_finals"]["FULL_plainfloor_diagnostic"] = round(rpf.final, 2)
    ok = ok and abs(round(rpf.final, 2) - pub_pf) < 0.011
    print(f"integrity full plainfloor diagnostic: published {pub_pf} "
          f"reproduced {rpf.final:.2f} halt={rpf.halt_date}", flush=True)
    # v9-form validation check (monthly wrapper must give $69.35)
    v9v = run_v9(mkt, snaps, snaps_keys, "2023-01-01", "2026-11-20",
                 "monthly", "ranked")
    integrity["v9_validation_check"] = {
        "final": round(v9v["final"], 2), "halt_dates": v9v["halt_dates"],
        "restart_date": v9v["restart_date"],
        "restart_cash": v9v["restart_cash"],
        "published_v9_final": 69.35}
    ok = ok and abs(round(v9v["final"], 2) - 69.35) < 0.011
    print(f"integrity v9 validation: {v9v['final']:.2f} "
          f"halts={v9v['halt_dates']} restart={v9v['restart_date']}",
          flush=True)
    integrity["status"] = "reproduced" if ok else "FAILED"
    integrity["divergence"] = (
        "The original validation run never enforced a floor: it crossed "
        "$85 and kept trading to $61.11 because no floor was applied in "
        "that window (the original's only floored run was the FULL "
        "diagnostic, which never fired). Reproduced in that original "
        "no-floor form above; the v9-form check applies the floor and "
        "gives $69.35 (halt 2026-02-03 at $84.37, restart 2026-06-01, "
        "second halt 2026-06-06).")

    # ---------------- Benchmarks on the decade road -----------------
    btc_dec = E.btc_net(mkt, DEC_START, DEC_END)
    btc_dec_dd = round(E.btc_dd(mkt, DEC_START, DEC_END) * 100, 2)
    print(f"BTC decade buy-hold: {btc_dec:.2f} dd {btc_dec_dd}", flush=True)

    # ---------------- SWEEP ------------------------------------------
    cells = {}
    for cad in CADENCES:
        run = run_v9(mkt, snaps, snaps_keys, DEC_START, DEC_END, cad,
                     "ranked")
        cagr, dd = stats(run["curve"], run["final"], DEC_START, DEC_END)
        # placebos: 20 seeds, same cadence, same v9 wrapper
        p_finals = []
        for seed in range(1, 21):
            pr = run_v9(mkt, snaps, snaps_keys, DEC_START, DEC_END, cad,
                        "placebo", seed=seed)
            p_finals.append(round(pr["final"], 2))
        beaten = sum(1 for v in p_finals if run["final"] > v)
        cell = {
            "final": round(run["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": dd, "halts": len(run["halt_dates"]),
            "halt_dates": run["halt_dates"], "restart": run["restart"],
            "restart_date": run["restart_date"],
            "restart_cash": run["restart_cash"],
            "second_halt": run["second_halt"],
            "costs": round(run["costs"], 2), "orders": run["orders"],
            "placebo_beaten": beaten, "placebo_note": None}
        cells[cad] = cell
        cj = {
            "slug": "crypto-basket-pit", "cadence": cad,
            "window": [DEC_START, DEC_END],
            "road_note": ("Decade road. Stored PIT snapshots begin "
                          "2017-01-01 (119 monthly snapshots, Jan 2017-"
                          "Nov 2026); before that date no snapshot "
                          "exists and the pot holds cash. Universe at "
                          "each cadence date = most recent stored "
                          "monthly snapshot on/before that date."),
            "final": cell["final"], "cagr_pct": cagr, "max_dd_pct": dd,
            "costs": cell["costs"], "orders": cell["orders"],
            "halts": cell["halts"], "halt_dates": run["halt_dates"],
            "restart": run["restart"], "restart_date": run["restart_date"],
            "restart_cash": run["restart_cash"],
            "second_halt": run["second_halt"],
            "benchmarks": {"btc_final": round(btc_dec, 2),
                           "btc_max_dd_pct": btc_dec_dd,
                           "spy_final": SPY_DECADE},
            "placebo_beaten": beaten,
            "placebo_finals": p_finals,
            "placebo_median": round(sorted(p_finals)[9:11].__len__() and
                                    (sorted(p_finals)[9] + sorted(p_finals)[10]) / 2, 2),
            "events": (run["ep1"].events
                       + (run["ep2"].events if run["ep2"] else [])),
            "equity_curve": [[d, round(v, 4)] for d, v in run["curve"]],
        }
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cj, f, indent=1)
        print(f"{cad}: final {cell['final']} cagr {cagr} dd {dd} "
              f"halts {cell['halts']} {run['halt_dates']} "
              f"placebo beaten {beaten}/20 "
              f"median {cj['placebo_median']}", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > SPY_DECADE
             and cells[c]["final"] > btc_dec
             and cells[c]["placebo_beaten"] is not None
             and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "crypto-basket-pit",
        "area": ("Crypto era itself — point-in-time top-20 momentum "
                 "basket on the decade road (2016-11-21 -> 2026-11-20; "
                 "PIT snapshots exist from 2017-01-01), judged vs BTC "
                 "buy-hold on the same road AND vs SPY."),
        "area_source": "SPEC W10 + CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": {
            "foreign": False,
            "note": ("Original test ran monthly selection — its native "
                     "cadence. No foreign cadence was forced.")},
        "integrity": integrity,
        "decade_spy_final": SPY_DECADE,
        "decade_btc_final": round(btc_dec, 2),
        "decade_btc_max_dd_pct": btc_dec_dd,
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "OWNS ITS GROUND",
        "verdict_change": "see RESULTS.md",
    }
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("saved results.json; money cadences:", money, flush=True)


if __name__ == "__main__":
    main()
