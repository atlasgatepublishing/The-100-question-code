import importlib.util, time, os, pickle, sys
SRC=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/canslim-oneil-judgment/run_judgment.py")
spec=importlib.util.spec_from_file_location("cj",SRC); M=importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
t0=time.time()
series_by,funds={},{}
for t in M.lr.POOL:
    bars=M.load_bars(t)
    if not bars or len(bars)<300: continue
    facts=M.load_facts_for(t)
    if facts is None: continue
    series_by[t]=M.Series(bars); funds[t]=M.Fund(facts)
print("load",round(time.time()-t0),len(series_by),flush=True)
spy=series_by.get("SPY") or M.Series(M.load_bars("SPY")); series_by["SPY"]=spy
master=spy.dates
rs=M.compute_rs({t:s for t,s in series_by.items() if t!="SPY"},master)
print("rs",round(time.time()-t0),flush=True)
ms=M.market_states(spy)
print("ms",round(time.time()-t0),flush=True)
cands={t:M.breakout_candidates(s) for t,s in series_by.items() if t!="SPY"}
print("cands",round(time.time()-t0),sum(len(v) for v in cands.values()),flush=True)
out=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/holdings-canslim-oneil-judgment/prep_cache.pkl")
with open(out,"wb") as f: pickle.dump({"rs":rs,"mstates":ms,"cands":cands,"names":sorted(series_by)},f)
print("saved",round(time.time()-t0),os.path.getsize(out),flush=True)
