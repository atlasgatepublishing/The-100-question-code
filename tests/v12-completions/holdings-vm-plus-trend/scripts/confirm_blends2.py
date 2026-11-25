#!/usr/bin/env python3
"""Confirmations for slice H3 blends2: vm-plus-trend count 3 (and 2) and
switch-blend-to-champion count 3 vs native 5 — fresh-$100 calendar-year
folds 2017..2026 + halves, house form, same patched engines as the sweep."""
import json, os, random
BT = os.path.expanduser("~/workspace/stock-app/backtests")
HERE = os.path.dirname(os.path.abspath(__file__))
END = "2026-11-20"
out = {}

# plus-trend folds: window = calendar year, sel_all quarterly over full span
p = os.path.join(BT, "v10-retest/vm-plus-trend/vm-plus-trend-v10.py")
src = open(p).read()
src = src.replace("picks = placebo_rng.sample(sorted(scores), 5)",
                  "picks = placebo_rng.sample(sorted(scores), min(COUNT[0], len(scores)))")
src = src.replace("picks = sorted(combined, key=lambda t: -combined[t])[:5]",
                  "picks = sorted(combined, key=lambda t: -combined[t])[:COUNT[0]]")
src = src.replace("each = pv / 5.0", "each = pv / len(picks)")
src = src.replace("if len(scores) >= 5:", "if len(scores) >= 1:")
ns = {"__file__": p, "__name__": "pt_patched", "COUNT": [5]}
exec(compile(src, "pt_patched", "exec"), ns)
pb, eq_rows, sh_rows = ns["v9"].build_vm_book()
cb = ns["CadenceBook"](pb)
sel_all = ns["cadence_dates"](pb, "quarterly", "2016-11-21", END)

def folds_for(run_fn, cands=(3,)):
    res = {}
    for cand in cands:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"; e = END if yr == 2026 else f"{yr}-12-31"
            row = {}
            for c in (cand, 5):
                row[str(c)] = run_fn(c, s, e)
            row["win"] = row[str(cand)] > row["5"]
            folds[str(yr)] = row
            print("fold", cand, yr, row, flush=True)
        halves = {}
        for hn, (s, e) in {"H1": ("2016-11-21", "2021-12-31"),
                           "H2": ("2022-01-01", END)}.items():
            row = {}
            for c in (cand, 5):
                row[str(c)] = run_fn(c, s, e)
            row["win"] = row[str(cand)] > row["5"]
            halves[hn] = row
            print("half", cand, hn, row, flush=True)
        fw = sum(1 for v in folds.values() if v["win"])
        hw = sum(1 for v in halves.values() if v["win"])
        res[str(cand)] = {"folds": folds, "fold_wins": fw, "halves": halves,
                          "half_wins": hw, "confirmed": fw >= 6 and hw >= 1}
    return res

def pt_run(c, s, e):
    ns["COUNT"][0] = c
    h = ns["blend_v9_cadence"](cb, eq_rows, sh_rows, sel_all, s, e, 100.0)
    return round(h["final"], 2)

out["vm-plus-trend"] = folds_for(pt_run, cands=(3, 2))
json.dump(out, open(os.path.join(HERE, "blends2_confirmation.json"), "w"))
print("PLUS-TREND CONFIRM DONE", flush=True)

# switch folds
p2 = os.path.join(BT, "v10-retest/switch-blend-to-champion/switch_v10.py")
src2 = open(p2).read()
src2 = src2.replace("vm_picks = placebo_rng.sample(sorted(vm_pool), 5)",
                    "vm_picks = placebo_rng.sample(sorted(vm_pool), min(COUNT[0], len(vm_pool)))")
src2 = src2.replace("f3_picks = placebo_rng.sample(sorted(f3_pool), 5)",
                    "f3_picks = placebo_rng.sample(sorted(f3_pool), min(COUNT[0], len(f3_pool)))")
src2 = src2.replace("vm.pending = ({t: budget / 5.0 for t in vm_picks},",
                    "vm.pending = ({t: budget / len(vm_picks) for t in vm_picks},")
src2 = src2.replace("f3.pending = ({t: budget / 5.0 for t in f3_picks},",
                    "f3.pending = ({t: budget / len(f3_picks) for t in f3_picks},")
src2 = src2.replace("vm.pending = ({t: combined / 5.0 for t in vm_picks},",
                    "vm.pending = ({t: combined / len(vm_picks) for t in vm_picks},")
src2 = src2.replace("picks = sorted(combined, key=lambda t: -combined[t])[:5]",
                    "picks = sorted(combined, key=lambda t: -combined[t])")
src2 = src2.replace("picks = sorted(scores, key=lambda t: (scores[t], t))[:5]",
                    "picks = sorted(scores, key=lambda t: (scores[t], t))")
ns2 = {"__file__": p2, "__name__": "sw_patched", "COUNT": [5]}
exec(compile(src2, "sw_patched", "exec"), ns2)
champ = ns2["champ"]; UNIVERSE = ns2["UNIVERSE"]
ciks = champ.get_ciks(); OV = {"XOM": 34088}
facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
for t in UNIVERSE:
    cik = OV.get(t, ciks[t][0]); facts = champ.get_companyfacts(cik)
    facts_by_ticker[t] = facts
    equity_rows[t] = (champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
        champ.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
    shares_rows[t] = (champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
        champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
        champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
bars = {t: champ.get_prices(t) for t in UNIVERSE + ["SPY"]}
fb = ns2["FastBook"](bars)
eq_idx = {t: ns2["PitIndex"](equity_rows[t]) for t in UNIVERSE}
sh_idx = {t: ns2["PitIndex"](shares_rows[t]) for t in UNIVERSE}
print("switch inputs built", flush=True)

def sw_run(c, s, e):
    ns2["COUNT"][0] = c
    sel = ns2["cadence_dates"](fb, "quarterly", s, e)
    trig = ns2["halfway"](s, e)
    stats = {"direct": 0, "derived": 0}
    vm_s, nf3_s = {}, {}
    for d in sel:
        pool, picks = ns2["vm_pool_picks"](fb, eq_idx, sh_idx, d)
        vm_s[d] = (pool, picks[:c])
        pool3, picks3 = ns2["nf3_pool_picks"](facts_by_ticker, d, stats)
        nf3_s[d] = (pool3, picks3[:c])
    h = ns2["run_v9_switch"](fb, vm_s, nf3_s, sel, s, e, trig, 100.0)
    return round(h["final"], 2)

out["switch-blend-to-champion"] = folds_for(sw_run, cands=(3,))
json.dump(out, open(os.path.join(HERE, "blends2_confirmation.json"), "w"))
print("SWITCH CONFIRM DONE")
