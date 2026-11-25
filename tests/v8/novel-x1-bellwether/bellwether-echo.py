#!/usr/bin/env python3
"""
N-1 BELLWETHER ECHO — invented rule, v8 novel track ("1 of 12 invented rules").
Simulation only. Implements the frozen spec in
~/workspace/stock-app/research/v8-novel/novel-cross-calendar.md (section N-1)
verbatim, run once, no tuning:

  - 8 fixed Nov-2016 GICS clusters (membership exactly as listed in the spec).
  - Bellwether per cluster = largest market cap as of 2016-11-21
    (point-in-time EDGAR shares outstanding x actual traded close that day,
    computed once, never updated). Bellwethers are signal sources only; the
    rule never holds a bellwether.
  - Fire (daily, on closes): bellwether residual r_b(t) - r_SPY(t) >= +2.00%.
  - Follower qualifies only if its own day-t residual <= +0.50%.
  - Entry at the open of t+1: all qualifying followers of all fired
    bellwethers, equal weight, 100% of the pot; if >5 qualify, hold only the
    5 with the smallest day-t residuals.
  - Exit: sell the entire basket at the close of t+3.
  - Stacking: one event at a time; a signal firing while a basket is held is
    ignored (the exit day's own close is still "held" — see forced readings
    in the report). Outside events the pot sits in cash.
  - Placebo: same fire dates; per fired cluster, the same number of followers
    as the ranked run picked from that cluster, drawn at random from that
    cluster's followers (bellwether excluded), same mechanics, 20 seeds.

Chassis: $100 pot, costs 0.10% of trade value per side + $0.01 per sell
order, plain -15% floor ($85.00: close at/below -> liquidate at next open,
run ends). Windows: continuous 2019-01-02 -> 2026-11-20 (primary) and
validation 2023-01-03 -> 2026-11-20.

Prices for the backtest: the champion engine's cached split/dividend-
adjusted daily bars (read-only). Market-cap prices for 2016-11-21 are the
ACTUAL traded closes: Yahoo's split-adjusted close for that date multiplied
back up by every split factor after that date (splits change the share
count basis, so cap = as-filed 2016 shares x as-traded 2016 price).
"""

import importlib.util
import json
import math
import os
import random
import time
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

CHAMP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")
_spec = importlib.util.spec_from_file_location("champ", CHAMP_PATH)
champ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(champ)

UNIVERSE = champ.UNIVERSE  # the honest top-30 pond, champion order

CLUSTERS = {
    "Technology":    ["AAPL", "MSFT", "GOOGL", "META", "CSCO", "INTC", "IBM", "V", "MA"],
    "Financials":    ["BRK-B", "JPM", "BAC", "WFC"],
    "Energy":        ["XOM", "CVX"],
    "Telecom":       ["T", "VZ"],
    "Staples":       ["PG", "WMT", "KO", "PEP"],
    "Health care":   ["JNJ", "PFE", "UNH"],
    "Discretionary": ["AMZN", "HD", "DIS", "NFLX"],
    "Industrials":   ["GE", "MMM"],
}

FIRE_THRESHOLD = 0.02      # bellwether residual >= +2.00%
FOLLOWER_MAX_RESID = 0.005  # follower residual <= +0.50%
MAX_PICKS = 5
START_CASH = 100.0
FLOOR = 85.0
WINDOWS = [("CONTINUOUS", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20")]

# ---------------------------------------------------------------- bellwethers
CIK_OVERRIDES = {"XOM": 34088}  # champion engine's documented override


def shares_asof(ciks, ticker, asof="2016-11-21"):
    """Champion engine's point-in-time shares chain, as of 2016-11-21."""
    cik = CIK_OVERRIDES.get(ticker, ciks[ticker][0])
    facts = champ.get_companyfacts(cik)
    rows = (champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    return champ.pit_value(rows, asof)  # (filed, end, val) or None


def fetch_cap_payload(ticker):
    path = os.path.join(DATA_DIR, f"cap_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path) as f:
            return json.load(f)
    import calendar as _cal
    t1 = _cal.timegm(time.strptime("2016-11-01", "%Y-%m-%d"))
    t2 = _cal.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = champ.fetch(url, path, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(blob)


def actual_close_20161121(ticker, target="2016-11-21"):
    """Actual traded close on (or last bar before) 2016-11-21: Yahoo's
    split-adjusted close un-adjusted by all split factors after that date."""
    j = fetch_cap_payload(ticker)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    best = None
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        if d <= target and closes[i]:
            best = (d, closes[i])
    splits = (res.get("events") or {}).get("splits") or {}
    factor = 1.0
    split_list = []
    for ev in splits.values():
        sd = time.strftime("%Y-%m-%d", time.gmtime(ev["date"]))
        if sd > target:
            factor *= ev["numerator"] / ev["denominator"]
            split_list.append([sd, ev["numerator"], ev["denominator"]])
    return {"bar_date": best[0], "adj_close": best[1], "split_factor": factor,
            "actual_close": best[1] * factor, "splits_after": split_list}


def compute_bellwethers():
    ciks = champ.get_ciks()
    caps = {}
    for t in UNIVERSE:
        so = shares_asof(ciks, t)
        px = actual_close_20161121(t)
        if so is None:
            caps[t] = {"shares": None, **px, "cap": None}
            print(f"  CAP {t}: NO point-in-time shares as of 2016-11-21", flush=True)
            continue
        cap = so[2] * px["actual_close"]
        caps[t] = {"shares": so[2], "shares_filed": so[0], "shares_end": so[1],
                   **px, "cap": cap}
        print(f"  CAP {t}: shares={so[2]:,.0f} (filed {so[0]}) px=${px['actual_close']:,.2f} "
              f"cap=${cap/1e9:,.1f}B", flush=True)
        time.sleep(0.1)
    bellwether, followers = {}, {}
    for cname, members in CLUSTERS.items():
        scored = [(t, caps[t]["cap"]) for t in members if caps[t]["cap"]]
        scored.sort(key=lambda kv: -kv[1])
        bellwether[cname] = scored[0][0]
        followers[cname] = [t for t in members if t != scored[0][0]]
        print(f"  CLUSTER {cname}: bellwether={scored[0][0]} "
              f"(${scored[0][1]/1e9:,.1f}B); ranking=" +
              ", ".join(f"{t} ${c/1e9:,.0f}B" for t, c in scored), flush=True)
    return caps, bellwether, followers


# ---------------------------------------------------------------- price book
def load_book():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
    return champ.PriceBook(bars), bars


# ---------------------------------------------------------------- event scan
def build_returns(bars):
    spy_dates = [b["d"] for b in bars["SPY"]]
    prev_day = {spy_dates[i]: spy_dates[i - 1] for i in range(1, len(spy_dates))}
    close_map = {t: {b["d"]: b["c"] for b in bl} for t, bl in bars.items()}

    def ret(t, d):
        pd_ = prev_day.get(d)
        if pd_ is None:
            return None
        c1 = close_map[t].get(d)
        c0 = close_map[t].get(pd_)
        if c1 is None or c0 is None or c0 <= 0:
            return None
        return c1 / c0 - 1.0
    return spy_dates, ret


def scan_events(days, ret, bellwether, followers):
    """Deterministic event schedule for a window (list of SPY trading days).
    Independent of any pot's picks, so ranked and placebo runs share it."""
    events = []
    busy_until = -1  # window-day index of the current basket's exit day
    for i, d in enumerate(days):
        if i <= busy_until:
            continue
        r_spy = ret("SPY", d)
        if r_spy is None:
            continue
        resid = {}
        for t in UNIVERSE:
            r = ret(t, d)
            resid[t] = None if r is None else r - r_spy
        fired = [c for c in CLUSTERS
                 if resid[bellwether[c]] is not None
                 and resid[bellwether[c]] >= FIRE_THRESHOLD]
        if not fired:
            continue
        qual = []  # (residual, ticker, cluster)
        for c in fired:
            for f in followers[c]:
                if resid[f] is not None and resid[f] <= FOLLOWER_MAX_RESID:
                    qual.append((resid[f], f, c))
        if not qual:
            continue
        if i + 1 >= len(days):
            continue  # no room to enter inside the window
        qual.sort(key=lambda x: (x[0], x[1]))
        picks = qual[:MAX_PICKS]
        events.append({
            "signal_date": d, "signal_idx": i,
            "entry_idx": i + 1, "exit_idx": i + 3,
            "entry_date": days[i + 1],
            "exit_date": days[min(i + 3, len(days) - 1)],
            "fired_clusters": fired,
            "bellwether_resid": {c: resid[bellwether[c]] for c in fired},
            "picks": [{"ticker": t, "cluster": c, "resid": r} for r, t, c in picks],
            "qualifying_count": len(qual),
            "cluster_counts": dict(Counter(c for _, _, c in picks)),
        })
        busy_until = i + 3
    return events


# ---------------------------------------------------------------- pot runner
def run_pot(pb, days, events, pick_fn, label=""):
    """pick_fn(event) -> list of tickers to buy at the event's entry open."""
    cash = START_CASH
    positions = {}
    total_costs = 0.0
    trades = []
    halted = None
    halt_detail = None
    curve = []
    ev_by_entry = {e["entry_idx"]: e for e in events}
    ev_by_exit = {}
    for e in events:
        ev_by_exit[min(e["exit_idx"], len(days) - 1)] = e
    pending_liquidation = False
    event_pnl = []
    cash_at_entry = None
    days_invested = 0

    def close_equity(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def sell_all_at_open(d):
        nonlocal cash, total_costs
        for t in list(positions):
            b = pb.bar(t, d)
            if b:
                val = positions[t] * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, t, "SELL-HALT", positions[t], b["o"], val, c))
            del positions[t]

    def sell_all_at_close(d):
        nonlocal cash, total_costs
        for t in list(positions):
            b = pb.bar(t, d)
            px = b["c"] if b else pb.close_on_or_before(t, d)
            if px:
                val = positions[t] * px
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, t, "SELL-EXIT", positions[t], px, val, c))
            del positions[t]

    final = None
    for i, d in enumerate(days):
        if pending_liquidation:
            sell_all_at_open(d)
            final = cash
            break
        # entry at today's open
        if i in ev_by_entry and not positions:
            e = ev_by_entry[i]
            picks = pick_fn(e)
            avail = [(t, pb.bar(t, d)) for t in picks]
            avail = [(t, b) for t, b in avail if b]
            if avail:
                cash_at_entry = cash
                target = cash / len(avail)
                for t, b in avail:
                    buy_val = min(target, cash / 1.001)
                    if buy_val <= 0.005:
                        continue
                    sh = buy_val / b["o"]
                    c = buy_val * 0.001
                    cash -= buy_val + c
                    total_costs += c
                    positions[t] = positions.get(t, 0.0) + sh
                    trades.append((d, t, "BUY", sh, b["o"], buy_val, c))
        # scheduled exit at today's close
        if i in ev_by_exit and positions:
            sell_all_at_close(d)
            if cash_at_entry is not None:
                event_pnl.append(cash / cash_at_entry - 1.0)
                cash_at_entry = None
        v = close_equity(d)
        curve.append((d, v))
        if positions:
            days_invested += 1
        # floor check (champion convention: not evaluated on the final day)
        if v <= FLOOR and i < len(days) - 1:
            halted = d
            if positions:
                halt_detail = {"signal_close": round(v, 2), "floor": FLOOR,
                               "mode": "liquidate next open"}
                pending_liquidation = True
            else:
                halt_detail = {"signal_close": round(v, 2), "floor": FLOOR,
                               "mode": "flat at/below floor after exit"}
                final = cash
                break
    if final is None:
        if positions:  # safety net: mark out at final close
            sell_all_at_close(days[-1])
        final = cash
    worst_d, worst_v = min(curve, key=lambda kv: kv[1]) if curve else (None, None)
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"label": label, "final": round(final, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted, "halt_detail": halt_detail,
            "events_executed": len(event_pnl), "event_pnl": event_pnl,
            "days_invested": days_invested, "n_days": len(days),
            "worst_close": round(worst_v, 2) if worst_v is not None else None,
            "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2), "trades": trades}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# --------------------------------------------------------------------- main
def main():
    print("== Bellwether designation (Nov-2016 caps, computed once) ==", flush=True)
    caps, bellwether, followers = compute_bellwethers()

    print("== Loading champion price cache ==", flush=True)
    pb, bars = load_book()
    spy_dates, ret = build_returns(bars)

    # Integrity gate: SPY buy-hold through the champion engine's own spy_net.
    print("== Integrity gate (champion spy_net) ==", flush=True)
    spy_ok = {}
    for wname, ws, we in WINDOWS:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        spy_ok[wname] = round(s, 2)
        print(f"  {wname} SPY net = ${s:,.2f}", flush=True)
    assert abs(spy_ok["CONTINUOUS"] - 313.62) < 0.01, spy_ok
    assert abs(spy_ok["VALIDATION"] - 187.77) < 0.01, spy_ok
    print("  SPY gate passed to the cent ($313.62 / $187.77).", flush=True)

    out = {"rule": "N-1 Bellwether Echo (invented 2026; 1 of 12 invented rules)",
           "bellwethers": bellwether, "followers": followers, "caps_2016_11_21": caps,
           "spy_gate": spy_ok, "windows": {}}

    for wname, ws, we in WINDOWS:
        days = [d for d in spy_dates if ws <= d <= we]
        events = scan_events(days, ret, bellwether, followers)
        print(f"\n== {wname} {ws} -> {we}: {len(events)} events ==", flush=True)
        for e in events:
            print(f"  signal {e['signal_date']} fired={e['fired_clusters']} "
                  f"qual={e['qualifying_count']} picks="
                  f"{[(p['ticker'], round(p['resid'] * 100, 2)) for p in e['picks']]} "
                  f"entry {e['entry_date']} exit {e['exit_date']}", flush=True)

        ranked = run_pot(pb, days, events,
                         lambda e: [p["ticker"] for p in e["picks"]],
                         label=f"{wname} RANKED")
        print(f"  RANKED final=${ranked['final']:,.2f} costs=${ranked['costs']:,.2f} "
              f"orders={ranked['orders']} halted={ranked['halted']} "
              f"events={ranked['events_executed']}", flush=True)

        placebo_finals, placebo_runs = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)

            def placebo_picks(e, rng=rng):
                picks = []
                for c, k in e["cluster_counts"].items():
                    picks.extend(rng.sample(sorted(followers[c]), k))
                return picks

            r = run_pot(pb, days, events, placebo_picks, label=f"{wname} P{seed}")
            placebo_finals.append(r["final"])
            placebo_runs.append({"seed": seed, "final": r["final"],
                                 "halted": r["halted"], "costs": r["costs"],
                                 "orders": r["orders"]})
        sf = sorted(placebo_finals)
        beat = sum(1 for f in placebo_finals if ranked["final"] > f)
        print(f"  PLACEBO median=${_pct(sf, 0.5):,.2f} best=${sf[-1]:,.2f} "
              f"worst=${sf[0]:,.2f} beat={beat}/20", flush=True)

        out["windows"][wname] = {
            "start": ws, "end": we, "n_events": len(events),
            "events": [{k: v for k, v in e.items()} for e in events],
            "ranked": {k: v for k, v in ranked.items() if k != "trades"},
            "ranked_trades": ranked["trades"],
            "placebo": {"finals": placebo_finals, "runs": placebo_runs,
                        "median": round(_pct(sf, 0.5), 2),
                        "p25": round(_pct(sf, 0.25), 2),
                        "p75": round(_pct(sf, 0.75), 2),
                        "best": sf[-1], "worst": sf[0], "beat": beat,
                        "halted_twins": sum(1 for r in placebo_runs if r["halted"])},
        }

    # CANDIDATE checklist (task's pre-registered bar for an invented rule)
    val = out["windows"]["VALIDATION"]
    con = out["windows"]["CONTINUOUS"]
    checks = {
        "validation_final_gt_spy_187.77": val["ranked"]["final"] > 187.77,
        "validation_placebo_beat_ge_19_of_20": val["placebo"]["beat"] >= 19,
        "continuous_final_gt_spy_313.62": con["ranked"]["final"] > 313.62,
        "no_floor_halt_either_window": (val["ranked"]["halted"] is None
                                        and con["ranked"]["halted"] is None),
    }
    out["candidate_checks"] = checks
    out["verdict"] = "CANDIDATE" if all(checks.values()) else "NOT A CANDIDATE"
    print(f"\n== VERDICT: {out['verdict']} == checks: {checks}", flush=True)

    with open(os.path.join(HERE, "bellwether-echo-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
