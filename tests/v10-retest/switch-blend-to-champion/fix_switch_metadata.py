#!/usr/bin/env python3
"""
Metadata fix (reporting only — no simulation logic changes):
re-runs the RANKED biweekly and monthly decade pots with pools built
only for those cadences' selection dates, and prints the episode-2
switch date/close/exec that switch_v10.py's wrapper failed to copy
into cells/biweekly.json and cells/monthly.json. The finals must
match the saved cells exactly ($306.54 / $315.83) — asserted here.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("switch_v10",
                                              os.path.join(
                                                  HERE, "switch_v10.py"))
M = importlib.util.module_from_spec(spec)
# prevent main() from running: switch_v10 guards with __main__, and
# this module's name is not __main__ for it — safe to exec.
spec.loader.exec_module(M)

champ = M.champ
ciks = champ.get_ciks()
facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
for t in M.UNIVERSE:
    cik = {"XOM": 34088}.get(t, ciks[t][0])
    facts = champ.get_companyfacts(cik)
    facts_by_ticker[t] = facts
    equity_rows[t] = (
        champ.pit_series(facts, "us-gaap", "StockholdersEquity",
                         prio=2) +
        champ.pit_series(
            facts, "us-gaap",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            prio=1))
    shares_rows[t] = (
        champ.pit_series(facts, "dei",
                         "EntityCommonStockSharesOutstanding", prio=3) +
        champ.pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
        champ.pit_series(
            facts, "us-gaap",
            "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
bars = {t: champ.get_prices(t) for t in M.UNIVERSE + ["SPY"]}
fb = M.FastBook(bars)
eq_idx = {t: M.PitIndex(equity_rows[t]) for t in M.UNIVERSE}
sh_idx = {t: M.PitIndex(shares_rows[t]) for t in M.UNIVERSE}

out = {}
for cad, expect in (("biweekly", 306.54), ("monthly", 315.83)):
    sel = M.cadence_dates(fb, cad, M.DECADE[0], M.DECADE[1])
    vm_s, nf3_s = {}, {}
    stats = {"direct": 0, "derived": 0}
    for d in sel:
        vm_s[d] = M.vm_pool_picks(fb, eq_idx, sh_idx, d)
        nf3_s[d] = M.nf3_pool_picks(facts_by_ticker, d, stats)
    # episode-level detail: replicate the wrapper's two episode runs
    floor1 = round(0.85 * M.START_CASH, 2)
    r1 = M.run_switch_cadence(fb, vm_s, nf3_s, sel, M.DECADE[0],
                              M.DECADE[1], M.TRIGGER_DECADE,
                              M.START_CASH, floor1)
    print(f"{cad}: ep1 halted={r1['halted']} final={r1['final']:.2f} "
          f"ep1 switch_close={r1['switch_close']}", flush=True)
    from datetime import date as _date
    liq = r1["end"]
    day90 = _date.fromisoformat(liq).toordinal() + 90
    restart = next(d for d in sel
                   if _date.fromisoformat(d).toordinal() >= day90)
    floor2 = round(0.85 * r1["final"], 2)
    sel2 = [d for d in sel if d >= restart]
    r2 = M.run_switch_cadence(fb, vm_s, nf3_s, sel2, restart,
                              M.DECADE[1], M.TRIGGER_DECADE,
                              r1["final"], floor2)
    print(f"{cad}: restart={restart} ep2 final={r2['final']:.2f} "
          f"ep2 switch_date={r2['switch_date']} "
          f"switch_close={r2['switch_close']} "
          f"switch_exec={r2['switch_exec_date']}", flush=True)
    assert round(r2["final"], 2) == expect, (cad, r2["final"], expect)
    out[cad] = {
        "switch_date_episode2": r2["switch_date"],
        "switch_close_episode2": (round(r2["switch_close"], 2)
                                  if r2["switch_close"] is not None
                                  else None),
        "switch_exec_date_episode2": r2["switch_exec_date"],
        "restart_date": restart,
        "final_reproduced": round(r2["final"], 2)}
with open(os.path.join(HERE, "_switch_metadata_fix.json"), "w") as f:
    json.dump(out, f, indent=1)
print("saved _switch_metadata_fix.json")
