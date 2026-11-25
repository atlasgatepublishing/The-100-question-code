#!/usr/bin/env python3
"""Completes the v10 integrity gate for dividend-growth: re-runs the
ORIGINAL v6 engine's VALIDATION placebo block and walk-forward folds
(the first integrity_original.py process was killed mid-run by the host
after reproducing both ranked finals and the full CONT placebo block;
see integrity_run.log). Everything here calls the unmodified original
engine functions."""
import importlib.util, json, os, random
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("orig", os.path.join(HERE, "integrity_original.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
E = M.E

ciks = E.get_ciks()
facts_by_t = {t: E.get_companyfacts(34088 if t == "XOM" else ciks[t][0]) for t in M.UNIVERSE}
raw_bars, divs, splits = M.load_raw_market()
raw_pb = E.PriceBook(raw_bars)
adj_pb = E.PriceBook({t: E.get_prices(t) for t in M.UNIVERSE + ["SPY"]})
all_sel = E.quarter_selection_dates(raw_pb, "2019-01-02", "2026-11-20")
pools = {}
for d in all_sel:
    ranked = []
    for t in M.UNIVERSE:
        res = M.eligibility(facts_by_t[t], d, splits.get(t, []))
        if res is not None:
            ranked.append((t, res[0]))
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    pools[d] = ranked
print("pools built", flush=True)

out = {}
r = M.run_pot_div(raw_pb, divs, pools, "2023-01-03", "2026-11-20", label="VAL RANKED")
finals, rows = M.placebo_block(raw_pb, divs, pools, "2023-01-03", "2026-11-20")
dist = M.dist_stats(finals, r["final"])
dist["halted_count"] = sum(1 for x in rows if x["halted"])
out["VALIDATION"] = {"final": round(r["final"], 2),
                     "dividends_credited": round(r["div_total"], 2),
                     "placebo": dist, "placebo_rows": rows}
print("VAL placebo:", dist, flush=True)

folds = []
for y in range(2020, 2027):
    fs = f"{y}-01-01"; fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
    fr = M.run_pot_div(raw_pb, divs, pools, fs, fe, label=f"FOLD {y}")
    fspy, _ = E.spy_net(adj_pb, fs, fe, 100.0)
    folds.append({"year": y, "final": round(fr["final"], 2),
                  "spy_net_final": round(fspy, 2), "halted": fr["halted"],
                  "dividends_credited": round(fr["div_total"], 2)})
    print("FOLD", y, folds[-1], flush=True)
out["folds"] = folds
with open(os.path.join(HERE, "integrity_completion.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("COMPLETION DONE", flush=True)
