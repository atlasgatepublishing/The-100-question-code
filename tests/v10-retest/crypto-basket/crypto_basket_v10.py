#!/usr/bin/env python3
"""
CRYPTO-BASKET — v10 GREAT RETEST (cadence sweep). Simulation only.

Original strategy (v4 crypto-basket.py, unchanged architecture):
  Survivor 20-coin universe (BTC ETH XRP BNB ADA DOGE LTC BCH LINK XLM
  TRX ETC XMR EOS DASH ZEC NEO XTZ VET ATOM) — built in 2026 from coins
  that survived 2020->2026. NOT point-in-time. SURVIVORSHIP-FLATTERED
  BY CONSTRUCTION (see RESULTS.md; the pit sibling row is the PIT form).
  Eligible: close above own 200-day SMA. Rank by 12-1 momentum
  (close[t-30]/close[t-365]-1, calendar days). Top 5 at 20% each,
  fewer eligible -> rest cash. Rebalance at decision day's OPEN,
  signals from prior day's close. Costs 0.25%/side, no per-order fee.
  Pot $100.

Integrity: original form = monthly decisions, plain floor (FULL) and
plain floor episode-1 + v9 restart (VALIDATION). Reproduced through
this plumbing (precomputed SMA/momentum arrays, same arithmetic).

Sweep: DECADE road. The basket's data cannot honestly cover
2016-11-21: the cache starts 2018-01-01 (ATOM 2019-03-14, VET
2018-08-03) and the rule needs 365+200 days of lookback; the original
FULL window starts 2020-06-01 for exactly that reason. Every sweep
cell therefore runs the longest honest sub-window of the decade,
2020-06-01 -> 2026-11-20 (the original FULL window), documented in
every cell. Cadence governs re-rank/rebalance dates ONLY (SPEC uniform
definition): daily=every calendar day (crypto trades daily);
weekly=Mondays; biweekly=every second Monday (anchored 1970-01-05);
monthly=1st of month (NATIVE); quarterly=1st of Jan/Apr/Jul/Oct;
semiannual=1st of Jan/Jul; annual=1st of Jan. Floor monitoring stays
daily (protection is not a trading cadence). v9 protections per cell:
plain -15% floor from episode start; first halt -> liquidate at next
open (engine's own rule), cash 90 calendar days, restart at the next
cadence date on/after day 90 with episode-2 floor -15% from restart
balance; second halt ends the run.
Placebos: random 5 eligible coins at each decision, 20 seeds, same
v9 machinery (fresh RNG per episode, same seed).
Benchmarks on the same road: BTC buy-and-hold net of 0.25%/side
(original engine's convention); SPY decade $367.80 is the SPEC
reference figure for the full 2016-11-21 decade (different road —
printed for the scoreboard, flagged as such).
Data: read-only shared cache ../../v4/crypto-basket-data/ (Yahoo daily
bars 2018-01-01 -> 2026-11-21). No downloads, no writes outside here.
"""
import json, os, random
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "v4", "crypto-basket-data"))
UNIVERSE = ["BTC","ETH","XRP","BNB","ADA","DOGE","LTC","BCH","LINK","XLM",
            "TRX","ETC","XMR","EOS","DASH","ZEC","NEO","XTZ","VET","ATOM"]
COST = 0.0025; POT = 100.0; SMA_N = 200; MOM_FAR = 365; MOM_NEAR = 30
ROAD_START, ROAD_END = "2020-06-01", "2026-11-20"   # honest sub-window of DECADE
DECADE_START, DECADE_END = "2016-11-21", "2026-11-20"
SPY_DECADE = 367.80  # SPEC reference (full decade road, dividend-adjusted)

# ---------------- data / precompute ----------------
def load():
    raw = {}
    for t in UNIVERSE:
        raw[t] = json.load(open(os.path.join(CACHE, f"{t}.json")))
    cal = [r["d"] for r in raw["BTC"]]
    ci = {d: i for i, d in enumerate(cal)}
    opens, closes = {}, {}
    for t in UNIVERSE:
        bars = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
        op = [None]*len(cal); cl = [None]*len(cal); last = None
        for i, d in enumerate(cal):
            if d in bars:
                op[i] = bars[d][0]; last = bars[d][1]
            cl[i] = last
        opens[t], closes[t] = op, cl
    sma, mom = {}, {}
    for t in UNIVERSE:
        cl = closes[t]; n = len(cl)
        pref = [0.0]*(n+1); cnt = [0]*(n+1)
        for i, v in enumerate(cl):
            pref[i+1] = pref[i] + (v or 0.0); cnt[i+1] = cnt[i] + (1 if v is not None else 0)
        s = [None]*n
        for i in range(n):
            if i+1 >= SMA_N and cnt[i+1]-cnt[i+1-SMA_N] == SMA_N:
                s[i] = (pref[i+1]-pref[i+1-SMA_N])/SMA_N
        m = [None]*n
        for i in range(n):
            if i-MOM_FAR >= 0:
                a, b = cl[i-MOM_FAR], cl[i-MOM_NEAR]
                if a and b and a > 0: m[i] = b/a - 1.0
        sma[t], mom[t] = s, m
    return cal, ci, opens, closes, sma, mom

CAL, CI, OPENS, CLOSES, SMA, MOM = load()

def elig_at(j):
    """Eligible (coin, momentum) at signal index j, ranked desc."""
    out = []
    for t in UNIVERSE:
        c = CLOSES[t][j]
        if c is None or SMA[t][j] is None or c <= SMA[t][j]: continue
        if MOM[t][j] is None: continue
        out.append((t, MOM[t][j]))
    out.sort(key=lambda x: -x[1])
    return out

def cadence_dates(cad, start, end):
    out = set()
    d = date.fromisoformat(start); e = date.fromisoformat(end)
    anchor = date(1970, 1, 5)  # a Monday
    while d <= e:
        s = d.isoformat(); add = False
        if cad == "daily": add = True
        elif cad == "weekly": add = d.weekday() == 0
        elif cad == "biweekly": add = d.weekday() == 0 and ((d-anchor).days % 14 == 0)
        elif cad == "monthly": add = d.day == 1
        elif cad == "quarterly": add = d.day == 1 and d.month in (1,4,7,10)
        elif cad == "semiannual": add = d.day == 1 and d.month in (1,7)
        elif cad == "annual": add = d.day == 1 and d.month == 1
        if add: out.add(s)
        d += timedelta(days=1)
    return out

def next_cadence_on_or_after(cad, dstr, end):
    ds = cadence_dates(cad, dstr, end)
    return min(ds) if ds else None

# ---------------- engine ----------------
class Res:
    def __init__(self):
        self.final=None; self.orders=0; self.costs=0.0; self.halt=None; self.curve=[]

def simulate(start, end, cad, mode="ranked", seed=42, start_cash=POT,
             floor_abs=None, ladder=None):
    """One episode. Decision dates = cadence dates in [start,end].
    Floor: plain 85 (or floor_abs) plus optional original ladder list."""
    dec = cadence_dates(cad, start, end)
    elig_cache = {}
    rng = random.Random(seed)
    i0 = next(i for i,d in enumerate(CAL) if d >= start)
    i1 = max(i for i,d in enumerate(CAL) if d <= end)
    floor = 85.0 if floor_abs is None else float(floor_abs)
    if floor_abs is not None: ladder = None
    cash = float(start_cash); pos = {}; res = Res(); pending = False
    def eq_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = OPENS[t][i] if use_open else CLOSES[t][i]
            if px is None: px = CLOSES[t][i]
            tot += sh*px
        return tot
    for i in range(i0, i1+1):
        d = CAL[i]
        if pending:
            for t in list(pos):
                px = OPENS[t][i] if OPENS[t][i] is not None else CLOSES[t][i]
                val = pos[t]*px; fee = val*COST
                cash += val-fee; res.costs += fee; res.orders += 1; del pos[t]
            res.halt = d; res.final = cash; res.curve.append((d, round(cash,4))); break
        if d in dec and i > 0:
            j = i-1
            if j not in elig_cache: elig_cache[j] = elig_at(j)
            elig = elig_cache[j]
            if mode == "ranked": picks = [t for t,_ in elig[:5]]
            else:
                names = sorted(t for t,_ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            eq_open = eq_at(i, True)
            target = {t: 0.20*eq_open for t in picks}
            for t in list(pos):
                px = OPENS[t][i]
                if px is None: continue
                cur = pos[t]*px; want = target.get(t, 0.0)
                if cur > want + 0.01:
                    sv = cur-want; fee = sv*COST
                    cash += sv-fee; res.costs += fee; res.orders += 1
                    pos[t] -= sv/px
                    if want <= 0.0 or pos[t]*px < 0.01: del pos[t]
            for t in picks:
                px = OPENS[t][i]
                if px is None: continue
                deficit = target[t] - pos.get(t,0.0)*px
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1.0+COST))
                if bv <= 0.01: continue
                fee = bv*COST; cash -= bv+fee; res.costs += fee; res.orders += 1
                pos[t] = pos.get(t,0.0) + bv/px
        eqc = eq_at(i, False); res.curve.append((d, round(eqc,4)))
        if ladder:
            for thresh, nf in ladder:
                if eqc >= thresh: floor = max(floor, nf)
        if eqc <= floor:
            pending = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh*CLOSES[t][i]; fee = val*COST
                    tot += val-fee; res.costs += fee; res.orders += 1
                res.final = tot; res.halt = d; pos.clear(); break
    if res.final is None: res.final = res.curve[-1][1]
    return res

def run_v9(start, end, cad, mode="ranked", seed=42):
    """Full v9 run: episode 1 + optional restart episode."""
    ep1 = simulate(start, end, cad, mode, seed)
    halts = []; restart = False; second_halt = False; rinfo = None
    final = ep1.final; costs = ep1.costs; orders = ep1.orders; curve = list(ep1.curve)
    if ep1.halt:
        halts.append(ep1.halt)
        earliest = (date.fromisoformat(ep1.halt) + timedelta(days=90)).isoformat()
        rdate = next_cadence_on_or_after(cad, earliest, end)
        if rdate is not None:
            restart = True
            ep2 = simulate(rdate, end, cad, mode, seed, start_cash=ep1.final,
                           floor_abs=0.85*ep1.final)
            rinfo = {"restart_date": rdate, "restart_cash": round(ep1.final,2),
                     "ep2_floor": round(0.85*ep1.final,2)}
            final = ep2.final; costs += ep2.costs; orders += ep2.orders
            curve += [(d,v) for d,v in ep2.curve]
            if ep2.halt: second_halt = True; halts.append(ep2.halt)
    peak = -1.0; dd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v/peak-1.0)
    yrs = (date.fromisoformat(end)-date.fromisoformat(start)).days/365.25
    return {"final": round(final,2),
            "cagr_pct": round(((final/POT)**(1/yrs)-1)*100,2) if final>0 else None,
            "max_dd_pct": round(dd*100,2), "costs": round(costs,2), "orders": orders,
            "halts": len(halts), "halt_dates": halts, "restart": restart,
            "second_halt": second_halt, "restart_info": rinfo, "curve": curve}

def btc_hold(start, end):
    i0 = next(i for i,d in enumerate(CAL) if d >= start)
    i1 = max(i for i,d in enumerate(CAL) if d <= end)
    sh = (POT*(1-COST))/OPENS["BTC"][i0]
    return round(sh*CLOSES["BTC"][i1]*(1-COST), 2)

def main():
    os.makedirs(os.path.join(HERE,"cells"), exist_ok=True)
    # ---- INTEGRITY: original form (monthly, original floor variants) ----
    full_plain = simulate("2020-06-01","2026-11-20","monthly","ranked")  # plain: floor 85, no ladder
    val_ep1 = simulate("2023-01-01","2026-11-20","monthly","ranked")
    val_v9 = run_v9("2023-01-01","2026-11-20","monthly","ranked")
    integrity = {
        "status": "reproduced" if (round(full_plain.final,2)==297.62 and round(val_ep1.final,2)==82.49 and val_v9["final"]==80.39) else "FAILED",
        "original_finals": {"full_plain": 297.62, "validation_plain_as_published": 82.49,
                            "validation_v9_rules": 80.39},
        "reproduced_finals": {"full_plain": round(full_plain.final,2),
                              "validation_plain_as_published": round(val_ep1.final,2),
                              "validation_halt": val_ep1.halt,
                              "validation_v9_rules": val_v9["final"],
                              "validation_v9_halts": val_v9["halt_dates"],
                              "validation_v9_restart": val_v9["restart_info"]},
        "note": "Original form = monthly decisions, plain -15% floor, original windows (FULL 2020-06-01->2026-11-20; VALIDATION 2023-01-01->2026-11-20), 0.25%/side. v9 form adds the 90-day cash sit + restart at next monthly selection (2023-10-01) under an episode-2 floor."}
    print("INTEGRITY:", json.dumps(integrity["reproduced_finals"]), integrity["status"], flush=True)
    btc_road = btc_hold(ROAD_START, ROAD_END)
    print(f"BTC buy-hold same road: {btc_road} (original published 618.21)", flush=True)
    # ---- SWEEP ----
    cells = {}; money = []
    for cad in ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]:
        r = run_v9(ROAD_START, ROAD_END, cad, "ranked")
        placebo_finals = []
        for s in range(1,21):
            pr = run_v9(ROAD_START, ROAD_END, cad, "placebo", seed=s)
            placebo_finals.append(pr["final"])
        beaten = sum(1 for v in placebo_finals if r["final"] > v)
        cell = {"final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
                "halts": r["halts"], "halt_dates": r["halt_dates"], "restart": r["restart"],
                "second_halt": r["second_halt"], "restart_info": r["restart_info"],
                "costs": r["costs"], "orders": r["orders"],
                "placebo_beaten": beaten, "placebo_finals": placebo_finals,
                "placebo_note": "20 seeds, random 5 eligible per decision, same v9 machinery, fresh RNG per episode",
                "btc_hold_same_road": btc_road, "spy_decade_reference": SPY_DECADE,
                "road": {"start": ROAD_START, "end": ROAD_END,
                         "note": "Longest honest sub-window of DECADE 2016-11-21->2026-11-20: cache starts 2018, rule needs 365d momentum + 200d SMA lookback; original FULL window start. SPY $367.80 is the full-decade reference (different road)."},
                "equity_curve": [[d,v] for d,v in r["curve"]]}
        with open(os.path.join(HERE,"cells",f"{cad}.json"),"w") as f: json.dump(cell,f,indent=1)
        cells[cad] = {k: cell[k] for k in ("final","cagr_pct","max_dd_pct","halts","restart","second_halt","costs","orders","placebo_beaten","placebo_note")}
        if r["final"] > btc_road and beaten >= 11: money.append(cad)  # beats BTC road benchmark AND placebo majority; SPY is a different road, reported not gated
        print(f"{cad}: final={r['final']} CAGR={r['cagr_pct']} DD={r['max_dd_pct']} halts={r['halts']} {r['halt_dates']} costs={r['costs']} orders={r['orders']} placebo {beaten}/20", flush=True)
    results = {"slug":"crypto-basket",
        "area":"Crypto era — multi-coin momentum basket on its own universe (survivor 20-coin list, NOT point-in-time; the PIT form is the separate crypto-basket-pit row)",
        "area_source":"SPEC W10: baskets per their snapshot history; judged vs BTC buy-hold AND vs SPY",
        "native_cadence":"monthly","cadence":"monthly",
        "original_cadence_foreign": False,
        "native_change":"none — original form was native (monthly). Sweep varies cadence only; road is the longest honest sub-window of the decade (see cells road note).",
        "integrity": integrity, "decade_spy_final": SPY_DECADE,
        "btc_hold_same_road": btc_road,
        "champion_decade_reference": 65.89,
        "cells": cells, "money_cadences": money,
        "verdict_area":"NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change":"No change — the original program already found the basket does not transfer to crypto (ranking lost to random, BTC hold beat every variant); the sweep confirms it at every cadence on the decade road. Any cadence beating BTC+placebo would have been marked PROVISIONAL pending confirmation per the CONFIRMATION RULE; none did." if not money else "PROVISIONAL flip — see RESULTS.md"}
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(results,f,indent=1)
    print("saved results.json; money cadences:", money)

if __name__ == "__main__": main()
