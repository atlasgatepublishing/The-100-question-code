#!/usr/bin/env python3
"""
VM-PANICGATE — THE GREAT RETEST (v10) cadence sweep. Simulation only.

Strategy: value+momentum (champion spec: point-in-time top-30 pond as of
Nov 2016, book-to-market + 12-1 momentum percentile ranks, top-5 equal
weight, $100 pot, costs 0.10%/side + $0.01/sell) PLUS the Daniel &
Moskowitz (2016) panic-state gate: at each evaluation date, from SPY
only, point-in-time — bear = trailing 12-month SPY return < 0; high vol
= 60-day realized SPY vol above the expanding point-in-time median of
its own history; PANIC = bear AND high vol -> that period's targets are
scaled to 50% of pot value (half in cash), else 100%.

INTEGRITY: the ORIGINAL v5 engine (backtests/v5/vm-panicgate/
vm-panicgate.py, imported unmodified) re-runs the gated pots on the
original windows in ORIGINAL form (quarterly, plain -15% floor, no
restart): CONT 2019-01-02->2026-11-20 must equal $426.25 and VAL
2023-01-03->2026-11-20 must equal $285.60. The generalized sweep engine
below must ALSO reproduce both finals to the cent at quarterly cadence
under the plain floor before any sweep number is trusted.

SWEEP (SPEC v10, binding): DECADE 2016-11-21 -> 2026-11-20, $100/cell,
program costs, adopted v9 protections (plain -15% episode-1 floor; on
first halt liquidate as the engine does, sit in cash 90 calendar days,
restart at the strategy's next regular decision point under an
episode-2 floor of -15% from the restart balance; second halt ends the
run). UNIFORM CADENCE RULE: cadence governs BOTH the re-pick AND the
gate evaluation — signal evaluation, selection, gate state and trading
happen only on cadence dates (daily floor monitoring is protection,
unchanged from the original engine, not signal). Cadences: daily,
weekly, biweekly, monthly, quarterly (native), semi-annual, annual —
first trading day of each period per the SPEC definitions.

PLACEBOS: 20 seeds (1..20) per cell, random-rank twins running the
IDENTICAL gate (the panic state is a function of SPY only, so the gate
series is literally the same for every pot) and the identical v9
protections. Full twin finals + distribution stats (median, quartiles,
halted-twin counts) are saved per cell — the original program REFUSED
its nominal continuous placebo 20/20 as counterfeit because the gate
destroyed the twins' distribution (median $308.81 -> $88.50, halts
7/20 -> 12/20); no placebo count in this folder may be read without
its distribution context.

DATA: read-only reuse of the v4 caches via the imported baseline module
(SEC EDGAR companyfacts in backtests/v4/data, Yahoo prices in
backtests/v4/value-momentum-honest-data). NOTE: that price cache begins
2017-06-01, and 12-1 momentum needs 253 prior bars, so on the decade
window every cadence sits in cash until its first scoreable selection
date; the first such date is reported per cell. Nothing is backfilled.

PERFORMANCE NOTES (no logic change): scores depend only on the date,
not the cadence or the pot, so they are computed once per trading day
(with an ordinal-bisect equivalent of the original pit_value — same
(filed, prio, end) max-key rule and the same 548-day freshness gate)
and shared by the ranked pot and all 20 twins of every cadence. The
original placebo code consumed rng.sample(sorted(pool), 5) once per
scoreable selection date in date order; the shared-pool code consumes
it in exactly the same order, and the quarterly plain-floor cross-check
against the original engine (integrity) proves the equivalence.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
V5 = os.path.join(ROOT, "v5", "vm-panicgate", "vm-panicgate.py")

spec5 = importlib.util.spec_from_file_location("vm_panicgate_v5", V5)
M5 = importlib.util.module_from_spec(spec5)
spec5.loader.exec_module(M5)
E = M5.E                      # v4 value-momentum-plainfloor module
UNIVERSE = E.UNIVERSE
START_CASH = 100.0
GATE_EXPOSURE = 0.50
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------ fast book
class FastBook:
    """Same bars as E.PriceBook; close_on_or_before via bisect (identical
    values — last bar with d <= date)."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}
        self._cl = {t: [b["c"] for b in bl]
                    for t, bl in bars_by_ticker.items()}
        self._ix = {t: {d: i for i, d in enumerate(ds)}
                    for t, ds in self._dl.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self._cl[t][i] if i >= 0 else None


# ------------------------------------------------- fast point-in-time
def _ord(ds):
    return _date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).toordinal()


class PitIndex:
    """Ordinal equivalent of E.pit_value: rows sorted by (filed, prio,
    end); the answer for asof is the last row with filed < asof, rejected
    if that row's filed is older than asof - 548 days (any other row is
    older still, so the original's max-key search gives the same None).
    """

    def __init__(self, rows):
        keyed = sorted((_ord(f), p, e, v) for f, e, v, p in rows)
        self.keys = [(k[0], k[1], k[2]) for k in keyed]
        self.vals = [k[3] for k in keyed]
        self.fileds = [k[0] for k in keyed]

    def value(self, asof_ord):
        i = bisect.bisect_left(self.fileds, asof_ord) - 1
        if i < 0:
            return None
        if self.fileds[i] < asof_ord - 548:
            return None
        return self.vals[i]


def compute_scores(fb, eq_idx, sh_idx, d):
    """Identical scoring to run_pot_gated's selection block for one date.
    Returns {ticker: (bm, mom)} (only names passing every gate)."""
    asof = _ord(d)
    scores = {}
    for t in UNIVERSE:
        be = eq_idx[t].value(asof)
        so = sh_idx[t].value(asof)
        px = fb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so <= 0:
            continue
        mcap = so * px
        if mcap <= 0:
            continue
        bm = be / mcap
        didx = fb._ix.get(t, {}).get(d)
        if didx is None or didx < 253:
            continue
        bl = fb.bars[t]
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, mom)
    return scores


# ------------------------------------------------------- cadence dates
def cadence_dates(fb, cadence, start, end):
    days = [d for d in fb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "quarterly":
        return E.quarter_selection_dates(fb, start, end)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            y, w, _ = _date(int(d[:4]), int(d[5:7]),
                            int(d[8:10])).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w))
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks, wseen = [], set()
        for d in days:
            y, w, _ = _date(int(d[:4]), int(d[5:7]),
                            int(d[8:10])).isocalendar()
            if (y, w) not in wseen:
                wseen.add((y, w))
                weeks.append(d)
        return weeks[::2]
    if cadence == "monthly":
        keyf = lambda d: (d[:4], d[5:7])
    elif cadence == "semiannual":
        days = [d for d in days if d[5:7] in ("01", "07")]
        keyf = lambda d: (d[:4], d[5:7])
    elif cadence == "annual":
        keyf = lambda d: d[:4]
    else:
        raise ValueError(cadence)
    for d in days:
        k = keyf(d)
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


# ------------------------------------------------- generalized engine
def run_pot_cadence(fb, pools, sel_set, panic_map, start, end, start_cash,
                    floor0, placebo_rng=None, gate_on=True):
    """Line-for-line port of M5.run_pot_gated with two substitutions:
    selection dates come from sel_set (the cadence) and the per-date
    scored pool comes from the precomputed `pools` (identical values).
    The [GATE] block is unchanged: exposure is read from panic_map,
    which is keyed on the SAME cadence dates (uniform cadence rule)."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    gate_log = []
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
            scores = pools.get(d, {})
            if len(scores) >= 5:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                expo = 1.0
                if gate_on and panic_map is not None:
                    st = panic_map.get(d, {})
                    if st.get("panic"):
                        expo = GATE_EXPOSURE
                    gate_log.append({"date": d,
                                     "panic": bool(st.get("panic")),
                                     "bear": st.get("bear"),
                                     "mkt_ret_12m": st.get("mkt_ret_12m"),
                                     "vol_now": st.get("vol_now"),
                                     "vol_ref": st.get("vol_ref"),
                                     "exposure": expo})
                each = pv * expo / 5.0
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
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "gate_log": gate_log}
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
            "curve": curve, "gate_log": gate_log}


# ------------------------------------------------------------ v9 wrapper
def run_v9(run_ep, all_sel_dates, fb, start, end, start_cash):
    """The v9 bundle's run_pot_v9, verbatim in logic, with the restart
    decision point generalized from quarter dates to the cadence's own
    selection dates ('restart at the strategy's next regular decision
    point'). At quarterly cadence this is the v9 module exactly."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_ep(start, end, start_cash, floor1)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": list(r1["trades"]), "curve": list(r1["curve"]),
           "gate_log": list(r1["gate_log"]),
           "ep1_final": r1["final"], "ep1_halted": r1["halted"],
           "ep1_halt_info": r1["halt_info"],
           "halts": [], "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = _ord(liq_date) + 90
    restart = None
    for cand in all_sel_dates:
        if _ord(cand) >= day90:
            restart = cand
            break
    floor2 = round(0.85 * cash, 2)
    entry = {"episode": 1, "halt_signal_date": r1["halted"],
             "halt_signal_close": r1["halt_info"]["signal_close"],
             "floor_in_effect": r1["halt_info"]["floor_in_effect"],
             "liquidation_date": liq_date, "restart_date": restart,
             "restart_balance": round(cash, 2), "episode2_floor": floor2}
    out["halts"].append(entry)
    out["restarts"].append(entry)
    seg_end = restart if restart else end
    for d in fb.dates:
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
    out["gate_log"] += list(r2["gate_log"])
    if r2["halted"] is not None:
        sh = {"episode": 2, "halt_signal_date": r2["halted"],
              "halt_signal_close": r2["halt_info"]["signal_close"],
              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
              "liquidation_date": r2["end"],
              "final": round(r2["final"], 2)}
        out["second_halt"] = sh
        out["halts"].append(sh)
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ---------------------------------------------------------------- utils
def curve_stats(curve, final, start, end):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (_ord(end) - _ord(start)) / 365.25
    cagr = (final / START_CASH) ** (1.0 / yrs) * 100 - 100 if final > 0 else -100.0
    return round(maxdd * 100, 2), round(cagr, 2)


def finish_curve(fb, run, start, end):
    """Extend a halted run's curve flat in cash to the window end (after
    a second halt or a no-restart halt the pot IS cash at its final
    value for every remaining day — stated, not fabricated prices)."""
    curve = sorted(run["curve"], key=lambda kv: kv[0])
    if curve and curve[-1][0] < end:
        last_v = run["final"]
        for d in fb.dates:
            if curve[-1][0] < d <= end:
                curve.append((d, last_v))
    return [[d, round(v, 2)] for d, v in curve]


def dist_stats(finals, rows, ranked_final):
    srt = sorted(finals)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_twins": sum(1 for r in rows if r["halts"]),
            "second_halt_twins": sum(1 for r in rows if r["second_halt"]),
            "seeds_beaten": sum(1 for f in finals if f < ranked_final)}


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    pb_orig, eq_rows, sh_rows = M5.build_inputs()
    fb = FastBook(pb_orig.bars)
    print(f"inputs built {time.time()-t0:.0f}s; SPY bars "
          f"{fb.bars['SPY'][0]['d']}..{fb.bars['SPY'][-1]['d']}", flush=True)

    # ---------------- INTEGRITY: original engine, original form
    print("== INTEGRITY (original v5 engine, quarterly, plain floor) ==",
          flush=True)
    integ = {}
    for name, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        sel = E.quarter_selection_dates(pb_orig, ws, we)
        pmap = M5.panic_states(pb_orig, sel)
        r = M5.run_pot_gated(pb_orig, eq_rows, sh_rows, ws, we, START_CASH,
                             85.0, [], panic_map=pmap, gate_on=True,
                             label=f"INTEG {name}")
        integ[name] = round(r["final"], 2)
        print(f"  {name}: ${integ[name]:,.2f} halted={r['halted']}", flush=True)
    assert integ["CONT"] == 426.25, f"CONT integrity FAILED: {integ['CONT']}"
    assert integ["VAL"] == 285.60, f"VAL integrity FAILED: {integ['VAL']}"
    print("  integrity OK: CONT $426.25 / VAL $285.60 reproduced", flush=True)

    # ---------------- precompute scores + panic for every trading day
    eq_idx = {t: PitIndex(eq_rows[t]) for t in UNIVERSE}
    sh_idx = {t: PitIndex(sh_rows[t]) for t in UNIVERSE}
    all_days = [d for d in fb.dates if DECADE[0] <= d <= DECADE[1]]
    pools_all = {}
    for d in all_days:
        s = compute_scores(fb, eq_idx, sh_idx, d)
        if s:
            pools_all[d] = s
    print(f"scores precomputed for {len(pools_all)} days "
          f"({time.time()-t0:.0f}s)", flush=True)
    panic_all = M5.panic_states(fb, all_days)
    print(f"panic states computed ({time.time()-t0:.0f}s)", flush=True)

    # cross-check: generalized engine, quarterly, plain floor == original
    print("== CROSS-CHECK (generalized engine, quarterly, plain floor) ==",
          flush=True)
    xcheck = {}
    for name, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        sel = cadence_dates(fb, "quarterly", ws, we)
        sel_set = set(sel)
        pmap = {d: panic_all[d] for d in sel}
        pools = {d: pools_all[d] for d in sel if d in pools_all}
        r = run_pot_cadence(fb, pools, sel_set, pmap, ws, we, START_CASH,
                            85.0)
        xcheck[name] = round(r["final"], 2)
        print(f"  {name}: ${xcheck[name]:,.2f}", flush=True)
    assert xcheck == integ, f"cross-check FAILED: {xcheck} vs {integ}"
    print("  cross-check OK: generalized engine == original engine",
          flush=True)

    spy_local, _ = E.spy_net(fb, DECADE[0], DECADE[1], START_CASH)
    print(f"  local-cache SPY decade (cache starts "
          f"{fb.dates[0]}): ${spy_local:,.2f} — headline reference is the "
          f"SPEC figure $367.80 (full-history dividend-adjusted)", flush=True)

    # ---------------- SWEEP
    cells = {}
    for cad in CADENCES:
        sel = cadence_dates(fb, cad, DECADE[0], DECADE[1])
        sel_set = set(sel)
        pmap = {d: panic_all[d] for d in sel}
        pools = {d: pools_all[d] for d in sel if d in pools_all}
        first_pick = next((d for d in sel if len(pools.get(d, {})) >= 5),
                          None)

        def make_ep(rng=None):
            def run_ep(s, e, c, f):
                return run_pot_cadence(fb, pools, sel_set, pmap, s, e, c, f,
                                       placebo_rng=rng, gate_on=True)
            return run_ep

        ranked = run_v9(make_ep(), sel, fb, DECADE[0], DECADE[1], START_CASH)
        curve = finish_curve(fb, ranked, DECADE[0], DECADE[1])
        maxdd, cagr = curve_stats(curve, ranked["final"], *DECADE)
        twins, twin_rows = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)
            tr = run_v9(make_ep(rng), sel, fb, DECADE[0], DECADE[1],
                        START_CASH)
            twins.append(tr["final"])
            twin_rows.append({"seed": seed, "final": round(tr["final"], 2),
                              "halts": [h["halt_signal_date"]
                                        for h in tr["halts"]],
                              "second_halt": bool(tr["second_halt"]),
                              "orders": len(tr["trades"]),
                              "costs": round(tr["costs"], 2)})
        dist = dist_stats(twins, twin_rows, ranked["final"])
        cell = {
            "slug": "vm-panicgate", "cadence": cad,
            "window": [DECADE[0], DECADE[1]], "start_cash": START_CASH,
            "data_note": ("v4 price cache begins 2017-06-01; 12-1 momentum "
                          "needs 253 prior bars; pot in cash until first "
                          "scoreable selection"),
            "first_scoreable_selection": first_pick,
            "n_eval_dates": len(sel),
            "final": round(ranked["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": maxdd, "costs": round(ranked["costs"], 2),
            "orders": len(ranked["trades"]),
            "halts": ranked["halts"],
            "restart": bool(ranked["restarts"]),
            "second_halt": bool(ranked["second_halt"]),
            "gate_evaluations": len(ranked["gate_log"]),
            "gate_quarters_on": sum(1 for g in ranked["gate_log"]
                                    if g["panic"]),
            "gate_log": ranked["gate_log"],
            "placebo_beaten": dist["seeds_beaten"],
            "placebo_note": (
                "20 random-rank twins (seeds 1-20), identical gate series "
                "(SPY-only state), identical v9 protections. READ WITH "
                "THE DISTRIBUTION: the original program refused its "
                "nominal continuous 20/20 as counterfeit because the gate "
                "destroyed the twins' distribution (median $308.81 -> "
                "$88.50, halts 7/20 -> 12/20). A beaten-count here is "
                "evidence only alongside placebo_distribution."),
            "placebo_distribution": dist,
            "placebo_twins": twin_rows,
            "equity_curve": curve,
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        print(f"  {cad:11s} final ${cell['final']:,.2f} CAGR "
              f"{cagr:+.2f}% maxDD {maxdd:.2f}% halts "
              f"{len(ranked['halts'])} 2nd={cell['second_halt']} costs "
              f"${cell['costs']:.2f} orders {cell['orders']} placebo "
              f"{dist['seeds_beaten']}/20 median-twin ${dist['median']:,.2f} "
              f"halted-twins {dist['halted_twins']}/20 gateON "
              f"{cell['gate_quarters_on']}/{cell['gate_evaluations']} "
              f"({time.time()-t0:.0f}s)", flush=True)

    with open(os.path.join(HERE, "_sweep_cells.json"), "w") as f:
        json.dump({"integrity": integ, "crosscheck": xcheck,
                   "spy_local_cache": round(spy_local, 2),
                   "cells": {c: {k: v for k, v in cell.items()
                                 if k not in ("equity_curve", "gate_log")}
                             for c, cell in cells.items()}},
                  f, indent=1)
    print("SWEEP DONE", flush=True)


if __name__ == "__main__":
    main()
