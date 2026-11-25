#!/usr/bin/env python3
"""Appel Triple Momentum — V13 BEST RULES (spec frozen in BEST-RULES-SPEC.md before this run).
MY RULES: single read = ROC(25 trading days) of ^IXIC close; WEEKLY evaluation (last trading
day of each week); long QQQ when ROC25 > 0, cash when <= 0; next-open execution; program
costs; NO floor. Comparator: published form (TM=ROC5+ROC15+ROC25, 4% cross, daily) in the
same engine on the same data. 20-seed circular-shift placebos of my state series per road.
Confirmation (half-windows + calendar-year fresh pots vs champion-implied growth) runs ONLY
if a road beats champion V+M, per the bars frozen in the spec."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/hunt-appel-triple-momentum")
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
V12_PUBLISHED = {"LONG": 182.55, "DECADE": 168.86, "CONT": 180.73, "VAL": 127.79}

ixic = load_yahoo_file(os.path.join(HERE, "data", "ixic.json"))
qqq = load_yahoo_file(os.path.join(HERE, "data", "qqq.json"))
icl = [b["c"] for b in ixic]

# daily ROC25 sign on ^IXIC
roc_sign = []
for i in range(len(icl)):
    roc_sign.append(1 if i >= 25 and icl[i] / icl[i - 25] - 1 > 0 else 0)

# published TM states on ^IXIC (v12 logic, verbatim)
def tm_states(closes):
    states = []; pos = 0
    for i in range(len(closes)):
        if i >= 25:
            tm = sum((closes[i] / closes[i - k] - 1) * 100 for k in (5, 15, 25))
            ptm = sum((closes[i - 1] / closes[i - 1 - k] - 1) * 100 for k in (5, 15, 25))
            if tm > 4 and ptm <= 4: pos = 1
            elif tm < 4 and ptm >= 4: pos = 0
        states.append(pos)
    return states
tm = tm_states(icl)

# map ^IXIC daily states onto QQQ bars by date (last ^IXIC bar <= QQQ bar date)
def map_states(src_bars, src_states):
    out = []; j = -1
    for b in qqq:
        while j + 1 < len(src_bars) and src_bars[j + 1]["d"] <= b["d"]: j += 1
        out.append(src_states[j] if j >= 0 else 0)
    return out

daily_sign_q = map_states(ixic, roc_sign)
tm_q = map_states(ixic, tm)

# WEEKLY gating: state may only change at the last trading day of an ISO week.
# states[i] is the position decided at close of bar i (executed next open, per chassis).
def weekly_gate(bars, daily_states):
    out = []; cur = 0
    for i, b in enumerate(bars):
        y, m, d = (int(x) for x in b["d"].split("-"))
        from datetime import date as _date
        iso = _date(y, m, d).isocalendar()
        nxt = bars[i + 1] if i + 1 < len(bars) else None
        is_week_end = True
        if nxt is not None:
            y2, m2, d2 = (int(x) for x in nxt["d"].split("-"))
            is_week_end = _date(y2, m2, d2).isocalendar()[:2] != iso[:2]
        if is_week_end: cur = daily_states[i]
        out.append(cur)
    return out

my_q = weekly_gate(qqq, daily_sign_q)

out = {"family": "hunt-appel-triple-momentum", "program": "v13-best-rules",
       "my_rules": "ROC25(^IXIC) sign, weekly eval, QQQ long/cash, next-open, program costs, no floor",
       "roads": {}}
confirm_needed = []
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(qqq) if s <= b["d"] <= e]
    bars = [qqq[i] for i in idx]
    mine = sim_open_exec(bars, [my_q[i] for i in idx])
    pub = sim_open_exec(bars, [tm_q[i] for i in idx])
    pls = [sim_open_exec(bars, placebo_shift([my_q[i] for i in idx], sd))["final"] for sd in range(1, 21)]
    out["roads"][road] = {
        "window": [bars[0]["d"], bars[-1]["d"]],
        "my_rules": mine, "published_same_engine": pub,
        "v12_published_final": V12_PUBLISHED[road],
        "qqq_buyhold": round(buyhold_open(bars), 2),
        "champion_vm": CHAMP[road], "spy_ref": SPYREF[road],
        "placebos_beaten": sum(1 for p in pls if mine["final"] > p),
        "placebo_finals": [round(p, 2) for p in pls],
        "periods_monthly": period_stats(mine["curve"], "monthly"),
        "periods_daily": period_stats(mine["curve"], "daily")}
    if mine["final"] > CHAMP[road]: confirm_needed.append(road)
    print(road, "mine", mine["final"], "DD", mine["maxdd"], "trades", mine["trades"],
          "| published(same engine)", pub["final"], "| buyhold", out["roads"][road]["qqq_buyhold"],
          "| placebos beaten", out["roads"][road]["placebos_beaten"], "/20")

# ---- Confirmation, only if triggered (bars frozen in spec) ----
out["confirmation_triggered"] = confirm_needed
if confirm_needed:
    conf = {}
    for road in confirm_needed:
        s, e = ROADS[road]
        idx = [i for i, b in enumerate(qqq) if s <= b["d"] <= e]
        bars = [qqq[i] for i in idx]; st = [my_q[i] for i in idx]
        yrs_full = (len(bars) / 252.0)
        champ_cagr = (CHAMP[road] / 100.0) ** (1 / yrs_full) - 1
        mid = len(bars) // 2
        halves = []
        for hb, hs in ((bars[:mid], st[:mid]), (bars[mid:], st[mid:])):
            r = sim_open_exec(hb, hs)
            bar = 100.0 * (1 + champ_cagr) ** (len(hb) / 252.0)
            halves.append({"final": r["final"], "champion_implied_bar": round(bar, 2), "pass": r["final"] > bar})
        years = {}
        for y in sorted(set(b["d"][:4] for b in bars)):
            yi = [i for i, b in enumerate(bars) if b["d"][:4] == y]
            if len(yi) < 20: continue
            r = sim_open_exec([bars[i] for i in yi], [st[i] for i in yi])
            years[y] = r["final"]
        above = sum(1 for v in years.values() if v > 100)
        conf[road] = {"halves": halves, "years_above_100": f"{above}/{len(years)}",
                      "year_finals": years,
                      "pass": all(h["pass"] for h in halves) and above * 2 >= len(years)}
        print("CONFIRM", road, conf[road]["pass"], halves, conf[road]["years_above_100"])
    out["confirmation"] = conf

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done; confirmation triggered:", confirm_needed)
