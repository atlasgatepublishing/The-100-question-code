#!/usr/bin/env python3
"""hunt-raschke-holy-grail — V13 BEST RULES (see BEST-RULES-SPEC.md, frozen pre-run).
Trend gate: ADX(14)>25 AND EMA20 rising (EMA20[t]>EMA20[t-5]).
Pullback: fresh touch (low<=EMA20 after prior bar low>EMA20) while gate holds.
Entry: next session buy stop at touch high x1.001, lapses if not taken out.
Stop: touch low x0.999 intraday from entry bar (entry-bar breach = stopped).
Exit: close on first bar ADX(14)<25. No target, no cap, no floor.
SPY only, $100 all-in, one position. Costs 0.10%/side + $0.01 sell fee.
Placebos: 20 seeds, touch bars shifted +-30..250, machinery rebuilt locally.
Simulation only. Public data + published signals only."""
import json, os, sys, random, statistics as st, time

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.001; FEE = 0.01

def load_spy():
    p = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    j = json.load(open(p)); r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]; bars = []
    for i, t in enumerate(ts):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]): continue
        k = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": q["open"][i]*k,
                     "h": q["high"][i]*k, "l": q["low"][i]*k, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def adx_ema(bars, n=14):
    N = len(bars); tr = [0.0]*N; pdm = [0.0]*N; mdm = [0.0]*N
    for i in range(1, N):
        up = bars[i]["h"]-bars[i-1]["h"]; dn = bars[i-1]["l"]-bars[i]["l"]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(bars[i]["h"]-bars[i]["l"], abs(bars[i]["h"]-bars[i-1]["c"]), abs(bars[i]["l"]-bars[i-1]["c"]))
    str_ = [0.0]*N; sp = [0.0]*N; sm = [0.0]*N; dx = [None]*N; adx = [None]*N
    if N > n+1:
        str_[n] = sum(tr[1:n+1]); sp[n] = sum(pdm[1:n+1]); sm[n] = sum(mdm[1:n+1])
        for i in range(n+1, N):
            str_[i] = str_[i-1]-str_[i-1]/n+tr[i]; sp[i] = sp[i-1]-sp[i-1]/n+pdm[i]; sm[i] = sm[i-1]-sm[i-1]/n+mdm[i]
        for i in range(n, N):
            if str_[i] > 0:
                pdi = 100*sp[i]/str_[i]; mdi = 100*sm[i]/str_[i]
                dx[i] = 100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi) > 0 else 0.0
        first = 2*n
        if N > first:
            adx[first] = sum(x for x in dx[n:first] if x is not None)/n
            for i in range(first+1, N):
                if dx[i] is not None and adx[i-1] is not None: adx[i] = (adx[i-1]*(n-1)+dx[i])/n
    ema = [None]*N; k = 2/21; s = None
    for i, b in enumerate(bars):
        s = b["c"] if s is None else s + k*(b["c"]-s)
        if i >= 19: ema[i] = s
    return adx, ema

def build_trade(bars, adx, t):
    """Entry next bar at touch high x1.001 (lapse if not taken out); stop touch
    low x0.999 (intraday, entry bar included); exit close on first ADX<25 bar."""
    n = len(bars); e = t+1
    if e >= n: return None
    entry = bars[t]["h"]*1.001; stop = bars[t]["l"]*0.999
    if bars[e]["h"] < entry: return None
    for k in range(e, n):
        if bars[k]["l"] <= stop:
            return dict(entry_i=e, entry_px=entry, exit_i=k, exit_px=stop, exit_reason="stop")
        if adx[k] is not None and adx[k] < 25:
            return dict(entry_i=e, entry_px=entry, exit_i=k, exit_px=bars[k]["c"], exit_reason="trend-death")
    return dict(entry_i=e, entry_px=entry, exit_i=n-1, exit_px=bars[n-1]["c"], exit_reason="data-end")

def gen_touches(bars, adx, ema):
    touches = []
    for t in range(5, len(bars)):
        if adx[t] is None or ema[t] is None or ema[t-5] is None: continue
        if not (adx[t] > 25 and ema[t] > ema[t-5]): continue
        if bars[t]["l"] <= ema[t] and bars[t-1]["l"] > ema[t-1]:
            touches.append(t)
    return touches

def select_nonoverlap(trades):
    out = []; last_exit = -1
    for tr in sorted(trades, key=lambda x: x["entry_i"]):
        if tr["entry_i"] > last_exit:
            out.append(tr); last_exit = tr["exit_i"]
    return out

def simulate(bars, trades, w0, w1):
    """trades: non-overlapping candidate trades (global). Only trades entering
    inside the window are taken; exit past w1 is forced at w1 close."""
    eq = 100.0; curve = [(bars[w0]["d"], eq)]; peak = eq; maxdd = 0.0; done = []; costs = 0.0
    sel = [t for t in trades if w0 <= t["entry_i"] <= w1]
    ti = 0; active = None
    for i in range(w0, w1+1):
        b = bars[i]
        if active is None and ti < len(sel) and sel[ti]["entry_i"] == i:
            t = sel[ti]; ti += 1
            active = dict(sh=eq*(1-COST)/t["entry_px"], **t); costs += eq*COST
        elif active is None and ti < len(sel) and sel[ti]["entry_i"] < i:
            ti += 1  # defensive; should not happen with non-overlap selection
        if active is not None:
            xi = min(active["exit_i"], w1)
            if i >= xi:
                xp = active["exit_px"] if active["exit_i"] <= w1 else b["c"]
                reason = active["exit_reason"] if active["exit_i"] <= w1 else "window-end"
                proceeds = active["sh"]*xp; eq = proceeds*(1-COST) - FEE; costs += proceeds*COST + FEE
                done.append({"entry_d": bars[active["entry_i"]]["d"], "exit_d": b["d"], "reason": reason,
                             "ret": round(xp/active["entry_px"]-1, 4)})
                active = None
        mark = active["sh"]*b["c"] if active else eq
        peak = max(peak, mark); maxdd = min(maxdd, mark/peak-1)
        curve.append((b["d"], round(mark, 4)))
    return round(eq, 2), curve, done, round(maxdd, 4), round(costs, 2)

def monthly_stats(curve):
    marks = {}
    for d, e in curve: marks[d[:7]] = e
    ks = sorted(marks); rets = [marks[b]/marks[a]-1 for a, b in zip(ks, ks[1:])]
    if not rets: return {}
    streak = cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; streak = max(streak, cur)
    peak = -1; last = 0; longest = 0
    for i, k in enumerate(ks):
        if marks[k] >= peak: peak = marks[k]; last = i
        longest = max(longest, i-last)
    return dict(periods=len(rets), share_positive=round(sum(1 for r in rets if r > 0)/len(rets), 3),
                median=round(st.median(rets), 4), best=round(max(rets), 4), worst=round(min(rets), 4),
                mean_secondary=round(st.mean(rets), 4), longest_losing_streak=streak,
                longest_between_highs_months=longest)

def window_idx(bars, a, b):
    idx = [i for i, x in enumerate(bars) if x["d"] >= a and x["d"] <= b]
    return idx[0], idx[-1]

def bh(bars, w0, w1):
    return round(100.0*(1-COST)*(bars[w1]["c"]/bars[w0]["c"])*(1-COST) - FEE*(bars[w1]["c"]/bars[w0]["c"]), 2)

ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

bars = load_spy(); adx, ema = adx_ema(bars)
touches = gen_touches(bars, adx, ema)
cand = [tr for tr in (build_trade(bars, adx, t) for t in touches) if tr]
trades = select_nonoverlap(cand)
print(f"touches={len(touches)} triggered={len(cand)} nonoverlap={len(trades)}")

out = {"family": "hunt-raschke-holy-grail", "rules": "v13-best-rules (ADX>25 + EMA20 rising; every fresh EMA touch; buy-stop entry; stop=touch low; exit ADX<25 close; no floor)",
       "assets": {"SPY": {}}}
res = {}
for rn, (a, b) in ROADS.items():
    w0, w1 = window_idx(bars, a, b)
    f, curve, done, dd, costs = simulate(bars, trades, w0, w1)
    wins = [x["ret"] for x in done if x["ret"] > 0]; losses = [x["ret"] for x in done if x["ret"] <= 0]
    invested = 0  # approx: days with open position
    finals = []
    for s in range(20):
        rng = random.Random(7000+s); ptr = []
        for t in touches:
            nt_idx = t + rng.choice([-1, 1])*rng.randint(30, 250)
            if 20 <= nt_idx < len(bars)-2:
                nt = build_trade(bars, adx, nt_idx)
                if nt: ptr.append(nt)
        pf, _, _, _, _ = simulate(bars, select_nonoverlap(ptr), w0, w1); finals.append(pf)
    r = dict(final=f, max_dd=dd, n_trades=len(done),
             win_rate=round(len(wins)/len(done), 3) if done else None,
             avg_win=round(st.mean(wins), 4) if wins else None,
             avg_loss=round(st.mean(losses), 4) if losses else None,
             expectancy=round(st.mean([x["ret"] for x in done]), 4) if done else None,
             costs=costs, curve=curve, monthly=monthly_stats(curve), trades=done,
             placebo_finals=finals, placebo_beaten=sum(1 for x in finals if f > x),
             placebo_median=round(st.median(finals), 2), bh_bar=bh(bars, w0, w1))
    res[rn] = r
    print(rn, "FINAL", f, "DD", dd, "ntr", r["n_trades"], "win", r["win_rate"], "exp", r["expectancy"],
          "costs", costs, "BH", r["bh_bar"], "plbeat", r["placebo_beaten"], "/20")
out["assets"]["SPY"] = res

# Confirmation (frozen bars) — only for roads beating champion V+M
conf = {}
for rn, (a, b) in ROADS.items():
    if res[rn]["final"] > CHAMP[rn]:
        w0, w1 = window_idx(bars, a, b)
        years = sorted(set(bars[i]["d"][:4] for i in range(w0, w1+1)))
        folds = {}
        for y in years:
            yi = [i for i in range(w0, w1+1) if bars[i]["d"][:4] == y]
            ff, _, _, _, _ = simulate(bars, trades, yi[0], yi[-1]); folds[y] = ff
        mid = bars[(w0+w1)//2]["d"]
        h1 = simulate(bars, trades, w0, (w0+w1)//2); h2 = simulate(bars, trades, (w0+w1)//2, w1)
        bh1 = bh(bars, w0, (w0+w1)//2); bh2 = bh(bars, (w0+w1)//2, w1)
        med = st.median(folds.values())
        passed = med > 100 and h1[0] > 100 and h2[0] > 100 and h1[0] > bh1 and h2[0] > bh2
        conf[rn] = dict(yearly_folds=folds, median_fold=round(med, 2), half1=h1[0], half2=h2[0],
                        bh_half1=bh1, bh_half2=bh2, midpoint=mid, passed=bool(passed))
        print("CONFIRMATION", rn, conf[rn])
out["confirmation"] = conf
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
