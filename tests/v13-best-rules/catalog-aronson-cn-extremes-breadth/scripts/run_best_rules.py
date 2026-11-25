#!/usr/bin/env python3
"""Aronson CN-extremes breadth — V13 BEST RULES (frozen in BEST-RULES-SPEC.md
before this run).
Series: ADR_t=(adv-dec)/issues from CONSTRUCTED breadth (program PIT price
stack, v7 long-hold pxfull, non-SPY series); CAD = cumsum(ADR).
Signal: CN(91) of CAD, 4-day LMA smoothing (v12 engine definitions).
State: default CASH; smoothed CN <=10 while flat -> buy SPY next open (100%);
smoothed CN >=50 while long -> sell next open. Long only, no floor, $100 pot,
costs 0.10%/side + $0.01 sell fee.
Placebos (20 seeds each): circular shift of the daily position series;
random-window Monte Carlo (same event windows/durations, random starts).
Roads: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03,
all ending 2026-11-20.
BIAS FENCE: constructed breadth is NOT Aronson's NYSE tape — survivor-leaning
~150-name universe, smoother than true NYSE breadth; FLATTERS stability.
"""
import json, os, glob, time, random, statistics

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0; END = "2026-11-20"
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}

def load_bars(path):
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if None in (o, c) or c == 0: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c
        bars.append({"d": d, "o": o * r, "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

spy = load_bars(os.path.join(DATA, "pxfull_SPY.json"))
spy_dates = [b["d"] for b in spy]
spy_by_date = {b["d"]: b for b in spy}
spy_idx = {d: i for i, d in enumerate(spy_dates)}

# --- constructed breadth: ADR per SPY trading day ---
closes = {}
for p in sorted(glob.glob(os.path.join(DATA, "pxfull_*.json"))):
    t = os.path.basename(p)[7:-5]
    if t == "SPY": continue
    closes[t] = {b["d"]: b["c"] for b in load_bars(p)}
tickers = sorted(closes)

adr_by_date = {}
for k, d in enumerate(spy_dates):
    if k == 0: continue
    prev = spy_dates[k - 1]
    adv = dec = unch = 0
    for t in tickers:
        m = closes[t]
        if d in m and prev in m:
            if m[d] > m[prev]: adv += 1
            elif m[d] < m[prev]: dec += 1
            else: unch += 1
    tot = adv + dec + unch
    if tot < 20: continue
    adr_by_date[d] = (adv - dec) / tot

# CAD cumulative + CN(91) + LMA4, over SPY dates in order
cad = {}; run_sum = 0.0; have = False
for d in spy_dates:
    if d in adr_by_date:
        run_sum += adr_by_date[d]; have = True
    if have: cad[d] = run_sum
cad_dates = [d for d in spy_dates if d in cad]
cad_vals = [cad[d] for d in cad_dates]

def cn_series(vals, n=91):
    out = [None] * len(vals)
    for i in range(len(vals)):
        if i < n - 1: continue
        w = vals[i - n + 1:i + 1]
        lo, hi = min(w), max(w)
        out[i] = 100.0 * (vals[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out

def lma4(vals):
    out = [None] * len(vals); w = (1.0, 2.0, 3.0, 4.0)
    for i in range(3, len(vals)):
        seg = vals[i - 3:i + 1]
        if any(v is None for v in seg): continue
        out[i] = sum(a * b for a, b in zip(w, seg)) / 10.0
    return out

cn_s = lma4(cn_series(cad_vals))
cn_by_date = {d: v for d, v in zip(cad_dates, cn_s) if v is not None}

# --- state machine: target weight decided at each close (for next open) ---
target_by_date = {}   # date -> target weight in force AFTER that close
state = 0
for d in spy_dates:
    v = cn_by_date.get(d)
    if v is not None:
        if state == 0 and v <= 10.0: state = 1
        elif state == 1 and v >= 50.0: state = 0
    target_by_date[d] = state

def run_weights(weight_by_exec_date, start, end):
    """weight_by_exec_date: dict exec_date -> target weight applied at that open."""
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    cash, shares, costs, orders = START, 0.0, 0.0, 0
    curve = []
    events = []
    entry_val = None
    for i in idx:
        b = spy[i]
        if b["d"] in weight_by_exec_date:
            tgt = weight_by_exec_date[b["d"]]
            val_open = cash + shares * b["o"]
            tgt_shares = (tgt * val_open) / b["o"] if b["o"] > 0 else 0.0
            diff = tgt_shares - shares
            if abs(diff) > 1e-9:
                if diff > 0:
                    spend = diff * b["o"]; fee = spend * COST
                    if spend + fee > cash:
                        diff = cash / (b["o"] * (1 + COST)); spend = diff * b["o"]; fee = spend * COST
                    cash -= spend + fee; shares += diff; costs += fee
                    entry_val = val_open - fee
                    events.append({"type": "entry", "date": b["d"]})
                else:
                    proceeds = -diff * b["o"]; fee = proceeds * COST + SELL_FEE
                    cash += proceeds - fee; shares += diff; costs += fee
                    if entry_val:
                        events.append({"type": "exit", "date": b["d"],
                                       "event_return_pct": round((cash / entry_val - 1) * 100, 2)})
                        entry_val = None
                orders += 1
        curve.append([b["d"], round(cash + shares * b["c"], 2)])
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": curve[-1][1] if curve else START, "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "events": events, "equity_curve": curve}

def weights_for_road(start, end):
    """Exec-date weights from the frozen state machine: target decided at
    close of day i is executed at open of day i+1. Frozen starting-state
    rule: a road that opens mid-event-window starts FLAT and waits for the
    next fresh entry cross — weights from a window that opened before the
    road are suppressed until that window closes."""
    out = {}
    # suppress until the pre-road window (if any) has closed
    suppress = False
    prev_dates = [d for d in spy_dates if d < start]
    if prev_dates and target_by_date[prev_dates[-1]] == 1:
        suppress = True
    for i, d in enumerate(spy_dates[:-1]):
        nxt = spy_dates[i + 1]
        if not (start <= nxt <= end): continue
        if suppress:
            if target_by_date[d] == 0: suppress = False
            else: continue
        out[nxt] = target_by_date[d]
    return out

def daily_position_series(start, end):
    """Position (0/1) held during each road day (after that day's open)."""
    w = weights_for_road(start, end)
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    pos = []; cur = 0
    for i in idx:
        d = spy[i]["d"]
        if d in w: cur = w[d]
        pos.append(cur)
    return [spy[i]["d"] for i in idx], pos

def weights_from_pos(dates, pos):
    out = {}; prev = 0
    for d, p in zip(dates, pos):
        if p != prev: out[d] = p
        prev = p
    if dates and pos and pos[0] == 1: out[dates[0]] = 1
    return out

def buy_hold(start, end):
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    sh = START / (spy[idx[0]]["o"] * (1 + COST))
    curve = [[spy[i]["d"], round(sh * spy[i]["c"], 2)] for i in idx]
    v = sh * spy[idx[-1]]["c"]; final = v - (v * COST + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for d, vv in curve:
        peak = max(peak, vv); maxdd = max(maxdd, (peak - vv) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

def monthly_dist(curve):
    by = {}
    for d, v in curve: by.setdefault(d[:7], []).append(v)
    months = sorted(by); rets = []; prev = START
    for m in months:
        e = by[m][-1]; rets.append((m, (e / prev - 1) * 100 if prev else 0.0)); prev = e
    vals = [r for _, r in rets]
    if not vals: return {}
    longest_loss = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0; longest_loss = max(longest_loss, cur)
    peak = -1; last_d = None; longest_days = 0
    for d, v in curve:
        if v >= peak: peak = v; last_d = d
        if last_d:
            dd = (time.mktime(time.strptime(d, "%Y-%m-%d")) - time.mktime(time.strptime(last_d, "%Y-%m-%d"))) / 86400
            longest_days = max(longest_days, dd)
    return {"periods": len(vals), "pct_profitable": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1),
            "median_pct": round(statistics.median(vals), 2), "best_pct": round(max(vals), 2),
            "worst_pct": round(min(vals), 2), "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": int(longest_days),
            "average_pct_secondary": round(statistics.mean(vals), 2)}

results = {"family": "catalog-aronson-cn-extremes-breadth", "program": "v13-best-rules",
           "design": "CN(91)+LMA4 of cumulative A/D line (constructed breadth); default CASH; CN<=10 -> long SPY next open; CN>=50 -> exit next open; long only; no floor",
           "breadth_universe": f"CONSTRUCTED from program PIT price stack: {len(tickers)} non-SPY daily series (v7 long-hold pxfull)",
           "bias": "FLATTERS — NOT Aronson's NYSE tape; survivor-leaning universe ~20x smaller than NYSE list; breadth smoother, washouts cleaner. Rule-shape test only.",
           "breadth_coverage": {"first": cad_dates[0], "last": cad_dates[-1], "days": len(cad_dates)},
           "champion_vm": {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05},
           "spy_reference": {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77},
           "published_form_final": None,
           "published_form_note": "v12 STILL UNBUILDABLE — no published-form final exists; none invented.",
           "roads": {}}
for name, start in ROADS.items():
    end = min(END, spy_dates[-1])
    w = weights_for_road(start, end)
    real = run_weights(w, start, end)
    bh = buy_hold(start, end)
    dates_r, pos = daily_position_series(start, end)
    n = len(pos)
    # placebo 1: circular shift of position series
    shift_finals = []
    for s in range(20):
        rng = random.Random(4000 + s)
        sh = rng.randrange(1, n)
        sp = pos[sh:] + pos[:sh]
        shift_finals.append(run_weights(weights_from_pos(dates_r, sp), start, end)["final"])
    # placebo 2: random windows — same event durations, random starts
    runs = []
    i = 0
    while i < n:
        if pos[i] == 1:
            j = i
            while j < n and pos[j] == 1: j += 1
            runs.append(j - i); i = j
        else: i += 1
    win_finals = []
    for s in range(20):
        rng = random.Random(5000 + s)
        placed = [0] * n; ok = True
        for dur in runs:
            for _try in range(200):
                st = rng.randrange(0, n - dur + 1)
                if all(placed[k] == 0 for k in range(st, st + dur)):
                    for k in range(st, st + dur): placed[k] = 1
                    break
            else: ok = False
        if not ok: win_finals.append(None); continue
        win_finals.append(run_weights(weights_from_pos(dates_r, placed), start, end)["final"])
    wf = [x for x in win_finals if x is not None]
    entries = [e for e in real["events"] if e["type"] == "entry"]
    exits = [e for e in real["events"] if e["type"] == "exit"]
    results["roads"][name] = {
        "window": [start, end], "best_rules": {k: real[k] for k in ("final", "max_dd_pct", "costs", "orders")},
        "equity_curve": real["equity_curve"], "spy_buy_hold": bh,
        "event_count_entries": len(entries), "event_count_exits": len(exits),
        "events": real["events"], "days_invested": sum(pos), "days_total": n,
        "placebo_shift_finals": [round(x, 2) for x in shift_finals],
        "placebo_shift_beaten": f"{sum(1 for x in shift_finals if real['final'] > x)}/20",
        "placebo_shift_median": round(statistics.median(shift_finals), 2),
        "placebo_window_finals": [round(x, 2) if x is not None else None for x in win_finals],
        "placebo_window_beaten": f"{sum(1 for x in wf if real['final'] > x)}/{len(wf)}",
        "placebo_window_median": round(statistics.median(wf), 2) if wf else None,
        "monthly_distribution": monthly_dist(real["equity_curve"])}
    print(name, "final", real["final"], "dd", real["max_dd_pct"], "entries", len(entries),
          "exits", len(exits), "days_in", sum(pos), "/", n, "costs", real["costs"],
          "SPY", bh["final"], "shift", results["roads"][name]["placebo_shift_beaten"],
          "window", results["roads"][name]["placebo_window_beaten"], flush=True)
json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
