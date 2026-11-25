#!/usr/bin/env python3
"""
KAGI — v13 BEST RULES. SIMULATION ONLY.
Implements BEST-RULES-SPEC.md exactly (frozen before this run):
  Vehicle SPY only. Kagi on daily closes with volatility-scaled reversal:
  R_leg = clamp(2.0 * ATR%(14), 2%, 8%), ATR% = Wilder ATR(14)/close,
  computed point-in-time, frozen for the life of each leg (no repainting).
  Entry/exit on DIRECTION change (thickness layer removed). Trades execute
  at the NEXT OPEN after the signal close. No floor, no ladder.
Costs: 0.10%/side + $0.01 sell fee. $100 pots.
Roads: LONG 2010-01-04->2026-11-20, DECADE 2016-11-21->2026-11-20,
       CONT 2019-01-02->2026-11-20, VAL 2023-01-03->2026-11-20.
Placebos: 20-seed circular shifts of the in-road direction-state series.
Data READ-ONLY: v7 pxfull_SPY cache.
"""
import json, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED_BEST = {  # v12 native SPY finals (published form, both R settings; best per road)
    "LONG": {"final": 587.88, "maxdd_pct": -23.3, "form": "R=3% yang/yin, same-close"},
    "DECADE": {"final": 356.25, "maxdd_pct": -22.7, "form": "R=3% yang/yin, same-close"},
    "CONT": {"final": 322.46, "maxdd_pct": -22.7, "form": "R=3% yang/yin, same-close"},
    "VAL": {"final": 197.77, "maxdd_pct": -8.4, "form": "R=3% yang/yin, same-close"}}

# ------------------------------------------------------------------- data ----
def load_bars():
    j = json.loads(open(PX, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c): continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o * r, "h": h * r, "l": l * r, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------- ATR + Kagi (PIT) ----
def atr_pct_series(bars, period=14):
    """Wilder ATR as fraction of close; None until seeded."""
    n = len(bars); out = [None] * n
    trs = [None] * n
    for i in range(1, n):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = None
    for i in range(1, n):
        if i == period:
            atr = statistics.mean(trs[1:period + 1])
        elif i > period:
            atr = (atr * (period - 1) + trs[i]) / period
        if atr is not None:
            out[i] = atr / bars[i]["c"] if bars[i]["c"] else None
    return out

def band(x):
    return min(0.08, max(0.02, x))

def kagi_direction(bars, atrp):
    """long_state[i] = True if Kagi direction is UP after close i.
    R_leg set on the day a leg begins (from that day's ATR%), frozen per leg."""
    n = len(bars)
    state = [False] * n
    direction = 0; tip = None; ref = None; R_leg = None
    for i, b in enumerate(bars):
        c = b["c"]; a = atrp[i]
        if a is None:
            continue
        if direction == 0:
            if ref is None:
                ref = c; R_leg = band(2.0 * a); tip = c
            elif c >= ref * (1 + R_leg):
                direction = 1; tip = c; R_leg = band(2.0 * a)
            elif c <= ref * (1 - R_leg):
                direction = -1; tip = c; R_leg = band(2.0 * a)
        elif direction == 1:
            if c > tip:
                tip = c
            elif c <= tip * (1 - R_leg):
                direction = -1; tip = c; R_leg = band(2.0 * a)
        else:
            if c < tip:
                tip = c
            elif c >= tip * (1 + R_leg):
                direction = 1; tip = c; R_leg = band(2.0 * a)
        state[i] = (direction == 1)
    return state

# ---------------------------------------------------------------- engine ----
def run_engine(bars, state, prev_state):
    """Next-open execution: at bar i's open, act on state after close i-1
    (prev_state seeds the first bar from the day before the window)."""
    cash, units = START, 0.0
    trades = 0; costs = 0.0; held = 0
    curve = []; dates = []
    want_prev = prev_state
    for i, b in enumerate(bars):
        if want_prev and units == 0 and cash > 0:
            units = cash * (1 - COST) / b["o"]; costs += cash * COST; cash = 0.0; trades += 1
        elif not want_prev and units > 0:
            v = units * b["o"]; fee = v * COST + SELL_FEE; costs += fee
            cash = v - fee; units = 0.0; trades += 1
        eq = cash + units * b["c"]
        if units > 0: held += 1
        curve.append(round(eq, 4)); dates.append(b["d"])
        want_prev = state[i]
    final = cash + units * bars[-1]["c"] if bars else START
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "maxdd_pct": round(maxdd * 100, 1),
            "trades": trades, "costs": round(costs, 2),
            "exposure_pct": round(100.0 * held / max(len(bars), 1), 1),
            "curve": curve, "dates": dates}

def buy_hold(bars):
    units = START * (1 - COST) / bars[0]["o"]
    curve = [round(units * b["c"], 4) for b in bars]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(units * bars[-1]["c"], 2), "maxdd_pct": round(maxdd * 100, 1), "curve": curve}

def period_stats(curve, dates):
    pts = {}
    for d, v in zip(dates, curve):
        pts[d[:7]] = v
    keys = sorted(pts); rets = []; ends = []; prev = START
    for k in keys:
        v = pts[k]; rets.append(v / prev - 1.0 if prev > 0 else 0.0); ends.append(v); prev = v
    if not rets: return None
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; longest_loss = max(longest_loss, cur)
    peak = START; since = 0; longest_between = 0
    for e in ends:
        if e > peak: peak = e; since = 0
        else: since += 1; longest_between = max(longest_between, since)
    return {"periods": len(rets),
            "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 1), "worst_pct": round(min(rets) * 100, 1),
            "longest_losing_run": longest_loss,
            "longest_between_new_highs": longest_between,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def placebos(bars, state, seed_base=20261122):
    finals = []; n = len(bars)
    rng = random.Random(seed_base)
    for _ in range(20):
        shift = rng.randrange(1, n)
        shifted = state[shift:] + state[:shift]
        finals.append(run_engine(bars, shifted, shifted[-1])["final"])
    return finals

def slice_idx(bars, start, end):
    return [i for i, b in enumerate(bars) if start <= b["d"] <= end]

def run_window(bars, state, idx):
    wb = [bars[i] for i in idx]; ws = [state[i] for i in idx]
    prev = state[idx[0] - 1] if idx[0] > 0 else False
    return run_engine(wb, ws, prev), wb, ws

def main():
    bars = load_bars()
    atrp = atr_pct_series(bars)
    state = kagi_direction(bars, atrp)
    out = {"family": "hunt-kagi", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "rules": "SPY only; Kagi direction-change entries; R_leg = clamp(2.0*ATR%(14), 2%, 8%) frozen per leg; next-open execution; no floor",
           "costs": "0.10%/side + $0.01 sell fee", "roads": {}}
    for road, (s, e) in ROADS.items():
        idx = slice_idx(bars, s, e)
        res, wb, ws = run_window(bars, state, idx)
        hold = buy_hold(wb)
        tw = placebos(wb, ws)
        cell = {"window": [wb[0]["d"], wb[-1]["d"]], "bars": len(wb),
                "best_rules": {k: res[k] for k in ("final", "maxdd_pct", "trades", "costs", "exposure_pct")},
                "spy_buy_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]},
                "spy_reference_given": SPY_REF[road],
                "published_form_best_v12": PUBLISHED_BEST[road],
                "champion_vm": CHAMPION[road],
                "placebo_median": round(statistics.median(tw), 2),
                "placebo_beats": f"{sum(1 for v in tw if res['final'] > v)}/20",
                "period_stats_monthly": period_stats(res["curve"], res["dates"]),
                "equity_curve": res["curve"], "curve_dates": res["dates"],
                "hold_curve": hold["curve"]}
        if res["final"] > CHAMPION[road]:
            # confirmation: yearly folds + half-windows, state carried in (PIT)
            years = {}
            for y in sorted({b["d"][:4] for b in wb}):
                yi = slice_idx(bars, f"{y}-01-01", f"{y}-12-31")
                yi = [i for i in yi if idx[0] <= i <= idx[-1]]
                if len(yi) >= 30:
                    r_y, _, _ = run_window(bars, state, yi)
                    years[y] = {"final": r_y["final"], "maxdd_pct": r_y["maxdd_pct"]}
            mid = len(idx) // 2
            h1, _, _ = run_window(bars, state, idx[:mid])
            h2, _, _ = run_window(bars, state, idx[mid:])
            cell["confirmation"] = {"yearly_folds": years,
                "years_profitable": f"{sum(1 for v in years.values() if v['final'] > 100)}/{len(years)}",
                "median_year_final": round(statistics.median([v['final'] for v in years.values()]), 2) if years else None,
                "half1": {"final": h1["final"], "maxdd_pct": h1["maxdd_pct"]},
                "half2": {"final": h2["final"], "maxdd_pct": h2["maxdd_pct"]}}
        out["roads"][road] = cell
        print(road, cell["best_rules"], "hold", hold["final"], "placebo", cell["placebo_beats"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
