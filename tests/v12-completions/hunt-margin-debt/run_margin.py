#!/usr/bin/env python3
"""Margin-Debt Trend Timer (hunt-margin-debt, v12) — SPEC-FROZEN.
Signal: month-end FINRA margin debt D(m) vs trailing 12-month MA.
Decision on the 20th calendar day of month m+1 (after FINRA's
third-week publication lag — month-end timing would be look-ahead).
D(m) >= MA12(m) -> hold SPY for the coming month; below -> cash.
Fill at next trading day's open after the decision day. Program costs
0.10%/side + $0.01 sell fee; native no floor; house = v9 floor pair.
Coins: same monthly state as an EXTERNAL leverage-regime gate on BTC
(labelled external per spec), 0.60%/side. Placebos: 20-seed circular
shifts of the monthly state series."""
import json, os, sys, zipfile, re, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

def parse_finra():
    p = os.path.join(HERE, "data", "margin-statistics.xlsx")
    z = zipfile.ZipFile(p)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for si in root.findall("m:si", ns):
            ss.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows = []
    for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        vals = []
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            if v is None: vals.append(None); continue
            if c.get("t") == "s": vals.append(ss[int(v.text)])
            else:
                try: vals.append(float(v.text))
                except Exception: vals.append(v.text)
        rows.append(vals)
    out = {}
    for r in rows:
        if not r or not isinstance(r[0], str): continue
        m = re.match(r"(\d{4})-(\d{2})", r[0])
        if m and len(r) > 1 and isinstance(r[1], (int, float)):
            out[f"{m.group(1)}-{m.group(2)}"] = r[1]
    return dict(sorted(out.items()))

def monthly_states(debt):
    """Returns list of (decision_month 'YYYY-MM' = m+1, in_state) using
    data through month m. State applies from decision day of m+1."""
    months = sorted(debt)
    out = []
    for i, m in enumerate(months):
        if i < 11: continue
        ma = sum(debt[months[j]] for j in range(i-11, i+1)) / 12
        y, mo = int(m[:4]), int(m[5:7])
        dy, dmo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        out.append((f"{dy:04d}-{dmo:02d}", debt[m] >= ma))
    return out

def simulate_monthly(bars, states, cost, fee, house=False):
    """states: list of (decision_month, in_state). Decision day = 20th of
    decision month; fill next trading day open. Daily equity curve."""
    dec = {}
    for dm, s in states: dec[dm] = s
    eq = START; shares = 0.0; inpos = False; curve = []; costs = 0.0; orders = 0
    anchor = START; halts = 0; halt_until = None; ended = False
    pending = None
    cur_state = False
    for i, b in enumerate(bars):
        if pending is not None:
            tgt = pending; pending = None
            if tgt and not inpos and not ended:
                cst = eq * cost; costs += cst; shares = (eq - cst) / b["o"]; eq -= cst; inpos = True; orders += 1
            elif not tgt and inpos:
                gross = shares * b["o"]; cst = gross * cost + fee; costs += cst
                eq = gross - cst; shares = 0.0; inpos = False; orders += 1
        # decision: on first bar with day>=20 of a decision month, state set at that close -> pending for next open
        dm = b["d"][:7]
        if dm in dec and int(b["d"][8:10]) >= 20 and cur_state != dec[dm]:
            # only trigger once: check previous bar month/day
            prev = bars[i-1]["d"] if i > 0 else "0000"
            if not (prev[:7] == dm and int(prev[8:10]) >= 20):
                cur_state = dec[dm]; pending = cur_state
        val = shares * b["c"] if inpos else eq
        if house and inpos and not ended and val <= 0.85 * anchor:
            halts += 1; pending = False
            if halts >= 2: ended = True
            else: halt_until = b["d"]; anchor = None
        if halt_until is not None and not ended:
            # 90 calendar days later, new episode anchor
            from datetime import date, timedelta
            y, mo, dd = int(halt_until[:4]), int(halt_until[5:7]), int(halt_until[8:10])
            if b["d"] >= str(date(y, mo, dd) + timedelta(days=90)):
                halt_until = None; anchor = val
        curve.append([b["d"], round(val, 4)])
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(curve[-1][1], 2) if curve else START, "max_dd": round(maxdd, 4),
            "costs": round(costs, 2), "orders": orders, "halts": halts, "curve": curve}

def main():
    debt = parse_finra()
    states = monthly_states(debt)
    res = {"family": "hunt-margin-debt", "n_months": len(debt),
           "first_month": min(debt), "last_month": max(debt), "roads": {}}
    spy = load_stock("SPY")
    for road, s0 in ROADS.items():
        rb = slice_road(spy, s0, END)
        st = [(dm, s) for dm, s in states if dm >= s0[:7]]
        rn = simulate_monthly(rb, st, STK_COST, STK_FEE)
        rh = simulate_monthly(rb, st, STK_COST, STK_FEE, house=True)
        res["roads"][road] = {"native": rn, "house": rh, "hold": hold_final(rb),
                              "period_stats_monthly": period_stats(rn["curve"])}
        print(road, "native", rn["final"], "house", rh["final"], flush=True)
    # placebos LONG: shift states by random months
    import random
    rb = slice_road(spy, ROADS["LONG"], END)
    st_long = [(dm, s) for dm, s in states if dm >= "2010-01"]
    beaten = 0; twins = []
    for s in range(1, 21):
        rng = random.Random(900+s); off = rng.randrange(6, len(st_long)-6)
        vals = [x[1] for x in st_long]
        sh = vals[off:] + vals[:off]
        st2 = [(st_long[i][0], sh[i]) for i in range(len(st_long))]
        rr = simulate_monthly(rb, st2, STK_COST, STK_FEE)
        twins.append(rr["final"]); beaten += 1 if res["roads"]["LONG"]["native"]["final"] > rr["final"] else 0
    res["placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins}
    # BTC external gate
    btc = load_coin("BTC")
    st_btc = [(dm, s) for dm, s in states]
    bn = simulate_monthly(btc, st_btc, CRY_COST, 0.0)
    bh = simulate_monthly(btc, st_btc, CRY_COST, 0.0, house=True)
    res["BTC_external_gate"] = {"native_FULL": bn, "house_FULL": bh, "hold_FULL": hold_final(btc),
                                "period_stats_monthly": period_stats(bn["curve"])}
    print("BTC gate native", bn["final"], "hold", hold_final(btc), flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
