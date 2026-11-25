"""Spinoffs v13 BEST-RULES run. Frozen spec: BEST-RULES-SPEC.md.
Ride the forced-selling mechanic: enter close 21 trading days after first regular-way day,
exit 252 trading days after entry, 20 slots, no floor/stop, costs 0.25%/side (2% if <$5).
Shared inputs (v11 census, v11 yh caches, v3 bars, v11 native_lib) are READ-ONLY."""
import sys, os, json, random, re
import pandas as pd, numpy as np

V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/spinoffs")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, V11)
from native_lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate, CACHE, _parse_yahoo

DELAY = 21      # trading days after first regular-way day
HOLD = 252      # trading days
SLOTS = 20
BASE_COST = 0.0025

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20", 1415.62, 822.94),
    "DECADE": ("2016-11-21", "2026-11-20", 667.35, 367.80),
    "CONT":   ("2019-01-02", "2026-11-20", 544.47, 313.62),
    "VAL":    ("2023-01-03", "2026-11-20", 288.05, 187.77),
}

def load_child(ticker):
    """v3 bars first (via native_lib), else v11's yh_<ticker>.json cache parsed read-only."""
    if ticker in CACHE and CACHE[ticker] is not None:
        return CACHE[ticker]
    df = get_bars(ticker, HERE)  # checks v3, else fetches into THIS folder only
    if df is None or len(df) == 0:
        p = os.path.join(V11, f"yh_{ticker.replace('/', '-')}.json")
        if os.path.exists(p):
            try: df = _parse_yahoo(json.load(open(p)))
            except Exception: df = None
        CACHE[ticker] = df
    return df

def build_events(spy):
    cen = json.load(open(os.path.join(V11, "census.json")))
    cal = list(spy.index); cal_pos = {d: i for i, d in enumerate(cal)}
    events, dropped = [], {"no_bars": 0, "no_entry": 0, "too_late": 0}
    for c in cen:
        dist = pd.Timestamp(c["distribution"])
        if dist < pd.Timestamp("2020-01-01") or dist > pd.Timestamp("2026-11-20"):
            continue
        df = load_child(c["ticker"])
        if df is None or len(df) == 0:
            dropped["no_bars"] += 1; continue
        idx = df.index[df.index >= dist]
        if len(idx) == 0:
            dropped["no_entry"] += 1; continue
        first_pos = df.index.get_loc(idx[0])
        if isinstance(first_pos, slice): first_pos = first_pos.start
        entry_pos = first_pos + DELAY
        if entry_pos >= len(df):
            dropped["too_late"] += 1; continue
        ed = df.index[entry_pos]
        if ed not in cal_pos:  # align to SPY calendar (next session)
            nxt = [d for d in cal if d >= ed]
            if not nxt:
                dropped["no_entry"] += 1; continue
            ed = nxt[0]
        exit_pos = entry_pos + HOLD
        complete = exit_pos < len(df)
        xd = df.index[exit_pos] if complete else df.index[-1]
        events.append({
            "ticker": c["ticker"], "distribution": c["distribution"],
            "entry_date": ed, "entry_price": float(df["close"].iloc[entry_pos]),
            "exit_date": xd, "exit_price": float(df["close"].asof(xd)),
            "df": df, "complete12": bool(complete),
            "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy["close"].asof(xd)),
        })
    events.sort(key=lambda e: e["entry_date"])
    return events, dropped, len(cen)

def period_distribution(curve):
    """curve: [(date_str, equity)] daily. Periods = calendar years."""
    s = pd.Series({pd.Timestamp(d): v for d, v in curve}).sort_index()
    yrs = {}
    for y, g in s.groupby(s.index.year):
        prev = s[s.index < g.index[0]]
        base = float(prev.iloc[-1]) if len(prev) else 100.0
        yrs[int(y)] = float(g.iloc[-1]) / base - 1.0
    rets = list(yrs.values())
    # longest losing streak (consecutive negative years)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days)
    peak = -np.inf; peak_i = 0; longest = 0
    vals = s.values
    for i, v in enumerate(vals):
        if v >= peak: peak, peak_i = v, i
        longest = max(longest, i - peak_i)
    return {
        "periods_yearly_returns_pct": {str(k): round(v * 100, 2) for k, v in yrs.items()},
        "median_period_pct": round(float(np.median(rets)) * 100, 2) if rets else None,
        "share_positive_pct": round(float(np.mean([r > 0 for r in rets])) * 100, 1) if rets else None,
        "best_period_pct": round(max(rets) * 100, 2) if rets else None,
        "worst_period_pct": round(min(rets) * 100, 2) if rets else None,
        "longest_losing_streak_periods": streak,
        "longest_days_between_new_highs": int(longest),
    }

def main():
    log = []
    spy = spy_calendar(HERE)
    events, dropped, census_rows = build_events(spy)
    log.append(f"census rows={census_rows} tradable events={len(events)} dropped={dropped}")

    # Event study (my delayed-entry 12m window), excess vs SPY net of costs
    ex = []
    for e in events:
        r_child = e["exit_price"] * (1 - cost_rate(e["exit_price"], BASE_COST)) / (e["entry_price"] * (1 + cost_rate(e["entry_price"], BASE_COST))) - 1
        r_spy = e["spy_exit"] / e["spy_entry"] - 1
        ex.append(r_child - r_spy)
    ex = np.array(ex)
    comp = np.array([e["complete12"] for e in events])
    ev_study = {
        "n": len(ex),
        "mean_excess_pct": round(float(ex.mean()) * 100, 2),
        "median_excess_pct": round(float(np.median(ex)) * 100, 2),
        "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1),
        "complete_only": {
            "n": int(comp.sum()),
            "mean_excess_pct": round(float(ex[comp].mean()) * 100, 2) if comp.any() else None,
            "median_excess_pct": round(float(np.median(ex[comp])) * 100, 2) if comp.any() else None,
            "pct_beat_spy": round(float((ex[comp] > 0).mean()) * 100, 1) if comp.any() else None,
        },
    }
    log.append(f"event study: {ev_study}")

    # 20-seed random-ticker placebos on the same delayed-entry 12m windows
    pool = [p[:-5] for p in os.listdir(os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars"))
            if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    base_mean = ev_study["mean_excess_pct"]; beaten = 0; twins = []
    for seed in range(20):
        r = random.Random(5000 + seed); tex = []
        for e in events:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t, HERE)
                if df is None or len(df) == 0: continue
                ep = df["close"].asof(e["entry_date"]); xp = df["close"].asof(e["exit_date"])
                if ep and xp and ep == ep and xp == xp:
                    tex.append((xp / ep - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = round(float(np.mean(tex)) * 100, 3) if tex else None
        twins.append(m)
        if m is not None and base_mean > m: beaten += 1
    placebo = {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twins, "base_mean_excess_pct": base_mean}
    log.append(f"placebo: beaten {beaten}/20")

    roads_out = {}
    for name, (s0, s1, champ, spyref) in ROADS.items():
        start, end = pd.Timestamp(s0), pd.Timestamp(s1)
        ev_road = [e for e in events if start <= e["entry_date"] <= end]
        pot = run_event_pot(ev_road, spy, start, end, slots=SLOTS, base_cost=BASE_COST)
        curve = pot["curve"]
        # prepend flat-cash segment if road starts before SPY tape (2018-06) — no events exist pre-2020
        if curve and pd.Timestamp(curve[0][0]) > start:
            pre = pd.bdate_range(start, pd.Timestamp(curve[0][0]) - pd.Timedelta(days=1))
            curve = [(str(d.date()), 100.0) for d in pre] + curve
        dist = period_distribution(curve)
        roads_out[name] = {
            "window": [s0, s1], "final": pot["final"], "max_dd_pct": pot["max_dd_pct"],
            "costs": pot["costs"], "orders": pot["orders"], "taken": pot["taken"], "skipped": pot["skipped"],
            "events_available": len(ev_road),
            "champion_vm": champ, "spy_reference": spyref,
            "beats_champion": bool(pot["final"] > champ), "beats_spy": bool(pot["final"] > spyref),
            "distribution": dist, "curve": curve,
        }
        log.append(f"{name}: final={pot['final']} maxDD={pot['max_dd_pct']}% taken={pot['taken']} skipped={pot['skipped']} costs={pot['costs']}")

    out = {
        "family": "spinoffs", "program": "v13-best-rules", "verdict_ceiling": "CANDIDATE",
        "spec": {"delay_trading_days": DELAY, "hold_trading_days": HOLD, "slots": SLOTS,
                 "base_cost_per_side": BASE_COST, "penny_cost_per_side": 0.02, "floor": None},
        "census_rows": census_rows, "events_tradable": len(events), "dropped": dropped,
        "event_study_delayed12mo": ev_study, "placebo_random_ticker": placebo,
        "roads": roads_out,
        "published_native_best": {"form": "CMW day-1 entry, 36mo hold, 10 slots, 2020-01-01..2026-11-20",
                                  "pot_final": 127.82, "pot_max_dd_pct": 46.47, "spy_same_road": 233.52},
        "events": [{"ticker": e["ticker"], "distribution": e["distribution"],
                    "entry": str(e["entry_date"].date()), "exit": str(e["exit_date"].date()),
                    "complete12": e["complete12"]} for e in events],
    }
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    open(os.path.join(HERE, "run.log"), "w").write("\n".join(log) + "\n")
    print("\n".join(log))

if __name__ == "__main__":
    main()
