import importlib.util, json, os, pickle, statistics, time, sys
HERE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/canslim-oneil-judgment/run_judgment.py")
spec=importlib.util.spec_from_file_location("cj",SRC); M=importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
t0=time.time()
cache=pickle.load(open(os.path.join(HERE,"prep_cache.pkl"),"rb"))
rs, mstates, cands = cache["rs"], cache["mstates"], cache["cands"]
series_by,funds={},{}
for t in M.lr.POOL:
    bars=M.load_bars(t)
    if not bars or len(bars)<300: continue
    facts=M.load_facts_for(t)
    if facts is None: continue
    series_by[t]=M.Series(bars); funds[t]=M.Fund(facts)
spy=series_by.get("SPY") or M.Series(M.load_bars("SPY")); series_by["SPY"]=spy
master=spy.dates
print("load+cache",round(time.time()-t0),len(series_by),flush=True)
ROADS=M.ROADS
CONF={"CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
def period_stats(curve):
    bym={}
    for d,v in curve: bym[d[:7]]=v
    keys=sorted(bym); rets=[]; prev=100.0
    for k in keys: rets.append(bym[k]/prev-1); prev=bym[k]
    if not rets: return None
    prof=sum(1 for r in rets if r>0); worst=cur=0
    for r in rets: cur=cur+1 if r<=0 else 0; worst=max(worst,cur)
    peak,since,longest=100.0,0,0
    for k in keys:
        if bym[k]>=peak: peak=bym[k]; longest=max(longest,since); since=0
        else: since+=1
    longest=max(longest,since)
    return {"period":"calendar month","n_periods":len(rets),"pct_profitable":round(100*prof/len(rets),1),
            "median_pct":round(statistics.median(rets)*100,2),"mean_pct_secondary_average":round(statistics.mean(rets)*100,2),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "longest_losing_run_periods":worst,"longest_stretch_between_new_highs_periods":longest}
def run_cell(n,start,end,with_placebos):
    if n is None: M.MAX_POS=10**9; M.POS_FRAC=0.20; M.PILOT_FRAC=0.10
    elif n=="NATIVE6": M.MAX_POS=6; M.POS_FRAC=0.20; M.PILOT_FRAC=0.10
    else: M.MAX_POS=n; M.POS_FRAC=1.0/n; M.PILOT_FRAC=0.5/n
    days=[d for d in master if d<=end]
    r=M.simulate(days,series_by,rs,mstates,cands,funds,start,end)
    cell={"final":r["final"],"costs":r["costs"],"orders":r["orders"],"halted":r["halted"],
          "max_dd_pct":r["max_dd_pct"],"n_entries":len(r["entries"]),"entries":r["entries"],"curve":r["curve"]}
    if with_placebos:
        pfin=[]
        for seed in range(20):
            pr=M.simulate(days,series_by,rs,mstates,cands,funds,start,end,placebo_seed=seed,real_entries=r["entries"])
            pfin.append(pr["final"])
        cell["placebo_finals"]=pfin; cell["placebo_beaten"]=sum(1 for x in pfin if r["final"]>x)
    return cell
COUNTS=["NATIVE6",3,5,8,10,15,20,30,None,1,2]
for n in COUNTS:
    key="ALL" if n is None else str(n)
    path=os.path.join(HERE,f"cells_{key}.json")
    if os.path.exists(path): print("skip",key,flush=True); continue
    cell={}
    complete=True
    for w,(a,b) in {**ROADS,**CONF}.items():
        wpath=os.path.join(HERE,f"cells_{key}_{w}.json")
        if os.path.exists(wpath):
            cell[w]=json.load(open(wpath))[w]; print(f"  n={key} {w} cached",flush=True); continue
        c=run_cell(n,a,b,True)
        wc={k:v for k,v in c.items() if k!="curve"}
        if w=="LONG":
            wc["period_stats_monthly"]=period_stats(c["curve"])
        cell[w]=wc
        json.dump({w:wc},open(wpath,"w"),indent=1)
        print(f"  n={key} {w} {c['final']} e{c['n_entries']} p{c['placebo_beaten']} SAVED ({round(time.time()-t0)}s)",flush=True)
    json.dump({key:cell},open(path,"w"),indent=1)
    print(f"n={key} ASSEMBLED ({round(time.time()-t0)}s)",flush=True)
print("ALL CHUNKS DONE",round(time.time()-t0),flush=True)
