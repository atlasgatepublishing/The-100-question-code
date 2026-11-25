#!/usr/bin/env python3
"""
V13 BEST-RULES — hunt-tobin-q (firm-level Tobin's Q factor).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: Q = (mktcap + (total assets - book equity)) / total assets,
all PIT EDGAR as filed (548d freshness), rank ascending, hold 10 equal
weight, quarterly re-pick, next-open execution, honest program ponds,
program costs, NO floor. Pure Q — no momentum overlay.

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
INTEGRITY GATE: its house count-5 must reproduce the published champion
finals before any v13 number counts.
CONFIRMATION (pre-registered): if Q beats champion V+M on any road ->
fresh-$100 calendar folds 2017-2026 + DECADE half-windows, my rules vs
published champion house form; confirmed = >=6/10 folds AND >=1/2 halves.
"""
import importlib.util, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"; COUNT = 10; SEEDS = list(range(1, 21))
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED_TIMER = 100.00  # v12 aggregate timer final, every road

def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

S = load("vm_sweep", SWEEP)
E, LC = S.E, S.LC

def assets_fixed():
    ciks = E.get_ciks(); out = {}
    for t in S.UNIVERSE:
        cik = 34088 if t == "XOM" else ciks[t][0]
        f = E.get_companyfacts(cik)
        out[t] = S.PitIndex(E.pit_series(f, "us-gaap", "Assets", prio=2))
    return out

def assets_long(pond):
    out = {}
    for t in pond:
        f = LC.load_facts(LC.cik_for(t))
        out[t] = S.PitIndex(E.pit_series(f, "us-gaap", "Assets", prio=2))
        del f
    return out

def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); r = [0]*len(v)
        for rank, i in enumerate(order): r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys); n = len(xs)
    mx = sum(rx)/n; my = sum(ry)/n
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    den = (sum((a-mx)**2 for a in rx) * sum((b-my)**2 for b in ry)) ** 0.5
    return num/den if den else None

def q_decisions(pb, pit_eq, pit_sh, pit_a, universe, sel_dates):
    dec = {}; cors = []
    for d in sel_dates:
        q, bm, pool = {}, {}, []
        for t in universe:
            be = pit_eq[t].value(d); so = pit_sh[t].value(d); ta = pit_a[t].value(d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or ta is None or px is None: continue
            if so[2] <= 0 or ta[2] <= 0: continue
            mcap = so[2]*px
            if mcap <= 0: continue
            tl = ta[2] - be[2]
            if tl < 0: continue
            q[t] = (mcap + tl) / ta[2]; bm[t] = be[2]/mcap; pool.append(t)
        if len(q) >= 5:
            ranked = sorted(q, key=lambda t: q[t])
            ts = sorted(q)
            c = spearman([q[t] for t in ts], [-bm[t] for t in ts])  # Q asc vs B/M desc = same cheap direction
            if c is not None: cors.append(round(c, 3))
        else:
            ranked = []
        dec[d] = {"ranked": ranked, "pool": sorted(pool)}
    return dec, cors

def main():
    t0 = time.time()
    res = {"program": "v13-best-rules", "family": "hunt-tobin-q (firm-level Tobin's Q factor)",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "my_rules": {"count": COUNT, "floor": None, "cadence": "quarterly",
                        "formula": "Q=(mktcap + assets - book_equity)/assets, ascending",
                        "costs": "0.10%/side + $0.01 per sell order", "start_cash": 100.0},
           "published_timer_finals_all_roads": PUBLISHED_TIMER,
           "champion_vm": CHAMP, "spy_reference": SPYREF, "integrity": {}, "roads": {}, "confirmation": None}

    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    pit_a = assets_fixed()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_q_fixed, cor_fixed = q_decisions(pb, pit_eq, pit_sh, pit_a, universe, all_sel)
    dec_c_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)

    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    pit_aL = assets_long(pondL)
    selL = S.quarter_dates(pbL, "2010-01-04", END)
    dec_q_long, cor_long = q_decisions(pbL, pit_eqL, pit_shL, pit_aL, pondL, selL)
    dec_c_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL)
    res["long_pond"] = pondL
    res["q_vs_bm_rank_corr"] = {"fixed_pond_mean_spearman_Qasc_vs_BMdesc": round(sum(cor_fixed)/len(cor_fixed), 3) if cor_fixed else None,
                                "long_pond_mean_spearman_Qasc_vs_BMdesc": round(sum(cor_long)/len(cor_long), 3) if cor_long else None,
                                "note": "1.0 = Q ranking identical to champion value-leg ranking"}

    roads = [("DECADE", pb, dec_q_fixed, dec_c_fixed, "2016-11-21", END),
             ("CONT", pb, dec_q_fixed, dec_c_fixed, "2019-01-02", END),
             ("VAL", pb, dec_q_fixed, dec_c_fixed, "2023-01-03", END),
             ("LONG", pbL, dec_q_long, dec_c_long, "2010-01-04", END)]

    for name, pbx, dq, dc, s, e in roads:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, dc, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - CHAMP[name]) < 0.02
        res["integrity"][name] = {"expected_house_count5": CHAMP[name], "reproduced": round(r["final"], 2), "match": ok}
        print(f"INTEGRITY {name}: ${r['final']:,.2f} vs ${CHAMP[name]} match={ok}", flush=True)
        assert ok

    beat_any = False
    for name, pbx, dq, dc, s, e in roads:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        r = S.run_native(pbx, dq, sel, s, e, COUNT)
        diag = S.diagnostics(r["curve"])
        pf = [round(S.run_native(pbx, dq, sel, s, e, COUNT, placebo_seed=sd)["final"], 2) for sd in SEEDS]
        beaten = sum(1 for f in pf if f < r["final"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        pools = [len(dq[d]["pool"]) for d in sel if d in dq]
        beat = round(r["final"], 2) > CHAMP[name]; beat_any |= beat
        res["roads"][name] = {"window": [s, e], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2), "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"], "max_dd_date": diag["max_dd_date"],
                         "placebo_beaten": beaten, "placebo_finals": pf, "beats_champion": beat,
                         "beats_published_timer": round(r["final"], 2) > PUBLISHED_TIMER,
                         "pool_size_min": min(pools) if pools else None, "pool_size_max": max(pools) if pools else None,
                         "period_distribution": dist, "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "published_timer_final": PUBLISHED_TIMER, "champion_vm_final": CHAMP[name]}
        print(f"{name} Q10: ${r['final']:,.2f} champ ${CHAMP[name]} SPY ${spy} placebos {beaten}/20 DD {diag['max_dd_pct']}% orders {r['orders']}", flush=True)

    if beat_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"; e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rc = S.run_native(pb, dec_q_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_c_fixed, sel, s, e, 5)
            folds[str(yr)] = {"my_rules_final": round(rc["final"], 2), "champion_final": round(rp["final"], 2),
                              "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"], "my_rules_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"), "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rc = S.run_native(pb, dec_q_fixed, sel, s, e, COUNT)
            rp = S.run_house(pb, dec_c_fixed, sel, s, e, 5)
            halves[hn] = {"my_rules_final": round(rc["final"], 2), "champion_final": round(rp["final"], 2),
                          "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"], "my_rules_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_rules_win"]); hw = sum(1 for v in halves.values() if v["my_rules_win"])
        res["confirmation"] = {"design": "fresh-$100 calendar folds 2017-2026 + DECADE halves; my rules vs champion house form",
                               "year_folds": folds, "fold_wins": f"{wins}/10", "half_windows": halves, "half_wins": f"{hw}/2",
                               "confirmed": wins >= 6 and hw >= 1}
        print(f"CONFIRMATION folds {wins}/10 halves {hw}/2 confirmed={res['confirmation']['confirmed']}", flush=True)

    res["elapsed_sec"] = round(time.time() - t0, 1)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE", res["elapsed_sec"], flush=True)

if __name__ == "__main__":
    main()
