#!/usr/bin/env python3
"""
VM-PLUS-TREND — THE GREAT RETEST (v10), cadence sweep. Simulation only.

STRATEGY (one line): one $100 pot split 50/50 — Sleeve A = Value+Momentum
(quarterly top-5, book-to-market + 12-1 momentum average percentile rank,
2016 top-30 pond, EDGAR point-in-time) and Sleeve B = ETF Trend Sleeve
MONTHLY variant (SPY/QQQ/TLT/IEF/GLD/DBC/UUP, 3/6/12-month sign-blend
trend, inverse-vol weights capped 40%, 20% no-trade band) — with the
split rebalanced back to 50/50 in January, plain -15% pot floor in the
original; v9 protection (floor + 90-day sit-out + one restart) in v10.

CADENCE TREATMENT (stated once, applied uniformly to every cell):
  cadence governs (a) the V+M sleeve's re-pick / selection dates and
  (b) the blend's 50/50 split-rebalance rhythm (rebalance on every
  cadence date after inception, charged at the published convention:
  0.10% sell + 0.10% buy on the transferred value + $0.01 x 5 sell
  orders). The trend sleeve's own monthly trend checks STAY MONTHLY as
  published inside every cell — they do not follow cadence.
  Native cadence (SPEC grid, W1): quarterly. Original test cadence:
  quarterly V+M picks + January-only split rebalance, so the quarterly
  sweep cell differs from the original form ONLY in the split-rebalance
  rhythm (quarterly instead of January-only); the original form itself
  is reproduced exactly in the INTEGRITY section below.

INTEGRITY TARGETS (original published finals, original form):
  - blend CONT 2019-01-02 -> 2026-11-20: $320.97, max DD -18.80%
  - blend VAL  2023-01-03 -> 2026-11-20: $192.36, max DD -11.74%
  - V+M parent $100 plain floor: CONT $544.47, VAL $288.05
  - ETF trend monthly as-proven $100 decade: $194.61
  - v9 fold-2020: episode-1 $83.51 (halt 2020-03-20) -> v9 final $93.53

SWEEP: DECADE 2016-11-21 -> 2026-11-20 x 7 cadences, $100/cell,
program costs, v9 protections at the whole-pot level (the v9 folder's
blend_v9 generalized to cadence selection/rebalance dates), 20-seed
placebos per cell (V+M sleeve draws 5 random names from the scored
pool each selection; trend sleeve unchanged; same blend + v9 rules).

DATA (read-only shared caches): EDGAR companyfacts + Yahoo bars under
backtests/v4/data (the champion's caches; price history starts
2017-06-01, so the pot's first curve date is 2017-06-01 and the V+M
sleeve holds cash until 12-1 momentum history exists, ~mid-2018 — the
identical constraint the champion's own $65.89 decade run ran under);
ETF bars under backtests/v3/data_etf. Nothing is written outside this
folder.
"""

import bisect
import importlib.util
import json
import math
import os
import random
from datetime import date as _date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.abspath(os.path.join(HERE, "..", ".."))
DS, DE = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vm = _load("vm_plainfloor_v10",
           os.path.join(BT, "v4", "value-momentum-plainfloor.py"))
etf = _load("etf_trend_monthly_v10",
            os.path.join(BT, "v3", "etf-trend-sleeve-monthly.py"))
v9 = _load("vm_plus_trend_v9",
           os.path.join(BT, "v9-muse-rules", "vm-plus-trend",
                        "vm-plus-trend-v9.py"))


# ---------------------------------------------------------------- helpers
def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst


def cagr_pct(final, start_cash, sd, ed):
    yrs = (datetime.strptime(ed, "%Y-%m-%d")
           - datetime.strptime(sd, "%Y-%m-%d")).days / 365.25
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100.0, 2)


# ------------------------------------------------- cadence selection dates
def cadence_dates(pb, cadence, start, end):
    """Selection dates per the SPEC's uniform definition: first trading
    day of each cadence period inside [start, end] (daily = every
    trading day; quarterly = the engine's own quarter_selection_dates,
    verbatim)."""
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return vm.quarter_selection_dates(pb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = _date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            iso = _date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        for d in days:
            if d[:7] not in seen:
                seen.add(d[:7])
                out.append(d)
        return out
    if cadence == "semiannual":
        for d in days:
            if d[5:7] in ("01", "07"):
                key = (d[:4], d[5:7])
                if key not in seen:
                    seen.add(key)
                    out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            if d[5:7] == "01" and d[:4] not in seen:
                seen.add(d[:4])
                out.append(d)
        return out
    raise ValueError(cadence)


# --------------------------------------- point-in-time lookup (exact copy
# of vm.pit_value semantics, indexed + memoized; equivalence self-checked)
class PitBook:
    def __init__(self):
        self._idx = {}
        self._memo = {}

    def _index(self, rows):
        key = id(rows)
        if key not in self._idx:
            srt = sorted(rows, key=lambda r: r[0])
            self._idx[key] = ([r[0] for r in srt], srt)
        return self._idx[key]

    def value(self, rows, asof, max_age_days=548):
        mkey = (id(rows), asof)
        if mkey in self._memo:
            return self._memo[mkey]
        fileds, srt = self._index(rows)
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        cutoff = _date.fromordinal(
            _date(ay, am, ad).toordinal() - max_age_days).isoformat()
        lo = bisect.bisect_left(fileds, cutoff)
        hi = bisect.bisect_left(fileds, asof)
        best = None
        for r in srt[lo:hi]:
            k = (r[0], r[3], r[1])          # (filed, prio, end) — as orig
            if best is None or k > best[0]:
                best = (k, (r[0], r[1], r[2]))
        out = best[1] if best else None
        self._memo[mkey] = out
        return out


PIT = PitBook()


# --------------------------------- cadence V+M sleeve (vm.run_pot copied;
# only the selection calendar and lookup speed differ — mechanics, scoring,
# costs, execution and end-liquidation are the original's, verified against
# the original engine at quarterly cadence before the sweep runs)
class CadenceBook:
    """Bisect close_on_or_before over the engine's own PriceBook bars."""

    def __init__(self, pb):
        self.pb = pb
        self.dates = pb.dates
        self._dl = {t: [b["d"] for b in bl] for t, bl in pb.bars.items()}
        self._pos = {t: {d: i for i, d in enumerate(ds)}
                     for t, ds in self._dl.items()}

    def close_before(self, t, d):
        ds = self._dl.get(t)
        if not ds:
            return None
        i = bisect.bisect_right(ds, d) - 1
        if i < 0:
            return None
        return self.pb.bars[t][i]["c"]


def run_vm_cadence(cb, equity_rows, shares_rows, start, end, start_cash,
                   sel_dates, placebo_rng=None):
    pb = cb.pb
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = cb.close_before(t, d)
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

    for d in days:
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = {}
            for t in vm.UNIVERSE:
                be = PIT.value(equity_rows.get(t, []), d)
                so = PIT.value(shares_rows.get(t, []), d)
                px = cb.close_before(t, d)
                if (be is None or so is None or px is None
                        or so[2] <= 0 or be[2] is None):
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                didx = cb._pos.get(t, {}).get(d)
                if didx is None or didx < 253:
                    continue
                bl = pb.bars.get(t, [])
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 5:
                vr = vm.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = vm.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        curve.append((d, portfolio_close(d)))
    last = days[-1]
    for t in list(positions):
        c_ = cb.close_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "curve": curve, "halted": None}


def etf_sleeve(sd, ed, cash):
    return etf.simulate(sd, ed, start_cash=cash, floor0=0.0, ladder=())


# --------------------------------------- cadence blend (v9 blend_curves /
# blend_v9 generalized: rebalance dates and restart selection come from
# the cadence calendar; liquidation, 90-day sit-out, episode-2 floor and
# transfer-cost convention are the published ones, unchanged)
def blend_curves_cad(curveA, curveB, pot0, floor, rebal_dates):
    A = dict(curveA)
    B = dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    rebal = {d for d in rebal_dates if first < d <= last}
    scaleA = scaleB = 1.0
    lastA = lastB = None
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        va = scaleA * lastA
        vb = scaleB * lastB
        tot = va + vb
        if d in rebal:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            rebalances.append({"date": d, "sleeveA_before": round(va, 2),
                               "sleeveB_before": round(vb, 2),
                               "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                na = A.get(nd, lastA)
                nb = B.get(nd, lastB)
                nxt = scaleA * na + scaleB * nb
                final = nxt * (1 - 0.001) - 0.10
            else:
                final = tot * (1 - 0.001) - 0.10
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


def blend_v9_cadence(cb, eq_rows, sh_rows, sel_all, start, end,
                     start_cash=100.0, rng=None):
    """One window under v9 protection at a given cadence. sel_all = the
    cadence's selection dates over the whole sweep window (restart picks
    the first of them on/after liquidation + 90 days)."""
    floor1 = round(0.85 * start_cash, 2)
    sel1 = [d for d in sel_all if start <= d <= end]
    vms = run_vm_cadence(cb, eq_rows, sh_rows, start, end,
                         start_cash / 2.0, sel1, placebo_rng=rng)
    etfs = etf_sleeve(start, end, start_cash / 2.0)
    curve1, info1 = blend_curves_cad(vms["curve"], etfs["curve"],
                                     start_cash, floor1, sel1)
    out = {"final": info1["final"], "curve": list(curve1),
           "halts": [], "restarts": [], "second_halt": None,
           "episodes": 1,
           "costs_sleeves": vms["costs"] + etfs["costs"],
           "costs_transfers": info1["transfer_costs"],
           "orders": len(vms["trades"]) + etfs["orders"]
                     + len(info1["rebalances"])}
    if info1["halt"] is None:
        return out
    all_dates = sorted(set(d for d, _ in vms["curve"])
                       | set(d for d, _ in etfs["curve"]))
    later = [d for d in all_dates if d > info1["halt"]]
    if not later:                       # halted on the final date: no
        out["halts"].append({"episode": 1, "signal_date": info1["halt"],
                             "liquidation_date": info1["halt"],
                             "proceeds": round(info1["final"], 2)})
        return out                        # liquidation date exists
    liq_date = later[0]
    cash = info1["final"]
    out["halts"].append({"episode": 1, "signal_date": info1["halt"],
                         "liquidation_date": liq_date,
                         "proceeds": round(cash, 2)})
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_all:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90 and cand <= end:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in all_dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": info1["halt"], "liquidation_date": liq_date,
        "halt_signal_close": round(dict(curve1)[info1["halt"]], 2),
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    sel2 = [d for d in sel_all if restart <= d <= end]
    vms2 = run_vm_cadence(cb, eq_rows, sh_rows, restart, end,
                          cash / 2.0, sel2, placebo_rng=rng)
    etfs2 = etf_sleeve(restart, end, cash / 2.0)
    curve2, info2 = blend_curves_cad(vms2["curve"], etfs2["curve"],
                                     cash, floor2, sel2)
    out["episodes"] = 2
    out["final"] = info2["final"]
    out["curve"] += list(curve2)
    out["costs_sleeves"] += vms2["costs"] + etfs2["costs"]
    out["costs_transfers"] += info2["transfer_costs"]
    out["orders"] += (len(vms2["trades"]) + etfs2["orders"]
                      + len(info2["rebalances"]))
    if info2["halt"] is not None:
        out["second_halt"] = {"signal_date": info2["halt"],
                              "liquidation_final": round(info2["final"], 2),
                              "floor_in_effect": floor2}
        out["halts"].append({"episode": 2, "signal_date": info2["halt"],
                             "liquidation_date": None,
                             "proceeds": round(info2["final"], 2)})
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------------- main
def main():
    print("loading value+momentum book (shared caches, read-only)...",
          flush=True)
    pb, eq_rows, sh_rows = v9.build_vm_book()
    cb = CadenceBook(pb)

    # ---- self-checks: indexed PIT == engine PIT; cadence engine at
    # quarterly == original engine (CONT $50 sleeve curve + final)
    rng = random.Random(99)
    pit_bad = 0
    tickers = list(vm.UNIVERSE)
    sample_dates = [d for d in pb.dates if "2018-01-01" <= d <= DE]
    for _ in range(300):
        t = rng.choice(tickers)
        d = rng.choice(sample_dates)
        for rows in (eq_rows[t], sh_rows[t]):
            if vm.pit_value(rows, d) != PIT.value(rows, d):
                pit_bad += 1
    print(f"PIT equivalence: {pit_bad} mismatches / 600", flush=True)
    assert pit_bad == 0

    orig50 = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-01", DE, 50.0,
                        0.0, [], quiet=True)
    q_sel = cadence_dates(pb, "quarterly", "2019-01-01", DE)
    mine50 = run_vm_cadence(cb, eq_rows, sh_rows, "2019-01-01", DE, 50.0,
                            q_sel)
    eng_diff = abs(orig50["final"] - mine50["final"])
    curve_same = orig50["curve"] == mine50["curve"]
    print(f"engine equivalence (quarterly, CONT $50 sleeve): original "
          f"${orig50['final']:.2f} vs cadence ${mine50['final']:.2f} "
          f"(diff {eng_diff:.4f}, curves identical: {curve_same})",
          flush=True)
    assert eng_diff < 0.01 and curve_same

    # ---- INTEGRITY: original published finals, original form
    print("INTEGRITY: reproducing original published finals...", flush=True)
    vm_cont = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-01", DE, 100.0,
                         85.0, [], quiet=True)
    vm_val = vm.run_pot(pb, eq_rows, sh_rows, "2023-01-01", DE, 100.0,
                        85.0, [], quiet=True)
    etf_dec = etf.simulate(DS, DE)      # as-proven: floor 85 + ladder
    integ = {"vm_parent_cont": round(vm_cont["final"], 2),
             "vm_parent_val": round(vm_val["final"], 2),
             "etf_parent_decade_asproven": round(etf_dec["final"], 2)}
    print(f"  V+M parent: CONT ${integ['vm_parent_cont']} (pub 544.47), "
          f"VAL ${integ['vm_parent_val']} (pub 288.05)", flush=True)
    print(f"  ETF parent decade as-proven: "
          f"${integ['etf_parent_decade_asproven']} (pub 194.61)",
          flush=True)
    assert abs(integ["vm_parent_cont"] - 544.47) < 0.05
    assert abs(integ["vm_parent_val"] - 288.05) < 0.05
    assert abs(integ["etf_parent_decade_asproven"] - 194.61) < 0.05

    blend_orig = {}
    for wname, ws in (("continuous", "2019-01-01"),
                      ("validation", "2023-01-01")):
        vs = v9.vm_sleeve(pb, eq_rows, sh_rows, ws, DE, cash=50.0)
        es = v9.etf_sleeve(ws, DE, cash=50.0)
        curve, info = v9.blend_curves(vs["curve"], es["curve"],
                                      pot0=100.0, floor=85.0)
        blend_orig[wname] = {"final": round(info["final"], 2),
                             "max_dd_pct": round(info["max_dd"] * 100, 2),
                             "halt": info["halt"],
                             "curve": curve}
        print(f"  blend {wname}: ${blend_orig[wname]['final']} "
              f"maxDD {blend_orig[wname]['max_dd_pct']}% "
              f"halt={info['halt']}", flush=True)
    assert abs(blend_orig["continuous"]["final"] - 320.97) < 0.05
    assert abs(blend_orig["validation"]["final"] - 192.36) < 0.05
    assert abs(blend_orig["continuous"]["max_dd_pct"] - (-18.80)) < 0.05
    fold = v9.blend_v9(pb, eq_rows, sh_rows, "2020-01-01", "2020-12-31",
                       100.0)
    integ.update({
        "blend_cont": blend_orig["continuous"]["final"],
        "blend_cont_max_dd_pct": blend_orig["continuous"]["max_dd_pct"],
        "blend_val": blend_orig["validation"]["final"],
        "blend_val_max_dd_pct": blend_orig["validation"]["max_dd_pct"],
        "fold2020_ep1": round(fold["ep1_final"], 2),
        "fold2020_v9_final": round(fold["final"], 2)})
    print(f"  v9 fold-2020: ep1 ${integ['fold2020_ep1']} (pub 83.51) -> "
          f"v9 ${integ['fold2020_v9_final']} (pub 93.53)", flush=True)
    assert abs(integ["fold2020_ep1"] - 83.51) < 0.05
    assert abs(integ["fold2020_v9_final"] - 93.53) < 0.05
    integrity = {
        "status": "reproduced",
        "original_finals": {"blend_continuous": 320.97,
                            "blend_continuous_max_dd_pct": -18.80,
                            "blend_validation": 192.36,
                            "blend_validation_max_dd_pct": -11.74,
                            "vm_parent_continuous": 544.47,
                            "vm_parent_validation": 288.05,
                            "etf_parent_decade_asproven": 194.61,
                            "fold2020_ep1_his_rules": 83.51,
                            "fold2020_v9": 93.53},
        "reproduced_finals": integ,
        "notes": ("Original form = quarterly V+M picks, monthly trend "
                  "checks, January-only split rebalance, pot-level "
                  "floor; reproduced through this script's plumbing "
                  "(parents' own engines) to the cent. Cadence-engine "
                  "equivalence at quarterly verified against the "
                  "original engine (identical $50 CONT sleeve curve).")}

    # ---- SWEEP: DECADE x 7 cadences
    spy_dec = 367.80                    # SPEC reference, dividend-adj
    cells = {}
    summary = {}
    for cad in CADENCES:
        sel_all = cadence_dates(pb, cad, DS, DE)
        r = blend_v9_cadence(cb, eq_rows, sh_rows, sel_all, DS, DE)
        dd = max_dd(r["curve"]) * 100.0
        twins = []
        for seed in PLACEBO_SEEDS:
            prng = random.Random(seed)
            pr = blend_v9_cadence(cb, eq_rows, sh_rows, sel_all, DS, DE,
                                  rng=prng)
            twins.append({"seed": seed, "final": round(pr["final"], 2)})
        beaten = sum(1 for t in twins if t["final"] < r["final"])
        cell = {
            "cadence": cad, "window": [DS, DE],
            "effective_first_curve_date": r["curve"][0][0],
            "n_selection_dates": len(sel_all),
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], 100.0, DS, DE),
            "max_dd_pct": round(dd, 2),
            "costs": round(r["costs_sleeves"] + r["costs_transfers"], 2),
            "costs_sleeves": round(r["costs_sleeves"], 2),
            "costs_transfers": round(r["costs_transfers"], 2),
            "orders": r["orders"],
            "halts": r["halts"], "restarts": r["restarts"],
            "second_halt": r["second_halt"], "episodes": r["episodes"],
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "placebo_finals": twins,
            "placebo_beaten": beaten}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        summary[cad] = {k: cell[k] for k in
                        ("final", "cagr_pct", "max_dd_pct", "costs",
                         "orders", "placebo_beaten")}
        summary[cad]["halts"] = len(r["halts"])
        summary[cad]["restart"] = bool(r["restarts"])
        summary[cad]["second_halt"] = r["second_halt"] is not None
        print(f"{cad:11s} final=${cell['final']:>9,.2f} "
              f"CAGR={cell['cagr_pct']:>6}% DD={cell['max_dd_pct']:>7}% "
              f"costs=${cell['costs']:>7,.2f} orders={cell['orders']:>5} "
              f"halts={len(r['halts'])} placebo beaten {beaten}/20",
              flush=True)

    money = [c for c in CADENCES
             if summary[c]["final"] > spy_dec
             and summary[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "vm-plus-trend",
        "area": ("long-horizon quarterly value/momentum holding on the "
                 "pond, blended 50/50 with a defensive ETF trend sleeve "
                 "(W1 family: the champion's road)"),
        "area_source": "SPEC W1 assignment + task brief",
        "native_cadence": "quarterly",
        "cadence": "quarterly",
        "original_cadence_foreign": False,
        "cadence_treatment": (
            "Cadence governs the V+M sleeve's re-pick dates AND the "
            "blend's 50/50 split-rebalance rhythm (rebalance on every "
            "cadence date after inception, published transfer-cost "
            "convention). The trend sleeve's monthly trend checks stay "
            "monthly as published inside every cell."),
        "integrity": integrity,
        "decade_spy_final": spy_dec,
        "decade_parents": {
            "champion_vm_decade": {
                "final": 65.89,
                "note": ("lazy-quarterly test, same plumbing family; "
                         "two halts — halted 2018-12-21, restarted "
                         "2019-04-01, second halt 2020-03-20 ended the "
                         "run at $65.89. Caveat: the decade is the "
                         "champion's worst road, not its crown.")},
            "etf_trend_sleeve_decade": {
                "final": 194.61, "max_dd_pct": -13.73,
                "note": ("its own v3 test, as-proven $100 (floor + "
                         "ladder), 2016-11-21 -> 2026-11-20")}},
        "cells": summary,
        "money_cadences": money,
        "verdict_area": None,           # filled by RESULTS.md author pass
        "verdict_change": None}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("saved cells/*.json + results.json", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
