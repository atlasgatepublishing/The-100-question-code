#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-TWOSLEEVE. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: $100 pot split $50/$50. Sleeve V = pure book-to-market top-2.
Sleeve M = pure 12-1 momentum top-2. Quarterly re-pick per sleeve,
next-open execution, equal weight within sleeve, program costs
0.10%/side + $0.01/sell. Sleeves re-equalized to 50/50 ONLY at the
January selection each year. NO floor/stop/ladder. PIT EDGAR + honest
top-30 pond per road start (v12 holdings-champion-vm chassis inputs).

INTEGRITY GATE: chassis house count-5 combined must reproduce the
published champion finals to the cent before any v13 number counts.

CONFIRMATION (frozen in spec): if my form beats the published champion
OR the v13 single-book host (combined top-2, no floor) on any road ->
fresh-$100 calendar folds 2017-2026 + DECADE half-windows vs whichever
line was beaten; confirmed requires >=6/10 folds AND >=1/2 halves.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
PER_SLEEVE = 2
START = 100.0

HOST = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73, "VAL": 461.20}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)
E = S.E


def compute_sleeve_decisions(pb, pit_eq, pit_sh, universe, sel_dates):
    """Same PIT scores as chassis compute_decisions, but keep the pure
    per-signal rankings (value-only, momentum-only) beside combined."""
    dec = {}
    for d in sel_dates:
        scores = {}
        for t in universe:
            be = pit_eq[t].value(d)
            so = pit_sh[t].value(d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = pb.didx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        if len(scores) >= 5:
            vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            dec[d] = {
                "ranked": sorted(combined, key=lambda t: -combined[t]),
                "value": sorted(scores, key=lambda t: -scores[t][0]),
                "momentum": sorted(scores, key=lambda t: -scores[t][1]),
                "pool": sorted(scores)}
        else:
            dec[d] = {"ranked": [], "value": [], "momentum": [],
                      "pool": sorted(scores)}
    return dec


def run_twosleeve(pb, dec, sel_dates, start, end, placebo_seed=None):
    """Two sub-books, each with own cash/positions. Quarterly: each
    sleeve re-picks its pure top-2 within its own capital. January
    selection: first re-equalize sleeve capitals to 50/50 of total pot
    (sell richer sleeve pro-rata at next open, transfer cash), then
    re-pick. No floor. Final liquidation at last close, program costs."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    sel_set = set(sel_dates)
    sleeves = [{"cash": START / 2.0, "pos": {}},
               {"cash": START / 2.0, "pos": {}}]  # 0=value, 1=momentum
    keys = ["value", "momentum"]
    total_costs = 0.0
    orders = 0
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    pending = None  # (targets_per_sleeve, rebalance_first: bool)

    def sleeve_close(sl, d):
        v = sl["cash"]
        for t, sh in sl["pos"].items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute(d, pend):
        nonlocal total_costs, orders
        targets, do_rebal = pend
        opens = {}
        allt = set()
        for sl in sleeves:
            allt |= set(sl["pos"])
        for tg in targets:
            allt |= set(tg)
        for t in allt:
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        if do_rebal:
            vals = []
            for sl in sleeves:
                v = sl["cash"]
                for t, sh in sl["pos"].items():
                    if t in opens:
                        v += sh * opens[t]
                    else:
                        c = pb.close_on_or_before(t, d)
                        v += sh * c if c else 0.0
                vals.append(v)
            total = sum(vals)
            for i, sl in enumerate(sleeves):
                excess = vals[i] - total / 2.0
                if excess > 0.005:
                    # sell pro-rata across positions at open
                    pos_val = sum(sh * opens[t] for t, sh in sl["pos"].items()
                                  if t in opens)
                    if pos_val > 0:
                        frac = min(1.0, excess / pos_val)
                        for t in list(sl["pos"]):
                            if t not in opens:
                                continue
                            sv = sl["pos"][t] * opens[t] * frac
                            sh = sv / opens[t]
                            c = sv * 0.001 + 0.01
                            sl["cash"] += sv - c
                            total_costs += c
                            orders += 1
                            sl["pos"][t] -= sh
                            if sl["pos"][t] < 1e-9:
                                del sl["pos"][t]
                elif excess < -0.005:
                    pass  # funded by the other sleeve's sale below
            # transfer cash so both sleeves hold equal total value
            vals2 = []
            for sl in sleeves:
                v = sl["cash"]
                for t, sh in sl["pos"].items():
                    if t in opens:
                        v += sh * opens[t]
                vals2.append(v)
            total2 = sum(vals2)
            for i, sl in enumerate(sleeves):
                diff = total2 / 2.0 - vals2[i]  # + means needs cash
                if diff > 0:
                    # take from the other sleeve's cash (it sold down)
                    other = sleeves[1 - i]
                    take = min(diff, max(0.0, other["cash"]))
                    other["cash"] -= take
                    sl["cash"] += take
        for i, sl in enumerate(sleeves):
            tg = targets[i]
            for t in list(sl["pos"]):
                if t not in opens:
                    continue
                cur = sl["pos"][t] * opens[t]
                tgt = tg.get(t, 0.0)
                if cur > tgt + 0.005:
                    sv = cur - tgt
                    sh = sv / opens[t]
                    c = sv * 0.001 + 0.01
                    sl["cash"] += sv - c
                    total_costs += c
                    orders += 1
                    sl["pos"][t] -= sh
                    if sl["pos"][t] < 1e-9:
                        del sl["pos"][t]
            for t, tgt in tg.items():
                if t not in opens:
                    continue
                cur = sl["pos"].get(t, 0.0) * opens[t]
                bv = tgt - cur
                if bv > 0.005:
                    bv = min(bv, sl["cash"] / 1.001)
                    if bv <= 0.005:
                        continue
                    sh = bv / opens[t]
                    c = bv * 0.001
                    sl["cash"] -= bv + c
                    total_costs += c
                    orders += 1
                    sl["pos"][t] = sl["pos"].get(t, 0.0) + sh

    for d in days:
        if pending is not None:
            execute(d, pending)
            pending = None
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                targets = []
                for i, sl in enumerate(sleeves):
                    if rng is not None:
                        picks = rng.sample(sorted(pool),
                                           min(PER_SLEEVE, len(pool)))
                    else:
                        picks = dd[keys[i]][:PER_SLEEVE]
                    pv = sleeve_close(sl, d)
                    each = pv / len(picks) if picks else 0.0
                    targets.append({t: each for t in picks})
                pending = (targets, d[5:7] == "01")
        curve.append((d, sum(sleeve_close(sl, d) for sl in sleeves)))
    last = days[-1]
    final = 0.0
    for sl in sleeves:
        final += sl["cash"]
        for t, sh in list(sl["pos"].items()):
            c = pb.close_on_or_before(t, last)
            if c:
                val = sh * c
                cst = val * 0.001 + 0.01
                final += val - cst
                total_costs += cst
                orders += 1
    return {"final": final, "costs": total_costs, "orders": orders,
            "curve": curve}


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules", "family": "vm-twosleeve",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"split": "50/50", "per_sleeve_count": PER_SLEEVE,
                     "sleeve_V": "pure book-to-market top-2",
                     "sleeve_M": "pure 12-1 momentum top-2",
                     "cadence": "quarterly", "rebalance": "annual January",
                     "floor": None,
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": START},
        "published_champion": CHAMP, "v13_single_book_host": HOST,
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None}

    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = compute_sleeve_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    dec_comb = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)

    pbL, pit_eqL, pit_shL, pondL, _info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = compute_sleeve_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    dec_combL = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    results["long_pond"] = pondL

    road_specs = [("DECADE", pb, dec_fixed, dec_comb, "2016-11-21"),
                  ("CONT", pb, dec_fixed, dec_comb, "2019-01-02"),
                  ("VAL", pb, dec_fixed, dec_comb, "2023-01-03"),
                  ("LONG", pbL, dec_long, dec_combL, "2010-01-04")]

    for name, pbx, decx, decc, s in road_specs:
        sel = S.quarter_dates(pbx, s, END)
        r = S.run_house(pbx, decc, sel, s, END, 5)
        ok = abs(round(r["final"], 2) - CHAMP[name]) < 0.02
        results["integrity"][name] = {"expected_house_count5": CHAMP[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name} house-5: ${r['final']:,.2f} expected "
              f"${CHAMP[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"

    beat_champ, beat_host = [], []
    for name, pbx, decx, decc, s in road_specs:
        sel = S.quarter_dates(pbx, s, END)
        spy = S.spy_final(pbx, s, END)
        r = run_twosleeve(pbx, decx, sel, s, END)
        diag = S.diagnostics(r["curve"])
        # host reference re-run on this chassis (combined top-2, no floor)
        hr = S.run_native(pbx, decc, sel, s, END, 2)
        hdiag = S.diagnostics(hr["curve"])
        assert abs(round(hr["final"], 2) - HOST[name]) < 0.02, \
            f"host mismatch {name}: {hr['final']} vs {HOST[name]}"
        pfinals = []
        for seed in SEEDS:
            pr = run_twosleeve(pbx, decx, sel, s, END, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        hdist = S.period_distribution([(d, v) for d, v in hr["curve"]], sel)
        if round(r["final"], 2) > CHAMP[name]:
            beat_champ.append(name)
        if round(r["final"], 2) > HOST[name]:
            beat_host.append(name)
        results["roads"][name] = {
            "window": [s, END], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "placebo_beaten": beaten, "placebo_finals": pfinals,
                         "beats_champion": round(r["final"], 2) > CHAMP[name],
                         "beats_host": round(r["final"], 2) > HOST[name],
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "host_single_book_top2": {
                "final": round(hr["final"], 2),
                "max_dd_pct": hdiag["max_dd_pct"],
                "period_distribution": hdist,
                "curve": [[d, round(v, 4)] for d, v in hr["curve"]]},
            "published_champion_final": CHAMP[name]}
        print(f"{name} TWOSLEEVE: ${r['final']:,.2f} (champ "
              f"${CHAMP[name]:,.2f}, host ${HOST[name]:,.2f}, SPY "
              f"${spy:,.2f}) placebos {beaten}/20 maxDD "
              f"{diag['max_dd_pct']}% orders={r['orders']} "
              f"costs=${r['costs']:,.2f}", flush=True)

    # ---------------- confirmation (frozen bars in spec)
    conf_targets = []
    if beat_host:
        conf_targets.append("host")
    if beat_champ:
        conf_targets.append("champion")
    if conf_targets:
        conf = {}
        for target in conf_targets:
            folds, halves = {}, {}
            for yr in range(2017, 2027):
                s = f"{yr}-01-01"
                e = END if yr == 2026 else f"{yr}-12-31"
                sel = S.quarter_dates(pb, s, e)
                # decisions for fold window: reuse dec_fixed where dates
                # align (quarter_dates from Jan 1 gives same Jan/Apr/Jul/Oct
                # first trading days as the DECADE decision set)
                rc = run_twosleeve(pb, dec_fixed, sel, s, e)
                if target == "host":
                    rp = S.run_native(pb, dec_comb, sel, s, e, 2)
                else:
                    rp = S.run_house(pb, dec_comb, sel, s, e, 5)
                folds[str(yr)] = {"my_final": round(rc["final"], 2),
                                  "line_final": round(rp["final"], 2),
                                  "my_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                                  "win": rc["final"] > rp["final"]}
            for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                               "H2_2022-2026": ("2022-01-01", END)}.items():
                sel = S.quarter_dates(pb, s, e)
                rc = run_twosleeve(pb, dec_fixed, sel, s, e)
                if target == "host":
                    rp = S.run_native(pb, dec_comb, sel, s, e, 2)
                else:
                    rp = S.run_house(pb, dec_comb, sel, s, e, 5)
                halves[hn] = {"my_final": round(rc["final"], 2),
                              "line_final": round(rp["final"], 2),
                              "my_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                              "win": rc["final"] > rp["final"]}
            wins = sum(1 for v in folds.values() if v["win"])
            hwins = sum(1 for v in halves.values() if v["win"])
            conf[target] = {"year_folds": folds, "fold_wins": f"{wins}/10",
                            "half_windows": halves, "half_wins": f"{hwins}/2",
                            "confirmed": wins >= 6 and hwins >= 1}
            print(f"CONFIRMATION vs {target}: folds {wins}/10 halves "
                  f"{hwins}/2 confirmed={conf[target]['confirmed']}",
                  flush=True)
        results["confirmation"] = conf

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
