#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — N-F3 "PAYING IN STOCK" cadence sweep.
Simulation only.

Strategy (invented in this program, 2026; v8 novel track, Rule N-F3):
rank the honest top-30 pond (Nov 2016) by ACCEL = SBC_INT(now) -
SBC_INT(same fiscal quarter, one year earlier), where SBC_INT = TTM
share-based compensation / TTM revenue, both built point-in-time from
as-filed EDGAR companyfacts. Rank ascending (decelerating SBC intensity
first), top 5, equal weight. The signal machinery below (concept_rows,
dedupe_asof, dur_class, build_quarters, ttm_pair, signal_at) and the
trade mechanics in run_pot (pending rebalance at next open, costs
0.10%/side + $0.01 per sell order, end-of-day floor check, halt
liquidation at next open) are copied VERBATIM from the original engine
backtests/v8/novel-f3-paying-in-stock/novel-f3-paying-in-stock.py; the
only changes are (a) selection dates are a parameter (the cadence), and
(b) scores are precomputed once per (ticker, selection date) and shared
by the main run and its 20 placebo twins (the twins differ only in
which 5 of the eligible pool they pick — exactly the original placebo
design, which resampled picks from the same scores).

UNIFORM CADENCE TREATMENT (SPEC): the SBC signal updates only as
filings land; at faster cadences the ranking simply re-evaluates on the
freshest filed data. Selection dates per the SPEC's uniform definition:
daily = every trading day; weekly = first trading day of each week;
biweekly = first trading day of every second week (weeks counted from
the first week in the window); monthly = first trading day of each
month; quarterly = first trading day of each calendar quarter;
semi-annual = first trading day of each half-year; annual = first
trading day of each year.

PROTECTIONS: adopted v9 rules via run_v9 (copied verbatim from
backtests/long-run-2010/lr_common.py): plain -15% floor from the
episode's starting balance; on first halt, liquidate at next open, sit
in cash 90 calendar days, restart at the next regular cadence date
under an episode-2 floor of -15% from the restart balance; a second
halt ends the run.

DATA (read-only shared caches; nothing written outside this folder):
- Prices: full-range Yahoo chart payloads via long-run-2010 plumbing
  (lr_common.yahoo_payload / bars_adj — the champion bar construction:
  close = adjclose, open scaled by adjclose/close), so the DECADE road
  2016-11-21 -> 2026-11-20 is fully covered (the v8 cache starts
  2017-06-01 and cannot cover the road's first months).
- Facts: EDGAR companyfacts via lr_common.load_facts (long-hold cache,
  read-only), loaded ONLY for the 30 pond names + nothing else.
Point-in-time discipline is by `filed` date inside signal_at, identical
to the original.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell, 20 placebo seeds
(1..20) per cell.
"""
import json
import math
import os
import random
import sys
from bisect import bisect_left
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402  (data access only: caches + PriceBook)

UNIVERSE = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'BRK-B', 'JPM', 'XOM',
            'JNJ', 'PG', 'V', 'WMT', 'HD', 'BAC', 'CVX', 'PFE', 'VZ', 'T',
            'DIS', 'NFLX', 'INTC', 'CSCO', 'GE', 'IBM', 'MMM', 'UNH', 'MA',
            'KO', 'PEP', 'WFC']
PLACEBO_SEEDS = list(range(1, 21))
START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0

SBC_CONCEPT = "ShareBasedCompensation"
REVENUE_CHAIN = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "Revenues",
                 "RevenuesNetOfInterestExpense",
                 "SalesRevenueNet"]


# --------------------------------------- signal machinery (v8, verbatim)
def dord(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10])).toordinal()


def concept_rows(facts, concept):
    """All USD duration rows for a us-gaap concept (raw, unfiltered)."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else None
    if key is None:
        return []
    out = []
    for e in units[key]:
        if "start" in e and "end" in e and "val" in e and "filed" in e:
            out.append(e)
    return out


def dedupe_asof(rows, asof):
    """(start,end) -> entry with the latest filed date strictly < asof."""
    best = {}
    for e in rows:
        if not (e["filed"] < asof):
            continue
        k = (e["start"], e["end"])
        cur = best.get(k)
        if cur is None or e["filed"] > cur["filed"]:
            best[k] = e
    return best


def dur_class(start, end):
    dd = dord(end) - dord(start) + 1
    if 75 <= dd <= 110:
        return "Q"
    if 160 <= dd <= 200:
        return "H1"
    if 250 <= dd <= 290:
        return "M9"
    if 340 <= dd <= 385:
        return "FY"
    return None


def build_quarters(facts_by_se):
    by_start = {}
    for (s, e), ent in facts_by_se.items():
        cls = dur_class(s, e)
        if cls is None:
            continue
        by_start.setdefault(s, {})[cls] = (e, float(ent["val"]))
    quarters = {}
    n_direct = 0
    n_derived = 0
    for s, d in by_start.items():
        if "Q" in d:
            e, v = d["Q"]
            if e not in quarters:
                quarters[e] = v
                n_direct += 1
    for s, d in by_start.items():
        if "H1" in d and "Q" in d:
            e = d["H1"][0]
            if e not in quarters:
                quarters[e] = d["H1"][1] - d["Q"][1]
                n_derived += 1
        if "M9" in d and "H1" in d:
            e = d["M9"][0]
            if e not in quarters:
                quarters[e] = d["M9"][1] - d["H1"][1]
                n_derived += 1
        if "FY" in d and "M9" in d:
            e = d["FY"][0]
            if e not in quarters:
                quarters[e] = d["FY"][1] - d["M9"][1]
                n_derived += 1
    return quarters, n_direct, n_derived


def ttm_pair(quarters):
    ends = sorted(quarters)
    if len(ends) < 8:
        return None

    def window_ok(idxs):
        es = [ends[i] for i in idxs]
        for a, b in zip(es, es[1:]):
            gap = dord(b) - dord(a)
            if not (60 <= gap <= 130):
                return False
        span = dord(es[-1]) - dord(es[0])
        return 250 <= span <= 400

    now_idx = [len(ends) - 4, len(ends) - 3, len(ends) - 2, len(ends) - 1]
    if not window_ok(now_idx):
        return None
    latest = ends[-1]
    target = dord(latest) - 365
    anchor = None
    best_diff = None
    for i, e in enumerate(ends):
        diff = abs(dord(e) - target)
        if diff <= 45 and (best_diff is None or diff < best_diff):
            anchor, best_diff = i, diff
    if anchor is None or anchor < 3:
        return None
    ago_idx = [anchor - 3, anchor - 2, anchor - 1, anchor]
    if ago_idx[-1] >= now_idx[0]:
        return None
    if not window_ok(ago_idx):
        return None
    ttm_now = sum(quarters[ends[i]] for i in now_idx)
    ttm_ago = sum(quarters[ends[i]] for i in ago_idx)
    return ttm_now, ttm_ago


def signal_at(facts, asof, stats):
    """ACCEL for one name at one selection date, or None if unscorable."""
    sbc_rows = concept_rows(facts, SBC_CONCEPT)
    if not sbc_rows:
        return None
    sbc_q, nd, nder = build_quarters(dedupe_asof(sbc_rows, asof))
    sbc_ttm = ttm_pair(sbc_q)
    if sbc_ttm is None:
        return None
    stats["direct"] += nd
    stats["derived"] += nder
    for concept in REVENUE_CHAIN:
        rev_rows = concept_rows(facts, concept)
        if not rev_rows:
            continue
        rev_q, _, _ = build_quarters(dedupe_asof(rev_rows, asof))
        rev_ttm = ttm_pair(rev_q)
        if rev_ttm is None:
            continue
        if rev_ttm[0] <= 0 or rev_ttm[1] <= 0:
            continue
        int_now = sbc_ttm[0] / rev_ttm[0]
        int_ago = sbc_ttm[1] / rev_ttm[1]
        return int_now - int_ago
    return None


class SignalCache:
    """Memoized signal_at. The signal for a name depends only on the set
    of facts filed strictly before `asof`, which changes only when asof
    passes a filed date of the SBC or revenue-chain concepts. Keying the
    cache by the count of such filed dates < asof is therefore exact —
    same inputs, same outputs as calling signal_at directly."""

    def __init__(self, facts):
        self.facts = facts
        filed = set()
        for concept in [SBC_CONCEPT] + REVENUE_CHAIN:
            for e in concept_rows(facts, concept):
                filed.add(e["filed"])
        self.filed = sorted(filed)
        self.cache = {}

    def get(self, asof):
        k = bisect_left(self.filed, asof)
        if k not in self.cache:
            stats = {"direct": 0, "derived": 0}
            self.cache[k] = (signal_at(self.facts, asof, stats), stats)
        return self.cache[k]


# ------------------------------------------------------------- cadences
def cadence_dates(days, cadence):
    """SPEC uniform cadence dates over the sorted trading days given."""
    if cadence == "daily":
        return list(days)
    out = []
    seen = set()
    week_idx = {}
    for d in days:
        y, m = d[:4], d[5:7]
        iso = date(int(y), int(m), int(d[8:10])).isocalendar()
        wk = (iso[0], iso[1])
        if cadence == "weekly":
            key = wk
        elif cadence == "biweekly":
            if wk not in week_idx:
                week_idx[wk] = len(week_idx)
            if week_idx[wk] % 2 == 1:
                continue
            key = wk
        elif cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            if m not in ("01", "04", "07", "10"):
                continue
            key = (y, m)
        elif cadence == "semiannual":
            if m not in ("01", "07"):
                continue
            key = (y, m)
        elif cadence == "annual":
            key = y
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------------- engine (v8, verbatim
# mechanics; selection dates + precomputed scores are parameters)
def run_pot(pb, scores_by_date, sel_dates, start, end, start_cash, floor0,
            placebo_rng=None, label=""):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
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
            scores = scores_by_date[d]
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sorted(scores, key=lambda t: (scores[t], t))[:5]
                pools.append((d, {t: round(scores[t], 6)
                                  for t in sorted(scores)}, list(picks)))
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


# --------------------------------------- v9 wrapper (lr_common, verbatim)
def run_v9(run_one, trading_days, start, end, start_cash=START_CASH):
    episodes = []
    ep1 = run_one(start, end, start_cash, 0.85 * start_cash)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(elig, end, ep1["final"], 0.85 * ep1["final"])
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = None
                if ep2.get("pools"):
                    first = ep2["pools"][0]
                    first_sel = first[0] if isinstance(first, (list, tuple)) \
                        else first.get("date")
                restart = {"halt_date": ep1["halted"],
                           "halt_signal_close":
                               ep1["halt_info"]["signal_close"]
                               if ep1.get("halt_info") else None,
                           "liquidation_proceeds": round(ep1["final"], 2),
                           "eligibility_date": elig,
                           "episode2_first_selection": first_sel,
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "second_halt": ep2["halted"]}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        gap_days = [d for d in trading_days
                    if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap_days]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1, "signal_date": ep["halted"],
                          "signal_close":
                              ep["halt_info"]["signal_close"]
                              if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"episodes": episodes, "final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "halts": halts, "restart": restart, "curve": curve}


def curve_diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d}


def cagr_pct(final, start, end):
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2)


# ------------------------------------------------------------------ main
def main():
    print("loading facts (30 pond names only, read-only caches)...",
          flush=True)
    sig_caches = {}
    for t in UNIVERSE:
        cik = C.cik_for(t)
        if t == "XOM":
            cik = 34088  # champion engine's override, carried over
        sig_caches[t] = SignalCache(C.load_facts(cik))
        print(f"  {t}: facts loaded", flush=True)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = C.bars_adj(C.yahoo_payload(t))
    pb = C.FastPriceBook(bars)
    days = [d for d in pb.dates if START <= d <= END]
    print(f"book: {len(days)} trading days {days[0]}..{days[-1]}", flush=True)

    spy, _ = C.champ.spy_net(pb, START, END, START_CASH)
    print(f"SPY decade net: ${spy:,.2f}", flush=True)

    # Precompute scores for every trading day once (daily is the finest
    # cadence; every other cadence's dates are a subset of trading days).
    print("precomputing daily scores...", flush=True)
    scores_by_date = {}
    pool_sizes = {}
    for d in days:
        sc = {}
        for t in UNIVERSE:
            v, _st = sig_caches[t].get(d)
            if v is not None:
                sc[t] = v
        scores_by_date[d] = sc
        pool_sizes[d] = len(sc)
    elig = sorted(pool_sizes.values())
    print(f"eligible pool: min={elig[0]} median={elig[len(elig)//2]} "
          f"max={elig[-1]} of 30", flush=True)

    cadences = ["daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"]
    cells = {}
    for cad in cadences:
        sel = cadence_dates(days, cad)
        sel_set = set(sel)

        def run_one(s, e, cash, floor, rng=None):
            sub = [d for d in sel if s <= d <= e]
            return run_pot(pb, scores_by_date, sub, s, e, cash, floor,
                           placebo_rng=rng)

        r = run_v9(lambda s, e, c, f: run_one(s, e, c, f), pb.dates,
                   START, END)
        diag = curve_diagnostics(r["curve"])
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_v9(lambda s, e, c, f, rng=rng: run_one(s, e, c, f, rng),
                        pb.dates, START, END)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for x in placebo_finals if r["final"] > x)
        cell = {
            "cadence": cad, "start": START, "end": END,
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], START, END),
            "max_dd_pct": diag["max_drawdown_pct"],
            "max_dd_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": r["halts"],
            "restart": ({"halt_date": r["restart"]["halt_date"],
                         "eligibility_date": r["restart"]["eligibility_date"],
                         "episode2_first_selection":
                             r["restart"]["episode2_first_selection"],
                         "episode2_floor": r["restart"]["episode2_floor"],
                         "second_halt": r["restart"]["second_halt"]}
                        if r["restart"] else None),
            "second_halt": bool(r["restart"] and r["restart"]["second_halt"]),
            "n_selection_dates": len(sel),
            "eligible_pool_min": min(pool_sizes[d] for d in sel),
            "eligible_pool_max": max(pool_sizes[d] for d in sel),
            "placebo_finals": placebo_finals,
            "placebo_beaten": beaten,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        }
        if cad == "quarterly":
            stats = {"direct": 0, "derived": 0}
            for d in sel:
                for t in UNIVERSE:
                    _v, st = sig_caches[t].get(d)
                    if _v is not None:
                        stats["direct"] += st["direct"]
                        stats["derived"] += st["derived"]
            cell["quarter_values_direct"] = stats["direct"]
            cell["quarter_values_derived"] = stats["derived"]
            cell["pools"] = [
                [d, {t: round(scores_by_date[d][t], 6)
                     for t in sorted(scores_by_date[d])}]
                for d in sel]
        cells[cad] = cell
        print(f"== {cad}: final=${r['final']:,.2f} CAGR={cell['cagr_pct']}% "
              f"maxDD={diag['max_drawdown_pct']}% costs=${r['costs']:,.2f} "
              f"orders={r['orders']} halts={len(r['halts'])} "
              f"placebo beaten={beaten}/20", flush=True)
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1, default=str)

    out = {"slug": "novel-f3-paying-in-stock", "decade_spy_final": round(spy, 2),
           "eligible_pool_over_decade": {"min": elig[0],
                                         "median": elig[len(elig) // 2],
                                         "max": elig[-1]},
           "cells": {c: {k: v for k, v in cells[c].items()
                         if k not in ("equity_curve", "pools")}
                     for c in cadences}}
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
