#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — Lazy Prices parameterized engine.

A verbatim copy of the original gap-a5 `run_pot` mechanics
(~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/lazy-prices.py,
READ-ONLY) with exactly one change: the hardcoded top-5 becomes a
parameter N.

  - picks   = top-min(N, scored pool) by most-recent 10-K similarity
  - target  = portfolio value / len(picks) each (equal weight)
  - placebo = random sample of len(picks) names from the same scored pool
  - the original viability gate is kept: a selection happens only when
    at least 5 names are scorable (the original engine's `len >= 5`)
  - N = "ALL" holds the entire scored pool, equal weight

Everything else — quarterly selection calendar (first trading day of
Jan/Apr/Jul/Oct), rebalance at the next open, sells before buys,
program costs (0.10%/side + $0.01 per sell order), plain -15% floor
semantics (a close at/below the floor liquidates at the next open and
ends the episode), end-of-window liquidation at the final close — is
copied line for line. The v9 house wrapper is lr_common.run_v9,
imported unmodified.
"""
import os
import sys

LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

lazy = C.load_module("lazy_hcount", os.path.join(
    C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
latest_signal = lazy.latest_signal
quarter_selection_dates = lazy.quarter_selection_dates


def run_pot_n(pb, signals, universe, start, end, n,
              start_cash=100.0, floor0=85.0, placebo_rng=None,
              label="", record_pools=False):
    cash = start_cash
    positions, trades, pools = {}, [], []
    total_costs = 0.0
    halted, halt_info = None, None
    curve = []
    sel_dates = quarter_selection_dates(pb, start, end)
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

    for di, d in enumerate(days):
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
                k = len(scores) if n == "ALL" else min(n, len(scores))
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
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
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
