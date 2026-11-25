#!/usr/bin/env python3
"""
V10 GREAT RETEST — CONFIRMATION RUN for quality-standalone (Novy-Marx GP/A).

Terry's CONFIRMATION RULE (SPEC.md): the decade sweep FLIPPED the verdict
("no edge shown" -> REAL BUT SMALL, native ANNUAL best $553.14, 14/20).
A flipped verdict is not crowned until the money cadence is re-run on the
other roads. This script does exactly that, frozen spec, one clean shot:

  1. INTEGRITY GATE: original v9 engine verbatim, v4 price cache, quarterly
     form -> CONT $308.29 / VAL $195.05 must reproduce to the cent before
     any confirmation number counts. SPY verified in-plumbing on every
     window (CONT $313.62, VAL $187.77, LONG $822.94, DECADE $367.80).
  2. CONT (2019-01-02->2026-11-20) and VAL (2023-01-03->2026-11-20) at
     ANNUAL (native) and QUARTERLY (original tempo), identical sweep
     plumbing (run_v10.py's generalized engine, copied verbatim except
     finish() computes CAGR from the run's own window and selections are
     recorded), v9 protections, $100, program costs, PIT only, 20-seed
     random-pick placebos per road/cadence (same design as the sweep).
  3. LONG (2010-01-04->2026-11-20): the published pond is the Nov-2016
     top-30 — running IT from 2010 would be a fixed-later-universe run,
     which is banned. Instead the pond is REBUILT point-in-time at
     2010-01-04 using the program's own long-run construction
     (long-run-2010/lr_common.build_pond: PIT shares x actual close over
     its 175-name candidate pool), and the ROA-substitution flag is
     re-derived by the original's own mechanical rule relative to the
     LONG first selection (usable GP/OPINC observation filed on/after
     first-selection minus 548 days; the published form used exactly
     this rule with 2019-01-02 -> cutoff 2017-07-03). quality_value
     itself is fully PIT (filed strictly before asof, 548-day gate), so
     the scoring is honest back to 2010. Facts loaded ONE NAME AT A TIME
     (the 1.7GB long-run cache is never bulk-loaded).
  4. Fresh yearly folds: fresh $100 per calendar year 2017-2026 (the
     first full years after the Nov-2016 pond formation) at ANNUAL on
     the published pond, + SPY + 20-seed placebos per fold.
  5. UNH ARTIFACT: carried in every headline number exactly as the
     original handled it (documented, never patched). Measured, where
     measurable: UNH selection frequency/rank per run, and a clearly
     labelled DIAGNOSTIC ex-UNH run per road/cadence (not a headline
     number — it only sizes the artifact's contribution).

Outputs (this folder): integrity.json, cont_annual.json,
cont_quarterly.json, val_annual.json, val_quarterly.json,
long_annual.json, long_quarterly.json, folds.json — each with final,
CAGR, max DD, costs, orders, halts/restarts WITH DATES, the full equity
curve, and all 20 placebo twin finals.
"""
import importlib.util, json, os, random, sys, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH, FLOOR0 = 100.0, 85.0

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

# Sweep plumbing: import run_v10 (loads the v9 quality engine + champion
# engine); reuse its data loaders verbatim.
RV = load("run_v10", os.path.join(BT, "v10-retest", "quality-standalone", "run_v10.py"))
Q, E = RV.Q, RV.E
UNIVERSE = RV.UNIVERSE
load_pxfull = RV.load_pxfull
FastBook = RV.FastBook

# ---------------- cadence selection dates (verbatim from run_v10.py) ----
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily": return days
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        iso = date(y, m, int(d[8:10])).isocalendar()
        if cadence == "weekly": key = (iso[0], iso[1])
        elif cadence == "biweekly":
            wk = (date(y, m, int(d[8:10])) - date(2016, 11, 21)).days // 7
            key = ("bw", wk // 2 * 2) if wk % 2 == 0 else None
            if key is None: continue
        elif cadence == "monthly": key = (y, m)
        elif cadence == "quarterly":
            if m not in (1, 4, 7, 10): continue
            key = (y, m)
        elif cadence == "semiannual":
            if m not in (1, 7): continue
            key = (y, m)
        elif cadence == "annual": key = (y,)
        if key not in seen: seen.add(key); out.append(d)
    return out

# ---------------- generalized engine (run_v10.run_pot, verbatim mechanics;
# finish() takes the run's own window; selections recorded) ---------------
def run_pot(pb, scores_by_date, sel_dates, start, end, placebo_rng=None):
    cash, floor = START_CASH, FLOOR0
    positions, trades, total_costs = {}, [], 0.0
    episode, resume, restarts, curve = 1, None, [], []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    pending = None
    selections = []
    def pclose(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(positions):
            if t not in opens: continue
            cur = positions[t] * opens[t]; tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt; sh = sv / opens[t]; c = sv * 0.001 + 0.01
                cash += sv - c; total_costs += c; positions[t] -= sh
                trades.append((d, t, "SELL", round(sh, 6), opens[t], round(sv, 2), round(c, 4)))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur = positions.get(t, 0.0) * opens[t]; bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, cash / 1.001)
                if bv <= 0.005: continue
                sh = bv / opens[t]; c = bv * 0.001
                cash -= bv + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(sh, 6), opens[t], round(bv, 2), round(c, 4)))
    second_halt, halt_dates = False, []
    for di, d in enumerate(days):
        if pending is not None: execute(d, pending); pending = None
        if d in sel_set and (resume is None or d >= resume):
            scores = scores_by_date.get(d, {})
            if len(scores) >= 5:
                if placebo_rng is not None: picks = placebo_rng.sample(sorted(scores), 5)
                else: picks = sorted(scores, key=lambda t: (-scores[t], t))[:5]
                if placebo_rng is None:
                    ranked = sorted(scores, key=lambda t: (-scores[t], t))
                    selections.append({"date": d,
                                       "picks": [[t, round(scores[t], 4)] for t in picks],
                                       "unh_rank": (ranked.index("UNH") + 1) if "UNH" in ranked else None,
                                       "unh_score": round(scores["UNH"], 4) if "UNH" in scores else None})
                pv = pclose(d); pending = {t: pv / 5.0 for t in picks}
        v = pclose(d); curve.append((d, round(v, 4)))
        if v <= floor and di < len(days) - 1:
            nd = days[di + 1]; halt_dates.append(d)
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]; c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", round(positions[t], 6), b["o"], round(val, 2), round(c, 4)))
            positions = {}
            if episode == 1:
                episode = 2
                resume = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2), "resume_on_or_after": resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash; pending = None
            else:
                second_halt = True
                return finish(cash, total_costs, trades, curve, halt_dates, restarts, True, start, end, selections)
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_; cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6), c_, round(val, 2), round(cst, 4)))
    return finish(cash, total_costs, trades, curve, halt_dates, restarts, second_halt, start, end, selections)

def finish(cash, costs, trades, curve, halts, restarts, second, start, end, selections):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return {"final": round(cash, 2), "cagr_pct": round(((cash / 100.0) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": len(trades), "halts": len(halts), "halt_dates": halts,
            "restart": bool(restarts), "restarts": restarts, "second_halt": second,
            "curve": curve, "trades": trades, "selections": selections}

# ---------------- helpers -------------------------------------------------
def scores_for(qdata, universe, sel_dates):
    out = {}
    for d in sel_dates:
        s = {}
        for t in universe:
            qv = Q.quality_value(qdata, t, d)
            if qv is not None: s[t] = qv[0]
        out[d] = s
    return out

def run_cell(pb, qdata, universe, cadence, start, end, tag):
    sd = cadence_dates(pb, cadence, start, end)
    scores = scores_for(qdata, universe, sd)
    r = run_pot(pb, scores, sd, start, end)
    placebo_finals = []
    for seed in range(1, 21):
        pr = run_pot(pb, scores, sd, start, end, placebo_rng=random.Random(seed))
        placebo_finals.append(round(pr["final"], 2))
    beaten = sum(1 for f in placebo_finals if f < r["final"])
    # DIAGNOSTIC ONLY (not a headline): same run with UNH removed from the
    # score tables, to size the artifact's contribution.
    diag = None
    if any("UNH" in s for s in scores.values()):
        scores_x = {d: {t: v for t, v in s.items() if t != "UNH"} for d, s in scores.items()}
        dr = run_pot(pb, scores_x, sd, start, end)
        diag = {"note": "DIAGNOSTIC ONLY — headline numbers keep UNH exactly as published; "
                        "this run merely sizes the artifact's contribution.",
                "final_ex_unh": dr["final"], "costs_ex_unh": dr["costs"], "orders_ex_unh": dr["orders"]}
    sels = r["selections"]
    unh = {"selections_total": len(sels),
           "unh_picked": sum(1 for s in sels if any(p[0] == "UNH" for p in s["picks"])),
           "unh_rank1": sum(1 for s in sels if s["unh_rank"] == 1),
           "diagnostic": diag}
    cell = {"road": tag, "cadence": cadence, "start": start, "end": end,
            "final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"], "halts": r["halts"],
            "halt_dates": r["halt_dates"], "restart": r["restart"], "restarts": r["restarts"],
            "second_halt": r["second_halt"], "placebo_beaten": beaten,
            "placebo_finals": placebo_finals, "equity_curve": r["curve"],
            "selections": sels, "unh_artifact": unh}
    print(tag, cadence, "final", r["final"], "placebo", beaten, "/20",
          "UNH picked", unh["unh_picked"], "/", unh["selections_total"],
          "diag ex-UNH", (diag or {}).get("final_ex_unh"), flush=True)
    return cell

def save(name, obj):
    with open(os.path.join(HERE, name), "w") as f: json.dump(obj, f, indent=1)

def main():
    t0 = time.time()
    # ============ 1. INTEGRITY GATE (original engine, v4 cache) ============
    qdata = RV.build_qdata()
    bars4 = {t: E.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb4 = E.PriceBook(bars4)
    integ = {}
    for wname, ws, we, pub in (("CONT", "2019-01-02", "2026-11-20", 308.29),
                               ("VAL", "2023-01-03", "2026-11-20", 195.05)):
        r = Q.run_pot_q(pb4, qdata, ws, we, START_CASH, FLOOR0, [], label="INTEG", quiet=True)
        spy4, _ = E.spy_net(pb4, ws, we, START_CASH)
        integ[wname] = {"published": pub, "reproduced": round(r["final"], 2),
                        "match": round(r["final"], 2) == pub,
                        "orders": len(r["trades"]), "costs": round(r["costs"], 2),
                        "halted": r["halted"], "spy_v4cache": round(spy4, 2)}
        print("INTEGRITY", wname, integ[wname], flush=True)
    if not all(v["match"] for v in integ.values()):
        save("integrity.json", {"status": "FAILED", "windows": integ})
        print("INTEGRITY GATE FAILED — aborting before any confirmation number counts.", flush=True)
        sys.exit(1)

    # ============ pxfull book (sweep plumbing) for CONT/VAL/folds =========
    bars = {t: load_pxfull(t) for t in UNIVERSE + ["SPY"]}
    pb = FastBook(bars)
    spy = {}
    for nm, ws, we in (("CONT", "2019-01-02", "2026-11-20"), ("VAL", "2023-01-03", "2026-11-20"),
                       ("DECADE", "2016-11-21", "2026-11-20"), ("LONG", "2010-01-04", "2026-11-20")):
        f, _ = E.spy_net(pb, ws, we, START_CASH)
        spy[nm] = round(f, 2)
    print("SPY in-plumbing (pxfull):", spy, flush=True)
    save("integrity.json", {"status": "reproduced",
                            "original_finals": {"CONT": 308.29, "VAL": 195.05},
                            "windows": integ, "spy_pxfull": spy,
                            "spy_reference": {"CONT": 313.62, "VAL": 187.77, "LONG": 822.94, "DECADE": 367.80},
                            "note": "Original v9 engine imported verbatim, v4 price cache, quarterly form. "
                                    "UNH artifact carried exactly as original (fake GP figure, ranked #1 on a "
                                    "wrong reason, ~20% of the pot) — documented, NOT patched."})

    # ============ 2. CONT + VAL at ANNUAL and QUARTERLY ===================
    for road, ws, we in (("cont", "2019-01-02", "2026-11-20"), ("val", "2023-01-03", "2026-11-20")):
        for cad in ("annual", "quarterly"):
            cell = run_cell(pb, qdata, UNIVERSE, cad, ws, we, road.upper())
            cell["spy_final"] = spy[road.upper()]
            save(f"{road}_{cad}.json", cell)
    print("CONT/VAL done", time.time() - t0, flush=True)

    # ============ 4. Fresh yearly folds at ANNUAL (published pond) =======
    folds = {}
    for yr in range(2017, 2027):
        days = [d for d in pb.dates if d[:4] == str(yr)]
        ws, we = days[0], days[-1]
        cell = run_cell(pb, qdata, UNIVERSE, "annual", ws, we, f"FOLD{yr}")
        sf, _ = E.spy_net(pb, ws, we, START_CASH)
        cell["spy_final"] = round(sf, 2)
        folds[str(yr)] = cell
    save("folds.json", {"design": "Fresh $100 per calendar year, ANNUAL cadence (single first-trading-day "
                                  "selection, held to year-end), published Nov-2016 pond, v9 protections, "
                                  "20-seed placebos per fold. 2017 is the first full calendar year after "
                                  "the pond's Nov-2016 formation; 2016 is a partial stub and is not folded.",
                        "folds": folds})
    print("folds done", time.time() - t0, flush=True)

    # ============ 3. LONG: pond rebuilt PIT at 2010-01-04 =================
    # Stream the 175-name candidate pool ONE NAME AT A TIME (facts discarded
    # after chain extraction; payload discarded after its close is read).
    LR = load("lr_common", os.path.join(BT, "long-run-2010", "lr_common.py"))
    C = LR.champ
    spy_dates = [b["d"] for b in bars["SPY"]]
    chains_by, payload_by, failures = {}, {}, []
    for t in LR.POOL:
        try:
            cik = LR.cik_for(t)
            facts = LR.load_facts(cik)
        except Exception as e:
            failures.append((t, f"facts/CIK failed: {e}")); continue
        ename = facts.get("entityName", "?")
        if t in LR.NAME_HINTS and LR.NAME_HINTS[t].lower() not in ename.lower():
            failures.append((t, f"entityName mismatch: {ename!r}")); continue
        chains_by[t] = (LR.equity_chain(facts), LR.shares_chain(facts))
        del facts
        try:
            payload_by[t] = LR.yahoo_payload(t)
        except Exception as e:
            failures.append((t, f"yahoo failed: {e}")); del chains_by[t]
    rows, pond2010, unrankable, price_date = LR.build_pond(chains_by, payload_by, spy_dates, "2010-01-04")
    del chains_by, payload_by
    print("LONG pond 2010 (PIT, price_date", price_date, "):", pond2010, flush=True)
    print("LONG pond unrankable:", unrankable, "failures:", failures, flush=True)
    # qdata for the 2010 pond only, facts one name at a time from the
    # long-hold EDGAR cache; ROA flag re-derived by the original's own
    # mechanical rule relative to the LONG first selection date.
    cutoff_long = (date(2010, 1, 4) - timedelta(days=548)).isoformat()
    qdata_long = {}
    for t in pond2010:
        cik = LR.cik_for(t)
        facts = LR.load_facts(cik)
        obs = Q.build_quality_observations(facts)
        usable = [o for o in obs if o[0] >= cutoff_long]
        qdata_long[t] = {"obs": obs, "roa": len(usable) == 0,
                         "income_rows": Q.pit_series_income(facts),
                         "assets_rows": E.pit_series(facts, "us-gaap", "Assets")}
        del facts
    bars_long = {t: load_pxfull(t) for t in pond2010 + ["SPY"]}
    pb_long = FastBook(bars_long)
    spy_long, _ = E.spy_net(pb_long, "2010-01-04", "2026-11-20", START_CASH)
    print("SPY LONG in-plumbing:", round(spy_long, 2), "(reference $822.94)", flush=True)
    for cad in ("annual", "quarterly"):
        cell = run_cell(pb_long, qdata_long, pond2010, cad, "2010-01-04", "2026-11-20", "LONG")
        cell["spy_final"] = round(spy_long, 2)
        cell["pond_2010"] = pond2010
        cell["pond_price_date"] = price_date
        cell["pond_ranking"] = [{k: r[k] for k in ("ticker", "rank", "market_cap_usd")} for r in rows[:30]]
        cell["roa_substituted_names"] = sorted(t for t in pond2010 if qdata_long[t]["roa"])
        cell["roa_cutoff"] = cutoff_long
        save(f"long_{cad}.json", cell)
    save("long_pond.json", {"pond_2010": pond2010, "price_date": price_date,
                            "ranking": [{k: r[k] for k in ("ticker", "rank", "market_cap_usd", "shares", "shares_filed", "price_actual", "price_bar_date")} for r in rows],
                            "unrankable": unrankable, "pool_failures": failures,
                            "roa_cutoff": cutoff_long,
                            "roa_substituted_names": sorted(t for t in pond2010 if qdata_long[t]["roa"]),
                            "note": "Pond rebuilt point-in-time at 2010-01-04 via long-run-2010 build_pond "
                                    "(PIT shares x actual close, 10-day staleness guard) over its 175-name "
                                    "candidate pool. The published Nov-2016 pond was NOT used for LONG — "
                                    "that would be a fixed-later-universe run."})
    print("DONE", time.time() - t0, flush=True)

if __name__ == "__main__": main()
