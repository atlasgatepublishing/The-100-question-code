#!/usr/bin/env python3
"""V13 sector-rotation BEST RULES — frozen in BEST-RULES-SPEC.md before this run.
12-1 cross-sectional momentum over 11 SPDRs (point-in-time: XLRE eligible from
Oct 2016 signals, XLC from Jun 2019 signals), per-name absolute-momentum gate
(12-1 > 0), top 3 at 1/3 slots, unfilled slots in cash, monthly month-end
signals, program costs 0.10%/side, cash 0%, $100 pots. 20-seed placebos:
random picks of the same count from the same month's eligible set.
Chassis convention identical to v12 sector-rotation (signal at month-end i,
earns month i -> i+1). Data: Yahoo adjusted closes (v12 cache for 9+SPY,
fetched identically for XLRE/XLC into this folder's data/)."""
import csv, io, json, pathlib, random, statistics
from datetime import date

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
CORE = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
EXTRA = {"XLRE": "2016-10", "XLC": "2019-06"}  # first eligible signal month (inception + 12m)
TICKERS = CORE + list(EXTRA)
ALL = TICKERS + ["SPY"]
COST = 0.0010

def month_ends(sym):
    rows = list(csv.DictReader(io.StringIO((DATA / f"{sym}.csv").read_text())))
    out = {}
    for r in rows:
        r = {k.lower(): v for k, v in r.items()}
        if r["close"] in ("", "N/D", None):
            continue
        out[r["date"][:7]] = (r["date"], float(r["close"]))
    return out

def load_all():
    me = {s: month_ends(s) for s in ALL}
    months = sorted(set(me["SPY"]))  # master calendar = SPY months
    px, dates = {}, {}
    for s in ALL:
        px[s] = [me[s][m][1] if m in me[s] else None for m in months]
        dates[s] = [me[s][m][0] if m in me[s] else None for m in months]
    spy_dates = [me["SPY"][m][0] for m in months]
    return months, spy_dates, px

def score(px_s, i):
    """12-1 momentum at month index i: px[i-1]/px[i-12]-1. None if unavailable."""
    if i < 12 or px_s[i - 1] is None or px_s[i - 12] is None:
        return None
    return px_s[i - 1] / px_s[i - 12] - 1.0

def eligible_set(months, px, i):
    out = []
    for t in TICKERS:
        if t in EXTRA and months[i] < EXTRA[t]:
            continue
        sc = score(px[t], i)
        if sc is not None and sc > 0:
            out.append((t, sc))
    return out

def run_window(months, dates, px, start, end, rng=None):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx:
        return None
    eq = 100.0; weights = {}; curve = []; costs = 0.0; trades = 0
    spy_i0 = idx[0]
    for i in idx:
        elig = eligible_set(months, px, i)
        if rng is not None:  # placebo: same count, random from eligible set
            k = min(3, len(elig))
            picks = rng.sample([t for t, _ in elig], k) if k else []
            target = {t: 1 / 3 for t in picks}
        else:
            top = sorted(elig, key=lambda x: -x[1])[:3]
            target = {t: 1 / 3 for t, _ in top}
        keys = set(weights) | set(target)
        traded = sum(abs(target.get(k, 0.0) - weights.get(k, 0.0)) for k in keys)
        if traded > 1e-9:
            ch = eq * COST * traded; eq -= ch; costs += ch; trades += 1
        weights = target
        if i + 1 < len(months):
            r = 0.0
            for t, w in weights.items():
                if px[t][i + 1] is not None and px[t][i] is not None:
                    r += w * (px[t][i + 1] / px[t][i] - 1.0)
            eq *= (1.0 + r)
            curve.append([dates[i + 1], round(eq, 4)])
    last_i = months.index(curve[-1][0][:7]) if curve else idx[0]
    spy_final = 100.0 * px["SPY"][last_i] / px["SPY"][spy_i0] * (1 - COST)
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    yrs = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(dates[spy_i0])).days / 365.25 if curve else 0
    return {"start": dates[spy_i0], "end": curve[-1][0] if curve else dates[spy_i0],
            "final": round(eq, 2), "spy_buyhold": round(spy_final, 2),
            "cagr_pct": round(((eq / 100.0) ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else None,
            "max_dd_pct": round(mdd * 100, 2), "rebalance_months": trades,
            "costs": round(costs, 2), "curve": curve}

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    run = mx = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        mx = max(mx, run)
    peak, last_high, maxgap = vals[0], 0, 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; maxgap = max(maxgap, i - last_high); last_high = i
    maxgap = max(maxgap, len(vals) - 1 - last_high)
    return {"months": len(rets), "pos_months": sum(1 for r in rets if r > 0),
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(100 * statistics.median(rets), 2),
            "best_pct": round(100 * max(rets), 2), "worst_pct": round(100 * min(rets), 2),
            "longest_losing_streak_months": mx,
            "longest_stretch_between_new_highs_months": maxgap,
            "average_pct_labeled_average": round(100 * sum(rets) / len(rets), 2)}

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
CHAMPIONS = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_PROG = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED_A = {"LONG": 753.49, "DECADE": 382.96, "CONT": 322.35, "VAL": 160.72}

def main():
    months, dates, px = load_all()
    out = {"strategy": "V13 best-rules sector rotation: 12-1 momentum, per-name absolute gate (>0), top 3 at 1/3 slots, 11 SPDRs point-in-time (XLRE>=2016-10 signals, XLC>=2019-06 signals), monthly, no floor",
           "universe": TICKERS, "cost_per_side": COST, "cash_return": 0.0,
           "data": "Yahoo chart API daily adjusted closes, month-end (9 SPDRs + SPY copied read-only from v12 folder; XLRE/XLC fetched identically 2026-11-22)",
           "first_month": months[0], "last_month": months[-1],
           "champions_vm": CHAMPIONS, "spy_program_refs": SPY_PROG,
           "published_form_a_v12": PUBLISHED_A, "roads": {}}
    beaten = []
    for wname, (s, e) in ROADS.items():
        r = run_window(months, dates, px, s, e)
        pls = []
        for seed in range(20):
            rng = random.Random(3000 + seed)
            pls.append(run_window(months, dates, px, s, e, rng=rng)["final"])
        r["placebo_finals"] = pls
        r["placebo_beaten"] = sum(1 for p in pls if r["final"] > p)
        r["placebo_median"] = round(statistics.median(pls), 2)
        r["period_stats"] = period_stats(r["curve"])
        out["roads"][wname] = r
        if r["final"] > CHAMPIONS[wname]:
            beaten.append(wname)
        print(wname, r["final"], "SPY(plumbing)", r["spy_buyhold"], "DD", r["max_dd_pct"],
              "placebo", r["placebo_beaten"], "/20", "costs", r["costs"])
    out["champion_roads_beaten"] = beaten
    # Confirmation material (spec section 9) — computed regardless, verdict applied per bars
    folds = {}
    for y in range(2010, 2027):
        r = run_window(months, dates, px, f"{y}-01-01", f"{y}-12-31")
        if r:
            folds[str(y)] = {"final": r["final"], "spy_buyhold": r["spy_buyhold"],
                             "beat_spy": r["final"] > r["spy_buyhold"]}
    halves = {}
    for name, (s, e) in {"H1_2010_2018": ("2010-01-01", "2018-12-31"),
                         "H2_2018_2026": ("2018-01-01", "2026-11-20")}.items():
        r = run_window(months, dates, px, s, e)
        halves[name] = {"final": r["final"], "spy_buyhold": r["spy_buyhold"],
                        "max_dd_pct": r["max_dd_pct"], "beat_spy": r["final"] > r["spy_buyhold"]}
    strat_folds = [f["final"] for f in folds.values()]
    spy_folds = [f["spy_buyhold"] for f in folds.values()]
    conf = {"year_folds": folds, "half_windows": halves,
            "folds_beat_spy_count": sum(1 for f in folds.values() if f["beat_spy"]),
            "folds_n": len(folds),
            "median_fold_strategy": round(statistics.median(strat_folds), 2),
            "median_fold_spy": round(statistics.median(spy_folds), 2),
            "bar_a_pass": (sum(1 for f in folds.values() if f["beat_spy"]) * 2 >= len(folds)
                           and statistics.median(strat_folds) >= statistics.median(spy_folds)),
            "bar_b_pass": all(h["beat_spy"] for h in halves.values())}
    conf["confirmation_pass"] = conf["bar_a_pass"] and conf["bar_b_pass"]
    out["confirmation"] = conf
    print("champion roads beaten:", beaten, "| confirmation pass:", conf["confirmation_pass"],
          "| folds beat SPY:", conf["folds_beat_spy_count"], "/", conf["folds_n"],
          "| halves:", {k: (v["final"], v["spy_buyhold"]) for k, v in halves.items()})
    (HERE / "results.json").write_text(json.dumps(out, indent=1))
    print("wrote results.json")

if __name__ == "__main__":
    main()
