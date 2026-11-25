#!/usr/bin/env python3
"""V13 BEST RULES — catalog-taa-regime-based-saa (Bouye & Teiletche regime-based SAA).
Spec frozen in BEST-RULES-SPEC.md before this run.
Construction of the published METHOD (no author weights exist in the free record):
  - PIT regime classification imported verbatim from the program's validated
    macro engine (Philly Fed vintages PCPI/IPT, within-vintage YoY vs 6mo earlier).
  - Regime probabilities = trailing 36-month box frequency (each month from its own vintage).
  - Portfolio = sum_box P(box) * W_box (frozen reasoned table), quarterly rebalance
    at quarter-end close, close-valued, costs 0.10%/side, NO floor, $100 pots.
Comparators: static equal-probability blend (same table/engine), SPY buy-hold.
Placebos: 20 seeds/road, monthly box sequence permuted, probabilities recomputed.
Prices: v12 Keller-BAA Yahoo adjclose CSV caches (read-only shared input).
"""
import csv, importlib.util, json, os, random, statistics

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "/home/hatch/workspace/stock-app/backtests/v10-retest/re-macro-regime/integrity_original.py"
spec = importlib.util.spec_from_file_location("fam_engine", SRC)
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

PRICE_DIR = "/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-baa/data"
ASSETS = ["SPY", "TLT", "LQD", "TIP", "VNQ", "GLD", "DBC"]
COST = 0.0010
START = 100.0

W = {  # (growth, inflation) -> weights, frozen in spec
    ("R", "F"): {"SPY": .35, "TLT": .20, "LQD": .15, "TIP": .05, "VNQ": .15, "GLD": .05, "DBC": .05},
    ("R", "R"): {"SPY": .25, "TLT": .05, "LQD": .10, "TIP": .15, "VNQ": .10, "GLD": .15, "DBC": .20},
    ("F", "R"): {"SPY": .10, "TLT": .05, "LQD": .05, "TIP": .20, "VNQ": .05, "GLD": .25, "DBC": .30},
    ("F", "F"): {"SPY": .15, "TLT": .35, "LQD": .10, "TIP": .15, "VNQ": .05, "GLD": .15, "DBC": .05},
}
STATIC = {t: sum(W[b][t] for b in W) / 4.0 for t in ASSETS}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-01-04", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_prices():
    px = {}
    for t in ASSETS:
        d = {}
        with open(os.path.join(PRICE_DIR, f"{t}.csv")) as f:
            for row in csv.DictReader(f):
                if row["adjclose"]:
                    d[row["date"]] = float(row["adjclose"])
        px[t] = d
    return px


PX = load_prices()
CAL = sorted(d for d in PX["SPY"] if d <= "2026-11-20")


def price(t, date):
    s = PX[t]
    if date in s:
        return s[date]
    # nearest prior trading day in SPY calendar
    for d in reversed(CAL):
        if d <= date and d in s:
            return s[d]
    return None


def build_boxes(first=(2006, 1), last=(2026, 10)):
    mc, mi = E.load_matrix("CPI"), E.load_matrix("IP")
    boxes, y, m = [], *first
    while (y, m) <= last:
        g, _ = E.classify(mi, y, m); i, _ = E.classify(mc, y, m)
        boxes.append({"ym": f"{y}-{m:02d}", "box": (g, i)})
        m += 1
        if m == 13: y, m = y + 1, 1
    return boxes


def probs_at(boxes, idx):
    """Trailing 36-month frequency ending at boxes[idx] (inclusive)."""
    win = boxes[max(0, idx - 35): idx + 1]
    p = {b: 0.0 for b in W}
    for b in win: p[b["box"]] += 1.0 / len(win)
    return p


def blend(p):
    return {t: sum(p[b] * W[b][t] for b in W) for t in ASSETS}


def simulate(start, end, boxes, mode="mine"):
    """Quarterly rebalance at quarter-end close. mode: mine|static|placebo handled
    by caller passing permuted boxes; static ignores boxes."""
    days = [d for d in CAL if start <= d <= end]
    qends = {}
    for d in days:
        if d[5:7] in ("03", "06", "09", "12"):
            qends[d[:7]] = d  # last trading day of quarter months (refined below)
    # true quarter-end: last CAL day of Mar/Jun/Sep/Dec present in days
    qset = set()
    for ym, d in qends.items():
        cand = [x for x in days if x[:7] == ym]
        qset.add(cand[-1])
    box_idx = {b["ym"]: k for k, b in enumerate(boxes)}
    shares = {t: 0.0 for t in ASSETS}; cash = START
    curve, trades, total_costs, turnover = [], 0, 0.0, 0.0
    modal_switches, prev_modal = 0, None
    targets_log = []

    def equity(date):
        return cash + sum(shares[t] * price(t, date) for t in ASSETS if shares[t] > 0)

    def rebalance(date, target):
        nonlocal cash, trades, total_costs, turnover
        eq = equity(date)
        traded = 0.0
        for t in ASSETS:
            cur = shares[t] * price(t, date) if shares[t] > 0 else 0.0
            diff = target[t] * eq - cur
            if abs(diff) > 0.01:
                traded += abs(diff); trades += 1
        cost = traded * COST
        total_costs += cost; turnover += traded / eq if eq else 0
        cash = eq - cost
        for t in ASSETS:
            shares[t] = (target[t] * (eq - cost)) / price(t, date) if target[t] > 0 else 0.0
        cash = 0.0

    # initial allocation at first day using probabilities at prior month-end
    first_ym = start[:7]
    y, m = int(first_ym[:4]), int(first_ym[5:7])
    pm = (y - 1, 12) if m == 1 else (y, m - 1)
    idx = box_idx.get(f"{pm[0]}-{pm[1]:02d}", 0)
    tgt = STATIC if mode == "static" else blend(probs_at(boxes, idx))
    rebalance(days[0], tgt); targets_log.append((days[0], dict(tgt)))

    for d in days:
        if d in qset:
            idx = box_idx.get(d[:7])
            if idx is not None:
                if mode == "static":
                    tgt = STATIC
                else:
                    p = probs_at(boxes, idx); tgt = blend(p)
                    modal = max(p, key=p.get)
                    if prev_modal is not None and modal != prev_modal: modal_switches += 1
                    prev_modal = modal
                rebalance(d, tgt); targets_log.append((d, dict(tgt)))
        curve.append((d, equity(d)))
    return {"final": curve[-1][1], "curve": curve, "costs": total_costs,
            "orders": trades, "turnover_x": round(turnover, 2),
            "modal_switches": modal_switches, "targets": targets_log}


def spy_hold(start, end):
    days = [d for d in CAL if start <= d <= end]
    sh = START * (1 - COST) / price("SPY", days[0])
    curve = [(d, sh * price("SPY", d)) for d in days]
    return curve[-1][1], curve


def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0: mdd = min(mdd, eq / peak - 1)
    return mdd


def longest_no_new_high(curve):
    peak, cur, best = -1e18, 0, 0
    for _, eq in curve:
        if eq >= peak: peak, cur = eq, 0
        else: cur += 1; best = max(best, cur)
    return best


def year_distribution(curve):
    by = {}
    for d, eq in curve: by.setdefault(d[:4], []).append(eq)
    rets, prev = {}, None
    for y in sorted(by):
        base = prev if prev is not None else by[y][0]
        rets[y] = by[y][-1] / base - 1; prev = by[y][-1]
    vals = list(rets.values()); streak = cur = 0
    for v in vals: cur = cur + 1 if v < 0 else 0; streak = max(streak, cur)
    return {"median_year_pct": round(statistics.median(vals) * 100, 2),
            "mean_year_pct": round(statistics.mean(vals) * 100, 2),
            "share_positive_pct": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1),
            "n_years": len(vals),
            "best_year": [max(rets, key=rets.get), round(max(vals) * 100, 2)],
            "worst_year": [min(rets, key=rets.get), round(min(vals) * 100, 2)],
            "longest_losing_streak_years": streak,
            "longest_no_new_high_days": longest_no_new_high(curve),
            "year_returns_pct": {y: round(rets[y] * 100, 2) for y in rets}}


def main():
    boxes = build_boxes()
    out = {"family": "catalog-taa-regime-based-saa", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md", "note": "No published author weights exist (v12 STILL UNBUILDABLE); this grades a Claude construction of the published method. Static equal-probability blend = published-form proxy bar.",
           "static_weights": STATIC, "roads": {}}
    for road, (start, end) in ROADS.items():
        res = simulate(start, end, boxes, "mine")
        stat = simulate(start, end, boxes, "static")
        spy_f, spy_c = spy_hold(start, end)
        placebo_finals = []
        sub = [b for b in boxes if "2006-01" <= b["ym"] <= "2026-10"]
        for seed in range(1, 21):
            rng = random.Random(seed)
            perm = [dict(b) for b in boxes]
            blist = [b["box"] for b in perm]; rng.shuffle(blist)
            for b, bx in zip(perm, blist): b["box"] = bx
            placebo_finals.append(round(simulate(start, end, perm, "mine")["final"], 2))
        beaten = sum(1 for f in placebo_finals if res["final"] > f)
        out["roads"][road] = {
            "start": start, "end": end, "final": round(res["final"], 2),
            "max_dd_pct": round(max_dd(res["curve"]) * 100, 2),
            "costs": round(res["costs"], 2), "orders": res["orders"],
            "turnover_x_equity": res["turnover_x"], "modal_switches": res["modal_switches"],
            "static_final": round(stat["final"], 2), "static_max_dd_pct": round(max_dd(stat["curve"]) * 100, 2),
            "spy_in_engine": round(spy_f, 2), "spy_reference": SPY_REF[road],
            "champion_vm": CHAMPION[road],
            "placebo_finals": placebo_finals, "placebo_median": round(statistics.median(placebo_finals), 2),
            "placebos_beaten": f"{beaten}/20",
            "distribution": year_distribution(res["curve"]),
            "equity_curve": [[d, round(v, 4)] for d, v in res["curve"]],
            "static_curve": [[d, round(v, 4)] for d, v in stat["curve"]],
            "spy_curve": [[d, round(v, 4)] for d, v in spy_c]}
        print(f"{road}: mine ${res['final']:.2f} DD {max_dd(res['curve'])*100:.1f}% | static ${stat['final']:.2f} | SPY ${spy_f:.2f} | placebos {beaten}/20 | switches {res['modal_switches']} costs ${res['costs']:.2f}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json", flush=True)


if __name__ == "__main__":
    main()
