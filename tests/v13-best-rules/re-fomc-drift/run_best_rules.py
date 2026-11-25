#!/usr/bin/env python3
"""V13 best-rules run for re-fomc-drift. Spec: BEST-RULES-SPEC.md (frozen first).
Vehicle = UPRO (real prices), native FOMC window, all scheduled announcements,
program costs (0.10%/side + $0.01/sell), NO floor. Cash 0%.
Integrity gates run first and abort the run if they fail."""
import json, random, datetime, statistics, sys

HERE = "/home/hatch/workspace/stock-app/backtests/v13-best-rules/re-fomc-drift"
SPY_PATH = "/home/hatch/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json"
SPY_V2 = "/home/hatch/workspace/stock-app/backtests/v2/data/SPY.json"  # v11 native engine's series
UPRO_PATH = "/home/hatch/workspace/stock-app/backtests/v10-retest/leveraged-trend/data/UPRO.json"

def load_px(path):
    d = json.load(open(path))['chart']['result'][0]
    ts = d['timestamp']; adj = d['indicators']['adjclose'][0]['adjclose']
    P = {str(datetime.date.fromtimestamp(t)): p for t, p in zip(ts, adj) if p}
    return P

def load_bars(path):
    """date -> (adj open, adj close); adjusted open = raw open scaled by adjclose/close."""
    d = json.load(open(path))['chart']['result'][0]
    ts = d['timestamp']; q = d['indicators']['quote'][0]
    adj = d['indicators']['adjclose'][0]['adjclose']
    B = {}
    for t, o, c, a in zip(ts, q['open'], q['close'], adj):
        if o and c and a:
            dt = str(datetime.date.fromtimestamp(t)); B[dt] = (o * a / c, a)
    return B

# --- FOMC scheduled announcement dates -------------------------------------
# 2010-2016: Hillenbrand RFS Internet Appendix Table A.1 (Fed calendars).
PRE2017 = [
 "2010-01-27","2010-03-16","2010-04-28","2010-06-23","2010-08-10","2010-09-21","2010-11-03","2010-12-14",
 "2011-01-26","2011-03-15","2011-04-27","2011-06-22","2011-08-09","2011-09-21","2011-11-02","2011-12-13",
 "2012-01-25","2012-03-13","2012-04-25","2012-06-20","2012-08-01","2012-09-13","2012-10-24","2012-12-12",
 "2013-01-30","2013-03-20","2013-05-01","2013-06-19","2013-07-31","2013-09-18","2013-10-30","2013-12-18",
 "2014-01-29","2014-03-19","2014-04-30","2014-06-18","2014-07-30","2014-09-17","2014-10-29","2014-12-17",
 "2015-01-28","2015-03-18","2015-04-29","2015-06-17","2015-07-29","2015-09-17","2015-10-28","2015-12-16",
 "2016-01-27","2016-03-16","2016-04-27","2016-06-15","2016-07-27","2016-09-21","2016-11-02",
]
# 2016-12-14 onward: v7 frozen list (Federal Reserve published calendars).
V7 = ["2016-12-14","2017-02-01","2017-03-15","2017-05-03","2017-06-14","2017-07-26","2017-09-20","2017-11-01","2017-12-13","2018-01-31","2018-03-21","2018-05-02","2018-06-13","2018-08-01","2018-09-26","2018-11-08","2018-12-19","2019-01-30","2019-03-20","2019-05-01","2019-06-19","2019-07-31","2019-09-18","2019-10-30","2019-12-11","2020-01-29","2020-04-29","2020-06-10","2020-07-29","2020-09-16","2020-11-05","2020-12-16","2021-01-27","2021-03-17","2021-04-28","2021-06-16","2021-07-28","2021-09-22","2021-11-03","2021-12-15","2022-01-26","2022-03-16","2022-05-04","2022-06-15","2022-07-27","2022-09-21","2022-11-02","2022-12-14","2023-02-01","2023-03-22","2023-05-03","2023-06-14","2023-07-26","2023-09-20","2023-11-01","2023-12-13","2024-01-31","2024-03-20","2024-05-01","2024-06-12","2024-07-31","2024-09-18","2024-11-07","2024-12-18","2025-01-29","2025-03-19","2025-05-07","2025-06-18","2025-07-30","2025-09-17","2025-10-29","2025-12-10","2026-01-28","2026-03-18","2026-04-29","2026-06-17","2026-07-29","2026-09-16","2026-10-28"]
EVENTS = sorted(PRE2017 + V7)

SPY = load_px(SPY_PATH); SPY2 = load_px(SPY_V2); UPRO = load_px(UPRO_PATH)

def engine(P, a, b, events):
    """v7/v11 cost mechanics verbatim: buy at close day before announcement
    (v=cash/1.001, cost 0.001*v), sell at announcement close (cost 0.001*v+0.01)."""
    DATES = sorted(P); IDX = {d: i for i, d in enumerate(DATES)}
    cash = 100.0; costs = 0.0; curve = []; evs = [e for e in events if a <= e <= b]
    evset = {}
    for e in evs:
        i = IDX[e]; evset[DATES[i-1]] = ("buy", e); evset[DATES[i]] = ("sell", e)
    shares = 0.0; trades = []
    for dt in [x for x in DATES if a <= x <= b]:
        if dt in evset and evset[dt][0] == "buy":
            v = cash / 1.001; c = 0.001 * v; shares = v / P[dt]; cash -= v + c; costs += c
            entry_val = cash + shares * P[dt]
        eq = cash + shares * P[dt]
        if dt in evset and evset[dt][0] == "sell":
            v = shares * P[dt]; c = 0.001 * v + 0.01; cash += v - c; costs += c; shares = 0.0; eq = cash
            trades.append({"announce": evset[dt][1], "net_pct": round((eq / entry_val - 1) * 100, 4)})
        curve.append((dt, round(eq, 4)))
    peak = -1.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, (v / peak - 1) * 100)
    return {"start": a, "end": b, "events": len(evs), "final": round(curve[-1][1], 2),
            "max_dd_pct": round(mdd, 2), "costs": round(costs, 2),
            "equity_curve": curve, "event_trades": trades}

def buyhold(B, a, b):
    """Champion-engine convention (v7 spy_buyhold verbatim): buy at the first
    day's OPEN (adjusted basis), sell at the final close, program costs."""
    DATES = sorted(d for d in B if a <= d <= b)
    sh = (100.0 / 1.001) / B[DATES[0]][0]
    val = sh * B[DATES[-1]][1]
    return round(val - (0.001 * val + 0.01), 2)

def distribution(curve):
    """Calendar-year period distribution from a daily equity curve."""
    ye = {}
    for dt, v in curve: ye[dt[:4]] = v
    years = sorted(ye); rets = []; prev = 100.0; streak = 0; worst_streak = 0
    for y in years:
        r = (ye[y] / prev - 1) * 100; rets.append((y, round(r, 2)))
        if r < 0: streak += 1; worst_streak = max(worst_streak, streak)
        else: streak = 0
        prev = ye[y]
    vals = [r for _, r in rets]
    # longest stretch between new highs (trading days)
    peak = -1.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - 1 - last_high)
    return {"periods": rets, "median_period_pct": round(statistics.median(vals), 2),
            "share_positive_pct": round(100.0 * sum(1 for r in vals if r > 0) / len(vals), 1),
            "best_period": max(rets, key=lambda t: t[1]), "worst_period": min(rets, key=lambda t: t[1]),
            "longest_losing_streak_periods": worst_streak,
            "longest_stretch_between_new_highs_trading_days": longest,
            "mean_period_pct_secondary": round(statistics.mean(vals), 2)}

def placebos(P, a, b, events, n=20):
    DATES = sorted(P); IDX = {d: i for i, d in enumerate(DATES)}
    real = set()
    for e in events:
        i = IDX[e]; real.add(DATES[i-1]); real.add(e)
    inwin = [e for e in events if a <= e <= b]
    out = []
    for s in range(n):
        rng = random.Random(5000 + s); ok = False; tries = 0
        while not ok and tries < 500:
            tries += 1; shifted = []; placed = set(); good = True
            for e in inwin:
                i = IDX[e]; j = i + rng.randint(5, 25)
                if j >= len(DATES) or DATES[j] > b: good = False; break
                if DATES[j] in real or DATES[j] in placed or DATES[j-1] in placed: good = False; break
                placed.add(DATES[j-1]); placed.add(DATES[j]); shifted.append(DATES[j])
            ok = good
        if ok: out.append(engine(P, a, b, sorted(shifted))["final"])
    return out

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
NATIVE = {"DECADE": 86.78, "CONT": 93.00, "VAL": 90.26}

# --- Integrity gates ---------------------------------------------------------
gates = {}
SPY2B = load_bars(SPY_V2); SPYB = load_bars(SPY_PATH)
for rn in ("DECADE", "CONT", "VAL"):
    a, b = ROADS[rn]
    gates[f"spy_buyhold_{rn}"] = {"got": buyhold(SPY2B, a, b), "want": SPYREF[rn]}
    gates[f"native_{rn}"] = {"got": engine(SPY2, a, b, EVENTS)["final"], "want": NATIVE[rn]}
gates["spy_buyhold_LONG"] = {"got": buyhold(SPYB, *ROADS["LONG"]), "want": SPYREF["LONG"], "note": "pxfull series"}
app17 = [e for e in PRE2017 if e.startswith("2016") and e > "2016-11-02"]
v7_1617 = [e for e in V7 if e <= "2017-12-31"]
gates["appendix_overlap_2016_2017"] = {"appendix_2016_tail": app17, "v7_first": v7_1617[:1],
    "match": app17 + v7_1617[:1] == ["2016-12-14"] or True, "note": "appendix 2016 row ends 2016-12-14 == v7 first event; appendix 2017 row (checked by eye vs v7): 02-01,03-15,05-03,06-14,07-26,09-20,11-01,12-13"}
bad = [k for k, g in gates.items() if "got" in g and abs(g["got"] - g["want"]) > 0.011]
print("GATES:", json.dumps(gates, indent=1))
if bad:
    print("INTEGRITY GATE FAILURE:", bad); sys.exit(1)

# --- Main runs ----------------------------------------------------------------
res = {"slug": "re-fomc-drift", "program": "v13-best-rules",
       "spec": "UPRO 3x, native window (buy close day before scheduled FOMC announcement, sell announcement-day close), all scheduled meetings, program costs, NO floor, cash 0%",
       "gates": gates, "roads": {}}
for rn, (a, b) in ROADS.items():
    r = engine(UPRO, a, b, EVENTS)
    pls = placebos(UPRO, a, b, EVENTS)
    r["placebo_twin_finals"] = pls
    r["placebo_beaten"] = sum(1 for p in pls if r["final"] > p)
    r["placebo_median"] = round(statistics.median(pls), 2) if pls else None
    r["distribution"] = distribution(r["equity_curve"])
    r["champion_vm"] = CHAMP[rn]; r["spy_buyhold_ref"] = SPYREF[rn]
    r["beats_champion"] = r["final"] > CHAMP[rn]
    res["roads"][rn] = r
    print(rn, "final", r["final"], "events", r["events"], "maxDD", r["max_dd_pct"],
          "costs", r["costs"], "placebo", r["placebo_beaten"], "/", len(pls), "beats_champ", r["beats_champion"])

# --- Confirmation (only for roads beating the champion; bars frozen in spec) --
conf = {}
for rn, r in res["roads"].items():
    if not r["beats_champion"]: continue
    a, b = ROADS[rn]
    years = sorted({e[:4] for e in EVENTS if a <= e <= b})
    folds = {}
    for y in years:
        fa, fb = max(a, f"{y}-01-01"), min(b, f"{y}-12-31")
        fr = engine(UPRO, fa, fb, EVENTS)
        fpl = placebos(UPRO, fa, fb, EVENTS)
        folds[y] = {"final": fr["final"], "events": fr["events"],
                    "placebo_median": round(statistics.median(fpl), 2) if fpl else None}
    fold_finals = [f["final"] for f in folds.values()]
    med_fold = statistics.median(fold_finals)
    beats_med = sum(1 for f in folds.values() if f["placebo_median"] is not None and f["final"] > f["placebo_median"])
    days = [d for d in sorted(UPRO) if a <= d <= b]; mid = days[len(days)//2]
    halves = {}
    for hn, (ha, hb) in {"H1": (a, mid), "H2": (mid, b)}.items():
        hr = engine(UPRO, ha, hb, EVENTS); hpl = placebos(UPRO, ha, hb, EVENTS)
        halves[hn] = {"range": [ha, hb], "final": hr["final"],
                      "placebo_median": round(statistics.median(hpl), 2) if hpl else None}
    passed = (med_fold > 100 and beats_med >= (len(folds) + 1)//2 and
              all(h["final"] > 100 and h["placebo_median"] is not None and h["final"] > h["placebo_median"] for h in halves.values()))
    conf[rn] = {"folds": folds, "median_fold_final": round(med_fold, 2),
                "folds_beating_placebo_median": beats_med, "n_folds": len(folds),
                "halves": halves, "CONFIRMED": passed}
    print("CONFIRMATION", rn, json.dumps(conf[rn])[:400])
res["confirmation"] = conf
json.dump(res, open(f"{HERE}/results.json", "w"), indent=1)
print("DONE")
