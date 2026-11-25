#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — CADENCE SWEEP — value-momentum-ey.
Simulation only.

Strategy: Value + Momentum, earnings-yield variant (v4 value-momentum-ey.py).
Quarterly-native top-5 pond strategy: value = trailing point-in-time annual
NetIncomeLoss / market cap (earnings yield; negative earnings rank at the
bottom of the value percentile, never excluded), momentum = 12-1 trailing
return; combined score = average of the two percentile ranks; hold top 5,
equal weight. This sweep re-runs it on the DECADE road
2016-11-21 -> 2026-11-20 at all seven cadences under the SPEC's uniform
cadence definition: signal evaluation, selection and trading happen ONLY
on cadence dates (rebalance executes at the next trading day's open,
exactly as the original engine's pending mechanism). The v9 protection
(plain -15% floor checked on EVERY close — protection is not the signal,
and the SPEC keeps v9 protections unchanged per cell; 90-calendar-day
cash sit-out after a first halt; restart at the next regular cadence
decision point on/after eligibility under an episode-2 floor of -15%
from the restart balance; second halt ends the run) wraps every cell.

Mechanics (selection, scoring, execution, costs) are the original v4
engine's, verbatim where it counts:
  - PIT EDGAR only: facts FILED strictly before the selection date,
    ~18-month filed-freshness gate (max_age_days=548), XOM CIK override
    34088, shares fallback chain dei(3) > CommonStockSharesOutstanding(2)
    > WeightedAverageNumberOfSharesOutstandingBasic(1); income chain
    NetIncomeLoss(2) merged with ProfitLoss(1), fiscal-year facts only
    (period 300-400 days).
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Placebo: 20 seeds (1..20) per cell; at each selection date the twin
    draws rng.sample(sorted(scored pool), 5) — the original chassis's
    random-rank design.

Data (read-only shared caches + one own-folder download):
  - EDGAR companyfacts: backtests/v4/data/facts_*.json (the original
    test's cache).
  - Prices: Yahoo full-range payloads (2008 -> 2026-11-22) from
    backtests/v7/long-hold/data/pxfull_*.json — the same Yahoo chart
    method and the same adjclose bar construction as the original
    engine's get_prices; GOOGL had no pxfull payload in that cache, so
    it was pulled fresh from Yahoo into THIS folder's data/ (documented
    in RESULTS.md).
  - pit_value is evaluated through a bisect fast path proven identical
    to the original function on a sampled grid at startup (asserted).
"""
import bisect
import json
import math
import os
import random
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V4_DATA = os.path.join(BT, "v4", "data")                       # read-only
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")          # read-only
MY_DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------ data loading
def load_facts(cik):
    import gzip
    path = os.path.join(V4_DATA, f"facts_{cik:010d}.json")
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return json.loads(blob)


def get_ciks():
    with open(os.path.join(V4_DATA, "company_tickers.json")) as f:
        raw = json.load(f)
    return {row["ticker"]: int(row["cik_str"]) for row in raw.values()}


def yahoo_payload(ticker):
    path = os.path.join(MY_DATA, f"pxfull_{ticker}.json")
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        path = os.path.join(LH_DATA, f"pxfull_{ticker}.json")
    with open(path, "rb") as f:
        return json.loads(f.read())


def bars_adj(payload):
    """Original engine's bar construction: open/close scaled by
    adjclose/close; close = adjclose."""
    res = payload["chart"]["result"][0]
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


class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}
        self._di = {t: {b["d"]: i for i, b in enumerate(bl)}
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ------------------------------------------------- PIT chains (original)
def pit_series(facts, taxonomy, concept, prio=0):
    try:
        units = facts["facts"][taxonomy][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else ("shares" if "shares" in units
                                        else list(units)[0])
    rows = []
    for e in units[key]:
        if "filed" not in e or "val" not in e:
            continue
        rows.append((e["filed"], e.get("end", ""), float(e["val"]), prio))
    return rows


def pit_series_income(facts):
    """Original: trailing ANNUAL NetIncomeLoss(2) + ProfitLoss(1),
    fiscal-year facts only (period 300-400 days)."""
    rows = []
    for concept, prio in (("NetIncomeLoss", 2), ("ProfitLoss", 1)):
        try:
            units = facts["facts"]["us-gaap"][concept]["units"]
        except KeyError:
            continue
        key = "USD" if "USD" in units else list(units)[0]
        for e in units[key]:
            if "filed" not in e or "val" not in e or "start" not in e \
                    or "end" not in e:
                continue
            sy, sm, sd = int(e["start"][:4]), int(e["start"][5:7]), \
                int(e["start"][8:10])
            ey_, em, ed = int(e["end"][:4]), int(e["end"][5:7]), \
                int(e["end"][8:10])
            dur = date(ey_, em, ed).toordinal() - \
                date(sy, sm, sd).toordinal()
            if 300 <= dur <= 400:
                rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows


def pit_value_slow(rows, asof, max_age_days=548):
    """The original engine's pit_value, verbatim logic."""
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    cutoff_ord = date(ay, am, ad).toordinal() - max_age_days
    best = None
    for filed, end, val, prio in rows:
        if filed < asof:
            fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
            if date(fy, fm, fd).toordinal() < cutoff_ord:
                continue
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, (filed, end, val))
    return best[1] if best else None


class PitChain:
    """Bisect fast path over rows sorted by (filed, prio, end): the last
    row with filed < asof is the max-key eligible row; the freshness gate
    then only needs that row's filed date (largest filed of all). Proven
    identical to pit_value_slow on a sampled grid at startup."""

    def __init__(self, rows):
        # Sort by the original's tie-break key (filed, prio, end); among
        # rows with an identical key the original keeps the FIRST in list
        # order (it only replaces on a strictly greater key), so the sort
        # key ends with -original_index: the last row with filed < asof
        # is then exactly the row the original would return.
        self.rows = [r for _, r in sorted(
            enumerate(rows),
            key=lambda p: (p[1][0], p[1][3], p[1][1], -p[0]))]
        self.fileds = [r[0] for r in self.rows]

    def value(self, asof, max_age_days=548):
        i = bisect.bisect_left(self.fileds, asof) - 1
        if i < 0:
            return None
        filed, end, val, prio = self.rows[i]
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
        if date(fy, fm, fd).toordinal() < \
                date(ay, am, ad).toordinal() - max_age_days:
            return None
        return (filed, end, val)


# ---------------------------------------------------------------- scoring
def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}


class Scorer:
    """Memoized per-date scored pool: {ticker: (ey, mom)} — the original
    engine's selection-day scoring, identical inputs and exclusions."""

    def __init__(self, pb, income_chains, shares_chains):
        self.pb = pb
        self.inc = income_chains
        self.shr = shares_chains
        self.memo = {}

    def scores(self, d):
        if d in self.memo:
            return self.memo[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            ni = self.inc[t].value(d)
            so = self.shr[t].value(d)
            px = pb.close_on_or_before(t, d)
            if ni is None or so is None or px is None or so[2] <= 0 \
                    or ni[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            ey = ni[2] / mcap
            bl = pb.bars.get(t, [])
            didx = pb._di.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (ey, mom)
        self.memo[d] = scores
        return scores


# ---------------------------------------------------------------- cadence
def cadence_dates(days, cadence):
    """Selection dates within the given trading-day list, per the SPEC's
    uniform definitions. Biweekly anchor: the week containing the first
    day of the window is week 0; every second week from there."""
    if cadence == "daily":
        return list(days)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            iso = date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append((key, d))
        return [d for i, (_, d) in enumerate(weeks) if i % 2 == 0]
    if cadence == "monthly":
        keyf = lambda d: (d[:4], d[5:7])  # noqa: E731
    elif cadence == "quarterly":
        keyf = lambda d: (d[:4], (int(d[5:7]) - 1) // 3)  # noqa: E731
    elif cadence == "semiannual":
        keyf = lambda d: (d[:4], (int(d[5:7]) - 1) // 6)  # noqa: E731
    elif cadence == "annual":
        keyf = lambda d: d[:4]  # noqa: E731
    else:
        raise ValueError(cadence)
    for d in days:
        key = keyf(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ----------------------------------------------------------------- engine
def run_one(pb, scorer, start, end, start_cash, floor, cadence,
            placebo_rng=None):
    """One episode under a plain floor — the original run_pot mechanics
    with the selection calendar parameterized by cadence, an equity
    curve recorded, and pools logged. Returns the champion-chassis
    result shape."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    pools = []
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    sel_set = set(cadence_dates(days, cadence))
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
            scores = scorer.scores(d)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    vr = percentile_ranks({t: v[0] for t, v in
                                           scores.items()})
                    mr = percentile_ranks({t: v[1] for t, v in
                                           scores.items()})
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined,
                                   key=lambda t: -combined[t])[:5]
                pools.append((d, sorted(scores), list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
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
            curve.append((nd, cash))
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if curve and curve[-1][0] == last:
        curve[-1] = (last, cash)
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve}


def run_v9(pb, scorer, cadence, placebo_seed=None):
    """Adopted v9 protection wrapper (lr_common.run_v9 semantics):
    episode 1 plain -15% floor; on first halt, cash 90 calendar days,
    restart at the next regular cadence decision point on/after
    eligibility under an episode-2 floor of -15% from the restart
    balance; second halt ends the run."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    episodes = []
    ep1 = run_one(pb, scorer, START, END, START_CASH, 0.85 * START_CASH,
                  cadence, placebo_rng=rng)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= END:
            ep2 = run_one(pb, scorer, elig, END, ep1["final"],
                          0.85 * ep1["final"], cadence, placebo_rng=rng)
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = ep2["pools"][0][0] if ep2["pools"] else None
                restart = {"halt_date": ep1["halted"],
                           "eligibility": elig,
                           "restart_balance": round(ep1["final"], 2),
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "episode2_first_selection": first_sel}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        trading_days = [d for d in pb.dates if START <= d <= END]
        gap = [d for d in trading_days
               if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1,
                          "signal_date": ep["halted"],
                          "signal_close": ep["halt_info"]["signal_close"]
                          if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "trades": [tr for ep in episodes for tr in ep["trades"]],
            "halts": halts, "restart": restart,
            "second_halt": bool(len(episodes) > 1 and
                                episodes[1]["halted"]),
            "curve": curve}


def curve_stats(curve):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return round(maxdd * 100, 2)


def cagr_pct(final):
    yrs = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
    return round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2)


def spy_net(pb, start, end, start_cash):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# --------------------------------------------------------------------- main
def main():
    t0 = time.time()
    ciks = get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    income_chains, shares_chains = {}, {}
    raw_income, raw_shares = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t])
        facts = load_facts(cik)
        inc = pit_series_income(facts)
        so = (pit_series(facts, "dei",
                         "EntityCommonStockSharesOutstanding", prio=3) +
              pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
              pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        raw_income[t], raw_shares[t] = inc, so
        income_chains[t] = PitChain(inc)
        shares_chains[t] = PitChain(so)
        print(f"{t}: income rows={len(inc)} shares rows={len(so)}",
              flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = bars_adj(yahoo_payload(t))
    pb = PriceBook(bars)
    print(f"price book: {len(pb.dates)} union dates "
          f"{pb.dates[0]}..{pb.dates[-1]}", flush=True)

    # fast-path equivalence check vs the original pit_value
    sample_days = [d for d in pb.dates if START <= d <= END][::37]
    for t in UNIVERSE:
        for d in sample_days:
            assert income_chains[t].value(d) == \
                pit_value_slow(raw_income[t], d), (t, d, "income")
            assert shares_chains[t].value(d) == \
                pit_value_slow(raw_shares[t], d), (t, d, "shares")
    print(f"pit fast path == original pit_value on "
          f"{len(sample_days)} sampled dates x {len(UNIVERSE)} names "
          f"x 2 chains", flush=True)

    spy_final, spy_costs = spy_net(pb, START, END, START_CASH)
    print(f"SPY decade (this plumbing, program cost convention): "
          f"${spy_final:,.2f}", flush=True)

    scorer = Scorer(pb, income_chains, shares_chains)
    summary = {"spy_decade_computed": round(spy_final, 2), "cells": {}}
    for cadence in CADENCES:
        ranked = run_v9(pb, scorer, cadence)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            twin = run_v9(pb, scorer, cadence, placebo_seed=seed)
            placebo_finals.append(round(twin["final"], 2))
        n_beat = sum(1 for v in placebo_finals if ranked["final"] > v)
        sfin = sorted(placebo_finals)
        med = sfin[len(sfin) // 2] if len(sfin) % 2 == 1 else \
            (sfin[len(sfin) // 2 - 1] + sfin[len(sfin) // 2]) / 2.0
        cell = {
            "cadence": cadence,
            "window": {"start": START, "end": END},
            "final": round(ranked["final"], 2),
            "cagr_pct": cagr_pct(ranked["final"]),
            "max_dd_pct": curve_stats(ranked["curve"]),
            "halts": ranked["halts"],
            "restart": ranked["restart"],
            "second_halt": ranked["second_halt"],
            "costs": round(ranked["costs"], 2),
            "orders": ranked["orders"],
            "placebo_beaten": n_beat,
            "placebo_median": round(med, 2),
            "placebo_finals": placebo_finals,
            "trades": [[d, t, side, round(sh, 6), round(px, 4),
                        round(val, 2), round(c, 4)]
                       for (d, t, side, sh, px, val, c) in ranked["trades"]],
            "equity_curve": [[d, round(v, 4)] for d, v in ranked["curve"]],
        }
        with open(os.path.join(CELLS, f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        summary["cells"][cadence] = {
            "final": cell["final"], "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": cell["max_dd_pct"],
            "halts": len(ranked["halts"]),
            "restart": ranked["restart"] is not None,
            "second_halt": ranked["second_halt"],
            "costs": cell["costs"], "orders": cell["orders"],
            "placebo_beaten": n_beat,
            "placebo_median": cell["placebo_median"]}
        print(f"== {cadence}: final=${cell['final']:,.2f} "
              f"cagr={cell['cagr_pct']}% maxdd={cell['max_dd_pct']}% "
              f"costs=${cell['costs']:,.2f} orders={cell['orders']} "
              f"halts={len(ranked['halts'])} placebo beaten "
              f"{n_beat}/20 (median ${cell['placebo_median']:,.2f})",
              flush=True)
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(f"DONE in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
