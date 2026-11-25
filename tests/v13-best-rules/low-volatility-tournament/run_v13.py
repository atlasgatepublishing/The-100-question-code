#!/usr/bin/env python3
"""V13 BEST RULES - low-volatility-tournament. Spec frozen in BEST-RULES-SPEC.md.
Two-tier (equities first, GLD/TLT fallback), vol60 ranking, inverse-vol weights,
monthly, 200d gate, NO floor. Program costs. 20-seed placebos. Roads LONG/DECADE/CONT/VAL.
Shared inputs read-only; writes only in this folder."""
import bisect, json, os, random
from datetime import date
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/workspace/stock-app/backtests")
CACHE = os.path.join(ROOT, "v3", "tournament2-data")
LONGD = os.path.join(ROOT, "v12-completions", "low-volatility-tournament", "data_long")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
EQUITIES = ["SPY", "QQQ", "IWM"]
START = 100.0; COST = 0.001; SELL_FEE = 0.01
ROADS = {"LONG": (date(2010,1,4), date(2026,11,20)), "DECADE": (date(2016,11,21), date(2026,11,20)),
         "CONT": (date(2019,1,2), date(2026,11,20)), "VAL": (date(2023,1,3), date(2026,11,20))}

def read_csv(p):
    df = pd.read_csv(p); df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date","open","high","low","close","volume"]].drop_duplicates("date").sort_values("date").reset_index(drop=True)

def prepare(df):
    df = df.copy()
    df["ma200"] = df["close"].rolling(200).mean()
    df["vol60"] = df["close"].pct_change().rolling(60).std()
    df.attrs["pos"] = {d:i for i,d in enumerate(df["date"])}; df.attrs["dates"] = df["date"].tolist()
    return df

class Store:
    def __init__(self, base):
        self.data = {s: prepare(read_csv(os.path.join(base, f"{s}.csv"))) for s in UNIVERSE}
        self.cal = self.data["SPY"]["date"].tolist()
    def bar(self, sym, d, f):
        df = self.data[sym]; i = df.attrs["pos"].get(d)
        if i is None: return None
        v = df[f].iloc[i]
        return None if (v is None or (isinstance(v,float) and np.isnan(v))) else float(v)
    def last_close(self, sym, d):
        df = self.data[sym]; j = bisect.bisect_right(df.attrs["dates"], d)-1
        return None if j < 0 else float(df["close"].iloc[j])

class Pot:
    def __init__(self, store): self.store=store; self.cash=START; self.pos={}; self.costs=0.0; self.orders=0
    def buy(self, sym, price, notional):
        if not price or price<=0 or notional<=0: return
        c = notional*COST
        if notional+c > self.cash: notional = self.cash/(1+COST); c = notional*COST
        if notional < 0.01: return
        self.cash -= notional+c; self.pos[sym]=self.pos.get(sym,0.0)+notional/price; self.costs+=c; self.orders+=1
    def sell(self, sym, price, shares=None):
        if not price or price<=0 or sym not in self.pos: return
        sh = self.pos[sym] if shares is None else min(shares, self.pos[sym])
        if sh<=0: return
        val = sh*price; c = val*COST+SELL_FEE; self.cash += val-c; self.costs+=c; self.orders+=1
        self.pos[sym]-=sh
        if self.pos[sym]<=1e-9: del self.pos[sym]
    def liquidate(self, d, at_open):
        for s in list(self.pos): 
            px = self.store.bar(s,d,"open") if at_open else self.store.bar(s,d,"close")
            self.sell(s, px if px else self.store.last_close(s,d))
    def equity(self, d, at_open=False):
        eq = self.cash
        for s,sh in self.pos.items():
            px = self.store.bar(s,d,"open" if at_open else "close") or self.store.last_close(s,d)
            eq += sh*px
        return eq
    def pos_val_open(self, sym, d):
        if sym not in self.pos: return 0.0
        px = self.store.bar(sym,d,"open") or self.store.last_close(sym,d)
        return self.pos[sym]*px

def tiered(store, sig_day, rng=None):
    """Return (targets list, vols dict) per spec tiering."""
    elig = {}
    for s in UNIVERSE:
        c = store.bar(s,sig_day,"close"); ma = store.bar(s,sig_day,"ma200"); v = store.bar(s,sig_day,"vol60")
        if c is not None and ma is not None and v is not None and c>ma: elig[s]=v
    eq = sorted([s for s in EQUITIES if s in elig], key=lambda s: elig[s])
    df_ = sorted([s for s in UNIVERSE if s not in EQUITIES and s in elig], key=lambda s: elig[s])
    if rng is not None:
        pool_eq, pool_df = eq[:], df_[:]; rng.shuffle(pool_eq); rng.shuffle(pool_df)
        if len(eq)>=2: t = pool_eq[:2]
        elif len(eq)==1: t = pool_eq[:1]+pool_df[:1]
        else: t = pool_df[:2]
        return t, elig
    if len(eq)>=2: t = eq[:2]
    elif len(eq)==1: t = eq[:1]+df_[:1]
    else: t = df_[:2]
    return t, elig

def monthly_exec(days):
    out, prev = [], None
    for d in days:
        k=(d.year,d.month)
        if k!=prev: out.append(d); prev=k
    return out

def run_road(store, days, seed=None):
    rng = random.Random(seed) if seed is not None else None
    exec_set = set(monthly_exec(days)); didx = {d:i for i,d in enumerate(days)}
    pot = Pot(store); curve=[]
    for d in days:
        if d in exec_set:
            i = didx[d]
            if i>0:
                targets, vols = tiered(store, days[i-1], rng)
                for s in list(pot.pos):
                    if s not in targets: pot.sell(s, store.bar(s,d,"open"))
                if targets:
                    eqv = pot.equity(d, at_open=True)
                    inv = {s: 1.0/vols[s] for s in targets}; tot = sum(inv.values())
                    for s in targets:
                        o = store.bar(s,d,"open")
                        if o is None: continue
                        delta = eqv*inv[s]/tot - pot.pos_val_open(s,d)
                        if delta>0.25: pot.buy(s,o,delta)
                        elif delta<-0.25: pot.sell(s,o,shares=(-delta)/o)
        curve.append((d, pot.equity(d)))
    if pot.pos: pot.liquidate(days[-1], at_open=False)
    final = pot.cash
    if curve: curve[-1]=(days[-1], final)
    peak, maxdd = START, 0.0
    for _,e in curve: peak=max(peak,e); maxdd=max(maxdd,(peak-e)/peak if peak>0 else 0)
    years=(days[-1]-days[0]).days/365.25
    cagr=(final/START)**(1/years)-1 if final>0 else -1
    return {"final": round(final,2), "cagr_pct": round(cagr*100,2), "max_dd_pct": round(maxdd*100,2),
            "costs": round(pot.costs,2), "orders": pot.orders, "halts": [],
            "curve": [[d.isoformat(), round(e,4)] for d,e in curve]}

def spy_bench(store, days):
    o0=store.bar("SPY",days[0],"open"); cN=store.bar("SPY",days[-1],"close")
    sh=(START/(1+COST))/o0; net=sh*cN*(1-COST)-SELL_FEE
    peak,dd=None,0.0
    for d in days:
        v=store.bar("SPY",d,"close")/o0*START; peak=v if peak is None else max(peak,v); dd=max(dd,(peak-v)/peak)
    return {"net": round(net,2), "max_dd_pct": round(dd*100,2)}

def period_stats(curve):
    # monthly periods: mark at each month-end (last curve point per month)
    marks=[(curve[0][0], START)]; seen={}
    for ds,e in curve: seen[ds[:7]]=(ds,e)
    pts=[(curve[0][0],START)]+sorted(seen.values())
    rets=[]; 
    for (d0,e0),(d1,e1) in zip(pts, pts[1:]):
        if e0>0: rets.append(((d1), (e1/e0-1)*100))
    if not rets: return {}
    vals=[r for _,r in rets]
    los=0; worst_run=0
    for v in vals:
        los = los+1 if v<0 else 0; worst_run=max(worst_run,los)
    # longest stretch between new highs (days, from daily curve)
    peak=-1; peak_date=None; longest=0; import datetime as _dt
    for ds,e in curve:
        dd=_dt.date.fromisoformat(ds)
        if e>=peak: peak=e; peak_date=dd
        elif peak_date: longest=max(longest,(dd-peak_date).days)
    return {"periods": len(vals), "pct_positive": round(100*sum(1 for v in vals if v>0)/len(vals),1),
            "median_pct": round(float(np.median(vals)),2), "mean_pct_secondary": round(float(np.mean(vals)),2),
            "best_pct": round(max(vals),2), "best_end": max(rets,key=lambda x:x[1])[0],
            "worst_pct": round(min(vals),2), "worst_end": min(rets,key=lambda x:x[1])[0],
            "longest_losing_streak_periods": worst_run, "longest_days_between_new_highs": longest}

def main():
    cache=Store(CACHE); long_store=Store(LONGD)
    stores={"LONG": long_store, "DECADE": cache, "CONT": cache, "VAL": cache}
    roads={}
    for name,(ws,we) in ROADS.items():
        store=stores[name]; days=[d for d in store.cal if ws<=d<=we]
        r=run_road(store,days)
        twins=[run_road(store,days,seed=s)["final"] for s in range(20)]
        beaten=sum(1 for t in twins if r["final"]>t)
        bench=spy_bench(store,days)
        roads[name]={"window":[days[0].isoformat(),days[-1].isoformat()],"trading_days":len(days),
            "final":r["final"],"cagr_pct":r["cagr_pct"],"max_dd_pct":r["max_dd_pct"],"costs":r["costs"],
            "orders":r["orders"],"halts":r["halts"],"spy_priceonly_net_same_plumbing":bench["net"],
            "spy_priceonly_max_dd_pct":bench["max_dd_pct"],"placebo_beaten":f"{beaten}/20",
            "placebo_finals":twins,"placebo_median":round(float(np.median(twins)),2),
            "period_stats_monthly":period_stats(r["curve"]),"equity_curve":r["curve"]}
        print(f"{name}: ${r['final']:.2f} CAGR {r['cagr_pct']:+.2f}% DD {r['max_dd_pct']:.2f}% costs ${r['costs']:.2f} orders {r['orders']} placebo {beaten}/20 SPYnet ${bench['net']:.2f}", flush=True)
    out={"slug":"low-volatility-tournament","program":"v13-best-rules","spec":"BEST-RULES-SPEC.md (frozen before run)",
        "design":"two-tier equities-first / defensive fallback; vol60; inverse-vol weights; monthly; 200d gate; NO floor",
        "costs":"0.10%/side + $0.01/sell","roads":roads,
        "program_references":{"spy_dividend_adjusted":{"LONG":822.94,"DECADE":367.80,"CONT":313.62,"VAL":187.77},
                              "champion_vm":{"LONG":1415.62,"DECADE":667.35,"CONT":544.47,"VAL":288.05},
                              "published_tournament_form":{"LONG":412.18,"DECADE":236.63,"CONT":186.44,"VAL":161.60}}}
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("wrote results.json")

if __name__=="__main__": main()
