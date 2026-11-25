#!/usr/bin/env python3
"""V13 BEST RULES — hunt-options-implied. Simulation only.

Implements BEST-RULES-SPEC.md (frozen before this run):
  Monthly dial on SPY. At each month-end close: VRP = VIX - trailing-21d
  realized vol (annualised, vol points). VRP>=0 -> 100% SPY; VRP<0 -> 50%
  SPY; VIX>=40 -> 100% regardless. Trade next trading day on adjusted close
  basis. Costs 0.10% on traded notional. No floor. Cash 0%. $100 pots.
  Placebos: 20-seed phase-shifted VRP (shift 20-500 trading days).
Data: SPY adj closes from shared v7 cache (read-only); VIX = CBOE published
daily history (VIX_History.csv in this folder).
"""
import csv, json, math, os, random, statistics, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_spy():
    j = json.load(open(SPY_PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None:
            continue
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_vix():
    out = {}
    with open(os.path.join(HERE, "VIX_History.csv")) as f:
        for row in csv.DictReader(f):
            m, d, y = row["DATE"].split("/")
            out[f"{y}-{int(m):02d}-{int(d):02d}"] = float(row["CLOSE"])
    return out


def build_series(bars, vix):
    """Per trading day: close, realized vol (21d, vol pts), VRP, VIX."""
    closes = [b["c"] for b in bars]
    rets = [0.0] + [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    out = []
    for i, b in enumerate(bars):
        rv = None
        if i >= 21:
            window = rets[i - 20:i + 1]
            rv = statistics.pstdev(window) * math.sqrt(252) * 100
        v = vix.get(b["d"])
        vrp = (v - rv) if (v is not None and rv is not None) else None
        out.append({"d": b["d"], "c": b["c"], "vix": v, "rv": rv, "vrp": vrp})
    return out


def month_end_indices(series, start, end):
    idx = [i for i, s in enumerate(series) if start <= s["d"] <= end]
    mes = []
    for k, i in enumerate(idx):
        nxt = idx[k + 1] if k + 1 < len(idx) else None
        if nxt is None or series[nxt]["d"][:7] != series[i]["d"][:7]:
            mes.append(i)
    return idx, mes


def run_dial(series, start, end, vrp_override=None):
    """Monthly dial. vrp_override: dict date->vrp (placebo). Returns dict."""
    idx, mes = month_end_indices(series, start, end)
    first = idx[0]
    cash, shares = START, 0.0
    trades, costs, switches = 0, 0.0, 0
    curve = [(series[first]["d"], START)]
    monthly = []  # (month, equity at month end)
    cur_weight = 0.0
    pending = 1.0  # enter fully at road start (first month-end decision refines)
    # enter at first close
    c = cash * COST; shares = (cash - c) / series[first]["c"]; costs += c; cash = 0.0
    trades += 1; cur_weight = 1.0
    prev_month_equity = START
    for k, i in enumerate(idx):
        s = series[i]
        eq = cash + shares * s["c"]
        is_me = i in set(mes)
        if is_me:
            monthly.append((s["d"][:7], eq))
        # decide at month-end close, execute at next trading day's close
        if is_me and k + 1 < len(idx):
            vrp = vrp_override.get(s["d"], s["vrp"]) if vrp_override else s["vrp"]
            if s["vix"] is not None and s["vix"] >= 40:
                target = 1.0
            elif vrp is None:
                target = cur_weight
            elif vrp >= 0:
                target = 1.0
            else:
                target = 0.5
            if target != cur_weight:
                j = idx[k + 1]
                eq_next = cash + shares * series[j]["c"]
                target_val = target * eq_next
                cur_val = shares * series[j]["c"]
                delta = target_val - cur_val
                cst = abs(delta) * COST; costs += cst
                if delta > 0:  # buy
                    buy = min(delta, cash)
                    shares += (buy * (1 - COST)) / series[j]["c"]
                    cash -= buy
                else:  # sell
                    sell_val = -delta
                    shares -= sell_val / series[j]["c"]
                    cash += sell_val * (1 - COST)
                trades += 1; switches += 1; cur_weight = target
        curve.append((s["d"], eq))
    final_eq = cash + shares * series[idx[-1]]["c"]
    # monthly distribution
    rets_m = []
    prev = START
    for m, eq in monthly:
        rets_m.append(eq / prev - 1); prev = eq
    # max drawdown on daily curve
    peak, maxdd, peak_d, trough_d = -1, 0.0, None, None
    last_high_d, longest_gap, cur_gap_start = curve[0][0], 0, None
    high_eq = curve[0][1]; last_high_idx = 0; longest_between = 0
    for n, (d, eq) in enumerate(curve):
        if eq >= high_eq:
            high_eq = eq
            longest_between = max(longest_between, n - last_high_idx)
            last_high_idx = n
        peak = max(peak, eq)
        dd = eq / peak - 1
        if dd < maxdd: maxdd = dd
    longest_between = max(longest_between, len(curve) - 1 - last_high_idx)
    # losing streak (months)
    streak = cur = 0
    for r in rets_m:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    dist = {
        "periods": len(rets_m),
        "median_period_pct": round(statistics.median(rets_m) * 100, 2) if rets_m else None,
        "share_positive_pct": round(100 * sum(1 for r in rets_m if r > 0) / len(rets_m), 1) if rets_m else None,
        "best_period_pct": round(max(rets_m) * 100, 2) if rets_m else None,
        "worst_period_pct": round(min(rets_m) * 100, 2) if rets_m else None,
        "longest_losing_streak_months": streak,
        "longest_days_between_new_highs": longest_between,
        "avg_period_pct_secondary": round(statistics.mean(rets_m) * 100, 2) if rets_m else None,
    }
    return {"final": round(final_eq, 2), "max_dd_pct": round(maxdd * 100, 2),
            "trades": trades, "switches": switches, "costs": round(costs, 2),
            "dist": dist, "curve": [[d, round(e, 4)] for d, e in curve]}


def buy_hold(series, start, end):
    idx = [i for i, s in enumerate(series) if start <= s["d"] <= end]
    sh = (START - START * COST) / series[idx[0]]["c"]
    return round(sh * series[idx[-1]]["c"], 2)


def main():
    bars = load_spy(); vix = load_vix(); series = build_series(bars, vix)
    dates = [s["d"] for s in series]
    vrp_by_date = {s["d"]: s["vrp"] for s in series if s["vrp"] is not None}
    vrp_dates = sorted(vrp_by_date)
    results = {"family": "hunt-options-implied", "program": "v13-best-rules",
               "spec": "BEST-RULES-SPEC.md", "verdict_ceiling": "CANDIDATE", "roads": {}}
    for road, (start, end) in ROADS.items():
        mine = run_dial(series, start, end)
        bh = buy_hold(series, start, end)
        # placebos: phase-shifted VRP
        random.seed(1300 + len(road))
        placebo_finals = []
        pos = {d: n for n, d in enumerate(vrp_dates)}
        for seed in range(20):
            rng = random.Random(9000 + seed * 37 + len(road))
            shift = rng.randint(20, 500)
            override = {}
            for d in vrp_dates:
                n = pos[d]
                src = vrp_dates[(n + shift) % len(vrp_dates)]
                override[d] = vrp_by_date[src]
            pf = run_dial(series, start, end, vrp_override=override)
            placebo_finals.append(pf["final"])
        beaten = sum(1 for p in placebo_finals if mine["final"] > p)
        results["roads"][road] = {
            "my_rules": {k: mine[k] for k in ("final", "max_dd_pct", "trades", "switches", "costs", "dist")},
            "equity_curve": mine["curve"],
            "spy_buy_hold_same_plumbing": bh, "spy_reference": SPYREF[road],
            "champion_vm": CHAMP[road],
            "published_form": "STILL UNBUILDABLE (v12) — no honest final exists",
            "placebos_beaten_of_20": beaten,
            "placebo_finals": sorted(placebo_finals),
            "beats_champion": mine["final"] > CHAMP[road],
        }
        print(road, mine["final"], "DD", mine["max_dd_pct"], "BH", bh,
              "placebos beaten", beaten, "switches", mine["switches"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("WROTE results.json")


if __name__ == "__main__":
    main()
