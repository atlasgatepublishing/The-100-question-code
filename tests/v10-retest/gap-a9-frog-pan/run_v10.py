#!/usr/bin/env python3
"""
V10 GREAT RETEST — gap-a9-frog-pan (Da, Gurun & Warachka 2014 frog-in-the-pan).

(1) INTEGRITY: original-form runs (monthly, plain -15% floor, NO restart,
    original chassis from backtests/v7/gap-a9-frog-pan/frog-pan.py) on
    CONT 2019-01-02->2026-11-20 and VAL 2023-01-03->2026-11-20.
    Published targets: frog CONT $199.91, VAL $118.59; basket identical
    dates $291.53 / $208.27; VAL placebo beaten 1/20 (5th percentile);
    canonical SPY $313.62 / $187.77.
(2) SWEEP: DECADE 2016-11-21 -> 2026-11-20 at 7 cadences (daily, weekly,
    biweekly, monthly, quarterly, semiannual, annual) under the SPEC's
    uniform cadence definition + v9 protections (plain -15% floor from
    episode start; on first halt liquidate at next open, sit in cash 90
    calendar days, restart at the next regular cadence decision point
    under an episode-2 floor of -15% from the restart balance; second
    halt ends the run in cash). $100/cell, program costs
    (0.10%/side + $0.01 per sell order), 20-seed random-rank placebos
    per cell (random 5 from the same positive-momentum eligible set).

Cadence dates: decision dates are generated on the SPY master calendar —
daily = every trading day; weekly = first trading day of each ISO week;
biweekly = every second weekly date, anchored on the first weekly date
of the data calendar (week of 2015-01-02); monthly = first trading day
of each month; quarterly = first trading day of each calendar quarter;
semiannual = first trading day of each half-year; annual = first
trading day of each year. The first trading day of the window is always
an entry decision point (so no pot idles waiting for a boundary);
thereafter decisions occur only on cadence dates. Signals use the
prior trading day's close; trades execute at the decision day's open —
identical mechanics to the original engine. The -15% floor is checked
on every daily close (protection is not cadence-gated).

Data: read-only shared cache backtests/v4/momentum-basket-honest-data/
(Yahoo split-adjusted daily bars, 2015-01-02 -> 2026-11-20, 30-name pond
+ SPY master calendar) — the identical basis of the original test.
Canonical SPY benchmark: dividend-adjusted series from
backtests/v4/data/px_SPY.json via the champion engine's spy_net formula.
Precomputed per-ticker momentum / information-discreteness arrays keep
memory bounded (no long-run cache is loaded).
"""
import json, math, os, random
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG",
            "V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO",
            "GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COST_RATE = 0.001; SELL_FEE = 0.01; POT = 100.0
SEEDS = list(range(1, 21))
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]

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
        # precompute momentum 12-1 and DGW information discreteness per index
        self.mom = {}; self.idv = {}; self.sma200 = {}
        n = len(self.cal)
        for t in tickers:
            c = self.closes[t]
            mom = [None]*n; idv = [None]*n; sma = [None]*n
            run = 0.0
            for i in range(n):
                if c[i] is not None: run += c[i]
                if i >= 199 and c[i-199] is not None: sma[i] = (run - (sum(c[max(0,i-399):i-199]) if False else 0))  # placeholder replaced below
            # proper SMA200 via prefix sums
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
                        seg = c[i-252:i-20]  # 232 closes [i-252..i-21]
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
            # anchor: global weekly list from data start, take every 2nd
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
    out.add(i0)  # window-entry decision point
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
    pending_liq = False; ended = False; restart_after = None  # date string
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
            trig = res.halts[-1]["trigger_date"]
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
        # decision / rebalance
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
    if pending_liq:  # window ended next day out of range (defensive)
        pass
    res.final = res.curve[-1][1] if not ended else cash
    if ended: res.final = cash
    peak = -1.0
    for d, eq in res.curve:
        peak = max(peak, eq)
        if peak > 0: res.max_dd = min(res.max_dd, eq/peak-1.0)
    return res

# canonical SPY (dividend-adjusted). NOTE: backtests/v4/data/px_SPY.json
# only starts 2017-06-01, so it silently shortens the DECADE window
# (it gave $329.76 on a 2017-06 start). The full-range series in
# backtests/v7/long-hold/data/pxfull_SPY.json (2008->2026, read-only,
# single file) reproduces ALL published canonical figures exactly:
# DECADE $367.80, CONT $313.62, VAL $187.77 — so it is the source here.
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

def main():
    mkt = Market(UNIVERSE)
    out = {"slug":"gap-a9-frog-pan"}
    # ---------- INTEGRITY (original form: monthly, plain floor, no restart)
    integ = {}
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
                       "spy_canonical": spy_net_canon(sd,ed)}
        print(f"INTEGRITY {name}: frog={rf.final:.2f} basket={rb.final:.2f} "
              f"spy={integ[name]['spy_canonical']} placebo_beaten={beat}/20", flush=True)
    out["integrity_runs"] = integ
    # ---------- SWEEP: decade x 7 cadences, v9 protections
    spy_dec = spy_net_canon(*DECADE)
    print(f"DECADE SPY canonical = {spy_dec} (SPEC reference 367.80)", flush=True)
    ydec = yrs(*DECADE)
    cells = {}
    os.makedirs(os.path.join(HERE,"cells"), exist_ok=True)
    basket_dec = None
    for cad in CADENCES:
        r = simulate(mkt, *DECADE, "frog", cad, v9=True)
        twins = []; twin_full = []
        for s in SEEDS:
            rp = simulate(mkt, *DECADE, "placebo", cad, seed=s, v9=True)
            twins.append(round(rp.final,2)); twin_full.append(rp)
        beat = sum(1 for v in twins if r.final > v)
        s = summ(r, ydec); s["placebo_beaten"] = beat; s["placebo_finals"] = twins
        cells[cad] = s
        cell_doc = {"slug":"gap-a9-frog-pan","window":"DECADE","start":DECADE[0],"end":DECADE[1],
                    "cadence":cad, **s,
                    "equity_curve": [[d, round(v,2)] for d,v in r.curve],
                    "placebo_twins": [{"seed": sd_, "final": twins[k],
                                       "max_dd_pct": round(twin_full[k].max_dd*100,2),
                                       "costs": round(twin_full[k].costs,2),
                                       "orders": twin_full[k].orders,
                                       "halts": twin_full[k].halts}
                                      for k, sd_ in enumerate(SEEDS)]}
        with open(os.path.join(HERE,"cells",f"{cad}.json"),"w") as f:
            json.dump(cell_doc, f, indent=1)
        print(f"CELL {cad}: final={r.final:.2f} cagr={s['cagr_pct']} dd={s['max_dd_pct']} "
              f"costs={s['costs']} orders={r.orders} halts={len(r.halts)} placebo {beat}/20", flush=True)
        if cad == "monthly":
            basket_dec = simulate(mkt, *DECADE, "basket", "monthly", v9=True)
    bs = summ(basket_dec, ydec)
    out["decade_spy_final"] = spy_dec
    out["basket_decade_monthly_v9"] = bs
    out["cells_summary"] = cells
    out["integrity_status_check"] = {
        "frog_cont": integ["CONT"]["frog"]["final"], "frog_val": integ["VAL"]["frog"]["final"],
        "basket_cont": integ["CONT"]["basket_same_dates"]["final"],
        "basket_val": integ["VAL"]["basket_same_dates"]["final"]}
    with open(os.path.join(HERE,"sweep_raw.json"),"w") as f:
        json.dump(out, f, indent=1)
    print("saved sweep_raw.json + cells/")

if __name__ == "__main__":
    main()
