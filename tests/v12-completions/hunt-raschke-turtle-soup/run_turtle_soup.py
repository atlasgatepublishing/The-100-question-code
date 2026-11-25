#!/usr/bin/env python3
"""hunt-raschke-turtle-soup — frozen SPEC-FROZEN.md. FORM A: new 20-day low,
previous 20-day low >=4 sessions ago, buy stop next session at old low x1.001
(NAMED DEVIATION: literal rule is same-day intraday; daily translation arms
next session — HURTS). Stop = signal-day low x0.999. Exit CONSTRUCTED: trail
at 2-session lowest low once >=1R profit; hard exit close of session 5.
Re-entry once if stopped on day 1/2, at original entry, those days only.
FORM B (Plus One): entry on day 2 at prior 20-day low level, stop day-1 low.
Long side only (long-only chassis). Placebos: anchor-date shifts, 20 seeds.
Simulation only."""
import json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from raschke_common import load_spy, load_coin, simulate, monthly_stats, window_idx, bh
HERE=os.path.dirname(os.path.abspath(__file__))

def find_signals(bars):
    sig=[]
    last_low_bar=None; last_low_val=None
    for t in range(19, len(bars)):
        w=min(b["l"] for b in bars[t-19:t+1])
        if bars[t]["l"]<=w:  # new 20-day low today
            if last_low_bar is not None and t-last_low_bar>=4:
                sig.append((t, last_low_val))
            last_low_bar=t; last_low_val=bars[t]["l"]
    return sig

def build_trade(bars, t, old_low, form):
    n=len(bars)
    if form=="A": e=t+1
    else: e=t+2
    if e>=n: return None
    entry=old_low*1.001; stop=bars[t]["l"]*0.999
    if bars[e]["h"]<entry: return None
    def run_leg(e, entry, stop, cap_end):
        R=entry-stop
        if R<=0: return None
        trail=None
        for k in range(e, min(cap_end, n-1)+1):
            if bars[k]["l"]<=stop:
                return ("stop", k, stop)
            if trail is not None and k>e and bars[k]["l"]<=trail:
                return ("trail", k, trail)
            if bars[k]["h"]>=entry+R and k>=e:
                trail=min(bars[k-1]["l"], bars[k]["l"]) if k>=1 else bars[k]["l"]
        k=min(cap_end, n-1)
        return ("time", k, bars[k]["c"])
    cap=e+4
    r=run_leg(e, entry, stop, cap)
    if r is None: return None
    reason, xi, xp = r
    if reason=="stop" and xi-e<=1:
        # one re-entry on following bar if within day1/2 window
        e2=xi+1
        if e2<=e+2 and e2<n and bars[e2]["h"]>=entry:
            r2=run_leg(e2, entry, stop, cap)
            if r2: reason, xi, xp = "reentry-"+r2[0], r2[1], r2[2]
    return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=xi, exit_px=xp, exit_reason=reason)

def gen(bars, form):
    return [tr for tr in (build_trade(bars,t,ol,form) for t,ol in find_signals(bars)) if tr]

ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
CROADS={"FULL":(None,"2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
out={"family":"hunt-raschke-turtle-soup","assets":{}}
def run_asset(bars, cost, fee, roads, label):
    res={}
    for form in ["A","B"]:
        trades=gen(bars, form); res[form]={}
        sigs=find_signals(bars)
        for rn,(a,b) in roads.items():
            w0,w1=window_idx(bars,a or bars[0]["d"],b)
            r={}
            for fl_name, fl in [("NATIVE",False),("V9",True)]:
                f,curve,done,dd,stop=simulate(bars,trades,cost,fee,floor=fl,w0=w0,w1=w1)
                r[fl_name]=dict(final=f, n_trades=len(done), max_dd=dd, stopped=stop,
                    win_rate=round(sum(1 for x in done if x["ret"]>0)/len(done),3) if done else None,
                    curve=curve, monthly=monthly_stats(curve), trades=done)
            r["BH_bar"]=bh(bars,w0,w1,cost,fee)
            # placebos: shift anchors
            finals=[]
            for s in range(20):
                rng=random.Random(5000+s); off=rng.choice([-1,1])*rng.randint(30,250)
                ptr=[]
                for t,ol in sigs:
                    t2=t+off
                    if t2<len(bars)-2:
                        # recompute prior 20-day low at the shifted anchor
                        ol2=None; j=t2-1
                        while j>=19:
                            if bars[j]["l"]<=min(x["l"] for x in bars[j-19:j+1]): ol2=bars[j]["l"]; break
                            j-=1
                        if ol2 is None: continue
                        tr=build_trade(bars,t2,ol2,form)
                        if tr: ptr.append(tr)
                f,_,_,_,_=simulate(bars,ptr,cost,fee,w0=w0,w1=w1)
                finals.append(f)
            r["placebo_finals"]=finals
            r["placebo_beaten"]=sum(1 for x in finals if r["NATIVE"]["final"]>x)
            res[form][rn]=r
    out["assets"][label]=res
    for form in ["A","B"]:
        for rn in roads: 
            r=res[form][rn]; print(label, form, rn, "NAT", r["NATIVE"]["final"], "V9", r["V9"]["final"], "BH", r["BH_bar"], "ntr", r["NATIVE"]["n_trades"], "plbeat", r["placebo_beaten"])
run_asset(load_spy(), 0.001, 0.01, ROADS, "SPY")
run_asset(load_coin("BTC"), 0.006, 0.0, CROADS, "BTC")
run_asset(load_coin("ETH"), 0.006, 0.0, CROADS, "ETH")
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
