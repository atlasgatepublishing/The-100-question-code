#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-PLUS-TREND. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: one $100 pot split 70% V+M / 30% ETF Trend AT INCEPTION ONLY,
no inter-sleeve rebalancing (weights drift), NO floor anywhere.
  - V+M sleeve: its v13 best-rules form (top-2, quarterly, no floor),
    taken from the v13 value-momentum folder's results.json (that run
    was integrity-gated to the cent against the published champion).
  - Trend sleeve: its v13 best-rules form (monthly; SPY+QQQ risk-on;
    top-2 GLD/DBC/UUP risk-off; 20% no-trade band; no floor), run here
    on the engine copied verbatim from the v13 etf-trend-sleeve
    folder's run_best.py, integrity-gated below against that folder's
    published v13 finals AND placebo finals before any blend number
    is taken.
Combination at the equity-curve level (the family's original method):
blend final = 0.70*VM_final + 0.30*TR_final (parents' post-liquidation
basis). Placebos seed-paired (VM twins from the v13 VM run; trend
twins seeds 1000-1019, the trend pass's own seeds).
"""
import gc
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "results.json")
VM13_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v13-best-rules/value-momentum/results.json")
TR13_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v13-best-rules/etf-trend-sleeve/results.json")
W_VM, W_TR = 0.70, 0.30
END = "2026-11-20"
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
VM13_FINALS = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73,
               "VAL": 461.20}
TR13_FINALS = {"LONG": 389.49, "DECADE": 248.54, "CONT": 185.36,
               "VAL": 127.38}
BLEND_PUB = {"CONT": 320.97, "VAL": 192.36, "DECADE": 317.85}
SPY_PUB = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
ROADS = {"LONG": ("2010-01-04", END), "DECADE": ("2016-11-21", END),
         "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END)}

# ---------------------------------------------------------------------
# Trend engine — copied verbatim from v13 etf-trend-sleeve/run_best.py
# (engine section only; that folder is read-only shared input).
# ---------------------------------------------------------------------
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
ON_POOL = ["SPY", "QQQ"]
OFF_POOL = ["GLD", "DBC", "UUP"]
ALL = ON_POOL + OFF_POOL
COST = 0.0010
SELL_FEE = 0.01
START = 100.0


def load_series(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"] \
        if "adjclose" in res["indicators"] else None
    out = {}
    for i, tt in enumerate(ts):
        d = datetime.fromtimestamp(tt, tz=timezone.utc).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            out[d] = (o * adj[i] / c, adj[i])
        else:
            out[d] = (o, c)
    return out


SERIES = {t: load_series(t) for t in ALL}
CAL = sorted(SERIES["SPY"].keys())
CI = {d: i for i, d in enumerate(CAL)}


def close_on(t, d):
    s = SERIES[t]
    if d in s:
        return s[d][1]
    i = CI[d]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s:
            return s[CAL[j]][1]
    return None


def open_on(t, d):
    s = SERIES[t]
    return s[d][0] if d in s else close_on(t, d)


def ret_n(t, d, n):
    i = CI[d]
    if i - n < 0:
        return None
    a, b = close_on(t, CAL[i - n]), close_on(t, d)
    return None if a is None or b is None else b / a - 1.0


def uptrend(t, d):
    rs = [ret_n(t, d, n) for n in (63, 126, 252)]
    if any(r is None for r in rs):
        return False
    return sum(1 for r in rs if r > 0) >= 2


def vol_free_targets(d, rng=None):
    if uptrend("SPY", d):
        pool, mode = ON_POOL, "on"
        if rng is None:
            picks = [t for t in pool if uptrend(t, d)]
        else:
            qual = [t for t in pool if uptrend(t, d)]
            k = len(qual)
            picks = rng.sample(pool, k) if k else []
    else:
        pool, mode = OFF_POOL, "off"
        qual = [t for t in pool if uptrend(t, d)]
        if rng is None:
            qual.sort(key=lambda t: ret_n(t, d, 126), reverse=True)
            picks = qual[:2]
        else:
            k = min(2, len(qual))
            picks = rng.sample(pool, k) if k else []
    if not picks:
        return {}, mode
    w = 1.0 / len(picks)
    return {t: w for t in picks}, mode


def month_ends(start, end):
    days = [d for d in CAL if start <= d <= end]
    out = []
    for i, d in enumerate(days):
        if i == len(days) - 1 or days[i + 1][:7] != d[:7]:
            out.append(d)
    return out


def run_road(start, end, seed=None):
    rng = random.Random(seed) if seed is not None else None
    days = [d for d in CAL if start <= d <= end]
    rebal = set(month_ends(start, end))
    cash, shares = START, {t: 0.0 for t in ALL}
    costs, orders = 0.0, 0
    pending = None
    curve = []

    def value(d, use_open=False):
        v = cash
        for t in ALL:
            if shares[t]:
                p = open_on(t, d) if use_open else close_on(t, d)
                if p:
                    v += shares[t] * p
        return v
    for idx, d in enumerate(days):
        if pending is not None:
            targets = pending
            pending = None
            total = value(d, use_open=True)
            cur_w = {}
            for t in ALL:
                p = open_on(t, d)
                cur_w[t] = (shares[t] * p / total) \
                    if (shares[t] and p and total > 0) else 0.0
            for t in ALL:
                tw = targets.get(t, 0.0)
                if shares[t] > 0 and tw > 0 \
                        and abs(tw - cur_w[t]) / tw <= 0.20:
                    continue
                p = open_on(t, d)
                if not p:
                    continue
                delta_val = tw * total - shares[t] * p
                if abs(delta_val) < 0.01:
                    continue
                if delta_val < 0:
                    amt = min(-delta_val, shares[t] * p)
                    fee = amt * COST + SELL_FEE
                    cash += amt - fee
                    costs += fee
                    orders += 1
                    shares[t] -= amt / p
                else:
                    amt = min(delta_val, max(cash - 0.0, 0.0))
                    if amt <= 0:
                        continue
                    fee = amt * COST
                    if amt + fee > cash:
                        amt = cash / (1 + COST)
                        fee = amt * COST
                    cash -= amt + fee
                    costs += fee
                    orders += 1
                    shares[t] += amt / p
        curve.append([d, round(value(d), 4)])
        if d in rebal and idx < len(days) - 1:
            pending, _ = vol_free_targets(d, rng)
    final = curve[-1][1] if curve else START
    peak, maxdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1.0)
    return {"start": start, "end": end, "final": round(final, 2),
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "equity_curve": curve}

# ---------------------------------------------------------------------
# Blend helpers (vm-lazyp pass's method)
# ---------------------------------------------------------------------


def max_dd(curve):
    peak, mdd, mdd_date = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0 and (peak - v) / peak > mdd:
            mdd, mdd_date = (peak - v) / peak, d
    return round(mdd * 100, 2), mdd_date


def blend_curves(vm_curve, tr_curve):
    A, B = dict(vm_curve), dict(tr_curve)
    lo = max(min(A), min(B))
    hi = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if lo <= d <= hi)
    out, la, lb = [], None, None
    for d in dates:
        la = A.get(d, la)
        lb = B.get(d, lb)
        if la is not None and lb is not None:
            out.append((d, W_VM * la + W_TR * lb))
    return out


def period_distribution(curve):
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
                        "pct": round((v / prev - 1) * 100, 2)
                        if prev else None})
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
            "share_positive_pct":
                round(100.0 * sum(1 for c in ch if c > 0) / n, 1),
            "best": best, "worst": worst,
            "longest_losing_streak_qtrs": longest,
            "longest_between_new_highs_qtrs": max_gap,
            "mean_change_secondary": round(sum(ch) / n, 2)}


def main():
    t0 = time.time()
    with open(VM13_PATH) as f:
        vm13 = json.load(f)
    with open(TR13_PATH) as f:
        tr13 = json.load(f)
    out = {"program": "v13-best-rules", "family": "vm-plus-trend",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "my_rules": {"weights_inception": {"vm": W_VM, "trend": W_TR},
                        "rebalancing": "none (weights drift)",
                        "floor": None,
                        "vm_sleeve": "v13 best-rules: top-2 quarterly "
                                     "no floor",
                        "trend_sleeve": "v13 best-rules: monthly, "
                                        "SPY+QQQ on / top-2 GLD-DBC-UUP "
                                        "off, 20% band, no floor",
                        "costs": "0.10%/side + $0.01 per sell order "
                                 "(in-sleeve)",
                        "start_cash": 100.0},
           "integrity": {}, "roads": {}, "confirmation": None}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            out = json.load(f)

    def save():
        with open(OUT_PATH, "w") as f:
            json.dump(out, f, indent=1)

    # ---------- integrity gate: trend engine reproduces its v13 pass
    if not out["integrity"]:
        checks = []
        for road, (s, e) in ROADS.items():
            r = run_road(s, e)
            twins = [run_road(s, e, seed=1000 + i)["final"]
                     for i in range(20)]
            pub = tr13["roads"][road]["run"]
            ok_f = r["final"] == TR13_FINALS[road]
            ok_p = twins == [round(x, 2) for x in pub["placebo_finals"]]
            checks.append({"check": f"trend {road} v13 form",
                           "expected_final": TR13_FINALS[road],
                           "reproduced_final": r["final"],
                           "final_match": ok_f,
                           "placebo_finals_match": ok_p})
            print(f"INTEGRITY trend {road}: final {r['final']} vs "
                  f"{TR13_FINALS[road]} match={ok_f} placebos "
                  f"match={ok_p} ({time.time()-t0:.0f}s)", flush=True)
        vm_int = {k: v for k, v in vm13["integrity"].items()}
        out["integrity"] = {"trend_engine": checks,
                            "vm_v13_integrity": vm_int,
                            "vm_v13_all_match": all(
                                v["match"] for v in vm_int.values())}
        save()
        if not (all(c["final_match"] and c["placebo_finals_match"]
                    for c in checks)
                and out["integrity"]["vm_v13_all_match"]):
            print("INTEGRITY FAILED — no v13 blend numbers produced",
                  flush=True)
            sys.exit(1)

    # ---------- the one frozen run, per road
    beat = []
    for road, (s, e) in ROADS.items():
        if road in out["roads"]:
            if out["roads"][road]["beats_champion_published"] or \
                    out["roads"][road]["beats_vm_v13_parent"]:
                beat.append(road)
            continue
        tr = run_road(s, e)
        tr_twins = [run_road(s, e, seed=1000 + i)["final"]
                    for i in range(20)]
        assert tr["final"] == TR13_FINALS[road]
        assert tr_twins == [round(x, 2) for x in
                            tr13["roads"][road]["run"]["placebo_finals"]]
        vmr = vm13["roads"][road]["my_rules"]
        assert abs(round(vmr["final"], 2) - VM13_FINALS[road]) < 0.02
        vm_twins = [round(x, 2) for x in vmr["placebo_finals"]]
        curve = blend_curves(vmr["curve"], tr["equity_curve"])
        blend_final = round(W_VM * vmr["final"] + W_TR * tr["final"], 2)
        twins = sorted(round(W_VM * a + W_TR * b, 2)
                       for a, b in zip(vm_twins, tr_twins))
        beaten = sum(1 for x in twins if blend_final > x)
        dd, dd_date = max_dd(curve)
        cell = {
            "window": [s, e],
            "blend_final": blend_final,
            "blend_final_mtm": round(curve[-1][1], 2),
            "blend_max_dd_pct": -dd, "blend_max_dd_date": dd_date,
            "blend_costs": round(W_VM * vmr["costs"]
                                 + W_TR * tr["costs"], 2),
            "blend_costs_note": "sleeve costs scaled by inception "
                                "weights (fixed $0.01 fees approx)",
            "orders": vmr["orders"] + tr["orders"],
            "vm_sleeve_final_100basis": round(vmr["final"], 2),
            "vm_sleeve_max_dd_pct": vmr["max_dd_pct"],
            "vm_sleeve_costs": vmr["costs"],
            "vm_sleeve_orders": vmr["orders"],
            "tr_sleeve_final_100basis": tr["final"],
            "tr_sleeve_max_dd_pct": tr["max_dd_pct"],
            "tr_sleeve_costs": tr["costs"],
            "tr_sleeve_orders": tr["orders"],
            "tr_placebo_finals": tr_twins,
            "placebo_beaten": beaten,
            "placebo_median": round(twins[len(twins) // 2], 2),
            "placebo_best": twins[-1], "placebo_worst": twins[0],
            "placebo_finals": twins,
            "champion_published": CHAMPION[road],
            "blend_published": BLEND_PUB.get(road),
            "vm_v13_parent": VM13_FINALS[road],
            "trend_v13_parent": TR13_FINALS[road],
            "spy_published": SPY_PUB[road],
            "beats_champion_published": blend_final > CHAMPION[road],
            "beats_blend_published":
                (blend_final > BLEND_PUB[road]) if road in BLEND_PUB
                else None,
            "beats_vm_v13_parent": blend_final > VM13_FINALS[road],
            "distribution": period_distribution(curve),
            "curve": [[d, round(v, 4)] for d, v in curve],
        }
        out["roads"][road] = cell
        save()
        print(f"{road}: BLEND ${blend_final:,.2f} dd -{dd}% "
              f"(VM13 ${VM13_FINALS[road]:,.2f} / TR13 "
              f"${tr['final']:,.2f} / champ ${CHAMPION[road]:,.2f}) "
              f"placebo {beaten}/20 ({time.time()-t0:.0f}s)", flush=True)
        if blend_final > CHAMPION[road] or \
                blend_final > VM13_FINALS[road]:
            beat.append(road)
        gc.collect()

    # ---------- confirmation (Terry's rule) if triggered
    if beat and not out.get("confirmation"):
        print(f"CONFIRMATION triggered for: {beat}", flush=True)
        vm_conf = vm13["confirmation"]
        folds = {}
        for yr in range(2017, 2027):
            fs = "2017-01-03" if yr == 2017 else f"{yr}-01-01"
            fe = END if yr == 2026 else f"{yr}-12-31"
            trf = run_road(fs, fe)
            vmf = vm_conf["year_folds"][str(yr)]
            bf = round(W_VM * vmf["my_rules_final"]
                       + W_TR * trf["final"], 2)
            folds[str(yr)] = {
                "blend_final": bf,
                "vm_v13_final": vmf["my_rules_final"],
                "trend_v13_final": trf["final"],
                "published_champion_final": vmf["published_final"],
                "blend_beats_published_champion":
                    bf > vmf["published_final"],
                "blend_beats_vm_v13":
                    bf > vmf["my_rules_final"]}
            print(f"FOLD {yr}: blend ${bf:,.2f} vs published champ "
                  f"${vmf['published_final']:,.2f} win="
                  f"{bf > vmf['published_final']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        halves = {}
        for hn, (hs, he) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                             "H2_2022-2026": ("2022-01-01", END)}.items():
            trh = run_road(hs, he)
            vmh = vm_conf["half_windows"][hn]
            bf = round(W_VM * vmh["my_rules_final"]
                       + W_TR * trh["final"], 2)
            halves[hn] = {
                "blend_final": bf,
                "vm_v13_final": vmh["my_rules_final"],
                "trend_v13_final": trh["final"],
                "published_champion_final": vmh["published_final"],
                "blend_beats_published_champion":
                    bf > vmh["published_final"],
                "blend_beats_vm_v13": bf > vmh["my_rules_final"]}
            print(f"HALF {hn}: blend ${bf:,.2f} vs published champ "
                  f"${vmh['published_final']:,.2f}", flush=True)
        wins = sum(1 for v in folds.values()
                   if v["blend_beats_published_champion"])
        hwins = sum(1 for v in halves.values()
                    if v["blend_beats_published_champion"])
        out["confirmation"] = {
            "trigger_roads": beat,
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full blend rule set vs the "
                      "published champion house form (count 5 + floor); "
                      "VM fold finals from the v13 value-momentum "
                      "confirmation, trend folds run here, same spec. "
                      "Bar frozen in spec: >=6/10 folds AND >=1/2 halves",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        save()
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={out['confirmation']['confirmed']}", flush=True)
        gc.collect()
    out["elapsed_sec"] = round(time.time() - t0, 1)
    save()
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
