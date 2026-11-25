#!/usr/bin/env python3
"""hunt-zweig-breadth-thrust — v13 BEST RULES (spec frozen in
BEST-RULES-SPEC.md before this run). Trigger PUBLISHED exactly (Zweig
1986): 10-day EMA (alpha 2/11) of advancing/(advancing+declining);
thrust = rise from below 0.40 to above 0.615 within any 10-trading-day
window. MY RULE (the design): the pot is invested in SPY iff a thrust
occurred within the trailing 12 months (a fresh thrust renews the
window); otherwise cash. 100% all-in/all-out, NO floor, program costs.
UNIVERSE SUBSTITUTION (as v12, labelled): A/D from the program's
154-name pond cache, NOT the NYSE — bias FLATTERS signal frequency."""
import json, os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_core.py")).read())
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
ROADS13 = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

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
            below_start = i if ema < 0.40 else below_start
    return events

def build_states(spy, events):
    """state[t]=1 iff the most recent thrust is within the trailing
    365 calendar days at bar t's close (decided at close, executed at
    next open by the chassis)."""
    ev_ord = sorted(_date.fromisoformat(d).toordinal() for d, _ in events)
    states = []
    j = -1
    for b in spy:
        o = _date.fromisoformat(b["d"]).toordinal()
        while j + 1 < len(ev_ord) and ev_ord[j + 1] <= o:
            j += 1
        states.append(1 if (j >= 0 and o - ev_ord[j] <= 365) else 0)
    return states

def main():
    spy = load_stock("SPY")
    spy_dates = [b["d"] for b in spy]
    series = pond_ad_series(spy_dates)
    events = thrust_events(series)
    states = build_states(spy, events)
    out = {"family": "hunt-zweig-breadth-thrust (Zweig Breadth Thrust, 1986) — v13 BEST RULES — RUN ON CONSTRUCTED UNIVERSE (program pond A/D, NOT NYSE)",
           "spec": "BEST-RULES-SPEC.md (frozen before run): invested iff a thrust occurred within the trailing 12 months (fresh thrust renews); else cash; SPY; 100% sizing; NO floor; 0.10%/side + $0.01 sell fee; $100 pots",
           "universe_substitution": "A/D from the program's 154-name pond cache; the pond is NOT the NYSE; mega-cap bias FLATTERS signal frequency — printed with every number",
           "ad_series_days": len(series), "thrust_events": events, "roads": {}}
    print("thrust events:", events, flush=True)
    beats = []
    for name, (s, e) in ROADS13.items():
        r = simulate_states(spy, states, s, e, STK_COST, STK_SELL_FEE, chassis=False)
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        nev = sum(1 for d, _ in events if s <= d <= e)
        # state carried into the road (thrust in the 12mo before road start)
        carried = any(s > d and (_date.fromisoformat(s) - _date.fromisoformat(d)).days <= 365
                      for d, _ in events)
        pf = placebo_states(spy, states, s, e, STK_COST, STK_SELL_FEE, n=20)
        beaten = sum(1 for p in pf if r["final"] > p)
        rec = {"my_rules": {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")},
               "benchmark_hold": {"name": "SPY buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")},
               "events_in_road": nev, "carried_in_invested": bool(carried),
               "placebo_shift": {"seed_finals": pf, "beaten_of_20": beaten,
                                 "design": "20-seed circular-shift placebos of the road state series (matched invested fraction and hold structure; only thrust-date alignment destroyed)"},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name]}
        out["roads"][name] = rec
        if r["final"] > CHAMP[name]: beats.append(name)
        print(f"SPY {name}: mine ${r['final']} (DD {r['max_dd_pct']}%, invested {r['invested_pct']}%) "
              f"hold ${bh['final']} champ ${CHAMP[name]} events {nev} carried {carried} placebos {beaten}/20", flush=True)
    out["roads_beating_champion"] = beats
    if beats:
        # CONFIRMATION (frozen in spec): yearly folds (median fold vs same-year
        # SPY buy-hold) + half-windows (both halves vs SPY buy-hold).
        conf = {}
        for name in beats:
            s, e = ROADS13[name]
            years = sorted({d[:4] for d in spy_dates if s <= d <= e})
            folds = []
            for y in years:
                fs, fe = max(s, f"{y}-01-01"), min(e, f"{y}-12-31")
                fr = simulate_states(spy, states, fs, fe, STK_COST, STK_SELL_FEE)
                fb = buy_hold(spy, fs, fe, STK_COST, STK_SELL_FEE)
                if fr and fb: folds.append({"year": y, "mine": fr["final"], "spy": fb["final"], "beats_spy": fr["final"] > fb["final"]})
            idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
            mid = spy[idx[len(idx)//2]]["d"]
            halves = []
            for hs, he in ((s, mid), (mid, e)):
                hr = simulate_states(spy, states, hs, he, STK_COST, STK_SELL_FEE)
                hb = buy_hold(spy, hs, he, STK_COST, STK_SELL_FEE)
                halves.append({"window": [hs, he], "mine": hr["final"], "spy": hb["final"], "beats_spy": hr["final"] > hb["final"]})
            med = sorted(f["mine"] - f["spy"] for f in folds)
            conf[name] = {"yearly_folds": folds,
                          "median_fold_margin_vs_spy": med[len(med)//2] if med else None,
                          "folds_beating_spy": sum(1 for f in folds if f["beats_spy"]),
                          "half_windows": halves,
                          "confirmed": bool(folds) and (med[len(med)//2] > 0) and all(h["beats_spy"] for h in halves)}
        out["confirmation"] = conf
        print("CONFIRMATION:", json.dumps(conf), flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
