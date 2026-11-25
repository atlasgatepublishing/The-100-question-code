"""Shared loaders + trade simulator for the Raschke hunt families.
One position at a time, $100 pot, all-in. Costs: SPY-class stocks
0.10%/side + $0.01 sell fee; crypto 0.60%/side. V9 = plain -15% floor
from $100 on daily close marks (liquidate at close, end). Simulation only."""
import json, os, time, statistics as st

def load_spy():
    p=os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
    j=json.load(open(p)); r=j["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    adj=r["indicators"]["adjclose"][0]["adjclose"]; bars=[]
    for i,t in enumerate(ts):
        if None in (q["open"][i],q["high"][i],q["low"][i],q["close"][i],adj[i]): continue
        k=adj[i]/q["close"][i]
        bars.append({"d":time.strftime("%Y-%m-%d",time.gmtime(t)),"o":q["open"][i]*k,"h":q["high"][i]*k,"l":q["low"][i]*k,"c":adj[i]})
    bars.sort(key=lambda b:b["d"]); return bars

def load_coin(sym):
    p=os.path.expanduser(f"~/workspace/stock-app/backtests/v4/crypto-trend-data/{sym}-USD.csv")
    bars=[]
    with open(p) as f:
        next(f)
        for line in f:
            x=line.strip().split(",")
            if len(x)<5: continue
            bars.append({"d":x[0],"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4])})
    bars.sort(key=lambda b:b["d"]); return bars

def simulate(bars, trades, cost, sell_fee=0.0, floor=False, w0=0, w1=None):
    """trades: dicts entry_i, entry_px, stop_px, exit_i, exit_px, exit_reason.
    Stop (intraday low) takes precedence on bars after the entry bar; on the
    entry bar the generator sets stop_ok=False if the frozen convention scores
    same-bar stop-through at entry (handled by generator exit choice)."""
    if w1 is None: w1=len(bars)-1
    eq=100.0; curve=[(bars[w0]["d"],eq)]; peak=eq; maxdd=0.0; done=[]; active=None
    trades=sorted([t for t in trades if w0<=t["entry_i"]<=w1], key=lambda t:t["entry_i"])
    ti=0
    for i in range(w0, w1+1):
        b=bars[i]
        if active is None and ti<len(trades) and trades[ti]["entry_i"]==i:
            t=trades[ti]; ti+=1
            active=dict(sh=eq*(1-cost)/t["entry_px"], **t)
        if active is not None:
            if i>active["entry_i"] and b["l"]<=active["stop_px"]:
                eq=active["sh"]*active["stop_px"]*(1-cost)-sell_fee
                done.append({"entry_d":bars[active["entry_i"]]["d"],"exit_d":b["d"],"reason":"stop","ret":round(active["stop_px"]/active["entry_px"]-1,4)})
                active=None
            elif i>=active["exit_i"]:
                eq=active["sh"]*active["exit_px"]*(1-cost)-sell_fee
                done.append({"entry_d":bars[active["entry_i"]]["d"],"exit_d":b["d"],"reason":active.get("exit_reason","exit"),"ret":round(active["exit_px"]/active["entry_px"]-1,4)})
                active=None
        mark=active["sh"]*b["c"] if active else eq
        peak=max(peak,mark); maxdd=min(maxdd,mark/peak-1)
        curve.append((b["d"],round(mark,4)))
        if floor and mark<=85.0:
            if active: eq=active["sh"]*b["c"]*(1-cost)-sell_fee
            else: eq=mark
            curve[-1]=(b["d"],round(eq,4))
            return round(eq,2),curve,done,round(maxdd,4),b["d"]
    if active:
        eq=active["sh"]*bars[w1]["c"]*(1-cost)-sell_fee
        done.append({"entry_d":bars[active["entry_i"]]["d"],"exit_d":bars[w1]["d"],"reason":"window-end","ret":round(bars[w1]["c"]/active["entry_px"]-1,4)})
        curve[-1]=(bars[w1]["d"],round(eq,4))
    return round(eq,2),curve,done,round(maxdd,4),None

def monthly_stats(curve):
    marks={}
    for d,e in curve: marks[d[:7]]=e
    ks=sorted(marks); rets=[marks[b]/marks[a]-1 for a,b in zip(ks,ks[1:])]
    if not rets: return {}
    streak=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    peak=-1; last=0; longest=0
    for i,k in enumerate(ks):
        if marks[k]>=peak: peak=marks[k]; last=i
        longest=max(longest,i-last)
    return dict(periods=len(rets),share_positive=round(sum(1 for r in rets if r>0)/len(rets),3),
        median=round(st.median(rets),4),best=round(max(rets),4),worst=round(min(rets),4),
        mean_secondary=round(st.mean(rets),4),longest_losing_streak=streak,
        longest_between_highs_months=longest)

def window_idx(bars, a, b):
    idx=[i for i,x in enumerate(bars) if (a is None or x["d"]>=a) and x["d"]<=b]
    return idx[0], idx[-1]

def bh(bars, w0, w1, cost, sell_fee=0.0):
    return round(100.0*(1-cost)*(bars[w1]["c"]/bars[w0]["c"])*(1-cost)-sell_fee*(bars[w1]["c"]/bars[w0]["c"]),2)
