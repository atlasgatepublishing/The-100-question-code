#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — residual momentum.
FORM USED (stated plainly): the PUBLISHED Blitz-Huij-Martens signal as frozen
in the v12 CONSTRUCTION-SPEC (FF3 36-month OLS residuals; score = mean/sd of
residuals over months M-12..M-1; PIT S&P 500 universe; price>$1; monthly
scores), in its CONSTRUCTED long-only form (the published long-short decile
form is UNBUILDABLE-NATIVE in this program — v11 NATIVE-SPEC). The v10 pond
adaptation (SPY-beta, 30 names, top-5) is a DIFFERENT signal and is NOT swept
here; the fenced v10 weekly LONG print is not re-judged by this sweep.

Sweep variable: holdings count N in the fixed pre-registered grid
1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE, plus the NATIVE count = top decile
(count = floor(eligible/10) at each formation month, as published).
Cadence: monthly rebalance (native tempo; scores are monthly objects).
Rule sets:
  native = as published: no floor, no stop.
  house  = v9 protections on the same signal/cadence: plain -15% floor,
           on first halt liquidate at next trading day's adjclose, sit out
           90 calendar days, restart at next monthly rebalance on/after the
           eligible date with episode-2 floor = 85% of restart cash; second
           halt ends the run.
Costs: program standard 0.10%/side + $0.01 per sell order. $100 pot,
fractional shares, execution at the rebalance day's adjclose, final
liquidation at the last close with sell costs. Vanished tapes -> ZERO
(v12 frozen rule: tape ended >=10 trading days ago marks the holding 0 and
it can never be sold).
Placebos: 20 seeds per cell; at each formation month the twin holds the
same count of names drawn at random (seeded) from the same eligible pool.
Roads: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03,
all ending 2026-11-20.
Outputs: cells/<rules>-<road>-<count>.json, results.json."""
import bisect, csv, json, math, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells"); os.makedirs(CELLS, exist_ok=True)
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

# ---------- factors ----------
ff = {}
with open(os.path.join(DATA, "ff3_monthly.csv")) as f:
    for row in csv.DictReader(f):
        ff[row["yyyymm"]] = tuple(float(row[k]) / 100.0 for k in ("mktrf", "smb", "hml", "rf"))

def ym(d): return d[:4] + d[5:7]
def month_add(s, k):
    y, m = int(s[:4]), int(s[4:6]) + k
    y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f"{y:04d}{m:02d}"

# ---------- roster ----------
snaps = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
snaps.sort()
snap_dates = [d for d, _ in snaps]
def members_on(date_str):
    i = bisect.bisect_right(snap_dates, date_str) - 1
    return set(snaps[i][1]) if i >= 0 else set()

# ---------- prices -> aligned matrix on SPY calendar ----------
raw = {}
for fn in sorted(os.listdir(DATA)):
    if fn.startswith("px_") and fn.endswith(".json"):
        bars = json.load(open(os.path.join(DATA, fn)))["bars"]
        if len(bars) >= 50:
            raw[fn[3:-5]] = bars
if "SPY" not in raw:
    sys.exit("SPY tape missing — cannot run")
cal = [b[0] for b in raw["SPY"]]
cal_idx = {d: i for i, d in enumerate(cal)}
N_DAYS = len(cal)
tickers = sorted(raw)
t_idx = {t: i for i, t in enumerate(tickers)}
PX = np.full((len(tickers), N_DAYS), np.nan)
LASTBAR = np.full(len(tickers), -1, dtype=int)   # last calendar idx with a bar
for t, bars in raw.items():
    i = t_idx[t]
    for d, v in bars:
        gi = cal_idx.get(d)
        if gi is not None:
            PX[i, gi] = v
            if gi > LASTBAR[i]: LASTBAR[i] = gi
# forward-fill for valuation (a name missing a day or two carries last close);
# the ZERO rule is applied separately via LASTBAR.
for i in range(len(tickers)):
    row = PX[i]
    m = np.isnan(row)
    if m.all(): continue
    idx = np.where(~m, np.arange(N_DAYS), 0)
    np.maximum.accumulate(idx, out=idx)
    PX[i] = row[idx]
print(f"tapes {len(tickers)} days {N_DAYS} cal {cal[0]}..{cal[-1]}", flush=True)

def close_gi(t, gi):
    return float(PX[t_idx[t], gi])

# ---------- monthly returns & scores (as v12 spec) ----------
month_end_close = {}   # t -> {yyyymm: close}
for t in tickers:
    me = {}
    for d, v in raw[t]:
        me[ym(d)] = float(v)
    month_end_close[t] = me
    raw[t] = None  # free bar lists as we go (memory pressure from sibling workers)
del raw
mon_ret = {}
for t, me in month_end_close.items():
    r = {}
    for a, b in zip(sorted(me), sorted(me)[1:]):
        pass
    ms = sorted(me)
    for a, b in zip(ms, ms[1:]):
        if month_add(a, 1) == b and me[a] > 0:
            r[b] = me[b] / me[a] - 1.0
    mon_ret[t] = r

all_months = sorted({ym(d) for d in cal})
def compute_scores(M):
    reg = [month_add(M, -k) for k in range(35, -1, -1)]
    if any(m not in ff for m in reg): return {}, []
    X = np.array([[1.0, ff[m][0], ff[m][1], ff[m][2]] for m in reg])
    XtX_inv = np.linalg.pinv(X.T @ X)
    cand = [d for d in cal if ym(d) == M]
    if not cand: return {}, []
    members = members_on(cand[-1])
    win = [reg.index(month_add(M, -k)) for k in range(12, 0, -1)]
    scores = {}
    for t in members:
        r = mon_ret.get(t)
        if r is None or any(m not in r for m in reg): continue
        if month_end_close[t].get(M, 0) <= 1.0: continue
        y = np.array([r[m] - ff[m][3] for m in reg])
        resid = y - X @ (XtX_inv @ (X.T @ y))
        w = resid[win]
        sd = float(w.std(ddof=1))
        if sd <= 1e-12: continue
        scores[t] = float(w.mean() / sd)
    return scores, sorted(scores)

SCORES = {}
_cache = os.path.join(HERE, "scores_cache.json")
if os.path.exists(_cache):
    for M, (s, elig) in json.load(open(_cache)).items():
        SCORES[M] = (s, elig)
    print("scores loaded from cache", flush=True)
else:
    for M in [m for m in all_months if "200912" <= m <= "202610"]:
        s, elig = compute_scores(M)
        if elig: SCORES[M] = (s, elig)
    with open(_cache, "w") as f:
        json.dump({M: [s, elig] for M, (s, elig) in SCORES.items()}, f)
    print("scores computed and cached", flush=True)
if len(sys.argv) > 1 and sys.argv[1] == "build_scores_only":
    print("BUILD_SCORES_ONLY done", flush=True); sys.exit(0)
ec = sorted(len(v[1]) for v in SCORES.values())
print(f"formation months {len(SCORES)} eligible min/med/max {ec[0]}/{ec[len(ec)//2]}/{ec[-1]}", flush=True)

def latest_score_month(d):
    prev = month_add(ym(d), -1)
    ks = [k for k in SCORES if k <= prev]
    return max(ks) if ks else None

def quarterly_rebal_dates(start, end):
    out, seen = [], set()
    for d in cal:
        if start <= d <= end and d[5:7] in ("01","04","07","10") and d[:7] not in seen:
            seen.add(d[:7]); out.append(d)
    return out

# ---------- engine ----------
def run_pot(start, end, count_spec, rules, placebo_seed=None):
    """count_spec: int N, 'ALL', or 'DECILE' (native). rules: 'native'|'house'."""
    rebal = set(quarterly_rebal_dates(start, end))
    days = [d for d in cal if start <= d <= end]
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH; pos = {}
    total_costs = 0.0; orders = 0; curve = []
    cur_target = []; cur_M = None
    floor = 0.85 * START_CASH; halts = 0; restarts = []
    waiting = False; eligible_date = None; second_halt = None
    vanished = set()

    def live_value(gi):
        v = cash
        for t, sh in pos.items():
            i = t_idx[t]
            if gi - LASTBAR[i] >= 10: continue
            v += sh * PX[i, gi]
        return v

    for d in days:
        gi = cal_idx[d]
        if waiting and d in rebal and d >= eligible_date:
            waiting = False
            restarts[-1]["restart_date"] = d
            restarts[-1]["restart_balance"] = round(cash, 2)
            floor = 0.85 * cash
        if d in rebal and not waiting:
            M = latest_score_month(d)
            if M is not None and M != cur_M:
                scores, elig = SCORES[M]
                if count_spec == "DECILE": k = max(1, len(elig) // 10)
                elif count_spec == "ALL": k = len(elig)
                else: k = min(count_spec, len(elig))
                if rng is None:
                    cur_target = sorted(elig, key=lambda t: -scores[t])[:k]
                else:
                    cur_target = rng.sample(elig, k)
                cur_M = M
            if cur_target:
                tot = live_value(gi)
                tgt_each = tot / len(cur_target)
                tgt = {t: tgt_each for t in cur_target}
                for t in list(pos):  # sells
                    i = t_idx[t]
                    if gi - LASTBAR[i] >= 10:
                        vanished.add(t); del pos[t]; continue
                    cur = pos[t] * PX[i, gi]
                    want = tgt.get(t, 0.0)
                    if cur > want + 0.005:
                        sv = cur - want
                        c = sv * COST_RATE + SELL_FEE
                        cash += sv - c; total_costs += c; orders += 1
                        pos[t] -= sv / PX[i, gi]
                        if pos[t] < 1e-9: del pos[t]
                for t in cur_target:  # buys
                    i = t_idx[t]
                    if gi - LASTBAR[i] >= 10 or PX[i, gi] <= 0: continue
                    cur = pos.get(t, 0.0) * PX[i, gi]
                    bv = tgt[t] - cur
                    if bv > 0.005:
                        bv = min(bv, cash / (1 + COST_RATE))
                        if bv <= 0.005: continue
                        c = bv * COST_RATE
                        cash -= bv + c; total_costs += c; orders += 1
                        pos[t] = pos.get(t, 0.0) + bv / PX[i, gi]
        v = live_value(gi)
        curve.append([d, round(v, 4)])
        if rules == "house" and v <= floor and d != days[-1]:
            # halt: liquidate at NEXT trading day's adjclose
            gi2 = gi + 1
            if gi2 < N_DAYS:
                for t in list(pos):
                    i = t_idx[t]
                    if gi2 - LASTBAR[i] >= 10: continue
                    val = pos[t] * PX[i, gi2]
                    if val > 0.005:
                        c = val * COST_RATE + SELL_FEE
                        cash += val - c; total_costs += c; orders += 1
                pos = {}
            halts += 1
            if halts >= 2:
                second_halt = d
                return finish(cash, total_costs, orders, curve, halts, restarts, second_halt, vanished)
            from datetime import date as _dt, timedelta as _td
            nd = cal[gi2] if gi2 < N_DAYS else d
            elig = (_dt(int(nd[:4]), int(nd[5:7]), int(nd[8:10])) + _td(days=90)).isoformat()
            eligible_date = elig; waiting = True; cur_target = []
            restarts.append({"halt_signal_date": d, "liquidation_date": nd,
                             "liquidation_cash": round(cash, 2),
                             "cash_until_eligible": elig,
                             "restart_date": None, "restart_balance": None})
    # final liquidation
    gi = cal_idx[days[-1]]
    for t in list(pos):
        i = t_idx[t]
        if gi - LASTBAR[i] >= 10: continue
        val = pos[t] * PX[i, gi]
        if val > 0.005:
            c = val * COST_RATE + SELL_FEE
            cash += val - c; total_costs += c; orders += 1
    return finish(cash, total_costs, orders, curve, halts, restarts, second_halt, vanished)

def finish(cash, costs, orders, curve, halts, restarts, second_halt, vanished):
    peak = -1e18; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak * 100.0)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "restarts": restarts, "second_halt": second_halt,
            "vanished_held": sorted(vanished), "curve": curve}

def spy_final(start, end):
    days = [d for d in cal if start <= d <= end]
    i = t_idx["SPY"]
    sh = (START_CASH / (1 + COST_RATE)) / PX[i, cal_idx[days[0]]]
    proceeds = sh * PX[i, cal_idx[days[-1]]]
    return round(proceeds - (proceeds * COST_RATE + SELL_FEE), 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL", "DECILE"]

def dist_stats(curve):
    # monthly periods from daily curve
    bym={}
    for d,v in curve: bym[d[:7]]=v
    ks=sorted(bym); vals=[bym[k] for k in ks]
    rets=[vals[i]/vals[i-1]-1 for i in range(1,len(vals)) if vals[i-1]>0]
    if not rets: return {}
    srt=sorted(rets); n=len(srt)
    med=srt[n//2] if n%2 else (srt[n//2-1]+srt[n//2])/2
    pos=sum(1 for r in rets if r>0)
    ll=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; ll=max(ll,cur)
    peak=-1e18; since=0; lnodh=0
    for v in vals:
        if v>=peak: peak, since = v, 0
        else: since+=1
        lnodh=max(lnodh,since)
    return {"periods":n,"pct_positive":round(100*pos/n,1),"median_pct":round(med*100,2),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "avg_pct_secondary":round(100*sum(rets)/n,2),
            "longest_losing_streak_months":ll,"longest_stretch_between_new_highs_months":lnodh}

def spy_curve_dd(start,end):
    days=[d for d in cal if start<=d<=end]; i=t_idx["SPY"]
    sh=(START_CASH/(1+COST_RATE))/PX[i,cal_idx[days[0]]]
    curve=[[d, round(sh*float(PX[i,cal_idx[d]]),4)] for d in days]
    peak=-1e18; mdd=0.0; pkd=trd=None; curpk=None
    for d,v in curve:
        if v>peak: peak, curpk = v, d
        dd=(peak-v)/peak*100 if peak>0 else 0
        if dd>mdd: mdd, trd, pkd = dd, d, curpk
    fin=spy_final(start,end)
    return fin, round(mdd,2), pkd, trd

def crash_window_ret(curve, pkd, trd):
    if not pkd or not trd: return None
    pts={d:v for d,v in curve}
    ds=[d for d,_ in curve]
    a=max([d for d in ds if d<=pkd], default=None); b=max([d for d in ds if d<=trd], default=None)
    if a and b and pts[a]>0: return round((pts[b]/pts[a]-1)*100,2)
    return None

CHAMP={"LONG":1415.62,"CONT":544.47,"VAL":288.05,"DECADE":667.35}

def run_road(s,e):
    r=run_pot(s,e,20,"native")
    twins=[]
    for seed in range(1,21):
        twins.append(run_pot(s,e,20,"native",placebo_seed=seed)["final"])
    beaten=sum(1 for x in twins if r["final"]>x)
    return r, twins, beaten

def main():
    results={"family":"residual-momentum","program":"v13-best-rules",
             "spec":"BEST-RULES-SPEC.md — quarterly rebalance, top-20, published FF3 signal, PIT S&P500, no floor",
             "spy":{},"cells":{},"confirmation":None}
    beats=[]
    for road,(s,e) in ROADS.items():
        sf, sdd, pkd, trd = spy_curve_dd(s,e)
        results["spy"][road]=sf
        r,twins,beaten=run_road(s,e)
        cell={"road":road,"start":s,"end":e,"final":r["final"],"max_dd_pct":r["max_dd_pct"],
              "costs":r["costs"],"orders":r["orders"],"halts":r["halts"],
              "placebo_beaten":beaten,"placebo_finals":twins,
              "placebo_median":round(float(np.median(twins)),2),
              "spy_final":sf,"spy_max_dd_pct":sdd,
              "crash_window":{"spy_peak_date":pkd,"spy_trough_date":trd,
                              "strategy_ret_pct":crash_window_ret(r["curve"],pkd,trd),
                              "spy_ret_pct":round(-sdd,2)},
              "distribution_monthly":dist_stats(r["curve"]),
              "vanished_held":r["vanished_held"],"equity_curve":r["curve"]}
        results["cells"][road]=cell
        print(f"{road}: ${r['final']} dd {r['max_dd_pct']}% costs ${r['costs']} orders {r['orders']} placebos {beaten}/20 SPY ${sf} dd {sdd}%", flush=True)
        if r["final"]>CHAMP[road]: beats.append(road)
    if beats:
        print(f"CONFIRMATION triggered: {beats}", flush=True)
        folds={}
        for yr in range(2017,2027):
            s=f"{yr}-01-01"; e="2026-11-20" if yr==2026 else f"{yr}-12-31"
            r,twins,beaten=run_road(s,e)
            folds[str(yr)]={"final":r["final"],"spy":spy_final(s,e),"max_dd_pct":r["max_dd_pct"],
                            "placebo_beaten":beaten,"placebo_finals":twins}
            print(f"FOLD {yr}: ${r['final']} SPY ${folds[str(yr)]['spy']} placebos {beaten}/20 dd {r['max_dd_pct']}%", flush=True)
        results["confirmation"]={"roads_triggering":beats,"folds":folds}
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(results,f,indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
