import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from w4lib import *  # noqa

M = load_mod("res_v9", os.path.join(BT, "v9-muse-rules", "residual-momentum",
                                    "residual-momentum-v9.py"))
PUB = {"CONT": 413.31, "VAL": 277.43}


def monthly_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def norm(r, start, end):
    halts = (1 if r["halted"] else 0) + (1 if r.get("second_halt") else 0)
    st = run_stats(r["curve"], r["final"], start, end)
    return {"start": start, "end": end, "final": st["final"],
            "cagr_pct": st["cagr_pct"], "max_dd_pct": st["max_dd_pct"],
            "worst_close": st["worst_close"], "halts": halts,
            "restart": bool(r.get("restarts")),
            "second_halt": bool(r.get("second_halt")),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "placebo_beaten": None}


def chains_for(tickers):
    eq, so = {}, {}
    for t in tickers:
        facts = C.load_facts(C.cik_for(t))
        eq[t] = (champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                 champ.pit_series(facts, "us-gaap",
                     "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        so[t] = (champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                 champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                 champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    return eq, so


def run(pb, eq, so, start, end, placebo=False):
    M.SPY_RET = M.spy_daily_returns(pb)
    r = M.run_pot_resmom(pb, eq, so, start, end, 100.0, 85.0, M.LADDER,
                         label="W4", quiet=True)
    out = norm(r, start, end)
    if placebo:
        pl = M.placebo_block(pb, eq, so, start, end, r["final"], "W4")
        out["placebo_beaten"] = pl["seeds_beaten"]
        out["placebo_median"] = pl["median"]
    return out


# ---------- integrity: ORIGINAL quarterly form, native inputs ----------
pb, eq, so = M.build_inputs()
integ = {}
for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
    M.SPY_RET = M.spy_daily_returns(pb)
    r = M.run_pot_resmom(pb, eq, so, ws, we, 100.0, 85.0, M.LADDER,
                         label="INTEG", quiet=True)
    integ[tag] = {"published": PUB[tag], "reproduced": round(r["final"], 2),
                  "match": abs(r["final"] - PUB[tag]) < 0.011}
    print("INTEG", tag, round(r["final"], 2), "pub", PUB[tag], flush=True)

# ---------- area runs at NATIVE MONTHLY cadence ----------
M.E.quarter_selection_dates = monthly_selection_dates
runs, spy = {}, {}
for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
    runs[tag] = run(pb, eq, so, ws, we, placebo=True)
    spy[tag] = spy_final(pb, ws, we)
    print("MONTHLY", tag, runs[tag], flush=True)

nat = list(M.UNIVERSE)
pb2 = book_for(nat)
eq2, so2 = chains_for(nat)
runs["DECADE"] = run(pb2, eq2, so2, *DEC)
spy["DECADE"] = spy_final(pb2, *DEC)
print("MONTHLY DECADE", runs["DECADE"], "SPY", spy["DECADE"], flush=True)

pb3 = book_for(POND2010)
eq3, so3 = chains_for(POND2010)
runs["LONG"] = run(pb3, eq3, so3, "2010-01-04", END)
spy["LONG"] = spy_final(pb3, "2010-01-04", END)
print("MONTHLY LONG", runs["LONG"], "SPY", spy["LONG"], flush=True)

status = "reproduced" if all(v["match"] for v in integ.values()) else "FAILED"
payload = {
    "slug": "residual-momentum",
    "area": "Pond ranking on the long road (LONG + DECADE + CONT + VAL), run at native monthly cadence",
    "area_source": "SPEC W4 + CADENCE GRID (W4 line): residual-momentum — monthly",
    "cadence": "monthly",
    "original_cadence_foreign": True,
    "original_cadence_note": "Original program test ran it QUARTERLY on the champion chassis; Blitz-Huij-Martens residual momentum is a monthly-rebalanced strategy — the original cadence was foreign.",
    "native_change": "Cadence only: the v9 engine's selection calendar is switched from quarterly to monthly (first trading day of each month); signal (12-1 residual return vs SPY beta), pool gate, costs and v9 protection are unchanged. LONG uses the 2010 pond from long-run-2010; DECADE uses the native Nov-2016 pond with long-run price bars.",
    "integrity": {"status": status,
                  "original_finals": {"CONT": 413.31, "VAL": 277.43},
                  "reproduced_finals": {k: v["reproduced"] for k, v in integ.items()},
                  "notes": "Integrity runs are in the ORIGINAL quarterly form on the engine's own cached inputs: published his-rules finals $413.31 (CONT) / $277.43 (VAL); the v9 sweep recorded identical finals (floor never fired on either main window)."},
    "spy": spy, "runs": runs,
    "champion_finals_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05},
    "verdict_area": "TBD"}
json.dump(payload, open("/tmp/w4/res_payload.json", "w"), indent=1, default=str)
print("DONE_RES", flush=True)
