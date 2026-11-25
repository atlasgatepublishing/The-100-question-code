#!/usr/bin/env python3
"""V13 BEST RULES — N-2 CORRELATION-REGIME SWITCH (invented rule X2).
Simulation only. Spec: BEST-RULES-SPEC.md in this folder, frozen before
this run. Nothing in the spec was revised after any result was seen.

MY FORM (the spec in one breath): the published statistic untouched
(mean pairwise Pearson correlation of daily returns, trailing 60 trading
days, complete-window pond names, point-in-time); decisions QUARTERLY
(first trading day of Jan/Apr/Jul/Oct) instead of monthly; regime test
unchanged (C vs expanding median of all prior readings, now quarterly
readings from 2010); legs unchanged (LOW = equal-weight pond, HIGH =
SPY); NEW maintenance — the pond is rebalanced to equal weight on every
decision date while held; NO floor. Placebos: 20 seeds, my mechanics
with flip timing randomized over the road's decision dates, flip count
matched. Static-leg control beside every road: the same pond, bought at
the first decision date, rebalanced quarterly, never switched.

INTEGRITY GATE (runs first, aborts on failure):
  (1) the original v10 plumbing (integrity copy of the v8 engine +
      driver.py's construction) reproduces the published form on the
      full roads: SPY $822.94/$367.80/$313.62/$187.77 and published
      finals LONG $1,120.65 / DECADE $446.12 / CONT $358.94 /
      VAL $219.77, no halts;
  (2) this folder's own engine, run in published mode (monthly
      decisions, no rebalancing, no floor), matches those finals to
      the cent (the floor never fired on any road, so no-floor must
      equal the v9-wrapped record).

DATA (read-only): program pxfull payloads in
backtests/v7/long-hold/data/ plus pxfull_GOOGL.json in the v10 folder —
the identical sources the v10 record used. Costs: program standard,
0.10% of trade value per side + $0.01 per sell order. $100 pots.
"""
import importlib.util, json, math, os, random, statistics, time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
V10 = os.path.join(BT, "v10-retest", "novel-x2-correlation-switch")

spec_m = importlib.util.spec_from_file_location(
    "x2orig", os.path.join(V10, "integrity", "novel-x2-correlation-switch.py"))
M = importlib.util.module_from_spec(spec_m); spec_m.loader.exec_module(M)

# ------------------------------------------------------------------ data
def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(V10, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

POND = M.POND
BARS = {t: pxfull(t) for t in POND + ["SPY"]}
CAL = [b["d"] for b in BARS["SPY"]]
CIDX = {d: i for i, d in enumerate(CAL)}
CLOSES = {t: {b["d"]: b["c"] for b in bl} for t, bl in BARS.items()}
BOOK = M.Book(BARS, CAL)

ARR = np.full((len(POND), len(CAL)), np.nan)
for ti, t in enumerate(POND):
    cm = CLOSES[t]
    for d, v in cm.items():
        if d in CIDX:
            ARR[ti, CIDX[d]] = v

def stat_C(i):
    """Identical to the v10 sweep's statistic (proven there to reproduce
    the original engine's readings): mean pairwise Pearson correlation
    over the 61 closes ending at the prior close; complete names only."""
    if i < 61:
        return None, []
    win = ARR[:, i - 61:i]
    ok = ~np.isnan(win).any(axis=1)
    names = [POND[k] for k in range(len(POND)) if ok[k]]
    if len(names) < 2:
        return None, names
    sub = win[ok]
    rets = sub[:, 1:] / sub[:, :-1] - 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        cc = np.corrcoef(rets)
    iu = np.triu_indices(len(names), k=1)
    vals = cc[iu]
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None, names
    return float(vals.mean()), names

def quarterly_dates():
    out, seen = [], set()
    for d in CAL:
        y, m = int(d[:4]), int(d[5:7])
        key = (y, (m - 1) // 3)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

def build_quarterly_regime():
    """Quarterly readings from 2010; regime vs expanding median of prior
    quarterly readings. Returns (regime, scoreable, readings)."""
    regime, scoreable, readings = {}, {}, []
    prior = []
    for d in quarterly_dates():
        if d < "2010-01-01":
            continue
        C, names = stat_C(CIDX[d])
        if C is None:
            continue
        scoreable[d] = names
        med = statistics.median(prior) if prior else None
        readings.append({"date": d, "C": round(C, 6),
                         "median_prior": (round(med, 6) if med is not None
                                          else None)})
        if prior:
            regime[d] = "POND" if C <= med else "SPY"
        prior.append(C)
    return regime, scoreable, readings

QREGIME, QSCORE, QREADINGS = build_quarterly_regime()

def scoreable_fn(scoreable):
    keys = sorted(scoreable)
    def f(d):
        elig = [x for x in keys if x <= d]
        return scoreable[max(elig)] if elig else []
    return f

Q_NAMES = scoreable_fn(QSCORE)

# ------------------------------------------------------- benchmarks (SPY)
def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    by = {b["d"]: b for b in BARS["SPY"]}
    sh = (cash / 1.001) / by[days[0]]["o"]
    val = sh * by[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)

def spy_maxdd(start, end):
    days = [d for d in CAL if start <= d <= end]
    by = {b["d"]: b for b in BARS["SPY"]}
    peak, maxdd = -1.0, 0.0
    for d in days:
        v = by[d]["c"]
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return round(maxdd * 100, 2)

# ------------------------------------------------------------- my engine
def run_switch(start, end, targets, names_fn, rebalance):
    """targets: {date: 'POND'|'SPY'} decision dates. Mechanics follow the
    published engine's primitives exactly: sells at the decision open
    (0.10% + $0.01/order), then buys (0.10%); SPY buy = cash/1.001; pond
    buy = equal split of post-sell cash. If rebalance and the target is
    POND while already holding the pond, trade only the drift back to
    equal weight (target = equity at the decision open / tradeable
    names). No floor. End of window: liquidate at the final close."""
    days = [d for d in CAL if start <= d <= end]
    cash = 100.0
    positions = {}
    holding = None
    trades = []
    total_costs = 0.0
    curve = []
    flips = 0
    days_in = {"POND": 0, "SPY": 0, "CASH": 0}

    def close_val(d):
        v = cash
        for t, sh in positions.items():
            c = BOOK.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def sell_shares(d, t, sh, tag):
        nonlocal cash, total_costs
        b = BOOK.bar(t, d)
        if not b or sh <= 0:
            return
        val = sh * b["o"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, t, tag, sh, b["o"], val, c))
        positions[t] -= sh
        if positions[t] <= 1e-12:
            del positions[t]

    def sell_all(d):
        for t in list(positions):
            sell_shares(d, t, positions[t], "SELL")

    def buy_leg(d, target):
        nonlocal cash, total_costs
        if target == "SPY":
            b = BOOK.bar("SPY", d)
            if not b:
                return
            buy_val = cash / 1.001
            if buy_val <= 0.005:
                return
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            positions["SPY"] = positions.get("SPY", 0.0) + sh
            trades.append((d, "SPY", "BUY", sh, b["o"], buy_val, c))
        else:
            names = [t for t in names_fn(d) if BOOK.bar(t, d)]
            if not names:
                return
            each = cash / len(names)
            for t in names:
                b = BOOK.bar(t, d)
                buy_val = min(each, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / b["o"]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, b["o"], buy_val, c))

    def rebalance_pond(d):
        nonlocal cash, total_costs
        names = [t for t in names_fn(d) if BOOK.bar(t, d)]
        if not names:
            return
        equity = cash
        for t, sh in positions.items():
            b = BOOK.bar(t, d)
            if b:
                equity += sh * b["o"]
        target = equity / len(names)
        # sells first: overweight drift only
        for t in names:
            if t in positions:
                b = BOOK.bar(t, d)
                cur = positions[t] * b["o"]
                if cur > target + 0.005:
                    sell_shares(d, t, (cur - target) / b["o"], "SELL-RB")
        # then buys: underweight drift only
        for t in names:
            b = BOOK.bar(t, d)
            cur = positions.get(t, 0.0) * b["o"]
            deficit = target - cur
            if deficit > 0.005:
                buy_val = min(deficit, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / b["o"]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY-RB", sh, b["o"], buy_val, c))

    for d in days:
        if d in targets:
            target = targets[d]
            if holding is None:
                buy_leg(d, target)
                holding = target
            elif target != holding:
                sell_all(d)
                buy_leg(d, target)
                holding = target
                flips += 1
            elif target == "POND" and rebalance:
                rebalance_pond(d)
        curve.append((d, close_val(d)))
        days_in[holding if holding else "CASH"] += 1
    last = days[-1]
    for t in list(positions):
        c_ = BOOK.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "flips": flips, "curve": curve,
            "days_in": days_in}

def curve_stats(curve):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "year_end_closes": year_end}

def quarter_distribution(curve, start_value=100.0):
    """Period = calendar quarter, values at each quarter's last curve
    date in the window (final partial quarter included)."""
    qend = {}
    for d, v in curve:
        qend[(d[:4], (int(d[5:7]) - 1) // 3)] = v
    vals = [qend[k] for k in sorted(qend)]
    rets = []
    prev = start_value
    for v in vals:
        rets.append(v / prev - 1.0)
        prev = v
    n = len(rets)
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (quarters, quarter-end series)
    peak = start_value
    since = stretch = 0
    for v in vals:
        if v > peak:
            peak = v
            since = 0
        else:
            since += 1
            stretch = max(stretch, since)
    return {"periods": n,
            "pct_positive": round(100.0 * pos / n, 1) if n else None,
            "median_pct": round(statistics.median(rets) * 100, 2) if n else None,
            "best_pct": round(max(rets) * 100, 2) if n else None,
            "worst_pct": round(min(rets) * 100, 2) if n else None,
            "longest_losing_streak": longest,
            "longest_stretch_between_highs_qtrs": stretch,
            "mean_pct_secondary": round(statistics.mean(rets) * 100, 2) if n else None}

# ------------------------------------------------------- integrity gate
def gate_original_plumbing():
    """Replicates backtests/v10-retest/novel-x2-correlation-switch/
    driver.py exactly: original engine, monthly readings gated to
    2010-01, v9 wrapper. Returns {window: (final, halts)}."""
    import inspect
    src = inspect.getsource(M.compute_readings).replace('"2016-12"', '"2010-01"')
    ns = dict(M.__dict__)
    exec(compile(src, "readings2010", "exec"), ns)
    readings = ns["compute_readings"](CAL, CLOSES)
    prior, regime, scoreable = [], {}, {}
    for r in readings:
        if prior:
            regime[r["date"]] = "POND" if r["C"] <= statistics.median(prior) else "SPY"
        prior.append(r["C"])
        scoreable[r["date"]] = r["scoreable"]

    def pond_names(d):
        elig = [x for x in scoreable if x <= d]
        return scoreable[max(elig)] if elig else []

    def run_once(s, e, switches, cash, floor):
        M.START_CASH = cash; M.FLOOR = floor
        r = M.run_pot(BOOK, s, e, switches, pond_names)
        M.START_CASH = 100.0; M.FLOOR = 85.0
        return r

    def run_v9(s, e):
        dec = [r["date"] for r in readings if s <= r["date"] <= e
               and r["date"] in regime]
        sw = {d: regime[d] for d in dec}
        r1 = run_once(s, e, sw, 100.0, 85.0)
        eps = [r1]
        if r1["halted"]:
            elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
            if elig <= e:
                dec2 = [d for d in dec if d >= elig]
                r2 = run_once(elig, e, {d: regime[d] for d in dec2},
                              r1["final"], 0.85 * r1["final"])
                eps.append(r2)
        return round(eps[-1]["final"], 2), [e_["halted"] for e_ in eps if e_["halted"]]

    out = {}
    for w, (s, e) in WINDOWS.items():
        out[w] = run_v9(s, e)
    return out, regime, scoreable, readings

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}
PUBLISHED = {"LONG": 1120.65, "DECADE": 446.12, "CONT": 358.94, "VAL": 219.77}
PUBLISHED_DD = {"LONG": 33.63, "DECADE": 33.71, "CONT": 33.75, "VAL": 16.04}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def main():
    out = {"family": "novel-x2-correlation-switch",
           "form": "v13 best rules: quarterly decisions, maintained EW pond leg, no floor",
           "integrity": {}, "roads": {}}

    # ---- gate 1: original plumbing reproduces the published record
    gate, mregime, mscore, mreadings = gate_original_plumbing()
    m_names = scoreable_fn(mscore)
    gate_ok = True
    for w, (s, e) in WINDOWS.items():
        fin, halts = gate[w]
        spy = spy_net(s, e)
        ok = (fin == PUBLISHED[w] and not halts)
        gate_ok = gate_ok and ok
        out["integrity"][w] = {"published_final": PUBLISHED[w],
                               "gate_final": fin, "halts": halts,
                               "spy_net": spy, "match": ok}
        print(f"GATE1 {w}: published=${PUBLISHED[w]} gate=${fin} "
              f"halts={halts} SPY=${spy} match={ok}", flush=True)
    assert gate_ok, "integrity gate 1 FAILED — aborting before any v13 number"

    # ---- gate 2: my engine in published mode (monthly, drift, no floor)
    for w, (s, e) in WINDOWS.items():
        dec = [r["date"] for r in mreadings if s <= r["date"] <= e
               and r["date"] in mregime]
        sw = {d: mregime[d] for d in dec}
        r = run_switch(s, e, sw, m_names, rebalance=False)
        ok = r["final"] == PUBLISHED[w]
        out["integrity"][w]["my_engine_published_mode"] = r["final"]
        out["integrity"][w]["my_engine_match"] = ok
        print(f"GATE2 {w}: my-engine published mode=${r['final']} "
              f"expected=${PUBLISHED[w]} match={ok}", flush=True)
        assert ok, f"integrity gate 2 FAILED on {w} — aborting"

    # ---- my form, per road
    for w, (s, e) in WINDOWS.items():
        dec = [d for d in sorted(QREGIME) if s <= d <= e]
        targets = {d: QREGIME[d] for d in dec}
        mine = run_switch(s, e, targets, Q_NAMES, rebalance=True)
        mstats = curve_stats(mine["curve"])

        # static-leg control: same maintained pond, never switched
        ctrl_rebal = run_switch(s, e, {d: "POND" for d in dec}, Q_NAMES,
                                rebalance=True)
        # drift pond: published maintenance (enter once, never trade)
        ctrl_drift = run_switch(s, e, {dec[0]: "POND"}, Q_NAMES,
                                rebalance=False)
        cstats = curve_stats(ctrl_rebal["curve"])
        dstats = curve_stats(ctrl_drift["curve"])

        # placebos: my mechanics, timing randomized over decision dates
        init_asset = QREGIME[dec[0]]
        pool = dec[1:]
        k = mine["flips"]
        pfinals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            fdates = sorted(rng.sample(pool, k)) if k else []
            psw = {dec[0]: init_asset}
            cur = init_asset
            for fd in fdates:
                cur = "SPY" if cur == "POND" else "POND"
                psw[fd] = cur
            pr = run_switch(s, e, psw, Q_NAMES, rebalance=True)
            pfinals.append(pr["final"])
        beat = sum(1 for f in pfinals if mine["final"] > f)
        ps = sorted(pfinals)

        spy = spy_net(s, e)
        spydd = spy_maxdd(s, e)
        road = {
            "window": [s, e],
            "my_rules": {"final": mine["final"], "costs": mine["costs"],
                         "orders": mine["orders"], "flips": mine["flips"],
                         "decisions": len(dec), "days_in": mine["days_in"],
                         **mstats,
                         "distribution_quarters": quarter_distribution(mine["curve"]),
                         "decisions_detail": [
                             {"date": d, "C": next(r["C"] for r in QREADINGS
                                                   if r["date"] == d),
                              "median_prior": next(r["median_prior"] for r in QREADINGS
                                                   if r["date"] == d),
                              "regime": QREGIME[d]} for d in dec],
                         "equity_curve": [[d, round(v, 4)] for d, v in mine["curve"]]},
            "static_control_rebalanced_pond": {
                "final": ctrl_rebal["final"], "costs": ctrl_rebal["costs"],
                "orders": ctrl_rebal["orders"], **cstats,
                "distribution_quarters": quarter_distribution(ctrl_rebal["curve"]),
                "equity_curve": [[d, round(v, 4)] for d, v in ctrl_rebal["curve"]]},
            "static_control_drift_pond": {
                "final": ctrl_drift["final"], "costs": ctrl_drift["costs"],
                "orders": ctrl_drift["orders"], **dstats},
            "spy_buy_hold": {"final": spy, "max_dd_pct": spydd},
            "published_form": {"final": PUBLISHED[w],
                               "max_dd_pct": PUBLISHED_DD[w]},
            "champion_vm": CHAMPION[w],
            "decomposition": {
                "static_leg_effect_drift_minus_spy": round(ctrl_drift["final"] - spy, 2),
                "maintenance_effect_rebal_minus_drift": round(ctrl_rebal["final"] - ctrl_drift["final"], 2),
                "switch_timing_effect_mine_minus_rebal_control": round(mine["final"] - ctrl_rebal["final"], 2),
                "mine_minus_spy": round(mine["final"] - spy, 2),
                "mine_minus_published": round(mine["final"] - PUBLISHED[w], 2)},
            "placebo": {"finals": ps, "median": round(statistics.median(pfinals), 2),
                        "best": ps[-1], "worst": ps[0], "beat": beat,
                        "flips_matched": k,
                        "design": "my mechanics (quarterly cadence + pond "
                                  "rebalancing), flip dates uniform over the "
                                  "road's decision dates after the first, "
                                  "same initial asset, seeds 1..20"}}
        out["roads"][w] = road
        print(f"{w}: MINE=${mine['final']} (DD {mstats['max_dd_pct']}%, "
              f"flips {mine['flips']}, costs ${mine['costs']}) | "
              f"ctrl-rebal=${ctrl_rebal['final']} ctrl-drift=${ctrl_drift['final']} "
              f"SPY=${spy} published=${PUBLISHED[w]} | timing effect="
              f"${road['decomposition']['switch_timing_effect_mine_minus_rebal_control']} "
              f"| placebo beat {beat}/20 median ${road['placebo']['median']}",
              flush=True)

    out["quarterly_readings"] = QREADINGS
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
