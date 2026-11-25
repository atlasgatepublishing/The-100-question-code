#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — LOW-VOLATILITY CADENCE SWEEP.

Strategy: hold the 5 lowest trailing-volatility pond names (trailing
252 daily simple returns of split/dividend-adjusted closes, sample
stdev, ending on the selection day), equal weight, from the champion
engine's honest point-in-time top-30 pool (EDGAR pool gate identical
to backtests/v6/low-volatility). Native cadence per the SPEC CADENCE
GRID: MONTHLY. The original program test used QUARTERLY (foreign).

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell, program costs
(0.10%/side + $0.01 per sell order), adopted v9 protections (plain
-15% floor; first halt -> liquidate at next open, 90 calendar days in
cash, restart at the next regular cadence date under an episode-2
floor of -15% from the restart balance; second halt ends the run).

CADENCE (SPEC uniform definition): signal evaluation, selection and
trading ONLY on cadence dates — daily = every trading day; weekly =
first trading day of each ISO week; biweekly = first trading day of
every second ISO week (absolute anchor: the Monday of the week
containing the window start is week 0); monthly = first trading day
of each month; quarterly = first trading day of each calendar
quarter; semiannual = first trading day of each half-year; annual =
first trading day of each year. Rebalance executes at the NEXT
trading day's open (original engine mechanics).

DATA: Yahoo Finance chart API prices 2015-01-01 -> 2026-11-21
(split/dividend-adjusted, same fetch/parse method as the original
engine), downloaded once and cached in this folder's data/ (the
original caches start 2017-06-01, too late for a 2016 road with a
252-day vol lookback). EDGAR companyfacts are read read-only through
the original engine's own loaders (shared caches, never written).
Only the data this strategy needs is loaded: 30 pond names + SPY
price payloads and the pond's EDGAR equity/shares fact series. The
1.7GB long-run cache is NOT touched.

ENGINE EQUIVALENCE: mechanics copied from the v6/v9 low-volatility
engine (pool gate, vol ranking, sell-then-buy rebalance at next open,
cost schedule, halt liquidation at next open, end-of-window
liquidation at final close, daily close curve). Speed changes only:
bisect-based close_on_or_before and per-date pool/vol scores
precomputed once and shared by the ranked run and all placebo twins
(placebo picks depend only on the pool set and the rng, exactly as in
the original). crosscheck.py verifies this engine against the
original engine on the CONT window.

PLACEBOS: 20 seeds per cell; each twin draws 5 random names from the
identical pool on identical cadence dates with identical mechanics
and identical v9 protections (random.Random(seed), seeds 1..20, as
in the original study).

DEFENSE SCORING (this family's claim): per cell, max drawdown vs
SPY's decade max drawdown, and calendar-2020 / calendar-2022 returns
(strategy equity curve vs SPY buy-and-hold curve, last-close to
last-close) are reported alongside the final balance.
"""
import bisect
import calendar
import importlib.util
import json
import math
import os
import random
import statistics
import time
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
V4_ENGINE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

spec = importlib.util.spec_from_file_location("vm_plainfloor", V4_ENGINE)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))


# ------------------------------------------------------------- data loading
def get_prices_wide(ticker, p1="2015-01-01", p2="2026-11-21"):
    """Yahoo chart API, same parse as E.get_prices (adjclose-scaled
    opens, adjusted closes), wider window, cached in this folder."""
    path = os.path.join(DATA, f"px_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        last = None
        for i in range(3):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    blob = r.read()
                with open(path, "wb") as f:
                    f.write(blob)
                break
            except Exception as e:  # noqa
                last = e
                time.sleep(2 * (i + 1))
        else:
            raise RuntimeError(f"fetch failed {ticker}: {last}")
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


def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        del facts
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices_wide(t)
        print(f"  prices {t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    return FastBook(bars), equity_rows, shares_rows


# ------------------------------------------------------------- fast book
class FastBook:
    """Same semantics as E.PriceBook; bisect/index lookups only."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self.tdates = {t: [b["d"] for b in bl]
                       for t, bl in bars_by_ticker.items()}
        self.didx = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self.tdates.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ------------------------------------------------------------- cadences
def _ord(dstr):
    return date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return E.quarter_selection_dates(pb, start, end)
    out, seen = [], set()
    monday0 = None
    if cadence == "biweekly":
        d0 = date(int(days[0][:4]), int(days[0][5:7]), int(days[0][8:10]))
        monday0 = d0.toordinal() - d0.weekday()
    for d in days:
        dt = date(int(d[:4]), int(d[5:7]), int(d[8:10]))
        if cadence == "weekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1])
        elif cadence == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            wk = (monday - monday0) // 7
            if wk % 2 != 0:
                continue
            key = ("bi", wk)
        elif cadence == "monthly":
            key = (d[:4], d[5:7])
        elif cadence == "semiannual":
            key = (d[:4], "H1" if d[5:7] <= "06" else "H2")
        elif cadence == "annual":
            key = (d[:4],)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------------- pool / vol precompute
def compute_scores(pb, equity_rows, shares_rows, d):
    """Pool gate + low-vol scores for one date — byte-equivalent logic
    to the v6/v9 engine's pick block."""
    scores = {}
    for t in UNIVERSE:
        be = E.pit_value(equity_rows.get(t, []), d)
        so = E.pit_value(shares_rows.get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0 \
                or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        didx = pb.didx.get(t, {}).get(d)
        if didx is None or didx < 253:
            continue
        bl = pb.bars[t]
        closes = [bl[i]["c"] for i in range(didx - 252, didx + 1)]
        rets = [closes[i] / closes[i - 1] - 1.0
                for i in range(1, len(closes))]
        scores[t] = statistics.stdev(rets)
    return scores


# ------------------------------------------------------------- the engine
def run_episode(pb, scores_by_date, sel_dates, start, end, start_cash,
                floor0, placebo_rng=None):
    """One episode: identical mechanics to v6 run_pot_lowvol except
    selection dates are the cadence list and scores are precomputed.
    Returns dict with final/costs/trades/halted/halt_info/curve/end."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
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
            scores = scores_by_date.get(d, {})
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sorted(scores, key=lambda t: scores[t])[:5]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
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
                    "halted": d, "end": nd, "halt_info": halt_info,
                    "curve": curve}
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
            "halted": None, "end": last, "halt_info": None, "curve": curve}


def run_v9(pb, scores_by_date, sel_dates, start, end,
           start_cash=START_CASH, placebo_rng=None):
    """Adopted v9 protections, generalized from the v9 module's run_v9
    to an arbitrary cadence-date list (absolute phase preserved: the
    episode-2 run reuses the same full-window cadence list)."""
    floor1 = round(0.85 * start_cash, 2)
    ep1_dates = [d for d in sel_dates if start <= d <= end]
    r1 = run_episode(pb, scores_by_date, ep1_dates, start, end,
                     start_cash, floor1, placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halts": [], "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        return out
    out["halts"].append({"episode": 1,
                         "signal_date": r1["halted"],
                         "signal_close": r1["halt_info"]["signal_close"],
                         "floor_in_effect":
                             r1["halt_info"]["floor_in_effect"],
                         "liquidation_date": r1["end"],
                         "liquidated_final": round(r1["final"], 2)})
    liq = r1["end"]
    cash = r1["final"]
    day90 = _ord(r1["halted"]) + 90
    restart = None
    for cand in sel_dates:
        if start <= cand <= end and _ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"], "liquidation_date": liq,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    ep2_dates = [d for d in sel_dates if restart <= d <= end]
    r2 = run_episode(pb, scores_by_date, ep2_dates, restart, end,
                     cash, floor2, placebo_rng=placebo_rng)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {
            "signal_date": r2["halted"],
            "signal_close": r2["halt_info"]["signal_close"],
            "floor_in_effect": r2["halt_info"]["floor_in_effect"],
            "liquidation_date": r2["end"],
            "final": round(r2["final"], 2)}
        out["halts"].append({"episode": 2, **out["second_halt"]})
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------- statistics
def max_dd(curve):
    peak, mdd, mdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd, mdd_d = dd, d
    return round(mdd * 100, 2), mdd_d


def year_return(curve, year):
    """Last-close to last-close calendar-year return from a curve."""
    prev = None
    last = None
    for d, v in curve:
        if d[:4] == str(year - 1):
            prev = v
        if d[:4] == str(year):
            last = v
    if prev is None or last is None:
        return None
    return round((last / prev - 1.0) * 100, 2)


def spy_curve(pb, start, end, start_cash=START_CASH):
    """SPY buy-and-hold daily close curve (adj prices), bought at the
    first open with the program cost schedule; curve values are
    pre-liquidation (final net final computed separately via spy_net
    on the equivalent E.PriceBook semantics)."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    curve = [(d, sh * pb.close_on_or_before("SPY", d)) for d in days]
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    net_final = val - (val * 0.001 + 0.01)
    return curve, net_final


def main():
    t0 = time.time()
    print("building inputs (wide Yahoo prices + EDGAR facts) ...",
          flush=True)
    pb, equity_rows, shares_rows = build_inputs()
    start, end = DECADE
    days = [d for d in pb.dates if start <= d <= end]
    print(f"decade trading days: {len(days)}", flush=True)

    # precompute pool/vol scores for every decade trading day once
    print("precomputing pool/vol scores ...", flush=True)
    scores_by_date = {}
    for d in days:
        scores_by_date[d] = compute_scores(pb, equity_rows, shares_rows, d)
    pool_sizes = [len(s) for s in scores_by_date.values()]
    print(f"  pool size min={min(pool_sizes)} max={max(pool_sizes)}",
          flush=True)

    scurve, spy_final = spy_curve(pb, start, end)
    spy_dd, spy_dd_date = max_dd(scurve)
    spy_2020 = year_return(scurve, 2020)
    spy_2022 = year_return(scurve, 2022)
    years = (_ord(end) - _ord(start)) / 365.25
    spy_cagr = round(((spy_final / START_CASH) ** (1 / years) - 1) * 100, 2)
    print(f"SPY decade: final=${spy_final:,.2f} CAGR={spy_cagr}% "
          f"maxDD={spy_dd}% ({spy_dd_date}) 2020={spy_2020}% 2022={spy_2022}%",
          flush=True)

    cells = {}
    for cad in CADENCES:
        sel = cadence_dates(pb, cad, start, end)
        r = run_v9(pb, scores_by_date, sel, start, end)
        dd, dd_date = max_dd(r["curve"])
        cagr = round(((r["final"] / START_CASH) ** (1 / years) - 1) * 100, 2) \
            if r["final"] > 0 else None
        # placebos (same cadence, same v9 protections)
        twin_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_v9(pb, scores_by_date, sel, start, end,
                        placebo_rng=rng)
            twin_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in twin_finals if f < r["final"])
        cell = {
            "cadence": cad, "selection_dates": len(sel),
            "final": round(r["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": dd, "max_dd_date": dd_date,
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": r["halts"], "restarts": r["restarts"],
            "second_halt": r["second_halt"],
            "ret_2020_pct": year_return(r["curve"], 2020),
            "ret_2022_pct": year_return(r["curve"], 2022),
            "placebo_twin_finals": twin_finals,
            "placebo_beaten": beaten,
            "placebo_median": round(statistics.median(twin_finals), 2),
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        print(f"{cad:11s} sel={len(sel):4d} final=${r['final']:,.2f} "
              f"CAGR={cagr}% maxDD={dd}% costs=${r['costs']:,.2f} "
              f"orders={r['orders']} halts={len(r['halts'])} "
              f"restart={bool(r['restarts'])} "
              f"placebo {beaten}/20 (median ${cell['placebo_median']:,.2f}) "
              f"2020={cell['ret_2020_pct']}% 2022={cell['ret_2022_pct']}% "
              f"[{time.time()-t0:.0f}s]", flush=True)

    summary = {
        "window": {"start": start, "end": end, "trading_days": len(days)},
        "spy": {"final": round(spy_final, 2), "cagr_pct": spy_cagr,
                "max_dd_pct": spy_dd, "max_dd_date": spy_dd_date,
                "ret_2020_pct": spy_2020, "ret_2022_pct": spy_2022,
                "equity_curve": [[d, round(v, 4)] for d, v in scurve]},
        "cells": {cad: {k: v for k, v in cell.items()
                        if k != "equity_curve"}
                  for cad, cell in cells.items()},
    }
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(f"DONE SWEEP in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
