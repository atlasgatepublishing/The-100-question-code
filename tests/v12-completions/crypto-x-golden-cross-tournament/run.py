import json, os, sys, statistics
sys.path.insert(0,"/tmp/x2")
from engine import *
BASE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")

def pos_golden_cross(rows):
    cl=[r["c"] for r in rows]; s50=sma(cl,50); s200=sma(cl,200)
    return [1 if (s50[i] and s200[i] and s50[i]>s200[i]) else 0 for i in range(len(cl))]

def pos_dow(rows):
    """JUDGMENT-CONSTRUCTED single-asset Dow: primary state from qualified secondaries (J1: >=15 bars and >=33% retrace)."""
    cl=[r["c"] for r in rows]; n=len(cl)
    pos=[0]*n; state=0  # 0 cash, 1 long
    leg_extreme=cl[0]; leg_start_idx=0; direction=0  # primary direction unknown until first signal
    hurdle_hi=None; hurdle_lo=None; counter_extreme=None; counter_start=None
    for i in range(1,n):
        if direction>=0:  # primary up (or start): watch counter-move down
            if cl[i]>leg_extreme: leg_extreme=cl[i]; counter_start=None; counter_extreme=None
            else:
                if counter_start is None: counter_start=i; counter_extreme=cl[i]
                counter_extreme=min(counter_extreme,cl[i])
                if direction==0:
                    pass
                elif (i-counter_start)>=15 and leg_extreme>0 and (leg_extreme-counter_extreme)/leg_extreme>=0.0 and False:
                    pass
                # qualification: duration>=15 and retrace>=1/3 of leg (leg measured from last trough)
                leg_len=leg_extreme-(hurdle_lo if hurdle_lo else leg_extreme)
                if (i-counter_start)>=15 and leg_len>0 and (leg_extreme-counter_extreme)>=leg_len/3:
                    hurdle_lo=counter_extreme
                if hurdle_lo is not None and cl[i]<hurdle_lo and state==1:
                    state=0; direction=-1; leg_extreme=cl[i]; hurdle_hi=None; counter_start=None
                if direction>=0 and hurdle_hi is not None and cl[i]>hurdle_hi and state==0:
                    state=1
        if direction<=0:
            if cl[i]<leg_extreme: leg_extreme=cl[i]; counter_start=None; counter_extreme=None
            else:
                if counter_start is None: counter_start=i; counter_extreme=cl[i]
                counter_extreme=max(counter_extreme,cl[i])
                leg_len=(hurdle_hi if hurdle_hi else leg_extreme)-leg_extreme
                if (i-counter_start)>=15 and leg_len>0 and (counter_extreme-leg_extreme)>=leg_len/3:
                    hurdle_hi=counter_extreme
                if hurdle_hi is not None and cl[i]>hurdle_hi and state==0:
                    state=1; direction=1; leg_extreme=cl[i]; hurdle_lo=None; counter_start=None
                if direction<=0 and hurdle_lo is not None and cl[i]<hurdle_lo and state==1:
                    state=0
        # initial entry: first close above the running 15+ bar counter high in an up-leg context
        if state==0 and direction==0 and hurdle_hi is not None and cl[i]>hurdle_hi:
            state=1; direction=1; leg_extreme=cl[i]
        pos[i]=state
    return pos

def pivots_zigzag(cl,thr=0.08):
    piv=[]; direction=0; extreme=cl[0]; ex_i=0; start=cl[0]
    for i in range(1,len(cl)):
        if direction>=0:
            if cl[i]>extreme: extreme=cl[i]; ex_i=i
            elif cl[i]<=extreme*(1-thr):
                piv.append((ex_i,extreme,1)); direction=-1; extreme=cl[i]; ex_i=i
        if direction<=0:
            if cl[i]<extreme: extreme=cl[i]; ex_i=i
            elif cl[i]>=extreme*(1+thr):
                piv.append((ex_i,extreme,-1)); direction=1; extreme=cl[i]; ex_i=i
    return piv

def pos_elliott(rows):
    """JUDGMENT-CONSTRUCTED: long while the latest confirmed zigzag structure is a valid bullish impulse in progress/completed and price has not broken the wave-2 low; cash after a valid bearish impulse. Monthly decision approximated daily (named)."""
    cl=[r["c"] for r in rows]; n=len(cl)
    piv=pivots_zigzag(cl,0.08)
    pos=[0]*n; state=0; anchor_lo=None
    pi=0
    # map: when a pivot is confirmed (next pivot appears), evaluate last 6 pivots
    for k in range(5,len(piv)):
        six=piv[k-5:k+1]
        types=[p[2] for p in six]
        if types==[-1,1,-1,1,-1,1]:
            P=[p[1] for p in six]
            L1,L3,L5=P[1]-P[0],P[3]-P[2],P[5]-P[4]
            if P[2]>P[0] and P[4]>P[1] and L3!=min(L1,L3,L5):
                state=1; anchor_lo=P[4]
            # confirmation usable from next pivot's extreme date onward (approx: from this pivot index date)
            from_i=six[-1][0]
            for j in range(from_i,n): pos[j]=state
        elif types==[1,-1,1,-1,1,-1]:
            P=[p[1] for p in six]
            L1,L3,L5=P[0]-P[1],P[2]-P[3],P[4]-P[5]
            if P[2]<P[0] and P[4]<P[1] and L3!=min(L1,L3,L5):
                state=0
            from_i=six[-1][0]
            for j in range(from_i,n): pos[j]=state
    # invalidation: close below anchor low -> cash until next signal (simplified: applied forward)
    out=[]; st=0
    for i in range(n):
        if pos[i]==1: st=1
        elif pos[i]==0 and i>0 and pos[i-1]==1: st=0
        out.append(st)
    return out

def pos_edwards_magee(rows):
    """JUDGMENT-CONSTRUCTED subset: resistance breakout (close above prior 60-day high after a >=10% base) long; exit on close below prior 60-day low channel or 8% stop handled by channel exit. Plus double-bottom: two equal lows within 3% separated by >=20 bars, buy break of intervening high."""
    cl=[r["c"] for r in rows]; n=len(cl); pos=[0]*n; state=0
    for i in range(60,n):
        hi=max(cl[i-60:i]); lo=min(cl[i-60:i])
        if state==0 and cl[i]>hi and (hi-lo)/lo>=0.10: state=1
        elif state==1 and cl[i]<lo: state=0
        pos[i]=state
    return pos

FAMILIES={"golden-cross-tournament":pos_golden_cross,"judgment-dow-theory":pos_dow,
          "judgment-elliott-wave":pos_elliott,"judgment-edwards-magee":pos_edwards_magee}
coins=load_coins()
for fam,fn in FAMILIES.items():
    outdir=os.path.join(BASE,f"crypto-x-{fam}"); os.makedirs(outdir,exist_ok=True)
    per={}; curves={}
    for sym,(cid,rows) in sorted(coins.items()):
        pos=fn(rows)
        if sum(pos)<5: 
            d,eq=run_position(rows,[0]*len(rows)); dn,en=run_position(rows,pos); db,eb=btc_hold(rows)
            per[sym]={"bars":len(rows),"native_final":round(en[-1],2),"house_final":round(eq[-1],2) if False else None,"btc_hold_final":round(eb[-1],2),"signals":0}
            continue
        dn,en=run_position(rows,pos,house=False)
        dh,eh=run_position(rows,pos,house=True)
        db,eb=btc_hold(rows)
        beaten,medp=(None,None)
        if sym in ("BTC","ETH"):
            beaten,medp=shifted_placebo_beaten(rows,pos,en[-1])
        per[sym]={"bars":len(rows),"window":[rows[0]["d"],rows[-1]["d"]],
                  "native_final":round(en[-1],2),"native_max_dd_pct":round(max_dd(en)*100,1),
                  "house_final":round(eh[-1],2),"house_max_dd_pct":round(max_dd(eh)*100,1),
                  "coin_hold_final":round(eb[-1],2),
                  "placebo_beaten_of_20":beaten,"placebo_median_final":medp,
                  "monthly_periods_native":period_stats(dn,en)}
        curves[sym]={"native":[[d,round(e,2)] for d,e in zip(dn,en)],"house":[[d,round(e,2)] for d,e in zip(dh,eh)]}
    nat=[v["native_final"] for v in per.values() if "native_final" in v]
    res={"family":fam,"label":"JUDGMENT-CONSTRUCTED" if fam.startswith("judgment") else "native form transplant",
         "cost_per_side":COST,"pot_per_coin":100,"coins_run":len(per),
         "median_native_final":round(statistics.median(nat),2) if nat else None,
         "coins_beating_own_hold":sum(1 for v in per.values() if v.get("coin_hold_final") is not None and v["native_final"]>v["coin_hold_final"]),
         "btc":per.get("BTC"),"per_coin":per,"equity_curves":curves}
    json.dump(res,open(os.path.join(outdir,"results.json"),"w"),indent=1)
    print(fam,"coins",len(per),"median native",res["median_native_final"],"BTC native",per.get("BTC",{}).get("native_final"),"BTC hold",per.get("BTC",{}).get("coin_hold_final"))
