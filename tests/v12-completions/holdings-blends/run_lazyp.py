#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — combo-vm-lazyp (V+M x Lazy Prices 50/50).
Simulation only.

Construction (the family's own, unchanged): the two sleeves run as
standalone pots at half the pot each with their floors disabled, and
the original blend_curves combines the two sleeve curves with 50/50
resets at the quarterly selection dates and one plain -15% floor on
the combined pot. At grid count N, EACH sleeve holds its own top-N.
Native count = 5 per sleeve (10 effective). Cadence = quarterly
(native) throughout — the sweep variable is COUNT.

Forms: house = v9 wrapper at pot level (episode 1 plain -15% floor;
first halt -> liquidate, 90 days cash, restart at next quarterly
selection date under -15% from restart balance; second halt ends);
native = the original single-episode plain-floor form (run_combo's
construction). Roads: DECADE 2016-11-21, CONT 2019-01-02,
VAL 2023-01-03 -> 2026-11-20 on the family's own books (v4 cached
bars from 2017-06-01 — the documented effective-road artifact of
this plumbing). Program costs. Placebos: 20 seeds per cell,
vm_rng = lz_rng = Random(seed) (the family's own convention).

Sleeve engines: VM = verbatim copy of v4 value-momentum-plainfloor
run_pot with the hardcoded top-5 parameterized (vm_run_pot_n below);
LZ = the parameterized copy of the gap-a5 engine saved by the
holdings-lazy-prices worker (engine_n.run_pot_n). Speed shims
(bisect book lookups + indexed pit_value) are the v10 sweep's own,
proven identical there and re-proven here by the integrity gate:
N=5 house CONT $540.72 / VAL $312.55 / DECADE $514.06 must reproduce
to the cent before any sweep number is taken.
"""
import bisect
import importlib.util
import json
import os
import random
import sys
import time
from bisect import bisect_left, bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/combo-vm-lazyp"))
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-lazy-prices"))
import combo_base as B  # noqa: E402  (read-only import of the v10 copy)
import engine_n as LZN  # noqa: E402
import sweep_common as SC  # noqa: E402

def _safe_dump(obj, path):
    """json.dump with retries — writes on this box intermittently
    fail with EPERM under parallel load; retry before giving up."""
    import time as _t
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            _t.sleep(10)
    raise last


def _safe_load(path):
    import time as _t
    for _i in range(40):
        try:
            with open(path) as _f:
                return json.load(_f)
        except (PermissionError, ValueError):
            _t.sleep(10)
    return None


vm, lz = B.vm, B.lz
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
END = "2026-11-20"
ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}


# ------------------------------------------------------- speed shims
_PIT_STRUCTS = {}


def _pit_struct(rows):
    key = id(rows)
    st = _PIT_STRUCTS.get(key)
    if st is None:
        best_by_filed = {}
        for filed, end, val, prio in rows:
            cur = best_by_filed.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best_by_filed[filed] = (prio, end, val)
        fileds = sorted(best_by_filed)
        st = (fileds, best_by_filed,
              {f: date(int(f[:4]), int(f[5:7]), int(f[8:10])).toordinal()
               for f in fileds})
        _PIT_STRUCTS[key] = st
    return st


def pit_value_fast(rows, asof, max_age_days=548):
    fileds, best_by_filed, ords = _pit_struct(rows)
    i = bisect_left(fileds, asof) - 1
    if i < 0:
        return None
    filed = fileds[i]
    a_ord = date(int(asof[:4]), int(asof[5:7]),
                 int(asof[8:10])).toordinal()
    if ords[filed] < a_ord - max_age_days:
        return None
    _prio, end, val = best_by_filed[filed]
    return (filed, end, val)


def _fast_book_methods(pb):
    dates_by_t = {}
    for t, bl in pb.bars.items():
        ds = [b["d"] for b in bl]
        dates_by_t[t] = ds

    def close_on_or_before(t, d, _pb=pb, _dbt=dates_by_t):
        bl = _pb.bars.get(t, [])
        if not bl:
            return None
        i = bisect_right(_dbt[t], d) - 1
        return bl[i]["c"] if i >= 0 else None

    def next_open(t, d, _pb=pb, _dbt=dates_by_t):
        bl = _pb.bars.get(t, [])
        if not bl:
            return None, None
        i = bisect_right(_dbt[t], d)
        if i >= len(bl):
            return None, None
        b = bl[i]
        return b["d"], b["o"]

    pb.close_on_or_before = close_on_or_before
    pb.next_open = next_open


# ------------------------------------------------- parameterized VM
def vm_run_pot_n(pb, equity_rows, shares_rows, start, end, start_cash,
                 floor0, n, placebo_rng=None, label="", quiet=True):
    """Verbatim copy of v4 value-momentum-plainfloor.run_pot (ladder
    removed — the combo always ran ladder=[]) with top-5 -> n."""
    cash = start_cash
    floor = floor0
    positions, trades = {}, []
    total_costs = 0.0
    halted, halt_info = None, None
    curve, pools = [], []
    sel_dates = vm.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
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

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = {}
            for t in vm.UNIVERSE:
                be = vm.pit_value(equity_rows.get(t, []), d)
                so = vm.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 \
                        or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 5:
                k = len(scores) if n == "ALL" else min(n, len(scores))
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), k)
                else:
                    vr = vm.percentile_ranks(
                        {t: v[0] for t, v in scores.items()})
                    mr = vm.percentile_ranks(
                        {t: v[1] for t, v in scores.items()})
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined,
                                   key=lambda t: -combined[t])[:k]
                pools.append((d, sorted(scores), list(picks)))
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
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
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}


def lz_run_pot_n(pb, signals, start, end, n, start_cash=50.0,
                 placebo_rng=None):
    return LZN.run_pot_n(pb, signals, lz.UNIVERSE, start, end, n,
                         start_cash=start_cash, floor0=0.0,
                         placebo_rng=placebo_rng)


# ------------------------------------------------------------ blend
def run_episode(ctx, sd, ed, start_cash, floor, n, vm_rng=None,
                lz_rng=None):
    half = start_cash / 2.0
    vms = vm_run_pot_n(ctx["pb_vm"], ctx["eq"], ctx["sh"], sd, ed, half,
                       0.0, n, placebo_rng=vm_rng)
    lzs = lz_run_pot_n(ctx["pb_lz"], ctx["signals"], sd, ed, n,
                       start_cash=half, placebo_rng=lz_rng)
    sel_vm = vm.quarter_selection_dates(ctx["pb_vm"], sd, ed)
    sel_lz = lz.quarter_selection_dates(ctx["pb_lz"], sd, ed)
    assert sel_vm == sel_lz, "selection dates diverge"
    curve, info = B.blend_curves(vms["curve"], lzs["curve"], sel_vm,
                                 pot0=start_cash, floor=floor)
    info["sleeve_costs"] = vms["costs"] + lzs["costs"]
    info["sleeve_orders"] = len(vms["trades"]) + len(lzs["trades"])
    info["curve"] = curve
    info["sel_dates"] = sel_vm
    return info


def run_house(ctx, sd, ed, n, seed=None):
    vm_rng = random.Random(seed) if seed is not None else None
    lz_rng = random.Random(seed) if seed is not None else None
    start_cash = 100.0
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_episode(ctx, sd, ed, start_cash, floor1, n, vm_rng, lz_rng)
    out = {"final": r1["final"],
           "costs": r1["sleeve_costs"] + r1["transfer_costs"],
           "orders": r1["sleeve_orders"], "curve": list(r1["curve"]),
           "halted": r1["halt"], "restarts": [], "second_halt": None}
    if r1["halt"] is None:
        return out
    liq_date = min(d for d in ctx["pb_vm"].dates
                   if d > r1["halt"] and d <= ed)
    cash = r1["final"]
    day90 = date(int(liq_date[:4]), int(liq_date[5:7]),
                 int(liq_date[8:10])).toordinal() + 90
    restart = None
    for cand in r1["sel_dates"]:
        if date(int(cand[:4]), int(cand[5:7]),
                int(cand[8:10])).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else ed
    for d in ctx["pb_vm"].dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((ed, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halt"],
                            "liquidation_date": liq_date,
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_episode(ctx, restart, ed, cash, floor2, n, vm_rng, lz_rng)
    out["final"] = r2["final"]
    out["costs"] += r2["sleeve_costs"] + r2["transfer_costs"]
    out["orders"] += r2["sleeve_orders"]
    out["curve"] += list(r2["curve"])
    if r2["halt"] is not None:
        out["second_halt"] = {"signal_date": r2["halt"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def run_native(ctx, sd, ed, n, seed=None):
    vm_rng = random.Random(seed) if seed is not None else None
    lz_rng = random.Random(seed) if seed is not None else None
    r = run_episode(ctx, sd, ed, 100.0, 85.0, n, vm_rng, lz_rng)
    return {"final": r["final"],
            "costs": r["sleeve_costs"] + r["transfer_costs"],
            "orders": r["sleeve_orders"], "curve": list(r["curve"]),
            "halted": r["halt"], "restarts": [], "second_halt": None}


def main():
    t0 = time.time()
    pb_vm, eq, sh = B.build_vm_book()
    pb_lz, signals, _census = B.build_lz_book()
    _fast_book_methods(pb_vm)
    _fast_book_methods(pb_lz)
    vm.pit_value = pit_value_fast
    ctx = {"pb_vm": pb_vm, "eq": eq, "sh": sh, "pb_lz": pb_lz,
           "signals": signals}

    checks = []
    for road, want in (("CONT", 540.72), ("VAL", 312.55),
                       ("DECADE", 514.06)):
        r = run_house(ctx, ROADS[road], END, 5)
        checks.append((f"{road} house N=5 == {want}",
                       round(r["final"], 2) == want,
                       round(r["final"], 2)))
    for name, ok, val in checks:
        print(f"INTEGRITY {'PASS' if ok else 'FAIL'}: {name} (got {val})",
              flush=True)
    if not all(ok for _, ok, _ in checks):
        print("INTEGRITY FAILED", flush=True)
        sys.exit(1)

    _opath = os.path.join(HERE, "cells_lazyp.json")
    out = (_safe_load(_opath) if os.path.exists(_opath) else None) or {"family": "combo-vm-lazyp", "native_count_per_sleeve": 5,
           "integrity": [{"check": n, "pass": ok, "value": v}
                         for n, ok, v in checks],
           "cells": {}, "curves": {}}
    for road, start in ROADS.items():
        for form, runner in (("house", run_house), ("native", run_native)):
            for n in COUNTS:
                key = f"{road}|{form}|{n}"
                if key in out["cells"]:
                    print(f"{key}: SKIP (saved)", flush=True)
                    continue
                r = runner(ctx, start, END, n)
                twins = []
                for seed in range(1, 21):
                    tr = runner(ctx, start, END, n, seed=seed)
                    twins.append(round(tr["final"], 2))
                beats = sum(1 for x in twins if r["final"] > x)
                halts = (1 if r["halted"] else 0) \
                    + (1 if r.get("second_halt") else 0)
                out["cells"][key] = {
                    "final": round(r["final"], 2),
                    "costs": round(r["costs"], 2),
                    "orders": r["orders"], "halts": halts,
                    "max_dd_pct": SC.max_dd(r["curve"]),
                    "placebo_beats": beats,
                    "placebo_median": round(
                        (sorted(twins)[9] + sorted(twins)[10]) / 2, 2),
                    "placebo_finals": sorted(twins)}
                if form == "house":
                    out["curves"][key] = [[d, round(v, 4)]
                                          for d, v in r["curve"]]
                print(f"{key}: ${r['final']:,.2f} placebo {beats}/20 "
                      f"({time.time()-t0:.0f}s)", flush=True)
                _safe_dump(out, _opath)
    _safe_dump(out, os.path.join(HERE, "cells_lazyp.json"))
    print(f"DONE lazyp in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
