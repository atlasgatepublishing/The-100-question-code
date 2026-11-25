"""V13 Best Rules — Zweig Four Percent Model.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Design: signal AND vehicle unified on RSP (tradable equal-weight S&P 500 ETF);
+-4% swing-extreme trigger on RSP weekly closes; all-in/cash; next-open
execution; program costs 0.10%/side + $0.01 sell fee; NO floor.
Engine functions (simulate_targets / period_stats / buy_hold /
four_percent_states / weekly_series_of) copied from the v12 family script.
Placebos: (a) circular shift of state series, (b) pure random timing with
matched invested fraction — 20 seeds each.
"""
import json, os, time, random, statistics, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 321.78, "DECADE": 228.17, "CONT": 210.63, "VAL": 154.53}

def fetch_rsp():
    cache = os.path.join(HERE, "rsp_daily_cache.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    url = "https://query1.finance.yahoo.com/v8/finance/chart/RSP?range=25y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": q["high"][i]*ratio,
                     "l": q["low"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    json.dump(bars, open(cache, "w"))
    return bars

def simulate_targets(bars, targets, start, end, cost, sell_fee):
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    if not days: return None
    desired = 0
    for d in sorted(targets):
        if d < days[0]["d"]: desired = targets[d]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired if desired else None
    days_invested = 0
    for b in days:
        if pending is not None:
            if pending == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif pending == 0 and shares > 0:
                val = shares * b["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if b["d"] in targets:
            t = targets[b["d"]]
            if t != (1 if shares > 0 else 0):
                pending = t
            desired = t
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = days[-1]; val = shares * last["c"]; fee = val * cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/len(days), 1) if days else 0.0,
            "equity_curve": curve}

def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    if not days: return None
    sh = (START / (1 + cost)) / days[0]["o"]
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * cost + sell_fee)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def period_stats(curve, tempo="weekly"):
    if not curve: return None
    seen = {}
    for d, v in curve:
        if tempo == "weekly":
            y, m, dd = map(int, d.split("-"))
            k = str(date(y, m, dd).isocalendar()[:2])
        else:
            k = d[:7]
        seen[k] = v
    vals = [seen[k] for k in sorted(seen)]
    series = [START] + vals
    if len(series) < 2: return None
    rets = [(series[i]/series[i-1] - 1.0)*100.0 if series[i-1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": tempo, "periods": len(rets),
            "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_periods": longest}

def weekly_series_of(bars):
    wk = {}
    for b in bars:
        y, m, dd = map(int, b["d"].split("-"))
        key = date(y, m, dd).isocalendar()[:2]
        wk[key] = (b["d"], b["c"])
    return [wk[k] for k in sorted(wk)]

def four_percent_states(weekly_series):
    targets = {}; events = []
    state = 0
    lo = hi = weekly_series[0][1]
    for d, v in weekly_series:
        if state == 0:
            lo = min(lo, v)
            if v >= lo * 1.04:
                state = 1; hi = v
                events.append([d, "BUY", round(v, 2)])
        else:
            hi = max(hi, v)
            if v <= hi * 0.96:
                state = 0; lo = v
                events.append([d, "SELL", round(v, 2)])
        targets[d] = state
    return targets, events

def shifted_weekly_targets(targets, seed):
    dates = sorted(targets); vals = [targets[d] for d in dates]
    rng = random.Random(seed)
    k = rng.randrange(1, len(vals))
    vals = vals[k:] + vals[:k]
    return dict(zip(dates, vals))

def random_timing_targets(targets, start, end, seed):
    """Random weekly state series over the road's signal dates, matched to the
    real signal's invested fraction on that road (per spec, frozen)."""
    dates = sorted(d for d in targets if start <= d <= end)
    if not dates: return {}
    frac = statistics.mean(targets[d] for d in dates)
    rng = random.Random(10000 + seed)
    return {d: (1 if rng.random() < frac else 0) for d in dates}

def confirmation(bars, targets, road_start, road_end):
    """Frozen bars: (1) yearly folds — median fold final > $100 and >=60% of
    folds positive; (2) half-windows — beat RSP buy-hold in BOTH halves."""
    folds = {}
    y0, y1 = int(road_start[:4]), int(road_end[:4])
    for y in range(y0, y1 + 1):
        s = max(road_start, f"{y}-01-01"); e = min(road_end, f"{y}-12-31")
        r = simulate_targets(bars, targets, s, e, STK_COST, STK_SELL_FEE)
        if r: folds[str(y)] = r["final"]
    vals = list(folds.values())
    med = statistics.median(vals) if vals else 0.0
    share_pos = (sum(1 for v in vals if v > START) / len(vals)) if vals else 0.0
    days = [b["d"] for b in bars if road_start <= b["d"] <= road_end]
    mid = days[len(days)//2]
    halves = {}
    for label, (s, e) in (("first", (road_start, mid)), ("second", (mid, road_end))):
        rs = simulate_targets(bars, targets, s, e, STK_COST, STK_SELL_FEE)
        rb = buy_hold(bars, s, e, STK_COST, STK_SELL_FEE)
        halves[label] = {"strategy": rs["final"], "rsp_hold": rb["final"],
                         "beats_hold": rs["final"] > rb["final"]}
    passed = (med > START and share_pos >= 0.60
              and halves["first"]["beats_hold"] and halves["second"]["beats_hold"])
    return {"yearly_folds": folds, "median_fold_final": round(med, 2),
            "share_folds_positive_pct": round(100*share_pos, 1),
            "half_windows": halves, "passed": passed}

def main():
    log = []
    rsp = fetch_rsp()
    log.append(f"RSP bars: {rsp[0]['d']} -> {rsp[-1]['d']} ({len(rsp)} bars), Yahoo adjusted, cached rsp_daily_cache.json")
    ws = weekly_series_of(rsp)
    targets, events = four_percent_states(ws)
    log.append(f"RSP weekly series: {ws[0][0]} -> {ws[-1][0]} ({len(ws)} weeks); signal events: {len(events)}")
    out = {"family": "hunt-zweig-four-percent (Zweig Four Percent Model, 1986)",
           "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "design": "Signal and vehicle unified on RSP (tradable equal-weight S&P 500 ETF); +-4% swing-extreme trigger on RSP weekly closes; all-in/cash; next-open execution; 0.10%/side + $0.01 sell fee; NO floor",
           "honesty": "RSP is NOT the Value Line Geometric Index (~500 large-cap arithmetic equal-weight vs ~1,700 all-cap geometric). ^VLG unobtainable free (Yahoo 404, re-confirmed 2026-11-22). See spec honesty paragraph.",
           "signal_series_range": f"{ws[0][0]} -> {ws[-1][0]} ({len(ws)} weeks)",
           "signal_events": events, "roads": {}}
    for name, (s, e) in ROADS.items():
        r = simulate_targets(rsp, targets, s, e, STK_COST, STK_SELL_FEE)
        bh = buy_hold(rsp, s, e, STK_COST, STK_SELL_FEE)
        shift_fin, rand_fin = [], []
        for seed in range(1, 21):
            shift_fin.append(simulate_targets(rsp, shifted_weekly_targets(targets, seed), s, e, STK_COST, STK_SELL_FEE)["final"])
            rt = random_timing_targets(targets, s, e, seed)
            # random-timing placebo needs pre-road desired state 0; simulate_targets handles via targets dict
            rand_fin.append(simulate_targets(rsp, rt, s, e, STK_COST, STK_SELL_FEE)["final"])
        rec = {"my_rules": {**r, "period_stats_weekly": period_stats(r["equity_curve"], "weekly"),
                            "period_stats_monthly": period_stats(r["equity_curve"], "monthly")},
               "rsp_buy_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                "period_stats_weekly": period_stats(bh["equity_curve"], "weekly")},
               "published_form_final_v12": PUBLISHED[name],
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "placebo_shift": {"seed_finals": shift_fin,
                                 "beaten_of_20": sum(1 for p in shift_fin if r["final"] > p),
                                 "design": "circular shift of weekly state series, 20 seeds"},
               "placebo_random_timing": {"seed_finals": rand_fin,
                                         "beaten_of_20": sum(1 for p in rand_fin if r["final"] > p),
                                         "design": "random weekly states, matched invested fraction, 20 seeds"}}
        if r["final"] > CHAMP[name]:
            rec["confirmation"] = confirmation(rsp, targets, s, e)
            log.append(f"{name}: BEAT CHAMPION — confirmation run: passed={rec['confirmation']['passed']}")
        out["roads"][name] = rec
        log.append(f"{name}: my-rules ${r['final']} (DD {r['max_dd_pct']}%, invested {r['invested_pct']}%, orders {r['orders']}, costs ${r['costs']}) | RSP hold ${bh['final']} | published ${PUBLISHED[name]} | champ ${CHAMP[name]} | shift placebos beaten {rec['placebo_shift']['beaten_of_20']}/20 | random-timing beaten {rec['placebo_random_timing']['beaten_of_20']}/20")
        print(log[-1], flush=True)
    out["run_log"] = log
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(HERE, "run.log"), "w") as f:
        f.write("\n".join(log) + "\n")
    print("DONE")

if __name__ == "__main__":
    main()
