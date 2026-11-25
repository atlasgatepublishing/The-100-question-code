#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — the ranked aggressive families (v12 wing).
Simulation only. No broker orders.

ASSIGNMENT (holdings-ledger flagged rows + task order): aggressive-v2,
aggressive-v3, v0-aggressive — all rank their qualifying entries by
5-day gain (then volume ratio) and take the top names up to a concurrent
-position cap (native cap = 2 in all three). high-winrate-lab: examined
per shape — H1/H2/H3 do NOT rank (candidates fill free slots in fixed
universe order; their caps are concurrency risk limits, NOT-APPLICABLE
with that reason); H4 DOES rank (its frozen spec orders same-day
candidates by signal-day % gain, largest first, when candidates exceed
the slots) — H4 is swept here.

WHAT VARIES: ONLY the concurrent-positions cap N (the holdings count).
Everything else is each family's frozen form, unchanged:
  - v0-aggressive: position size is intrinsically 1/N of prior-close
    equity (native N=2 -> the frozen 50% each); exits -3%/+6%/fade,
    down-day block, program costs. Protections run BOTH ways:
    (a) era form = its own frozen profit-ladder floor ($85, rising to
        $100 at $125, $125 at $150; breach liquidates at next open and
        ENDS the run);
    (b) house = v9 (plain -15% floor per episode, 90-day sit-out, one
        restart at 85% of restart balance, second breach ends the run)
        — the protection v10 substituted for this family.
  - aggressive-v2: ATR risk sizing unchanged (stop = max(3%, 1.5xATR),
    risk ladder 1%/0.5%/0.25%, position value cap 50% of pot, max 1 new
    entry/day). The drawdown ladder's deep-drawdown step still caps at
    1 position (that is the sizing ladder, not the holdings count).
    Protections BOTH ways: (a) its own frozen form (original engine:
    $85 floor + $125/$150 ladder, breach ends the run); (b) house v9
    (the v10 cadence chassis at daily cadence).
  - aggressive-v3: cfg-driven engine; only cfg["max_positions"] varies
    (the v3 study itself ablated this knob as A10). Configs BASE
    (ATR 1.5x, risk 1%) and COMBO (A3+A6: ATR 1.0x, risk 2% — the
    family's selected form). Protections BOTH ways: (a) house v9 (the
    form its v12 standard roads used); (b) its own frozen form
    (original engine, ladder floor, breach ends the run). Placebos for
    the original-engine form: NOT SUPPORTED — that engine has no
    placebo mode (the v2-design placebo lives in the cadence chassis);
    those cells carry placebo=null with this reason.
  - high-winrate-lab H4: frozen shape unchanged (frac 20% of equity per
    position — a fixed slice, not 1/N; +4% target, -12% stop, SMA20 MA
    exit, gain-ranked overflow). Protection: its frozen form IS v9
    (plain -15% floor, 90-day restart, episode-2 floor) — one form only,
    printed as such.

GRID (pre-registered, identical for every family): counts
1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE. Universe = 10 names for
every family here, so counts 15/20/30 exceed the universe and are
marked UNSUPPORTED (not run); ALL-ELIGIBLE = no cap beyond the universe
itself (= 10; printed as its own cell, identical to count 10 by
construction where the cap is the only binding constraint).

ROADS: all roads each family's v12 record runs on —
  v0: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02,
      VAL 2023-01-03 (all -> 2026-11-20)
  v2: DECADE / CONT / VAL (LONG not runnable: cache begins 2015-06-01,
      200-day warmup — the family's own stated closure)
  v3: LONG / DECADE / CONT / VAL (LONG on the v12 extended-fetch data)
  H4: DECADE / CONT / VAL (LONG impossible in its plumbing: cache
      begins 2015-01-02, 252-session warm-up — its stated closure)

PLACEBOS: 20 seeds per cell where the chassis supports them, each
family's own frozen placebo design, at that cell's own entry frequency.

CONFIRMATION RULE (Terry): a non-native count that beats the native
count on ALL roads under house rules is re-run on different years —
fresh-$100 calendar-year folds 2017-2026 + two continuous half-windows
(2016-11-21->2021-12-31, 2022-01-01->2026-11-20), head-to-head vs the
native count. Only a confirmed winner is a VARIANT-CANDIDATE.

INTEGRITY: every family's native-count cell must reproduce its v12
record to the cent before its sweep numbers count; checks are printed
and saved. Costs everywhere: program costs 0.10%/side + $0.01 sell fee.
Data: shared program caches, READ-ONLY. This folder writes only itself.
"""
import importlib.util, json, os, random, statistics, sys, zlib
from datetime import date, datetime, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V12 = os.path.join(BT, "v12-completions")
COUNTS = [1, 2, 3, 5, 8, 10]          # runnable (universe = 10)
UNSUPPORTED = [15, 20, 30]            # exceed the 10-name universe
SEEDS = list(range(1, 21))
POT0 = 100.0

OUT = {"wing": "holdings-count sweep — ranked aggressive families",
       "grid_counts": ["1", "2", "3", "5", "8", "10", "15", "20", "30", "ALL"],
       "unsupported_counts": {"15": "exceeds 10-name universe",
                              "20": "exceeds 10-name universe",
                              "30": "exceeds 10-name universe"},
       "all_eligible_note": "ALL-ELIGIBLE = cap 10 (the whole universe); "
                            "identical to count 10 wherever the cap is the "
                            "only binding constraint",
       "families": {}}

CURVES = {}
try:
    import pickle as _pk
    with open(os.path.join(HERE, "curves.pkl"), "rb") as _f:
        CURVES.update(_pk.load(_f))
except Exception:
    pass
def save():
    import copy, pickle
    # merge families already on disk (separate per-family invocations)
    try:
        disk = json.load(open(os.path.join(HERE, "results.json")))
        for fk, fv in disk.get("families", {}).items():
            OUT["families"].setdefault(fk, fv)
    except Exception:
        pass
    for fam_name, fam in OUT.get("families", {}).items():
        for ck, cell in fam.get("cells", {}).items():
            if "_curve" in cell:
                CURVES[f"{fam_name}|{ck}"] = cell.pop("_curve")
    with open(os.path.join(HERE, "curves.pkl"), "wb") as f:
        pickle.dump(CURVES, f)
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(strip(OUT), f, indent=1)

def period_distribution(curve, start_cash=POT0):
    """Daily periods (these families' native tempo) — Terry's standard."""
    rets = []
    prev = start_cash
    for _, eq in curve:
        if prev and prev > 0:
            rets.append(eq / prev - 1.0)
        prev = eq
    n = len(rets)
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak = -1.0; last_high = 0; max_gap = 0
    eqs = [eq for _, eq in curve]
    for idx, eq in enumerate(eqs):
        if eq >= peak:
            peak = eq; max_gap = max(max_gap, idx - last_high); last_high = idx
    if eqs:
        max_gap = max(max_gap, len(eqs) - 1 - last_high)
    return {"tempo": "daily", "periods": n,
            "pct_periods_profitable": round(100.0 * prof / n, 1) if n else None,
            "median_period_pct": round(100 * statistics.median(rets), 2) if rets else None,
            "best_period_pct": round(100 * max(rets), 2) if rets else None,
            "worst_period_pct": round(100 * min(rets), 2) if rets else None,
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": max_gap,
            "average_period_pct_SECONDARY_LABELED":
                round(100 * statistics.mean(rets), 2) if rets else None}

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ======================================================================
# v0-aggressive — engine transcribed from its v12 run_roads.py (verified
# there against the original year engine to the cent), parameterized by
# count N and protection form. Era form = run_roads.py exactly at N=2.
# ======================================================================
V0_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
V0_COST = 0.001; V0_FEE = 0.01
V0_FILES = {s: os.path.join(BT, "v7", "long-hold", "data", f"pxfull_{s}.json")
            for s in ["SPY", "AAPL", "MSFT", "AMZN", "NVDA", "TSLA", "AVGO", "META"]}
V0_FILES["AMD"] = os.path.join(BT, "v10-retest", "quality-momentum", "data", "pxfull_AMD.json")
V0_FILES["QQQ"] = os.path.join(BT, "v3", "data_etf", "QQQ.json")

def v0_load():
    data = {}
    for s in V0_UNIVERSE:
        res = json.load(open(V0_FILES[s]))["chart"]["result"][0]
        ts, q = res["timestamp"], res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                continue
            rows.append({"date": datetime.fromtimestamp(t, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%d"),
                         "open": float(q["open"][i]), "high": float(q["high"][i]),
                         "low": float(q["low"][i]), "close": float(q["close"][i]),
                         "volume": float(q["volume"][i] or 0)})
        rows.sort(key=lambda r: r["date"])
        data[s] = rows
    return data

def v0_run(data, win_start, win_end, count, protection,
           placebo_seed=None, entry_schedule=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    idx = {s: {r["date"]: i for i, r in enumerate(rows)} for s, rows in data.items()}
    spy = data["SPY"]
    cal = [r["date"] for r in spy if win_start <= r["date"] <= win_end]
    start_date, end_date = cal[0], cal[-1]
    def bar(s, d):
        i = idx[s].get(d)
        return data[s][i] if i is not None else None
    def prev_bar(s, d):
        i = idx[s].get(d)
        return data[s][i - 1] if i is not None and i > 0 else None
    cash = POT0; positions = {}; trades = 0; round_trips = []
    equity_curve = []; total_costs = 0.0; halted = None
    prev_equity = POT0; no_entry_today = False; entries_made = {}
    # era-ladder state
    floor = 85.0
    # v9 state
    episode = 1; v9_floor = 0.85 * POT0; sit_out_until = None; ended = False
    halts = []
    def equity_at_close(d):
        eq = cash
        for s, p in positions.items():
            b = bar(s, d)
            if b: eq += p["shares"] * b["close"]
        return eq
    def sell(sym, d, price):
        nonlocal cash, total_costs, trades
        p = positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * V0_COST + V0_FEE
        total_costs += cost; cash += gross - cost
        round_trips.append((gross - cost) - p["cost_in"]); trades += 1
    for di, d in enumerate(cal):
        last_day = (d == end_date)
        if protection == "house" and sit_out_until is not None:
            if d < sit_out_until:
                equity_curve.append([d, round(cash, 4)])
                prev_equity = cash
                continue
            # restart episode 2
            episode = 2; v9_floor = 0.85 * cash; sit_out_until = None
        prev_date = None
        if di == 0:
            for r in spy:
                if r["date"] < start_date: prev_date = r["date"]
        else:
            prev_date = cal[di - 1]
        if prev_date and not no_entry_today and not ended and len(positions) < count:
            if rng is None:
                quals = []
                for s in V0_UNIVERSE:
                    if s in positions: continue
                    i = idx[s].get(prev_date)
                    if i is None or i < 20: continue
                    rows = data[s]; b = rows[i]
                    prior10_high = max(r["high"] for r in rows[i - 10:i])
                    gain5 = b["close"] / rows[i - 5]["close"] - 1
                    day_gain = b["close"] / rows[i - 1]["close"] - 1
                    vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
                    vol_ratio = (b["volume"] / vol20) if vol20 else 0
                    if b["close"] >= prior10_high or (day_gain > 0.02 and vol_ratio > 1.5):
                        quals.append((s, gain5, vol_ratio))
                quals.sort(key=lambda x: (-x[1], -x[2]))
                picks = [q[0] for q in quals]
            else:
                want = entry_schedule.get(d, 0) if entry_schedule else 0
                eligible = sorted(s for s in V0_UNIVERSE if s not in positions)
                picks = rng.sample(eligible, min(want, len(eligible))) if want > 0 else []
            slots = count - len(positions); made = 0
            for s in picks[:slots]:
                b = bar(s, d)
                if b is None: continue
                alloc = min(prev_equity / count, cash)
                if alloc < 1.0: break
                price = b["open"]
                shares = alloc / (price * (1 + V0_COST))
                cost_in = shares * price * (1 + V0_COST)
                total_costs += shares * price * V0_COST
                cash -= cost_in
                positions[s] = {"shares": shares, "entry_price": price, "cost_in": cost_in}
                trades += 1; made += 1
            if rng is None: entries_made[d] = made
        for s in list(positions.keys()):
            b = bar(s, d)
            if b is None: continue
            p = positions[s]
            stop = p["entry_price"] * 0.97; target = p["entry_price"] * 1.06
            if b["low"] <= stop:
                sell(s, d, b["open"] if b["open"] < stop else stop)
            elif b["high"] >= target:
                sell(s, d, b["open"] if b["open"] > target else target)
            else:
                pb = prev_bar(s, d)
                if pb and b["close"] < pb["low"]:
                    sell(s, d, b["close"])
        eq = equity_at_close(d)
        equity_curve.append([d, round(eq, 4)])
        if protection == "era":
            if eq >= 150: floor = max(floor, 125.0)
            elif eq >= 125: floor = max(floor, 100.0)
            if eq <= floor and not last_day:
                nxt = cal[di + 1]
                for s in list(positions.keys()):
                    nb = bar(s, nxt)
                    if nb: sell(s, nxt, nb["open"])
                halted = {"trigger_date": d, "liquidation_date": nxt,
                          "balance": round(cash, 2), "floor": floor}
                equity_curve.append([nxt, round(cash, 4)])
                break
        else:  # house v9
            if eq <= v9_floor and not last_day and not ended:
                nxt = cal[di + 1]
                for s in list(positions.keys()):
                    nb = bar(s, nxt)
                    if nb: sell(s, nxt, nb["open"])
                halts.append({"trigger_date": d, "liquidation_date": nxt,
                              "balance": round(cash, 2), "episode": episode})
                equity_curve.append([nxt, round(cash, 4)])
                if episode == 1:
                    sit_out_until = (datetime.strptime(d, "%Y-%m-%d")
                                     + timedelta(days=90)).strftime("%Y-%m-%d")
                    prev_equity = cash
                    continue
                ended = True
                break
        no_entry_today = bool(prev_equity > 0 and (eq / prev_equity - 1) <= -0.04)
        prev_equity = eq
        if last_day:
            for s in list(positions.keys()):
                b = bar(s, d)
                if b: sell(s, d, b["close"])
            equity_curve[-1] = [d, round(cash, 4)]
    final = halted["balance"] if halted else (round(cash, 2) if not ended
            else round(cash, 2))
    if protection == "house" and halts and ended:
        final = round(cash, 2)
    peak, max_dd = POT0, 0.0
    for _, e in equity_curve:
        peak = max(peak, e); max_dd = min(max_dd, e / peak - 1.0)
    wins = [p for p in round_trips if p > 0]
    return {"final": round(final, 2), "max_dd_pct": round(max_dd * 100, 2),
            "orders": trades, "round_trips": len(round_trips),
            "win_rate_pct": round(len(wins) / len(round_trips) * 100, 1) if round_trips else 0,
            "costs": round(total_costs, 2), "halted": halted, "halts": halts,
            "curve": equity_curve, "entries_made": entries_made}

V0_ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21",
            "CONT": "2019-01-02", "VAL": "2023-01-03"}
V0_PUBLISHED_ERA = {"LONG": 83.90, "DECADE": 98.52, "CONT": 83.83, "VAL": 83.07}

def sweep_v0():
    print("=== v0-aggressive ===", flush=True)
    data = v0_load()
    fam = {"native_count": 2, "universe": V0_UNIVERSE,
           "protections": {"era": "its own frozen form: $85 floor + profit ladder "
                                  "($125->$100, $150->$125); breach liquidates at "
                                  "next open and ENDS the run",
                           "house": "v9: plain -15% floor per episode, 90-day "
                                    "sit-out, one restart (episode-2 floor 85% of "
                                    "restart balance), second breach ends the run"},
           "sizing_note": "alloc = min(prior-close equity / N, cash) — the frozen "
                          "50% at native N=2 is 1/N",
           "cells": {}, "integrity": {}}
    for prot in ("era", "house"):
        for road, start in V0_ROADS.items():
            for count in COUNTS:
                label = "ALL" if count == 10 and road == "ALLFLAG" else str(count)
                n = count
                key = f"{prot}|{road}|{n}"
                real = v0_run(data, start, "2026-11-20", n, prot)
                twins = []
                for seed in range(20):
                    tw = v0_run(data, start, "2026-11-20", n, prot,
                                placebo_seed=seed, entry_schedule=real["entries_made"])
                    twins.append(tw["final"])
                beaten = sum(1 for t in twins if real["final"] > t)
                fam["cells"][key] = {"protection": prot, "road": road, "count": n,
                    "final": real["final"], "max_dd_pct": real["max_dd_pct"],
                    "costs": real["costs"], "orders": real["orders"],
                    "round_trips": real["round_trips"],
                    "win_rate_pct": real["win_rate_pct"],
                    "halted": real["halted"], "halts": real["halts"],
                    "placebo_beaten": beaten, "placebo_finals": twins,
                    "_curve": real["curve"]}
                print(f"v0 {key}: ${real['final']:.2f} win {real['win_rate_pct']}% "
                      f"DD {real['max_dd_pct']}% beaten {beaten}/20", flush=True)
            # ALL-ELIGIBLE cell (= cap 10, whole universe)
            src = fam["cells"][f"{prot}|{road}|10"]
            fam["cells"][f"{prot}|{road}|ALL"] = dict(src, count="ALL")
    for road, pub in V0_PUBLISHED_ERA.items():
        got = fam["cells"][f"era|{road}|2"]["final"]
        fam["integrity"][road] = {"published_v12_era_N2": pub, "reproduced": got,
                                  "match": abs(got - pub) < 0.005}
        print(f"v0 integrity era N=2 {road}: published {pub} got {got}", flush=True)
    OUT["families"]["v0-aggressive"] = fam
    save()
    return fam

def v0_house_runner(start, end, count):
    data = v0_house_runner._data
    return v0_run(data, start, end, count, "house")["final"]

# ======================================================================
# aggressive-v2 — original engine (own protection) + v10 cadence chassis
# (house v9, daily). Count enters only via risk_fraction's max_pos.
# ======================================================================
def sweep_v2():
    print("=== aggressive-v2 ===", flush=True)
    m2 = load_module("aggv2_engine", os.path.join(BT, "v2", "aggressive-v2.py"))
    D = m2.load_data()
    class SimN(m2.Sim):
        def __init__(self, D, cal, count, **kw):
            super().__init__(D, cal, **kw); self.count = count
        def risk_fraction(self):
            dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
            if dd >= 0.10: return 0.0025, 1
            if dd >= 0.05: return 0.005, self.count
            return m2.BASE_RISK, self.count
    sys.path.insert(0, os.path.join(BT, "v10-retest", "aggressive-v2"))
    import sweep_aggressive_v2 as sw2
    class CadN(sw2.CadenceSim):
        def __init__(self, D, cal, cad, count, **kw):
            super().__init__(D, cal, cad, **kw); self.count = count
        def risk_fraction(self):
            dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
            if dd >= 0.10: return 0.0025, 1
            if dd >= 0.05: return 0.005, self.count
            return sw2.BASE_RISK, self.count
    roads = {"DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"),
             "VAL": ("2023-01-03", "2026-11-20")}
    fam = {"native_count": 2, "universe": m2.UNIVERSE,
           "protections": {"original": "its own frozen form (original v2 engine): "
                                        "$85 floor + $125/$150 profit ladder; breach "
                                        "ends the run",
                           "house": "v9 via the v10 cadence chassis at daily cadence: "
                                    "plain -15% floor, 90-day sit-out, one restart, "
                                    "second breach ends the run"},
           "sizing_note": "ATR risk sizing unchanged; only the concurrent cap varies "
                          "(drawdown ladder still caps at 1 position at >=10% DD)",
           "long_note": "LONG not runnable: v2 cache begins 2015-06-01 (200-day "
                        "warmup) — the family's own stated closure",
           "cells": {}, "integrity": {}}
    for road, (sd, ed) in roads.items():
        cal = m2.calendar(D, sd, ed)
        cad = sw2.cadence_dates(cal, "daily")
        for n in COUNTS:
            # original protection
            sim = SimN(D, cal, n, mode="v2").run(); st = sim.stats()
            ep = st["counters"]["entries"] / len(cal) if cal else 0
            twins = []
            for seed in SEEDS:
                tw = SimN(D, cal, n, mode="placebo", rng=random.Random(seed),
                          entry_prob=ep).run()
                twins.append(round(tw.stats()["final_balance"], 2))
            beaten = sum(1 for t in twins if st["final_balance"] > t)
            fam["cells"][f"original|{road}|{n}"] = {
                "protection": "original", "road": road, "count": n,
                "final": st["final_balance"], "max_dd_pct": st["max_drawdown_pct"],
                "costs": st["total_costs"], "orders": st["total_orders"],
                "round_trips": st["round_trips"], "win_rate_pct": st["win_rate"],
                "halted": bool(sim.halted), "placebo_beaten": beaten,
                "placebo_finals": twins,
                "_curve": [[d, round(e, 4)] for d, e in sim.equity_curve]}
            print(f"v2 original|{road}|{n}: ${st['final_balance']:.2f} "
                  f"win {st['win_rate']}% beaten {beaten}/20", flush=True)
            # house v9
            cs = CadN(D, cal, cad, n).run(); cst = cs.stats()
            ep9 = cst["counters"]["entries"] / len(cal) if cal else 0
            twins9 = []
            for seed in SEEDS:
                tw = CadN(D, cal, cad, n, placebo_rng=random.Random(seed),
                          entry_prob=min(1.0, ep9)).run()
                twins9.append(round(tw.cash, 2))
            beaten9 = sum(1 for t in twins9 if cst["final"] > t)
            fam["cells"][f"house|{road}|{n}"] = {
                "protection": "house", "road": road, "count": n,
                "final": cst["final"], "max_dd_pct": cst["max_dd_pct"],
                "costs": cst["costs"], "orders": cst["orders"],
                "round_trips": cst["round_trips"],
                "win_rate_pct": cst["win_rate_pct"], "halts": cst["halts"],
                "placebo_beaten": beaten9, "placebo_finals": twins9,
                "_curve": [[d, round(e, 4)] for d, e in cs.equity_curve]}
            print(f"v2 house|{road}|{n}: ${cst['final']:.2f} "
                  f"win {cst['win_rate_pct']}% beaten {beaten9}/20", flush=True)
        for prot in ("original", "house"):
            fam["cells"][f"{prot}|{road}|ALL"] = dict(
                fam["cells"][f"{prot}|{road}|10"], count="ALL")
    fam["integrity"] = {
        "original_N2_DECADE": {"published_v12": 103.80,
            "reproduced": fam["cells"]["original|DECADE|2"]["final"]},
        "original_N2_CONT": {"published_v12": 90.53,
            "reproduced": fam["cells"]["original|CONT|2"]["final"]},
        "original_N2_VAL": {"published_v12": 90.48,
            "reproduced": fam["cells"]["original|VAL|2"]["final"]},
        "house_N2_DECADE": {"published_v10": 103.80,
            "reproduced": fam["cells"]["house|DECADE|2"]["final"]}}
    for k, v in fam["integrity"].items():
        pub = v.get("published_v12", v.get("published_v10"))
        v["match"] = abs(v["reproduced"] - pub) < 0.005
        print(f"v2 integrity {k}: published {pub} got {v['reproduced']}", flush=True)
    fam["_long_data"] = None
    OUT["families"]["aggressive-v2"] = fam
    save()
    # house runner for confirmation
    def runner(start, end, count):
        cal = m2.calendar(D, start, end)
        cad = sw2.cadence_dates(cal, "daily")
        return CadN(D, cal, cad, count).run().stats()["final"]
    fam["_runner_house"] = runner
    return fam

# ======================================================================
# aggressive-v3 — v10 cadence chassis (house v9) for BASE + COMBO, and
# the original v3 engine (its own ladder protection), cfg max_positions.
# ======================================================================
def sweep_v3():
    print("=== aggressive-v3 ===", flush=True)
    sys.path.insert(0, os.path.join(BT, "v10-retest", "aggressive-v3"))
    import sweep_aggressive_v3 as sw3
    m3 = sw3.m
    BASE = dict(m3.BASE_CFG)
    COMBO = dict(m3.BASE_CFG); COMBO.update({"atr_mult": 1.0, "base_risk": 0.02})
    CONFIGS = [("base", BASE), ("combo", COMBO)]
    m3.DATA = os.path.join(BT, "v3", "data")
    D3 = m3.load_data()
    m3.DATA = os.path.join(V12, "aggressive-v3", "data_long")
    DL = m3.load_data()
    roads3 = {"DECADE": ("2016-11-21", "2026-11-20"),
              "CONT": ("2019-01-02", "2026-11-20"),
              "VAL": ("2023-01-03", "2026-11-20")}
    fam = {"native_count": 2, "universe": m3.UNIVERSE if hasattr(m3, "UNIVERSE") else
           ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"],
           "protections": {"house": "v9 via the v10 cadence chassis at daily cadence "
                                    "(the form its v12 standard roads used)",
                           "original": "its own frozen form (original v3 engine): "
                                       "$85 floor + $125/$150 ladder; breach ends "
                                       "the run. Placebos NOT SUPPORTED in this "
                                       "chassis (no placebo mode) — cells carry "
                                       "placebo=null"},
           "configs": {"base": "ATR 1.5x, risk 1% (v2 as coded)",
                       "combo": "A3+A6: ATR 1.0x, risk 2% (the family's selected form)"},
           "cells": {}, "integrity": {}}
    def run_house(D, sd, ed, cfg0, n):
        cal = m3.calendar(D, sd, ed)
        cad = sw3.cadence_dates(cal, "daily")
        cfg = dict(cfg0); cfg["max_positions"] = n
        sim = sw3.CadenceSim(D, cal, cfg, cad).run(); st = sim.stats()
        return sim, st, cal, cad, cfg
    # house v9: LONG on extended data, other roads on v3 cache
    house_roads = dict(roads3); house_roads["LONG"] = ("2010-01-04", "2026-11-20")
    for road, (sd, ed) in house_roads.items():
        D = DL if road == "LONG" else D3
        for cname, cfg0 in CONFIGS:
            for n in COUNTS:
                sim, st, cal, cad, cfg = run_house(D, sd, ed, cfg0, n)
                ep = min(1.0, st["counters"]["entries"] / max(1, len(cal)))
                twins = []
                for seed in SEEDS:
                    tw = sw3.CadenceSim(D, cal, dict(cfg), cad,
                                        placebo_rng=random.Random(seed),
                                        entry_prob=ep).run()
                    twins.append(round(tw.cash, 2))
                beaten = sum(1 for t in twins if st["final"] > t)
                fam["cells"][f"house|{cname}|{road}|{n}"] = {
                    "protection": "house", "config": cname, "road": road, "count": n,
                    "final": st["final"], "max_dd_pct": st["max_dd_pct"],
                    "costs": st["costs"], "orders": st["orders"],
                    "round_trips": st["round_trips"],
                    "win_rate_pct": st["win_rate_pct"], "halts": st["halts"],
                    "placebo_beaten": beaten, "placebo_finals": twins,
                    "_curve": [[d, round(e, 4)] for d, e in sim.equity_curve]}
                print(f"v3 house|{cname}|{road}|{n}: ${st['final']:.2f} "
                      f"win {st['win_rate_pct']}% beaten {beaten}/20", flush=True)
            fam["cells"][f"house|{cname}|{road}|ALL"] = dict(
                fam["cells"][f"house|{cname}|{road}|10"], count="ALL")
    # original protection: v3 cache roads + LONG on extended data
    orig_roads = dict(roads3); orig_roads["LONG"] = ("2010-01-04", "2026-11-20")
    for road, (sd, ed) in orig_roads.items():
        D = DL if road == "LONG" else D3
        cal = m3.calendar(D, sd, ed)
        for cname, cfg0 in CONFIGS:
            for n in COUNTS:
                cfg = dict(cfg0); cfg["max_positions"] = n
                sim = m3.Sim(D, cal, cfg).run(); st = sim.stats()
                fam["cells"][f"original|{cname}|{road}|{n}"] = {
                    "protection": "original", "config": cname, "road": road,
                    "count": n, "final": st["final_balance"],
                    "max_dd_pct": st["max_drawdown_pct"], "costs": st["total_costs"],
                    "orders": st["total_orders"], "round_trips": st["round_trips"],
                    "win_rate_pct": st["win_rate"], "halted": bool(sim.halted),
                    "placebo_beaten": None, "placebo_finals": None,
                    "placebo_note": "original v3 engine has no placebo mode",
                    "_curve": [[d, round(e, 4)] for d, e in sim.equity_curve]}
                print(f"v3 original|{cname}|{road}|{n}: ${st['final_balance']:.2f} "
                      f"win {st['win_rate']}%", flush=True)
            fam["cells"][f"original|{cname}|{road}|ALL"] = dict(
                fam["cells"][f"original|{cname}|{road}|10"], count="ALL")
    fam["integrity"] = {
        "house_combo_N2_DECADE": {"published_v12": 118.56,
            "reproduced": fam["cells"]["house|combo|DECADE|2"]["final"]},
        "house_base_N2_DECADE": {"published_v12": 103.80,
            "reproduced": fam["cells"]["house|base|DECADE|2"]["final"]},
        "house_combo_N2_LONG": {"published_v12": 90.92,
            "reproduced": fam["cells"]["house|combo|LONG|2"]["final"]},
        "house_combo_N2_VAL": {"published_v12": 88.51,
            "reproduced": fam["cells"]["house|combo|VAL|2"]["final"]},
        "original_combo_N2_DECADE_fullperiod": {"published_v3": 118.56,
            "reproduced": fam["cells"]["original|combo|DECADE|2"]["final"]},
        "original_base_N2_VAL_validation": {"published_v3": 90.48,
            "reproduced": fam["cells"]["original|base|VAL|2"]["final"]}}
    for k, v in fam["integrity"].items():
        pub = v.get("published_v12", v.get("published_v3"))
        v["match"] = abs(v["reproduced"] - pub) < 0.005
        print(f"v3 integrity {k}: published {pub} got {v['reproduced']}", flush=True)
    OUT["families"]["aggressive-v3"] = fam
    save()
    def make_runner(cname):
        cfg0 = COMBO if cname == "combo" else BASE
        def runner(start, end, count):
            D = D3
            cal = m3.calendar(D, start, end)
            cad = sw3.cadence_dates(cal, "daily")
            cfg = dict(cfg0); cfg["max_positions"] = count
            return sw3.CadenceSim(D, cal, cfg, cad).run().stats()["final"]
        return runner
    fam["_runners_house"] = {c: make_runner(c) for c, _ in CONFIGS}
    return fam

# ======================================================================
# high-winrate-lab H4 — the one ranked shape. Runner imported from its
# v12 folder (verbatim v9 engine mechanics + v9 protection).
# ======================================================================
def sweep_h4():
    print("=== high-winrate-lab H4 ===", flush=True)
    hw = load_module("hw_v12", os.path.join(V12, "high-winrate-lab",
                                            "high-winrate-lab-v12.py"))
    E = hw.E
    E.CACHE_DIR = os.path.join(BT, "v2", "tournament-data")
    raw = {sym: E.load_symbol(sym) for sym in E.UNIVERSE}
    frames = E.align_frames(raw)
    mkt = E.Market(frames)
    cfg = {k: v for k, v in E.SHAPES["H4"].items() if k != "label"}
    universe = cfg["universe"]
    roads = {"DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
             "CONT": (date(2019, 1, 1), date(2026, 11, 20)),
             "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
    fam = {"native_count": 5, "universe": E.UNIVERSE,
           "disposition": {
               "H1": "NOT-APPLICABLE — no cross-sectional ranking: qualifying "
                     "names fill free slots in fixed universe order (SPY/QQQ "
                     "only); its cap of 2 is a concurrency risk limit, not a "
                     "ranked top-N selection",
               "H2": "NOT-APPLICABLE — no ranking: Bollinger qualifiers fill "
                     "free slots in fixed universe order; cap 5 is a "
                     "concurrency limit, not a ranked selection",
               "H3": "NOT-APPLICABLE — no ranking: down-streak qualifiers fill "
                     "free slots in fixed universe order; cap 5 is a "
                     "concurrency limit, not a ranked selection",
               "H4": "SWEPT — frozen spec ranks same-day candidates by "
                     "signal-day % gain (largest first) when candidates "
                     "exceed the slots (order_by_gain)"},
           "protections": {"house": "v9 — which IS this lab's frozen form "
                                    "(plain -15% floor, 90-day restart, "
                                    "episode-2 floor 85% of restart balance)"},
           "sizing_note": "frac fixed at 20% of equity per position (the frozen "
                          "shape's slice, not 1/N); only the cap varies",
           "cells": {}, "integrity": {}}
    # resume support: preload cells already saved on disk and skip them
    try:
        disk = json.load(open(os.path.join(HERE, "results.json")))
        prev = disk["families"]["high-winrate-lab-H4"]["cells"]
        for k, v in prev.items():
            if "|ALL" not in k:
                fam["cells"][k] = v
        print(f"resume: {len(fam['cells'])} cells preloaded", flush=True)
    except Exception as e:
        print("resume: none", e, flush=True)
    OUT["families"]["high-winrate-lab-H4"] = fam
    save()
    for road, (rs, re_) in roads.items():
        dates, positions = mkt.window(rs, re_)
        for n in COUNTS:
            if f"house|{road}|{n}" in fam["cells"]:
                print(f"H4 house|{road}|{n}: SKIP (saved)", flush=True)
                continue
            kw = dict(cfg); kw["max_positions"] = n
            pf, signals_by_t = hw.run_shape_daily(mkt, "H4", dates, positions,
                                                  POT0, **kw)
            st = hw.cell_stats(pf, dates[0], dates[-1])
            twins = []
            for seed in range(20):
                rng = np.random.default_rng(
                    1000 * seed + zlib.crc32(b"H4|daily"))
                override = {}
                for t, syms in signals_by_t.items():
                    k = min(len(syms), len(universe))
                    if k > 0:
                        override[t] = list(rng.choice(universe, size=k,
                                                      replace=False))
                tpf, _ = hw.run_shape_daily(mkt, "H4", dates, positions, POT0,
                                            signal_override=override, **kw)
                twins.append(hw.cell_stats(tpf, dates[0], dates[-1])["final"])
            beaten = sum(1 for t in twins if st["final"] > t)
            fam["cells"][f"house|{road}|{n}"] = {
                "protection": "house", "road": road, "count": n,
                "final": st["final"], "max_dd_pct": st["max_dd_pct"],
                "costs": st["costs"], "orders": st["orders"],
                "round_trips": st["closed_trades"],
                "win_rate_pct": st["win_rate_pct"],
                "expectancy": st["expectancy"], "halts": st["halts"],
                "placebo_beaten": beaten, "placebo_finals": twins,
                "_curve": st["equity_curve"]}
            print(f"H4 house|{road}|{n}: ${st['final']:.2f} "
                  f"win {st['win_rate_pct']}% beaten {beaten}/20", flush=True)
            save()  # incremental: survive a kill under load
        fam["cells"][f"house|{road}|ALL"] = dict(
            fam["cells"][f"house|{road}|10"], count="ALL")
    fam["integrity"] = {"H4_N5_DECADE": {"published_v9v12": 171.12,
        "reproduced": fam["cells"]["house|DECADE|5"]["final"],
        "win_rate_published": 60.0,
        "win_rate_reproduced": fam["cells"]["house|DECADE|5"]["win_rate_pct"]}}
    v = fam["integrity"]["H4_N5_DECADE"]
    v["match"] = abs(v["reproduced"] - 171.12) < 0.005
    print(f"H4 integrity: published 171.12 got {v['reproduced']}", flush=True)
    # resume support: preload cells already saved on disk and skip them
    try:
        disk = json.load(open(os.path.join(HERE, "results.json")))
        prev = disk["families"]["high-winrate-lab-H4"]["cells"]
        for k, v in prev.items():
            if "|ALL" not in k:
                fam["cells"][k] = v
        print(f"resume: {len(fam['cells'])} cells preloaded", flush=True)
    except Exception as e:
        print("resume: none", e, flush=True)
    OUT["families"]["high-winrate-lab-H4"] = fam
    save()
    def runner(start_s, end_s, count):
        rs = date.fromisoformat(start_s); re_ = date.fromisoformat(end_s)
        dates, positions = mkt.window(rs, re_)
        kw = dict(cfg); kw["max_positions"] = count
        pf, _ = hw.run_shape_daily(mkt, "H4", dates, positions, POT0, **kw)
        return hw.cell_stats(pf, dates[0], dates[-1])["final"]
    fam["_runner_house"] = runner
    return fam

# ======================================================================
# Confirmation + distributions + curve trimming
# ======================================================================
def confirmation(runner, native, cand, fold_years=range(2017, 2027)):
    folds = {}
    for yr in fold_years:
        sd, ed = f"{yr}-01-01", f"{yr}-12-31"
        try:
            folds[str(yr)] = {"candidate": round(runner(sd, ed, cand), 2),
                              "native": round(runner(sd, ed, native), 2)}
        except Exception as e:
            folds[str(yr)] = {"error": str(e)}
    halves = {}
    for lbl, (sd, ed) in {"H1": ("2016-11-21", "2021-12-31"),
                          "H2": ("2022-01-01", "2026-11-20")}.items():
        try:
            halves[lbl] = {"candidate": round(runner(sd, ed, cand), 2),
                           "native": round(runner(sd, ed, native), 2)}
        except Exception as e:
            halves[lbl] = {"error": str(e)}
    wins = sum(1 for v in folds.values()
               if "candidate" in v and v["candidate"] > v["native"])
    hwins = sum(1 for v in halves.values()
                if "candidate" in v and v["candidate"] > v["native"])
    return {"folds": folds, "fold_wins_of_10": wins, "halves": halves,
            "confirmed": wins >= 6 and hwins == 2}

def finish_family(fam, house_prefix_roads, native, runner=None, label=""):
    """house_prefix_roads: list of cell-key prefixes ending with '|' whose
    road segment follows; we instead pass explicit road list + key builder."""
    pass

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    fams = {}
    if which in ("all", "v0"):
        fams["v0"] = sweep_v0()
    if which in ("all", "v2"):
        fams["v2"] = sweep_v2()
    if which in ("all", "v3"):
        fams["v3"] = sweep_v3()
    if which in ("all", "h4"):
        fams["h4"] = sweep_h4()
    save()
    print("sweep cells done", flush=True)

if __name__ == "__main__":
    main()
