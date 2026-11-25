#!/usr/bin/env python3
"""v13 BEST RULES — hunt-aaii-sentiment. Rules frozen in BEST-RULES-SPEC.md
before this run. Always-in SPY base; weekly AAII dial sets target exposure
(100/50/0) from the latest PUBLISHED print; rebalance the delta at the next
trading day's open after Thursday publication. Bearish>=50% -> 100% override;
bullish>=55% -> 0%; bullish>=50% -> 50%; else 100%. NO floor. Program costs
0.10%/side on traded delta + $0.01/trade. Placebos: 20-seed circular shifts
of the daily exposure path (random timing, same distribution/turnover).
Data: AAII mirror CSV in ./data/aaii.csv (ends 2024-06-27; dial holds last
exposure after the fence). SPY from the v7 pxfull cache via common.py."""
import csv, json, os, random, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

HERE = os.path.dirname(os.path.abspath(__file__))
ROADS13 = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
V12 = {"LONG": 273.65, "DECADE": 210.66, "CONT": 189.88, "VAL": 137.05}

# --- AAII prints (CSV date = week ending Wednesday; fractions -> %) ---
rows = []
for r in csv.reader(open(os.path.join(HERE, "data", "aaii.csv"))):
    if not r or not r[0] or not r[0][0].isdigit():
        continue
    try:
        dt = datetime.strptime(r[0].strip(), "%m-%d-%y")
        rows.append((dt.strftime("%Y-%m-%d"), float(r[1]) * 100, float(r[3]) * 100))
    except Exception:
        continue
rows.sort()
DATA_END = rows[-1][0]

def dial(bull, bear):
    if bear >= 50.0:
        return 1.0
    if bull >= 55.0:
        return 0.0
    if bull >= 50.0:
        return 0.5
    return 1.0

def build_exposure(prints, bar_dates):
    """Target exposure per bar: a print published Thu (Wed+1) takes effect at
    the first trading day strictly after publication (its open)."""
    expo = [1.0] * len(bar_dates)
    cur = 1.0
    pi = 0
    for i, d in enumerate(bar_dates):
        while pi < len(prints):
            w, bull, bear = prints[pi]
            pub = (datetime.fromisoformat(w) + timedelta(days=1)).strftime("%Y-%m-%d")
            if d > pub:
                cur = dial(bull, bear)
                pi += 1
            else:
                break
        expo[i] = cur
    return expo

def sim_dial(bars, expo, cost=STK_COST, fee=STK_FEE):
    """Fractional-exposure sim: at each bar open, rebalance shares to
    expo[i] of equity-at-open; cost on traded notional + fee per trade."""
    cash, shares = START, 0.0
    curve, trades, costs = [], 0, 0.0
    applied = None
    for i, b in enumerate(bars):
        tgt = expo[i]
        if tgt != applied:
            eq_open = cash + shares * b["o"]
            want_sh = (tgt * eq_open) / b["o"] if b["o"] > 0 else shares
            delta_val = abs(want_sh - shares) * b["o"]
            if delta_val > 1e-9:
                c = delta_val * cost + fee
                costs += c; trades += 1
                if want_sh > shares:  # buy: spend from cash, cost out of cash
                    shares = want_sh
                    cash = eq_open - shares * b["o"] - c
                else:                 # sell down to target
                    shares = want_sh
                    cash = eq_open - shares * b["o"] - c
                if cash < 0:  # cost overrun on a full buy: trim shares
                    shares += cash / b["o"]; cash = 0.0
            applied = tgt
        curve.append({"d": b["d"], "eq": round(cash + shares * b["c"], 4)})
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve,
            "trades": trades, "costs": round(costs, 2), "maxdd": maxdd(curve)}

spy = load_pxfull("SPY")
out = {"family": "hunt-aaii-sentiment", "program": "v13-best-rules",
       "spec": "BEST-RULES-SPEC.md (frozen before run)", "data_end": DATA_END,
       "verdict_ceiling": "CANDIDATE", "roads": {}}
for road, (s, e) in ROADS13.items():
    bars = [b for b in spy if s <= b["d"] <= e]
    bd = [b["d"] for b in bars]
    prints = [r for r in rows if r[0] < e]
    expo = build_exposure(prints, bd)
    nat = sim_dial(bars, expo)
    pls = []
    for sd in range(1, 21):
        rng = random.Random(sd)
        k = rng.randrange(1, len(expo))
        shifted = expo[k:] + expo[:k]
        pls.append(sim_dial(bars, shifted)["final"])
    frac = {str(v): round(sum(1 for x in expo if x == v) / len(expo), 4) for v in (1.0, 0.5, 0.0)}
    out["roads"][road] = {
        "my_rules": nat, "spy_buyhold": round(buyhold_open(bars), 2),
        "champion_vm": CHAMP[road], "spy_reference": SPYREF[road], "v12_published_final": V12[road],
        "placebos_beaten_of_20": sum(1 for p in pls if nat["final"] > p),
        "placebo_finals": [round(p, 2) for p in pls],
        "placebo_median": round(sorted(pls)[10], 2),
        "exposure_day_fraction": frac,
        "periods_monthly": period_stats(nat["curve"], "monthly")}
    print(road, "final", nat["final"], "dd", nat["maxdd"], "trades", nat["trades"],
          "placebos", out["roads"][road]["placebos_beaten_of_20"], "/20", "expo", frac)

# Confirmation (frozen bars) — only if a road beats the champion
conf = {}
for road, (s, e) in ROADS13.items():
    if out["roads"][road]["my_rules"]["final"] > CHAMP[road]:
        bars = [b for b in spy if s <= b["d"] <= e]
        bd = [b["d"] for b in bars]
        prints = [r for r in rows if r[0] < e]
        total_days = len(bars)
        champ = CHAMP[road]
        def seg_final(sb):
            if len(sb) < 2: return None
            ex = build_exposure([r for r in rows if r[0] < sb[-1]["d"]], [b["d"] for b in sb])
            return sim_dial(sb, ex)["final"]
        years = {}
        for y in range(int(s[:4]), int(e[:4]) + 1):
            sb = [b for b in bars if b["d"][:4] == str(y)]
            f = seg_final(sb)
            if f is None: continue
            bar = 100.0 * (champ / 100.0) ** (len(sb) / total_days)
            years[str(y)] = {"final": f, "champ_prorata_bar": round(bar, 2), "beats_bar": f > bar}
        mid = bars[total_days // 2]["d"]
        halves = {}
        for name, sb in (("H1", [b for b in bars if b["d"] < mid]), ("H2", [b for b in bars if b["d"] >= mid])):
            f = seg_final(sb)
            bar = 100.0 * (champ / 100.0) ** (len(sb) / total_days)
            halves[name] = {"final": f, "champ_prorata_bar": round(bar, 2), "beats_bar": f > bar}
        yrs_beat = sum(1 for v in years.values() if v["beats_bar"])
        conf[road] = {"yearly_folds": years, "halves": halves,
                      "years_beaten": f"{yrs_beat}/{len(years)}",
                      "confirmed": yrs_beat > len(years) / 2 and any(v["beats_bar"] for v in halves.values())}
out["confirmation"] = conf
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("confirmation:", json.dumps(conf)[:400] if conf else "not triggered")
print("done")
