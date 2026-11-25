#!/usr/bin/env python3
"""
V11 NATIVE RULES — vm-trendgate in its NATIVE published form.

The improvement under test is the portfolio trend gate. Its native
published form is Faber (2007), "A Quantitative Approach to Tactical
Asset Allocation": a MONTHLY timing rule — at each month-end, hold the
risky asset only if its price is above its 10-month simple moving
average; otherwise hold cash/T-bills. The gate is checked monthly; the
underlying portfolio is NOT re-picked or rebalanced at gate checks.

House adaptation being replaced (v4/v5/v9/v10): the gate was evaluated
only at the champion's QUARTERLY re-pick dates, using SPY vs its
200-trading-day MA, so the pot could sit invested through months of a
downtrend between quarterly checks.

THIS RUN (frozen in NATIVE-SPEC.md before the run):
- Underlying sleeve: the champion value+momentum pot exactly as in the
  prior program (30-name pond, EDGAR point-in-time book-to-market +
  12-1 momentum, average of percentile ranks, top-5 equal weight,
  re-picked QUARTERLY — the champion's own cadence, unchanged).
- Gate: Faber native — evaluated at the first trading day of every
  month on SPY month-end closes strictly before that date: ON iff the
  latest month-end close >= the mean of the last 10 month-end closes.
  Gate OFF -> liquidate at the next open, cash until a monthly check
  turns ON. Gate ON at a non-quarterly month -> if in cash, re-enter
  the currently adopted picks at equal weight; if already invested, NO
  trade (Faber does not rebalance the underlying). Quarterly dates
  adopt new picks and rebalance if the gate is ON.
- Costs: program standard 0.10%/side + $0.01 per sell order.
- Protections: program v9 chassis (plain -15% floor per episode;
  first halt -> liquidate at next open, 90 calendar days cash, restart
  at the next monthly decision date under an episode-2 -15% floor;
  second halt ends the run). NOTE: the floor is house protection, not
  part of Faber's published form — stated in the spec.
- Placebos: 20 seeds; at each quarterly adoption the placebo adopts a
  random 5 from the scored pool (same scores, same gate, same chassis).
- Baseline: the same runner with the gate forced ON (= the champion on
  this plumbing) for an apples-to-apples gate contribution read.
- Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
  VAL 2023-01-03->2026-11-20, LONG 2010-01-04->2026-11-20.

Data (read-only): full-history Yahoo payloads in
backtests/v7/long-hold/data and backtests/long-run-2010/data; EDGAR
companyfacts from backtests/v4/data — via the v10 module's own
build_inputs_full / precompute_decisions / cadence_dates, imported
read-only. Simulation only. Writes ONLY inside this folder.
"""
import importlib.util
import json
import os
import random
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V10_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/vm-trendgate/vm-trendgate-v10.py")
spec = importlib.util.spec_from_file_location("tg_v10", V10_PATH)
TG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TG)
E = TG.E
UNIVERSE = TG.UNIVERSE

ROADS = {
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT": ("2019-01-02", "2026-11-20"),
    "VAL": ("2023-01-03", "2026-11-20"),
    "LONG": ("2010-01-04", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))


def faber_gate(pb, sel_date):
    """Faber (2007) native gate: month-end SPY closes strictly before
    sel_date; ON iff latest month-end close >= mean of last 10."""
    bars = pb.bars["SPY"]
    month_end = {}
    for b in bars:
        if b["d"] < sel_date:
            month_end[b["d"][:7]] = b["c"]  # bars sorted; last wins
    months = sorted(month_end)
    if len(months) < 10:
        return None
    last10 = [month_end[m] for m in months[-10:]]
    return {"signal_month": months[-1], "close": round(last10[-1], 2),
            "sma10": round(sum(last10) / 10.0, 2),
            "gate_on": bool(last10[-1] >= sum(last10) / 10.0)}


def run_pot(pb, decisions, monthly_dates, quarterly_set, start, end,
            start_cash, floor0, placebo_rng=None, gate_mode="faber"):
    """decisions: monthly date -> {scores, picks(ranked), faber gate}.
    Picks are ADOPTED only on quarterly dates; monthly dates only move
    the pot in/out per the gate."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    gate_log = []
    adopted = None
    invested = False
    dec_dates = set(monthly_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # None = no action; {} = go cash; {t:val} = targets

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
            invested = bool(positions)
            pending = None
        if d in dec_dates:
            dec = decisions[d]
            scores = dec["scores"]
            is_q = d in quarterly_set
            if is_q and len(scores) >= 5:
                if placebo_rng is not None:
                    adopted = placebo_rng.sample(sorted(scores), 5)
                else:
                    adopted = list(dec["picks"])
            g = dec["gate"]
            gate_on = True if gate_mode == "off" else (
                g["gate_on"] if g is not None else True)
            gate_log.append({"date": d, "quarterly": is_q,
                             "signal_month": g["signal_month"] if g else None,
                             "spy_close": g["close"] if g else None,
                             "sma10": g["sma10"] if g else None,
                             "gate_on": gate_on,
                             "adopted": list(adopted) if adopted else None})
            if adopted:
                if not gate_on:
                    if invested or positions:
                        pending = {}
                else:
                    if is_q or not invested:
                        pv = portfolio_close(d)
                        each = pv / 5.0
                        pending = {t: each for t in adopted}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
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
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "gate_log": gate_log}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "gate_log": gate_log}


def run_v9(pb, decisions, monthly_dates, quarterly_set, start, end,
           placebo_seed=None, gate_mode="faber"):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    floor1 = round(0.85 * 100.0, 2)
    r1 = run_pot(pb, decisions, monthly_dates, quarterly_set, start, end,
                 100.0, floor1, placebo_rng=rng, gate_mode=gate_mode)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halted": r1["halted"], "restarts": [], "second_halt": None,
           "episodes": 1, "gate_log": list(r1["gate_log"])}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in monthly_dates:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    rng2 = random.Random(placebo_seed) if placebo_seed is not None else None
    r2 = run_pot(pb, decisions, monthly_dates, quarterly_set, restart, end,
                 cash, floor2, placebo_rng=rng2, gate_mode=gate_mode)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    out["gate_log"] += list(r2["gate_log"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def main():
    pb, equity_rows, shares_rows = TG.build_inputs_full()
    fb = TG.FastBook(pb)
    results = {"slug": "vm-trendgate", "form": "Faber (2007) native monthly "
               "10-month SMA gate over the champion V+M sleeve (quarterly "
               "re-pick unchanged)", "roads": {}}
    for road, (start, end) in ROADS.items():
        monthly = TG.cadence_dates(pb, "monthly", start, end)
        quarterly = E.quarter_selection_dates(pb, start, end)
        qset = set(quarterly)
        # decisions on the union (monthly dates carry scores for placebo
        # pool reference; picks adopted only on quarterly dates)
        dec = TG.precompute_decisions(fb, equity_rows, shares_rows, monthly)
        for d in monthly:
            dec[d]["gate"] = faber_gate(pb, d)
        gated = run_v9(pb, dec, monthly, qset, start, end)
        base = run_v9(pb, dec, monthly, qset, start, end, gate_mode="off")
        pfinals = []
        for s in PLACEBO_SEEDS:
            pr = run_v9(pb, dec, monthly, qset, start, end, placebo_seed=s)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if gated["final"] > f)
        mdd, mdd_d = TG.max_dd(gated["curve"])
        bmdd, _ = TG.max_dd(base["curve"])
        results["roads"][road] = {
            "window": [start, end],
            "gated_final": round(gated["final"], 2),
            "gated_cagr_pct": TG.cagr_pct(gated["final"], start, end),
            "gated_max_dd_pct": mdd, "gated_max_dd_date": mdd_d,
            "gated_costs": round(gated["costs"], 2),
            "gated_orders": gated["orders"],
            "gated_halted": gated["halted"],
            "gated_second_halt": gated["second_halt"],
            "ungated_baseline_final": round(base["final"], 2),
            "ungated_max_dd_pct": bmdd,
            "placebo_beaten": beaten, "placebo_finals": pfinals,
            "gate_months_off": sum(1 for g in gated["gate_log"]
                                   if not g["gate_on"]),
            "gate_checks": len(gated["gate_log"]),
            "curve": [[d, round(v, 4)] for d, v in gated["curve"]],
            "gate_log": gated["gate_log"],
        }
        print(road, "gated", round(gated["final"], 2), "base",
              round(base["final"], 2), "placebo", beaten, "/20",
              "maxdd", mdd, flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
