#!/usr/bin/env python3
"""
CONFIRMATION RUNS — buyback-events, semiannual cadence (v10 retest).

The decade sweep found ONE candidate money cadence on the 8-K-visible
subset: semiannual ($579.81 vs SPY $367.80, 18/20 seeded placebos
beaten, canonical +6mo placebo $277.03 beaten). Under the SPEC's
CONFIRMATION RULE a flipped verdict / new money cadence does not stand
until re-run on the OTHER roads. This script runs the semiannual cell,
with identical mechanics, costs and v9 protections, on:

  CONT  2019-01-02 -> 2026-11-20   (real, canonical +6mo placebo,
                                    20 seeded shift placebos, SPY)
  VAL   2023-01-03 -> 2026-11-20   (same)
  FOLDS fresh $100 per calendar year 2020..2026 (real + canonical
        placebo + SPY), the program's original fold design

LONG (2010 start) CANNOT be run: the audited event census begins with
filings of 2016-11-21 — the original detection scan enumerated 8-Ks
from that date, and no audited pre-2016-11-21 event list exists on any
free channel available to this program. Extending the census to 2010
would require a new multi-year EDGAR audit, not a re-run. That blocker
is stated, not papered over: under the confirmation rule the
semiannual crown therefore remains UNCONFIRMED regardless of what
CONT/VAL/folds show (they also overlap the decade's own years).

Machinery duplicates run_sweep.py's (same data_ext/ bars, same
FastCal price access, same cadence-exit routing, same v9 protection
logic), generalized to arbitrary windows, so this file runs alone.
Simulation only.
"""
import bisect
import importlib.util
import json
import os
import random
import time
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "data_ext")
OUT = os.path.join(HERE, "confirmation")
os.makedirs(OUT, exist_ok=True)
START_CASH = 100.0
FLOOR = 85.0
MAX_POS = 5
HOLD_MONTHS = 12
CAD = "semiannual"


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


def fetch_ext(ticker):
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


bars = {t: fetch_ext(t) for t in TICKERS + ["SPY"]}
pb = champ.PriceBook(bars)


class FastCal:
    def __init__(self, pb):
        self.pb = pb
        self.days = sorted(b["d"] for b in pb.bars["SPY"])
        self._dates = {t: [b["d"] for b in bl] for t, bl in pb.bars.items()}
        self._closes = {t: [b["c"] for b in bl] for t, bl in pb.bars.items()}

    def first_day_after(self, ds):
        i = bisect.bisect_right(self.days, ds)
        return self.days[i] if i < len(self.days) else None

    def open_on(self, t, d):
        b = self.pb.bar(t, d)
        return b["o"] if b else None

    def close_on_or_before(self, t, d):
        dates = self._dates.get(t, [])
        i = bisect.bisect_right(dates, d) - 1
        return self._closes[t][i] if i >= 0 else None


cal = FastCal(pb)


def cadence_dates(days):
    out, seen = [], set()
    for d in days:
        key = (int(d[:4]), (int(d[5:7]) - 1) // 6)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return sorted(out)


def run_pot(events, start, end):
    days = [d for d in cal.days if start <= d <= end]
    cad_dates = cadence_dates(days)

    def exit_day_for(entry):
        target = add_months(entry, HOLD_MONTHS)
        i = bisect.bisect_left(cad_dates, target)
        return cad_dates[i] if i < len(cad_dates) else None

    by_entry, eligible = {}, []
    for tk, fd, note in events:
        if not (start <= fd <= end):
            continue
        entry = cal.first_day_after(fd)
        if entry is None or entry > end:
            continue
        by_entry.setdefault(entry, []).append((tk, fd, note))
        eligible.append((tk, fd))
    cash, positions, trades, skipped = START_CASH, [], [], []
    total_costs, curve = 0.0, []
    episode, floor = 1, FLOOR
    restart_not_before, restart_logged = None, False
    halts, restarts, second_halt = [], [], None

    def close_value(d):
        v = cash
        for p in positions:
            c = cal.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    def done():
        return {"final": round(cash, 2), "costs": round(total_costs, 2),
                "halted": second_halt, "halts": halts, "restarts": restarts,
                "trades": trades, "skipped": skipped,
                "events_eligible": len(eligible), "curve": curve}

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
            buy_val = min(pv / MAX_POS, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "insufficient cash"})
                continue
            sh = buy_val / o
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            xd = exit_day_for(d)
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
                return done()
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
    return done()


def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)


def cagr(final, start, end):
    days_n = (date.fromisoformat(end) - date.fromisoformat(start)).days
    yrs = days_n / 365.25
    return round(((final / 100.0) ** (1.0 / yrs) - 1.0) * 100, 2) if final > 0 else None


def shifted(months):
    return sorted([(tk, add_months(fd, months), n) for tk, fd, n in EVENTS],
                  key=lambda e: e[1])


def seeded(seed):
    rng = random.Random(1000 + seed)
    offsets = list(range(-18, 0)) + list(range(1, 19))
    return sorted([(tk, add_months(fd, rng.choice(offsets)), n)
                   for tk, fd, n in EVENTS], key=lambda e: e[1])


CANON = shifted(6)
SEEDED = {s: seeded(s) for s in range(1, 21)}
summary = {}

for name, ws, we in (("CONT", "2019-01-02", "2026-11-20"),
                     ("VAL", "2023-01-03", "2026-11-20")):
    spy, _ = champ.spy_net(pb, ws, we, 100.0)
    r = run_pot(EVENTS, ws, we)
    canon = run_pot(CANON, ws, we)
    seed_finals = {str(s): run_pot(SEEDED[s], ws, we)["final"]
                   for s in range(1, 21)}
    beaten = sum(1 for v in seed_finals.values() if r["final"] > v)
    payload = {"road": name, "window": [ws, we], "cadence": CAD,
               "spy_final": round(spy, 2), "final": r["final"],
               "cagr_pct": cagr(r["final"], ws, we),
               "max_dd_pct": max_dd(r["curve"]), "costs": r["costs"],
               "orders": len(r["trades"]), "halts": r["halts"],
               "restarts": r["restarts"], "second_halt": r["halted"],
               "events_eligible": r["events_eligible"],
               "events_traded": sum(1 for t in r["trades"] if t[2] == "BUY"),
               "placebo_canonical_plus6mo_final": canon["final"],
               "placebo_seed_finals": seed_finals,
               "placebo_beaten": beaten,
               "equity_curve": r["curve"], "trades": r["trades"]}
    with open(os.path.join(OUT, f"{name.lower()}.json"), "w") as f:
        json.dump(payload, f, indent=1, default=str)
    summary[name] = {k: payload[k] for k in
                     ("spy_final", "final", "cagr_pct", "max_dd_pct", "costs",
                      "orders", "events_eligible", "events_traded",
                      "placebo_canonical_plus6mo_final", "placebo_beaten")}
    print(f"{name}: real=${r['final']} spy=${round(spy,2)} canon_placebo=${canon['final']} "
          f"beaten={beaten}/20 halts={r['halts']}", flush=True)

folds = {}
for y in range(2020, 2027):
    ws = f"{y}-01-01"
    we = "2026-11-20" if y == 2026 else f"{y}-12-31"
    spy, _ = champ.spy_net(pb, ws, we, 100.0)
    r = run_pot(EVENTS, ws, we)
    canon = run_pot(CANON, ws, we)
    folds[str(y)] = {"window": [ws, we], "spy_final": round(spy, 2),
                     "final": r["final"], "costs": r["costs"],
                     "orders": len(r["trades"]), "halts": r["halts"],
                     "restarts": r["restarts"], "second_halt": r["halted"],
                     "events_eligible": r["events_eligible"],
                     "events_traded": sum(1 for t in r["trades"] if t[2] == "BUY"),
                     "placebo_canonical_plus6mo_final": canon["final"],
                     "equity_curve": r["curve"]}
    print(f"fold {y}: real=${r['final']} placebo=${canon['final']} spy=${round(spy,2)} "
          f"halts={r['halts']}", flush=True)
with open(os.path.join(OUT, "folds.json"), "w") as f:
    json.dump(folds, f, indent=1, default=str)
summary["folds"] = {y: {k: v[k] for k in ("final", "spy_final",
                                         "placebo_canonical_plus6mo_final")}
                    for y, v in folds.items()}
with open(os.path.join(OUT, "confirmation_summary.json"), "w") as f:
    json.dump(summary, f, indent=1, default=str)
print("CONFIRMATION DONE", flush=True)
