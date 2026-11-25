#!/usr/bin/env python3
"""
LOW VOLATILITY (LONG-ONLY) — Terry's AI stock app. Simulation only.

THE RULE (published long-only form of the low-volatility anomaly;
Frazzini-Pedersen BAB family, stripped to its long leg):
  - Universe: the honest point-in-time top-30 as of Nov 2016 (the champion
    value+momentum engine's UNIVERSE, unchanged).
  - At each quarterly selection (first trading day of Jan/Apr/Jul/Oct),
    rank the pool by trailing 12-month realized volatility — the standard
    deviation of the last 252 daily returns of split/dividend-adjusted
    closes, ending on the selection day.
  - Hold the 5 LOWEST-volatility names, equal weight, rebalance at next
    open. NO other signal: no value, no momentum, no quality. Pure low-vol.
  - $100 start, costs 0.10%/side + $0.01/sell (program standard), plain
    -15% floor ($85) only, no ladder.

ENGINE: mechanics copied verbatim from the champion engine
(~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py) —
selection dates, next-open execution, sell-then-buy rebalance, cost
schedule, floor/halt liquidation, end-of-window liquidation, daily close
curve. The ONLY change is the pick block: the pool gate is byte-identical
(EDGAR point-in-time scorability + >=253 bars of price history), and the
ranking is lowest trailing-252d realized vol instead of the value+
momentum percentile average. Placebo pots draw 5 random names from the
identical pool with identical mechanics (20 seeds), exactly as the
champion was judged.

JUDGMENT (program standard):
  - Continuous 2019-01-02 -> 2026-11-20 and validation 2023-01-03 ->
    2026-11-20, vs champion V+M ($544.47 / $288.05; placebo 19/20
    continuous, 18/20 validation; folds 4/7; max DD -36.26%) and SPY net
    ($313.62 / $187.77).
  - 20-seed placebo on both windows; walk-forward folds (fresh $100 pot
    per calendar year 2020-2026 vs SPY net).
  - Defense report: max drawdown and the COVID-window worst close — this
    family's published promise is defense, so it is graded on it.

A replication check runs FIRST: the imported champion engine must
reproduce $544.47 (continuous) and $288.05 (validation) to the cent
before any variant number is trusted.
"""
import importlib.util
import json
import math
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4_ENGINE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

spec = importlib.util.spec_from_file_location("vm_plainfloor", V4_ENGINE)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0            # plain -15% floor on $100, no ladder, ever
LADDER = []
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


# ------------------------------------------------------------- variant engine
# Copied from value-momentum-plainfloor.run_pot; ONLY the pick block differs
# (marked VARIANT). Everything else — execution, costs, floor, curve — is
# byte-identical mechanics.
def run_pot_lowvol(pb, equity_rows, shares_rows, start, end, start_cash,
                   floor0, ladder, placebo_rng=None, label="", quiet=False,
                   record_pools=False):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
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
            for t in UNIVERSE:
                # --- pool gate: IDENTICAL to the champion engine ---
                be = E.pit_value(equity_rows.get(t, []), d)
                so = E.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    continue
                # --- VARIANT: pure low-volatility score ---
                # trailing 252 daily simple returns ending on selection day
                closes = [bl[i]["c"] for i in range(didx - 252, didx + 1)]
                rets = [closes[i] / closes[i - 1] - 1.0
                        for i in range(1, len(closes))]
                scores[t] = statistics.stdev(rets)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    # 5 LOWEST realized volatility, equal weight
                    picks = sorted(scores, key=lambda t: scores[t])[:5]
                if record_pools:
                    pools.append((d, sorted(scores), list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} pot=${pv:,.2f}", flush=True)
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
    diag = E.diagnostics(r, FLOOR0)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "worst_close_above_floor": diag["worst_close_above_floor"],
            "covid_worst_close": diag["covid_worst_close"],
            "covid_worst_date": diag["covid_worst_date"],
            "year_end_closes": diag["year_end_closes"]}


def placebo_block(pb, equity_rows, shares_rows, ws, we, ranked_final, tag):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_lowvol(pb, equity_rows, shares_rows, ws, we, START_CASH,
                            FLOOR0, LADDER, placebo_rng=rng,
                            label=f"{tag} PLACEBO {seed}", quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  {tag} PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


def main():
    pb, equity_rows, shares_rows = build_inputs()
    out = {"strategy": "LOW VOLATILITY long-only: quarterly top-5 LOWEST "
                       "trailing-252d realized vol, honest top-30 pool, "
                       "$100, plain -15% floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0}

    # ---- (0) replication check: champion engine must reproduce published
    for tag, (ws, we), expect in (("FULL", FULL, 544.47),
                                  ("VALIDATION", VALIDATION, 288.05)):
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, LADDER, label=f"REPL {tag}", quiet=True)
        ok = abs(r["final"] - expect) < 0.005
        print(f"REPLICATION {tag}: champion=${r['final']:,.2f} "
              f"expected=${expect:,.2f} match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {
            "champion_final": round(r["final"], 2), "expected": expect,
            "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED — variant numbers untrusted")

    # ---- (1) ranked runs + SPY + placebo, both windows
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_lowvol(pb, equity_rows, shares_rows, ws, we, START_CASH,
                           FLOOR0, LADDER, label=f"{tag} LOWVOL",
                           quiet=True, record_pools=True)
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "picks_by_selection": [(d, p) for d, _, p in r["pools"]]})
        print(f"{tag} LOWVOL: final=${r['final']:,.2f} ({st['return_pct']:+.2f}%) "
              f"maxDD={st['max_drawdown_pct']}% orders={st['orders']} "
              f"costs=${st['costs']} halted={r['halted']} | SPY=${spy:,.2f}",
              flush=True)
        print(f"   worst close ${st['worst_close']} on {st['worst_close_date']} "
              f"(floor margin ${st['worst_close_above_floor']}) | COVID worst "
              f"${st['covid_worst_close']} on {st['covid_worst_date']}", flush=True)
        st["placebo"] = placebo_block(pb, equity_rows, shares_rows, ws, we,
                                      r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} best=${pl['best']:,.2f} "
              f"worst=${pl['worst']:,.2f} halted={pl['halted_count']}/20 | "
              f"RANKED ${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    # ---- (2) walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_lowvol(pb, equity_rows, shares_rows, fs, fe, START_CASH,
                            FLOOR0, LADDER, label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": fst["return_pct"],
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: LOWVOL ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) "
              f"vs SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) "
              f"beat={row['beat_spy']} maxDD={row['max_drawdown_pct']}% "
              f"halted={row['halted']}", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)

    with open(os.path.join(HERE, "low-volatility-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
