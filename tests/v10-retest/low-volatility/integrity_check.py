#!/usr/bin/env python3
"""
INTEGRITY GATE — low-volatility (v10 retest).

Reproduces the ORIGINAL published finals in ORIGINAL form through the
original plumbing: the v6/v9 engine (quarterly selection, plain -15%
floor, his rules, no restart), imported verbatim from
backtests/v9-muse-rules/low-volatility/low-volatility-v9.py (which is
itself a verbatim copy of backtests/v6/low-volatility/low-volatility.py
plus the v9 protection module; the ranked engine run_pot_lowvol is
byte-identical in both).

Published targets:
  CONT 2019-01-02 -> 2026-11-20 : $235.34  (placebo 40th pct, 8/20 beaten)
  VAL  2023-01-03 -> 2026-11-20 : $148.85  (placebo 15th pct, 3/20 beaten)
Champion replication check (as in the original): $544.47 / $288.05.
"""
import importlib.util
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V9 = os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/low-volatility/"
    "low-volatility-v9.py")

spec = importlib.util.spec_from_file_location("lowvol_v9", V9)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
E = M.E

START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
EXPECT = {"CONT": 235.34, "VAL": 148.85}
EXPECT_CHAMP = {"CONT": 544.47, "VAL": 288.05}
EXPECT_PCT = {"CONT": (40.0, 8), "VAL": (15.0, 3)}


def main():
    pb, equity_rows, shares_rows = M.build_inputs()
    out = {"published": {"CONT_final": 235.34, "VAL_final": 148.85,
                         "CONT_placebo_percentile": 40.0,
                         "CONT_placebo_seeds_beaten": 8,
                         "VAL_placebo_percentile": 15.0,
                         "VAL_placebo_seeds_beaten": 3},
           "windows": {}}
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        rc = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPL {tag}", quiet=True)
        champ_ok = abs(rc["final"] - EXPECT_CHAMP[tag]) < 0.005
        print(f"CHAMPION REPLICATION {tag}: ${rc['final']:,.2f} "
              f"expected ${EXPECT_CHAMP[tag]:,.2f} match={champ_ok}",
              flush=True)
        r = M.run_pot_lowvol(pb, equity_rows, shares_rows, ws, we,
                             START_CASH, FLOOR0, LADDER,
                             label=f"{tag} LOWVOL", quiet=True)
        ok = abs(r["final"] - EXPECT[tag]) < 0.005
        print(f"INTEGRITY {tag}: lowvol=${r['final']:,.2f} "
              f"expected=${EXPECT[tag]:,.2f} match={ok} "
              f"halted={r['halted']} orders={len(r['trades'])} "
              f"costs=${r['costs']:,.2f}", flush=True)
        out["windows"][tag] = {
            "start": ws, "end": we,
            "champion_reproduced": round(rc["final"], 2),
            "champion_expected": EXPECT_CHAMP[tag],
            "champion_match": champ_ok,
            "reproduced_final": round(r["final"], 2),
            "expected_final": EXPECT[tag], "match": ok,
            "halted": r["halted"], "orders": len(r["trades"]),
            "costs": round(r["costs"], 2)}
        with open(os.path.join(HERE, "integrity.json"), "w") as f:
            json.dump(out, f, indent=1, default=str)
        if not (ok and champ_ok):
            print("INTEGRITY FAILED", flush=True)
            sys.exit(1)
    # placebo percentile reproduction (context: worse than random)
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        ranked = out["windows"][tag]["reproduced_final"]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pr = M.run_pot_lowvol(pb, equity_rows, shares_rows, ws, we,
                                  START_CASH, FLOOR0, LADDER,
                                  placebo_rng=rng,
                                  label=f"{tag} PLACEBO {seed}", quiet=True)
            finals.append(round(pr["final"], 2))
            print(f"  {tag} PLACEBO seed {seed:2d}: ${pr['final']:,.2f}",
                  flush=True)
        below = sum(1 for f in finals if f < ranked)
        ties = sum(1 for f in finals if f == ranked)
        pctile = 100.0 * (below + 0.5 * ties) / len(finals)
        exp_pct, exp_beaten = EXPECT_PCT[tag]
        out["windows"][tag]["placebo"] = {
            "finals": finals, "seeds_beaten": below,
            "percentile": pctile,
            "expected_percentile": exp_pct,
            "expected_seeds_beaten": exp_beaten,
            "match": (below == exp_beaten and abs(pctile - exp_pct) < 0.51)}
        print(f"{tag} PLACEBO: percentile={pctile} beaten={below}/20 "
              f"(published {exp_pct}th, {exp_beaten}/20)", flush=True)
        with open(os.path.join(HERE, "integrity.json"), "w") as f:
            json.dump(out, f, indent=1, default=str)
    out["status"] = "reproduced"
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("INTEGRITY DONE", flush=True)


if __name__ == "__main__":
    main()
