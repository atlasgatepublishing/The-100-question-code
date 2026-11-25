#!/usr/bin/env python3
"""
V12 HOLDINGS-COUNT SWEEP — N-F3 "Paying in Stock" (invented rule, CANDIDATE ceiling).
Simulation only. Writes ONLY inside this folder.

FROZEN SPEC (pre-registered, from PROGRAM.md HOLDINGS-COUNT SWEEP wing):
- Grid counts: 1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE (capped by the
  eligible pool on each selection date: hold min(count, pool) names;
  ALL-ELIGIBLE = the whole eligible pool).
- Native count = 5 (v8 frozen spec). Native cadence = quarterly (first
  trading day of Jan/Apr/Jul/Oct), execution at next open, equal weight.
- Signal (verbatim from v8/v10 engines): ACCEL = SBC_INT(now) -
  SBC_INT(same fiscal quarter one year earlier), SBC_INT = TTM
  ShareBasedCompensation / TTM revenue, point-in-time by EDGAR `filed`
  date, revenue concept chain as frozen. Rank ascending.
- Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
  VAL 2023-01-03->2026-11-20 (all on the Nov-2016 top-30 pond);
  LONG 2012-10-01->2026-11-20 (point-in-time pond as of 2012-10-01,
  the long-run-2010 measured construction — earliest honest start).
- Forms: HOUSE = v9 protections (plain -15% floor; first halt ->
  liquidate next open, 90 days cash, restart at next quarterly date
  under episode-2 -15% floor; second halt ends). NATIVE = the original
  v8 form (plain -15% floor, a halt ends the run, no restart).
- Costs (both forms, program standard): 0.10% of trade value per side
  + $0.01 per sell order.
- Placebos: 20 seeds (1..20) per cell — random picks of the same count
  from the same eligible pool on the same dates, same form/costs.
- Integrity gate: count 5 must reproduce the published finals
  (DECADE $737.97 house; CONT $505.43; VAL $289.53; LONG $453.93 —
  native identical, no halts at count 5 on any road).

Signal machinery (concept_rows..signal_at, SignalCache) and trade
mechanics are copied from the v10 sweep engine
(backtests/v10-retest/novel-f3-paying-in-stock/sweep.py), which copied
them verbatim from the v8 original; the only changes are (a) the
holdings count is a parameter, and (b) prices are pre-aligned arrays
(close_on_or_before / open per trading day) for speed — values are the
same ones the original accessors return.
"""
import json
import os
import random
import sys
import time
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

UNIVERSE = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'BRK-B', 'JPM', 'XOM',
            'JNJ', 'PG', 'V', 'WMT', 'HD', 'BAC', 'CVX', 'PFE', 'VZ', 'T',
            'DIS', 'NFLX', 'INTC', 'CSCO', 'GE', 'IBM', 'MMM', 'UNH', 'MA',
            'KO', 'PEP', 'WFC']
LONG_POND = ['ORCL', 'AAPL', 'XOM', 'MSFT', 'WMT', 'GOOG', 'GE', 'IBM',
             'CVX', 'T', 'PG', 'JNJ', 'PFE', 'WFC', 'JPM', 'PM', 'MRK',
             'VZ', 'AMZN', 'INTC', 'PEP', 'ABT', 'QCOM', 'CSCO', 'CMCSA',
             'SLB', 'C', 'BAC', 'MCD', 'HD']
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
END_ALL = "2026-11-20"
ROADS_MAIN = [("DECADE", "2016-11-21", END_ALL),
              ("CONT", "2019-01-02", END_ALL),
              ("VAL", "2023-01-03", END_ALL)]
ROAD_LONG = ("LONG", "2012-10-01", END_ALL)
PUBLISHED5 = {"DECADE": 737.97, "CONT": 505.43, "VAL": 289.53, "LONG": 453.93}

SBC_CONCEPT = "ShareBasedCompensation"
REVENUE_CHAIN = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "Revenues",
                 "RevenuesNetOfInterestExpense",
                 "SalesRevenueNet"]


# --------------------------------------- signal machinery (v8, verbatim)
def dord(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10])).toordinal()


def concept_rows(facts, concept):
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


# ------------------------------------------------------------- cadence
def cadence_dates(days, cadence):
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


# ------------------------------------------------- engine (v8 mechanics,
# count parameterised; prices pre-aligned to the window's trading days)
class Window:
    """Per-road aligned price arrays: closes[i][t] = close_on_or_before,
    opens[i][t] = that day's bar open (or None)."""

    def __init__(self, pb, tickers, start, end):
        self.days = [d for d in pb.dates if start <= d <= end]
        self.closes = []
        self.opens = []
        for d in self.days:
            crow = {}
            orow = {}
            for t in tickers:
                c = pb.close_on_or_before(t, d)
                if c:
                    crow[t] = c
                b = pb.bar(t, d)
                if b:
                    orow[t] = b["o"]
            self.closes.append(crow)
            self.opens.append(orow)


def run_pot(win, scores_by_date, sel_set, n_req, start_cash, floor,
            placebo_rng=None):
    cash = start_cash
    positions = {}
    n_trades = 0
    total_costs = 0.0
    curve = []
    pools = []
    pending = None
    days = win.days

    def pclose(di):
        v = cash
        crow = win.closes[di]
        for t, sh in positions.items():
            c = crow.get(t)
            if c:
                v += sh * c
        return v

    def execute(di, targets):
        nonlocal cash, total_costs, n_trades
        orow = win.opens[di]
        for t in list(positions):
            if t not in orow:
                continue
            cur_val = positions[t] * orow[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / orow[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                total_costs += c
                n_trades += 1
                positions[t] -= sh
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in orow:
                continue
            cur_val = positions.get(t, 0.0) * orow[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / orow[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                n_trades += 1
                positions[t] = positions.get(t, 0.0) + sh

    for di, d in enumerate(days):
        if pending is not None:
            execute(di, pending)
            pending = None
        if d in sel_set:
            scores = scores_by_date[d]
            if scores:
                n_hold = len(scores) if n_req == "ALL" else min(n_req, len(scores))
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), n_hold)
                else:
                    picks = sorted(scores, key=lambda t: (scores[t], t))[:n_hold]
                pools.append([d, list(picks)])
                pv = pclose(di)
                each = pv / n_hold
                pending = {t: each for t in picks}
        v = pclose(di)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            orow = win.opens[di + 1]
            for t in list(positions):
                if t in orow:
                    val = positions[t] * orow[t]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    n_trades += 1
            positions = {}
            return {"final": cash, "costs": total_costs, "orders": n_trades,
                    "halted": d, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve}
    last = len(days) - 1
    crow = win.closes[last]
    for t in list(positions):
        c_ = crow.get(t)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            n_trades += 1
    return {"final": cash, "costs": total_costs, "orders": n_trades,
            "halted": None, "end": days[-1], "halt_info": None,
            "pools": pools, "curve": curve}


# --------------------------------------- v9 wrapper (lr_common, verbatim
# logic; run_one signature carries the window + rng)
def run_v9(run_one, all_days, start, end, start_cash=START_CASH):
    episodes = []
    ep1 = run_one(start, end, start_cash, 0.85 * start_cash, None)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(elig, end, ep1["final"], 0.85 * ep1["final"], None)
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = ep2["pools"][0][0] if ep2.get("pools") else None
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
        gap_days = [d for d in all_days
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
            "orders": sum(ep["orders"] for ep in episodes),
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
def load_caches(tickers):
    caches = {}
    for t in tickers:
        cik = C.cik_for(t)
        if t == "XOM":
            cik = 34088
        caches[t] = SignalCache(C.load_facts(cik))
        print(f"  {t}: facts loaded", flush=True)
    return caches


def build_book(tickers):
    bars = {}
    for t in tickers + ["SPY"]:
        bars[t] = C.bars_adj(C.yahoo_payload(t))
    return C.FastPriceBook(bars)


def run_pond(pond, roads, out):
    print(f"loading facts ({len(pond)} names)...", flush=True)
    caches = load_caches(pond)
    pb = build_book(pond)
    for road, start, end in roads:
        days_all = [d for d in pb.dates if start <= d <= end]
        sel = cadence_dates(days_all, "quarterly")
        sel_set = set(sel)
        scores = {}
        for d in sel:
            sc = {}
            for t in pond:
                v, _st = caches[t].get(d)
                if v is not None:
                    sc[t] = v
            scores[d] = sc
        win = Window(pb, pond, start, end)
        spy, _ = C.champ.spy_net(pb, start, end, START_CASH)
        pool_sizes = [len(scores[d]) for d in sel]
        print(f"[{road}] {start}..{end} sel={len(sel)} pool "
              f"{min(pool_sizes)}-{max(pool_sizes)} SPY=${spy:,.2f}",
              flush=True)

        for form in ("house", "native"):
            for n_req in COUNTS:
                def run_one(s, e, cash, floor, rng, n_req=n_req):
                    idx = [i for i, d in enumerate(win.days) if s <= d <= e]
                    return run_pot_slice(win, idx, sel_set, scores, n_req,
                                         cash, floor, rng)
                if form == "house":
                    r = run_v9(run_one, pb.dates, start, end)
                    halts = r["halts"]
                    restart = r["restart"]
                    second = bool(restart and restart["second_halt"])
                else:
                    rr = run_one(start, end, START_CASH, 0.85 * START_CASH,
                                 None)
                    r = {"final": rr["final"], "costs": rr["costs"],
                         "orders": rr["orders"], "curve": rr["curve"]}
                    halts = ([{"episode": 1, "signal_date": rr["halted"],
                               "signal_close": rr["halt_info"]["signal_close"],
                               "floor_in_effect":
                                   rr["halt_info"]["floor_in_effect"],
                               "liquidation_date": rr["end"],
                               "proceeds": round(rr["final"], 2)}]
                             if rr["halted"] else [])
                    restart = None
                    second = False
                diag = curve_diagnostics(r["curve"])
                placebo_finals = []
                for seed in PLACEBO_SEEDS:
                    rng = random.Random(seed)
                    if form == "house":
                        def run_one_p(s, e, cash, floor, _rng,
                                      n_req=n_req, rng=rng):
                            idx = [i for i, d in enumerate(win.days)
                                   if s <= d <= e]
                            return run_pot_slice(win, idx, sel_set, scores,
                                                 n_req, cash, floor, rng)
                        pr = run_v9(run_one_p, pb.dates, start, end)
                    else:
                        idx = list(range(len(win.days)))
                        pr = run_pot_slice(win, idx, sel_set, scores, n_req,
                                           START_CASH, 0.85 * START_CASH, rng)
                    placebo_finals.append(round(pr["final"], 2))
                beaten = sum(1 for x in placebo_finals if r["final"] > x)
                key = f"{road}-{form}-{n_req}"
                cell = {
                    "road": road, "form": form, "count": n_req,
                    "start": start, "end": end, "cadence": "quarterly",
                    "final": round(r["final"], 2),
                    "cagr_pct": cagr_pct(r["final"], start, end),
                    "max_dd_pct": diag["max_drawdown_pct"],
                    "max_dd_date": diag["max_drawdown_date"],
                    "worst_close": diag["worst_close"],
                    "worst_close_date": diag["worst_close_date"],
                    "costs": round(r["costs"], 2), "orders": r["orders"],
                    "halts": halts, "restart": restart,
                    "second_halt": second,
                    "n_selection_dates": len(sel),
                    "eligible_pool_min": min(pool_sizes),
                    "eligible_pool_max": max(pool_sizes),
                    "spy_final": round(spy, 2),
                    "placebo_finals": placebo_finals,
                    "placebo_beaten": beaten,
                    "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
                }
                out["cells"][key] = cell
                with open(os.path.join(HERE, "cells", f"{key}.json"),
                          "w") as f:
                    json.dump(cell, f, indent=1, default=str)
                print(f"  [{key}] final=${r['final']:,.2f} "
                      f"maxDD={diag['max_drawdown_pct']}% "
                      f"costs=${r['costs']:,.2f} orders={r['orders']} "
                      f"halts={len(halts)} placebo {beaten}/20",
                      flush=True)
                if n_req == 5:
                    pub = PUBLISHED5[road]
                    ok = abs(round(r["final"], 2) - pub) < 0.005
                    out["integrity"][f"{road}-{form}"] = {
                        "published": pub,
                        "reproduced": round(r["final"], 2),
                        "match_to_cent": ok}
                    print(f"  INTEGRITY [{road}-{form}] published "
                          f"${pub:,.2f} vs ${r['final']:,.2f} -> "
                          f"{'REPRODUCED' if ok else 'MISMATCH'}",
                          flush=True)
    return out


def run_pot_slice(win, idx, sel_set, scores_by_date, n_req, start_cash,
                  floor, placebo_rng=None):
    """run_pot over a sub-window of win (by day indices)."""
    sub = Window.__new__(Window)
    sub.days = [win.days[i] for i in idx]
    sub.closes = [win.closes[i] for i in idx]
    sub.opens = [win.opens[i] for i in idx]
    return run_pot(sub, scores_by_date, sel_set, n_req, start_cash, floor,
                   placebo_rng=placebo_rng)


def main():
    t0 = time.time()
    out = {"family": "N-F3 Paying in Stock (novel-f3-paying-in-stock)",
           "native_count": 5, "counts_grid": COUNTS,
           "integrity": {}, "cells": {}}
    run_pond(UNIVERSE, ROADS_MAIN, out)
    run_pond(LONG_POND, [ROAD_LONG], out)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"DONE ({time.time()-t0:.0f}s)", flush=True)
    print(json.dumps(out["integrity"], indent=1), flush=True)


if __name__ == "__main__":
    main()
