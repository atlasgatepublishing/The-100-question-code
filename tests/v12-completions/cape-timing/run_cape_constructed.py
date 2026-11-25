#!/usr/bin/env python3
"""CAPE Timing CONSTRUCTED form (v12). Implements CONSTRUCTION-SPEC.md
exactly: monthly checks (last trading day of month, decide at close,
execute next open), signal = Shiller CAPE dated that month from the LIVE
shillerdata ie_data.xls; CAPE <= 25 -> 100% SPY next month, CAPE > 25 ->
100% cash. Costs 0.10%/side + $0.01 sell fee (program standard). Cash 0%.
No floor. Placebos: circular shifts of the window's monthly target series
(20 seeds), preserving invested-month fraction. Simulation only.
The CONSTRUCTED label applies to every number: this is the genre's
most-documented convention (the CAPE 25 line), NOT a Shiller system."""
import json, os, time, random
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
XLS = os.path.join(HERE, "data", "ie_data_live_shillerdata.xls")
START = 100.0
LINE = 25.0
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_bars():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_cape():
    wb = xlrd.open_workbook(XLS); sh = wb.sheet_by_name("Data")
    out = {}
    for r in range(8, sh.nrows):
        d = sh.cell_value(r, 0); cape = sh.cell_value(r, 12)
        if isinstance(d, (int, float)) and d > 0 and isinstance(cape, (int, float)):
            y = int(d); m = int(round((d - y) * 100))
            out[f"{y}-{m:02d}"] = float(cape)
    return out


def month_end_checks(bars):
    """Last trading day of each month -> (date, month)."""
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = b["d"]
    return sorted((d, m) for m, d in seen.items())


def run(bars, by_date, checks, cape, start, end, shift=0, seed=None):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    # checks relevant: entry check (last on/before start) + checks in window
    rel = [(d, m) for d, m in checks if d < days[0]] [-1:] + \
          [(d, m) for d, m in checks if days[0] <= d <= end]
    targets = []
    for d, m in rel:
        v = cape.get(m)
        targets.append("SPY" if (v is not None and v <= LINE) else "CASH")
    if shift:
        rng = random.Random(seed)
        k = rng.randrange(1, len(targets)) if len(targets) > 1 else 0
        targets = targets[k:] + targets[:k]
    tmap = {d: t for (d, m), t in zip(rel, targets)}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = None
    days_invested = 0
    # entry: target of entry check executed at first open
    if rel and rel[0][0] < days[0]:
        pending = tmap[rel[0][0]]
    for d in days:
        bar = by_date[d]
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                bv = cash / 1.001; c = bv * 0.001
                shares = bv / bar["o"]; cash -= bv + c; costs += c
                trades.append([d, "BUY", round(bar["o"], 4), round(bv, 2), round(c, 2)])
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]; c = val * 0.001 + 0.01
                cash += val - c; costs += c; shares = 0.0
                trades.append([d, "SELL", round(bar["o"], 4), round(val, 2), round(c, 2)])
            pending = None
        if d in tmap and d >= days[0]:
            cur = "SPY" if shares > 0 else "CASH"
            if tmap[d] != cur:
                pending = tmap[d]
        if shares > 0:
            days_invested += 1
        curve.append([d, round(cash + shares * bar["c"], 4)])
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; c = val * 0.001 + 0.01
        cash += val - c; costs += c; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(c, 2)])
        curve[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "checks": len(rel), "checks_invested": targets.count("SPY"),
            "invested_pct": round(100.0 * days_invested / len(days), 1),
            "equity_curve": curve}


def spy_hold(bars, by_date, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    o = by_date[days[0]]["o"]; sh = (START / 1.001) / o
    val = sh * by_date[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)


def main():
    bars = load_bars(); by_date = {b["d"]: b for b in bars}
    cape = load_cape(); checks = month_end_checks(bars)
    print(f"bars {bars[0]['d']}->{bars[-1]['d']} ({len(bars)}); CAPE months {len(cape)}")
    out = {"family": "cape-timing",
           "form": "CONSTRUCTED v12: monthly, CAPE<=25 -> SPY else cash, live shillerdata CAPE, program costs, no floor",
           "constructed_label": "Genre convention (CAPE 25 line), NOT a Shiller/Campbell system",
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = run(bars, by_date, checks, cape, s, e)
        spy = spy_hold(bars, by_date, s, e)
        placebos, beaten = [], None
        if r["checks_invested"] in (0, r["checks"]):
            pnote = "degenerate: signal never changes state on this road; shifted twins are identical"
        else:
            for seed in range(1, 21):
                pr = run(bars, by_date, checks, cape, s, e, shift=1, seed=seed)
                placebos.append(pr["final"])
            beaten = sum(1 for p in placebos if r["final"] > p)
            pnote = f"real beats {beaten}/20 shifted-signal twins"
        out["roads"][name] = {**r, "spy_same_plumbing": spy,
                              "spy_program_ref": SPYREF[name], "champion_vm": CHAMP[name],
                              "placebo_finals": placebos, "placebos_beaten": beaten,
                              "placebo_note": pnote}
        print(f"{name}: final ${r['final']} maxDD {r['max_dd_pct']}% costs ${r['costs']} "
              f"orders {r['orders']} invested {r['invested_pct']}% checks SPY {r['checks_invested']}/{r['checks']} "
              f"SPY ${spy} champ ${CHAMP[name]} placebos beaten {beaten}")
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = "2026-11-20" if y == 2026 else f"{y}-12-31"
        folds[str(y)] = run(bars, by_date, checks, cape, s, e)["final"]
    out["year_folds"] = folds
    print("folds:", folds)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
