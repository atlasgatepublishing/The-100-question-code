#!/usr/bin/env python3
"""
INTEGRITY GATE — buyback-events (v10 retest).

Reproduces the ORIGINAL published record through the ORIGINAL v6 engine
(backtests/v6/buyback-events/buyback-events.py, original single-halt
protection) in its original form and windows, and compares every number
to the original results JSON (buyback-events-results.json) to the cent:

  - champion replication (the engine's own mandatory gate):
    FULL pot $544.47 / SPY $313.62; VALIDATION pot $288.05 / SPY $187.77
  - pots: FULL real $314.04, FULL placebo(+6mo) $89.85 halted 2020-03-23,
    VALIDATION real $213.22, VALIDATION placebo $224.06
  - standalone per-event summaries (completed holds only)
  - yearly folds 2020-2026 (real pot finals + halts)

Writes integrity_results.json beside this script. Simulation only.
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
V6_PATH = os.path.join(HERE, "..", "..", "v6", "buyback-events",
                       "buyback-events.py")
ORIG_JSON = os.path.join(HERE, "..", "..", "v6", "buyback-events",
                         "buyback-events-results.json")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    eng = load(V6_PATH, "buyback_v6_original")
    champ = eng.load_champion()
    with open(ORIG_JSON) as f:
        orig = json.load(f)

    # ---- champion replication (mandatory gate, as in the original) ----
    ciks = champ.get_ciks()
    equity_rows, shares_rows = {}, {}
    for t in champ.UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        del facts
    bars = {}
    for t in champ.UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
    pb = champ.PriceBook(bars)
    rep = {}
    for wname, ws, we in (("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")):
        r = champ.run_pot(pb, equity_rows, shares_rows, ws, we, 100.0, 85.0,
                          [], label=f"REPLICATION {wname}", quiet=True)
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        rep[wname] = {"pot": round(r["final"], 2), "spy": round(s, 2)}
        print(f"replication {wname}: pot=${rep[wname]['pot']} spy=${rep[wname]['spy']}", flush=True)
    del equity_rows, shares_rows, bars

    cal = eng.Cal(pb)
    events = sorted(eng.EVENTS, key=lambda e: e[1])
    placebo_events = sorted(
        [(tk, eng.add_months(fd, 6), note) for tk, fd, note in eng.EVENTS],
        key=lambda e: e[1])

    checks = []

    def check(name, reproduced, published):
        ok = reproduced == published
        checks.append({"item": name, "reproduced": reproduced,
                       "published": published, "match": ok})
        print(f"{'OK ' if ok else 'FAIL'} {name}: reproduced={reproduced} published={published}", flush=True)

    check("champion FULL pot", rep["FULL"]["pot"], orig["replication"]["FULL"]["pot"])
    check("champion FULL SPY", rep["FULL"]["spy"], orig["replication"]["FULL"]["spy"])
    check("champion VALIDATION pot", rep["VALIDATION"]["pot"], orig["replication"]["VALIDATION"]["pot"])
    check("champion VALIDATION SPY", rep["VALIDATION"]["spy"], orig["replication"]["VALIDATION"]["spy"])

    # ---- standalone per-event summaries --------------------------------
    sa = [eng.standalone(cal, t, d) for t, d, _ in events]
    sa_full = [r for r in sa if r and not r["truncated"]]
    ssum = eng.summarize(sa_full)
    check("standalone real completed-holds summary", ssum,
          orig["standalone_real"]["completed_holds_only"])
    sap = [eng.standalone(cal, t, d) for t, d, _ in placebo_events]
    sap_full = [r for r in sap if r and not r["truncated"]]
    psum = eng.summarize(sap_full)
    check("standalone placebo completed-holds summary", psum,
          orig["standalone_placebo"]["completed_holds_only"])

    # ---- pots ------------------------------------------------------------
    pots = {}
    for wname, ws, we in (("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")):
        for tag, evs in (("real", events), ("placebo", placebo_events)):
            r = eng.run_event_pot(cal, evs, ws, we, f"{wname} {tag}")
            key = f"{wname}_{tag}"
            pots[key] = {"final": r["final"], "costs": r["costs"],
                         "halted": r["halted"],
                         "events_eligible": r["events_eligible"]}
            pub = orig["pots"][key]
            check(f"pot {key} final", r["final"], pub["final"])
            check(f"pot {key} costs", r["costs"], pub["costs"])
            check(f"pot {key} halted", r["halted"], pub["halted"])
            check(f"pot {key} events_eligible", r["events_eligible"], pub["events_eligible"])

    # ---- folds -------------------------------------------------------------
    folds = {}
    for y in range(2020, 2027):
        ws = f"{y}-01-01"
        we = "2026-11-20" if y == 2026 else f"{y}-12-31"
        r = eng.run_event_pot(cal, events, ws, we, f"FOLD {y} real")
        folds[str(y)] = {"final": r["final"], "halted": r["halted"]}
        pub = orig["folds"][str(y)]["real"]
        check(f"fold {y} real final", r["final"], pub["final"])
        check(f"fold {y} real halted", r["halted"], pub["halted"])

    n_ok = sum(1 for c in checks if c["match"])
    status = "reproduced" if n_ok == len(checks) else "FAILED"
    out = {
        "integrity_status": status,
        "checks_passed": f"{n_ok}/{len(checks)}",
        "engine_used": "backtests/v6/buyback-events/buyback-events.py (original, single-halt protection)",
        "published_source": "backtests/v6/buyback-events/buyback-events-results.json + buyback-events.md",
        "checks": checks,
        "replication": rep,
        "pots": pots,
        "standalone_real_completed": ssum,
        "standalone_placebo_completed": psum,
        "folds": folds,
    }
    with open(os.path.join(HERE, "integrity_results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"INTEGRITY: {status} ({n_ok}/{len(checks)} checks)", flush=True)


if __name__ == "__main__":
    main()
