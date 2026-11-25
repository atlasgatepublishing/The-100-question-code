#!/usr/bin/env python3
"""V13 BEST RULES — Appel MACD at WEEKLY cadence (BEST-RULES-SPEC.md, frozen before this run).
MACD(12,26,9) on weekly SPY closes; cross above -> buy, cross below -> cash;
signal at week close -> next session's open; all-in/all-out; NO floor; program
stock costs; $100 pots. EMAs seeded at first close of full history (2008-),
first signal after 35 weekly bars (v12 convention). Placebos: 20-seed circular
shift + 20-seed matched random-timing (run-length permutation: exact same
invested days and same number of switches, calendar placement randomized)."""
import json, os, random, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (START, load_pxfull, sim_open_exec, buyhold_open, maxdd,
                    period_stats, placebo_shift, ema_series, CHAMP, SPYREF)

HERE = os.path.dirname(os.path.abspath(__file__))
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
PUB = {"LONG": 186.52, "DECADE": 159.36, "CONT": 153.23, "VAL": 115.92}  # v12 published daily form

spy = load_pxfull("SPY")

# ---- weekly bars: close = last trading day's close of each ISO week ----
weeks = []  # (week_key, last_daily_idx, close)
for i, b in enumerate(spy):
    y, m, d = (int(x) for x in b["d"].split("-"))
    from datetime import date
    iso = date(y, m, d).isocalendar()
    key = (iso[0], iso[1])
    if weeks and weeks[-1][0] == key:
        weeks[-1] = (key, i, b["c"])
    else:
        weeks.append((key, i, b["c"]))
wcloses = [w[2] for w in weeks]

e12 = ema_series(wcloses, 12); e26 = ema_series(wcloses, 26)
macd = [a - b for a, b in zip(e12, e26)]; sig = ema_series(macd, 9)
wstate = []; pos = 0
for i in range(len(weeks)):
    if i >= 35:
        if macd[i] > sig[i] and macd[i - 1] <= sig[i - 1]: pos = 1
        elif macd[i] < sig[i] and macd[i - 1] >= sig[i - 1]: pos = 0
    wstate.append(pos)

# ---- map weekly states onto daily bars: at the last bar of week w, the desired
# state (decided at that close) becomes week w's MACD state; sim trades next open ----
week_of_last = {w[1]: wi for wi, w in enumerate(weeks)}
dstates = []; cur = 0
for i in range(len(spy)):
    if i in week_of_last: cur = wstate[week_of_last[i]]
    dstates.append(cur)

def runs_of(states):
    runs = []  # (state, length)
    for s in states:
        if runs and runs[-1][0] == s: runs[-1][1] += 1
        else: runs.append([s, 1])
    return runs

def random_timing(states, seed):
    """Permute run lengths within each state class: invested days and switch
    count are EXACTLY the real series'; calendar placement is randomized."""
    runs = runs_of(states)
    rng = random.Random(seed)
    inv = [r[1] for r in runs if r[0] == 1]; cash = [r[1] for r in runs if r[0] == 0]
    rng.shuffle(inv); rng.shuffle(cash)
    out = []; ii = ci = 0
    for st, _ in runs:
        if st == 1: ln = inv[ii]; ii += 1
        else: ln = cash[ci]; ci += 1
        out.extend([st] * ln)
    return out

def weekly_stats(curve):
    wk = {}
    from datetime import date
    for c in curve:
        y, m, d = (int(x) for x in c["d"].split("-"))
        iso = date(y, m, d).isocalendar(); wk[(iso[0], iso[1])] = c["eq"]
    ks = sorted(wk); rets = []; prev = START
    for k in ks: rets.append(wk[k] / prev - 1 if prev > 0 else 0.0); prev = wk[k]
    if not rets: return {}
    streak = worst = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst = max(worst, streak)
    vals = [START] + [wk[k] for k in ks]; peak = vals[0]; since = longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"tempo": "weekly", "n_periods": len(rets),
            "share_positive": round(sum(1 for r in rets if r > 0) / len(rets), 4),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def run_window(bars, states):
    r = sim_open_exec(bars, states)
    return r

out = {"family": "hunt-appel-macd", "program": "v13-best-rules",
       "design": "Weekly MACD(12,26,9) crossover timer on SPY, next-open exec, no floor, program costs, $100",
       "ema_seed": "EMA seeded at first close of full SPY history (2008-01-02); first signal after 35 weekly bars",
       "roads": {}}
beats = []
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; states = [dstates[i] for i in idx]
    nat = run_window(bars, states)
    bh = round(buyhold_open(bars), 2)
    sh = [sim_open_exec(bars, placebo_shift(states, sd))["final"] for sd in range(1, 21)]
    rt = [sim_open_exec(bars, random_timing(states, sd))["final"] for sd in range(1, 21)]
    rec = {"final": nat["final"], "maxdd_pct": nat["maxdd"], "trades": nat["trades"],
           "costs": nat["costs"], "invested_frac": nat["invested_frac"], "halted": nat["halted"],
           "spy_buyhold": bh, "champion_vm": CHAMP[road], "spy_ref": SPYREF[road],
           "published_daily_final": PUB[road],
           "shift_placebos_beaten": sum(1 for p in sh if nat["final"] > p),
           "shift_placebo_finals": [round(p, 2) for p in sh],
           "random_timing_beaten": sum(1 for p in rt if nat["final"] > p),
           "random_timing_median": round(statistics.median(rt), 2),
           "random_timing_finals": [round(p, 2) for p in rt],
           "periods_monthly": period_stats(nat["curve"], "monthly"),
           "periods_weekly": weekly_stats(nat["curve"]),
           "curve": nat["curve"]}
    out["roads"][road] = rec
    if nat["final"] > CHAMP[road]: beats.append(road)
    print(road, "final", nat["final"], "maxdd", nat["maxdd"], "trades", nat["trades"],
          "BH", bh, "shift", rec["shift_placebos_beaten"], "/20  randtiming",
          rec["random_timing_beaten"], "/20 med", rec["random_timing_median"])

# ---- confirmation (frozen bars in spec) only for roads beating the champion ----
out["champion_beats"] = beats
out["confirmation"] = {}
for road in beats:
    s, e = ROADS[road]
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; states = [dstates[i] for i in idx]
    years = sorted(set(b["d"][:4] for b in bars))
    folds = []
    for y in years:
        yi = [j for j, b in enumerate(bars) if b["d"][:4] == y]
        if len(yi) < 200: continue
        yb = [bars[j] for j in yi]; ys = [states[j] for j in yi]
        folds.append({"year": y, "strat": sim_open_exec(yb, ys)["final"],
                      "spy": round(buyhold_open(yb), 2)})
    strat_wins = sum(1 for f in folds if f["strat"] > f["spy"])
    med_ok = statistics.median([f["strat"] for f in folds]) >= statistics.median([f["spy"] for f in folds])
    mid = len(bars) // 2
    h1 = sim_open_exec(bars[:mid], states[:mid])["final"]; h1s = round(buyhold_open(bars[:mid]), 2)
    h2 = sim_open_exec(bars[mid:], states[mid:])["final"]; h2s = round(buyhold_open(bars[mid:]), 2)
    conf = {"yearly_folds": folds, "years_beaten": f"{strat_wins}/{len(folds)}",
            "majority_years": strat_wins > len(folds) / 2, "median_year_ok": med_ok,
            "half1": {"strat": h1, "spy": h1s}, "half2": {"strat": h2, "spy": h2s},
            "both_halves_beat_spy": h1 > h1s and h2 > h2s}
    conf["passed"] = conf["majority_years"] and med_ok and conf["both_halves_beat_spy"]
    out["confirmation"][road] = conf
    print("CONFIRM", road, conf["passed"], conf["years_beaten"], conf["half1"], conf["half2"])

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("champion beats:", beats)
