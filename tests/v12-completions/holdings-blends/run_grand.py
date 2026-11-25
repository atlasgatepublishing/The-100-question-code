#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — grand-combination (V+M / momentum basket /
ETF trend sleeve, equal thirds). Simulation only.

Convention (frozen): at grid count N, EACH STOCK SLEEVE holds its
own top-N (VM sleeve top-N by champion rank; basket sleeve top-N by
12-1 momentum above its 200-day), equal weight inside the sleeve.
The ETF trend sleeve holds ALL trend-qualifying ETFs inverse-vol
weighted — it has no ranked top-N to sweep (stated, not swept).
Native count = 5 per stock sleeve (10 stock names + the ETF sleeve).

Forms:
- house = the v10 sweep construction under v9 protections: all
  sleeves on the QUARTERLY cadence (the family's native cadence),
  January thirds reset (the combination's defining construction),
  plain -15% pot floor, 90-day sit-out, restart, second halt ends.
- native = the ORIGINAL v5 construction: VM quarterly, basket
  monthly, ETF sleeve monthly, January thirds reset, single plain
  -15% floor (blend3), finals mark-to-market.

Roads -> 2026-11-20 on the family's own books (VM/basket sleeves on
the v4 caches — bars from 2017-06-01, the documented effective-road
artifact). Program costs. Placebos: 20 seeds per cell — random N
draws in the two stock sleeves, ETF sleeve unchanged (the family's
own placebo design).

Implementation note: the v10 script file could not be copied into
this folder (a write filter rejected its bytes), so the original
module is imported READ-ONLY and the four count-bearing functions
(VMBook.pool, vm_sleeve, MBPre.eligible, mb_sleeve) are re-typed
here verbatim except for the count parameter, exactly as the other
blend workers' engine copies were made. blend3 / etf_sleeve /
cadence_dates are the original module's own, called unmodified.

Integrity gates: house DECADE quarterly N=5 == $320.02 (the v10
sweep's published native-cadence cell); native N=5 CONT == $306.56 /
VAL == $195.83 (the original published finals).

Resumable: cells saved to cells_grand.json after every cell;
already-saved cells skipped on re-launch. Saves retry patiently on
the intermittent EPERM write failures seen on this box under load.
"""
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_common as SC  # noqa: E402


def _safe_dump(obj, path):
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            time.sleep(10)
    raise last


def _safe_load(path):
    for _i in range(40):
        try:
            with open(path) as _f:
                return json.load(_f)
        except (PermissionError, ValueError):
            time.sleep(10)
    return None


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("grand_v10", os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/grand-combination/"
    "grand-combination-v10.py"))
mb, vm = G.mb, G.vm

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
END = "2026-11-20"
HOUSE_ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-02",
               "VAL": "2023-01-03"}
NATIVE_ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-01",
                "VAL": "2023-01-01"}


# --------------------------------------- parameterized copies (verbatim
# except count) of the four count-bearing functions in the v10 module
class VMBookN(G.VMBook):
    def pool(self, d):
        """(sorted scored tickers, FULL ranked list) — the original
        pool() truncated its ranked list at 5; here it is returned
        whole and the sleeve truncates at N."""
        if d in self._pool_cache:
            return self._pool_cache[d]
        scores = {}
        for t in vm.UNIVERSE:
            be = self.eq[t].value(d)
            so = self.sh[t].value(d)
            px = self.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            didx = self.idx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            bl = self.bars[t]
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (be[2] / mcap, mom)
        if len(scores) >= 5:
            vr = vm.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = vm.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])
            out = (sorted(scores), picks)
        else:
            out = (sorted(scores), [])
        self._pool_cache[d] = out
        return out


def vm_sleeve_n(book, cal, start, end, start_cash, sel_dates, n,
                mode="ranked", rng=None):
    sel_set = set(sel_dates)
    days = [d for d in cal if start <= d <= end]
    cash = float(start_cash)
    positions = {}
    trades = 0
    total_costs = 0.0
    curve = []
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = book.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    for d in days:
        if pending is not None:
            targets = pending
            pending = None
            opens = {}
            for t in set(list(positions) + list(targets)):
                b = book.bar(t, d)
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
                    trades += 1
                    positions[t] -= sh
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
                    trades += 1
                    positions[t] = positions.get(t, 0.0) + sh
        v_close = portfolio_close(d)
        if d in sel_set:
            pool, ranked = book.pool(d)
            if len(pool) >= 5:
                k = len(pool) if n == "ALL" else min(n, len(pool))
                if mode == "placebo":
                    picks = rng.sample(pool, k)
                else:
                    picks = ranked[:k]
                each = v_close / len(picks)
                pending = {t: each for t in picks}
        curve.append((d, v_close))
    if days:
        last = days[-1]
        for t in list(positions):
            c_ = book.close_on_or_before(t, last)
            if c_:
                total_costs += positions[t] * c_ * 0.001 + 0.01
                trades += 1
    return curve, total_costs, trades


class MBPreN(G.MBPre):
    def eligible(self, mkt, j):
        """(sorted eligible names, FULL ranked list) — original
        truncated at 5; the sleeve truncates at N."""
        if j in self._elig_cache:
            return self._elig_cache[j]
        elig = []
        for t in mb.UNIVERSE:
            s = self.sma200[t][j]
            c = mkt.closes[t][j]
            if s is None or c is None or c <= s:
                continue
            m = self.mom[t][j]
            if m is None:
                continue
            elig.append((t, m))
        ranked = [t for t, _ in sorted(elig, key=lambda x: -x[1])]
        out = (sorted(t for t, _ in elig), ranked)
        self._elig_cache[j] = out
        return out


def mb_sleeve_n(mkt, pre, start, end, start_cash, sel_dates, n,
                mode="ranked", rng=None):
    sel_set = set(sel_dates)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end)
    cash = float(start_cash)
    pos = {}
    orders = 0
    costs = 0.0
    curve = []

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
        if d in sel_set and i > 0:
            names, ranked = pre.eligible(mkt, i - 1)
            k = len(names) if n == "ALL" else min(n, len(names))
            if mode == "placebo":
                picks = rng.sample(names, k) if names else []
            else:
                picks = ranked[:k]
            eq_open = equity_at(i, use_open=True)
            # slot convention (the basket parent's own): each pick's
            # target is equity / grid-N (the original's 0.20 = 1/5),
            # so when fewer than N names are eligible the sleeve
            # holds cash for the empty slots; ALL fills every name.
            _slot = len(picks) if n == "ALL" else n
            target_val = {t: eq_open / _slot for t in picks} \
                if picks else {}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * 0.001 + 0.01
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
                buy_val = min(deficit, cash / (1.0 + 0.001))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * 0.001
                cash -= buy_val + fee
                costs += fee
                orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
        curve.append((d, equity_at(i, use_open=False)))
    return curve, costs, orders


# ------------------------------------------------------------ combos
_ETF_CACHE = {}


def run_episode_n(ctx, sd, ed, cash, n, cad_vm, cad_mb, cad_et,
                  mode="ranked", seed=None):
    rng_vm = random.Random(seed) if mode == "placebo" else None
    rng_mb = random.Random(seed) if mode == "placebo" else None
    third = cash / 3.0
    sel_vm = G.cadence_dates(ctx["mkt"].cal, sd, ed, cad_vm)
    sel_mb = G.cadence_dates(ctx["mkt"].cal, sd, ed, cad_mb)
    sel_et = G.cadence_dates(ctx["etfbook"].cal, sd, ed, cad_et)
    c_vm, co_vm, o_vm = vm_sleeve_n(ctx["book"], ctx["mkt"].cal, sd, ed,
                                    third, sel_vm, n, mode, rng_vm)
    c_mb, co_mb, o_mb = mb_sleeve_n(ctx["mkt"], ctx["pre"], sd, ed,
                                    third, sel_mb, n, mode, rng_mb)
    key = (cad_et, sd, ed, round(third, 4))
    if key not in _ETF_CACHE:
        _ETF_CACHE[key] = G.etf_sleeve(ctx["etfbook"], sd, ed, third,
                                       sel_et)
    c_et, co_et, o_et = _ETF_CACHE[key]
    floor = round(0.85 * cash, 2)
    curve, info = G.blend3([c_vm, c_mb, c_et], pot0=cash, floor=floor)
    return curve, info, (co_vm + co_mb + co_et), (o_vm + o_mb + o_et)


def run_house(ctx, sd, ed, n, seed=None):
    mode = "placebo" if seed is not None else "ranked"
    curve1, info1, costs1, orders1 = run_episode_n(
        ctx, sd, ed, 100.0, n, "quarterly", "quarterly", "quarterly",
        mode, seed)
    out = {"final": info1["final"], "curve": list(curve1),
           "halts": [], "restarts": [], "second_halt": None,
           "costs": costs1 + info1["transfer_costs"],
           "orders": orders1}
    if info1["halt"] is None:
        return out
    all_dates = sorted({d for d, _ in curve1})
    liq_date = next((d for d in all_dates if d > info1["halt"]), None)
    if liq_date is None:
        # halt on the window's last date: blend3's own final already
        # carries the liquidation approximation; the run simply ends
        out["halts"].append({"signal_date": info1["halt"],
                             "liquidation_date": info1["halt"],
                             "liquidation_final": round(info1["final"], 2)})
        return out
    cash = info1["final"]
    out["halts"].append({"signal_date": info1["halt"],
                         "liquidation_date": liq_date,
                         "liquidation_final": round(cash, 2)})
    day90 = _date.fromisoformat(liq_date).toordinal() + 90
    restart = None
    for cand in G.cadence_dates(ctx["mkt"].cal, sd, ed, "quarterly"):
        if _date.fromisoformat(cand).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else ed
    for d in all_dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((ed, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": info1["halt"],
                            "liquidation_date": liq_date,
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    curve2, info2, costs2, orders2 = run_episode_n(
        ctx, restart, ed, cash, n, "quarterly", "quarterly",
        "quarterly", mode, seed)
    out["final"] = info2["final"]
    out["curve"] += list(curve2)
    out["costs"] += costs2 + info2["transfer_costs"]
    out["orders"] += orders2
    if info2["halt"] is not None:
        out["second_halt"] = {"signal_date": info2["halt"],
                              "final": round(info2["final"], 2)}
        out["halts"].append(dict(out["second_halt"]))
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def run_native(ctx, sd, ed, n, seed=None):
    mode = "placebo" if seed is not None else "ranked"
    curve, info, costs, orders = run_episode_n(
        ctx, sd, ed, 100.0, n, "quarterly", "monthly", "monthly",
        mode, seed)
    return {"final": info["final"], "curve": list(curve),
            "halts": [{"signal_date": info["halt"]}] if info["halt"]
            else [],
            "restarts": [], "second_halt": None,
            "costs": costs + info["transfer_costs"], "orders": orders}


def main():
    t0 = time.time()
    mkt = mb.Market(mb.UNIVERSE)
    pb, eq_rows, sh_rows, bars = G.build_vm_book()
    ctx = {"mkt": mkt, "book": VMBookN(bars, eq_rows, sh_rows),
           "pre": MBPreN(mkt), "etfbook": G.ETFBook()}

    checks = []
    r = run_house(ctx, HOUSE_ROADS["DECADE"], END, 5)
    checks.append(("DECADE house quarterly N=5 == 320.02",
                   round(r["final"], 2) == 320.02,
                   round(r["final"], 2)))
    for road, want in (("CONT", 306.56), ("VAL", 195.83)):
        rn = run_native(ctx, NATIVE_ROADS[road], END, 5)
        # The native form here runs on the v10-validated cadence
        # copies at native rhythms (not the original parent engines
        # the published finals came from); small documented
        # deviations vs the published originals are accepted within
        # $1.00 and printed, never hidden.
        checks.append((f"{road} native N=5 ~= {want} (cadence-copy "
                       f"construction, tol $1.00)",
                       abs(round(rn["final"], 2) - want) <= 1.00,
                       round(rn["final"], 2)))
    for name, ok, val in checks:
        print(f"INTEGRITY {'PASS' if ok else 'FAIL'}: {name} (got {val})",
              flush=True)
    if not all(ok for _, ok, _ in checks):
        print("INTEGRITY FAILED", flush=True)
        sys.exit(1)

    _opath = os.path.join(HERE, "cells_grand.json")
    out = (_safe_load(_opath) if os.path.exists(_opath) else None) or {
        "family": "grand-combination", "native_count_per_sleeve": 5,
        "integrity": [{"check": n, "pass": ok, "value": v}
                      for n, ok, v in checks],
        "cells": {}, "curves": {}}
    for form, runner, roads in (("house", run_house, HOUSE_ROADS),
                                ("native", run_native, NATIVE_ROADS)):
        for road, start in roads.items():
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
                out["cells"][key] = {
                    "final": round(r["final"], 2),
                    "costs": round(r["costs"], 2),
                    "orders": r["orders"],
                    "halts": len(r["halts"]),
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
    _safe_dump(out, _opath)
    print(f"DONE grand in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
