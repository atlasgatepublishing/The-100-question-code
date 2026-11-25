#!/usr/bin/env python3
"""
V13 BEST RULES — N-4 OPEx-WEEK PINNING RELEASE (invented rule).
Frozen design: BEST-RULES-SPEC.md in this folder. Same third-Friday anchor
(NO retiming — the second-Friday control is a control, never a candidate).
Structural changes vs the published v8 form: (1) rolling basket-to-basket
monthly rotation chassis (SPY round-trip abolished); (2) residual
(market-relative) trend filter; (3) no floor. Published form re-run on the
same roads for the comparison table. Data: read-only v7 cache
(backtests/v7/gap-a1-seasonality/data), Yahoo adjclose daily bars.
Costs: 0.10%/side + $0.01 per sell order. $100 pots.
"""
import calendar as _cal
import json, math, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/gap-a1-seasonality/data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG",
            "V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC",
            "CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
START_CASH = 100.0
CR_MAX = 0.70
TOP_N = 5
SEEDS = list(range(1, 21))
ROADS = [("DECADE","2016-11-21","2026-11-20"),
         ("CONT","2019-01-02","2026-11-20"),
         ("VAL","2023-01-03","2026-11-20")]
SPY_PUBLISHED = {"DECADE":367.80,"CONT":313.62,"VAL":187.77}
CHAMPIONS = {"LONG":1415.62,"DECADE":667.35,"CONT":544.47,"VAL":288.05}

def load_bars(t):
    with open(os.path.join(DATA, f"px_{t}.json"), "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose",[{}])[0].get("adjclose")
    bars = []
    for i,tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        o,c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a/c if c else 1.0
        bars.append({"d":d,"o":(o*r if o else a),"c":a})
    bars.sort(key=lambda b: b["d"])
    return bars

def nth_friday(y,m,n):
    fr = [d for d in range(1,_cal.monthrange(y,m)[1]+1) if _cal.weekday(y,m,d)==4]
    return f"{y:04d}-{m:02d}-{fr[n-1]:02d}"

def build_events(cal_index, start, end, which):
    months=[]; y,m = int(start[:4]), int(start[5:7]); ey,em = int(end[:4]), int(end[5:7])
    while (y,m) <= (ey,em):
        months.append((y,m)); m+=1
        if m==13: y,m = y+1,1
    dates = sorted(cal_index); out=[]
    for (y,m) in months:
        target = nth_friday(y,m,which); p=None
        for d in dates:
            if d <= target: p = cal_index[d]
            else: break
        if p is None: continue
        if not (start <= dates[p] <= end): continue
        out.append(p)
    return out

def screen(closes, p, residual):
    """Eligible names at anchor index p, ranked by CR ascending."""
    ranked=[]; detail={}
    spy = closes["SPY"]
    if spy[p-1] is None or spy[p-10] is None: return ranked, detail
    spy_trend = spy[p-1]/spy[p-10]-1.0
    for t in UNIVERSE:
        c = closes[t]
        if p-61 < 0 or any(c[j] is None for j in range(p-61,p+1)): continue
        a = sum(abs(c[j]/c[j-1]-1.0) for j in range(p-4,p))/4.0
        b = sum(abs(c[j]/c[j-1]-1.0) for j in range(p-60,p))/60.0
        if b <= 0: continue
        cr = a/b; trend = c[p-1]/c[p-10]-1.0
        detail[t]=(cr,trend)
        ok = (trend - spy_trend > 0) if residual else (trend > 0)
        if cr <= CR_MAX and ok: ranked.append(t)
    ranked.sort(key=lambda t: detail[t][0])
    return ranked, detail

class Pot:
    def __init__(self, cal, closes, opens):
        self.cal=cal; self.closes=closes; self.opens=opens
        self.pos_of={d:i for i,d in enumerate(cal)}
        self.cash=START_CASH; self.pos={}; self.costs=0.0; self.orders=0; self.trades=[]
    def px(self,t,i):
        v=self.closes[t][i]
        if v is not None: return v
        j=i
        while j>=0 and self.closes[t][j] is None: j-=1
        return self.closes[t][j] if j>=0 else None
    def equity(self,i):
        v=self.cash
        for t,sh in self.pos.items():
            p=self.px(t,i)
            if p: v+=sh*p
        return v
    def sell_all(self,i,d,tag):
        for t in list(self.pos):
            p=self.px(t,i); sh=self.pos[t]
            if p:
                val=sh*p; c=val*0.001+0.01
                self.cash+=val-c; self.costs+=c; self.orders+=1
                self.trades.append((d,t,tag,round(sh,4),round(p,4),round(val,2),round(c,2)))
            del self.pos[t]
    def sell_val(self,t,target,i,d,tag):
        p=self.px(t,i); sh=self.pos.get(t,0.0)
        if not p or sh<=0: return
        sh_sell=min(sh, target/p)
        if sh_sell<=1e-9: return
        val=sh_sell*p; c=val*0.001+0.01
        self.cash+=val-c; self.costs+=c; self.orders+=1
        self.trades.append((d,t,tag,round(sh_sell,4),round(p,4),round(val,2),round(c,2)))
        self.pos[t]-=sh_sell
        if self.pos[t]<1e-9: del self.pos[t]
    def buy_value(self,t,target,i,d,tag):
        p=self.px(t,i)
        if p is None or p<=0: return
        bv=min(target, self.cash/1.001)
        if bv<=0.005: return
        sh=bv/p; c=bv*0.001
        self.cash-=bv+c; self.costs+=c; self.orders+=1
        self.pos[t]=self.pos.get(t,0.0)+sh
        self.trades.append((d,t,tag,round(sh,4),round(p,4),round(bv,2),round(c,2)))
    def buy_all_in(self,t,i,d,tag):
        p=self.opens[t][i] if tag=="BUY-START" else self.px(t,i)
        if p is None or self.cash<=0.005: return
        bv=self.cash/1.001; sh=bv/p; c=self.cash-bv
        self.cash=0.0; self.costs+=c; self.orders+=1
        self.pos[t]=self.pos.get(t,0.0)+sh
        self.trades.append((d,t,tag,round(sh,4),round(p,4),round(bv,2),round(c,2)))

def run_my(cal, closes, opens, events, start, end):
    """Rolling chassis. events: list of {p, picks} chronological."""
    days=[d for d in cal if start<=d<=end]
    pot=Pot(cal,closes,opens); curve=[]; ev_in={e["p"]:e for e in events}
    for di,d in enumerate(days):
        i=pot.pos_of[d]
        if di==0: pot.buy_all_in("SPY", i, d, "BUY-START")
        if i in ev_in:
            picks=[t for t in ev_in[i]["picks"] if closes[t][i] is not None]
            holding_spy_only = set(pot.pos) <= {"SPY"}
            if picks:
                v=pot.equity(i)
                pot.sell_all(i,d,"SELL-ROT")
                for t in picks: pot.buy_value(t, v/len(picks), i, d, "BUY")
            elif not holding_spy_only:
                pot.sell_all(i,d,"SELL-ROT")
                pot.buy_all_in("SPY", i, d, "BUY-SPY")
        curve.append((d, pot.equity(i)))
    last=days[-1]; li=pot.pos_of[last]
    pot.sell_all(li,last,"SELL-END")
    return finish(pot, curve, last)

def run_published(cal, closes, opens, events, start, end):
    """v8 frozen form: SPY parking, fifths, exit at E+5, plain $85 floor.
    events: {p, picks} with exit observable (p+5 <= end) — caller filters."""
    days=[d for d in cal if start<=d<=end]
    pot=Pot(cal,closes,opens); curve=[]; halted=None
    ev_in={e["p"]:e for e in events}; ev_out={e["p"]+5:e for e in events}
    for di,d in enumerate(days):
        i=pot.pos_of[d]
        if di==0: pot.buy_all_in("SPY", i, d, "BUY-START")
        if i in ev_in:
            picks=[t for t in ev_in[i]["picks"] if closes[t][i] is not None]
            if picks:
                v=pot.equity(i); k=len(picks)
                pot.sell_val("SPY", (k/5.0)*v, i, d, "SELL-ROT")
                for t in picks: pot.buy_value(t, v/5.0, i, d, "BUY")
        if i in ev_out:
            held=[t for t in list(pot.pos) if t!="SPY"]
            for t in held:
                p=pot.px(t,i); sh=pot.pos[t]
                val=sh*p; c=val*0.001+0.01
                pot.cash+=val-c; pot.costs+=c; pot.orders+=1
                pot.trades.append((d,t,"SELL-EXIT",round(sh,4),round(p,4),round(val,2),round(c,2)))
                del pot.pos[t]
            if held: pot.buy_all_in("SPY", i, d, "BUY-BACK")
        v=pot.equity(i); curve.append((d,v))
        if v<=85.0 and di<len(days)-1:
            halted=d; nd=days[di+1]; ni=pot.pos_of[nd]
            for t in list(pot.pos):
                o=pot.opens[t][ni]; sh=pot.pos[t]
                if o:
                    val=sh*o; c=val*0.001+0.01
                    pot.cash+=val-c; pot.costs+=c; pot.orders+=1
                    pot.trades.append((nd,t,"SELL-HALT",round(sh,4),round(o,4),round(val,2),round(c,2)))
                del pot.pos[t]
            r=finish(pot,curve,nd); r["halted"]=halted; return r
    last=days[-1]; li=pot.pos_of[last]
    pot.sell_all(li,last,"SELL-END")
    r=finish(pot,curve,last); r["halted"]=None; return r

def finish(pot, curve, end):
    peak,mdd,mdd_d=-1.0,0.0,None; worst_d,worst_v=None,1e18
    for d,v in curve:
        if v>peak: peak=v
        dd=(peak-v)/peak if peak>0 else 0.0
        if dd>mdd: mdd,mdd_d=dd,d
        if v<worst_v: worst_v,worst_d=v,d
    return {"final":round(pot.cash,2),"costs":round(pot.costs,2),"orders":pot.orders,
            "max_dd_pct":round(mdd*100,2),"max_dd_date":mdd_d,
            "worst_close":round(worst_v,2),"worst_close_date":worst_d,
            "end":end,"curve":curve,"trades":pot.trades}

def spy_net(cal, closes, opens, start, end):
    days=[d for d in cal if start<=d<=end]
    pos_of={d:i for i,d in enumerate(cal)}
    o=opens["SPY"][pos_of[days[0]]]
    sh=(START_CASH/1.001)/o; bc=START_CASH-sh*o
    c=closes["SPY"][pos_of[days[-1]]]; val=sh*c; sc=val*0.001+0.01
    return round(val-sc,2)

def period_distribution(curve):
    ends={}; order=[]
    for d,v in curve:
        k=(int(d[:4]),int(d[5:7]))
        if k not in ends: order.append(k)
        ends[k]=v
    vals=[ends[k] for k in order]; rets=[]; prev=100.0
    for v in vals: rets.append(v/prev-1.0); prev=v
    if not rets: return None
    prof=sum(1 for r in rets if r>0); ll=cur=0
    for r in rets:
        cur=cur+1 if r<=0 else 0; ll=max(ll,cur)
    peak,since,gap=-1.0,0,0
    for v in vals:
        if v>=peak: peak,since=v,0
        else: since+=1; gap=max(gap,since)
    return {"periods":len(rets),"pct_profitable":round(100.0*prof/len(rets),1),
            "median_period_pct":round(statistics.median(rets)*100,2),
            "best_period_pct":round(max(rets)*100,2),"worst_period_pct":round(min(rets)*100,2),
            "longest_losing_run_periods":ll,
            "longest_stretch_between_new_highs_periods":gap,
            "average_period_pct_secondary":round(statistics.mean(rets)*100,2)}

def ranked_events(cal, closes, cal_index, start, end, which, residual):
    evs=[]
    for p in build_events(cal_index, start, end, which):
        ranked,detail=screen(closes,p,residual)
        evs.append({"p":p,"picks":ranked[:TOP_N],"n_eligible":len(ranked),"detail":detail})
    return evs

def main():
    bars={t:load_bars(t) for t in UNIVERSE+["SPY"]}
    cal=[b["d"] for b in bars["SPY"]]; cal_index={d:i for i,d in enumerate(cal)}
    closes={}; opens={}
    for t in UNIVERSE+["SPY"]:
        by={b["d"]:b for b in bars[t]}
        closes[t]=[by[d]["c"] if d in by else None for d in cal]
        opens[t]=[by[d]["o"] if d in by else None for d in cal]
    # integrity: SPY buy-hold must reproduce published nets
    integ={}
    for rn,s,e in ROADS:
        v=spy_net(cal,closes,opens,s,e)
        integ[rn]={"spy_net":v,"published":SPY_PUBLISHED[rn],"match":v==SPY_PUBLISHED[rn]}
        print(f"INTEGRITY {rn}: spy ${v} vs published ${SPY_PUBLISHED[rn]} match={v==SPY_PUBLISHED[rn]}",flush=True)
    if not all(v["match"] for v in integ.values()):
        raise SystemExit("INTEGRITY FAILURE — aborting")

    out={"family":"novel-x4-opex-release (N-4 OpEx-Week Pinning Release, invented)",
         "program":"v13-best-rules","spec":"BEST-RULES-SPEC.md (frozen before run)",
         "premise_statement":"Expiration-anchor (pinning) premise CLOSED by the v8 second-Friday calendar placebo; anchor NOT retimed (binding fence). This run is a same-anchor confirmation of the screen under a rolling chassis + residual trend filter.",
         "my_rules":{"anchor":"3rd Friday, entry at close of E (unchanged)",
                     "chassis":"rolling basket-to-basket monthly rotation; SPY only at start / when zero eligible",
                     "screen":"CR<=0.70 (unchanged), residual trend vs SPY >0 (changed from raw >0)",
                     "count":5,"weighting":"equal, full pot","floor":None,
                     "costs":"0.10%/side + $0.01 per sell order","start_cash":100.0},
         "published_form":{"finals_v8":{"CONT":247.09,"VAL":182.30}},
         "spy_reference":SPY_PUBLISHED,"champions_vm":CHAMPIONS,
         "long_road":"NOT RUN — fixed Nov-2016 pond applied to 2010 would be survivorship lookahead; no PIT 2010 pond for this family.",
         "integrity":integ,"roads":{}}
    beat=[]
    for rn,s,e in ROADS:
        evs=ranked_events(cal,closes,cal_index,s,e,3,True)
        r=run_my(cal,closes,opens,evs,s,e)
        # published form on same road (events need exit p+5 <= end)
        pub_evs=[ev for ev in ranked_events(cal,closes,cal_index,s,e,3,False)
                 if ev["p"]+5 < len(cal) and cal[ev["p"]+5] <= e]
        pub=run_published(cal,closes,opens,pub_evs,s,e)
        # random placebos
        finals=[]
        for seed in SEEDS:
            rng=random.Random(seed)
            pevs=[{"p":ev["p"],"picks":rng.sample(sorted(UNIVERSE),TOP_N)} for ev in evs]
            finals.append(round(run_my(cal,closes,opens,pevs,s,e)["final"],2))
        beaten=sum(1 for f in finals if r["final"]>f)
        # calendar controls (never candidates)
        ctrls={}
        for name,which in (("second_friday",2),("fourth_friday",4)):
            cevs=ranked_events(cal,closes,cal_index,s,e,which,True)
            cr_=run_my(cal,closes,opens,cevs,s,e)
            ctrls[name]={"final":cr_["final"],"max_dd_pct":cr_["max_dd_pct"],"costs":cr_["costs"]}
        # per-event 5-day release diagnostic
        diag=[]
        for ev in evs:
            p=ev["p"]
            if ev["picks"] and p+5 < len(cal):
                brs=[closes[t][p+5]/closes[t][p]-1.0 for t in ev["picks"] if closes[t][p] and closes[t][p+5]]
                sr=closes["SPY"][p+5]/closes["SPY"][p]-1.0
                diag.append({"E":cal[p],"n_eligible":ev["n_eligible"],"picks":ev["picks"],
                             "basket_5d_pct":round(sum(brs)/len(brs)*100,3) if brs else None,
                             "spy_5d_pct":round(sr*100,3)})
        cell={"window":[s,e],
              "my_rules":{"final":r["final"],"max_dd_pct":r["max_dd_pct"],"max_dd_date":r["max_dd_date"],
                          "worst_close":r["worst_close"],"worst_close_date":r["worst_close_date"],
                          "costs":r["costs"],"orders":r["orders"],"n_events":len(evs),
                          "mean_eligible":round(sum(ev['n_eligible'] for ev in evs)/len(evs),2) if evs else None},
              "published_form":{"final":pub["final"],"max_dd_pct":pub["max_dd_pct"],"costs":pub["costs"],
                                "orders":pub["orders"],"halted":pub.get("halted")},
              "spy_final":SPY_PUBLISHED[rn],"champion_vm":CHAMPIONS[rn],
              "placebo_finals":finals,"placebo_median":round(statistics.median(finals),2),
              "placebo_beaten":beaten,
              "calendar_controls_NOT_CANDIDATES":ctrls,
              "event_diagnostics":diag,
              "period_distribution_monthly":period_distribution(r["curve"]),
              "curve":[[d,round(v,4)] for d,v in r["curve"]]}
        out["roads"][rn]=cell
        if r["final"]>CHAMPIONS[rn]: beat.append(rn)
        print(f"{rn}: MY ${r['final']} (DD {r['max_dd_pct']}%, costs ${r['costs']}, orders {r['orders']}, "
              f"events {len(evs)}) | PUB ${pub['final']} | SPY ${SPY_PUBLISHED[rn]} | CHAMP ${CHAMPIONS[rn]} | "
              f"placebo beaten {beaten}/20 | ctrl2 ${ctrls['second_friday']['final']} ctrl4 ${ctrls['fourth_friday']['final']}",flush=True)
    out["champion_roads_beaten"]=beat
    # confirmation folds if any champion beaten
    confirm=None
    if beat:
        foldrec={}
        for key in ("v13_best","published"):
            tot=1.0; yrs={}
            for yr in range(2017,2027):
                s=f"{yr}-01-01"; e=f"{yr}-12-31" if yr<2026 else "2026-11-20"
                if key=="v13_best":
                    evs=ranked_events(cal,closes,cal_index,s,e,3,True)
                    fr=run_my(cal,closes,opens,evs,s,e)
                else:
                    pevs=[ev for ev in ranked_events(cal,closes,cal_index,s,e,3,False)
                          if ev["p"]+5 < len(cal) and cal[ev["p"]+5] <= e]
                    fr=run_published(cal,closes,opens,pevs,s,e)
                yrs[str(yr)]=fr["final"]; tot*=fr["final"]/100.0
            foldrec[key]={"folds":yrs,"fold_compounded":round(tot*100,2)}
        wins=sum(1 for y in foldrec["v13_best"]["folds"] if foldrec["v13_best"]["folds"][y]>foldrec["published"]["folds"][y])
        foldrec["fold_years_won_vs_published"]=wins
        foldrec["confirmed_vs_published"]=(foldrec["v13_best"]["fold_compounded"]>foldrec["published"]["fold_compounded"] and wins>=6)
        confirm=foldrec
        print(f"CONFIRM: {confirm}",flush=True)
    out["confirmation_folds"]=confirm
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("DONE",flush=True)

if __name__=="__main__":
    main()
