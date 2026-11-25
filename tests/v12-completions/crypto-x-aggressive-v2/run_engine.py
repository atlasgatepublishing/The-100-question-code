#!/usr/bin/env python3
"""V12 crypto cross-run slice X1 engine. Closes/opens cache (v4, read-only).
Translations frozen in each family's RESULTS.md. Costs 0.60%/side."""
import json, os, glob, math, random, statistics
from datetime import date, timedelta

BASE = "/home/hatch/workspace/stock-app/backtests"
DATA = os.path.join(BASE, "v4", "crypto-basket-pit-data")
OUT = os.path.join(BASE, "v12-completions")
COST = 0.006
END = "2026-11-20"
PEGGED = {"USDT","USDC","DAI","BUSD","USD1","USDE","USTC"}

def load_series():
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        b = os.path.basename(f)
        if b == "snapshots.json": continue
        rows = json.load(open(f))
        if not rows: continue
        stem = b[:-5]; sym = stem.split("_",1)[1]
        for suf in ("USDT","-USD","USD"):
            if sym.endswith(suf): sym = sym[:-len(suf)]; break
        if sym == "IOTA": sym = "MIOTA"
        rows = [r for r in rows if r["d"] <= END and r["c"] and r["c"]>0 and r["o"] and r["o"]>0]
        if not rows: continue
        if sym in out and len(out[sym][0]) >= len(rows): continue
        out[sym] = ([r["d"] for r in rows],[float(r["o"]) for r in rows],[float(r["c"]) for r in rows], b)
    return out

SER = load_series()
SNAPS = json.load(open(os.path.join(DATA,"snapshots.json")))
SNAP_KEYS = sorted(SNAPS.keys())
def pit_members(dstr):
    import bisect
    k = bisect.bisect_right(SNAP_KEYS, dstr)-1
    if k < 0: return []
    return [e["symbol"] for e in SNAPS[SNAP_KEYS[k]]["top20"]]

def sma(c,i,n):
    if i < n-1: return None
    return sum(c[i-n+1:i+1])/n

def maxdd(curve):
    peak=-1; dd=0
    for v in curve:
        peak=max(peak,v); 
        if peak>0: dd=min(dd, v/peak-1)
    return dd

def period_stats(dates, curve, tempo):
    # resample: last equity in each period bucket
    buckets={}
    for d,v in zip(dates,curve):
        if tempo=="monthly": k=d[:7]
        elif tempo=="weekly":
            dt=date.fromisoformat(d); k=f"{dt.isocalendar()[0]}-{dt.isocalendar()[1]:02d}"
        else: k=d
        buckets[k]=v
    vals=list(buckets.values())
    rets=[vals[i]/vals[i-1]-1 for i in range(1,len(vals)) if vals[i-1]>0]
    if not rets: return {}
    los=0; ml=0
    for r in rets:
        los = los+1 if r<0 else 0; ml=max(ml,los)
    peak=-1; under=0; mu=0
    for v in vals:
        if v>=peak: peak=v; under=0
        else: under+=1; mu=max(mu,under)
    return {"periods":len(rets),"pct_profitable":round(100*sum(1 for r in rets if r>0)/len(rets),1),
            "median_pct":round(100*statistics.median(rets),3),"best_pct":round(100*max(rets),2),
            "worst_pct":round(100*min(rets),2),"longest_losing_run":ml,"longest_below_high":mu,
            "average_pct_secondary":round(100*statistics.mean(rets),3)}

# ---------- per-coin schedule simulator ----------
def run_schedule(d,o,c,inv, v9=False):
    """inv[i]=1 means: signal at close i -> hold open[i+1]->open[i+2] segment etc.
    Simplified consistent model: position during day i+1 (open->close and close->next open)
    decided by inv[i]. Equity marked at closes; costs on transitions at opens approx at close."""
    n=len(c); eq=[100.0]; dates=[d[0]]; pos=0; cash=100.0; units=0.0
    # state machine with v9 floors
    ep=1; floor=85.0; restart_bal=None; halted_until=None; ended=False; halts=[]
    equity=100.0
    curve=[100.0]; dts=[d[0]]
    in_pos=False
    for i in range(n-1):
        # decide target from inv[i] (signal at close i), executed at open i+1
        target = inv[i]==1
        if ended: 
            curve.append(cash); dts.append(d[i+1]); continue
        if halted_until is not None:
            if d[i+1] < halted_until:
                curve.append(cash); dts.append(d[i+1]); continue
            else:
                halted_until=None; restart_bal=cash; floor=0.85*cash
        if target and not in_pos:
            # buy at open i+1
            units = cash*(1-COST)/o[i+1]; cash=0.0; in_pos=True; entry_i=i+1
        elif not target and in_pos:
            cash = units*o[i+1]*(1-COST); units=0.0; in_pos=False
        # mark at close i+1
        equity = units*c[i+1] if in_pos else cash
        if v9 and equity <= floor:
            # liquidate at next open if possible
            if in_pos:
                px = o[i+2] if i+2<n else c[i+1]
                cash = units*px*(1-COST); units=0.0; in_pos=False
            else: cash=equity
            halts.append({"date":d[i+1],"equity":round(cash,2)})
            if ep==1:
                ep=2; halted_until=(date.fromisoformat(d[i+1])+timedelta(days=90)).isoformat()
            else:
                ended=True
            equity=cash
        curve.append(round(equity,6)); dts.append(d[i+1])
    final = units*c[-1] if in_pos else cash
    if curve: curve[-1]=round(final,6)
    return {"final":round(final,2),"max_dd_pct":round(100*maxdd(curve),2),"curve":curve,"dates":dts,"halts":halts}

def hold_run(d,o,c):
    units=100*(1-COST)/o[0]; curve=[100.0]+[round(units*x,6) for x in c[1:]]
    # align: curve[0] at d[0] pre-buy value 100; marks from c[0]
    curve=[round(units*x,6) for x in c]
    return {"final":round(units*c[-1],2),"max_dd_pct":round(100*maxdd(curve),2),"curve":curve}

# schedules
def sched_aggressive(d,o,c,btc_inv, stop_pct):
    n=len(c); inv=[0]*n; pos=0; entry=None
    for i in range(n-1):
        if pos==0:
            s50=sma(c,i,50); s200b = btc_inv[i] if btc_inv else 1
            if s50 is not None and c[i]>s50 and i>=20 and c[i]>max(c[i-20:i]) and s200b==1:
                pos=1; entry=c[i]
        else:
            s20=sma(c,i,20)
            if (s20 is not None and c[i]<s20) or (entry and c[i]<=entry*(1-stop_pct)): pos=0; entry=None
        inv[i]=pos
    return inv

def btc_regime_inv():
    d,o,c,_=SER["BTC"]; inv=[]
    for i in range(len(c)):
        s=sma(c,i,200); inv.append(1 if (s is not None and c[i]>s) else 0)
    # map by date
    return {d[i]:inv[i] for i in range(len(d))}

BTCREG = btc_regime_inv()
def regime_for(d):
    return [BTCREG.get(x,0) for x in d]

def per_coin_family(stop_pct):
    results={}
    for sym,(d,o,c,src) in sorted(SER.items()):
        if len(c)<320: 
            results[sym]={"skipped":"fewer than 320 bars"}; continue
        reg=regime_for(d)
        inv=sched_aggressive(d,o,c,reg,stop_pct)
        nat=run_schedule(d,o,c,inv,False); v9=run_schedule(d,o,c,inv,True)
        hold=hold_run(d,o,c)
        # validation window: slice from 2023-01-01
        vi=next((i for i,x in enumerate(d) if x>="2023-01-01"), None)
        val=None
        if vi is not None and len(c)-vi>=120:
            inv2=sched_aggressive(d[vi:],o[vi:],c[vi:],reg[vi:],stop_pct)
            val={"native":run_schedule(d[vi:],o[vi:],c[vi:],inv2,False)["final"],
                 "hold":hold_run(d[vi:],o[vi:],c[vi:])["final"]}
        results[sym]={"pegged":sym in PEGGED,"bars":len(c),"start":d[0],
            "native_final":nat["final"],"native_dd":nat["max_dd_pct"],
            "v9_final":v9["final"],"v9_dd":v9["max_dd_pct"],"v9_halts":v9["halts"],
            "hold_final":hold["final"],"hold_dd":hold["max_dd_pct"],
            "val":val,
            "_curve_nat":nat["curve"],"_dates":nat["dates"],"_curve_v9":v9["curve"]}
    return results

def placebo_per_coin(stop_pct, seeds=20):
    # pooled: rotation of inv schedule per coin
    beaten=0; total=0
    for sym,(d,o,c,src) in sorted(SER.items()):
        if len(c)<320: continue
        reg=regime_for(d)
        inv=sched_aggressive(d,o,c,reg,stop_pct)
        real=run_schedule(d,o,c,inv,False)["final"]
        rng_master=random.Random(12345)
        for s in range(seeds):
            rng=random.Random(rng_master.random())
            shift=rng.randrange(30, max(31,len(inv)-30))
            rot=inv[-shift:]+inv[:-shift]
            pf=run_schedule(d,o,c,rot,False)["final"]
            total+=1; beaten+= 1 if real>pf else 0
    return {"seeds_per_coin":seeds,"pooled_pairs":total,"share_real_beats_placebo":round(beaten/total,3) if total else None}

# ---------- basket simulator ----------
BTCD = {SER["BTC"][0][i]: i for i in range(len(SER["BTC"][0]))}
CAL = SER["BTC"][0]  # daily calendar from BTC

def price_on(sym, dstr):
    if sym not in SER: return None
    dd,oo,cc,_=SER[sym]
    import bisect
    i=bisect.bisect_right(dd,dstr)-1
    if i<0: return None
    return i  # index into series

def basket_run(start,end,cadence,selector,v9=False,seed=None):
    """selector(members, idx_map, ref_date) -> dict sym->weight (sum<=1). Monthly/weekly rebalance on BTC calendar."""
    days=[x for x in CAL if start<=x<=end]
    if not days: return None
    cash=100.0; units={}; curve=[]; dts=[]; costs=0.0; orders=0
    ep=1; floor=85.0; halted_until=None; ended=False; halts=[]; restart_bal=None
    def equity_at(dstr):
        tot=cash
        for s,u in units.items():
            i=price_on(s,dstr)
            if i is not None: tot+=u*SER[s][2][i]
        return tot
    def is_rebal(dstr, first):
        if first: return True
        if cadence=="monthly": return dstr[8:]=="01" or dstr[:7]!=prev[:7]
        if cadence=="weekly": return date.fromisoformat(dstr).weekday()==0
        return False
    prev=None
    for k,dstr in enumerate(days):
        if ended:
            curve.append(round(cash,6)); dts.append(dstr); prev=dstr; continue
        if halted_until is not None and dstr<halted_until:
            curve.append(round(cash,6)); dts.append(dstr); prev=dstr; continue
        if halted_until is not None and dstr>=halted_until:
            halted_until=None; floor=0.85*cash
        if is_rebal(dstr, k==0):
            eq=equity_at(dstr)
            members=pit_members(dstr)
            picks=selector(members, dstr, seed)
            # turnover cost
            cur_w={}
            for s,u in units.items():
                i=price_on(s,dstr); cur_w[s]= (u*SER[s][2][i]/eq) if (i is not None and eq>0) else 0
            alls=set(cur_w)|set(picks)
            turn=sum(abs(picks.get(s,0)-cur_w.get(s,0)) for s in alls)
            cost_amt=eq*COST*turn
            costs+=cost_amt; eq-=cost_amt; orders+=sum(1 for s in alls if abs(picks.get(s,0)-cur_w.get(s,0))>1e-6)
            cash=eq*(1-sum(picks.values())); units={}
            for s,w in picks.items():
                i=price_on(s,dstr)
                if i is not None and SER[s][2][i]>0: units[s]=eq*w/SER[s][2][i]
        eq=equity_at(dstr)
        if v9 and eq<=floor and k>0:
            cash=eq*(1-COST) if units else eq; units={}
            halts.append({"date":dstr,"equity":round(cash,2)})
            if ep==1: ep=2; halted_until=(date.fromisoformat(dstr)+timedelta(days=90)).isoformat()
            else: ended=True
            eq=cash
        curve.append(round(eq,6)); dts.append(dstr); prev=dstr
    return {"final":round(curve[-1],2) if curve else None,"max_dd_pct":round(100*maxdd(curve),2),
            "costs":round(costs,2),"orders":orders,"halts":halts,"curve":curve,"dates":dts}

def hist(sym, dstr, n):
    i=price_on(sym,dstr)
    if i is None or i<n: return None
    return SER[sym][2][:i+1]

def sel_momentum_top5(members, dstr, seed=None):
    cand=[]
    for s in members:
        h=hist(s,dstr,365)
        if h is None: continue
        m=h[-31]/h[-366]-1 if len(h)>365 else None
        if m is not None and m>0: cand.append((m,s))
    cand.sort(reverse=True)
    if seed is not None:
        rng=random.Random(seed); pool=[s for _,s in cand]; rng.shuffle(pool); picks=pool[:5]
        return {s:0.2 for s in picks}
    return {s:0.2 for _,s in cand[:5]}

def sel_breakout_top5(members, dstr, seed=None, regime=False):
    if regime:
        bd,bo,bc,_=SER["BTC"]; bi=price_on("BTC",dstr)
        if bi is None or bi<200 or bc[bi]<sma(bc,bi,200): return {}
    cand=[]
    for s in members:
        h=hist(s,dstr,252)
        if h is None: continue
        ratio=h[-1]/max(h[-253:-1]) if len(h)>252 else None
        if ratio is not None: cand.append((ratio,s))
    cand.sort(reverse=True)
    if seed is not None:
        rng=random.Random(seed); pool=[s for _,s in cand]; rng.shuffle(pool); picks=pool[:5]
        return {s:0.2 for s in picks}
    return {s:0.2 for _,s in cand[:5] if _>=0.95}

def make_disciplined(topn, invvol, use_ddcap=False):
    pond=["BTC","ETH","XRP","LTC","XMR"]
    def sel(members, dstr, seed=None):
        # members ignored: fixed pond translation
        cand=[]
        for s in pond:
            h=hist(s,dstr,200)
            if h is None: continue
            if h[-1]>sum(h[-200:])/200:
                mom=h[-1]/h[-64]-1
                cand.append((mom,s))
        cand.sort(reverse=True)
        picks=[s for _,s in cand[:topn]]
        if seed is not None:
            rng=random.Random(seed); pool=[s for _,s in cand]; rng.shuffle(pool); picks=pool[:topn]
        if not picks: return {}
        share=0.5 if len(picks)==1 else 1.0
        # BTC defensive cap
        bd=hist("BTC",dstr,200)
        if bd is not None and bd[-1]<sum(bd[-200:])/200: share=min(share,0.5)
        if invvol:
            ws=[]
            for s in picks:
                h=hist(s,dstr,20); 
                rets=[math.log(h[i]/h[i-1]) for i in range(len(h)-19,len(h))]
                v=statistics.pstdev(rets) if len(rets)>1 else 0
                ws.append(1/v if v>0 else 0)
            tot=sum(ws)
            if tot<=0: return {s:share/len(picks) for s in picks}
            return {s:share*w/tot for s,w in zip(picks,ws)}
        return {s:share/len(picks) for s in picks}
    return sel

def sel_trendsleeve_weekly(members, dstr, seed=None):
    picks=[]
    for s in members:
        h=hist(s,dstr,252)
        if h is None: continue
        score=sum(1 for lag in (63,126,252) if h[-1]/h[-1-lag]-1>0)
        if score>=2: picks.append(s)
    if seed is not None:
        rng=random.Random(seed); rng.shuffle(picks); picks=picks[:len(picks)//2] if picks else picks
    if not picks: return {}
    w=1.0/len(picks)
    return {s:w for s in picks}

def btc_hold_window(start,end):
    d,o,c,_=SER["BTC"]
    idx=[i for i,x in enumerate(d) if start<=x<=end]
    if not idx: return None
    i0=idx[0]; units=100*(1-COST)/o[i0]
    curve=[round(units*c[i],6) for i in idx]
    return {"final":round(units*c[idx[-1]],2),"max_dd_pct":round(100*maxdd(curve),2)}

WINDOWS_BASKET=[("FULL","2017-01-01","2026-11-20"),("DESIGN","2017-01-01","2022-12-31"),("VALIDATION","2023-01-01","2026-11-20")]
