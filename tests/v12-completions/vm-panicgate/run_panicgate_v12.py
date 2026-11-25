#!/usr/bin/env python3
"""
V12 CONSTRUCTED — Daniel & Moskowitz (2016) panic gate on the champion
value+momentum host. Simulation only. Spec frozen in CONSTRUCTION-SPEC.md
before this run; nothing here was tuned on results.

Host: v4 value-momentum-plainfloor engine imported verbatim (same as v5):
PIT Nov-2016 top-30 universe, quarterly top-5 by B/M + 12-1 momentum,
$100, costs 0.10%/side + $0.01/sell, plain -15% floor $85.

Gate (CONSTRUCTED, paper-exact inputs):
  IB   = SPY trailing 504-trading-day (24m) cumulative return < 0
  var  = variance of SPY daily simple returns, preceding 126 days
  expo = 1.00 if IB==0 else min(1, var_ref/var), var_ref = expanding PIT
         median of the 126d variance series. Monthly checkpoints
         (first trading day of month, signal from prior close, fill at
         that day's open, pro-rata). Quarterly targets scaled by expo.
Arms: ranked off/on; Arm A paired-seed placebos (20 seeds, gated+ungated);
Arm B shuffled-timing exposure placebos (20 seeds, ranked picks);
Arm C floorless diagnostics (ranked + Arm A seeds, CONT/VAL only).
"""
import importlib.util
import json
import math
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
SEEDS = list(range(1, 21))
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CONFIRM = ("2019-01-02", "2022-12-30")
BEAR_WIN = 504     # 24 months, paper-exact
VAR_WIN = 126      # paper-exact


# ------------------------------------------------------------ panic state
def build_spy_series(pb):
    bars = pb.bars["SPY"]
    dates = [b["d"] for b in bars]
    closes = [b["c"] for b in bars]
    rets = [None] + [closes[i] / closes[i - 1] - 1.0
                     for i in range(1, len(closes))]
    var_series = {}
    for i in range(VAR_WIN, len(closes)):
        seg = rets[i - VAR_WIN + 1: i + 1]
        var_series[i] = statistics.variance(seg)
    return dates, closes, var_series


def expo_at(spy, d, strict=False):
    """Exposure for decision date d. strict=True uses only bars < d
    (for fills at d's open); strict=False uses bars <= d (signal on
    close of d, fill next open). Returns (expo, info)."""
    dates, closes, var_series = spy
    idx = None
    for i, bd in enumerate(dates):
        if (bd < d) if strict else (bd <= d):
            idx = i
        else:
            break
    if idx is None or idx < BEAR_WIN or idx not in var_series:
        return 1.0, {"insufficient_history": True, "panic": False}
    mkt_ret = closes[idx] / closes[idx - BEAR_WIN] - 1.0
    bear = mkt_ret < 0
    vnow = var_series[idx]
    hist = [var_series[i] for i in range(VAR_WIN, idx + 1)]
    vref = statistics.median(hist)
    expo = 1.0 if not bear else min(1.0, vref / vnow)
    return expo, {"insufficient_history": False, "panic": bool(bear and expo < 1.0),
                  "bear": bool(bear), "mkt_ret_24m": round(mkt_ret, 4),
                  "var_now": vnow, "var_ref": vref, "exposure": round(expo, 4)}


def month_key(d):
    return d[:7]


def monthly_expo_map(pb, spy, start, end):
    """{month: expo} using strict (prior-close) evaluation at the first
    trading day of each month in the window."""
    days = [d for d in pb.dates if start <= d <= end]
    out = {}
    seen = set()
    for d in days:
        mk = month_key(d)
        if mk not in seen:
            seen.add(mk)
            out[mk] = expo_at(spy, d, strict=True)
    return out


# ------------------------------------------------------------ gated engine
def run_pot(pb, spy, equity_rows, shares_rows, start, end, floor0,
            expo_mode="off", expo_map=None, placebo_rng=None, label=""):
    """Champion run_pot copy with the [GATE] monthly exposure overlay.
    expo_mode: 'off' | 'on' | 'map' (expo_map: {month: (expo, info)})."""
    cash = START_CASH
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    gate_log = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    checkpoints = set()
    seen = set()
    for d in days:
        if month_key(d) not in seen:
            seen.add(month_key(d))
            checkpoints.add(d)
    pending = None
    cur_expo = 1.0

    def expo_for(d, strict):
        if expo_mode == "off":
            return 1.0, {}
        if expo_mode == "on":
            return expo_at(spy, d, strict=strict)
        return expo_map.get(month_key(d), (1.0, {}))

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

    def execute_exposure_adjust(d, target_expo):
        """Pro-rata scale holdings at d's open so invested = expo * pv."""
        opens = {}
        for t in positions:
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        invested = sum(positions[t] * opens[t] for t in opens)
        pv = cash + invested
        if invested <= 0.005 or pv <= 0:
            return
        target_inv = target_expo * pv
        factor = target_inv / invested
        if abs(factor - 1.0) < 0.005:
            return
        targets = {t: positions[t] * opens[t] * factor for t in opens}
        execute_rebalance(d, targets)

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # [GATE] monthly checkpoint: adjust at today's open (expo from
        # prior close). Skipped on selection dates (selection applies
        # the same month's expo to its targets) and when flat.
        if expo_mode != "off" and d in checkpoints and d not in sel_set and positions:
            ex, info = expo_for(d, strict=True)
            if abs(ex - cur_expo) > 0.005:
                execute_exposure_adjust(d, ex)
                gate_log.append({"date": d, "kind": "monthly_adjust",
                                 "exposure": round(ex, 4), **{
                                     k: info.get(k) for k in
                                     ("bear", "mkt_ret_24m", "insufficient_history")}})
            cur_expo = ex
        if d in sel_set:
            scores = {}
            for t in UNIVERSE:
                be = E.pit_value(equity_rows.get(t, []), d)
                so = E.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
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
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                # Frozen spec SS3.2/SS3.4: exposure state is the monthly
                # checkpoint state, computed from the PRIOR close
                # (strict=True) -- the same state the monthly overlay
                # uses. (An earlier draft evaluated selections on the
                # selection day's own close; that deviated from the spec
                # and is documented in RESULTS.md.)
                ex, info = expo_for(d, strict=True)
                cur_expo = ex
                gate_log.append({"date": d, "kind": "selection",
                                 "exposure": round(ex, 4), **{
                                     k: info.get(k) for k in
                                     ("bear", "mkt_ret_24m", "insufficient_history")}})
                each = pv * ex / 5.0
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
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "gate_log": gate_log}
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
            "halt_info": None, "curve": curve, "gate_log": gate_log}


# ------------------------------------------------------------------ utils
def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "curve": [[d, round(v, 2)] for d, v in curve],
            "gate_log": r["gate_log"]}


def dist(finals, rows, ranked_final):
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    return {"median": round(statistics.median(srt), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "seeds_beaten": below, "rows": rows}


def run_window(pb, spy, eq, sh, name, window, full_arms=True):
    ws, we = window
    print(f"===== {name} {ws} -> {we} =====", flush=True)
    out = {"window": [ws, we]}
    # replication: gate off must reproduce the champion plain-floor finals
    ru = run_pot(pb, spy, eq, sh, ws, we, FLOOR0, expo_mode="off", label=f"{name} OFF")
    rg = run_pot(pb, spy, eq, sh, ws, we, FLOOR0, expo_mode="on", label=f"{name} ON")
    su, sg = stats(ru), stats(rg)
    spy_net, _ = E.spy_net(pb, ws, we, START_CASH)
    out["spy_net_final"] = round(spy_net, 2)
    out["ranked_ungated"] = su
    out["ranked_gated"] = sg
    print(f"  ranked OFF ${su['final']:,.2f} | ON ${sg['final']:,.2f} | SPY ${spy_net:,.2f}", flush=True)
    if not full_arms:
        return out
    # Arm B: shuffled-timing exposure placebos on ranked picks
    emap = monthly_expo_map(pb, spy, ws, we)
    months = sorted(emap)
    values = [emap[m] for m in months]
    avg_expo = round(sum(v[0] for v in values) / len(values), 4)
    out["avg_monthly_exposure"] = avg_expo
    shuf_finals, shuf_rows = [], []
    for s in SEEDS:
        rng = random.Random(9000 + s)
        perm = values[:]
        rng.shuffle(perm)
        smap = {m: perm[i] for i, m in enumerate(months)}
        r = run_pot(pb, spy, eq, sh, ws, we, FLOOR0, expo_mode="map",
                    expo_map=smap, label=f"{name} SHUF {s}")
        shuf_finals.append(r["final"])
        shuf_rows.append({"seed": s, "final": round(r["final"], 2),
                          "halted": r["halted"]})
        print(f"  armB seed {s:2d}: ${r['final']:,.2f} halted={r['halted']}", flush=True)
    out["armB_shuffled_timing"] = dist(shuf_finals, shuf_rows, sg["final"])
    # Arm A: paired-seed placebos, gated + ungated (+ floorless)
    rows_off, rows_on, rows_off_nf, rows_on_nf = [], [], [], []
    for s in SEEDS:
        ro = run_pot(pb, spy, eq, sh, ws, we, FLOOR0, expo_mode="off",
                     placebo_rng=random.Random(s), label=f"{name} P{s} OFF")
        rn = run_pot(pb, spy, eq, sh, ws, we, FLOOR0, expo_mode="on",
                     placebo_rng=random.Random(s), label=f"{name} P{s} ON")
        rows_off.append({"seed": s, "final": round(ro["final"], 2), "halted": ro["halted"]})
        rows_on.append({"seed": s, "final": round(rn["final"], 2), "halted": rn["halted"]})
        print(f"  armA seed {s:2d}: off ${ro['final']:,.2f} on ${rn['final']:,.2f}", flush=True)
        if name in ("CONT", "VAL"):
            rnf_o = run_pot(pb, spy, eq, sh, ws, we, -1e18, expo_mode="off",
                            placebo_rng=random.Random(s), label=f"{name} P{s} OFF NF")
            rnf_n = run_pot(pb, spy, eq, sh, ws, we, -1e18, expo_mode="on",
                            placebo_rng=random.Random(s), label=f"{name} P{s} ON NF")
            rows_off_nf.append({"seed": s, "final": round(rnf_o["final"], 2), "halted": None})
            rows_on_nf.append({"seed": s, "final": round(rnf_n["final"], 2), "halted": None})
    fo = [r["final"] for r in rows_off]
    fn = [r["final"] for r in rows_on]
    paired = [round(b - a, 2) for a, b in zip(fo, fn)]
    out["armA_paired_placebos"] = {
        "ungated": dist(fo, rows_off, su["final"]),
        "gated": dist(fn, rows_on, sg["final"]),
        "paired_diff_on_minus_off": paired,
        "paired_median_diff": round(statistics.median(paired), 2),
        "seeds_gate_helped": sum(1 for x in paired if x > 0),
        "seeds_gate_hurt": sum(1 for x in paired if x < 0)}
    # Arm C: floorless ranked
    if name in ("CONT", "VAL"):
        ru_nf = run_pot(pb, spy, eq, sh, ws, we, -1e18, expo_mode="off", label=f"{name} OFF NF")
        rg_nf = run_pot(pb, spy, eq, sh, ws, we, -1e18, expo_mode="on", label=f"{name} ON NF")
        out["armC_floorless"] = {
            "ranked_ungated_final": round(ru_nf["final"], 2),
            "ranked_gated_final": round(rg_nf["final"], 2),
            "ranked_ungated_maxdd_pct": stats(ru_nf)["max_drawdown_pct"],
            "ranked_gated_maxdd_pct": stats(rg_nf)["max_drawdown_pct"],
            "twins_ungated": dist([r["final"] for r in rows_off_nf], rows_off_nf,
                                  round(ru_nf["final"], 2)),
            "twins_gated": dist([r["final"] for r in rows_on_nf], rows_on_nf,
                                round(rg_nf["final"], 2))}
        print(f"  armC floorless: off ${ru_nf['final']:,.2f} on ${rg_nf['final']:,.2f}", flush=True)
    return out


def main():
    pb, eq, sh = build_inputs()
    spy = build_spy_series(pb)
    out = {"family": "vm-panicgate",
           "construction": "Daniel-Moskowitz panic state (24m bear x 126d market variance), "
                           "monthly inverse-variance exposure in bear state, on champion V+M host. CONSTRUCTED.",
           "champions": {"CONT": 544.47, "VAL": 288.05},
           "v5_house_gate": {"CONT": 426.25, "VAL": 285.60}}
    # replication assertions vs champion plain-floor published finals
    out["CONT"] = run_window(pb, spy, eq, sh, "CONT", CONT)
    assert abs(out["CONT"]["ranked_ungated"]["final"] - 544.47) < 0.01, \
        f"CONT replication failed: {out['CONT']['ranked_ungated']['final']}"
    out["VAL"] = run_window(pb, spy, eq, sh, "VAL", VAL)
    assert abs(out["VAL"]["ranked_ungated"]["final"] - 288.05) < 0.01, \
        f"VAL replication failed: {out['VAL']['ranked_ungated']['final']}"
    print("replication OK: ungated CONT $544.47 / VAL $288.05 reproduced", flush=True)
    out["CONFIRM"] = run_window(pb, spy, eq, sh, "CONFIRM", CONFIRM, full_arms=False)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
