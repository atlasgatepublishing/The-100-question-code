#!/usr/bin/env python3
"""V10 CONFIRMATION RUN — N-2 CORRELATION-REGIME SWITCH (X2), QUARTERLY cadence.

Terry's CONFIRMATION RULE (SPEC.md): the sweep crowned a NEW best tempo —
quarterly $455.02 (placebo 20/20) on the DECADE, edging native monthly
$446.12 (19/20). A new money cadence is not crowned until it is re-run on
the other roads. This script re-runs X2 at QUARTERLY signal-evaluation
frequency ONLY, one clean shot, no tuning, on:
  LONG 2010-01-04 -> 2026-11-20 (SPY reference $822.94)
  CONT 2019-01-02 -> 2026-11-20 (SPY reference $313.62)
  VAL  2023-01-03 -> 2026-11-20 (SPY reference $187.77)
plus fresh yearly folds (each calendar year standalone, fresh $100) and
20-seed flip-count-matched placebos per road.

Plumbing is copied from the parent folder's sweep.py (which reproduced
the area DECADE monthly run to the cent): identical statistic (mean
pairwise Pearson correlation of daily returns over trailing 60 trading
days, 61 closes ending at the prior close, complete-window names only),
identical expanding-median-of-prior-readings regime rule AT THIS CADENCE,
identical v9 wrapper (plain -15% floor, 90-day sit-out, episode-2 floor
-15% from restart balance, second halt ends the run), program costs via
the original engine (0.10%/side + $0.01/share sell charge in engine form).

READINGS GATE (carried exactly from sweep.py): readings history begins
2010-01 — cadence dates before 2010-01-01 are NOT readings, even though
the price payloads contain 2008-2009 bars. (The sweep's first pass
included 2009 readings and printed $456.23 for monthly; restoring this
gate reproduced the area $446.12 to the cent. Do not reintroduce it.)
"""
import importlib.util, json, os, random, statistics
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "x2", os.path.join(PARENT, "integrity", "novel-x2-correlation-switch.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def pxfull(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(PARENT, "pxfull_GOOGL.json")))
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

ARR = np.full((len(POND), len(CAL)), np.nan)
for ti, t in enumerate(POND):
    cm = CLOSES[t]
    for d, v in cm.items():
        if d in CIDX:
            ARR[ti, CIDX[d]] = v

def stat_C(i):
    if i < 61:
        return None, []
    win = ARR[:, i - 61:i]
    ok = ~np.isnan(win).any(axis=1)
    names = [POND[k] for k in range(len(POND)) if ok[k]]
    if len(names) < 2:
        return None, names
    sub = win[ok]
    rets = sub[:, 1:] / sub[:, :-1] - 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        cc = np.corrcoef(rets)
    iu = np.triu_indices(len(names), k=1)
    vals = cc[iu]
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None, names
    return float(vals.mean()), names

def cadence_dates(kind):
    out = []
    if kind == "daily":
        return list(CAL)
    seen = set()
    weeks = []
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
    regime, scoreable = {}, {}
    prior = []
    for d in cadence_dates(kind):
        if d < "2010-01-01":
            continue  # readings history starts 2010-01, exactly as sweep.py
        C, names = stat_C(CIDX[d])
        if C is None:
            continue
        scoreable[d] = names
        if prior:
            regime[d] = "POND" if C <= statistics.median(prior) else "SPY"
        prior.append(C)
    return regime, scoreable

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

def spy_curve_maxdd(start, end):
    """SPY buy-hold equity-curve drawdown on the same net basis is not
    used; spy_maxdd (close series) is the sweep/area convention."""
    return spy_maxdd(start, end)

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
    halts = [{"date": e["halted"]} for e in eps if e["halted"]]
    restarts = []
    if restart:
        restarts.append({"halt_date": restart["halt_date"],
                         "restart_date": restart["eligibility"],
                         "restart_balance": restart["liquidation"],
                         "episode2_floor": restart["episode2_floor"],
                         "second_halt_date": restart["second_halt"]})
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "flips": sum(e["flips"] for e in eps),
            "halts": halts,
            "restarts": restarts,
            "restart": restart is not None,
            "second_halt": bool(restart and restart["second_halt"]),
            "max_dd_pct": round(maxdd * 100, 2),
            "_r1flips": eps[0]["flips"], "_curve": curve}

def cagr(final, start, end):
    years = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    if years <= 0:
        return None
    return round(((final / 100.0) ** (1.0 / years) - 1.0) * 100, 2)

# ------------------------------------------------------------ confirmation
if __name__ == "__main__":
    KIND = "quarterly"
    regime, scoreable = build_regime(KIND)
    names_fn = pond_names_fn(scoreable)
    qdates = cadence_dates(KIND)
    print("quarterly regime dates:", len(regime),
          "first:", min(regime), "last:", max(regime), flush=True)

    def switches_for(s, e):
        dec = [d for d in qdates if s <= d <= e and d in regime]
        return {d: regime[d] for d in dec}, dec

    def run_window(start, end, do_placebos=True):
        switches, dec = switches_for(start, end)
        r = run_v9(start, end, lambda s, e, sw=switches:
                   {d: t for d, t in sw.items() if s <= d <= e}, names_fn)
        r1flips = r.pop("_r1flips"); curve = r.pop("_curve")
        pfinals = []
        beaten = None
        if do_placebos:
            dec0 = dec[0]; init_asset = regime[dec0]
            days = [d for d in CAL if start <= d <= end]
            cand = [d for d in days if d > dec0]
            for seed in range(1, 21):
                rng = random.Random(seed)
                fdates = sorted(rng.sample(cand, r1flips)) if r1flips else []
                def pswitch(s2, e2, fdates=fdates, init_asset=init_asset,
                            dec0=dec0):
                    sw = {}
                    if s2 <= dec0 <= e2:
                        sw[dec0] = init_asset
                    cur = init_asset
                    for fd in fdates:
                        cur = "SPY" if cur == "POND" else "POND"
                        if s2 <= fd <= e2:
                            sw[fd] = cur
                    return sw
                pr = run_v9(start, end, pswitch, names_fn)
                pfinals.append(pr["final"])
            beaten = sum(1 for f in pfinals if f < r["final"])
        out = {"slug": "novel-x2-correlation-switch", "cadence": KIND,
               "cadence_definition": "timer signal-evaluation frequency",
               "window": [start, end], "pot": 100,
               "final": r["final"], "cagr_pct": cagr(r["final"], start, end),
               "max_dd_pct": r["max_dd_pct"],
               "costs": r["costs"], "orders": r["orders"],
               "flips": r["flips"], "decision_dates": len(dec),
               "decision_date_list": dec,
               "halts": r["halts"], "restarts": r["restarts"],
               "restart": r["restart"], "second_halt": r["second_halt"],
               "placebo_beaten": beaten,
               "placebo_note": ("sweep design: same initial asset, flip count "
                                "matched to the ranked run's episode-1 flips "
                                "(%d), random flip dates, seeds 1..20, same "
                                "v9 wrapper" % r1flips),
               "placebo_finals": pfinals,
               "placebo_median": (round(statistics.median(pfinals), 2)
                                  if pfinals else None),
               "spy_final": spy_net(start, end),
               "spy_max_dd_pct": spy_maxdd(start, end),
               "equity_curve": [[d, round(v, 4)] for d, v in curve]}
        return out

    ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"),
             "VAL": ("2023-01-03", "2026-11-20")}
    roads = {}
    for name, (s, e) in ROADS.items():
        cell = run_window(s, e, do_placebos=True)
        roads[name] = cell
        json.dump(cell, open(os.path.join(HERE, f"{name.lower()}-quarterly.json"), "w"), indent=1)
        print(name, "final", cell["final"], "SPY", cell["spy_final"],
              "CAGR", cell["cagr_pct"], "maxDD", cell["max_dd_pct"],
              "SPY DD", cell["spy_max_dd_pct"], "costs", cell["costs"],
              "orders", cell["orders"], "flips", cell["flips"],
              "decisions", cell["decision_dates"], "halts", cell["halts"],
              "placebo", cell["placebo_beaten"], "/20 median",
              cell["placebo_median"], flush=True)

    # ---- yearly folds: each calendar year standalone, fresh $100.
    # Full range 2010-2026 run because the quarterly readings history
    # (gated to 2010-01, 61-close rule) honestly supports regime dates
    # from 2010-04-01 onward (the 2010-01-04 reading has no prior
    # reading, so it carries no regime); the 2010 fold's first decision
    # date is printed so its partial-year character is on the record.
    folds = {}
    for y in range(2010, 2027):
        days = [d for d in CAL if d[:4] == str(y)]
        if not days:
            continue
        s, e = days[0], days[-1]
        cell = run_window(s, e, do_placebos=False)
        fold = {"year": y, "window": [s, e], "final": cell["final"],
                "spy_final": cell["spy_final"],
                "max_dd_pct": cell["max_dd_pct"],
                "spy_max_dd_pct": cell["spy_max_dd_pct"],
                "costs": cell["costs"], "orders": cell["orders"],
                "flips": cell["flips"],
                "decision_dates": cell["decision_dates"],
                "decision_date_list": cell["decision_date_list"],
                "halts": cell["halts"], "restarts": cell["restarts"],
                "restart": cell["restart"], "second_halt": cell["second_halt"],
                "beat_spy": cell["final"] > cell["spy_final"],
                "beat_100": cell["final"] > 100.0,
                "equity_curve": cell["equity_curve"]}
        folds[str(y)] = fold
        print("FOLD", y, "final", fold["final"], "SPY", fold["spy_final"],
              "beatSPY", fold["beat_spy"], "beat100", fold["beat_100"],
              "maxDD", fold["max_dd_pct"], "halts", fold["halts"],
              "first_decision", (cell["decision_date_list"][0]
                                 if cell["decision_date_list"] else None),
              flush=True)
    json.dump({"slug": "novel-x2-correlation-switch", "cadence": KIND,
               "note": ("standalone calendar-year folds, fresh $100 each; "
                        "regime readings use the full point-in-time prior "
                        "history at quarterly cadence (gated to 2010-01); "
                        "first quarterly reading 2010-01-04 carries no "
                        "regime (no prior reading), so the first quarterly "
                        "regime date is 2010-04-01 and the 2010 fold sits "
                        "in cash until then. 2015 and 2016 folds held SPY "
                        "at every quarterly check (0 flips), so their "
                        "finals equal the SPY net by construction"),
               "folds": folds},
              open(os.path.join(HERE, "folds.json"), "w"), indent=1)
    print("DONE")
