#!/usr/bin/env python3
"""
V13 BEST RULES — re-macro-regime (Bridgewater four-box, macro-regime family).

Implements BEST-RULES-SPEC.md (frozen before this run):
  - Signal UNCHANGED from the family's engine: Philly Fed Real-Time Data Set
    vintages (PCPI/IPT), within-vintage YoY now vs YoY 6 obs-months earlier,
    decision at month-end close on vintage M (latest obs M-1), fill next open.
  - MY RULES: SPY/TLT/GLD only (DBC dropped); equity weight is a DIAL,
    clip(0.55 + 0.30*G - 0.25*I, 0.25, 1.00); remainder -> TLT if inflation
    falling, GLD if inflation rising; applied target = average of this
    month's and last month's dial weights (partial adjustment); monthly;
    NO floor; program costs 0.10%/side + $0.01/sell.
  - Placebos: 20 seeds/road, the road's monthly box sequence permuted.
  - Plumbing validation: the published weight table run through THIS
    simulate (floor removed; it never bound in the native record) must
    reproduce the v7 originals CONT $230.81 / VAL $137.99.

Classification, vintage loading and price series are imported verbatim from
the family's v10 integrity engine (read-only shared input).
"""
import importlib.util, json, os, random, statistics, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/home/hatch/workspace/stock-app/backtests/v10-retest/re-macro-regime/integrity_original.py"
spec = importlib.util.spec_from_file_location("fam_engine", SRC)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

ASSETS = E.ASSETS  # SPY, TLT, GLD, DBC (DBC weight is always 0 under my rules)
COST_RATE, SELL_FEE, START_CASH = E.COST_RATE, E.SELL_FEE, E.START_CASH

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 297.19, "DECADE": 259.84, "CONT": 238.47, "VAL": 143.48}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


# ------------------------------------------------------------------ dial
def dial_weights(box):
    """box = (growth 'R'/'F', inflation 'R'/'F') -> full weight dict."""
    g = 1 if box[0] == "R" else -1
    i = 1 if box[1] == "R" else -1
    spy = min(1.00, max(0.25, 0.55 + 0.30 * g - 0.25 * i))
    w = {"SPY": spy, "TLT": 0.0, "GLD": 0.0, "DBC": 0.0}
    if spy < 1.0:
        if box[1] == "F":
            w["TLT"] = 1.0 - spy
        else:
            w["GLD"] = 1.0 - spy
    return w


def build_boxes(mat_cpi, mat_ip, first_dec, last_dec):
    boxes = []
    y, m = first_dec
    while (y, m) <= last_dec:
        g, _ = E.classify(mat_ip, y, m)
        i, _ = E.classify(mat_cpi, y, m)
        boxes.append({"decision_month": f"{y}-{m:02d}", "box": (g, i)})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return boxes


def apply_partial(boxes, weight_fn):
    """Applied target = mean of this month's and last month's weights."""
    out, prev = [], None
    for b in boxes:
        w = weight_fn(b["box"])
        if prev is None:
            applied = dict(w)
        else:
            applied = {t: 0.5 * (w[t] + prev[t]) for t in ASSETS}
        out.append({"decision_month": b["decision_month"], "box": b["box"],
                    "weights": applied})
        prev = w
    return out


# ------------------------------------------------------------------ engine
def simulate(start, end, schedule, cost_rate=COST_RATE, sell_fee=SELL_FEE):
    """The family's own simulate (v7/v10 integrity engine) with the floor
    block removed — my spec has NO floor; the native record shows the floor
    never bound, so removal changes nothing for the published-form check."""
    first_eval_month = schedule[0]["decision_month"]
    days = [d for d in E.CAL if d[:7] >= first_eval_month and d <= end]
    eval_days = E.month_eval_days(days[0], end)
    sched_by_month = {s["decision_month"]: s for s in schedule}

    cash = START_CASH
    shares = {t: 0.0 for t in ASSETS}
    orders, total_costs = 0, 0.0
    trades_log, curve, in_force = [], [], []
    pending = None

    def equity_at(date, price_fn):
        eq = cash
        for t in ASSETS:
            if shares[t] > 0:
                p = price_fn(t, date)
                if p:
                    eq += shares[t] * p
        return eq

    for di, d in enumerate(days):
        if pending is not None:
            targets, dec_month = pending
            eq_open = equity_at(d, E.open_on)
            for t in ASSETS:
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * E.open_on(t, d)
                diff = cur_val - tgt_val
                if diff > 0.01 and shares[t] > 0:
                    sell_val = min(diff, cur_val)
                    sh = sell_val / E.open_on(t, d)
                    cost = sell_val * cost_rate + sell_fee
                    cash += sell_val - cost
                    shares[t] -= sh
                    if shares[t] < 1e-9:
                        shares[t] = 0.0
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "SELL", t, round(sell_val, 2)))
            buy_list = []
            for t in ASSETS:
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * E.open_on(t, d)
                diff = tgt_val - cur_val
                if diff > 0.01:
                    buy_list.append((t, diff))
            tot_buy = sum(v for _, v in buy_list)
            if tot_buy > 0:
                scale = min(1.0, cash / (tot_buy * (1 + cost_rate)))
                for t, diff in buy_list:
                    buy_val = diff * scale
                    if buy_val < 0.01:
                        continue
                    cost = buy_val * cost_rate
                    cash -= buy_val + cost
                    shares[t] += buy_val / E.open_on(t, d)
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "BUY", t, round(buy_val, 2)))
            in_force.append((d, dec_month, dict(targets)))
            pending = None

        eq_close = equity_at(d, E.close_on)
        if d >= start:
            curve.append((d, eq_close))

        if d in eval_days and di + 1 < len(days):
            s = sched_by_month.get(d[:7])
            if s is not None:
                pending = (s["weights"], s["decision_month"])

    return {"final": curve[-1][1] if curve else START_CASH, "curve": curve,
            "orders": orders, "costs": total_costs, "trades": trades_log,
            "in_force": in_force}


# ------------------------------------------------------------------ stats
def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd


def longest_no_new_high(curve):
    peak, cur, best = -1e18, 0, 0
    for _, eq in curve:
        if eq >= peak:
            peak, cur = eq, 0
        else:
            cur += 1
            best = max(best, cur)
    return best


def year_distribution(curve):
    """Calendar-year returns from the daily curve."""
    by_year = {}
    for d, eq in curve:
        by_year.setdefault(d[:4], []).append(eq)
    years = sorted(by_year)
    rets, prev_end = {}, None
    for y in years:
        first, last = by_year[y][0], by_year[y][-1]
        base = prev_end if prev_end is not None else first
        rets[y] = last / base - 1.0
        prev_end = last
    vals = [rets[y] for y in years]
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    return {
        "median_year_pct": round(statistics.median(vals) * 100, 2),
        "mean_year_pct": round(statistics.mean(vals) * 100, 2),
        "share_positive_pct": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1),
        "n_years": len(vals),
        "best_year": [max(rets, key=rets.get), round(max(vals) * 100, 2)],
        "worst_year": [min(rets, key=rets.get), round(min(vals) * 100, 2)],
        "longest_losing_streak_years": streak,
        "longest_no_new_high_days": longest_no_new_high(curve),
        "year_returns_pct": {y: round(rets[y] * 100, 2) for y in years},
    }


def prev_month(ym):
    y, m = ym
    return (y - 1, 12) if m == 1 else (y, m - 1)


def main():
    mat_cpi = E.load_matrix("CPI")
    mat_ip = E.load_matrix("IP")
    out = {"family": "re-macro-regime", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md", "validation": {}, "roads": {}}

    # ---- plumbing validation: published table through THIS simulate
    for road in ("CONT", "VAL"):
        start, end = ROADS[road]
        sy, sm = int(start[:4]), int(start[5:7])
        boxes = build_boxes(mat_cpi, mat_ip, prev_month((sy, sm)),
                            (2026, 10))
        sched = [{"decision_month": b["decision_month"], "box": b["box"],
                  "weights": E.WEIGHTS[b["box"]]} for b in boxes]
        r = simulate(start, end, sched)
        out["validation"][road] = round(r["final"], 2)
    print("validation (published form, this plumbing):", out["validation"],
          "targets CONT 230.81 / VAL 137.99", flush=True)

    for road, (start, end) in ROADS.items():
        sy, sm = int(start[:4]), int(start[5:7])
        boxes = build_boxes(mat_cpi, mat_ip, prev_month((sy, sm)),
                            (2026, 10))
        sched = apply_partial(boxes, dial_weights)
        res = simulate(start, end, sched)
        stress = simulate(start, end, sched, cost_rate=COST_RATE * 2,
                          sell_fee=SELL_FEE * 2)
        spy = E.buy_hold({"SPY": 1.0}, start, end)
        spy_dd = max_dd(E.spy_curve(start, end))

        placebo_finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            perm = [dict(b) for b in boxes]
            blist = [b["box"] for b in perm]
            rng.shuffle(blist)
            for b, bx in zip(perm, blist):
                b["box"] = bx
            pr = simulate(start, end, apply_partial(perm, dial_weights))
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if res["final"] > f)

        avg_spy_w = statistics.mean(s["weights"]["SPY"] for s in sched)
        box_counts = {}
        for b in boxes:
            k = f"{b['box'][0]}{b['box'][1]}"
            box_counts[k] = box_counts.get(k, 0) + 1

        out["roads"][road] = {
            "start": start, "end": end,
            "final": round(res["final"], 2),
            "max_dd_pct": round(max_dd(res["curve"]) * 100, 2),
            "orders": res["orders"], "costs": round(res["costs"], 2),
            "stress2x_final": round(stress["final"], 2),
            "spy_same_plumbing": round(spy, 2), "spy_max_dd_pct": round(spy_dd * 100, 2),
            "spy_reference": SPY_REF[road],
            "published_native": PUBLISHED[road],
            "champion_vm": CHAMPION[road],
            "avg_applied_spy_weight_pct": round(avg_spy_w * 100, 1),
            "box_counts": box_counts,
            "placebo_finals": placebo_finals,
            "placebo_median": round(statistics.median(placebo_finals), 2),
            "placebos_beaten": f"{beaten}/20",
            "distribution": year_distribution(res["curve"]),
            "trades": res["trades"],
            "equity_curve": [[d, round(v, 4)] for d, v in res["curve"]],
        }
        print(f"{road}: final ${res['final']:.2f} DD {max_dd(res['curve'])*100:.2f}% "
              f"SPY ${spy:.2f} placebos {beaten}/20 stress ${stress['final']:.2f}",
              flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json", flush=True)


if __name__ == "__main__":
    main()
