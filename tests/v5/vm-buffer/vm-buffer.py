#!/usr/bin/env python3
"""
VALUE + MOMENTUM (HONEST, PLAIN FLOOR) — RANK BUFFER (HYSTERESIS) VARIANT
Terry's AI stock app. Simulation only. No broker orders were placed.

ONE pre-published change to the promoted spec, run once as specified —
no tuning. The baseline engine is imported from
../../v4/value-momentum-plainfloor.py and reused verbatim (same honest
point-in-time top-30 universe as of Nov 2016, same EDGAR rules with the
~18-month filed-freshness gate, same book-to-market + 12-1 momentum
percentile-rank scoring, same costs 0.10%/side + $0.01/sell, same plain
-15% floor: $85.00 on the $100 pot, no ladder). The run_pot below is a
copy of the baseline's run_pot with ONLY the pick-selection block
changed (marked BUFFER CHANGE); every other line — execution, floor
check, liquidation, end-of-window handling — is identical.

THE CHANGE (standard published buffer / hysteresis rule for cutting
turnover): at each quarterly rebalance,
  - a current holding is SOLD only if its combined rank has fallen out
    of the top 10 (not merely out of the top 5);
  - freed slots (5 - kept) are filled by the highest-ranked non-held
    names, in rank order;
  - the resulting 5 names are held equal-weight, exactly as baseline.
Pre-specified edge rules (fixed before the run, not tuned after):
  - a held name that cannot be scored that quarter (missing point-in-time
    EDGAR fact or insufficient price history) has no rank, so it cannot
    be verified inside the top 10 and is sold — the baseline's treatment
    of unscored names is unchanged;
  - PLACEBO control uses the identical buffer mechanics on a RANDOM
    ordering of the scored pool each quarter (rng shuffle): held names
    inside the random top 10 are kept, slots filled by the highest
    random-ordered non-held names. Same machinery, same turnover rule,
    no ranking skill — so the placebo isolates the ranking, exactly as
    in the parent studies.

Runs ($100 pot only, per the task):
  (0) replication: baseline engine ranked on both windows — must
      reproduce $544.47 (continuous) and $288.05 (validation);
  (1) buffer ranked: continuous 2019-01-02 -> 2026-11-20 and
      validation 2023-01-03 -> 2026-11-20;
  (2) buffer placebo: 20 seeds (1..20) on both windows;
  (3) walk-forward: fresh $100 pot per calendar year 2020-2026 vs SPY
      net, same fold methodology as vm-walkforward.py.

Judged against the baseline's published numbers: validation $288.05,
continuous $544.47, placebo beaten 18/20 (validation) and 19/20
(continuous), folds 4 wins / 7 vs SPY, costs $2.19 (validation) and
$5.49 (continuous).

Data: same read-only caches as the parent studies (SEC EDGAR
companyfacts in v4/data, Yahoo prices in v4/value-momentum-honest-data),
loaded through the baseline module itself.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.abspath(os.path.join(HERE, "..", "..", "v4"))

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0          # plain -15% floor on $100, no ladder, ever
LADDER = []
BUFFER_KEEP_RANK = 10  # held name survives while its combined rank <= 10
PLACEBO_SEEDS = list(range(1, 21))
FULL = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")


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


# ------------------------------------------------- buffer engine (copy of
# baseline run_pot; ONLY the selection block differs — marked inline)
def run_pot_buffer(pb, equity_rows, shares_rows, start, end, start_cash,
                   floor0, ladder, placebo_rng=None, label="", quiet=False):
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity)
    pools = []      # (date, sorted scored pool, picks, kept, dropped)
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
                # ===== BUFFER CHANGE (the only change vs baseline) =====
                # Baseline: picks = top 5 by combined rank, unconditionally.
                # Buffer: rank ALL scored names (for the placebo, a random
                # ordering stands in for the ranking); keep any current
                # holding ranked inside the top BUFFER_KEEP_RANK; fill the
                # remaining slots with the highest-ranked non-held names.
                combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                if placebo_rng is not None:
                    order = sorted(scores)
                    placebo_rng.shuffle(order)  # random ordering, best first
                else:
                    order = sorted(combined, key=lambda t: -combined[t])
                rank = {t: i + 1 for i, t in enumerate(order)}
                held = list(positions)
                kept = [t for t in held
                        if t in rank and rank[t] <= BUFFER_KEEP_RANK]
                dropped = [t for t in held if t not in kept]
                slots = 5 - len(kept)
                fill = [t for t in order if t not in held][:slots]
                picks = kept + fill
                # ===== END BUFFER CHANGE =====
                pools.append((d, sorted(scores), list(picks),
                              list(kept), list(dropped)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} "
                          f"kept={kept} dropped={dropped} pot=${pv:,.2f}",
                          flush=True)
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
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d}


def placebo_block(pb, equity_rows, shares_rows, ws, we, ranked_final):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_buffer(pb, equity_rows, shares_rows, ws, we,
                            START_CASH, FLOOR0, LADDER, placebo_rng=rng,
                            label=f"BUFFER PLACEBO seed {seed}", quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"PLACEBO {ws[:4]} seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} orders={len(pr['trades'])} "
              f"costs=${pr['costs']:,.2f}", flush=True)
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
            "seeds_beaten": below,
            "rows": rows}


def main():
    pb, equity_rows, shares_rows = build_inputs()
    out = {"variant": "value+momentum rank buffer (keep while combined rank <= 10)",
           "engine": "value-momentum-plainfloor imported verbatim; only the "
                     "pick-selection block differs (buffer/hysteresis)",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "baseline_published": {
               "validation_final": 288.05, "validation_costs": 2.19,
               "validation_orders": 100,
               "continuous_final": 544.47, "continuous_costs": 5.49,
               "continuous_orders": 202,
               "placebo_validation": "ranked beat 18/20 (median $201.15)",
               "placebo_continuous": "ranked beat 19/20 (median $308.81)",
               "folds": "4 wins, 3 losses vs SPY (2020-2026)"}}

    # ---- (0) replication: baseline engine must reproduce published finals
    for wname, (ws, we) in [("FULL", FULL), ("VALIDATION", VALIDATION)]:
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, LADDER, label=f"REPL BASELINE {wname}",
                      quiet=True)
        out[f"replication_baseline_{wname.lower()}"] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"]}
        print(f"REPLICATION baseline {wname}: final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']}", flush=True)

    # ---- (1) buffer ranked on both windows
    ranked = {}
    for wname, (ws, we) in [("FULL", FULL), ("VALIDATION", VALIDATION)]:
        r = run_pot_buffer(pb, equity_rows, shares_rows, ws, we,
                           START_CASH, FLOOR0, LADDER,
                           label=f"BUFFER {wname}", quiet=True)
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "spy_net_final": round(spy, 2),
                   "name_changes_total": sum(len(p[4]) for p in r["pools"]),
                   "selections": len(r["pools"])})
        ranked[wname] = r
        out[f"buffer_{wname.lower()}"] = st
        print(f"BUFFER {wname}: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) maxDD={st['max_drawdown_pct']}% "
              f"orders={st['orders']} costs=${st['costs']:,.2f} "
              f"halted={r['halted']} | SPY net=${spy:,.2f}", flush=True)

    # ---- (2) buffer placebo on both windows
    for wname, (ws, we) in [("FULL", FULL), ("VALIDATION", VALIDATION)]:
        dist = placebo_block(pb, equity_rows, shares_rows, ws, we,
                             ranked[wname]["final"])
        out[f"buffer_placebo_{wname.lower()}"] = dist
        print(f"BUFFER PLACEBO {wname}: median=${dist['median']:,.2f} "
              f"Q1=${dist['q1']:,.2f} Q3=${dist['q3']:,.2f} "
              f"best=${dist['best']:,.2f} worst=${dist['worst']:,.2f} "
              f"halted={dist['halted_count']}/20 | RANKED "
              f"${dist['ranked_final']:,.2f} = {dist['ranked_percentile']}th "
              f"percentile (beat {dist['seeds_beaten']}/20)", flush=True)

    # ---- (3) walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_buffer(pb, equity_rows, shares_rows, fs, fe,
                            START_CASH, FLOOR0, LADDER,
                            label=f"BUFFER FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe,
               "final": fst["final"], "return_pct": fst["return_pct"],
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"BUFFER FOLD {y}: ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} "
              f"halted={row['halted']}", flush=True)
    out["buffer_folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["buffer_fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    # fold-compounded comparison
    comp_vm, comp_spy = 1.0, 1.0
    for f in folds:
        comp_vm *= 1 + f["return_pct"] / 100.0
        comp_spy *= 1 + f["spy_return_pct"] / 100.0
    out["buffer_fold_compounded"] = {
        "vm_final_on_100": round(100 * comp_vm, 2),
        "spy_final_on_100": round(100 * comp_spy, 2)}

    with open(os.path.join(HERE, "vm-buffer-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
