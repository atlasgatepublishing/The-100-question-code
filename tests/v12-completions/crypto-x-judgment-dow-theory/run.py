import json, os, sys, statistics
sys.path.insert(0,"/tmp/x2")
from engine import *
BASE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
def pos_dow(rows):
    """JUDGMENT-CONSTRUCTED single-asset Dow (Hamilton J1): zigzag 5% pivots confirmed in real time.
    A counter-move qualifies as secondary when it lasts >=15 bars AND retraces >=1/3 of the prior leg;
    only a qualified secondary's extreme becomes a hurdle. Long on close above the qualified hurdle high,
    cash on close below the qualified hurdle low."""
    cl=[r["c"] for r in rows]; n=len(cl)
    # build pivots with confirmation dates
    piv=[]; direction=0; extreme=cl[0]; ex_i=0
    for i in range(1,n):
        if direction>=0:
            if cl[i]>extreme: extreme=cl[i]; ex_i=i
            elif cl[i]<=extreme*0.95: piv.append([ex_i,extreme,1,i]); direction=-1; extreme=cl[i]; ex_i=i
        if direction<=0:
            if cl[i]<extreme: extreme=cl[i]; ex_i=i
            elif cl[i]>=extreme*1.05: piv.append([ex_i,extreme,-1,i]); direction=1; extreme=cl[i]; ex_i=i
    pos=[0]*n; state=0; hurdle_hi=None; hurdle_lo=None
    pi=0
    for i in range(n):
        while pi<len(piv) and piv[pi][3]<=i:
            idx,price,typ,conf=piv[pi]
            if pi>=1:
                pidx,pprice,ptyp,_=piv[pi-1]
                dur=idx-pidx
                if pi>=2:
                    leg=abs(piv[pi-1][1]-piv[pi-2][1]); retrace=abs(price-pprice)
                else: leg=0; retrace=0
                if dur>=15 and leg>0 and retrace>=leg/3:
                    if typ==1: hurdle_hi=price
                    else: hurdle_lo=price
            pi+=1
        if state==0 and hurdle_hi is not None and cl[i]>hurdle_hi: state=1
        elif state==1 and hurdle_lo is not None and cl[i]<hurdle_lo: state=0
        pos[i]=state
    return pos
coins=load_coins()
outdir=os.path.join(BASE,"crypto-x-judgment-dow-theory"); os.makedirs(outdir,exist_ok=True)
per={}; curves={}
for sym,(cid,rows) in sorted(coins.items()):
    pos=pos_dow(rows)
    dn,en=run_position(rows,pos,house=False); dh,eh=run_position(rows,pos,house=True); db,eb=btc_hold(rows)
    beaten,medp=(None,None)
    if sym in ("BTC","ETH"): beaten,medp=shifted_placebo_beaten(rows,pos,en[-1])
    per[sym]={"bars":len(rows),"window":[rows[0]["d"],rows[-1]["d"]],"invested_days":int(sum(pos)),
      "native_final":round(en[-1],2),"native_max_dd_pct":round(max_dd(en)*100,1),
      "house_final":round(eh[-1],2),"house_max_dd_pct":round(max_dd(eh)*100,1),
      "coin_hold_final":round(eb[-1],2),"placebo_beaten_of_20":beaten,"placebo_median_final":medp,
      "monthly_periods_native":period_stats(dn,en)}
    curves[sym]={"native":[[d,round(e,2)] for d,e in zip(dn,en)],"house":[[d,round(e,2)] for d,e in zip(dh,eh)]}
nat=[v["native_final"] for v in per.values()]
res={"family":"judgment-dow-theory","label":"JUDGMENT-CONSTRUCTED","cost_per_side":COST,"pot_per_coin":100,
 "coins_run":len(per),"median_native_final":round(statistics.median(nat),2),
 "coins_beating_own_hold":sum(1 for v in per.values() if v["native_final"]>v["coin_hold_final"]),
 "btc":per.get("BTC"),"per_coin":per,"equity_curves":curves}
json.dump(res,open(os.path.join(outdir,"results.json"),"w"),indent=1)
print("dow median",res["median_native_final"],"BTC",per["BTC"]["native_final"],"hold",per["BTC"]["coin_hold_final"],"beat own hold",res["coins_beating_own_hold"])
