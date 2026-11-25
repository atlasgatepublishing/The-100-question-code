#!/usr/bin/env python3
"""CADENCE GRID — canslim-oneil-judgment (JUDGMENT-CONSTRUCTED CAN SLIM).
Second-Chance Protocol slice. DECADE 2016-11-21 -> 2026-11-20.
Imports the family's frozen run_judgment.py data/signal machinery
(read-only) and re-runs its simulation with CADENCE GATING (v10 uniform
definition for event-driven systems): the engine walks every trading day
(day counters, highs and the $85 floor are daily, exactly as frozen), but
entries, exit checks and pyramiding fire ONLY on cadence dates. Signals
are the frozen daily-computed RS / market-state / breakout series, read
on the cadence dates. Native cadence = daily.
Costs/floor identical to the frozen spec (0.1%/side + $0.01 sell fee,
plain $85 floor, halt ends the run — the judgment engine's own form).
Placebos: 20 seeds per cell, the engine's own entry-date placebo design,
re-based on each cadence cell's real entry dates.
The gated simulator below is the frozen simulate() with an eval_set gate
added at the exit / pyramid / entry blocks and nowhere else.
"""
import importlib.util, json, os, random
from bisect import bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/canslim-oneil-judgment/run_judgment.py")

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

M = load("canslim_engine", BASE)
import sys as _sys
_sys.modules["canslim_engine"] = M
START_CASH, FLOOR = M.START_CASH, M.FLOOR
BUY_COST, SELL_COST, SELL_FEE = M.BUY_COST, M.SELL_COST, M.SELL_FEE
MAX_POS, POS_FRAC, PILOT_FRAC = M.MAX_POS, M.POS_FRAC, M.PILOT_FRAC
STOP, PROFIT = M.STOP, M.PROFIT
START, END = "2016-11-21", "2026-11-20"
CONT = ("2019-01-02", "2026-11-20")
CADENCES = ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]

def cadence_dates(master, cad, start, end):
    days = [d for d in master if start <= d <= end]
    if cad == "daily": return set(days)
    out, seen = set(), set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        iso = date.fromisoformat(d).isocalendar()
        if cad == "weekly": k = (iso[0], iso[1])
        elif cad == "biweekly": k = (iso[0], iso[1] // 2)
        elif cad == "monthly": k = (y, m)
        elif cad == "quarterly":
            if m not in (1,4,7,10): continue
            k = (y, m)
        elif cad == "semiannual":
            if m not in (1,7): continue
            k = (y, m)
        elif cad == "annual":
            if m != 1: continue
            k = (y,)
        if k not in seen: seen.add(k); out.add(d)
    return out

def simulate_gated(days, series_by, rs, mstates, cands, funds, start, end,
                   eval_set, placebo_seed=None, real_entries=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    pos = {}
    curve, trades = [], []
    total_costs = 0.0
    halted = None
    entries_made = []
    entry_plan = None
    if rng is not None:
        entry_plan = {}
        for (d, _t, _f) in real_entries:
            entry_plan.setdefault(d, []).append(_f)

    def equity(d):
        v = cash
        for t, p in pos.items():
            s = series_by[t]
            i = s.idx.get(d)
            if i is None:
                j = bisect_right(s.dates, d) - 1
                px = s.c[j] if j >= 0 else 0.0
            else:
                px = s.c[i]
            v += p["shares"] * px
        return v

    for d in days:
        if not (start <= d <= end):
            continue
        is_eval = d in eval_set
        # ---- exits (gated: checked only on cadence dates; day counters daily)
        for t in list(pos):
            s = series_by[t]
            i = s.idx.get(d)
            if i is None:
                continue
            p = pos[t]
            if d <= p["entry_date"]:
                continue
            p["days"] += 1
            bar = s.bars[i]
            p["hi"] = max(p.get("hi", p["fill"]), bar["c"])
            if not p.get("exc") and bar["c"] >= p["fill"] * 1.40:
                p["exc"] = True
            if not p["eight"] and p["days"] <= 15 and bar["c"] >= p["fill"] * 1.20:
                p["eight"] = True
            if not is_eval:
                continue
            sell_px, why = None, None
            if p.get("exc"):
                stop_px = p["hi"] * (1 - STOP)
            else:
                stop_px = p["fill"] * (1 - STOP)
            ma50 = sum(s.c[i - 49:i + 1]) / 50 if i >= 49 else None
            gain = bar["c"] / p["fill"] - 1
            if bar["l"] <= stop_px:
                sell_px = bar["o"] if bar["o"] < stop_px else stop_px
                why = "stop7.5" if not p.get("exc") else "trail7.5-exc"
            elif (p["days"] >= 40 and gain >= 0.25 and ma50
                    and i >= 10 and s.c[i] / s.c[i - 10] - 1 >= 0.25
                    and bar["c"] >= ma50 * 1.15):
                sell_px, why = bar["c"], "climax"
            elif p["eight"] and p["days"] >= 40:
                if ma50 and bar["c"] < ma50:
                    sell_px, why = bar["c"], "eightwk-ma50"
            elif (p["days"] >= 40 and gain >= 0.10 and ma50
                    and bar["c"] < ma50 and i >= 50
                    and bar["v"] >= 1.5 * (sum(s.v[i - 50:i]) / 50)):
                sell_px, why = bar["c"], "ma50-break-hivol"
            elif not p["eight"] and not p.get("exc") and bar["c"] >= p["fill"] * (1 + PROFIT):
                sell_px, why = bar["c"], "profit22.5"
            if sell_px is not None:
                val = p["shares"] * sell_px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", sell_px, val, why))
                del pos[t]
        # ---- floor (daily, as frozen)
        eq = equity(d)
        if eq <= FLOOR:
            for t in list(pos):
                s = series_by[t]
                j = bisect_right(s.dates, d) - 1
                px = s.c[j] if j >= 0 else 0.0
                val = pos[t]["shares"] * px
                cst = val * SELL_COST + SELL_FEE if val > 0 else 0.0
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", px, val, "floor"))
                del pos[t]
            halted = d
            curve.append((d, cash))
            break
        if is_eval:
            # ---- pyramiding (gated)
            for t in list(pos):
                pp = pos[t]
                if pp.get("added"):
                    continue
                ss = series_by[t]
                ii = ss.idx.get(d)
                if ii is None or d <= pp["entry_date"]:
                    continue
                ei = ss.idx[pp["entry_date"]]
                if ss.c[ii] >= pp["fill"] * 1.05 and ss.c[ii] >= max(ss.c[ei:ii + 1]):
                    px = ss.c[ii]
                    budget = min(0.10 * equity(d), cash / (1 + BUY_COST))
                    if budget >= 1.0:
                        sh = budget / px
                        cst = budget * BUY_COST
                        cash -= budget + cst
                        total_costs += cst
                        newsh = pp["shares"] + sh
                        pp["fill"] = (pp["shares"] * pp["fill"] + sh * px) / newsh
                        pp["shares"] = newsh
                        pp["hi"] = max(pp.get("hi", px), px)
                        pp["added"] = True
                        trades.append((d, t, "BUY", px, budget, "pyramid-add"))
            # ---- entries (gated)
            if rng is None:
                tier = mstates.get(d, 0)
                if tier and len(pos) < MAX_POS:
                    frac = POS_FRAC if tier == 2 else PILOT_FRAC
                    day_cands = []
                    for t, cd in cands.items():
                        if d in cd and t not in pos:
                            r = rs.get(d, {}).get(t)
                            if r is not None and r >= 80 and funds[t].fund_ok(d):
                                day_cands.append((r, t))
                    day_cands.sort(reverse=True)
                    for r, t in day_cands:
                        if len(pos) >= MAX_POS:
                            break
                        s = series_by[t]
                        px = s.bars[s.idx[d]]["c"]
                        budget = min(frac * equity(d), cash / (1 + BUY_COST))
                        if budget < 1.0:
                            break
                        sh = budget / px
                        cst = budget * BUY_COST
                        cash -= budget + cst
                        total_costs += cst
                        pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                                  "days": 0, "eight": False, "added": False,
                                  "exc": False, "hi": px}
                        trades.append((d, t, "BUY", px, budget, f"rs{r}t{tier}"))
                        entries_made.append((d, t, frac))
            else:
                for frac in entry_plan.get(d, []):
                    if len(pos) >= MAX_POS:
                        break
                    pool = [t for t, s in series_by.items()
                            if d in s.idx and s.idx[d] >= 252 and t not in pos]
                    if not pool:
                        break
                    t = rng.choice(pool)
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    budget = min(frac * equity(d), cash / (1 + BUY_COST))
                    if budget < 1.0:
                        break
                    sh = budget / px
                    cst = budget * BUY_COST
                    cash -= budget + cst
                    total_costs += cst
                    pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                              "days": 0, "eight": False, "added": False,
                              "exc": False, "hi": px}
                    trades.append((d, t, "BUY", px, budget, "placebo"))
                    entries_made.append((d, t, frac))
        curve.append((d, equity(d)))
    if halted is None:
        last_d = days[-1] if days else end
        for t in list(pos):
            s = series_by[t]
            if s.dates and s.dates[-1] >= end:
                px = s.c[s.idx[end]] if end in s.idx else s.c[-1]
                val = pos[t]["shares"] * px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((end, t, "SELL", px, val, "end"))
            else:
                trades.append((end, t, "SELL", 0.0, 0.0, "vanished-zero"))
            del pos[t]
        if curve:
            curve[-1] = (curve[-1][0], cash)
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted,
            "max_dd_pct": round(mdd * 100, 2),
            "curve": [[d, round(v, 2)] for d, v in curve],
            "trades": trades, "entries": entries_made}

def period_stats(curve, eval_dates_sorted):
    closes = dict(curve)
    pts = [(d, closes[d]) for d in eval_dates_sorted if d in closes]
    if curve and (not pts or pts[-1][0] != curve[-1][0]):
        pts.append(curve[-1])
    if len(pts) < 2: return {"n_periods": 0}
    rets = [(d1, v1/v0-1) for (d0,v0),(d1,v1) in zip(pts, pts[1:]) if v0]
    n = len(rets); srt = sorted(r for _,r in rets)
    med = srt[n//2] if n%2 else (srt[n//2-1]+srt[n//2])/2
    longest = cur = 0
    for _,r in rets:
        cur = cur+1 if r < 0 else 0; longest = max(longest, cur)
    peak, last_high, longest_gap = -1, 0, 0
    for i,(d,v) in enumerate(pts):
        if v >= peak: peak, last_high = v, i
        longest_gap = max(longest_gap, i-last_high)
    return {"n_periods": n, "pct_profitable": round(100*sum(1 for _,r in rets if r>0)/n,1),
            "median_period_pct": round(med*100,3),
            "mean_period_pct_secondary": round(100*sum(r for _,r in rets)/n,3),
            "best_period_pct": round(max(r for _,r in rets)*100,2),
            "worst_period_pct": round(min(r for _,r in rets)*100,2),
            "longest_losing_streak": longest, "longest_between_new_highs_periods": longest_gap}


def _one_ticker(t):
    bars = M.load_bars(t)
    if not bars or len(bars) < 300: return t, None
    facts = M.load_facts_for(t)
    if facts is None and t != "SPY": return t, None
    s = M.Series(bars)
    if t == "SPY":
        return t, (s, None, None)
    return t, (s, M.Fund(facts), M.breakout_candidates(s))

_CTX = {}

def _init(ctx):
    global _CTX
    _CTX = ctx

def _task(job):
    cad, seed = job
    ctx = _CTX
    r = simulate_gated(ctx["days"], ctx["series_by"], ctx["rs"], ctx["mstates"],
                       ctx["cands"], ctx["funds"], ctx["start"], ctx["end"],
                       ctx["eval_sets"][cad],
                       placebo_seed=seed,
                       real_entries=ctx["real_entries"].get(cad) if seed is not None else None)
    return cad, seed, r

def main():
    import pickle
    from multiprocessing import Pool
    cache = os.path.join(HERE, "inputs_cache.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as fh:
            series_by, funds, rs, mstates, cands, master = pickle.load(fh)
        print("loaded inputs from cache", flush=True)
    else:
        from multiprocessing import Pool as _Pool
        series_by, funds, cands = {}, {}, {}
        with _Pool(processes=8) as pool:
            for t, res in pool.imap_unordered(_one_ticker, list(M.lr.POOL) + ["SPY"]):
                if res is None: continue
                s, fnd, cd = res
                series_by[t] = s; funds[t] = fnd
                if cd is not None: cands[t] = cd
        spy = series_by["SPY"]
        master = spy.dates
        rs = M.compute_rs({t:s for t,s in series_by.items() if t != "SPY"}, master)
        mstates = M.market_states(spy)
        with open(cache, "wb") as fh:
            pickle.dump((series_by, funds, rs, mstates, cands, master), fh, protocol=4)
        print("precomputed + cached inputs", flush=True)
    print(f"universe {len(series_by)-1} names", flush=True)

    def build_ctx(start, end, cadences):
        days = [d for d in master if d <= end]
        return {"days": days, "series_by": series_by, "rs": rs, "mstates": mstates,
                "cands": cands, "funds": funds, "start": start, "end": end,
                "eval_sets": {c: cadence_dates(master, c, start, end) for c in cadences},
                "real_entries": {}}

    def run_window(start, end, cadences):
        ctx = build_ctx(start, end, cadences)
        cells = {}
        # real runs first (sequential, they define placebo entry dates)
        for cad in cadences:
            r = simulate_gated(ctx["days"], series_by, rs, mstates, cands, funds,
                               start, end, ctx["eval_sets"][cad])
            ctx["real_entries"][cad] = r["entries"]
            cells[cad] = {"real": r}
            print(f"{start} {cad} REAL: ${r['final']} entries {len(r['entries'])}", flush=True)
        jobs = [(cad, seed) for cad in cadences for seed in range(20)]
        with Pool(processes=6, initializer=_init, initargs=(ctx,)) as pool:
            for cad, seed, pr in pool.imap_unordered(_task, jobs):
                cells[cad].setdefault("pfin", []).append(pr["final"])
        out_cells = {}
        for cad in cadences:
            r = cells[cad]["real"]; pfin = cells[cad]["pfin"]
            beaten = sum(1 for v in pfin if r["final"] > v)
            ev = ctx["eval_sets"][cad]
            out_cells[cad] = {"final": r["final"], "costs": r["costs"], "orders": r["orders"],
                          "halted": r["halted"], "max_dd_pct": r["max_dd_pct"],
                          "n_entries": len(r["entries"]),
                          "placebo_beaten": beaten, "placebo_finals": pfin,
                          "n_eval_dates": len(ev), "curve": r["curve"],
                          "period_stats_at_this_cadence": period_stats(r["curve"], sorted(ev))}
            print(f"{start} {cad}: ${r['final']} entries {len(r['entries'])} DD {r['max_dd_pct']}% placebo {beaten}/20 halted {r['halted']}", flush=True)
        return out_cells

    out = {"family": "canslim-oneil-judgment",
           "label": "JUDGMENT-CONSTRUCTED: frozen reconstruction of O'Neil's documented decision-making; not O'Neil's own trading.",
           "window": [START, END], "native_cadence": "daily",
           "spy_decade": 367.80, "cells": {}}
    out["cells"] = run_window(START, END, CADENCES)
    nat = out["cells"]["daily"]["final"]
    live = [c for c in CADENCES if c != "daily" and out["cells"][c]["final"] > nat]
    out["confirmation"] = {}
    for cad in live:
        conf = run_window(CONT[0], CONT[1], [cad, "daily"])
        out["confirmation"][cad] = {"window": list(CONT), "cells": conf,
            "beats_native_on_CONT": conf[cad]["final"] > conf["daily"]["final"]}
    with open(os.path.join(HERE, "cadence_results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved cadence_results.json")

if __name__ == "__main__":
    main()
