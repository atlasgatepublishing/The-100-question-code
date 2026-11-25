#!/usr/bin/env python3
"""
V13 BEST-RULES — WINNERS' BLEND (momentum basket x value+momentum).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (from the frozen spec):
  - Two SEPARATE sub-pots of one $100 pot: V+M $67 / basket $33.
    NO resets, NO transfers — weights drift; each sleeve compounds
    its own gains.
  - V+M sleeve: its v13 form verbatim — top-2, quarterly, NO floor —
    run on the v12 holdings-champion-vm chassis (run_native, count=2)
    at the sleeve's cash.
  - Basket sleeve: its v13 form verbatim — top-3, monthly, 200-day
    filter, SPY 63d vol-scaled exposure E=clip(0.18/vol,0.40,1.00),
    NO floor — run on the v13 momentum-basket engine (simulate)
    at the sleeve's cash.
  - Program costs inside each sleeve exactly as in the parent engines.
  - Combined final = sum of sleeve finals; combined curve = date-aligned
    sum of sleeve curves (forward-filled).

SELECTION CAVEAT (from the spec, carried at full size): this family's
members were chosen BECAUSE they won on these same roads. Members here
are taken by pre-registered program standing (the two promoted
strategies), not by best-ever numbers.

INTEGRITY GATE (before any blend number counts): each sleeve at $100
under its sleeve form must reproduce its parent's v13 record —
V+M: DECADE 906.90 / CONT 691.73 / VAL 461.20;
basket: DECADE 474.63 / CONT 341.62 / VAL 272.37.

PLACEBOS: 20 seeds/road; twin = both sleeves randomized together
(VM chassis placebo_seed + basket simulate mode='placebo', same seed),
identical weights/mechanics/costs.

CONFIRMATION (frozen in the spec): if the blend beats the published
champion V+M or the v13 pure V+M form on any road -> fresh-$100
calendar-year folds 2017-2026 + DECADE half-windows, blend vs each
beaten form head-to-head; confirmed requires >=6/10 folds AND
>=1/2 half-windows against that form.

LONG road: NOT RUN — the basket parent's pond is point-in-time
Nov-2016; a 2010 basket run would trade on 2016 knowledge.

Shared inputs READ-ONLY. Writes only inside this folder.
"""
import gc
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
END = "2026-11-20"
SEEDS = list(range(1, 21))
W = {"VM": 67.0, "BK": 33.0}
OUT_PATH = os.path.join(HERE, "results.json")

VM_V13 = {"DECADE": 906.90, "CONT": 691.73, "VAL": 461.20}
BK_V13 = {"DECADE": 474.63, "CONT": 341.62, "VAL": 272.37}
VM_PUBLISHED = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
BK_PUBLISHED = {"DECADE": 439.45, "CONT": 291.53, "VAL": 208.27}
BLEND_PUBLISHED = {"CONT": 400.84, "VAL": 245.18}  # v4 original form
SPY_PUBLISHED = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

# road -> (vm_start, basket_start) — same first trading days, each
# engine's own convention (VM chassis snaps to 01-02/01-03; the basket
# engine snaps forward from 01-01)
ROADS = {"DECADE": ("2016-11-21", "2016-11-21"),
         "CONT": ("2019-01-02", "2019-01-01"),
         "VAL": ("2023-01-03", "2023-01-01")}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", os.path.join(
    BT, "v12-completions/holdings-champion-vm/run_sweep.py"))
BK = load_module("basket_v13", os.path.join(
    BT, "v13-best-rules/momentum-basket/run_best.py"))


# ------------------------------------------------------------ sleeves
def vm_run(pb, dec, s, e, cash, seed=None):
    sel = S.quarter_dates(pb, s, e)
    if seed is None:
        # run_episode at the sleeve's cash (rescaling a $100 run would
        # be invalid — fixed $0.01 sell fees). This is the exact call
        # the combo-three-way pass integrity-verified against the
        # v13 V+M finals.
        r = S.run_episode(pb, dec, set(sel), s, e, cash, None, 2)
    else:
        r = S.run_episode(pb, dec, set(sel), s, e, cash, None, 2,
                          placebo_rng=__import__("random").Random(seed))
    return {"final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "curve": r["curve"]}


def vm_house(pb, dec, s, e, cash=100.0):
    """Published champion form (count 5 + house floor chassis) at $100.
    Used only as the confirmation comparator; the house chassis is a
    $100-pot construction, so folds compare at $100 vs $100."""
    sel = S.quarter_dates(pb, s, e)
    r = S.run_house(pb, dec, sel, s, e, 5)
    return {"final": r["final"], "costs": r["costs"],
            "orders": r["orders"], "curve": r["curve"]}


def bk_run(mkt, s, e, cash, seed=None):
    if seed is None:
        r = BK.simulate(mkt, s, e, "ranked", pot0=cash)
    else:
        r = BK.simulate(mkt, s, e, "placebo", seed=seed, pot0=cash)
    return {"final": r["final"], "costs": r["costs"],
            "orders": r["orders"], "curve": r["equity_curve"]}


# ------------------------------------------------------------ combine
def combine(sleeves):
    dates = sorted({d for _c, curve in sleeves for d, _v in curve})
    idx = [0] * len(sleeves)
    last = [c for c, _curve in sleeves]
    out = []
    for d in dates:
        tot = 0.0
        for i, (_c, curve) in enumerate(sleeves):
            while idx[i] < len(curve) and curve[idx[i]][0] <= d:
                last[i] = curve[idx[i]][1]
                idx[i] += 1
            tot += last[i]
        out.append((d, tot))
    return out


def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d}


def period_distribution(curve):
    """Quarterly periods (calendar quarters) on the combined curve."""
    q_last = {}
    order = []
    for d, v in curve:
        q = (d[:4], (int(d[5:7]) - 1) // 3)
        if q not in q_last:
            order.append(q)
        q_last[q] = v
    changes = []
    prev = 100.0
    for q in order:
        changes.append(q_last[q] - prev)
        prev = q_last[q]
    n = len(changes)
    srt = sorted(changes)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = longest = 0
    for c in changes:
        streak = streak + 1 if c <= 0 else 0
        longest = max(longest, streak)
    peak = -1.0
    last_high = 0
    gap = 0
    for i, (_d, v) in enumerate(curve):
        if v >= peak:
            peak = v
            gap = max(gap, i - last_high)
            last_high = i
    gap = max(gap, len(curve) - 1 - last_high)
    return {"periods": n,
            "median_period_usd": round(median, 2),
            "share_positive_pct": round(
                100.0 * sum(1 for c in changes if c > 0) / n, 1),
            "best_period_usd": round(max(changes), 2),
            "worst_period_usd": round(min(changes), 2),
            "longest_losing_streak_qtrs": longest,
            "longest_between_new_highs_trading_days": gap,
            "mean_period_usd_secondary": round(sum(changes) / n, 2)}


def blend_run(ctx, road, s_vm, s_bk, e, seed=None):
    vm = vm_run(ctx["pb"], ctx["dec"], s_vm, e, W["VM"], seed)
    bk = bk_run(ctx["mkt"], s_bk, e, W["BK"], seed)
    curve = combine([(W["VM"], vm["curve"]), (W["BK"], bk["curve"])])
    parts = {"VM": vm, "BK": bk}
    return {"final": round(sum(p["final"] for p in parts.values()), 2),
            "sleeve_finals": {k: round(p["final"], 2)
                              for k, p in parts.items()},
            "costs": round(sum(p["costs"] for p in parts.values()), 2),
            "orders": sum(p["orders"] for p in parts.values()),
            "curve": curve}


def run_road(out, road, ctx):
    t0 = time.time()
    s_vm, s_bk = ROADS[road]
    e = END
    # ---- integrity: sleeves at $100 under their sleeve forms
    vm100 = vm_run(ctx["pb"], ctx["dec"], s_vm, e, 100.0)
    bk100 = bk_run(ctx["mkt"], s_bk, e, 100.0)
    integ = {
        "VM": {"expected_v13": VM_V13[road],
               "got": round(vm100["final"], 2),
               "match": abs(round(vm100["final"], 2)
                            - VM_V13[road]) < 0.02},
        "BK": {"expected_v13": BK_V13[road],
               "got": round(bk100["final"], 2),
               "match": abs(round(bk100["final"], 2)
                            - BK_V13[road]) < 0.02}}
    print(f"INTEGRITY {road}: VM {integ['VM']} BK {integ['BK']}",
          flush=True)
    assert integ["VM"]["match"], f"VM integrity failed on {road}"
    assert integ["BK"]["match"], f"BK integrity failed on {road}"

    # ---- the one frozen run + 20 placebo twins
    r = blend_run(ctx, road, s_vm, s_bk, e)
    diag = diagnostics(r["curve"])
    twins = []
    for seed in SEEDS:
        pr = blend_run(ctx, road, s_vm, s_bk, e, seed=seed)
        twins.append(round(pr["final"], 2))
        print(f"  {road} placebo {seed}: ${pr['final']:,.2f}", flush=True)
    beaten = sum(1 for x in twins if r["final"] > x)
    sf = sorted(twins)
    cell = {"road": road, "window": [s_vm, e],
            "weights_initial": W,
            "final": r["final"], "sleeve_finals": r["sleeve_finals"],
            "sleeve_end_shares_pct": {
                k: round(100.0 * v / r["final"], 1)
                for k, v in r["sleeve_finals"].items()},
            "costs": r["costs"], "orders": r["orders"],
            "max_dd_pct": diag["max_dd_pct"],
            "max_dd_date": diag["max_dd_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "spy_published": SPY_PUBLISHED[road],
            "vm_published": VM_PUBLISHED[road],
            "vm_v13": VM_V13[road],
            "bk_published": BK_PUBLISHED[road],
            "bk_v13": BK_V13[road],
            "blend_published": BLEND_PUBLISHED.get(road),
            "beats_published_champion": r["final"] > VM_PUBLISHED[road],
            "beats_vm_v13": r["final"] > VM_V13[road],
            "placebo_beaten": beaten, "placebo_finals": sf,
            "placebo_median": round((sf[9] + sf[10]) / 2.0, 2),
            "placebo_best": sf[-1], "placebo_worst": sf[0],
            "integrity": integ,
            "period_distribution_quarterly": period_distribution(
                r["curve"]),
            "curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    out["roads"][road] = cell
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{road}: BLEND ${r['final']:,.2f} "
          f"(VM ${r['sleeve_finals']['VM']:,.2f} / "
          f"BK ${r['sleeve_finals']['BK']:,.2f}) maxDD "
          f"{diag['max_dd_pct']}% placebo {beaten}/20 "
          f"({time.time()-t0:.0f}s)", flush=True)
    return cell


def main():
    t0 = time.time()
    out = {"family": "winners-blend (momentum basket x value+momentum)",
           "program": "v13-best-rules",
           "spec": "separate sub-pots VM 67 / BK 33, no resets/"
                   "transfers; VM top-2 quarterly no floor (v13 form); "
                   "BK top-3 monthly 200d filter vol-scaled no floor "
                   "(v13 form); program costs. LONG not runnable: "
                   "basket pond is PIT Nov-2016.",
           "selection_caveat": "Members chosen BECAUSE they won on "
                   "these same roads (hindsight-selected by "
                   "construction); taken by pre-registered promoted "
                   "standing, not best-ever numbers.",
           "roads": {}, "confirmation": None}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            out = json.load(f)

    print("loading VM fixed inputs...", flush=True)
    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    print("loading basket market (v4 honest cache)...", flush=True)
    mkt = BK.Mkt()
    ctx = {"pb": pb, "dec": dec, "mkt": mkt}

    for road in ("DECADE", "CONT", "VAL"):
        if road in out["roads"]:
            continue
        run_road(out, road, ctx)

    # ---- adoption bar (pre-registered)
    cont = out["roads"].get("CONT")
    val = out["roads"].get("VAL")
    bar_met = bool(cont and val
                   and cont["final"] > VM_V13["CONT"]
                   and cont["final"] > BK_V13["CONT"]
                   and val["final"] > VM_V13["VAL"]
                   and val["final"] > BK_V13["VAL"])
    out["adoption_bar_met"] = bar_met
    print(f"ADOPTION BAR MET: {bar_met}", flush=True)

    # ---- confirmation (frozen design): triggered if the blend beat
    # the published champion or the v13 pure form on ANY road.
    beat_pub = any(out["roads"][r]["beats_published_champion"]
                   for r in out["roads"])
    beat_v13 = any(out["roads"][r]["beats_vm_v13"] for r in out["roads"])
    out["confirmation_trigger"] = {"beats_published_champion_any_road":
                                   beat_pub,
                                   "beats_vm_v13_any_road": beat_v13}
    print(f"CONFIRMATION TRIGGER: pub={beat_pub} v13={beat_v13}",
          flush=True)
    if (beat_pub or beat_v13) and not out.get("confirmation"):
        conf = {}
        comparators = []
        if beat_pub:
            comparators.append("published_champion_house5")
        if beat_v13:
            comparators.append("vm_v13_top2")
        for comp in comparators:
            folds = {}
            for yr in range(2017, 2027):
                s = f"{yr}-01-01"
                e = END if yr == 2026 else f"{yr}-12-31"
                br = blend_run(ctx, "CONT", s, f"{yr}-01-01", e)
                if comp == "published_champion_house5":
                    cf = vm_house(pb, dec, s, e)
                else:
                    cf = vm_run(pb, dec, s, e, 100.0)
                folds[str(yr)] = {
                    "blend": br["final"],
                    "comparator": round(cf["final"], 2),
                    "blend_win": br["final"] > cf["final"]}
                print(f"FOLD {yr} vs {comp}: blend ${br['final']:,.2f}"
                      f" vs ${cf['final']:,.2f} "
                      f"win={folds[str(yr)]['blend_win']}", flush=True)
            halves = {}
            for hn, (hs, he) in {
                    "H1_2016-2021": ("2016-11-21", "2021-12-31"),
                    "H2_2022-2026": ("2022-01-01", END)}.items():
                br = blend_run(ctx, "DECADE", hs, hs, he)
                if comp == "published_champion_house5":
                    cf = vm_house(pb, dec, hs, he)
                else:
                    cf = vm_run(pb, dec, hs, he, 100.0)
                halves[hn] = {"blend": br["final"],
                              "comparator": round(cf["final"], 2),
                              "blend_win": br["final"] > cf["final"]}
                print(f"HALF {hn} vs {comp}: blend ${br['final']:,.2f}"
                      f" vs ${cf['final']:,.2f} "
                      f"win={halves[hn]['blend_win']}", flush=True)
            wins = sum(1 for v in folds.values() if v["blend_win"])
            hwins = sum(1 for v in halves.values() if v["blend_win"])
            conf[comp] = {
                "design": "fresh-$100 calendar-year folds 2017-2026 + "
                          "DECADE half-windows; blend (67/33 frozen "
                          "rules) vs the beaten form head-to-head",
                "folds": folds, "fold_wins": f"{wins}/10",
                "half_windows": halves, "half_wins": f"{hwins}/2",
                "confirmed": wins >= 6 and hwins >= 1}
            print(f"CONFIRMATION vs {comp}: folds {wins}/10 halves "
                  f"{hwins}/2 confirmed={conf[comp]['confirmed']}",
                  flush=True)
        out["confirmation"] = conf
    out["elapsed_sec"] = round(time.time() - t0, 1)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
