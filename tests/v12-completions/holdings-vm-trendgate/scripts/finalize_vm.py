#!/usr/bin/env python3
"""Finalize per-family folders for vm-trendgate / vm-panicgate /
vm-volscale from scripts/vm_results.json (this folder's sweep output)."""
import json, os, sys
B = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "vm_results.json")))
COUNTS = ["1", "2", "3", "5", "8", "10", "15", "20", "30", "ALL"]
ROADS = ["LONG", "DECADE", "CONT", "VAL"]
META = {
 "trendgate": ("vm-trendgate",
   "Faber trend gate on the champion: at each quarterly selection, if SPY's close is at/below its trailing 200-day moving average the pot holds cash for the quarter; otherwise it holds the champion's top-N. Native count 5.",
   "The gate is a portfolio-level switch on SPY only; it never re-ranks. Practitioners of Faber-style timing check the 200-day line monthly in the published form; this family's frozen form evaluates it at the champion's quarterly selection dates (the v11 native form)."),
 "panicgate": ("vm-panicgate",
   "Daniel & Moskowitz panic-state gate on the champion: at each quarterly selection, if SPY is in a panic state (trailing 504-trading-day return < 0 AND 60-day realized vol above the expanding median of its own history, per the family's v12 construction spec) the quarter's invested fraction is halved to 50% cash; otherwise fully invested in the champion's top-N. Native count 5.",
   "The gate is a function of SPY only. In the family's v12 record the panic state never occurred on the CONT/VAL roads at all (SPY's trailing 24-month return was never negative in 2019-2026), so on those roads the gated pot is the champion, cell for cell."),
 "volscale": ("vm-volscale",
   "Barroso & Santa-Clara volatility scaling on the champion (v12 frozen form): quarterly picks of the champion's top-N; the invested fraction w = min(1, 0.12 / sigma-hat) is re-evaluated MONTHLY, sigma-hat = annualized stdev of the trailing 126 trading days of equal-weight daily returns of the picks in force; non-pick months rescale the existing book to w. Native count 5.",
   "B&SC scaling changes only the invested fraction; it never re-ranks or re-counts - the count axis here is the champion's own ranking at each count, with the scaling applied on top."),
}
only = sys.argv[1:] or list(META)
for fam in only:
    if fam not in data:
        print(fam, "not in results yet"); continue
    slug, desc, prac = META[fam]
    res = data[fam]
    folder = os.path.join(B, f"holdings-{slug}")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "SPEC.md"), "w") as f:
        f.write(f"""# SPEC — {slug} holdings-count sweep (slice H3, frozen before runs)

{desc}

**Count semantics:** the champion chassis' ranked top-N at each
quarterly selection (pond of 30; LONG road uses the point-in-time 2010
pond). Grid: 1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE. Native
count = 5. **Forms:** house = v9 protections (plain −15% floor, 90-day
sit-out, one restart); native = same ranking/cadence/costs, no
protection layer. **Costs:** program standard 0.10%/side + $0.01 per
sell order. **Placebos:** 20 seeds per cell on LONG and DECADE (house);
ALL-ELIGIBLE placebos are degenerate (the draw is the pool) and marked.
**Confirmation (pre-registered):** a non-native count beating native 5
on at least 3 of 4 roads under house rules is re-run on different
years (fresh-$100 folds 2017–2026 + halves); ≥6/10 folds and ≥1/2
halves confirms → VARIANT-CANDIDATE.

Plumbing: `holdings-champion-vm/run_sweep.py` (read-only) with the
overlay added as a per-selection invested fraction; the ungated chassis
at count 5 reproduced the champion exactly on all four roads
(LONG $1,415.62 · DECADE $667.35 · CONT $544.47 · VAL $288.05) before
any overlay number counted. Script: `holdings-vm-trendgate/scripts/sweep_vm.py`.
""")
    with open(os.path.join(folder, "results.json"), "w") as f:
        json.dump({"family": slug, "native_count": 5, "roads": res["roads"],
                   "sums": res["sums"], "beats_native": res["beats_native"],
                   "winner": res["winner"], "confirmation": res["confirmation"],
                   "period_dist_DECADE": res["period_dist_DECADE"]}, f, indent=1)
    lines = [f"# HOLDINGS-COUNT SWEEP — {slug} — RESULTS (v12, slice H3)", "",
             desc, "", "## Full grid — house form (final $ per $100; placebos beaten /20, house)",
             "", "| Count | LONG | DECADE | CONT | VAL | Placebos LONG | Placebos DECADE |",
             "|---|---|---|---|---|---|---|"]
    for c in COUNTS:
        row = []
        for r in ROADS:
            v = res["roads"][r][c]["house"]["final"]
            row.append(f"${v:,.2f}")
        pb = []
        for r in ("LONG", "DECADE"):
            b = res["roads"][r][c].get("placebo_beaten")
            pb.append("degenerate" if c == "ALL" else (f"{b}/20" if b is not None else "—"))
        lines.append(f"| {c} | " + " | ".join(row) + " | " + " | ".join(pb) + " |")
    lines += ["", "## Full grid — native form (final $ per $100)", "",
              "| Count | LONG | DECADE | CONT | VAL |", "|---|---|---|---|---|"]
    for c in COUNTS:
        row = [f"${res['roads'][r][c]['native']['final']:,.2f}" for r in ROADS]
        lines.append(f"| {c} | " + " | ".join(row) + " |")
    nat = {r: res["roads"][r]["5"]["house"]["final"] for r in ROADS}
    win = res["winner"]
    best = {r: res["roads"][r][win]["house"]["final"] for r in ROADS}
    conf = res["confirmation"]
    lines += ["", "## Verdict", "",
              f"Native count 5 (house): " + " · ".join(f"{r} ${nat[r]:,.2f}" for r in ROADS),
              f"Best count by 4-road house sum: **{win}** — " +
              " · ".join(f"{r} ${best[r]:,.2f}" for r in ROADS),
              f"Roads beating native (house), by count: {res['beats_native']}",
              (f"Confirmation: candidate {conf['candidate']} — folds {conf['fold_wins']}/10, "
               f"halves {conf['half_wins']}/2, confirmed = {conf['confirmed']}."
               if conf else "Confirmation: not triggered (no non-native count beat native on ≥3 roads)."),
              "", "## Practitioners", "", prac, "",
              "## Per-period distribution", "",
              "Quarterly distribution for the winning and native counts on DECADE",
              "is in `results.json` under `period_dist_DECADE` (computed from the",
              "saved equity curves at the family's quarterly tempo).", "",
              "## Grid gaps", "",
              "Count axis only, native cadence, pond universe, stocks only —",
              "cadence / universe / crypto dimensions are separate grid slices.", ""]
    with open(os.path.join(folder, "RESULTS.md"), "w") as f:
        f.write("\n".join(lines))
    print(slug, "filed; winner", win, "native", nat, "best", best,
          "conf", bool(conf and conf["confirmed"]))
print("FINALIZE DONE")
