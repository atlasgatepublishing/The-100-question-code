#!/usr/bin/env python3
"""Low Volatility — v12 HOLDINGS-COUNT SWEEP. Spec: SWEEP-SPEC.md (frozen).
Base construction identical to ../low-volatility CONSTRUCTION-SPEC.md:
PIT S&P 500 membership, 252-day vol on reference dates (last business day of
Jan/Apr/Jul/Oct), eligibility >=200 returns + bar on the reference date,
N lowest-vol names, INVERSE-VOL weights among those held, quarterly rebalance
at the close of the 3rd Friday of Feb/May/Aug/Nov, $100 pot, costs
0.10%/side + $0.01/sell order, no floor (native form), vanishing prices ->
ZERO after >10 trading days missing (FB->META rename excepted).
House form adds the program's plain -15% floor (close check vs episode-start
balance; breach -> liquidate at next trading day's close, 90 cash days,
restart at next quarterly rebalance on/after day 90 with episode-2 floor at
85% of restart cash; second halt ends the run).
Sweep variable: N in 1,2,3,5,8,10,15,20,30,100 (native), ALL-ELIGIBLE.
Placebos: 20 seeds/cell, N names drawn uniformly at random from the same
eligible pool, inverse-vol weighted by their true vols, same form/costs.
Prices: data/merged_prices.json (program caches merged read-only, Yahoo
adjusted-close convention) + data/px_*.json fetched into this folder.
Simulation only."""
import bisect, csv, json, math, os, random, time
from datetime import date, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
START_CASH = 100.0
COST = 0.001
SELL_FEE = 0.01
RENAMES = {"FB": "META"}

# ---------------- prices -> aligned matrix on SPY calendar ----------------
raw = {}
mp = json.load(open(os.path.join(DATA, "merged_prices.json")))
for t, rows in mp.items():
    raw[t] = rows
import glob as _g
for p in _g.glob(os.path.join(DATA, "px_*.json")):
    t = os.path.basename(p)[3:-5]
    if t not in raw:
        raw[t] = json.load(open(p))

spy_j = json.load(open(os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")))
_r = spy_j["chart"]["result"][0]
SPY = {}
for i, ts in enumerate(_r["timestamp"]):
    a = _r["indicators"]["adjclose"][0]["adjclose"][i]
    if a is not None:
        SPY[time.strftime("%Y-%m-%d", time.gmtime(ts))] = a
CAL = sorted(d for d in SPY if "2008-12-01" <= d <= "2026-11-20")
CAL_IDX = {d: i for i, d in enumerate(CAL)}
N_DAYS = len(CAL)
tickers = sorted(raw)
T_IDX = {t: i for i, t in enumerate(tickers)}
NT = len(tickers)
PX = np.full((NT, N_DAYS), np.nan)
LASTBAR = np.full(NT, -1, dtype=int)
for t, rows in raw.items():
    i = T_IDX[t]
    for d, v in rows:
        gi = CAL_IDX.get(d)
        if gi is not None:
            PX[i, gi] = v
            if gi > LASTBAR[i]:
                LASTBAR[i] = gi
# forward-filled copy for marking (zero rule applied via LASTBAR separately)
PXF = PX.copy()
for i in range(NT):
    row = PXF[i]
    m = np.isnan(row)
    if m.all():
        continue
    idx = np.where(~m, np.arange(N_DAYS), 0)
    np.maximum.accumulate(idx, out=idx)
    PXF[i] = row[idx]
PY = np.nan_to_num(PXF).tolist()          # forward-filled marking prices, 0.0 = no tape yet
PL = PX.tolist()                          # raw prices, NaN = no bar that day
LB = LASTBAR.tolist()
print(f"tapes {NT} days {N_DAYS} cal {CAL[0]}..{CAL[-1]}", flush=True)

# ---------------- membership ----------------
_rows = list(csv.reader(open(os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/low-volatility/data/sp500_hist.csv"))))[1:]
SNAPS = sorted((d, t.split(",")) for d, t in _rows)
SNAP_DATES = [s[0] for s in SNAPS]

def members_on(dstr):
    i = bisect.bisect_right(SNAP_DATES, dstr) - 1
    return SNAPS[i][1] if i >= 0 else []

# ---------------- rebalance calendar + vols (precomputed once) ----------------
def third_friday(y, m):
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7 + 14)

def last_business_day(y, m):
    d = date(y, 12, 31) if m == 12 else date(y, m + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

SCHED = []  # (ref_str, exec_str)
for y in range(2009, 2027):
    for ref_m, exec_m in ((1, 2), (4, 5), (7, 8), (10, 11)):
        ref = last_business_day(y, ref_m).isoformat()
        ex = third_friday(y, exec_m).isoformat()
        if ex not in CAL_IDX:
            cand = [d for d in CAL if d <= ex]
            ex = cand[-1] if cand else ex
        SCHED.append((ref, ex))

VOL_CACHE = {}
def vols_at(ref):
    """{ticker: vol} for eligible members at ref (spec: >=200 returns over the
    252 trading days ending at ref, and a price bar exactly on ref)."""
    if ref in VOL_CACHE:
        return VOL_CACHE[ref]
    out = {}
    if ref not in CAL_IDX:
        VOL_CACHE[ref] = out
        return out
    end_i = CAL_IDX[ref]
    if end_i < 252:
        VOL_CACHE[ref] = out
        return out
    lo = end_i - 252
    for t in members_on(ref):
        i = T_IDX.get(t)
        if i is None:
            continue
        seg = PX[i, lo:end_i + 1]
        if np.isnan(seg[-1]):
            continue
        seg = seg[~np.isnan(seg)]
        if len(seg) < 201:
            continue
        rets = seg[1:] / seg[:-1] - 1.0
        if len(rets) < 200:
            continue
        v = float(np.std(rets, ddof=1))
        if v > 0:
            out[t] = v
    VOL_CACHE[ref] = out
    return out

# ---------------- engine ----------------
def px_at(i, gi):
    return PY[i][gi]

def run(start, end, count, form, seed=None):
    rng = random.Random(4000 + seed) if seed is not None else None
    sched = {ex: ref for ref, ex in SCHED if start <= ex <= end}
    days = [d for d in CAL if start <= d <= end]
    cash = START_CASH
    pos = {}  # ticker -> shares
    zeroed = []
    costs = 0.0
    orders = 0
    curve = []
    halts = []
    mode = "invested"          # invested | liquidate | cash_wait | ended
    episode_start = START_CASH
    halt_date = None
    for d in days:
        gi = CAL_IDX[d]
        if mode == "liquidate":
            for t in list(pos):
                i = T_IDX[t]
                p = PL[i][gi]
                if p != p:
                    continue
                val = pos[t] * p
                fee = val * COST + SELL_FEE
                costs += fee; cash += val - fee; orders += 1
            pos = {}
            mode = "ended" if len(halts) >= 2 else "cash_wait"
            curve.append((d, round(cash, 4)))
            continue
        # vanishing / rename handling for held names
        for t in list(pos):
            i = T_IDX[t]
            if gi - LB[i] > 10:
                if t in RENAMES and RENAMES[t] in T_IDX:
                    j = T_IDX[RENAMES[t]]
                    bv = px_at(i, LB[i])
                    sv = px_at(j, gi)
                    if sv > 0 and bv > 0:
                        pos[RENAMES[t]] = pos.get(RENAMES[t], 0.0) + pos[t] * bv / sv
                    else:
                        zeroed.append(t)
                    del pos[t]
                else:
                    del pos[t]
                    zeroed.append(t)
        if d in sched and mode in ("invested", "cash_wait"):
            skip = False
            if mode == "cash_wait":
                if (date.fromisoformat(d) - date.fromisoformat(halt_date)).days < 90:
                    skip = True
                else:
                    episode_start = cash
                    mode = "invested"
            if not skip:
                ref = sched[d]
                vols = vols_at(ref)
                elig = sorted(vols)
                if elig:
                    n = len(elig) if count == "ALL" else min(count, len(elig))
                    if rng is None:
                        chosen = sorted(elig, key=lambda t: vols[t])[:n]
                    else:
                        chosen = rng.sample(elig, n)
                    inv_sum = sum(1.0 / vols[t] for t in chosen)
                    target_w = {t: (1.0 / vols[t]) / inv_sum for t in chosen}
                    pv = cash + sum(sh * px_at(T_IDX[t], gi) for t, sh in pos.items())
                    # sells / trims
                    for t in list(pos):
                        i = T_IDX[t]
                        p = PL[i][gi]
                        price = 0.0 if p != p else p
                        cur = pos[t] * price
                        tgt = target_w.get(t, 0.0) * pv
                        if tgt <= 0:
                            if cur > 0:
                                fee = cur * COST + SELL_FEE
                                costs += fee; cash += cur - fee; orders += 1
                            del pos[t]
                        elif cur > tgt and price > 0:
                            sell_val = cur - tgt
                            fee = sell_val * COST + SELL_FEE
                            costs += fee; cash += sell_val - fee; orders += 1
                            pos[t] = tgt / price
                    # buys
                    pv2 = cash + sum(sh * px_at(T_IDX[t], gi) for t, sh in pos.items())
                    for t in chosen:
                        i = T_IDX[t]
                        p = PL[i][gi]
                        if p != p or p <= 0:
                            continue
                        price = p
                        cur = pos.get(t, 0.0) * price
                        tgt = target_w[t] * pv2
                        if tgt > cur and cash > 0:
                            buy_val = min(tgt - cur, cash / (1 + COST))
                            if buy_val <= 0:
                                continue
                            fee = buy_val * COST
                            costs += fee; cash -= buy_val + fee; orders += 1
                            pos[t] = pos.get(t, 0.0) + buy_val / price
        eq = cash + sum(sh * px_at(T_IDX[t], gi) for t, sh in pos.items())             if mode == "invested" else cash
        curve.append((d, round(eq, 4)))
        if form == "house" and mode == "invested" and pos \
                and eq <= 0.85 * episode_start and d != days[-1]:
            halts.append({"signal_date": d, "signal_close": round(eq, 2),
                          "floor": round(0.85 * episode_start, 2)})
            halt_date = d
            mode = "liquidate"
    peak = -1.0; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    final = curve[-1][1] if curve else START_CASH
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "zeroed": sorted(set(zeroed)), "curve": curve}

def buyhold(start, end):
    days = [d for d in CAL if start <= d <= end]
    sh = (START_CASH * (1 - COST)) / SPY[days[0]]
    gross = sh * SPY[days[-1]]
    return round(gross - gross * COST - SELL_FEE, 2)

def period_distribution(curve):
    """Quarterly (rebalance-tempo) distribution from a daily equity curve:
    period = interval between successive rebalance execution dates present
    in the curve span (plus the head/tail stubs). REPORTING STANDARD fields."""
    bounds = sorted({ex for _, ex in SCHED})
    days = [d for d, _ in curve]
    eq = dict(curve)
    cuts = [days[0]] + [b for b in bounds if days[0] < b < days[-1]] + [days[-1]]
    rets = []
    for a, b in zip(cuts, cuts[1:]):
        if eq[a] > 0:
            rets.append((b, (eq[b] / eq[a] - 1) * 100))
    vals = [r for _, r in rets]
    n = len(vals)
    svals = sorted(vals)
    med = svals[n // 2] if n % 2 else (svals[n // 2 - 1] + svals[n // 2]) / 2
    longest_loss = 0; cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        longest_loss = max(longest_loss, cur)
    high = -1; last_high = None; max_gap = 0
    for d, v in curve:
        if v > high:
            high = v
            if last_high is not None:
                max_gap = max(max_gap, (date.fromisoformat(d) - date.fromisoformat(last_high)).days)
            last_high = d
    return {"periods": n,
            "period_returns_pct": {b: round(r, 2) for b, r in rets},
            "pct_profitable": round(100.0 * sum(1 for v in vals if v > 0) / n, 1) if n else None,
            "median_pct": round(med, 2),
            "best_pct": round(max(vals), 2), "worst_pct": round(min(vals), 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": max_gap,
            "average_pct_secondary": round(sum(vals) / n, 2) if n else None}


def write_bytes(path, data):
    """Robust writer for this sandbox's flaky write gate: unbuffered 2KB
    slices; on PermissionError, wait and resume in append mode."""
    if isinstance(data, str):
        data = data.encode()
    pos = 0; mode = "wb"; attempts = 0
    while pos < len(data):
        try:
            with open(path, mode, buffering=0) as f:
                while pos < len(data):
                    pos += f.write(data[pos:pos + 2048])
        except PermissionError:
            attempts += 1
            if attempts > 90:
                raise
            time.sleep(20)
            mode = "ab"

def safe_dump(obj, path):
    write_bytes(path, json.dumps(obj, indent=1))

# ---------------- sweep ----------------
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF-A_2012-2019": ("2012-01-03", "2019-12-31"),
        "CONF-B_2020-2026": ("2020-01-02", "2026-11-20")}
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 100, "ALL"]
NATIVE_COUNT = 100
FORMS = ["native", "house"]

def cell(start, end, count, form):
    r = run(start, end, count, form)
    out = {k: v for k, v in r.items() if k != "curve"}
    if count == "ALL":
        out["placebo_beaten"] = None
        out["placebo_note"] = "degenerate: count covers the whole eligible pool; random draw = the ranked set"
    else:
        twins = [run(start, end, count, form, seed=s)["final"] for s in range(20)]
        out["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
        out["placebo_median"] = round(sorted(twins)[10], 2)
        out["placebo_finals"] = twins
    return r, out

def main():
    t0 = time.time()
    result = {"family": "low-volatility (S&P 500 Low Volatility construction)",
              "spec": "SWEEP-SPEC.md (frozen before runs)",
              "count_convention": "sweep varies how many of the lowest-vol names are held; weights among those held stay inverse-vol as published",
              "native_count": NATIVE_COUNT,
              "roads": ROADS, "spy": {}, "cells": {}, "curves": {},
              "distributions": {}, "confirmation": {},
              "eligible_counts_sample": {}}
    for road, (s, e) in ROADS.items():
        result["spy"][road] = buyhold(s, e)
    for ref, ex in SCHED:
        if ex in ("2010-02-19", "2016-11-18", "2019-02-15", "2023-02-17", "2026-02-20"):
            result["eligible_counts_sample"][ex] = len(vols_at(ref))
    rp = os.path.join(HERE, "results.json")
    if os.path.exists(rp):
        try:
            prev = json.load(open(rp))
        except Exception:
            prev = {}
        result["cells"].update(prev.get("cells", {}))
        result["curves"].update(prev.get("curves", {}))
        print("resumed cells:", sorted(result["cells"]), flush=True)
    for form in FORMS:
        for count in COUNTS:
            key = f"{form}|{count}"
            if key in result["cells"] and len(result["cells"][key]) == 4:
                print(f"{key}: skipped (checkpointed)", flush=True)
                continue
            result["cells"][key] = {}
            for road, (s, e) in ROADS.items():
                r, c = cell(s, e, count, form)
                result["cells"][key][road] = c
                if road == "LONG":
                    result["curves"][key] = r["curve"]
            print(f"{key}: " + " ".join(f"{rd} {result['cells'][key][rd]['final']}"
                  f" (pb {result['cells'][key][rd]['placebo_beaten']})" for rd in ROADS)
                  + f" ({time.time()-t0:.0f}s)", flush=True)
            ck = dict(result); ck["curves"] = {}
            safe_dump(ck, rp)
            safe_dump(result["curves"][key], os.path.join(HERE, f"curve_{key.replace('|', '_')}.json"))
    for key in list(result["curves"]):
        pass
    # winners + distributions (LONG road decides the winning count per form)
    winners = {}
    for form in FORMS:
        best = max(COUNTS, key=lambda c: result["cells"][f"{form}|{c}"]["LONG"]["final"])
        winners[form] = {"winning_count": best, "native_count": NATIVE_COUNT}
        for c in {best, NATIVE_COUNT}:
            key = f"{form}|{c}"
            if key not in result["curves"]:
                cf = os.path.join(HERE, f"curve_{key.replace('|', '_')}.json")
                if os.path.exists(cf):
                    result["curves"][key] = json.load(open(cf))
                else:
                    s0, e0 = ROADS["LONG"]
                    result["curves"][key] = run(s0, e0, c, form)["curve"]
            result["distributions"][key] = period_distribution(result["curves"][key])
    result["winners"] = winners
    # confirmation rule
    for form in FORMS:
        nk = f"{form}|{NATIVE_COUNT}"
        for count in COUNTS:
            if count in (NATIVE_COUNT, "ALL"):
                continue
            ck = f"{form}|{count}"
            if all(result["cells"][ck][r]["final"] > result["cells"][nk][r]["final"] for r in ROADS):
                entry = {"beats_native_all_roads": True, "windows": {}}
                for cname, (s, e) in CONF.items():
                    cand = run(s, e, count, form)["final"]
                    nat = run(s, e, NATIVE_COUNT, form)["final"]
                    entry["windows"][cname] = {"candidate": cand, "native": nat, "beats": cand > nat}
                entry["variant_candidate"] = all(w["beats"] for w in entry["windows"].values())
                result["confirmation"][ck] = entry
                print(f"CONFIRMATION {ck}: {entry}", flush=True)
    safe_dump(result, os.path.join(HERE, "results.json"))
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)

def cli(argv):
    """Stdout-only modes (used when the sandbox file-write gate is closed):
    cells <form> <count...>  -> one JSON line per road-cell (no curve)
    dist  <form> <count>     -> LONG period distribution + headline stats
    conf  <form> <count>     -> confirmation-window finals vs native count
    spy                      -> SPY buy-hold per road
    elig                     -> eligible-pool sizes at sampled refs"""
    mode = argv[1]
    if mode == "spy":
        print(json.dumps({r: buyhold(s, e) for r, (s, e) in ROADS.items()}))
        return
    if mode == "elig":
        out = {}
        for ref, ex in SCHED:
            out[ex] = len(vols_at(ref))
        print(json.dumps(out))
        return
    form = argv[2]
    counts = [("ALL" if c == "ALL" else int(c)) for c in argv[3:]]
    if mode == "cells":
        for count in counts:
            for road, (s, e) in ROADS.items():
                r, c = cell(s, e, count, form)
                c["form"] = form; c["count"] = str(count); c["road"] = road
                print("CELL " + json.dumps(c), flush=True)
        return
    if mode == "dist":
        count = counts[0]
        s, e = ROADS["LONG"]
        r = run(s, e, count, form)
        d = period_distribution(r["curve"])
        print("DIST " + json.dumps({"form": form, "count": str(count),
                                    "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                                    "costs": r["costs"], "orders": r["orders"],
                                    "halts": r["halts"], "dist": d}))
        return
    if mode == "conf":
        count = counts[0]
        out = {}
        for cname, (s, e) in CONF.items():
            out[cname] = {"candidate": run(s, e, count, form)["final"],
                          "native": run(s, e, NATIVE_COUNT, form)["final"]}
        print("CONF " + json.dumps({"form": form, "count": str(count), "windows": out}))
        return
    raise SystemExit(f"unknown mode {mode}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cli(sys.argv)
    else:
        main()
