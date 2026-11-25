#!/usr/bin/env python3
"""
V13 BEST-RULES — COMBO V+M x LAZY PRICES. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: one $100 pot split 70% V+M / 30% Lazy AT INCEPTION ONLY,
no inter-sleeve rebalancing (weights drift), NO floor anywhere.
  - V+M sleeve: its v13 best-rules form (top-2, quarterly, no floor),
    taken from the v13 value-momentum folder's results.json (that run
    was integrity-gated to the cent against the published champion).
  - Lazy sleeve: top-5, QUARTERLY, no floor, run here on the Lazy
    chassis (lq_common + v12 engine_n), integrity-gated below against
    the published Lazy record before any v13 number is taken.
Combination at the equity-curve level (the original combo's method):
sleeve paths scaled to $70/$30, summed daily (forward-fill alignment).
Blend final on the parents' basis = 0.70*VM_final + 0.30*LZ_final
(each parent final is post-liquidation). Placebos seed-paired.
"""
import gc
import json
import os
import random
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/lazy-quarterly"))
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-lazy-prices"))
import lq_common as Q  # noqa: E402
import engine_n as EN  # noqa: E402

C = Q.C
END = Q.END
OUT_PATH = os.path.join(HERE, "results.json")
VM13_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v13-best-rules/value-momentum/results.json")
W_VM, W_LZ = 0.70, 0.30
SEEDS = list(range(1, 21))
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
LAZY_PUB = {"LONG": 559.69, "DECADE": 514.77, "CONT": 504.34, "VAL": 324.12}
COMBO_PUB = {"CONT": 540.72, "VAL": 312.55}
SPY_PUB = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
VM13_FINALS = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73,
               "VAL": 461.20}


def road_setup(road):
    if road == "LONG":
        pond = Q.pond2010()
        bars = {t: C.bars_adj(C.yahoo_payload(t)) for t in pond}
        bars["SPY"] = C.bars_adj(C.yahoo_payload("SPY"))
        return C.FastPriceBook(bars), Q.era_signals(), pond, "2010-01-04", END
    lazy, _pb, sims = Q.gap_book()
    book = C.FastPriceBook({t: lazy.get_prices(t)
                            for t in lazy.UNIVERSE + ["SPY"]})
    starts = {"DECADE": "2016-11-21", "CONT": "2019-01-02",
              "VAL": "2023-01-03"}
    return book, sims, list(lazy.UNIVERSE), starts[road], END


def max_dd(curve):
    peak, mdd, mdd_date = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > mdd:
            mdd, mdd_date = (peak - v) / peak, d
    return round(mdd * 100, 2), mdd_date


def blend_curves(vm_curve, lz_curve):
    """Daily pot curve: 0.70*VM($100 mtm) + 0.30*LZ($100 mtm),
    forward-filled over the union of dates in the overlap window."""
    A, B = dict(vm_curve), dict(lz_curve)
    lo = max(min(A), min(B))
    hi = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if lo <= d <= hi)
    out, la, lb = [], None, None
    for d in dates:
        la = A.get(d, la)
        lb = B.get(d, lb)
        if la is not None and lb is not None:
            out.append((d, W_VM * la + W_LZ * lb))
    return out


def period_distribution(curve):
    """Quarterly periods (the sleeves' tempo), VM-v13 reporting style."""
    qend = {}
    for d, v in curve:
        q = f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}"
        qend[q] = (d, v)
    keys = sorted(qend)
    periods = []
    prev = 100.0
    for q in keys:
        d, v = qend[q]
        periods.append({"q": q, "end_date": d, "end_value": round(v, 2),
                        "change": round(v - prev, 2),
                        "pct": round((v / prev - 1) * 100, 2) if prev else None})
        prev = v
    ch = [p["change"] for p in periods]
    if not ch:
        return None
    srt = sorted(ch)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = longest = 0
    for c in ch:
        streak = streak + 1 if c < 0 else 0
        longest = max(longest, streak)
    peak, last_high_i = -1.0, 0
    max_gap = 0
    for i, p in enumerate(periods):
        if p["end_value"] >= peak:
            max_gap = max(max_gap, i - last_high_i)
            peak, last_high_i = p["end_value"], i
    max_gap = max(max_gap, len(periods) - 1 - last_high_i)
    best = max(periods, key=lambda p: p["change"])
    worst = min(periods, key=lambda p: p["change"])
    return {"periods": len(periods), "median_change": round(median, 2),
            "share_positive_pct": round(100.0 * sum(1 for c in ch if c > 0) / n, 1),
            "best": best, "worst": worst,
            "longest_losing_streak_qtrs": longest,
            "longest_between_new_highs_qtrs": max_gap,
            "mean_change_secondary": round(sum(ch) / n, 2)}


def lz_run(book, sims, uni, s, e, rng=None):
    return EN.run_pot_n(book, sims, uni, s, e, 5, 100.0, 0.0,
                        placebo_rng=rng, record_pools=False)


def main():
    t0 = time.time()
    with open(VM13_PATH) as f:
        vm13 = json.load(f)
    out = {"program": "v13-best-rules", "family": "combo-vm-lazyp",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "my_rules": {"weights_inception": {"vm": W_VM, "lazy": W_LZ},
                        "rebalancing": "none (weights drift)",
                        "floor": None,
                        "vm_sleeve": "v13 best-rules: top-2 quarterly no floor",
                        "lazy_sleeve": "top-5 quarterly no floor",
                        "costs": "0.10%/side + $0.01 per sell order (in-sleeve)",
                        "start_cash": 100.0},
           "integrity": {}, "roads": {}, "confirmation": None}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            out = json.load(f)

    def save():
        with open(OUT_PATH, "w") as f:
            json.dump(out, f, indent=1)

    # ---------- integrity gate: Lazy chassis reproduces published record
    if not out["integrity"]:
        checks = []
        for road, form, expect in (("VAL", "native", 324.12),
                                   ("CONT", "native", 504.34),
                                   ("DECADE", "house", 514.77),
                                   ("LONG", "house", 559.69)):
            book, sims, uni, s, e = road_setup(road)

            def run_one(ss, ee, cash, floor, _b=book, _s=sims, _u=uni):
                return EN.run_pot_n(_b, _s, _u, ss, ee, 5, cash, floor)
            if form == "house":
                val = round(C.run_v9(run_one, book.dates, s, e)["final"], 2)
            else:
                val = round(run_one(s, e, 100.0, 85.0)["final"], 2)
            checks.append({"check": f"lazy {road} {form} N=5 quarterly",
                           "expected": expect, "reproduced": val,
                           "pass": val == expect})
            print(f"INTEGRITY lazy {road}: {val} vs {expect} "
                  f"pass={val == expect} ({time.time()-t0:.0f}s)", flush=True)
            del book
            gc.collect()
        vm_int = {k: v for k, v in vm13["integrity"].items()}
        out["integrity"] = {"lazy_chassis": checks,
                            "vm_v13_integrity": vm_int,
                            "vm_v13_all_match": all(
                                v["match"] for v in vm_int.values())}
        save()
        if not (all(c["pass"] for c in checks)
                and out["integrity"]["vm_v13_all_match"]):
            print("INTEGRITY FAILED — no v13 blend numbers produced",
                  flush=True)
            sys.exit(1)

    # ---------- the one frozen run, per road
    beat_champion = []
    for road in ("LONG", "DECADE", "CONT", "VAL"):
        if road in out["roads"]:
            if out["roads"][road]["blend_final"] > CHAMPION[road]:
                beat_champion.append(road)
            continue
        book, sims, uni, s, e = road_setup(road)
        lz = lz_run(book, sims, uni, s, e)
        lz_twins = []
        for seed in SEEDS:
            tr = lz_run(book, sims, uni, s, e, rng=random.Random(seed))
            lz_twins.append(round(tr["final"], 2))
        vmr = vm13["roads"][road]["my_rules"]
        assert abs(round(vmr["final"], 2) - VM13_FINALS[road]) < 0.02
        vm_twins = [round(x, 2) for x in vmr["placebo_finals"]]
        curve = blend_curves(vmr["curve"],
                             [[d, v] for d, v in lz["curve"]])
        blend_final = round(W_VM * vmr["final"] + W_LZ * lz["final"], 2)
        twins = sorted(round(W_VM * a + W_LZ * b, 2)
                       for a, b in zip(vm_twins, lz_twins))
        beaten = sum(1 for x in twins if blend_final > x)
        dd, dd_date = max_dd(curve)
        cell = {
            "window": [s, e],
            "blend_final": blend_final,
            "blend_final_mtm": round(curve[-1][1], 2),
            "blend_max_dd_pct": -dd, "blend_max_dd_date": dd_date,
            "blend_costs_scaled_note": "sleeve costs scaled by inception "
                                       "weights (fixed $0.01 fees approx)",
            "blend_costs": round(W_VM * vmr["costs"]
                                 + W_LZ * lz["costs"], 2),
            "orders": vmr["orders"] + len(lz["trades"]),
            "vm_sleeve_final_100basis": round(vmr["final"], 2),
            "vm_sleeve_max_dd_pct": vmr["max_dd_pct"],
            "lz_sleeve_final_100basis": round(lz["final"], 2),
            "lz_sleeve_costs": round(lz["costs"], 2),
            "lz_sleeve_orders": len(lz["trades"]),
            "lz_sleeve_max_dd_pct": -max_dd(lz["curve"])[0],
            "placebo_beaten": beaten,
            "placebo_median": round(twins[len(twins) // 2], 2),
            "placebo_best": twins[-1], "placebo_worst": twins[0],
            "placebo_finals": twins,
            "lz_placebo_finals": lz_twins,
            "champion_published": CHAMPION[road],
            "lazy_published": LAZY_PUB[road],
            "combo_published": COMBO_PUB.get(road),
            "vm_v13_parent": VM13_FINALS[road],
            "spy_published": SPY_PUB[road],
            "beats_champion_published": blend_final > CHAMPION[road],
            "beats_lazy_published": blend_final > LAZY_PUB[road],
            "beats_vm_v13_parent": blend_final > VM13_FINALS[road],
            "distribution": period_distribution(curve),
            "curve": [[d, round(v, 4)] for d, v in curve],
        }
        out["roads"][road] = cell
        save()
        print(f"{road}: BLEND ${blend_final:,.2f} dd -{dd}% "
              f"(VM13 ${VM13_FINALS[road]:,.2f} / LZq-nf "
              f"${cell['lz_sleeve_final_100basis']:,.2f} / champ "
              f"${CHAMPION[road]:,.2f}) placebo {beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)
        if blend_final > CHAMPION[road]:
            beat_champion.append(road)
        del book
        gc.collect()

    # ---------- confirmation (Terry's rule) if a champion fell
    if beat_champion and not out.get("confirmation"):
        print(f"CONFIRMATION triggered for: {beat_champion}", flush=True)
        book, sims, uni, _s, _e = road_setup("CONT")  # Nov-2016 pond book
        vm_conf = vm13["confirmation"]
        folds = {}
        for yr in range(2017, 2027):
            fs = f"{yr}-01-01"
            fe = END if yr == 2026 else f"{yr}-12-31"
            if yr == 2017:
                fs = "2017-01-03"
            lzf = lz_run(book, sims, uni, fs, fe)
            vmf = vm_conf["year_folds"][str(yr)]
            bf = round(W_VM * vmf["my_rules_final"]
                       + W_LZ * lzf["final"], 2)
            folds[str(yr)] = {
                "blend_final": bf,
                "vm_v13_final": vmf["my_rules_final"],
                "lz_q_nofloor_final": round(lzf["final"], 2),
                "published_champion_final": vmf["published_final"],
                "blend_beats_published_champion": bf > vmf["published_final"]}
            print(f"FOLD {yr}: blend ${bf:,.2f} vs published champ "
                  f"${vmf['published_final']:,.2f} "
                  f"win={bf > vmf['published_final']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        halves = {}
        for hn, (hs, he) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                             "H2_2022-2026": ("2022-01-01", END)}.items():
            lzh = lz_run(book, sims, uni, hs, he)
            vmh = vm_conf["half_windows"][hn]
            bf = round(W_VM * vmh["my_rules_final"]
                       + W_LZ * lzh["final"], 2)
            halves[hn] = {
                "blend_final": bf,
                "vm_v13_final": vmh["my_rules_final"],
                "lz_q_nofloor_final": round(lzh["final"], 2),
                "published_champion_final": vmh["published_final"],
                "blend_beats_published_champion":
                    bf > vmh["published_final"]}
            print(f"HALF {hn}: blend ${bf:,.2f} vs published champ "
                  f"${vmh['published_final']:,.2f}", flush=True)
        wins = sum(1 for v in folds.values()
                   if v["blend_beats_published_champion"])
        hwins = sum(1 for v in halves.values()
                    if v["blend_beats_published_champion"])
        out["confirmation"] = {
            "trigger_roads": beat_champion,
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full blend rule set vs the "
                      "published champion house form (count 5 + floor); "
                      "VM fold finals from the v13 value-momentum "
                      "confirmation, Lazy folds run here, same spec",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        save()
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={out['confirmation']['confirmed']}", flush=True)
        del book
        gc.collect()
    out["elapsed_sec"] = round(time.time() - t0, 1)
    save()
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
