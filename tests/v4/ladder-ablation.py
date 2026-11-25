#!/usr/bin/env python3
"""
LADDER ABLATION — Terry's AI stock app, simulation only.

Question: does the PROFIT LADDER in Terry's floor rule help or hurt?
Evidence prompting the test: in two separate studies (slow-illiquidity
sleeve; value+momentum), pots were liquidated when a crash pulled them
down to a floor the LADDER had ratcheted up during earlier gains —
banking near-breakeven and missing the entire recovery — while a plain
-15%-from-start floor would NOT have fired in either case.

Base strategy: the survivorship-honest momentum basket
(momentum-basket-honest.py) — engine, universe (Nov-2016 top-30),
monthly top-5 by 12-1 momentum among names above their 200-day average,
costs 0.10%/side + $0.01/sell — reused exactly. The ONLY change across
variants is the pot-level protection rule:

  (a) CONTROL — Terry's ladder as-is:
        $100 pot: floor $85; -> $100 at a $125 close, -> $125 at a $150 close.
        $50  pot: floor $42.50; -> $50 at $62.50, -> $62.50 at $75.
  (b) PLAIN FLOOR — -15% from the starting balance, no ladder, ever.
  (c) PEAK TRAILING FLOOR — plain -15% floor until the pot's highest
        CLOSE exceeds +25% over start; from then on the floor trails at
        85% of the highest close (protection scales with gains).

Runs: full 2016-11-21 -> 2026-11-20 and validation 2023-01-01 ->
2026-11-20, at $50 and $100, all three variants (ranked mode only).
Control check: variant (a) must reproduce the published honest-basket
numbers (full $439.45 / $215.61; validation $208.27 / $103.18) exactly.

Data: same Yahoo cache as momentum-basket-honest (./momentum-basket-honest-data/).
"""

import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "mbh", os.path.join(HERE, "momentum-basket-honest.py"))
mbh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mbh)

UNIVERSE = mbh.UNIVERSE
COST_RATE = mbh.COST_RATE
SELL_FEE = mbh.SELL_FEE
FLOORS = mbh.FLOORS            # control ladder config, reused for variant (a)
WINDOWS = {
    "full":       ("2016-11-21", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PUBLISHED_CONTROL = {          # from momentum-basket-honest.md
    ("full", 100): 439.45, ("full", 50): 215.61,
    ("validation", 100): 208.27, ("validation", 50): 103.18,
}
VARIANTS = ("ladder", "plain", "trailing")


class Result(mbh.Result):
    def __init__(self):
        super().__init__()
        self.floor_at_halt = None     # floor value in force when halt fired
        self.halt_cause = None        # which part of the rule fired
        self.peak_close = 0.0         # highest closing equity in the run
        self.protection_engaged = None  # date ladder/trailing first rose


def simulate(mkt, start_d, end_d, pot0, variant):
    """Ranked momentum basket; `variant` selects ONLY the protection rule.
    Body is momentum-basket-honest.simulate(mode='ranked') with the floor
    block parameterized; everything else is unchanged."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = FLOORS[pot0]
    floor = floor0
    cash = float(pot0)
    pos = {}
    res = Result()
    pending_liquidation = False
    mark_px = {}
    cur_month = None
    peak_close = 0.0

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    def cause():
        if variant == "ladder":
            return ("initial -15% floor" if floor <= floor0 + 1e-9
                    else "ladder-ratcheted floor")
        if variant == "plain":
            return "initial -15% floor (plain, never moved)"
        return ("initial -15% floor (trailing not yet active)"
                if peak_close <= 1.25 * pot0
                else "peak trailing floor (85% of highest close)")

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

        # --- floor liquidation at the open -------------------------------
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                if t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        # --- monthly selection / rebalance at the open -------------------
        if month_key != cur_month and i > 0:
            cur_month = month_key
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            elig.sort(key=lambda x: -x[1])
            picks = [t for t, _ in elig[:5]]

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}

            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        # --- close: equity, PROTECTION RULE (the only change), floor -----
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        peak_close = max(peak_close, eq_close)
        if variant == "ladder":
            for thresh, new_floor in ladder:
                if eq_close >= thresh and new_floor > floor:
                    floor = new_floor
                    if res.protection_engaged is None:
                        res.protection_engaged = d
        elif variant == "trailing":
            if peak_close > 1.25 * pot0:
                new_floor = 0.85 * peak_close
                if new_floor > floor:
                    floor = new_floor
                    if res.protection_engaged is None:
                        res.protection_engaged = d
        # variant == "plain": floor never moves.
        if eq_close <= floor:
            res.floor_at_halt = floor
            res.halt_cause = cause()
            pending_liquidation = True
            if i == i1:      # no next open inside window: liquidate at close
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    res.peak_close = peak_close
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        res.month_rets.append(r)
        if r > 0:
            res.month_wins += 1
    return res


def main():
    mkt = mbh.Market(UNIVERSE)
    out = {"variants": list(VARIANTS), "windows": WINDOWS}
    ok = True
    for wname, (sd, ed) in WINDOWS.items():
        yrs = mbh.years_between(sd, ed)
        for pot in (100, 50):
            bench = mbh.spy_net(mkt, sd, ed, pot)
            runs = {}
            for v in VARIANTS:
                r = simulate(mkt, sd, ed, pot, v)
                runs[v] = r
                out[f"{wname}|{pot}|{v}"] = {
                    "final": round(r.final, 2),
                    "ret_pct": round((r.final / pot - 1) * 100, 2),
                    "cagr_pct": round(mbh.cagr(r.final, pot, yrs) * 100, 2),
                    "orders": r.orders,
                    "costs": round(r.costs, 2),
                    "max_dd_pct": round(r.max_dd * 100, 2),
                    "halt": r.halt_date,
                    "halt_cause": r.halt_cause,
                    "floor_at_halt": (round(r.floor_at_halt, 2)
                                      if r.floor_at_halt else None),
                    "peak_close": round(r.peak_close, 2),
                    "protection_engaged": r.protection_engaged,
                    "bench_final": round(bench, 2),
                }
                print(f"{wname}|{pot}|{v}: final={r.final:.2f} "
                      f"ret={(r.final/pot-1)*100:+.2f}% "
                      f"maxDD={r.max_dd*100:.2f}% halt={r.halt_date} "
                      f"cause={r.halt_cause} peak={r.peak_close:.2f} "
                      f"SPYnet={bench:.2f}", flush=True)
            # protection cost/save vs control, this window & size
            ctrl = runs["ladder"].final
            for v in ("plain", "trailing"):
                out[f"{wname}|{pot}|{v}"]["vs_control"] = round(
                    runs[v].final - ctrl, 2)
            # control reproduction check
            pub = PUBLISHED_CONTROL[(wname, pot)]
            if abs(runs["ladder"].final - pub) > 0.011:
                ok = False
                print(f"CONTROL MISMATCH {wname}|{pot}: got "
                      f"{runs['ladder'].final:.2f}, published {pub:.2f}",
                      flush=True)
    out["control_reproduced"] = ok
    print("control reproduced:", ok)
    with open(os.path.join(HERE, "ladder-ablation-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved ladder-ablation-results.json")


if __name__ == "__main__":
    main()
