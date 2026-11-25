#!/usr/bin/env python3
"""
VM-BROAD — THE GREAT RETEST (v10) — value+momentum on the top-60 pond.
Simulation only.

WHAT THIS IS
  The v5 vm-broad strategy (promoted value+momentum spec on the top-60
  universe: original 30 + next 30 by point-in-time Nov-2016 market cap),
  re-run under the v10 SPEC:
    (1) INTEGRITY — reproduce the original published finals in original
        (his-rules, plain floor, no restart) form through the ORIGINAL
        engine (engine_vm.py = verbatim copy of
        backtests/v4/value-momentum-plainfloor.py):
          CONT 2019-01-02->2026-11-20 ranked  $82.24, halted 2020-03-18
          VAL  2023-01-03->2026-11-20 ranked  $302.61
          VAL placebo (seeds 1..20) beats 19/20, per-seed finals as
          published in backtests/v5/vm-broad/vm-broad-results.json
        Plus the v9 cross-check: CONT under v9 protections = $346.87
        (restart 2020-07-01 with $82.24).
    (2) SWEEP — DECADE 2016-11-21->2026-11-20 x 7 cadences (daily,
        weekly, biweekly, monthly, quarterly, semiannual, annual),
        $100/cell, program costs (0.10%/side + $0.01 per sell order,
        the engine's own cost code), v9 protections (plain -15% floor;
        first halt -> liquidate at next open, 90 calendar days in cash,
        restart at the next CADENCE selection date on/after
        liquidation+90d under an episode-2 floor of -15% from the
        restart balance; second halt ends the run).
    (3) PLACEBOS — 20 seeds (1..20) per cadence cell, same machinery
        and same v9 protections, random 5 from the scored pool at each
        selection (the engine's own placebo design).

FAST SIMULATOR — WHY IT EXISTS AND HOW IT IS PROVEN
  The original engine recomputes every name's score from raw EDGAR rows
  at every selection date; at a daily cadence over a decade x 21 runs
  per cell that is not computable in reasonable time. The score on a
  date depends ONLY on the date (point-in-time facts filed before it +
  prices up to it), never on the pot's cash, picks or cadence. So this
  script precomputes the scored pool for every trading day once, then
  runs a simulator whose body is the engine's run_pot copied line for
  line, with ONLY the scoring block replaced by the precomputed lookup
  and quarter_selection_dates replaced by the cadence date list.
  The simulator is not trusted until it reproduces, to the cent, through
  the quarterly cadence: his-rules CONT $82.24 (halt 2020-03-18, signal
  close $84.30), his-rules VAL $302.61, all 20 his-rules VAL placebo
  finals, and v9 CONT $346.87. Those assertions run BEFORE the sweep;
  if any fails the script stops and no sweep number is produced.

DATA (read-only shared caches; nothing is written outside this folder)
  - Prices + EDGAR facts: backtests/v5/vm-broad/data (the original
    study's cache; Yahoo bars begin 2017-06-01 — the program-wide
    convention. CONSEQUENCE, documented not patched: on the DECADE
    window the pot sits in cash until the first selection date with
    >=5 names carrying 253 bars of price history (~mid-2018); the
    window itself is the full 2016-11-21->2026-11-20 as specified).
  - Universe: backtests/v5/vm-broad/universe-build.json (top-60 list).
  - Decade SPY reference $367.80 is the SPEC's dividend-adjusted
    figure (2016-11-21 start); the in-plumbing SPY on this PriceBook
    (first bar 2017-06-01) is also computed and reported.

CADENCE DEFINITION (SPEC, uniform): selection dates are the first
trading day of each period — daily = every trading day; weekly = first
trading day of each ISO week; biweekly = first trading day of every
second ISO week (anchored on the first week of the window); monthly =
first trading day of each month; quarterly = first trading day of
Jan/Apr/Jul/Oct (identical to the engine's quarter_selection_dates);
semiannual = Jan/Jul; annual = Jan. Signal evaluation, selection and
rebalancing happen ONLY on cadence dates. The -15% floor check stays
daily: it is the protection module, not the signal, and the original
engine checks it on every close in every published run.
"""
import importlib.util
import json
import os
import random
import time
from bisect import bisect_left, bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V5DIR = "/home/hatch/workspace/stock-app/backtests/v5/vm-broad"
V5DATA = os.path.join(V5DIR, "data")
CELLS = os.path.join(HERE, "cells")

# ------------------------------------------------------------ engine (verbatim copy)
spec = importlib.util.spec_from_file_location(
    "engine_vm", os.path.join(HERE, "engine_vm.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
E.DATA = V5DATA      # read-only original cache (path-only, as in v5/v9)
E.SHARED = V5DATA

with open(os.path.join(V5DIR, "universe-build.json")) as f:
    BUILD = json.load(f)
UNIVERSE60 = BUILD["universe60"]
ORIGINAL30 = list(E.UNIVERSE)
assert len(UNIVERSE60) == 60 and set(ORIGINAL30) <= set(UNIVERSE60)
E.UNIVERSE = UNIVERSE60

CIK_GONE = {
    "TWX": 1105705, "MON": 1110783, "AET": 1122304, "RAI": 898173,
    "YHOO": 1043000, "CELG": 816284, "ESRX": 1532063, "AGN": 1578845,
    "UTX": 101829, "ANTM": 1156039, "PCLN": 1075531,
    "ALXN": 939767, "WBA": 1618921,
}
CIK_OVERRIDES = {"XOM": 34088}

START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
SEEDS = list(range(1, 21))
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
DECADE_SPY_SPEC = 367.80
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def build_inputs(universe):
    """Identical to backtests/v5/vm-broad/vm-broad.py build_inputs
    (minus its courtesy sleep; every read is a cache hit)."""
    ciks = E.get_ciks()
    equity_rows, shares_rows, data_notes = {}, {}, {}
    for t in universe:
        cik = CIK_OVERRIDES.get(t) or CIK_GONE.get(t) or ciks[t][0]
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        if not equity_rows[t] or not shares_rows[t]:
            data_notes[t] = (f"thin EDGAR: equity facts={len(equity_rows[t])} "
                             f"shares facts={len(shares_rows[t])}")
    bars = {}
    for t in universe + ["SPY"]:
        try:
            bars[t] = E.get_prices(t)
        except Exception as e:  # noqa — delisted series purged by Yahoo
            bars[t] = []
            data_notes[t] = f"no Yahoo price series ({type(e).__name__})"
            print(f"{t}: NO PRICE SERIES — engine will never score it", flush=True)
    return bars, equity_rows, shares_rows, data_notes


# ------------------------------------------------------------ fast plumbing
class FastBook:
    """Same values as the engine's PriceBook, bisect lookups."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.dates_by_t = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self.closes_by_t = {t: [b["c"] for b in bl] for t, bl in bars_by_ticker.items()}
        self.pos = {t: {d: i for i, d in enumerate(dl)}
                    for t, dl in self.dates_by_t.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self.dates_by_t.get(t, [])
        i = bisect_right(dl, d) - 1
        return self.closes_by_t[t][i] if i >= 0 else None


class PitFast:
    """E.pit_value with identical semantics: among rows FILED strictly
    before asof and filed within 548 days of asof, the winner is the max
    by key (filed, prio, end). Pre-grouped by filed date."""

    def __init__(self, rows):
        best_by_filed = {}
        for filed, end, val, prio in rows:
            cur = best_by_filed.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best_by_filed[filed] = (prio, end, val)
        self.fileds = sorted(best_by_filed)
        self.best = best_by_filed
        self.ords = [date(int(f[:4]), int(f[5:7]), int(f[8:10])).toordinal()
                     for f in self.fileds]

    def value(self, asof):
        j = bisect_left(self.fileds, asof) - 1
        if j < 0:
            return None
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        if self.ords[j] < date(ay, am, ad).toordinal() - 548:
            return None
        f = self.fileds[j]
        _prio, end, val = self.best[f]
        return (f, end, val)


def precompute_scores(fb, equity_rows, shares_rows):
    """Scored pool for every trading day: {date: {ticker: (bm, mom)}}
    in UNIVERSE60 order — the engine's scoring block, hoisted."""
    pit_eq = {t: PitFast(equity_rows.get(t, [])) for t in UNIVERSE60}
    pit_sh = {t: PitFast(shares_rows.get(t, [])) for t in UNIVERSE60}
    scores_by_date = {}
    for d in fb.dates:
        scores = {}
        for t in UNIVERSE60:
            be = pit_eq[t].value(d)
            so = pit_sh[t].value(d)
            px = fb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = fb.bars.get(t, [])
            didx = fb.pos.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        scores_by_date[d] = scores
    return scores_by_date


def percentile_ranks(values):
    return E.percentile_ranks(values)


def run_ep_fast(fb, scores_by_date, sel_dates, start, end, start_cash,
                floor0, placebo_rng=None):
    """The engine's run_pot, copied line for line, with the scoring
    block replaced by the precomputed pool for the day and the
    selection-date list supplied by the cadence. Ladder is empty
    (plain floor), exactly as in the published vm-broad runs."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_set = {d for d in sel_dates if start <= d <= end}
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
            scores = scores_by_date.get(d, {})
            if len(scores) >= 5:
                vr = percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pools.append((d, sorted(scores), list(picks)))
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
                    "pools": pools, "curve": curve}
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
            "pools": pools, "curve": curve}


# ------------------------------------------------------------ cadences
def cadence_dates(all_dates, cadence, start, end):
    """First trading day of each period, within [start, end]."""
    ds = [d for d in all_dates if start <= d <= end]
    if cadence == "daily":
        return ds
    out, seen = [], set()
    if cadence == "weekly":
        for d in ds:
            iso = date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = cadence_dates(all_dates, "weekly", start, end)
        return weeks[::2]
    months = {"monthly": None,
              "quarterly": ("01", "04", "07", "10"),
              "semiannual": ("01", "07"),
              "annual": ("01",)}[cadence]
    for d in ds:
        if months is not None and d[5:7] not in months:
            continue
        key = (d[:4], d[5:7]) if cadence == "monthly" else (
            (d[:4], d[5:7]) if cadence in ("quarterly", "semiannual")
            else (d[:4],))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------------------------ v9 protections
def run_v9(run_ep, all_dates, sel_dates, start, end, start_cash):
    """The v9 wrapper (copied from backtests/v9-muse-rules/vm-broad/
    vm-broad-v9.py run_pot_v9) with ONE generalization required by the
    sweep: the restart lands on the next CADENCE selection date on or
    after liquidation+90 days (the v9 original used the quarterly list,
    which is exactly this function at the quarterly cadence)."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_ep(start, end, start_cash, floor1)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "ep1_final": r1["final"], "ep1_halted": r1["halted"],
           "ep1_halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_dates:
        if not (start <= cand <= end):
            continue
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    entry = {"halt_signal_date": r1["halted"],
             "halt_signal_close": r1["halt_info"]["signal_close"],
             "liquidation_date": liq_date,
             "restart_date": restart,
             "restart_balance": round(cash, 2),
             "episode2_floor": floor2}
    out["restarts"].append(entry)
    seg_end = restart if restart else end
    for d in all_dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    r2 = run_ep(restart, end, cash, floor2)
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
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------ metrics
def max_dd_pct(curve):
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > maxdd:
                maxdd = dd
    return round(maxdd * 100, 2)


def cagr_pct(final, start, end):
    days = (date(int(end[:4]), int(end[5:7]), int(end[8:10])) -
            date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days
    years = days / 365.25
    return round(((final / START_CASH) ** (1.0 / years) - 1.0) * 100, 2)


def summarize(res, start, end):
    halts = (1 if res["restarts"] else 0) + (1 if res["second_halt"] else 0)
    return {"final": round(res["final"], 2),
            "cagr_pct": cagr_pct(res["final"], start, end),
            "max_dd_pct": max_dd_pct(res["curve"]),
            "halts": halts,
            "restart": bool(res["restarts"] and
                            res["restarts"][0]["restart_date"]),
            "second_halt": bool(res["second_halt"]),
            "costs": round(res["costs"], 2),
            "orders": len(res["trades"])}


def curve_json(curve):
    return [[d, round(v, 4)] for d, v in curve]


def trades_json(trades):
    return [{"date": d, "ticker": t, "side": s, "shares": round(sh, 6),
             "price": round(p, 4), "value": round(v, 2),
             "cost": round(c, 4)} for d, t, s, sh, p, v, c in trades]


# ------------------------------------------------------------ main
def main():
    t0 = time.time()
    bars, equity_rows, shares_rows, data_notes = build_inputs(UNIVERSE60)
    pb = E.PriceBook(bars)
    fb = FastBook(bars)
    assert fb.dates == pb.dates
    print(f"inputs built ({time.time()-t0:.0f}s); bars {fb.dates[0]}..{fb.dates[-1]}",
          flush=True)

    with open(os.path.join(V5DIR, "vm-broad-results.json")) as f:
        v5res = json.load(f)
    v5_val_placebo = {r["seed"]: r["final"]
                      for r in v5res["placebo_validation"]["rows"]}

    integrity = {"status": None, "checks": {}}

    # ---- INTEGRITY 1: original engine, his rules (plain floor, no restart)
    r_cont = E.run_pot(pb, equity_rows, shares_rows, CONT[0], CONT[1],
                       START_CASH, FLOOR0, LADDER, label="INTEGRITY CONT",
                       quiet=True)
    r_val = E.run_pot(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                      START_CASH, FLOOR0, LADDER, label="INTEGRITY VAL",
                      quiet=True)
    integrity["checks"]["original_engine_cont"] = {
        "final": round(r_cont["final"], 2), "halted": r_cont["halted"],
        "signal_close": r_cont["halt_info"]["signal_close"] if r_cont["halt_info"] else None}
    integrity["checks"]["original_engine_val"] = {
        "final": round(r_val["final"], 2), "halted": r_val["halted"]}
    assert round(r_cont["final"], 2) == 82.24 and r_cont["halted"] == "2020-03-18" \
        and r_cont["halt_info"]["signal_close"] == 84.30, integrity["checks"]
    assert round(r_val["final"], 2) == 302.61 and r_val["halted"] is None
    print("INTEGRITY original-engine CONT $82.24 halted 2020-03-18 "
          "(signal close $84.30); VAL $302.61 — MATCH", flush=True)

    # ---- INTEGRITY 2: original engine VAL placebos, per-seed vs published
    val_placebo_finals = {}
    for seed in SEEDS:
        rng = random.Random(seed)
        pr = E.run_pot(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                       START_CASH, FLOOR0, LADDER, placebo_rng=rng,
                       label=f"INTEGRITY PLACEBO s{seed}", quiet=True)
        val_placebo_finals[seed] = round(pr["final"], 2)
    mismatch = {s: (val_placebo_finals[s], v5_val_placebo[s]) for s in SEEDS
                if val_placebo_finals[s] != v5_val_placebo[s]}
    assert not mismatch, f"VAL placebo mismatch vs published: {mismatch}"
    beaten_val = sum(1 for s in SEEDS if val_placebo_finals[s] < 302.61)
    integrity["checks"]["original_engine_val_placebo"] = {
        "per_seed_finals": {str(s): val_placebo_finals[s] for s in SEEDS},
        "seeds_beaten_by_ranked": beaten_val}
    assert beaten_val == 19, beaten_val
    print("INTEGRITY original-engine VAL placebos: all 20 per-seed finals "
          "match the published v5 rows; ranked beats 19/20 — MATCH", flush=True)

    # ---- precompute scores, then prove the fast simulator on quarterly
    scores_by_date = precompute_scores(fb, equity_rows, shares_rows)
    print(f"scores precomputed ({time.time()-t0:.0f}s)", flush=True)
    q_sel_engine = E.quarter_selection_dates(pb, "2016-01-01", "2026-11-20")
    q_sel_mine = cadence_dates(fb.dates, "quarterly", "2016-01-01", "2026-11-20")
    assert q_sel_engine == q_sel_mine, "quarterly cadence dates differ from engine"

    def fast_ep(sel):
        return lambda s, e, c, f, rng=None: run_ep_fast(
            fb, scores_by_date, sel, s, e, c, f, placebo_rng=rng)

    f_cont = run_ep_fast(fb, scores_by_date, q_sel_mine, CONT[0], CONT[1],
                         START_CASH, FLOOR0)
    f_val = run_ep_fast(fb, scores_by_date, q_sel_mine, VAL[0], VAL[1],
                        START_CASH, FLOOR0)
    assert round(f_cont["final"], 2) == 82.24 and f_cont["halted"] == "2020-03-18"
    assert round(f_val["final"], 2) == 302.61
    for seed in SEEDS:
        rng = random.Random(seed)
        pr = run_ep_fast(fb, scores_by_date, q_sel_mine, VAL[0], VAL[1],
                         START_CASH, FLOOR0, placebo_rng=rng)
        assert round(pr["final"], 2) == val_placebo_finals[seed], \
            f"fast placebo seed {seed}: {pr['final']} != {val_placebo_finals[seed]}"
    print("FAST SIMULATOR proven: quarterly his-rules CONT/VAL + all 20 VAL "
          "placebo finals reproduce the original engine to the cent", flush=True)

    # ---- INTEGRITY 3: v9 cross-check on CONT (quarterly), both engines
    def orig_ep(s, e, c, f):
        return E.run_pot(pb, equity_rows, shares_rows, s, e, c, f, LADDER,
                         quiet=True)
    v9_orig = run_v9(orig_ep, pb.dates, q_sel_mine, CONT[0], CONT[1], START_CASH)
    v9_fast = run_v9(fast_ep(q_sel_mine), fb.dates, q_sel_mine,
                     CONT[0], CONT[1], START_CASH)
    integrity["checks"]["v9_cont_quarterly"] = {
        "original_engine_final": round(v9_orig["final"], 2),
        "fast_final": round(v9_fast["final"], 2),
        "restarts": v9_fast["restarts"], "second_halt": v9_fast["second_halt"]}
    assert round(v9_orig["final"], 2) == 346.87, v9_orig["final"]
    assert round(v9_fast["final"], 2) == 346.87
    assert v9_fast["restarts"][0]["restart_date"] == "2020-07-01"
    assert v9_fast["restarts"][0]["restart_balance"] == 82.24
    print("INTEGRITY v9 CONT quarterly: $346.87, restart 2020-07-01 with "
          "$82.24 — MATCH on original engine and fast simulator", flush=True)
    integrity["status"] = "reproduced"
    integrity["original_finals"] = {
        "cont_his_rules": 82.24, "cont_his_halt": "2020-03-18",
        "cont_his_signal_close": 84.30, "val_his_rules": 302.61,
        "val_placebo_beaten": "19/20", "cont_v9": 346.87, "val_v9": 302.61}
    integrity["reproduced_finals"] = {
        "cont_his_rules": round(r_cont["final"], 2),
        "val_his_rules": round(r_val["final"], 2),
        "val_placebo_beaten": f"{beaten_val}/20",
        "cont_v9": round(v9_fast["final"], 2)}

    # ---- SPY references
    spy_cont, _ = E.spy_net(pb, CONT[0], CONT[1], START_CASH)
    spy_val, _ = E.spy_net(pb, VAL[0], VAL[1], START_CASH)
    spy_dec_inplumbing, _ = E.spy_net(pb, DECADE[0], DECADE[1], START_CASH)
    print(f"SPY in-plumbing: CONT ${spy_cont:,.2f} VAL ${spy_val:,.2f} "
          f"DECADE(from first bar 2017-06-01) ${spy_dec_inplumbing:,.2f}; "
          f"SPEC decade SPY ${DECADE_SPY_SPEC:,.2f}", flush=True)

    # ---- SWEEP: decade x 7 cadences, v9 protections, 20-seed placebos
    cells_summary = {}
    money = []
    for cadence in CADENCES:
        sel = cadence_dates(fb.dates, cadence, DECADE[0], DECADE[1])
        ep = fast_ep(sel)
        ranked = run_v9(ep, fb.dates, sel, DECADE[0], DECADE[1], START_CASH)
        summ = summarize(ranked, DECADE[0], DECADE[1])
        placebo_finals = []
        for seed in SEEDS:
            rng = random.Random(seed)
            pr = run_v9(lambda s, e, c, f, _rng=rng: ep(s, e, c, f, rng=_rng),
                        fb.dates, sel, DECADE[0], DECADE[1], START_CASH)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for x in placebo_finals if x < summ["final"])
        summ["placebo_beaten"] = beaten
        summ["placebo_note"] = ("20 seeds (1..20), random 5 from the scored "
                                "pool at each selection, same v9 protections")
        cells_summary[cadence] = dict(
            summ,
            restart_date=(ranked["restarts"][0]["restart_date"]
                          if ranked["restarts"] else None),
            halt_signal_dates=([ranked["restarts"][0]["halt_signal_date"]]
                               if ranked["restarts"] else []) +
                              ([ranked["second_halt"]["signal_date"]]
                               if ranked["second_halt"] else []))
        cell_doc = {
            "slug": "vm-broad", "cadence": cadence,
            "window": {"start": DECADE[0], "end": DECADE[1]},
            "start_cash": START_CASH,
            "selection_dates": sel,
            "first_selection_with_pool_ge5": next(
                (d for d in sel if len(scores_by_date.get(d, {})) >= 5), None),
            "final": summ["final"], "cagr_pct": summ["cagr_pct"],
            "max_dd_pct": summ["max_dd_pct"], "costs": summ["costs"],
            "orders": summ["orders"],
            "halts": summ["halts"], "restart": summ["restart"],
            "second_halt": summ["second_halt"],
            "restarts": ranked["restarts"],
            "second_halt_detail": ranked["second_halt"],
            "placebo_beaten": beaten,
            "placebo_twin_finals": {str(s): placebo_finals[s - 1] for s in SEEDS},
            "equity_curve": curve_json(ranked["curve"]),
            "trades": trades_json(ranked["trades"]),
        }
        with open(os.path.join(CELLS, f"{cadence}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        if summ["final"] > DECADE_SPY_SPEC and beaten == 20:
            money.append(cadence)
        print(f"CELL {cadence:11s} sel={len(sel):4d} final=${summ['final']:,.2f} "
              f"CAGR={summ['cagr_pct']}% DD={summ['max_dd_pct']}% "
              f"costs=${summ['costs']:,.2f} orders={summ['orders']} "
              f"halts={summ['halts']} restart={summ['restart']} "
              f"2ndhalt={summ['second_halt']} placebo {beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)

    # first date each cadence could actually trade (pool >= 5) — evidence
    first_pool = {}
    for cadence in CADENCES:
        sel = cadence_dates(fb.dates, cadence, DECADE[0], DECADE[1])
        first_pool[cadence] = next(
            (d for d in sel if len(scores_by_date.get(d, {})) >= 5), None)

    results = {
        "slug": "vm-broad",
        "area": "long-horizon quarterly value/momentum holding on the pond "
                "(W1: variants of the champion — the champion's road is "
                "their native ground)",
        "area_source": "v10 SPEC, W1 assignment; native pond top-60 kept",
        "native_cadence": "quarterly",
        "cadence": "quarterly",
        "original_cadence_foreign": False,
        "original_cadence_note": "original v5 test ran the native quarterly "
                                 "cadence; no foreign cadence was forced",
        "integrity": integrity,
        "decade_spy_final": DECADE_SPY_SPEC,
        "decade_spy_note": "SPEC dividend-adjusted figure, 2016-11-21 start. "
                           f"In-plumbing SPY on this PriceBook (bars begin "
                           f"2017-06-01) = ${spy_dec_inplumbing:,.2f}; money-"
                           "cadence test uses the stricter SPEC figure.",
        "spy_in_plumbing": {"cont": round(spy_cont, 2),
                            "val": round(spy_val, 2),
                            "decade_from_2017_06_01": round(spy_dec_inplumbing, 2)},
        "champion_windows_v9_quarterly": {
            "cont": {"final": round(v9_fast["final"], 2),
                     "champion_final": 544.47, "spy": round(spy_cont, 2)},
            "val": {"final": 302.61, "champion_final": 288.05,
                    "spy": round(spy_val, 2)},
            "long_2010": None,
            "long_note": "not computable: the top-60 pond is defined as of "
                         "Nov 2016 and the price cache begins 2017-06-01"},
        "first_selection_with_full_pool": first_pool,
        "cells": cells_summary,
        "money_cadences": money,
        "money_cadence_rule": "final > decade SPY $367.80 AND placebo_beaten "
                              "== 20/20 (strict reading of the SPEC anti-luck "
                              "guardrail)",
        "data_notes": data_notes,
        "verdict_area": None,  # filled below
        "verdict_change": None,
    }
    with open(os.path.join(HERE, "run_summary.json"), "w") as f:
        json.dump(results, f, indent=1)
    print(f"SWEEP DONE ({time.time()-t0:.0f}s). Money cadences: {money}",
          flush=True)
    print(json.dumps(cells_summary, indent=1), flush=True)


if __name__ == "__main__":
    main()
