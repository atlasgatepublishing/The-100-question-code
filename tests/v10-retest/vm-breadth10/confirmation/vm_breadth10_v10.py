#!/usr/bin/env python3
"""
V10 GREAT RETEST — vm-breadth10 (value+momentum, top-10 holdings).
Simulation only. One clean shot, no tuning.

(1) INTEGRITY: the ORIGINAL v5 engine (backtests/v5/vm-breadth10/vm-breadth10.py,
    imported unmodified) must reproduce its published finals in original form
    (plain -15% floor, quarterly, original v4 caches):
      CONT 2019-01-02 -> 2026-11-20 : $416.08
      VAL  2023-01-03 -> 2026-11-20 : $259.73

(2) CADENCE SWEEP: DECADE 2016-11-21 -> 2026-11-20, $100/cell, at
    daily / weekly / biweekly / monthly / quarterly / semi-annual / annual
    under the SPEC's uniform cadence definition (signal evaluation, selection
    and trading ONLY on cadence dates; first trading day of the period;
    rebalance at next open, exactly as the original engine does).
    Protections: adopted v9 rules — plain -15% floor from the episode start
    balance; on first halt: liquidate at next open (the engine's own rule),
    sit in cash 90 calendar days, restart at the next cadence selection date
    on/after liquidation+90d under an episode-2 floor of -15% from the
    restart balance; second halt ends the run.
    Costs: program conventions, identical to the original engine
    (0.10%/side + $0.01 per sell order).
    Placebos: 20 seeds (1..20) per cell — random-rank twins drawing 10 names
    from the same scored pool at each selection, run under the same v9
    protection wrapper.

Engine note: the sweep engine below replicates v4 value-momentum-plainfloor
run_pot's mechanics byte-for-byte in logic (same scoring: book-to-market +
12-1 momentum percentile-rank average, top 10, equal weight; same PIT EDGAR
rules incl. the 548-day filed-freshness gate; same execution, halt and
end-of-window liquidation rules), with two mechanical generalizations:
  (a) the selection-date set is a parameter (the cadence), and
  (b) point-in-time fact lookup and close lookup use bisect over
      pre-sorted lists — provably the same values the original linear
      scans return (pit_value's max over key (filed, prio, end) is the
      latest filed date's best (prio, end) row).
The quarterly sweep cell uses the same selection dates as the original
engine's quarter_selection_dates.

Data (all read-only shared caches):
  - Prices: full-history Yahoo payloads in backtests/v7/long-hold/data/
    pxfull_*.json, parsed with the original engine's adjclose-ratio method
    (needed so 12-1 momentum exists at the 2016-11-21 decade start).
  - Fundamentals: SEC EDGAR companyfacts through the original engine's own
    loaders (v4/data cache) — identical chains to the original test.
Outputs are written ONLY into this folder: cells/<cadence>.json,
results.json. RESULTS.md is written by hand from those files.
"""
import bisect
import importlib.util
import json
import os
import random
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH = 100.0
SEEDS = list(range(1, 21))
DEC = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# Original engines, unmodified.
E = load_module("vm_plainfloor", os.path.join(BT, "v4", "value-momentum-plainfloor.py"))
V5 = load_module("vm_breadth10_v5", os.path.join(BT, "v5", "vm-breadth10", "vm-breadth10.py"))
UNIVERSE = E.UNIVERSE

# ------------------------------------------------------------------ inputs
def build_fundamentals():
    """Identical to v5 build_inputs (EDGAR chains), minus price loading."""
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
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
    return equity_rows, shares_rows


def parse_payload(blob):
    """Same adjclose-ratio parsing as v4 get_prices."""
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


def build_pricebook_full():
    lh = os.path.join(BT, "v7", "long-hold", "data")
    lr = os.path.join(BT, "long-run-2010", "data")
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        path = os.path.join(lh, f"pxfull_{t}.json")
        if not os.path.exists(path):
            # GOOGL's full-history payload lives in the long-run-2010 cache
            # (same Yahoo payload format); v7/long-hold only carries GOOG.
            path = os.path.join(lr, f"pxfull_{t}.json")
        with open(path, "rb") as f:
            bars[t] = parse_payload(f.read())
    return FastBook(bars)


class FastBook:
    """PriceBook with bisect lookups; identical values to E.PriceBook."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.dlist = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self.didx = {t: {d: i for i, d in enumerate(ds)}
                     for t, ds in self.dlist.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self.dlist.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ------------------------------------------------------- fast PIT lookup
class PitIndex:
    """Replicates E.pit_value exactly: among rows filed strictly before
    asof and filed within 548 days of asof, the winner is the max by
    (filed, prio, end) — i.e. the latest filed date, its best (prio, end)."""

    def __init__(self, rows):
        best = {}
        for filed, end, val, prio in rows:
            cur = best.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best[filed] = (prio, end, val)
        self.fileds = sorted(best)
        self.vals = [best[f] for f in self.fileds]
        self.ords = [date.fromisoformat(f).toordinal() for f in self.fileds]

    def value(self, asof):
        i = bisect.bisect_left(self.fileds, asof) - 1  # last filed < asof
        if i < 0:
            return None
        cutoff = date.fromisoformat(asof).toordinal() - 548
        if self.ords[i] < cutoff:
            return None
        prio, end, val = self.vals[i]
        return (self.fileds[i], end, val)


# ------------------------------------------------------------- cadences
def selection_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return E.quarter_selection_dates(pb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            k = date.fromisoformat(d).isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            k = date.fromisoformat(d).isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        for d in days:
            k = d[:7]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    if cadence == "semiannual":
        for d in days:
            if d[5:7] in ("01", "07"):
                k = (d[:4], d[5:7])
                if k not in seen:
                    seen.add(k)
                    out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            k = d[:4]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    raise ValueError(cadence)


# ------------------------------------------------------------ sweep engine
def run_episode(pb, pit_eq, pit_sh, start, end, start_cash, floor, sel_set,
                placebo_rng=None):
    """One episode. Logic replicates v4 run_pot (top-10 form) exactly,
    with sel_set in place of quarter_selection_dates."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
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
            scores = {}
            for t in UNIVERSE:
                be = pit_eq[t].value(d)
                so = pit_sh[t].value(d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                bl = pb.bars.get(t, [])
                didx = pb.didx.get(t, {}).get(d)
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 10:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 10)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:10]
                pv = portfolio_close(d)
                each = pv / 10.0
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
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None, "curve": curve}


def run_v9(pb, pit_eq, pit_sh, start, end, sel_dates, placebo_rng=None):
    """Adopted v9 protection wrapper (generalized from the v9 bundle):
    restart at the next cadence selection date on/after liquidation+90d."""
    sel_set = set(sel_dates)
    floor1 = round(0.85 * START_CASH, 2)
    r1 = run_episode(pb, pit_eq, pit_sh, start, end, START_CASH, floor1,
                     sel_set, placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"], "trades": r1["trades"],
           "curve": list(r1["curve"]), "halts": 0, "restart": False,
           "second_halt": False, "restarts": [], "second_halt_info": None}
    if r1["halted"] is None:
        return out
    out["halts"] = 1
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = date.fromisoformat(liq_date).toordinal() + 90
    restart = None
    for cand in sel_dates:
        if date.fromisoformat(cand).toordinal() >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "liquidation_date": liq_date, "restart_date": restart,
        "restart_balance": round(cash, 2), "episode2_floor": floor2})
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    out["restart"] = True
    r2 = run_episode(pb, pit_eq, pit_sh, restart, end, cash, floor2,
                     sel_set, placebo_rng=placebo_rng)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += r2["curve"]
    if r2["halted"] is not None:
        out["halts"] = 2
        out["second_halt"] = True
        out["second_halt_info"] = {
            "signal_date": r2["halted"],
            "signal_close": r2["halt_info"]["signal_close"],
            "floor_in_effect": r2["halt_info"]["floor_in_effect"],
            "liquidation_date": r2["end"], "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d}


def cagr_pct(final, start, end):
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2)


# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    equity_rows, shares_rows = build_fundamentals()
    pit_eq = {t: PitIndex(equity_rows[t]) for t in UNIVERSE}
    pit_sh = {t: PitIndex(shares_rows[t]) for t in UNIVERSE}

    # ---------------- INTEGRITY: original v5 engine, original form/caches
    pb_orig = V5.build_inputs()[0]  # v5's own PriceBook from v4 caches
    integrity = {}
    for name, (ws, we), expect in (("CONT", CONT, 416.08), ("VAL", VAL, 259.73)):
        r = V5.run_pot10(pb_orig, equity_rows, shares_rows, ws, we,
                         START_CASH, 85.0, [], label=f"INTEGRITY {name}",
                         quiet=True)
        integrity[name] = {"window": [ws, we], "expected": expect,
                           "reproduced": round(r["final"], 2),
                           "match": abs(r["final"] - expect) < 0.02,
                           "costs": round(r["costs"], 2),
                           "orders": len(r["trades"]), "halted": r["halted"]}
        print(f"INTEGRITY {name}: ${r['final']:,.2f} expected ${expect} "
              f"match={integrity[name]['match']}", flush=True)
    assert all(v["match"] for v in integrity.values()), "INTEGRITY FAILED"

    # Cross-check: my sweep engine at quarterly on CONT/VAL, original caches,
    # plain floor single episode, must equal the same finals.
    for name, (ws, we), expect in (("CONT", CONT, 416.08), ("VAL", VAL, 259.73)):
        pbq = FastBook(pb_orig.bars)
        sel = selection_dates(pbq, "quarterly", ws, we)
        r = run_episode(pbq, pit_eq, pit_sh, ws, we, START_CASH, 85.0, set(sel))
        ok = abs(r["final"] - expect) < 0.02
        print(f"SWEEP-ENGINE XCHECK {name} quarterly: ${r['final']:,.2f} "
              f"match={ok}", flush=True)
        assert ok, "sweep engine does not replicate the original engine"

    # ---------------- SWEEP on the decade, full-history prices
    pb = build_pricebook_full()
    spy_final, spy_costs = E.spy_net(pb, DEC[0], DEC[1], START_CASH)
    print(f"DECADE SPY net: ${spy_final:,.2f} (SPEC reference $367.80)",
          flush=True)

    cells = {}
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    for cad in CADENCES:
        sel = selection_dates(pb, cad, DEC[0], DEC[1])
        r = run_v9(pb, pit_eq, pit_sh, DEC[0], DEC[1], sel)
        diag = diagnostics(r["curve"])
        placebo_finals = []
        for seed in SEEDS:
            pr = run_v9(pb, pit_eq, pit_sh, DEC[0], DEC[1], sel,
                        placebo_rng=random.Random(seed))
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if f < r["final"])
        cell = {"final": round(r["final"], 2),
                "cagr_pct": cagr_pct(r["final"], DEC[0], DEC[1]),
                "max_dd_pct": diag["max_dd_pct"],
                "max_dd_date": diag["max_dd_date"],
                "worst_close": diag["worst_close"],
                "worst_close_date": diag["worst_close_date"],
                "costs": round(r["costs"], 2), "orders": len(r["trades"]),
                "halts": r["halts"], "restart": r["restart"],
                "second_halt": r["second_halt"],
                "restarts": r["restarts"],
                "second_halt_info": r["second_halt_info"],
                "placebo_beaten": beaten,
                "placebo_note": "20 seeds (1..20), random-rank top-10 twins "
                                "from the same scored pool, same v9 wrapper",
                "placebo_finals": placebo_finals,
                "selection_dates_count": len(sel)}
        cells[cad] = cell
        cell_doc = dict(cell)
        cell_doc.update({
            "slug": "vm-breadth10", "cadence": cad, "window": list(DEC),
            "start_cash": START_CASH, "decade_spy_final": round(spy_final, 2),
            "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]]})
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        print(f"CELL {cad}: final=${r['final']:,.2f} CAGR={cell['cagr_pct']}% "
              f"maxDD={diag['max_dd_pct']}% costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halts={r['halts']} "
              f"restart={r['restart']} second_halt={r['second_halt']} "
              f"placebo beaten {beaten}/20", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > spy_final and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "vm-breadth10",
        "area": "long-horizon quarterly value/momentum holding on the pond "
                "(W1 V+M variant family — the champion's road)",
        "area_source": "SPEC W1 assignment + CADENCE GRID (W1: quarterly, native)",
        "native_cadence": "quarterly",
        "cadence": "quarterly",
        "original_cadence_foreign": False,
        "native_change": "none in form — original test was already quarterly "
                         "top-10 on the same pond; the sweep varies only the "
                         "decision cadence, and protection is the adopted v9 "
                         "form (identical on the original windows: floor "
                         "never fired there)",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT": 416.08, "VAL": 259.73},
            "reproduced_finals": {k: v["reproduced"] for k, v in integrity.items()},
            "detail": integrity,
            "note": "Original v5 engine imported unmodified, run in original "
                    "form (plain floor, quarterly, v4 caches). Sweep engine "
                    "cross-checked to reproduce both finals at quarterly "
                    "before the sweep ran."},
        "decade_spy_final": round(spy_final, 2),
        "decade_window": list(DEC),
        "cells": {c: {k: v for k, v in cells[c].items()
                      if k not in ("placebo_finals", "worst_close",
                                   "worst_close_date", "max_dd_date",
                                   "selection_dates_count")}
                  for c in CADENCES},
        "money_cadences": money,
        "verdict_area": None,  # filled in RESULTS.md narrative; set below
        "champion_reference": {
            "decade_final": 65.89,
            "note": "champion decade $65.89 came with two halts on this road; "
                    "its crown rests on the 2010/2019 roads (SPEC)"},
        "runtime_sec": round(time.time() - t0, 1),
    }
    # Verdict per SPEC scale, judged on its own ground (the decade sweep):
    if money:
        results["verdict_area"] = "OWNS ITS GROUND" if "quarterly" in money else "REAL BUT SMALL"
    else:
        results["verdict_area"] = "NO GROUND"
    results["verdict_change"] = None
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"DONE in {time.time() - t0:.0f}s. money_cadences={money} "
          f"verdict={results['verdict_area']}", flush=True)


if __name__ == "__main__":
    main()
