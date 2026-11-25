#!/usr/bin/env python3
"""V13 Best Rules — Three-Line Break, trend-state weekly form.
Implements BEST-RULES-SPEC.md exactly:
- TLB lines (3-line reversal geometry, v12 mechanisation) on WEEKLY closes.
- State = colour of most recent completed line: white=long, black=flat.
  No >=3-run trading gate. Line count stays three.
- Execution at NEXT trading day's OPEN after the signal week's close.
- SPY only, $100 pot, costs 0.10%/side + $0.01 sell fee, cash 0%, NO floor.
- Warm-up: causal line state from all pre-road data.
- Placebos: 20-seed circular shifts of weekly desired state within road.
Simulation only. Shared inputs read-only; writes only in this folder.
"""
import json, os, time, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
COST = 0.001; FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 217.20, "DECADE": 138.72, "CONT": 157.71, "VAL": 118.44}

def load_stock(sym):
    j = json.load(open(os.path.join(PXDIR, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    dates, opens, closes = [], [], []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
        opens.append(q["open"][i] * ratio); closes.append(adj[i])
    return dates, opens, closes

def weekly_bars(dates, closes):
    """Return list of (last_daily_idx, week_close) per ISO week."""
    bars = []
    for i, d in enumerate(dates):
        iso = date.fromisoformat(d).isocalendar()[:2]
        if bars and bars[-1][2] == iso:
            bars[-1] = (i, closes[i], iso)
        else:
            bars.append((i, closes[i], iso))
    return [(i, c) for i, c, _ in bars]

def tlb_state(closes):
    """TLB on a close series; return state[t] = 1 if last line white else 0,
    plus line count. Same geometry as v12 run_tlb.tlb_desired, but the
    trading state is the line colour itself (no >=3-run gate)."""
    n = len(closes); state = [0] * n
    if n < 2: return state, 0
    lines = []; base = closes[0]; cur = 0
    run_dir = 0; run_len = 0
    for t in range(1, n):
        c = closes[t]
        if not lines:
            if c > base: lines.append([1, base, c]); run_dir, run_len = 1, 1; cur = 1
            elif c < base: lines.append([-1, base, c]); run_dir, run_len = -1, 1; cur = 0
            state[t] = cur; continue
        last = lines[-1]
        top = max(last[1], last[2]); bot = min(last[1], last[2])
        new_line = 0
        if last[0] == 1:
            if c > top: new_line = 1
            elif c < min(min(l[1], l[2]) for l in lines[-run_len:][-3:]): new_line = -1
        else:
            if c < bot: new_line = -1
            elif c > max(max(l[1], l[2]) for l in lines[-run_len:][-3:]): new_line = 1
        if new_line:
            if new_line == run_dir: run_len += 1
            else: run_dir = new_line; run_len = 1
            lines.append([new_line, last[2], c])
            cur = 1 if new_line == 1 else 0
        state[t] = cur
    return state, len(lines)

def simulate(dates, opens, closes, wbars, wstate, i0, i1, state_override=None):
    """state_override: dict weekly_bar_idx -> desired state (placebos).
    Executions: at open of first daily bar after the signal week's last bar;
    at road start, prevailing state (last weekly signal executable by i0)
    is taken at i0's open."""
    # build execution schedule: exec_daily_idx -> desired
    sched = {}
    prevailing = 0
    for w, (di, _c) in enumerate(wbars):
        st = wstate[w] if state_override is None else state_override.get(w, wstate[w])
        ex = di + 1
        if ex <= i0: prevailing = st
        elif ex <= i1: sched[ex] = st
    cash = START; shares = 0.0; costs = 0.0; orders = 0; trades = []
    curve = []
    def buy(t, px):
        nonlocal cash, shares, costs, orders
        bv = cash / (1 + COST); cf = bv * COST
        shares = bv / px; cash -= bv + cf; costs += cf; orders += 1
        trades.append([dates[t], "BUY", round(px, 4), round(bv, 2)])
    def sell(t, px, tag="SELL"):
        nonlocal cash, shares, costs, orders
        val = shares * px; cf = val * COST + FEE
        cash += val - cf; costs += cf; orders += 1; shares = 0.0
        trades.append([dates[t], tag, round(px, 4), round(val, 2)])
    if prevailing == 1: buy(i0, opens[i0])
    invested_days = 0
    for t in range(i0, i1 + 1):
        if t in sched and t != i0:
            want = sched[t]
            if want == 1 and shares == 0.0 and cash > 0: buy(t, opens[t])
            elif want == 0 and shares > 0: sell(t, opens[t])
        if shares > 0: invested_days += 1
        curve.append([dates[t], round(cash + shares * closes[t], 4)])
    if shares > 0:
        sell(i1, closes[i1], "SELL-END")
        curve[-1] = [dates[i1], round(cash, 4)]
    peak = START; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders,
            "invested_pct": round(100.0 * invested_days / (i1 - i0 + 1), 1),
            "trades": trades, "equity_curve": curve}

def buyhold(closes, i0, i1):
    sh = (START / (1 + COST)) / closes[i0]
    val = sh * closes[i1]
    return round(val - (val * COST + FEE), 2)

def period_stats(curve):
    months = {}; order = []
    for d, v in curve:
        m = d[:7]
        if m not in months: order.append(m)
        months[m] = v
    vals = [months[m] for m in order]
    rets = []; prev = START
    for v in vals: rets.append(v / prev - 1.0); prev = v
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0; longest_loss = max(longest_loss, run)
    peak = -1.0; since = 0; gap = 0
    for v in vals:
        if v > peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_pct": round(100.0 * statistics.median(rets), 2),
            "best_pct": round(100.0 * max(rets), 2), "worst_pct": round(100.0 * min(rets), 2),
            "longest_losing_run": longest_loss, "longest_between_highs_periods": gap,
            "average_pct_secondary": round(100.0 * statistics.mean(rets), 2)}

def idx_range(dates, s, e):
    idx = [i for i, d in enumerate(dates) if s <= d <= e]
    return (idx[0], idx[-1]) if idx else (None, None)

def main():
    dates, opens, closes = load_stock("SPY")
    wbars = weekly_bars(dates, closes)
    wcloses = [c for _, c in wbars]
    wstate, nlines = tlb_state(wcloses)
    out = {"family": "hunt-three-line-break", "program": "v13-best-rules",
           "form": "TLB 3-line geometry on weekly closes; trend-state (last line colour); next-open execution; no floor",
           "costs": "0.10%/side + $0.01 sell fee", "champions": CHAMP,
           "spy_reference": SPYREF, "published_v12_spy_native": PUBLISHED,
           "n_weekly_bars": len(wbars), "n_weekly_lines": nlines, "roads": {}}
    log = [f"weekly bars={len(wbars)} weekly lines={nlines}"]
    for road, (s, e) in ROADS.items():
        i0, i1 = idx_range(dates, s, e)
        r = simulate(dates, opens, closes, wbars, wstate, i0, i1)
        # weekly bars whose execution falls in (i0, i1] plus prevailing bar
        win_w = [w for w, (di, _) in enumerate(wbars) if i0 < di + 1 <= i1]
        pls = []
        for sd in range(20):
            seg = [wstate[w] for w in win_w]
            L = len(seg)
            rng = random.Random(4200 + sd)
            k = rng.randrange(1, L) if L > 1 else 0
            rot = seg[k:] + seg[:k]
            ov = {w: rot[j] for j, w in enumerate(win_w)}
            pls.append(simulate(dates, opens, closes, wbars, wstate, i0, i1, ov)["final"])
        ent = {**{k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "invested_pct")},
               "placebo_finals": pls,
               "placebos_beaten": sum(1 for x in pls if r["final"] > x),
               "placebo_median": round(statistics.median(pls), 2),
               "period_stats_monthly": period_stats(r["equity_curve"]),
               "buyhold_own_plumbing": buyhold(closes, i0, i1),
               "spy_reference_program": SPYREF[road], "champion_vm": CHAMP[road],
               "published_v12_native": PUBLISHED[road],
               "equity_curve": r["equity_curve"], "trades": r["trades"]}
        out["roads"][road] = ent
        log.append(f"{road}: final={r['final']} dd={r['max_dd_pct']} orders={r['orders']} "
                   f"inv={r['invested_pct']}% placebos_beaten={ent['placebos_beaten']}/20")
    # ---- confirmation machinery (runs regardless; claim gated in RESULTS) ----
    conf = {}
    for road, (s, e) in ROADS.items():
        folds = {}
        y0, y1 = int(s[:4]), int(e[:4])
        for y in range(y0, y1 + 1):
            a, b = idx_range(dates, max(s, f"{y}-01-01"), min(e, f"{y}-12-31"))
            if a is None: continue
            folds[str(y)] = {"system": simulate(dates, opens, closes, wbars, wstate, a, b)["final"],
                             "buyhold": buyhold(closes, a, b)}
        i0, i1 = idx_range(dates, s, e)
        mid = (i0 + i1) // 2
        halves = {"H1": {"system": simulate(dates, opens, closes, wbars, wstate, i0, mid)["final"],
                         "buyhold": buyhold(closes, i0, mid)},
                  "H2": {"system": simulate(dates, opens, closes, wbars, wstate, mid + 1, i1)["final"],
                         "buyhold": buyhold(closes, mid + 1, i1)}}
        conf[road] = {"year_folds": folds, "halves": halves}
        log.append(f"{road} confirmation computed: folds={len(folds)}")
    out["confirmation"] = conf
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f)
    with open(os.path.join(HERE, "run.log"), "w") as f: f.write("\n".join(log) + "\n")
    print("\n".join(log))

if __name__ == "__main__":
    main()
