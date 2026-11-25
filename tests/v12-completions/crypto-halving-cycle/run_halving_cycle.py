#!/usr/bin/env python3
"""
crypto-halving-cycle — Pantera 500-day rule (buy H-500 open, sell H+500 open),
frozen in CONSTRUCTION-SPEC.md before this run. Simulation only.

Data (read-only): backtests/v4/crypto-basket-pit-data/y_<SYM>-USD.json
Costs: 0.60%/side primary (crypto standard 0.40-0.80); BTC native also at 0.40/0.80.
Rule sets: NATIVE (no floor) and V9 (plain -15% ep-1 floor from $100 start,
90d cash pause, restart at next decision point, ep-2 floor -15% of restart
balance, second halt = end).
Placebos: 20 seeds, uniform phase shift of all halving dates, native, same costs.
"""
import json, math, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v4", "crypto-basket-pit-data")
POT = 100.0
COST = 0.006

HALVINGS = {
    "BTC": ["2016-07-09", "2020-05-11", "2024-04-20"],
    "LTC": ["2019-08-05", "2023-08-02"],
    "BCH": ["2020-04-08", "2024-04-04"],
    "BSV": ["2020-04-10", "2024-04-13"],
    "BTG": ["2024-04-24"],
    "ZEC": ["2020-11-18", "2024-11-23"],
}

def dparse(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)

def load(sym):
    with open(os.path.join(DATA, f"y_{sym}-USD.json")) as f:
        rows = json.load(f)
    bars = [(dparse(r["d"]), float(r["o"]), float(r["c"])) for r in rows]
    bars.sort()
    return bars

def windows_for(halvings, shift=0):
    ws = []
    for h in halvings:
        hd = dparse(h) + timedelta(days=shift)
        ws.append((hd - timedelta(days=500), hd + timedelta(days=500), hd))
    return ws

def run(bars, windows, cost=COST, v9=False):
    """Daily simulation. Returns dict with final, curve, trades, halts, maxdd, exposure."""
    idx = {b[0]: i for i, b in enumerate(bars)}
    dates = [b[0] for b in bars]
    def bar_on_or_after(d):
        # first bar with date >= d
        import bisect
        i = bisect.bisect_left(dates, d)
        return i if i < len(bars) else None
    first_buy = windows[0][0]
    start_i = bar_on_or_after(first_buy)
    if start_i is None:
        return None
    # schedule: map bar index -> action
    cash = POT
    units = 0.0
    curve = []
    trades = []
    halts = []
    invested_days = 0
    total_days = 0
    # v9 state
    episode = 1
    floor_level = 0.85 * POT
    halted_until = None   # date until which we sit in cash after a halt
    ended = False
    pending_sell_floor = False  # breach seen on close, sell at next open

    # Precompute intended buy/sell bar indices per window
    sched = []  # (buy_i, sell_i, halving_date)
    for (bd, sd, hd) in windows:
        bi = bar_on_or_after(bd)
        si = bar_on_or_after(sd)
        sched.append((bi, si, hd))
    in_window = [False] * len(bars)
    for (bi, si, hd) in sched:
        if bi is not None and si is not None:
            for i in range(bi, si):
                in_window[i] = True

    peak = POT
    maxdd = 0.0
    for i in range(start_i, len(bars)):
        d, o, c = bars[i]
        total_days += 1
        # --- open actions ---
        if pending_sell_floor and units > 0:
            proceeds = units * o * (1 - cost)
            trades.append({"date": str(d), "side": "SELL-FLOOR", "price": o, "proceeds": round(proceeds, 2)})
            cash = proceeds
            units = 0.0
            halts.append({"breach_fill_date": str(d), "fill_value": round(cash, 2), "episode": episode})
            pending_sell_floor = False
            if episode == 1:
                episode = 2
                halted_until = d + timedelta(days=90)
                floor_level = 0.85 * cash
            else:
                ended = True
        # scheduled sells at open
        if units > 0:
            for (bi, si, hd) in sched:
                if si == i:
                    proceeds = units * o * (1 - cost)
                    trades.append({"date": str(d), "side": "SELL", "price": o, "proceeds": round(proceeds, 2), "halving": str(hd)})
                    cash = proceeds
                    units = 0.0
        # buys at open: scheduled window entry, or v9 restart re-entry
        want_in = in_window[i] and not ended
        if v9 and halted_until is not None and d < halted_until:
            want_in = False
        if units == 0 and cash > 0 and want_in:
            is_sched_buy = any(bi == i for (bi, si, hd) in sched)
            is_restart = v9 and halted_until is not None and d >= halted_until
            if is_sched_buy or is_restart:
                spend = cash
                units = spend * (1 - cost) / o
                trades.append({"date": str(d), "side": "BUY" if is_sched_buy else "BUY-RESTART",
                               "price": o, "spent": round(spend, 2)})
                cash = 0.0
                if is_restart:
                    halted_until = None
        # --- mark on close ---
        equity = cash + units * c
        if units > 0:
            invested_days += 1
        curve.append([str(d), round(equity, 4)])
        if equity > peak:
            peak = equity
        dd = equity / peak - 1.0
        if dd < maxdd:
            maxdd = dd
        # --- v9 floor check on close ---
        if v9 and units > 0 and not ended and equity <= floor_level:
            pending_sell_floor = True
    final = curve[-1][1] if curve else POT
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 1),
            "trades": trades, "n_trades": len(trades), "halts": halts,
            "exposure_pct": round(100.0 * invested_days / max(total_days, 1), 1),
            "curve": curve}

def buyhold(bars, start_date, cost=COST):
    import bisect
    dates = [b[0] for b in bars]
    i = bisect.bisect_left(dates, start_date)
    o = bars[i][1]
    units = POT * (1 - cost) / o
    curve = []
    peak = POT
    maxdd = 0.0
    for j in range(i, len(bars)):
        eq = units * bars[j][2]
        curve.append([str(bars[j][0]), round(eq, 4)])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(maxdd * 100, 1), "curve": curve}

def main():
    out = {"spec": "Pantera 500-day rule, frozen CONSTRUCTION-SPEC.md 2026-11-22",
           "cost_primary_per_side": COST, "pot": POT, "coins": {}}
    btc_bh = None
    for sym, halv in HALVINGS.items():
        bars = load(sym)
        ws = windows_for(halv)
        native = run(bars, ws, v9=False)
        v9r = run(bars, ws, v9=True)
        bh = buyhold(bars, ws[0][0])
        if sym == "BTC":
            btc_bh = bh
        # placebos
        rng = random.Random(20261122)
        finals = []
        for seed in range(20):
            shift = rng.choice([-1, 1]) * rng.randint(60, 730)
            pw = windows_for(halv, shift=shift)
            pr = run(bars, pw, v9=False)
            finals.append(pr["final"])
        finals_sorted = sorted(finals)
        med = finals_sorted[10]
        pct = sum(1 for f in finals if f < native["final"]) / len(finals) * 100
        # per-window native finals (standalone $100 per window, for confirmation split)
        per_window = []
        for w in ws:
            r = run(bars, [w], v9=False)
            # window buy-and-hold: buy at window buy open, sell at window sell open
            import bisect as _b
            _dates = [b[0] for b in bars]
            _bi = _b.bisect_left(_dates, w[0]); _si = _b.bisect_left(_dates, w[1])
            _units = POT * (1 - COST) / bars[_bi][1]
            _wb = _units * bars[_si][1] * (1 - COST)
            per_window.append({"halving": str(w[2]), "buy": str(w[0]), "sell": str(w[1]),
                               "strategy_final": r["final"], "strategy_max_dd_pct": r["max_dd_pct"],
                               "buyhold_window_final": round(_wb, 2)})
        entry = {"windows": [[str(a), str(b), str(c)] for a, b, c in ws],
                 "native": {k: v for k, v in native.items() if k != "curve"},
                 "v9": {k: v for k, v in v9r.items() if k != "curve"},
                 "buyhold_same_span": {k: v for k, v in bh.items() if k != "curve"},
                 "placebo_phase_shift": {"seeds": 20, "median_final": med,
                                         "min_final": finals_sorted[0], "max_final": finals_sorted[-1],
                                         "strategy_percentile": pct, "finals": finals},
                 "per_window_native": per_window,
                 "curves": {"native": native["curve"], "v9": v9r["curve"], "buyhold": bh["curve"]}}
        if sym == "BTC":
            entry["native_cost_040"] = run(bars, ws, cost=0.004)["final"]
            entry["native_cost_080"] = run(bars, ws, cost=0.008)["final"]
        out["coins"][sym] = entry
        print(sym, "native", native["final"], "v9", v9r["final"], "B&H", bh["final"],
              "placebo med", med, "pct", pct, "maxDD native", native["max_dd_pct"], "B&H DD", bh["max_dd_pct"])
    out["btc_buyhold_reference"] = {k: v for k, v in btc_bh.items() if k != "curve"}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("written results.json")

if __name__ == "__main__":
    main()
