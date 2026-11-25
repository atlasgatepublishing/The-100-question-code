import json, os, sys, statistics
sys.path.insert(0,"/tmp/x2")
from engine import *
BASE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")

def trade_sim(rows,trades,house=False):
    """trades: list of (entry_idx, exit_idx) executed at open of idx. Full-equity single position, sequential."""
    cash=100.0; eqmap={}
    ti=0; trades=sorted(trades)
    floor=85.0; halts=0; cash_until=-1; end_idx=len(rows)-1
    pos=None
    curve=[]
    for i,r in enumerate(rows):
        if pos is None and ti<len(trades) and trades[ti][0]==i:
            if not (house and (i<cash_until or halts>=2)):
                pos=(r["o"],trades[ti][1]); ti+=1
            else:
                ti+=1
        val = cash*(r["c"]/pos[0]) if pos else cash
        if pos and i>=pos[1]:
            cash=cash*(rows[pos[1]]["o"]/pos[0])*(1-COST)*(1-COST) if False else cash
            # exit at open of exit idx: recompute properly below
            pos=None
        curve.append(val)
    return curve
# The above skeleton is error-prone; implement cleanly:
def simulate(rows,signals,house=False):
    """signals: function(i, rows, state)-> trade intent handled by caller-specific logic; here generic event list approach:
    events: list of dicts {entry:i, exit_fn} too complex. Use per-family loops instead."""
    pass

def run_events(rows,events,house=False):
    """events: sorted list of (entry_idx, exit_idx, entry_price_ref='o', exit_price_ref='o'). Sequential, skip overlapping."""
    n=len(rows); cash=100.0; curve=[100.0]*n; busy_until=-1
    floor=85.0; halts=0; cash_until=-1; halted_end=False
    active=None
    ev=sorted(events)
    ei=0
    for i in range(n):
        if active is None and ei<len(ev) and ev[ei][0]==i:
            e,x=ev[ei]; ei+=1
            if house and (i<cash_until or halts>=2): continue
            active=(e,x,cash)
        if active is not None:
            e,x,amt=active
            val=amt*(rows[i]["c"]/rows[e]["o"])
            curve[i]=val
            if i>=x:
                cash=amt*(rows[x]["o"]/rows[e]["o"])*(1-COST)**2
                curve[i]=cash; active=None
        else:
            curve[i]=cash
        if house and halts<2 and curve[i]<=floor:
            if active is not None:
                e,x,amt=active; cash=amt*(rows[i]["c"]/rows[e]["o"])*(1-COST)**2; curve[i]=cash; active=None
            halts+=1
            if halts==1: cash_until=i+90; floor=0.85*cash
            else: cash_until=n+10**9
    if active is not None:
        e,x,amt=active; curve[-1]=amt*(rows[-1]["c"]/rows[e]["o"])*(1-COST)
    return [r["d"] for r in rows], curve

def zigzag_pivots(cl,thr=0.08):
    piv=[]; direction=0; extreme=cl[0]; ex_i=0
    conf=[]
    for i in range(1,len(cl)):
        if direction>=0:
            if cl[i]>extreme: extreme=cl[i]; ex_i=i
            elif cl[i]<=extreme*(1-thr):
                piv.append((ex_i,extreme,1)); conf.append(i); direction=-1; extreme=cl[i]; ex_i=i
        if direction<=0:
            if cl[i]<extreme: extreme=cl[i]; ex_i=i
            elif cl[i]>=extreme*(1+thr):
                piv.append((ex_i,extreme,-1)); conf.append(i); direction=1; extreme=cl[i]; ex_i=i
    return piv,conf

def gartley_events(rows):
    cl=[r["c"] for r in rows]; n=len(cl)
    piv,conf=zigzag_pivots(cl,0.08)
    events=[]
    for k in range(3,len(piv)):
        # bullish: X low, A high, B low, C high ; pivots known at conf[k]
        (xi,X,xt),(ai,A,at),(bi,B,bt),(ci,C,ct)=piv[k-3],piv[k-2],piv[k-1],piv[k]
        if not (xt==-1 and at==1 and bt==-1 and ct==1): continue
        if A<=X: continue
        bret=(A-B)/(A-X)
        if not (0.588<=bret<=0.648): continue
        cret=(C-B)/(A-B) if A>B else 0
        if not (0.382<=cret<=0.886): continue
        D=X+0.214*(A-X)  # 78.6% retracement level: D = A - 0.786*(A-X)
        D=A-0.786*(A-X)
        start=conf[k]
        entry=None
        for i in range(start,n-1):
            if cl[i]<X: break
            if cl[i]<=D: entry=i+1; break
        if entry is None or entry>=n: continue
        # exits: target2 61.8% of AD first (single-position pot: exit all at T2, partials noted), stop below X, no time exit (native)
        t2=D+0.618*(A-D); exit_i=n-1
        for i in range(entry,n):
            if cl[i]<X: exit_i=min(i+1,n-1); break
            if cl[i]>=t2: exit_i=min(i+1,n-1); break
        events.append((entry,exit_i))
    return events

def rsi2(cl):
    out=[50.0]*len(cl)
    for i in range(2,len(cl)):
        gains=0;loss=0
        for j in (i-1,i):
            d=cl[j]-cl[j-1]
            if d>0: gains+=d
            else: loss-=d
        if loss==0: out[i]=100.0
        elif gains==0: out[i]=0.0
        else: out[i]=100-100/(1+(gains/2)/(loss/2))
    return out

def hwr_events(rows,shape):
    cl=[r["c"] for r in rows]; op=[r["o"] for r in rows]; n=len(cl)
    s200=sma(cl,200); s20=sma(cl,20); r2=rsi2(cl)
    events=[]; i=200
    while i<n-1:
        entry=None; exit_i=None
        if shape=="H1":
            if r2[i]<10 and s200[i] and cl[i]>s200[i]:
                entry=i+1; ep=op[entry]; exit_i=min(entry+5,n-1)
                for j in range(entry,min(entry+6,n)):
                    if cl[j]>=ep*1.02 or cl[j]<=ep*0.94: exit_i=min(j+1,n-1); break
        elif shape=="H2":
            if s20[i]:
                sd=(sum((cl[j]-s20[i])**2 for j in range(i-19,i+1))/20)**0.5
                lb=s20[i]-2*sd
                if cl[i]<lb and s200[i] and cl[i]>s200[i]:
                    entry=i+1; ep=op[entry]; exit_i=min(entry+10,n-1)
                    for j in range(entry,min(entry+11,n)):
                        m=sma(cl[:j+1],20)[j]
                        if (m and cl[j]>=m) or cl[j]<=ep*0.93: exit_i=min(j+1,n-1); break
        elif shape=="H3":
            if i>=3 and cl[i]<cl[i-1]<cl[i-2] and (cl[i]/cl[i-3]-1)<=-0.04 and s200[i] and cl[i]>s200[i]:
                entry=i+1; ep=op[entry]; exit_i=min(entry+4,n-1)
                for j in range(entry,min(entry+5,n)):
                    if cl[j]>=ep*1.025 or cl[j]<=ep*0.94: exit_i=min(j+1,n-1); break
        elif shape=="H4":
            if i>=252 and cl[i]>max(cl[i-252:i]):
                entry=i+1; ep=op[entry]; exit_i=n-1
                for j in range(entry,n):
                    m=sma(cl[:j+1],20)[j]
                    if cl[j]>=ep*1.04 or cl[j]<=ep*0.88 or (m and cl[j]<m): exit_i=min(j+1,n-1); break
        if entry is not None:
            events.append((entry,exit_i)); i=exit_i+1
        else: i+=1
    return events

def gap_events(rows):
    """CONSTRUCTED 24/7 analogue: daily bar up >=10% vs prior close = 'gap'; enter next open; stop -8%, target +16%, time exit 5 days."""
    cl=[r["c"] for r in rows]; op=[r["o"] for r in rows]; n=len(cl); events=[]; i=1
    while i<n-1:
        if cl[i]/cl[i-1]-1>=0.10:
            entry=i+1; ep=op[entry]; exit_i=min(entry+5,n-1)
            for j in range(entry,min(entry+6,n)):
                if cl[j]>=ep*1.16 or cl[j]<=ep*0.92: exit_i=min(j+1,n-1); break
            events.append((entry,exit_i)); i=exit_i+1
        else: i+=1
    return events

coins=load_coins()
FAMS={"folklore-f10-gartley":("gartley",None),"gap-up-continuation":("gap",None),
      "high-winrate-lab":("hwr",None)}
for fam,(kind,_) in FAMS.items():
    outdir=os.path.join(BASE,f"crypto-x-{fam}"); os.makedirs(outdir,exist_ok=True)
    per={}; curves={}
    shapes=["H1","H2","H3","H4"] if kind=="hwr" else [None]
    agg={}
    for shape in shapes:
        key=shape or fam; per[key]={}; finals=[]
        for sym,(cid,rows) in sorted(coins.items()):
            ev=gartley_events(rows) if kind=="gartley" else gap_events(rows) if kind=="gap" else hwr_events(rows,shape)
            if not ev: continue
            dn,en=run_events(rows,ev,house=False); dh,eh=run_events(rows,ev,house=True)
            db,eb=btc_hold(rows)
            per[key][sym]={"trades":len(ev),"native_final":round(en[-1],2),"native_max_dd_pct":round(max_dd(en)*100,1),
                           "house_final":round(eh[-1],2),"coin_hold_final":round(eb[-1],2),
                           "monthly_periods_native":period_stats(dn,en)}
            finals.append(en[-1])
            if sym=="BTC": curves[key]={"native":[[d,round(e,2)] for d,e in zip(dn,en)],"house":[[d,round(e,2)] for d,e in zip(dh,eh)]}
        agg[key]={"coins_with_trades":len(per[key]),"median_native_final":round(statistics.median(finals),2) if finals else None,
                  "btc":per[key].get("BTC")}
    res={"family":fam,"cost_per_side":COST,"pot_per_coin":100,"summary":agg,"per_coin":per,"btc_curves":curves}
    json.dump(res,open(os.path.join(outdir,"results.json"),"w"),indent=1)
    print(fam,agg)
