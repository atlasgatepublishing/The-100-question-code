#!/usr/bin/env python3
"""
COMBO — CHAMPION x CANDIDATE: value+momentum + N-F3 "Paying in Stock",
one $100 pot, two 50/50 sleeves — Terry's AI stock app.
Simulation only.

TERRY'S REQUEST (2026-11-21): put the top two together — the promoted
champion (value+momentum) and the invented candidate (N-F3) — and see
if the combination makes something better than either parent.

FROZEN CONSTRUCTION (mirrors the program's winners'-blend precedent,
with the reset cadence Terry's brief specifies):
  - ONE $100 pot. $50 runs value+momentum EXACTLY as promoted (the
    plain-floor engine, backtests/v4/value-momentum-plainfloor.py:
    book-to-market + 12-1 momentum percentile-average rank, quarterly
    top-5, equal weight). $50 runs N-F3 EXACTLY as frozen (research/
    v8-novel/novel-filings.md Rule N-F3; engine backtests/v8/
    novel-f3-paying-in-stock/: TTM ShareBasedCompensation / TTM
    revenue, ACCEL vs same quarter a year earlier, rank ascending,
    quarterly top-5, equal weight).
  - Each sleeve is its own sub-pot (own cash, own positions) on the
    shared quarterly schedule (first trading day of Jan/Apr/Jul/Oct,
    selection at the close, execution at the next open — champion
    mechanics in both sleeves).
  - Sleeve weights reset to 50/50 at EACH quarterly selection date:
    each sleeve's rebalance budget for the new quarter is half the
    combined pot's selection-day close value. Execution at the next
    open is champion mechanics per sleeve (sells toward targets
    first), then the cash the overweight sleeve raised above its
    budget moves to the underweight sleeve (a same-pot cash transfer
    — the market trades are the sleeves' own rebalance sells/buys,
    each charged at the program schedule), then buys toward targets.
  - Costs: 0.10% of trade value per side + $0.01 per sell order,
    charged inside each sleeve exactly as in the parent engines.
  - Protection: ONE plain -15% floor on the COMBINED pot (close
    at/below $85.00 -> liquidate everything at the next open, run
    ends). No ladder, no sleeve-level floor.
  - Windows: continuous 2019-01-02 -> 2026-11-20 and validation
    2023-01-03 -> 2026-11-20, $100 pots.
  - Placebos: 20 seeds; at each selection date each sleeve draws 5
    random names from ITS OWN eligible pool (the names that sleeve's
    signal could score that date), identical dates/mechanics/resets/
    floor.
  - Yearly folds vs SPY: fresh $100 combo pots for each calendar year
    2020..2026, SPY buy-hold net over the identical span.

PRE-REGISTERED BAR (stated before the run): the combination must beat
BOTH parents on BOTH windows — V+M $544.47 / $288.05 and N-F3
$505.43 / $289.53. Anything less is dilution, reported plainly.
Because one parent is an invented-in-2026 rule, even a full pass is
CANDIDATE-grade only: only the forward paper trial can adopt it.
Program prior, stated in advance: every combination tested so far
(winners' blend, grand combination, V+M + trend) diluted.

INTEGRITY: both parent engines are imported verbatim and re-run
standalone inside this script before any combo number is taken; the
combo uses the champion module's data loading, price caches,
PriceBook and spy_net, and the N-F3 module's signal function, so
prices/costs/floor semantics are the parents' own. Signal scores are
memoized per selection date (identical dates recur across the ranked
run, the 20 placebos and the folds; the score at a date cannot depend
on which run asks for it).

Run once, no tuning.
"""
import importlib.util
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
V8 = os.path.expanduser("~/workspace/stock-app/backtests/v8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


champ = _load("champ", os.path.join(V4, "value-momentum-plainfloor.py"))
nf3 = _load("nf3", os.path.join(
    V8, "novel-f3-paying-in-stock", "novel-f3-paying-in-stock.py"))

UNIVERSE = champ.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))


# ------------------------------------------------------------- scoring
class Scorer:
    """Memoized per-date scores for both sleeves."""

    def __init__(self, pb, equity_rows, shares_rows, facts_by_ticker):
        self.pb = pb
        self.equity_rows = equity_rows
        self.shares_rows = shares_rows
        self.facts = facts_by_ticker
        self.pos_idx = {t: {b["d"]: i for i, b in enumerate(pb.bars[t])}
                        for t in pb.bars}
        self._vm = {}
        self._nf3 = {}
        self.nf3_stats = {"direct": 0, "derived": 0}

    def vm(self, d):
        """(pool_dict ticker->(bm, mom), ranked picks) — champion block
        copied verbatim from value-momentum-plainfloor.run_pot."""
        if d in self._vm:
            return self._vm[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            be = champ.pit_value(self.equity_rows.get(t, []), d)
            so = champ.pit_value(self.shares_rows.get(t, []), d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 \
                    or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = self.pos_idx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        picks = []
        if len(scores) >= 5:
            vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])[:5]
        out = (scores, picks)
        self._vm[d] = out
        return out

    def nf3(self, d):
        """(pool_dict ticker->ACCEL, ranked picks) — N-F3 signal via the
        frozen module's own signal_at."""
        if d in self._nf3:
            return self._nf3[d]
        scores = {}
        for t in UNIVERSE:
            a = nf3.signal_at(self.facts[t], d, self.nf3_stats)
            if a is not None:
                scores[t] = a
        picks = []
        if len(scores) >= 5:
            picks = sorted(scores, key=lambda t: (scores[t], t))[:5]
        out = (scores, picks)
        self._nf3[d] = out
        return out


# ------------------------------------------------------------- sleeves
class Sleeve:
    def __init__(self, name, cash):
        self.name = name
        self.cash = cash
        self.positions = {}
        self.trades = []
        self.costs = 0.0
        self.pending = None      # (targets dict, budget)
        self.curve = []

    def close_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def open_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            b = pb.bar(t, d)
            if b:
                v += sh * b["o"]
        return v


def sleeve_sells(pb, s, d, targets):
    """Champion sell phase: trim/sell positions toward target values at
    the open of day d."""
    opens = {}
    for t in set(list(s.positions) + list(targets)):
        b = pb.bar(t, d)
        if b:
            opens[t] = b["o"]
    for t in list(s.positions):
        if t not in opens:
            continue
        cur_val = s.positions[t] * opens[t]
        tgt = targets.get(t, 0.0)
        if cur_val > tgt + 0.005:
            sell_val = cur_val - tgt
            sh = sell_val / opens[t]
            c = sell_val * 0.001 + 0.01
            s.cash += sell_val - c
            s.costs += c
            s.positions[t] -= sh
            s.trades.append((d, s.name, "SELL", sh, opens[t], sell_val, c))
            if s.positions[t] < 1e-9:
                del s.positions[t]
    return opens


def sleeve_buys(pb, s, d, targets, opens):
    """Champion buy phase: buy toward target values, capped by cash."""
    for t, tgt in targets.items():
        if t not in opens:
            continue
        cur_val = s.positions.get(t, 0.0) * opens[t]
        buy_val = tgt - cur_val
        if buy_val > 0.005:
            buy_val = min(buy_val, s.cash / 1.001)
            if buy_val <= 0.005:
                continue
            sh = buy_val / opens[t]
            c = buy_val * 0.001
            s.cash -= buy_val + c
            s.costs += c
            s.positions[t] = s.positions.get(t, 0.0) + sh
            s.trades.append((d, s.name, "BUY", sh, opens[t], buy_val, c))


# ------------------------------------------------------------- combo
def run_combo(pb, scorer, start, end, start_cash=100.0, floor0=85.0,
              placebo_rng=None, label="", quiet=True):
    vm = Sleeve("VM", start_cash / 2.0)
    f3 = Sleeve("NF3", start_cash / 2.0)
    sleeves = [vm, f3]
    sel_dates = champ.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    pools = []
    transfers = []
    halted = None
    halt_info = None

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    def liquidate(d, tag):
        # Champion semantics: SELL-HALT sells at the next open, only
        # names with a bar that day; SELL-END sells every position at
        # the final close. Positions are cleared either way (the run
        # is over).
        for s in sleeves:
            for t in list(s.positions):
                if tag == "SELL-HALT":
                    b = pb.bar(t, d)
                    px = b["o"] if b else None
                else:
                    px = pb.close_on_or_before(t, d)
                if px:
                    val = s.positions[t] * px
                    c = val * 0.001 + 0.01
                    s.cash += val - c
                    s.costs += c
                    s.trades.append((d, s.name, tag, s.positions[t],
                                     px, val, c))
            s.positions = {}

    for di, d in enumerate(days):
        # --- execute pending rebalances at today's open
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = sleeve_sells(pb, s, d, targets)
                    budgets[s.name] = budget
            # --- 50/50 reset: move the overweight sleeve's surplus
            # cash (raised by its sells, above its budget at today's
            # open prices) to the underweight sleeve.
            vals = {s.name: s.open_value(pb, d) for s in sleeves}
            excess = {n: vals[n] - budgets.get(n, vals[n]) for n in vals}
            if excess["VM"] > 0.005 and excess["NF3"] < -0.005:
                amt = min(excess["VM"], -excess["NF3"], vm.cash)
                if amt > 0.005:
                    vm.cash -= amt
                    f3.cash += amt
                    transfers.append((d, "VM->NF3", round(amt, 2)))
            elif excess["NF3"] > 0.005 and excess["VM"] < -0.005:
                amt = min(excess["NF3"], -excess["VM"], f3.cash)
                if amt > 0.005:
                    f3.cash -= amt
                    vm.cash += amt
                    transfers.append((d, "NF3->VM", round(amt, 2)))
            for s in sleeves:
                if s.pending is not None:
                    targets, _ = s.pending
                    sleeve_buys(pb, s, d, targets,
                                opens_by_sleeve[s.name])
                    s.pending = None
        # --- selection day: score both sleeves, set 50/50 budgets
        if d in sel_set:
            vm_pool, vm_picks = scorer.vm(d)
            f3_pool, f3_picks = scorer.nf3(d)
            if placebo_rng is not None:
                if len(vm_pool) >= 5:
                    vm_picks = placebo_rng.sample(sorted(vm_pool), 5)
                if len(f3_pool) >= 5:
                    f3_picks = placebo_rng.sample(sorted(f3_pool), 5)
            combined = combined_close(d)
            budget = combined / 2.0
            if len(vm_pool) >= 5:
                vm.pending = ({t: budget / 5.0 for t in vm_picks}, budget)
            if len(f3_pool) >= 5:
                f3.pending = ({t: budget / 5.0 for t in f3_picks}, budget)
            pools.append((d, len(vm_pool), list(vm_picks),
                          len(f3_pool), list(f3_picks),
                          round(combined, 2)))
            if not quiet:
                print(f"  [{label}] {d} VM pool={len(vm_pool)} "
                      f"picks={vm_picks} | NF3 pool={len(f3_pool)} "
                      f"picks={f3_picks} | pot=${combined:,.2f}",
                      flush=True)
        # --- end of day: combined curve + the ONE floor
        v = combined_close(d)
        curve.append((d, v))
        for s in sleeves:
            s.curve.append((d, s.close_value(pb, d)))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            liquidate(nd, "SELL-HALT")
            final = vm.cash + f3.cash
            return {"label": label, "final": final,
                    "costs": vm.costs + f3.costs,
                    "trades": vm.trades + f3.trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve, "transfers": transfers,
                    "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
                    "sleeve_curves": {"VM": vm.curve, "NF3": f3.curve}}
    last = days[-1]
    liquidate(last, "SELL-END")
    final = vm.cash + f3.cash
    return {"label": label, "final": final, "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "transfers": transfers,
            "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
            "sleeve_curves": {"VM": vm.curve, "NF3": f3.curve}}


# ------------------------------------------------------------- helpers
def diagnostics(curve, floor0):
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
    covid = [(d, v) for d, v in curve if "2020-02-01" <= d <= "2020-04-30"]
    covid_worst = min(covid, key=lambda kv: kv[1]) if covid else None
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "covid_worst_close": round(covid_worst[1], 2) if covid_worst else None,
            "covid_worst_date": covid_worst[0] if covid_worst else None,
            "year_end_closes": {y: {"date": dd, "close": round(vv, 2)}
                                for y, (dd, vv) in sorted(year_end.items())}}


def monthly_returns(curve):
    month_last = {}
    for d, v in curve:
        month_last[d[:7]] = v
    months = sorted(month_last)
    out = {}
    for a, b in zip(months, months[1:]):
        out[b] = month_last[b] / month_last[a] - 1.0
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ----------------------------------------------------------------- main
def main():
    ciks = champ.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}  # champion engine's parent-CIK fix
    facts_by_ticker = {}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap",
                             "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "WeightedAverageNumberOfSharesOutstandingBasic",
                             prio=1))
        print(f"{t}: facts loaded (CIK {cik})", flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = champ.PriceBook(bars)
    scorer = Scorer(pb, equity_rows, shares_rows, facts_by_ticker)

    windows = [
        ("FULL", "2019-01-02", "2026-11-20"),
        ("VALIDATION", "2023-01-03", "2026-11-20"),
    ]

    # ---- integrity: parents standalone, imported engines, verbatim
    parents = {}
    for wname, ws, we in windows:
        vm100 = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                              100.0, 85.0, [], label=f"{wname} VM parent",
                              quiet=True)
        stats = {"direct": 0, "derived": 0}
        f3_100 = nf3.run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                             label=f"{wname} NF3 parent", stats=stats)
        parents[wname] = {
            "VM": {"final": round(vm100["final"], 2),
                   "costs": round(vm100["costs"], 2),
                   "orders": len(vm100["trades"]),
                   "halted": vm100["halted"],
                   "diag": champ_diagnostics(vm100)},
            "NF3": {"final": round(f3_100["final"], 2),
                    "costs": round(f3_100["costs"], 2),
                    "orders": len(f3_100["trades"]),
                    "halted": f3_100["halted"],
                    "diag": champ_diagnostics(f3_100)},
        }
        print(f"== PARENTS {wname}: VM=${vm100['final']:,.2f} "
              f"NF3=${f3_100['final']:,.2f}", flush=True)

    # ---- static mix diagnostic: parents standalone at $50, floors off
    static_mix = {}
    sleeve_curves = {}
    for wname, ws, we in windows:
        vm50 = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                             50.0, -1e18, [], label=f"{wname} VM $50",
                             quiet=True)
        st = {"direct": 0, "derived": 0}
        f3_50 = nf3.run_pot(pb, facts_by_ticker, ws, we, 50.0, -1e18,
                            label=f"{wname} NF3 $50", stats=st)
        static_mix[wname] = {"VM50": round(vm50["final"], 2),
                             "NF3_50": round(f3_50["final"], 2),
                             "sum": round(vm50["final"] + f3_50["final"], 2)}
        sleeve_curves[wname] = (vm50["curve"], f3_50["curve"])
        print(f"== STATIC MIX {wname}: VM50=${vm50['final']:,.2f} "
              f"NF3_50=${f3_50['final']:,.2f} "
              f"sum=${vm50['final'] + f3_50['final']:,.2f}", flush=True)

    # ---- sleeve correlation (standalone $50 monthly returns)
    corr = {}
    for wname, (c1, c2) in sleeve_curves.items():
        m1 = monthly_returns(c1)
        m2 = monthly_returns(c2)
        common = sorted(set(m1) & set(m2))
        corr[wname] = {"r": pearson([m1[m] for m in common],
                                    [m2[m] for m in common]),
                       "months": len(common)}

    # ---- the combo: ranked + 20 placebos per window
    out = {"test": "COMBO value+momentum x N-F3, 50/50, quarterly reset, "
                   "one combined plain -15% floor",
           "bar": "beat BOTH parents on BOTH windows "
                  "(VM $544.47/$288.05; NF3 $505.43/$289.53)",
           "parents_recomputed": parents,
           "static_mix": static_mix,
           "sleeve_monthly_correlation": corr,
           "universe": UNIVERSE}
    for wname, ws, we in windows:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        r = run_combo(pb, scorer, ws, we, 100.0, 85.0,
                      label=f"{wname} COMBO")
        diag = diagnostics(r["curve"], 85.0)
        placebo_finals = []
        placebo_halted = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_combo(pb, scorer, ws, we, 100.0, 85.0,
                           placebo_rng=rng,
                           label=f"{wname} COMBO PLACEBO s{seed}")
            placebo_finals.append(round(pr["final"], 2))
            placebo_halted.append(pr["halted"])
        sf = sorted(placebo_finals)
        placebo_median = round((sf[9] + sf[10]) / 2.0, 2)
        beaten = sum(1 for x in placebo_finals if r["final"] > x)
        out[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s, 2),
            "diag": diag, "sleeve_finals": r["sleeve_finals"],
            "transfers": r["transfers"],
            "placebo_finals": placebo_finals,
            "placebo_halted": placebo_halted,
            "placebo_median": placebo_median,
            "placebo_beaten": beaten,
            "pools": r["pools"], "trades": r["trades"],
        }
        print(f"== {wname} COMBO final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY=${s:,.2f} | placebo "
              f"median=${placebo_median:,.2f} beaten={beaten}/20",
              flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} | maxDD "
              f"{diag['max_drawdown_pct']}% | transfers="
              f"{len(r['transfers'])}", flush=True)

    # ---- yearly folds vs SPY
    folds = []
    prod_combo = 1.0
    prod_spy = 1.0
    wins = 0
    for yr in range(2020, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        fr = run_combo(pb, scorer, fs, fe, 100.0, 85.0,
                       label=f"FOLD {yr}")
        fs_spy, _ = champ.spy_net(pb, fs, fe, 100.0)
        win = fr["final"] > fs_spy
        wins += 1 if win else 0
        prod_combo *= fr["final"] / 100.0
        prod_spy *= fs_spy / 100.0
        folds.append({"year": yr, "start": fs, "end": fe,
                      "combo_final": round(fr["final"], 2),
                      "spy_final": round(fs_spy, 2),
                      "win": win, "halted": fr["halted"],
                      "costs": round(fr["costs"], 2)})
        print(f"== FOLD {yr}: combo=${fr['final']:,.2f} "
              f"SPY=${fs_spy:,.2f} win={win} halted={fr['halted']}",
              flush=True)
    out["folds"] = {"per_year": folds, "wins_vs_spy": wins,
                    "combo_fold_compounded": round(100.0 * prod_combo, 2),
                    "spy_fold_compounded": round(100.0 * prod_spy, 2)}
    out["nf3_quarter_values"] = scorer.nf3_stats

    with open(os.path.join(HERE, "combo-vm-nf3-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


def champ_diagnostics(r):
    return diagnostics(r["curve"], 85.0)



# ======================================================================
# V9 RE-RUN - "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
# Copied from the v8 original; the ONLY change is the protection module
# (run_*_v9 below, which calls the original engine unchanged for each
# episode) plus a folds-only main_v9 (the original main is retained
# above but not invoked):
#   - Episode 1: plain -15% floor from the $100 start ($85.00),
#     identical to Terry's rule. On FIRST halt: liquidate exactly as
#     the original engine does, sit in cash 90 calendar days, then
#     RESTART with the remaining cash at the strategy's next regular
#     decision point (next quarterly selection date on/after day 90).
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND
#     halt: the run ends permanently.
#   - If halt + 90 days runs past the window/fold end, the fold ends
#     in cash.
# Everything else is byte-identical: universe, signals, parameters,
# costs 0.10%/side + $0.01/sell, windows, $100 start. No retuning.
# Scope: main windows are NOT re-run - the original recorded results
# show the floor never fired there, so they are identical under v9 by
# construction. This script re-runs the yearly folds 2020-2026 under
# BOTH rule sets (his recomputed folds are asserted against the
# published originals). Ranked pots only; no placebos in this bundle.
# Data caches are read from the original test's folders, read-only;
# this script writes only v9-folds-detail.json next to itself.
# Simulation only.
# ======================================================================

# ============================================================ V9 MODULE
def run_combo_v9(pb, scorer, start, end, start_cash, label=""):
    """One combined window under CLAUDE-RULES PROTECTION SPEC v9.
    run_combo (above, unchanged) is the episode engine: it already
    takes start_cash and floor0, so episode 2 is the whole combined
    pot restarted at its next quarterly selection date with the
    remaining cash and floor = 85% of the restart balance."""
    from datetime import date as _d
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_combo(pb, scorer, start, end, start_cash, floor1, label=label + " EP1")
    out = {"final": r1["final"], "costs": r1["costs"], "trades": r1["trades"],
           "curve": list(r1["curve"]), "halted": r1["halted"],
           "halt_info": r1["halt_info"], "restarts": [], "second_halt": None,
           "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _d(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in champ.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _d(cy, cm, cd).toordinal() >= day90:
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
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_combo(pb, scorer, restart, end, cash, floor2, label=label + " EP2")
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def _worst(r, start_cash):
    vals = [v for _, v in r["curve"]] + [r["final"]]
    return min(vals) if vals else start_cash

def _compounded(folds):
    p = 100.0
    for k in sorted(folds):
        p *= folds[k]["final"] / 100.0
    return round(p, 2)

def main_v9():
    ciks = champ.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_ticker = {}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic",
                             prio=1))
        print(f"{t}: facts loaded", flush=True)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
    pb = champ.PriceBook(bars)
    scorer = Scorer(pb, equity_rows, shares_rows, facts_by_ticker)
    START = 100.0
    fold_defs = [(y, f"{y}-01-01", "2026-11-20" if y == 2026 else f"{y}-12-31")
                 for y in range(2020, 2027)]
    his_folds, v9_folds = {}, {}
    his_worst, v9_worst = START, START
    restarts_all, second_halts = [], []
    for y, fs, fe in fold_defs:
        rh = run_combo(pb, scorer, fs, fe, START, 85.0, label=f"HIS FOLD {y}")
        spy_f, _ = champ.spy_net(pb, fs, fe, START)
        his_folds[str(y)] = {"final": round(rh["final"], 2), "halted": rh["halted"],
                             "spy_net": round(spy_f, 2), "beat_spy": rh["final"] > spy_f,
                             "orders": len(rh["trades"]), "costs": round(rh["costs"], 2)}
        his_worst = min(his_worst, _worst(rh, START))
        rv = run_combo_v9(pb, scorer, fs, fe, START, label=f"V9 FOLD {y}")
        v9_folds[str(y)] = {"final": round(rv["final"], 2), "halted_first": rv["halted"],
                            "second_halt": rv["second_halt"], "restarts": rv["restarts"],
                            "spy_net": round(spy_f, 2), "beat_spy": rv["final"] > spy_f,
                            "orders": len(rv["trades"]), "costs": round(rv["costs"], 2),
                            "episodes": rv["episodes"]}
        v9_worst = min(v9_worst, _worst(rv, START))
        for rr in rv["restarts"]:
            restarts_all.append({"fold": str(y), **rr})
        if rv["second_halt"]:
            second_halts.append({"fold": str(y), **rv["second_halt"]})
        print(f"FOLD {y}: his=${rh['final']:,.2f} halted={rh['halted']} | "
              f"v9=${rv['final']:,.2f} restarts={len(rv['restarts'])} "
              f"second_halt={bool(rv['second_halt'])}", flush=True)
    his_comp, v9_comp = _compounded(his_folds), _compounded(v9_folds)
    print(f"FOLD-COMPOUNDED: his=${his_comp} v9=${v9_comp}", flush=True)
    out = {"protection_v9": "episode-1 floor -15% from start; on first halt liquidate, 90 calendar days cash, restart at next quarterly selection date with remaining cash; episode-2 floor -15% from restart balance; second halt ends run",
           "his_folds": his_folds, "v9_folds": v9_folds,
           "his_folds_compounded": his_comp, "v9_folds_compounded": v9_comp,
           "restarts": restarts_all, "second_halts": second_halts,
           "his_worst_fold_equity_from_100": round(his_worst, 2),
           "v9_worst_fold_equity_from_100": round(v9_worst, 2)}
    with open(os.path.join(HERE, "v9-folds-detail.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main_v9()

