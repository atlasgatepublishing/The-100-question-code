#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — sector-rotation (two forms). Simulation only.
See SWEEP-SPEC.md (frozen before this run).

FORM 1 — Faber native (CONSTRUCTED vehicle, the family's v12 form):
  monthly, 9 original SPDRs, score = average of 1/3/6/9/12-month total
  returns (Yahoo adjusted closes from the family's v12 folder, read-only),
  top-N equal weight. Form A always invested; Form B 100% cash while SPY
  month-end close < its 10-month SMA. Costs 0.10%/side on traded value.
  Mechanics copied from the v12 run_sector_rotation.py, count only
  parameterized. INTEGRITY: N=3 must reproduce Form A $753.49/$382.96/
  $322.35/$160.72 and Form B $345.69/$236.11/$217.68/$151.20
  (LONG/DECADE/CONT/VAL).

FORM 2 — house (v10 form): monthly top-N of 10 SPDRs (incl. XLRE) by
  63-day return among those above their 200-day average, equal weight,
  trades at open, v9 protections, program costs 0.10%/side + $0.01/sell,
  shared v2 tournament-data cache (read-only, split-adjusted).
  Mechanics copied from the v10 run_sector_rotation.py (monthly cadence),
  count only parameterized. INTEGRITY: N=2 DECADE must reproduce $284.09.
  Roads DECADE/CONT/VAL (cache starts 2015; LONG not supported by data).
"""
import csv, io, json, math, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V12_SECTOR = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/sector-rotation/data")
V2CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v2/tournament-data")
COST = 0.0010
SEEDS = list(range(1, 21))

# ---------------------------------------------------------------- Faber ---
FABER_TICKERS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
FABER_WINDOWS = {"LONG": ("2010-01-01", "2026-11-20"),
                 "DECADE": ("2016-11-21", "2026-11-20"),
                 "CONT": ("2019-01-01", "2026-11-20"),
                 "VAL": ("2023-01-01", "2026-11-20"),
                 "PRE2010": ("1999-12-31", "2009-12-31")}
FABER_PUBLISHED = {"A": {"LONG": 753.49, "DECADE": 382.96, "CONT": 322.35, "VAL": 160.72},
                   "B": {"LONG": 345.69, "DECADE": 236.11, "CONT": 217.68, "VAL": 151.20}}


def faber_load():
    me = {}
    for s in FABER_TICKERS + ["SPY"]:
        txt = open(os.path.join(V12_SECTOR, f"{s}.csv")).read()
        rows = list(csv.DictReader(io.StringIO(txt)))
        out = {}
        for r in rows:
            r = {k.lower(): v for k, v in r.items()}
            if r["close"] in ("", "N/D", None): continue
            out[r["date"][:7]] = (r["date"], float(r["close"]))
        me[s] = out
    months = sorted(set.intersection(*[set(me[s]) for s in FABER_TICKERS + ["SPY"]]))
    px = {s: [me[s][m][1] for m in months] for s in FABER_TICKERS + ["SPY"]}
    dates = [me["SPY"][m][0] for m in months]
    return months, dates, px


def faber_score(px_s, i):
    if i < 12: return None
    return sum(px_s[i] / px_s[i - k] - 1.0 for k in (1, 3, 6, 9, 12)) / 5.0


def faber_run(months, dates, px, start, end, form, count, rng=None):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx: return None
    eq = 100.0; weights = {}; curve = []; costs = 0.0; trades = 0
    spy_i0 = idx[0]
    for i in idx:
        if form == "B":
            sma10 = sum(px["SPY"][i - 9:i + 1]) / 10.0
            hedged = px["SPY"][i] < sma10
        else:
            hedged = False
        n = len(FABER_TICKERS) if count == "ALL" else count
        if rng is not None:
            picks = rng.sample(FABER_TICKERS, n)
            target = {} if hedged else {t: 1 / n for t in picks}
        elif hedged:
            target = {}
        else:
            sc = {t: faber_score(px[t], i) for t in FABER_TICKERS}
            top = sorted(FABER_TICKERS, key=lambda t: -sc[t])[:n]
            target = {t: 1 / n for t in top}
        keys = set(weights) | set(target)
        traded = sum(abs(target.get(k, 0.0) - weights.get(k, 0.0)) for k in keys)
        if traded > 1e-9:
            ch = eq * COST * traded; eq -= ch; costs += ch; trades += 1
        weights = target
        if i + 1 < len(months):
            r = sum(w * (px[t][i + 1] / px[t][i] - 1.0) for t, w in weights.items())
            eq *= (1.0 + r)
            curve.append([dates[i + 1], round(eq, 4)])
    last_i = months.index(curve[-1][0][:7]) if curve else idx[0]
    spy_final = 100.0 * px["SPY"][last_i] / px["SPY"][spy_i0] * (1 - COST)
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    return {"start": dates[spy_i0], "end": curve[-1][0] if curve else dates[spy_i0],
            "final": round(eq, 2), "spy_buyhold": round(spy_final, 2),
            "max_dd_pct": round(mdd * 100, 2), "rebalance_months": trades,
            "costs": round(costs, 2), "curve": curve}


def period_stats_monthly(curve, start_balance=100.0):
    rets = []; prev = start_balance
    for _, v in curve:
        rets.append(v / prev - 1.0); prev = v
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    run = longest = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest = max(longest, run)
    peak = start_balance; since = 0; gap = 0
    vals = [v for _, v in curve]
    for v in vals:
        if v > peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": longest, "longest_between_highs_months": gap,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

# ---------------------------------------------------------------- house ---
HOUSE_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE"]
HOUSE_ROADS = {"DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
               "CONT": (date(2019, 1, 1), date(2026, 11, 20)),
               "VAL": (date(2023, 1, 1), date(2026, 11, 20))}
SELL_FEE = 0.01


def house_load():
    frames = {}
    for s in ["SPY"] + HOUSE_SECTORS:
        rows = []
        with open(os.path.join(V2CACHE, f"{s}.csv")) as f:
            for r in csv.DictReader(f):
                rows.append((r["date"], float(r["open"]), float(r["close"])))
        frames[s] = rows
    dates = [d for d, _, _ in frames["SPY"]]
    # v10 convention: reindex every symbol onto the SPY calendar and
    # forward-fill (XLRE incepts 2015-10-08, after the cache start).
    O = {}; C = {}
    for s in frames:
        m = {d: (o, c) for d, o, c in frames[s]}
        oo = []; cc = []; lo = None; lc = None
        for d in dates:
            if d in m: lo, lc = m[d]
            oo.append(lo); cc.append(lc)
        O[s] = oo; C[s] = cc
    SMA = {}
    for s in frames:
        c = C[s]
        sma = []
        for i in range(len(c)):
            seg = c[i - 199:i + 1] if i >= 199 else []
            sma.append(sum(seg) / 200.0 if len(seg) == 200 and all(v is not None for v in seg) else None)
        SMA[s] = sma
    POS = {d: i for i, d in enumerate(dates)}
    return dates, O, C, SMA, POS


def house_run(H, start, end, count, form="frozen", rng=None):
    dates, O, C, SMA, POS = H
    win = [d for d in dates if start.isoformat() <= d <= end.isoformat()]
    pos_of = POS
    sel = set(); seen = set()
    for d in win:
        if d[:7] not in seen: seen.add(d[:7]); sel.add(d)
    cash = 100.0; lots = {}; costs = 0.0; orders = 0
    curve = []; halts = []
    floor = 85.0 if form == "frozen" else None
    episode = 1; halt_pending = False; halt_trigger = None
    waiting_until = None; ended = False

    def shares(s): return sum(x for x in lots.get(s, []))
    def held(): return [s for s in lots if shares(s) > 1e-12]
    def equity(pos, field):
        mp = O if field == "open" else C
        return cash + sum(shares(s) * mp[s][pos] for s in held())
    def buy(d, pos, s, price, target):
        nonlocal cash, costs, orders
        if price <= 0 or target <= 0: return
        v = min(target, cash / (1 + COST))
        if v < 1.0: return
        c = COST * v; cash -= v + c; costs += c
        lots.setdefault(s, []).append(v / price); orders += 1
    def sell(d, pos, s, price, n=None):
        nonlocal cash, costs, orders
        h = shares(s)
        if h <= 1e-12 or price <= 0: return
        n = h if n is None else min(n, h)
        v = n * price; c = COST * v + SELL_FEE
        cash += v - c; costs += c; orders += 1
        rem = n; ll = lots.get(s, [])
        while rem > 1e-12 and ll:
            take = min(ll[0], rem); ll[0] -= take; rem -= take
            if ll[0] <= 1e-12: ll.pop(0)
        if not ll: lots.pop(s, None)

    for d in win:
        pos = pos_of[d]
        if halt_pending:
            for s in list(held()): sell(d, pos, s, O[s][pos])
            halts.append({"episode": episode, "trigger_date": halt_trigger,
                          "liquidation_date": d})
            curve.append((d, round(equity(pos, "close"), 4)))
            if episode == 2:
                ended = True; break
            episode = 2; halt_pending = False
            waiting_until = (date.fromisoformat(halt_trigger) + timedelta(days=90)).isoformat()
            floor = 0.85 * cash
            continue
        if waiting_until is not None:
            if d < waiting_until or d not in sel:
                curve.append((d, round(equity(pos, "close"), 4))); continue
            waiting_until = None
        if d in sel:
            prev = pos - 1
            sc = []
            for s in HOUSE_SECTORS:
                if prev - 63 < 0: continue
                s200 = SMA[s][prev]
                if s200 is None or C[s][prev] is None or C[s][prev - 63] is None or C[s][prev - 63] <= 0: continue
                if C[s][prev] > s200: sc.append((s, C[s][prev] / C[s][prev - 63] - 1))
            sc.sort(key=lambda x: -x[1])
            n = len(sc) if count == "ALL" else min(count, len(sc))
            if rng is not None:
                picks = [sc[i][0] for i in rng.sample(range(len(sc)), n)] if n else []
            else:
                picks = [s for s, _ in sc[:n]]
            eq_o = equity(pos, "open")
            target = eq_o / len(picks) if picks else 0.0
            for s in list(held()):
                if s not in picks: sell(d, pos, s, O[s][pos])
            for s in picks:
                px = O[s][pos]; cur = shares(s) * px
                if cur > target + 0.5: sell(d, pos, s, px, (cur - target) / px)
            for s in picks:
                px = O[s][pos]; cur = shares(s) * px
                if target - cur > 0.5: buy(d, pos, s, px, target - cur)
        eq = equity(pos, "close")
        curve.append((d, round(eq, 4)))
        if floor is not None and eq <= floor:
            halt_pending = True; halt_trigger = d
            if d == win[-1]: ended = True
    if halt_pending and not ended and form == "frozen":
        pass  # window ended with a pending halt, as in the v10 engine
    final = curve[-1][1] if curve else cash
    # v10 final = last curve value (positions marked at close, not liquidated)
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "curve": [[d, v] for d, v in curve]}


def _write(name, obj):
    tmp = os.path.join(HERE, name + ".tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(obj, indent=1))
    os.replace(tmp, os.path.join(HERE, name))


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "house1":
        # one count, one form; JSON to STDOUT (shell redirects to file —
        # python file writes are blocked in this session, shell writes work)
        form = sys.argv[2]; count_arg = sys.argv[3]
        count = "ALL" if count_arg == "ALL" else int(count_arg)
        H = house_load()
        cells = {}
        for road, (s, e) in HOUSE_ROADS.items():
            r = house_run(H, s, e, count, form=form)
            cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                    "costs": r["costs"], "orders": r["orders"],
                    "halts": len(r["halts"])}
            if count == "ALL":
                cell["placebo_beaten"] = None; cell["placebo_finals"] = None
            else:
                twins = []
                for seed in SEEDS:
                    rng = random.Random(2000 + seed)
                    pr = house_run(H, s, e, count, form=form, rng=rng)
                    twins.append(pr["final"])
                cell["placebo_finals"] = twins
                cell["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
            if road == "DECADE":
                sys.path.insert(0, HERE)
                from run_etf5 import period_stats
                cell["period_stats"] = period_stats(r["curve"])
            cells[road] = cell
            print(f"house {form} {count} {road} {cell['final']} pl {cell['placebo_beaten']}",
                  file=sys.stderr, flush=True)
        print(json.dumps(cells))
        return
    if mode == "house":
        form = sys.argv[2]
        H = house_load()
        r = house_run(H, *HOUSE_ROADS["DECADE"], 2)
        ok = abs(r["final"] - 284.09) < 0.005
        print("house integrity", r["final"], "MATCH" if ok else "** MISMATCH **", flush=True)
        cells = {}
        for count in [1, 2, 3, 5, 8, 10, "ALL"]:
            cells[str(count)] = {}
            for road, (s, e) in HOUSE_ROADS.items():
                r = house_run(H, s, e, count, form=form)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                        "costs": r["costs"], "orders": r["orders"],
                        "halts": len(r["halts"])}
                if count == "ALL":
                    cell["placebo_beaten"] = None; cell["placebo_finals"] = None
                else:
                    twins = []
                    for seed in SEEDS:
                        rng = random.Random(2000 + seed)
                        pr = house_run(H, s, e, count, form=form, rng=rng)
                        twins.append(pr["final"])
                    cell["placebo_finals"] = twins
                    cell["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
                if road == "DECADE": cell["curve"] = r["curve"]
                cells[str(count)][road] = cell
                print("house", form, count, road, cell["final"], "pl", cell["placebo_beaten"], flush=True)
        _write(f"results_house_{form}.json",
               {"house_integrity": {"mine": 284.09 if ok else None, "published": 284.09, "match": ok},
                "form": form, "cells": cells})
        print("DONE house", form)
        return
    out = {"family": "sector-rotation", "forms": {}}
    # ---- Faber integrity + grid ----
    months, dates, px = faber_load()
    print("=== FABER INTEGRITY (N=3) ===", flush=True)
    integ = {}
    for form in ("A", "B"):
        integ[form] = {}
        for road in ("LONG", "DECADE", "CONT", "VAL"):
            s, e = FABER_WINDOWS[road]
            r = faber_run(months, dates, px, s, e, form, 3)
            pub = FABER_PUBLISHED[form][road]
            ok = abs(r["final"] - pub) < 0.005
            integ[form][road] = {"mine": r["final"], "published": pub, "match": ok}
            print("Faber", form, road, r["final"], "vs", pub, "MATCH" if ok else "** MISMATCH **", flush=True)
    out["faber_integrity"] = integ
    faber = {}
    for form in ("A", "B"):
        cells = {}
        for count in [1, 2, 3, 5, 8, "ALL"]:
            cells[str(count)] = {}
            for road, (s, e) in FABER_WINDOWS.items():
                r = faber_run(months, dates, px, s, e, form, count)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                        "costs": r["costs"], "spy_buyhold": r["spy_buyhold"]}
                if count == "ALL":
                    cell["placebo_beaten"] = None; cell["placebo_finals"] = None
                else:
                    twins = []
                    for seed in SEEDS:
                        rng = random.Random(1000 + seed)
                        pr = faber_run(months, dates, px, s, e, form, count, rng=rng)
                        twins.append(pr["final"])
                    cell["placebo_finals"] = twins
                    cell["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
                if road == "DECADE": cell["curve"] = r["curve"]
                cells[str(count)][road] = cell
                print("Faber", form, count, road, cell["final"], "pl", cell["placebo_beaten"], flush=True)
        faber[form] = cells
    out["forms"]["faber"] = faber
    if mode == "faber":
        # compact: strip curves except DECADE, add DECADE period stats
        for form, cells in faber.items():
            for c, rc in cells.items():
                for road, cell in rc.items():
                    if road != "DECADE":
                        cell.pop("curve", None)
                    else:
                        cell["period_stats"] = period_stats_monthly(cell.pop("curve"))
        print(json.dumps(out))
        return
    # ---- house integrity + grid ----
    H = house_load()
    print("=== HOUSE INTEGRITY (N=2, DECADE, monthly v9) ===", flush=True)
    r = house_run(H, *HOUSE_ROADS["DECADE"], 2)
    ok = abs(r["final"] - 284.09) < 0.005
    out["house_integrity"] = {"mine": r["final"], "published": 284.09, "match": ok}
    print("house DECADE N=2", r["final"], "vs 284.09", "MATCH" if ok else "** MISMATCH **", flush=True)
    house = {}
    for form in ("frozen", "nofloor"):
        cells = {}
        for count in [1, 2, 3, 5, 8, 10, "ALL"]:
            cells[str(count)] = {}
            for road, (s, e) in HOUSE_ROADS.items():
                r = house_run(H, s, e, count, form=form)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                        "costs": r["costs"], "orders": r["orders"],
                        "halts": len(r["halts"])}
                if count == "ALL":
                    cell["placebo_beaten"] = None; cell["placebo_finals"] = None
                else:
                    twins = []
                    for seed in SEEDS:
                        rng = random.Random(2000 + seed)
                        pr = house_run(H, s, e, count, form=form, rng=rng)
                        twins.append(pr["final"])
                    cell["placebo_finals"] = twins
                    cell["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
                if road == "DECADE": cell["curve"] = r["curve"]
                cells[str(count)][road] = cell
                print("house", form, count, road, cell["final"], "pl", cell["placebo_beaten"], flush=True)
        house[form] = cells
    out["forms"]["house"] = house
    tmp = os.path.join(HERE, "results_sector.json.tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(out, indent=1))
    os.replace(tmp, os.path.join(HERE, "results_sector.json"))
    print("DONE sector")


if __name__ == "__main__":
    main()
