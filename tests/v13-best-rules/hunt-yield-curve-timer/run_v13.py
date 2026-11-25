#!/usr/bin/env python3
"""v13 BEST RULES — hunt-yield-curve-timer.
Frozen spec (BEST-RULES-SPEC.md): T10Y3M monthly check; inversion -> 50%
exposure; re-entry on un-inversion OR after 12 reduced months in one episode
(episode-locked); no floor; SPY; program costs 0.10%/side + $0.01 sell fee;
fills next open. Placebos: 20-seed circular shift + 20-seed random timing.
Signal read in place from the v12 derived series (input only, not re-cached).
"""
import csv, json, os, random, statistics, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
START = 100.0
COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SIG = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-yield-curve-timer/signal_series.csv")
CAP_MONTHS = 12

def load_spy():
    j = json.load(open(PX)); r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]; adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i]): continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars

def load_spread():
    rows = []
    with open(SIG) as f:
        rd = csv.DictReader(f)
        for r in rd:
            try: rows.append((r["date"], float(r["t10y3m"])))
            except Exception: pass
    rows.sort()
    return rows

def monthly_checks(bars):
    checks = {}
    for b in bars: checks[b["d"][:7]] = b["d"]
    return [checks[m] for m in sorted(checks)]

def spread_on(spread, d):
    v = None
    for sd, sv in spread:
        if sd <= d: v = sv
        else: break
    return v

def build_targets(bars, spread):
    """State machine over all monthly checks. Returns dict check_date ->
    exposure target (1.0 or 0.5) for the month following the check, plus
    episode log. Point-in-time: each check sees only spread obs <= check."""
    targets = {}; episodes = []
    in_ep = False; spent = False; reduced = 0; ep_start = None
    for d in monthly_checks(bars):
        s = spread_on(spread, d)
        if s is None: continue
        if s >= 0:
            if in_ep: episodes.append([ep_start, d, reduced]); in_ep = False
            spent = False; reduced = 0
            targets[d] = 1.0
        else:
            if not in_ep: in_ep = True; ep_start = d; spent = False; reduced = 0
            if not spent and reduced < CAP_MONTHS:
                targets[d] = 0.5; reduced += 1
            else:
                targets[d] = 1.0; spent = True
    if in_ep: episodes.append([ep_start, "open at series end", reduced])
    return targets, episodes

def simulate(bars, targets, start, end):
    """targets: dict date->exposure decided at that date's close; changes fill
    at next bar's open. Entry exposure = last target before road start."""
    days = [b for b in bars if start <= b["d"] <= end]
    if not days: return None
    desired = 1.0
    for d in sorted(targets):
        if d < days[0]["d"]: desired = targets[d]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired
    invested_days = 0
    for b in days:
        if pending is not None:
            eq_o = cash + shares * b["o"]
            want = eq_o * pending
            have = shares * b["o"]
            if want > have + 1e-9 and cash > 0:
                spend = min(cash, (want - have) / (1 + COST))
                if spend > 0.01:
                    fee = spend * COST; shares += spend / b["o"]; cash -= spend + fee; costs += fee
                    trades.append([b["d"], "BUY", round(b["o"], 4), round(spend, 2), round(fee, 2)])
            elif want < have - 1e-9:
                sell_val = have - want
                fee = sell_val * COST + SELL_FEE
                shares -= sell_val / b["o"]; cash += sell_val - fee; costs += fee
                trades.append([b["d"], "SELL", round(b["o"], 4), round(sell_val, 2), round(fee, 2)])
            pending = None
        if b["d"] in targets:
            pending = targets[b["d"]]
        eq = cash + shares * b["c"]
        if shares > 0: invested_days += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = days[-1]; val = shares * last["c"]; fee = val * COST + SELL_FEE
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_days_pct": round(100.0*invested_days/len(days), 1),
            "equity_curve": curve}

def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    sh = (START / (1 + COST)) / days[0]["o"]
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * COST + SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def period_stats(curve):
    if not curve: return None
    seen = {}
    for d, v in curve: seen[d[:7]] = v
    vals = [seen[k] for k in sorted(seen)]
    series = [START] + vals
    rets = [(series[i]/series[i-1]-1.0)*100.0 if series[i-1] > 0 else 0.0 for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i-last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": "monthly", "periods": len(rets),
            "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_periods": longest}

def main():
    bars = load_spy(); spread = load_spread()
    targets, episodes = build_targets(bars, spread)
    out = {"family": "hunt-yield-curve-timer", "program": "v13-best-rules",
           "verdict_ceiling": "CANDIDATE",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "rules": "T10Y3M monthly check; inversion -> 50% exposure; re-entry on un-inversion or after 12 reduced months per episode (episode-locked); no floor; SPY; 0.10%/side + $0.01 sell fee; next-open fills; cash 0%",
           "inversion_episodes_full_series": episodes,
           "roads": {}}
    check_dates = sorted(targets)
    for name, (s, e) in ROADS.items():
        r = simulate(bars, targets, s, e)
        bh = buy_hold(bars, s, e)
        road_checks = [d for d in check_dates if s <= d <= e]
        reduced_months = sum(1 for d in road_checks if targets[d] == 0.5)
        eps_in_road = [ep for ep in episodes if ep[1] >= s and ep[0] <= e]
        # placebos: circular shift of full monthly target series
        vals = [targets[d] for d in check_dates]
        shift_finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); k = rng.randrange(1, len(vals))
            st = dict(zip(check_dates, vals[k:] + vals[:k]))
            shift_finals.append(simulate(bars, st, s, e)["final"])
        # random timing: same count of reduced months, randomly placed
        n_red = sum(1 for v in vals if v == 0.5)
        rand_finals = []
        for seed in range(1, 21):
            rng = random.Random(1000 + seed)
            red_idx = set(rng.sample(range(len(vals)), n_red))
            rt = {d: (0.5 if i in red_idx else 1.0) for i, d in enumerate(check_dates)}
            rand_finals.append(simulate(bars, rt, s, e)["final"])
        rec = {"my_rules": {**r, "period_stats_monthly": period_stats(r["equity_curve"])},
               "spy_buy_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                "period_stats_monthly": period_stats(bh["equity_curve"])},
               "spy_program_ref": SPYREF[name], "champion_vm": CHAMP[name],
               "published_v12_constructed_final": {"LONG": 591.80, "DECADE": 264.45, "CONT": 225.49, "VAL": 115.95}[name],
               "episodes_overlapping_road": eps_in_road,
               "reduced_months_decided_in_road": reduced_months,
               "placebo_shift": {"seed_finals": shift_finals, "beaten_of_20": sum(1 for p in shift_finals if r["final"] > p)},
               "placebo_random_timing": {"seed_finals": rand_finals, "beaten_of_20": sum(1 for p in rand_finals if r["final"] > p)}}
        # confirmation machinery (frozen bars) — computed for every road
        mid = days_mid = None
        days = [b["d"] for b in bars if s <= b["d"] <= e]
        mid = days[len(days)//2]
        h1 = (s, days[len(days)//2 - 1]); h2 = (days[len(days)//2], e)
        conf = {}
        for lab, (hs, he) in (("half1", h1), ("half2", h2)):
            conf[lab] = {"mine": simulate(bars, targets, hs, he)["final"],
                         "spy": buy_hold(bars, hs, he)["final"]}
        years = sorted(set(d[:4] for d in days))
        folds = {}
        for y in years:
            ys = max(s, y + "-01-01"); ye = min(e, y + "-12-31")
            folds[y] = {"mine": simulate(bars, targets, ys, ye)["final"],
                        "spy": buy_hold(bars, ys, ye)["final"]}
        wins = sum(1 for y in folds if folds[y]["mine"] > folds[y]["spy"])
        conf["yearly_folds"] = folds
        conf["years_beating_spy"] = f"{wins}/{len(folds)}"
        conf["median_year_mine"] = round(statistics.median(f["mine"] for f in folds.values()), 2)
        conf["median_year_spy"] = round(statistics.median(f["spy"] for f in folds.values()), 2)
        conf["beats_champion"] = r["final"] > CHAMP[name]
        conf["confirmation_passes"] = bool(conf["beats_champion"] and
            conf["half1"]["mine"] > conf["half1"]["spy"] and conf["half2"]["mine"] > conf["half2"]["spy"] and
            conf["median_year_mine"] >= conf["median_year_spy"] and wins > len(folds)/2)
        rec["confirmation"] = conf
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} (DD {r['max_dd_pct']}%) | v12 ${rec['published_v12_constructed_final']} | SPY ${bh['final']} | champ ${CHAMP[name]} | shift {rec['placebo_shift']['beaten_of_20']}/20 rand {rec['placebo_random_timing']['beaten_of_20']}/20 | reduced-mo {reduced_months} | conf {conf['confirmation_passes']}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
