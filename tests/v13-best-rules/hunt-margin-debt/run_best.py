#!/usr/bin/env python3
"""hunt-margin-debt v13 BEST RULES — see BEST-RULES-SPEC.md (frozen pre-run).
Signal: FINRA margin debt drawdown from trailing 12m peak dd(m).
Dial: dd>=-4% -> w=1.0 ; -12%<dd<-4% -> w=0.5 ; dd<=-12% -> w=0.0.
Decision 20th of month m+1, fill next trading day open. Costs 0.10% of
traded notional + $0.01 on any sell rebalance. No floor. $100 pots."""
import json, os, sys, zipfile, re, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import load_stock, slice_road, period_stats, START
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_XLSX = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-margin-debt/data/margin-statistics.xlsx")
COST = 0.001; FEE = 0.01; END = "2026-11-20"
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB = {"LONG": 439.05, "DECADE": 257.83, "CONT": 206.26, "VAL": 148.52}

def parse_finra():
    z = zipfile.ZipFile(SRC_XLSX); ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for si in root.findall("m:si", ns):
            ss.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out = {}
    for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        vals = []
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            if v is None: vals.append(None); continue
            if c.get("t") == "s": vals.append(ss[int(v.text)])
            else:
                try: vals.append(float(v.text))
                except Exception: vals.append(v.text)
        if vals and isinstance(vals[0], str):
            m = re.match(r"(\d{4})-(\d{2})", vals[0])
            if m and len(vals) > 1 and isinstance(vals[1], (int, float)):
                out[f"{m.group(1)}-{m.group(2)}"] = vals[1]
    return dict(sorted(out.items()))

def monthly_weights(debt):
    """{(decision_month 'YYYY-MM'): target weight} using data through m."""
    months = sorted(debt); out = {}
    for i, m in enumerate(months):
        if i < 11: continue
        peak = max(debt[months[j]] for j in range(i-11, i+1))
        dd = debt[m] / peak - 1.0
        w = 1.0 if dd >= -0.04 else (0.5 if dd > -0.12 else 0.0)
        y, mo = int(m[:4]), int(m[5:7])
        dy, dmo = (y+1, 1) if mo == 12 else (y, mo+1)
        out[f"{dy:04d}-{dmo:02d}"] = (w, round(dd, 4))
    return out

def simulate(bars, weights):
    """weights: {decision_month: target_weight}. Rebalance at open of first
    bar after the decision trigger (first bar with day>=20 sets pending)."""
    cash = START; shares = 0.0; curve = []; costs = 0.0; orders = 0
    pending = None; triggered = set()
    for i, b in enumerate(bars):
        if pending is not None:
            w = pending; pending = None
            eq_open = cash + shares * b["o"]
            tgt_val = w * eq_open; cur_val = shares * b["o"]
            diff = tgt_val - cur_val
            if abs(diff) > 1e-9:
                cst = abs(diff) * COST + (FEE if diff < 0 else 0.0)
                costs += cst; orders += 1
                cash -= diff + cst
                shares = (cur_val + diff) / b["o"]
        dm = b["d"][:7]
        if dm in weights and dm not in triggered and int(b["d"][8:10]) >= 20:
            triggered.add(dm); pending = weights[dm]
        val = cash + shares * b["c"]
        curve.append([b["d"], round(val, 4)])
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    return {"final": round(curve[-1][1], 2) if curve else START,
            "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "curve": curve}

def hold_curve(bars):
    if len(bars) < 2: return None
    sh = START / bars[0]["o"]
    return [[b["d"], round(sh*b["c"], 4)] for b in bars]

def main():
    debt = parse_finra(); mw = monthly_weights(debt)
    spy = load_stock("SPY")
    res = {"family": "hunt-margin-debt", "program": "v13-best-rules",
           "n_months": len(debt), "first_month": min(debt), "last_month": max(debt),
           "roads": {}, "dial_months_LONG": {}}
    beats_champ = []
    for road, s0 in ROADS.items():
        rb = slice_road(spy, s0, END)
        wts = {dm: w for dm, (w, dd) in mw.items() if dm >= s0[:7]}
        r = simulate(rb, wts)
        hc = hold_curve(rb)
        res["roads"][road] = {"best_rules": r, "spy_hold_final": round(hc[-1][1], 2),
                              "spy_hold_curve": hc,
                              "published_v12_final": PUB[road], "champion_VM": CHAMP[road],
                              "spy_reference": SPYREF[road],
                              "period_stats_monthly": period_stats(r["curve"])}
        if r["final"] > CHAMP[road]: beats_champ.append(road)
        print(road, "best", r["final"], "dd", r["max_dd"], "orders", r["orders"],
              "hold", round(hc[-1][1], 2), flush=True)
    # dial composition on LONG
    lw = {dm: w for dm, (w, dd) in mw.items() if dm >= "2010-01"}
    res["dial_months_LONG"] = {k: mw[k][0] for k in sorted(lw)}
    # placebos LONG: (a) circular shifts, (b) random permutations
    rb = slice_road(spy, ROADS["LONG"], END)
    keys = sorted(lw); vals = [lw[k] for k in keys]
    real = res["roads"]["LONG"]["best_rules"]["final"]
    for kind in ("shift", "random_timing"):
        beaten = 0; twins = []
        for s in range(1, 21):
            rng = random.Random(1300 + s if kind == "shift" else 7300 + s)
            if kind == "shift":
                off = rng.randrange(6, len(vals)-6); vv = vals[off:] + vals[:off]
            else:
                vv = vals[:]; rng.shuffle(vv)
            w2 = {keys[i]: vv[i] for i in range(len(keys))}
            rr = simulate(rb, w2); twins.append(rr["final"])
            beaten += 1 if real > rr["final"] else 0
        res[f"placebo_LONG_{kind}"] = {"beaten_of_20": beaten, "twin_finals": twins,
                                       "twin_median": round(statistics.median(twins), 2)}
        print("placebo", kind, "beaten", beaten, "/20 median twin", round(statistics.median(twins), 2), flush=True)
    # confirmation ONLY if a road beat champion (frozen bar in spec)
    res["champion_beats"] = beats_champ
    if beats_champ:
        conf = {}
        for s0 in ("2016-01-01", "2019-01-01", "2022-01-01", "2024-01-01",
                   "2010-01-04", "2018-01-01"):
            rb = slice_road(spy, s0, END)
            wts = {dm: w for dm, (w, dd) in mw.items() if dm >= s0[:7]}
            r = simulate(rb, wts); hc = hold_curve(rb)
            conf[s0] = {"final": r["final"], "spy_hold": round(hc[-1][1], 2),
                        "max_dd": r["max_dd"], "beats_spy": r["final"] > hc[-1][1]}
        # second half-window
        rb = slice_road(spy, "2018-01-01", END)
        res["confirmation"] = conf
        folds = [conf[k]["beats_spy"] for k in ("2016-01-01", "2019-01-01", "2022-01-01", "2024-01-01")]
        halves = [conf["2010-01-04"]["beats_spy"] if False else None]
        h1 = None
        rb1 = slice_road(spy, "2010-01-04", "2017-12-29")
        w1 = {dm: w for dm, (w, dd) in mw.items() if dm >= "2010-01"}
        r1 = simulate(rb1, w1); hc1 = hold_curve(rb1)
        res["confirmation"]["half1_2010_2017"] = {"final": r1["final"], "spy_hold": round(hc1[-1][1], 2), "beats_spy": r1["final"] > hc1[-1][1]}
        res["confirmation"]["half2_2018_2026"] = conf["2018-01-01"]
        res["confirmation"]["PASS"] = (sum(folds) >= 3 and res["confirmation"]["half1_2010_2017"]["beats_spy"] and conf["2018-01-01"]["beats_spy"])
        print("confirmation PASS:", res["confirmation"]["PASS"], flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
