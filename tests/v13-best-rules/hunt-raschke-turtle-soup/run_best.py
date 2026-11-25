#!/usr/bin/env python3
"""v13 BEST RULES — Turtle Soup. Frozen spec: BEST-RULES-SPEC.md.
4-ETF basket (SPY/QQQ/DIA/IWM), one 25%-of-equity slot per ETF.
Signal (published): new 20-day low, previous 20-day low >=4 sessions ago.
Entry: same-day close if close reclaimed prior low; else buy-stop next
session only at prior low x1.001. Stop: signal-day low x0.999 intraday.
Exit: close of 10th session after entry (entry session = 1). No re-entry,
no trail, no target, no pot floor. Costs 0.10%/side + $0.01/sell.
Placebos: 20 seeds, anchors shifted +-30..250 bars, prior low recomputed.
Simulation only."""
import json, os, sys, random, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.001; FEE = 0.01; HOLD = 10

def load(sym):
    if sym == "SPY":
        p = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    else:
        p = os.path.expanduser(f"~/workspace/stock-app/backtests/v13-best-rules/hunt-connors-cumulative-rsi/data/pxfull_{sym}.json")
    import time
    j = json.load(open(p)); r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]; bars = []
    for i, t in enumerate(ts):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]): continue
        k = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": q["open"][i]*k, "h": q["high"][i]*k, "l": q["low"][i]*k, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

SYMS = ["SPY", "QQQ", "DIA", "IWM"]
DATA = {s: load(s) for s in SYMS}
DATES = DATA["SPY"]  # all four share the same session calendar (verified in log)
IDX = {s: {b["d"]: i for i, b in enumerate(DATA[s])} for s in SYMS}

def find_signals(bars):
    sig = []; last_bar = None; last_val = None
    for t in range(19, len(bars)):
        w = min(b["l"] for b in bars[t-19:t+1])
        if bars[t]["l"] <= w:
            if last_bar is not None and t - last_bar >= 4:
                sig.append((t, last_val))
            last_bar = t; last_val = bars[t]["l"]
    return sig

def build_trade(bars, t, old_low):
    """Returns dict entry_i, entry_px, stop_px, exit_i, exit_px, reason or None."""
    n = len(bars); stop = bars[t]["l"] * 0.999
    if bars[t]["c"] > old_low:  # same-day reclaim at the close
        e, entry = t, bars[t]["c"]
    else:
        e = t + 1
        if e >= n: return None
        entry = old_low * 1.001
        if bars[e]["h"] < entry: return None
    # stop / time exit; stop checked intraday from the bar AFTER a close entry,
    # and on the entry bar itself for a stop entry (conservative, per spec)
    xi, xp, reason = min(e + HOLD - 1, n - 1), None, "time"
    start = e if e > t else e + 1
    for k in range(start, min(e + HOLD - 1, n - 1) + 1):
        if bars[k]["l"] <= stop:
            xi, xp, reason = k, stop, "stop"; break
    if xp is None: xp = bars[xi]["c"]
    return dict(entry_i=e, entry_px=entry, stop_px=stop, exit_i=xi, exit_px=xp, reason=reason)

def gen_trades(bars):
    return [tr for tr in (build_trade(bars, t, ol) for t, ol in find_signals(bars)) if tr]

def run_portfolio(trades_by_sym, a, b):
    """trades_by_sym: {sym: [trade,...]} with global (SPY-calendar) indices per sym
    (calendars identical, so per-sym index == calendar index)."""
    w0 = next(i for i, x in enumerate(DATES) if x["d"] >= a)
    w1 = max(i for i, x in enumerate(DATES) if x["d"] <= b)
    cash = 100.0; pos = {}  # sym -> dict(sh, exit_i, exit_px)
    pending = {}
    for s, trs in trades_by_sym.items():
        for tr in trs:
            if w0 <= tr["entry_i"] <= w1: pending.setdefault(tr["entry_i"], []).append((s, tr))
    curve = []; done = []; costs = 0.0; in_mkt_days = 0
    peak = 100.0; maxdd = 0.0
    for i in range(w0, w1 + 1):
        # exits first (free the slot / cash for same-day entries is NOT allowed: entries use cash as-is after exits)
        for s in list(pos):
            p = pos[s]
            if i >= p["exit_i"]:
                px = p["exit_px"] if i == p["exit_i"] else DATA[s][i]["c"]
                proceeds = p["sh"] * px * (1 - COST) - FEE
                costs += p["sh"] * px * COST + FEE
                cash += proceeds
                done.append({"sym": s, "entry_d": p["entry_d"], "exit_d": DATES[i]["d"],
                             "reason": p["reason"], "ret": round(px / p["entry_px"] - 1, 4)})
                del pos[s]
        # entries
        for s, tr in sorted(pending.get(i, []), key=lambda x: x[0]):
            if s in pos: continue
            equity = cash + sum(p["sh"] * DATA[sy][min(i, len(DATA[sy])-1)]["c"] for sy, p in pos.items())
            notional = 0.25 * equity
            if cash < 1.0: continue
            spend = min(notional, cash)
            sh = spend * (1 - COST) / tr["entry_px"]
            costs += spend * COST
            cash -= spend
            pos[s] = dict(sh=sh, exit_i=tr["exit_i"], exit_px=tr["exit_px"], reason=tr["reason"],
                          entry_px=tr["entry_px"], entry_d=DATES[i]["d"])
        if pos: in_mkt_days += 1
        mark = cash + sum(p["sh"] * DATA[s][i]["c"] for s, p in pos.items())
        peak = max(peak, mark); maxdd = min(maxdd, mark / peak - 1)
        curve.append((DATES[i]["d"], round(mark, 4)))
    if pos:
        for s in list(pos):
            p = pos[s]; px = DATA[s][w1]["c"]
            cash += p["sh"] * px * (1 - COST) - FEE
            costs += p["sh"] * px * COST + FEE
            done.append({"sym": s, "entry_d": p["entry_d"], "exit_d": DATES[w1]["d"],
                         "reason": "window-end", "ret": round(px / p["entry_px"] - 1, 4)})
        curve[-1] = (DATES[w1]["d"], round(cash, 4))
    final = round(cash, 2)
    return final, curve, done, round(maxdd, 4), round(costs, 2), round(in_mkt_days / max(1, w1 - w0 + 1), 3)

def monthly_stats(curve):
    marks = {}
    for d, e in curve: marks[d[:7]] = e
    ks = sorted(marks); rets = [marks[y] / marks[x] - 1 for x, y in zip(ks, ks[1:])]
    if not rets: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = -1; last = 0; longest = 0
    for i, k in enumerate(ks):
        if marks[k] >= peak: peak = marks[k]; last = i
        longest = max(longest, i - last)
    return dict(periods=len(rets), share_positive=round(sum(1 for r in rets if r > 0) / len(rets), 3),
                median=round(st.median(rets), 4), best=round(max(rets), 4), worst=round(min(rets), 4),
                mean_secondary=round(st.mean(rets), 4), longest_losing_streak=streak,
                longest_between_highs_months=longest)

def placebo_trades(seed):
    rng = random.Random(9000 + seed); out = {}
    for s in SYMS:
        bars = DATA[s]; sigs = find_signals(bars); ptr = []
        for t, ol in sigs:
            off = rng.choice([-1, 1]) * rng.randint(30, 250); t2 = t + off
            if t2 >= len(bars) - 2 or t2 < 20: continue
            ol2 = None; j = t2 - 1
            while j >= 19:
                if bars[j]["l"] <= min(x["l"] for x in bars[j-19:j+1]): ol2 = bars[j]["l"]; break
                j -= 1
            if ol2 is None: continue
            tr = build_trade(bars, t2, ol2)
            if tr: ptr.append(tr)
        out[s] = ptr
    return out

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
REAL = {s: gen_trades(DATA[s]) for s in SYMS}
out = {"family": "hunt-raschke-turtle-soup", "form": "v13-best-rules", "roads": {}}
for rn, (a, b) in ROADS.items():
    f, curve, done, dd, costs, tim = run_portfolio(REAL, a, b)
    pf = []
    for s in range(20):
        pf.append(run_portfolio(placebo_trades(s), a, b)[0])
    beaten = sum(1 for x in pf if f > x)
    rets = [x["ret"] for x in done]
    out["roads"][rn] = dict(final=f, max_dd=dd, n_trades=len(done), total_costs=costs,
                            time_in_market=tim, win_rate=round(sum(1 for r in rets if r > 0) / len(rets), 3) if rets else None,
                            expectancy_pct=round(st.mean(rets), 4) if rets else None,
                            placebo_finals=pf, placebo_beaten=beaten, monthly=monthly_stats(curve),
                            curve=curve, trades=done)
    print(rn, "final", f, "dd", dd, "ntr", len(done), "costs", costs, "tim", tim, "placebo", beaten, "/20", flush=True)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("DONE")
