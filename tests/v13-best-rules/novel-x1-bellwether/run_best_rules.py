#!/usr/bin/env python3
"""
V13 BEST-RULES — N-1 BELLWETHER ECHO. Simulation only.
Implements BEST-RULES-SPEC.md (frozen before this run) exactly:
  - SPY baseline when no event is live (was: cash)
  - NO floor (was: plain -15%)
  - Trigger: bellwether idiosyncratic residual >= +3.00% (was: +2.00%)
  - Selection: ALL followers of fired cluster(s), equal weight, cap 10,
    clusters filled by bellwether residual desc (was: <=5 least-reacted,
    non-reaction screen <= +0.50% -- deleted)
  - Market-state gate: SPY close > 200d MA on day t AND SPY trailing
    10-session return > -3%
  - Hold 5 sessions: enter t+1 open, exit close of t+5 (was: t+3)
  - One event at a time; daily scan; program costs on every trade incl. SPY.
Placebos: 20 seeds/road, same gated fire dates, same name count drawn at
random from all 22 followers, same mechanics.
Data: program long-run pxfull payloads (read-only) via the v8 engine's
chassis; bellwether designations from the v8 run's recorded output.
"""
import importlib.util
import json
import math
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")

_spec = importlib.util.spec_from_file_location(
    "x1v8", os.path.join(BT, "v8", "novel-x1-bellwether", "bellwether-echo.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
champ = M.champ


def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(
            BT, "v10-retest", "novel-x1-bellwether", "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


champ.get_prices = pxfull
PB, BARS = M.load_book()
SPY_DATES, RET = M.build_returns(BARS)
_orig = json.load(open(os.path.join(
    BT, "v8", "novel-x1-bellwether", "bellwether-echo-results.json")))
BEL = _orig["bellwethers"]          # {cluster: ticker}
FOL = _orig["followers"]            # {cluster: [tickers]}
CLUSTERS = M.CLUSTERS
ALL_FOLLOWERS = sorted({f for v in FOL.values() for f in v})

SPY_CLOSE = {b["d"]: b["c"] for b in BARS["SPY"]}
_spy_series = [SPY_CLOSE[d] for d in SPY_DATES]
SPY_IDX = {d: i for i, d in enumerate(SPY_DATES)}


def gate_ok(d):
    """Market-state gate on day t (SPY data through t only)."""
    i = SPY_IDX[d]
    if i < 200:
        return False
    ma200 = sum(_spy_series[i - 199:i + 1]) / 200.0
    if not (_spy_series[i] > ma200):
        return False
    if i < 10:
        return False
    return _spy_series[i] / _spy_series[i - 10] - 1.0 > -0.03


FIRE = 0.03
MAX_PICKS = 10
HOLD_EXIT_OFF = 5  # exit at close of t+5 (entry t+1)


def scan_events(days):
    """Gated fire schedule for a window. Returns events with ranked picks
    (all followers of fired clusters, cap 10) and per-event pick count."""
    dayset = {d: i for i, d in enumerate(days)}
    events = []
    busy_until = -1
    for i, d in enumerate(days):
        if i <= busy_until:
            continue
        r_spy = RET("SPY", d)
        if r_spy is None:
            continue
        resid = {}
        for t in M.UNIVERSE:
            r = RET(t, d)
            resid[t] = None if r is None else r - r_spy
        fired = [c for c in CLUSTERS
                 if resid[BEL[c]] is not None and resid[BEL[c]] >= FIRE]
        if not fired:
            continue
        if not gate_ok(d):
            continue
        if i + 1 >= len(days):
            continue
        fired.sort(key=lambda c: -resid[BEL[c]])
        picks = []
        for c in fired:
            for f in FOL[c]:
                if len(picks) >= MAX_PICKS:
                    break
                picks.append(f)
            if len(picks) >= MAX_PICKS:
                break
        exit_idx = min(i + HOLD_EXIT_OFF, len(days) - 1)
        events.append({"signal_date": d, "signal_idx": i,
                       "entry_idx": i + 1, "exit_idx": exit_idx,
                       "entry_date": days[i + 1], "exit_date": days[exit_idx],
                       "fired_clusters": fired,
                       "bellwether_resid": {c: resid[BEL[c]] for c in fired},
                       "picks": picks, "n_picks": len(picks)})
        busy_until = exit_idx
    return events


def run_pot(days, events, pick_fn):
    """SPY-baseline event pot. pick_fn(event)->tickers bought at entry open.
    Start: buy SPY at first day's open. Event entry: sell SPY at open, buy
    basket. Exit: sell basket at exit close; re-buy SPY at next day's open
    (or mark final if window ends). No floor."""
    cash = 100.0
    positions = {}  # ticker -> shares ("SPY" or basket names)
    total_costs = 0.0
    orders = 0
    trades = []
    curve = []
    ev_by_entry = {e["entry_idx"]: e for e in events}
    ev_by_exit = {e["exit_idx"]: e for e in events}
    event_pnl = []
    cash_at_entry = None

    def buy(t, d, px, val):
        nonlocal cash, total_costs, orders
        if val <= 0.005 or px is None or px <= 0:
            return
        sh = val / px
        c = val * 0.001
        cash -= val + c
        total_costs += c
        orders += 1
        positions[t] = positions.get(t, 0.0) + sh
        trades.append([d, t, "BUY", round(sh, 6), px, round(val, 2), round(c, 4)])

    def sell(t, d, px):
        nonlocal cash, total_costs, orders
        if t not in positions or px is None or px <= 0:
            return
        val = positions[t] * px
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        orders += 1
        trades.append([d, t, "SELL", round(positions[t], 6), px,
                       round(val, 2), round(c, 4)])
        del positions[t]

    def equity(d):
        v = cash
        for t, sh in positions.items():
            c = PB.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    for i, d in enumerate(days):
        # window start: buy SPY at open
        if i == 0:
            b = PB.bar("SPY", d)
            if b:
                buy("SPY", d, b["o"], cash / 1.001)
        # event entry at open: SPY -> basket
        if i in ev_by_entry and "SPY" in positions:
            e = ev_by_entry[i]
            bspy = PB.bar("SPY", d)
            sell("SPY", d, bspy["o"] if bspy else None)
            picks = pick_fn(e)
            avail = [(t, PB.bar(t, d)) for t in picks]
            avail = [(t, b) for t, b in avail if b]
            if avail:
                cash_at_entry = cash
                target = cash / len(avail)
                for t, b in avail:
                    buy(t, d, b["o"], min(target, cash / 1.001))
        # event exit at close
        if i in ev_by_exit and positions and "SPY" not in positions:
            for t in list(positions):
                b = PB.bar(t, d)
                sell(t, d, b["c"] if b else PB.close_on_or_before(t, d))
            if cash_at_entry is not None:
                event_pnl.append(round(cash / cash_at_entry - 1.0, 6))
                cash_at_entry = None
            # re-buy SPY at next open is handled by flag below
            if i + 1 < len(days):
                positions["_PENDING_SPY"] = 0.0
        elif i > 0 and "_PENDING_SPY" in positions:
            del positions["_PENDING_SPY"]
            b = PB.bar("SPY", d)
            if b:
                buy("SPY", d, b["o"], cash / 1.001)
        curve.append((d, round(equity(d), 4)))
    # final liquidation at last close (costs charged)
    last = days[-1]
    for t in list(positions):
        if t == "_PENDING_SPY":
            del positions[t]
            continue
        b = PB.bar(t, last)
        sell(t, last, b["c"] if b else PB.close_on_or_before(t, last))
    final = cash
    peak, maxdd, worst_v, worst_d = -1.0, 0.0, None, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
        if worst_v is None or v < worst_v:
            worst_v, worst_d = v, d
    return {"final": round(final, 2), "costs": round(total_costs, 2),
            "orders": orders, "events_executed": len(event_pnl),
            "event_pnl": event_pnl,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "curve": curve, "trades": trades}


def monthly_dist(curve):
    """Per-period (calendar-month) distribution from a daily curve."""
    months = {}
    for d, v in curve:
        months[d[:7]] = v  # last value of month wins (curve is ordered)
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        rets.append((k, months[k] / prev - 1.0, months[k] - prev))
        prev = months[k]
    if not rets:
        return {}
    pcts = sorted(r for _, r, _ in rets)

    def pctile(s, q):
        if len(s) == 1:
            return s[0]
        pos = q * (len(s) - 1)
        lo, hi = int(math.floor(pos)), int(math.ceil(pos))
        return s[lo] if lo == hi else s[lo] * (1 - pos + lo) + s[hi] * (pos - lo)

    streak = mx = 0
    for _, r, _ in rets:
        streak = streak + 1 if r < 0 else 0
        mx = max(mx, streak)
    peak, since, mx_since = -1.0, 0, 0
    for _, v in curve:
        if v >= peak:
            peak, since = v, 0
        else:
            since += 1
        mx_since = max(mx_since, since)
    best = max(rets, key=lambda x: x[1])
    worst = min(rets, key=lambda x: x[1])
    return {"n_periods": len(rets),
            "median_period_pct": round(pctile(pcts, 0.5) * 100, 2),
            "share_positive_pct": round(100.0 * sum(1 for r in pcts if r > 0) / len(pcts), 1),
            "best_period": {"month": best[0], "pct": round(best[1] * 100, 2), "usd": round(best[2], 2)},
            "worst_period": {"month": worst[0], "pct": round(worst[1] * 100, 2), "usd": round(worst[2], 2)},
            "longest_losing_streak_months": mx,
            "longest_stretch_between_new_highs_days": mx_since,
            "mean_period_pct_secondary": round(sum(pcts) / len(pcts) * 100, 2)}


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return sorted_vals[lo] if lo == hi else \
        sorted_vals[lo] * (1 - pos + lo) + sorted_vals[hi] * (pos - lo)


ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 71.88, "DECADE": 71.09, "CONT": 67.20, "VAL": 124.74}


def main():
    print("== Integrity gate: SPY buy-hold via champion spy_net ==", flush=True)
    gate = {}
    for w, (s, e) in ROADS.items():
        v, _ = champ.spy_net(PB, s, e, 100.0)
        gate[w] = round(v, 2)
        print(f"  {w} SPY net = ${v:,.2f} (ref ${SPY_REF[w]:,.2f})", flush=True)
        assert abs(gate[w] - SPY_REF[w]) < 0.02, (w, gate[w])
    print("  SPY gate passed on all four roads.", flush=True)

    out = {"rule": "N-1 Bellwether Echo — V13 BEST RULES (SPY baseline, no floor, "
                   "+3% trigger, all-followers basket, market-state gate, 5-session hold)",
           "bellwethers": BEL, "followers": FOL, "spy_gate": gate,
           "roads": {}}
    for w, (s, e) in ROADS.items():
        days = [d for d in SPY_DATES if s <= d <= e]
        events = scan_events(days)
        print(f"\n== {w} {s}->{e}: {len(events)} gated events ==", flush=True)
        ranked = run_pot(days, events, lambda ev: ev["picks"])
        print(f"  RANKED final=${ranked['final']:,.2f} costs=${ranked['costs']:,.2f} "
              f"orders={ranked['orders']} maxDD=-{ranked['max_drawdown_pct']}% "
              f"events={ranked['events_executed']}", flush=True)
        pfinals, pruns = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)

            def placebo_picks(ev, rng=rng):
                return rng.sample(ALL_FOLLOWERS, ev["n_picks"])

            r = run_pot(days, events, placebo_picks)
            pfinals.append(r["final"])
            pruns.append({"seed": seed, "final": r["final"],
                          "max_drawdown_pct": r["max_drawdown_pct"],
                          "costs": r["costs"], "orders": r["orders"]})
        sf = sorted(pfinals)
        beat = sum(1 for f in pfinals if ranked["final"] > f)
        print(f"  PLACEBO median=${pct(sf, 0.5):,.2f} best=${sf[-1]:,.2f} "
              f"worst=${sf[0]:,.2f} beat={beat}/20", flush=True)
        ep = ranked["event_pnl"]
        out["roads"][w] = {
            "start": s, "end": e, "n_events": len(events),
            "events": [{k: v for k, v in ev.items()} for ev in events],
            "ranked": {k: v for k, v in ranked.items() if k != "trades"},
            "ranked_trades": ranked["trades"],
            "monthly_distribution": monthly_dist(ranked["curve"]),
            "event_stats": {
                "n": len(ep),
                "win_rate_pct": round(100.0 * sum(1 for x in ep if x > 0) / len(ep), 1) if ep else None,
                "mean_net_pct": round(sum(ep) / len(ep) * 100, 3) if ep else None,
                "best_pct": round(max(ep) * 100, 2) if ep else None,
                "worst_pct": round(min(ep) * 100, 2) if ep else None},
            "placebo": {"finals": pfinals, "runs": pruns,
                        "median": round(pct(sf, 0.5), 2),
                        "p25": round(pct(sf, 0.25), 2),
                        "p75": round(pct(sf, 0.75), 2),
                        "best": sf[-1], "worst": sf[0], "beat": beat},
            "references": {"spy": SPY_REF[w], "champion_vm": CHAMP[w],
                           "published_form_v11": PUBLISHED[w]}}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
