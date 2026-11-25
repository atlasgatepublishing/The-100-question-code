#!/usr/bin/env python3
"""GMMA v13 BEST RULES run — implements BEST-RULES-SPEC.md exactly (frozen
before this run). Group-mean reduction of Guppy's two ribbons:
  S = mean of trader EMAs (3,5,8,10,12,15); L = mean of investor EMAs
  (30,35,40,45,50,60). Entry (flat->long): SPY S>L AND pond breadth >= 50%
  (share of pond names with own S>L). Exit (long->flat): SPY S<L only.
  No floor, no stop, no CBL. Daily close decision, next-open execution.
  $100 pot, stocks program costs 0.10%/side + $0.01 sell fee.
Loaders/engine/period-stats/placebo chassis copied from the v12 hunt-gmma
run (read-only shared inputs). Simulation only."""
import json, os, random, statistics, time
import numpy as np
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
SHORT = [3, 5, 8, 10, 12, 15]
LONGP = [30, 35, 40, 45, 50, 60]
START = 100.0
SCOST = 0.001; SFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB_A = {"LONG": 333.99, "DECADE": 239.49, "CONT": 192.40, "VAL": 156.66}

def load_stock(sym):
    p = os.path.join(PXDIR, f"pxfull_{sym}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    d, o, h, l, c = [], [], [], [], []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        dt = date.fromordinal(date(1970, 1, 1).toordinal() + t // 86400)
        d.append(dt.toordinal()); o.append(q["open"][i] * ratio)
        h.append(q["high"][i] * ratio); l.append(q["low"][i] * ratio); c.append(adj[i])
    if len(c) < 100:
        return None
    return {"d": d, "o": o, "h": h, "l": l, "c": c}

def ema(arr, n):
    out = [None] * len(arr); k = 2.0 / (n + 1)
    s = None
    for i, v in enumerate(arr):
        if i == n - 1:
            s = sum(arr[:n]) / n; out[i] = s
        elif i >= n:
            s = (v - s) * k + s; out[i] = s
    return out

def group_means(c):
    """Returns (S, L) lists of group-mean EMAs (None until EMA-60 warm)."""
    es = {n: ema(c, n) for n in SHORT + LONGP}
    n = len(c); S = [None] * n; L = [None] * n
    for i in range(n):
        if es[60][i] is None:
            continue
        S[i] = sum(es[p][i] for p in SHORT) / 6.0
        L[i] = sum(es[p][i] for p in LONGP) / 6.0
    return S, L

def simulate(s, tgt, i0, i1, cost=SCOST, sell_fee=SFEE):
    """Decide close t -> execute open t+1; liquidate at final close.
    NO floor (spec 3.6)."""
    d, o, c = s["d"], s["o"], s["c"]
    cash = START; shares = 0.0; costs = 0.0; orders = 0
    curve = []; peak = START; maxdd = 0.0
    for t in range(i0, i1 + 1):
        if t > i0:
            desired = tgt[t - 1]
            if desired == 1 and shares == 0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / o[t]; cash = 0.0; costs += fee; orders += 1
            elif desired == 0 and shares > 0:
                v = shares * o[t]; fee = v * cost + sell_fee
                cash = v - fee; costs += fee; shares = 0.0; orders += 1
        eq = cash + shares * c[t]
        curve.append((d[t], eq))
        if eq > peak: peak = eq
        if peak > 0: maxdd = max(maxdd, (peak - eq) / peak)
    if shares > 0:
        v = shares * c[i1]; fee = v * cost + sell_fee
        cash = v - fee; costs += fee; orders += 1
        shares = 0.0
        curve[-1] = (d[i1], cash)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "orders": orders, "costs": round(costs, 2), "curve": curve}

def buy_hold(s, i0, i1, cost=SCOST, sell_fee=SFEE):
    o, c = s["o"], s["c"]
    bv = START / (1 + cost); sh = bv / o[i0]
    curve = [(s["d"][t], sh * c[t]) for t in range(i0, i1 + 1)]
    v = sh * c[i1]; fin = v - (v * cost + sell_fee)
    peak = START; maxdd = 0.0
    for _, vv in curve:
        peak = max(peak, vv); maxdd = max(maxdd, (peak - vv) / peak if peak > 0 else 0.0)
    return {"final": round(fin, 2), "max_dd_pct": round(maxdd * 100, 2), "curve": curve}

def period_stats(curve, tempo="M"):
    if tempo == "M":
        vals = []; last_key = None
        for ordv, v in curve:
            dt = date.fromordinal(ordv); key = (dt.year, dt.month)
            if key != last_key:
                vals.append(v); last_key = key
            else:
                vals[-1] = v
        series = [START] + vals
    else:
        series = [v for _, v in curve]
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst, "longest_between_highs": longest}

def placebo_series(s, st, i0, i1, cost=SCOST, seeds=20):
    """20-seed circular shifts of the position series, open-to-open replay
    with switch costs (v12 chassis method, single asset)."""
    finals = []
    rng = random.Random(20261122)
    o = np.array(s["o"][i0:i1 + 1], dtype=float)
    seg = np.array(st[i0 - 1:i1 - 1], dtype=float) if i0 >= 1 else np.array(st[i0:i1], dtype=float)
    m = min(len(seg), len(o) - 1)
    seg = seg[:m]
    oo = o[1:m + 1] / o[:m]
    for _ in range(seeds):
        shift = rng.randrange(1, len(seg))
        sh = np.roll(seg, shift)
        fac = np.where(sh > 0, oo, 1.0)
        prev = np.concatenate(([0.0], sh[:-1]))
        sw = (sh != prev).astype(float)
        fac = fac * (1.0 - cost) ** sw
        finals.append(round(float(np.prod(fac)) * START, 2))
    return finals

def idx_range(s, start_s, end_s):
    so = date(*map(int, start_s.split("-"))).toordinal()
    eo = date(*map(int, end_s.split("-"))).toordinal()
    idx = [i for i, dv in enumerate(s["d"]) if so <= dv <= eo]
    if len(idx) < 30 or idx[0] < 60:
        return None
    return idx[0], idx[-1]

def curve_out(curve, step=5):
    return [[date.fromordinal(dv).isoformat(), round(v, 2)] for dv, v in curve[::step]]

def main():
    t0 = time.time()
    symbols = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(PXDIR)
                     if fn.startswith("pxfull_"))
    print(f"pond symbols: {len(symbols)}", flush=True)
    spy = load_stock("SPY")
    assert spy is not None
    # ---- breadth: per-date bull/total counts across the pond (incl. SPY)
    bull = {}; tot = {}
    n_used = 0
    for sym in symbols:
        s = load_stock(sym)
        if s is None:
            continue
        n_used += 1
        S, L = group_means(s["c"])
        for i, dv in enumerate(s["d"]):
            if S[i] is None:
                continue
            tot[dv] = tot.get(dv, 0) + 1
            if S[i] > L[i]:
                bull[dv] = bull.get(dv, 0) + 1
    print(f"breadth built from {n_used} names in {time.time()-t0:.0f}s", flush=True)
    breadth = {}
    last = None
    for dv in sorted(tot):
        if tot[dv] >= 20:
            last = bull.get(dv, 0) / tot[dv]
        breadth[dv] = last
    # ---- SPY group means + frozen state machine (spec 3.4)
    Ss, Ls = group_means(spy["c"])
    n = len(spy["c"]); state = [0] * n; pos = 0
    for i in range(n):
        if Ss[i] is None:
            state[i] = 0; continue
        b = breadth.get(spy["d"][i])
        if pos == 0:
            if Ss[i] > Ls[i] and b is not None and b >= 0.50:
                pos = 1
        else:
            if Ss[i] < Ls[i]:
                pos = 0
        state[i] = pos
    exposure = round(100.0 * sum(state) / max(1, sum(1 for x in Ss if x is not None)), 1)
    print(f"SPY in-market share of warmed days: {exposure}%", flush=True)
    # ---- roads
    roads_out = {}
    for rname, (rs, re_) in ROADS.items():
        i0, i1 = idx_range(spy, rs, re_)
        r = simulate(spy, state, i0, i1)
        bh = buy_hold(spy, i0, i1)
        plac = placebo_series(spy, state, i0, i1)
        roads_out[rname] = {
            "window": [date.fromordinal(spy["d"][i0]).isoformat(),
                       date.fromordinal(spy["d"][i1]).isoformat()],
            "final": r["final"], "max_dd_pct": r["max_dd_pct"],
            "orders": r["orders"], "costs": r["costs"],
            "hold_final": bh["final"], "hold_max_dd_pct": bh["max_dd_pct"],
            "hold_ref": SPYREF[rname], "champion_vm": CHAMP[rname],
            "published_formA_native": PUB_A[rname],
            "beat_champion": r["final"] > CHAMP[rname],
            "beat_published": r["final"] > PUB_A[rname],
            "beat_hold": r["final"] > bh["final"],
            "period_stats_monthly": period_stats(r["curve"], "M"),
            "period_stats_monthly_hold": period_stats(bh["curve"], "M"),
            "placebo_20seed": {"finals": plac, "median": round(statistics.median(plac), 2),
                               "min": min(plac), "max": max(plac),
                               "seeds_beaten": sum(1 for x in plac if r["final"] > x)},
            "curve": curve_out(r["curve"], 5),
            "hold_curve": curve_out(bh["curve"], 5)}
        print(f"{rname}: best-rules {r['final']} (DD -{r['max_dd_pct']}%, {r['orders']} orders) "
              f"vs hold {bh['final']} (ref {SPYREF[rname]}) vs champ {CHAMP[rname]} "
              f"vs published A {PUB_A[rname]}; placebo med {roads_out[rname]['placebo_20seed']['median']} "
              f"beaten {roads_out[rname]['placebo_20seed']['seeds_beaten']}/20", flush=True)
    res = {"family": "GMMA (Guppy Multiple Moving Average) — hunt-gmma",
           "program": "v13 BEST RULES (spec frozen before run)",
           "spec": "BEST-RULES-SPEC.md",
           "rules": "S=mean(EMA 3,5,8,10,12,15), L=mean(EMA 30,35,40,45,50,60) on SPY; "
                    "entry S>L and pond breadth>=50%; exit S<L only; no floor/stop/CBL; "
                    "daily close -> next open; 0.10%/side + $0.01 sell fee; $100 pot",
           "breadth_names_used": n_used, "spy_in_market_pct_warmed": exposure,
           "roads": roads_out, "confirmation": None}
    # ---- confirmation (spec section 6) only if a road beats the champion
    beaten = [k for k, v in roads_out.items() if v["beat_champion"]]
    if beaten:
        conf = {}
        for rname in beaten:
            rs, re_ = ROADS[rname]
            so = date(*map(int, rs.split("-"))).toordinal()
            eo = date(*map(int, re_.split("-"))).toordinal()
            mid = date.fromordinal((so + eo) // 2)
            halves = {}
            for hname, (hs, he) in {"H1": (rs, mid.isoformat()), "H2": ((mid + __import__('datetime').timedelta(days=1)).isoformat(), re_)}.items():
                rng_ = idx_range(spy, hs, he)
                if rng_:
                    a, b = rng_
                    halves[hname] = {"window": [date.fromordinal(spy["d"][a]).isoformat(),
                                                date.fromordinal(spy["d"][b]).isoformat()],
                                     "final": simulate(spy, state, a, b)["final"],
                                     "hold_final": buy_hold(spy, a, b)["final"]}
            folds = {}
            for y in range(int(rs[:4]), int(re_[:4]) + 1):
                rng_ = idx_range(spy, f"{y}-01-01", f"{y}-12-31")
                if rng_ is None:
                    continue
                a, b = rng_
                if spy["d"][a] < so or spy["d"][b] > eo:
                    continue
                folds[str(y)] = {"final": simulate(spy, state, a, b)["final"],
                                 "hold_final": buy_hold(spy, a, b)["final"]}
            strat_f = [v["final"] for v in folds.values()]
            hold_f = [v["hold_final"] for v in folds.values()]
            halves_pass = all(v["final"] > v["hold_final"] and v["final"] > 100 for v in halves.values()) and len(halves) == 2
            folds_pass = (statistics.median(strat_f) > statistics.median(hold_f)
                          and statistics.median(strat_f) > 100
                          and sum(1 for a_, b_ in zip(strat_f, hold_f) if a_ > b_) >= len(folds) / 2)
            plac_pass = roads_out[rname]["placebo_20seed"]["median"] < roads_out[rname]["final"]
            conf[rname] = {"halves": halves, "halves_pass": halves_pass,
                           "yearly_folds": folds, "folds_pass": folds_pass,
                           "median_fold": round(statistics.median(strat_f), 2),
                           "median_fold_hold": round(statistics.median(hold_f), 2),
                           "placebo_pass": plac_pass,
                           "confirmed": bool(halves_pass and folds_pass and plac_pass)}
        res["confirmation"] = conf
        print("CONFIRMATION:", json.dumps(conf), flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f)
    print(f"wrote results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
