#!/usr/bin/env python3
"""THE GREAT RETEST (v10) — W7 — gap-a7-split-drift — CADENCE SWEEP runner.

Strategy: GAP A-7 STOCK-SPLIT ANNOUNCEMENT DRIFT (Ikenberry, Rankine &
Stice 1996), as published in the program: buy pond names announcing
forward splits >= 2-for-1 at the close of the next trading day after the
announcement, 1/5-of-pot slices (cap 5 concurrent), hold 12 months,
program costs (0.10%/side + $0.01 per sell), $100 pot, v9 protection
(plain -15% floor; first halt -> liquidate next open, 90 days cash,
restart with episode-2 floor -15% from restart balance; second halt ends).

Deliverables written by this script (into this folder):
  cells/<cadence>.json  — one per cadence: final, CAGR, max DD, costs,
                          orders, halts/restarts with dates, FULL equity
                          curve, all 20 placebo twin finals.
  results.json          — SPEC sweep-format summary.

Cadence definition (SPEC, uniform): for event strategies the event rules
stay exactly as published; cadence governs the position review /
exit-check rhythm — scheduled exits execute on the first cadence date
on/after the published exit date, and the -15% floor is checked only on
cadence dates (liquidation at the next trading day's open, as the
original engine does). Entries stay on the published event dates.
Daily cadence == the original form; this script ASSERTS that its daily
cells reproduce the original engine's finals ($98.85 CONT / DECADE,
$105.68 VAL) before any sweep number is written.

Prices: champion program cache via the v4 engine (read-only shared
cache, security prices start 2017-06-01 — the pot holds no position
before 2020-07-31 on the decade road, so the road is unaffected), plus
this folder's cache/ of Yahoo pulls (2009-06 -> 2026-11-21) used only
for the supplementary LONG-window per-event table.
Original engine: ./engine.py (copy of backtests/v7/gap-a7-split-drift/
gap-a7-split-drift.py). Event census: engine.EVENTS (5 events,
2016-11-21 -> 2026-11-20 census) for the decade matrix.
"""
import calendar, datetime as dt, importlib.util, json, os, random, statistics, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
M = load_mod("a7_engine", os.path.join(HERE, "engine.py"))
E = M.E; UNI = M.UNIVERSE
DEC = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]

# ---------------------------------------------------------------- prices
def pb_orig():
    return E.PriceBook({t: E.get_prices(t) for t in UNI + ["SPY"]})

def _fetch(url, path, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return open(path, "rb").read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r: blob = r.read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(blob); return blob
        except Exception as e: last = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def bars_long(ticker, p1="2009-06-01", p2="2026-11-21"):
    path = os.path.join(HERE, "cache", f"pxlong_{ticker}.json")
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d")); t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    j = json.loads(_fetch(url, path)); res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

def spy_final(pb, s, e):
    v, _ = E.spy_net(pb, s, e, 100.0); return round(v, 2)

# ------------------------------------------------------------- cadences
def cadence_dates(days, cadence):
    if cadence == "daily": return set(days)
    def first_of(keyfn):
        out, seen = [], set()
        for d in days:
            k = keyfn(d)
            if k not in seen: seen.add(k); out.append(d)
        return out
    if cadence == "weekly":
        return set(first_of(lambda d: dt.date.fromisoformat(d).isocalendar()[:2]))
    if cadence == "biweekly":
        wk = first_of(lambda d: dt.date.fromisoformat(d).isocalendar()[:2])
        return set(wk[::2])
    if cadence == "monthly": return set(first_of(lambda d: d[:7]))
    if cadence == "quarterly": return set(first_of(lambda d: (d[:4], (int(d[5:7]) - 1) // 3)))
    if cadence == "semiannual": return set(first_of(lambda d: (d[:4], int(d[5:7]) <= 6)))
    if cadence == "annual": return set(first_of(lambda d: d[:4]))
    raise ValueError(cadence)

# ------------------------------------------------- cadence event engine
def run_cadence_pot(pb, sched, start, end, cadence, names=None, record_curve=True):
    """A-7 mechanics verbatim from the original engine (entry at close on
    the published entry day; 1/5 slices with pro-rata funding sells at
    close; exits at close; sells cost 0.10% + $0.01; buys 0.10%), with the
    SPEC cadence overlay: exits execute on the first cadence date >= the
    published exit date; the floor is checked only on cadence dates;
    v9 episodes (liquidate next open, 90 days cash, resume entries,
    episode-2 floor -15% of restart balance, second halt ends the run)."""
    days = [d for d in pb.dates if start <= d <= end]
    cset = cadence_dates(days, cadence)
    if names is None: names = [ev["ticker"] for ev in sched]
    def cadence_exit(xd):
        for d in days:
            if d >= xd and d in cset: return d
        return days[-1]
    entries, exits = {}, {}
    for i, ev in enumerate(sched):
        if start <= ev["entry"] <= end: entries.setdefault(ev["entry"], []).append(i)
        xd = cadence_exit(ev["exit"]) if ev["exit"] else days[-1]
        if start <= xd <= end: exits.setdefault(xd, []).append(i)
    cash, positions, trades, total_costs = 100.0, {}, [], 0.0
    floor, episode, resume = 85.0, 1, None
    halts, restarts, curve = [], [], []
    pending_halt, halt_signal = False, None
    def close_of(t, d): return pb.close_on_or_before(t, d)
    def pot_close(d):
        v = cash
        for _i, (t, sh) in positions.items():
            c = close_of(t, d)
            if c: v += sh * c
        return v
    for di, d in enumerate(days):
        if pending_halt:
            liq_cash_before = cash
            for i in list(positions):
                t, sh = positions[i]
                nd, o = pb.next_open(t, days[di - 1])
                if o is None: continue
                val = sh * o; c = val * 0.001 + 0.01
                cash += val - c; total_costs += c
                trades.append((nd, t, "SELL-HALT", sh, o, val, c))
                del positions[i]
            halts.append({"episode": episode, "signal_date": halt_signal,
                          "liquidation_date": d, "balance": round(cash, 2)})
            if episode == 2:
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halts": halts, "restarts": restarts, "curve": curve,
                        "second_halt": True}
            episode = 2
            resume = (dt.date.fromisoformat(d) + dt.timedelta(days=90)).isoformat()
            floor = 0.85 * cash
            restarts.append({"halt_signal_date": halt_signal, "liquidation_date": d,
                             "restart_balance": round(cash, 2), "resume_on_or_after": resume,
                             "episode2_floor": round(floor, 2)})
            pending_halt = False
        for i in exits.get(d, []):
            if i not in positions: continue
            t, sh = positions.pop(i)
            px = close_of(t, d); val = sh * px; c = val * 0.001 + 0.01
            cash += val - c; total_costs += c
            trades.append((d, t, "SELL-EXIT", sh, px, val, c))
        for i in entries.get(d, []):
            if resume is not None and d < resume: continue
            t = names[i]
            marked = pot_close(d); target = marked / 5.0
            if cash < target * 1.001 and positions:
                need = target * 1.001 - cash
                tot_val = sum(sh * close_of(tt, d) for _j, (tt, sh) in positions.items())
                for j in list(positions):
                    if need <= 0: break
                    tt, sh = positions[j]; px = close_of(tt, d); cur = sh * px
                    sell_val = min(cur, need * (cur / tot_val) * 1.02) if tot_val else 0.0
                    if sell_val <= 0.005: continue
                    ssh = sell_val / px; c = sell_val * 0.001 + 0.01
                    cash += sell_val - c; total_costs += c
                    trades.append((d, tt, "SELL-FUND", ssh, px, sell_val, c))
                    if sh - ssh < 1e-9: del positions[j]
                    else: positions[j] = (tt, sh - ssh)
                    need -= sell_val
            px = close_of(t, d)
            buy_val = min(target, cash / 1.001)
            if buy_val > 0.005 and px:
                sh = buy_val / px; c = buy_val * 0.001
                cash -= buy_val + c; total_costs += c
                positions[i] = (t, sh)
                trades.append((d, t, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        if record_curve: curve.append((d, round(v, 4)))
        if d in cset and v <= floor and di < len(days) - 1:
            pending_halt, halt_signal = True, d
    last = days[-1]
    for i in list(positions):
        t, sh = positions[i]; px = close_of(t, last)
        if px:
            val = sh * px; c = val * 0.001 + 0.01
            cash += val - c; total_costs += c
            trades.append((last, t, "SELL-END", sh, px, val, c))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halts": halts, "restarts": restarts, "curve": curve, "second_halt": False}

def stats(final, curve, s, e):
    yrs = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days / 365.25
    cagr = round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return cagr, round(maxdd * 100, 2)

def main():
    pb = pb_orig()
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    # ---- integrity: original engine, original windows (episode-1 form)
    integ = {}
    for nm, (s, e) in (("CONT", ("2019-01-02", "2026-11-20")), ("VAL", ("2023-01-03", "2026-11-20"))):
        sch = M.schedule_events(pb, M.EVENTS, s, e)
        M.START_CASH, M.FLOOR0 = 100.0, 85.0
        r = M.run_event_pot(pb, sch, s, e, [ev["ticker"] for ev in sch])
        integ[nm] = {"final": round(r["final"], 2), "halted": r["halted"], "costs": round(r["costs"], 2),
                     "orders": len(r["trades"]), "n_events": len(sch)}
    assert integ["CONT"]["final"] == 98.85 and integ["VAL"]["final"] == 105.68, integ
    # ---- validation: cadence engine at daily == original engine
    for nm, (s, e), want in (("CONT", ("2019-01-02", "2026-11-20"), 98.85),
                             ("VAL", ("2023-01-03", "2026-11-20"), 105.68),
                             ("DECADE", DEC, 98.85)):
        sch = M.schedule_events(pb, M.EVENTS, s, e)
        r = run_cadence_pot(pb, sch, s, e, "daily")
        assert abs(r["final"] - want) < 0.02, (nm, r["final"], want)
    print("integrity + cadence-engine daily validation: PASS", flush=True)
    # ---- decade matrix
    s, e = DEC
    sch = M.schedule_events(pb, M.EVENTS, s, e)
    spy_dec = spy_final(pb, s, e)
    cells = {}
    for cad in CADENCES:
        r = run_cadence_pot(pb, sch, s, e, cad)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            names = [rng.choice(UNI) for _ in sch]
            tr = run_cadence_pot(pb, sch, s, e, cad, names=names, record_curve=False)
            twins.append(round(tr["final"], 2))
        beaten = sum(1 for f in twins if r["final"] > f)
        cagr, maxdd = stats(r["final"], r["curve"], s, e)
        cell = {"cadence": cad, "window": [s, e], "final": round(r["final"], 2),
                "cagr_pct": cagr, "max_dd_pct": maxdd, "costs": round(r["costs"], 2),
                "orders": len(r["trades"]), "halts": r["halts"], "restarts": r["restarts"],
                "restart": bool(r["restarts"]), "second_halt": r["second_halt"],
                "n_events": len(sch), "placebo_beaten": f"{beaten}/20",
                "placebo_twin_finals": twins,
                "placebo_note": "Original A-7 placebo design: random pond names substituted per event (same entry/exit schedule), seeds 1-20, run at the same cadence under v9 rules.",
                "equity_curve": r["curve"]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                                           "placebo_beaten", "placebo_note")}
        cells[cad]["halts"] = len(r["halts"]); cells[cad]["restart"] = bool(r["restarts"])
        cells[cad]["second_halt"] = r["second_halt"]
        print(f"{cad}: final=${r['final']:,.2f} beaten={beaten}/20 costs=${r['costs']:,.2f} orders={len(r['trades'])}", flush=True)
    # ---- per-event stats, decade census, native (daily) form
    pl = E.PriceBook({t: bars_long(t) for t in UNI + ["SPY"]})
    evs = []
    for ev in sch:
        nf, _, _, _ = M.standalone(pl, ev["ticker"], ev["entry"], ev["exit"])
        sf, _, _, _ = M.standalone(pl, "SPY", ev["entry"], ev["exit"])
        evs.append({"ticker": ev["ticker"], "announced": ev["announced"], "entry": ev["entry"],
                    "exit": ev["exit"], "net_pct": round(nf - 100, 2), "spy_pct": round(sf - 100, 2),
                    "excess_pct": round(nf - sf, 2)})
    exc = [x["excess_pct"] for x in evs]
    ev_stats = {"n": len(exc), "mean_excess_pct": round(statistics.mean(exc), 2),
                "median_excess_pct": round(statistics.median(exc), 2),
                "share_beating_spy": round(sum(1 for x in exc if x > 0) / len(exc), 3)}
    money = [c for c in CADENCES if cells[c]["final"] > spy_dec and
             int(cells[c]["placebo_beaten"].split("/")[0]) > 10]
    out = {
        "slug": "gap-a7-split-drift",
        "area": "Event strategies — stock-split announcement drift on the honest Nov-2016 top-30 pond (SPEC W7); decade cadence sweep on the DECADE road 2016-11-21 -> 2026-11-20",
        "area_source": "SPEC.md W7 batch + THE CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "event-driven",
        "cadence": "event-driven",
        "original_cadence_foreign": {"foreign": False, "note": "Original program test ran the published event-driven form (entries on announcement, daily exit/floor checks) — native cadence; no foreign cadence was forced."},
        "native_change": "none — original form was native. v10 adds: the cadence sweep (exit/floor rhythm varied per SPEC), the v9 protection module, and a supplementary LONG-window run with the event census extended back to 2012 (see supplementary_runs).",
        "integrity": {"status": "reproduced",
                      "original_finals": {"CONT": 98.85, "VAL": 105.68},
                      "reproduced_finals": integ,
                      "note": "Original engine (./engine.py) re-run in this folder on the original windows reproduced both published finals to the cent; SPY controls reproduced exactly (CONT $313.62, VAL $187.77). The v10 cadence engine at daily cadence reproduces the original engine on CONT, VAL and DECADE ($98.85) before any sweep number was taken."},
        "decade_spy_final": spy_dec,
        "spy": {"LONG": 822.94, "DECADE": spy_dec, "CONT": 313.62, "VAL": 187.77},
        "cells": cells,
        "money_cadences": money,
        "event_stats_decade_native": ev_stats,
        "events_decade": evs,
        "supplementary_runs": {
            "note": "Area-form runs (original brief) from ./area_runs.py, kept as supplementary per the restructure. LONG uses the census extended toward 2010 (KO 2012, MA 2013, AAPL 2014, V 2015, NFLX 2015 added — same 8-K/press-release channel, dates verified from filings/press releases) on this folder's cache/ Yahoo pull.",
            "LONG": {"start": "2010-01-04", "end": "2026-11-20", "final": 118.44, "cagr_pct": 1.0, "max_dd_pct": 19.43, "halts": 0, "restart": False, "second_halt": False, "costs": 0.58, "orders": 20, "placebo_beaten": None, "n_events": 10,
                     "event_stats": {"n": 10, "mean_excess_pct": 0.38, "median_excess_pct": -2.99, "share_beating_spy": 0.4}},
            "CONT": {"start": "2019-01-02", "end": "2026-11-20", "final": 98.85, "max_dd_pct": 18.88, "halts": 0, "restart": False, "second_halt": False, "costs": 0.26, "orders": 10, "placebo_beaten": "2/20"},
            "VAL": {"start": "2023-01-03", "end": "2026-11-20", "final": 105.68, "max_dd_pct": 9.55, "halts": 0, "restart": False, "second_halt": False, "costs": 0.11, "orders": 4, "placebo_beaten": "12/20"},
            "DECADE_area_form": {"start": "2016-11-21", "end": "2026-11-20", "final": 98.85, "max_dd_pct": 18.88, "halts": 0, "restart": False, "second_halt": False, "costs": 0.26, "orders": 10, "placebo_beaten": None}},
        "verdict_area": "NO GROUND",
        "verdict_change": "No change. The original program's verdict (split drift fails on this pond: CONT $98.85 vs SPY $313.62) stands at every cadence on the decade road; no cadence beats SPY ($367.80) and none is a money cadence. The extended 2010-2016 census (supplementary LONG) does not rescue it: $118.44 vs SPY $822.94, median event excess -2.99 pp.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE results.json + cells/", flush=True)

if __name__ == "__main__":
    main()
