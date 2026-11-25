#!/usr/bin/env python3
"""
NOVEL N-F3 — "PAYING IN STOCK" (share-based compensation intensity
acceleration) — Terry's AI stock app, v8 novel ("never been done") track.
Simulation only.

INVENTED-IN-2026 RULE: this rule was invented by this program in 2026,
knowing the test era exists. It is reported as 1 of 12 invented rules.
The best verdict available to it is CANDIDATE (only a forward paper
trial can promote an invented rule). CANDIDATE requires ALL of:
  - validation final > SPY $187.77
  - validation placebo >= 19/20 beaten
  - continuous final > SPY $313.62
  - no floor halt on either main window
Anything less = NOT A CANDIDATE.

SPEC (frozen, research/v8-novel/novel-filings.md, Rule N-F3), implemented
verbatim:
  - Data: EDGAR companyfacts, us-gaap ShareBasedCompensation (flow) and
    revenue. As-filed values only; latest filing before the selection
    date wins; only facts filed strictly before the selection date.
  - TTM construction (frozen): trailing twelve months = the sum of the
    latest four distinct fiscal-quarter duration values filed strictly
    before the selection date; where a standalone Q4 duration is not
    tagged, Q4 = fiscal-year duration - nine-month duration, both as
    filed.
  - Revenue concept chain (first available, in order):
    RevenueFromContractWithCustomerExcludingAssessedTax -> Revenues ->
    RevenuesNetOfInterestExpense -> SalesRevenueNet.
  - Signal: SBC_INT(t) = TTM ShareBasedCompensation / TTM revenue.
    ACCEL = SBC_INT(now) - SBC_INT(same fiscal quarter, one year
    earlier). Rank ascending (decelerating intensity first). Top 5,
    equal weight.
  - Eligibility: ShareBasedCompensation tagged and computable for BOTH
    the current and year-ago TTM windows. Names that do not tag the
    concept separately are unscorable and excluded — never patched,
    never proxied.
  - Shared chassis: honest top-30 pond as of Nov 2016; $100; quarterly
    selection on the first trading day of Jan/Apr/Jul/Oct, execution at
    the next open (champion-engine mechanics); costs 0.10% of trade
    value per side + $0.01 per sell order; plain -15% floor (close
    at/below $85.00 -> liquidate at next open, run ends). No ladder.

FORCED READINGS (stated here, before any result):
  1. Quarter-value derivation. The frozen TTM is "the sum of the latest
     four distinct fiscal-quarter duration values", and the spec names
     the Q4 case of the general as-filed subtraction (Q4 = FY - 9M).
     The identical as-filed subtraction is applied to Q2 (H1 - Q1) and
     Q3 (9M - H1) where a standalone quarter duration is not tagged; a
     directly tagged standalone quarter value is always preferred when
     one exists. The script counts how many quarter values were direct
     vs derived, per window, and reports them.
  2. Year-ago anchor. "Same fiscal quarter, one year earlier" = the
     quarter whose end date is closest to (latest quarter end - 365
     days), required within 45 days; TTM(year-ago) = the four
     consecutive quarters ending at that anchor. Within each TTM
     window, consecutive quarter-end gaps must be 60-130 days and the
     4-quarter span 250-400 days, else the window is not computable
     (data-integrity guard against silently spanning a missing quarter).
  3. Revenue concept choice is per (name, selection date): the first
     concept in the frozen chain for which BOTH TTM windows are
     computable at that date; that concept is used for both windows.
  4. Duplicate facts for the same (start, end): the entry with the
     latest `filed` date strictly before the selection date wins
     (restatements enter only once filed — the chassis rule).
  5. No filed-freshness gate is added beyond the spec's construction:
     the "latest four" quarters are whatever was most recently filed
     before the selection date. (All pond filers report quarterly; the
     guard in reading 2 keeps the windows honest.)

ENGINE: the trade engine below is the champion engine
(backtests/v4/value-momentum-plainfloor.py) with the scoring block
replaced by the N-F3 signal; data loading (EDGAR companyfacts cache,
Yahoo price cache, PriceBook, spy_net) is imported from the champion
module verbatim so prices/costs/floor semantics are identical.
"""
import importlib.util
import json
import math
import os
import random
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

_spec = importlib.util.spec_from_file_location(
    "champ", os.path.join(V4, "value-momentum-plainfloor.py"))
champ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(champ)

UNIVERSE = champ.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))

SBC_CONCEPT = "ShareBasedCompensation"
REVENUE_CHAIN = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "Revenues",
                 "RevenuesNetOfInterestExpense",
                 "SalesRevenueNet"]


# ------------------------------------------------------------ TTM builder
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
    """Standalone fiscal-quarter values from as-filed duration facts.

    Returns (quarters, n_direct, n_derived): quarters maps end date ->
    standalone quarter value. Directly tagged quarter durations are
    preferred; missing quarters are derived by as-filed subtraction
    (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M) per forced reading 1.
    """
    by_start = {}   # start -> {cls: (end, val)}
    for (s, e), ent in facts_by_se.items():
        cls = dur_class(s, e)
        if cls is None:
            continue
        by_start.setdefault(s, {})[cls] = (e, float(ent["val"]))
    quarters = {}
    n_direct = 0
    n_derived = 0
    # direct quarters first
    for s, d in by_start.items():
        if "Q" in d:
            e, v = d["Q"]
            if e not in quarters:
                quarters[e] = v
                n_direct += 1
    # derivations (only fill quarters not directly tagged)
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
    """(ttm_now, ttm_ago) from a quarter-end -> value map, or None.

    ttm_now  = sum of the latest four distinct fiscal quarters.
    ttm_ago  = sum of the four consecutive quarters ending at the
               anchor quarter (same fiscal quarter one year earlier).
    Guards per forced reading 2.
    """
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


# ------------------------------------------------------------------ engine
# Mirrors the champion engine's run_pot exactly (pending rebalance at
# next open, quarterly selection, end-of-day floor check, liquidation
# semantics, costs), with the scoring block replaced by the N-F3 signal.
def run_pot(pb, facts_by_ticker, start, end, start_cash, floor0,
            placebo_rng=None, label="", quiet=True, stats=None):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_dates = champ.quarter_selection_dates(pb, start, end)
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
            for t in UNIVERSE:
                a = signal_at(facts_by_ticker[t], d, stats)
                if a is not None:
                    scores[t] = a
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
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} "
                          f"picks={picks} pot=${pv:,.2f}", flush=True)
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


def diagnostics(r, floor0):
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d}


# --------------------------------------------------------------------- main
def main():
    ciks = champ.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}  # carried over from the champion engine
    facts_by_ticker = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_ticker[t] = champ.get_companyfacts(cik)
        print(f"{t}: facts loaded (CIK {cik})", flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = champ.PriceBook(bars)

    windows = [
        ("FULL", "2019-01-02", "2026-11-20"),
        ("VALIDATION", "2023-01-03", "2026-11-20"),
    ]
    out = {"rule": "N-F3 Paying in Stock (SBC intensity acceleration)",
           "invented": "2026, 1 of 12 invented rules",
           "protection": "plain -15% floor only",
           "universe": UNIVERSE}
    for wname, ws, we in windows:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        stats = {"direct": 0, "derived": 0}
        r = run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                    label=f"{wname} $100 N-F3", stats=stats)
        diag = diagnostics(r, 85.0)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pstats = {"direct": 0, "derived": 0}
            pr = run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                         placebo_rng=rng,
                         label=f"{wname} $100 PLACEBO s{seed}",
                         stats=pstats)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for x in placebo_finals if r["final"] > x)
        sf = sorted(placebo_finals)
        placebo_median = round((sf[9] + sf[10]) / 2.0, 2)
        out[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s, 2),
            "diag": diag,
            "placebo_finals": placebo_finals,
            "placebo_median": placebo_median,
            "placebo_beaten": beaten,
            "quarter_values_direct": stats["direct"],
            "quarter_values_derived": stats["derived"],
            "pools": r["pools"],
            "trades": r["trades"],
        }
        print(f"== {wname} $100 N-F3 final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY net=${s:,.2f} | "
              f"placebo median=${placebo_median:,.2f} beaten={beaten}/20",
              flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} | maxDD "
              f"{diag['max_drawdown_pct']}% on {diag['max_drawdown_date']} | "
              f"quarter values direct={stats['direct']} "
              f"derived={stats['derived']}", flush=True)

    with open(os.path.join(HERE,
                           "novel-f3-paying-in-stock-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
