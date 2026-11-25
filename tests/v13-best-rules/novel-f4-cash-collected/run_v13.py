#!/usr/bin/env python3
"""
V13 BEST RULES — N-F4 "Cash Already Collected" (invented rule, CANDIDATE
ceiling). Simulation only. Writes ONLY inside this folder.

FROZEN SPEC: BEST-RULES-SPEC.md in this folder (frozen before this run).
- CL / revenue machinery verbatim from the v8 engine (branch priority per
  period end, N-F3 TTM construction, revenue chain, 320-410d year-ago
  match, 548d freshness anchor, PIT by EDGAR `filed` strictly before the
  selection date, latest filing wins).
- MY RULES: rank descending on COVERAGE = CL(now)/TTM revenue(now);
  gates: COVERAGE(now) >= 2%, COVERAGE(year-ago) >= 1%, CL dollars grew
  YoY, TTM revenue growth >= -10%. Hold up to top 10 equal weight (all
  eligible if fewer; <3 eligible -> cash quarter). Quarterly cadence
  (first trading day of Jan/Apr/Jul/Oct, execute next open). NO floor.
  Costs 0.10%/side + $0.01 per sell order. $100 pots.
- Roads: LONG 2012-10-01 (2012 pond), DECADE 2016-11-21, CONT
  2019-01-02, VAL 2023-01-03 (2016 pond), all -> 2026-11-20.
- Placebos: 20 seeds per road, random same-count draws from the same
  date's gated eligible pool, same dates/costs/form.
- Integrity gates (must pass before any verdict counts): SPY nets in
  this plumbing reproduce $367.80 / $313.62 / $187.77; the published
  form (EXCESS, top 5, -15% floor) re-run in this plumbing reproduces
  CONT $283.18 / VAL $169.59.
- Confirmation: fresh-$100 yearly folds (my form vs SPY vs 20 placebos),
  2012 pond for 2013-2016, 2016 pond for 2017-2026.

Data: SEC EDGAR companyfacts + Yahoo payloads via the shared read-only
caches in backtests/long-run-2010/lr_common.py.
"""
import json
import os
import random
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
LONG_POND = ['ORCL', 'AAPL', 'XOM', 'MSFT', 'WMT', 'GOOG', 'GE', 'IBM',
             'CVX', 'T', 'PG', 'JNJ', 'PFE', 'WFC', 'JPM', 'PM', 'MRK',
             'VZ', 'AMZN', 'INTC', 'PEP', 'ABT', 'QCOM', 'CSCO', 'CMCSA',
             'SLB', 'C', 'BAC', 'MCD', 'HD']
COUNT = 10
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
END_ALL = "2026-11-20"
NO_FLOOR = -1e18
ROADS_MAIN = [("DECADE", "2016-11-21", END_ALL),
              ("CONT", "2019-01-02", END_ALL),
              ("VAL", "2023-01-03", END_ALL)]
ROAD_LONG = ("LONG", "2012-10-01", END_ALL)

FRESH_DAYS = 548
YA_LO, YA_HI = 320, 410
REV_CHAIN = ["RevenueFromContractWithCustomerExcludingAssessedTax",
             "Revenues", "RevenuesNetOfInterestExpense", "SalesRevenueNet"]
CL_BRANCHES = [
    ["ContractWithCustomerLiability"],
    ["ContractWithCustomerLiabilityCurrent",
     "ContractWithCustomerLiabilityNoncurrent"],
    ["DeferredRevenueCurrent", "DeferredRevenueNoncurrent"],
]

# ------------------------------------------------------------ EDGAR prep
# (v8 engine, verbatim)


def ord_of(ds):
    return _date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).toordinal()


def instant_entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else (list(units)[0] if units else None)
    if key is None:
        return []
    out = []
    for e in units[key]:
        if "filed" in e and "val" in e and "end" in e:
            out.append((e["end"], e["filed"], float(e["val"])))
    return out


def duration_entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else (list(units)[0] if units else None)
    if key is None:
        return []
    out = []
    for e in units[key]:
        if "filed" in e and "val" in e and "end" in e and "start" in e:
            out.append((e["start"], e["end"], e["filed"], float(e["val"])))
    return out


def as_filed_instants(entries, asof):
    best = {}
    for end, filed, val in entries:
        if filed < asof:
            if end not in best or filed > best[end][0]:
                best[end] = (filed, val)
    return best


def as_filed_durations(entries, asof):
    best = {}
    for start, end, filed, val in entries:
        if filed < asof:
            k = (start, end)
            if k not in best or filed > best[k][0]:
                best[k] = (filed, val)
    return {k: v[1] for k, v in best.items()}


def cl_series(facts, asof):
    branch_maps = []
    for branch in CL_BRANCHES:
        leg_maps = [as_filed_instants(instant_entries(facts, c), asof)
                    for c in branch]
        ends = set()
        for m in leg_maps:
            ends |= set(m)
        merged = {}
        for e in ends:
            tot, ok = 0.0, False
            for m in leg_maps:
                if e in m:
                    tot += m[e][1]
                    ok = True
            if ok:
                merged[e] = tot
        branch_maps.append(merged)
    ends = set()
    for m in branch_maps:
        ends |= set(m)
    series = {}
    for e in ends:
        for m in branch_maps:
            if e in m:
                series[e] = m[e]
                break
    return series


def cl_anchor(facts, asof):
    series = cl_series(facts, asof)
    if not series:
        return None
    branch_raw = []
    for branch in CL_BRANCHES:
        leg_maps = [as_filed_instants(instant_entries(facts, c), asof)
                    for c in branch]
        ends = set()
        for m in leg_maps:
            ends |= set(m)
        filed_map = {}
        for e in ends:
            fs = [m[e][0] for m in leg_maps if e in m]
            filed_map[e] = max(fs)
        branch_raw.append(filed_map)
    cutoff = ord_of(asof) - FRESH_DAYS
    best = None
    for e in series:
        filed = None
        for fm in branch_raw:
            if e in fm:
                filed = fm[e]
                break
        if filed is not None and ord_of(filed) >= cutoff:
            if best is None or e > best[0]:
                best = (e, filed)
    if best is None:
        return None
    return best[0], best[1], series


def year_ago_end(series, E):
    eo = ord_of(E)
    cands = []
    for e in series:
        gap = eo - ord_of(e)
        if YA_LO <= gap <= YA_HI:
            cands.append((abs(gap - 365), e))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


def _durations_by_end(dmap):
    by_end = {}
    for (s, e), v in dmap.items():
        by_end.setdefault(e, []).append((s, v))
    return by_end


def _ytd_at(by_end, end):
    best = None
    for s, v in by_end.get(end, []):
        days = ord_of(end) - ord_of(s)
        if days >= 150 and (best is None or days > best[2]):
            best = (s, v, days)
    return best


def _quarter_value(dmap, by_end, end):
    direct = None
    for s, v in by_end.get(end, []):
        days = ord_of(end) - ord_of(s)
        if 60 <= days <= 115:
            if direct is None or days > direct[0]:
                direct = (days, v)
    if direct is not None:
        return direct[1]
    ytd = _ytd_at(by_end, end)
    if ytd is None:
        return None
    eo = ord_of(end)
    prevs = []
    for e2 in by_end:
        gap = eo - ord_of(e2)
        if 75 <= gap <= 115 and _ytd_at(by_end, e2) is not None:
            prevs.append(e2)
    if not prevs:
        return None
    prev = max(prevs)
    return ytd[1] - _ytd_at(by_end, prev)[1]


def ttm_revenue(dmap, anchor_end):
    by_end = _durations_by_end(dmap)
    ends = [anchor_end]
    cur = anchor_end
    for _ in range(3):
        co = ord_of(cur)
        prevs = [e for e in by_end if 75 <= co - ord_of(e) <= 115]
        if not prevs:
            return None
        cur = max(prevs)
        ends.append(cur)
    total = 0.0
    for e in ends:
        q = _quarter_value(dmap, by_end, e)
        if q is None:
            return None
        total += q
    return total


# ------------------------------------------------------------- scoring


def base_numbers(facts, asof):
    """Shared inputs for both the published score and my v13 score.
    Returns dict or None (CL anchor / year-ago / TTM pair not computable)."""
    anch = cl_anchor(facts, asof)
    if anch is None:
        return None
    E, _filed, series = anch
    E_ya = year_ago_end(series, E)
    if E_ya is None:
        return None
    cl_now, cl_ya = series[E], series[E_ya]
    if cl_ya is None or cl_ya <= 0:
        return None
    rev = None
    for concept in REV_CHAIN:
        dmap = as_filed_durations(duration_entries(facts, concept), asof)
        if not dmap:
            continue
        t_now = ttm_revenue(dmap, E)
        t_ya = ttm_revenue(dmap, E_ya)
        if t_now is not None and t_ya is not None and t_now > 0 and t_ya > 0:
            rev = (concept, t_now, t_ya)
            break
    if rev is None:
        return None
    concept, t_now, t_ya = rev
    return {"CL_now": cl_now, "CL_ya": cl_ya, "TTM_now": t_now,
            "TTM_ya": t_ya, "E": E, "E_ya": E_ya, "rev_concept": concept,
            "CL_GROWTH": cl_now / cl_ya - 1.0,
            "REV_GROWTH": t_now / t_ya - 1.0,
            "COVERAGE": cl_now / t_now, "COVERAGE_YA": cl_ya / t_ya}


def score_published(b):
    """Frozen v8 form: gate CL(now) >= 1% of TTM revenue; EXCESS rank."""
    if b is None or b["CL_now"] < 0.01 * b["TTM_now"]:
        return None
    return b["CL_GROWTH"] - b["REV_GROWTH"]


def score_v13(b):
    """MY RULES (spec SS1): COVERAGE level with gates A/B/C."""
    if b is None:
        return None
    if b["COVERAGE"] < 0.02:          # Gate A, now end
        return None
    if b["COVERAGE_YA"] < 0.01:       # Gate A, year-ago end
        return None
    if not (b["CL_now"] > b["CL_ya"]):  # Gate B: dollars grew
        return None
    if b["REV_GROWTH"] < -0.10:       # Gate C: denominator not collapsing
        return None
    return b["COVERAGE"]


# ---------------------------------------------------------------- engine
# (v8 champion mechanics, verbatim except floor is a parameter)


class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None


def quarter_selection_dates(pb, start, end):
    out = []
    seen = set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out


def run_pot(pb, picks_by_date, start, end, start_cash, floor0,
            placebo_rng=None, label="", quiet=True):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    sel_dates = quarter_selection_dates(pb, start, end)
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
                picks = placebo_rng.sample(sorted(eligible), k) \
                    if k > 0 else []
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
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
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


def diagnostics(r):
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
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d}


def per_period(curve):
    """Quarterly (calendar) period distribution from the curve."""
    periods = []
    prev = curve[0][1]
    cur_key = None
    last_v = curve[0][1]
    for d, v in curve:
        key = (d[:4], (int(d[5:7]) - 1) // 3)
        if cur_key is None:
            cur_key = key
        if key != cur_key:
            periods.append(last_v - prev)
            prev = last_v
            cur_key = key
        last_v = v
    periods.append(last_v - prev)
    pos = sum(1 for p in periods if p > 0)
    sp = sorted(periods)
    n = len(sp)
    median = sp[n // 2] if n % 2 == 1 else (sp[n // 2 - 1] + sp[n // 2]) / 2.0
    streak = mx = 0
    for p in periods:
        streak = streak + 1 if p <= 0 else 0
        mx = max(mx, streak)
    peak = -1.0
    last_high_i = 0
    longest = 0
    for i, (d, v) in enumerate(curve):
        if v >= peak:
            peak = v
            longest = max(longest, i - last_high_i)
            last_high_i = i
    longest = max(longest, len(curve) - 1 - last_high_i)
    return {"n_periods": n, "pct_positive": round(100.0 * pos / n, 1),
            "median_period": round(median, 2),
            "mean_period_secondary": round(sum(periods) / n, 2),
            "best_period": round(max(periods), 2),
            "worst_period": round(min(periods), 2),
            "longest_losing_streak_periods": mx,
            "longest_stretch_between_new_highs_trading_days": longest,
            "period_changes": [round(p, 2) for p in periods]}


def cagr_pct(final, start, end):
    yrs = (ord_of(end) - ord_of(start)) / 365.25
    return round(100.0 * ((final / START_CASH) ** (1.0 / yrs) - 1.0), 2)


def median_of(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ------------------------------------------------------------------ main


def load_pond(pond):
    facts_by = {}
    for t in pond:
        cik = C.cik_for(t)
        if t == "XOM":
            cik = 34088
        facts_by[t] = C.load_facts(cik)
        print(f"  {t}: facts loaded (CIK {cik})", flush=True)
    bars = {}
    for t in pond + ["SPY"]:
        bars[t] = C.bars_adj(C.yahoo_payload(t))
    return facts_by, C.FastPriceBook(bars)


def score_pond(facts_by, pond, pb, start, end):
    """Score every quarterly selection date in [start, end] under BOTH
    the published form and my v13 form (one pass over the facts)."""
    sel = quarter_selection_dates(pb, start, end)
    pub, mine = {}, {}
    for d in sel:
        scored_pub, scored_mine = {}, {}
        for t in pond:
            b = base_numbers(facts_by[t], d)
            if b is None:
                continue
            sp_ = score_published(b)
            if sp_ is not None:
                scored_pub[t] = dict(b, EXCESS=sp_)
            sm_ = score_v13(b)
            if sm_ is not None:
                scored_mine[t] = dict(b, COVERAGE_SCORE=sm_)
        rp = sorted(scored_pub, key=lambda t: -scored_pub[t]["EXCESS"])
        pub[d] = {"eligible": sorted(scored_pub),
                  "picks": rp[:5] if len(rp) >= 3 else [],
                  "scores": {t: scored_pub[t] for t in rp}}
        rm = sorted(scored_mine, key=lambda t: -scored_mine[t]["COVERAGE"])
        mine[d] = {"eligible": sorted(scored_mine),
                   "picks": rm[:COUNT] if len(rm) >= 3 else [],
                   "scores": {t: scored_mine[t] for t in rm}}
        print(f"  {d}: pub_elig={len(scored_pub)} mine_elig="
              f"{len(scored_mine)} mine_picks={mine[d]['picks']}",
              flush=True)
    return pub, mine


def run_road(pb, picks_by_date, name, start, end, floor0):
    spy, _ = spy_net(pb, start, end, START_CASH)
    r = run_pot(pb, picks_by_date, start, end, START_CASH, floor0,
                label=name)
    diag = diagnostics(r)
    twins = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        tw = run_pot(pb, picks_by_date, start, end, START_CASH, floor0,
                     placebo_rng=rng, label=f"{name} twin{seed}")
        twins.append({"seed": seed, "final": round(tw["final"], 2),
                      "halted": tw["halted"]})
    finals = [tw["final"] for tw in twins]
    beats = sum(1 for f in finals if r["final"] > f)
    elig = [len(picks_by_date[d]["eligible"])
            for d in quarter_selection_dates(pb, start, end)
            if d in picks_by_date]
    out = {"road": name, "start": start, "end": end,
           "final": round(r["final"], 2),
           "cagr_pct": cagr_pct(r["final"], start, end),
           "costs": round(r["costs"], 2), "orders": len(r["trades"]),
           "halted": r["halted"], "spy_net": round(spy, 2),
           "diag": diag, "per_period": per_period(r["curve"]),
           "eligible_pool_min": min(elig) if elig else None,
           "eligible_pool_max": max(elig) if elig else None,
           "placebo": {"twins": twins, "beats": beats,
                       "median": round(median_of(finals), 2),
                       "best_twin": round(max(finals), 2),
                       "worst_twin": round(min(finals), 2)},
           "curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    print(f"== {name}: final=${r['final']:,.2f} maxDD="
          f"{diag['max_drawdown_pct']}% costs=${r['costs']:,.2f} "
          f"orders={len(r['trades'])} halted={r['halted']} | SPY="
          f"${spy:,.2f} | placebo {beats}/20 median="
          f"${median_of(finals):,.2f}", flush=True)
    return out


def dump_picks(picks_by_date, path, with_scores=True):
    slim = {}
    for d, v in picks_by_date.items():
        e = {"eligible": v["eligible"], "picks": v["picks"]}
        if with_scores:
            e["scores"] = {t: {"COVERAGE": round(s["COVERAGE"], 4),
                               "COVERAGE_YA": round(s["COVERAGE_YA"], 4),
                               "CL_GROWTH": round(s["CL_GROWTH"], 4),
                               "REV_GROWTH": round(s["REV_GROWTH"], 4)}
                           for t, s in v["scores"].items()}
        slim[d] = e
    with open(path, "w") as f:
        json.dump(slim, f)
    return slim


def load_picks(path):
    with open(path) as f:
        return json.load(f)


def load_results():
    p = os.path.join(HERE, "results.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {"family": "novel-f4-cash-collected",
            "form": "v13 best rules: COVERAGE level rank, gates A/B/C, "
                    "count<=10, quarterly, no floor",
            "published_form": "EXCESS growth-difference rank, top 5, "
                              "plain -15% floor",
            "roads": {}, "integrity": {}, "confirmation_folds": []}


def save_results(out):
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)


def stage_main():
    out = load_results()
    print("loading 2016 pond...", flush=True)
    facts_main, pb_main = load_pond(UNIVERSE)
    print("scoring 2016 pond (both forms)...", flush=True)
    pub_main, mine_main = score_pond(facts_main, UNIVERSE, pb_main,
                                     "2016-11-21", END_ALL)
    out["picks_main_mine"] = dump_picks(
        mine_main, os.path.join(HERE, "picks_main.json"))
    dump_picks(pub_main, os.path.join(HERE, "picks_main_pub.json"),
               with_scores=False)

    spy_checks = {}
    for name, s, e, pub_spy in [("DECADE", "2016-11-21", END_ALL, 367.80),
                                ("CONT", "2019-01-02", END_ALL, 313.62),
                                ("VAL", "2023-01-03", END_ALL, 187.77)]:
        got, _ = spy_net(pb_main, s, e, START_CASH)
        spy_checks[name] = {"computed": round(got, 2), "published": pub_spy,
                            "ok": abs(got - pub_spy) < 0.02}
    out["integrity"]["spy"] = spy_checks
    print(f"INTEGRITY SPY: {spy_checks}", flush=True)
    assert all(v["ok"] for v in spy_checks.values()), "SPY gate failed"

    pub_cont = run_pot(pb_main, pub_main, "2019-01-02", END_ALL,
                       START_CASH, 85.0, label="pub CONT")
    pub_val = run_pot(pb_main, pub_main, "2023-01-03", END_ALL,
                      START_CASH, 85.0, label="pub VAL")
    pub_dec = run_pot(pb_main, pub_main, "2016-11-21", END_ALL,
                      START_CASH, 85.0, label="pub DECADE")
    out["integrity"]["published_form_reproduction"] = {
        "CONT": {"computed": round(pub_cont["final"], 2),
                 "published": 283.18},
        "VAL": {"computed": round(pub_val["final"], 2),
                "published": 169.59},
        "DECADE": {"computed": round(pub_dec["final"], 2),
                   "published": 398.11}}
    print(f"INTEGRITY PUBLISHED FORM: "
          f"{out['integrity']['published_form_reproduction']}", flush=True)
    assert abs(pub_cont["final"] - 283.18) < 0.02
    assert abs(pub_val["final"] - 169.59) < 0.02
    assert abs(pub_dec["final"] - 398.11) < 0.02
    out["published_form_roads"] = {
        "DECADE": round(pub_dec["final"], 2),
        "CONT": round(pub_cont["final"], 2),
        "VAL": round(pub_val["final"], 2)}
    save_results(out)

    for name, s, e in ROADS_MAIN:
        out["roads"][name] = run_road(pb_main, mine_main, name, s, e,
                                      NO_FLOOR)
        save_results(out)
    print("STAGE MAIN DONE", flush=True)


def stage_long():
    out = load_results()
    print("loading 2012 pond (prices only for run; facts for scoring)...",
          flush=True)
    facts_long, pb_long = load_pond(LONG_POND)
    print("scoring 2012 pond...", flush=True)
    _pub_long, mine_long = score_pond(facts_long, LONG_POND, pb_long,
                                      "2012-10-01", END_ALL)
    out["picks_long_mine"] = dump_picks(
        mine_long, os.path.join(HERE, "picks_long.json"),
        with_scores=False)
    save_results(out)
    name, s, e = ROAD_LONG
    out["roads"][name] = run_road(pb_long, mine_long, name, s, e, NO_FLOOR)
    save_results(out)
    print("STAGE LONG DONE", flush=True)


def stage_folds():
    out = load_results()
    mine_main = load_picks(os.path.join(HERE, "picks_main.json"))
    mine_long = load_picks(os.path.join(HERE, "picks_long.json"))
    bars_m, bars_l = {}, {}
    for t in UNIVERSE + ["SPY"]:
        bars_m[t] = C.bars_adj(C.yahoo_payload(t))
    pb_main = C.FastPriceBook(bars_m)
    for t in LONG_POND + ["SPY"]:
        bars_l[t] = C.bars_adj(C.yahoo_payload(t))
    pb_long = C.FastPriceBook(bars_l)
    folds = []
    for yr in range(2013, 2027):
        if yr <= 2016:
            pb_f, picks_f = pb_long, mine_long
        else:
            pb_f, picks_f = pb_main, mine_main
        ws = f"{yr}-01-01"
        we = f"{yr}-12-31" if yr < 2026 else END_ALL
        r = run_pot(pb_f, picks_f, ws, we, START_CASH, NO_FLOOR,
                    label=f"FOLD {yr}")
        spy_f, _ = spy_net(pb_f, ws, we, START_CASH)
        tf = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            tw = run_pot(pb_f, picks_f, ws, we, START_CASH, NO_FLOOR,
                         placebo_rng=rng, label=f"FOLD {yr} twin{seed}")
            tf.append(round(tw["final"], 2))
        beats_f = sum(1 for f in tf if r["final"] > f)
        folds.append({"year": yr, "final": round(r["final"], 2),
                      "spy_final": round(spy_f, 2),
                      "beat_spy": r["final"] > spy_f,
                      "placebo_beats": beats_f,
                      "placebo_median": round(median_of(tf), 2)})
        print(f"FOLD {yr}: mine=${r['final']:,.2f} SPY=${spy_f:,.2f} "
              f"placebo {beats_f}/20", flush=True)
    out["confirmation_folds"] = folds
    save_results(out)
    print("STAGE FOLDS DONE", flush=True)


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "main"
    {"main": stage_main, "long": stage_long,
     "folds": stage_folds}[stage]()
