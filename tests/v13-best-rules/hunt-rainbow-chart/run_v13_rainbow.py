#!/usr/bin/env python3
"""
V13 BEST RULES — hunt-rainbow-chart. SIMULATION ONLY.
Frozen spec: BEST-RULES-SPEC.md in this folder (written before this run).

TODAY'S published rainbow, frozen: centreline log10(P) = 2.445861*ln(days
since 2009-01-03) - 16.319632 (OLS fit over the FULL cached history
2010-07-18 -> 2026-11-21 — IN-SAMPLE BY CONSTRUCTION, see spec section
WARNING; the caveat is permanent). Nine bands of 0.10 log10 centred on the
fit; band LADDER (dial) target weights 100/100/90/75/60/45/30/15/0 %.
Weekly checks (every 7th bar of the road), signal + rebalance at the check
day's close, cost 0.60%/side on traded dollars. No floor/stop. $100 pots.
BTC only. Data READ-ONLY: v12 family cache (CoinMetrics PriceUSD).
Roads: FULL 2010-07-18->2026-11-21, DESIGN ->2022-12-31,
VALIDATION 2023-01-01->2026-11-21. Placebos (20 seeds, FULL+VALIDATION):
matched random timing + circularly shifted signal.
"""
import json, os, random, statistics, math
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-rainbow-chart/data/cm_btc.json")
COST = 0.006
START = 100.0
A_COEF, B_COEF = 2.445861, -16.319632   # frozen in spec BEFORE the run
GEN = date(2009, 1, 3)
WEIGHTS = [1.0, 1.0, 0.90, 0.75, 0.60, 0.45, 0.30, 0.15, 0.0]  # bands 1..9

def load_rows():
    cm = json.load(open(SRC))
    rows = sorted((r["time"][:10], float(r["PriceUSD"])) for r in cm if float(r["PriceUSD"]) > 0)
    return rows

def deviation(dstr, price):
    days = (date.fromisoformat(dstr) - GEN).days
    return math.log10(price) - (A_COEF * math.log(days) + B_COEF)

def band_of(d):
    if d < -0.45: return 1
    if d >= 0.45: return 9
    return int(math.floor((d + 0.45) / 0.10)) + 1

def verify_fit(rows):
    xs, ys = [], []
    for dstr, p in rows:
        days = (date.fromisoformat(dstr) - GEN).days
        xs.append(math.log(days)); ys.append(math.log10(p))
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    b = my - a * mx
    assert abs(a - A_COEF) < 5e-4 and abs(b - B_COEF) < 5e-3, (a, b)
    return {"n": n, "a_refit": round(a, 6), "b_refit": round(b, 6)}

def run_ladder(rows, targets_by_check):
    """targets_by_check: one target weight per weekly check (bars 0,7,14,...).
    Rebalance at the check day's close. Returns final (after terminal
    liquidation cost on any residual BTC), daily curve (pre-liquidation
    marks), maxdd, trades."""
    n = len(rows)
    cash, units = START, 0.0
    curve = []
    trades = 0
    checks = set(range(0, n, 7))
    ci = 0
    expo_sum = 0.0
    for i in range(n):
        c = rows[i][1]
        if i in checks and ci < len(targets_by_check):
            tgt = targets_by_check[ci]; ci += 1
            eq = cash + units * c
            want = tgt * eq
            cur = units * c
            delta = want - cur
            if abs(delta) > 1e-9:
                if delta > 0:
                    spend = min(delta, cash)
                    units += spend * (1 - COST) / c
                    cash -= spend
                else:
                    sell = min(-delta, cur)
                    units -= sell / c
                    cash += sell * (1 - COST)
                trades += 1
        eq = cash + units * c
        curve.append(eq)
        expo_sum += (units * c / eq) if eq > 0 else 0.0
    final = cash + units * rows[-1][1] * (1 - COST)
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "maxdd_pct": round(maxdd * 100, 1),
            "trades": trades, "avg_exposure_pct": round(100 * expo_sum / max(n, 1), 1),
            "curve": curve}

def buy_hold(rows):
    units = START * (1 - COST) / rows[0][1]
    curve = [units * p for _, p in rows]
    final = units * rows[-1][1] * (1 - COST)
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "maxdd_pct": round(maxdd * 100, 1), "curve": curve}

def monthly_stats(dates, curve):
    marks = [START]
    seen = []
    for i, d in enumerate(dates):
        ym = d[:7]
        if not seen or seen[-1] != ym:
            seen.append(ym); marks.append(curve[i])
        else:
            marks[-1] = curve[i]
    rets = [marks[i + 1] / marks[i] - 1.0 for i in range(len(marks) - 1) if marks[i] > 0]
    if not rets: return None
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    runmax = marks[0]; since = 0; maxgap = 0
    for m in marks[1:]:
        if m >= runmax: runmax = m; since = 0
        else:
            since += 1; maxgap = max(maxgap, since)
    return {"months": len(rets), "median_pct": round(statistics.median(rets) * 100, 3),
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_months": streak,
            "longest_stretch_between_new_highs_months": maxgap,
            "avg_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def real_targets(rows):
    return [WEIGHTS[band_of(deviation(rows[i][0], rows[i][1])) - 1] for i in range(0, len(rows), 7)]

def pct_rank(vals, x):
    return round(100.0 * sum(1 for y in vals if y < x) / len(vals), 0)

def run_road(rows, label, placebos=False):
    dates = [d for d, _ in rows]
    targets = real_targets(rows)
    real = run_ladder(rows, targets)
    hold = buy_hold(rows)
    out = {"label": label, "window": [dates[0], dates[-1]], "bars": len(rows),
           "strategy": {k: real[k] for k in ("final", "maxdd_pct", "trades", "avg_exposure_pct")},
           "buy_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]},
           "monthly_stats_strategy": monthly_stats(dates, real["curve"]),
           "monthly_stats_buy_hold": monthly_stats(dates, hold["curve"]),
           "band_freq_checks": {str(k): targets.count(WEIGHTS[k - 1]) for k in range(1, 10)},
           "curves": {"strategy": [round(x, 4) for x in real["curve"]],
                      "buy_hold": [round(x, 4) for x in hold["curve"]]},
           "curve_dates": dates}
    if placebos:
        n = len(targets)
        levels = sorted(set(targets))
        pool = []
        for lv in levels: pool += [lv] * targets.count(lv)
        rand_finals, shift_finals = [], []
        for s in range(20):
            rng = random.Random(20261122 + s)
            rt = [rng.choice(pool) for _ in range(n)]
            rand_finals.append(run_ladder(rows, rt)["final"])
            off = rng.randint(4, max(5, n - 5))
            st = targets[off:] + targets[:off]
            shift_finals.append(run_ladder(rows, st)["final"])
        out["placebo_random_timing"] = {"median_final": round(statistics.median(rand_finals), 2),
            "real_pct_rank": pct_rank(rand_finals, real["final"]), "finals": [round(x, 2) for x in rand_finals]}
        out["placebo_shifted"] = {"median_final": round(statistics.median(shift_finals), 2),
            "real_pct_rank": pct_rank(shift_finals, real["final"]), "finals": [round(x, 2) for x in shift_finals]}
    return out

def main():
    rows = load_rows()
    fit_check = verify_fit(rows)
    out = {"family": "hunt-rainbow-chart", "program": "v13-best-rules",
           "spec": "Today's published rainbow frozen (OLS fit on FULL history — IN-SAMPLE, see spec); "
                   "9 bands x 0.10 log10; band ladder dial weekly; BTC only; 0.60%/side; no floor",
           "frozen_centreline": {"a": A_COEF, "b": B_COEF, "fit_check": fit_check},
           "in_sample_caveat": "Centreline fitted on the same 2010-2026 history the roads grade. "
                               "Execution is point-in-time (frozen bands, that day's price only); "
                               "the fit-on-the-future caveat is permanent and attaches to any beat.",
           "cost_per_side": COST, "roads": {}}
    roads = {
        "FULL": [r for r in rows],
        "DESIGN": [r for r in rows if r[0] <= "2022-12-31"],
        "VALIDATION": [r for r in rows if r[0] >= "2023-01-01"],
    }
    for name, rr in roads.items():
        out["roads"][name] = run_road(rr, name, placebos=(name in ("FULL", "VALIDATION")))
    out["family_published_best_v12"] = {"FULL": 357110053.98, "DESIGN": 100269534.37, "VALIDATION": 352.25,
        "note": "v12 RAINBOW-ACCUM NATIVE (binary switch, 2014 trolololo formula), windows ending 2026-11-20"}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    for k, r in out["roads"].items():
        line = f"{k} {r['window']} strategy={r['strategy']} bh={r['buy_hold']}"
        if "placebo_random_timing" in r:
            line += (f" rand_med={r['placebo_random_timing']['median_final']} rank={r['placebo_random_timing']['real_pct_rank']}"
                     f" shift_med={r['placebo_shifted']['median_final']} rank={r['placebo_shifted']['real_pct_rank']}")
        print(line)
    print("fit_check", fit_check)

if __name__ == "__main__":
    main()
