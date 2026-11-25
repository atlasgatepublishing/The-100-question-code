#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-PV2 THE LAST SELLER, DECADE road
2016-11-21 -> 2026-11-20. Simulation only.

CADENCE TREATMENT (stated, per SPEC event-driven rule): the event
rule stays exactly as published — signals detected on daily bars
(126-day volume high + close-to-close return <= -1.5%), entries at
the NEXT session's open, ranked by volume ratio, max 5 concurrent,
1/5-of-pot slices. Cadence governs the position review / exit-check
rhythm ONLY: a position's published exit (open of the entry name's
bar 20 bars after entry) becomes DUE on that date but is executed at
the open of the first cadence date on/after the due date on which
the name actually trades. At the daily cadence this is the original
form exactly (check: the daily cell must reproduce the area DECADE
run, $72.58). The ranked plan's held/slot eligibility uses the same
effective (cadence-deferred) exit dates, so max-5 and one-per-name
track the positions actually held. The v9 -15% floor remains a
DAILY close check with next-open liquidation (the adopted
protection, not the strategy's tempo — same convention as the
sibling PV1 sweep). Restart: cash 90 calendar days, resume at the
eligibility date under an episode-2 floor of -15% from the restart
balance; second halt ends the run (driver.py's wrapper, unchanged).

Placebos per cell: the original design — replay the ranked run's
taken slots (per episode) with uniform random pond names, seeds
1..20, same v9 wrapper, same cadence-deferred exits.
Costs: 0.10%/side + $0.01/sell order (engine's own code). $100/cell.
"""
import importlib.util, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv2", os.path.join(HERE, "integrity", "novel-pv2-last-seller.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def load_payload(ticker):
    if ticker == "GOOGL":
        return json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    return json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
M.load_payload = load_payload

BARS = {t: M.get_bars(t) for t in M.POND + ["SPY"]}
PB = M.PriceBook(BARS)
EVENTS = M.detect_events(PB)
CAL = PB.dates
START, END = "2016-11-21", "2026-11-20"
DAYS = [d for d in CAL if START <= d <= END]
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

def cadence_dates(name):
    if name == "daily":
        return list(DAYS)
    if name == "biweekly":
        wk, seen = [], set()
        for d in DAYS:
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key); wk.append(d)
        return wk[::2]
    firsts, seen = [], set()
    for d in DAYS:
        if name == "weekly":
            iso = date.fromisoformat(d).isocalendar(); key = (iso[0], iso[1])
        elif name == "monthly":
            key = d[:7]
        elif name == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
        elif name == "semiannual":
            key = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
        elif name == "annual":
            key = d[:4]
        if key not in seen:
            seen.add(key); firsts.append(d)
    return firsts

def eff_exit(ticker, entry_date, cad_set):
    """Effective exit date: nominal = entry bar + HOLD_BARS bars of
    the name; deferred to first cadence date >= nominal on which the
    name has a bar. None = held to window end."""
    bl = PB.bars[ticker]
    ei = PB.idx[ticker][entry_date]
    if ei + M.HOLD_BARS >= len(bl):
        return None
    nominal = bl[ei + M.HOLD_BARS]["d"]
    for b in bl[ei + M.HOLD_BARS:]:
        if b["d"] >= nominal and b["d"] in cad_set:
            return b["d"]
    return None

def run_pot_cad(start, end, entry_plan, cad_set, label="",
                start_cash=None, floor=None):
    """Engine run_pot copied from integrity/novel-pv2-last-seller.py
    with ONE change: exit_date computed via eff_exit (cadence-
    deferred). Halt, costs, entries, end-liquidation identical."""
    days = [d for d in PB.dates if start <= d <= end]
    cash = M.START_CASH if start_cash is None else start_cash
    if floor is None:
        floor = M.FLOOR0
    positions = {}; trades = []; total_costs = 0.0; curve = []
    equity_by_date = {}; halted = None; halt_info = None
    pending_halt = False; slot_seq = [0]; taken = []; skipped_cash = 0

    def pot_close(d):
        v = cash
        for p in positions.values():
            c = PB.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for di, d in enumerate(days):
        if pending_halt:
            sig = halt_info["signal_date"]
            for sid in list(positions):
                p = positions[sid]
                nb = next((b for b in PB.bars[p["ticker"]]
                           if b["d"] > sig), None)
                if nb is None:
                    continue
                val = p["shares"] * nb["o"]
                c = val * 0.001 + 0.01
                cash += val - c; total_costs += c
                trades.append((nb["d"], p["ticker"], "SELL-HALT",
                               p["shares"], nb["o"], val, c))
                del positions[sid]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": sig,
                    "halt_info": halt_info, "curve": curve,
                    "taken": taken, "skipped_cash": skipped_cash}
        for sid in list(positions):
            p = positions[sid]
            if p["exit_date"] is not None and p["exit_date"] == d:
                b = PB.bar_on(p["ticker"], d)
                val = p["shares"] * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c; total_costs += c
                trades.append((d, p["ticker"], "SELL-EXIT", p["shares"],
                               b["o"], val, c))
                del positions[sid]
        for slot in entry_plan.get(d, []):
            t = slot["ticker"]; sig = slot["signal_date"]
            marked = equity_by_date.get(sig)
            if marked is None:
                marked = pot_close(sig)
            slice_val = marked / 5.0
            b = PB.bar_on(t, d)
            if b is None:
                cand = [x for x in PB.bars[t] if x["d"] >= d]
                if not cand or cand[0]["d"] > end:
                    continue
                b = cand[0]
            buy_val = min(slice_val, cash / 1.001)
            if buy_val <= 0.005:
                skipped_cash += 1; continue
            sh = buy_val / b["o"]; c = buy_val * 0.001
            cash -= buy_val + c; total_costs += c
            slot_seq[0] += 1
            positions[slot_seq[0]] = {
                "ticker": t, "shares": sh, "entry_date": b["d"],
                "exit_date": eff_exit(t, b["d"], cad_set),
                "signal_date": sig}
            trades.append((b["d"], t, "BUY", sh, b["o"], buy_val, c))
            taken.append({"signal_date": sig, "entry_date": b["d"],
                          "ticker": t})
        v = pot_close(d)
        curve.append((d, v)); equity_by_date[d] = v
        if v <= floor and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            pending_halt = True
    last = days[-1]
    for sid in list(positions):
        p = positions[sid]
        px = PB.close_on_or_before(p["ticker"], last)
        if px:
            val = p["shares"] * px
            c = val * 0.001 + 0.01
            cash += val - c; total_costs += c
            trades.append((last, p["ticker"], "SELL-END", p["shares"],
                           px, val, c))
        del positions[sid]
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": halted, "halt_info": halt_info,
            "curve": curve, "taken": taken,
            "skipped_cash": skipped_cash}

def build_ranked_plan_cad(start, end, cad_set):
    """Engine build_ranked_plan with held_until on effective
    (cadence-deferred) exit dates."""
    in_window = [e for e in EVENTS if start <= e["signal_date"] <= end]
    by_entry = {}
    for e in in_window:
        if e["entry_date"] is None or e["entry_date"] > end:
            continue
        by_entry.setdefault(e["entry_date"], []).append(e)
    plan = {}; held_until = {}
    for d in sorted(by_entry):
        held_now = {t for t, xd in held_until.items()
                    if xd is None or xd > d}
        fresh = [e for e in by_entry[d] if e["ticker"] not in held_now]
        slots = M.MAX_POS - len(held_now)
        fresh.sort(key=lambda e: (-(e["vol_ratio"] or 0), e["ticker"]))
        for e in fresh[:max(slots, 0)]:
            held_until[e["ticker"]] = eff_exit(e["ticker"],
                                               e["entry_date"], cad_set)
            plan.setdefault(d, []).append(
                {"ticker": e["ticker"], "signal_date": e["signal_date"],
                 "event": e})
    return plan

def run_v9_cad(plan_fn, cad_set):
    plan = plan_fn(START, END)
    r1 = run_pot_cad(START, END, plan, cad_set, label="ep1")
    eps = [r1]; restart = None
    if r1["halted"]:
        elig = (date.fromisoformat(r1["halted"])
                + timedelta(days=90)).isoformat()
        if elig <= END:
            plan2 = plan_fn(elig, END)
            r2 = run_pot_cad(elig, END, plan2, cad_set, label="ep2",
                             start_cash=r1["final"],
                             floor=0.85 * r1["final"])
            eps.append(r2)
            restart = {"halt_date": r1["halted"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig,
                       "episode2_floor": round(0.85 * r1["final"], 2),
                       "second_halt": r2["halted"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]:
            curve[d] = v
    if len(eps) > 1:
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(len(e["trades"]) for e in eps),
            "halts": [e["halted"] for e in eps if e["halted"]],
            "restart": restart is not None, "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "curve": sorted(curve.items()),
            "taken": [e["taken"] for e in eps]}

def diag(curve):
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return round(maxdd * 100, 2)

YEARS = (date.fromisoformat(END) - date.fromisoformat(START)).days / 365.25
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
cells = {}
for name in CADENCES:
    cad = cadence_dates(name); cad_set = set(cad)
    def ranked_plan(s, e, cad_set=cad_set):
        return build_ranked_plan_cad(s, e, cad_set)
    r = run_v9_cad(ranked_plan, cad_set)
    taken = r.pop("taken"); curve = r.pop("curve")
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        ep_taken = [list(t) for t in taken]
        def placebo_plan(s2, e2, rng=rng, ep_taken=ep_taken):
            slots = ep_taken.pop(0) if ep_taken else []
            pplan = {}
            for slot in slots:
                pplan.setdefault(slot["entry_date"], []).append(
                    {"ticker": rng.choice(M.POND),
                     "signal_date": slot["signal_date"]})
            return pplan
        pr = run_v9_cad(placebo_plan, cad_set)
        finals.append(pr["final"])
    beaten = sum(1 for f in finals if f < r["final"])
    sf = sorted(finals)
    cell = {"cadence": name, "final": r["final"],
            "cagr_pct": round(((r["final"] / 100.0) ** (1 / YEARS) - 1) * 100, 2),
            "max_dd_pct": diag(curve), "costs": r["costs"],
            "orders": r["orders"], "halts": r["halts"],
            "restart": r["restart_info"], "second_halt": r["second_halt"],
            "entries": sum(len(t) for t in taken),
            "placebo_beaten": beaten,
            "placebo_median": round((sf[9] + sf[10]) / 2, 2),
            "placebo_finals": finals,
            "equity_curve": [[d, round(v, 4)] for d, v in curve]}
    cells[name] = cell
    json.dump(cell, open(os.path.join(HERE, "cells", f"{name}.json"), "w"),
              indent=1)
    print(name, r["final"], "halts", r["halts"], "orders", r["orders"],
          "costs", r["costs"], "placebo", beaten, "/20 med",
          cell["placebo_median"], flush=True)
json.dump(cells, open(os.path.join(HERE, "sweep_cells.json"), "w"), indent=1)
print("DONE")
