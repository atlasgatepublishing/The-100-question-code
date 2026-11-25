#!/usr/bin/env python3
"""
V13 BEST RULES — hunt-ssr-oscillator (SSR = Glassnode Stablecoin Supply
Ratio Oscillator). SIMULATION ONLY.
Frozen spec: BEST-RULES-SPEC.md in this folder (written before this run).
  SSR = BTC CapMrktCurUSD / sum(SplyCur*PriceUSD over USDT,USDC,DAI),
  CoinMetrics Community (keyless). Bands: SMA200(SSR) +/- k*popSD200(SSR),
  PIT trailing only. MY RULE: enter long BTC on close SSR <= lower band;
  exit to cash on close SSR >= basis (SMA200). v12 form (validation +
  comparison): exit on close SSR >= upper band. Costs 0.60%/side, $100
  pot, long-or-cash, signal at close t earns t->t+1.
Roads: FULL 2019-01-01..2026-11-20, DESIGN 2019-01-01..2022-12-31,
       VAL 2023-01-01..2026-11-20 (bands warmed on trailing SSR history).
Placebos: 20 seeds, band width ~ U[1.5,2.5], my exit rule, FULL + VAL.
"""
import json, os, random, statistics, urllib.request, urllib.parse
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
COST = 0.006
START = 100.0
FETCH_START = "2018-01-01"
END = "2026-11-20"

def fetch(asset, metrics):
    out = {}
    params = {"assets": asset, "metrics": ",".join(metrics), "frequency": "1d",
              "start_time": FETCH_START + "T00:00:00Z",
              "end_time": "2026-11-21T00:00:00Z", "page_size": "10000"}
    url = API + "?" + urllib.parse.urlencode(params)
    while url:
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.load(r)
        for row in d.get("data", []):
            day = row["time"][:10]
            out[day] = {m: (float(row[m]) if row.get(m) is not None else None)
                        for m in metrics}
        url = d.get("next_page_url")
    return out

def build_series():
    cache = os.path.join(HERE, "cm_cache.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    btc = fetch("btc", ["CapMrktCurUSD", "PriceUSD"])
    supply = {}
    for a in ("usdt", "usdc", "dai", "sai"):
        supply[a] = fetch(a, ["SplyCur", "PriceUSD"])
    days = sorted(d for d in btc
                  if btc[d]["CapMrktCurUSD"] is not None and btc[d]["PriceUSD"])
    rows = []
    for d in days:
        tot, ok = 0.0, True
        for a in ("usdt", "usdc"):
            r = supply[a].get(d)
            if not r or r["SplyCur"] is None or not r["PriceUSD"]:
                ok = False; break
            tot += r["SplyCur"] * r["PriceUSD"]
        if not ok:
            continue
        # Dai leg: CoinMetrics split the series at the Nov 2019 SAI->DAI
        # migration (asset 'sai' through 2019-11-30, 'dai' from 2019-11-13).
        # The Dai system's aggregate USD supply during coexistence is
        # SAI + DAI; sum whichever legs are present (documented splice).
        dv, any_dai = 0.0, False
        for a in ("dai", "sai"):
            r = supply[a].get(d)
            if r and r["SplyCur"] is not None and r["PriceUSD"]:
                dv += r["SplyCur"] * r["PriceUSD"]; any_dai = True
        if any_dai and tot + dv > 0:
            rows.append({"d": d, "px": btc[d]["PriceUSD"],
                         "ssr": btc[d]["CapMrktCurUSD"] / (tot + dv)})
    with open(cache, "w") as f:
        json.dump(rows, f)
    return rows

def bands(ssr, k=2.0):
    n = len(ssr); basis = [None]*n; lo = [None]*n; hi = [None]*n
    for i in range(n):
        if i >= 199:
            w = ssr[i-199:i+1]
            m = sum(w)/200.0
            var = sum((x-m)**2 for x in w)/200.0
            sd = var**0.5
            basis[i] = m; lo[i] = m - k*sd; hi[i] = m + k*sd
    return basis, lo, hi

def run_timer(rows, ssr, basis, lo, hi, exit_mode):
    """rows/ssr/bands aligned to the road window. exit_mode: 'basis' (v13)
    or 'upper' (v12). Warmup: bands None -> cash. Returns dict."""
    # curve[t] = equity at close t: earn return t-1->t under the position
    # set at close t-1, then apply the close-t signal (cost on a switch).
    n = len(rows)
    eq = START; pos = False; curve = []
    for t in range(n):
        if t > 0:
            r = rows[t]["px"]/rows[t-1]["px"] - 1.0
            if pos:
                eq *= (1.0 + r)
        if basis[t] is not None:
            if not pos and ssr[t] <= lo[t]:
                pos = True; eq *= (1.0 - COST)
            elif pos:
                exit_line = basis[t] if exit_mode == "basis" else hi[t]
                if ssr[t] >= exit_line:
                    pos = False; eq *= (1.0 - COST)
        curve.append(eq)
    peak, maxdd = START, 0.0
    for e in curve:
        peak = max(peak, e); maxdd = min(maxdd, e/peak - 1.0)
    return {"final": round(curve[-1], 2), "curve": [round(x, 4) for x in curve],
            "max_dd_pct": round(-maxdd*100, 2)}

def orders_count(rows, ssr, basis, lo, hi, exit_mode):
    pos = False; n = 0
    for t in range(len(rows)):
        if basis[t] is None: continue
        if not pos and ssr[t] <= lo[t]:
            pos = True; n += 1
        elif pos:
            line = basis[t] if exit_mode == "basis" else hi[t]
            if ssr[t] >= line:
                pos = False; n += 1
    return n

def buy_hold(rows):
    eq = START*(1-COST)
    curve = []
    p0 = rows[0]["px"]
    for r in rows:
        curve.append(eq*r["px"]/p0)
    final = curve[-1]*(1-COST)
    curve[-1] = final
    peak, maxdd = START, 0.0
    for e in curve:
        peak = max(peak, e); maxdd = min(maxdd, e/peak - 1.0)
    return {"final": round(final, 2), "curve": [round(x, 4) for x in curve],
            "max_dd_pct": round(-maxdd*100, 2)}

def monthly_stats(rows, curve):
    # month-end equity points
    pts = [(rows[0]["d"][:7], START)]
    last_m = None
    for r, e in zip(rows, curve):
        m = r["d"][:7]
        if m != last_m:
            pts.append((m, e)); last_m = m
        else:
            pts[-1] = (m, e)
    vals = [v for _, v in pts]
    rets = [vals[i+1]/vals[i]-1.0 for i in range(len(vals)-1) if vals[i] > 0]
    if not rets: return None
    streak = cur = 0
    for r in rets:
        cur = cur+1 if r < 0 else 0
        streak = max(streak, cur)
    runmax = vals[0]; since = 0; maxgap = 0
    for v in vals[1:]:
        if v >= runmax: runmax = v; since = 0
        else:
            since += 1; maxgap = max(maxgap, since)
    return {"periods": len(rets),
            "share_positive": round(sum(1 for r in rets if r > 0)/len(rets), 4),
            "median": round(statistics.median(rets), 5),
            "best": round(max(rets), 5), "worst": round(min(rets), 5),
            "longest_losing_streak": streak,
            "longest_between_highs_periods": maxgap,
            "average_secondary": round(statistics.mean(rets), 5)}

def window(rows_all, a, b):
    return [r for r in rows_all if a <= r["d"] <= b]

def main():
    rows_all = build_series()
    print("series", rows_all[0]["d"], "->", rows_all[-1]["d"], len(rows_all))
    ssr_all = [r["ssr"] for r in rows_all]
    basis_all, lo_all, hi_all = bands(ssr_all, 2.0)
    idx = {r["d"]: i for i, r in enumerate(rows_all)}

    def slice_bands(rows, warmup_trailing):
        if warmup_trailing:
            gi = [idx[r["d"]] for r in rows]
            return ([basis_all[i] for i in gi], [lo_all[i] for i in gi],
                    [hi_all[i] for i in gi])
        ssr = [r["ssr"] for r in rows]
        return bands(ssr, 2.0)

    out = {"family": "hunt-ssr-oscillator", "program": "v13-best-rules",
           "signal": "Glassnode SSR Oscillator (200d Bollinger, 2 SD pop)",
           "my_rule": "enter SSR<=lower band; exit SSR>=basis; no floor",
           "cost_per_side": COST, "roads": {}, "validation_v12_replication": {}}

    roads = {"FULL": ("2019-01-01", "2026-11-20", False),
             "DESIGN": ("2019-01-01", "2022-12-31", False),
             "VAL": ("2023-01-01", "2026-11-20", True)}

    # 1) ENGINE VALIDATION: reproduce v12 published form (exit at upper)
    for name, (a, b, trail) in roads.items():
        rows = window(rows_all, a, b)
        ssr = [r["ssr"] for r in rows]
        bs, lo, hi = slice_bands(rows, trail)
        rep = run_timer(rows, ssr, bs, lo, hi, "upper")
        out["validation_v12_replication"][name] = {
            "final": rep["final"], "orders": orders_count(rows, ssr, bs, lo, hi, "upper"),
            "max_dd_pct": rep["max_dd_pct"]}
        print("v12-replication", name, rep["final"], rep["max_dd_pct"])

    # 2) MY RULES on all roads + published form + bar
    for name, (a, b, trail) in roads.items():
        rows = window(rows_all, a, b)
        ssr = [r["ssr"] for r in rows]
        bs, lo, hi = slice_bands(rows, trail)
        mine = run_timer(rows, ssr, bs, lo, hi, "basis")
        pub = run_timer(rows, ssr, bs, lo, hi, "upper")
        bar = buy_hold(rows)
        out["roads"][name] = {
            "window": [rows[0]["d"], rows[-1]["d"]], "bars": len(rows),
            "my_rules": {"final": mine["final"], "max_dd_pct": mine["max_dd_pct"],
                         "orders": orders_count(rows, ssr, bs, lo, hi, "basis"),
                         "curve": mine["curve"]},
            "published_form_v12": {"final": pub["final"], "max_dd_pct": pub["max_dd_pct"],
                                   "orders": orders_count(rows, ssr, bs, lo, hi, "upper")},
            "bar_btc_buy_hold": {"final": bar["final"], "max_dd_pct": bar["max_dd_pct"],
                                 "curve": bar["curve"]},
            "monthly_stats_my_rules": monthly_stats(rows, mine["curve"]),
            "monthly_stats_buy_hold": monthly_stats(rows, bar["curve"]),
            "curve_dates": [r["d"] for r in rows]}
        print(name, "mine", mine["final"], "dd", mine["max_dd_pct"],
              "| published", pub["final"], "| bar", bar["final"], bar["max_dd_pct"])

    # 3) Placebos: 20 seeds, width U[1.5,2.5], my exit rule, FULL + VAL
    out["placebos_20"] = {}
    for name in ("FULL", "VAL"):
        a, b, trail = roads[name]
        rows = window(rows_all, a, b)
        ssr = [r["ssr"] for r in rows]
        finals = []
        for s in range(20):
            rng = random.Random(777000 + s)
            k = rng.uniform(1.5, 2.5)
            if trail:
                # jitter around global basis: recompute bands on global ssr
                gb, glo, ghi = bands(ssr_all, k)
                gi = [idx[r["d"]] for r in rows]
                bs = [gb[i] for i in gi]; lo = [glo[i] for i in gi]; hi = [ghi[i] for i in gi]
            else:
                bs, lo, hi = bands(ssr, k)
            finals.append(run_timer(rows, ssr, bs, lo, hi, "basis")["final"])
        mine_final = out["roads"][name]["my_rules"]["final"]
        beaten = sum(1 for f in finals if mine_final > f)
        out["placebos_20"][name] = {"finals": [round(f, 2) for f in finals],
                                    "beaten_by_my_rules": beaten,
                                    "median": round(statistics.median(finals), 2)}
        print("placebos", name, "beaten", beaten, "/20 median", round(statistics.median(finals), 2))

    # 4) Sign-flipped control, FULL, my exit shape (long on upper touch,
    #    exit when SSR falls back to basis)
    rows = window(rows_all, "2019-01-01", "2026-11-20")
    ssr = [r["ssr"] for r in rows]
    bs, lo, hi = bands(ssr, 2.0)
    eq = START; pos = False; curve = []
    for t in range(len(rows)):
        if t > 0:
            r = rows[t]["px"]/rows[t-1]["px"] - 1.0
            if pos: eq *= (1.0 + r)
        if bs[t] is not None:
            if not pos and ssr[t] >= hi[t]:
                pos = True; eq *= (1.0 - COST)
            elif pos and ssr[t] <= bs[t]:
                pos = False; eq *= (1.0 - COST)
        curve.append(eq)
    out["sign_flipped_control_FULL"] = round(curve[-1], 2)
    print("sign-flipped FULL", round(curve[-1], 2))

    # 5) Split-half of FULL (standalone $100 pots, my rules)
    rows = window(rows_all, "2019-01-01", "2026-11-20")
    mid = len(rows)//2
    halves = {}
    for nm, sub in (("half1", rows[:mid]), ("half2", rows[mid:])):
        ssr = [r["ssr"] for r in sub]
        gi = [idx[r["d"]] for r in sub]
        bs = [basis_all[i] for i in gi]; lo = [lo_all[i] for i in gi]; hi = [hi_all[i] for i in gi]
        m = run_timer(sub, ssr, bs, lo, hi, "basis")
        bar = buy_hold(sub)
        halves[nm] = {"window": [sub[0]["d"], sub[-1]["d"]],
                      "my_rules_final": m["final"], "my_rules_max_dd_pct": m["max_dd_pct"],
                      "buy_hold_final": bar["final"], "buy_hold_max_dd_pct": bar["max_dd_pct"]}
    out["split_half_FULL"] = halves
    print("split-half", json.dumps(halves))

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    print("DONE")

if __name__ == "__main__":
    main()
