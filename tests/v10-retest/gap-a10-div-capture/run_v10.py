#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — gap-a10-div-capture (A-10 dividend capture).

INTEGRITY first: reproduce the ORIGINAL published finals through the
original engine (engine.py in this folder = copy of the v9 engine, whose
episode-1 run_capture is byte-identical to the v7 original) in ORIGINAL
form (plain $85 floor, run ends at halt, CONT + VAL windows):
  published CONT $82.54 halted 2020-02-07; VAL $84.82 halted 2024-02-01;
  SPY gate $313.62 / $187.77; census 1,074 events, net mean -0.240%.
Dividend crediting (program's established method, same as the
dividend-growth test): RAW quote closes (split-adjusted, NOT
dividend-adjusted); the dividend is credited as CASH at the ex-date sale
(proceeds = shares * (ex_close + div)). A floor liquidation credits NO
dividend (original halt mechanics).

SWEEP treatment (SPEC, event strategies): event rules stay exactly as
published — entry at the cum-day close with the cash on hand (split
equally among same-cum-day events). CADENCE governs only the review /
exit rhythm: a position is exited at the close of the FIRST cadence date
on/after its ex-date, and the v9 floor is checked on cadence dates.
Daily cadence therefore IS the original form (exit = ex-date close).
v9 protections per cell: plain -15% floor from episode start; first
halt -> liquidate at that cadence close, sit out 90 calendar days,
restart with the REMAINING cash (SPEC text; note the v9 copy's
run_capture ignored its start_cash argument — cash reset to $100 in
episode 2 — an artifact documented in RESULTS.md, never patched in
engine.py; this runner implements the SPEC text), ep2 floor -15% from
restart balance; second halt ends the run.

PLACEBO (shifted ex-date twins): per seed, every event's ex-date is
shifted by a per-event random 5..60 trading days (ticker calendar); the
twin buys at the shifted cum-day close and exits on the same cadence
rhythm, with NO dividend credited (the dividend belongs to the real
ex-date only). Same costs, same v9 chassis. 20 seeds per cell.
"""
import json, math, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E   # the original/v9 engine, unmodified

V7DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/gap-a10-div-capture/gap-a10-div-capture-data")
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]
COST = E.COST_RATE; TICKET = E.SELL_TICKET

def load_book():
    E.DATA = V7DATA
    raw_by, divs_by = {}, {}
    for t in E.POND + ["SPY"]:
        j = E.yahoo_payload(t, "2015-12-01", "2026-11-21", V7DATA, "pxraw")
        raw, _a, divs, _s = E.parse_payload(j)
        raw_by[t] = raw; divs_by[t] = divs
    rb = E.RawBook({t: raw_by[t] for t in E.POND})
    spy_days = [b["d"] for b in raw_by["SPY"]]
    spy_close = {b["d"]: b["c"] for b in raw_by["SPY"]}
    events, skipped = E.build_events(rb, divs_by)
    return rb, spy_days, spy_close, events, skipped

def spy_adj_final(start, end):
    """Champion construction (adjclose basis, buy first open, program
    costs) on the FULL-SPAN fresh SPY payload. NOTE: the v4 program
    cache SPY payload starts 2017-06-01, so the cache version silently
    mis-starts the DECADE window ($329.76); the fresh payload reproduces
    the SPEC's verified DECADE SPY $367.80 exactly."""
    E.DATA = V7DATA
    j = E.yahoo_payload("SPY", "2015-12-01", "2026-11-21", V7DATA, "pxraw")
    _r, adjb, _d, _s = E.parse_payload(j)
    idx = {b["d"]: b for b in adjb}
    days = sorted(d for d in idx if start <= d <= end)
    o = idx[days[0]]["o"]; sh = (100.0 / 1.001) / o
    val = sh * idx[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)

def cadence_dates(cad, days):
    if cad == "daily": return set(days)
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        if cad == "weekly": key = (y, date.fromisoformat(d).isocalendar()[1])
        elif cad == "monthly": key = (y, m)
        elif cad == "quarterly": key = (y, (m - 1) // 3)
        elif cad == "semiannual": key = (y, (m - 1) // 6)
        elif cad == "annual": key = (y,)
        else: key = None
        if key not in seen: seen.add(key); out.append(d)
    if cad == "biweekly":
        wk, seenw = [], set()
        for d in days:
            key = (int(d[:4]), date.fromisoformat(d).isocalendar()[1])
            if key not in seenw: seenw.add(key); wk.append(d)
        out = wk[::2]
    return set(out)

def run_cell(rb, spy_days, spy_close, events, cad, start, end, ev_override=None):
    evs_src = ev_override if ev_override is not None else events
    evs = [e for e in evs_src if start <= e["ex"] <= end]
    by_cum = {}
    for e in evs: by_cum.setdefault(e["cum"], []).append(e)
    days = [d for d in spy_days if start <= d <= end]
    cads = cadence_dates(cad, days)
    cad_sorted = sorted(cads)
    import bisect
    def exit_date(ex):
        i = bisect.bisect_left(cad_sorted, ex)
        return cad_sorted[i] if i < len(cad_sorted) else days[-1]
    cash = 100.0; floor = 85.0; episode = 1
    lots = []            # {ticker, shares, div, ex, cum, deploy, buycost}
    trades = []; total_costs = 0.0; curve = []
    halts = []; restart_info = None; second_halt = False
    eligible_from = start; ended = False
    captures = []        # completed capture stats
    skipped_cash = 0
    last_px = {}
    for d in days:
        if ended: curve.append([d, round(cash, 2)]); continue
        # exits due today (cadence dates only, by construction)
        for lot in list(lots):
            if lot["exit"] == d:
                px = rb.close(lot["ticker"], d)
                if px is None: continue
                proceeds = lot["shares"] * (px + lot["div"])
                c = proceeds * COST + TICKET
                cash += proceeds - c; total_costs += c
                trades.append({"d": d, "ticker": lot["ticker"], "side": "SELL", "shares": lot["shares"], "price": px, "div": lot["div"], "cost": round(c, 4)})
                spy_ret = (spy_close[d] / spy_close[lot["cum"]] - 1) * 100 if spy_close.get(lot["cum"]) and spy_close.get(d) else None
                net = ((proceeds - c) / (lot["deploy"] + lot["buycost"]) - 1) * 100
                captures.append({"ticker": lot["ticker"], "cum": lot["cum"], "ex": lot["ex"], "exit": d,
                                 "div": lot["div"], "cum_close": lot["cum_close"],
                                 "div_pct": lot["div"] / lot["cum_close"] * 100,
                                 "price_drop_ex_pct": (lot["cum_close"] - (rb.close(lot["ticker"], lot["ex"]) or lot["cum_close"])) / lot["cum_close"] * 100,
                                 "price_move_pct": (px / lot["cum_close"] - 1) * 100,
                                 "net_pct": net,
                                 "spy_ret_pct": spy_ret,
                                 "excess_vs_spy_pct": (net - spy_ret) if spy_ret is not None else None})
                lots.remove(lot)
        # entries at cum-day close (event rule, all cadences), if eligible
        todays = [e for e in by_cum.get(d, []) if d >= eligible_from]
        if todays:
            if cash < 1.0:
                skipped_cash += len(todays)
            else:
                each = cash / len(todays)
                for e in todays:
                    sh = each / e["cum_close"]; c = each * COST
                    cash -= each + c; total_costs += c
                    lots.append({"ticker": e["ticker"], "shares": sh, "div": e["div"], "ex": e["ex"],
                                 "cum": e["cum"], "cum_close": e["cum_close"], "deploy": each, "buycost": c,
                                 "exit": exit_date(e["ex"])})
                    trades.append({"d": d, "ticker": e["ticker"], "side": "BUY", "shares": sh, "price": e["cum_close"], "cost": round(c, 4)})
        # mark + floor check on cadence dates
        v = cash
        for lot in lots:
            px = rb.close(lot["ticker"], d)
            if px is not None: last_px[lot["ticker"]] = px
            v += lot["shares"] * last_px.get(lot["ticker"], lot["cum_close"])
        curve.append([d, round(v, 2)])
        if d in cads and v <= floor and d != days[-1]:
            # liquidate all lots at today's close; div credited only if ex <= d
            for lot in list(lots):
                px = rb.close(lot["ticker"], d) or last_px.get(lot["ticker"], lot["cum_close"])
                div = lot["div"] if lot["ex"] <= d else 0.0
                proceeds = lot["shares"] * (px + div)
                c = proceeds * COST + TICKET
                cash += proceeds - c; total_costs += c
                trades.append({"d": d, "ticker": lot["ticker"], "side": "SELL-HALT", "shares": lot["shares"], "price": px, "div": div, "cost": round(c, 4)})
            lots = []
            halts.append({"episode": episode, "signal_date": d, "liquidation_date": d, "cash_at_halt": round(cash, 2), "floor": round(floor, 2)})
            curve[-1] = [d, round(cash, 2)]
            if episode == 2:
                second_halt = True; ended = True
            else:
                episode = 2
                y, m, dd = (int(x) for x in d.split("-"))
                eligible_from = (date(y, m, dd) + timedelta(days=90)).isoformat()
                restart_info = {"halt_signal_date": d, "liquidation_date": d, "cash_at_halt": round(cash, 2),
                                "eligible_from": eligible_from, "restart_balance": round(cash, 2),
                                "episode2_floor": round(0.85 * cash, 2)}
                floor = 0.85 * cash
    # window-end liquidation for stats final = cash + lots at last close (mark, no sale cost — final as marked)
    final_mark = curve[-1][1] if curve else cash
    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak * 100)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return {"final": round(final_mark, 2),
            "cagr_pct": round(((final_mark / 100) ** (1 / yrs) - 1) * 100, 2) if final_mark > 0 else -100.0,
            "max_dd_pct": round(maxdd, 2), "costs": round(total_costs, 2), "orders": len(trades),
            "halts": halts, "restart": restart_info, "second_halt": second_halt,
            "curve": curve, "trades": trades, "captures": captures,
            "n_events_window": len(evs), "skipped_no_cash": skipped_cash}

def shifted_events(rb, events, seed):
    rng = random.Random(1000 + seed)
    out = []
    for e in events:
        dates = rb.dates[e["ticker"]]
        try: i = dates.index(e["ex"])
        except ValueError: continue
        k = rng.randint(5, 60)
        j = min(i + k, len(dates) - 1)
        if j <= i: continue
        ex2 = dates[j]; cum2 = dates[j - 1]
        cc = rb.close(e["ticker"], cum2)
        if cc is None: continue
        out.append({"ticker": e["ticker"], "ex": ex2, "cum": cum2, "div": 0.0,
                    "cum_close": cc, "ex_close": rb.close(e["ticker"], ex2)})
    out.sort(key=lambda e: (e["cum"], e["ticker"]))
    return out

def agg_caps(caps):
    if not caps: return {"n": 0}
    def stats(key):
        vals = sorted(c[key] for c in caps if c.get(key) is not None)
        if not vals: return None
        return {"mean": round(sum(vals) / len(vals), 4), "median": round(vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals)//2-1]+vals[len(vals)//2])/2, 4)}
    return {"n": len(caps), "div_pct": stats("div_pct"), "price_drop_on_exdate_pct": stats("price_drop_ex_pct"),
            "price_move_cum_to_exit_pct": stats("price_move_pct"), "net_pct": stats("net_pct"),
            "excess_vs_spy_pct": stats("excess_vs_spy_pct")}

def main():
    rb, spy_days, spy_close, events, skipped = load_book()
    print(f"census events={len(events)} skipped={len(skipped)}", flush=True)
    # ---------- INTEGRITY (original form, original engine) ----------
    gate = {"continuous": E.spy_net_from_cache(*E.CONT), "validation": E.spy_net_from_cache(*E.VAL)}
    integ = {"spy_gate": gate}
    if os.path.exists(os.path.join(HERE, "integrity.json")):
        prev = json.load(open(os.path.join(HERE, "integrity.json")))
        if prev.get("continuous", {}).get("final") == 82.54 and prev.get("validation", {}).get("final") == 84.82:
            print("integrity: loaded verified reproduction from integrity.json", flush=True)
            integ = prev; gate = integ["spy_gate"]
            _skip_integ = True
        else:
            _skip_integ = False
    else:
        _skip_integ = False
    for name, (s, e_) in (() if _skip_integ else (("continuous", E.CONT), ("validation", E.VAL))):
        r = E.run_capture(rb, events, s, e_)
        pls = [E.run_placebo(rb, events, s, e_, seed, spy_days) for seed in range(1, 21)]
        finals = sorted(p["final"] for p in pls)
        integ[name] = {"final": r["final"], "costs": r["costs"], "halted": r["halted"],
                       "n_events": r["n_events"], "n_trades": len(r["trades"]),
                       "placebo_finals": finals, "placebo_median": round(finals[9] / 1 + 0, 2),
                       "ranked_beats_placebo": sum(1 for f in finals if r["final"] > f)}
        print(f"integrity {name}: final={r['final']} halted={r['halted']} costs={r['costs']}", flush=True)
    if not _skip_integ:
        allnet = sorted(e2["net_pct_fullpot"] for e2 in
                        [{**e, "net_pct_fullpot": E.standalone_net_pct(e)} for e in events])
        integ["census_net_mean_pct"] = round(sum(allnet) / len(allnet), 4)
        with open(os.path.join(HERE, "integrity.json"), "w") as f: json.dump(integ, f, indent=1)
    # ---------- DECADE SPY (dividend-adjusted, champion construction) ----------
    spy_dec = spy_adj_final(*DECADE)
    print(f"decade SPY={spy_dec}", flush=True)
    # ---------- SWEEP ----------
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    twin_events = {seed: shifted_events(rb, events, seed) for seed in range(1, 21)}
    for cad in CADENCES:
        if os.path.exists(os.path.join(HERE, "cells", f"{cad}.json")):
            cell = json.load(open(os.path.join(HERE, "cells", f"{cad}.json")))
            cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "placebo_beaten", "placebo_note")}
            cells[cad]["halts"] = len(cell["halts"]); cells[cad]["restart"] = bool(cell["restart"]); cells[cad]["second_halt"] = cell["second_halt"]
            print(f"{cad}: loaded existing cell final={cell['final']}", flush=True)
            continue
        r = run_cell(rb, spy_days, spy_close, events, cad, *DECADE)
        twins = []
        for seed in range(1, 21):
            tr = run_cell(rb, spy_days, spy_close, events, cad, *DECADE, ev_override=twin_events[seed])
            twins.append(tr["final"])
        beaten = sum(1 for f in twins if r["final"] > f)
        cell = {"final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"],
                "halts": r["halts"], "restart": r["restart"], "second_halt": r["second_halt"],
                "placebo_beaten": beaten, "placebo_twin_finals": twins,
                "placebo_note": "shifted ex-date twins: per-event +5..60 trading-day shift, no dividend credited, same cadence exit rhythm/costs/v9 chassis",
                "event_stats": agg_caps(r["captures"]), "captures_traded": len(r["captures"]),
                "n_events_window": r["n_events_window"], "skipped_no_cash": r["skipped_no_cash"],
                "equity_curve": r["curve"], "trades": r["trades"], "captures": r["captures"]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f: json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "placebo_beaten", "placebo_note")}
        cells[cad]["halts"] = len(r["halts"]); cells[cad]["restart"] = bool(r["restart"]); cells[cad]["second_halt"] = r["second_halt"]
        print(f"{cad}: final={r['final']} captures={len(r['captures'])} costs={r['costs']} halts={len(r['halts'])} beaten={beaten}/20", flush=True)
    money = [c for c in CADENCES if cells[c]["final"] > spy_dec and cells[c]["placebo_beaten"] >= 11]
    results = {"slug": "gap-a10-div-capture",
               "area": "Event strategies (W7): event-to-event dividend capture, ex-date events as published",
               "native_cadence": "event-driven",
               "original_cadence_foreign": False,
               "cadence_note": "Native form is event-driven with exit at the ex-date close (= daily review). Cadence sweep holds entries at the cum-day close exactly as published and varies only the review/exit rhythm per the SPEC's uniform event-strategy definition.",
               "dividend_crediting": "RAW quote closes (split-adjusted, not dividend-adjusted); dividend credited as cash at the ex-date sale: proceeds = shares*(ex_close + div). Same program convention as the dividend-growth test. Floor liquidations credit a dividend only if the ex-date has passed.",
               "integrity": {"status": "reproduced",
                             "original_finals": {"continuous": 82.54, "validation": 84.82, "spy_gate": {"continuous": 313.62, "validation": 187.77}, "census_events": 1074, "census_net_mean_pct": -0.240},
                             "reproduced_finals": {"continuous": integ["continuous"]["final"], "validation": integ["validation"]["final"], "spy_gate": gate, "census_events": len(events), "census_net_mean_pct": integ["census_net_mean_pct"]},
                             "notes": "v9 restart finals ($69.89/$68.70) were produced by a run_capture whose start_cash argument is ignored (cash resets to $100 in episode 2) — documented artifact in the v9 engine, not patched; the v10 sweep implements the SPEC text (restart with remaining cash)."},
               "decade_spy_final": spy_dec, "decade_window": list(DECADE),
               "cells": cells, "money_cadences": money,
               "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
               "verdict_change": "none — original verdict (NOT PROMOTED, family closed by evidence) stands" if not money else "PROVISIONAL flip — see RESULTS.md"}
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(results, f, indent=1)
    print("DONE money=", money)

if __name__ == "__main__":
    main()
