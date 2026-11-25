#!/usr/bin/env python3
"""
V13 BEST-RULES — LADDER-ABLATION (profit-ladder ablation family).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

HOST: champion V+M published form (PIT EDGAR book-to-market + 12-1
momentum, percentile ranks averaged, top 5, equal weight, quarterly
re-pick, next-open execution, honest top-30 pond PIT at road start,
program costs 0.10%/side + $0.01/sell). The ladder is the only variable.

MY LADDER (frozen):
  - Base phase: adopted plain floor = 85% of episode start balance;
    breach -> liquidate next open, 90-day cash sit-out, ONE restart
    (fresh episode scaled to restart balance); second base halt ends.
  - Arming: ratchet arms when a daily close >= 3.0x episode start.
  - Ratchet floor: 70% of highest close since episode start.
  - Ratchet breach: TRIM — sell 1/3 of every position at next open,
    proceeds to cash; run CONTINUES; cash redeploys at ordinary
    quarterly rebalances; ratchet disarms until a close exceeds the
    peak that triggered the trim (one trim per peak cycle).
  - Base floor stays live throughout, on total pot value incl. cash.

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
INTEGRITY GATE: house count-5 must reproduce published finals to the
cent before any v13 number counts.

CONFIRMATION (pre-registered): only if my ladder beats the plain-floor
host on any road -> fresh-$100 calendar folds 2017..2026 + DECADE
half-windows, my schedule vs plain-floor host; >=6/10 folds AND
>=1/2 halves required.
"""
import importlib.util
import json
import os
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
COUNT = 5
ARM_MULT = 3.0
TRAIL = 0.70
TRIM_FRAC = 1.0 / 3.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)
START_CASH = S.START_CASH


def run_ladder_episode(pb, dec, sel_set, start, end, start_cash, count,
                       placebo_rng=None):
    """One episode under my trim-ladder schedule. Same rebalance/cost
    mechanics as the chassis; floor is dynamic; ratchet breach trims
    instead of halting. Returns halt_type None | 'base' (ratchet never
    halts the run)."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    pending_trim = False
    base_floor = round(0.85 * start_cash, 2)
    arm_level = ARM_MULT * start_cash
    peak = start_cash
    armed_date = None
    disarmed_until_above = None  # trigger peak while disarmed post-trim
    events = []
    trims = []

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

    def execute_trim(d):
        nonlocal cash, total_costs
        banked = 0.0
        for t in list(positions):
            b = pb.bar(t, d)
            if not b:
                continue
            sh = positions[t] * TRIM_FRAC
            val = sh * b["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            banked += val - c
            positions[t] -= sh
            trades.append((d, t, "SELL-TRIM", sh, b["o"], val, c))
            if positions[t] < 1e-9:
                del positions[t]
        return banked

    for di, d in enumerate(days):
        if pending_trim:
            banked = execute_trim(d)
            trims[-1]["execution_date"] = d
            trims[-1]["cash_banked"] = round(banked, 2)
            pending_trim = False
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = min(count, len(pool))
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                pv = portfolio_close(d)
                each = pv / k
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v > peak:
            peak = v
        if disarmed_until_above is not None and v > disarmed_until_above:
            events.append({"event": "rearmed_new_peak", "date": d,
                           "close": round(v, 2),
                           "prior_trigger_peak": round(disarmed_until_above, 2)})
            disarmed_until_above = None
        if armed_date is None and disarmed_until_above is None and peak >= arm_level:
            armed_date = d
            events.append({"event": "armed", "date": d,
                           "peak_close": round(peak, 2),
                           "floor_after_arm": round(max(base_floor, TRAIL * peak), 2)})
        armed = armed_date is not None and disarmed_until_above is None
        ratchet_floor = TRAIL * peak if armed else None
        # Ratchet breach -> schedule a trim at next open (never a halt).
        if (armed and ratchet_floor > base_floor and v <= ratchet_floor
                and di < len(days) - 1):
            trims.append({"signal_date": d, "signal_close": round(v, 2),
                          "floor_in_effect": round(ratchet_floor, 2),
                          "peak_close": round(peak, 2),
                          "trim_fraction": TRIM_FRAC})
            events.append({"event": "trim_signal", "date": d,
                           "signal_close": round(v, 2),
                           "floor_in_effect": round(ratchet_floor, 2),
                           "peak_close": round(peak, 2)})
            pending_trim = True
            disarmed_until_above = peak
        # Base floor breach -> halt (adopted chassis behavior).
        if v <= base_floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": round(base_floor, 2),
                         "peak_close": round(peak, 2), "type": "base"}
            events.append({"event": "halt_base", "date": d,
                           "signal_close": round(v, 2),
                           "floor_in_effect": round(base_floor, 2),
                           "peak_close": round(peak, 2)})
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "halt_type": "base", "curve": curve, "events": events,
                    "trims": trims, "armed_date": armed_date,
                    "peak": round(peak, 2)}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "halt_type": None, "curve": curve, "events": events,
            "trims": trims, "armed_date": armed_date,
            "peak": round(peak, 2)}


def run_my_ladder(pb, dec, sel_dates, start, end, count, placebo_seed=None):
    import random as _r
    rng = _r.Random(placebo_seed) if placebo_seed is not None else None
    sel_set = set(sel_dates)
    r1 = run_ladder_episode(pb, dec, sel_set, start, end, START_CASH,
                            count, placebo_rng=rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halts": 0, "restart": None, "second_halt": None,
           "events": list(r1["events"]), "trims": list(r1["trims"]),
           "armed_date": r1["armed_date"], "peak_close": r1["peak"]}
    if r1["halted"] is None:
        return out
    out["halts"] = 1
    liq = r1["end"]
    cash = r1["final"]
    day90 = date.fromisoformat(liq).toordinal() + 90
    restart = None
    for cand in sel_dates:
        if date.fromisoformat(cand).toordinal() >= day90:
            restart = cand
            break
    out["restart"] = {"halt_signal_date": r1["halted"],
                      "liquidation_date": liq, "restart_date": restart,
                      "restart_balance": round(cash, 2),
                      "episode2_base_floor": round(0.85 * cash, 2),
                      "episode2_arm_level": round(ARM_MULT * cash, 2)}
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        out["ended_by"] = "base_no_restart_date"
        return out
    r2 = run_ladder_episode(pb, dec, sel_set, restart, end, cash, count,
                            placebo_rng=rng)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    out["events"] += list(r2["events"])
    out["trims"] += list(r2["trims"])
    out["episode2"] = {"armed_date": r2["armed_date"], "peak": r2["peak"]}
    if r2["halted"] is not None:
        out["halts"] = 2
        out["second_halt"] = {"signal_date": r2["halted"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2),
                              "type": r2["halt_type"]}
        out["ended_by"] = r2["halt_type"]
        out["curve"].append((end, r2["final"]))
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "ladder-ablation (profit-ladder ablation family)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "host": "champion V+M published form: B/M + 12-1 momentum, top 5, "
                "equal weight, quarterly, next-open, PIT top-30 pond",
        "my_ladder": {"base_floor": "85% of episode start",
                      "arm": "close >= 3.0x episode start",
                      "ratchet_floor": "70% of highest close since episode start",
                      "ratchet_breach": "trim 1/3 of every position at next "
                                        "open to cash; run continues; cash "
                                        "redeploys at next quarterly rebalance; "
                                        "ratchet disarms until a close exceeds "
                                        "the triggering peak",
                      "base_breach": "liquidate, 90-day sit-out, one restart"},
        "published_ladder_form_finals": {"LONG": 85.34, "DECADE": 124.20,
                                         "CONT": 95.53, "VAL": 288.05},
        "plain_floor_host_finals": {"LONG": 1415.62, "DECADE": 667.35,
                                    "CONT": 544.47, "VAL": 288.05},
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)

    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    results["long_pond"] = pondL

    road_specs = [
        ("DECADE", pb, dec_fixed, "2016-11-21", END),
        ("CONT", pb, dec_fixed, "2019-01-02", END),
        ("VAL", pb, dec_fixed, "2023-01-03", END),
        ("LONG", pbL, dec_long, "2010-01-04", END),
    ]

    expect = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    plain_runs = {}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, decx, sel, s, e, COUNT)
        ok = abs(round(r["final"], 2) - expect[name]) < 0.02
        results["integrity"][name] = {"expected_plain_floor_count5": expect[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name} plain-floor-5: ${r['final']:,.2f} expected "
              f"${expect[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"
        plain_runs[name] = (sel, r)

    beat_any = False
    for name, pbx, decx, s, e in road_specs:
        sel, pr = plain_runs[name]
        spy = S.spy_final(pbx, s, e)
        mine = run_my_ladder(pbx, decx, sel, s, e, COUNT)
        unf = S.run_native(pbx, decx, sel, s, e, COUNT)
        mdiag = S.diagnostics(mine["curve"])
        pdiag = S.diagnostics(pr["curve"])
        udiag = S.diagnostics(unf["curve"])
        # Counterfactual for each trim: plain host's value on the signal
        # date and at the next quarterly selection after the trim (the
        # moment the trimmed cash would have been redeployed).
        plain_curve = dict(pr["curve"])
        plain_dates = sorted(plain_curve)
        for tr in mine["trims"]:
            sd = tr["signal_date"]
            tr["plain_host_close_on_signal_date"] = (
                round(plain_curve[sd], 2) if sd in plain_curve else None)
            nxt = [x for x in sel if x > sd]
            if nxt and nxt[0] in plain_curve:
                tr["plain_host_close_at_next_selection"] = round(plain_curve[nxt[0]], 2)
                tr["next_selection_date"] = nxt[0]
        pfinals = []
        for seed in SEEDS:
            prr = run_my_ladder(pbx, decx, sel, s, e, COUNT, placebo_seed=seed)
            pfinals.append(round(prr["final"], 2))
        beaten = sum(1 for f in pfinals if f < mine["final"])
        dist = S.period_distribution([(d, v) for d, v in mine["curve"]], sel)
        pdist = S.period_distribution([(d, v) for d, v in pr["curve"]], sel)
        beat = round(mine["final"], 2) > expect[name]
        beat_any = beat_any or beat
        results["roads"][name] = {
            "window": [s, e], "spy_final": spy,
            "my_ladder": {"final": round(mine["final"], 2),
                          "costs": round(mine["costs"], 2),
                          "orders": mine["orders"], "halts": mine["halts"],
                          "restart": mine["restart"],
                          "second_halt": mine["second_halt"],
                          "ended_by": mine.get("ended_by"),
                          "armed_date": mine["armed_date"],
                          "peak_close": mine["peak_close"],
                          "events": mine["events"],
                          "trims": mine["trims"],
                          "n_trims": len(mine["trims"]),
                          "episode2": mine.get("episode2"),
                          "max_dd_pct": mdiag["max_dd_pct"],
                          "max_dd_date": mdiag["max_dd_date"],
                          "worst_close": mdiag["worst_close"],
                          "worst_close_date": mdiag["worst_close_date"],
                          "placebo_beaten": beaten,
                          "placebo_finals": pfinals,
                          "beats_plain_floor_host": beat,
                          "period_distribution": dist,
                          "curve": [[d, round(v, 4)] for d, v in mine["curve"]]},
            "plain_floor_host": {
                "final": round(pr["final"], 2), "costs": round(pr["costs"], 2),
                "orders": pr["orders"], "halts": pr["halts"],
                "max_dd_pct": pdiag["max_dd_pct"],
                "max_dd_date": pdiag["max_dd_date"],
                "period_distribution": pdist,
                "curve": [[d, round(v, 4)] for d, v in pr["curve"]]},
            "unfloored_host": {
                "final": round(unf["final"], 2), "costs": round(unf["costs"], 2),
                "orders": unf["orders"],
                "max_dd_pct": udiag["max_dd_pct"],
                "max_dd_date": udiag["max_dd_date"]},
            "published_ladder_form": {
                "final": results["published_ladder_form_finals"][name]},
        }
        print(f"{name} MY-TRIM-LADDER: ${mine['final']:,.2f} "
              f"(plain ${expect[name]:,.2f}, unfloored ${unf['final']:,.2f}, "
              f"SPY ${spy:,.2f}) placebos {beaten}/20 "
              f"maxDD {mdiag['max_dd_pct']}% halts={mine['halts']} "
              f"trims={len(mine['trims'])} armed={mine['armed_date']}",
              flush=True)

    if beat_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rc = run_my_ladder(pb, dec_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, COUNT)
            folds[str(yr)] = {"my_ladder_final": round(rc["final"], 2),
                              "plain_floor_final": round(rp["final"], 2),
                              "my_ladder_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                              "my_ladder_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rc = run_my_ladder(pb, dec_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, COUNT)
            halves[hn] = {"my_ladder_final": round(rc["final"], 2),
                          "plain_floor_final": round(rp["final"], 2),
                          "my_ladder_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                          "my_ladder_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_ladder_win"])
        hwins = sum(1 for v in halves.values() if v["my_ladder_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my ladder vs plain-floor host",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={results['confirmation']['confirmed']}", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
