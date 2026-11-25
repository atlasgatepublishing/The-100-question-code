#!/usr/bin/env python3
"""hunt-raschke-holy-grail — frozen SPEC-FROZEN.md. ADX(14)>30 and rising
arms; FIRST pullback touch of EMA20 while armed; entry next session buy stop
at touch-bar high x1.001 (CONSTRUCTED tick); stop = touch-bar low (entry bar
also breaching stop = stopped, per spec); target = highest high from ADX
trigger day through touch bar; 10-session cap exit at close (CONSTRUCTED).
Re-arm only after ADX dips below 30 and re-triggers. Long only on this
chassis (short side published but not run — long-only spot chassis).
Placebos: touch-bar date shifts +-30..250 bars, machinery rebuilt locally.
Simulation only."""
import json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from raschke_common import load_spy, load_coin, simulate, monthly_stats, window_idx, bh
HERE=os.path.dirname(os.path.abspath(__file__))

def adx_ema(bars, n=14):
    N=len(bars); tr=[0.0]*N; pdm=[0.0]*N; mdm=[0.0]*N
    for i in range(1,N):
        up=bars[i]["h"]-bars[i-1]["h"]; dn=bars[i-1]["l"]-bars[i]["l"]
        pdm[i]= up if (up>dn and up>0) else 0.0
        mdm[i]= dn if (dn>up and dn>0) else 0.0
        tr[i]=max(bars[i]["h"]-bars[i]["l"], abs(bars[i]["h"]-bars[i-1]["c"]), abs(bars[i]["l"]-bars[i-1]["c"]))
    str_=[0.0]*N; sp=[0.0]*N; sm=[0.0]*N; dx=[None]*N; adx=[None]*N
    if N>n+1:
        str_[n]=sum(tr[1:n+1]); sp[n]=sum(pdm[1:n+1]); sm[n]=sum(mdm[1:n+1])
        for i in range(n+1,N):
            str_[i]=str_[i-1]-str_[i-1]/n+tr[i]; sp[i]=sp[i-1]-sp[i-1]/n+pdm[i]; sm[i]=sm[i-1]-sm[i-1]/n+mdm[i]
        for i in range(n,N):
            if str_[i]>0:
                pdi=100*sp[i]/str_[i]; mdi=100*sm[i]/str_[i]
                dx[i]= 100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi)>0 else 0.0
        first=2*n
        if N>first:
            adx[first]=sum(x for x in dx[n:first] if x is not None)/n
            for i in range(first+1,N):
                if dx[i] is not None and adx[i-1] is not None: adx[i]=(adx[i-1]*(n-1)+dx[i])/n
    ema=[None]*N; k=2/21
    s=None
    for i,b in enumerate(bars):
        s= b["c"] if s is None else s+k*(b["c"]-s)
        if i>=19: ema[i]=s
    return adx, ema

def build_from_touch(bars, t, trig_start):
    """Entry next bar at touch high x1.001; stop touch low; target = max high
    trig_start..t; exits: stop (incl. entry bar), target, close of session 10."""
    n=len(bars); e=t+1
    if e>=n: return None
    entry=bars[t]["h"]*1.001; stop=bars[t]["l"]; target=max(b["h"] for b in bars[trig_start:t+1])
    if bars[e]["h"]<entry: return None
    cap=min(e+9, n-1)
    for k in range(e, cap+1):
        if bars[k]["l"]<=stop: return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=stop, exit_reason="stop")
        if bars[k]["h"]>=target: return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=target, exit_reason="target")
    return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=cap, exit_px=bars[cap]["c"], exit_reason="time")

def gen(bars):
    adx, ema = adx_ema(bars)
    trades=[]; armed=False; trig=None; below=True
    for t in range(1, len(bars)):
        if adx[t] is None or ema[t] is None: continue
        cond = adx[t]>30 and adx[t-1] is not None and adx[t]>adx[t-1]
        if adx[t]<30: below=True
        if below and cond and not armed:
            armed=True; trig=t; below=False
        elif armed:
            if bars[t]["l"]<=ema[t]:
                tr=build_from_touch(bars, t, trig)
                if tr: trades.append(tr)
                armed=False
            elif not cond and adx[t]<=30:
                armed=False
    return trades, adx, ema

ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
CROADS={"FULL":(None,"2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
out={"family":"hunt-raschke-holy-grail","assets":{}}
def run_asset(bars, cost, fee, roads, label):
    trades, adx, ema = gen(bars)
    res={}
    for rn,(a,b) in roads.items():
        w0,w1=window_idx(bars,a or bars[0]["d"],b); r={}
        for fl_name, fl in [("NATIVE",False),("V9",True)]:
            f,curve,done,dd,stop=simulate(bars,trades,cost,fee,floor=fl,w0=w0,w1=w1)
            r[fl_name]=dict(final=f, n_trades=len(done), max_dd=dd, stopped=stop,
                win_rate=round(sum(1 for x in done if x["ret"]>0)/len(done),3) if done else None,
                curve=curve, monthly=monthly_stats(curve), trades=done)
        r["BH_bar"]=bh(bars,w0,w1,cost,fee)
        finals=[]
        for s in range(20):
            rng=random.Random(6000+s); ptr=[]
            for tr in trades:
                t=tr["entry_i"]-1+rng.choice([-1,1])*rng.randint(30,250)
                if 20<=t<len(bars)-2:
                    lo=max(0,t-60)
                    nt=build_from_touch(bars,t,lo)
                    if nt: ptr.append(nt)
            f,_,_,_,_=simulate(bars,ptr,cost,fee,w0=w0,w1=w1); finals.append(f)
        r["placebo_finals"]=finals; r["placebo_beaten"]=sum(1 for x in finals if r["NATIVE"]["final"]>x)
        res[rn]=r; print(label, rn, "NAT", r["NATIVE"]["final"], "V9", r["V9"]["final"], "BH", r["BH_bar"], "ntr", r["NATIVE"]["n_trades"], "plbeat", r["placebo_beaten"])
    out["assets"][label]=res
run_asset(load_spy(), 0.001, 0.01, ROADS, "SPY")
run_asset(load_coin("BTC"), 0.006, 0.0, CROADS, "BTC")
run_asset(load_coin("ETH"), 0.006, 0.0, CROADS, "ETH")
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
