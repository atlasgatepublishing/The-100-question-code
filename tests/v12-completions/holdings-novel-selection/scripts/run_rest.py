#!/usr/bin/env python3
"""PV1, PV2, PV4, X3 holdings-count sweeps (see RESULTS.md for frozen mappings)."""
import json, os, sys, random, statistics
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import COUNTS, ckey, period_stats, maxdd
BASE=os.path.dirname(os.path.abspath(__file__))
WIN4={"LONG":("2010-01-04","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),
 "CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20"),
 "CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
import os as _os
def _forms():
    o=_os.environ.get("ONLY","")
    return o.split(":")[0].split(",") if o else ("house","native")
def _counts():
    o=_os.environ.get("ONLY","")
    if not o or ":" not in o: return COUNTS
    want=o.split(":")[1].split(",")
    return [n for n in COUNTS if ckey(n) in want]
def finish(res, fname, tempo="month"):
    for form in list(res["forms"]):
        cells=res["forms"][form]; best=max((k for k in cells if not k.startswith("_")), key=lambda k: cells[k]["DECADE"]["final"])
        res["forms"][form]["_best_DECADE"]=best
        for k in {"5",best}:
            if k in cells: cells[k]["DECADE"]["period_stats_monthly"]=period_stats(cells[k]["DECADE"]["curve"])
        for k in list(cells):
            if k.startswith("_"): continue
            for w in list(cells[k]):
                if isinstance(cells[k][w],dict): cells[k][w].pop("curve",None)
    import sys as _s
    _s.stdout.write("RESULTJSON:"+json.dumps(res)+"\n"); print("DONE",fname,flush=True)
def cell(final,curve,costs,orders,halts):
    return {"final":round(final,2),"max_dd_pct":maxdd(curve),"costs":round(costs,2),"orders":orders,
            "halts":halts,"curve":[[d,round(v,2)] for d,v in curve]}

# ---------------- PV1: monthly ranked rotation (native form per frozen engine)
def do_pv1():
    import pv1_engine as E
    M=E.M
    def run_window(s,e,n,form,rng=None):
        E.START,E.END=s,e; E.DAYS=[d for d in E.CAL if s<=d<=e]
        cs=set(E.cadence_dates("monthly"))
        if rng is None:
            picker=lambda scores: sorted(scores, key=lambda t: -scores[t])[:n] if n else sorted(scores, key=lambda t: -scores[t])
        else:
            picker=lambda scores: rng.sample(sorted(scores), min(n,len(scores))) if n else sorted(scores)
        if form=="house":
            r=E.run_v9(cs,picker,n_hold=n)
            return cell(r["final"],r["curve"],r["costs"],r["orders"],len(r["halts"]))
        r=E.run_episode(100.0,85.0,s,cs,picker,n)
        return cell(r["final"],r["curve"],r["costs"],r["orders"],1 if r["halted"] else 0)
    res={"family":"novel-pv1-standing-bid","native_count":5,"cadence":"monthly","forms":{}}
    for form in _forms():
        cells={}
        for n in _counts():
            c={w:run_window(s,e,n,form) for w,(s,e) in WIN4.items()}
            s,e=WIN4["DECADE"]; finals=[run_window(s,e,n,form,rng=random.Random(sd))["final"] for sd in range(1,21)]
            real=c["DECADE"]["final"]
            c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
            cells[ckey(n)]=c; print("pv1",form,ckey(n),{w:c[w]["final"] for w in WIN4},"pl",c["placebos_DECADE"]["beaten"],flush=True)
        res["forms"][form]=cells
    finish(res,"cells_pv1.json")

# ---------------- PV2: event, ranked by vol_ratio, max-concurrent N, slice 1/N
def do_pv2():
    import pv2_engine as E
    M=E.M; ALLDAYS=set(E.CAL)
    def run_window(s,e,n,form,rng=None):
        E.START,E.END=s,e
        M.MAX_POS = n if n else 10**9; E.SLICE_N[0] = n if n else 5
        if rng is None:
            r=E.run_v9_cad(lambda a,b: E.build_ranked_plan_cad(a,b,ALLDAYS), ALLDAYS)
            taken=r["taken"]
            return cell(r["final"],r["curve"],r["costs"],r["orders"],len(r["halts"])), taken
        # placebo: needs taken slots from the ranked run of the same form/window
        raise RuntimeError
    def run_placebo(s,e,n,form,seed,taken):
        E.START,E.END=s,e
        M.MAX_POS = n if n else 10**9; E.SLICE_N[0] = n if n else 5
        rng=random.Random(seed); ep_taken=[list(t) for t in taken]
        def placebo_plan(a,b):
            slots=ep_taken.pop(0) if ep_taken else []
            pplan={}
            for slot in slots:
                pplan.setdefault(slot["entry_date"],[]).append({"ticker":rng.choice(M.POND),"signal_date":slot["signal_date"]})
            return pplan
        r=E.run_v9_cad(placebo_plan, ALLDAYS)
        return r["final"]
    def run_native(s,e,n,rng_taken=None):
        E.START,E.END=s,e
        M.MAX_POS = n if n else 10**9; E.SLICE_N[0] = n if n else 5
        plan=E.build_ranked_plan_cad(s,e,ALLDAYS)
        r=E.run_pot_cad(s,e,plan,ALLDAYS,label="ep1")
        return cell(r["final"],r["curve"],r["costs"],len(r["trades"]),1 if r["halted"] else 0), r["taken"]
    res={"family":"novel-pv2-last-seller","native_count":5,"cadence":"daily (event)","forms":{}}
    for form in _forms():
        cells={}
        for n in _counts():
            c={}; taken_dec=None
            for w,(s,e) in WIN4.items():
                if form=="house": cc,taken=run_window(s,e,n,form)
                else: cc,taken=run_native(s,e,n)
                c[w]=cc
                if w=="DECADE": taken_dec=taken
            s,e=WIN4["DECADE"]; finals=[]
            for sd in range(1,21):
                if form=="house": finals.append(run_placebo(s,e,n,form,sd,taken_dec))
                else:
                    rng=random.Random(sd); pplan={}
                    for slot in taken_dec:
                        pplan.setdefault(slot["entry_date"],[]).append({"ticker":rng.choice(M.POND),"signal_date":slot["signal_date"]})
                    E.START,E.END=s,e; M.MAX_POS=n if n else 10**9; E.SLICE_N[0]=n if n else 5
                    r=E.run_pot_cad(s,e,pplan,ALLDAYS,label="p")
                    finals.append(round(r["final"],2))
            real=c["DECADE"]["final"]
            c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
            cells[ckey(n)]=c; print("pv2",form,ckey(n),{w:c[w]["final"] for w in WIN4},"pl",c["placebos_DECADE"]["beaten"],flush=True)
        res["forms"][form]=cells
    finish(res,"cells_pv2.json")

# ---------------- PV4: event, gap-rank order, max-concurrent N, slice 1/N
def do_pv4():
    import pv4_engine as E
    M=E.M; ALLDAYS=set(E.CAL)
    def one(s,e,n,names_fn,form,start_cash=100.0):
        sched=M.window_events(E.EVENTS, E.PB, s, e)
        cap=n if n else 10**9; sn=n if n else 5
        r1=E.run_event_pot_cad(sched,s,e,names_fn(sched),ALLDAYS,start_cash=start_cash,floor=0.85*start_cash,n_cap=cap,slice_n=sn)
        if form=="native" or not r1["halted"]: return r1,[r1]
        elig=(date.fromisoformat(r1["halted"])+timedelta(days=90)).isoformat()
        if elig>e: return r1,[r1]
        sched2=M.window_events(E.EVENTS, E.PB, elig, e)
        r2=E.run_event_pot_cad(sched2,elig,e,names_fn(sched2),ALLDAYS,start_cash=r1["final"],floor=0.85*r1["final"],n_cap=cap,slice_n=sn)
        curve={}
        for ep in (r1,r2):
            for d,v in ep["curve"]: curve[d]=v
        for d in E.CAL:
            if r1["curve"] and r2["curve"] and r1["curve"][-1][0]<d<r2["curve"][0][0]: curve[d]=r1["final"]
        out=dict(r2); out["curve"]=sorted(curve.items()); out["costs"]=r1["costs"]+r2["costs"]
        out["trades"]=r1["trades"]+r2["trades"]; out["halts_n"]=2 if r2["halted"] else 1
        out["taken"]=r1["taken"]+r2["taken"]; return out,[r1,r2]
    def run_window(s,e,n,form,rng=None):
        if rng is None: nf=lambda sched:[ev["ticker"] for ev in sched]
        else: nf=lambda sched:[rng.choice([t for t in E.UNIVERSE if t!=ev["ticker"]]) for ev in sched]
        r,eps=one(s,e,n,nf,form)
        halts=getattr(r,"halts_n",None)
        h=r.get("halts_n", 1 if r["halted"] else 0) if isinstance(r,dict) else 0
        return cell(r["final"],r["curve"],r["costs"],len(r["trades"]),h)
    res={"family":"novel-pv4-overnight-confession","native_count":5,"cadence":"daily (event)","forms":{}}
    for form in _forms():
        cells={}
        for n in _counts():
            c={w:run_window(s,e,n,form) for w,(s,e) in WIN4.items()}
            s,e=WIN4["DECADE"]; finals=[run_window(s,e,n,form,rng=random.Random(sd))["final"] for sd in range(1,21)]
            real=c["DECADE"]["final"]
            c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
            cells[ckey(n)]=c; print("pv4",form,ckey(n),{w:c[w]["final"] for w in WIN4},"pl",c["placebos_DECADE"]["beaten"],flush=True)
        res["forms"][form]=cells
    finish(res,"cells_pv4.json")

# ---------------- X3: quarterly event basket of N worst QTD names (SPY otherwise)
def do_x3():
    import x3_engine as E
    M=E.M
    def ranked_n(n):
        def pick(ev,qtd):
            r=sorted(qtd.items(), key=lambda kv:(kv[1],kv[0]))
            return [t for t,_ in (r[:n] if n else r)]
        return pick
    def placebo_n(n,seed):
        rng=random.Random(seed)
        def pick(ev,qtd):
            pool=sorted(qtd); return rng.sample(pool, min(n,len(pool))) if n else list(pool)
        return pick
    def run_window(s,e,n,form,rng_seed=None):
        E.START,E.END=s,e
        picker=ranked_n(n) if rng_seed is None else placebo_n(n,rng_seed)
        if form=="house":
            r=E.run_v9_cad("daily",picker)
            return cell(r["final"],r["curve"],r["costs"],r["orders"],len(r["halts"]))
        evs=[ev for ev in E.ALL_EVENTS if s<=ev["exit"]<=e]
        r=E.simulate_cad(E.CAL,s,e,evs,picker,"daily",100.0,85.0)
        return cell(r["final"],r["curve"],r["costs"],len(r["trades"]),1 if r["halted"] else 0)
    res={"family":"novel-x3-window-dressing","native_count":5,"cadence":"event (quarter-end)","forms":{}}
    for form in _forms():
        cells={}
        for n in _counts():
            c={w:run_window(s,e,n,form) for w,(s,e) in WIN4.items()}
            s,e=WIN4["DECADE"]; finals=[run_window(s,e,n,form,rng_seed=sd)["final"] for sd in range(1,21)]
            real=c["DECADE"]["final"]
            c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
            cells[ckey(n)]=c; print("x3",form,ckey(n),{w:c[w]["final"] for w in WIN4},"pl",c["placebos_DECADE"]["beaten"],flush=True)
        res["forms"][form]=cells
    finish(res,"cells_x3.json")

if __name__=="__main__":
    which=sys.argv[1]
    {"pv1":do_pv1,"pv2":do_pv2,"pv4":do_pv4,"x3":do_x3}[which]()
