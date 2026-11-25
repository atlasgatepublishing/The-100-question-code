#!/usr/bin/env python3
"""
V13 BEST-RULES — VALUE+MOMENTUM + PANIC GATE (vm-panicgate).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: the v13 ungated host unchanged (PIT EDGAR book-to-market +
12-1 momentum, percentile ranks averaged, quarterly re-pick, next-open
execution, equal weight, honest top-30 pond PIT at each road start,
program costs 0.10%/side + $0.01/sell, top-2, NO floor) plus ONE change:
the Daniel & Moskowitz (2016) panic state as a DIAL. At each quarterly
selection date, from SPY only, point-in-time:
  bear    = trailing 12-month SPY return < 0
  vol_now = stdev of SPY daily log returns, trailing 60 trading days,
            annualized
  vol_ref = expanding PIT median of that same 60-day vol series
  PANIC   = bear AND vol_now > vol_ref
  expo    = 1.0 if not PANIC else min(1.0, max(0.50, vol_ref / vol_now))
That quarter's targets are scaled by expo; the remainder sits in cash.

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
The gated runner below is that module's run_episode copied with the
single [GATE] change in the selection block; floor is always None
(the host carries none). INTEGRITY: dial disabled must reproduce the
v13 host finals (LONG $2,923.60 / DECADE $906.90 / CONT $691.73 /
VAL $461.20) and house count-5 the published champion finals
(LONG $1,415.62 / DECADE $667.35 / CONT $544.47 / VAL $288.05).

CONFIRMATION (pre-registered in the spec): if the gated form beats
the published champion OR the ungated host on any road -> fresh-$100
calendar-year folds 2017..2026 + DECADE half-windows, gated vs BOTH
the ungated host and the published house form. Confirmed requires
>=6/10 folds AND >=1/2 halves against each comparator.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
COUNT = 2
START_CASH = 100.0
VOL_WIN = 60
BEAR_WIN = 252
EXPO_FLOOR = 0.50


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)


# ------------------------------------------------------------ panic dial
def panic_exposures(pb, sel_dates):
    """D&M panic state + dial exposure per selection date, SPY only.
    Returns {date: {panic, bear, mkt_ret_12m, vol_now, vol_ref, expo}}."""
    bars = pb.bars["SPY"]
    dates = [b["d"] for b in bars]
    closes = [b["c"] for b in bars]
    logret = [None] + [math.log(closes[i] / closes[i - 1])
                       for i in range(1, len(closes))]

    def rvol(end_idx):
        seg = logret[end_idx - VOL_WIN + 1: end_idx + 1]
        return statistics.stdev(seg) * math.sqrt(252)

    vol_series = {}
    for i in range(VOL_WIN, len(closes)):
        vol_series[i] = rvol(i)
    # expanding PIT median via incremental sorted insertion
    med_at = {}
    seen = []
    for i in range(VOL_WIN, len(closes)):
        bisect.insort(seen, vol_series[i])
        n = len(seen)
        med_at[i] = seen[n // 2] if n % 2 else 0.5 * (seen[n // 2 - 1] + seen[n // 2])

    out = {}
    for d in sel_dates:
        idx = bisect.bisect_right(dates, d) - 1
        if idx is None or idx < BEAR_WIN or idx not in vol_series:
            out[d] = {"panic": False, "bear": None, "mkt_ret_12m": None,
                      "vol_now": None, "vol_ref": None, "expo": 1.0,
                      "note": "insufficient SPY history"}
            continue
        mkt_ret = closes[idx] / closes[idx - BEAR_WIN] - 1.0
        bear = mkt_ret < 0
        vnow = vol_series[idx]
        vref = med_at[idx]
        panic = bool(bear and vnow > vref)
        expo = 1.0
        if panic:
            expo = min(1.0, max(EXPO_FLOOR, vref / vnow))
        out[d] = {"panic": panic, "bear": bool(bear),
                  "mkt_ret_12m": round(mkt_ret, 4),
                  "vol_now": round(vnow, 4), "vol_ref": round(vref, 4),
                  "expo": round(expo, 4)}
    return out


# ------------------------------------------------------------ gated engine
def run_gated(pb, dec, sel_dates, start, end, count, expo_map=None,
              placebo_seed=None):
    """Copy of S.run_episode with floor=None (host carries none) and the
    single [GATE] change: targets scaled by expo_map[selection date].
    expo_map=None (or all-1.0) must reproduce the ungated host exactly."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    sel_set = set(sel_dates)
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    gate_log = []
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
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = min(count, len(pool))
                if rng is not None:
                    picks = rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                pv = portfolio_close(d)
                # [GATE] the ONLY change vs the host runner
                expo = 1.0
                if expo_map is not None:
                    st = expo_map.get(d, {})
                    expo = st.get("expo", 1.0)
                    gate_log.append({"date": d, "panic": st.get("panic"),
                                     "bear": st.get("bear"),
                                     "mkt_ret_12m": st.get("mkt_ret_12m"),
                                     "vol_now": st.get("vol_now"),
                                     "vol_ref": st.get("vol_ref"),
                                     "expo": expo})
                each = pv * expo / k
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "orders": len(trades),
            "curve": curve, "gate_log": gate_log,
            "panic_quarters": sum(1 for g in gate_log if g["panic"])}


def pack(r, pb_dec_sel):
    diag = S.diagnostics(r["curve"])
    dist = S.period_distribution([(d, v) for d, v in r["curve"]], pb_dec_sel)
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": r["orders"], "max_dd_pct": diag["max_dd_pct"],
            "max_dd_date": diag["max_dd_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "period_distribution": dist,
            "curve": [[d, round(v, 4)] for d, v in r["curve"]]}


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "vm-panicgate (Value+Momentum + Daniel & Moskowitz panic gate)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"host": "v13 value-momentum: top-2, no floor, quarterly",
                     "gate": "D&M panic state as DIAL: expo = clamp(vol_ref/vol_now, 0.50, 1.00) when PANIC, else 1.0",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "published_form": {"description": "v5: binary 50% switch on top-5 + -15% floor host",
                           "finals": {"CONT": 426.25, "VAL": 285.60}},
        "champion_vm": {"LONG": 1415.62, "DECADE": 667.35,
                        "CONT": 544.47, "VAL": 288.05},
        "ungated_host_v13": {"LONG": 2923.60, "DECADE": 906.90,
                             "CONT": 691.73, "VAL": 461.20},
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    # ---------------- inputs (v12 chassis builders, read-only caches)
    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    expo_fixed = panic_exposures(pb, all_sel)

    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    expo_long = panic_exposures(pbL, selL_all)
    results["long_pond"] = pondL

    road_specs = [
        ("DECADE", pb, dec_fixed, expo_fixed, "2016-11-21", END),
        ("CONT", pb, dec_fixed, expo_fixed, "2019-01-02", END),
        ("VAL", pb, dec_fixed, expo_fixed, "2023-01-03", END),
        ("LONG", pbL, dec_long, expo_long, "2010-01-04", END),
    ]

    # ---------------- integrity: house count-5 = published champion
    expect_pub = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    for name, pbx, decx, expx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, decx, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - expect_pub[name]) < 0.02
        results["integrity"][f"house5_{name}"] = {
            "expected": expect_pub[name], "reproduced": round(r["final"], 2),
            "match": ok}
        print(f"INTEGRITY {name} house-5: ${r['final']:,.2f} expected "
              f"${expect_pub[name]} match={ok}", flush=True)
        assert ok, f"house-5 integrity failed on {name}"

    # ---------------- roads: gated vs ungated host, same code
    expect_host = {"DECADE": 906.90, "CONT": 691.73, "VAL": 461.20, "LONG": 2923.60}
    beat_champion_any = False
    beat_host_any = False
    for name, pbx, decx, expx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        ru = run_gated(pbx, decx, sel, s, e, COUNT, expo_map=None)
        ok = abs(round(ru["final"], 2) - expect_host[name]) < 0.02
        results["integrity"][f"host_{name}"] = {
            "expected_ungated_host": expect_host[name],
            "reproduced_gate_off": round(ru["final"], 2), "match": ok}
        print(f"INTEGRITY {name} gate-off host: ${ru['final']:,.2f} expected "
              f"${expect_host[name]} match={ok}", flush=True)
        assert ok, f"host integrity failed on {name}"

        rg = run_gated(pbx, decx, sel, s, e, COUNT, expo_map=expx)
        gu = pack(ru, sel)
        gg = pack(rg, sel)
        gg["panic_quarters"] = rg["panic_quarters"]
        gg["gate_log"] = rg["gate_log"]

        pu, pg = [], []
        for seed in SEEDS:
            pu.append(round(run_gated(pbx, decx, sel, s, e, COUNT,
                                      expo_map=None, placebo_seed=seed)["final"], 2))
            pg.append(round(run_gated(pbx, decx, sel, s, e, COUNT,
                                      expo_map=expx, placebo_seed=seed)["final"], 2))
        gu["placebo_finals"] = pu
        gu["placebo_beaten"] = sum(1 for f in pu if f < ru["final"])
        gg["placebo_finals"] = pg
        gg["placebo_beaten"] = sum(1 for f in pg if f < rg["final"])

        beat_c = round(rg["final"], 2) > expect_pub[name]
        beat_h = round(rg["final"], 2) > round(ru["final"], 2)
        beat_champion_any = beat_champion_any or beat_c
        beat_host_any = beat_host_any or beat_h
        gg["beats_champion"] = beat_c
        gg["beats_ungated_host"] = beat_h
        gg["gate_contribution_vs_host"] = round(rg["final"] - ru["final"], 2)
        results["roads"][name] = {"window": [s, e], "spy_final": spy,
                                  "gated": gg, "ungated_host": gu}
        print(f"{name} GATED-DIAL: ${rg['final']:,.2f} (host ${ru['final']:,.2f}, "
              f"champion ${expect_pub[name]:,.2f}, SPY ${spy:,.2f}) "
              f"panic_q={rg['panic_quarters']} placebos gated "
              f"{gg['placebo_beaten']}/20 ungated {gu['placebo_beaten']}/20 "
              f"maxDD gated {gg['max_dd_pct']}% host {gu['max_dd_pct']}%", flush=True)

    # ---------------- confirmation (Terry's rule, pre-registered)
    if beat_champion_any or beat_host_any:
        folds, halves = {}, {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rg = run_gated(pb, dec_fixed, sel, s, e, COUNT, expo_map=expo_fixed)
            ru = run_gated(pb, dec_fixed, sel, s, e, COUNT, expo_map=None)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            folds[str(yr)] = {
                "gated_final": round(rg["final"], 2),
                "ungated_host_final": round(ru["final"], 2),
                "published_final": round(rp["final"], 2),
                "gated_max_dd_pct": S.diagnostics(rg["curve"])["max_dd_pct"],
                "gated_beats_host": rg["final"] > ru["final"],
                "gated_beats_published": rg["final"] > rp["final"]}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rg = run_gated(pb, dec_fixed, sel, s, e, COUNT, expo_map=expo_fixed)
            ru = run_gated(pb, dec_fixed, sel, s, e, COUNT, expo_map=None)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            halves[hn] = {
                "gated_final": round(rg["final"], 2),
                "ungated_host_final": round(ru["final"], 2),
                "published_final": round(rp["final"], 2),
                "gated_max_dd_pct": S.diagnostics(rg["curve"])["max_dd_pct"],
                "gated_beats_host": rg["final"] > ru["final"],
                "gated_beats_published": rg["final"] > rp["final"]}
        fh = sum(1 for v in folds.values() if v["gated_beats_host"])
        fp = sum(1 for v in folds.values() if v["gated_beats_published"])
        hh = sum(1 for v in halves.values() if v["gated_beats_host"])
        hp = sum(1 for v in halves.values() if v["gated_beats_published"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; gated vs ungated host AND vs published "
                      "house form; bar >=6/10 folds AND >=1/2 halves vs each",
            "year_folds": folds,
            "fold_wins_vs_host": f"{fh}/10",
            "fold_wins_vs_published": f"{fp}/10",
            "half_windows": halves,
            "half_wins_vs_host": f"{hh}/2",
            "half_wins_vs_published": f"{hp}/2",
            "confirmed_vs_host": fh >= 6 and hh >= 1,
            "confirmed_vs_published": fp >= 6 and hp >= 1}
        print(f"CONFIRMATION: folds vs host {fh}/10, vs published {fp}/10; "
              f"halves vs host {hh}/2, vs published {hp}/2", flush=True)
    else:
        print("CONFIRMATION: not triggered (gated beat neither champion "
              "nor host on any road)", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
