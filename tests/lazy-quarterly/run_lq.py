#!/usr/bin/env python3
"""
LAZY PRICES QUARTERLY (LQ) — the test itself.

Runs only after the integrity gate (integrity.py) passes in-process.

THE SPEC-MAPPING FACT, asserted mechanically below: the LQ frozen
spec — first trading day of each calendar quarter, rank by most
recent 10-K similarity, top-5 equal weight, sell dropouts at the
open, program costs — is, point for point, the selection and
rebalance mechanics the promoted Lazy Prices engine has used since
its first published run. What is "annual" in Lazy Prices is the
SIGNAL (a company's score changes only when it files a new 10-K);
the portfolio has always re-picked quarterly. The LQ runs below are
therefore executed by the promoted engine itself, and the integrity
gate has already proven this plumbing reproduces its published
finals to the cent. A separate re-typed "quarterly" engine would
test my typing, not Terry's idea.

Windows 2/3 (continuous/validation) run on the published chassis:
no halt occurred on either window in the ranked runs, so the plain
floor and the adopted v9 wrapper are the same run there; placebos
use the published protocol (plain-floor run_pot, seeds 1..20, random
rank from the same scored pool). The long window and the decade
window run under the full v9 wrapper (floor, 90-day sit-out, one
restart), as specified.

The decade window (2016-11-21 -> 2026-11-20, Terry's addition) also
runs the ANNUAL variant — the identical engine and signal with the
selection calendar restricted to the first trading day of January —
plus the champion and SPY, all in this plumbing on the Nov-2016
pond. Its LQ placebos are v9-wrapped, matching its ranked run.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lq_common as Q  # noqa: E402
import integrity  # noqa: E402

C, E = Q.C, Q.E
END = Q.END
OUT = {"test": "Lazy Prices Quarterly (LQ) — Terry's short-cycle proposal"}


def pick_change_stats(pools):
    """Consecutive-selection comparison: how often the quarterly
    re-pick actually changes the held five, and how often any score
    in the pool moved (new 10-K information landed)."""
    chg_picks = chg_scores = 0
    for a, b in zip(pools, pools[1:]):
        if set(a["picks"]) != set(b["picks"]):
            chg_picks += 1
        sa, sb = a.get("scores", {}), b.get("scores", {})
        if any(sa.get(t) != sb.get(t) for t in set(sa) | set(sb)):
            chg_scores += 1
    return {"selections": len(pools),
            "transitions": max(len(pools) - 1, 0),
            "pick_set_changes": chg_picks,
            "any_score_changes": chg_scores}


def placebo_block(lazy, pb, sims, start, end, ranked_final):
    twins = []
    for seed in range(1, 21):
        tr = lazy.run_pot(pb, sims, start, end,
                          placebo_rng=random.Random(seed),
                          label=f"PLACEBO {seed}")
        twins.append({"seed": seed, "final": round(tr["final"], 2),
                      "costs": round(tr["costs"], 2),
                      "orders": len(tr["trades"]),
                      "halted": tr["halted"]})
    finals = sorted(t["final"] for t in twins)
    beats = sum(1 for x in finals if ranked_final > x)
    return {"finals_sorted": finals,
            "median": round(lazy._pct(finals, 0.5), 2),
            "best": finals[-1], "worst": finals[0],
            "ranked_beats": beats,
            "percentile_of_twins": round(100.0 * beats / len(finals), 1),
            "twin_halts": sum(1 for t in twins if t["halted"]),
            "twins": twins}


def main():
    fails, _ = integrity.run_gate()
    if fails:
        print("INTEGRITY FAILED — no LQ numbers produced", flush=True)
        sys.exit(1)

    lazy, pb, sims = Q.gap_book()

    # ---- spec mapping: LQ calendar == engine calendar, asserted
    mapping = {}
    for wname in ("continuous", "validation"):
        s, e = Q.WINDOWS[wname]
        spec = Q.spec_selection_dates(pb, s, e)
        eng = lazy.quarter_selection_dates(pb, s, e)
        mapping[wname] = {"spec_dates": spec, "engine_dates": eng,
                          "identical": spec == eng}
        assert spec == eng, f"selection calendars differ on {wname}"
    print("spec mapping: LQ quarterly calendar == promoted engine "
          "calendar on continuous + validation", flush=True)

    # ---- windows 2/3: ranked LQ + placebos (published chassis)
    for wname in ("continuous", "validation"):
        s, e = Q.WINDOWS[wname]
        r = lazy.run_pot(pb, sims, s, e, label=f"LQ {wname}",
                         record_pools=True)
        diag = lazy.diagnostics(r)
        spy, spy_costs = lazy.spy_net(pb, s, e)
        cg, yrs = C.cagr(r["final"], 100.0, s, e)
        pl = placebo_block(lazy, pb, sims, s, e, r["final"])
        OUT[wname] = {
            "window": [s, e], "final": round(r["final"], 2),
            "cagr_pct": cg, "years": yrs,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "worst_close_above_floor": diag["worst_close_above_floor"],
            "max_drawdown_pct": diag["max_drawdown_pct"],
            "max_drawdown_date": diag["max_drawdown_date"],
            "spy_final": round(spy, 2),
            "turnover": pick_change_stats(r["pools"]),
            "placebo": pl}
        print(f"LQ {wname}: ${r['final']:,.2f} costs ${r['costs']:,.2f} "
              f"orders {len(r['trades'])} placebo beats "
              f"{pl['ranked_beats']}/20", flush=True)

    # ---- window 1: long, full v9 (fresh run in this plumbing)
    pond = Q.pond2010()
    res = E.lazy_v9(pond, Q.era_signals(), "2010-01-04", END)
    pools = []
    for ep in res["episodes"]:
        pools += ep.get("pools") or []
    OUT["long"] = {
        "window": ["2010-01-04", END], "final": res["final"],
        "cagr_pct": res["cagr_pct"], "years": res["years"],
        "costs": res["costs"], "orders": res["orders"],
        "halts": res["halts"], "restart": res["restart"],
        "episodes": [{k: ep[k] for k in
                      ("start_cash", "floor", "final", "halted", "end",
                       "costs", "orders", "worst_close",
                       "worst_close_date", "worst_close_above_floor",
                       "max_drawdown_pct")} for ep in res["episodes"]],
        "max_drawdown_pct": res["diag"]["max_drawdown_pct"],
        "max_drawdown_date": res["diag"]["max_drawdown_date"],
        "worst_close": res["diag"]["worst_close"],
        "worst_close_date": res["diag"]["worst_close_date"],
        "spy_final": res["spy_final"],
        "turnover": pick_change_stats(pools)}
    print(f"LQ long: ${res['final']:,.2f} costs ${res['costs']:,.2f} "
          f"orders {res['orders']}", flush=True)

    # ---- window 4: the decade, 2016-11-21 -> 2026-11-20
    DS, DE = "2016-11-21", END
    pond16 = list(lazy.UNIVERSE)
    # The decade book is built from the champion's shared price cache
    # (the same source as windows 2/3): the long-run payload cache
    # keys Alphabet as GOOG, not GOOGL, so E._book cannot serve the
    # Nov-2016 pond. FastPriceBook equivalence with the engine's own
    # PriceBook was proven in the long-run test's phase 0.
    book16 = C.FastPriceBook({t: lazy.get_prices(t)
                              for t in pond16 + ["SPY"]})

    def lq_run_one(mod):
        def run_one(s, e, cash, floor):
            return mod.run_pot(book16, sims, s, e, cash, floor,
                               label="DECADE", record_pools=True)
        return run_one

    v9 = C.run_v9(lq_run_one(lazy), book16.dates, DS, DE)
    lq_dec = E._normalize("lazy prices quarterly (LQ)", DS, DE, v9,
                          C.champ.spy_net(book16, DS, DE, 100.0)[0])
    pools = []
    for ep in v9["episodes"]:
        pools += ep.get("pools") or []
    lq_dec["turnover"] = pick_change_stats(pools)
    lq_dec["first_selection_pools"] = pools[:4]
    OUT["decade_lq"] = lq_dec
    print(f"LQ decade: ${lq_dec['final']:,.2f} costs "
          f"${lq_dec['costs']:,.2f} orders {lq_dec['orders']}", flush=True)

    # annual variant: identical module, January-only calendar
    ann = C.load_module("lazy_annual", os.path.join(Q.GAPA5,
                                                    "lazy-prices.py"))
    ann.UNIVERSE = pond16

    def annual_dates(pb_, start, end):
        out, seen = [], set()
        for d in pb_.dates:
            if start <= d <= end and d[5:7] == "01":
                if d[:4] not in seen:
                    seen.add(d[:4])
                    out.append(d)
        return out
    ann.quarter_selection_dates = annual_dates
    v9a = C.run_v9(lq_run_one(ann), book16.dates, DS, DE)
    ann_dec = E._normalize("lazy prices annual (january-only)",
                           DS, DE, v9a, lq_dec["spy_final"])
    pools_a = []
    for ep in v9a["episodes"]:
        pools_a += ep.get("pools") or []
    ann_dec["turnover"] = pick_change_stats(pools_a)
    OUT["decade_annual"] = ann_dec
    print(f"ANNUAL decade: ${ann_dec['final']:,.2f} costs "
          f"${ann_dec['costs']:,.2f} orders {ann_dec['orders']}",
          flush=True)

    # decade LQ placebos, v9-wrapped like the ranked run
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)

        def run_pl(s, e, cash, floor, rng=rng):
            return lazy.run_pot(book16, sims, s, e, cash, floor,
                                placebo_rng=rng, label=f"DEC PL {seed}")
        v9p = C.run_v9(run_pl, book16.dates, DS, DE)
        twins.append({"seed": seed, "final": round(v9p["final"], 2),
                      "costs": round(v9p["costs"], 2),
                      "orders": v9p["orders"],
                      "halts": len(v9p["halts"])})
    finals = sorted(t["final"] for t in twins)
    beats = sum(1 for x in finals if lq_dec["final"] > x)
    OUT["decade_placebo"] = {
        "finals_sorted": finals,
        "median": round(lazy._pct(finals, 0.5), 2),
        "best": finals[-1], "worst": finals[0], "ranked_beats": beats,
        "percentile_of_twins": round(100.0 * beats / len(finals), 1),
        "twins": twins}
    print(f"decade placebo: ranked beats {beats}/20, median "
          f"${lazy._pct(finals, 0.5):,.2f}", flush=True)

    # champion on the identical decade window and pond, phase-0
    # style (its own caches + FastPriceBook) under the v9 wrapper
    champ = C.champ
    ciks = champ.get_ciks()
    eq, so = {}, {}
    for t in pond16:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = champ.get_companyfacts(cik)
        eq[t], so[t] = C.equity_chain(facts), C.shares_chain(facts)
    saved_u = champ.UNIVERSE
    champ.UNIVERSE = pond16
    try:
        def champ_one(s, e, cash, floor):
            return champ.run_pot(book16, eq, so, s, e, cash, floor,
                                 [], label="DECADE VM", quiet=True,
                                 record_pools=True)
        v9c = C.run_v9(champ_one, book16.dates, DS, DE)
        spy_c, _ = champ.spy_net(book16, DS, DE, 100.0)
    finally:
        champ.UNIVERSE = saved_u
    ch = E._normalize("value+momentum", DS, DE, v9c, spy_c)
    OUT["decade_champion"] = {
        "final": ch["final"], "cagr_pct": ch["cagr_pct"],
        "costs": ch["costs"], "orders": ch["orders"],
        "halts": ch["halts"], "restart": ch["restart"],
        "max_drawdown_pct": ch["diag"]["max_drawdown_pct"],
        "max_drawdown_date": ch["diag"]["max_drawdown_date"],
        "worst_close": ch["diag"]["worst_close"],
        "worst_close_date": ch["diag"]["worst_close_date"],
        "spy_final": ch["spy_final"]}
    print(f"CHAMPION decade: ${ch['final']:,.2f} spy "
          f"${ch['spy_final']:,.2f}", flush=True)

    OUT["spec_mapping"] = mapping
    OUT["champion_reference"] = {
        "long": 1415.62, "continuous": 544.47, "validation": 288.05,
        "source": "long-run-2010 phase-0-verified record (same "
                  "plumbing family); decade champion computed fresh "
                  "in this test, see decade_champion"}
    with open(os.path.join(HERE, "results_lq.json"), "w") as f:
        json.dump(OUT, f, indent=1, default=str)
    print("saved results_lq.json", flush=True)


if __name__ == "__main__":
    main()
