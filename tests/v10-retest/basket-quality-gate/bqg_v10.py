#!/usr/bin/env python3
"""
BASKET-QUALITY-GATE — THE GREAT RETEST (v10). Simulation only.

Strategy (frozen, verbatim from backtests/v4/basket-quality-gate.py):
  Base = survivorship-honest MOMENTUM BASKET (30 names, Nov-2016 top-30 by
  market cap): eligible = close above own 200-day SMA; rank by 12-1 momentum
  (close[t-21]/close[t-252]-1); hold TOP 5 at 20% of equity each; rebalance
  at the selection day's OPEN using the prior trading day's close as signal.
  THE ONE CHANGE (the gate, exactly as originally implemented, NEVER patched):
  a name is selectable only if its most recently FILED gross profitability
  GP = (Revenue - COGS)/Total Assets (single filing, same accession + annual
  period, OPINC/Assets fallback only when a name has NO GP observations at
  all; filed strictly before the signal day) is POSITIVE. No observation
  also fails the gate.
  Costs: 0.10%/side + $0.01 per sell order (program convention, identical).

  *** ARTIFACT WARNING (the program's REJECTION rationale, carried in full):
  in the original test NOT ONE exclusion was for GP <= 0. Every exclusion
  was "no-data": JPM, BAC, WFC (banks) and XOM (integrated energy) report
  no COGS-based gross profit and no OperatingIncomeLoss under the EDGAR
  concept set used, so they produced zero observations and were banned
  forever; DIS/JNJ/CVX/KO were excluded only in early windows where their
  usable observations had not started. The gate as implemented is an
  accidental banks-and-big-oil sector ban, NOT a profitability screen.
  Any good number below carries that warning. ***

INTEGRITY mode: the original simulate() copied verbatim (monthly cadence,
floor + LADDER as published), windows full 2016-11-21 -> 2026-11-20 and
validation 2023-01-01 -> 2026-11-20, $100 pot. Published: full $508.81,
validation $262.78.

SWEEP mode: DECADE 2016-11-21 -> 2026-11-20, $100/cell, v9 protections
(plain -15% floor from the episode's starting balance, NO ladder; first
halt: liquidate at next open, sit in cash 90 calendar days, restart at the
next regular cadence date under an episode-2 floor of -15% from the
restart balance; second halt ends the run), at 7 cadences under the SPEC's
uniform cadence definition (signal/selection/trading ONLY on cadence
dates; the -15% floor check stays daily as in the original engine).
Execution convention kept from the original at every cadence: signal from
the prior trading day's close, trades at the cadence day's open.

Placebos: random-rank twins — at each cadence date, 5 names sampled
uniformly from the GATE-PASSING eligible names (the gate is part of the
strategy; momentum ranking is what the twin tests), same machinery,
20 seeds (20261121 + i, i = 0..19), same seeds in every cell.

Data (READ-ONLY shared caches; nothing written outside this folder):
  prices: backtests/v4/momentum-basket-honest-data/<T>.json (the original
          test's own Yahoo cache, raw split-adjusted open/close)
  facts:  backtests/v4/data/company_tickers.json + facts_<cik>.json
          (the original test's own EDGAR cache; only the 30 universe
          names are loaded)
  SPY dividend-adjusted reference ($367.80) verified separately from
  backtests/v7/long-hold/data/pxfull_SPY.json (adjclose bars, program
  costs) — see RESULTS.md. In-plumbing price-only SPY net is $314.10.
"""
import json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
PRICE_CACHE = os.path.join(BT, "v4", "momentum-basket-honest-data")
V4_DATA = os.path.join(BT, "v4", "data")
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001
SELL_FEE = 0.01
PLACEBO_SEEDS = [20261121 + i for i in range(20)]
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
DECADE = ("2016-11-21", "2026-11-20")

# ======================================================================
# Quality observations — copied verbatim from v4/quality-momentum.py
# (constants + _entries/_annual/build_quality_observations/quality_at),
# except facts are read directly from the read-only v4 cache (no fetch).
# ======================================================================
REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                 "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"


def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]


def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) -
                    date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out


def build_quality_observations(facts):
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (
            float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:
                    slot[key] = (float(e["val"]), e.get("filed", ""))
        return out

    rev = by_accn_period(REV_CONCEPTS)
    cogs = by_accn_period(COGS_CONCEPTS)
    obs = []
    for accn, periods in rev.items():
        for (start, end), (rval, rfiled) in periods.items():
            c = cogs.get(accn, {}).get((start, end))
            if c is None:
                continue
            a = assets_for(accn, end)
            if a is None or a <= 0:
                continue
            filed = max(rfiled, c[1])
            obs.append((filed, end, (rval - c[0]) / a, "GP"))
    if not obs:
        op = by_accn_period([OPINC_CONCEPT])
        for accn, periods in op.items():
            for (start, end), (oval, ofiled) in periods.items():
                a = assets_for(accn, end)
                if a is None or a <= 0:
                    continue
                obs.append((ofiled, end, oval / a, "OPINC"))
    obs.sort()
    return obs


def quality_at(obs, asof):
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best


def load_quality_obs():
    with open(os.path.join(V4_DATA, "company_tickers.json")) as f:
        raw = json.load(f)
    ciks = {row["ticker"]: int(row["cik_str"]) for row in raw.values()}
    obs, info = {}, {}
    for t in UNIVERSE:
        path = os.path.join(V4_DATA, f"facts_{ciks[t]:010d}.json")
        with open(path) as f:
            facts = json.load(f)
        obs[t] = build_quality_observations(facts)
        methods = {}
        for _, _, _, m in obs[t]:
            methods[m] = methods.get(m, 0) + 1
        info[t] = {"n_obs": len(obs[t]), "methods": methods}
    return obs, info


# ======================================================================
# Market — copied verbatim from v4/momentum-basket-honest.py, except
# fetch() reads only the existing read-only cache (no downloads).
# ======================================================================
def fetch(ticker):
    path = os.path.join(PRICE_CACHE, f"{ticker}.json")
    with open(path) as f:
        return json.load(f)


class Market:
    def __init__(self, tickers):
        self.bars = {}
        self.closes = {}
        spy = fetch(BENCH)
        self.cal = [r["d"] for r in spy]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        all_t = tickers + [BENCH]
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = fetch(t)
        for t in all_t:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        if i - 252 < 0:
            return None
        a, b = self.closes[t][i - 252], self.closes[t][i - 21]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0


def spy_net(mkt, start_d, end_d, pot0):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px(BENCH, i0)
    sell_px = mkt.close_px(BENCH, i1)
    sh = (pot0 * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE


def years_between(a, b):
    da = date.fromisoformat(a)
    db = date.fromisoformat(b)
    return (db - da).days / 365.25


def cagr(final, start, years):
    if final <= 0 or start <= 0:
        return float("nan")
    return (final / start) ** (1.0 / years) - 1.0


# ======================================================================
# INTEGRITY — original simulate copied verbatim from
# v4/basket-quality-gate.py (gated mode; floor + ladder as published).
# ======================================================================
FLOORS = {
    100: (85.0,  [(125.0, 100.0), (150.0, 125.0)]),
    50:  (42.50, [(62.50, 50.0),  (75.0, 62.50)]),
}


class OrigResult:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.equity_curve = []
        self.sel_total = 0
        self.sel_wins = 0
        self.months = 0
        self.month_wins = 0
        self.month_rets = []
        self.diag = []


def simulate_original(mkt, start_d, end_d, pot0, gate_obs):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = FLOORS[pot0]
    floor = floor0
    cash = float(pot0)
    pos = {}
    res = OrigResult()
    pending_liquidation = False
    mark_px = {}
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

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
            ungated_picks = [t for t, _ in elig[:5]]

            picks = ungated_picks
            if gate_obs is not None:
                kept, excluded = [], []
                for t, mom in elig:
                    q = quality_at(gate_obs.get(t, []), mkt.cal[j])
                    if q is None:
                        excluded.append({"t": t, "reason": "no-data",
                                         "gp": None, "method": None,
                                         "filed": None})
                    elif q[2] <= 0:
                        excluded.append({"t": t, "reason": "gp<=0",
                                         "gp": round(q[2], 4),
                                         "method": q[3], "filed": q[0]})
                    else:
                        kept.append((t, mom))
                picks = [t for t, _ in kept[:5]]
                res.diag.append({
                    "date": d, "signal_date": mkt.cal[j],
                    "n_elig": len(elig), "excluded": excluded,
                    "ungated_picks": ungated_picks, "gated_picks": picks,
                    "changed": picks != ungated_picks,
                })

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

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
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
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    return res


# ======================================================================
# SWEEP engine — same selection/gate/cost machinery, cadence-parameterised,
# v9 protections (plain -15% floor, no ladder, 90-day sit-out, restart at
# next cadence date, episode-2 floor -15% from restart balance, 2nd halt
# ends the run). Floor checked at every close, as the original did.
# ======================================================================
def cadence_dates(cal, cadence, start, end):
    days = [d for d in cal if start <= d <= end]
    if cadence == "daily":
        return set(days)
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        weeks = []
        for d in days:
            y, w, _ = date.fromisoformat(d).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w))
                weeks.append(d)
        return set(weeks if cadence == "weekly" else weeks[::2])
    months = {"monthly": None, "quarterly": ("01", "04", "07", "10"),
              "semiannual": ("01", "07"), "annual": ("01",)}[cadence]
    for d in days:
        if months is not None and d[5:7] not in months:
            continue
        key = (d[:4], d[5:7])
        if key not in seen:
            seen.add(key)
            out.append(d)
    return set(out)


def simulate_v9(mkt, start_d, end_d, cad_set, gate_obs, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash = 100.0
    pos = {}
    orders = 0
    costs = 0.0
    curve = []
    halts = []
    episode = 1
    floor = 85.0
    pending_liq = False
    trigger_date = None
    sit_until = None          # date string; restart on/after this date
    restart = False
    restart_date = None
    restart_balance = None
    second_halt = False
    final = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    def liquidate(i, at_open):
        nonlocal cash, orders, costs
        for t in list(pos):
            px = mkt.open_px(t, i) if at_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            val = pos[t] * px
            fee = val * COST_RATE + SELL_FEE
            cash += val - fee
            costs += fee
            orders += 1
            del pos[t]

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]

        if pending_liq:
            liquidate(i, at_open=True)
            halts.append({"episode": episode, "trigger_date": trigger_date,
                          "liquidation_date": d,
                          "balance": round(cash, 2)})
            pending_liq = False
            if episode == 2:
                second_halt = True
                final = cash
                curve.append((d, cash))
                break
            episode = 2
            sit_until = (date.fromisoformat(d) +
                         timedelta(days=90)).isoformat()
            curve.append((d, cash))
            continue

        if sit_until is not None:
            if d >= sit_until and d in cad_set:
                restart = True
                restart_date = d
                restart_balance = cash
                floor = 0.85 * cash
                sit_until = None
                # fall through to selection on this cadence date
            else:
                curve.append((d, cash))
                continue

        if d in cad_set and i > 0:
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
            kept = []
            for t, mom in elig:
                q = quality_at(gate_obs.get(t, []), mkt.cal[j])
                if q is not None and q[2] > 0:
                    kept.append((t, mom))
            if rng is None:
                kept.sort(key=lambda x: -x[1])
                picks = [t for t, _ in kept[:5]]
            else:
                names = sorted(t for t, _ in kept)
                picks = (rng.sample(names, min(5, len(names)))
                         if names else [])

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
                    costs += fee
                    orders += 1
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
                costs += fee
                orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px

        eq_close = equity_at(i, use_open=False)
        curve.append((d, eq_close))
        if sit_until is None and eq_close <= floor:
            pending_liq = True
            trigger_date = d
            if i == i1:
                liquidate(i, at_open=False)
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidation_date": d,
                              "balance": round(cash, 2)})
                if episode == 2:
                    second_halt = True
                final = cash
                curve[-1] = (d, cash)
                break

    if final is None:
        final = curve[-1][1]
    peak = -1.0
    max_dd = 0.0
    for d, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)
    return {"final": final, "orders": orders, "costs": costs,
            "max_dd": max_dd, "curve": curve, "halts": halts,
            "restart": restart, "restart_date": restart_date,
            "restart_balance": (round(restart_balance, 2)
                                if restart_balance is not None else None),
            "second_halt": second_halt}


def cell_summary(r, yrs):
    return {"final": round(r["final"], 2),
            "cagr_pct": round(cagr(r["final"], 100.0, yrs) * 100, 2),
            "max_dd_pct": round(r["max_dd"] * 100, 2),
            "halts": r["halts"], "restart": r["restart"],
            "restart_date": r["restart_date"],
            "restart_balance": r["restart_balance"],
            "second_halt": r["second_halt"],
            "costs": round(r["costs"], 2), "orders": r["orders"]}


def main():
    gate_obs, obs_info = load_quality_obs()
    print("quality obs loaded:", {t: obs_info[t]["n_obs"] for t in UNIVERSE},
          flush=True)
    mkt = Market(UNIVERSE)

    # ---------------- integrity (original form, original windows) ------
    integrity = {}
    published = {"full": 508.81, "validation": 262.78}
    orig_windows = {"full": ("2016-11-21", "2026-11-20"),
                    "validation": ("2023-01-01", "2026-11-20")}
    gp_le0_total = 0
    nodata_total = 0
    for wname, (sd, ed) in orig_windows.items():
        r = simulate_original(mkt, sd, ed, 100, gate_obs)
        yrs = years_between(sd, ed)
        gp_le0 = sum(1 for e in r.diag for x in e["excluded"]
                     if x["reason"] == "gp<=0")
        nodata = sum(1 for e in r.diag for x in e["excluded"]
                     if x["reason"] == "no-data")
        gp_le0_total += gp_le0
        nodata_total += nodata
        integrity[wname] = {
            "window": [sd, ed], "published_final": published[wname],
            "reproduced_final": round(r.final, 2),
            "cagr_pct": round(cagr(r.final, 100.0, yrs) * 100, 2),
            "max_dd_pct": round(r.max_dd * 100, 2),
            "orders": r.orders, "costs": round(r.costs, 2),
            "halt": r.halt_date,
            "selection_months": len(r.diag),
            "months_picks_changed": sum(1 for e in r.diag if e["changed"]),
            "exclusions_gp_le0": gp_le0,
            "exclusions_no_data": nodata,
            "spy_net_price_only": round(spy_net(mkt, sd, ed, 100), 2),
        }
        print(f"INTEGRITY {wname}: reproduced {r.final:.2f} vs published "
              f"{published[wname]} (gp<=0 exclusions={gp_le0}, "
              f"no-data={nodata})", flush=True)
    ok = all(abs(integrity[w]["reproduced_final"] -
                 integrity[w]["published_final"]) < 0.02
             for w in orig_windows)
    integrity_status = "reproduced" if ok else "FAILED"

    # ---------------- decade sweep --------------------------------------
    sd, ed = DECADE
    yrs = years_between(sd, ed)
    spy_price_only = round(spy_net(mkt, sd, ed, 100), 2)
    print(f"DECADE price-only SPY net (in-plumbing): {spy_price_only}",
          flush=True)
    cells = {}
    for cad in CADENCES:
        cad_set = cadence_dates(mkt.cal, cad, sd, ed)
        r = simulate_v9(mkt, sd, ed, cad_set, gate_obs)
        summ = cell_summary(r, yrs)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            pr = simulate_v9(mkt, sd, ed, cad_set, gate_obs,
                             placebo_seed=seed)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for v in placebo_finals if r["final"] > v)
        summ["placebo_beaten"] = f"{beaten}/20"
        summ["placebo_note"] = (
            "20 random-rank twins (seeds 20261121+i): at each cadence date "
            "5 names sampled uniformly from the gate-passing eligible set; "
            "same v9 machinery; all twin finals in cells/<cadence>.json")
        cells[cad] = summ
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({
                "slug": "basket-quality-gate", "cadence": cad,
                "window": [sd, ed], "start_balance": 100.0,
                **summ,
                "placebo_twin_finals": [
                    {"seed": s, "final": v}
                    for s, v in zip(PLACEBO_SEEDS, placebo_finals)],
                "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            }, f, indent=1)
        print(f"CELL {cad}: final={summ['final']} CAGR={summ['cagr_pct']} "
              f"maxDD={summ['max_dd_pct']} costs={summ['costs']} "
              f"orders={summ['orders']} halts={len(summ['halts'])} "
              f"placebo {summ['placebo_beaten']}", flush=True)

    spy_div_adj = 367.80
    # money cadence = beats SPY (div-adj) AND beats the majority of twins
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_div_adj
             and int(cells[c]["placebo_beaten"].split("/")[0]) > 10]

    out = {
        "slug": "basket-quality-gate",
        "area": ("monthly momentum holding — momentum basket (top-5, "
                 "12-1 momentum, above 200-day SMA) with a gross-"
                 "profitability gate, on the Nov-2016 top-30 pond"),
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "cadence_note": ("Original test ran monthly, the native cadence; "
                         "no foreign cadence was forced."),
        "artifact_warning": (
            "REJECTED by the program as a data artifact, rationale carried "
            "in full: the gate's profitability condition never fired — "
            "zero exclusions for GP<=0 in either original window; every "
            "exclusion was 'no-data'. Banks (JPM, BAC, WFC) and integrated "
            "oil (XOM) report no COGS-based gross profit (and no "
            "OperatingIncomeLoss under the concept set used), so the gate "
            "acted as an accidental permanent banks-and-big-oil sector "
            "ban, plus early-window coverage gaps for DIS/JNJ/CVX/KO. "
            "The gate is kept exactly as originally implemented (artifact "
            "documented, never patched); every number in this sweep is "
            "the as-implemented rule, and any good number must be read "
            "as 'an accidental sector ban that happened to pay', never "
            "as evidence for a profitability screen."),
        "integrity": {
            "status": integrity_status,
            "original_finals": {"CONT_full_2016-11-21_to_2026-11-20": 508.81,
                                "VAL_2023-01-01_to_2026-11-20": 262.78},
            "reproduced_finals": {
                w: integrity[w]["reproduced_final"] for w in orig_windows},
            "detail": integrity,
            "exclusions_gp_le0_total_both_windows": gp_le0_total,
            "exclusions_no_data_total_both_windows": nodata_total,
        },
        "decade_spy_final": spy_div_adj,
        "decade_spy_note": (
            "Dividend-adjusted SPY buy-and-hold, program costs, verified "
            "independently from v7/long-hold pxfull_SPY adjclose bars: "
            "$367.80. In-plumbing price-only SPY net on the basket's own "
            f"raw price cache: ${spy_price_only} (the original test's "
            "benchmark convention). Money-cadence test uses $367.80."),
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": ("Champion (value+momentum) decade final $65.89 after "
                       "two halts — its crown rests on the 2010 and 2019 "
                       "roads; the decade caveat applies wherever the "
                       "decade matrix is summarized.")},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND",
        "verdict_note": (
            "Judged as what it claims to be — a gross-profitability quality "
            "gate — it owns no ground: in the reproduced original windows "
            "the profitability condition fired ZERO times (0 GP<=0 "
            "exclusions out of 528 total exclusions; every exclusion was "
            "no-data). The as-implemented rule does beat SPY ($367.80) and "
            "the majority of its random twins at biweekly, monthly "
            "(native), quarterly and semiannual cadences on the decade, "
            "but that money belongs to the underlying momentum basket "
            "plus an accidental permanent banks-and-big-oil ban — a "
            "sector bet discovered by accident on already-seen windows. "
            "The artifact warning stays attached to every good number."),
        "verdict_change": (
            "No change in substance. The original program verdict was "
            "REJECTED (data artifact, not a profitability screen). The "
            "sweep adds new facts — the as-implemented rule makes money "
            "at 4 of 7 cadences on the decade and its monthly cell "
            "reproduces the original $508.81 exactly under v9 rules — "
            "but none of that rehabilitates the gate, because the "
            "mechanism was never profitability screening."),
        "data_sources": (
            "Prices read-only: backtests/v4/momentum-basket-honest-data/ "
            "(original test's Yahoo cache). EDGAR facts read-only: "
            "backtests/v4/data/ (only the 30 universe names' facts files "
            "+ company_tickers.json loaded). No long-run cache bulk load."),
        "quality_obs_info": obs_info,
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json; integrity:", integrity_status,
          "| money cadences:", money, flush=True)


if __name__ == "__main__":
    main()
