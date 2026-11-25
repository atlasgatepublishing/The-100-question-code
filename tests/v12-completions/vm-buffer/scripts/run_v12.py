#!/usr/bin/env python3
"""
V12 vm-buffer — CONSTRUCTED Novy-Marx & Velikov buy/hold spread.
Frozen spec: ../CONSTRUCTION-SPEC.md (read it first).

The paper's exact band for a value+momentum host (NMV 2016, Table 6
Panel A: ValMom/ValMomProf are mid-turnover): BUY top 10%, HOLD until
out of top 20%, implemented in the paper's own set form — the holding
set is (holdings still inside the hold range) UNION (non-held names
inside the buy range), variable count, path-dependent. Host: the
program champion V+M engine (ranking, PIT EDGAR, 30-name pond,
quarterly cadence, equal weight, program costs, v9 protections),
imported verbatim from the v5/v4 modules; only the selection block
differs. Plumbing (FastBook/FastPIT/score cache) follows the v10
vm-buffer script, whose FastPIT equivalence with E.pit_value is
asserted in-script before running.

Runs per road: (1) CONSTRUCTED sS ranked; (2) HOST CONTROL — the
unbuffered champion selection (fixed top 5) on identical plumbing;
(3) 20 placebo seeds — identical sS mechanics on random pool
orderings. Roads: LONG, DECADE, CONT, VAL + pre-registered CONFIRM
fold (reported either way; see spec §4).

Shared inputs are READ-ONLY (v4/v5 modules and caches, v7 pxfull
payloads, v10 GOOGL payload). All outputs land in this folder.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
BT = os.path.expanduser("~/workspace/stock-app/backtests")

START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
ROADS = {
    "LONG":    ("2010-01-04", "2026-11-20"),
    "DECADE":  ("2016-11-21", "2026-11-20"),
    "CONT":    ("2019-01-02", "2026-11-20"),
    "VAL":     ("2023-01-03", "2026-11-20"),
    "CONFIRM": ("2010-01-04", "2016-11-18"),
}
CHAMPION_PUBLISHED = {"LONG": 1415.62, "DECADE": 667.35,
                      "CONT": 544.47, "VAL": 288.05}
SPY_PUBLISHED = {"LONG": 822.94, "DECADE": 367.80,
                 "CONT": 313.62, "VAL": 187.77}

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

V5 = load_module("vm_buffer_v5", os.path.join(BT, "v5", "vm-buffer", "vm-buffer.py"))
E = V5.E
UNIVERSE = E.UNIVERSE

# ------------------------------------------------------------------ FastBook
class FastBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


def bars_adj(payload):
    res = payload["chart"]["result"][0]
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


def build_book():
    lh = os.path.join(BT, "v7", "long-hold", "data")
    fallback = os.path.join(BT, "v10-retest", "vm-buffer", "cache")
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        p = os.path.join(lh, f"pxfull_{t}.json")
        if not os.path.exists(p):
            p = os.path.join(fallback, f"pxfull_{t}.json")
        with open(p, "rb") as f:
            bars[t] = bars_adj(json.loads(f.read()))
    return FastBook(bars)

# ------------------------------------------------------------------ FastPIT
class FastPIT:
    def __init__(self, rows):
        indexed = list(enumerate(rows))
        indexed.sort(key=lambda ir: (ir[1][0], ir[1][3], ir[1][1], -ir[0]))
        self.rows = [r for _i, r in indexed]
        self.filed = [r[0] for r in self.rows]

    def pit(self, asof):
        i = bisect.bisect_left(self.filed, asof) - 1
        if i < 0:
            return None
        filed, end, val, _prio = self.rows[i]
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
        if _date(fy, fm, fd).toordinal() < _date(ay, am, ad).toordinal() - 548:
            return None
        return (filed, end, val)

EQF, SHF = {}, {}

def verify_fast_pit(equity_rows, shares_rows, fb):
    rng = random.Random(7)
    days = [d for d in fb.dates if "2010-01-04" <= d <= "2026-11-20"]
    for t in UNIVERSE:
        for rows, fast in ((equity_rows[t], EQF[t]), (shares_rows[t], SHF[t])):
            for d in rng.sample(days, 12):
                a = E.pit_value(rows, d)
                b = fast.pit(d)
                assert (a is None) == (b is None), (t, d, a, b)
                if a is not None:
                    assert a == b, (t, d, a, b)
    print("FastPIT verified == E.pit_value on sampled pairs", flush=True)

# ------------------------------------------------------------- scores
def compute_scores(fb, d, didx_map):
    scores = {}
    for t in UNIVERSE:
        be = EQF[t].pit(d)
        so = SHF[t].pit(d)
        if be is None or so is None:
            continue
        b = fb.bar(t, d)
        if b is None:
            continue
        px = b["c"]
        if so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bl = fb.bars[t]
        didx = didx_map[t].get(d)
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (be[2] / mcap, mom)
    return scores

# ------------------------------------------------------------- engine
def run_episode(fb, score_cache, sel_set, start, end, start_cash, floor0,
                mode, placebo_rng=None):
    """Host engine (v5 run_pot mechanics) with the selection block set by
    mode: 'ss' = CONSTRUCTED NMV 10/20 set rule; 'host' = champion fixed
    top-5. Execution, floor and liquidation are the host's, verbatim in
    behaviour."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    days = [d for d in fb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = fb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = fb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = score_cache[d]
            if len(scores) >= 5:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                if placebo_rng is not None:
                    order = sorted(scores)
                    placebo_rng.shuffle(order)
                else:
                    order = sorted(combined, key=lambda t: -combined[t])
                rank = {t: i + 1 for i, t in enumerate(order)}
                held = list(positions)
                n = len(scores)
                if mode == "ss":
                    buy_n = max(1, math.floor(0.10 * n + 0.5))
                    hold_n = max(buy_n, math.floor(0.20 * n + 0.5))
                    kept = [t for t in held if t in rank and rank[t] <= hold_n]
                    new = [t for t in order if t not in held and rank[t] <= buy_n]
                    picks = kept + new
                elif mode == "host":
                    picks = order[:5]
                    kept = [t for t in held if t in picks]
                else:
                    raise ValueError(mode)
                pools.append((d, n, list(picks)))
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = fb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "pools": pools}
    last = days[-1]
    for t in list(positions):
        c_ = fb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "pools": pools}

# ------------------------------------------------------------- v9 wrapper
def run_v9(fb, score_cache, sel_all, start, end, start_cash, mode,
           placebo_rng=None):
    floor1 = round(0.85 * start_cash, 2)
    sel1 = {d for d in sel_all if start <= d <= end}
    r1 = run_episode(fb, score_cache, sel1, start, end, start_cash, floor1,
                     mode, placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "pools": list(r1["pools"]), "episodes": 1,
           "halt_events": [], "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        return out
    out["halt_events"].append(
        {"episode": 1, "signal_date": r1["halted"],
         "signal_close": r1["halt_info"]["signal_close"],
         "liquidation_date": r1["end"], "proceeds": round(r1["final"], 2)})
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_all:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if start <= cand <= end and _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append(
        {"halt_signal_date": r1["halted"], "liquidation_date": liq_date,
         "restart_date": restart, "restart_balance": round(cash, 2),
         "episode2_floor": floor2})
    seg_end = restart if restart else end
    for d in fb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    sel2 = {d for d in sel_all if restart <= d <= end}
    r2 = run_episode(fb, score_cache, sel2, restart, end, cash, floor2,
                     mode, placebo_rng=placebo_rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    out["pools"] += list(r2["pools"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
        out["halt_events"].append(
            {"episode": 2, "signal_date": r2["halted"],
             "signal_close": r2["halt_info"]["signal_close"],
             "liquidation_date": r2["end"], "proceeds": round(r2["final"], 2)})
    out["curve"].sort(key=lambda kv: kv[0])
    return out

# ------------------------------------------------------------- stats
def stats_for(r, start, end):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in r["curve"]:
        if v > peak:
            peak = v
        if peak > 0 and (peak - v) / peak > maxdd:
            maxdd, maxdd_d = (peak - v) / peak, d
    yrs = (_date(int(end[:4]), int(end[5:7]), int(end[8:10])) -
           _date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days / 365.25
    sizes = [len(p[2]) for p in r["pools"]]
    return {
        "final": round(r["final"], 2),
        "cagr_pct": round(((r["final"] / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
        "costs": round(r["costs"], 2), "orders": len(r["trades"]),
        "halts": len(r["halt_events"]), "restarts": r["restarts"],
        "second_halt": r["second_halt"], "episodes": r["episodes"],
        "selections": len(r["pools"]),
        "holdings_min": min(sizes) if sizes else None,
        "holdings_max": max(sizes) if sizes else None,
        "holdings_mean": round(sum(sizes) / len(sizes), 2) if sizes else None,
    }

def main():
    t0 = time.time()
    _pb4, equity_rows, shares_rows = V5.build_inputs()
    global EQF, SHF
    EQF = {t: FastPIT(equity_rows[t]) for t in UNIVERSE}
    SHF = {t: FastPIT(shares_rows[t]) for t in UNIVERSE}
    fb = build_book()
    verify_fast_pit(equity_rows, shares_rows, fb)
    didx_map = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])}
                for t in UNIVERSE}
    # selection dates per road (host's quarter_selection_dates on the book)
    sel_by_road = {name: E.quarter_selection_dates(fb, ws, we)
                   for name, (ws, we) in ROADS.items()}
    all_sel = sorted({d for v in sel_by_road.values() for d in v})
    score_cache = {d: compute_scores(fb, d, didx_map) for d in all_sel}
    print(f"scores for {len(all_sel)} selection dates ({time.time()-t0:.0f}s)",
          flush=True)

    results = {"family": "vm-buffer", "program": "v12-completions",
               "constructed": True,
               "rule": "NMV 10%/20% buy/hold spread, set form, on champion V+M host",
               "roads": {}}
    for name, (ws, we) in ROADS.items():
        sel = sel_by_road[name]
        spy, _ = E.spy_net(fb, ws, we, START_CASH)
        r_ss = run_v9(fb, score_cache, sel, ws, we, START_CASH, "ss")
        r_host = run_v9(fb, score_cache, sel, ws, we, START_CASH, "host")
        placebo = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_v9(fb, score_cache, sel, ws, we, START_CASH, "ss",
                        placebo_rng=rng)
            placebo.append({"seed": seed, "final": round(pr["final"], 2),
                            "halts": len(pr["halt_events"])})
        finals = sorted(p["final"] for p in placebo)
        beaten = sum(1 for f in finals if f < r_ss["final"])
        med = E._pct(finals, 0.50)
        road = {
            "window": [ws, we],
            "ss_constructed": stats_for(r_ss, ws, we),
            "host_control_unbuffered": stats_for(r_host, ws, we),
            "spy_net_own_plumbing": round(spy, 2),
            "spy_published": SPY_PUBLISHED.get(name),
            "champion_published": CHAMPION_PUBLISHED.get(name),
            "placebo": {"seeds_beaten": beaten, "median": round(med, 2),
                        "q1": round(E._pct(finals, 0.25), 2),
                        "q3": round(E._pct(finals, 0.75), 2),
                        "best": finals[-1], "worst": finals[0],
                        "rows": placebo},
            "ss_curve": [[d, round(v, 4)] for d, v in r_ss["curve"]],
            "host_curve": [[d, round(v, 4)] for d, v in r_host["curve"]],
            "ss_pools": [[d, n, picks] for d, n, picks in r_ss["pools"]],
        }
        results["roads"][name] = road
        print(f"{name:8s} sS=${r_ss['final']:,.2f} host=${r_host['final']:,.2f} "
              f"SPY=${spy:,.2f} placebo {beaten}/20 med=${med:,.2f} "
              f"halts={len(r_ss['halt_events'])} ({time.time()-t0:.0f}s)",
              flush=True)
    results["runtime_s"] = round(time.time() - t0, 1)
    with open(os.path.join(FAM, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
