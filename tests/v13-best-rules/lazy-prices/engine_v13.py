#!/usr/bin/env python3
"""
V13 BEST RULES — Lazy Prices engine.

The original gap-a5 `run_pot` mechanics (via the v12 parameterized
engine_n.py, READ-ONLY source) with exactly the two changes frozen in
BEST-RULES-SPEC.md:

  1. MONTHLY selection calendar — first trading day of every month
     (the original used Jan/Apr/Jul/Oct only).
  2. NO floor — the halt block is removed; the pot rides full drawdowns.

Everything else is verbatim: top-5 by most-recent 10-K similarity
(acceptance date strictly before the selection date), the >=5 scorable
viability gate, equal-weight targets, rebalance at the next open, sells
before buys, program costs (0.10%/side + $0.01 per sell order),
end-of-window liquidation at the final close. Placebo mode samples 5
names at random from the same scored pool on the same dates.
"""
import os
import sys

LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

lazy = C.load_module("lazy_v13", os.path.join(
    C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
latest_signal = lazy.latest_signal

N = 5


def month_selection_dates(pb, start, end):
    """First trading day of each calendar month inside the window."""
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def run_pot(pb, signals, universe, start, end, start_cash=100.0,
            placebo_rng=None, label="", record_pools=False):
    cash = start_cash
    positions, trades, pools = {}, [], []
    total_costs = 0.0
    curve = []
    sel_dates = month_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for d in days:
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = {}
            for t in universe:
                sig = latest_signal(signals.get(t, []), d)
                if sig is not None:
                    scores[t] = sig[1]
            if len(scores) >= 5:
                k = min(N, len(scores))
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), k)
                else:
                    picks = sorted(scores, key=lambda t: -scores[t])[:k]
                if record_pools:
                    pools.append({"date": d, "pool": len(scores),
                                  "picks": list(picks)})
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}
