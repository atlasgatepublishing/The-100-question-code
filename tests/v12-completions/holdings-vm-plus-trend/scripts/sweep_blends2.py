#!/usr/bin/env python3
"""Slice H3: vm-plus-trend + switch-blend-to-champion count sweeps, via
exec-patched v10 engines (count replaces the hardcoded 5 in picks,
per-pick budget and placebo draws).
plus-trend convention: count = V+M sleeve's top-N; the ETF trend sleeve
has no ranked stock count (fixed ETF set) and is unchanged; the 50/50
split and quarterly split-rebalance are the published form. House = v9
wrapper in blend_v9_cadence. Native (no-floor) form: not run by this
chassis (the v10 blend chassis is v9-only); recorded as a grid gap.
switch convention (stated in advance): LOCKSTEP - count N applies to
BOTH sleeves (champion sleeve pre-switch and both blend sleeves
post-switch), per the holdings-blends lockstep convention. Mechanism =
Switch B (champion first half -> 50/50 champion x N-F3 blend), the
candidate form per the v10 folder's naming note. House = run_v9_switch.
Roads: DECADE/CONT/VAL (the v4 cache begins 2017-06-01; LONG is not an
honest road on this chassis - the v9 LONG print $920.77 stands as the
count-5 reference only)."""
import json, os, random, time
BT = os.path.expanduser("~/workspace/stock-app/backtests")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "blends2_results.json")
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
END = "2026-11-20"
out = {}
if os.path.exists(OUT):
    out = json.load(open(OUT))

# ---------- vm-plus-trend ----------
if "vm-plus-trend" not in out:
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
    roads_pt = {"DECADE": ("2016-11-21", END), "CONT": ("2019-01-02", END),
                "VAL": ("2023-01-03", END)}
    res = {"roads": {}}
    for rn, (s, e) in roads_pt.items():
        cell = {}
        for c in COUNTS:
            ns["COUNT"][0] = 30 if c == "ALL" else c
            h = ns["blend_v9_cadence"](cb, eq_rows, sh_rows, sel_all, s, e, 100.0)
            cell[str(c)] = {"house": {"final": round(h["final"], 2),
                            "costs": round(h["costs_sleeves"] + h["costs_transfers"], 2),
                            "halts": len(h["halts"]),
                            "second_halt": bool(h["second_halt"]),
                            "curve": h["curve"]}}
            print("plus-trend", rn, c, cell[str(c)]["house"]["final"], flush=True)
        if rn == "DECADE":
            for c in COUNTS:
                ns["COUNT"][0] = 30 if c == "ALL" else c
                finals = []
                for seed in range(1, 21):
                    r = ns["blend_v9_cadence"](cb, eq_rows, sh_rows, sel_all,
                                               s, e, 100.0, rng=random.Random(seed))
                    finals.append(round(r["final"], 2))
                cell[str(c)]["placebo_finals"] = finals
                cell[str(c)]["placebo_beaten"] = sum(
                    1 for f in finals if f < cell[str(c)]["house"]["final"])
        res["roads"][rn] = cell
        json.dump(out | {"vm-plus-trend": res}, open(OUT, "w"))
    out["vm-plus-trend"] = res
    json.dump(out, open(OUT, "w"))
    print("PLUS-TREND DONE", flush=True)

# ---------- switch-blend-to-champion (Switch B) ----------
if "switch-blend-to-champion" not in out:
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
    roads_sw = {"DECADE": ("2016-11-21", END), "CONT": ("2019-01-02", END),
                "VAL": ("2023-01-03", END)}
    res2 = {"roads": {}}
    for rn, (s, e) in roads_sw.items():
        sel = ns2["cadence_dates"](fb, "quarterly", s, e)
        trig = ns2["halfway"](s, e)
        stats = {"direct": 0, "derived": 0}
        vm_full, nf3_full = {}, {}
        for d in sel:
            vm_full[d] = ns2["vm_pool_picks"](fb, eq_idx, sh_idx, d)
            nf3_full[d] = ns2["nf3_pool_picks"](facts_by_ticker, d, stats)
        cell = {}
        for c in COUNTS:
            n = 30 if c == "ALL" else c
            ns2["COUNT"][0] = n
            vm_s = {d: (p[0], p[1][:n]) for d, p in vm_full.items()}
            nf3_s = {d: (p[0], p[1][:n]) for d, p in nf3_full.items()}
            h = ns2["run_v9_switch"](fb, vm_s, nf3_s, sel, s, e, trig, 100.0)
            cell[str(c)] = {"house": {"final": round(h["final"], 2),
                            "costs": round(h["costs"], 2),
                            "halts": len(h["halts"]),
                            "second_halt": bool(h["second_halt"]),
                            "curve": h["curve"]}}
            print("switch", rn, c, cell[str(c)]["house"]["final"], flush=True)
        if rn in ("DECADE", "CONT"):
            for c in COUNTS:
                n = 30 if c == "ALL" else c
                ns2["COUNT"][0] = n
                vm_s = {d: (p[0], p[1][:n]) for d, p in vm_full.items()}
                nf3_s = {d: (p[0], p[1][:n]) for d, p in nf3_full.items()}
                finals = []
                for seed in range(1, 21):
                    tr = ns2["run_v9_switch"](fb, vm_s, nf3_s, sel, s, e, trig,
                                              100.0, placebo_rng=random.Random(seed))
                    finals.append(round(tr["final"], 2))
                cell[str(c)]["placebo_finals"] = finals
                cell[str(c)]["placebo_beaten"] = sum(
                    1 for f in finals if f < cell[str(c)]["house"]["final"])
        res2["roads"][rn] = cell
        json.dump(out | {"switch-blend-to-champion": res2}, open(OUT, "w"))
    out["switch-blend-to-champion"] = res2
    json.dump(out, open(OUT, "w"))
    print("SWITCH DONE", flush=True)
print("BLENDS2 ALL DONE")
