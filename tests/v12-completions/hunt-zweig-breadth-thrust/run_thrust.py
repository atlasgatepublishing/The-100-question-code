#!/usr/bin/env python3
"""hunt-zweig-breadth-thrust — Zweig Breadth Thrust (Winning on Wall Street,
1986). Trigger PUBLISHED exactly: 10-day EMA (alpha 2/11) of NYSE advancing /
(advancing + declining); a thrust = the EMA rises from below 0.40 to above
0.615 within any 10-trading-day window. Exit CONSTRUCTED per frozen spec:
hold exactly 12 months, exit at the open of the first trading day after the
anniversary; a new thrust while holding does not extend the hold.
UNIVERSE SUBSTITUTION (frozen fallback, route iii): A/D computed from the
program's 154-name pond cache, NOT the NYSE — bias FLATTERS signal frequency,
printed with every number (see HUNT-LOG.md). SPY is the traded instrument."""
import json, os, random
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_core.py")).read())

HERE = os.path.dirname(os.path.abspath(__file__))

def pond_ad_series(spy_dates):
    closes = {}
    for sym in pond_symbols():
        try: bars = load_stock(sym)
        except Exception: continue
        closes[sym] = {b["d"]: b["c"] for b in bars}
    syms = list(closes)
    series = []
    prev = {}
    for d in spy_dates:
        adv = dec = 0
        for sym in syms:
            c = closes[sym].get(d)
            if c is not None and sym in prev:
                if c > prev[sym]: adv += 1
                elif c < prev[sym]: dec += 1
            if c is not None: prev[sym] = c
        if adv + dec >= 50:
            series.append((d, adv / (adv + dec), adv, dec))
    return series

def thrust_events(series):
    ema = None
    events = []
    armed_below = False
    below_start = None
    for i, (d, ratio, a, dn) in enumerate(series):
        ema = ratio if ema is None else ema + (2.0/11.0) * (ratio - ema)
        if ema < 0.40:
            if not armed_below: below_start = i
            armed_below = True
        if armed_below and ema > 0.615:
            if below_start is not None and i - below_start <= 9:
                events.append((d, round(ema, 4)))
            armed_below = False; below_start = None
        if armed_below and below_start is not None and i - below_start > 9:
            # window expired; re-arm only on a fresh dip structure: keep
            # watching from the most recent below-0.40 day
            below_start = i if ema < 0.40 else below_start
    return events

def targets_from_events(spy, events):
    dates = [b["d"] for b in spy]
    targets = {}
    holding_until = None
    ev_dates = [d for d, _ in events]
    for d in dates:
        if holding_until is not None and d > holding_until:
            targets[d] = 0; holding_until = None
        if d in ev_dates and holding_until is None:
            targets[d] = 1
            y = date.fromisoformat(d)
            holding_until = date.fromordinal(y.toordinal() + 365).isoformat()
    return targets

def random_event_targets(spy, n_events, seed):
    dates = [b["d"] for b in spy]
    rng = random.Random(seed)
    cand = [d for d in dates if d <= "2025-11-20"]
    picks = sorted(rng.sample(cand, min(n_events, len(cand)))) if n_events else []
    return targets_from_events(spy, [(d, None) for d in picks])

def main():
    spy = load_stock("SPY")
    spy_dates = [b["d"] for b in spy]
    series = pond_ad_series(spy_dates)
    events = thrust_events(series)
    targets = targets_from_events(spy, events)
    out = {"family": "hunt-zweig-breadth-thrust (Zweig Breadth Thrust, 1986) — RUN ON CONSTRUCTED UNIVERSE (program pond A/D, NOT NYSE)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-odd)",
           "universe_substitution": "A/D from the program's 154-name pond cache; the pond is NOT the NYSE; mega-cap bias FLATTERS signal frequency — printed with every number",
           "chassis": "$100; SPY; 0.10%/side + $0.01 sell fee; native = no floor; house = v9 chassis; entry next open after signal close; exit at the open of the first trading day after the 12-month anniversary (CONSTRUCTED exit)",
           "holdings_grid": "NOT-APPLICABLE — SPY event timer, no selection",
           "coins": "NOT-APPLICABLE — the signal is defined on NYSE issue breadth; no honest crypto analogue (spec (e))",
           "ad_series_days": len(series), "thrust_events": events, "roads": {}}
    print("thrust events:", events, flush=True)
    for name, (s, e) in ROADS.items():
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate_targets(spy, targets, s, e, STK_COST, STK_SELL_FEE, chassis=ch)
            rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        rec["benchmark_hold"] = {"name": "SPY buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")}
        nev = sum(1 for d, _ in events if s <= d <= e)
        rec["events_in_road"] = nev
        pf = []
        for seed in range(1, 21):
            rt = random_event_targets(spy, nev, seed)
            pf.append(simulate_targets(spy, rt, s, e, STK_COST, STK_SELL_FEE)["final"])
        rec["placebo_native"] = {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if rec["native"]["final"] > p),
                                 "design": "20-seed random-event placebos, same event count, same 12-month hold (spec (e): MANDATORY)"}
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        out["roads"][name] = rec
        print(f"SPY {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} events {nev} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
