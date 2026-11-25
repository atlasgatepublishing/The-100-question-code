import json, os, sys, statistics
sys.path.insert(0,"/tmp/x2")
from engine import *
BASE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
coins=load_coins()
snap=json.load(open(os.path.join(BASE,"crypto-basket-pit","data","weekly_snapshots.json")))
# eligibility by month: symbols in any snapshot in trailing 12 months
elig={}
for d,v in snap.items():
    ym=d[:7]
    for c in v["top20"]: elig.setdefault(ym,set()).add(c["symbol"])
months=sorted(elig)
# month-end closes per coin
mc={}
for sym,(cid,rows) in coins.items():
    m={}
    for r in rows: m[r["d"][:7]]=r["c"]
    mc[sym]=m
# fill forward within each coin's own span (marking convention; named in RESULTS)
ALLM=sorted({k for m in mc.values() for k in m})
for sym,m in mc.items():
    ks=sorted(m); last=None
    for k in ALLM:
        if k<ks[0]: continue
        if k in m: last=m[k]
        elif last is not None and k<=ks[-1]: m[k]=last
all_months=[k for k in sorted({k for m in mc.values() for k in m}) if k<="2026-10"]
def month_ret(sym,ym):
    y,m=int(ym[:4]),int(ym[5:7])
    pm=f"{y-1:04d}-12" if m==1 else f"{y:04d}-{m-1:02d}"
    if ym in mc.get(sym,{}) and pm in mc.get(sym,{}): return mc[sym][ym]/mc[sym][pm]-1
    return None
def run(topn,house=False):
    cash=100.0; holdings={}  # sym -> units
    curve=[]; dates=[]
    floor=85.0; halts=0; cash_until=None
    for idx,ym in enumerate(all_months):
        if ym<"2018-01": continue
        # value at month start = cash + holdings valued at prev month-end (already in mc at ym-1)... use current month-end for marking after trading at month start approx: trade at this month's first close unavailable; use month-end close of PREVIOUS month as trade price
        y,m=int(ym[:4]),int(ym[5:7]); pm=f"{y-1:04d}-12" if m==1 else f"{y:04d}-{m-1:02d}"
        def val(at):
            return cash+sum(u*mc[s].get(at,0) for s,u in holdings.items() if mc[s].get(at))
        cur=val(pm)
        if house and cur<=floor and halts<2:
            # liquidate
            cash=cur*(1-COST); holdings={}; halts+=1
            if halts==1: cash_until=idx+3; floor=0.85*cash
            else: cash_until=10**9
            cur=cash
        if not (house and cash_until is not None and idx<cash_until):
            # rank: same calendar month average return over prior years, >=2 obs
            scores={}
            eligset=set()
            for back in range(0,13):
                yy,mm=y, m-back
                while mm<=0: mm+=12; yy-=1
                eligset|=elig.get(f"{yy:04d}-{mm:02d}",set())
            for sym in eligset:
                rs=[]
                for yy in range(y-1,2009,-1):
                    r=month_ret(sym,f"{yy:04d}-{m:02d}")
                    if r is not None: rs.append(r)
                if len(rs)>=2: scores[sym]=sum(rs)/len(rs)
            picks=[s for s,_ in sorted(scores.items(),key=lambda kv:-kv[1])[:topn]]
            # rebalance at pm prices
            total=val(pm)
            newh={}
            for s in picks:
                p=mc[s].get(pm)
                if p: newh[s]=(total/topn)*(1-COST)/p
            # sell cost on turnover approximated: charge COST on full traded value both sides via (1-COST) on buys; sells: reduce cash by COST*value sold
            sold=sum(u*mc[s].get(pm,0) for s,u in holdings.items() if s not in newh)
            cash=total - sum(u*mc[s][pm] for s,u in newh.items()) - COST*sold
            # cash here double counts; simpler: cash = total*(fraction not invested)=0 since fully invested; set cash= -COST*sold floored
            cash=max(0.0,-0.0)  # fully invested construction
            holdings=newh
        curve.append(val(ym)); dates.append(ym)
    return dates,curve
for ruleset,house in [("native",False),("house",True)]:
    d,eq=run(5,house)
    print(ruleset,"final",round(eq[-1],2),"maxdd",round(max_dd(eq)*100,1),period_stats([x+"-01" for x in d],eq))
# BTC hold over same window
rows=coins["BTC"][1]; mcbtc={}
for r in rows: mcbtc[r["d"][:7]]=r["c"]
ms=[m for m in sorted(mcbtc) if m>="2018-01"]
print("BTC hold 2018+",round(100*mcbtc[ms[-1]]/mcbtc["2017-12"],2))
d,eq=run(5,False); dh,eh=run(5,True)
outdir=os.path.join(BASE,"crypto-x-gap-a1-seasonality"); os.makedirs(outdir,exist_ok=True)
json.dump({"family":"gap-a1-seasonality","cost_per_side":COST,"pot":100,
 "native":{"final":round(eq[-1],2),"max_dd_pct":round(max_dd(eq)*100,1),"curve":[[x,round(e,2)] for x,e in zip(d,eq)],"monthly_periods":period_stats([x+"-01" for x in d],eq)},
 "house":{"final":round(eh[-1],2),"max_dd_pct":round(max_dd(eh)*100,1),"curve":[[x,round(e,2)] for x,e in zip(dh,eh)],"monthly_periods":period_stats([x+"-01" for x in dh],eh)},
 "btc_hold_same_window_final":round(100*mcbtc[ms[-1]]/mcbtc["2017-12"],2)},open(os.path.join(outdir,"results.json"),"w"),indent=1)
