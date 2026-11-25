#!/usr/bin/env python3
"""V13 BEST RULES — crypto-x-timers. Spec: BEST-RULES-SPEC.md (frozen before run).
Reuses the v12 engine's frozen signal builders + data loaders (read-only import).
My chassis: weekly (7-bar) state checks for state gauges, Ichimoku exposure dial
(conditions met / 4), NO floor/chassis, 0.60%/side, next-open execution
(Bollinger native keeps its frozen at-close execution).
Roads: FULL (warm-up -> 2026-11-21), RECENT (2023-01-01 -> end),
MID fold (2019-01-01 -> 2022-12-31, confirmation only). Bar: own buy-and-hold.
Placebos: 20-seed circular shift of each coin's exposure series, pooled.
"""
import json, os, sys, math, random, statistics
from datetime import date

sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/crypto-x-timers"))
import run_timers as V12  # frozen builders/loaders, read-only

import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
END_ORD = date(2026, 11, 21).toordinal()
RECENT_ORD = date(2023, 1, 1).toordinal()
MID_ORD = date(2019, 1, 1).toordinal()

# ---------------- Ichimoku dial (exposure = native conditions met / 4) --------

def ichimoku_dial(s):
    n = len(s["c"]); h, l, c = s["h"], s["l"], s["c"]
    ten = [None] * n; kij = [None] * n; sa = [None] * n; sb = [None] * n
    for i in range(n):
        if i >= 8: ten[i] = V12._mid(h, l, i, 9)
        if i >= 25: kij[i] = V12._mid(h, l, i, 26)
        if i >= 51: sb[i] = V12._mid(h, l, i, 52)
        if ten[i] is not None and kij[i] is not None: sa[i] = (ten[i] + kij[i]) / 2.0
    expo = [0.0] * n
    for t in range(78, n):
        if sa[t - 26] is None or sb[t - 26] is None or ten[t] is None or kij[t] is None:
            continue
        cloud_hi = max(sa[t - 26], sb[t - 26])
        conds = [c[t] > cloud_hi, ten[t] > kij[t], c[t] > c[t - 26],
                 sa[t] is not None and sb[t] is not None and sa[t] > sb[t]]
        expo[t] = sum(1 for x in conds if x) / 4.0
    return expo, 78

# ---------------- fractional-exposure simulator -------------------------------

def simulate_frac(s, expo, start, end):
    """expo[t] decided at close t -> rebalance at open t+1. Costs on |traded|."""
    o, c = s["o"], s["c"]
    cash = 100.0; shares = 0.0; costs = 0.0; orders = 0
    curve = []; peak = 100.0; maxdd = 0.0
    for t in range(start, end):
        if t > start:
            target = expo[t - 1]
            eq_open = cash + shares * o[t]
            delta = target * eq_open - shares * o[t]
            if abs(delta) > 1e-9 and o[t] > 0:
                fee = abs(delta) * COST; costs += fee; orders += 1
                if delta > 0:
                    spend = min(delta, cash)
                    shares += spend * (1 - COST) / o[t]; cash -= spend
                else:
                    sell = min(-delta, shares * o[t])
                    shares -= sell / o[t]; cash += sell * (1 - COST)
        eq = cash + shares * c[t]
        curve.append((s["d"][t], eq))
        if eq > peak: peak = eq
        if peak > 0: maxdd = max(maxdd, (peak - eq) / peak)
    return {"final": round(curve[-1][1], 2) if curve else 100.0,
            "max_dd_pct": round(maxdd * 100, 2), "orders": orders,
            "costs": round(costs, 2), "curve": curve}

def buy_hold_we(s, start, end):
    o, c = s["o"], s["c"]
    sh = 100.0 * (1 - COST) / o[start]
    curve = [(s["d"][t], sh * c[t]) for t in range(start, end)]
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(maxdd * 100, 2),
            "curve": curve}

def bollinger_native_we(s, start, end):
    """V12 frozen Method I, at-the-close execution, window-limited.
    Also returns the implied daily position-state series (full length)."""
    c = s["c"]; n = len(c)
    mid, up, lo, bw = V12.bollinger_arrays(s)
    cash = 100.0; shares = 0.0; costs = 0.0; orders = 0; pos = 0
    curve = []; peak = 100.0; maxdd = 0.0
    state = [0] * n
    for t in range(n):
        if 144 <= t < end and t >= start:
            if pos == 1 and c[t] <= lo[t]:
                cash = shares * c[t] * (1 - COST); costs += shares * c[t] * COST
                shares = 0.0; pos = 0; orders += 1
            elif pos == 0:
                win = bw[t - 125:t + 1]
                squeeze = any(bw[u] is not None and bw[u] == min(win)
                              for u in range(max(19, t - 4), t + 1))
                if squeeze and c[t] > up[t]:
                    shares = cash * (1 - COST) / c[t]; costs += cash * COST
                    cash = 0.0; pos = 1; orders += 1
        state[t] = pos
        if t >= start and t < end:
            eq = cash + shares * c[t]
            curve.append((s["d"][t], eq))
            peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak > 0 else 0.0)
    return {"final": round(curve[-1][1], 2) if curve else 100.0,
            "max_dd_pct": round(maxdd * 100, 2), "orders": orders,
            "costs": round(costs, 2), "curve": curve}, state

# ---------------- windows ------------------------------------------------------

def first_idx(s, ordv):
    for i, dv in enumerate(s["d"]):
        if dv >= ordv:
            return i
    return None

def windows(s, warm):
    n = len(s["c"])
    out = {}
    if n - warm >= 30:
        out["FULL"] = (warm, n)
    rs = first_idx(s, RECENT_ORD)
    if rs is not None and rs > warm and n - rs >= 30:
        out["RECENT_2023"] = (rs, n)
    ms = first_idx(s, MID_ORD); me = first_idx(s, RECENT_ORD)
    if ms is not None and me is not None:
        ms2 = max(ms, warm)
        if me - ms2 >= 30 and ms2 > warm:
            out["MID_2019_2022"] = (ms2, me)
    return out

def pooled(cell):
    if not cell: return None
    finals = [v["final"] for v in cell.values()]
    holds = [v["hold_final"] for v in cell.values()]
    return {"coins": len(cell), "median_final": round(statistics.median(finals), 2),
            "median_hold": round(statistics.median(holds), 2),
            "coins_beating_hold": sum(1 for v in cell.values() if v["beat_hold"]),
            "mean_final_secondary": round(statistics.mean(finals), 2),
            "mean_hold_secondary": round(statistics.mean(holds), 2),
            "beats_hold_tests": (statistics.median(finals) > statistics.median(holds)
                                 and sum(1 for v in cell.values() if v["beat_hold"]) * 2 > len(cell))}

# ---------------- placebo (numpy replay of shifted exposure) -------------------

def placebo_pooled(items, seeds=20):
    """items: (series, expo, start, end). Circular shift per coin per seed."""
    rng = random.Random(20261122)
    seed_means = []; seed_medians = []
    for _ in range(seeds):
        finals = []
        for s, expo, start, end in items:
            o = np.array(s["o"][start:end], dtype=float)
            e = np.array(expo[start:end], dtype=float)
            if len(o) < 3:
                continue
            shift = rng.randrange(1, len(e))
            es = np.roll(e, shift)
            oo = np.empty_like(o); oo[0] = 1.0
            oo[1:] = o[1:] / o[:-1]
            fac = 1.0 + es[:-1] * (oo[1:] - 1.0)
            dexp = np.abs(np.diff(es, prepend=0.0))
            fac = fac * (1.0 - COST * dexp[1:])
            finals.append(100.0 * float(np.prod(fac)))
        if finals:
            seed_means.append(round(statistics.mean(finals), 2))
            seed_medians.append(round(statistics.median(finals), 2))
    return seed_means, seed_medians

# ---------------- driver --------------------------------------------------------

def run_gauge(data, btc, eth, builder, min_bars, kind):
    """builder(series, other) -> (expo_list, warm). kind: 'state' weekly-gated,
    'daily' ungated state, 'bollinger' dedicated engine."""
    cells = {"FULL": {}, "RECENT_2023": {}, "MID_2019_2022": {}}
    pitems = []
    for sym, s in data.items():
        if len(s["c"]) < min_bars:
            continue
        other = eth if sym == "BTC" else btc
        if kind == "bollinger":
            _, state = bollinger_native_we(s, 0, len(s["c"]))
            expo = [float(x) for x in state]; warm = 144
        else:
            expo, warm = builder(s, other)
            if kind == "state":
                expo = V12.gate(expo, warm, 7)
        wins = windows(s, warm)
        for wname, (a, b) in wins.items():
            if kind == "bollinger":
                r, _ = bollinger_native_we(s, a, b)
            else:
                r = simulate_frac(s, expo, a, b)
            bh = buy_hold_we(s, a, b)
            rec = {"final": r["final"], "hold_final": bh["final"],
                   "beat_hold": r["final"] > bh["final"],
                   "max_dd_pct": r["max_dd_pct"], "hold_max_dd_pct": bh["max_dd_pct"],
                   "orders": r["orders"], "costs": r["costs"],
                   "start": date.fromordinal(s["d"][a]).isoformat(),
                   "end": date.fromordinal(s["d"][b - 1]).isoformat()}
            if wname == "FULL":
                rec["period_stats_monthly"] = V12.period_stats(r["curve"], "M")
                if sym in ("BTC", "ETH"):
                    rec["curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)]
                                    for dv, v in r["curve"][::7]]
                    rec["hold_curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)]
                                         for dv, v in bh["curve"][::7]]
            cells[wname][sym] = rec
        if "FULL" in wins:
            a, b = wins["FULL"]
            pitems.append((s, expo, a, b))
    out = {}
    for wname, cell in cells.items():
        out[wname] = {"per_coin": cell, "pooled": pooled(cell)}
    sm, smed = placebo_pooled(pitems)
    real_mean = out["FULL"]["pooled"]["mean_final_secondary"] if out["FULL"]["pooled"] else None
    real_med = out["FULL"]["pooled"]["median_final"] if out["FULL"]["pooled"] else None
    out["placebo"] = {
        "design": "20-seed circular shift of each coin's exposure series (preserves time-in-market and switch count); numpy open-to-open replay at identical costs; Bollinger/Fibonacci position-state shifted the same way, replayed next-open (declared approximation)",
        "seed_pooled_means": sm, "seed_pooled_medians": smed,
        "seeds_beaten_by_real_mean": (sum(1 for x in sm if real_mean > x) if real_mean is not None else None),
        "seeds_beaten_by_real_median": (sum(1 for x in smed if real_med > x) if real_med is not None else None),
        "of": len(sm)}
    return out

def main():
    universe = V12.load_universe()
    data = {}
    for sym in universe:
        s = V12.load_series(sym)
        if s is not None:
            data[sym] = s
    btc, eth = data["BTC"], data["ETH"]

    gauges = {
        "golden_cross": ("Golden cross SMA50/200 — weekly checks, binary",
                         lambda s, o: V12.state_golden_cross(s), 230, "state"),
        "ichimoku_dial": ("Ichimoku — weekly checks, exposure = native conditions met / 4",
                          lambda s, o: ichimoku_dial(s), 108, "state"),
        "heikin_ashi": ("Heikin-Ashi native strong-trend — weekly checks, binary",
                        lambda s, o: V12.state_heikin_ashi(s, True), 40, "state"),
        "dow_theory": ("Dow Theory native (coin + BTC) — weekly checks, binary w/ hold-on-disagreement",
                       lambda s, o: V12.state_dow(s, o, True), 150, "state"),
        "pivots": ("Floor-trader pivots, monthly house form — daily state checks (line changes monthly)",
                   lambda s, o: V12.state_pivots(s), 62, "daily"),
        "fibonacci": ("Fibonacci 61.8% retracement — daily event form, native (no time exit)",
                      lambda s, o: V12.state_fibonacci(s, False), 150, "daily"),
        "bollinger": ("Bollinger squeeze Method I — daily event form, frozen at-close execution",
                      None, 174, "bollinger"),
        "presidential_A": ("Presidential cycle Form A — calendar",
                           lambda s, o: V12.state_presidential(s, False), 365, "daily"),
        "presidential_B": ("Presidential cycle Form B (sweet spot) — calendar",
                           lambda s, o: V12.state_presidential(s, True), 365, "daily"),
        "lunar_15d": ("Lunar new-moon 15-day window — calendar",
                      lambda s, o: V12.state_lunar(s, 7, False), 60, "daily"),
        "lunar_7d": ("Lunar new-moon 7-day window — calendar",
                     lambda s, o: V12.state_lunar(s, 3, False), 60, "daily"),
        "lunar_fullmoon_control": ("Lunar FULL-moon 15-day window — the papers' own control",
                                   lambda s, o: V12.state_lunar(s, 7, True), 60, "daily"),
    }

    results = {"meta": {
        "family": "crypto-x-timers (V13 best rules)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "coins_with_series": len(data), "cost_per_side": COST, "start_pot": 100.0,
        "chassis": "weekly 7-bar state checks (state gauges); Ichimoku dial = conditions/4; no floor, no chassis; event gauges daily; calendar gauges calendar",
        "roads": "FULL warm-up->2026-11-21; RECENT_2023 2023-01-01->end; MID_2019_2022 fold (confirmation)",
        "bar": "each coin's own buy-and-hold, identical window",
        "verdict_ceiling": "CANDIDATE"},
        "gauges": {}}

    for key, (label, builder, min_bars, kind) in gauges.items():
        g = run_gauge(data, btc, eth, builder, min_bars, kind)
        g["label"] = label
        results["gauges"][key] = g
        p = g["FULL"]["pooled"]; pl = g["placebo"]
        print(f"{key:26s} FULL median {p['median_final']:>10.2f} vs hold {p['median_hold']:>10.2f} "
              f"| coins beat {p['coins_beating_hold']}/{p['coins']} | placebo mean {pl['seeds_beaten_by_real_mean']}/20 "
              f"median {pl['seeds_beaten_by_real_median']}/20", flush=True)

    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
