#!/usr/bin/env python3
"""
VALUE + MOMENTUM + DANIEL & MOSKOWITZ (2016) PANIC-STATE GATE — Terry's AI
stock app. Simulation only. ONE pre-published variant, run ONCE, no tuning.

Baseline (promoted spec): the engine of
~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py, imported
verbatim (same honest point-in-time top-30 universe as of Nov 2016, same
EDGAR point-in-time rules with the ~18-month filed-freshness gate, same
book-to-market + 12-1 momentum percentile-rank scoring, quarterly top-5
equal weight, $100 pot, costs 0.10%/side + $0.01/sell, plain -15% floor
$85, no ladder). The pot loop below is a line-for-line copy of the
baseline run_pot with exactly ONE change, marked [GATE].

THE CHANGE — Daniel & Moskowitz (2016, JFE) panic-state gate, as
summarized in ~/workspace/stock-app/research/v5/crash-protection.md
(candidate 2). D&M: momentum crashes cluster in "panic states" —
post-decline markets with high volatility — and their dynamic strategy
scales exposure down in those states (mean forecast driven mainly by a
bear-market indicator interacted with volatility).

Gate definition (fixed before the run; nothing searched):
  Evaluated ONLY at each quarterly selection date d, from SPY (the
  program's market proxy), point-in-time:
    idx       = last SPY bar on/before d
    bear      = SPY close[idx] / close[idx-252] - 1 < 0
                (trailing 12-month market return negative)
    vol_now   = stdev of SPY daily log returns over the 60 trading days
                ending at idx, annualized (x sqrt(252))
    vol_ref   = median of that same 60-day realized-vol series over all
                windows ending on/before idx (expanding, point-in-time)
    PANIC     = bear AND vol_now > vol_ref
  When PANIC is ON at a selection date, that quarter's five equal-weight
  targets are scaled to 50% of pot value (each = pot x 0.50 / 5); the
  other half of the pot is held in cash. When OFF, exposure is 100%
  (baseline). The 0.50 scale was fixed a priori as the report's
  documented long-only de-risk ("hold part of the pot in cash this
  quarter"); it was NOT searched over any grid.

Adaptations the quarterly long-only format forces on the published rule
(documented per the assignment):
  1. D&M's crash lives mostly in the SHORT leg (past losers rebounding
     violently). A long-only pot cannot short, hedge, or flip; the only
     available de-risk is cutting long exposure to cash. Implemented as
     50% cash, not a position flip.
  2. D&M's dynamic strategy scales exposure CONTINUOUSLY by forecasts of
     momentum's conditional mean and variance (weights can exceed 1 or
     approach 0). A 5-stock quarterly book has too short/noisy a history
     to estimate those forecasts, and the pot cannot lever; the coarse
     binary state with a fixed 50% scale-down is the only implementable
     form (the crash-protection report says exactly this).
  3. The paper evaluates the state at high frequency; here it is
     evaluated ONLY at quarterly rebalance dates (per the assignment).
     A crash that begins and bottoms inside one quarter (Mar 2020) can
     never trigger the gate mid-quarter.
  4. Market proxy is SPY (split/dividend-adjusted), not the CRSP
     value-weighted index of the paper.
  5. "High volatility" is operationalized as above the point-in-time
     expanding MEDIAN of the market's own 60-day realized vol — a
     parameter-free stand-in for the paper's estimated conditional
     variance forecast. Sample stdev (ddof=1) used for both vol_now and
     every observation in the reference distribution.
  6. Placebo pots run the IDENTICAL gate (the state is a function of
     SPY only, so the gate series is literally the same for every pot
     in a window) — the comparison stays honest, per the report's
     warning that an overlay shifts the twins' distribution too.

Runs (all $100, plain floor $85):
  - REPLICATION: gate disabled -> must reproduce baseline ranked finals
    ($544.47 continuous, $288.05 validation) and the published plain-
    floor placebo/fold records before any gated number is trusted.
  - GATED ranked: continuous 2019-01-02 -> 2026-11-20 and validation
    2023-01-03 -> 2026-11-20.
  - GATED placebo: 20 seeds (1..20) on BOTH windows, identical gate.
  - GATED walk-forward folds: fresh $100 per calendar year 2020-2026
    vs SPY net, same protocol as vm-walkforward.py.
  - UNGATED controls (gate disabled) for placebo on both windows and
    all folds, so every gated number has its same-code control.

Data: read-only reuse of the v4 caches (SEC EDGAR companyfacts in
v4/data, Yahoo prices in v4/value-momentum-honest-data) via the imported
baseline module. Outputs are written ONLY to this folder.
"""
import importlib.util
import json
import math
import os
import random
import statistics
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
PLACEBO_SEEDS = list(range(1, 21))
FULL = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")
GATE_EXPOSURE = 0.50          # fixed a priori; NOT tuned
VOL_WIN = 60                  # trading days, realized-vol window
BEAR_WIN = 252                # trading days, trailing market return window


# ------------------------------------------------------------- panic state
def panic_states(pb, sel_dates):
    """D&M panic state per selection date, from SPY bars only.
    Returns {date: {panic, bear, mkt_ret_12m, vol_now, vol_ref}}."""
    bars = pb.bars["SPY"]
    dates = [b["d"] for b in bars]
    closes = [b["c"] for b in bars]
    logret = [None] + [math.log(closes[i] / closes[i - 1])
                       for i in range(1, len(closes))]

    def rvol(end_idx):
        seg = logret[end_idx - VOL_WIN + 1: end_idx + 1]
        return statistics.stdev(seg) * math.sqrt(252)

    # realized-vol series for every end index where it is defined
    vol_series = {}
    for i in range(VOL_WIN, len(closes)):
        vol_series[i] = rvol(i)

    out = {}
    for d in sel_dates:
        # last SPY bar on/before d
        idx = None
        for i, bd in enumerate(dates):
            if bd <= d:
                idx = i
            else:
                break
        if idx is None or idx < BEAR_WIN:
            out[d] = {"panic": False, "bear": None, "mkt_ret_12m": None,
                      "vol_now": None, "vol_ref": None,
                      "note": "insufficient SPY history"}
            continue
        mkt_ret = closes[idx] / closes[idx - BEAR_WIN] - 1.0
        bear = mkt_ret < 0
        vnow = vol_series[idx]
        hist = [vol_series[i] for i in range(VOL_WIN, idx + 1)]
        vref = statistics.median(hist)
        out[d] = {"panic": bool(bear and vnow > vref), "bear": bool(bear),
                  "mkt_ret_12m": round(mkt_ret, 4),
                  "vol_now": round(vnow, 4), "vol_ref": round(vref, 4),
                  "n_vol_obs": len(hist)}
    return out


# ------------------------------------------------------------ gated engine
def run_pot_gated(pb, equity_rows, shares_rows, start, end, start_cash,
                  floor0, ladder, panic_map=None, gate_on=True,
                  placebo_rng=None, label="", quiet=True):
    """Line-for-line copy of the baseline run_pot (value-momentum-
    plainfloor.py) with the single [GATE] change in the selection block.
    With gate_on=False it must reproduce the baseline to the cent."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    gate_log = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
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
                pv = portfolio_close(d)
                # [GATE] the ONLY change vs baseline: scale this
                # quarter's targets by the panic-state exposure.
                expo = 1.0
                if gate_on and panic_map is not None:
                    st = panic_map.get(d, {})
                    if st.get("panic"):
                        expo = GATE_EXPOSURE
                    gate_log.append({"date": d, "panic": bool(st.get("panic")),
                                     "bear": st.get("bear"),
                                     "mkt_ret_12m": st.get("mkt_ret_12m"),
                                     "vol_now": st.get("vol_now"),
                                     "vol_ref": st.get("vol_ref"),
                                     "exposure": expo})
                each = pv * expo / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} "
                          f"pot=${pv:,.2f} expo={expo}", flush=True)
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
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
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve,
                    "gate_log": gate_log}
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


def stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "year_end_closes": year_end,
            "gate_quarters_on": sum(1 for g in r["gate_log"] if g["panic"]),
            "gate_log": r["gate_log"]}


def placebo_block(pb, eq, sh, window, gate_on):
    ws, we = window
    sel = E.quarter_selection_dates(pb, ws, we)
    pmap = panic_states(pb, sel)
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_gated(pb, eq, sh, ws, we, START_CASH, FLOOR0, LADDER,
                           panic_map=pmap, gate_on=gate_on, placebo_rng=rng,
                           label=f"PLACEBO {'GATED' if gate_on else 'UNGATED'} seed {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  placebo {'gated' if gate_on else 'ungated'} seed {seed:2d}: "
              f"${pr['final']:,.2f} halted={pr['halted']}", flush=True)
    return finals, rows


def dist_block(finals, rows, ranked_final):
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below, "rows": rows}


def folds_block(pb, eq, sh, gate_on):
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        sel = E.quarter_selection_dates(pb, fs, fe)
        pmap = panic_states(pb, sel)
        fr = run_pot_gated(pb, eq, sh, fs, fe, START_CASH, FLOOR0, LADDER,
                           panic_map=pmap, gate_on=gate_on,
                           label=f"FOLD {y} {'GATED' if gate_on else 'UNGATED'}")
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": fst["return_pct"],
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"],
               "gate_quarters_on": fst["gate_quarters_on"],
               "gate_log": fst["gate_log"]}
        folds.append(row)
        print(f"  fold {y} {'gated' if gate_on else 'ungated'}: ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} beat={row['beat_spy']} "
              f"halted={row['halted']} gate_on_quarters={row['gate_quarters_on']}",
              flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    comp = 1.0
    for f in folds:
        comp *= f["final"] / START_CASH
    return folds, f"{wins} wins, {len(folds) - wins} losses vs SPY", round(comp * START_CASH, 2)


# --------------------------------------------------------------------- main
def main():
    pb, eq, sh = build_inputs()
    out = {"variant": "Daniel & Moskowitz (2016) panic-state gate, quarterly, "
                      "50% exposure when ON",
           "baseline_judgment": {"validation_final": 288.05,
                                 "continuous_final": 544.47,
                                 "placebo_validation": "18/20 (ladder-era honest run)",
                                 "placebo_continuous": "19/20 (plain floor)",
                                 "folds": "4/7 (2020 halted -16.38%)"}}

    # ---------- replication: gate disabled must reproduce the baseline
    print("== REPLICATION (gate disabled) ==", flush=True)
    rep = {}
    for name, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        sel = E.quarter_selection_dates(pb, ws, we)
        pmap = panic_states(pb, sel)
        r = run_pot_gated(pb, eq, sh, ws, we, START_CASH, FLOOR0, LADDER,
                          panic_map=pmap, gate_on=False, label=f"REP {name}")
        rep[name] = round(r["final"], 2)
        print(f"  replication {name}: ${r['final']:,.2f}", flush=True)
    out["replication_ranked_ungated"] = rep
    assert abs(rep["FULL"] - 544.47) < 0.01, f"FULL replication failed: {rep['FULL']}"
    assert abs(rep["VALIDATION"] - 288.05) < 0.01, f"VALIDATION replication failed: {rep['VALIDATION']}"
    print("  replication OK: baseline reproduced to the cent", flush=True)

    # ---------- ranked, gated vs ungated, both windows
    results = {}
    for name, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        sel = E.quarter_selection_dates(pb, ws, we)
        pmap = panic_states(pb, sel)
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        print(f"== {name} RANKED ==", flush=True)
        ru = run_pot_gated(pb, eq, sh, ws, we, START_CASH, FLOOR0, LADDER,
                           panic_map=pmap, gate_on=False, label=f"{name} UNGATED")
        rg = run_pot_gated(pb, eq, sh, ws, we, START_CASH, FLOOR0, LADDER,
                           panic_map=pmap, gate_on=True, label=f"{name} GATED")
        su, sg = stats(ru), stats(rg)
        print(f"  ungated ${su['final']:,.2f} | gated ${sg['final']:,.2f} | "
              f"SPY ${spy:,.2f} | gate ON {sg['gate_quarters_on']} quarters", flush=True)
        results[name] = {"window": [ws, we], "spy_net_final": round(spy, 2),
                         "ungated": su, "gated": sg,
                         "panic_states": pmap}
    out["ranked"] = results

    # ---------- placebo, both windows, gated + ungated control
    for name, window in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        print(f"== {name} PLACEBO ungated control ==", flush=True)
        fu, rowu = placebo_block(pb, eq, sh, window, gate_on=False)
        du = dist_block(fu, rowu, results[name]["ungated"]["final"])
        print(f"== {name} PLACEBO gated ==", flush=True)
        fg, rowg = placebo_block(pb, eq, sh, window, gate_on=True)
        dg = dist_block(fg, rowg, results[name]["gated"]["final"])
        out[f"placebo_{name.lower()}"] = {"ungated": du, "gated": dg}
        print(f"  {name} placebo ungated: median ${du['median']:,.2f} ranked "
              f"${du['ranked_final']:,.2f} beat {du['seeds_beaten']}/20 halted {du['halted_count']}/20",
              flush=True)
        print(f"  {name} placebo gated:   median ${dg['median']:,.2f} ranked "
              f"${dg['ranked_final']:,.2f} beat {dg['seeds_beaten']}/20 halted {dg['halted_count']}/20",
              flush=True)

    # ---------- walk-forward folds, gated + ungated control
    print("== FOLDS ungated control ==", flush=True)
    fu, recu, compu = folds_block(pb, eq, sh, gate_on=False)
    print("== FOLDS gated ==", flush=True)
    fg, recg, compg = folds_block(pb, eq, sh, gate_on=True)
    out["folds"] = {"ungated": {"rows": fu, "record": recu, "compounded_final": compu},
                    "gated": {"rows": fg, "record": recg, "compounded_final": compg}}
    print(f"  folds ungated: {recu}, compounded ${compu:,.2f}", flush=True)
    print(f"  folds gated:   {recg}, compounded ${compg:,.2f}", flush=True)

    with open(os.path.join(HERE, "vm-panicgate-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
