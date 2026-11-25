#!/usr/bin/env python3
"""v10 GREAT RETEST — sector-rotation (tournament style F).
Monthly top-2 of 10 sector ETFs by 63-day return among those above their
200-day average, equal weight, all cash if none qualify (tournament.py F).
Integrity: original ladder-era floor, no restarts, DECADE, split-adjusted bars.
Sweep: DECADE x 7 cadences, uniform cadence definition (SPEC), $100/cell,
program costs (0.10%/side + $0.01/sell order), v9 protections (plain -15%
floor per episode, 90-calendar-day cash sit, one restart at next regular
decision point under episode-2 -15% floor, second halt ends run).
Placebos: 20 seeds/cell — random 2 picks from the same qualifying set at the
same cadence, same sizing/costs/protections. Seeds 2000..2019.
Data: read-only shared cache backtests/v2/tournament-data/ (SPY + 10 sector
ETFs only loaded). Split-adjusted, NOT dividend-adjusted (tournament conv.).
"""
import json, os, sys
from datetime import date, timedelta
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v2", "tournament-data")
SECTORS = ["XLK","XLF","XLE","XLV","XLI","XLY","XLP","XLU","XLB","XLRE"]
START_CASH=100.0; COST_RATE=0.001; SELL_FEE=0.01
TEST_START=date(2016,11,21); TEST_END=date(2026,11,20)

def load(sym):
    df=pd.read_csv(os.path.join(DATA,f"{sym}.csv"))
    df["date"]=pd.to_datetime(df["date"]).dt.date
    return df

def build():
    raw={s:load(s) for s in ["SPY"]+SECTORS}
    spy_dates=raw["SPY"]["date"]; frames={}
    for sym,df in raw.items():
        d=df.set_index("date").reindex(spy_dates)
        d[["open","high","low","close"]]=d[["open","high","low","close"]].ffill()
        d["volume"]=d["volume"].fillna(0); d=d.reset_index().rename(columns={"index":"date"})
        d["sma200"]=d["close"].rolling(200).mean(); frames[sym]=d
    dates=list(spy_dates); pos_of={d:i for i,d in enumerate(dates)}
    test=[d for d in dates if TEST_START<=d<=TEST_END]
    return frames,dates,pos_of,test

FRAMES,DATES,POS_OF,TEST_DATES=build()

class PF:
    def __init__(self):
        self.cash=START_CASH; self.lots={}; self.trades=[]; self.costs=0.0
        self.halt_pending=False
    def held(self): return [s for s,l in self.lots.items() if sum(x["sh"] for x in l)>1e-12]
    def shares(self,s): return sum(x["sh"] for x in self.lots.get(s,[]))
    def equity(self,pos,field="close"):
        t=self.cash
        for s in self.held(): t+=self.shares(s)*float(FRAMES[s][field].iloc[pos])
        return t
    def buy(self,d,pos,sym,price,target):
        if price<=0 or target<=0: return
        v=min(target, self.cash/(1+COST_RATE))
        if v<1.0: return
        c=COST_RATE*v; self.cash-=v+c; self.costs+=c
        self.lots.setdefault(sym,[]).append({"sh":v/price})
        self.trades.append({"date":str(d),"symbol":sym,"side":"buy","price":round(price,4),"value":round(v,2),"cost":round(c,4)})
    def sell(self,d,pos,sym,price,shares_to_sell=None):
        held=self.shares(sym)
        if held<=1e-12 or price<=0: return
        if shares_to_sell is None: shares_to_sell=held
        shares_to_sell=min(shares_to_sell,held)
        v=shares_to_sell*price; c=COST_RATE*v+SELL_FEE
        self.cash+=v-c; self.costs+=c
        rem=shares_to_sell; lots=self.lots.get(sym,[])
        while rem>1e-12 and lots:
            take=min(lots[0]["sh"],rem); lots[0]["sh"]-=take; rem-=take
            if lots[0]["sh"]<=1e-12: lots.pop(0)
        if not lots: self.lots.pop(sym,None)
        self.trades.append({"date":str(d),"symbol":sym,"side":"sell","price":round(price,4),"value":round(v,2),"cost":round(c,4)})
    def liquidate(self,d,pos):
        for s in list(self.held()): self.sell(d,pos,s,float(FRAMES[s]["open"].iloc[pos]))

def cadence_positions(cadence):
    """Indices into TEST_DATES that are decision dates, per SPEC uniform def."""
    out=[]
    if cadence=="daily": return list(range(len(TEST_DATES)))
    seen=set()
    for i,d in enumerate(TEST_DATES):
        if cadence=="weekly": key=(d.isocalendar()[0],d.isocalendar()[1])
        elif cadence=="biweekly":
            # first trading day of every second week, anchored on first week
            wk=(d-TEST_DATES[0]).days//7; key=("bw",wk//2, (d.weekday())) # placeholder replaced below
            key=None
        elif cadence=="monthly": key=(d.year,d.month)
        elif cadence=="quarterly": key=(d.year,(d.month-1)//3)
        elif cadence=="semiannual": key=(d.year,(d.month-1)//6)
        elif cadence=="annual": key=(d.year,)
        if cadence=="biweekly":
            # group by ISO week index from start; take first day of even weeks
            wk=((d-TEST_DATES[0]).days)//7
            # first trading day of a week = first date with that (year,week)
            wkey=(d.isocalendar()[0],d.isocalendar()[1])
            if wkey in seen: continue
            seen.add(wkey)
            # week ordinal
            if (len([1 for x in seen])%2)==1: out.append(i)
            continue
        if key in seen: continue
        seen.add(key); out.append(i)
    return out

def scored(prev, rng=None):
    sc=[]
    for sym in SECTORS:
        df=FRAMES[sym]
        if prev-63<0: continue
        cp=float(df["close"].iloc[prev]); s200=df["sma200"].iloc[prev]; c63=float(df["close"].iloc[prev-63])
        if np.isnan(s200) or c63<=0: continue
        if cp>s200: sc.append((sym, cp/c63-1))
    sc.sort(key=lambda x:-x[1])
    if rng is None: return [s for s,_ in sc[:2]]
    if len(sc)<=2: return [s for s,_ in sc]
    idx=rng.choice(len(sc), size=2, replace=False)
    return [sc[i][0] for i in idx]

def rebalance(pf,d,pos,picks):
    eq_open=pf.equity(pos,"open")
    target=eq_open/len(picks) if picks else 0.0
    for sym in list(pf.held()):
        if sym not in picks: pf.sell(d,pos,sym,float(FRAMES[sym]["open"].iloc[pos]))
    for sym in picks:
        px=float(FRAMES[sym]["open"].iloc[pos]); cur=pf.shares(sym)*px
        if cur>target+0.5: pf.sell(d,pos,sym,px,shares_to_sell=(cur-target)/px)
    for sym in picks:
        px=float(FRAMES[sym]["open"].iloc[pos]); cur=pf.shares(sym)*px; deficit=target-cur
        if deficit>0.5: pf.buy(d,pos,sym,px,deficit)

def run(cadence, mode, seed=None):
    """mode: 'original' (ladder floor, no restart) or 'v9'."""
    pf=PF(); rng=np.random.default_rng(seed) if seed is not None else None
    dec=set(cadence_positions(cadence))
    curve=[]; halts=[]; floor=85.0; episode=1; restart=False
    halted=False; halt_trigger=None; waiting_until=None; final_holdings=[]
    for t,d in enumerate(TEST_DATES):
        pos=POS_OF[d]
        if pf.halt_pending:
            pf.liquidate(d,pos)
            halts.append({"episode":episode,"trigger_date":str(halt_trigger),"liquidation_date":str(d),
                          "holdings_at_halt":final_holdings})
            curve.append((str(d),round(pf.equity(pos),4)))
            if mode=="original" or episode==2:
                halted=True; break
            episode=2; restart=True; pf.halt_pending=False
            waiting_until=d+timedelta(days=90)
            floor=0.85*pf.cash  # episode-2 floor from restart balance (cash now)
            continue
        if waiting_until is not None:
            if d<waiting_until or t not in dec:
                curve.append((str(d),round(pf.equity(pos),4))); continue
            waiting_until=None  # restart at this regular decision point
        if t in dec:
            picks=scored(pos-1, rng)
            rebalance(pf,d,pos,picks)
        eq=pf.equity(pos)
        curve.append((str(d),round(eq,4)))
        # floor check at close
        if mode=="original":
            if eq>=150: floor=max(floor,125.0)
            elif eq>=125: floor=max(floor,100.0)
        if eq<=floor:
            pf.halt_pending=True; halt_trigger=d; final_holdings=pf.held()
            if t==len(TEST_DATES)-1: halted=True
    if pf.halt_pending and not halted and mode!="original":
        pass
    final=curve[-1][1] if curve else pf.cash
    peak=START_CASH; mdd=0.0
    for _,v in curve:
        peak=max(peak,v); mdd=max(mdd,(peak-v)/peak if peak>0 else 0)
    days=(TEST_DATES[-1]-TEST_DATES[0]).days if not halted else (date.fromisoformat(curve[-1][0])-TEST_DATES[0]).days
    yrs=max(days,1)/365.25
    cagr=(final/START_CASH)**(1/yrs)-1 if final>0 else -1
    return {"final":round(final,2),"cagr_pct":round(cagr*100,2),"max_dd_pct":round(mdd*100,2),
            "costs":round(pf.costs,2),"orders":len(pf.trades),"halts":len(halts),
            "halt_records":halts,"restart":restart,"second_halt":len(halts)>=2,
            "equity_curve":curve,"trades":pf.trades,
            "end_date":curve[-1][0],"final_holdings":pf.held()}

def spy_price_only():
    p0=POS_OF[TEST_DATES[0]]; p1=POS_OF[TEST_DATES[-1]]
    o=float(FRAMES["SPY"]["open"].iloc[p0]); c=float(FRAMES["SPY"]["close"].iloc[p1])
    gross=100/o*c; bv=100/(1+COST_RATE); sh=bv/o; sv=sh*c; net=sv-(COST_RATE*sv+SELL_FEE)
    return round(gross,2), round(net,2)

if __name__=="__main__":
    # integrity first
    integ=run("monthly","original")
    print("INTEGRITY monthly/original:", {k:integ[k] for k in ("final","costs","orders","halts","end_date")}, integ["halt_records"])
    print("SPY price-only gross/net:", spy_price_only())
    if "--integrity-only" in sys.argv: sys.exit(0)
    results={"slug":"sector-rotation","integrity_run":integ}
    cells={}
    for cad in ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]:
        r=run(cad,"v9")
        twins=[]
        for s in range(20):
            tr=run(cad,"v9",seed=2000+s); twins.append(tr["final"])
        beaten=sum(1 for x in twins if r["final"]>x)
        cell={k:r[k] for k in ("final","cagr_pct","max_dd_pct","costs","orders","halts","restart","second_halt","halt_records","equity_curve")}
        cell["placebo_twin_finals"]=twins; cell["placebo_beaten"]=beaten
        with open(os.path.join(HERE,"cells",f"{cad}.json"),"w") as f: json.dump(cell,f)
        cells[cad]={"final":r["final"],"cagr_pct":r["cagr_pct"],"max_dd_pct":r["max_dd_pct"],
                    "halts":r["halts"],"restart":r["restart"],"second_halt":r["second_halt"],
                    "costs":r["costs"],"orders":r["orders"],"placebo_beaten":beaten,
                    "placebo_twin_finals":twins}
        print(cad, r["final"], "halts",r["halts"], r["halt_records"], "placebo beaten",beaten,"/20")
    results["cells"]=cells
    with open(os.path.join(HERE,"_sweep_raw.json"),"w") as f: json.dump(results,f)
    print("done")
