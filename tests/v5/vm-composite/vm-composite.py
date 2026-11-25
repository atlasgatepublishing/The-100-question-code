#!/usr/bin/env python3
"""
VALUE + MOMENTUM — COMPOSITE VALUE VARIANT — Terry's AI stock app.
Simulation only. NO parameter tuning: the spec below is run ONCE, as
described, and judged against the promoted baseline's published numbers.

One-variable change against the promoted spec (value leg = BOOK-TO-MARKET
only, engine in ~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py,
imported and reused verbatim for all machinery). THE ONLY CHANGE:
  - The value leg becomes a COMPOSITE: for each scored name, the value
    score is the AVERAGE of the three percentile ranks of
      (a) book-to-market          = StockholdersEquity / market cap
      (b) earnings yield          = trailing filed fiscal-year
                                    NetIncomeLoss / market cap
      (c) cash-flow yield         = trailing filed fiscal-year operating
                                    cash flow / market cap
    all from SEC EDGAR point-in-time filings (filed strictly before the
    selection date, ~18-month filed-freshness gate, same shares-outstanding
    fallback chain). Earnings and cash-flow use the EY variant's trailing-
    annual rule (period duration 300-400 days; NetIncomeLoss merged with
    ProfitLoss; operating cash flow = NetCashProvidedByUsedInOperating-
    Activities merged with its ContinuingOperations variant, lower prio).
  - The composite value score then combines with momentum EXACTLY as the
    baseline combined its single value leg: combined = (value + momentum
    percentile) / 2; hold top 5, equal weight.
  - A name must be scorable on ALL THREE value components (plus shares,
    price, momentum) to enter the pool; otherwise excluded, never patched
    (the standing rule). Negative earnings / negative operating cash flow
    / negative book equity keep their (negative) yields and rank at the
    bottom of that component, exactly as the EY variant treated negative
    NetIncomeLoss.

Everything else is the baseline, unchanged:
  - Universe: honest point-in-time top-30 as of Nov 2016 (baseline UNIVERSE).
  - Momentum: trailing 12-1 return. Quarterly selection (first trading
    day of Jan/Apr/Jul/Oct), rebalance at next open.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no ladder).
    Close at/below floor -> liquidate at next open, run ends.
  - Pot: $100 only (Terry's current standard).

Runs:
  (0) REPLICATION CHECK — the imported baseline engine must reproduce the
      published $544.47 (continuous) and $288.05 (validation) to the cent
      before any variant number is taken.
  (1) Ranked composite: CONTINUOUS 2019-01-02 -> 2026-11-20 and
      VALIDATION 2023-01-03 -> 2026-11-20.
  (2) PLACEBO: 20 seeds (1..20), random 5 from the composite's own scored
      pool at each selection, on BOTH windows, plain floor.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026
      (Jan 1 -> Dec 31; 2026 -> Nov 20), scored vs SPY net — the same
      fold methodology as vm-walkforward.py.

Baseline numbers judged against (published):
  validation $288.05 | continuous $544.47 | placebo beats 18/20 validation
  (median $201.15) and 19/20 continuous (median $308.81) | folds 4 wins / 7
  vs SPY | SPY net $187.77 validation / $313.62 continuous (recomputed
  in-run as a control).

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

# ------------------------------------------- trailing-annual fact series
def pit_series_income(facts):
    """Verbatim from value-momentum-ey.py: trailing ANNUAL NetIncomeLoss
    rows (filed, end, val, prio). NetIncomeLoss (prio 2) merged with
    ProfitLoss (prio 1); only facts whose period spans 300-400 days."""
    rows = []
    for concept, prio in (("NetIncomeLoss", 2), ("ProfitLoss", 1)):
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

def pit_series_ocf(facts):
    """Trailing ANNUAL operating cash flow rows (filed, end, val, prio).
    Same construction as pit_series_income: NetCashProvidedByUsedIn-
    OperatingActivities (prio 2) merged with NetCashProvidedByUsedIn-
    OperatingActivitiesContinuingOperations (prio 1); only facts whose
    period spans 300-400 days (a reported fiscal year)."""
    rows = []
    for concept, prio in (("NetCashProvidedByUsedInOperatingActivities", 2),
                          ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", 1)):
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

# ------------------------------------------------------------------ engine
def run_pot_composite(pb, equity_rows, income_rows, ocf_rows, shares_rows,
                      start, end, start_cash, floor0, ladder,
                      placebo_rng=None, label="", quiet=False,
                      record_pools=False):
    """Baseline run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT the selection scoring block: the single book-to-market value
    percentile is replaced by the composite value score = average of the
    book-to-market, earnings-yield and cash-flow-yield percentile ranks.
    Execution, costs, floor, halt and liquidation mechanics are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, sorted list of scored tickers, picks)
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
            scores = {}
            for t in UNIVERSE:
                be = E.pit_value(equity_rows.get(t, []), d)
                ni = E.pit_value(income_rows.get(t, []), d)
                ocf = E.pit_value(ocf_rows.get(t, []), d)
                so = E.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if (be is None or ni is None or ocf is None or so is None
                        or px is None or so[2] <= 0):
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                ey = ni[2] / mcap    # negative NI -> negative EY -> bottom of that rank
                cfy = ocf[2] / mcap  # negative OCF -> negative CFY -> bottom of that rank
                # momentum 12-1: close ~252 trading days ago vs ~21 days ago
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, ey, cfy, mom)
            if len(scores) >= 5:
                rb = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                re_ = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                rc = E.percentile_ranks({t: v[2] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[3] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    value_score = {t: (rb[t] + re_[t] + rc[t]) / 3.0 for t in scores}
                    combined = {t: (value_score[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                if record_pools:
                    pools.append((d, sorted(scores), list(picks)))
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

def placebo_block(pb, rows, ws, we, ranked_final, tag):
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_pot_composite(pb, *rows, ws, we, START_CASH, FLOOR0, LADDER,
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
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from baseline
    equity_rows, income_rows, ocf_rows, shares_rows = {}, {}, {}, {}
    missing = []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        inc = pit_series_income(facts)
        ocf = pit_series_ocf(facts)
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], income_rows[t], ocf_rows[t], shares_rows[t] = eq, inc, ocf, so
        if not eq or not inc or not ocf or not so:
            missing.append((t, len(eq), len(inc), len(ocf), len(so)))
        print(f"{t}: equity={len(eq)} annualNI={len(inc)} annualOCF={len(ocf)} shares={len(so)}", flush=True)
        time.sleep(0.05)
    if missing:
        print("MISSING/THIN DATA:", missing, flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    rows = (equity_rows, income_rows, ocf_rows, shares_rows)

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"variant": "composite value = avg percentile rank of B/M, earnings yield, cash-flow yield",
           "baseline": "promoted value+momentum, book-to-market only, plain -15% floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "placebo_seeds": PLACEBO_SEEDS}

    # ---- (0) replication check: imported baseline engine, published numbers
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47), ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION BASELINE {tag}", quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION baseline {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}", flush=True)
    out["replication_baseline"] = rep

    # ---- (1) ranked composite runs
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_composite(pb, *rows, ws, we, START_CASH, FLOOR0, LADDER,
                              label=f"COMPOSITE {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        pool_sizes = sorted({len(p[1]) for p in r["pools"]})
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pool_sizes_seen": pool_sizes,
                                "pools": r["pools"], "trades": r["trades"]}
        print(f"== COMPOSITE {tag} final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f} "
              f"| pools={pool_sizes} maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (2) placebo on both windows
    out["placebo_VALIDATION"] = placebo_block(pb, rows, VAL[0], VAL[1],
                                              ranked["VALIDATION"], "VALIDATION")
    out["placebo_FULL"] = placebo_block(pb, rows, FULL[0], FULL[1],
                                        ranked["FULL"], "FULL")

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_composite(pb, *rows, fs, fe, START_CASH, FLOOR0, LADDER,
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
        print(f"FOLD {y}: COMPOSITE ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"FOLD RECORD: {out['fold_record']} (baseline: 4 wins, 3 losses)", flush=True)

    with open(os.path.join(HERE, "vm-composite-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
