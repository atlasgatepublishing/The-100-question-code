#!/usr/bin/env python3
"""
Per-engine v9 runners for the long run, normalized to one result shape.

Each helper runs ONE engine (original module, verbatim) under the
adopted v9 protection spec on supplied data and returns a dict:
  {engine, start, end, final, cagr_pct, years, costs, orders,
   halts, restart, episodes[], diag{worst_close, worst_close_date,
   max_drawdown_pct, max_drawdown_date, year_end_closes},
   spy_final, curve}
Episodes carry their own diagnostics (worst close vs that episode's
floor). The basket's v9 protection lives inside its simulate(); the
quarterly engines get it from lr_common.run_v9 (the long-hold-v9
episode pattern).
"""
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_basket as B  # noqa: E402

END = C.END
_POOL = {}


def pool_data():
    if not _POOL:
        facts_by, payload_by, failures = C.load_pool()
        chains_by = {t: (C.equity_chain(f), C.shares_chain(f))
                     for t, f in facts_by.items()}
        spy_bars = C.bars_adj(payload_by["SPY"])
        _POOL.update(facts_by=facts_by, payload_by=payload_by,
                     failures=failures, chains_by=chains_by,
                     spy_bars=spy_bars,
                     spy_dates=[b["d"] for b in spy_bars])
    return _POOL


def pond_at(start):
    P = pool_data()
    rows, top30, unrankable, price_date = C.build_pond(
        P["chains_by"], P["payload_by"], P["spy_dates"], start)
    return {"start": start, "price_date": price_date, "ranking": rows,
            "pond": top30, "unrankable": unrankable}


def _book(pond):
    P = pool_data()
    bars = {t: C.bars_adj(P["payload_by"][t]) for t in pond}
    bars["SPY"] = P["spy_bars"]
    return C.FastPriceBook(bars)


def _episode_diags(v9, start_cash):
    eps = []
    cash = start_cash
    for ep in v9["episodes"]:
        floor = 0.85 * cash
        d = C.curve_diagnostics(ep["curve"], cash)
        eps.append({"start_cash": round(cash, 2), "floor": round(floor, 2),
                    "final": round(ep["final"], 2),
                    "halted": ep["halted"],
                    "halt_info": ep.get("halt_info"),
                    "end": ep["end"], "costs": round(ep["costs"], 2),
                    "orders": len(ep["trades"]),
                    "worst_close": d["worst_close"],
                    "worst_close_date": d["worst_close_date"],
                    "worst_close_above_floor":
                        round(d["worst_close"] - floor, 2),
                    "max_drawdown_pct": d["max_drawdown_pct"],
                    "pools": ep.get("pools")})
        cash = ep["final"]
    return eps


def _normalize(engine, start, end, v9, spy_final, extra=None):
    cg, yrs = C.cagr(v9["final"], C.START_CASH, start, end)
    diag = C.curve_diagnostics(v9["curve"])
    out = {"engine": engine, "start": start, "end": end,
           "final": round(v9["final"], 2), "cagr_pct": cg, "years": yrs,
           "costs": round(v9["costs"], 2), "orders": v9["orders"],
           "halts": v9["halts"], "restart": v9["restart"],
           "episodes": _episode_diags(v9, C.START_CASH),
           "diag": diag, "spy_final": round(spy_final, 2),
           "spy_cagr_pct": C.cagr(spy_final, C.START_CASH, start, end)[0],
           "curve": v9["curve"]}
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------------- champion
def champion_v9(pond, start, end):
    P = pool_data()
    eq = {t: P["chains_by"][t][0] for t in pond}
    so = {t: P["chains_by"][t][1] for t in pond}
    pb = _book(pond)
    champ = C.champ
    saved = champ.UNIVERSE
    champ.UNIVERSE = pond
    try:
        def run_one(s, e, cash, floor):
            return champ.run_pot(pb, eq, so, s, e, cash, floor, [],
                                 label="LR VM", quiet=True,
                                 record_pools=True)
        v9 = C.run_v9(run_one, pb.dates, start, end)
        spy, _ = champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        champ.UNIVERSE = saved
    return _normalize("value+momentum", start, end, v9, spy)


def champion_terry(pond, start, end):
    """The published his-rules form (single plain-floor run, halt ends
    the run) — used to verify the published 2010 long-hold inside this
    test's plumbing."""
    P = pool_data()
    eq = {t: P["chains_by"][t][0] for t in pond}
    so = {t: P["chains_by"][t][1] for t in pond}
    pb = _book(pond)
    champ = C.champ
    saved = champ.UNIVERSE
    champ.UNIVERSE = pond
    try:
        r = champ.run_pot(pb, eq, so, start, end, C.START_CASH, 85.0, [],
                          label="LR VM TERRY", quiet=True)
        spy, _ = champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        champ.UNIVERSE = saved
    return r, spy


# ------------------------------------------------------------- basket
def basket_v9(pond, start, end):
    P = pool_data()
    raw = {t: C.bars_raw(P["payload_by"][t]) for t in pond}
    raw["SPY"] = C.bars_raw(P["payload_by"]["SPY"])
    mkt = B.Market(raw)
    saved = B.UNIVERSE
    B.UNIVERSE = pond
    try:
        res = B.simulate(mkt, start, end, 100, "ranked")
        spy = B.spy_net(mkt, start, end, 100)
    finally:
        B.UNIVERSE = saved
    curve = list(res.equity_curve)
    # halts: the basket records LIQUIDATION dates; the signal close is
    # the prior trading day. Floors: episode 1 = $85; episode 2 from
    # the restart record.
    cal = mkt.cal
    halts = []
    for i, hd in enumerate(res.halts):
        j = cal.index(hd)
        sig = cal[j - 1] if j > 0 else hd
        floor = 85.0 if i == 0 else res.restarts[0]["episode2_floor"]
        halts.append({"episode": i + 1, "signal_date": sig,
                      "signal_close": None,
                      "floor_in_effect": floor,
                      "liquidation_date": hd,
                      "proceeds": None})
    restart = None
    if res.restarts:
        r0 = res.restarts[0]
        restart = {"halt_date": r0["halt_date"],
                   "liquidation_proceeds": r0["restart_balance"],
                   "episode2_first_selection": r0["restart_date"],
                   "episode2_floor": r0["episode2_floor"],
                   "second_halt": res.halts[1] if len(res.halts) > 1
                   else None,
                   "note": "basket convention (its v9 engine): the "
                           "90-day sit-out is counted from the "
                           "liquidation date and the restart executes "
                           "at the next monthly selection day"}
    # per-episode worst closes from the curve
    eps = []
    if res.halts:
        hd = res.halts[0]
        seg1 = [v for d, v in curve if d <= hd]
        eps.append({"episode": 1, "floor": 85.0,
                    "worst_close": round(min(seg1), 2),
                    "worst_close_above_floor": round(min(seg1) - 85.0, 2)})
        seg2 = [v for d, v in curve if d > hd]
        if seg2:
            f2 = res.restarts[0]["episode2_floor"] if res.restarts else None
            eps.append({"episode": 2, "floor": f2,
                        "worst_close": round(min(seg2), 2),
                        "worst_close_above_floor":
                            round(min(seg2) - f2, 2) if f2 else None})
    cg, yrs = C.cagr(res.final, 100.0, start, end)
    diag = C.curve_diagnostics(curve)
    return {"engine": "momentum basket", "start": start, "end": end,
            "final": round(res.final, 2), "cagr_pct": cg, "years": yrs,
            "costs": round(res.costs, 2), "orders": res.orders,
            "halts": halts, "restart": restart, "episodes": eps,
            "diag": diag, "spy_final": round(spy, 2),
            "spy_cagr_pct": C.cagr(spy, 100.0, start, end)[0],
            "max_dd_engine_pct": round(res.max_dd * 100, 2),
            "curve": curve}


# ------------------------------------------------------------- lazy prices
_lazy = None


def _lazy_mod():
    global _lazy
    if _lazy is None:
        _lazy = C.load_module("lazy_lr", os.path.join(
            C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
    return _lazy


def lazy_v9(pond, signals, start, end):
    lazy = _lazy_mod()
    pb = _book(pond)
    saved = lazy.UNIVERSE
    lazy.UNIVERSE = pond
    try:
        def run_one(s, e, cash, floor):
            return lazy.run_pot(pb, signals, s, e, cash, floor,
                                label="LR LAZY", record_pools=True)
        v9 = C.run_v9(run_one, pb.dates, start, end)
        spy, _ = C.champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        lazy.UNIVERSE = saved
    return _normalize("lazy prices", start, end, v9, spy)


# ------------------------------------------------------------- N-F3
_nf3 = None


def _nf3_mod():
    global _nf3
    if _nf3 is None:
        _nf3 = C.load_module("nf3_lr", os.path.join(
            C.V8, "novel-f3-paying-in-stock",
            "novel-f3-paying-in-stock.py"))
    return _nf3


def nf3_facts(pond):
    return {t: C.load_facts(C.cik_for(t)) for t in pond}


def nf3_v9(pond, start, end, facts=None):
    nf3 = _nf3_mod()
    facts = facts or nf3_facts(pond)
    pb = _book(pond)
    saved = nf3.UNIVERSE
    nf3.UNIVERSE = pond
    stats = {"direct": 0, "derived": 0}
    try:
        def run_one(s, e, cash, floor):
            return nf3.run_pot(pb, facts, s, e, cash, floor,
                               label="LR NF3", stats=stats)
        v9 = C.run_v9(run_one, pb.dates, start, end)
        spy, _ = C.champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        nf3.UNIVERSE = saved
    return _normalize("nf3 paying in stock", start, end, v9, spy,
                      extra={"quarter_values": stats})


# ------------------------------------------------------------- switch B
_switch = None


def _switch_mod():
    global _switch
    if _switch is None:
        _switch = C.load_module("switch_lr", os.path.join(
            C.V8, "switch-champion-to-blend",
            "switch-champion-to-blend.py"))
    return _switch


def switch_v9(pond, start, end, switch_on_or_after, facts=None):
    sw = _switch_mod()
    P = pool_data()
    facts = facts or nf3_facts(pond)
    eq = {t: P["chains_by"][t][0] for t in pond}
    so = {t: P["chains_by"][t][1] for t in pond}
    pb = _book(pond)
    saved = sw.UNIVERSE
    sw.UNIVERSE = pond
    try:
        scorer = sw.Scorer(pb, eq, so, facts)

        def run_one(s, e, cash, floor):
            return sw.run_switch(pb, scorer, s, e, switch_on_or_after,
                                 cash, floor, label="LR SWITCH")
        v9 = C.run_v9(run_one, pb.dates, start, end)
        spy, _ = C.champ.spy_net(pb, start, end, C.START_CASH)
    finally:
        sw.UNIVERSE = saved
    sw_info = {}
    for ep in v9["episodes"]:
        if ep.get("switch_date"):
            sw_info = {"switch_date": ep["switch_date"],
                       "switch_close": ep.get("switch_close"),
                       "switch_exec_date": ep.get("switch_exec_date")}
    return _normalize("midpoint switch B", start, end, v9, spy,
                      extra={"switch": sw_info,
                             "switch_on_or_after": switch_on_or_after})


def halfway_on_or_after(start, end):
    """The frozen switch rule's trigger for a window: the calendar
    halfway date of [start, end]; the switch executes at the first
    quarterly selection date on/after it (inside run_switch)."""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    mid = d0 + timedelta(days=(d1 - d0).days // 2)
    return mid.isoformat()
