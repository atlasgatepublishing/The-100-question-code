#!/usr/bin/env python3
"""V13 Best Rules — hunt-zweig-super-model.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Design: Four Percent trend state is primary (from v12's derived
signal_series.csv, read-only input); fed-funds-target leg only, published
decay, as a 0.5/1.0 exposure dial; target = trend * dial; weekly eval,
trade next open; 0.10%/side + $0.01/sell; NO floor.
FF events: v12 results.json fed_funds_events (announcement dates, unrevised).
"""
import csv, json, os, random, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-zweig-super-model")
sys.path.insert(0, V12)
exec(open(os.path.join(V12, "engine_core.py")).read())  # load_stock, buy_hold, period_stats, START, costs

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
PUBLISHED = {"LONG": 579.92, "DECADE": 259.16, "CONT": 210.38, "VAL": 144.00}

def add_months(dstr, m):
    y, mo, dd = map(int, dstr.split("-"))
    mo2 = mo + m; y += (mo2 - 1) // 12; mo2 = (mo2 - 1) % 12 + 1
    return date(y, mo2, min(dd, 28)).isoformat()

def ff_state_on(eval_date, ff_events):
    """Published FedLeg decay applied to the fed funds instrument alone.
    Returns raw points: cut -> +2 (1 after 6mo, 0 after 12mo);
    hike -> -1 for 6mo. Later events overwrite earlier (v12 convention)."""
    pts, set_date = 0, None
    for d, direction in ff_events:
        if d > eval_date: break
        pts = 2 if direction < 0 else -1
        set_date = d
    if set_date is None or pts == 0: return 0
    if pts == 2:
        if eval_date > add_months(set_date, 12): return 0
        if eval_date > add_months(set_date, 6): return 1
        return 2
    if eval_date > add_months(set_date, 6): return 0
    return -1

def build_targets():
    v12 = json.load(open(os.path.join(V12, "results.json")))
    ff_events = sorted((d, int(dr)) for d, dr in v12["fed_funds_events"])
    weekly = []
    with open(os.path.join(V12, "signal_series.csv")) as f:
        for r in csv.DictReader(f):
            trend = 1 if int(r["momentum_pts"]) == 2 else 0
            ff = ff_state_on(r["date"], ff_events)
            dial = 0.5 if ff == -1 else 1.0
            weekly.append({"date": r["date"], "trend": trend, "ff_raw": ff,
                           "dial": dial, "target": trend * dial})
    return weekly, ff_events

def simulate_frac(bars, weekly_targets, start, end, shift_seed=None):
    """weekly_targets: list of dicts with date + target exposure in {0,.5,1}.
    Target decided at that date's close; rebalance at next bar's open to the
    target fraction of equity. Costs on traded notional; $0.01 per sell."""
    days = [b for b in bars if start <= b["d"] <= end]
    if not days: return None
    tg = {w["date"]: w["target"] for w in weekly_targets}
    if shift_seed is not None:
        dates = [w["date"] for w in weekly_targets]
        vals = [w["target"] for w in weekly_targets]
        rng = random.Random(shift_seed)
        k = rng.randrange(1, len(vals))
        vals = vals[k:] + vals[:k]
        tg = dict(zip(dates, vals))
    desired = 0.0
    for d in sorted(tg):
        if d < days[0]["d"]: desired = tg[d]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired if desired > 0 else None
    days_invested = 0
    for b in days:
        if pending is not None:
            eq_open = cash + shares * b["o"]
            want = pending * eq_open
            have = shares * b["o"]
            diff = want - have
            if diff > 0.01:  # buy
                bv = diff / (1 + STK_COST); fee = bv * STK_COST
                shares += bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif diff < -0.01:  # sell
                val = -diff; fee = val * STK_COST + STK_SELL_FEE
                shares -= val / b["o"]; cash += val - fee; costs += fee
                if shares < 1e-9: shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if b["d"] in tg:
            if tg[b["d"]] != desired:
                pending = tg[b["d"]]
            desired = tg[b["d"]]
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = days[-1]; val = shares * last["c"]; fee = val * STK_COST + STK_SELL_FEE
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(days), 1),
            "equity_curve": curve}

def main():
    weekly, ff_events = build_targets()
    with open(os.path.join(HERE, "target_series.csv"), "w") as f:
        f.write("date,trend,ff_raw,dial,target\n")
        for w in weekly:
            f.write(f"{w['date']},{w['trend']},{w['ff_raw']},{w['dial']},{w['target']}\n")
    spy = load_stock("SPY")
    out = {"family": "hunt-zweig-super-model — V13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "design": "Four Percent trend primary; fed-funds-only dial 0.5 while a hike is <6 months old else 1.0; target=trend*dial; weekly, next-open; 0.10%/side + $0.01 sell; no floor",
           "ff_events_used": ff_events, "roads": {}}
    changes = sum(1 for a, b in zip(weekly, weekly[1:]) if a["target"] != b["target"])
    print(f"weekly targets: {len(weekly)} weeks, {changes} target changes", flush=True)
    for name, (s, e) in ROADS.items():
        r = simulate_frac(spy, weekly, s, e)
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        pf = [simulate_frac(spy, weekly, s, e, shift_seed=seed)["final"] for seed in range(1, 21)]
        rec = {"best_rules": {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")},
               "published_form_final": PUBLISHED[name],
               "benchmark_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")},
               "placebo": {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if r["final"] > p),
                           "design": "circular shift of weekly target-exposure series, 20 seeds"},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "beats_champion": r["final"] > CHAMP[name]}
        out["roads"][name] = rec
        print(f"{name}: best ${r['final']} (DD {r['max_dd_pct']}%, inv {r['invested_pct']}%, orders {r['orders']}) "
              f"published ${PUBLISHED[name]} SPY ${bh['final']} champ ${CHAMP[name]} placebos {rec['placebo']['beaten_of_20']}/20", flush=True)
    # Confirmation machinery — runs only if a road beats the champion (spec bars frozen)
    if any(out["roads"][n]["beats_champion"] for n in ROADS):
        conf = {}
        for name, (s, e) in ROADS.items():
            if not out["roads"][name]["beats_champion"]: continue
            mid = out["roads"][name]["best_rules"]["equity_curve"][len(out["roads"][name]["best_rules"]["equity_curve"]) // 2][0]
            halves = {}
            for label, (hs, he) in {"first_half": (s, mid), "second_half": (mid, e)}.items():
                rr = simulate_frac(spy, weekly, hs, he)
                bb = buy_hold(spy, hs, he, STK_COST, STK_SELL_FEE)
                halves[label] = {"start": hs, "end": he, "best_final": rr["final"], "spy_final": bb["final"],
                                 "beats_spy": rr["final"] > bb["final"]}
            years = {}
            for y in range(int(s[:4]), int(e[:4]) + 1):
                ys, ye = f"{y}-01-01", f"{y}-12-31"
                if ye < s or ys > e: continue
                rr = simulate_frac(spy, weekly, max(ys, s), min(ye, e))
                bb = buy_hold(spy, max(ys, s), min(ye, e), STK_COST, STK_SELL_FEE)
                if rr and bb: years[str(y)] = {"best_final": rr["final"], "spy_final": bb["final"], "beats_spy": rr["final"] > bb["final"]}
            share = round(100.0 * sum(1 for v in years.values() if v["beats_spy"]) / len(years), 1) if years else 0.0
            conf[name] = {"half_windows": halves, "yearly_folds": years, "yearly_share_beats_spy_pct": share,
                          "confirmed": all(h["beats_spy"] for h in halves.values()) and share >= 60.0}
        out["confirmation"] = conf
        print("CONFIRMATION:", json.dumps(conf, indent=1), flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
