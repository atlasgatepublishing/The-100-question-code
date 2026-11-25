#!/usr/bin/env python3
"""
MIDPOINT SWITCH, DIRECTION B — champion first, blend second.
One $100 pot, Terry's rules. Simulation only.

TERRY'S IDEA (2026-11-21): the champion x N-F3 blend beat both
parents on the judging years but fell $12.08 behind the champion on
the long run. Terry's proposal: don't run the blend the whole way —
run the champion alone first, and switch into the blend halfway
through, before the blend's long-run drag sets in. The long run is
8 years (2019 -> 2026); the halfway mark is the start of 2023.

FROZEN SPEC (direction B, stated before the run):
  - ONE $100 pot under TERRY'S RULES: one plain -15% floor on the
    pot ($85.00, close at/below -> liquidate at next open, run
    ends). No ladder, no restart.
  - PHASE 1 (2019-01-02 -> switch): value+momentum alone on the
    full $100, EXACTLY as promoted (plain-floor engine:
    book-to-market + 12-1 momentum percentile-average rank,
    quarterly top-5, equal weight).
  - SWITCH: at the first quarterly selection date on or after
    2023-01-01 (the halfway mark of the 2019->2026 window), the
    pot splits into the 50/50 blend of value+momentum x N-F3
    "Paying in Stock", constructed EXACTLY as in backtests/v8/
    combo-vm-nf3/ (each parent engine unmodified; each sleeve its
    own sub-pot on the shared quarterly schedule; sleeve budgets
    reset to 50/50 of the combined close at each selection date;
    execution at the next open is champion mechanics per sleeve —
    sells toward targets, then the overweight sleeve's surplus
    cash transfers to the underweight sleeve, then buys).
  - PHASE 2 (switch -> 2026-11-20): the blend, as above.
  - Costs: 0.10% of trade value per side + $0.01 per sell order,
    on every trade INCLUDING the switch (the switch is executed
    through the sleeves' own rebalance sells/buys at the program
    schedule; the inter-sleeve cash transfer is a same-pot move,
    not a market trade — identical to the blend's resets).
  - Windows: continuous 2019-01-02 -> 2026-11-20 (primary) and
    validation 2023-01-03 -> 2026-11-20 (context; the validation
    window OPENS on the switch date itself, so the switch run
    there is the pure blend by construction — a built-in
    consistency check). Yearly folds vs SPY (context): fresh $100
    pots per calendar year 2020..2026 with the same frozen switch
    rule applied inside the fold — folds ending before 2023 never
    reach the switch (pure champion years); folds from 2023 on
    switch at their first selection date (pure blend years).
  - Placebos: 20 seeds; each sleeve draws 5 random names from ITS
    OWN eligible pool on identical dates, with identical phase
    structure, resets and the same single floor.

PRE-REGISTERED BAR (stated before the run): the switch must beat
BOTH the pure champion ($544.47) AND the pure blend ($532.39) on
the continuous window. Anything less and the switch is not
adopted.

HONESTY LABEL: the switch idea was suggested by the already-seen
path (Terry saw the blend's long-run shortfall before proposing
it), so even a full pass is CANDIDATE-grade only — the forward
paper trial would decide. No parameters were tuned: the switch
date is the window's calendar halfway mark, fixed by the brief.

INTEGRITY (all before any switch number is taken):
  - Both parents re-run standalone from the imported engines must
    reproduce their published finals to the cent (V+M $544.47 /
    $288.05; N-F3 $505.43 / $289.53), and SPY $313.62 / $187.77.
  - The pure blend, run through this script's copy of the combo
    machinery, must reproduce $532.39 / $290.45.
  - Degenerate checks of the switch runner itself: switch date
    set past the window end (never switches) must reproduce the
    pure champion $544.47 through the sleeve machinery; switch
    date set at the first selection date must reproduce the pure
    blend $532.39.

Run once, no tuning, no extra parameters.
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
SWITCH_ON_OR_AFTER = "2023-01-01"   # halfway mark of 2019->2026


# ------------------------------------------------------------- scoring
# (Scorer, Sleeve, sleeve_sells, sleeve_buys and run_combo are the
# combo-vm-nf3 machinery, copied verbatim so Phase 2 IS the blend.)
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


def _liquidate(pb, sleeves, d, tag):
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


# ------------------------------------------------------------- combo
# (verbatim from combo-vm-nf3.py — used for the integrity re-run of
# the pure blend inside this script)
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
        _liquidate(pb, sleeves, d, tag)

    for di, d in enumerate(days):
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = sleeve_sells(pb, s, d, targets)
                    budgets[s.name] = budget
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


# ------------------------------------------------------------- switch
def run_switch(pb, scorer, start, end, switch_on_or_after,
               start_cash=100.0, floor0=85.0,
               placebo_rng=None, label="", quiet=True):
    """Champion alone on the full pot until the first quarterly
    selection date >= switch_on_or_after; from that selection date
    on, the combo-vm-nf3 50/50 blend. One combined floor."""
    vm = Sleeve("VM", start_cash)        # phase 1: the WHOLE pot
    f3 = Sleeve("NF3", 0.0)              # empty until the switch
    sleeves = [vm, f3]
    sel_dates = champ.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    switch_date = None
    for d in sel_dates:
        if d >= switch_on_or_after:
            switch_date = d
            break
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    pools = []
    transfers = []
    halted = None
    halt_info = None
    switch_close = None          # combined close on the switch date
    switch_exec_date = None      # day the switch trades executed
    costs_at_switch_exec = None  # costs booked on the execution day

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    for di, d in enumerate(days):
        # --- execute pending rebalances at today's open (combo
        # machinery verbatim: sells, 50/50 reset transfer, buys)
        if vm.pending is not None or f3.pending is not None:
            costs_before = vm.costs + f3.costs
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = sleeve_sells(pb, s, d, targets)
                    budgets[s.name] = budget
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
            if switch_exec_date is None and switch_close is not None:
                switch_exec_date = d
                costs_at_switch_exec = (vm.costs + f3.costs) - costs_before
        # --- selection day
        if d in sel_set:
            vm_pool, vm_picks = scorer.vm(d)
            if placebo_rng is not None and len(vm_pool) >= 5:
                vm_picks = placebo_rng.sample(sorted(vm_pool), 5)
            combined = combined_close(d)
            if switch_date is not None and d >= switch_date:
                # PHASE 2: the blend — both sleeves, 50/50 budgets
                f3_pool, f3_picks = scorer.nf3(d)
                if placebo_rng is not None and len(f3_pool) >= 5:
                    f3_picks = placebo_rng.sample(sorted(f3_pool), 5)
                budget = combined / 2.0
                if len(vm_pool) >= 5:
                    vm.pending = ({t: budget / 5.0 for t in vm_picks},
                                  budget)
                if len(f3_pool) >= 5:
                    f3.pending = ({t: budget / 5.0 for t in f3_picks},
                                  budget)
                if d == switch_date and switch_close is None:
                    switch_close = combined
                pools.append((d, "BLEND", len(vm_pool), list(vm_picks),
                              len(f3_pool), list(f3_picks),
                              round(combined, 2)))
            else:
                # PHASE 1: champion alone, budget = the whole pot
                if len(vm_pool) >= 5:
                    vm.pending = ({t: combined / 5.0 for t in vm_picks},
                                  combined)
                pools.append((d, "VM-ONLY", len(vm_pool),
                              list(vm_picks), 0, [],
                              round(combined, 2)))
            if not quiet:
                print(f"  [{label}] {d} pot=${combined:,.2f}", flush=True)
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
            _liquidate(pb, sleeves, nd, "SELL-HALT")
            final = vm.cash + f3.cash
            return {"label": label, "final": final,
                    "costs": vm.costs + f3.costs,
                    "trades": vm.trades + f3.trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve, "transfers": transfers,
                    "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
                    "sleeve_curves": {"VM": vm.curve, "NF3": f3.curve},
                    "switch_date": switch_date,
                    "switch_close": switch_close,
                    "switch_exec_date": switch_exec_date,
                    "costs_at_switch_exec": costs_at_switch_exec}
    last = days[-1]
    _liquidate(pb, sleeves, last, "SELL-END")
    final = vm.cash + f3.cash
    return {"label": label, "final": final, "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "transfers": transfers,
            "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
            "sleeve_curves": {"VM": vm.curve, "NF3": f3.curve},
            "switch_date": switch_date,
            "switch_close": switch_close,
            "switch_exec_date": switch_exec_date,
            "costs_at_switch_exec": costs_at_switch_exec}


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


def year_returns(curve, start_cash=100.0):
    """Calendar-year % returns from a daily close curve; the first
    (partial) year is measured from the pot's start value."""
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = v
    out = {}
    prev = start_cash
    for y in sorted(year_end):
        out[y] = round((year_end[y] / prev - 1.0) * 100, 1)
        prev = year_end[y]
    return out


def cagr(final, start, years):
    return round(((final / start) ** (1.0 / years) - 1.0) * 100, 1)


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

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    windows = [("FULL", FULL), ("VALIDATION", VAL)]
    published = {
        "VM": {"FULL": 544.47, "VALIDATION": 288.05},
        "NF3": {"FULL": 505.43, "VALIDATION": 289.53},
        "BLEND": {"FULL": 532.39, "VALIDATION": 290.45},
        "SPY": {"FULL": 313.62, "VALIDATION": 187.77},
    }

    out = {"test": "MIDPOINT SWITCH direction B: champion alone -> "
                   "50/50 champion x N-F3 blend at the first quarterly "
                   "selection date on/after 2023-01-01; Terry's rules "
                   "(one plain -15% floor, no restart)",
           "bar": "continuous: beat BOTH pure champion $544.47 AND "
                  "pure blend $532.39",
           "honesty_label": "CANDIDATE-grade ceiling: the switch idea "
                            "was suggested by the already-seen path; "
                            "only the forward paper trial could adopt it",
           "universe": UNIVERSE}

    # ---- integrity 1: parents standalone, imported engines verbatim
    parents = {}
    parent_curves = {}
    for wname, (ws, we) in windows:
        vm100 = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                              100.0, 85.0, [], label=f"{wname} VM parent",
                              quiet=True)
        stats = {"direct": 0, "derived": 0}
        f3_100 = nf3.run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                             label=f"{wname} NF3 parent", stats=stats)
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        parents[wname] = {
            "VM": round(vm100["final"], 2), "NF3": round(f3_100["final"], 2),
            "SPY": round(s, 2),
            "VM_costs": round(vm100["costs"], 2),
            "NF3_costs": round(f3_100["costs"], 2),
            "VM_diag": diagnostics(vm100["curve"], 85.0),
            "NF3_diag": diagnostics(f3_100["curve"], 85.0),
        }
        parent_curves[wname] = {"VM": vm100["curve"], "NF3": f3_100["curve"]}
        ok = (round(vm100["final"], 2) == published["VM"][wname] and
              round(f3_100["final"], 2) == published["NF3"][wname] and
              round(s, 2) == published["SPY"][wname])
        print(f"== INTEGRITY parents {wname}: VM=${vm100['final']:,.2f} "
              f"NF3=${f3_100['final']:,.2f} SPY=${s:,.2f} "
              f"-> {'PASS' if ok else 'FAIL'}", flush=True)
        assert ok, f"parent integrity failed on {wname}"

    # ---- integrity 2: pure blend through this script's combo copy
    blend = {}
    blend_curves = {}
    for wname, (ws, we) in windows:
        r = run_combo(pb, scorer, ws, we, 100.0, 85.0,
                      label=f"{wname} BLEND integrity")
        blend[wname] = round(r["final"], 2)
        blend_curves[wname] = r["curve"]
        ok = blend[wname] == published["BLEND"][wname]
        print(f"== INTEGRITY blend {wname}: ${r['final']:,.2f} "
              f"-> {'PASS' if ok else 'FAIL'}", flush=True)
        assert ok, f"blend integrity failed on {wname}"
    out["integrity"] = {"parents": parents, "blend_recomputed": blend}

    # ---- integrity 3: degenerate switch runs (continuous window)
    sel_full = champ.quarter_selection_dates(pb, FULL[0], FULL[1])
    never = run_switch(pb, scorer, FULL[0], FULL[1], "9999-12-31",
                       label="DEGENERATE never-switch")
    first_sel = sel_full[0]
    atonce = run_switch(pb, scorer, FULL[0], FULL[1], first_sel,
                        label="DEGENERATE switch-at-start")
    deg = {"never_switch_final": round(never["final"], 2),
           "never_switch_expected": published["VM"]["FULL"],
           "switch_at_start_final": round(atonce["final"], 2),
           "switch_at_start_date": first_sel,
           "switch_at_start_expected": published["BLEND"]["FULL"]}
    deg["pass"] = (deg["never_switch_final"] == deg["never_switch_expected"]
                   and deg["switch_at_start_final"]
                   == deg["switch_at_start_expected"])
    out["degenerate_checks"] = deg
    print(f"== INTEGRITY degenerate: never-switch=${never['final']:,.2f} "
          f"(expect $544.47), switch-at-start=${atonce['final']:,.2f} "
          f"(expect $532.39) -> {'PASS' if deg['pass'] else 'FAIL'}",
          flush=True)
    assert deg["pass"], "degenerate switch checks failed"

    # ---- the switch: ranked + 20 placebos per window
    for wname, (ws, we) in windows:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        r = run_switch(pb, scorer, ws, we, SWITCH_ON_OR_AFTER,
                       label=f"{wname} SWITCH")
        diag = diagnostics(r["curve"], 85.0)
        placebo_finals = []
        placebo_halted = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_switch(pb, scorer, ws, we, SWITCH_ON_OR_AFTER,
                            placebo_rng=rng,
                            label=f"{wname} SWITCH PLACEBO s{seed}")
            placebo_finals.append(round(pr["final"], 2))
            placebo_halted.append(pr["halted"])
        sf = sorted(placebo_finals)
        placebo_median = round((sf[9] + sf[10]) / 2.0, 2)
        beaten = sum(1 for x in placebo_finals if r["final"] > x)
        sc = r["switch_close"]
        out[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s, 2),
            "diag": diag,
            "switch_date": r["switch_date"],
            "switch_close_value": (round(sc, 2) if sc is not None
                                   else None),
            "switch_exec_date": r["switch_exec_date"],
            "costs_at_switch_exec": (
                round(r["costs_at_switch_exec"], 2)
                if r["costs_at_switch_exec"] is not None else None),
            "phase1_return_pct": (round((sc / 100.0 - 1.0) * 100, 2)
                                  if sc else 0.0),
            "phase2_return_pct": (round((r["final"] / sc - 1.0) * 100, 2)
                                  if sc else None),
            "sleeve_finals": r["sleeve_finals"],
            "transfers": r["transfers"],
            "placebo_finals": placebo_finals,
            "placebo_halted": placebo_halted,
            "placebo_median": placebo_median,
            "placebo_beaten": beaten,
            "year_returns_pct": year_returns(r["curve"]),
            "pools": r["pools"], "trades": r["trades"],
        }
        print(f"== {wname} SWITCH final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} switch={r['switch_date']} "
              f"switch_close=${sc:,.2f} | SPY=${s:,.2f} | placebo "
              f"median=${placebo_median:,.2f} beaten={beaten}/20",
              flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} | maxDD "
              f"{diag['max_drawdown_pct']}%", flush=True)

    # per-year context for the continuous window
    out["FULL"]["year_returns_parents_pct"] = {
        "VM": year_returns(parent_curves["FULL"]["VM"]),
        "BLEND": year_returns(blend_curves["FULL"]),
    }

    # ---- yearly folds vs SPY (context)
    folds = []
    prod_sw = 1.0
    prod_spy = 1.0
    wins = 0
    for yr in range(2020, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        fr = run_switch(pb, scorer, fs, fe, SWITCH_ON_OR_AFTER,
                        label=f"FOLD {yr}")
        fs_spy, _ = champ.spy_net(pb, fs, fe, 100.0)
        win = fr["final"] > fs_spy
        wins += 1 if win else 0
        prod_sw *= fr["final"] / 100.0
        prod_spy *= fs_spy / 100.0
        folds.append({"year": yr, "start": fs, "end": fe,
                      "switch_final": round(fr["final"], 2),
                      "spy_final": round(fs_spy, 2),
                      "win": win, "halted": fr["halted"],
                      "switch_date_in_fold": fr["switch_date"],
                      "costs": round(fr["costs"], 2)})
        print(f"== FOLD {yr}: switch=${fr['final']:,.2f} "
              f"SPY=${fs_spy:,.2f} win={win} halted={fr['halted']} "
              f"switch_in_fold={fr['switch_date']}", flush=True)
    out["folds"] = {"per_year": folds, "wins_vs_spy": wins,
                    "switch_fold_compounded": round(100.0 * prod_sw, 2),
                    "spy_fold_compounded": round(100.0 * prod_spy, 2)}
    out["nf3_quarter_values"] = scorer.nf3_stats

    with open(os.path.join(
            HERE, "switch-champion-to-blend-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
