import json, os, math, random, statistics
BASE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
OHLC=os.path.join(BASE,"crypto-x-constructed","data_ohlc")
COST=0.006  # 0.60%/side crypto-realistic (program range 0.40-0.80)
def load_coins(min_bars=300):
    summ=json.load(open(os.path.join(OHLC,"fetch_summary.json")))
    coins={}
    for cid,meta in summ.items():
        p=os.path.join(OHLC,f"{cid}.json")
        if not os.path.exists(p): continue
        rows=json.load(open(p))
        rows=[r for r in rows if r.get("c")]
        if len(rows)<min_bars: continue
        coins[meta["symbol"]]=(cid,rows)
    return coins
def sma(v,n):
    out=[None]*len(v); s=0.0
    for i,x in enumerate(v):
        s+=x
        if i>=n: s-=v[i-n]
        if i>=n-1: out[i]=s/n
    return out
def max_dd(eq):
    peak=-1; dd=0.0
    for x in eq:
        peak=max(peak,x); dd=min(dd,x/peak-1 if peak>0 else 0)
    return dd
def period_stats(dates,eq):
    # monthly periods
    months={}
    for d,e in zip(dates,eq): months.setdefault(d[:7],[]).append(e)
    keys=sorted(months); rets=[]
    prev=eq[0]
    # month return = last equity of month / last equity of prior month -1
    last_by={}
    for k in keys: last_by[k]=months[k][-1]
    prev=100.0
    for k in keys:
        rets.append(last_by[k]/prev-1); prev=last_by[k]
    if not rets: return {}
    los=0; worst_run=0
    for r in rets:
        los=los+1 if r<0 else 0; worst_run=max(worst_run,los)
    return {"periods":len(rets),"share_positive":round(sum(1 for r in rets if r>0)/len(rets),3),
            "median_period_pct":round(statistics.median(rets)*100,2),
            "best_period_pct":round(max(rets)*100,2),"worst_period_pct":round(min(rets)*100,2),
            "longest_losing_run":worst_run}
def run_position(rows,pos,house=False,seed_shift=0):
    """pos[i] in {0,1}: desired holding decided at close i, executed open i+1.
    Returns (dates, equity curve starting 100)."""
    n=len(rows); eq=[100.0]; dates=[rows[0]["d"]]
    cash=100.0; units=0.0; holding=False
    start_bal=100.0; floor=85.0; halts=0; cash_until=-1
    if seed_shift: pos=pos[seed_shift:]+pos[:seed_shift]
    for i in range(n-1):
        o=rows[i+1]["o"]; c=rows[i+1]["c"]
        want = pos[i]==1
        if house and halts>=2: want=False
        if house and i<cash_until: want=False
        if want and not holding:
            units=cash*(1-COST)/o; cash=0.0; holding=True
        elif not want and holding:
            cash=units*o*(1-COST); units=0.0; holding=False
        cur = units*c if holding else cash
        eq.append(cur); dates.append(rows[i+1]["d"])
        if house and holding:
            pass
        if house:
            cur_close = units*c if holding else cash
            if cur_close<=floor and halts<2:
                # liquidate at next open handled by forcing want False via cash_until; approximate: liquidate at this close with cost
                if holding: cash=units*c*(1-COST); units=0.0; holding=False; eq[-1]=cash
                halts+=1
                if halts==1:
                    # 90 calendar days ~ 90 bars (24/7 daily bars)
                    cash_until=i+90; floor=0.85*cash
                else:
                    cash_until=n+10**9
    if holding: # final liquidation at last close with cost
        eq[-1]=units*rows[-1]["c"]*(1-COST)
    return dates,eq
def btc_hold(rows):
    eq=[100.0*r["c"]/rows[0]["c"] for r in rows]
    return [r["d"] for r in rows], eq
def shifted_placebo_beaten(rows,pos,real_final,nseed=20):
    n=len(pos); beaten=0; finals=[]
    rng=random.Random(12345)
    for s in range(nseed):
        sh=rng.randrange(30,max(31,n-30)) if n>60 else rng.randrange(1,n)
        _,eq=run_position(rows,pos,house=False,seed_shift=sh)
        finals.append(eq[-1])
        if real_final>eq[-1]: beaten+=1
    return beaten, (round(statistics.median(finals),2) if finals else None)
