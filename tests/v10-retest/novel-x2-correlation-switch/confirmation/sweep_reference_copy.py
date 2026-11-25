#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-2 CORRELATION-REGIME SWITCH (invented rule X2, timer).

DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs, v9 protections.
Cadence for a TIMER = signal-evaluation frequency (SPEC uniform definition):
the correlation statistic C (mean pairwise Pearson correlation of daily
returns over the trailing 60 trading days, 61 closes ending at the prior
close, pond names with a complete window) is recomputed ONLY on cadence
dates, and compared to the median of all PRIOR readings taken at that same
cadence (expanding window, point-in-time). C <= median -> hold equal-weight
pond; C > median -> hold SPY. Readings history at each cadence extends back
to the earliest date the 61-close rule allows (2010, the same data extension
documented in driver.py) so the DECADE run's prior-median is the full one.
Between cadence dates nothing is evaluated and nothing trades; the pond is
never rebalanced except on a regime flip (the frozen rule).

Cadence dates (from the SPY trading calendar):
  daily      = every trading day
  weekly     = first trading day of each ISO week
  biweekly   = first trading day of every second ISO week, anchored on the
               first trading week of the calendar (week of 2010-01-04)
  monthly    = first trading day of each month (the native cadence; this
               cell must reproduce the area DECADE run, $446.12)
  quarterly  = first trading day of each calendar quarter
  semiannual = first trading day of each half-year (Jan / Jul)
  annual     = first trading day of each year

Placebos (per cell, the original's own design, extended per cadence):
same initial asset as the ranked run, flip count matched to the ranked
run's episode-1 flip count, flip dates sampled uniformly from the
window's trading days after the first decision date, seeds 1..20, run
through the same v9 wrapper. All 20 finals saved per cell.
"""
import importlib.util, json, math, os, random, statistics
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x2", os.path.join(HERE, "integrity", "novel-x2-correlation-switch.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    import time
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

POND = M.POND
BARS = {t: pxfull(t) for t in POND + ["SPY"]}
CAL = [b["d"] for b in BARS["SPY"]]
CIDX = {d: i for i, d in enumerate(CAL)}
CLOSES = {t: {b["d"]: b["c"] for b in bl} for t, bl in BARS.items()}
BOOK = M.Book(BARS, CAL)

# aligned close matrix for the statistic (NaN = no bar that day)
ARR = np.full((len(POND), len(CAL)), np.nan)
for ti, t in enumerate(POND):
    cm = CLOSES[t]
    for d, v in cm.items():
        if d in CIDX:
            ARR[ti, CIDX[d]] = v

def stat_C(i):
    """C on CAL[i], using the 61 closes ending at the prior close
    (CAL[i-61:i]). Returns (C, complete_name_list) or (None, [])."""
    if i < 61:
        return None, []
    win = ARR[:, i - 61:i]                      # (names, 61 closes)
    ok = ~np.isnan(win).any(axis=1)
    names = [POND[k] for k in range(len(POND)) if ok[k]]
    if len(names) < 2:
        return None, names
    sub = win[ok]
    rets = sub[:, 1:] / sub[:, :-1] - 1.0       # (names, 60 returns)
    with np.errstate(invalid="ignore", divide="ignore"):
        cc = np.corrcoef(rets)
    iu = np.triu_indices(len(names), k=1)
    vals = cc[iu]
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None, names
    return float(vals.mean()), names

# ------------------------------------------------------------ cadence dates
def cadence_dates(kind):
    out = []
    if kind == "daily":
        return list(CAL)
    seen = set()
    weeks = []          # ordered unique ISO-week keys for biweekly anchor
    for d in CAL:
        y, m = int(d[:4]), int(d[5:7])
        if kind == "weekly" or kind == "biweekly":
            key = date.fromisoformat(d).isocalendar()[:2]
        elif kind == "monthly":
            key = (y, m)
        elif kind == "quarterly":
            key = (y, (m - 1) // 3)
        elif kind == "semiannual":
            key = (y, (m - 1) // 6)
        elif kind == "annual":
            key = (y,)
        if key not in seen:
            seen.add(key)
            if kind in ("weekly", "biweekly"):
                weeks.append((key, d))
            else:
                out.append(d)
    if kind == "weekly":
        return [d for _, d in weeks]
    if kind == "biweekly":
        return [d for j, (_, d) in enumerate(weeks) if j % 2 == 0]
    return out

def build_regime(kind):
    """Readings at this cadence over the full calendar; regime from the
    expanding median of prior readings at this cadence. Returns
    (regime{date: POND|SPY}, scoreable{date: [names]})."""
    regime, scoreable = {}, {}
    prior = []
    for d in cadence_dates(kind):
        if d < "2010-01-01":
            continue  # readings history starts 2010-01, exactly the data
            # extension in driver.py (its month gate) — earlier calendar
            # months exist in the price payloads but are NOT readings
        C, names = stat_C(CIDX[d])
        if C is None:
            continue
        scoreable[d] = names
        if prior:
            regime[d] = "POND" if C <= statistics.median(prior) else "SPY"
        prior.append(C)
    return regime, scoreable

# ------------------------------------------------------------ v9 wrapper
def pond_names_fn(scoreable):
    keys = sorted(scoreable)
    def f(d):
        elig = [x for x in keys if x <= d]
        return scoreable[max(elig)] if elig else []
    return f

def spy_net(start, end, cash=100.0):
    days = [d for d in CAL if start <= d <= end]
    by = {b["d"]: b for b in BARS["SPY"]}
    sh = (cash / 1.001) / by[days[0]]["o"]
    val = sh * by[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)

def spy_maxdd(start, end):
    days = [d for d in CAL if start <= d <= end]
    by = {b["d"]: b for b in BARS["SPY"]}
    peak, maxdd = -1.0, 0.0
    for d in days:
        v = by[d]["c"]; peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return round(maxdd * 100, 2)

def run_once(start, end, switches, cash, floor, names_fn):
    M.START_CASH = cash; M.FLOOR = floor
    r = M.run_pot(BOOK, start, end, switches, names_fn)
    M.START_CASH = 100.0; M.FLOOR = 85.0
    return r

def run_v9(start, end, switches_fn, names_fn):
    r1 = run_once(start, end, switches_fn(start, end), 100.0, 85.0, names_fn)
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"]) + timedelta(days=90)).isoformat()
        if elig <= end:
            r2 = run_once(elig, end, switches_fn(elig, end),
                          r1["final"], 0.85 * r1["final"], names_fn)
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85 * r1["final"], 2),
                       "second_halt": r2["halted"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]:
            curve[d] = v
    if len(eps) > 1:
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "flips": sum(e["flips"] for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": round(maxdd * 100, 2),
            "_r1flips": eps[0]["flips"], "_curve": curve}

# ------------------------------------------------------------ sweep
if __name__ == "__main__":
    START, END = "2016-11-21", "2026-11-20"
    YEARS = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
    SPY_FINAL = spy_net(START, END)
    SPY_DD = spy_maxdd(START, END)
    CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"]
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for kind in CADENCES:
        regime, scoreable = build_regime(kind)
        names_fn = pond_names_fn(scoreable)
        dec = [d for d in cadence_dates(kind)
               if START <= d <= END and d in regime]
        switches = {d: regime[d] for d in dec}
        r = run_v9(START, END, lambda s, e, sw=switches:
                   {d: t for d, t in sw.items() if s <= d <= e}, names_fn)
        r1flips = r.pop("_r1flips"); curve = r.pop("_curve")
        # placebos: original design, per cadence
        dec0 = dec[0]; init_asset = regime[dec0]
        days = [d for d in CAL if START <= d <= END]
        cand = [d for d in days if d > dec0]
        pfinals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            fdates = sorted(rng.sample(cand, r1flips)) if r1flips else []
            def pswitch(s2, e2, fdates=fdates, init_asset=init_asset, dec0=dec0):
                sw = {}
                if s2 <= dec0 <= e2:
                    sw[dec0] = init_asset
                cur = init_asset
                for fd in fdates:
                    cur = "SPY" if cur == "POND" else "POND"
                    if s2 <= fd <= e2:
                        sw[fd] = cur
                return sw
            pr = run_v9(START, END, pswitch, names_fn)
            pfinals.append(pr["final"])
        beaten = sum(1 for f in pfinals if f < r["final"])
        cagr = round(((r["final"] / 100.0) ** (1.0 / YEARS) - 1.0) * 100, 2)
        halts = [{"date": h} for h in r["halts"]]
        restarts = []
        if r["restart_info"]:
            ri = r["restart_info"]
            restarts.append({"halt_date": ri["halt_date"],
                             "restart_date": ri["eligibility"],
                             "restart_balance": ri["liquidation"],
                             "episode2_floor": ri["episode2_floor"],
                             "second_halt_date": ri["second_halt"]})
        cell = {"slug": "novel-x2-correlation-switch", "cadence": kind,
                "cadence_definition": "timer signal-evaluation frequency",
                "window": [START, END], "pot": 100,
                "final": r["final"], "cagr_pct": cagr,
                "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"],
                "flips": r["flips"], "decision_dates": len(dec),
                "halts": halts, "restarts": restarts,
                "restart": r["restart"], "second_halt": r["second_halt"],
                "placebo_beaten": beaten,
                "placebo_note": ("original placebo design extended per cadence: "
                                 "same initial asset, flip count matched to the "
                                 "ranked run's episode-1 flips (%d), random flip "
                                 "dates, seeds 1..20, same v9 wrapper" % r1flips),
                "placebo_finals": pfinals,
                "placebo_median": round(statistics.median(pfinals), 2),
                "spy_final": SPY_FINAL, "spy_max_dd_pct": SPY_DD,
                "equity_curve": [[d, round(v, 4)] for d, v in curve]}
        json.dump(cell, open(os.path.join(HERE, "cells", f"{kind}.json"), "w"),
                  indent=1)
        cells[kind] = {k: cell[k] for k in
                       ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                        "flips", "halts", "restart", "second_halt",
                        "placebo_beaten", "placebo_note")}
        cells[kind]["placebo_median"] = cell["placebo_median"]
        print(kind, "final", r["final"], "CAGR", cagr, "maxDD", r["max_dd_pct"],
              "costs", r["costs"], "orders", r["orders"], "flips", r["flips"],
              "decisions", len(dec), "halts", r["halts"],
              "placebo", beaten, "/20 median", cell["placebo_median"], flush=True)

    money = [k for k in CADENCES
             if cells[k]["final"] > SPY_FINAL and cells[k]["placebo_beaten"] >= 11]
    out = {"slug": "novel-x2-correlation-switch",
           "area": "correlation-regime timer (regime switcher, timer treatment) — "
                   "full road scored on final vs buy-hold SPY and drawdown vs SPY",
           "area_source": "SPEC W5: X2 = regime switcher (timer treatment: full "
                          "road + drawdown); CADENCE SWEEP: cadence for timers = "
                          "signal-evaluation frequency",
           "native_cadence": "monthly",
           "cadence": "monthly (native); sweep varies signal-evaluation frequency",
           "original_cadence_foreign": False,
           "original_cadence_note": "original test evaluated the regime monthly, "
                                    "the frozen spec's own cadence — not foreign",
           "native_change": "none in form for the area runs (monthly, readings "
                            "extended to 2010 on full-road data — a data "
                            "extension, not a rule change; see driver.py). The "
                            "sweep varies only the signal-evaluation frequency.",
           "integrity": {
               "status": "reproduced",
               "original_finals": {"CONT": 354.60, "VAL": 217.63},
               "reproduced_finals": {"CONT": 354.60, "VAL": 217.63},
               "placebo_beaten_original": {"CONT": "18/20", "VAL": "18/20"},
               "note": "batch worker's saved gate in integrity/ "
                       "(novel-x2-correlation-switch-results.json): SPY nets "
                       "$313.62 / $187.77 reproduced exactly; CONT $354.60 and "
                       "VAL $217.63 reproduced, placebos 18/20 on both windows."},
           "decade_spy_final": SPY_FINAL,
           "decade_spy_max_dd_pct": SPY_DD,
           "area_runs": {
               "LONG": {"final": 1120.65, "spy": 822.94, "max_dd_pct": 33.63,
                        "spy_max_dd_pct": 33.72},
               "DECADE": {"final": 446.12, "spy": 367.80, "max_dd_pct": 33.71,
                          "spy_max_dd_pct": 33.72},
               "CONT": {"final": 358.94, "spy": 313.62, "max_dd_pct": 33.75,
                        "placebo_beaten": 19,
                        "note": "~$4 above the original $354.60 because the "
                                "readings' prior-median history now extends to "
                                "2010 (documented data extension in driver.py)"},
               "VAL": {"final": 219.77, "spy": 187.77, "max_dd_pct": 16.04,
                       "placebo_beaten": 19,
                       "note": "~$2 above the original $217.63, same data "
                               "extension"}},
           "cells": cells,
           "money_cadences": money,
           "candidate_ceiling": "invented rule — even a confirmed sweep win is "
                                "candidate-grade; promotion is the forward "
                                "paper trial's alone",
           "verdict_area": "PROVISIONAL — pending cross-year confirmation "
                           "(see RESULTS.md)",
           "verdict_change": "see RESULTS.md"}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("SPY decade", SPY_FINAL, "SPY maxDD", SPY_DD, "money:", money)
    print("DONE")
