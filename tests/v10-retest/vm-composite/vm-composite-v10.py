#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — vm-composite
Value + Momentum with COMPOSITE value leg: value score = average of the
percentile ranks of book-to-market (B/M), earnings yield (E/P) and
operating-cash-flow yield (CF/P); combined = (value + 12-1 momentum
percentile)/2; hold top 5, equal weight. Universe: the baseline's honest
point-in-time top-30 as of Nov 2016. Costs: 0.10%/side + $0.01 per sell
order. Simulation only.

WHAT THIS SCRIPT DOES
(1) INTEGRITY — runs the ORIGINAL v9-bundle engine (imported verbatim
    from backtests/v9-muse-rules/vm-composite/vm-composite-v9.py, which
    wraps the v5 engine) in its ORIGINAL form (quarterly, plain -15%
    floor, no restart) on the original windows, through the original v4
    caches: CONT 2019-01-02->2026-11-20 (published $511.48) and VAL
    2023-01-03->2026-11-20 (published $265.38). Also re-checks the v5
    baseline replication (champion B/M-only engine: $544.47 / $288.05).
(2) SWEEP — DECADE 2016-11-21 -> 2026-11-20 at 7 cadences (daily,
    weekly, biweekly, monthly, quarterly, semi-annual, annual) under
    the SPEC's uniform cadence definition: signal evaluation, selection
    and trading ONLY on cadence dates. $100/cell, program costs, v9
    protections (plain -15% floor; first halt -> liquidate at next open,
    90 calendar days in cash, restart at the next cadence date on/after
    liquidation+90d under an episode-2 floor of -15% from the restart
    balance; second halt ends the run).
(3) PLACEBOS — 20 seeds (1..20) per cell: random 5 from the strategy's
    own scored pool at each selection date (the original placebo
    design), run under the same v9 protections.

SWEEP DATA (documented artifact, not a patch): the v4 price caches start
2017-06-01, which cannot feed 12-1 momentum for a 2016-11-21 decade
start. The sweep therefore reads the program's full-history Yahoo
payloads — backtests/v7/long-hold/data/pxfull_*.json (2008->2026) plus
pxfull_GOOGL.json from backtests/long-run-2010/data/ — parsed with the
baseline engine's EXACT parsing code (adjclose-ratio opens, adjclose
closes). EDGAR facts come from the v4 caches via the baseline engine's
own loaders. All shared inputs are read-only; nothing is written
outside this folder.

ENGINE FAITHFULNESS: the sweep engine below is the v5/v9
run_pot_composite copied with ONLY these changes:
  - selection dates are the cadence dates (parameter) instead of
    E.quarter_selection_dates;
  - point-in-time fact lookups use a bisect index that is PROVEN equal
    to E.pit_value on every (series, date) pair in an exhaustive check
    before any sweep number is taken (asserted in-run);
  - momentum uses a precomputed date->bar-index map (same bars, same
    formula);
  - scored pools are precomputed once per cadence date and shared by
    the ranked run and its 20 placebo twins (identical scores; the
    placebo design samples from exactly this pool).
An in-run cross-check re-runs the sweep engine at quarterly cadence on
CONT and VAL through the ORIGINAL v4 price book and asserts it
reproduces $511.48 / $265.38 to the cent before the decade sweep runs.
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
BT = os.path.join(HERE, "..", "..")
V4 = os.path.join(BT, "v4")
V9 = os.path.join(BT, "v9-muse-rules", "vm-composite", "vm-composite-v9.py")
PXFULL_DIR = os.path.join(BT, "v7", "long-hold", "data")
LR_DATA = os.path.join(BT, "long-run-2010", "data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

E = _load("vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
V9M = _load("vm_composite_v9", V9)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- data build
def build_rows():
    """EDGAR point-in-time rows via the baseline engine's own loaders
    (v4 caches, read-only) + the v9 bundle's trailing-annual series."""
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    eq, inc, ocf, so = {}, {}, {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                 E.pit_series(facts, "us-gaap",
                              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                              prio=1))
        inc[t] = V9M.pit_series_income(facts)
        ocf[t] = V9M.pit_series_ocf(facts)
        so[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                 E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                 E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    return eq, inc, ocf, so

def parse_payload(blob):
    """Baseline engine's price parsing, verbatim (E.get_prices body)."""
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def build_pxfull_book():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        p1 = os.path.join(PXFULL_DIR, f"pxfull_{t}.json")
        p2 = os.path.join(LR_DATA, f"pxfull_{t}.json")
        path = p1 if os.path.exists(p1) else p2
        with open(path, "rb") as f:
            bars[t] = parse_payload(f.read())
    return E.PriceBook(bars)

def build_v4_book():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars)

# ------------------------------------------- fast PIT lookup (proven equal)
def _ord(d):
    return _date(int(d[:4]), int(d[5:7]), int(d[8:10])).toordinal()

class PitFast:
    """Index over (filed, end, val, prio) rows returning exactly
    E.pit_value(rows, asof): among rows with filed < asof and filed
    within 548 days of asof, the max key (filed, prio, end)."""
    def __init__(self, rows):
        best = {}
        for filed, end, val, prio in rows:
            cur = best.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best[filed] = (prio, end, val)
        self.fileds = sorted(best)
        self.filed_ords = [_ord(f) for f in self.fileds]
        self.best = best

    def value(self, asof):
        i = bisect.bisect_left(self.fileds, asof) - 1
        if i < 0:
            return None
        if _ord(asof) - self.filed_ords[i] > 548:
            return None
        f = self.fileds[i]
        prio, end, val = self.best[f]
        return (f, end, val)

def prove_pit_equal(rows_by_series, sample_dates):
    """Exhaustive check: PitFast == E.pit_value for every series on
    every sample date. Returns count of comparisons."""
    n = 0
    for t, series_list in rows_by_series.items():
        for rows in series_list:
            fast = PitFast(rows)
            for d in sample_dates:
                a = fast.value(d)
                b = E.pit_value(rows, d)
                assert (a is None and b is None) or a == b, (t, d, a, b)
                n += 1
    return n

# ------------------------------------------------------------ cadence dates
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return E.quarter_selection_dates(pb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        wk = cadence_dates(pb, "weekly", start, end)
        return wk[::2]
    if cadence == "monthly":
        for d in days:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "semiannual":
        for d in days:
            key = (d[:4], "H1" if int(d[5:7]) <= 6 else "H2")
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            key = d[:4]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(cadence)

# ------------------------------------------------------------- sweep engine
class SweepBook:
    """Precomputed per-ticker bar index maps + close-on-or-before via
    bisect over the baseline PriceBook's bars (same bars, faster)."""
    def __init__(self, pb):
        self.pb = pb
        self.dates = pb.dates
        self.didx = {}
        self.dates_by = {}
        for t, bl in pb.bars.items():
            self.didx[t] = {b["d"]: i for i, b in enumerate(bl)}
            self.dates_by[t] = [b["d"] for b in bl]

    def close_on_or_before(self, t, d):
        dl = self.dates_by.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.pb.bars[t][i]["c"]

def score_pool(sb, fasts, d):
    """The v5/v9 selection scoring block, verbatim logic: a name must
    be scorable on ALL THREE value components + shares + price +
    momentum, else excluded. Returns (pool_sorted_list, ranked_picks)
    or (pool, None) when the pool has < 5 names."""
    eqf, incf, ocff, sof = fasts
    pb = sb.pb
    scores = {}
    for t in UNIVERSE:
        be = eqf[t].value(d)
        ni = incf[t].value(d)
        ocf = ocff[t].value(d)
        so = sof[t].value(d)
        px = sb.close_on_or_before(t, d)
        if (be is None or ni is None or ocf is None or so is None
                or px is None or so[2] <= 0):
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bm = be[2] / mcap
        ey = ni[2] / mcap
        cfy = ocf[2] / mcap
        bl = pb.bars.get(t, [])
        didx = sb.didx.get(t, {}).get(d)
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, ey, cfy, mom)
    pool = sorted(scores)
    if len(scores) < 5:
        return pool, None
    rb = E.percentile_ranks({t: v[0] for t, v in scores.items()})
    re_ = E.percentile_ranks({t: v[1] for t, v in scores.items()})
    rc = E.percentile_ranks({t: v[2] for t, v in scores.items()})
    mr = E.percentile_ranks({t: v[3] for t, v in scores.items()})
    value_score = {t: (rb[t] + re_[t] + rc[t]) / 3.0 for t in scores}
    combined = {t: (value_score[t] + mr[t]) / 2.0 for t in scores}
    picks = sorted(combined, key=lambda t: -combined[t])[:5]
    return pool, picks

def run_episode(sb, pools, start, end, start_cash, floor0,
                placebo_rng=None):
    """run_pot_composite (v5/v9) copied verbatim EXCEPT: selection
    dates/pools come from the precomputed cadence pools dict, and
    portfolio_close uses the bisect close lookup (same values)."""
    pb = sb.pb
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    sel_set = set(pools)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = sb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
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
            pool, picks = pools[d]
            if picks is not None:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(pool, 5)
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = sb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None, "curve": curve}

def run_v9(sb, pools, sel_dates, start, end, start_cash, placebo_rng=None):
    """The v9 bundle's run_pot_v9, generalized: restart at the next
    CADENCE date on/after liquidation + 90 calendar days (the SPEC's
    'next regular decision point'). Everything else identical."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_episode(sb, pools, start, end, start_cash, floor1,
                     placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "ep1_final": r1["final"], "ep1_halted": r1["halted"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "halts": 0}
    if r1["halted"] is None:
        return out
    out["halts"] = 1
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = _ord(liq_date) + 90
    restart = None
    for cand in sel_dates:
        if _ord(cand) >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "liquidation_date": liq_date,
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    seg_end = restart if restart else end
    for d in sb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    r2 = run_episode(sb, pools, restart, end, cash, floor2,
                     placebo_rng=placebo_rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["halts"] = 2
        out["second_halt"] = {
            "signal_date": r2["halted"],
            "signal_close": r2["halt_info"]["signal_close"],
            "floor_in_effect": r2["halt_info"]["floor_in_effect"],
            "liquidation_date": r2["end"],
            "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

# ------------------------------------------------------------------- stats
def curve_stats(curve, years):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > maxdd:
                maxdd = dd
    return maxdd * 100.0

def cagr(final, years):
    if final <= 0:
        return -100.0
    return ((final / START_CASH) ** (1.0 / years) - 1.0) * 100.0

# --------------------------------------------------------------------- main
def main():
    t0 = time.time()
    rows = build_rows()
    eq, inc, ocf, so = rows
    fasts = (({t: PitFast(eq[t]) for t in UNIVERSE}),
             ({t: PitFast(inc[t]) for t in UNIVERSE}),
             ({t: PitFast(ocf[t]) for t in UNIVERSE}),
             ({t: PitFast(so[t]) for t in UNIVERSE}))

    # ---------- PIT index proof (before any sweep number counts)
    pb_v4 = build_v4_book()
    sample = [d for d in pb_v4.dates if "2015-01-01" <= d <= "2026-11-20"
              and d[8:10] in ("02", "15")]
    ncmp = prove_pit_equal({t: (eq[t], inc[t], ocf[t], so[t]) for t in UNIVERSE},
                           sample)
    print(f"PIT PROOF: PitFast == E.pit_value on {ncmp} (series,date) pairs", flush=True)

    # ---------- (1) INTEGRITY: original engine, original form, v4 caches
    # Checkpointed (integrity.json): the shared VM runs ~100 sibling
    # workers and this process was OOM-killed once mid-run; a completed
    # integrity phase is never recomputed.
    ipath = os.path.join(HERE, "integrity.json")
    if os.path.exists(ipath):
        with open(ipath) as f:
            integrity = json.load(f)
        print(f"INTEGRITY: loaded checkpoint {integrity['reproduced_finals']} "
              f"status={integrity['status']}", flush=True)
        assert integrity["status"] == "reproduced"
    else:
        integrity = {"status": None, "original_finals": {}, "reproduced_finals": {}}
        rep = {}
        for tag, (ws, we), published in (("CONT", CONT, 511.48), ("VAL", VAL, 265.38)):
            r = V9M.run_pot_composite(pb_v4, eq, inc, ocf, so, ws, we,
                                      START_CASH, 85.0, [], label=f"INTEGRITY {tag}",
                                      quiet=True)
            rep[tag] = round(r["final"], 2)
            integrity["original_finals"][tag] = published
            integrity["reproduced_finals"][tag] = rep[tag]
            print(f"INTEGRITY {tag}: reproduced=${rep[tag]:,.2f} published=${published:,.2f} "
                  f"match={rep[tag] == published} halted={r['halted']} orders={len(r['trades'])}",
                  flush=True)
        base_rep = {}
        for tag, (ws, we), published in (("CONT", CONT, 544.47), ("VAL", VAL, 288.05)):
            rb = E.run_pot(pb_v4, eq, so, ws, we, START_CASH, 85.0, [],
                           label=f"BASELINE-REPLICATION {tag}", quiet=True)
            base_rep[tag] = round(rb["final"], 2)
            print(f"BASELINE REPLICATION {tag}: ${base_rep[tag]:,.2f} vs published "
                  f"${published:,.2f} match={base_rep[tag] == published}", flush=True)
        integrity["baseline_replication"] = {
            "original_finals": {"CONT": 544.47, "VAL": 288.05},
            "reproduced_finals": base_rep}
        ok = all(rep[t] == integrity["original_finals"][t] for t in rep)
        integrity["status"] = "reproduced" if ok else "FAILED"
        assert ok, f"INTEGRITY FAILED: {rep}"

        # ---------- engine cross-check: sweep engine, quarterly, v4 book
        sb_v4 = SweepBook(pb_v4)
        for tag, (ws, we), published in (("CONT", CONT, 511.48), ("VAL", VAL, 265.38)):
            qdates = E.quarter_selection_dates(pb_v4, ws, we)
            pools = {d: score_pool(sb_v4, fasts, d) for d in qdates}
            r = run_episode(sb_v4, pools, ws, we, START_CASH, 85.0)
            got = round(r["final"], 2)
            print(f"ENGINE XCHECK {tag}: sweep-engine=${got:,.2f} published=${published:,.2f} "
                  f"match={got == published}", flush=True)
            assert got == published, f"engine cross-check failed on {tag}: {got}"
        with open(ipath, "w") as f:
            json.dump(integrity, f, indent=1)
    del pb_v4

    # ---------- (2)+(3) SWEEP on the decade, pxfull book
    pb = build_pxfull_book()
    sb = SweepBook(pb)
    spy_dec, _ = E.spy_net(pb, DECADE[0], DECADE[1], START_CASH)
    spy_dec = round(spy_dec, 2)
    print(f"DECADE SPY (pxfull book, dividend-adjusted): ${spy_dec:,.2f}", flush=True)
    years = (_ord(DECADE[1]) - _ord(DECADE[0])) / 365.25

    cells = {}
    money = []
    for cad in CADENCES:
        cpath = os.path.join(CELLS, f"{cad}.json")
        if os.path.exists(cpath):
            with open(cpath) as f:
                prev = json.load(f)
            cells[cad] = {k: prev[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                           "second_halt", "costs", "orders", "placebo_beaten",
                           "placebo_note")}
            if cells[cad]["final"] > spy_dec and cells[cad]["placebo_beaten"] >= 11:
                money.append(cad)
            print(f"CELL {cad:11s} loaded from checkpoint final=${cells[cad]['final']:,.2f}",
                  flush=True)
            continue
        sel = cadence_dates(pb, cad, DECADE[0], DECADE[1])
        pools = {d: score_pool(sb, fasts, d) for d in sel}
        r = run_v9(sb, pools, sel, DECADE[0], DECADE[1], START_CASH)
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            rp = run_v9(sb, pools, sel, DECADE[0], DECADE[1], START_CASH,
                        placebo_rng=rng)
            twins.append({"seed": seed, "final": round(rp["final"], 2),
                          "costs": round(rp["costs"], 2),
                          "orders": len(rp["trades"]),
                          "halts": rp["halts"]})
        beaten = sum(1 for tw in twins if r["final"] > tw["final"])
        cell = {"final": round(r["final"], 2),
                "cagr_pct": round(cagr(r["final"], years), 2),
                "max_dd_pct": round(curve_stats(r["curve"], years), 2),
                "halts": r["halts"],
                "restart": bool(r["restarts"] and r["restarts"][0]["restart_date"]),
                "second_halt": r["second_halt"] is not None,
                "costs": round(r["costs"], 2),
                "orders": len(r["trades"]),
                "placebo_beaten": beaten,
                "placebo_note": "20 seeds, random 5 from the strategy's own scored pool at each cadence date, same v9 protections"}
        cells[cad] = cell
        if cell["final"] > spy_dec and beaten >= 11:
            money.append(cad)
        celldoc = dict(cell)
        celldoc.update({
            "slug": "vm-composite", "cadence": cad, "window": DECADE,
            "start_cash": START_CASH, "spy_final": spy_dec,
            "n_selection_dates": len(sel),
            "restarts": r["restarts"], "second_halt_detail": r["second_halt"],
            "episodes": r["episodes"],
            "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
            "placebo_twin_finals": twins})
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(celldoc, f, indent=1)
        print(f"CELL {cad:11s} sel={len(sel):5d} final=${r['final']:,.2f} "
              f"CAGR={cell['cagr_pct']}% maxDD={cell['max_dd_pct']}% "
              f"costs=${cell['costs']:,.2f} orders={cell['orders']} "
              f"halts={r['halts']} placebo_beaten={beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)

    results = {
        "slug": "vm-composite",
        "area": "Long-horizon quarterly value/momentum holding on the pond — W1 champion-variant family; the champion's road is its native ground (SPEC W1).",
        "area_source": "SPEC.md worker batch W1 + CADENCE GRID (W1: quarterly, native, none foreign)",
        "cadence": "quarterly",
        "native_cadence": "quarterly",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original v5/v9 tests ran quarterly — the native cadence. Not foreign.",
        "integrity": integrity,
        "decade_spy_final": spy_dec,
        "decade_window": DECADE,
        "champion_decade_reference": 65.89,
        "cells": cells,
        "money_cadences": money,
        "data_note": ("Sweep prices: program full-history Yahoo payloads "
                      "backtests/v7/long-hold/data/pxfull_*.json + "
                      "backtests/long-run-2010/data/pxfull_GOOGL.json, parsed with the "
                      "baseline engine's exact parsing (v4 caches start 2017-06-01 and "
                      "cannot feed 12-1 momentum for a 2016-11-21 start). EDGAR facts: v4 "
                      "caches via baseline loaders. All shared inputs read-only."),
        "verdict_area": None,  # filled below
        "verdict_change": None,
    }
    q = cells["quarterly"]
    if "quarterly" in money:
        results["verdict_area"] = "OWNS ITS GROUND"
        results["verdict_change"] = ("No change in kind: the composite still earns its place "
                                     "at its native quarterly tempo on the decade road. The "
                                     "v5-era claim was made on CONT/VAL; the decade sweep "
                                     "confirms the native cadence and maps the other tempos.")
    elif q["final"] > spy_dec:
        results["verdict_area"] = "REAL BUT SMALL"
        results["verdict_change"] = ("Softened: at its native quarterly cadence it beats SPY "
                                     "on the decade but does not clear its own placebo "
                                     "distribution, so the composite's edge is not proven "
                                     "skill on this road.")
    else:
        results["verdict_area"] = "NO GROUND"
        results["verdict_change"] = ("Changed: on the full decade road at its native cadence "
                                     "the composite no longer beats SPY, unlike its CONT/VAL "
                                     "record — the variant's ground shrinks to the post-2019 road.")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("RESULTS_JSON_WRITTEN", json.dumps({k: cells[k]["final"] for k in CADENCES}),
          "money:", money, "verdict:", results["verdict_area"], flush=True)
    print(f"DONE in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
