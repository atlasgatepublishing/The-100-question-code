#!/usr/bin/env python3
"""
V10 GREAT RETEST — CONFIRMATION RUN for gap-a9-frog-pan, QUARTERLY and
SEMI-ANNUAL cadences (SPEC.md CONFIRMATION RULE, Terry 2026-11-21 ~22:19:
a new money cadence is not crowned until it is re-run on the other roads;
a decade-only flip reads "decade-only, unconfirmed").

Sweep findings under test (DECADE 2016-11-21 -> 2026-11-20): native
monthly NO GROUND ($267.50, 5/20 placebos, SPY $367.80, plain basket
$439.45), but quarterly $401.42 (16/20) and semiannual $459.96 (18/20),
both beating SPY.

This script (engine code copied verbatim from the sweep's run_v10.py —
identical plumbing/mechanics; cadence governs re-rank/rebalance dates
only; v9 protections: plain -15% floor from episode start, liquidate at
next open on halt, 90 calendar days in cash, restart at the next regular
cadence decision point under an episode-2 -15% floor, second halt ends):

  1. INTEGRITY GATE — original published finals reproduced through this
     plumbing in original form (monthly, plain floor, NO restart):
     frog CONT $199.91 / VAL $118.59; plain basket same dates
     $291.53 / $208.27; placebos beaten CONT 8/20, VAL 1/20.
     SPY (dividend-adjusted, champion spy_net formula) verified against
     SPEC references: LONG(2010) $822.94, DECADE $367.80, CONT $313.62,
     VAL $187.77.
  2. CONFIRMATION ROADS at quarterly + semiannual, $100, program costs
     (0.10%/side + $0.01 per sell order), point-in-time only:
       LONG  — LONGEST HONEST ROAD. The frog/basket pond data (read-only
               shared cache backtests/v4/momentum-basket-honest-data/,
               Yahoo split-adjusted daily bars) begins 2015-01-02 and
               covers only the 30-name pond; there is NO 2010 pond data
               in this chassis and none may be backfilled. The 12-1
               momentum + information-discreteness signal needs 252
               trading days of lookback, so the first date a decision
               can rest on a full lookback is 2016-01-04 (index 252 of
               the calendar). LONG here = 2016-01-04 -> 2026-11-20.
               SPY on that honest road is printed beside the strategy
               ($408.30); the 2010 SPY reference $822.94 is verified
               as a benchmark-integrity check only.
       CONT  — 2019-01-02 -> 2026-11-20 (SPY $313.62)
       VAL   — 2023-01-03 -> 2026-11-20 (SPY $187.77)
     On each road, the PLAIN (un-frogged) momentum basket is also run at
     the SAME cadence, and 20-seed random-rank placebos (random 5 from
     the same positive-12-1-momentum eligible set, same cadence/engine/
     protections, seeds 1..20 — the sweep's design) are run per
     road/cadence.
  3. FRESH YEARLY FOLDS — fresh $100 per calendar year, 2016..2026
     (2026 is the partial year 2026-01-02 -> 2026-11-20), both cadences,
     frog + plain basket + SPY + 20 placebos per fold.

Outputs (this folder only): per-road/per-cadence JSONs
(long_quarterly.json, long_semiannual.json, cont_quarterly.json,
cont_semiannual.json, val_quarterly.json, val_semiannual.json) each with
final/CAGR/max DD/costs/orders, halts & restarts WITH DATES, the full
equity curve, the basket block, and all 20 placebo twin finals;
folds.json; confirmation_summary.json. CONFIRMATION.md is written by
hand from these files.

MEMORY: data loaded narrowly, one ticker file at a time (same as the
sweep); the 1.7GB long-run cache is never touched.
"""
import json, math, os, random
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG",
            "V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO",
            "GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COST_RATE = 0.001; SELL_FEE = 0.01; POT = 100.0
SEEDS = list(range(1, 21))
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
LONG_HONEST = ("2016-01-04", "2026-11-20")   # see docstring: no 2010 pond data
LONG_REF = ("2010-01-04", "2026-11-20")      # SPY benchmark check only
CADENCES = ["quarterly", "semiannual"]
ROADS = [("LONG", LONG_HONEST), ("CONT", CONT), ("VAL", VAL)]

# ---------------------------------------------------------------- engine
# (verbatim from ../run_v10.py — identical sweep plumbing/mechanics)
def load(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f: return json.load(f)

class Market:
    def __init__(self, tickers):
        spy = load("SPY")
        self.cal = [r["d"] for r in spy]
        self.bars = {}; self.closes = {}
        for t in tickers + ["SPY"]:
            raw = spy if t == "SPY" else load(t)
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]: last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr
        self.mom = {}; self.idv = {}; self.sma200 = {}
        n = len(self.cal)
        for t in tickers:
            c = self.closes[t]
            mom = [None]*n; idv = [None]*n; sma = [None]*n
            pref = [0.0]; ok = [0]
            for v in c:
                pref.append(pref[-1] + (v if v is not None else 0.0))
                ok.append(ok[-1] + (1 if v is not None else 0))
            for i in range(n):
                if i >= 199 and ok[i+1]-ok[i-199] == 200:
                    sma[i] = (pref[i+1]-pref[i-199])/200.0
                if i >= 252:
                    a, b = c[i-252], c[i-21]
                    if a and b and a > 0:
                        m = b/a - 1.0; mom[i] = m
                        seg = c[i-252:i-20]
                        if all(v is not None and v > 0 for v in seg):
                            up = down = 0
                            for k in range(1, len(seg)):
                                r = seg[k]/seg[k-1]-1.0
                                if r > 0: up += 1
                                elif r < 0: down += 1
                            tot = len(seg)-1
                            sgn = 1.0 if m > 0 else (-1.0 if m < 0 else 0.0)
                            idv[i] = sgn*(down/tot - up/tot)
            self.mom[t] = mom; self.idv[t] = idv; self.sma200[t] = sma
    def open_px(self, t, i):
        d = self.cal[i]
        return self.bars[t][d][0] if d in self.bars[t] else None
    def close_px(self, t, i): return self.closes[t][i]

def cadence_dates(mkt, cadence, i0, i1):
    idx = list(range(i0, i1+1))
    cal = mkt.cal
    if cadence == "daily": return set(idx)
    out = set()
    if cadence == "weekly" or cadence == "biweekly":
        seen = {}
        for i in idx:
            dt = datetime.strptime(cal[i], "%Y-%m-%d")
            key = dt.isocalendar()[:2]
            if key not in seen: seen[key] = i
        weeks = [seen[k] for k in sorted(seen)]
        if cadence == "weekly": out = set(weeks)
        else:
            gseen = {}
            for i, d in enumerate(cal):
                dt = datetime.strptime(d, "%Y-%m-%d")
                key = dt.isocalendar()[:2]
                if key not in gseen: gseen[key] = i
            gweeks = [gseen[k] for k in sorted(gseen)]
            gset = set(gweeks[0::2])
            out = {i for i in weeks if i in gset}
    elif cadence == "monthly":
        seen = {}
        for i in idx:
            k = cal[i][:7]
            if k not in seen: seen[k] = i
        out = set(seen.values())
    elif cadence == "quarterly":
        seen = {}
        for i in idx:
            y, m = cal[i][:4], int(cal[i][5:7])
            k = (y, (m-1)//3)
            if k not in seen: seen[k] = i
        out = set(seen.values())
    elif cadence == "semiannual":
        seen = {}
        for i in idx:
            y, m = cal[i][:4], int(cal[i][5:7])
            k = (y, 0 if m <= 6 else 1)
            if k not in seen: seen[k] = i
        out = set(seen.values())
    elif cadence == "annual":
        seen = {}
        for i in idx:
            k = cal[i][:4]
            if k not in seen: seen[k] = i
        out = set(seen.values())
    out.add(i0)
    return out

class Res:
    def __init__(self):
        self.final=None; self.orders=0; self.costs=0.0; self.curve=[]
        self.halts=[]; self.restart=False; self.second_halt=False
        self.max_dd=0.0

def simulate(mkt, start_d, end_d, mode, cadence="monthly", seed=42, v9=True):
    """mode: frog | basket | placebo. v9=False reproduces the original
    plain-floor/no-restart form (monthly only, used for integrity)."""
    rng = random.Random(seed)
    i0 = next(i for i,d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i,d in enumerate(mkt.cal) if d <= end_d)
    dec = cadence_dates(mkt, cadence, i0, i1)
    cash = float(POT); pos = {}; res = Res()
    episode = 1; floor = 0.85*POT; ep_start_balance = POT
    pending_liq = False; ended = False; restart_after = None
    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t,i) if use_open else mkt.close_px(t,i)
            if px is None: px = mkt.close_px(t,i)
            if px is not None: tot += sh*px
        return tot
    def liquidate(i, use_open):
        nonlocal cash
        for t in list(pos):
            px = mkt.open_px(t,i) if use_open else mkt.close_px(t,i)
            if px is None: px = mkt.close_px(t,i)
            val = pos[t]*px; fee = val*COST_RATE + SELL_FEE
            cash += val - fee; res.costs += fee; res.orders += 1
            del pos[t]
    for i in range(i0, i1+1):
        d = mkt.cal[i]
        if ended:
            res.curve.append((d, cash)); continue
        if pending_liq:
            liquidate(i, use_open=True)
            res.halts[-1]["liquidation_date"] = d
            res.halts[-1]["balance_after"] = round(cash,2)
            pending_liq = False
            if episode == 1 and v9:
                episode = 2
                restart_after = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True; res.second_halt = (len(res.halts) >= 2)
                res.curve.append((d, cash)); continue
        can_trade = (restart_after is None or d >= restart_after)
        if i in dec and can_trade and i > 0:
            if restart_after is not None and not res.restart:
                res.restart = True; ep_start_balance = cash
                floor = 0.85*cash; restart_after = None
                res.halts[-1]["restart_date"] = d
                res.halts[-1]["restart_balance"] = round(cash,2)
            j = i-1
            if mode == "basket":
                elig = []
                for t in UNIVERSE:
                    s = mkt.sma200[t][j]; c = mkt.close_px(t,j)
                    if s is None or c is None or c <= s: continue
                    m = mkt.mom[t][j]
                    if m is None: continue
                    elig.append((t,m))
                elig.sort(key=lambda x: -x[1])
                picks = [t for t,_ in elig[:5]]
            else:
                elig = []
                for t in UNIVERSE:
                    m = mkt.mom[t][j]
                    if m is None or m <= 0: continue
                    v = mkt.idv[t][j]
                    if v is None: continue
                    elig.append((t,m,v))
                if mode == "frog":
                    elig.sort(key=lambda x: (x[2], -x[1], x[0]))
                    picks = [t for t,_,_ in elig[:5]]
                else:
                    names = sorted(t for t,_,_ in elig)
                    picks = rng.sample(names, min(5,len(names))) if names else []
            eq_open = equity_at(i, use_open=True)
            target = {t: 0.20*eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t,i)
                if px is None: continue
                cur = pos[t]*px; want = target.get(t,0.0)
                if cur > want + 0.01:
                    sv = cur-want; sh = sv/px; fee = sv*COST_RATE + SELL_FEE
                    cash += sv-fee; res.costs += fee; res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t]*px < 0.01: del pos[t]
            for t in picks:
                px = mkt.open_px(t,i)
                if px is None: continue
                cur = pos.get(t,0.0)*px; deficit = target[t]-cur
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1.0+COST_RATE))
                if bv <= 0.01: continue
                fee = bv*COST_RATE; cash -= bv+fee; res.costs += fee; res.orders += 1
                pos[t] = pos.get(t,0.0) + bv/px
        eq_close = equity_at(i, use_open=False)
        res.curve.append((d, round(eq_close,4)))
        if pos and eq_close <= floor:
            res.halts.append({"episode": episode, "trigger_date": d,
                              "floor": round(floor,2),
                              "episode_start_balance": round(ep_start_balance,2)})
            if i == i1:
                liquidate(i, use_open=False)
                res.halts[-1]["liquidation_date"] = d
                res.halts[-1]["balance_after"] = round(cash,2)
                if episode == 2 or not v9: res.second_halt = (episode==2)
                ended = True
            else:
                pending_liq = True
    res.final = res.curve[-1][1] if not ended else cash
    if ended: res.final = cash
    peak = -1.0
    for d, eq in res.curve:
        peak = max(peak, eq)
        if peak > 0: res.max_dd = min(res.max_dd, eq/peak-1.0)
    return res

# canonical SPY (dividend-adjusted) — same source/formula as the sweep:
# backtests/v7/long-hold/data/pxfull_SPY.json (single file, read-only),
# which reproduces DECADE $367.80, CONT $313.62, VAL $187.77, LONG $822.94.
def load_spy_canon():
    with open(os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json"),
        "rb") as f:
        jj = json.loads(f.read())
    r = jj["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose",[{}])[0].get("adjclose")
    bars = {}
    for k,t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o,c = q["open"][k], q["close"][k]
        if c is None: continue
        a = adj[k] if adj and adj[k] else c
        ratio = a/c if c else 1.0
        bars[d] = ((o*ratio) if o else a, a)
    return bars
SPY_CANON = load_spy_canon()
def spy_net_canon(sd, ed):
    days = sorted(d for d in SPY_CANON if sd <= d <= ed)
    o = SPY_CANON[days[0]][0]
    sh = (POT/1.001)/o
    val = sh*SPY_CANON[days[-1]][1]
    return round(val - (val*COST_RATE + SELL_FEE), 2)

def yrs(a,b):
    return (datetime.strptime(b,"%Y-%m-%d")-datetime.strptime(a,"%Y-%m-%d")).days/365.25
def cagr(final, y):
    return round(((final/POT)**(1.0/y)-1.0)*100,2) if final and final>0 else None
def summ(res, y):
    return {"final": round(res.final,2), "cagr_pct": cagr(res.final,y),
            "max_dd_pct": round(res.max_dd*100,2), "costs": round(res.costs,2),
            "orders": res.orders, "halts": len(res.halts),
            "restart": res.restart, "second_halt": res.second_halt,
            "halt_detail": res.halts}
def block(res, y):
    b = summ(res, y)
    b["equity_curve"] = [[d, round(v,2)] for d,v in res.curve]
    return b

def main():
    mkt = Market(UNIVERSE)
    summary = {"slug": "gap-a9-frog-pan", "run": "confirmation-quarterly-semiannual"}

    # ---------- 1. INTEGRITY GATE (original form, monthly, no restart)
    integ = {"spy_checks": {
        "LONG_2010_reference": {"computed": spy_net_canon(*LONG_REF), "spec_reference": 822.94},
        "DECADE": {"computed": spy_net_canon(*DECADE), "spec_reference": 367.80},
        "CONT": {"computed": spy_net_canon(*CONT), "spec_reference": 313.62},
        "VAL": {"computed": spy_net_canon(*VAL), "spec_reference": 187.77}}}
    targets = {"CONT": {"frog": 199.91, "basket": 291.53, "placebo_beaten": 8},
               "VAL": {"frog": 118.59, "basket": 208.27, "placebo_beaten": 1}}
    ok = all(v["computed"] == v["spec_reference"] for v in integ["spy_checks"].values())
    for name,(sd,ed) in [("CONT",CONT),("VAL",VAL)]:
        y = yrs(sd,ed)
        rf = simulate(mkt, sd, ed, "frog", "monthly", v9=False)
        rb = simulate(mkt, sd, ed, "basket", "monthly", v9=False)
        twins = []
        for s in SEEDS:
            rp = simulate(mkt, sd, ed, "placebo", "monthly", seed=s, v9=False)
            twins.append(round(rp.final,2))
        beat = sum(1 for v in twins if rf.final > v)
        integ[name] = {"frog": summ(rf,y), "basket_same_dates": summ(rb,y),
                       "placebo_finals": twins, "placebo_beaten": beat,
                       "published": targets[name],
                       "match": (round(rf.final,2)==targets[name]["frog"]
                                 and round(rb.final,2)==targets[name]["basket"]
                                 and beat==targets[name]["placebo_beaten"])}
        ok = ok and integ[name]["match"]
        print(f"INTEGRITY {name}: frog={rf.final:.2f} (pub {targets[name]['frog']}) "
              f"basket={rb.final:.2f} (pub {targets[name]['basket']}) "
              f"placebo_beaten={beat}/20 (pub {targets[name]['placebo_beaten']})", flush=True)
    integ["status"] = "reproduced" if ok else "FAILED"
    print(f"INTEGRITY SPY checks: " +
          ", ".join(f"{k}={v['computed']} vs {v['spec_reference']}" for k,v in integ['spy_checks'].items()), flush=True)
    print(f"INTEGRITY STATUS: {integ['status']}", flush=True)
    summary["integrity"] = integ
    if not ok:
        with open(os.path.join(HERE,"confirmation_summary.json"),"w") as f:
            json.dump(summary, f, indent=1)
        raise SystemExit("INTEGRITY GATE FAILED — confirmation numbers do not count.")

    # ---------- 2. CONFIRMATION ROADS: quarterly + semiannual
    summary["long_limitation"] = (
        "No 2010 LONG run is possible in this chassis: the pond price cache "
        "(backtests/v4/momentum-basket-honest-data/) starts 2015-01-02 and the "
        "12-1 momentum / information-discreteness signal needs 252 trading "
        "days of lookback, so the longest honest road is 2016-01-04 -> "
        "2026-11-20. SPY on that road: $408.30. The SPEC 2010 SPY reference "
        "($822.94) was verified in-plumbing as a benchmark check only.")
    summary["roads"] = {}
    for road,(sd,ed) in ROADS:
        y = yrs(sd,ed); spy = spy_net_canon(sd,ed)
        summary["roads"][road] = {"start": sd, "end": ed, "spy_final": spy, "cadences": {}}
        for cad in CADENCES:
            rf = simulate(mkt, sd, ed, "frog", cad, v9=True)
            rb = simulate(mkt, sd, ed, "basket", cad, v9=True)
            twins = []; twin_full = []
            for s in SEEDS:
                rp = simulate(mkt, sd, ed, "placebo", cad, seed=s, v9=True)
                twins.append(round(rp.final,2)); twin_full.append(rp)
            beat = sum(1 for v in twins if rf.final > v)
            doc = {"slug": "gap-a9-frog-pan", "confirmation": True,
                   "road": road, "start": sd, "end": ed, "cadence": cad,
                   "spy_final": spy,
                   "frog": block(rf, y),
                   "basket_same_cadence": block(rb, y),
                   "frog_minus_basket": round(rf.final - rb.final, 2),
                   "frog_minus_spy": round(rf.final - spy, 2),
                   "placebo_beaten": beat,
                   "placebo_finals": twins,
                   "placebo_twins": [{"seed": sd_, "final": twins[k],
                                       "max_dd_pct": round(twin_full[k].max_dd*100,2),
                                       "costs": round(twin_full[k].costs,2),
                                       "orders": twin_full[k].orders,
                                       "halts": twin_full[k].halts}
                                      for k, sd_ in enumerate(SEEDS)],
                   "placebo_note": "20 seeds (1..20), random 5 from the same positive-12-1-momentum eligible set, same cadence/engine/v9 protections — the sweep's design."}
            with open(os.path.join(HERE, f"{road.lower()}_{cad}.json"), "w") as f:
                json.dump(doc, f, indent=1)
            summary["roads"][road]["cadences"][cad] = {
                "frog_final": round(rf.final,2), "basket_final": round(rb.final,2),
                "spy_final": spy, "placebo_beaten": beat,
                "frog_cagr_pct": cagr(rf.final,y), "frog_max_dd_pct": round(rf.max_dd*100,2),
                "frog_costs": round(rf.costs,2), "frog_orders": rf.orders,
                "frog_halts": len(rf.halts), "frog_restart": rf.restart,
                "frog_second_halt": rf.second_halt}
            print(f"ROAD {road} {cad}: frog={rf.final:.2f} basket={rb.final:.2f} "
                  f"spy={spy} placebo {beat}/20 halts={len(rf.halts)}", flush=True)

    # ---------- 3. FRESH YEARLY FOLDS (fresh $100/year, 2016..2026)
    folds = {"note": "Fresh $100 per calendar year; 2026 is the partial year "
                     "2026-01-02 -> 2026-11-20 (last day of data). v9 protections "
                     "apply inside each fold. Placebos: same 20-seed design.",
             "years": {}}
    for yr in range(2016, 2027):
        days = [d for d in mkt.cal if d.startswith(str(yr)) and d <= "2026-11-20"]
        sd, ed = days[0], days[-1]
        y = yrs(sd, ed); spy = spy_net_canon(sd, ed)
        entry = {"start": sd, "end": ed, "spy_final": spy, "cadences": {}}
        for cad in CADENCES:
            rf = simulate(mkt, sd, ed, "frog", cad, v9=True)
            rb = simulate(mkt, sd, ed, "basket", cad, v9=True)
            twins = []
            for s in SEEDS:
                rp = simulate(mkt, sd, ed, "placebo", cad, seed=s, v9=True)
                twins.append(round(rp.final,2))
            beat = sum(1 for v in twins if rf.final > v)
            entry["cadences"][cad] = {
                "frog": summ(rf, y), "basket_same_cadence": summ(rb, y),
                "frog_minus_basket": round(rf.final - rb.final, 2),
                "frog_minus_spy": round(rf.final - spy, 2),
                "placebo_beaten": beat, "placebo_finals": twins}
        folds["years"][str(yr)] = entry
        print(f"FOLD {yr} ({sd}->{ed}): spy={spy} " +
              " ".join(f"{cad}: frog={entry['cadences'][cad]['frog']['final']} "
                       f"basket={entry['cadences'][cad]['basket_same_cadence']['final']} "
                       f"pl={entry['cadences'][cad]['placebo_beaten']}/20"
                       for cad in CADENCES), flush=True)
    with open(os.path.join(HERE,"folds.json"),"w") as f:
        json.dump(folds, f, indent=1)
    summary["folds_file"] = "folds.json"
    with open(os.path.join(HERE,"confirmation_summary.json"),"w") as f:
        json.dump(summary, f, indent=1)
    print("saved per-road JSONs + folds.json + confirmation_summary.json")

if __name__ == "__main__":
    main()
