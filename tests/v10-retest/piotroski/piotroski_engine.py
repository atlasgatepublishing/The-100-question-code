#!/usr/bin/env python3
"""
PIOTROSKI F-SCORE VALUE — Terry's AI stock app. Simulation only.
NO parameter tuning: the spec below is run ONCE, as described, and judged
against the promoted champion's published numbers.

THE STRATEGY (Piotroski 2000, "Value Investing: The Use of Historical
Financial Statement Information to Separate Winners from Losers",
Journal of Accounting Research): within the cheapest stocks by
book-to-market, separate winners from losers with a nine-signal
fundamental strength score (F-score, 0-9) built entirely from filed
financial statements:
  Profitability:  (1) ROA > 0            (2) operating cash flow > 0
                  (3) ROA rising         (4) CFO > ROA (low accruals)
  Leverage/liquidity/equity:
                  (5) long-term leverage ratio falling
                  (6) current ratio rising
                  (7) no new equity issued
  Operating efficiency:
                  (8) gross margin rising
                  (9) asset turnover rising
Ratios follow the paper: flows scaled by BEGINNING-of-year total assets;
leverage = long-term debt / AVERAGE total assets; margin and turnover
are year-over-year changes.

PROGRAM FORMAT (the task's rule; the published form holds high-B/M,
high-F names for one year — quarterly top-5 is the program's format,
stated here as an adaptation):
  - Universe / pool: the champion's honest point-in-time top-30 as of
    Nov 2016. The pool at each quarterly selection = names with a valid
    book-to-market under the champion's exact rules (point-in-time EDGAR
    equity + shares chains, selection-day close). Momentum is NOT
    required for pool entry — it is not part of this strategy.
  - Cheapest third: the top ceil(N/3) of the pool by book-to-market.
  - Among the cheapest third, rank by F-score (ties: higher B/M first —
    a deterministic tie-break the top-5 format forces; Piotroski held
    all high-F names). Hold top 5, equal weight (each target = pot/5;
    if fewer than 5 candidates qualify, the unfilled slots stay in
    cash). Quarterly selection (first trading day of Jan/Apr/Jul/Oct),
    rebalance at next open.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no ladder).
    Close at/below floor -> liquidate at next open, run ends.
  - Pot: $100 only (Terry's current standard).

POINT-IN-TIME DISCIPLINE (identical to the champion): every fact must
be FILED strictly before the selection date; the current fiscal year
(FY_t) is the latest fiscal year whose annual NetIncomeLoss filing is
before the selection date and passes the engine's ~18-month
filed-freshness gate (548 days). Each line item is taken as known at
the selection date: for a given fiscal-year end, the latest filing
before the selection date wins (restatements enter only once filed).

FORCED ADAPTATIONS (data-driven, documented, not tuned):
  A1. PARTIAL SCORES. US mega-caps do not all file the inputs: banks
      (JPM/BAC/WFC) and Berkshire file UNCLASSIFIED balance sheets (no
      AssetsCurrent/LiabilitiesCurrent — signal 6 not computable) and
      no gross profit (signal 8 not computable); Exxon/Chevron file no
      gross-profit or single COGS line (signal 8 not computable).
      Rule: a signal whose inputs were never filed earns NO point
      (missing = 0, the conservative reading — the program never
      patches data), and a name is F-scorable only if at least 7 of 9
      signals are computable. Financials are therefore capped at 7 —
      Piotroski's signals are industrial-firm signals and most
      published replications sideline financials the same way.
  A2. GROSS MARGIN input: GrossProfit as filed where it exists; else
      Revenue - COGS with COGS = CostOfRevenue / CostOfGoodsAndServicesSold
      and Revenue = RevenueFromContractWithCustomerExcludingAssessedTax
      / SalesRevenueNet / Revenues / RevenuesNetOfInterestExpense
      (the last is the banks' total-net-revenue line — WFC files its
      revenue ONLY under it after 2020; priority chains below). Note
      JPMorgan's long-term debt is not tagged in companyfacts after
      2013 under any standard concept, so JPM's dLEVER is uncomputable
      and JPM sits at 6 available signals — below the gate — whenever
      it enters the cheapest third. Never patched; stated, not fixed.
  A3. LONG-TERM DEBT input: priority chain LongTermDebt >
      LongTermDebtNoncurrent > DebtLongtermAndShorttermCombinedAmount >
      DebtAndCapitalLeaseObligations (the last is Berkshire's only
      filed debt aggregate). Pick-one per fiscal-year end, latest filed.
  A4. EQUITY ISSUANCE compares shares outstanding at the two fiscal
      year-ends (balance-sheet CommonStockSharesOutstanding, else the
      dei cover count, else annual weighted-average basic shares).
      GAAP restates share counts retroactively for splits in later
      comparative filings, and the latest-filed-wins rule reads both
      years on that consistent basis.
  A5. Fiscal-year bundles: FY_t and FY_{t-1} are located by period END
      (prior year = annual NI end 300-560 days before FY_t's end);
      balance-sheet items are matched to those ends within +/-20 days.
      Flow items use reported fiscal-year facts only (period duration
      300-400 days), exactly like the program's EY variant.

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) to
      the cent before any variant number is taken.
  (1) Ranked Piotroski: CONTINUOUS 2019-01-02 -> 2026-11-20 and
      VALIDATION 2023-01-03 -> 2026-11-20.
  (2) PLACEBO: 20 seeds (1..20) on BOTH windows — random 5 drawn from
      the SAME candidate set the ranked rule picks from at each
      selection (the cheapest-third, F-scorable names), plain floor.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026, vs SPY.

Judged against the champion (published): validation $288.05 |
continuous $544.47 | placebo beats 18/20 validation (median $201.15)
and 19/20 continuous (median $308.81) | folds 4 wins / 7 | SPY net
$187.77 validation / $313.62 continuous (recomputed in-run as control).

Data: SEC EDGAR companyfacts + Yahoo prices, reused read-only from the
v4 caches (./data and ./value-momentum-honest-data under backtests/v4).
"""
import importlib.util
import json
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
MIN_SIGNALS = 7          # A1: a name needs >= 7 of 9 computable signals

def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

# ------------------------------------------- point-in-time fact series
def annual_rows(facts, chain):
    """Annual (fiscal-year) flow facts for a concept chain.
    chain = [(taxonomy, concept, prio), ...]. Keeps only facts whose
    reporting period spans 300-400 days (a reported fiscal year), the
    EY variant's trailing-annual rule. Returns (filed, end, val, prio)."""
    rows = []
    for taxonomy, concept, prio in chain:
        try:
            units = facts["facts"][taxonomy][concept]["units"]
        except KeyError:
            continue
        key = "USD" if "USD" in units else list(units)[0]
        for e in units[key]:
            if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
                continue
            if 300 <= _ord(e["end"]) - _ord(e["start"]) <= 400:
                rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows

def instant_rows(facts, chain):
    """Instant (balance-sheet / cover) facts for a concept chain,
    via the engine's own pit_series. Returns (filed, end, val, prio)."""
    rows = []
    for taxonomy, concept, prio in chain:
        rows += E.pit_series(facts, taxonomy, concept, prio=prio)
    return rows

def build_concept_rows(facts):
    """All F-score inputs for one ticker, as point-in-time row lists."""
    return {
        # flows (annual)
        "ni":   annual_rows(facts, [("us-gaap", "NetIncomeLoss", 2),
                                    ("us-gaap", "ProfitLoss", 1)]),
        "ocf":  annual_rows(facts, [("us-gaap", "NetCashProvidedByUsedInOperatingActivities", 2),
                                    ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", 1)]),
        "rev":  annual_rows(facts, [("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", 3),
                                    ("us-gaap", "SalesRevenueNet", 2),
                                    ("us-gaap", "Revenues", 1),
                                    ("us-gaap", "RevenuesNetOfInterestExpense", 0)]),
        "gp":   annual_rows(facts, [("us-gaap", "GrossProfit", 3)]),
        "cogs": annual_rows(facts, [("us-gaap", "CostOfRevenue", 2),
                                    ("us-gaap", "CostOfGoodsAndServicesSold", 1)]),
        # balance sheet (instant)
        "assets": instant_rows(facts, [("us-gaap", "Assets", 0)]),
        "ltd":    instant_rows(facts, [("us-gaap", "LongTermDebt", 4),
                                       ("us-gaap", "LongTermDebtNoncurrent", 3),
                                       ("us-gaap", "DebtLongtermAndShorttermCombinedAmount", 2),
                                       ("us-gaap", "DebtAndCapitalLeaseObligations", 1)]),
        "ca":     instant_rows(facts, [("us-gaap", "AssetsCurrent", 0)]),
        "cl":     instant_rows(facts, [("us-gaap", "LiabilitiesCurrent", 0)]),
        # shares at fiscal year-end (A4)
        "sh_end": instant_rows(facts, [("us-gaap", "CommonStockSharesOutstanding", 2),
                                       ("dei", "EntityCommonStockSharesOutstanding", 1)]),
        "sh_avg": annual_rows(facts, [("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", 0)]),
    }

# ------------------------------------------------------- F-score bundle
def _at_end(rows, e_ord, asof, tol=20):
    """Value of a concept FOR the fiscal period ending at e_ord, as
    known at asof: facts filed strictly before asof whose period end is
    within +/-tol days of e_ord; latest filed wins, then priority."""
    best = None
    for filed, end, val, prio in rows:
        if filed < asof and abs(_ord(end) - e_ord) <= tol:
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, val)
    return best[1] if best else None

def _fy_ends(ni_rows, asof):
    """(E_t, E_{t-1}, E_{t-2}) period-end ordinals as known at asof.
    FY_t = latest annual-NI period end among facts filed before asof
    AND filed within the engine's 548-day freshness gate. Prior years:
    annual-NI ends 300-560 days before the previous end, filed < asof."""
    fresh_cut = _ord(asof) - 548
    fresh = [r for r in ni_rows if r[0] < asof and _ord(r[0]) >= fresh_cut]
    if not fresh:
        return None
    e_t = max(_ord(r[1]) for r in fresh)

    def prev(e):
        cands = [_ord(r[1]) for r in ni_rows
                 if r[0] < asof and e - 560 <= _ord(r[1]) <= e - 300]
        return max(cands) if cands else None

    e_p = prev(e_t)
    e_pp = prev(e_p) if e_p is not None else None
    return e_t, e_p, e_pp

def _year_bundle(rows, e_ord, asof):
    if e_ord is None:
        return None
    rev = _at_end(rows["rev"], e_ord, asof)
    gp = _at_end(rows["gp"], e_ord, asof)
    if gp is None:
        cogs = _at_end(rows["cogs"], e_ord, asof)
        if rev is not None and cogs is not None:
            gp = rev - cogs
    sh = _at_end(rows["sh_end"], e_ord, asof)
    if sh is None:
        sh = _at_end(rows["sh_avg"], e_ord, asof)
    return {"ni": _at_end(rows["ni"], e_ord, asof),
            "ocf": _at_end(rows["ocf"], e_ord, asof),
            "rev": rev, "gp": gp,
            "assets": _at_end(rows["assets"], e_ord, asof),
            "ltd": _at_end(rows["ltd"], e_ord, asof),
            "ca": _at_end(rows["ca"], e_ord, asof),
            "cl": _at_end(rows["cl"], e_ord, asof),
            "sh": sh}

def fscore(rows, asof):
    """Piotroski F-score as known at asof.
    Returns (score, n_available, {signal: 0/1/None}) or None if the
    current fiscal year cannot be located at all."""
    ends = _fy_ends(rows["ni"], asof)
    if ends is None:
        return None
    e_t, e_p, e_pp = ends
    cur = _year_bundle(rows, e_t, asof)
    pri = _year_bundle(rows, e_p, asof)
    a_pp = _at_end(rows["assets"], e_pp, asof) if e_pp is not None else None
    if cur is None or cur["ni"] is None:
        return None
    a_t = cur["assets"]
    a_p = pri["assets"] if pri else None

    def ratio(num, den):
        return num / den if (num is not None and den is not None and den > 0) else None

    roa_t = ratio(cur["ni"], a_p)          # NI_t / beginning assets
    roa_p = ratio(pri["ni"], a_pp) if pri else None
    cfo_t = ratio(cur["ocf"], a_p)
    lev_t = ratio(cur["ltd"], (a_t + a_p) / 2.0) if (cur["ltd"] is not None
            and a_t is not None and a_p is not None) else None
    lev_p = ratio(pri["ltd"], (a_p + a_pp) / 2.0) if (pri and pri["ltd"] is not None
            and a_p is not None and a_pp is not None) else None
    cr_t = ratio(cur["ca"], cur["cl"])
    cr_p = ratio(pri["ca"], pri["cl"]) if pri else None
    gm_t = ratio(cur["gp"], cur["rev"])
    gm_p = ratio(pri["gp"], pri["rev"]) if pri else None
    turn_t = ratio(cur["rev"], a_p)
    turn_p = ratio(pri["rev"], a_pp) if pri else None

    def s1(x):        # simple level test
        return None if x is None else (1 if x > 0 else 0)

    def s_up(new, old):   # rising
        return None if (new is None or old is None) else (1 if new > old else 0)

    def s_dn(new, old):   # falling
        return None if (new is None or old is None) else (1 if new < old else 0)

    sig = {
        "ROA>0": s1(roa_t),
        "CFO>0": s1(cfo_t),
        "dROA": s_up(roa_t, roa_p),
        "ACCRUAL": None if (cfo_t is None or roa_t is None) else (1 if cfo_t > roa_t else 0),
        "dLEVER": s_dn(lev_t, lev_p),
        "dLIQUID": s_up(cr_t, cr_p),
        "EQ_OFFER": None if (not pri or cur["sh"] is None or pri["sh"] is None)
                    else (1 if cur["sh"] <= pri["sh"] else 0),
        "dMARGIN": s_up(gm_t, gm_p),
        "dTURN": s_up(turn_t, turn_p),
    }
    n_avail = sum(1 for v in sig.values() if v is not None)
    score = sum(v for v in sig.values() if v is not None)
    return score, n_avail, sig

# ------------------------------------------------------------- selection
SELECTION_CACHE = {}

def compute_selection(pb, d, data):
    """Everything the rule needs at selection date d (cached per date —
    ranked and placebo pots share the identical candidate set).
    Returns {pool: {t: bm}, third: [t], cand: {t: (score, navail, sig)},
             third_detail: {t: (score, navail) or None}, picks: [t]}."""
    if d in SELECTION_CACHE:
        return SELECTION_CACHE[d]
    pool = {}
    for t in UNIVERSE:
        be = E.pit_value(data["equity"].get(t, []), d)
        so = E.pit_value(data["shares"].get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        pool[t] = be[2] / mcap
    third, cand, third_detail = [], {}, {}
    if pool:
        n_third = -(-len(pool) // 3)     # ceil(N/3)
        third = sorted(pool, key=lambda t: -pool[t])[:n_third]
        for t in third:
            fs = fscore(data["concepts"][t], d)
            third_detail[t] = None if fs is None else (fs[0], fs[1])
            if fs is not None and fs[1] >= MIN_SIGNALS:
                cand[t] = fs
    picks = sorted(cand, key=lambda t: (-cand[t][0], -pool[t]))[:5]
    sel = {"pool": pool, "third": third, "cand": cand,
           "third_detail": third_detail, "picks": picks}
    SELECTION_CACHE[d] = sel
    return sel

# ------------------------------------------------------------------ engine
def run_pot_piotroski(pb, data, start, end, start_cash,
                      floor0, ladder, placebo_rng=None, label="",
                      quiet=False, record_pools=False):
    """Champion run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT the selection scoring block: pool = valid book-to-market
    names; candidates = F-scorable names in the cheapest third; ranked
    picks = top 5 by (F-score, then B/M); placebo picks = random sample
    of the same candidate set. Each pick's target is pot/5 (unfilled
    slots stay in cash). Execution, costs, floor, halt and liquidation
    mechanics are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, pool, third, fscores, picks)
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # list of (ticker, target_value) to execute at next open

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        """Execute at open of day d toward target dollar values (dict t->value).
        Sells first, then buys. Returns total cost."""
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        # sells / trims
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
        # buys
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
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from data filed before today
        if d in sel_set:
            sel = compute_selection(pb, d, data)
            pool, cand = sel["pool"], sel["cand"]
            if len(pool) >= 5 and len(cand) >= 1:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(cand),
                                               min(5, len(cand)))
                else:
                    picks = sel["picks"]
                if record_pools:
                    pools.append((d, sorted(pool), list(sel["third"]),
                                  {t: [cand[t][0], cand[t][1]] for t in cand},
                                  list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(pool)} third={len(sel['third'])} "
                          f"cand={len(cand)} picks={picks} pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
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
                    "halt_info": halt_info, "pools": pools, "curve": curve}
    # end of window: liquidate at final close
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

def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "final": round(r["final"], 2)}

def placebo_block(pb, data, ws, we, ranked_final, tag):
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_pot_piotroski(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                               placebo_rng=rng, label=f"{tag} PLACEBO s{seed}",
                               quiet=True)
        finals.append(rp["final"])
        prow.append({"seed": seed, "final": round(rp["final"], 2),
                     "ret_pct": round((rp["final"] / START_CASH - 1) * 100, 2),
                     "costs": round(rp["costs"], 2),
                     "orders": len(rp["trades"]), "halted": rp["halted"]})
        print(f"  [{tag}] placebo seed {seed:2d}: final=${rp['final']:,.2f} "
              f"halted={rp['halted']} orders={len(rp['trades'])}", flush=True)
    sfin = sorted(finals)
    n_beat = sum(1 for v in finals if ranked_final > v)
    dist = {"n_seeds": len(finals),
            "median_final": round(E._pct(sfin, 0.50), 2),
            "p25_final": round(E._pct(sfin, 0.25), 2),
            "p75_final": round(E._pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "mean_final": round(sum(finals) / len(finals), 2),
            "n_halted": sum(1 for r_ in prow if r_["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_minus_median": round(ranked_final - E._pct(sfin, 0.50), 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
            "rows": prow}
    print(f"== {tag} PLACEBO_DIST median=${dist['median_final']:,.2f} "
          f"p25=${dist['p25_final']:,.2f} p75=${dist['p75_final']:,.2f} "
          f"best=${dist['best_final']:,.2f} worst=${dist['worst_final']:,.2f} "
          f"halted={dist['n_halted']}/20 | ranked=${ranked_final:,.2f} "
          f"beats {n_beat}/20 ({dist['ranked_percentile']}th pct)", flush=True)
    return dist

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from champion
    equity_rows, shares_rows, concepts = {}, {}, {}
    missing = []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        concepts[t] = build_concept_rows(facts)
        thin = [k for k, v in concepts[t].items() if not v]
        if thin:
            missing.append((t, thin))
        print(f"{t}: equity={len(eq)} shares={len(so)} " +
              " ".join(f"{k}={len(v)}" for k, v in concepts[t].items()), flush=True)
        time.sleep(0.05)
    if missing:
        print("EMPTY CONCEPT SERIES:", missing, flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    data = {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"variant": "Piotroski F-score value: cheapest third by B/M, rank by "
                      "F-score (0-9, >=7 of 9 signals computable, missing = 0), "
                      "top-5, quarterly, plain -15% floor",
           "baseline": "promoted value+momentum (B/M + 12-1 momentum), plain floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "placebo_seeds": PLACEBO_SEEDS}

    # ---- (0) replication check: imported champion engine, published numbers
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47), ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION CHAMPION {tag}", quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}", flush=True)
    out["replication_champion"] = rep

    # ---- (1) ranked Piotroski runs
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_piotroski(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                              label=f"PIOTROSKI {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pools": r["pools"],
                                "trades": r["trades"]}
        print(f"== PIOTROSKI {tag} final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f} "
              f"| maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (2) placebo on both windows (same candidate sets as ranked)
    out["placebo_VALIDATION"] = placebo_block(pb, data, VAL[0], VAL[1],
                                              ranked["VALIDATION"], "VALIDATION")
    out["placebo_FULL"] = placebo_block(pb, data, FULL[0], FULL[1],
                                        ranked["FULL"], "FULL")

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_piotroski(pb, data, fs, fe, START_CASH, FLOOR0, LADDER,
                               label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: PIOTROSKI ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"FOLD RECORD: {out['fold_record']} (champion: 4 wins, 3 losses)", flush=True)

    # ---- (4) selection coverage: candidate counts + signal availability
    cov = {"n_selection_dates": len(SELECTION_CACHE),
           "pool_sizes": {}, "third_sizes": {}, "cand_counts": {},
           "signal_availability": {}, "pick_fscores": []}
    sig_tot, sig_avail = {}, {}
    for d, sel in sorted(SELECTION_CACHE.items()):
        cov["pool_sizes"][d] = len(sel["pool"])
        cov["third_sizes"][d] = len(sel["third"])
        cov["cand_counts"][d] = len(sel["cand"])
        for t, fs in sel["cand"].items():
            for name, v in fs[2].items():
                sig_tot[name] = sig_tot.get(name, 0) + 1
                if v is not None:
                    sig_avail[name] = sig_avail.get(name, 0) + 1
        for t in sel["picks"]:
            if t in sel["cand"]:
                cov["pick_fscores"].append([d, t, sel["cand"][t][0], sel["cand"][t][1]])
    cov["signal_availability"] = {k: [sig_avail.get(k, 0), sig_tot[k]]
                                  for k in sorted(sig_tot)}
    out["coverage"] = cov
    print(f"COVERAGE: {cov['n_selection_dates']} selection dates; "
          f"cand counts {sorted(set(cov['cand_counts'].values()))}; "
          f"signal availability {cov['signal_availability']}", flush=True)

    with open(os.path.join(HERE, "piotroski-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


# ============================================================ V9 MODULE
# CLAUDE-RULES PROTECTION SPEC v9 — the ONLY change vs the original
# script above (copied verbatim). Episode 1: plain -15% floor from the
# $100 start, identical to Terry's rule. On FIRST halt: liquidate
# exactly as the original engine does, sit in cash 90 calendar days,
# then RESTART with the remaining cash at the next regular decision
# point (next quarterly selection date). Episode 2 floor: -15% from
# the RESTART balance. On SECOND halt: run ends permanently.
# Everything else byte-identical. Ranked pots only; no placebos.

def _v9_ord(dstr):
    from datetime import date as _d
    return _d(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def run_v9(pb, data, start, end, start_cash=100.0):
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_piotroski(pb, data, start, end, start_cash, floor1,
                           LADDER, label="V9 EP1", quiet=True)
    out = {"final": r1["final"], "costs": r1["costs"],
           "curve": list(r1["curve"]), "halted": r1["halted"],
           "ep1_final": r1["final"], "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        return out
    liq = r1["end"]
    cash = r1["final"]
    day90 = _v9_ord(r1["halted"]) + 90
    restart = None
    for cand in E.quarter_selection_dates(pb, start, end):
        if _v9_ord(cand) >= day90:
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
    r2 = run_pot_piotroski(pb, data, restart, end, cash, floor2,
                           LADDER, label="V9 EP2", quiet=True)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def main_v9():
    import glob as _glob
    his = json.load(open(_glob.glob(os.path.join(
        HERE, "..", "..", "v6", "piotroski", "*-results.json"))[0]))
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows, concepts = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                          E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        concepts[t] = build_concept_rows(facts)
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)
    data = {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}
    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    detail = {}

    def do_window(tag, ws, we, his_rec):
        if his_rec["halted"] is None:
            wc = his_rec["diag"]["worst_close"]
            print(f"V9 {tag}: IDENTICAL — floor never fired (worst close ${wc})", flush=True)
            return {"final": his_rec["final"], "status": "identical — floor never fired",
                    "restarts": [], "second_halt": None,
                    "worst_close": wc, "worst_close_date": his_rec["diag"]["worst_close_date"]}
        r = run_v9(pb, data, ws, we)
        assert round(r["ep1_final"], 2) == his_rec["final"], \
            f"EP1 replication mismatch {tag}: {r['ep1_final']} vs {his_rec['final']}"
        worst = min([v for _, v in r["curve"]] + [r["final"]])
        print(f"V9 {tag}: his=${his_rec['final']} v9=${r['final']:,.2f} restarts={r['restarts']} second_halt={r['second_halt']}", flush=True)
        return {"final": round(r["final"], 2),
                "status": "second halt — run ended" if r["second_halt"] else ("restarted once" if r["restarts"] else "halted, no in-window restart — ended in cash"),
                "restarts": r["restarts"], "second_halt": r["second_halt"],
                "worst_close": round(worst, 2)}

    detail["continuous"] = do_window("FULL", FULL[0], FULL[1], his["ranked_FULL"])
    detail["validation"] = do_window("VALIDATION", VAL[0], VAL[1], his["ranked_VALIDATION"])
    folds = []
    for hf in his["folds"]:
        y = hf["year"]
        fs, fe = hf["start"], hf["end"]
        if hf["halted"] is None:
            folds.append({"year": y, "his_final": hf["final"], "v9_final": hf["final"],
                          "halted_his": None, "restarts": [], "second_halt": None})
            print(f"V9 FOLD {y}: IDENTICAL (no halt)", flush=True)
        else:
            r = run_v9(pb, data, fs, fe)
            assert round(r["ep1_final"], 2) == hf["final"], f"FOLD {y} EP1 mismatch {r['ep1_final']} vs {hf['final']}"
            folds.append({"year": y, "his_final": hf["final"], "v9_final": round(r["final"], 2),
                          "halted_his": hf["halted"], "restarts": r["restarts"],
                          "second_halt": r["second_halt"]})
            print(f"V9 FOLD {y}: his=${hf['final']} v9=${r['final']:,.2f} restarts={r['restarts']}", flush=True)
    comp_his = 100.0
    comp_v9 = 100.0
    for f in folds:
        comp_his *= f["his_final"] / 100.0
        comp_v9 *= f["v9_final"] / 100.0
    worsts = [100.0 - detail["continuous"]["worst_close"],
              100.0 - detail["validation"]["worst_close"]]
    out = {"slug": "piotroski", "name": "Piotroski F-Score",
           "status": "partial-rerun",
           "his": {"continuous_final": his["ranked_FULL"]["final"],
                   "validation_final": his["ranked_VALIDATION"]["final"]},
           "v9": {"continuous_final": detail["continuous"]["final"],
                  "validation_final": detail["validation"]["final"],
                  "continuous_status": detail["continuous"]["status"],
                  "validation_status": detail["validation"]["status"],
                  "restarts": detail["continuous"]["restarts"] + detail["validation"]["restarts"],
                  "folds_note": f"his fold-compounded ${round(comp_his,2)} (record 4/7 vs SPY) -> v9 fold-compounded ${round(comp_v9,2)}; per-fold detail in detail.folds",
                  "worst_total_loss_pct": round(max(worsts), 2)},
           "notes": "Continuous halted under his rules 2020-03-12 at $88.10 and was re-run; validation never halted (worst close $97.30 on 2023-03-13 vs $85 floor) so it is identical by construction and was not re-run. Halted folds 2020 and 2022 re-run; other folds identical.",
           "detail": {"continuous": detail["continuous"], "validation": detail["validation"],
                      "folds": folds, "fold_compounded_his": round(comp_his, 2),
                      "fold_compounded_v9": round(comp_v9, 2)}}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE V9")


if __name__ == "__main__":
    main_v9()
