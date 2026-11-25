#!/usr/bin/env python3
"""
VALUE + MOMENTUM + INDEX TREND GATE — Terry's AI stock app. Simulation only.

ONE pre-published variant of the promoted value+momentum spec, run once,
no tuning. The variant is candidate #3 of
~/workspace/stock-app/research/v5/crash-protection.md: the portfolio-level
trend gate of Faber (2007) / Moskowitz-Ooi-Pedersen (2012) in its
single-index form.

BASELINE (unchanged): the promoted spec of
~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py — honest
point-in-time top-30 universe as of Nov 2016, quarterly top-5 by
book-to-market + 12-1 momentum (average of percentile ranks), equal
weight, $100 start, costs 0.10%/side + $0.01/sell, plain -15% floor
($85.00), point-in-time EDGAR with the ~18-month filed-freshness gate,
XOM CIK override 34088. The baseline's data loaders, PriceBook, scoring
helpers and SPY benchmark are imported verbatim from that module.

THE ONLY CHANGE (in run_pot_gated below, a copy of the baseline's
run_pot with one inserted block): at each quarterly selection date, the
gate is evaluated at the PRIOR QUARTER-END — the last SPY trading day
strictly before the selection date. If SPY's close on that day is below
its own trailing 200-trading-day moving average (computed on the same
adjusted-close series the engine uses for everything), the pot's
rebalance target is EMPTY: all holdings are sold at the next open and
the pot holds cash for the whole quarter. If SPY closed at or above the
average, the quarter runs exactly as baseline. Placebo pots receive the
identical gate (their random picks are still drawn every quarter, so
the RNG stream and the pick sequence match the baseline placebos pick
for pick in gate-on quarters).

Known caveat carried in from the literature survey (not discovered
here): a quarterly gate cannot react inside a quarter. COVID crashed
and recovered inside Q1-Q2 2020, and the post-2009 record of slow
moving-average gates is whipsaw-heavy; grinding bears (Q4 2018, 2022)
are the gate's home turf.

Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
2023-01-03 -> 2026-11-20, $100 pots; 20-seed placebo (seeds 1..20) on
both windows; walk-forward folds = fresh $100 per calendar year
2020-2026 (Jan 1 -> Dec 31; 2026 -> Nov 20), the vm-walkforward.py
methodology. Baseline judgments to beat: validation $288.05,
continuous $544.47, placebo 18/20 (validation) and 19/20 (continuous),
folds 4/7 with the 2020 fold halted 2020-03-09 at -16.38%.

Data: the baseline module's caches (SEC EDGAR companyfacts in the v4
./data dir, Yahoo prices in ./value-momentum-honest-data), read-only.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

spec = importlib.util.spec_from_file_location("vm_plainfloor", BASE_PATH)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")


# ------------------------------------------------------------------- gate
def spy_trend_gate(pb, sel_date):
    """Gate state for the quarter beginning at selection date sel_date,
    decided on prior-quarter-end data only: the last SPY bar strictly
    before sel_date. gate_on = SPY close >= its trailing 200-trading-day
    moving average (adjusted closes, the engine's price basis)."""
    bars = pb.bars["SPY"]
    idx = None
    for i, b in enumerate(bars):
        if b["d"] < sel_date:
            idx = i
        else:
            break
    if idx is None or idx < 199:
        return None
    window = bars[idx - 199: idx + 1]
    ma = sum(b["c"] for b in window) / 200.0
    close = bars[idx]["c"]
    return {"quarter_end": bars[idx]["d"], "spy_close": round(close, 2),
            "ma200": round(ma, 2), "gate_on": bool(close >= ma)}


# ------------------------------------------------- gated engine (copy of
# the baseline run_pot with ONLY the gate block inserted; marked GATE)
def run_pot_gated(pb, equity_rows, shares_rows, start, end, start_cash,
                  floor0, ladder, placebo_rng=None, label="", quiet=False,
                  record_pools=False):
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, sorted list of scored tickers, picks)
    gate_log = []   # (selection date, gate dict, picks) — GATE
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
            detail = {}
            for t in UNIVERSE:
                be = E.pit_value(equity_rows.get(t, []), d)
                so = E.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
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
                scores[t] = (bm, mom)
                detail[t] = (be, so, mcap)
            if len(scores) >= 5:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                if record_pools:
                    pools.append((d, sorted(scores), list(picks)))
                pv = portfolio_close(d)
                # ---- GATE: the only change vs the baseline engine ----
                g = spy_trend_gate(pb, d)
                gate_log.append({"selection_date": d,
                                 "quarter_end": g["quarter_end"] if g else None,
                                 "spy_close": g["spy_close"] if g else None,
                                 "ma200": g["ma200"] if g else None,
                                 "gate_on": g["gate_on"] if g else None,
                                 "picks": list(picks),
                                 "pot_at_selection": round(pv, 2)})
                if g is not None and not g["gate_on"]:
                    pending = {}   # GATE OFF: liquidate at next open, cash all quarter
                    if not quiet:
                        print(f"  [{label}] {d} GATE OFF (SPY {g['spy_close']} < "
                              f"MA200 {g['ma200']} at {g['quarter_end']}) -> cash",
                              flush=True)
                else:
                    each = pv / 5.0
                    pending = {t: each for t in picks}
                    if not quiet:
                        print(f"  [{label}] {d} pool={len(scores)} picks={picks} "
                              f"pot=${pv:,.2f} gate={'ON' if g else 'n/a'}",
                              flush=True)
                # ---- end GATE ----
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
                    "gate_log": gate_log}
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
            "gate_log": gate_log}


# ------------------------------------------------------------------ utils
def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def curve_stats(r):
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: round(v, 2) for y, (d, v)
                                in sorted(year_end.items())},
            "gate_log": r["gate_log"],
            "quarters_off": sum(1 for g in r["gate_log"]
                                if g["gate_on"] is False)}


def placebo_block(pb, eq, so, window, ranked_final):
    ws, we = window
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_gated(pb, eq, so, ws, we, START_CASH, FLOOR0, LADDER,
                           placebo_rng=rng, label=f"PLACEBO {seed}",
                           quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2),
                     "quarters_off": sum(1 for g in pr["gate_log"]
                                         if g["gate_on"] is False)})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {"seeds": PLACEBO_SEEDS,
            "median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below, "rows": rows}


# ------------------------------------------------------------------- main
def main():
    pb, eq, so = build_inputs()
    out = {"variant": "value+momentum + index trend gate (Faber/MOP single-index)",
           "gate_rule": "at each quarterly selection: if SPY close at prior "
                        "quarter-end < its 200-trading-day MA -> cash all "
                        "quarter; else baseline rebalance",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0}

    # ---- (0) replication check: ungated baseline engine, imported verbatim
    rep = {}
    for name, (ws, we), expect in (("continuous", CONT, 544.47),
                                   ("validation", VAL, 288.05)):
        r = E.run_pot(pb, eq, so, ws, we, START_CASH, FLOOR0, LADDER,
                      label=f"REPL {name}", quiet=True)
        rep[name] = {"final": round(r["final"], 2), "expected": expect,
                     "match": round(r["final"], 2) == expect}
        print(f"REPLICATION {name}: ungated=${r['final']:,.2f} "
              f"(expected ${expect:,.2f}) match={rep[name]['match']}", flush=True)
    out["replication_baseline_ungated"] = rep

    # ---- (1) gated ranked runs
    ranked = {}
    for name, (ws, we) in (("continuous", CONT), ("validation", VAL)):
        r = run_pot_gated(pb, eq, so, ws, we, START_CASH, FLOOR0, LADDER,
                          label=f"GATED {name}", quiet=True)
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        st = curve_stats(r)
        st.update({"start": ws, "end": we,
                   "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
                   "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2)})
        ranked[name] = st
        offs = [g["selection_date"] for g in r["gate_log"] if g["gate_on"] is False]
        print(f"GATED {name}: final=${r['final']:,.2f} ({st['return_pct']:+.2f}%) "
              f"maxDD={st['max_drawdown_pct']}% worst=${st['worst_close']} "
              f"orders={st['orders']} costs=${st['costs']} halted={r['halted']} "
              f"| SPY=${spy:,.2f} | quarters OFF: {offs}", flush=True)
    out["gated_ranked"] = ranked

    # ---- (2) gated placebos, both windows
    out["gated_placebo_continuous"] = placebo_block(
        pb, eq, so, CONT, ranked["continuous"]["final"])
    print(f"GATED PLACEBO CONT: median=${out['gated_placebo_continuous']['median']:,.2f} "
          f"ranked=${ranked['continuous']['final']:,.2f} = "
          f"{out['gated_placebo_continuous']['ranked_percentile']}th pctile, "
          f"beat {out['gated_placebo_continuous']['seeds_beaten']}/20", flush=True)
    out["gated_placebo_validation"] = placebo_block(
        pb, eq, so, VAL, ranked["validation"]["final"])
    print(f"GATED PLACEBO VAL: median=${out['gated_placebo_validation']['median']:,.2f} "
          f"ranked=${ranked['validation']['final']:,.2f} = "
          f"{out['gated_placebo_validation']['ranked_percentile']}th pctile, "
          f"beat {out['gated_placebo_validation']['seeds_beaten']}/20", flush=True)

    # ---- (3) gated walk-forward folds vs baseline folds
    base_wf = json.load(open(os.path.join(V4, "vm-walkforward-results.json")))
    base_folds = {f["year"]: f for f in base_wf["folds"]}
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_gated(pb, eq, so, fs, fe, START_CASH, FLOOR0, LADDER,
                           label=f"GATED FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        bf = base_folds[y]
        row = {"year": y, "start": fs, "end": fe,
               "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"],
               "quarters_off": fst["quarters_off"],
               "gate_log": fst["gate_log"],
               "baseline_final": bf["final"],
               "baseline_return_pct": bf["return_pct"],
               "baseline_beat_spy": bf["beat_spy"],
               "baseline_halted": bf["halted"],
               "delta_vs_baseline": round(fr["final"] - bf["final"], 2)}
        folds.append(row)
        print(f"GATED FOLD {y}: ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"halted={fr['halted']} qtrs_off={row['quarters_off']} | "
              f"baseline ${bf['final']:,.2f} ({bf['return_pct']:+.2f}%) "
              f"delta={row['delta_vs_baseline']:+.2f}", flush=True)
    out["gated_folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["gated_fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    # ---- (4) baseline reference block (for the report)
    base_cont_pl = base_wf["placebo_full_window"]
    out["baseline_reference"] = {
        "continuous_final": 544.47, "validation_final": 288.05,
        "continuous_placebo": {"median": base_cont_pl["median"],
                               "best": base_cont_pl["best"],
                               "worst": base_cont_pl["worst"],
                               "halted_count": base_cont_pl["halted_count"],
                               "seeds_beaten": base_cont_pl["seeds_beaten"],
                               "ranked_percentile": base_cont_pl["ranked_percentile"]},
        "validation_placebo": {"median": 201.15, "q1": 172.27, "q3": 231.58,
                               "best": 359.42, "worst": 84.23,
                               "seeds_beaten_by_baseline_ranked": 18},
        "fold_record": "4 wins, 3 losses vs SPY",
        "fold_2020": {"final": 83.62, "return_pct": -16.38,
                      "halted": "2020-03-09"}}

    with open(os.path.join(HERE, "vm-trendgate-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
