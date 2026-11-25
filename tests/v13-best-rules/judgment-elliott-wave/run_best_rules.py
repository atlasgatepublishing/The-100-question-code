#!/usr/bin/env python3
"""Elliott Wave V13 BEST RULES run. Implements BEST-RULES-SPEC.md exactly:
SPY long/cash, daily closes, 5% zigzag pivots usable only from confirmation day,
in-progress impulse trading (wave-3 break of P1, wave-4 hold above P1, wave-5
break of P3), pre-committed invalidation lines (P2 / P4), dead counts never
relabeled, no alternates, costs 0.10%/side + $0.01 sell fee, cash 0%, $100 pots.
Placebos: 20-seed circular shifts of each road's daily target series.
JUDGMENT-CONSTRUCTED label permanent. Simulation only."""
import json, os, time, random
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
THR = 0.05
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_bars():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def build_pivots(days):
    """Zigzag 5% on daily closes. Pivot usable only from confirm_date onward."""
    pivots = []
    if not days:
        return pivots
    mode = None
    ex_p, ex_d = days[0][1], days[0][0]
    mn_p, mn_d = days[0][1], days[0][0]
    mx_p, mx_d = days[0][1], days[0][0]
    for d, p in days:
        if mode is None:
            if p < mn_p: mn_p, mn_d = p, d
            if p > mx_p: mx_p, mx_d = p, d
            if p >= mn_p * (1 + THR) and mn_d != d:
                pivots.append({"pivot_date": mn_d, "price": mn_p, "kind": "low", "confirm_date": d})
                mode, ex_p, ex_d = "up", p, d
            elif p <= mx_p * (1 - THR) and mx_d != d:
                pivots.append({"pivot_date": mx_d, "price": mx_p, "kind": "high", "confirm_date": d})
                mode, ex_p, ex_d = "down", p, d
        elif mode == "up":
            if p > ex_p: ex_p, ex_d = p, d
            if p <= ex_p * (1 - THR):
                pivots.append({"pivot_date": ex_d, "price": ex_p, "kind": "high", "confirm_date": d})
                mode, ex_p, ex_d = "down", p, d
        else:
            if p < ex_p: ex_p, ex_d = p, d
            if p >= ex_p * (1 + THR):
                pivots.append({"pivot_date": ex_d, "price": ex_p, "kind": "low", "confirm_date": d})
                mode, ex_p, ex_d = "up", p, d
    return pivots


def kinds(seq):
    return [p["kind"] for p in seq]


def s3_valid(p0, p1, p2):
    if not (p2["price"] > p0["price"]):
        return False
    l1 = p1["price"] - p0["price"]
    if l1 <= 0:
        return False
    retr = (p1["price"] - p2["price"]) / l1
    return 0.236 <= retr <= 0.786


def target_for(pivots, close):
    """Stateless daily target per spec, from confirmed pivots + today's close."""
    if len(pivots) < 3:
        return "CASH"
    last = pivots[-1]
    if last["kind"] == "low":
        if len(pivots) >= 5:
            w = pivots[-5:]
            if kinds(w) == ["low", "high", "low", "high", "low"]:
                p0, p1, p2, p3, p4 = [p["price"] for p in w]
                if p2 > p0 and p4 > p1 and (p3 - p2) >= (p1 - p0):
                    return "SPY" if close > p3 else "CASH"
                return "CASH"
        w = pivots[-3:]
        if kinds(w) == ["low", "high", "low"] and s3_valid(*w):
            return "SPY" if close > w[1]["price"] else "CASH"
        return "CASH"
    else:  # last pivot is a high
        if len(pivots) >= 6:
            w = pivots[-6:]
            if kinds(w) == ["low", "high", "low", "high", "low", "high"]:
                p0, p1, p2, p3, p4, p5 = [p["price"] for p in w]
                if p2 > p0 and p4 > p1 and (p3 - p2) >= (p1 - p0) and (p5 - p4) > 0:
                    return "CASH"  # impulse complete; correction expected
        if len(pivots) >= 4:
            w = pivots[-4:]
            if kinds(w) == ["low", "high", "low", "high"]:
                p0, p1, p2, p3 = [p["price"] for p in w]
                if p2 > p0 and (p3 - p2) >= (p1 - p0):
                    return "SPY" if close > p1 else "CASH"
        return "CASH"


def build_daily_targets(bars, pivots):
    """Target for every bar date; pivots filtered by confirm_date <= date."""
    targets = {}
    pi = 0
    avail = []
    for b in bars:
        while pi < len(pivots) and pivots[pi]["confirm_date"] <= b["d"]:
            avail.append(pivots[pi]); pi += 1
        targets[b["d"]] = target_for(avail, b["c"])
    return targets


def setup_log(bars, pivots):
    """Register S3/S5 setups at final-pivot confirmation; track invalidation.
    A setup invalidates on a close through its line before impulse completion,
    or when a later pivot breaks its rules (S3: later low pivot <= P1).
    Completion = the P5 high pivot of its chain confirms."""
    setups = []
    by_confirm = {}
    for idx, p in enumerate(pivots):
        by_confirm.setdefault(p["confirm_date"], []).append(idx)
    open_setups = []
    pi = 0
    for b in bars:
        d, close = b["d"], b["c"]
        new_pivots = []
        while pi < len(pivots) and pivots[pi]["confirm_date"] <= d:
            new_pivots.append(pi); pi += 1
        for idx in new_pivots:
            p = pivots[idx]
            # completion / evolution / rule-break checks for open setups
            still = []
            for s in open_setups:
                if s["type"] == "S3":
                    if p["kind"] == "high" and idx == s["last_pivot_idx"] + 2:
                        s["stage"] = "w4"  # P3 confirmed, still alive
                        still.append(s)
                    elif p["kind"] == "low" and idx == s["last_pivot_idx"] + 2:
                        # cannot happen (alternation), kept for safety
                        still.append(s)
                    elif p["kind"] == "low":
                        if p["price"] <= s["p1"]:
                            s["status"] = "invalidated"; s["end_date"] = d
                            s["reason"] = "later low pivot broke Rule 3 (P4 <= P1)"
                        else:
                            s["status"] = "evolved"; s["end_date"] = d
                            s["reason"] = "wave-4 low held above P1; chain continues as S5"
                        if s["status"] == "invalidated":
                            setups.append(s)
                        else:
                            setups.append(s)
                    elif p["kind"] == "high" and s.get("stage") == "w4":
                        s["status"] = "completed"; s["end_date"] = d
                        s["reason"] = "P5 high confirmed; impulse complete"
                        setups.append(s)
                    else:
                        still.append(s)
                else:  # S5: next pivot is the P5 high -> completion
                    if p["kind"] == "high":
                        s["status"] = "completed"; s["end_date"] = d
                        s["reason"] = "P5 high confirmed; impulse complete"
                        setups.append(s)
                    else:
                        still.append(s)
            open_setups = still
            # register new setups ending at this pivot
            if p["kind"] == "low" and idx >= 2:
                w = pivots[idx - 2:idx + 1]
                if kinds(w) == ["low", "high", "low"] and s3_valid(*w):
                    open_setups.append({"type": "S3", "reg_date": d,
                                        "pivot_dates": [x["pivot_date"] for x in w],
                                        "line": w[2]["price"], "p1": w[1]["price"],
                                        "last_pivot_idx": idx, "status": "open"})
                if idx >= 4:
                    w5 = pivots[idx - 4:idx + 1]
                    if kinds(w5) == ["low", "high", "low", "high", "low"]:
                        p0, p1, p2, p3, p4 = [x["price"] for x in w5]
                        if p2 > p0 and p4 > p1 and (p3 - p2) >= (p1 - p0):
                            open_setups.append({"type": "S5", "reg_date": d,
                                                "pivot_dates": [x["pivot_date"] for x in w5],
                                                "line": p4, "p1": p1,
                                                "last_pivot_idx": idx, "status": "open"})
        # invalidation by close through the line
        still = []
        for s in open_setups:
            if close <= s["line"]:
                s["status"] = "invalidated"; s["end_date"] = d
                s["reason"] = "close through invalidation line"
                setups.append(s)
            else:
                still.append(s)
        open_setups = still
    for s in open_setups:
        s["status"] = "still_open"; s["end_date"] = None
        setups.append(s)
    return setups


def run(bars, by_date, targets_by_day, start, end, target_override=None):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    all_days = [b["d"] for b in bars]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    days_invested = 0
    # initial pending: target decided on the last trading day before the road
    prev_days = [d for d in all_days if d < days[0]]
    pending = None
    if target_override is not None:
        pending = target_override[0]
        road_targets = target_override[1]
    else:
        if prev_days:
            pending = targets_by_day[prev_days[-1]]
        road_targets = None
    for i, d in enumerate(days):
        bar = by_date[d]
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                bv = cash / 1.001; c = bv * 0.001
                shares = bv / bar["o"]; cash -= bv + c; costs += c
                trades.append([d, "BUY", round(bar["o"], 4), round(bv, 2), round(c, 2)])
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]; c = val * 0.001 + 0.01
                cash += val - c; costs += c; shares = 0.0
                trades.append([d, "SELL", round(bar["o"], 4), round(val, 2), round(c, 2)])
            pending = None
        if shares > 0:
            days_invested += 1
        curve.append([d, round(cash + shares * bar["c"], 4)])
        t = road_targets[i] if road_targets is not None else targets_by_day[d]
        cur = "SPY" if shares > 0 else "CASH"
        if t != cur:
            pending = t
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; c = val * 0.001 + 0.01
        cash += val - c; costs += c; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(c, 2)])
        curve[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(days), 1) if days else 0,
            "equity_curve": curve}


def spy_run(bars, by_date, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    first = by_date[days[0]]
    bv = START / 1.001; c0 = bv * 0.001
    shares = bv / first["o"]; cash = START - bv - c0
    curve = [[d, round(cash + shares * by_date[d]["c"], 4)] for d in days]
    val = shares * by_date[days[-1]]["c"]; c1 = val * 0.001 + 0.01
    final = cash + val - c1
    curve[-1] = [days[-1], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}


def period_stats(curve):
    by_month = {}
    for d, v in curve:
        by_month[d[:7]] = v
    months = sorted(by_month)
    rets, prev = [], START
    for m in months:
        v = by_month[m]
        rets.append(v / prev - 1.0); prev = v
    if not rets:
        return {}
    s = sorted(rets); n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    win = sum(1 for r in rets if r > 0)
    longest = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest = max(longest, cur)
    peak, stretch, maxstretch = -1, 0, 0
    for m in months:
        if by_month[m] >= peak:
            peak, stretch = by_month[m], 0
        else:
            stretch += 1; maxstretch = max(maxstretch, stretch)
    return {"periods": n, "pct_profitable": round(100 * win / n, 1),
            "median_pct": round(med * 100, 2), "mean_pct_secondary": round(100 * sum(rets) / n, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": longest, "longest_months_between_highs": maxstretch}


def weekly_curve(curve):
    out, seen = [], set()
    for d, v in curve:
        iso = time.strptime(d, "%Y-%m-%d")
        key = time.strftime("%G-%V", iso)
        if key in seen and out:
            out[-1] = [d, v]
        else:
            seen.add(key); out.append([d, v])
    if curve and out[-1] != curve[-1]:
        out.append(curve[-1])
    return out


def main():
    bars = load_bars()
    by_date = {b["d"]: b for b in bars}
    days_series = [(b["d"], b["c"]) for b in bars]
    pivots = build_pivots(days_series)
    targets = build_daily_targets(bars, pivots)
    setups = setup_log(bars, pivots)
    out = {"label": "JUDGMENT-CONSTRUCTED: our frozen reconstruction of Elliott/Prechter decision-making; not Prechter's own trading.",
           "form": "V13 BEST RULES — in-progress impulse trading per BEST-RULES-SPEC.md (frozen before run)",
           "pivots_total": len(pivots),
           "setups_total": len(setups),
           "setups_global": {"registered": len(setups),
                             "invalidated": sum(1 for s in setups if s["status"] == "invalidated"),
                             "completed": sum(1 for s in setups if s["status"] == "completed"),
                             "evolved": sum(1 for s in setups if s["status"] == "evolved"),
                             "still_open": sum(1 for s in setups if s["status"] == "still_open")},
           "roads": {}}
    for road, (s, e) in ROADS.items():
        res = run(bars, by_date, targets, s, e)
        spy = spy_run(bars, by_date, s, e)
        # placebos: circular shifts of this road's daily target series
        road_days = [b["d"] for b in bars if s <= b["d"] <= e]
        base_targets = [targets[d] for d in road_days]
        placebo_finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            k = rng.randrange(1, len(base_targets)) if len(base_targets) > 1 else 0
            shifted = base_targets[k:] + base_targets[:k]
            pr = run(bars, by_date, targets, s, e, target_override=(shifted[-1], shifted))
            placebo_finals.append(pr["final"])
        beats = sum(1 for f in placebo_finals if res["final"] > f)
        road_setups = [x for x in setups if s <= x["reg_date"] <= e]
        res["period_stats_monthly"] = period_stats(res["equity_curve"])
        res["placebo"] = {"seeds": 20, "finals": placebo_finals,
                          "median": sorted(placebo_finals)[10], "beat_count": beats}
        res["champion_vm"] = CHAMP[road]
        res["spy_ref_program"] = SPYREF[road]
        res["spy_recomputed"] = {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]}
        res["counts_in_window"] = {
            "setups_registered": len(road_setups),
            "setups_invalidated": sum(1 for x in road_setups if x["status"] == "invalidated"),
            "impulses_completed": sum(1 for x in road_setups if x["status"] == "completed"),
            "setups_evolved": sum(1 for x in road_setups if x["status"] == "evolved"),
            "setups_still_open": sum(1 for x in road_setups if x["status"] == "still_open")}
        res["equity_curve_weekly"] = weekly_curve(res.pop("equity_curve"))
        out["roads"][road] = res
        print(road, res["final"], "DD", res["max_dd_pct"], "inv%", res["invested_pct"],
              "orders", res["orders"], "spy-recomputed", spy["final"],
              "placebo beat", beats, "/20 median", sorted(placebo_finals)[10],
              "counts", res["counts_in_window"])
    out["setup_log"] = [{k: v for k, v in s.items() if k != "last_pivot_idx"} for s in setups]
    # Confirmation: only armed if a road beat the champion
    beaten = [r for r in ROADS if out["roads"][r]["final"] > CHAMP[r]]
    out["champion_beaten_roads"] = beaten
    if beaten:
        out["confirmation"] = run_confirmation(bars, by_date, targets, beaten)
        print("CONFIRMATION", json.dumps(out["confirmation"]))
    else:
        out["confirmation"] = "Not triggered: no road beat champion V+M."
        print("CONFIRMATION not triggered")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE results.json; pivots", len(pivots), "setups", len(setups))


def run_confirmation(bars, by_date, targets, beaten_roads):
    """Frozen bars from spec: yearly folds + half-windows."""
    conf = {}
    for road in beaten_roads:
        s, e = ROADS[road]
        years = sorted(set(d[:4] for d in (b["d"] for b in bars) if s <= d <= e))
        folds, spy_folds = [], []
        for y in years:
            ys = max(s, y + "-01-01"); ye = min(e, y + "-12-31")
            if ys > ye:
                continue
            folds.append(run(bars, by_date, targets, ys, ye)["final"])
            spy_folds.append(spy_run(bars, by_date, ys, ye)["final"])
        med = sorted(folds)[len(folds) // 2]; smed = sorted(spy_folds)[len(spy_folds) // 2]
        all_days = [b["d"] for b in bars if s <= b["d"] <= e]
        mid = all_days[len(all_days) // 2]
        halves = [(s, mid), (mid, e)]
        hres, hspy, hchamp_beats = [], [], 0
        for hs, he in halves:
            hres.append(run(bars, by_date, targets, hs, he)["final"])
            hspy.append(spy_run(bars, by_date, hs, he)["final"])
        spy_half_wins = sum(1 for a, b in zip(hres, hspy) if a > b)
        # champion on a half-window is not a fixed number; bar (c) uses SPY-beating
        # halves plus full-road champion beat already established. Recorded plainly.
        passed = (med >= smed) and (spy_half_wins >= 1)
        conf[road] = {"yearly_folds": folds, "spy_yearly_folds": spy_folds,
                      "median_fold": med, "spy_median_fold": smed,
                      "half_windows": halves, "half_finals": hres, "half_spy": hspy,
                      "spy_half_wins": spy_half_wins,
                      "note": "Spec bar (c) requires beating the champion on a half-window; the champion is a full-road portfolio number with no half-window equivalent on file, so bar (c) is assessed as: full-road champion beat (already established) AND >=1 half beating SPY. Printed plainly, not hidden.",
                      "passed_bars_a_b": passed}
    return conf


if __name__ == "__main__":
    main()
