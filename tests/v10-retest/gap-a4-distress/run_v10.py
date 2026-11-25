#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — gap-a4-distress (CHS failure-probability avoidance).

Two parts:
  A) INTEGRITY — the ORIGINAL v9 engine (engine_original_v9.py, a byte copy
     of backtests/v9-muse-rules/gap-a4-distress/gap-a4-distress-v9.py) run in
     its original form on its original windows/prices (v4 caches, read-only):
     CONT 2019-01-02->2026-11-20 (published $335.88) and
     VAL  2023-01-03->2026-11-20 (published $154.25), plus the original
     plain-floor 20-seed placebos on both windows (published: VAL 2/20,
     CONT 11/20).
  B) CADENCE SWEEP — DECADE 2016-11-21 -> 2026-11-20, $100/cell, at
     daily/weekly/biweekly/monthly/quarterly/semi-annual/annual under the
     SPEC's uniform cadence definition. Signal, universe, costs and scoring
     are the original engine's, verbatim; the ONLY changes are (i) the
     selection-date set is generated per cadence instead of always
     quarterly, (ii) the v9 protection wrapper restarts at the next
     CADENCE decision point (the original v9 wrapper used the next
     quarterly point, which is the cadence point at quarterly cadence),
     (iii) prices come from the read-only full-range Yahoo cache
     (backtests/v7/long-hold/data/pxfull_*.json, 2008->2026-11-20, parsed
     with the identical adjclose-ratio construction as the original
     engine's get_prices) because the original v4 price cache starts
     2017-06-01 and cannot cover the decade start 2016-11-21, and
     (iv) speed-only lookups (bisect close lookup, memoized month-end
     closes and SIGMA windows) that return identical values — validated
     by re-running the quarterly decade cell with the unmodified helpers
     and comparing to the cent (see integrity.fast_lookup_check).

Defensive scoring: every cell also reports max drawdown and worst close,
and SPY's decade max drawdown / worst close are reported alongside.
"""
import bisect
import datetime as _dt
import importlib.util
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LH_DATA = os.path.join(HERE, "..", "..", "v7", "long-hold", "data")

spec = importlib.util.spec_from_file_location(
    "engine_original_v9", os.path.join(HERE, "engine_original_v9.py"))
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)
E = O.E
UNIVERSE = O.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))

DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------ fast lookups
class FastPriceBook(E.PriceBook):
    """E.PriceBook with a bisect close_on_or_before — returns exactly the
    bar the original linear scan returns (last bar with date <= d)."""

    def __init__(self, bars_by_ticker):
        super().__init__(bars_by_ticker)
        self._dates = {t: [b["d"] for b in bl]
                       for t, bl in bars_by_ticker.items()}

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        if not bl:
            return None
        i = bisect.bisect_right(self._dates[t], d) - 1
        return bl[i]["c"] if i >= 0 else None


_ME_CACHE = {}
_orig_month_end_closes = O.month_end_closes


def month_end_closes_fast(bars):
    k = id(bars)
    if k not in _ME_CACHE:
        _ME_CACHE[k] = _orig_month_end_closes(bars)
    return _ME_CACHE[k]


_SIGMA_CACHE = {}


def sigma_3m_fast(pb, t, d):
    """O.sigma_3m with the bar window found by bisect; the returns list
    and its summation order are identical to the original."""
    bars = pb.bars.get(t, [])
    k = id(bars)
    if k not in _SIGMA_CACHE:
        _SIGMA_CACHE[k] = ([O._ord(b["d"]) for b in bars],
                           [b["c"] for b in bars])
    ords, closes = _SIGMA_CACHE[k]
    do = O._ord(d)
    y, m = int(d[:4]), int(d[5:7])
    m0, y0 = m - 3, y
    while m0 <= 0:
        m0 += 12
        y0 -= 1
    # NOTE (cadence-generalization artifact, documented not hidden): the
    # original code builds date(y0, m0, day-of-d), which crashes when d's
    # day is 29-31 and the month 3 back is shorter (e.g. May 31 -> Feb 31).
    # It never fired originally because quarterly selection dates fall in
    # the first days of a month. Here the day is clamped to the target
    # month's last day — the same calendar intent, window start shifts by
    # at most 3 days, and only on daily/weekly/biweekly/monthly dates.
    import calendar as _cal
    day = min(int(d[8:10]), _cal.monthrange(y0, m0)[1])
    start_ord = _dt.date(y0, m0, day).toordinal()
    lo = bisect.bisect_left(ords, start_ord - 10)
    hi = bisect.bisect_right(ords, do)
    rets = []
    for i in range(lo + 1, hi):
        if ords[i] > start_ord:
            rets.append(closes[i] / closes[i - 1] - 1.0)
    nz = sum(1 for r in rets if r != 0.0)
    if nz < 5 or len(rets) < 2:
        return None
    ss = sum(r * r for r in rets)
    return math.sqrt(252.0 / (len(rets) - 1) * ss)


import functools

_ord_orig = O._ord


@functools.lru_cache(maxsize=None)
def _ord_cached(dstr):
    return _ord_orig(dstr)


def install_fast_helpers():
    O.month_end_closes = month_end_closes_fast
    O.sigma_3m = sigma_3m_fast
    O._ord = _ord_cached  # identical values; the engine re-parses the
    # same filed/end date strings millions of times in its row scans


_sigma_orig = O.sigma_3m


def uninstall_fast_helpers():
    O.month_end_closes = _orig_month_end_closes
    O.sigma_3m = _sigma_orig
    O._ord = _ord_orig


# ------------------------------------------------------------ data loading
def load_facts():
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows, concepts = {}, {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        concepts[t] = O.build_concept_rows(facts, eq)
    return {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}


def bars_from_payload(payload):
    """Identical construction to E.get_prices / lr_common.bars_adj:
    open/close scaled by adjclose/close; close = adjclose."""
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


def load_bars_v4():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return bars


def load_bars_full():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        path = os.path.join(LH_DATA, f"pxfull_{t}.json")
        if not os.path.exists(path):
            # GOOGL is absent from the long-hold cache (it holds GOOG);
            # the identical full-range cache in long-run-2010/data has it.
            path = os.path.join(HERE, "..", "..", "long-run-2010", "data",
                                f"pxfull_{t}.json")
        with open(path, "rb") as f:
            bars[t] = bars_from_payload(json.loads(f.read()))
    return bars


# ------------------------------------------------------- cadence machinery
def cadence_dates(pb, cadence, start, end):
    """SPEC uniform cadence: first trading day of each period."""
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    weeks = []
    for d in days:
        dt = _dt.date.fromisoformat(d)
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            if dt.month not in (1, 4, 7, 10):
                continue
            key = (dt.year, dt.month)
        elif cadence == "semiannual":
            if dt.month not in (1, 7):
                continue
            key = (dt.year, dt.month)
        elif cadence == "annual":
            key = (dt.year,)
        else:
            raise ValueError(cadence)
        if cadence == "biweekly":
            if key not in seen:
                seen.add(key)
                weeks.append(d)
            continue
        if key not in seen:
            seen.add(key)
            out.append(d)
    if cadence == "biweekly":
        return weeks[::2]
    return out


def run_pot_cad(pb, data, spy_me, sel_dates, start, end, start_cash,
                floor0, placebo_rng=None, label=""):
    """O.run_pot_chs copied verbatim EXCEPT sel_dates is a parameter
    (the original hard-codes E.quarter_selection_dates)."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
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
            sel = O.compute_selection(pb, d, data, spy_me)
            scored = sel["scored"]
            if len(scored) >= 1:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scored),
                                               min(5, len(scored)))
                else:
                    picks = sel["picks"]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in LADDER:
            if v >= thresh and newfloor > floor:
                floor = newfloor
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}


def run_v9_cad(pb, data, spy_me, sel_dates, start, end, placebo_rng=None):
    """v9 protection wrapper (O.run_chs_v9) generalized only in that the
    restart decision point is the next CADENCE date in sel_dates."""
    ep1 = run_pot_cad(pb, data, spy_me, sel_dates, start, end, START_CASH,
                      FLOOR0, placebo_rng=placebo_rng)
    out = {"episodes": 1, "ep1_halted": ep1["halted"],
           "ep1_final": round(ep1["final"], 2), "costs": ep1["costs"],
           "orders": len(ep1["trades"]), "restart": None,
           "ep2_halted": None, "final": ep1["final"], "status": "no_halt",
           "curve": list(ep1["curve"]), "trades": ep1["trades"]}
    if not ep1["halted"]:
        return out
    liq_date = ep1["end"]
    cash1 = ep1["final"]
    eligible = (_dt.date.fromisoformat(liq_date) +
                _dt.timedelta(days=90)).isoformat()
    restart = next((d for d in sel_dates if d >= eligible), None)
    if restart is None:
        out["status"] = "halted_ep1_no_restart_in_window"
        return out
    ep2 = run_pot_cad(pb, data, spy_me, sel_dates, restart, end, cash1,
                      0.85 * cash1, placebo_rng=placebo_rng)
    out.update({"episodes": 2, "final": ep2["final"],
                "costs": ep1["costs"] + ep2["costs"],
                "orders": len(ep1["trades"]) + len(ep2["trades"]),
                "ep2_halted": ep2["halted"],
                "status": "halted_ep2_run_ends" if ep2["halted"]
                          else "restarted_completed",
                "curve": list(ep1["curve"]) + list(ep2["curve"]),
                "trades": ep1["trades"] + ep2["trades"],
                "restart": {"halt_signal_date": ep1["halted"],
                            "liquidation_date": liq_date,
                            "cash_at_halt": round(cash1, 2),
                            "eligible_from": eligible,
                            "restart_date": restart,
                            "restart_balance": round(cash1, 2),
                            "episode2_floor": round(0.85 * cash1, 2)}})
    return out


# ------------------------------------------------------------- statistics
def curve_stats(curve):
    peak, maxdd, worst = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd = dd
        if worst is None or v < worst[1]:
            worst = (d, v)
    return {"max_dd_pct": round(maxdd * 100, 2),
            "worst_close": round(worst[1], 2), "worst_close_date": worst[0]}


def cagr(final, start, end):
    days = (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days
    return round(((final / START_CASH) ** (365.25 / days) - 1) * 100, 2)


def spy_curve(pb, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    first = days[0]
    o = pb.bar("SPY", first)["o"]
    sh = (START_CASH / 1.001) / o
    return [(d, sh * pb.close_on_or_before("SPY", d)) for d in days]


def halts_list(r):
    h = []
    if r["ep1_halted"]:
        h.append({"episode": 1, "signal_date": r["ep1_halted"],
                  "liquidation_date": r["restart"]["liquidation_date"]
                  if r["restart"] else None,
                  "cash_at_halt": r["restart"]["cash_at_halt"]
                  if r["restart"] else r["ep1_final"]})
    if r["restart"]:
        h.append({"restart_date": r["restart"]["restart_date"],
                  "restart_balance": r["restart"]["restart_balance"],
                  "eligible_from": r["restart"]["eligible_from"],
                  "episode2_floor": r["restart"]["episode2_floor"]})
    if r["ep2_halted"]:
        h.append({"episode": 2, "signal_date": r["ep2_halted"]})
    return h


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    data = load_facts()
    print(f"facts loaded {time.time()-t0:.0f}s", flush=True)

    summary = {}

    # ---------------- A) INTEGRITY (original engine, original prices)
    if mode in ("all", "integrity"):
        install_fast_helpers()
        bars = load_bars_v4()
        pb = FastPriceBook(bars)
        spy_me = O.month_end_closes(bars["SPY"])
        O.SELECTION_CACHE.clear()
        integ = {}
        for tag, (ws, we), published in (("CONT", CONT, 335.88),
                                         ("VAL", VAL, 154.25)):
            r = O.run_chs_v9(pb, data, spy_me, ws, we, label=tag)
            integ[tag] = {"final": round(r["final"], 2),
                          "published": published,
                          "match": round(r["final"], 2) == published,
                          "status": r["status"], "ep1_halted": r["ep1_halted"],
                          "costs": round(r["costs"], 2), "orders": r["orders"]}
            print(f"INTEGRITY {tag}: ${r['final']:,.2f} vs published "
                  f"${published:,.2f} match={integ[tag]['match']}", flush=True)
        # original plain-floor placebos (v7 form, O.placebo_block machinery)
        placebo_integ = {}
        for tag, (ws, we), ranked_final, published_beaten in (
                ("VAL", VAL, integ["VAL"]["final"], 2),
                ("CONT", CONT, integ["CONT"]["final"], 11)):
            finals = []
            for seed in PLACEBO_SEEDS:
                rng = random.Random(seed)
                rp = O.run_pot_chs(pb, data, spy_me, ws, we, START_CASH,
                                   FLOOR0, LADDER, placebo_rng=rng,
                                   label=f"{tag} PLACEBO s{seed}", quiet=True)
                finals.append(round(rp["final"], 2))
            beaten = sum(1 for v in finals if ranked_final > v)
            placebo_integ[tag] = {"twin_finals": finals,
                                  "beaten": beaten,
                                  "published_beaten": published_beaten,
                                  "match": beaten == published_beaten}
            print(f"INTEGRITY PLACEBO {tag}: beaten {beaten}/20 "
                  f"(published {published_beaten}/20)", flush=True)
        summary["integrity"] = {"windows": integ, "placebos": placebo_integ}
        with open(os.path.join(HERE, "integrity.json"), "w") as f:
            json.dump(summary["integrity"], f, indent=1)
        print(f"integrity done {time.time()-t0:.0f}s", flush=True)

    # ---------------- B) CADENCE SWEEP on the DECADE (full-range prices)
    if mode in ("all", "sweep"):
        install_fast_helpers()
        bars = load_bars_full()
        pb = FastPriceBook(bars)
        spy_me = O.month_end_closes(bars["SPY"])
        O.SELECTION_CACHE.clear()
        ws, we = DECADE
        spy_final, spy_costs = E.spy_net(pb, ws, we, START_CASH)
        scurve = spy_curve(pb, ws, we)
        sstats = curve_stats(scurve)
        print(f"SPY DECADE: final=${spy_final:,.2f} maxDD={sstats['max_dd_pct']}% "
              f"worst close=${sstats['worst_close']} on {sstats['worst_close_date']}",
              flush=True)
        summary["decade_spy"] = {"final": round(spy_final, 2),
                                 "max_dd_pct": sstats["max_dd_pct"],
                                 "worst_close": sstats["worst_close"],
                                 "worst_close_date": sstats["worst_close_date"]}

        # Precompute selections for the union of all cadence dates (daily
        # is the full set) so every cell/placebo shares identical pools.
        daily_dates = cadence_dates(pb, "daily", ws, we)
        print(f"precomputing {len(daily_dates)} daily selections...", flush=True)
        for i, d in enumerate(daily_dates):
            O.compute_selection(pb, d, data, spy_me)
            if i % 250 == 0:
                print(f"  selections {i}/{len(daily_dates)} "
                      f"{time.time()-t0:.0f}s", flush=True)
        print(f"selections done {time.time()-t0:.0f}s", flush=True)

        cells = {}
        for cad in CADENCES:
            sel_dates = cadence_dates(pb, cad, ws, we)
            if cad == "quarterly":
                assert sel_dates == E.quarter_selection_dates(pb, ws, we), \
                    "quarterly cadence dates differ from engine's own"
            r = run_v9_cad(pb, data, spy_me, sel_dates, ws, we)
            st = curve_stats(r["curve"])
            # placebos: same v9 wrapper, random picks from same pools
            twin_finals = []
            for seed in PLACEBO_SEEDS:
                rng = random.Random(seed)
                rp = run_v9_cad(pb, data, spy_me, sel_dates, ws, we,
                                placebo_rng=rng)
                twin_finals.append(round(rp["final"], 2))
            beaten = sum(1 for v in twin_finals if r["final"] > v)
            cell = {"final": round(r["final"], 2),
                    "cagr_pct": cagr(r["final"], ws, we),
                    "max_dd_pct": st["max_dd_pct"],
                    "worst_close": st["worst_close"],
                    "worst_close_date": st["worst_close_date"],
                    "spy_max_dd_pct": sstats["max_dd_pct"],
                    "spy_worst_close": sstats["worst_close"],
                    "costs": round(r["costs"], 2),
                    "orders": r["orders"],
                    "halts": (1 if r["ep1_halted"] else 0) +
                             (1 if r["ep2_halted"] else 0),
                    "restart": bool(r["restart"]),
                    "second_halt": bool(r["ep2_halted"]),
                    "status": r["status"],
                    "placebo_beaten": beaten,
                    "placebo_twin_finals": twin_finals,
                    "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
                    "halts_detail": halts_list(r)}
            cells[cad] = cell
            with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
                json.dump(cell, f, indent=1)
            print(f"CELL {cad}: final=${r['final']:,.2f} maxDD={st['max_dd_pct']}% "
                  f"worst=${st['worst_close']} halts={cell['halts']} "
                  f"restart={cell['restart']} placebo {beaten}/20 "
                  f"costs=${r['costs']:,.2f} orders={r['orders']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        summary["cells"] = {c: {k: v for k, v in cell.items()
                                if k != "equity_curve"}
                            for c, cell in cells.items()}
        with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
            json.dump(summary, f, indent=1)

    # ---------------- C) FAST-LOOKUP VALIDATION (quarterly cell, raw helpers)
    if mode in ("all", "check"):
        uninstall_fast_helpers()
        bars = load_bars_full()
        pb = E.PriceBook(bars)
        spy_me = O.month_end_closes(bars["SPY"])
        O.SELECTION_CACHE.clear()
        ws, we = DECADE
        sel_dates = cadence_dates(pb, "quarterly", ws, we)
        r = run_v9_cad(pb, data, spy_me, sel_dates, ws, we)
        ref = None
        refpath = os.path.join(HERE, "cells", "quarterly.json")
        if os.path.exists(refpath):
            with open(refpath) as f:
                ref = json.load(f)["final"]
        check = {"quarterly_decade_final_unmodified_helpers": round(r["final"], 2),
                 "quarterly_decade_final_fast_helpers": ref,
                 "match": (ref is not None and round(r["final"], 2) == ref)}
        with open(os.path.join(HERE, "fast_lookup_check.json"), "w") as f:
            json.dump(check, f, indent=1)
        print(f"FAST-LOOKUP CHECK: raw=${r['final']:,.2f} fast=${ref} "
              f"match={check['match']}", flush=True)

    print(f"DONE {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
