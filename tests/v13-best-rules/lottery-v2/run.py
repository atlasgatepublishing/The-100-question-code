#!/usr/bin/env python3
"""V13 best-rules run for lottery-v2. Spec: BEST-RULES-SPEC.md (frozen first).
Data: v10 decade cache (read-only shared input). Roads DECADE/CONT/VAL;
LONG closed (cache begins 2016). 20-seed placebos per road."""
import bisect, json, os, random, statistics
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/lottery-v2/data_cache_decade")
ET = ZoneInfo("America/New_York")
START_CASH = 100.0
COST_RATE, SELL_FEE = 0.02, 0.01
MAX_POS, TICKET = 8, 0.125
MAX_PER_WEEK = 2
STOP0, TRAIL_ARM, TRAIL = 0.20, 0.30, 0.25
GAP_SKIP = 0.10
SCREEN_MAX_PRICE, SCREEN_MIN_AVG_DV = 5.00, 20_000_000
LISTED = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}
CANDIDATES = ["PLUG","FCEL","BLDP","SNDL","ACB","CGC","TLRY","OGI","CRON","BYND","GERN",
 "IOVA","RXRX","PACB","DNA","EDIT","OCGN","SAVA","BTBT","SDIG","GREE","CAN","EBON","SOS",
 "MULN","FFAI","NKLA","GOEV","WKHS","BLNK","EVGO","CHPT","SPCE","JBLU","ULCC","AMC","BB",
 "NOK","KOSS","VFS","PSNY","NIO","GRAB","FINV","NNDM","DDD","EXK","FSM","HYMC","TEF",
 "BBAI","OPEN","PTON","TDOC","LCID","CLOV","ACHR","CIFR","AGEN","INO","NVAX","LX","IQ",
 "TUYA","NGD","BTG","DNN","CLNE","GEVO"]
ROADS = {"DECADE": ("2016-11-21", "2026-11-20"), "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}

def load_symbol(sym):
    p = os.path.join(CACHE, f"{sym}.json")
    if not os.path.exists(p): return None
    d = json.load(open(p)); res = d.get("chart", {}).get("result")
    if not res: return None
    r = res[0]; meta = r.get("meta", {}); q = r.get("indicators", {}).get("quote", [{}])[0]
    dates, O, H, L, C, V = [], [], [], [], [], []
    for i, t in enumerate(r.get("timestamp", []) or []):
        try: o,h,l,c,v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        except (KeyError, IndexError, TypeError): continue
        if None in (o,h,l,c,v): continue
        dates.append(datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d"))
        O.append(o); H.append(h); L.append(l); C.append(c); V.append(v)
    if not dates: return None
    pv=[0.0]; pdv=[0.0]; pc=[0.0]
    for c,v in zip(C,V): pv.append(pv[-1]+v); pdv.append(pdv[-1]+c*v); pc.append(pc[-1]+c)
    return {"meta":meta,"dates":dates,"O":O,"H":H,"L":L,"C":C,"V":V,
            "idx":{d:i for i,d in enumerate(dates)},"pv":pv,"pdv":pdv,"pc":pc}

def bar(S, day):
    i = S["idx"].get(day)
    return None if i is None else (S["O"][i], S["H"][i], S["L"][i], S["C"][i], S["V"][i])
def last_close(S, day):
    j = bisect.bisect_right(S["dates"], day) - 1
    return S["C"][j] if j >= 0 else None
def tavg(S, day, n, arr="pv"):
    i = S["idx"].get(day)
    if i is None or i+1 < n: return None
    a = S[arr]; return (a[i+1]-a[i+1-n])/n

def screen(symbols, day):
    out=[]
    for sym,S in symbols.items():
        b=bar(S,day)
        if b is None: continue
        adv=tavg(S,day,20,"pdv")
        if adv is None: continue
        if (S["meta"].get("exchangeName") in LISTED and S["meta"].get("instrumentType")=="EQUITY"
            and b[3] < SCREEN_MAX_PRICE and adv > SCREEN_MIN_AVG_DV): out.append(sym)
    return sorted(out)

def ranked(symbols, universe, day, held):
    out=[]
    for s in universe:
        if s in held: continue
        S=symbols[s]; i=S["idx"].get(day)
        if i is None or i==0: continue
        pc=S["C"][i-1]
        if pc<=0: continue
        gain=(S["C"][i]/pc-1)*100
        av=tavg(S,day,20)
        spike=(S["V"][i]/av) if av else 0.0
        score=gain*spike
        sma20=tavg(S,day,20,"pc")
        if score>0 and sma20 is not None and S["C"][i] > sma20: out.append((score,s))
    out.sort(reverse=True)
    return [s for _,s in out]

def simulate(symbols, spy, tdays, start, end, rng=None):
    cash=START_CASH; positions={}; curve=[]; costs=0.0; orders=0; trades=0; wins=0
    entries_week={}; screen_cache={}
    spy_c={d:spy["C"][i] for i,d in enumerate(spy["dates"])}
    spy_dates=spy["dates"]
    def spy_gate(day):  # True = entries allowed (SPY >= 200d avg close)
        j=bisect.bisect_right(spy_dates, day)-1
        if j+1<200: return True
        avg=sum(spy["C"][j-199:j+1])/200
        return spy["C"][j] >= avg
    def equity(day):
        eq=cash
        for s,p in positions.items():
            c=last_close(symbols[s], day); eq += p["shares"]*(c if c else p["entry"])
        return eq
    def sell(day, sym, price):
        nonlocal cash, costs, orders, trades, wins
        p=positions.pop(sym); gross=p["shares"]*price
        costs += gross*COST_RATE + SELL_FEE; orders+=1; trades+=1
        if gross*(1-COST_RATE)-SELL_FEE > p["outlay"]: wins+=1
        cash += gross*(1-COST_RATE)-SELL_FEE
    inwin=[d for d in tdays if start<=d<=end]
    week_first=set()
    seen=set()
    for d in inwin:
        k=datetime.strptime(d,"%Y-%m-%d").date().isocalendar()[:2]
        if k not in seen: seen.add(k); week_first.add(d)
    for ti,day in enumerate(tdays):
        if day<start or day>end: continue
        # daily exits: close-based stop check -> sell next open (pending list)
        # implemented as: check yesterday's close breach at today's open
        if ti>0:
            yday=tdays[ti-1]
            for s in list(positions):
                p=positions[s]
                yc=last_close(symbols[s], yday)
                if yc is None: continue
                p["hi"]=max(p["hi"], yc)
                stop=p["entry"]*(1-STOP0)
                if p["hi"] >= p["entry"]*(1+TRAIL_ARM): stop=max(stop, p["hi"]*(1-TRAIL))
                if yc <= stop:
                    b=bar(symbols[s], day)
                    sell(day, s, b[0] if b else yc)
        # weekly entry
        if day in week_first and ti>0:
            sig=tdays[ti-1]
            mk=sig[:7]
            if mk not in screen_cache: screen_cache[mk]=screen(symbols, sig) if False else None
            # monthly screen: last trading day of prior month relative to sig
            prior=[d for d in tdays if d<=sig]
            scr_day=None
            for d in reversed(prior):
                if d[:7]!=sig[:7]: scr_day=d; break
            universe=screen(symbols, scr_day) if scr_day else []
            if spy_gate(sig):
                elig=ranked(symbols, universe, sig, set(positions))
                wk=datetime.strptime(day,"%Y-%m-%d").date().isocalendar()[:2]
                n=0
                while elig and len(positions)<MAX_POS and entries_week.get(wk,0)+n<MAX_PER_WEEK:
                    pick = elig[0] if rng is None else rng.choice(elig)
                    elig.remove(pick)
                    b=bar(symbols[pick], day)
                    if b is None or b[0]<=0: continue
                    sigc=last_close(symbols[pick], sig)
                    if sigc and b[0] > sigc*(1+GAP_SKIP): continue
                    amount=min(TICKET*equity(day), cash)
                    if amount<1.0: break
                    shares=amount/(b[0]*(1+COST_RATE))
                    costs += amount-shares*b[0]; orders+=1
                    cash-=amount
                    positions[pick]={"shares":shares,"entry":b[0],"outlay":amount,"hi":b[0]}
                    n+=1
                entries_week[wk]=entries_week.get(wk,0)+n
        if day==end:
            for s in list(positions):
                c=last_close(symbols[s], day)
                if c: sell(day, s, c)
            curve.append([day, round(cash,2)]); break
        curve.append([day, round(equity(day),2)])
    peak, mdd = START_CASH, 0.0
    for _,v in curve: peak=max(peak,v); mdd=min(mdd, v/peak-1)
    # monthly distribution
    months={}
    for d,v in curve: months[d[:7]]=v
    mk=sorted(months); rets=[]; prev=START_CASH
    for m in mk: rets.append(months[m]/prev-1); prev=months[m]
    pos=sum(1 for r in rets if r>0); streak=cur=0
    for r in rets: cur=cur+1 if r<=0 else 0; streak=max(streak,cur)
    hi=-1; last_hi=0
    for i,(_,v) in enumerate(curve):
        if v>=hi: hi=v; last_hi=i
    yrs=(datetime.strptime(end,"%Y-%m-%d")-datetime.strptime(start,"%Y-%m-%d")).days/365.25
    dist={"median_month_pct":round(statistics.median(rets)*100,2) if rets else None,
          "months":len(rets),"share_months_positive_pct":round(100*pos/len(rets),1) if rets else None,
          "best_month_pct":round(max(rets)*100,2) if rets else None,
          "worst_month_pct":round(min(rets)*100,2) if rets else None,
          "longest_losing_streak_months":streak,
          "days_since_new_high_at_end":len(curve)-1-last_hi,
          "mean_month_pct_secondary":round(statistics.mean(rets)*100,2) if rets else None}
    return {"final":round(cash,2),"cagr_pct":round(((cash/START_CASH)**(1/yrs)-1)*100,2) if cash>0 else -100.0,
            "max_dd_pct":round(mdd*100,2),"costs":round(costs,2),"orders":orders,
            "round_trips":trades,"win_rate_pct":round(100*wins/trades,1) if trades else None,
            "distribution":dist,"equity_curve":curve}

def main():
    symbols={}; failed=[]
    for s in CANDIDATES:
        S=load_symbol(s)
        if S is None: failed.append(s)
        else: symbols[s]=S
    spy=load_symbol("SPY"); tdays=[d for d in spy["dates"] if "2016-01-01"<=d<="2026-11-20"]
    print("loaded", len(symbols), "failed", failed, flush=True)
    out={"family":"lottery-v2","program":"v13-best-rules","failed_symbols":failed,"roads":{}}
    for road,(st,en) in ROADS.items():
        res=simulate(symbols, spy, tdays, st, en)
        twins=[]
        for seed in range(1,21):
            t=simulate(symbols, spy, tdays, st, en, rng=random.Random(1000+seed))
            twins.append(t["final"])
        res["placebo_finals"]=twins
        res["placebo_beaten"]=sum(1 for f in twins if res["final"]>f)
        res["placebo_median"]=round(statistics.median(twins),2)
        out["roads"][road]=res
        print(road, res["final"], res["max_dd_pct"], "placebo", res["placebo_beaten"], "/20 median", res["placebo_median"], flush=True)
    json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
    print("done")

if __name__=="__main__": main()
