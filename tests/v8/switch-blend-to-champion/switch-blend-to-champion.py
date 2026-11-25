#!/usr/bin/env python3
"""
MIDPOINT SWITCH, DIRECTION A — BLEND FIRST, CHAMPION SECOND.
One $100 pot, Terry's rules. Simulation only.

TERRY'S IDEA (2026-11-21): the 50/50 blend of value+momentum x N-F3
beat both parents on the judging years but fell $12.08 behind the
champion on the long run. Terry: "let's not do it on the long run...
when it gets ready to lose or before it starts losing you sell...
if it's 8 years and it started to fall within the four years then go
ahead and switch it up." The long run is ~8 years (2019 -> 2026); the
blend's relative lead was a first-half / judging-years phenomenon.
Direction A tests the mechanical version of that idea with the
switch point frozen at the halfway mark — no peeking at peaks, no
extra parameters:

FROZEN CONSTRUCTION:
  - ONE $100 pot under TERRY'S RULES: plain -15% floor on the pot
    (close at/below $85.00 -> liquidate everything at the next open,
    run ends). No ladder, no restart.
  - Phase 1 (2019-01-02 -> the switch): the 50/50 blend EXACTLY as
    in backtests/v8/combo-vm-nf3/ — each parent engine unmodified,
    own $50 sub-pot, shared quarterly schedule, sleeve budgets reset
    to 50/50 at each quarterly selection date, champion mechanics
    (selection at the close, execution at the next open), program
    costs (0.10% of trade value per side + $0.01 per sell order)
    inside each sleeve. This script imports the combo module and
    reuses its Sleeve / Scorer / sell / buy machinery verbatim, so
    Phase 1 is the pure blend's own code path.
  - SWITCH: at the first quarterly selection date on or after
    2023-01-01 (the halfway mark of the 2019->2026 window), the
    N-F3 sleeve is liquidated in full (its positions sell at the
    next open at program costs, exactly like a rebalance to empty
    targets) and the entire pot's budget moves to the value+
    momentum sleeve. Mechanically this is the combo's own reset
    machinery with budgets (combined, 0) instead of (half, half).
  - Phase 2 (switch -> 2026-11-20): value+momentum alone on the
    whole pot, champion mechanics; at each later selection date the
    VM budget is the full combined pot value and any residual cash
    left in the empty N-F3 sleeve is swept across by the same
    transfer machinery, so the entire pot is always working in the
    champion.
  - Windows: continuous 2019-01-02 -> 2026-11-20 (primary) and
    validation 2023-01-03 -> 2026-11-20. The validation window
    starts on the switch date itself, so it lies entirely in
    Phase 2: a fresh $100 pot there switches at its first selection
    and is the champion alone from day one — its final must equal
    the pure champion's $288.05 to the cent, which is a built-in
    integrity check on the switch machinery.
  - Yearly folds vs SPY (context): fresh $100 pots per calendar
    year 2020..2026, same switch rule (folds starting before 2023
    never reach the switch and are the pure blend; folds from 2023
    on switch at their first selection and are the champion alone).

PRE-REGISTERED BAR (stated before the run): on the continuous
window the switch must beat BOTH the pure champion ($544.47) AND
the pure blend ($532.39). Anything less is reported plainly.

HONESTY LABEL: the switch idea was suggested by the already-seen
path (the blend's known first-half strength), so even a full pass
is CANDIDATE-grade only — the forward paper trial would decide.
The 2023-01-01 switch point is the window's halfway mark, frozen
in advance of this run; it is not fitted to any peak.

INTEGRITY: both parent engines and the pure blend are re-run
inside this script from the imported modules before any switch
number is taken — V+M $544.47 / $288.05, N-F3 $505.43 / $289.53,
blend $532.39 / $290.45, SPY $313.62 / $187.77 must all reproduce
to the cent.

Run once, no tuning, no extra parameters.
"""
import importlib.util
import json
import os

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
combo = _load("combo", os.path.join(V8, "combo-vm-nf3", "combo-vm-nf3.py"))

UNIVERSE = champ.UNIVERSE
SWITCH_ON_OR_AFTER = "2023-01-01"


# ------------------------------------------------------------- switch
def run_switch(pb, scorer, start, end, start_cash=100.0, floor0=85.0,
               label="", quiet=True):
    """Blend (combo machinery verbatim) until the first quarterly
    selection date >= SWITCH_ON_OR_AFTER, then champion alone."""
    Sleeve = combo.Sleeve
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
    switch_date = None
    switch_info = None

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    def liquidate(d, tag):
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
        # --- execute pending rebalances at today's open (combo code)
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = combo.sleeve_sells(
                        pb, s, d, targets)
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
                    combo.sleeve_buys(pb, s, d, targets,
                                      opens_by_sleeve[s.name])
                    s.pending = None
        # --- selection day
        if d in sel_set:
            vm_pool, vm_picks = scorer.vm(d)
            f3_pool, f3_picks = scorer.nf3(d)
            combined = combined_close(d)
            if switch_date is None and d >= SWITCH_ON_OR_AFTER \
                    and len(vm_pool) >= 5:
                # THE SWITCH: whole pot to the champion; N-F3 sleeve
                # rebalances to empty targets (full liquidation at
                # the next open, program costs).
                switch_date = d
                switch_info = {
                    "selection_date": d,
                    "combined_close": round(combined, 2),
                    "nf3_sleeve_close": round(f3.close_value(pb, d), 2),
                    "vm_sleeve_close": round(vm.close_value(pb, d), 2),
                    "nf3_positions_liquidated": sorted(f3.positions),
                }
                vm.pending = ({t: combined / 5.0 for t in vm_picks},
                              combined)
                f3.pending = ({}, 0.0)
            elif switch_date is not None:
                # Phase 2: champion alone on the whole pot; the empty
                # N-F3 sleeve keeps an empty pending so any residual
                # cash is swept to VM by the transfer machinery.
                if len(vm_pool) >= 5:
                    vm.pending = ({t: combined / 5.0 for t in vm_picks},
                                  combined)
                f3.pending = ({}, 0.0)
            else:
                # Phase 1: the pure blend's 50/50 reset.
                budget = combined / 2.0
                if len(vm_pool) >= 5:
                    vm.pending = ({t: budget / 5.0 for t in vm_picks},
                                  budget)
                if len(f3_pool) >= 5:
                    f3.pending = ({t: budget / 5.0 for t in f3_picks},
                                  budget)
            pools.append((d, len(vm_pool), list(vm_picks),
                          len(f3_pool), list(f3_picks),
                          round(combined, 2),
                          "SWITCH" if d == switch_date else
                          ("P2" if switch_date is not None else "P1")))
            if not quiet:
                print(f"  [{label}] {d} pot=${combined:,.2f} "
                      f"phase={'P2' if switch_date else 'P1'}",
                      flush=True)
        # --- end of day: combined curve + the ONE floor
        v = combined_close(d)
        curve.append((d, v))
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
                    "pools": pools, "curve": curve,
                    "transfers": transfers,
                    "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
                    "switch_date": switch_date,
                    "switch_info": switch_info}
    last = days[-1]
    liquidate(last, "SELL-END")
    final = vm.cash + f3.cash
    return {"label": label, "final": final, "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "transfers": transfers,
            "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash},
            "switch_date": switch_date, "switch_info": switch_info}


# ----------------------------------------------------------------- main
def main():
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
    scorer = combo.Scorer(pb, equity_rows, shares_rows, facts_by_ticker)

    windows = [
        ("FULL", "2019-01-02", "2026-11-20"),
        ("VALIDATION", "2023-01-03", "2026-11-20"),
    ]

    # ---- integrity: parents standalone + pure blend, imported engines
    integrity = {}
    for wname, ws, we in windows:
        vm100 = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                              100.0, 85.0, [], label=f"{wname} VM parent",
                              quiet=True)
        stats = {"direct": 0, "derived": 0}
        f3_100 = nf3.run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                             label=f"{wname} NF3 parent", stats=stats)
        blend = combo.run_combo(pb, scorer, ws, we, 100.0, 85.0,
                                label=f"{wname} BLEND integrity")
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        integrity[wname] = {
            "VM": round(vm100["final"], 2),
            "NF3": round(f3_100["final"], 2),
            "BLEND": round(blend["final"], 2),
            "SPY": round(s, 2),
        }
        print(f"== INTEGRITY {wname}: VM=${vm100['final']:,.2f} "
              f"NF3=${f3_100['final']:,.2f} "
              f"BLEND=${blend['final']:,.2f} SPY=${s:,.2f}", flush=True)

    expected = {"FULL": {"VM": 544.47, "NF3": 505.43, "BLEND": 532.39,
                         "SPY": 313.62},
                "VALIDATION": {"VM": 288.05, "NF3": 289.53,
                               "BLEND": 290.45, "SPY": 187.77}}
    for wname in integrity:
        for k, v in expected[wname].items():
            got = integrity[wname][k]
            assert abs(got - v) < 0.005, \
                f"INTEGRITY FAIL {wname} {k}: got {got}, expected {v}"
    print("== INTEGRITY: all published finals reproduced to the cent",
          flush=True)

    # ---- the switch runs
    out = {"test": "MIDPOINT SWITCH A: blend 50/50 VM x NF3 -> champion "
                   "alone at first quarterly selection >= 2023-01-01; "
                   "Terry's rules (one plain -15% floor, no restart)",
           "bar": "continuous: beat BOTH pure champion $544.47 AND "
                  "pure blend $532.39",
           "honesty_label": "switch idea suggested by the already-seen "
                            "path; even a full pass is CANDIDATE-grade "
                            "only — forward paper trial would decide",
           "integrity_recomputed": integrity,
           "universe": UNIVERSE}
    for wname, ws, we in windows:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        r = run_switch(pb, scorer, ws, we, 100.0, 85.0,
                       label=f"{wname} SWITCH-A")
        diag = combo.diagnostics(r["curve"], 85.0)
        out[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s, 2),
            "diag": diag, "sleeve_finals": r["sleeve_finals"],
            "transfers": r["transfers"],
            "switch_date": r["switch_date"],
            "switch_info": r["switch_info"],
            "pools": r["pools"], "trades": r["trades"],
        }
        print(f"== {wname} SWITCH-A final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} switch={r['switch_date']} | "
              f"SPY=${s:,.2f}", flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} | maxDD "
              f"{diag['max_drawdown_pct']}%", flush=True)

    # ---- yearly folds vs SPY (context)
    folds = []
    prod_sw = 1.0
    prod_spy = 1.0
    wins = 0
    for yr in range(2020, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        fr = run_switch(pb, scorer, fs, fe, 100.0, 85.0,
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
                      "switch_date": fr["switch_date"],
                      "costs": round(fr["costs"], 2)})
        print(f"== FOLD {yr}: switch=${fr['final']:,.2f} "
              f"SPY=${fs_spy:,.2f} win={win} halted={fr['halted']} "
              f"switch={fr['switch_date']}", flush=True)
    out["folds"] = {"per_year": folds, "wins_vs_spy": wins,
                    "switch_fold_compounded": round(100.0 * prod_sw, 2),
                    "spy_fold_compounded": round(100.0 * prod_spy, 2)}
    out["nf3_quarter_values"] = scorer.nf3_stats

    with open(os.path.join(HERE, "switch-blend-to-champion-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
