#!/usr/bin/env python3
"""
V12 — aggressive-v3 (§6 NO-NATIVE-FORM program construction).
Simulation only, no broker orders.

The frozen spec is the program's own: the v2 aggressive engine as
parameterized by the v3 ablation study (backtests/v3/aggressive-v3.py),
in its two published configurations:
  BASE  = v2 as coded (ATR 1.5x, risk 1%)
  COMBO = A3+A6, the v3 study's selected form (ATR 1.0x, risk 2%)
Full spec: CONSTRUCTION-SPEC.md in this folder. No spec changes, no tuning.

PART A — VERIFICATION. The byte-identical original v3 engine (the copy
saved in backtests/v10-retest/aggressive-v3/) is re-run on the read-only
v3 cache for the design, validation and full-period windows, and every
final is compared to the published v3 record (aggressive-v3.md).

PART B — STANDARD ROADS. The v10 cadence-sweep chassis (imported
read-only from backtests/v10-retest/aggressive-v3/sweep_aggressive_v3.py:
v3 mechanics + v9 protection — plain -15% floor, no ladder, 90-day
sit-out, one restart, second breach ends the run) at the family's NATIVE
DAILY cadence only, on the program roads:
  LONG   2010-01-04 -> 2026-11-20   (extended-fetch data, see below)
  DECADE 2016-11-21 -> 2026-11-20   (v3 cache)
  CONT   2019-01-02 -> 2026-11-20   (v3 cache)
  VAL    2023-01-03 -> 2026-11-20   (v3 cache; first trading day of the
                                     original 2023-01-01 validation window)
Costs are the engine's own: 0.10%/side + $0.01 sell fee.
Placebos: v2's own design (as in v10) — entry_prob = real entries / road
trading days; per day, rng draw < entry_prob enters a uniformly random
free universe name through the identical try_enter path; identical exits
and protection. 20 seeds (1..20) per road per configuration.

DATA:
- v3 cache (read-only): backtests/v3/data/ — Yahoo daily OHLCV,
  split-adjusted, not dividend-adjusted, 2015-06-01 -> 2026-11-20.
- LONG data: this folder's data_long/ — same Yahoo chart API, same
  format, fetched 2008-01-02 -> 2026-11-22 (CONSTRUCTION-SPEC named
  convention "extended fetch, same source"). Verified before the runs:
  all 28,880 overlapping bars (10 symbols x 2,888 days) are identical to
  the v3 cache. DECADE is additionally run on the extended data as a
  cross-check (saved under decade_on_long_data).
- SPY road benchmarks: dividend-adjusted buy-and-hold from the read-only
  v7 long-hold cache (pxfull_SPY.json), program costs — the method that
  reproduces the program's DECADE reference $367.80.
"""
import importlib.util, json, os, random, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/aggressive-v3")
V3DATA = os.path.expanduser("~/workspace/stock-app/backtests/v3/data")
LONGDATA = os.path.join(HERE, "data_long")

sys.path.insert(0, V10)
import sweep_aggressive_v3 as sweep   # imports original_aggressive_v3 as sweep.m
m = sweep.m

START = m.START_CASH
COST_RATE, SELL_FEE = m.COST_RATE, m.SELL_FEE
BASE_CFG = dict(m.BASE_CFG)
COMBO_CFG = dict(m.BASE_CFG); COMBO_CFG.update({"atr_mult": 1.0, "base_risk": 0.02})
CONFIGS = [("combo", COMBO_CFG), ("base", BASE_CFG)]

ROADS_V3 = {"DECADE": ("2016-11-21", "2026-11-20"),
            "CONT": ("2019-01-02", "2026-11-20"),
            "VAL": ("2023-01-03", "2026-11-20")}
ROADS_LONG = {"LONG": ("2010-01-04", "2026-11-20")}

# ------------------------------------------------------------- SPY bench --
def spy_benchmark(start, end):
    path = os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    d = json.load(open(path))
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, t in enumerate(res["timestamp"]):
        if q["close"][i] is None:
            continue
        rows.append((datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                     q["open"][i], q["close"][i], adj[i]))
    rows = [r for r in rows if start <= r[0] <= end]
    o0, c0, a0 = rows[0][1], rows[0][2], rows[0][3]
    sh = START / ((o0 * a0 / c0) * (1 + COST_RATE))
    net = sh * rows[-1][3] * (1 - COST_RATE) - SELL_FEE
    peak, mdd = 0.0, 0.0
    for r in rows:
        peak = max(peak, r[3]); mdd = max(mdd, (peak - r[3]) / peak * 100)
    return round(net, 2), round(mdd, 2)

# ------------------------------------------------------- Part A: verify ---
def part_a():
    m.DATA = V3DATA
    D = m.load_data()
    published = {
        ("design", "base"): 105.50, ("design", "combo"): 123.42,
        ("validation", "base"): 90.48, ("validation", "combo"): 88.51,
        ("full", "base"): 103.80, ("full", "combo"): 118.56,
    }
    windows = {"design": m.DESIGN, "validation": m.VALIDATION,
               "full": ("2016-11-21", "2026-11-20")}
    out = {}
    for wname, win in windows.items():
        cal = m.calendar(D, *win)
        for cname, cfg in CONFIGS:
            sim = m.Sim(D, cal, dict(cfg)).run()
            st = sim.stats()
            pub = published[(wname, cname)]
            out[f"{wname}_{cname}"] = {
                "window": list(win), "published_final": pub,
                "reproduced_final": st["final_balance"],
                "match_to_cent": abs(st["final_balance"] - pub) < 0.005,
                "round_trips": st["round_trips"], "win_rate_pct": st["win_rate"],
                "max_dd_pct": st["max_drawdown_pct"], "costs": st["total_costs"],
                "halted": st["halted"]}
            print(f"A {wname:10s} {cname:5s} published ${pub:7.2f} "
                  f"reproduced ${st['final_balance']:7.2f} "
                  f"match={out[f'{wname}_{cname}']['match_to_cent']}", flush=True)
    return out

# --------------------------------------------------------- Part B: roads --
def run_roads(D, roads):
    out = {}
    for rname, (start, end) in roads.items():
        cal = m.calendar(D, start, end)
        cad = sweep.cadence_dates(cal, "daily")
        spy_final, spy_dd = spy_benchmark(start, end)
        road = {"window": [start, end], "n_days": len(cal),
                "spy_final": spy_final, "spy_max_dd_pct": spy_dd, "configs": {}}
        for cname, cfg in CONFIGS:
            sim = sweep.CadenceSim(D, cal, dict(cfg), cad).run()
            st = sim.stats()
            entry_prob = min(1.0, st["counters"]["entries"] / max(1, len(cad)))
            twins = []
            for seed in range(1, 21):
                rng = random.Random(seed)
                twin = sweep.CadenceSim(D, cal, dict(cfg), cad,
                                        placebo_rng=rng,
                                        entry_prob=entry_prob).run()
                twins.append(round(twin.cash, 2))
            beaten = sum(1 for t in twins if st["final"] > t)
            road["configs"][cname] = {
                "final": st["final"], "cagr_pct": st["cagr_pct"],
                "max_dd_pct": st["max_dd_pct"], "costs": st["costs"],
                "orders": st["orders"], "round_trips": st["round_trips"],
                "win_rate_pct": st["win_rate_pct"], "halts": st["halts"],
                "restart": st["restart"], "second_halt": st["second_halt"],
                "counters": st["counters"],
                "placebo": {"entry_prob": round(entry_prob, 4),
                            "twin_finals": twins, "seeds_beaten": beaten},
                "equity_curve": [[d, round(e, 2)] for d, e in sim.equity_curve]}
            print(f"B {rname:6s} {cname:5s} final ${st['final']:8.2f} "
                  f"DD {st['max_dd_pct']:5.2f}% costs ${st['costs']:6.2f} "
                  f"orders {st['orders']:4d} halts {len(st['halts'])} "
                  f"placebo {beaten}/20 SPY ${spy_final}", flush=True)
        out[rname] = road
    return out

def main():
    results = {"family": "aggressive-v3",
               "form": "program construction (v2 engine + v3 COMBO A3+A6); "
                       "no published original — see HUNT-LOG.md",
               "cadence": "daily (native)",
               "protection": "v9 plain -15% floor, no ladder (v10 chassis)",
               "costs": "0.10%/side + $0.01 sell fee"}
    results["verification_original_engine"] = part_a()
    m.DATA = V3DATA
    D3 = m.load_data()
    results["roads"] = run_roads(D3, ROADS_V3)
    m.DATA = LONGDATA
    DL = m.load_data()
    results["roads"].update(run_roads(DL, ROADS_LONG))
    # cross-check: DECADE on the extended data must equal DECADE on v3 cache
    results["decade_on_long_data"] = run_roads(DL, {"DECADE": ROADS_V3["DECADE"]})["DECADE"]
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("saved results.json")

if __name__ == "__main__":
    main()
