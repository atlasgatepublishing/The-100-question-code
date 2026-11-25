#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — CADENCE SWEEP for buyback-events.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs
(0.10%/side + $0.01/share sell charge), point-in-time, v9 protections
(plain -15% episode-1 floor; first halt -> liquidate, 90 calendar days
in cash, restart with episode-2 floor -15% from restart balance; second
halt ends the run). One clean shot, no tuning.

EVENTS: the frozen, audited 8-K-visible event list from the original
v6 test (engine.py EVENTS, 91 events, filings 2017-02-21..2026-06-24).
This is the 8-K-VISIBLE SUBSET only — the published family (all
repurchase authorization announcements incl. press-release-only ones)
remains UNTESTABLE-AS-PUBLISHED on free data; see RESULTS.md.

PRICES: the champion's shared cache starts 2017-06-01, which cannot
price the first decade months. This script downloads Yahoo daily bars
2016-11-01..2026-11-21 for SPY + the 22 event tickers into data_ext/
(same chart API and same dividend-adjustment parsing as the champion's
get_prices), and verifies them against the shared cache on the overlap
and against the SPEC's decade SPY figure ($367.80).

CADENCE TREATMENT (SPEC uniform rule, event strategies): the event
rules stay exactly as published — entry at the next trading day's open
after the 8-K filing date, 1/5-slice sizing, max 5 concurrent, 12-month
hold. Cadence governs the REVIEW / EXIT-CHECK rhythm only: a position's
scheduled 12-month exit is executed at the open of the first cadence
date on or after entry + 12 calendar months (if no cadence date
remains in the window, the position is liquidated at the window end,
as in the original). The -15% floor is a protection, not a signal: it
stays checked at every daily close in every cell (SPEC: v9 protections
unchanged). Cadence dates: daily = every trading day; weekly = first
trading day of each ISO week; biweekly = first trading day of every
second ISO week (anchored on the first week of the window); monthly =
first trading day of each month; quarterly = first trading day of each
calendar quarter; semi-annual = first trading day of each half-year;
annual = first trading day of each year. The DAILY cell therefore
reproduces the original mechanics exactly (exit at the first trading
day on/after the 12-month target, floor daily) and is the
native-equivalent cell: the strategy is event-driven, its original
review rhythm was daily.

PLACEBOS: the original chassis's placebo design is a date shift of the
audited events. Per cell: (a) the canonical original placebo — every
event shifted +6 calendar months, identical mechanics; and (b) 20
seeded shift placebos — seed s (1..20) shifts each event by a
per-event offset drawn from random.Random(1000+s) uniformly over
{-18..-1, +1..+18} months, identical mechanics. placebo_beaten = how
many of the 20 seeded finals the real final beats. A cadence counts as
a money cadence only if it beats SPY AND all... (SPEC: beats its own
placebo distribution — reported as seeds beaten /20).

Outputs: cells/<cadence>.json per cell (final, CAGR, max DD, costs,
orders, halts/restarts with dates, FULL equity curve, all placebo
finals, event stats), decade standalone rows, and sweep_raw.json.
Simulation only.
"""
import importlib.util
import json
import math
import os
import random
import time
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "data_ext")
os.makedirs(EXT, exist_ok=True)
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0
FLOOR = 85.0
MAX_POS = 5
HOLD_MONTHS = 12
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = load(os.path.join(HERE, "engine.py"), "buyback_v9_engine")
champ = eng.load_champion()
add_months = eng.add_months
EVENTS = sorted(eng.EVENTS, key=lambda e: e[1])
TICKERS = sorted({t for t, _, _ in EVENTS})


# ---------------------------------------------------------------- prices
def fetch_ext(ticker):
    """Yahoo daily bars 2016-11-01..2026-11-21, parsed exactly like the
    champion's get_prices (dividend-adjusted open/close via adjclose
    ratio). Cached in data_ext/."""
    path = os.path.join(EXT, f"px_{ticker}.json")
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        import calendar
        t1 = calendar.timegm(time.strptime("2016-11-01", "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        with open(path, "wb") as f:
            f.write(blob)
        time.sleep(0.3)
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


bars = {}
for t in TICKERS + ["SPY"]:
    bars[t] = fetch_ext(t)
pb = champ.PriceBook(bars)
cal_slow = eng.Cal(pb)


class FastCal:
    """Same interface and semantics as eng.Cal, bisect-based (the
    champion PriceBook.close_on_or_before is a linear scan; with 154
    pot runs in this sweep that is the whole compute budget). Validated
    by the daily cross-check below, which runs the v9 engine's own
    run_event_pot on the slow Cal and must match this runner's daily
    cell to the cent."""

    def __init__(self, pb):
        import bisect
        self.pb = pb
        self._bisect = bisect
        self.days = sorted(b["d"] for b in pb.bars["SPY"])
        self._dates = {}
        self._closes = {}
        for t, bl in pb.bars.items():
            self._dates[t] = [b["d"] for b in bl]
            self._closes[t] = [b["c"] for b in bl]

    def first_day_after(self, ds):
        i = self._bisect.bisect_right(self.days, ds)
        return self.days[i] if i < len(self.days) else None

    def first_day_on_or_after(self, ds):
        i = self._bisect.bisect_left(self.days, ds)
        return self.days[i] if i < len(self.days) else None

    def open_on(self, t, d):
        b = self.pb.bar(t, d)
        return b["o"] if b else None

    def close_on_or_before(self, t, d):
        dates = self._dates.get(t, [])
        i = self._bisect.bisect_right(dates, d) - 1
        return self._closes[t][i] if i >= 0 else None


cal = FastCal(pb)

# overlap check vs the champion's shared cache (SPY + 3 tickers)
overlap = {}
for t in ["SPY", "AAPL", "JPM", "META"]:
    cached = {b["d"]: b["c"] for b in champ.get_prices(t)}
    diffs = [abs(b["c"] / cached[b["d"]] - 1.0) for b in bars[t]
             if b["d"] in cached]
    overlap[t] = {"overlap_days": len(diffs),
                  "max_rel_close_diff": round(max(diffs), 6) if diffs else None}
    print(f"overlap {t}: days={len(diffs)} max_rel_diff={overlap[t]['max_rel_close_diff']}", flush=True)

spy_final, spy_costs = champ.spy_net(pb, START, END, 100.0)
spy_final = round(spy_final, 2)
print(f"DECADE SPY (extended bars, champion spy_net): ${spy_final} (SPEC reference $367.80)", flush=True)

DAYS = [d for d in cal.days if START <= d <= END]


# ---------------------------------------------------------------- cadences
def cadence_dates(name):
    if name == "daily":
        return set(DAYS)
    out = []
    seen = set()
    week_idx = {}
    for d in DAYS:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        iso = date(y, m, dd).isocalendar()
        if name == "weekly":
            key = (iso[0], iso[1])
        elif name == "biweekly":
            key = (iso[0], iso[1])
        elif name == "monthly":
            key = (y, m)
        elif name == "quarterly":
            key = (y, (m - 1) // 3)
        elif name == "semiannual":
            key = (y, (m - 1) // 6)
        elif name == "annual":
            key = (y,)
        if key not in seen:
            seen.add(key)
            if name == "biweekly":
                # anchor: first week of window is week 0; take even weeks
                wk = len([k for k in week_idx])  # placeholder, replaced below
                out.append(d)
            else:
                out.append(d)
    if name == "biweekly":
        # rebuild properly: enumerate distinct ISO weeks in order
        weeks = []
        seenw = set()
        for d in DAYS:
            y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
            iso = date(y, m, dd).isocalendar()
            key = (iso[0], iso[1])
            if key not in seenw:
                seenw.add(key)
                weeks.append(d)
        out = weeks[::2]
    return set(out)


CAD_DATES = {c: cadence_dates(c) for c in CADENCES}
CAD_SORTED = {c: sorted(CAD_DATES[c]) for c in CADENCES}


def exit_day_for(entry, cad):
    """First cadence date on/after entry + 12 months; None if none left."""
    import bisect
    target = add_months(entry, HOLD_MONTHS)
    lst = CAD_SORTED[cad]
    i = bisect.bisect_left(lst, target)
    return lst[i] if i < len(lst) else None


# ---------------------------------------------------------------- pot runner
def run_pot_cadence(events, cad, label):
    """v9 run_event_pot (engine.py) with ONLY the scheduled-exit day
    routed through the cadence calendar. Protection module, sizing,
    costs, entry rule: byte-equivalent logic to engine.py."""
    days = DAYS
    by_entry = {}
    eligible = []
    for tk, fd, note in events:
        if not (START <= fd <= END):
            continue
        entry = cal.first_day_after(fd)
        if entry is None or entry > END:
            continue
        by_entry.setdefault(entry, []).append((tk, fd, note))
        eligible.append((tk, fd))
    cash = START_CASH
    positions = []
    trades = []
    skipped = []
    total_costs = 0.0
    curve = []
    episode = 1
    floor = FLOOR
    restart_not_before = None
    restart_logged = False
    halts = []
    restarts = []
    second_halt = None

    def close_value(d):
        v = cash
        for p in positions:
            c = cal.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for di, d in enumerate(days):
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
        if restart_not_before is not None and not restart_logged \
                and d >= restart_not_before:
            restarts.append({"date": d, "balance": round(cash, 2),
                             "episode2_floor": round(floor, 2)})
            restart_logged = True
        in_cooldown = restart_not_before is not None and d < restart_not_before
        for tk, fd, note in by_entry.get(d, []):
            if in_cooldown:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "v9 post-halt 90-day cash cooldown"})
                continue
            if any(p["ticker"] == tk for p in positions):
                skipped.append({"date": fd, "ticker": tk, "reason": "already held"})
                continue
            if len(positions) >= MAX_POS:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "pot full (5 positions)"})
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
            slice_val = pv / MAX_POS
            buy_val = min(slice_val, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "insufficient cash"})
                continue
            sh = buy_val / o
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            xd = exit_day_for(d, cad)
            if xd is None:
                xd = days[-1]
            positions.append({"ticker": tk, "shares": sh, "exit_day": xd,
                              "entry": d, "filing": fd})
            trades.append([d, tk, "BUY", round(sh, 4), o,
                           round(buy_val, 2), round(c, 2)])
        v = close_value(d)
        curve.append([d, round(v, 2)])
        if v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for p in list(positions):
                xp = cal.open_on(p["ticker"], nd)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], nd)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([nd, p["ticker"], "SELL-HALT", round(p["shares"], 4),
                               xp, round(val, 2), round(c, 2)])
            positions = []
            halts.append({"episode": episode, "breach_date": d,
                          "liquidation_date": nd, "balance": round(cash, 2)})
            if episode >= 2:
                second_halt = d
                return finish(label, cash, total_costs, second_halt, halts,
                              restarts, trades, skipped, eligible, curve)
            episode = 2
            floor = 0.85 * cash
            restart_not_before = (
                date.fromisoformat(nd) + timedelta(days=90)).isoformat()
            restart_logged = False
    last = days[-1]
    for p in list(positions):
        xp = cal.close_on_or_before(p["ticker"], last)
        val = p["shares"] * xp
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append([last, p["ticker"], "SELL-END", round(p["shares"], 4),
                       xp, round(val, 2), round(c, 2)])
    positions = []
    return finish(label, cash, total_costs, second_halt, halts, restarts,
                  trades, skipped, eligible, curve)


def finish(label, cash, total_costs, second_halt, halts, restarts, trades,
           skipped, eligible, curve):
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "halted": second_halt,
            "halts": halts, "restarts": restarts, "trades": trades,
            "skipped": skipped, "events_eligible": len(eligible),
            "curve": curve}


# ---------------------------------------------------------------- standalone
def standalone_cadence(ticker, filing_date, cad):
    entry = cal.first_day_after(filing_date)
    if entry is None or entry > END:
        return None
    o = cal.open_on(ticker, entry)
    if o is None:
        return None
    sh = (100.0 / 1.001) / o
    xd = exit_day_for(entry, cad)
    truncated = False
    if xd is None:
        xd = cal.days[-1]
        truncated = True
        xp = cal.close_on_or_before(ticker, xd)
    else:
        xp = cal.open_on(ticker, xd)
        if xp is None:
            xp = cal.close_on_or_before(ticker, xd)
    val = sh * xp
    net = val - (val * 0.001 + 0.01)
    so = cal.open_on("SPY", entry)
    ssh = (100.0 / 1.001) / so
    sxp = (cal.open_on("SPY", xd) if not truncated
           else cal.close_on_or_before("SPY", xd))
    sval = ssh * sxp
    snet = sval - (sval * 0.001 + 0.01)
    return {"ticker": ticker, "filing": filing_date, "entry": entry,
            "exit": xd, "net": round(net, 2),
            "ret_pct": round(net - 100.0, 2),
            "spy_net": round(snet, 2), "spy_ret_pct": round(snet - 100.0, 2),
            "excess_pct": round(net - snet, 2), "truncated": truncated}


def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)


def cagr(final):
    days_n = (date(2026, 11, 20) - date(2016, 11, 21)).days
    yrs = days_n / 365.25
    return round(((final / 100.0) ** (1.0 / yrs) - 1.0) * 100, 2) if final > 0 else None


# ---------------------------------------------------------------- placebo sets
def shifted_events(months):
    return sorted([(tk, add_months(fd, months), note) for tk, fd, note in EVENTS],
                  key=lambda e: e[1])


def seeded_events(seed):
    rng = random.Random(1000 + seed)
    offsets = list(range(-18, 0)) + list(range(1, 19))
    out = []
    for tk, fd, note in EVENTS:
        out.append((tk, add_months(fd, rng.choice(offsets)), note))
    return sorted(out, key=lambda e: e[1])


PLACEBO_CANON = shifted_events(6)
SEEDED = {s: seeded_events(s) for s in range(1, 21)}

# ---------------------------------------------------------------- cross-check
# The daily cell must reproduce, to the cent, the v9 engine's own
# run_event_pot (original exit logic + v9 protection) on the same
# extended bars and window — the cadence routing may change nothing at
# the daily rhythm.
_chk_mine = None  # filled after run_pot_cadence is defined (see below)

# ---------------------------------------------------------------- run cells
_ref = eng.run_event_pot(cal_slow, EVENTS, START, END, "DECADE daily reference (v9 engine)")
_mine = run_pot_cadence(EVENTS, "daily", "DECADE daily cross-check")
assert _mine["final"] == _ref["final"] and _mine["costs"] == _ref["costs"], (
    _mine["final"], _ref["final"], _mine["costs"], _ref["costs"])
print(f"CROSS-CHECK OK: daily cadence == v9 engine run_event_pot on decade: "
      f"${_ref['final']} costs=${_ref['costs']} halts={_ref['halts']}", flush=True)

results = {"decade_spy_final": spy_final, "spy_costs": round(spy_costs, 2),
           "overlap_check": overlap,
           "daily_crosscheck_vs_v9_engine": {"final": _ref["final"],
                                             "costs": _ref["costs"],
                                             "match": True},
           "cells": {}}
decade_events = [e for e in EVENTS if START <= e[1] <= END]
print(f"decade events (filings in window): {len(decade_events)} of {len(EVENTS)} frozen", flush=True)

for cad in CADENCES:
    r = run_pot_cadence(EVENTS, cad, f"DECADE {cad} real")
    buys = sum(1 for t in r["trades"] if t[2] == "BUY")
    sa = [standalone_cadence(t, d, cad) for t, d, _ in decade_events]
    sa_full = [x for x in sa if x and not x["truncated"]]
    ssum = eng.summarize(sa_full)
    canon = run_pot_cadence(PLACEBO_CANON, cad, f"DECADE {cad} placebo+6mo")
    seed_finals = {}
    for s in range(1, 21):
        pr = run_pot_cadence(SEEDED[s], cad, f"DECADE {cad} placebo seed {s}")
        seed_finals[str(s)] = pr["final"]
    beaten = sum(1 for v in seed_finals.values() if r["final"] > v)
    cell = {
        "cadence": cad,
        "final": r["final"],
        "cagr_pct": cagr(r["final"]),
        "max_dd_pct": max_dd(r["curve"]),
        "costs": r["costs"],
        "orders": len(r["trades"]),
        "buys": buys,
        "halts": r["halts"],
        "restart": bool(r["restarts"]),
        "restarts": r["restarts"],
        "second_halt": r["halted"],
        "events_eligible": r["events_eligible"],
        "events_traded": buys,
        "events_skipped": len(r["skipped"]),
        "skipped": r["skipped"],
        "per_event": ssum,
        "standalone_rows": sa,
        "placebo_canonical_plus6mo_final": canon["final"],
        "placebo_canonical_plus6mo_halts": canon["halts"],
        "placebo_seed_finals": seed_finals,
        "placebo_beaten": beaten,
        "placebo_note": ("20 seeded date-shift placebos (per-event month "
                         "offset uniform over -18..-1/+1..+18, seed "
                         "1000+s) plus the original chassis's canonical "
                         "+6-month shift placebo, identical mechanics."),
        "trades": r["trades"],
        "equity_curve": r["curve"],
    }
    with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
        json.dump(cell, f, indent=1, default=str)
    results["cells"][cad] = {k: cell[k] for k in
                             ("final", "cagr_pct", "max_dd_pct", "costs",
                              "orders", "events_eligible", "events_traded",
                              "per_event", "placebo_canonical_plus6mo_final",
                              "placebo_beaten")}
    results["cells"][cad]["halts"] = cell["halts"]
    results["cells"][cad]["restart"] = cell["restart"]
    results["cells"][cad]["second_halt"] = cell["second_halt"]
    print(f"{cad}: final=${r['final']} cagr={cell['cagr_pct']} dd={cell['max_dd_pct']} "
          f"costs=${r['costs']} orders={len(r['trades'])} traded={buys}/{r['events_eligible']} "
          f"mean_excess={ssum.get('mean_excess_vs_spy_pct')} beaten={beaten}/20 "
          f"canon_placebo=${canon['final']} halts={len(r['halts'])}", flush=True)

with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
    json.dump(results, f, indent=1, default=str)
print("SWEEP DONE", flush=True)
