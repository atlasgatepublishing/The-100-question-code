#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — gap-a9-frog-pan CONSTRUCTED form (v12 PIT S&P 500).
Replicates run_window() in backtests/v12-completions/gap-a9-frog-pan/run.py
exactly, with NHOLD replaced by the sweep count N (target weight =
equity/N — the original divides by NHOLD even when fewer names are
eligible; preserved verbatim). ALL-ELIGIBLE: N = number eligible that
month (target = equity/len(picks)). Eligibility lists are cached per
signal date (identical values across counts/seeds — the expensive part).
VALIDATION: at N=30 this sim is compared against the original module's
own run_window on DECADE before any sweep number is trusted.
Form: the constructed form as frozen (plain -15% floor, no restart).
Placebos: 20 seeds on DECADE, random same-count from the same eligible
pool (original placebo design). Roads: LONG/DECADE/CONT/VAL per the
construction (LONG only if the frozen 70% coverage check passes).
"""
import importlib.util, json, os, random, statistics, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a9-frog-pan/run.py")
spec = importlib.util.spec_from_file_location("frog_con", SRC)
M = importlib.util.module_from_spec(spec)
# DATA ARTIFACT (documented, not patched in place): at this sweep's
# first attempt (2026-11-22 ~14:11, see sweep_frog_constructed.log) the
# source folder's data/yahoo/MMM.json was truncated mid-file
# (JSONDecodeError at char 155747) and the run died at import. By the
# completion pass (~16:44) the file verified clean again (329,456 bytes,
# 4,753 rows, loads fine) — the corruption was transient. As a guard,
# at import time only, json.load is wrapped to return [] for an
# undecodable file (the Yahoo layer would skip that ticker; Layer 1,
# the Tiingo panel, is loaded after Yahoo and takes precedence, so a
# panel ticker would not be dropped). Skips are printed below; the
# completion run's printed list governs whether the guard ever fired.
_SKIPPED_YAHOO = []
_orig_json_load = json.load
def _safe_json_load(fp, *a, **k):
    try:
        return _orig_json_load(fp, *a, **k)
    except json.JSONDecodeError:
        _SKIPPED_YAHOO.append(getattr(fp, "name", "?"))
        return []
json.load = _safe_json_load
try:
    spec.loader.exec_module(M)
finally:
    json.load = _orig_json_load
print("yahoo files skipped as corrupt at import:", _SKIPPED_YAHOO, flush=True)

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CONF = {"CONF_A": ("2020-01-01", "2023-12-31"), "CONF_B": ("2024-01-01", "2026-11-20")}

_elig_cache = {}
def eligible_cached(j, members):
    if j not in _elig_cache:
        _elig_cache[j] = M.eligible(j, members)
    return _elig_cache[j]

def run_n(start_d, end_d, n_count, mode="strategy", seed=0):
    CAL, POT, COST, SELL_FEE, FLOOR = M.CAL, M.POT, M.COST, M.SELL_FEE, M.FLOOR
    i0 = next(i for i, d in enumerate(CAL) if d >= start_d)
    i1 = max(i for i, d in enumerate(CAL) if d <= end_d)
    cash = POT; pos = {}
    curve = []; costs = 0.0; orders = 0; writeoffs = []
    rng = random.Random(seed)
    rebal = set(); seen_months = set()
    for i in range(i0, i1 + 1):
        m = CAL[i][:7]
        if m not in seen_months:
            seen_months.add(m); rebal.add(i)
    def px_open(t, i):
        _, opn, traded, _, _, _ = M.aligned(t)
        if traded[i]:
            return opn[i]
        lt = M.last_traded_le(t, i)
        if lt < 0 or i - lt > 10:
            return None
        return M.aligned(t)[0][lt]
    def equity(i):
        v = cash
        for t, sh in pos.items():
            close = M.aligned(t)[0]
            lt = M.last_traded_le(t, i)
            if lt < 0 or i - lt > 20:
                continue
            v += sh * close[i]
        return v
    halted = False
    for i in range(i0, i1 + 1):
        if i in rebal and i > i0 or (i == i0):
            j = i - 1
            if j >= 252:
                members = M.members_on(CAL[j])
                elig = eligible_cached(j, members)
                if mode == "strategy":
                    elig_s = sorted(elig, key=lambda x: (x[1], -x[2], x[0]))
                    picks = [e[0] for e in elig_s] if n_count is None else [e[0] for e in elig_s[:n_count]]
                else:
                    pool = [e[0] for e in elig]
                    k = len(pool) if n_count is None else min(n_count, len(pool))
                    picks = rng.sample(pool, k) if pool else []
                if picks:
                    eq = equity(i)
                    denom = len(picks) if n_count is None else n_count
                    target_val = eq / denom
                    for t, sh in list(pos.items()):
                        if t not in picks:
                            p = px_open(t, i)
                            if p is None:
                                writeoffs.append((CAL[i], t, round(sh * (M.aligned(t)[0][M.last_traded_le(t, i)] or 0), 2)))
                            else:
                                amt = sh * p
                                cst = amt * COST + SELL_FEE
                                cash += amt - cst; costs += cst; orders += 1
                            del pos[t]
                    for t in picks:
                        p = px_open(t, i)
                        if p is None or p <= 0:
                            continue
                        cur = pos.get(t, 0.0) * p
                        diff = target_val - cur
                        if abs(diff) < 0.01:
                            continue
                        amt = abs(diff)
                        cst = amt * COST + (SELL_FEE if diff < 0 else 0.0)
                        if diff > 0:
                            buy = min(diff, cash - diff * COST)
                            if buy <= 0: continue
                            sh = buy / p
                            cash -= buy + buy * COST; costs += buy * COST; orders += 1
                            pos[t] = pos.get(t, 0.0) + sh
                        else:
                            sh = amt / p
                            cash += amt - cst; costs += cst; orders += 1
                            pos[t] = pos.get(t, 0.0) - sh
                            if pos[t] <= 1e-9: del pos[t]
        eq = equity(i)
        curve.append((CAL[i], round(eq, 2)))
        if eq <= FLOOR and i < i1:
            ni = i + 1
            for t, sh in list(pos.items()):
                p = px_open(t, ni)
                if p is None:
                    writeoffs.append((CAL[ni], t, round(sh * (M.aligned(t)[0][M.last_traded_le(t, ni)] or 0), 2)))
                else:
                    amt = sh * p; cst = amt * COST + SELL_FEE
                    cash += amt - cst; costs += cst; orders += 1
                del pos[t]
            curve.append((CAL[ni], round(cash, 2)))
            halted = True
            break
    final = curve[-1][1] if curve else POT
    peak = POT; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halted": halted,
            "n_writeoffs": len(writeoffs), "curve": curve}

def period_stats(curve):
    bym = {}
    for d, v in curve: bym[d[:7]] = v
    keys = sorted(bym); rets = []; prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

def main():
    t0 = time.time()
    out = {"family": "gap-a9-frog-pan", "form": "constructed_v12_PIT",
           "constructed_native_count": 30,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "cells": {}}
    # coverage gate for LONG (frozen in the construction's main())
    j0 = next(i for i, d in enumerate(M.CAL) if d >= "2010-01-01") - 1
    mem0 = M.members_on(M.CAL[j0])
    # NOTE (completion pass): the source module's aligned store is named
    # AL (aligned(t) returns AL[t] = (close, open, last_traded, first,
    # last)); an earlier draft of this sweep referenced a BARS attribute
    # that does not exist in the source and died here. Fixed to M.AL —
    # the coverage check itself (first_idx <= j0-252) is unchanged.
    have = sum(1 for t in mem0 if t in M.AL and M.aligned(t)[3] is not None and M.aligned(t)[3] <= j0 - 252)
    share = round(100 * have / len(mem0), 1) if mem0 else 0.0
    out["long_coverage"] = {"pit_members": len(mem0), "with_computable_window": have, "share_pct": share}
    run_long = share >= 70.0
    print("LONG coverage:", out["long_coverage"], "run_long:", run_long, flush=True)
    # validation vs original engine at N=30 on DECADE
    M.NHOLD = 30
    ref = M.run_window(*ROADS["DECADE"], "strategy")
    mine = run_n(*ROADS["DECADE"], 30)
    out["validation_vs_original_engine_DECADE_n30"] = {
        "original_final": ref["final"], "sweep_final": mine["final"],
        "original_dd": ref["max_dd_pct"], "sweep_dd": mine["max_dd_pct"],
        "match": ref["final"] == mine["final"]}
    print("VALIDATION n30 DECADE:", out["validation_vs_original_engine_DECADE_n30"], flush=True)
    roads = dict(ROADS) if run_long else {k: v for k, v in ROADS.items() if k != "LONG"}
    for n in COUNTS:
        key = "ALL" if n is None else str(n)
        cell = {}
        for w, (a, b) in {**roads, **CONF}.items():
            r = run_n(a, b, n)
            cell[w] = {k: v for k, v in r.items() if k != "curve"}
            if w == "DECADE":
                cell[w]["curve"] = r["curve"]
        a, b = ROADS["DECADE"]
        pls = [run_n(a, b, n, mode="placebo", seed=s)["final"] for s in range(1, 21)]
        cell["placebos_DECADE"] = {"finals": pls,
            "beaten": sum(1 for x in pls if cell["DECADE"]["final"] > x),
            "median": round(statistics.median(pls), 2)}
        out["cells"][key] = cell
        print(f"constructed n={key}: " + " ".join(f"{w} {cell[w]['final']}" for w in roads) +
              f" placebo {cell['placebos_DECADE']['beaten']}/20 ({round(time.time()-t0)}s)", flush=True)
    finals = {k: c["DECADE"]["final"] for k, c in out["cells"].items()}
    best = max(finals, key=finals.get)
    out["best_DECADE"] = best
    for k in {best, "30"}:
        out["cells"][k]["DECADE"]["period_stats_monthly"] = period_stats(out["cells"][k]["DECADE"]["curve"])
    for c in out["cells"].values():
        c["DECADE"].pop("curve", None)
    out["spy"] = {w: M.spy_net(a, b) for w, (a, b) in ROADS.items()}
    json.dump(out, open(os.path.join(HERE, "results_frog_constructed.json"), "w"), indent=1)
    print("constructed done", round(time.time() - t0), "s", flush=True)

if __name__ == "__main__":
    main()
