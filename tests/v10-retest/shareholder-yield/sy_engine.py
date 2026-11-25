#!/usr/bin/env python3
"""
SHAREHOLDER YIELD (Faber, "Shareholder Yield," 2013) — Terry's AI stock
app, v6 wave. Simulation only. NO parameter tuning: the spec below is
run ONCE, as described, and judged against the promoted champion
(value+momentum, plain -15% floor).

THE RULE (Faber 2013, in this program's format):
  shareholder yield = dividend yield + net buyback yield
                      + net debt paydown yield
  computed point-in-time for every scorable name in the honest universe,
  ranked descending; hold the top 5, equal weight; quarterly selection
  (first trading day of Jan/Apr/Jul/Oct), rebalance at next open.
  $100 pot, plain -15% floor ($85, no ladder), costs 0.10%/side +
  $0.01 per sell order — identical machinery to the champion's engine
  (~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py),
  imported and reused for all point-in-time EDGAR machinery, the
  replication check, and the SPY benchmark.

COMPONENTS (all from data FILED strictly before the selection date,
~18-month filed-freshness gate, exactly as the baseline engine):
  - Market cap = point-in-time shares outstanding (baseline merged
    series: dei cover page > us-gaap CommonStockSharesOutstanding >
    WeightedAverageNumberOfSharesOutstandingBasic) x selection-day
    close (raw price, see dividend method below).
  - Dividend yield = trailing fiscal-year dividends paid / market cap.
    Dividends-paid series merges, by priority: PaymentsOfDividends
    (total) > PaymentsOfDividendsCommonStock > DividendsCommonStockCash
    > PaymentsOfOrdinaryDividends; only facts whose period spans
    300-400 days (a reported fiscal year), the same trailing-annual
    rule as the program's earnings-yield variant. If NO annual
    dividends-paid fact passes the point-in-time gate, the component
    is 0 — the company paid no dividends in the trailing year (true
    of AMZN, BRK-B, NFLX for the whole window; of DIS while its
    dividend was suspended; of GOOGL/META before 2024). A missing
    dividend line is never treated as missing data, because a filer
    that paid dividends reports the line; the other two components
    still decide those names' ranks.
  - Net buyback yield = (shares_then - shares_now) / shares_then,
    where shares_now / shares_then are the point-in-time shares
    outstanding as known at the selection date and as known 365 days
    earlier (each lookup uses only facts filed before its own date).
    Positive issuance (dilution) counts negative, per Faber.
  - Net debt paydown yield = (net_debt_then - net_debt_now) / mcap_now.
    Total debt = LongTermDebtCurrent + LongTermDebtNoncurrent when
    both are filed with the same period end; otherwise the merged
    total-debt series (LongTermDebt > LongTermDebtAndCapitalLease-
    ObligationsIncludingCurrentPortion > LongTermDebtAndCapitalLease-
    Obligations > DebtAndCapitalLeaseObligations). Current-portion
    series merges LongTermDebtCurrent > DebtCurrent. Cash = merged
    series CashAndCashEquivalentsAtCarryingValue > CashAndDueFrom-
    Banks (the bank balance-sheet cash line) > Cash. Net debt =
    total debt - cash (negative = net cash). "Then" values use the
    same lookups as of 365 days before the selection date.
  - A name is scored only if shares (now and then), total debt (now
    and then), cash (now and then) and a price all exist point-in-
    time; otherwise it is excluded from that quarter's pool, never
    patched (the program's standing rule).

DIVIDEND CASH CREDITING — THE EXACT METHOD (a yield strategy judged
without its payouts is rigged against itself):
  - This study trades on RAW prices: split-adjusted but dividend-
    UNadjusted opens/closes taken from the same Yahoo chart payloads
    the baseline engine caches (its adjclose series is NOT used
    here), so no payout is embedded in prices and none is counted
    twice.
  - Dividend events come from those same payloads (events=div):
    ex-dividend date + cash amount per share (Yahoo reports amounts
    split-adjusted, consistent with the split-adjusted raw prices).
  - On each ex-dividend date, BEFORE any rebalance execution that
    day, the pot is credited in cash: (shares held at the prior
    trading day's close) x (dividend per share). Shares bought at
    the open on the ex-date do not receive that dividend; shares
    sold at the open on the ex-date do (they were held at the prior
    close). This is the market's own entitlement rule.
  - Credited cash sits in the pot (it counts toward the floor check
    like all pot value) and is deployed at the next quarterly
    rebalance, whose targets are set from total portfolio value.
  - No dividend withholding or tax is modeled.
  - Every credit is logged (date, ticker, shares, amount/share,
    dollars) in the results JSON; window totals are in the report.

BENCHMARK ASYMMETRY (stated, per instructions): the SPY figures
($187.77 validation / $313.62 continuous) are the program's standard
published benchmark — computed by the baseline engine's spy_net on
its price series, with no dividend cash ever credited to the
benchmark pot. The yield pot, by contrast, trades raw prices and
receives every payout as explicit cash. The champion's published
finals were likewise produced on the baseline's price series with
no explicit dividend crediting; only this study books payouts as
cash, because payouts are this strategy's entire claim.

Runs:
  (0) REPLICATION CHECK — imported baseline engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation).
  (1) Ranked shareholder yield: CONTINUOUS 2019-01-02 -> 2026-11-20
      and VALIDATION 2023-01-03 -> 2026-11-20.
  (2) PLACEBO: 20 seeds (1..20), random 5 from this strategy's own
      scored pool at each selection, BOTH windows, same dividend
      crediting, plain floor.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026,
      scored vs SPY net (baseline engine, same fold method as the
      program's other v5/v6 studies).

Judged against: champion V+M $288.05 validation / $544.47
continuous, placebo beats 18/20 validation (median $201.15) and
19/20 continuous (median $308.81), folds 4 wins / 7 vs SPY.
SPY net $187.77 validation / $313.62 continuous (recomputed in-run).

Data: SEC EDGAR companyfacts + Yahoo prices/dividend events, reused
read-only from the v4 caches (./data and ./value-momentum-honest-data
under backtests/v4). Nothing outside this folder is written.
"""
import importlib.util
import json
import os
import random
import time
from datetime import date as _date, timedelta

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

# ------------------------------------------------------- raw price data
def load_payload(ticker):
    """Same cache lookup order as the baseline engine's get_prices:
    v4/data first, then v4/value-momentum-honest-data. Read-only."""
    for sub in ("data", "value-momentum-honest-data"):
        p = os.path.join(V4, sub, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    raise RuntimeError(f"no cached payload for {ticker}")

def get_raw_bars_and_divs(ticker):
    """RAW bars: split-adjusted, dividend-UNadjusted open/close (the
    Yahoo quote series as-is). Dividend events: {ex_date: amount/share}."""
    j = load_payload(ticker)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        bars.append({"d": d, "o": (o if o else c), "c": c})
    bars.sort(key=lambda b: b["d"])
    divs = {}
    for v in res.get("events", {}).get("dividends", {}).values():
        d = time.strftime("%Y-%m-%d", time.gmtime(v["date"]))
        divs[d] = float(v["amount"])
    return bars, divs

# ------------------------------------------- trailing-annual fact series
def annual_series(facts, concept_prios):
    """(filed, end, val, prio) rows for flow concepts, only facts whose
    period spans 300-400 days (a reported fiscal year) — the trailing-
    annual rule of the program's earnings-yield / composite variants."""
    rows = []
    for concept, prio in concept_prios:
        try:
            units = facts["facts"]["us-gaap"][concept]["units"]
        except KeyError:
            continue
        key = "USD" if "USD" in units else list(units)[0]
        for e in units[key]:
            if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
                continue
            sy, sm, sd = int(e["start"][:4]), int(e["start"][5:7]), int(e["start"][8:10])
            ey_, em, ed = int(e["end"][:4]), int(e["end"][5:7]), int(e["end"][8:10])
            dur = _date(ey_, em, ed).toordinal() - _date(sy, sm, sd).toordinal()
            if 300 <= dur <= 400:
                rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows

def instant_series(facts, concept_prios):
    """(filed, end, val, prio) rows for balance-sheet (instant) concepts."""
    return [r for concept, prio in concept_prios
            for r in E.pit_series(facts, "us-gaap", concept, prio=prio)]

DIV_CONCEPTS = (("PaymentsOfDividends", 4),
                ("PaymentsOfDividendsCommonStock", 3),
                ("DividendsCommonStockCash", 2),
                ("PaymentsOfOrdinaryDividends", 1))
CUR_CONCEPTS = (("LongTermDebtCurrent", 2), ("DebtCurrent", 1))
NON_CONCEPTS = (("LongTermDebtNoncurrent", 1),)
TOT_CONCEPTS = (("LongTermDebt", 3),
                ("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentPortion", 2),
                ("LongTermDebtAndCapitalLeaseObligations", 2),
                ("DebtAndCapitalLeaseObligations", 1))
CASH_CONCEPTS = (("CashAndCashEquivalentsAtCarryingValue", 3),
                 ("CashAndDueFromBanks", 2),
                 ("Cash", 1))

def debt_value(rows, asof):
    """Total debt point-in-time: current + noncurrent with the same
    period end if both exist; else the merged total-debt series; else
    whichever part exists. Returns (end, value) or None."""
    cur = E.pit_value(rows["cur"], asof)
    non = E.pit_value(rows["non"], asof)
    if cur is not None and non is not None and cur[1] == non[1]:
        return (cur[1], cur[2] + non[2])
    tot = E.pit_value(rows["tot"], asof)
    if tot is not None:
        return (tot[1], tot[2])
    if non is not None:
        return (non[1], non[2])
    if cur is not None:
        return (cur[1], cur[2])
    return None

def year_ago(asof):
    y, m, d = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    return (_date(y, m, d) - timedelta(days=365)).isoformat()

# ------------------------------------------------------------------ engine
def run_pot_sy(pb, div_events, shares_rows, div_rows, debt_rows, cash_rows,
               start, end, start_cash, floor0, ladder,
               placebo_rng=None, label="", quiet=False, record_pools=False):
    """Baseline run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT: (a) prices are the RAW PriceBook, (b) the selection scoring
    block ranks by total shareholder yield, (c) dividend cash is
    credited on ex-dates per the method in the module docstring.
    Execution, costs, floor, halt and liquidation mechanics unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    div_credits = []  # (date, ticker, shares, amount_per_share, dollars)
    div_total = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, sorted list of scored tickers, picks)
    sy_detail = []  # (date, {ticker: (div_y, buyback_y, paydown_y, total)})
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
        # dividend crediting: ex-date today, shares held at prior close
        # (positions as they stand before today's trades) — see docstring
        for t in list(positions):
            amt = div_events.get(t, {}).get(d)
            if amt:
                dollars = positions[t] * amt
                cash += dollars
                div_total += dollars
                div_credits.append((d, t, positions[t], amt, dollars))
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from data filed before today
        if d in sel_set:
            d_then = year_ago(d)
            scores = {}
            detail = {}
            for t in UNIVERSE:
                so = E.pit_value(shares_rows.get(t, []), d)
                so_then = E.pit_value(shares_rows.get(t, []), d_then)
                px = pb.close_on_or_before(t, d)
                if so is None or so_then is None or px is None \
                        or so[2] <= 0 or so_then[2] <= 0:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                dv = debt_value(debt_rows[t], d)
                dv_then = debt_value(debt_rows[t], d_then)
                ca = E.pit_value(cash_rows.get(t, []), d)
                ca_then = E.pit_value(cash_rows.get(t, []), d_then)
                if dv is None or dv_then is None or ca is None or ca_then is None:
                    continue
                # dividend yield: trailing annual dividends paid; no
                # annual fact inside the gate -> 0 (none were paid)
                divf = E.pit_value(div_rows.get(t, []), d)
                div_paid = divf[2] if divf is not None else 0.0
                div_y = div_paid / mcap
                bb_y = (so_then[2] - so[2]) / so_then[2]
                nd_now = dv[1] - ca[2]
                nd_then = dv_then[1] - ca_then[2]
                pd_y = (nd_then - nd_now) / mcap
                total = div_y + bb_y + pd_y
                scores[t] = total
                detail[t] = (div_y, bb_y, pd_y, total)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sorted(scores, key=lambda t: -scores[t])[:5]
                if record_pools:
                    pools.append((d, sorted(scores), list(picks)))
                    sy_detail.append((d, {t: tuple(round(x, 5) for x in detail[t])
                                          for t in sorted(detail)}))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} pot=${pv:,.2f}", flush=True)
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
                    "halt_info": halt_info, "pools": pools, "curve": curve,
                    "dividends_total": div_total, "div_credits": div_credits,
                    "sy_detail": sy_detail}
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
            "halt_info": None, "pools": pools, "curve": curve,
            "dividends_total": div_total, "div_credits": div_credits,
            "sy_detail": sy_detail}

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

def placebo_block(pb, div_events, rows, ws, we, ranked_final, tag):
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_pot_sy(pb, div_events, *rows, ws, we, START_CASH, FLOOR0,
                        LADDER, placebo_rng=rng, label=f"{tag} PLACEBO s{seed}",
                        quiet=True)
        finals.append(rp["final"])
        prow.append({"seed": seed, "final": round(rp["final"], 2),
                     "ret_pct": round((rp["final"] / START_CASH - 1) * 100, 2),
                     "costs": round(rp["costs"], 2),
                     "dividends_total": round(rp["dividends_total"], 2),
                     "orders": len(rp["trades"]), "halted": rp["halted"]})
        print(f"  [{tag}] placebo seed {seed:2d}: final=${rp['final']:,.2f} "
              f"div=${rp['dividends_total']:,.2f} halted={rp['halted']} "
              f"orders={len(rp['trades'])}", flush=True)
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
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from baseline
    equity_rows, shares_rows = {}, {}
    div_rows, cash_rows, debt_rows = {}, {}, {}
    missing = []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        div_rows[t] = annual_series(facts, DIV_CONCEPTS)
        cash_rows[t] = instant_series(facts, CASH_CONCEPTS)
        debt_rows[t] = {"cur": instant_series(facts, CUR_CONCEPTS),
                        "non": instant_series(facts, NON_CONCEPTS),
                        "tot": instant_series(facts, TOT_CONCEPTS)}
        if not so or not cash_rows[t] or not (debt_rows[t]["cur"] or debt_rows[t]["non"] or debt_rows[t]["tot"]):
            missing.append((t, len(so), len(cash_rows[t]),
                            len(debt_rows[t]["cur"]), len(debt_rows[t]["non"]), len(debt_rows[t]["tot"])))
        print(f"{t}: shares={len(so)} annualDiv={len(div_rows[t])} cash={len(cash_rows[t])} "
              f"debtCur={len(debt_rows[t]['cur'])} debtNon={len(debt_rows[t]['non'])} debtTot={len(debt_rows[t]['tot'])}",
              flush=True)
        time.sleep(0.05)
    if missing:
        print("MISSING/THIN DATA:", missing, flush=True)

    # adjusted PriceBook (baseline engine) for replication + SPY benchmark
    bars_adj = {}
    for t in UNIVERSE + ["SPY"]:
        bars_adj[t] = E.get_prices(t)
    pb_adj = E.PriceBook(bars_adj)
    # raw PriceBook + dividend events for the yield strategy
    bars_raw, div_events = {}, {}
    for t in UNIVERSE + ["SPY"]:
        b, dv = get_raw_bars_and_divs(t)
        bars_raw[t] = b
        div_events[t] = dv
        print(f"{t}: raw bars {len(b)} {b[0]['d']}..{b[-1]['d']} div events={len(dv)}", flush=True)
    pb_raw = E.PriceBook(bars_raw)

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"strategy": "shareholder yield (Faber 2013): dividend yield + net buyback yield + net debt paydown yield, top-5, quarterly, equal weight",
           "baseline": "promoted value+momentum, plain -15% floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "placebo_seeds": PLACEBO_SEEDS,
           "dividend_method": "raw (split-adjusted, dividend-unadjusted) prices; on each ex-date, before that day's trades, cash += shares held at prior close x dividend/share (Yahoo events from the same cached chart payloads); credited cash deploys at the next quarterly rebalance; no withholding modeled",
           "benchmark_note": "SPY via baseline engine spy_net on its price series; no dividend cash is credited to the benchmark pot (asymmetry stated in the report)"}

    # ---- (0) replication check: imported baseline engine, published numbers
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47), ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb_adj, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION BASELINE {tag}", quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION baseline {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}", flush=True)
    out["replication_baseline"] = rep

    rows = (shares_rows, div_rows, debt_rows, cash_rows)

    # ---- (1) ranked shareholder-yield runs
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb_adj, ws, we, START_CASH)
        r = run_pot_sy(pb_raw, div_events, *rows, ws, we, START_CASH, FLOOR0,
                       LADDER, label=f"SHAREHOLDER-YIELD {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        pool_sizes = sorted({len(p[1]) for p in r["pools"]})
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "dividends_total": round(r["dividends_total"], 2),
                                "n_div_credits": len(r["div_credits"]),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pool_sizes_seen": pool_sizes,
                                "pools": r["pools"], "sy_detail": r["sy_detail"],
                                "div_credits": r["div_credits"],
                                "trades": r["trades"]}
        print(f"== SHAREHOLDER-YIELD {tag} final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} dividends=${r['dividends_total']:,.2f} "
              f"({len(r['div_credits'])} credits) orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY net=${s:,.2f} | pools={pool_sizes} "
              f"maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (2) placebo on both windows
    out["placebo_VALIDATION"] = placebo_block(pb_raw, div_events, rows, VAL[0], VAL[1],
                                              ranked["VALIDATION"], "VALIDATION")
    out["placebo_FULL"] = placebo_block(pb_raw, div_events, rows, FULL[0], FULL[1],
                                        ranked["FULL"], "FULL")

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_sy(pb_raw, div_events, *rows, fs, fe, START_CASH, FLOOR0,
                        LADDER, label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb_adj, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "dividends_total": round(fr["dividends_total"], 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: SY ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) "
              f"div=${fr['dividends_total']:,.2f} vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"FOLD RECORD: {out['fold_record']} (champion baseline: 4 wins, 3 losses)", flush=True)

    with open(os.path.join(HERE, "shareholder-yield-results.json"), "w") as f:
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


def run_v9(pb, div_events, rows, start, end, start_cash=100.0):
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_sy(pb, div_events, *rows, start, end, start_cash, floor1,
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
    r2 = run_pot_sy(pb, div_events, *rows, restart, end, cash, floor2,
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
        HERE, "..", "..", "v6", "shareholder-yield", "*-results.json"))[0]))
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    div_rows, cash_rows, debt_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                          E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        div_rows[t] = annual_series(facts, DIV_CONCEPTS)
        cash_rows[t] = instant_series(facts, CASH_CONCEPTS)
        debt_rows[t] = {"cur": instant_series(facts, CUR_CONCEPTS),
                        "non": instant_series(facts, NON_CONCEPTS),
                        "tot": instant_series(facts, TOT_CONCEPTS)}
        time.sleep(0.05)
    bars_raw, div_events = {}, {}
    for t in UNIVERSE + ["SPY"]:
        b, dv = get_raw_bars_and_divs(t)
        bars_raw[t] = b
        div_events[t] = dv
    pb_raw = E.PriceBook(bars_raw)
    rows = (shares_rows, div_rows, debt_rows, cash_rows)
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
        r = run_v9(pb_raw, div_events, rows, ws, we)
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
            r = run_v9(pb_raw, div_events, rows, fs, fe)
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
    out = {"slug": "shareholder-yield", "name": "Shareholder Yield (Faber)",
           "status": "rerun",
           "his": {"continuous_final": his["ranked_FULL"]["final"],
                   "validation_final": his["ranked_VALIDATION"]["final"]},
           "v9": {"continuous_final": detail["continuous"]["final"],
                  "validation_final": detail["validation"]["final"],
                  "continuous_status": detail["continuous"]["status"],
                  "validation_status": detail["validation"]["status"],
                  "restarts": detail["continuous"]["restarts"] + detail["validation"]["restarts"],
                  "folds_note": f"his fold-compounded ${round(comp_his,2)} (record 3/7 vs SPY) -> v9 fold-compounded ${round(comp_v9,2)}; per-fold detail in detail.folds",
                  "worst_total_loss_pct": round(max(worsts), 2)},
           "notes": "Both main windows halted under his rules (continuous 2020-03-23 at $88.56; validation 2023-10-12 at $84.56) and were re-run. Halted folds 2020 and 2023 re-run; the 2023 fold's next quarterly restart (2024-04-01) falls after the fold end, so that fold ends in cash under v9 too. Other folds identical.",
           "detail": {"continuous": detail["continuous"], "validation": detail["validation"],
                      "folds": folds, "fold_compounded_his": round(comp_his, 2),
                      "fold_compounded_v9": round(comp_v9, 2)}}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE V9")


if __name__ == "__main__":
    main_v9()
