#!/usr/bin/env python3
"""V13 BEST RULES — hunt-vix-term-structure. Simulation only.
Implements BEST-RULES-SPEC.md (frozen before this run):
  Vehicle SVXY (adjusted bars, actual traded history). R=VIX/VIX3M (CBOE).
  EXIT fast: close R>1.00 -> sell all next open.
  ENTRY slow: R<=0.95 on 5 consecutive closes -> buy all next open.
  Costs 0.10%/side + $0.01/share on sells. Cash 0%. $100 pots. NO floor.
Benchmarks: SVXY buy-hold, VXX buy-hold (roll-cost print), SPY buy-hold
(same plumbing, pxfull cache). Placebos: (A) phase-shifted R 20 seeds,
(B) random-timing blocks 20 seeds. Confirmation folds/halves only if a
road beats champion V+M.
"""
import csv, json, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0; COST = 0.001; SELLFEE = 0.01
ROADS = {"LONG": ("2011-10-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12 = {"LONG": 504.96, "DECADE": 287.04, "CONT": 251.81, "VAL": 168.73}

def load_yahoo(path):
    j = json.load(open(path)); r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        f = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * f, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def load_cboe(path):
    out = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            m, d, y = row["DATE"].split("/")
            out[f"{y}-{int(m):02d}-{int(d):02d}"] = float(row["CLOSE"])
    return out

def max_dd(curve):
    peak, dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v); dd = min(dd, (v / peak - 1.0) * 100.0)
    return round(dd, 2)

def period_stats(curve):
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months); rets = []; prev = START
    for k in keys:
        rets.append(months[k] / prev - 1.0); prev = months[k]
    pos = sum(1 for r in rets if r > 0); streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak, since, worst = START, 0, 0
    for k in keys:
        if months[k] >= peak: peak, since = months[k], 0
        else: since += 1; worst = max(worst, since)
    return {"n_periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1) if rets else 0.0,
            "median_pct": round(statistics.median(rets) * 100, 2) if rets else 0.0,
            "best_pct": round(max(rets) * 100, 2) if rets else 0.0,
            "worst_pct": round(min(rets) * 100, 2) if rets else 0.0,
            "longest_losing_streak": streak, "longest_stretch_between_highs_months": worst,
            "avg_pct_secondary": round(statistics.mean(rets) * 100, 2) if rets else 0.0}

def run_strategy(bars, ratio, s, e):
    """ratio: dict date->R (asof). Decide close t, fill open t+1."""
    idx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
    cash, shares, trades, costs = START, 0.0, 0, 0.0
    curve = []; pos = 0; pending = 0  # pending: +1 buy at next open, -1 sell
    holds = []; cur_hold = 0; entries = 0; worst_day = (None, 0.0); prev_eq = START
    for k, i in enumerate(idx):
        b = bars[i]
        if pending == 1 and pos == 0:
            c = cash * COST; shares = (cash - c) / b["o"]; costs += c; cash = 0.0
            pos = 1; trades += 1; entries += 1; cur_hold = 0; pending = 0
        elif pending == -1 and pos == 1:
            gross = shares * b["o"]; c = gross * COST + shares * SELLFEE
            cash = gross - c; costs += c; shares = 0.0; pos = 0; trades += 1
            holds.append(cur_hold); pending = 0
        eq = cash + shares * b["c"]
        curve.append((b["d"], round(eq, 4)))
        if prev_eq > 0:
            dr = eq / prev_eq - 1.0
            if dr < worst_day[1]: worst_day = (b["d"], round(dr * 100, 2))
        prev_eq = eq
        if pos == 1: cur_hold += 1
        # decide at close
        r = ratio.get(b["d"])
        if r is None: continue
        if pos == 1 and r > 1.00: pending = -1
        elif pos == 0 and pending == 0:
            # 5 consecutive closes R<=0.95 ending today (use bars' own dates)
            ok = True
            for j in range(i - 4, i + 1):
                if j < 0: ok = False; break
                rj = ratio.get(bars[j]["d"])
                if rj is None or rj > 0.95: ok = False; break
            if ok: pending = 1
    if pos == 1: holds.append(cur_hold)
    # worst single day computed from the finished curve (authoritative)
    wd = (None, 0.0)
    for k in range(1, len(curve)):
        drp = (curve[k][1] / curve[k - 1][1] - 1.0) * 100.0
        if drp < wd[1]: wd = (curve[k][0], round(drp, 2))
    return {"final": curve[-1][1], "trades": trades, "entries": entries, "worst_day_curve": wd,
            "costs": round(costs, 2), "maxdd_pct": max_dd(curve), "curve": curve,
            "periods": period_stats(curve), "holds": holds,
            "in_days": sum(holds), "worst_day": worst_day}

def buyhold(bars, s, e):
    idx = [b for b in bars if s <= b["d"] <= e]
    if not idx: return None
    sh = (START - START * COST) / idx[0]["o"]
    gross = sh * idx[-1]["c"]
    return round(gross - (gross * COST + sh * SELLFEE), 2)

def main():
    svxy = load_yahoo(os.path.join(HERE, "SVXY_yahoo.json"))
    vxx = load_yahoo(os.path.join(HERE, "VXX_yahoo.json"))
    spy = load_yahoo(SPY_PX)
    vix = load_cboe(os.path.join(HERE, "VIX_History.csv"))
    vix3m = load_cboe(os.path.join(HERE, "VIX3M_History.csv"))
    # asof ratio on SVXY dates
    ratio = {}; last = None
    vix_dates = sorted(vix); import bisect
    for b in svxy:
        j = bisect.bisect_right(vix_dates, b["d"]) - 1
        if j >= 0:
            d0 = vix_dates[j]
            if d0 in vix3m: last = vix[d0] / vix3m[d0]
        ratio[b["d"]] = last
    res = {"family": "hunt-vix-term-structure", "program": "v13-best-rules",
           "vehicle_first_day": svxy[0]["d"], "vxx_first_day": vxx[0]["d"],
           "roads": {}, "placebos": {}, "confirmation": {}}
    curves = {}
    for road, (s, e) in ROADS.items():
        mine = run_strategy(svxy, ratio, s, e)
        n_days = sum(1 for b in svxy if s <= b["d"] <= e)
        res["roads"][road] = {
            "window": [s, e], "my_rules_final": mine["final"], "my_maxdd_pct": mine["maxdd_pct"],
            "my_trades": mine["trades"], "my_entries": mine["entries"], "my_costs": mine["costs"],
            "my_worst_day": mine["worst_day_curve"], "pct_days_invested": round(100.0 * mine["in_days"] / n_days, 1),
            "svxy_buyhold": buyhold(svxy, s, e), "vxx_buyhold_rollcost_print": buyhold(vxx, s, e),
            "spy_buyhold_same_plumbing": buyhold(spy, s, e),
            "v12_published_spy_gate_final": V12[road], "champion_vm": CHAMP[road],
            "spy_program_ref": SPYREF[road], "periods_monthly_my_rules": mine["periods"]}
        curves[road] = mine["curve"]
        # placebo A: phase-shifted ratio
        dates = [b["d"] for b in svxy]; rvals = [ratio[d] for d in dates]
        fa = []
        for seed in range(1, 21):
            rng = random.Random(seed * 977 + len(road))
            shift = rng.randint(20, 500)
            shifted = {dates[i]: rvals[(i - shift) % len(dates)] for i in range(len(dates))}
            fa.append(run_strategy(svxy, shifted, s, e)["final"])
        # placebo B: random-timing blocks (matched in-days, real hold lengths)
        fb = []
        idxs = [i for i, b in enumerate(svxy) if s <= b["d"] <= e]
        for seed in range(1, 21):
            rng = random.Random(seed * 331 + len(road))
            in_set = set(); target = mine["in_days"]; guard = 0
            holds_pool = mine["holds"] or [5]
            while len(in_set) < target and guard < 5000:
                guard += 1
                st = rng.choice(idxs); ln = rng.choice(holds_pool)
                for k in range(st, min(st + ln, idxs[-1] + 1)): in_set.add(k)
            # run with explicit in-set: emulate via custom loop reusing costs model
            cash, shares, trades = START, 0.0, 0; pos = 0; pend = 0; eq = START
            for k, i in enumerate(idxs):
                b = svxy[i]
                want = 1 if i in in_set else 0
                if k > 0:
                    prev_want = 1 if idxs[k - 1] in in_set else 0
                    if want != prev_want: pend = 1 if want == 1 else -1
                if pend == 1 and pos == 0:
                    c = cash * COST; shares = (cash - c) / b["o"]; cash = 0.0; pos = 1; pend = 0
                elif pend == -1 and pos == 1:
                    gross = shares * b["o"]; cash = gross - (gross * COST + shares * SELLFEE)
                    shares = 0.0; pos = 0; pend = 0
                eq = cash + shares * b["c"]
            fb.append(round(eq, 2))
        res["placebos"][road] = {
            "phase_shifted_ratio": {"finals": [round(x, 2) for x in fa],
                "beaten": sum(1 for x in fa if mine["final"] > x), "median": round(statistics.median(fa), 2)},
            "random_timing_blocks": {"finals": fb,
                "beaten": sum(1 for x in fb if mine["final"] > x), "median": round(statistics.median(fb), 2)}}
        # confirmation if champion beaten
        if mine["final"] > CHAMP[road]:
            yrs = {}
            for y in range(int(s[:4]), 2027):
                ys, ye = f"{y}-01-01", f"{y}-12-31"
                if any(ys <= b["d"] <= ye for b in svxy):
                    yrs[str(y)] = run_strategy(svxy, ratio, max(ys, s), min(ye, e))["final"]
            mid_i = idxs[len(idxs) // 2]; mid = svxy[mid_i]["d"]
            halves = {"first_half": run_strategy(svxy, ratio, s, mid)["final"],
                      "second_half": run_strategy(svxy, ratio, mid, e)["final"]}
            res["confirmation"][road] = {"yearly_folds": yrs, "half_windows": halves,
                                         "champion": CHAMP[road]}
    # Feb-2018 episode print
    ep = {}
    for d in ["2018-02-02", "2018-02-05", "2018-02-06", "2018-02-07", "2018-02-08"]:
        for road_curve in [curves["LONG"]]:
            m = dict(road_curve)
            if d in m: ep[d] = m[d]
    res["feb2018_long_equity"] = ep
    res["ratio_on_2018_02_05"] = ratio.get("2018-02-05")
    res["curves"] = curves
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    for road in ROADS:
        r = res["roads"][road]; p = res["placebos"][road]
        print(road, "mine", r["my_rules_final"], "DD", r["my_maxdd_pct"], "trades", r["my_trades"],
              "| SVXYbh", r["svxy_buyhold"], "| VXXbh", r["vxx_buyhold_rollcost_print"],
              "| SPYbh", r["spy_buyhold_same_plumbing"],
              "| placA beaten", p["phase_shifted_ratio"]["beaten"], "/20 med", p["phase_shifted_ratio"]["median"],
              "| placB beaten", p["random_timing_blocks"]["beaten"], "/20 med", p["random_timing_blocks"]["median"])
    print("feb2018", ep, "R 2018-02-05", res["ratio_on_2018_02_05"])
    print("confirmation", json.dumps(res["confirmation"])[:500])

if __name__ == "__main__":
    main()
