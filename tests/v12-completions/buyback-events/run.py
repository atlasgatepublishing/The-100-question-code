#!/usr/bin/env python3
"""
BUYBACK-EVENTS v12 — COMPLETED-CENSUS RUN.

Construction frozen in CONSTRUCTION-SPEC.md before this run existed.
Mechanics inherited unchanged from v6/v10: entry next trading day's open
after the event date; 12-month hold (exit at open of first trading day
on/after entry+12mo); $100 pot, 1/5 slices, max 5 concurrent; costs
0.10%/side + $0.01/share sold; v9 protection module (plain -15% episode-1
floor, first halt -> liquidate next open + 90 calendar days cash +
restart, episode-2 floor -15% from restart balance, second halt ends).

Roads: DECADE 2016-11-21..2026-11-20, CONT 2019-01-02..2026-11-20,
VAL 2023-01-03..2026-11-20 (events dated inside the window only).
Placebos per road: canonical +6-month shift (the family's own control
since v6) + 20 seeded shifts (random.Random(1000+s), per-event offset
uniform over -18..-1/+1..+18 months), identical mechanics.

INTEGRITY GATES (must pass before any completed-census number counts):
  G1: SPY decade on extended bars == $367.80 (v10 SPEC reference).
  G2: the OLD 91-event 8-K census on DECADE == v10 daily cell $441.73.
Prices: v10 data_ext/ (read-only) for its 23 tickers; the 6 recovered
tickers (MSFT, MA, IBM, UNH, MMM, KO) fetched from Yahoo the same way
into this folder's data_ext/.
Simulation only.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import time
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V10DIR = os.path.join(HERE, "..", "..", "v10-retest", "buyback-events")
EXT_OLD = os.path.join(V10DIR, "data_ext")
EXT = os.path.join(HERE, "data_ext")
os.makedirs(EXT, exist_ok=True)

START_CASH = 100.0
FLOOR = 85.0
MAX_POS = 5
HOLD_MONTHS = 12


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = load(os.path.join(V10DIR, "engine.py"), "v10_buyback_engine")
champ = eng.load_champion()
add_months = eng.add_months

CENSUS = json.load(open(os.path.join(HERE, "census.json")))["events"]
EVENTS_NEW = sorted(((e["ticker"], e["date"], e["note"]) for e in CENSUS),
                    key=lambda e: e[1])
EVENTS_OLD = sorted(eng.EVENTS, key=lambda e: e[1])
TICKERS = sorted({t for t, _, _ in EVENTS_NEW})


# ---------------------------------------------------------------- prices
def parse_yahoo(blob):
    j = json.loads(blob)
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


def fetch_ext(ticker):
    old = os.path.join(EXT_OLD, f"px_{ticker}.json")
    if os.path.exists(old) and os.path.getsize(old) > 100:
        with open(old, "rb") as f:
            return parse_yahoo(f.read())
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
        return parse_yahoo(f.read())


bars = {}
for t in TICKERS + ["SPY"]:
    bars[t] = fetch_ext(t)
pb = champ.PriceBook(bars)


class FastCal:
    def __init__(self, pb):
        self.pb = pb
        self.days = sorted(b["d"] for b in pb.bars["SPY"])
        self._dates = {}
        self._closes = {}
        for t, bl in pb.bars.items():
            self._dates[t] = [b["d"] for b in bl]
            self._closes[t] = [b["c"] for b in bl]

    def first_day_after(self, ds):
        i = bisect.bisect_right(self.days, ds)
        return self.days[i] if i < len(self.days) else None

    def first_day_on_or_after(self, ds):
        i = bisect.bisect_left(self.days, ds)
        return self.days[i] if i < len(self.days) else None

    def open_on(self, t, d):
        b = self.pb.bar(t, d)
        return b["o"] if b else None

    def close_on_or_before(self, t, d):
        dates = self._dates.get(t, [])
        i = bisect.bisect_right(dates, d) - 1
        return self._closes[t][i] if i >= 0 else None


cal = FastCal(pb)


# ---------------------------------------------------------------- pot
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
            exit_day = cal.first_day_on_or_after(add_months(d, HOLD_MONTHS))
            if exit_day is None:
                exit_day = days[-1]
            positions.append({"ticker": tk, "shares": sh,
                              "exit_day": exit_day, "entry": d, "filing": fd})
            trades.append([d, tk, "BUY", round(sh, 4), o,
                           round(buy_val, 2), round(c, 2)])
        v = close_value(d)
        curve.append([d, round(v, 4)])
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
                return {"label": label, "final": round(cash, 2),
                        "costs": round(total_costs, 2), "halted": second_halt,
                        "halts": halts, "restarts": restarts,
                        "trades": trades, "skipped": skipped,
                        "events_eligible": len(eligible), "curve": curve}
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
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "halted": second_halt,
            "halts": halts, "restarts": restarts,
            "trades": trades, "skipped": skipped,
            "events_eligible": len(eligible), "curve": curve}


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


def period_record(curve, start):
    """Period-by-period record at the strategy's native tempo (daily
    review) + a monthly aggregation, computed from the saved curve."""
    pts = [(start, START_CASH)] + [(d, v) for d, v in curve]
    daily = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if v0 > 0:
            daily.append((d1, v1 / v0 - 1.0))
    months = {}
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        months[d1[:7]] = (v0, v1)  # overwritten: keeps (month-start, last)
    # rebuild month boundaries properly
    mret = []
    cur_m = None
    m_start_v = START_CASH
    last_v = START_CASH
    for d, v in curve:
        if d[:7] != cur_m:
            if cur_m is not None:
                mret.append((cur_m, last_v / m_start_v - 1.0))
            cur_m = d[:7]
            m_start_v = last_v
        last_v = v
    if cur_m is not None:
        mret.append((cur_m, last_v / m_start_v - 1.0))

    def stats(rets, name):
        rs = sorted(r for _, r in rets)
        n = len(rs)
        if n == 0:
            return {}
        med = rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2
        streak = worst_streak = 0
        for _, r in rets:
            streak = streak + 1 if r < 0 else 0
            worst_streak = max(worst_streak, streak)
        # longest stretch between new highs (in periods)
        peak = -1e18
        last_high = -1
        longest = 0
        vals = [v for _, v in [(None, START_CASH)] + [(d, v) for d, v in curve]] \
            if name == "daily" else None
        return {"periods": n,
                "share_positive_pct": round(100 * sum(1 for r in rs if r > 0) / n, 1),
                "median_pct": round(med * 100, 3),
                "best_pct": round(rs[-1] * 100, 2),
                "worst_pct": round(rs[0] * 100, 2),
                "longest_losing_streak": worst_streak,
                "mean_pct_secondary": round(100 * sum(rs) / n, 3)}

    out = {"daily": stats(daily, "daily"), "monthly": stats(mret, "monthly")}
    # longest stretch between new highs, on the daily curve (trading days)
    peak = START_CASH
    last_high_i = 0
    longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak = v
            longest = max(longest, i - last_high_i)
            last_high_i = i
    longest = max(longest, len(curve) - 1 - last_high_i)
    out["daily"]["longest_stretch_between_new_highs_trading_days"] = longest
    # monthly version
    peak = START_CASH
    mh = []
    seen = {}
    for d, v in curve:
        seen[d[:7]] = v
    mvals = [seen[k] for k in sorted(seen)]
    last_high_i = 0
    longest_m = 0
    peak = START_CASH
    for i, v in enumerate(mvals):
        if v >= peak:
            peak = v
            longest_m = max(longest_m, i - last_high_i)
            last_high_i = i
    longest_m = max(longest_m, len(mvals) - 1 - last_high_i)
    out["monthly"]["longest_stretch_between_new_highs_months"] = longest_m
    return out


def standalone(events, start, end):
    rows = []
    for tk, fd, note in events:
        if not (start <= fd <= end):
            continue
        r = eng.standalone(cal, tk, fd)
        if r:
            r["channel"] = next((e["channel"] for e in CENSUS
                                 if e["ticker"] == tk and e["date"] == fd), "?")
            rows.append(r)
    return rows


ROADS = [("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]


def main():
    # ---- integrity gates ---------------------------------------------
    spy_dec, _ = champ.spy_net(pb, "2016-11-21", "2026-11-20", 100.0)
    print(f"G1 SPY decade: ${round(spy_dec, 2)} (reference $367.80)", flush=True)
    assert round(spy_dec, 2) == 367.80, spy_dec
    old = run_pot(EVENTS_OLD, "2016-11-21", "2026-11-20", "OLD CENSUS DECADE")
    print(f"G2 old-census decade: ${old['final']} (v10 daily cell $441.73)",
          flush=True)
    assert old["final"] == 441.73, old["final"]
    print("INTEGRITY GATES PASS", flush=True)

    results = {"integrity": {"spy_decade": round(spy_dec, 2),
                             "old_census_decade": old["final"]},
               "roads": {}}
    for name, ws, we in ROADS:
        real = run_pot(EVENTS_NEW, ws, we, f"{name} real")
        spy, _ = champ.spy_net(pb, ws, we, 100.0)
        canon_events = [(tk, add_months(fd, 6), note) for tk, fd, note in EVENTS_NEW]
        canon = run_pot(canon_events, ws, we, f"{name} canonical +6mo placebo")
        seed_finals = []
        for s in range(1, 21):
            rng = random.Random(1000 + s)
            offs = [rng.choice([m for m in range(-18, 19) if m != 0])
                    for _ in EVENTS_NEW]
            sev = [(tk, add_months(fd, off), note)
                   for (tk, fd, note), off in zip(EVENTS_NEW, offs)]
            r = run_pot(sev, ws, we, f"{name} seed {s}")
            seed_finals.append(r["final"])
        beaten = sum(1 for f in seed_finals if real["final"] > f)
        road = {"window": [ws, we], "final": real["final"],
                "cagr_pct": cagr(real["final"], ws, we),
                "max_dd_pct": max_dd(real["curve"]),
                "costs": real["costs"], "halts": real["halts"],
                "restarts": real["restarts"],
                "events_eligible": real["events_eligible"],
                "events_traded": sum(1 for t in real["trades"] if t[2] == "BUY"),
                "skipped": real["skipped"], "trades": real["trades"],
                "equity_curve": real["curve"],
                "spy_final": round(spy, 2),
                "placebo_canonical_plus6mo_final": canon["final"],
                "placebo_canonical_halts": canon["halts"],
                "placebo_seed_finals": seed_finals,
                "placebo_beaten_of_20": beaten}
        results["roads"][name] = road
        print(f"{name}: real ${real['final']} vs SPY ${round(spy, 2)}; "
              f"canonical placebo ${canon['final']}; seeds beaten "
              f"{beaten}/20; maxDD {road['max_dd_pct']}%", flush=True)

    rows = standalone(EVENTS_NEW, "2016-11-21", "2026-11-20")
    done = [r for r in rows if not r["truncated"]]
    results["standalone_decade"] = {
        "summary": eng.summarize(done), "n_total": len(rows),
        "n_completed": len(done), "rows": rows}
    print("standalone:", results["standalone_decade"]["summary"], flush=True)

    pr = period_record(results["roads"]["DECADE"]["equity_curve"], "2016-11-21")
    results["period_record_decade"] = pr
    print("period record:", json.dumps(pr), flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
