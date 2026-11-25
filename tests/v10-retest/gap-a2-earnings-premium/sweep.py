#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — gap-a2-earnings-premium (A-2, Frazzini & Lamont
earnings announcement premium). Cadence sweep on the DECADE road
2016-11-21 -> 2026-11-20, per backtests/v10-retest/SPEC.md.

CADENCE TREATMENT (stated precisely, per SPEC's uniform definition):
A-2's signal is a monthly attribute: a name is "expected to announce" in
calendar month m if it filed an Item 2.02 earnings 8-K in month m of the
prior year (original reading R1, unchanged). Under the sweep, SELECTION,
REBALANCING and TRADING happen only on cadence dates: at each cadence
date the pot sets equal-weight targets across the expected announcers
OF THE MONTH CONTAINING THAT DATE (cash if none), executed at the next
trading day's open — the champion engine's pending-rebalance mechanics,
verbatim. Monthly cadence therefore reproduces the original strategy
exactly; daily rebalances to equal weight every day within the month;
quarterly/semi-annual/annual hold the selection month's expected set
until the next cadence date. No cadence is mechanically meaningless for
this chassis, so there are no N/A cells.

Protections: adopted v9 rules (plain -15% floor from episode start;
first halt -> liquidate next open, 90 calendar days in cash, restart at
the next cadence date with an episode-2 floor of -15% from the restart
balance; second halt ends the run). Costs: 0.10%/side + $0.01 per sell
order, the original engine's own cost code. Point-in-time throughout.

Data: prices = champion Yahoo cache (from 2017-06-01) with a spliced
2016-09-01..2017-05-31 Yahoo segment in front (prep_data.py; splice
scale factors were 1.000000-1.000001); EDGAR dates = original cache
extended back to 2015-01-01 from EDGAR submissions blocks the original
fetch skipped (prep_data.py; the >=2017-06-01 portion reproduces the
original cached table exactly, all 30 names).

EVENTS (per SPEC event-form reporting): one "event" = one name's
continuous holding stint, opened when a buy takes its position from
zero and closed when the position returns to zero (rotation exit, halt
liquidation, or end-of-window liquidation). Event net return = price
return over the stint minus the round-trip program costs attributable
to it (0.10% buy + 0.10% sell + the $0.01 sell-order charge over the
stint's entry value). Excess = event net return minus SPY's return
over the same entry/exit prices (open-to-open; close for the
end-of-window liquidation).
"""
import datetime as dt
import importlib.util
import json
import os
import random
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "engine", os.path.join(HERE, "engine.py"))
ENG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENG)
E = ENG.E
UNIVERSE = ENG.UNIVERSE
START_CASH = 100.0
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------------ integrity
def integrity():
    """Reproduce the ORIGINAL published finals with the copied engine in
    ORIGINAL form (plain -15% floor, no restart) and in v9 form."""
    earn = ENG.get_earnings_dates()  # local copy of the original EDGAR cache
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)
    pub = {
        "FULL": {"final": 86.12, "costs": 4.08, "orders": 296,
                 "halted": "2020-03-12", "spy_net": 313.62,
                 "v9_final": 197.95},
        "VALIDATION": {"final": 174.48, "costs": 13.86, "orders": 965,
                       "halted": None, "spy_net": 187.77,
                       "v9_final": 174.48},
    }
    out = {}
    ok = True
    for wname, ws, we in ENG.WINDOWS:
        r = ENG.run_monthly(pb, earn, ws, we, label=f"INTEGRITY {wname}")
        v9 = ENG.run_monthly_v9(pb, earn, ws, we, label=f"INTEGRITY-V9 {wname}")
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        p = pub[wname]
        match = (round(r["final"], 2) == p["final"]
                 and round(r["costs"], 2) == p["costs"]
                 and len(r["trades"]) == p["orders"]
                 and r["halted"] == p["halted"]
                 and round(s, 2) == p["spy_net"]
                 and round(v9["final"], 2) == p["v9_final"])
        ok = ok and match
        out[wname] = {
            "window": [ws, we], "published": p,
            "reproduced_original": {
                "final": round(r["final"], 2), "costs": round(r["costs"], 2),
                "orders": len(r["trades"]), "halted": r["halted"],
                "spy_net": round(s, 2)},
            "reproduced_v9_final": round(v9["final"], 2),
            "match": match}
        print(f"INTEGRITY {wname}: orig final=${r['final']:.2f} "
              f"(pub {p['final']}) costs=${r['costs']:.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} "
              f"SPY=${s:.2f} v9=${v9['final']:.2f} match={match}", flush=True)
    out["status"] = "reproduced" if ok else "FAILED"
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    return out


# ------------------------------------------------------------------ cadences
def selection_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "biweekly":
        return selection_dates(pb, start, end, "weekly")[0::2]
    out, seen = [], set()
    for d in days:
        if cadence == "weekly":
            iso = dt.date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
        elif cadence == "monthly":
            key = d[:7]
        elif cadence == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
        elif cadence == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
        elif cadence == "annual":
            key = d[:4]
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------------------------------ runner
def run_cadence(pb, earn_dates, start, end, sel_dates, start_cash=START_CASH,
                floor0=85.0, placebo_rng=None, track_events=False):
    """The original run_monthly mechanics verbatim (execution, costs,
    floor, liquidations), generalized only in WHICH dates are selection
    dates. Trades are counted, not stored (daily cadence makes ~10^5)."""
    cash = start_cash
    floor = floor0
    positions = {}
    n_orders = 0
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    events = []
    stints = {}   # ticker -> {entry_date, entry_price, shares}
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

    def spy_px(d, kind):
        b = pb.bar("SPY", d)
        if kind == "open" and b:
            return b["o"]
        return pb.close_on_or_before("SPY", d)

    def close_stint(t, exit_date, exit_price, kind):
        if not track_events or t not in stints:
            return
        s = stints.pop(t)
        val = s["shares"] * s["entry_price"]
        net = exit_price / s["entry_price"] - 1.0 - 0.002 \
            - (0.01 / val if val else 0.0)
        se, sx = spy_px(s["entry_date"], "open"), spy_px(exit_date, kind)
        exc = net - (sx / se - 1.0) if se and sx else None
        events.append({"ticker": t, "entry_date": s["entry_date"],
                       "exit_date": exit_date,
                       "net_return_pct": round(net * 100, 3),
                       "excess_vs_spy_pct": round(exc * 100, 3)
                       if exc is not None else None})

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs, n_orders
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
                n_orders += 1
                if positions[t] < 1e-9:
                    del positions[t]
                    close_stint(t, d, opens[t], "open")
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
                n_orders += 1
                if positions.get(t, 0.0) <= 0 and track_events:
                    stints[t] = {"entry_date": d, "entry_price": opens[t],
                                 "shares": sh}
                positions[t] = positions.get(t, 0.0) + sh
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            expected = ENG.expected_announcers(earn_dates, d)
            if placebo_rng is not None:
                picks = placebo_rng.sample(sorted(UNIVERSE), len(expected))
            else:
                picks = expected
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}
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
                    n_orders += 1
                    close_stint(t, nd, b["o"], "open")
            positions = {}
            return {"final": cash, "costs": total_costs, "orders": n_orders,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "events": events}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            n_orders += 1
            close_stint(t, last, c_, "close")
    return {"final": cash, "costs": total_costs, "orders": n_orders,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "events": events}


def run_v9(pb, earn_dates, start, end, cadence, placebo_rng=None,
           track_events=False):
    """Adopted v9 protections around run_cadence: plain -15% floor;
    first halt -> 90 calendar days in cash -> restart at the next
    cadence date under an episode-2 floor of -15% from the restart
    balance; second halt ends the run."""
    all_sel = selection_dates(pb, start, end, cadence)
    ep1 = run_cadence(pb, earn_dates, start, end, all_sel,
                      placebo_rng=placebo_rng, track_events=track_events)
    axis = [d for d in pb.dates if start <= d <= end]
    vals = {d: v for d, v in ep1["curve"]}
    res = {"final": ep1["final"], "costs": ep1["costs"],
           "orders": ep1["orders"], "events": ep1["events"],
           "halts": 0, "halt_dates": [], "restart": None,
           "second_halt": False, "status": "no_halt"}
    if not ep1["halted"]:
        res["curve"] = [[d, round(vals[d], 4)] for d in axis]
        return res
    res["halts"] = 1
    res["halt_dates"].append({"signal_date": ep1["halted"],
                              "liquidation_date": ep1["end"],
                              "cash_at_halt": round(ep1["final"], 2),
                              "floor_in_effect": 85.0})
    liq, cash1 = ep1["end"], ep1["final"]
    for d in axis:
        if d >= liq:
            vals[d] = cash1
    eligible = (dt.date.fromisoformat(liq) + dt.timedelta(days=90)).isoformat()
    restart = next((d for d in all_sel if d >= eligible), None)
    if restart is None:
        res["status"] = "halted_ep1_no_restart_in_window"
        res["curve"] = [[d, round(vals[d], 4)] for d in axis]
        return res
    ep2 = run_cadence(pb, earn_dates, restart, end,
                      [d for d in all_sel if d >= restart],
                      start_cash=cash1, floor0=0.85 * cash1,
                      placebo_rng=placebo_rng, track_events=track_events)
    res.update({"final": ep2["final"],
                "costs": ep1["costs"] + ep2["costs"],
                "orders": ep1["orders"] + ep2["orders"],
                "events": ep1["events"] + ep2["events"],
                "restart": {"halt_signal_date": ep1["halted"],
                            "liquidation_date": liq,
                            "cash_at_halt": round(cash1, 2),
                            "eligible_from": eligible,
                            "restart_date": restart,
                            "restart_balance": round(cash1, 2),
                            "episode2_floor": round(0.85 * cash1, 2)},
                "status": "restarted_completed"})
    for d, v in ep2["curve"]:
        vals[d] = v
    if ep2["halted"]:
        res["halts"] = 2
        res["second_halt"] = True
        res["status"] = "halted_ep2_run_ends"
        res["halt_dates"].append({"signal_date": ep2["halted"],
                                  "liquidation_date": ep2["end"],
                                  "cash_at_halt": round(ep2["final"], 2),
                                  "floor_in_effect": round(0.85 * cash1, 2)})
        for d in axis:
            if d >= ep2["end"]:
                vals[d] = ep2["final"]
    res["curve"] = [[d, round(vals[d], 4)] for d in axis]
    return res


def max_dd(curve):
    peak, mdd = 100.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)


def cagr(final, start, end):
    yrs = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days / 365.25
    return round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2)


# ------------------------------------------------------------------ sweep
class FastPriceBook(E.PriceBook):
    """Identical bar selection to the champion PriceBook; close_on_or_before
    via bisect instead of the original's linear scan (plumbing speed only —
    same bar is returned in every case)."""

    def __init__(self, bars_by_ticker):
        super().__init__(bars_by_ticker)
        import bisect as _b
        self._bisect = _b.bisect_right
        self._ds = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}

    def close_on_or_before(self, t, d):
        ds = self._ds.get(t)
        if not ds:
            return None
        i = self._bisect(ds, d)
        return self.bars[t][i - 1]["c"] if i else None


def sweep():
    earn_ext = json.load(open(os.path.join(HERE, "earnings_dates_ext.json")))
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = json.load(open(os.path.join(HERE, "px-ext", f"bars_{t}.json")))
    pb = FastPriceBook(bars)
    spy, _ = E.spy_net(pb, DEC_START, DEC_END, START_CASH)
    print(f"DECADE SPY net (spliced plumbing): ${spy:.2f} "
          f"(SPEC reference $367.80)", flush=True)

    cells = {}
    for cad in CADENCES:
        cpath = os.path.join(CELLS, f"{cad}.json")
        if os.path.exists(cpath):
            cells[cad] = json.load(open(cpath))
            print(f"{cad:11s} (resumed from saved cell)", flush=True)
            continue
        r = run_v9(pb, earn_ext, DEC_START, DEC_END, cad,
                   track_events=True)
        pfinals = []
        for seed in range(1, 21):
            pr = run_v9(pb, earn_ext, DEC_START, DEC_END, cad,
                        placebo_rng=random.Random(seed))
            pfinals.append(round(pr["final"], 2))
        beats = sum(1 for f in pfinals if r["final"] > f)
        ev = r["events"]
        nets = [e["net_return_pct"] for e in ev]
        excs = [e["excess_vs_spy_pct"] for e in ev
                if e["excess_vs_spy_pct"] is not None]
        cell = {
            "cadence": cad, "window": [DEC_START, DEC_END],
            "final": round(r["final"], 2),
            "cagr_pct": cagr(r["final"], DEC_START, DEC_END),
            "max_dd_pct": max_dd(r["curve"]),
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": r["halts"], "halt_dates": r["halt_dates"],
            "restart": r["restart"], "second_halt": r["second_halt"],
            "status": r["status"],
            "placebo_beaten": f"{beats}/20",
            "placebo_twin_finals": pfinals,
            "placebo_median": round(statistics.median(pfinals), 2),
            "event_stats": {
                "events_traded": len(ev),
                "mean_net_return_pct": round(statistics.mean(nets), 3) if nets else None,
                "median_net_return_pct": round(statistics.median(nets), 3) if nets else None,
                "mean_net_excess_vs_spy_pct": round(statistics.mean(excs), 3) if excs else None,
                "median_net_excess_vs_spy_pct": round(statistics.median(excs), 3) if excs else None,
                "events": ev},
            "equity_curve": r["curve"],
            "spy_final": round(spy, 2),
        }
        cells[cad] = cell
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"{cad:11s} final=${r['final']:8.2f} cagr={cell['cagr_pct']:6.2f}% "
              f"mdd={cell['max_dd_pct']:7.2f}% costs=${r['costs']:7.2f} "
              f"orders={r['orders']:6d} halts={r['halts']} "
              f"events={len(ev):4d} meanExc="
              f"{cell['event_stats']['mean_net_excess_vs_spy_pct']}% "
              f"placebo {beats}/20 (med ${cell['placebo_median']:.2f})",
              flush=True)
    return cells, round(spy, 2)


if __name__ == "__main__":
    integ = integrity()
    if integ["status"] != "reproduced":
        print("INTEGRITY FAILED — sweep still run, flagged in results.",
              flush=True)
    cells, spy = sweep()
    json.dump({"integrity_status": integ["status"], "decade_spy": spy,
               "cells": {c: {k: v for k, v in cell.items()
                             if k not in ("equity_curve",)}
                         | {"event_stats": {k: v for k, v in
                                            cell["event_stats"].items()
                                            if k != "events"}}
                        for c, cell in cells.items()}},
              open(os.path.join(HERE, "sweep-summary.json"), "w"), indent=1)
    print("SWEEP DONE")
