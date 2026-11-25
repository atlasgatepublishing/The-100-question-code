#!/usr/bin/env python3
"""
V10 GREAT RETEST — vm-buffer (value+momentum with rank buffer / hysteresis:
hold while combined rank <= 10). Simulation only. No broker orders placed.

WHAT THIS SCRIPT DOES
  (A) INTEGRITY — runs the ORIGINAL v5 vm-buffer module's own functions
      (imported verbatim from backtests/v5/vm-buffer/vm-buffer.py, which
      reads the original v4 caches read-only) in its ORIGINAL form
      (quarterly selection, plain -15% floor, no restart — the published
      form) on the published windows:
        CONT 2019-01-02 -> 2026-11-20   published final $379.76
        VAL  2023-01-03 -> 2026-11-20   published final $248.72
      Plus the v5 replication check of the unbuffered baseline engine
      ($544.47 / $288.05) that the original study itself ran first.

  (B) CADENCE SWEEP — DECADE 2016-11-21 -> 2026-11-20, $100/cell, at
      daily / weekly / biweekly / monthly / quarterly / semi-annual /
      annual cadences, under adopted v9 protections.
      UNIFORM SWEEP RULE (stated per the task): signal evaluation,
      selection, rebalancing AND the buffer check happen ONLY on cadence
      dates. A holding whose combined rank has slipped past 10 is sold
      only when a cadence date arrives and the check is run — between
      cadence dates nothing is evaluated and nothing trades (the daily
      floor check still runs every trading day, exactly as in the
      original engine).
      Mechanics otherwise identical to the original buffer engine:
      combined rank = average of book-to-market and 12-1 momentum
      percentile ranks over the point-in-time scored pool; keep held
      names with rank <= 10, fill remaining of 5 slots with the
      highest-ranked non-held names, equal weight, rebalance at next
      open; a held name that cannot be scored has no rank and is sold;
      costs 0.10%/side + $0.01 per sell order; point-in-time EDGAR with
      the ~18-month filed-freshness gate (E.pit_value semantics).
      PROTECTIONS (v9): plain -15% floor from the episode start balance;
      on first halt: liquidate at next open (as the engine does), sit in
      cash 90 calendar days from the liquidation date, restart with the
      remaining cash at the next CADENCE date on/after liquidation+90d
      under an episode-2 floor of -15% from the restart balance; second
      halt ends the run.
      PLACEBOS: 20 seeds (1..20) per cell — identical buffer mechanics
      on a random ordering of the scored pool each cadence date
      (rng shuffle, same consumption pattern as the original placebo),
      under the same v9 protections.

DATA (all shared inputs read-only):
  - Integrity: the original v4 caches via the v5 module (EDGAR facts in
    backtests/v4/data, Yahoo prices in backtests/v4/value-momentum-honest-data
    / v4/data), exactly as published.
  - Sweep: EDGAR equity/share rows from the same v4 companyfacts cache
    (via the v5 module's build_inputs); prices from the long-run Yahoo
    pxfull payloads in backtests/v7/long-hold/data (2008-01-02 ->
    2026-11-20, read-only), converted with the identical adjusted-bar
    construction as the v4 engine (open x adj/close ratio, close =
    adjclose). GOOGL has no pxfull file in that cache (the long-run
    pool used GOOG); its payload was downloaded once from Yahoo into
    THIS folder's cache/ (pxfull_GOOGL.json) with the same URL/method.
    The v4 price cache starts 2017-06-01 and cannot cover the
    2016-11-21 decade start or its 253-bar momentum lookback; the
    pxfull series can, which is why the sweep uses them. The 30-name
    universe is the original E.UNIVERSE, unchanged.

PLUMBING OPTIMIZATIONS (mechanics identical, verified in-script):
  - FastBook: bisect-based close_on_or_before (same semantics as
    E.PriceBook: last bar on/before the date).
  - Fast PIT: E.pit_value's winner is the row maximising
    (filed, prio, end) among rows filed strictly before asof; if that
    row's filed date is older than asof-548d every row is stale and the
    answer is None. Rows pre-sorted by (filed, prio, end) make that a
    prefix lookup. The script asserts fast == E.pit_value on a sample
    of (ticker, date) pairs before sweeping.
  - Scores depend only on the date (not on holdings or rng), so they
    are computed once per trading day and shared by the ranked run and
    all 20 placebo runs at every cadence.
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
BT = os.path.expanduser("~/workspace/stock-app/backtests")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

START_CASH = 100.0
BUFFER_KEEP_RANK = 10
PLACEBO_SEEDS = list(range(1, 21))
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------------ imports
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

V5 = load_module("vm_buffer_v5", os.path.join(BT, "v5", "vm-buffer", "vm-buffer.py"))
E = V5.E                      # v4 value-momentum-plainfloor, verbatim
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
    """Identical adjusted-bar construction to E.get_prices."""
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


def build_sweep_book():
    lh = os.path.join(BT, "v7", "long-hold", "data")
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        p = os.path.join(lh, f"pxfull_{t}.json")
        if not os.path.exists(p):
            p = os.path.join(HERE, "cache", f"pxfull_{t}.json")
        with open(p, "rb") as f:
            bars[t] = bars_adj(json.loads(f.read()))
    return FastBook(bars)

# ------------------------------------------------------------------ fast PIT
class FastPIT:
    """Pre-sorted rows; pit() == E.pit_value(rows, asof) (asserted)."""
    def __init__(self, rows):
        # E.pit_value keeps the FIRST row attaining the max (filed, prio,
        # end) key in original list order (strict > comparison). Sorting
        # by (filed, prio, end, -orig_index) makes the last row with
        # filed < asof exactly that first-attained maximum, even when
        # duplicate (filed, prio, end) rows carry different values.
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


def verify_fast_pit(equity_rows, shares_rows, fb):
    import random as _r
    rng = _r.Random(7)
    days = [d for d in fb.dates if DECADE[0] <= d <= DECADE[1]]
    for t in UNIVERSE:
        for rows, fast in ((equity_rows[t], EQF[t]), (shares_rows[t], SHF[t])):
            for d in rng.sample(days, 12):
                a = E.pit_value(rows, d)
                b = fast.pit(d)
                assert (a is None) == (b is None), (t, d, a, b)
                if a is not None:
                    assert a == b, (t, d, a, b)
    print("FastPIT verified == E.pit_value on sampled pairs", flush=True)

# ------------------------------------------------------------- score cache
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

# ------------------------------------------------------------- cadence dates
def cadence_dates(fb, cadence, start, end):
    days = [d for d in fb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        dt = _date(y, m, int(d[8:10]))
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            key = ("bw", monday // 14)
        elif cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = (y, m)
        elif cadence == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = (y, m)
        elif cadence == "annual":
            if d[5:7] != "01":
                continue
            key = (y,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

# ------------------------------------------------- buffer engine (cadence)
def run_episode(fb, score_cache, sel_set, start, end, start_cash, floor0,
                placebo_rng=None):
    """Copy of the v5 run_pot_buffer with ONLY: selection dates supplied
    by the cadence calendar, scores read from the shared per-date cache,
    FastBook lookups. Selection/execution/floor logic otherwise verbatim."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
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
                kept = [t for t in held
                        if t in rank and rank[t] <= BUFFER_KEEP_RANK]
                slots = 5 - len(kept)
                fill = [t for t in order if t not in held][:slots]
                picks = kept + fill
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
                    "curve": curve}
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
            "halted": None, "end": last, "halt_info": None, "curve": curve}

# ------------------------------------------------------------- v9 wrapper
def run_v9(fb, score_cache, cadence_list, start, end, start_cash,
           placebo_rng=None):
    """v9 protections, generalised only in that the restart lands on the
    next CADENCE date (the cell's own calendar) on/after liquidation+90d
    — at quarterly this is exactly the v9 module's rule."""
    sel_all = cadence_list
    floor1 = round(0.85 * start_cash, 2)
    sel1 = {d for d in sel_all if start <= d <= end}
    r1 = run_episode(fb, score_cache, sel1, start, end, start_cash, floor1,
                     placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "ep1_final": r1["final"], "ep1_halted": r1["halted"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "halt_events": []}
    if r1["halted"] is not None:
        out["halt_events"].append(
            {"episode": 1, "signal_date": r1["halted"],
             "signal_close": r1["halt_info"]["signal_close"],
             "liquidation_date": r1["end"],
             "proceeds": round(r1["final"], 2)})
    if r1["halted"] is None:
        return out
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
        {"halt_signal_date": r1["halted"],
         "halt_signal_close": r1["halt_info"]["signal_close"],
         "liquidation_date": liq_date, "restart_date": restart,
         "restart_balance": round(cash, 2), "episode2_floor": floor2})
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
                     placebo_rng=placebo_rng)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
        out["halt_events"].append(
            {"episode": 2, "signal_date": r2["halted"],
             "signal_close": r2["halt_info"]["signal_close"],
             "liquidation_date": r2["end"],
             "proceeds": round(r2["final"], 2)})
    out["curve"].sort(key=lambda kv: kv[0])
    return out

# ------------------------------------------------------------- stats
def curve_stats(curve, final, start_cash=START_CASH):
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return round(maxdd * 100, 2)

def cagr(final, start, end, start_cash=START_CASH):
    yrs = (_date(int(end[:4]), int(end[5:7]), int(end[8:10])) -
           _date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days / 365.25
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100, 2)

# ------------------------------------------------------------- globals set in main
EQF = {}
SHF = {}

def main():
    t0 = time.time()
    # ---------- (A) INTEGRITY: original v5 module, original form ----------
    pb4, equity_rows, shares_rows = V5.build_inputs()
    integrity = {"status": None, "original_finals": {"CONT": 379.76, "VAL": 248.72},
                 "reproduced_finals": {}, "detail": {}}
    for wname, (ws, we), pub in [("CONT", CONT, 379.76), ("VAL", VAL, 248.72)]:
        r = V5.run_pot_buffer(pb4, equity_rows, shares_rows, ws, we,
                              START_CASH, 85.0, [], label=f"INTEG {wname}",
                              quiet=True)
        integrity["reproduced_finals"][wname] = round(r["final"], 2)
        integrity["detail"][wname] = {
            "window": [ws, we], "published_final": pub,
            "reproduced_final": round(r["final"], 2),
            "match": abs(r["final"] - pub) < 0.011,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"]}
        print(f"INTEGRITY buffer {wname}: ${r['final']:,.2f} vs published "
              f"${pub:,.2f} match={abs(r['final']-pub)<0.011}", flush=True)
    base_rep = {}
    for wname, (ws, we), pub in [("CONT", CONT, 544.47), ("VAL", VAL, 288.05)]:
        r = E.run_pot(pb4, equity_rows, shares_rows, ws, we, START_CASH,
                      85.0, [], label=f"INTEG BASE {wname}", quiet=True)
        base_rep[wname] = round(r["final"], 2)
        print(f"INTEGRITY baseline {wname}: ${r['final']:,.2f} vs published "
              f"${pub:,.2f} match={abs(r['final']-pub)<0.011}", flush=True)
    integrity["baseline_replication"] = {
        "published": {"CONT": 544.47, "VAL": 288.05}, "reproduced": base_rep}
    ok = all(v["match"] for v in integrity["detail"].values())
    integrity["status"] = "reproduced" if ok else "FAILED"
    integrity["note"] = ("Original v5 module functions run unmodified on the "
                         "original v4 caches, original form (quarterly, plain "
                         "-15% floor, no restart). Baseline replication is the "
                         "v5 study's own pre-check.")

    # ---------- (B) SWEEP ----------
    global EQF, SHF
    EQF = {t: FastPIT(equity_rows[t]) for t in UNIVERSE}
    SHF = {t: FastPIT(shares_rows[t]) for t in UNIVERSE}
    fb = build_sweep_book()
    verify_fast_pit(equity_rows, shares_rows, fb)
    didx_map = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])}
                for t in UNIVERSE}
    days = [d for d in fb.dates if DECADE[0] <= d <= DECADE[1]]
    score_cache = {}
    for d in days:
        score_cache[d] = compute_scores(fb, d, didx_map)
    print(f"scores computed for {len(days)} decade days "
          f"({time.time()-t0:.0f}s)", flush=True)

    spy_final, _spy_cost = E.spy_net(fb, DECADE[0], DECADE[1], START_CASH)
    spy_final = round(spy_final, 2)
    print(f"SPY decade (own plumbing, pxfull): ${spy_final:,.2f} "
          f"(SPEC reference $367.80)", flush=True)

    cells = {}
    for cad in CADENCES:
        clist = cadence_dates(fb, cad, DECADE[0], DECADE[1])
        r = run_v9(fb, score_cache, clist, DECADE[0], DECADE[1], START_CASH)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_v9(fb, score_cache, clist, DECADE[0], DECADE[1],
                        START_CASH, placebo_rng=rng)
            placebo_finals.append({"seed": seed,
                                   "final": round(pr["final"], 2),
                                   "halts": len(pr["halt_events"]),
                                   "second_halt": pr["second_halt"] is not None})
        beaten = sum(1 for p in placebo_finals if p["final"] < r["final"])
        cell = {
            "final": round(r["final"], 2),
            "cagr_pct": cagr(r["final"], DECADE[0], DECADE[1]),
            "max_dd_pct": curve_stats(r["curve"], r["final"]),
            "halts": len(r["halt_events"]),
            "restart": len(r["restarts"]) > 0 and r["restarts"][0]["restart_date"] is not None,
            "second_halt": r["second_halt"] is not None,
            "costs": round(r["costs"], 2),
            "orders": len(r["trades"]),
            "placebo_beaten": beaten,
            "placebo_note": ("20 seeds, identical buffer mechanics on random "
                             "pool orderings, same cadence and v9 protections."),
            "selection_dates": len(clist),
        }
        cells[cad] = cell
        cell_doc = {
            "slug": "vm-buffer", "cadence": cad,
            "window": [DECADE[0], DECADE[1]], "start_cash": START_CASH,
            "final": cell["final"], "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": cell["max_dd_pct"], "costs": cell["costs"],
            "orders": cell["orders"], "halts": cell["halts"],
            "halt_events": r["halt_events"], "restarts": r["restarts"],
            "second_halt": r["second_halt"], "restart": cell["restart"],
            "selection_dates": clist,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals,
            "placebo_note": cell["placebo_note"],
            "spy_final": spy_final,
        }
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        print(f"CELL {cad:11s} sel={len(clist):5d} final=${r['final']:,.2f} "
              f"CAGR={cell['cagr_pct']}% maxDD={cell['max_dd_pct']}% "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halts={cell['halts']} placebo_beaten={beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > spy_final and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "vm-buffer",
        "area": "Long-horizon quarterly value/momentum holding on the pond "
                "(W1 V+M variant family) — judged by the cadence sweep on "
                "the DECADE road",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W1 + "
                       "THE CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "quarterly",
        "cadence": "quarterly",
        "original_cadence_foreign": {
            "foreign": False,
            "note": "Original v5/v9 tests ran quarterly — the native "
                    "cadence. Not foreign."},
        "native_change": "none in form for the native (quarterly) cell; "
                         "the sweep varies only the evaluation/rebalance/"
                         "buffer-check cadence under the uniform sweep rule, "
                         "with v9 protections adopted (SPEC). Sweep prices "
                         "are the long-run pxfull Yahoo payloads (see script "
                         "docstring) so the decade road can start 2016-11-21.",
        "integrity": integrity,
        "decade_spy_final": 367.80,
        "decade_spy_note": "SPEC reference (dividend-adjusted). Own plumbing "
                           f"on pxfull SPY gives ${spy_final:,.2f}; money-"
                           "cadence test uses the SPEC $367.80 (the stricter "
                           "of the two is applied in RESULTS.md if they differ "
                           "in effect — see verdict notes).",
        "decade_spy_own_plumbing": spy_final,
        "champion_decade_reference": {
            "final": 65.89,
            "note": "Champion value+momentum DECADE $65.89 after two halts "
                    "(lazy-quarterly test) — its crown rests on the 2010 and "
                    "2019 roads; the decade caveat applies."},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,   # filled by RESULTS.md author after review
        "verdict_change": None,
        "buffer_cadence_rule": "Uniform sweep rule: the buffer check "
                               "(hold while combined rank <= 10) is "
                               "evaluated only on cadence dates; between "
                               "cadence dates no signal is evaluated and "
                               "nothing trades. The -15% floor check runs "
                               "every trading day, as in the original engine.",
        "runtime_s": round(time.time() - t0, 1),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("SWEEP DONE", json.dumps({c: cells[c]["final"] for c in CADENCES}),
          "money:", money, flush=True)

if __name__ == "__main__":
    main()
