#!/usr/bin/env python3
"""
LADDER ABLATION — THE GREAT RETEST (v10). Simulation only.

The protection-rules comparison itself: Terry's profit ladder vs the
adopted plain -15% floor, applied to the CHAMPION (Value+Momentum) in
its own form at its native QUARTERLY cadence, on four roads:
  DECADE 2016-11-21 -> 2026-11-20
  LONG   2010-01-04 -> 2026-11-20
  CONT   2019-01-02 -> 2026-11-20
  VAL    2023-01-03 -> 2026-11-20

The two protection regimes (the ONLY difference between paired runs):
  (a) PLAIN FLOOR — the adopted v9 rules (v9-muse-rules SCOREBOARD,
      app/pots/protection.py): plain -15% floor from each episode's
      starting balance, NO ladder; first halt liquidates at the next
      open, sits in cash 90 calendar days, restarts once at the next
      quarterly selection date under an episode-2 floor of -15% from
      the restart balance; second halt ends the run. Implemented by
      lr_common.run_v9, the long-run test's own wrapper.
  (b) LADDER — Terry's original rules, exactly as every published
      engine ran them (v4 value-momentum-honest.py configs): floor
      $85.00; rungs (close >= $125 -> floor $100.00, i.e. +25% locks
      break-even; close >= $150 -> floor $125.00, i.e. +50% locks
      +25%); a close at/below the floor in effect liquidates at the
      next open and ENDS the run — no restart. NOTE: no tested engine
      ever carried a third (+85%) floor rung; +85% ($100 -> $185) is
      Terry's sprint TARGET in DESIGN.md, whose ladder text lists only
      the +25%/+50% rungs. The ladder tested here is the published
      two-rung form — documented, not patched (see RESULTS.md).

THE CHAMPION'S OWN FORM (why two constructions appear below):
  * DECADE/CONT/VAL run on the champion's FIXED universe — the honest
    Nov-2016 top-30 list carried by every published champion engine
    (champ.UNIVERSE) — with facts from the engine's own caches
    (champ.get_companyfacts, the long-run phase-0 source) and
    dividend-adjusted bars from the long-run pxfull cache (the
    construction whose SPY finals match the task's references to the
    cent on all four roads; phase 0 proved this plumbing reproduces
    the champion's published CONT/VAL finals — and the gates below
    re-prove it here, for both protection regimes).
  * LONG runs on the long-hold construction: the pond rebuilt
    point-in-time at 2010-01-04 from the ~175-name candidate pool
    (the published 2010 pond, reproduced exactly), because the fixed
    Nov-2016 list cannot be known in 2010.
  * DECADE cross-check: the program's existing decade champion number
    ($65.89, lazy-quarterly test) was produced on the Lazy Prices
    module's own price cache. That exact construction is re-run here
    as a cross-check and reported in runs_raw.json; any difference
    from the primary DECADE cell is a price-cache vintage artifact,
    documented in RESULTS.md — never silently merged.

Engine: v4 value-momentum-plainfloor.py imported verbatim via
lr_common (long-run-2010 plumbing, read-only). run_pot takes the
ladder as a parameter, so regime (b) is the same code with the
published ladder list passed in — the exact construction of the
original honest ladder run. Costs 0.10%/side + $0.01/sell. $100 start.

MEMORY NOTE: the first attempt loaded the shared pool loader's full
resident cache and was OOM-killed on this loaded machine; the lean
loaders below keep only PIT chains + adjusted bars per ticker and
discard raw payloads/facts as they go.

Integrity gates (checked in-script, printed, saved to runs_raw.json):
  * LONG plain == $1,415.62; LONG ladder == $85.34 with halt signal
    2010-08-26 at close $84.95 (published long-hold, both rule sets).
  * CONT plain == $544.47; VAL plain == $288.05 (published champion).
  * CONT ladder == $95.53, halt 2020-03-20, signal close $97.32, floor
    in effect $100.00; VAL ladder == $288.05, no halt (published honest
    ladder run, v4 value-momentum-honest-results.json).
  * SPY per road vs the task's dividend-adjusted references.

Outputs (this folder only): cells/<road>-plainfloor.json,
cells/<road>-ladder.json (full equity curves), runs_raw.json,
data/pxfull_GOOGL.json (the one payload no shared cache holds).
"""
import gc
import json
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, "data")
os.makedirs(MYDATA, exist_ok=True)
LR = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

END = "2026-11-20"
ROADS_FIXED = [("DECADE", "2016-11-21"), ("CONT", "2019-01-02"),
               ("VAL", "2023-01-03")]
LADDER = [(125.0, 100.0), (150.0, 125.0)]
SPY_REF = {"DECADE": 367.80, "LONG": 822.94, "CONT": 313.62, "VAL": 187.77}
champ = C.champ

# ------------------------------------------------------------ lean pool
POOL_DATA = {}


def load_pool_lean():
    """For LONG only: chains + adjusted bars for the candidate pool,
    one ticker at a time (raw payloads/facts discarded as we go)."""
    if POOL_DATA:
        return POOL_DATA
    spy_payload = C.yahoo_payload("SPY")
    spy_bars = C.bars_adj(spy_payload)
    spy_dates = [b["d"] for b in spy_bars]
    price_date = max(d for d in spy_dates if d < "2010-01-04")
    chains_by, bars_by, actual, failures = {}, {}, {}, []
    for n, t in enumerate(C.POOL):
        if n % 25 == 0:
            print(f"  pool load {n}/{len(C.POOL)}", flush=True)
        try:
            cik = C.cik_for(t)
        except KeyError:
            failures.append((t, "no CIK (not in tickers file, no override)"))
            continue
        try:
            facts = C.load_facts(cik)
        except Exception as e:  # noqa
            failures.append((t, f"companyfacts failed: {e}"))
            continue
        ename = facts.get("entityName", "?")
        if t in C.NAME_HINTS and C.NAME_HINTS[t].lower() not in ename.lower():
            failures.append((t, f"entityName mismatch: {ename!r} — dropped"))
            del facts
            continue
        chains_by[t] = (C.equity_chain(facts), C.shares_chain(facts))
        del facts
        try:
            payload = C.yahoo_payload(t)
            if not payload["chart"]["result"]:
                raise RuntimeError("empty chart result")
        except Exception as e:  # noqa
            failures.append((t, f"yahoo failed: {e}"))
            del chains_by[t]
            continue
        bars_by[t] = C.bars_adj(payload)
        actual[(t, price_date)] = C.actual_close_on_or_before(
            payload, price_date)
        del payload
    bars_by["SPY"] = spy_bars
    del spy_payload
    gc.collect()
    POOL_DATA.update(chains_by=chains_by, bars_by=bars_by,
                     spy_dates=spy_dates, actual=actual,
                     failures=failures)
    print(f"  pool loaded: {len(chains_by)} tickers", flush=True)
    return POOL_DATA


def pond_at_2010(P):
    """lr_common.build_pond logic with precomputed actual closes."""
    start = "2010-01-04"
    price_date = max(d for d in P["spy_dates"] if d < start)
    rows = []
    for t in P["chains_by"]:
        so = champ.pit_value(P["chains_by"][t][1], start)
        if so is None:
            continue
        px, px_d = P["actual"][(t, price_date)]
        if px is None:
            continue
        gap = (date(int(price_date[:4]), int(price_date[5:7]),
                    int(price_date[8:10])) -
               date(int(px_d[:4]), int(px_d[5:7]),
                    int(px_d[8:10]))).days
        if gap > 10:
            continue
        rows.append({"ticker": t, "market_cap_usd": so[2] * px})
    rows.sort(key=lambda r: -r["market_cap_usd"])
    return [r["ticker"] for r in rows[:30]]


# ------------------------------------------------------- fixed universe
def load_fixed_universe():
    """The champion's own form for DECADE/CONT/VAL: champ.UNIVERSE,
    chains from the engine's own fact caches (phase-0 source), bars
    from the long-run pxfull cache (read-only); GOOGL — which the
    long-run cache keys as GOOG — is fetched once into THIS folder."""
    universe = list(champ.UNIVERSE)
    ciks = champ.get_ciks()
    eq, so = {}, {}
    for t in universe:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = champ.get_companyfacts(cik)
        eq[t], so[t] = C.equity_chain(facts), C.shares_chain(facts)
        del facts
    bars = {}
    for t in universe + ["SPY"]:
        if t == "GOOGL":
            path = os.path.join(MYDATA, "pxfull_GOOGL.json")
            if os.path.exists(path):
                with open(path) as f:
                    payload = json.load(f)
            else:
                import calendar
                t1 = calendar.timegm(time.strptime("2008-01-01",
                                                   "%Y-%m-%d"))
                t2 = calendar.timegm(time.strptime("2026-11-22",
                                                   "%Y-%m-%d"))
                url = ("https://query1.finance.yahoo.com/v8/finance/"
                       f"chart/GOOGL?period1={t1}&period2={t2}"
                       "&interval=1d&events=div,split")
                blob = C.fetch_cached(
                    url, path, headers={"User-Agent": "Mozilla/5.0"})
                payload = json.loads(blob)
            bars[t] = C.bars_adj(payload)
            del payload
        else:
            bars[t] = C.bars_adj(C.yahoo_payload(t))
    pb = C.FastPriceBook(bars)
    return universe, eq, so, pb


# ------------------------------------------------------------- runners
def _episodes(v9):
    eps, cash = [], C.START_CASH
    for ep in v9["episodes"]:
        floor = 0.85 * cash
        d = C.curve_diagnostics(ep["curve"], cash)
        eps.append({"start_cash": round(cash, 2), "floor": round(floor, 2),
                    "final": round(ep["final"], 2),
                    "halted": ep["halted"], "halt_info": ep.get("halt_info"),
                    "end": ep["end"], "costs": round(ep["costs"], 2),
                    "orders": len(ep["trades"]),
                    "worst_close": d["worst_close"],
                    "worst_close_date": d["worst_close_date"],
                    "max_drawdown_pct": d["max_drawdown_pct"]})
        cash = ep["final"]
    return eps


def run_plain(pb, eq, so, universe, start, end):
    saved = champ.UNIVERSE
    champ.UNIVERSE = universe
    try:
        def run_one(s, e, cash, floor):
            return champ.run_pot(pb, eq, so, s, e, cash, floor, [],
                                 label="V10 PLAIN", quiet=True,
                                 record_pools=True)
        v9 = C.run_v9(run_one, pb.dates, start, end)
        spy, _ = champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        champ.UNIVERSE = saved
    cg, _ = C.cagr(v9["final"], C.START_CASH, start, end)
    return {"final": round(v9["final"], 2), "cagr_pct": cg,
            "costs": round(v9["costs"], 2), "orders": v9["orders"],
            "halts": v9["halts"], "restart": v9["restart"],
            "episodes": _episodes(v9),
            "diag": C.curve_diagnostics(v9["curve"]),
            "spy_final": round(spy, 2), "curve": v9["curve"]}


def run_ladder(pb, eq, so, universe, start, end):
    saved = champ.UNIVERSE
    champ.UNIVERSE = universe
    try:
        r = champ.run_pot(pb, eq, so, start, end, C.START_CASH, 85.0,
                          list(LADDER), label="V10 LADDER", quiet=True)
        spy, _ = champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        champ.UNIVERSE = saved
    curve = list(r["curve"])
    if r["halted"] and (not curve or curve[-1][0] != r["end"]):
        curve.append((r["end"], round(r["final"], 2)))
    halts = []
    if r["halted"]:
        fl = r["halt_info"]["floor_in_effect"]
        halts.append({"episode": 1, "signal_date": r["halted"],
                      "signal_close": r["halt_info"]["signal_close"],
                      "floor_in_effect": fl,
                      "cause": ("initial -15% floor" if fl <= 85.0 + 1e-9
                                else "ladder-ratcheted floor"),
                      "liquidation_date": r["end"],
                      "proceeds": round(r["final"], 2)})
    engaged = []
    for thresh, newfloor in LADDER:
        for d, v in r["curve"]:
            if v >= thresh:
                engaged.append({"threshold_close": thresh,
                                "new_floor": newfloor, "date": d,
                                "close": round(v, 2)})
                break
    cg, _ = C.cagr(r["final"], C.START_CASH, start, end)
    return {"final": round(r["final"], 2), "cagr_pct": cg,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halts": halts, "restart": None, "episodes": [],
            "ladder_rungs_engaged": engaged,
            "diag": C.curve_diagnostics(curve),
            "spy_final": round(spy, 2), "curve": curve}


def cell(road, start, regime, run, universe_note):
    c = {"road": road, "protection": regime, "start": start, "end": END,
         "start_cash": 100.0, "universe": universe_note,
         "final": run["final"], "cagr_pct": run["cagr_pct"],
         "max_dd_pct": run["diag"]["max_drawdown_pct"],
         "max_dd_date": run["diag"]["max_drawdown_date"],
         "worst_close": run["diag"]["worst_close"],
         "worst_close_date": run["diag"]["worst_close_date"],
         "costs": run["costs"], "orders": run["orders"],
         "halts": run["halts"], "n_halts": len(run["halts"]),
         "restart": run.get("restart"),
         "second_halt": bool(run.get("restart") and
                             run["restart"].get("second_halt")),
         "spy_final": run["spy_final"], "spy_ref_task": SPY_REF[road],
         "equity_curve": [[d, round(v, 2)] for d, v in run["curve"]]}
    if run.get("episodes"):
        c["episodes"] = run["episodes"]
    if run.get("ladder_rungs_engaged") is not None:
        c["ladder_rungs_engaged"] = run["ladder_rungs_engaged"]
    return c


def slim(run_cell):
    return {k: run_cell[k] for k in
            ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
             "halts", "restart", "second_halt", "spy_final")}


def main():
    t0 = time.time()
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    raw = {"roads": {}, "integrity": {}, "crosschecks": {}}

    # ---------- fixed-universe roads: DECADE / CONT / VAL ----------
    universe, eq, so, pb = load_fixed_universe()
    print(f"fixed universe ({len(universe)}): {universe}", flush=True)
    raw["fixed_universe"] = universe
    for road, start in ROADS_FIXED:
        plain = run_plain(pb, eq, so, universe, start, END)
        lad = run_ladder(pb, eq, so, universe, start, END)
        print(f"== {road} plain : final={plain['final']} halts="
              f"{[h['signal_date'] for h in plain['halts']]} "
              f"costs={plain['costs']} orders={plain['orders']} "
              f"spy={plain['spy_final']}", flush=True)
        print(f"== {road} ladder: final={lad['final']} halts="
              f"{[h['signal_date'] for h in lad['halts']]} "
              f"costs={lad['costs']} orders={lad['orders']} "
              f"rungs={lad['ladder_rungs_engaged']}", flush=True)
        pc = cell(road, start, "plain-floor-v9", plain,
                  "champion fixed Nov-2016 top-30 (champ.UNIVERSE)")
        lc = cell(road, start, "profit-ladder-his-rules", lad,
                  "champion fixed Nov-2016 top-30 (champ.UNIVERSE)")
        lc["ladder_rungs_engaged"] = lad["ladder_rungs_engaged"]
        for name, c in ((f"{road.lower()}-plainfloor", pc),
                        (f"{road.lower()}-ladder", lc)):
            with open(os.path.join(HERE, "cells", name + ".json"),
                      "w") as f:
                json.dump(c, f, indent=1)
        raw["roads"][road] = {
            "start": start, "universe": universe,
            "plain": slim(pc), "ladder": {**slim(lc),
                                          "ladder_rungs_engaged":
                                          lad["ladder_rungs_engaged"]},
            "delta_ladder_minus_plain": round(lad["final"] -
                                              plain["final"], 2)}
        del plain, lad, pc, lc
        gc.collect()

    # ---------- DECADE cross-check on the Lazy price cache ----------
    # The lazy-quarterly decade champion ($65.89) was built on the Lazy
    # Prices module's own price cache. Re-run that exact construction
    # (read-only: only if every cache file already exists, so the
    # module's get_prices can never fetch/write into shared folders).
    try:
        lazy = C.load_module("lazy_xchk", os.path.join(
            C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
        need = list(lazy.UNIVERSE) + ["SPY"]
        cached = all(os.path.exists(os.path.join(
            lazy.HONEST_DATA, f"px_{t}.json")) for t in need)
        raw["crosschecks"]["decade_lazy_book_cache_complete"] = cached
        if cached:
            book_l = lazy.PriceBook({t: lazy.get_prices(t) for t in need})
            xp = run_plain(book_l, eq, so, list(lazy.UNIVERSE),
                           "2016-11-21", END)
            xl = run_ladder(book_l, eq, so, list(lazy.UNIVERSE),
                            "2016-11-21", END)
            raw["crosschecks"]["decade_on_lazy_price_cache"] = {
                "plain_final": xp["final"], "plain_halts": xp["halts"],
                "plain_costs": xp["costs"], "plain_orders": xp["orders"],
                "ladder_final": xl["final"], "ladder_halts": xl["halts"],
                "ladder_rungs_engaged": xl["ladder_rungs_engaged"],
                "spy_final_lazy_book": xp["spy_final"],
                "note": "construction of backtests/lazy-quarterly "
                        "decade_champion (Lazy module price cache, "
                        "fixed Nov-2016 pond, v9 wrapper)"}
            print(f"XCHK decade lazy-book: plain={xp['final']} "
                  f"ladder={xl['final']} spy={xp['spy_final']}",
                  flush=True)
            del book_l, xp, xl
            gc.collect()
    except Exception as e:  # noqa
        raw["crosschecks"]["decade_lazy_book_error"] = str(e)
        print(f"XCHK failed: {e}", flush=True)

    # ---------- LONG on the rebuilt 2010 pond ----------
    P = load_pool_lean()
    pond = pond_at_2010(P)
    print(f"== LONG pond({len(pond)}): {pond}", flush=True)
    raw["long_pond"] = pond
    raw["pool_failures"] = [list(f) for f in P["failures"]]
    eq_l = {t: P["chains_by"][t][0] for t in pond}
    so_l = {t: P["chains_by"][t][1] for t in pond}
    bars_l = {t: P["bars_by"][t] for t in pond}
    bars_l["SPY"] = P["bars_by"]["SPY"]
    pb_l = C.FastPriceBook(bars_l)
    plain = run_plain(pb_l, eq_l, so_l, pond, "2010-01-04", END)
    lad = run_ladder(pb_l, eq_l, so_l, pond, "2010-01-04", END)
    print(f"== LONG plain : final={plain['final']} halts="
          f"{[h['signal_date'] for h in plain['halts']]} "
          f"costs={plain['costs']} orders={plain['orders']} "
          f"spy={plain['spy_final']}", flush=True)
    print(f"== LONG ladder: final={lad['final']} halts="
          f"{[h['signal_date'] for h in lad['halts']]} "
          f"costs={lad['costs']} orders={lad['orders']}", flush=True)
    pc = cell("LONG", "2010-01-04", "plain-floor-v9", plain,
              "point-in-time top-30 rebuilt at 2010-01-04 (long-hold "
              "construction)")
    lc = cell("LONG", "2010-01-04", "profit-ladder-his-rules", lad,
              "point-in-time top-30 rebuilt at 2010-01-04 (long-hold "
              "construction)")
    lc["ladder_rungs_engaged"] = lad["ladder_rungs_engaged"]
    for name, c in (("long-plainfloor", pc), ("long-ladder", lc)):
        with open(os.path.join(HERE, "cells", name + ".json"), "w") as f:
            json.dump(c, f, indent=1)
    raw["roads"]["LONG"] = {
        "start": "2010-01-04", "universe": pond, "plain": slim(pc),
        "ladder": {**slim(lc),
                   "ladder_rungs_engaged": lad["ladder_rungs_engaged"]},
        "delta_ladder_minus_plain": round(lad["final"] - plain["final"],
                                          2)}

    # ---------------- integrity gates ----------------
    def chk(name, got, want, tol=0.011):
        ok = got is not None and abs(got - want) <= tol
        raw["integrity"][name] = {"published": want, "reproduced": got,
                                  "match": bool(ok)}
        print(f"INTEGRITY {name}: published={want} reproduced={got} "
              f"-> {'MATCH' if ok else 'MISMATCH'}", flush=True)
    R = raw["roads"]
    chk("LONG plain final (v9 long-hold)", R["LONG"]["plain"]["final"],
        1415.62)
    chk("LONG ladder final (his-rules long-hold)",
        R["LONG"]["ladder"]["final"], 85.34)
    lh = R["LONG"]["ladder"]["halts"]
    chk("LONG ladder halt signal close",
        lh[0]["signal_close"] if lh else None, 84.95)
    raw["integrity"]["LONG ladder halt signal date"] = {
        "published": "2010-08-26",
        "reproduced": lh[0]["signal_date"] if lh else None,
        "match": bool(lh and lh[0]["signal_date"] == "2010-08-26")}
    chk("CONT plain final", R["CONT"]["plain"]["final"], 544.47)
    chk("VAL plain final", R["VAL"]["plain"]["final"], 288.05)
    chk("CONT ladder final (honest ladder run)",
        R["CONT"]["ladder"]["final"], 95.53)
    ch = R["CONT"]["ladder"]["halts"]
    chk("CONT ladder halt signal close",
        ch[0]["signal_close"] if ch else None, 97.32)
    chk("CONT ladder floor in effect",
        ch[0]["floor_in_effect"] if ch else None, 100.00)
    raw["integrity"]["CONT ladder halt signal date"] = {
        "published": "2020-03-20",
        "reproduced": ch[0]["signal_date"] if ch else None,
        "match": bool(ch and ch[0]["signal_date"] == "2020-03-20")}
    chk("VAL ladder final (honest ladder run, no halt)",
        R["VAL"]["ladder"]["final"], 288.05)
    xc = raw["crosschecks"].get("decade_on_lazy_price_cache", {})
    chk("DECADE plain final on lazy-quarterly construction",
        xc.get("plain_final"), 65.89)
    for road in SPY_REF:
        chk(f"{road} SPY final", R[road]["plain"]["spy_final"],
            SPY_REF[road], tol=0.51)
    with open(os.path.join(HERE, "runs_raw.json"), "w") as f:
        json.dump(raw, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s — cells + runs_raw.json written",
          flush=True)


if __name__ == "__main__":
    main()
