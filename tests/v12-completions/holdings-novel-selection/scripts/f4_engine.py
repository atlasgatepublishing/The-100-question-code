#!/usr/bin/env python3
"""
V10 GREAT RETEST SWEEP — N-F4 "Cash Already Collected" (novel-f4-cash-collected).

DECADE road 2016-11-21 -> 2026-11-20 at all 7 cadences (SPEC uniform
definition: signal evaluation, selection and trading ONLY on cadence dates;
faster cadences re-evaluate the ranking on the freshest data filed strictly
before that date — the frozen N-F4 scoring itself is unchanged, so between
filings the ranking only moves when a new filing lands).

Mechanics copied verbatim from the original engine (engine_original.py,
the v8 script): targets set at the cadence-date close, executed at the next
open, sells before buys, 0.10%/side + $0.01/share sell charge, end-of-window
liquidation at the final close. Protection = adopted v9 rules: plain -15%
floor from the episode start; on first halt liquidate at next open, sit in
cash 90 calendar days, restart at the next regular cadence date on/after
day 90 under an episode-2 floor of -15% from the restart balance; second
halt ends the run.

Prices: Yahoo chart API payloads downloaded for this run into data/
(the shared v4 cache starts 2017-06-01, after the decade start).
EDGAR companyfacts: shared v4 cache, read-only (the strategy's own channel).
Placebos: 20 seeds per cell, R5 verbatim — same dates, same number of names
drawn uniformly from that date's eligible pool; cash quarters stay cash.
"""
import json, math, os, random, sys, time
from datetime import date as _date

HERE = "/home/hatch/workspace/stock-app/backtests/v10-retest/novel-f4-cash-collected"
sys.path.insert(0, HERE)
import engine_original as eng

START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------ local prices
def get_prices_local(ticker):
    path = os.path.join(HERE, "data", f"px_{ticker}.json")
    with open(path, "rb") as f:
        blob = f.read()
    j = json.loads(blob)
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
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ---------------------------------------------------------- cadence dates
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        weeks = []
        for d in days:
            y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
            key = _date(y, m, dd).isocalendar()[:2]
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        if cadence == "weekly":
            return weeks
        return weeks[::2]
    months = {"monthly": None, "quarterly": ("01", "04", "07", "10"),
              "semiannual": ("01", "07"), "annual": ("01",)}[cadence]
    for d in days:
        if months is not None and d[5:7] not in months:
            continue
        key = (d[:4], d[5:7]) if cadence == "monthly" else \
              (d[:4], d[5:7]) if cadence != "annual" else d[:4]
        if cadence == "quarterly":
            key = (d[:4], d[5:7])
        if cadence == "semiannual":
            key = (d[:4], d[5:7])
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

# ------------------------------------------------- engine (verbatim copy,
# selection dates generalized from quarterly to any cadence list)
def run_pot_c(pb, picks_by_date, sel_dates, start, end, start_cash, floor0,
              placebo_rng=None, label=""):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
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
            entry = picks_by_date.get(d, {"eligible": [], "picks": []})
            eligible = entry["eligible"]
            if placebo_rng is not None:
                k = len(entry["picks"])
                picks = placebo_rng.sample(sorted(eligible), k) if k > 0 else []
            else:
                picks = list(entry["picks"])
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}
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
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve}
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
            "halt_info": None, "curve": curve}

def run_pot_v9c(pb, picks_by_date, sel_dates, start, end, start_cash, label=""):
    """v9 protection, restart at the next cadence date (run_pot_v9 verbatim
    except the restart search runs over this cell's cadence dates)."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_c(pb, picks_by_date, sel_dates, start, end, start_cash,
                   floor1, label=label + " EP1")
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = eng.ord_of(liq_date) + 90
    restart = None
    for cand in sel_dates:
        if eng.ord_of(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_pot_c(pb, picks_by_date, sel_dates, restart, end, cash,
                   floor2, label=label + " EP2")
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def metrics(r, start, end):
    curve = r["curve"]
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (eng.ord_of(end) - eng.ord_of(start)) / 365.25
    cagr = (r["final"] / START_CASH) ** (1.0 / years) - 1.0
    return {"final": round(r["final"], 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"])}


def run_pot_v9c_placebo(pb, picks_by_date, sel_dates, start, end, start_cash, rng):
    """run_pot_v9c with a placebo rng threaded through both episodes
    (one rng stream per pot, champion convention)."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_c(pb, picks_by_date, sel_dates, start, end, start_cash,
                   floor1, placebo_rng=rng)
    out = {"final": r1["final"], "costs": r1["costs"], "trades": r1["trades"],
           "curve": list(r1["curve"]), "halted": r1["halted"],
           "halt_info": r1["halt_info"], "restarts": [],
           "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = eng.ord_of(liq_date) + 90
    restart = None
    for cand in sel_dates:
        if eng.ord_of(cand) >= day90:
            restart = cand
            break
    if restart is None:
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_pot_c(pb, picks_by_date, sel_dates, restart, end, cash,
                   floor2, placebo_rng=rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

