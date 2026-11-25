#!/usr/bin/env python3
"""hunt-raschke-anti — frozen SPEC-FROZEN.md. 3/10 oscillator: Fast =
SMA3(c)-SMA10(c); Slow = SMA16(Fast). Armed when Slow crosses above 0.
First Fast<=Slow touch after being above = pullback bar. Entry next session
buy stop at pullback-bar high x1.001 (CONSTRUCTED tick). Stop = lowest low
from the pre-pullback Fast-peak bar through the pullback bar, x0.999.
Exit CONSTRUCTED: close on first bar where Fast makes a new 20-bar high
after entry; hard cap 10 sessions. Entry bar breaching stop = stopped.
Only the FIRST Anti per trend (later re-entries are the book's lower-quality
Anti Trap, not frozen). Long only. Placebos: pullback-bar date shifts.
Simulation only."""
import json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from raschke_common import load_spy, load_coin, simulate, monthly_stats, window_idx, bh
HERE=os.path.dirname(os.path.abspath(__file__))

def osc(bars):
    c=[b["c"] for b in bars]; N=len(bars)
    def sma(x,n):
        out=[None]*N; s=0.0
        for i,v in enumerate(x):
            s+=v
            if i>=n: s-=x[i-n]
            if i>=n-1: out[i]=s/n
        return out
    s3=sma(c,3); s10=sma(c,10)
    fast=[None if (a is None or b is None) else a-b for a,b in zip(s3,s10)]
    fv=[v if v is not None else 0.0 for v in fast]
    slow=sma(fv,16)
    for i in range(N):
        if fast[i] is None: slow[i]=None
    return fast, slow

def build(bars, fast, p, peak_bar):
    n=len(bars); e=p+1
    if e>=n: return None
    entry=bars[p]["h"]*1.001
    stop=min(b["l"] for b in bars[peak_bar:p+1])*0.999
    if bars[e]["h"]<entry: return None
    cap=min(e+9, n-1)
    for k in range(e, cap+1):
        if bars[k]["l"]<=stop: return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=stop, exit_reason="stop")
        if k>e and fast[k] is not None and all(fast[j] is not None and fast[k]>=fast[j] for j in range(max(0,k-20),k)):
            return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=bars[k]["c"], exit_reason="push")
    return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=cap, exit_px=bars[cap]["c"], exit_reason="time")

def gen(bars):
    fast, slow = osc(bars)
    trades=[]; armed=False; was_above=False; peak_bar=None; peak_val=None
    for t in range(N0(bars), len(bars)):
        if slow[t] is None or fast[t] is None: continue
        if not armed:
            if slow[t-1] is not None and slow[t-1]<=0<slow[t]:
                armed=True; was_above=False; peak_val=None
        else:
            if slow[t]<=0: armed=False; continue
            if fast[t]>slow[t]:
                if peak_val is None or fast[t]>peak_val: peak_val=fast[t]; peak_bar=t
                was_above=True
            elif was_above and fast[t]<=slow[t]:
                tr=build(bars, fast, t, peak_bar if peak_bar is not None else t)
                if tr: trades.append(tr)
                armed=False  # first Anti only per trend
    return trades, fast, slow
def N0(bars): return 1

ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
CROADS={"FULL":(None,"2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
out={"family":"hunt-raschke-anti","assets":{}}
def run_asset(bars, cost, fee, roads, label):
    trades, fast, slow = gen(bars); res={}
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
            rng=random.Random(7000+s); ptr=[]
            for tr in trades:
                p=tr["entry_i"]-1+rng.choice([-1,1])*rng.randint(30,250)
                if 30<=p<len(bars)-2:
                    pk=max(0,p-10)
                    nt=build(bars,fast,p,pk)
                    if nt: ptr.append(nt)
            f,_,_,_,_=simulate(bars,ptr,cost,fee,w0=w0,w1=w1); finals.append(f)
        r["placebo_finals"]=finals; r["placebo_beaten"]=sum(1 for x in finals if r["NATIVE"]["final"]>x)
        res[rn]=r; print(label, rn, "NAT", r["NATIVE"]["final"], "V9", r["V9"]["final"], "BH", r["BH_bar"], "ntr", r["NATIVE"]["n_trades"], "plbeat", r["placebo_beaten"])
    out["assets"][label]=res
run_asset(load_spy(), 0.001, 0.01, ROADS, "SPY")
run_asset(load_coin("BTC"), 0.006, 0.0, CROADS, "BTC")
run_asset(load_coin("ETH"), 0.006, 0.0, CROADS, "ETH")
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
