#!/usr/bin/env python3
"""V13 BEST RULES — Whaley Breadth Thrusts. Spec: BEST-RULES-SPEC.md (frozen).
Triggers UNCHANGED (Whaley 2010): ADT 5d advance share >73.66%, UDT 5d
up-volume share >77.88%, SPT 5d SPY % change >+10.05%; series from the
154-name PIT pond stack (v7 pxfull), point-in-time. ONE pot: entry on ANY
thrust print while flat, SPY all-in at next open. Exit: next open after
first SPY close below its 200d SMA while holding. No floor. Costs
0.10%/side + $0.01/sell. Placebo: 20 seeds/road random-timing, same entry
count, same trend exit."""
import json, os, random, statistics, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST, FEE, START = 0.001, 0.01, 100.0
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB_BEST = {"LONG": 185.09, "DECADE": 198.59, "CONT": 197.75, "VAL": 145.82}  # UDT native, v12

def load_bars(sym, want_vol=False):
    j = json.load(open(os.path.join(V7, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]; vol = q.get("volume")
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        b = {"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": q["open"][i]*ratio, "c": adj[i]}
        if want_vol: b["v"] = vol[i] if vol and vol[i] else 0
        bars.append(b)
    bars.sort(key=lambda b: b["d"]); return bars

def build_series(spy):
    pond = sorted(f[7:-5] for f in os.listdir(V7) if f.startswith("pxfull_") and f[7:-5] != "SPY")
    adv, dec, upv, dnv = {}, {}, {}, {}
    for t in pond:
        bars = load_bars(t, want_vol=True)
        for i in range(1, len(bars)):
            d = bars[i]["d"]; pc = bars[i-1]["c"]
            if bars[i]["c"] > pc: adv[d] = adv.get(d, 0) + 1; upv[d] = upv.get(d, 0) + bars[i]["v"]
            elif bars[i]["c"] < pc: dec[d] = dec.get(d, 0) + 1; dnv[d] = dnv.get(d, 0) + bars[i]["v"]
    dates = [b["d"] for b in spy]
    A = [adv.get(d, 0) for d in dates]; D = [dec.get(d, 0) for d in dates]
    U = [upv.get(d, 0) for d in dates]; W = [dnv.get(d, 0) for d in dates]
    C = [b["c"] for b in spy]
    n = len(dates)
    adt = [False]*n; udt = [False]*n; spt = [False]*n
    adt_cap = [False]*n; udt_cap = [False]*n; spt_cap = [False]*n
    for i in range(n):
        if i >= 4:
            sa, sd = sum(A[i-4:i+1]), sum(D[i-4:i+1]); su, sw = sum(U[i-4:i+1]), sum(W[i-4:i+1])
            if sa + sd > 0:
                adt[i] = sa/(sa+sd) > 0.7366; adt_cap[i] = sa/(sa+sd) < 0.1905
            if su + sw > 0:
                udt[i] = su/(su+sw) > 0.7788; udt_cap[i] = su/(su+sw) < 0.1641
        if i >= 5:
            chg = C[i]/C[i-5] - 1; spt[i] = chg > 0.1005; spt_cap[i] = chg < -0.1385
    union = [adt[i] or udt[i] or spt[i] for i in range(n)]
    sma = [None]*n
    for i in range(n):
        if i >= 199: sma[i] = sum(C[i-199:i+1]) / 200
    return {"dates": dates, "adt": adt, "udt": udt, "spt": spt, "union": union,
            "adt_cap": adt_cap, "udt_cap": udt_cap, "spt_cap": spt_cap, "sma": sma, "pond_n": len(pond)}

def clusters(flags, dates, s, e):
    return [dates[i] for i, f in enumerate(flags) if f and (i == 0 or not flags[i-1]) and s <= dates[i] <= e]

def simulate(seg, sma_seg, signal_idxs):
    """signal_idxs: indices into seg whose CLOSE carries a thrust print.
    Buy next open when flat; sell next open after first close < SMA200.
    Re-entry needs a print at/after the exit execution day. Liquidate at
    final close (net of costs) if still holding at road end."""
    sig = set(signal_idxs)
    cash, shares, curve, trades, log = START, 0.0, [], 0, []
    invested = 0; pend_buy = False; pend_sell = False; last_exit_idx = -1
    for i, b in enumerate(seg):
        if pend_sell and shares > 0:
            cash = shares * b["o"] * (1 - COST) - FEE; shares = 0.0; trades += 1
            log[-1]["exit"] = b["d"]; log[-1]["exit_reason"] = "close_below_200d_sma"
            pend_sell = False; last_exit_idx = i
        if pend_buy and shares == 0:
            shares = cash * (1 - COST) / b["o"]; cash = 0.0; trades += 1
            log.append({"entry": b["d"]}); pend_buy = False
        if shares > 0: invested += 1
        curve.append([b["d"], round(cash + shares * b["c"], 4)])
        if shares > 0 and sma_seg[i] is not None and b["c"] < sma_seg[i]:
            pend_sell = True
        if shares == 0 and not pend_buy and not pend_sell and i in sig and i >= last_exit_idx:
            pend_buy = True
    if shares > 0:
        cash = shares * seg[-1]["c"] * (1 - COST) - FEE; trades += 1
        log[-1]["exit"] = seg[-1]["d"]; log[-1]["exit_reason"] = "road_end_liquidation"
        curve[-1] = [curve[-1][0], round(cash, 4)]
    return {"final": round(curve[-1][1], 2), "curve": curve, "trades": trades,
            "entries": sum(1 for t in log if "entry" in t), "log": log,
            "invested_share": round(invested / max(1, len(seg)), 4)}

def max_dd(curve):
    peak, dd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq); dd = max(dd, (peak - eq)/peak if peak > 0 else 0.0)
    return round(dd*100, 2)

def period_stats(curve):
    months = {}
    for d, eq in curve: months[d[:7]] = eq
    ks = sorted(months); rets = []; prev = START
    for k in ks: rets.append(months[k]/prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets: streak = streak + 1 if r < 0 else 0; worst = max(worst, streak)
    vals = [START] + [months[k] for k in ks]
    peak = vals[0]; since = longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos/len(rets), 4),
            "median_pct": round(statistics.median(rets)*100, 3),
            "best_pct": round(max(rets)*100, 3), "worst_pct": round(min(rets)*100, 3),
            "longest_losing_streak": worst, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets)*100, 3)}

def yearly_and_halves(seg, curve):
    years = {}
    for d, eq in curve: years[d[:4]] = eq
    ks = sorted(years); yrets = {}; prev = START
    for k in ks: yrets[k] = round((years[k]/prev - 1)*100, 2); prev = years[k]
    mid = len(seg)//2
    def growth(part):
        if len(part) < 2: return None
        sh = START*(1-COST)/part[0]["o"]; return round(sh*part[-1]["c"]*(1-COST)-FEE, 2)
    def strat_growth(idxs):
        if len(idxs) < 2: return None
        base = curve[idxs[0]][1]
        return round(START * curve[idxs[-1]][1]/base, 2) if base > 0 else None
    half = len(curve)//2
    return {"yearly_pct": yrets, "years_positive_share": round(sum(1 for v in yrets.values() if v > 0)/max(1, len(yrets)), 4),
            "spy_half_finals": [growth(seg[:mid]), growth(seg[mid:])],
            "strat_half_finals": [strat_growth(list(range(0, half))), strat_growth(list(range(half, len(curve))))]}

def buyhold(seg):
    sh = START*(1-COST)/seg[0]["o"]
    return round(sh*seg[-1]["c"]*(1-COST)-FEE, 2)

def main():
    spy = load_bars("SPY")
    S = build_series(spy)
    dates = S["dates"]
    out = {"family": "hunt-whaley-thrusts", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "signal": "Whaley (2010) ADT/UDT/SPT 5-day thrusts, exact published thresholds, union entry; trend (200d SMA) exit; no floor",
           "pond_n": S["pond_n"],
           "census_full_history": {}, "roads": {}}
    for name, fl in [("ADT", S["adt"]), ("UDT", S["udt"]), ("SPT", S["spt"]), ("UNION", S["union"])]:
        out["census_full_history"][name] = {"print_days": sum(fl),
            "clusters": clusters(fl, dates, dates[0], dates[-1])}
    for name, fl in [("ADT", S["adt_cap"]), ("UDT", S["udt_cap"]), ("SPT", S["spt_cap"])]:
        out["census_full_history"][name + "_capitulation_print_days"] = sum(fl)
    for road, (s, e) in ROADS.items():
        i0 = next(i for i, b in enumerate(spy) if b["d"] >= s)
        i1 = max(i for i, b in enumerate(spy) if b["d"] <= e)
        seg = spy[i0:i1+1]; sma_seg = S["sma"][i0:i1+1]
        sig = [i - i0 for i in range(i0, i1+1) if S["union"][i]]
        r = simulate(seg, sma_seg, sig)
        k = r["entries"]
        pf = []
        for seed in range(1, 21):
            rng = random.Random(seed*7919 + len(road)*131 + k)
            ent = sorted(rng.sample(range(len(seg)-1), k)) if k else []
            pf.append(simulate(seg, sma_seg, ent)["final"])
        beaten = sum(1 for p in pf if r["final"] > p)
        cen = {}
        for name, fl in [("ADT", S["adt"]), ("UDT", S["udt"]), ("SPT", S["spt"])]:
            cen[name] = {"print_days_in_road": sum(1 for i in range(i0, i1+1) if fl[i]),
                         "clusters_in_road": clusters(fl, dates, s, e)}
        rec = {"final": r["final"], "max_dd_pct": max_dd(r["curve"]), "trades": r["trades"],
               "entries_taken": k, "invested_share": r["invested_share"],
               "curve": r["curve"], "trade_log": r["log"],
               "period_stats_monthly": period_stats(r["curve"]),
               "placebos_20": pf, "placebo_median": round(statistics.median(pf), 2) if pf else None,
               "placebos_beaten": beaten, "census": cen,
               "spy_buyhold_computed": buyhold(seg), "spy_program_ref": SPYREF[road],
               "champion_vm": CHAMP[road], "published_best_udt_native": PUB_BEST[road],
               **yearly_and_halves(seg, r["curve"])}
        out["roads"][road] = rec
        print(f"{road}: final ${r['final']} dd {rec['max_dd_pct']}% entries {k} invested {r['invested_share']} "
              f"placebos {beaten}/20 (med ${rec['placebo_median']}) SPY ${rec['spy_buyhold_computed']}", flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__": main()
