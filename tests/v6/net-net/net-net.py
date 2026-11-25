#!/usr/bin/env python3
"""
NET-NET GRAHAM VALUE — Terry's AI stock app. Simulation only.
NO parameter tuning: the spec below is run ONCE, as described, and judged
against the promoted champion's published numbers.

THE STRATEGY (Graham, "Security Analysis" / "The Intelligent Investor"):
buy stocks trading below their net current asset value,
    NCAV = current assets - TOTAL liabilities (all of them, incl. LT debt),
diversified across qualifying names; Graham's stricter bargain test was
price below 2/3 of NCAV per share. Sell discipline in the published form:
exit when price reaches NCAV, or after roughly two years. In this
program's quarterly-rebalance format the exit rule is mechanical: a name
is held only while it still qualifies at a quarterly selection; the
quarterly census below records every name's price/NCAV ratio so the
2/3 threshold is reported alongside the plain test.

PROGRAM FORMAT (stated in advance, run once):
  - Universe: the champion's honest point-in-time top-30 as of Nov 2016.
  - At each quarterly selection (first trading day of Jan/Apr/Jul/Oct),
    compute point-in-time NCAV per share for every name from EDGAR facts
    FILED strictly before the selection date, under the engine's
    ~18-month filed-freshness gate (548 days):
        CA  = AssetsCurrent as filed
        TL  = Liabilities as filed (see A1 for the identity fallback)
        sh  = the champion's shares-outstanding chain, verbatim
        px  = selection-day close (the engine's adjusted price series,
              the same series the champion's B/M uses)
    A name QUALIFIES if NCAV/share > 0 and px < NCAV/share.
  - Portfolio: if any names qualify, hold them equal-weight — the pot is
    divided equally across the qualifying names actually held (fully
    invested across qualifiers), max 5, ranked by discount depth
    (1 - px/(NCAV/share), deepest first). If NONE qualify, the pot sits
    in cash — that is the strategy, not a failure of the test.
    Rebalance at next open.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no ladder).
    Close at/below floor -> liquidate at next open, run ends.
  - Pot: $100 only (Terry's current standard).
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20, VALIDATION
    2023-01-03 -> 2026-11-20, fresh-$100 yearly folds 2020-2026 vs SPY.
  - CENSUS: the qualification test is also computed at EVERY quarterly
    selection date the program's price cache supports inside
    2016-11-21 -> 2026-11-20 (38 dates, 2017-07-03 -> 2026-10-01; the
    cache begins 2017-06-01, so the 2017-01 and 2017-04 quarterly dates
    have no prices — the same data wall every program test faces).

FORCED ADAPTATIONS (data-driven, decided from a coverage probe BEFORE
any qualification result was seen; documented, not tuned):
  A1. TOTAL LIABILITIES fallback. Seven of the 30 names (AMZN, WMT, VZ,
      DIS, INTC, KO — zero filed facts; T — 3 facts) never tag a total
      `Liabilities` concept in companyfacts; they file the components
      and the total `LiabilitiesAndStockholdersEquity`. Rule: use
      `Liabilities` as filed where point-in-time available; otherwise
      TL = LiabilitiesAndStockholdersEquity - StockholdersEquity (the
      balance-sheet identity, both inputs taken point-in-time under the
      same filed/freshness discipline; the equity series is the
      champion's own book-equity chain). The source (filed vs derived)
      is recorded per name per quarter in the census. This is the same
      species of fallback as Piotroski's A2 (gross profit via
      revenue - COGS): it makes names scorable, it does not favor an
      outcome — NCAV still subtracts ALL liabilities either way.
  A2. UNSCORABLE NAMES. BRK-B, JPM, BAC, WFC file UNCLASSIFIED balance
      sheets — no AssetsCurrent concept exists for them at any date
      (0 filed facts). They can never be scored and are excluded,
      never patched (identical treatment to the Piotroski test).
      Visa is additionally unscorable in most quarters through the
      champion's own shares gate (its only EDGAR share facts were
      filed in 2009/2010 — a decade stale; the engine rejects them).

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) to
      the cent before any variant number is taken. SPY net control:
      $313.62 / $187.77.
  (1) CENSUS — qualification counts and closest misses, all 38 dates.
  (2) Ranked net-net: CONTINUOUS and VALIDATION windows.
  (3) WALK-FORWARD folds 2020-2026 vs SPY.
  (4) PLACEBO — only if the strategy actually trades enough for one to
      be meaningful; the decision and its reason are recorded in the
      results (with <=5 qualifiers the ranked set IS the qualifier set,
      and with zero trades there is nothing to randomize).

Judged against the champion (published): validation $288.05 |
continuous $544.47 | placebo beats 18/20 validation and 19/20
continuous | folds 4 wins / 7 | SPY net $187.77 / $313.62.

Data: SEC EDGAR companyfacts + Yahoo prices, reused read-only from the
v4 caches (./data and ./value-momentum-honest-data under backtests/v4).
"""
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
MAX_HOLD = 5

# ------------------------------------------------------------- NCAV core
def ncav_detail(pb, data, t, d):
    """Point-in-time NCAV test for ticker t at selection date d.
    Returns a detail dict, or None if the name is unscorable at d
    (missing current assets / liabilities / shares / price)."""
    ca = E.pit_value(data["ca"].get(t, []), d)
    so = E.pit_value(data["shares"].get(t, []), d)
    px = pb.close_on_or_before(t, d)
    if ca is None or so is None or px is None or so[2] <= 0:
        return None
    tl_hit = E.pit_value(data["liab"].get(t, []), d)
    if tl_hit is not None:
        tl, tl_source = tl_hit[2], "filed"
    else:
        le = E.pit_value(data["le"].get(t, []), d)
        eq = E.pit_value(data["equity"].get(t, []), d)
        if le is None or eq is None:
            return None
        tl, tl_source = le[2] - eq[2], "derived(assets-equity)"
    ncav = ca[2] - tl
    ncav_ps = ncav / so[2]
    ratio = (px / ncav_ps) if ncav_ps > 0 else None
    return {"ticker": t,
            "ca": ca[2], "ca_end": ca[1],
            "tl": tl, "tl_source": tl_source,
            "shares": so[2], "px": px,
            "ncav": ncav, "ncav_ps": ncav_ps,
            "ratio": ratio,
            "qualifies": bool(ncav_ps > 0 and px < ncav_ps),
            "qualifies_2_3": bool(ncav_ps > 0 and px < (2.0 / 3.0) * ncav_ps),
            "discount": (1.0 - ratio) if ratio is not None else None}

# ------------------------------------------------------------- selection
SELECTION_CACHE = {}

def compute_selection(pb, data, d):
    """All names' NCAV detail at d + the ranked qualifier picks (cached;
    ranked runs and the census share the identical computation)."""
    if d in SELECTION_CACHE:
        return SELECTION_CACHE[d]
    detail = {}
    for t in UNIVERSE:
        det = ncav_detail(pb, data, t, d)
        if det is not None:
            detail[t] = det
    quals = [det for det in detail.values() if det["qualifies"]]
    quals.sort(key=lambda det: -det["discount"])
    picks = [det["ticker"] for det in quals[:MAX_HOLD]]
    sel = {"detail": detail, "qualifiers": quals, "picks": picks}
    SELECTION_CACHE[d] = sel
    return sel

# ------------------------------------------------------------------ engine
def run_pot_netnet(pb, data, start, end, start_cash,
                   floor0, ladder, label="", quiet=False, record_pools=False):
    """Champion run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT the selection scoring block: qualifiers = point-in-time
    price < NCAV/share; picks = up to 5 deepest discounts; targets =
    pot / N across the N names held (fully invested across qualifiers);
    if no name qualifies, targets = {} and the pot moves to cash at the
    next open. Execution, costs, floor, halt and liquidation mechanics
    are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, n_scorable, qualifiers, picks)
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # dict ticker -> target value, executed at next open

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
            sel = compute_selection(pb, data, d)
            picks = sel["picks"]
            if record_pools:
                pools.append((d, len(sel["detail"]),
                              [q["ticker"] for q in sel["qualifiers"]],
                              list(picks)))
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}   # no qualifiers: move to cash at next open
            if not quiet:
                print(f"  [{label}] {d} scorable={len(sel['detail'])} "
                      f"qualifiers={[q['ticker'] for q in sel['qualifiers']]} "
                      f"picks={picks} pot=${pv:,.2f}", flush=True)
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

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from champion
    equity_rows, shares_rows = {}, {}
    ca_rows, liab_rows, le_rows = {}, {}, {}
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
        ca_rows[t] = E.pit_series(facts, "us-gaap", "AssetsCurrent")
        liab_rows[t] = E.pit_series(facts, "us-gaap", "Liabilities")
        le_rows[t] = E.pit_series(facts, "us-gaap", "LiabilitiesAndStockholdersEquity")
        print(f"{t}: equity={len(eq)} shares={len(so)} CA={len(ca_rows[t])} "
              f"Liab={len(liab_rows[t])} L+E={len(le_rows[t])}", flush=True)
        time.sleep(0.05)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    data = {"equity": equity_rows, "shares": shares_rows,
            "ca": ca_rows, "liab": liab_rows, "le": le_rows}

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"variant": "Net-net Graham value: point-in-time price < NCAV/share "
                      "(NCAV = AssetsCurrent - total Liabilities), max 5 "
                      "deepest discounts equal-weight, cash when none qualify, "
                      "quarterly, plain -15% floor",
           "baseline": "promoted value+momentum (B/M + 12-1 momentum), plain floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0}

    # ---- (0) replication check: imported champion engine, published numbers
    rep = {}
    for tag, (ws, we), published, spy_pub in (
            ("FULL", FULL, 544.47, 313.62), ("VALIDATION", VAL, 288.05, 187.77)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION CHAMPION {tag}", quiet=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "spy_net": round(s, 2), "spy_published": spy_pub,
                    "spy_match": round(s, 2) == spy_pub,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']} | "
              f"SPY=${s:,.2f} published=${spy_pub:,.2f} match={rep[tag]['spy_match']}",
              flush=True)
    out["replication_champion"] = rep

    # ---- (1) census: every quarterly selection date the cache supports
    census_dates = E.quarter_selection_dates(pb, "2016-11-21", "2026-11-20")
    census, census_summary = {}, []
    ever_qual, ever_qual23 = [], []
    best_ratio = None        # (ratio, date, ticker) min over NCAV>0 rows
    for d in census_dates:
        sel = compute_selection(pb, data, d)
        rows = {}
        for t in UNIVERSE:
            det = sel["detail"].get(t)
            if det is None:
                rows[t] = {"scorable": False}
                continue
            rows[t] = {"scorable": True,
                       "ca": det["ca"], "tl": det["tl"],
                       "tl_source": det["tl_source"],
                       "shares": det["shares"], "px": round(det["px"], 4),
                       "ncav_ps": round(det["ncav_ps"], 4),
                       "ratio": (round(det["ratio"], 4)
                                 if det["ratio"] is not None else None),
                       "qualifies": det["qualifies"],
                       "qualifies_2_3": det["qualifies_2_3"]}
            if det["ratio"] is not None and (best_ratio is None
                                             or det["ratio"] < best_ratio[0]):
                best_ratio = (det["ratio"], d, t)
            if det["qualifies"]:
                ever_qual.append((d, t, round(det["ratio"], 4)))
            if det["qualifies_2_3"]:
                ever_qual23.append((d, t, round(det["ratio"], 4)))
        pos = [det for det in sel["detail"].values() if det["ncav_ps"] > 0]
        pos.sort(key=lambda det: det["ratio"])
        closest = None
        if pos:
            c0 = pos[0]
            closest = {"ticker": c0["ticker"], "ratio": round(c0["ratio"], 4),
                       "px": round(c0["px"], 2), "ncav_ps": round(c0["ncav_ps"], 2)}
        else:
            neg = sorted(sel["detail"].values(), key=lambda det: -det["ncav_ps"])
            if neg:
                c0 = neg[0]
                closest = {"ticker": c0["ticker"], "ratio": None,
                           "px": round(c0["px"], 2),
                           "ncav_ps": round(c0["ncav_ps"], 2),
                           "note": "no positive NCAV this quarter; least-negative NCAV/share"}
        census[d] = rows
        census_summary.append(
            {"date": d, "n_scorable": len(sel["detail"]),
             "n_positive_ncav": len(pos),
             "n_qualify": sum(1 for det in sel["detail"].values() if det["qualifies"]),
             "n_qualify_2_3": sum(1 for det in sel["detail"].values()
                                  if det["qualifies_2_3"]),
             "closest_miss": closest})
        print(f"CENSUS {d}: scorable={len(sel['detail'])} posNCAV={len(pos)} "
              f"qualify={census_summary[-1]['n_qualify']} "
              f"qualify2/3={census_summary[-1]['n_qualify_2_3']} "
              f"closest={closest}", flush=True)
    out["census_dates"] = census_dates
    out["census_summary"] = census_summary
    out["census"] = census
    out["census_totals"] = {
        "n_dates": len(census_dates),
        "quarters_with_any_qualifier": sum(1 for s in census_summary if s["n_qualify"] > 0),
        "quarters_with_any_qualifier_2_3": sum(1 for s in census_summary
                                               if s["n_qualify_2_3"] > 0),
        "ever_qualified": ever_qual,
        "ever_qualified_2_3": ever_qual23,
        "closest_approach_ever": ({"ratio": round(best_ratio[0], 4),
                                   "date": best_ratio[1], "ticker": best_ratio[2]}
                                  if best_ratio else None)}

    # ---- (2) ranked net-net runs
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_netnet(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                           label=f"NETNET {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pools": r["pools"],
                                "trades": r["trades"]}
        print(f"== NETNET {tag} final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f} "
              f"| maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_netnet(pb, data, fs, fe, START_CASH, FLOOR0, LADDER,
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
        print(f"FOLD {y}: NETNET ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = START_CASH
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)
    print(f"FOLD RECORD: {out['fold_record']} (champion: 4 wins, 3 losses); "
          f"fold-compounded=${out['fold_compounded_final']:,.2f}", flush=True)

    # ---- (4) placebo decision (recorded, per task rule)
    n_trades = len(out["ranked_FULL"]["trades"]) + len(out["ranked_VALIDATION"]["trades"])
    n_qual_events = sum(1 for s in census_summary if s["n_qualify"] > 0)
    if n_trades == 0:
        placebo_note = ("NOT RUN: the ranked strategy placed zero trades in both "
                        "windows (no name ever qualified), so there is no return "
                        "distribution to randomize — a placebo of an all-cash pot "
                        "is the same all-cash pot 20 times.")
    elif n_qual_events <= 2:
        placebo_note = ("NOT RUN: qualifiers appeared in only "
                        f"{n_qual_events} quarter(s) across the whole census, and "
                        "whenever names qualify the rule holds ALL of them (up to "
                        "the 5-name cap) — there is no selection discretion for a "
                        "random draw to test against.")
    else:
        placebo_note = ("NOT RUN: whenever names qualify the rule holds ALL of "
                        "them (up to the 5-name cap), so the ranked set is the "
                        "qualifier set itself; a random-draw placebo has no "
                        "distinct selection to compare against.")
    out["placebo"] = {"run": False, "note": placebo_note,
                      "total_ranked_trades_both_windows": n_trades,
                      "quarters_with_qualifiers_in_census": n_qual_events}
    print(f"PLACEBO: {placebo_note}", flush=True)

    with open(os.path.join(HERE, "net-net-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
