#!/usr/bin/env python3
"""
BUYBACK-EVENTS v13 — BEST-RULES RUN. Spec frozen in BEST-RULES-SPEC.md
before this script was written.

Mechanics: v12 completed census (123 events, read-only); take an event
ONLY if the announcer's adjusted close on the last trading day before
entry is below its close 252 trading days earlier (>=120 trading days of
history required); exclude "offset" authorizations; entry next open;
24-month hold; max 10 concurrent, slice = pot value/10; one position per
ticker; NO floor/halt/stop; costs 0.10%/side + $0.01/share sold.

Roads DECADE/CONT/VAL (LONG = named closure: census+cache begin Nov 2016).
Placebos per road: canonical +6mo shift + 20 seeded shifts, identical
mechanics (filter evaluated at shifted dates).
Integrity gate: SPY DECADE on shared bars == $367.80.
Simulation only.
"""
import bisect
import importlib.util
import json
import os
import random
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.join(HERE, "..", "..", "v12-completions", "buyback-events")
V10 = os.path.join(HERE, "..", "..", "v10-retest", "buyback-events")
START_CASH = 100.0
MAX_POS = 10
HOLD_MONTHS = 24


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = load(os.path.join(V10, "engine.py"), "v10_engine")
v12run = load(os.path.join(V12, "run.py"), "v12_run")  # reuse bars/calendar
add_months = eng.add_months
champ = eng.load_champion()
pb = v12run.pb
cal = v12run.cal

CENSUS = json.load(open(os.path.join(V12, "census.json")))["events"]
EVENTS = sorted(((e["ticker"], e["date"], e["note"]) for e in CENSUS),
                key=lambda e: e[1])


def is_offset(note):
    return "offset" in note.lower()


def undervalued(tk, entry_day):
    """Close on last trading day before entry < close 252 trading days
    before that. Returns True/False, or None if <120 days of history."""
    dates = cal._dates.get(tk, [])
    closes = cal._closes.get(tk, [])
    i = bisect.bisect_left(dates, entry_day) - 1  # last bar before entry
    if i < 119:
        return None
    j = i - 252
    if j < 0:
        j = 0
    return closes[i] < closes[j]


def run_pot(events, start, end, label):
    days = [d for d in cal.days if start <= d <= end]
    if not days:
        return None
    by_entry = {}
    eligible = []
    for tk, fd, note in events:
        if not (start <= fd <= end):
            continue
        entry = cal.first_day_after(fd)
        if entry is None or entry > end:
            continue
        by_entry.setdefault(entry, []).append((tk, fd, note))
        eligible.append((tk, fd))
    cash = START_CASH
    positions = []
    trades = []
    skipped = []
    total_costs = 0.0
    curve = []

    def close_value(d):
        v = cash
        for p in positions:
            c = cal.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for d in days:
        for p in list(positions):
            if p["exit_day"] == d:
                xp = cal.open_on(p["ticker"], d)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], d)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([d, p["ticker"], "SELL-EXIT", round(p["shares"], 4),
                               xp, round(val, 2), round(c, 2)])
                positions.remove(p)
        for tk, fd, note in by_entry.get(d, []):
            if is_offset(note):
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "offset authorization excluded (spec)"})
                continue
            if any(p["ticker"] == tk for p in positions):
                skipped.append({"date": fd, "ticker": tk, "reason": "already held"})
                continue
            if len(positions) >= MAX_POS:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "pot full (10 positions)"})
                continue
            uv = undervalued(tk, d)
            if uv is None:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "insufficient price history for filter"})
                continue
            if not uv:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "filter: prior-12mo return not negative"})
                continue
            o = cal.open_on(tk, d)
            if o is None:
                skipped.append({"date": fd, "ticker": tk, "reason": "no price bar"})
                continue
            pv = cash
            for p in positions:
                po = cal.open_on(p["ticker"], d)
                if po:
                    pv += p["shares"] * po
            buy_val = min(pv / MAX_POS, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "insufficient cash"})
                continue
            sh = buy_val / o
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            exit_day = cal.first_day_on_or_after(add_months(d, HOLD_MONTHS))
            if exit_day is None:
                exit_day = days[-1]
            positions.append({"ticker": tk, "shares": sh,
                              "exit_day": exit_day, "entry": d, "filing": fd})
            trades.append([d, tk, "BUY", round(sh, 4), o,
                           round(buy_val, 2), round(c, 2)])
        curve.append([d, round(close_value(d), 4)])
    last = days[-1]
    for p in list(positions):
        xp = cal.close_on_or_before(p["ticker"], last)
        val = p["shares"] * xp
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append([last, p["ticker"], "SELL-END", round(p["shares"], 4),
                       xp, round(val, 2), round(c, 2)])
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "trades": trades,
            "skipped": skipped, "events_eligible": len(eligible),
            "curve": curve}


def max_dd(curve):
    peak = START_CASH
    worst = 0.0
    for _, v in curve:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return round(worst * 100, 2)


def cagr(final, start, end):
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / START_CASH) ** (1 / yrs) - 1) * 100, 2)


def period_record(curve):
    def stats(rets_list):
        rs = sorted(r for _, r in rets_list)
        n = len(rs)
        med = rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2
        streak = worst = 0
        for _, r in rets_list:
            streak = streak + 1 if r < 0 else 0
            worst = max(worst, streak)
        return {"periods": n,
                "share_positive_pct": round(100 * sum(1 for r in rs if r > 0) / n, 1),
                "median_pct": round(med * 100, 3),
                "best_pct": round(rs[-1] * 100, 2),
                "worst_pct": round(rs[0] * 100, 2),
                "longest_losing_streak": worst,
                "mean_pct_secondary": round(100 * sum(rs) / n, 3)}

    pts = [(curve[0][0], START_CASH)] + list(curve)
    daily = [(d1, v1 / v0 - 1.0) for (d0, v0), (d1, v1) in zip(pts, pts[1:]) if v0 > 0]
    out = {"daily": stats(daily)}
    # monthly from month-end values
    seen = {}
    for d, v in curve:
        seen[d[:7]] = v
    mvals = [(k, seen[k]) for k in sorted(seen)]
    mrets = [(k, v / pv - 1.0) for (pk, pv), (k, v) in
             zip([("start", START_CASH)] + mvals, mvals)]
    out["monthly"] = stats(mrets)
    for key, vals in (("daily", [v for _, v in curve]),
                      ("monthly", [v for _, v in mvals])):
        peak = START_CASH
        last_high = 0
        longest = 0
        for i, v in enumerate(vals):
            if v >= peak:
                peak = v
                longest = max(longest, i - last_high)
                last_high = i
        longest = max(longest, len(vals) - 1 - last_high)
        unit = "trading_days" if key == "daily" else "months"
        out[key][f"longest_stretch_between_new_highs_{unit}"] = longest
    return out


ROADS = [("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


def main():
    spy_dec, _ = champ.spy_net(pb, "2016-11-21", "2026-11-20", 100.0)
    print(f"GATE SPY decade: ${round(spy_dec, 2)} (reference $367.80)", flush=True)
    assert round(spy_dec, 2) == 367.80, spy_dec
    print("INTEGRITY GATE PASS", flush=True)

    results = {"spec": "v13 best-rules: undervaluation filter (prior-12mo "
                       "return < 0), offset excluded, 24mo hold, 10 slots, "
                       "no floor",
               "integrity": {"spy_decade": round(spy_dec, 2)},
               "roads": {}}
    for name, ws, we in ROADS:
        real = run_pot(EVENTS, ws, we, f"{name} real")
        spy, _ = champ.spy_net(pb, ws, we, 100.0)
        canon_events = [(tk, add_months(fd, 6), note) for tk, fd, note in EVENTS]
        canon = run_pot(canon_events, ws, we, f"{name} canonical +6mo placebo")
        seed_finals = []
        for s in range(1, 21):
            rng = random.Random(1000 + s)
            offs = [rng.choice([m for m in range(-18, 19) if m != 0])
                    for _ in EVENTS]
            sev = [(tk, add_months(fd, off), note)
                   for (tk, fd, note), off in zip(EVENTS, offs)]
            seed_finals.append(run_pot(sev, ws, we, f"{name} seed {s}")["final"])
        beaten = sum(1 for f in seed_finals if real["final"] > f)
        srt = sorted(seed_finals)
        road = {"window": [ws, we], "final": real["final"],
                "cagr_pct": cagr(real["final"], ws, we),
                "max_dd_pct": max_dd(real["curve"]),
                "costs": real["costs"],
                "events_eligible": real["events_eligible"],
                "events_traded": sum(1 for t in real["trades"] if t[2] == "BUY"),
                "skip_reasons": {}, "trades": real["trades"],
                "skipped": real["skipped"], "equity_curve": real["curve"],
                "spy_final": round(spy, 2),
                "champion_final": CHAMPION[name],
                "placebo_canonical_plus6mo_final": canon["final"],
                "placebo_seed_finals": seed_finals,
                "placebo_seed_median": srt[10] if len(srt) % 2 else (srt[9] + srt[10]) / 2,
                "placebo_beaten_of_20": beaten,
                "period_record": period_record(real["curve"])}
        for sk in real["skipped"]:
            road["skip_reasons"][sk["reason"]] = \
                road["skip_reasons"].get(sk["reason"], 0) + 1
        results["roads"][name] = road
        print(f"{name}: real ${real['final']} (DD {road['max_dd_pct']}%) vs "
              f"SPY ${round(spy, 2)} vs champion ${CHAMPION[name]}; "
              f"canonical placebo ${canon['final']}; seeds beaten "
              f"{beaten}/20; traded {road['events_traded']}/"
              f"{real['events_eligible']}; skips {road['skip_reasons']}",
              flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
