#!/usr/bin/env python3
"""V13 BEST RULES — Benner Cycle Calendar. Implements BEST-RULES-SPEC.md exactly
(frozen before this run):
- Frozen published table (no re-anchoring): Hard(buy) / Good(sell) / Panic(no action).
- Enter at first open of a Hard Times year if flat (unconditional).
- Exit at last close of a Good Times year if long.
- After a calendar exit, re-enter at the open after the first month-end close
  above the 10-month SMA (full PIT series); a Hard Times entry pre-empts.
- Road-start state inherited point-in-time from the table (state machine).
- NO -15% floor. SPY only, $100, program costs 0.10%/side + $0.01/sell.
- Placebos: whole class table phase-shifted by +seed years, seeds 1..20,
  identical rules/chassis.
Data: family PIT cache pxfull_SPY.json (same file the v12 run used)."""
import json, os, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
START = 100.0
STK_COST = 0.001
STK_FEE = 0.01

HARD = [1924, 1931, 1942, 1951, 1958, 1969, 1978, 1985, 1996, 2005, 2012, 2023]
GOOD = [1926, 1935, 1945, 1953, 1962, 1972, 1980, 1989, 1999, 2007, 2016, 2026]
PANIC = [1927, 1945, 1965, 1981, 1999, 2019, 2035]  # no action, frozen

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 363.41, "DECADE": 187.77, "CONT": 187.77, "VAL": 187.77}

def load_pxfull(sym):
    path = os.path.expanduser(f"~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_{sym}.json")
    j = json.load(open(path))
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

def maxdd(curve):
    peak = -1e18; dd = 0.0
    for p in curve:
        peak = max(peak, p["eq"])
        dd = max(dd, (peak - p["eq"]) / peak if peak > 0 else 0.0)
    return round(dd * 100, 2)

def period_stats(curve, tempo="monthly"):
    months = {}
    for c in curve:
        months[c["d"][:7]] = c["eq"]
    ks = sorted(months)
    rets = []; prev = START
    for k in ks:
        rets.append(months[k] / prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    streak = 0; worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst_streak = max(worst_streak, streak)
    vals = [START] + [months[k] for k in ks]
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; longest = max(longest, since)
    return {"tempo": tempo, "n_periods": len(rets),
            "share_positive": round(pos / len(rets), 4),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst_streak,
            "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def buyhold_open(bars):
    if len(bars) < 2:
        return START
    shares = START * (1 - STK_COST) / bars[0]["o"]
    return round(shares * bars[-1]["c"] * (1 - STK_COST) - STK_FEE, 2)

# ---- monthly closes / SMA10 on the FULL PIT series (point-in-time) ----
FULL = load_pxfull("SPY")
_month_last = {}
for b in FULL:
    _month_last[b["d"][:7]] = b["c"]
_MONTHS = sorted(_month_last)
_MCLOSE = [_month_last[m] for m in _MONTHS]
SMA10 = {}
for i, m in enumerate(_MONTHS):
    if i >= 9:
        SMA10[m] = sum(_MCLOSE[i - 9:i + 1]) / 10.0

# first/last bar index per year in the full series (for state reconstruction)
_year_idx = {}
for i, b in enumerate(FULL):
    _year_idx.setdefault(int(b["d"][:4]), []).append(i)

def initial_state(road_start, hard, good):
    """Simulate the table forward over events strictly before road_start."""
    events = []
    for y in hard:
        if y in _year_idx:
            events.append((FULL[_year_idx[y][0]]["d"], "buy"))
    for y in good:
        if y in _year_idx:
            events.append((FULL[_year_idx[y][-1]]["d"], "sell"))
    state = "FLAT_POST"  # before any labeled buy the pot has nothing to hold
    for d, kind in sorted(events):
        if d < road_start:
            state = "LONG" if kind == "buy" else "FLAT_POST"
    return state

def run_road(bars, hard_set, good_set):
    hard_set = set(hard_set); good_set = set(good_set)
    road_start = bars[0]["d"]
    state0 = initial_state(road_start, hard_set, good_set)
    # Entry/exit anchors are the FULL series' first/last trading day of the
    # class year (spec: first open / last close OF THE YEAR). A road that ends
    # mid-year (all roads end 2026-11-20, before the 2026 Good Times exit date
    # 2026-12-31) must mark to market, never fire the exit early.
    full_first = {y: FULL[idxs[0]]["d"] for y, idxs in _year_idx.items()}
    full_last = {y: FULL[idxs[-1]]["d"] for y, idxs in _year_idx.items()}
    last_of_month = {}
    for i, b in enumerate(bars):
        last_of_month[b["d"][:7]] = i
    cash, shares = START, 0.0
    curve = []; costs = 0.0; buys = 0; sells = 0
    log = []
    mode = "LONG" if state0 == "LONG" else "FLAT_POST"
    pending_reentry = False
    entered_hard = set()
    invested_days = 0
    for i, b in enumerate(bars):
        y = int(b["d"][:4]); m = b["d"][:7]
        # ---- open actions ----
        if shares == 0:
            why = None
            if i == 0 and mode == "LONG":
                why = "road-start state LONG (table inheritance)"
            elif pending_reentry:
                why = "trend re-entry (month-end close > 10M SMA)"
            elif y in hard_set and full_first.get(y) == b["d"] and y not in entered_hard:
                why = f"Hard Times {y} entry (first open)"
            if why:
                costs += cash * STK_COST
                shares = cash * (1 - STK_COST) / b["o"]; cash = 0.0
                buys += 1; pending_reentry = False
                if y in hard_set and full_first.get(y) == b["d"]:
                    entered_hard.add(y)
                log.append({"date": b["d"], "action": "BUY", "why": why, "px": round(b["o"], 4)})
        if shares > 0:
            invested_days += 1
        eq = cash + shares * b["c"]
        # ---- close actions ----
        # Exit fires only when the Good Times year actually completes inside
        # the data (a later bar exists). The 2026 exit date (2026-12-31) is
        # beyond the data end (2026-11-20): position stays open and is marked
        # to market with no liquidation cost — the v12 native convention.
        if shares > 0 and y in good_set and full_last.get(y) == b["d"] and b["d"] < FULL[-1]["d"]:
            proceeds = shares * b["c"] * (1 - STK_COST) - STK_FEE
            costs += shares * b["c"] * STK_COST + STK_FEE
            cash = proceeds; shares = 0.0; sells += 1
            mode = "FLAT_POST"
            log.append({"date": b["d"], "action": "SELL", "why": f"Good Times {y} exit (last close)", "px": round(b["c"], 4)})
            eq = cash
        elif shares == 0 and mode == "FLAT_POST" and last_of_month[m] == i:
            sma = SMA10.get(m)
            if sma is not None and b["c"] > sma:
                pending_reentry = True
        curve.append({"d": b["d"], "eq": round(eq, 4)})
    return {"final": curve[-1]["eq"], "curve": curve, "maxdd": maxdd(curve),
            "buys": buys, "sells": sells, "costs": round(costs, 2),
            "invested_frac": round(invested_days / max(1, len(bars)), 4),
            "initial_state": state0, "trade_log": log,
            "periods_monthly": period_stats(curve, "monthly")}

out = {"family": "hunt-benner-cycle", "program": "v13-best-rules",
       "spec": "BEST-RULES-SPEC.md (frozen before run)",
       "tables_frozen": {"hard": HARD, "good": GOOD, "panic_no_action": PANIC},
       "roads": {}}
for road, (s, e) in ROADS.items():
    bars = [b for b in FULL if s <= b["d"] <= e]
    mine = run_road(bars, HARD, GOOD)
    pls = []
    for seed in range(1, 21):
        hs = [y + seed for y in HARD]; gs = [y + seed for y in GOOD]
        pls.append(run_road(bars, hs, gs)["final"])
    out["roads"][road] = {
        "window": [s, e], "my_rules": mine,
        "published_native_final": PUBLISHED[road],
        "spy_buyhold": buyhold_open(bars), "spy_reference": SPYREF[road],
        "champion_vm": CHAMP[road],
        "placebos_shift_years_seeds_1_20": [round(p, 2) for p in pls],
        "placebos_beaten": sum(1 for p in pls if mine["final"] > p),
        "placebo_median": round(statistics.median(pls), 2)}
    print(road, "mine", mine["final"], "dd", mine["maxdd"], "pub", PUBLISHED[road],
          "spy", out["roads"][road]["spy_buyhold"], "champ", CHAMP[road],
          "placebos beaten", out["roads"][road]["placebos_beaten"], "/20 med",
          out["roads"][road]["placebo_median"], "buys/sells", mine["buys"], mine["sells"],
          "invested", mine["invested_frac"])
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("saved results.json")
