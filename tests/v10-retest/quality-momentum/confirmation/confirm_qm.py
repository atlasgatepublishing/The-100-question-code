#!/usr/bin/env python3
"""
QUALITY + MOMENTUM — CONFIRMATION RUN (v10, Terry's confirmation rule).

Question: the decade sweep crowned WEEKLY as a new money cadence
($1,164.49, 20/20 placebos) while the native QUARTERLY cadence was
crushed by placebos (0/20). A changed verdict is not confirmed until
the money cadence is re-run on the OTHER roads. This script re-runs
WEEKLY and QUARTERLY (native, head-to-head) on CONT and VAL with the
identical sweep plumbing (qm_v10.py imported read-only), v9
protections, $100, program costs, point-in-time only, 20-seed
random-rank placebos per road/cadence, plus fresh $100 yearly folds
at WEEKLY.

LONG (2010) is NOT run: see CONFIRMATION.md — at 2010-01-04 only 2 of
the 20 pond names are scoreable in this plumbing (AAPL, V), GOOGL has
no filed quality observation before 2016-02-11, AVGO none before
2018-12-21, and the pond itself is a fixed later-era 20-name list,
not a 2010 point-in-time universe construction. CONT/VAL + folds
carry the verdict.

Integrity gate runs FIRST (original his-rules + v9 published finals
and SPY CONT/VAL through the plumbing); confirmation numbers are
only written if the gate reproduces.
"""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location(
    "qm_v10", os.path.join(PARENT, "qm_v10.py"))
qm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qm)

CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
SEEDS = qm.PLACEBO_SEEDS

PUBLISHED = {
    "his_rules": {"CONT": 100.48, "VAL": 211.54},
    "v9_form": {"CONT": 428.46, "VAL": 211.54},
}
PUBLISHED_HALT = {"CONT": "2020-03-16"}  # his-rules ladder kill
SPY_REF = {"CONT": 313.62, "VAL": 187.77}


def dump(name, obj):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f, indent=1)
    print("WROTE", name, flush=True)


def run_cell(pb, quality, start, end, cadence):
    run = qm.run_v9(pb, quality, start, end, cadence, want_curve=True)
    cagr, mdd = qm.stats(run["curve"], start, end, run["final"])
    twins = []
    beaten = 0
    for seed in SEEDS:
        tw = qm.run_v9(pb, quality, start, end, cadence,
                       placebo_seed=seed)
        twins.append(round(tw["final"], 2))
        if run["final"] > tw["final"]:
            beaten += 1
    out = {"final": round(run["final"], 2), "cagr_pct": cagr,
           "max_dd_pct": mdd, "costs": round(run["costs"], 2),
           "orders": run["orders"], "halts": run["halts"],
           "restart": run["restart"], "second_halt": run["second_halt"],
           "placebo_beaten": f"{beaten}/20",
           "placebo_twin_finals": twins,
           "equity_curve": [[d, v] for d, v in run["curve"]]}
    if run["restart"]:
        out["restart_date"] = run.get("restart_date")
        out["restart_balance"] = round(run.get("restart_balance", 0), 2)
    return out


def main():
    quality = qm.load_quality()

    # ---------------- integrity gate (v4 cache, original forms) ----
    integ = qm.integrity(quality)
    gate = {"status": "reproduced", "checks": []}
    for road in ("CONT", "VAL"):
        for form in ("his_rules", "v9_form"):
            got = integ[road][form]["final"]
            want = PUBLISHED[form][road]
            ok = abs(got - want) < 0.005
            gate["checks"].append({"road": road, "form": form,
                                   "published": want, "reproduced": got,
                                   "match": ok})
            if not ok:
                gate["status"] = "FAILED"
        halt = integ[road]["his_rules"]["halted"]
        if road in PUBLISHED_HALT:
            ok = halt == PUBLISHED_HALT[road]
            gate["checks"].append({"road": road, "form": "his_rules_halt_date",
                                   "published": PUBLISHED_HALT[road],
                                   "reproduced": halt, "match": ok})
            if not ok:
                gate["status"] = "FAILED"
    # SPY on the integrity (v4) plumbing
    bars_v4 = {t: qm.load_bars_v4(t) for t in qm.UNIVERSE + ["SPY"]}
    pb_v4 = qm.PriceBook(bars_v4)
    for road, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        spy_final, _ = qm.spy_net(pb_v4, ws, we)
        ok = abs(round(spy_final, 2) - SPY_REF[road]) < 0.02
        gate["checks"].append({"road": road, "form": "spy_v4_plumbing",
                               "published": SPY_REF[road],
                               "reproduced": round(spy_final, 2),
                               "match": ok})
        if not ok:
            gate["status"] = "FAILED"
    gate["reproduced_finals"] = integ
    dump("integrity.json", gate)
    print("INTEGRITY:", gate["status"], flush=True)
    if gate["status"] != "reproduced":
        print("GATE FAILED — confirmation numbers do not count.", flush=True)
        sys.exit(1)

    # ---------------- confirmation roads (full-range plumbing) -----
    bars = {t: qm.load_bars_full(t) for t in qm.UNIVERSE + ["SPY"]}
    pb = qm.PriceBook(bars)
    roads = {}
    for road, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        spy_final, spy_costs = qm.spy_net(pb, ws, we)
        spy_ok = abs(round(spy_final, 2) - SPY_REF[road]) < 0.02
        print(f"ROAD {road}: SPY=${spy_final:.2f} (ref ${SPY_REF[road]}, "
              f"match={spy_ok})", flush=True)
        for cad in ("weekly", "quarterly"):
            cell = run_cell(pb, quality, ws, we, cad)
            cell.update({"slug": "quality-momentum", "road": road,
                         "cadence": cad, "window": [ws, we],
                         "start_cash": 100.0,
                         "spy_final": round(spy_final, 2),
                         "spy_reference_match": spy_ok})
            dump(f"{road.lower()}_{cad}.json", cell)
            roads.setdefault(road, {})[cad] = {
                k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                     "costs", "orders", "halts", "restart",
                                     "second_halt", "placebo_beaten")}
            print(f"  {cad}: final=${cell['final']} CAGR={cell['cagr_pct']} "
                  f"DD={cell['max_dd_pct']} costs=${cell['costs']} "
                  f"orders={cell['orders']} placebo={cell['placebo_beaten']} "
                  f"halts={len(cell['halts'])}", flush=True)

    # ---------------- yearly folds at WEEKLY (fresh $100) ----------
    folds = {}
    fold_years = [(f"{y}-01-01", f"{y}-12-31") for y in range(2017, 2026)]
    fold_years.append(("2026-01-01", "2026-11-20"))  # partial, labelled
    for ws, we in fold_years:
        label = ws[:4] + ("_partial" if we != f"{ws[:4]}-12-31" else "")
        spy_final, _ = qm.spy_net(pb, ws, we)
        cell = run_cell(pb, quality, ws, we, "weekly")
        folds[label] = {"window": [ws, we], "start_cash": 100.0,
                        "spy_final": round(spy_final, 2),
                        **{k: cell[k] for k in
                           ("final", "cagr_pct", "max_dd_pct", "costs",
                            "orders", "halts", "restart", "second_halt",
                            "placebo_beaten", "placebo_twin_finals",
                            "equity_curve")}}
        print(f"FOLD {label}: final=${cell['final']} SPY=${spy_final:.2f} "
              f"placebo={cell['placebo_beaten']} halts={len(cell['halts'])}",
              flush=True)
    dump("folds.json", {"slug": "quality-momentum", "cadence": "weekly",
                        "note": "Fresh $100 at each fold start; v9 "
                                "protections per fold; 2026 is partial "
                                "(2026-01-01 -> 2026-11-20).",
                        "folds": folds})

    dump("summary.json", {"slug": "quality-momentum",
                          "integrity_status": gate["status"],
                          "spy_ref": SPY_REF, "roads": roads,
                          "long_road": "NOT RUN — see CONFIRMATION.md"})
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
