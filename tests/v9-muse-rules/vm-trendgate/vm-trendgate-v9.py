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
# ============================================================ V9 MODULE
# "CLAUDE-RULES PROTECTION SPEC v9" - this copy only. The ONLY change vs
# the original v5 script is the protection module (the *_v9 wrapper
# below, which calls the original engine unchanged for each episode):
#   - Episode 1: plain -15% floor from the $100 start ($85.00), identical
#     to Terry's rule. On FIRST halt: liquidate exactly as the original
#     engine does, sit in cash 90 calendar days (counted from the
#     liquidation date), then RESTART with the remaining cash at the
#     strategy's next regular decision point after day 90.
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND halt:
#     the run ends permanently.
#   - If halt + 90 days runs past the window/fold end (no regular
#     decision point remains in-window), the run ends in cash.
# Everything else is byte-identical: universe, signals, parameters
# (vol-scaling / trend-gate parameters are SIGNAL, not protection -
# untouched), costs 0.10%/side + $0.01/sell, windows, $100 start.
# Scope (per spec): ranked pots only, no placebos. Windows/folds where
# the original recorded run never fired the floor are NOT re-run - they
# are identical under v9 by construction and are logged from the
# original results JSON. This script writes ONLY v9-results.json next
# to itself. Simulation only.
# ============================================================

def run_pot_v9(pb, equity_rows, shares_rows, start, end, start_cash=100.0,
               label=""):
    """One window under v9, wrapping the original run_pot_gated (gate
    logic untouched - it is signal, not protection)."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_gated(pb, equity_rows, shares_rows, start, end, start_cash,
                       floor1, [], label=label + " EP1", quiet=True)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "gate_log": list(r1["gate_log"]),
           "restarts": [], "second_halt": None, "episodes": 1,
           "ep1_final": r1["final"], "ep1_end": r1["end"]}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    from datetime import date as _date
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in E.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_pot_gated(pb, equity_rows, shares_rows, restart, end, cash,
                       floor2, [], label=label + " EP2", quiet=True)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    out["gate_log"] += list(r2["gate_log"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


HIS_FOLDS = [
    {"year": 2020, "final": 83.62, "spy_net": 117.47, "halted": "2020-03-09"},
    {"year": 2021, "final": 118.43, "spy_net": 127.97, "halted": None},
    {"year": 2022, "final": 98.33, "spy_net": 81.42, "halted": None},
    {"year": 2023, "final": 115.90, "spy_net": 125.28, "halted": None},
    {"year": 2024, "final": 144.32, "spy_net": 125.46, "halted": None},
    {"year": 2025, "final": 103.52, "spy_net": 116.81, "halted": None},
    {"year": 2026, "final": 95.29, "spy_net": 101.17, "halted": None},
]


def main():
    pb, equity_rows, shares_rows = build_inputs()
    print("inputs built", flush=True)

    # Continuous fired under his rules (halted 2020-03-20, final $79.36)
    # -> re-run. Validation never fired (worst close $94.01 on
    # 2023-05-31, halted=None) -> identical, NOT re-run.
    rc = run_pot_v9(pb, equity_rows, shares_rows, CONT[0], CONT[1], 100.0,
                    label="V9 CONTINUOUS")
    print(f"CONT EP1 final=${rc['ep1_final']:.2f} halted={rc['halted']} "
          f"liq={rc['ep1_end']} (recorded his: $79.36, halt 2020-03-20)",
          flush=True)
    assert abs(rc["ep1_final"] - 79.36) < 0.02 and rc["halted"] == "2020-03-20", \
        "continuous episode-1 reproduction failed"
    print(f"V9 CONTINUOUS final=${rc['final']:.2f} restarts={rc['restarts']} "
          f"second_halt={rc['second_halt']}", flush=True)

    rf = run_pot_v9(pb, equity_rows, shares_rows, "2020-01-01", "2020-12-31",
                    100.0, label="V9 FOLD 2020")
    print(f"FOLD2020 EP1 final=${rf['ep1_final']:.2f} halted={rf['halted']} "
          f"(recorded his: $83.62, halt 2020-03-09)", flush=True)
    assert abs(rf["ep1_final"] - 83.62) < 0.02 and rf["halted"] == "2020-03-09", \
        "fold episode-1 reproduction failed"
    print(f"V9 FOLD 2020 final=${rf['final']:.2f} restarts={rf['restarts']} "
          f"second_halt={rf['second_halt']}", flush=True)

    v9_folds = []
    for f in HIS_FOLDS:
        if f["year"] == 2020:
            v9_folds.append({"year": 2020, "final": round(rf["final"], 2),
                             "spy_net": f["spy_net"],
                             "beat_spy": rf["final"] > f["spy_net"],
                             "halted_ep1": rf["halted"],
                             "second_halt": rf["second_halt"]})
        else:
            v9_folds.append({"year": f["year"], "final": f["final"],
                             "spy_net": f["spy_net"],
                             "beat_spy": f["final"] > f["spy_net"],
                             "halted_ep1": f["halted"], "second_halt": None})
    his_wins = sum(1 for f in HIS_FOLDS if f["final"] > f["spy_net"])
    v9_wins = sum(1 for f in v9_folds if f["beat_spy"])
    def comp(folds):
        c = 100.0
        for f in folds:
            c *= f["final"] / 100.0
        return round(c, 2)
    his_min = min([v for _, v in rc["curve"]] + [rc["ep1_final"]])
    v9_min = min([v for _, v in rc["curve"]] + [rc["final"]] +
                 [v for _, v in rf["curve"]] + [rf["final"]])
    restarts = ([{"window": "continuous", **x} for x in rc["restarts"]] +
                [{"window": "fold-2020", **x} for x in rf["restarts"]])
    out = {
        "slug": "vm-trendgate",
        "name": "Value+Momentum + SPY vs 200-day trend gate (Faber/MOP)",
        "status": "rerun",
        "his": {"continuous_final": 79.36, "validation_final": 163.79},
        "v9": {
            "continuous_final": round(rc["final"], 2),
            "validation_final": 163.79,
            "continuous_status": (f"halted episode 1 on {rc['halted']} (liquidated {rc['ep1_end']} at "
                                  f"${round(rc['ep1_final'],2)}); restarted; "
                                  f"second_halt={rc['second_halt']}"),
            "validation_status": "identical - floor never fired (worst close $94.01 on 2023-05-31 vs $85 floor; halted=None in v5 results)",
            "restarts": restarts,
            "folds_note": (f"His folds 2/7 vs SPY (fold-compounded ${comp(HIS_FOLDS)}); "
                           f"v9 folds {v9_wins}/7 vs SPY (fold-compounded ${comp(v9_folds)}). "
                           f"Only the 2020 fold fired under his rules (halt 2020-03-09, final $83.62); "
                           f"re-run under v9: final ${round(rf['final'],2)}. Folds 2021-2026 never fired, unchanged."),
            "worst_total_loss_pct": round(v9_min / 100.0 * 100 - 100, 2),
        },
        "notes": ("Simulation only. Validation NOT re-run: floor never fired there under his rules. "
                  "Continuous and 2020-fold episode 1 reproduced the recorded his-rules results "
                  "($79.36 halt 2020-03-20; $83.62 halt 2020-03-09) before restarts were applied. "
                  f"His worst total loss from $100: {round(his_min/100*100-100,2)}% (continuous episode-1 curve/liquidation). "
                  f"V9 fold detail: {v9_folds}"),
        "detail": {"continuous_v9": {"ep1_final": round(rc["ep1_final"], 2),
                                     "final": round(rc["final"], 2),
                                     "costs": round(rc["costs"], 2),
                                     "orders": rc["orders"],
                                     "restarts": rc["restarts"],
                                     "second_halt": rc["second_halt"],
                                     "gate_log": rc["gate_log"]},
                   "fold_2020_v9": {"ep1_final": round(rf["ep1_final"], 2),
                                    "final": round(rf["final"], 2),
                                    "restarts": rf["restarts"],
                                    "second_halt": rf["second_halt"]},
                   "his_fold_compounded": comp(HIS_FOLDS),
                   "v9_fold_compounded": comp(v9_folds),
                   "his_fold_record": f"{his_wins} wins, {7-his_wins} losses vs SPY",
                   "v9_fold_record": f"{v9_wins} wins, {7-v9_wins} losses vs SPY"},
    }
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
