#!/usr/bin/env python3
"""Slice H3: count sweeps for vm-trendgate, vm-panicgate, vm-volscale on the
champion chassis (holdings-champion-vm plumbing, read-only import).
Overlay = per-selection-date invested fraction frac[d]:
 trendgate: 0 if SPY close <= trailing 200d MA at selection else 1
 panicgate: 0.5 if panic (SPY trailing 504d ret <0 AND 60d vol > expanding
            median of 60d vol) else 1  [v12 construction spec]
 volscale:  min(1, 0.12 / ann. vol of trailing 126d equal-weight daily
            returns of the new picks), re-evaluated MONTHLY (v12 frozen
            form: monthly rescale, quarterly picks); monthly non-pick
            dates rescale existing book to frac.
"""
import importlib.util, json, math, os, random, statistics, sys, time
BT = os.path.expanduser("~/workspace/stock-app/backtests")
OUT = os.path.join(BT, "v12-completions/holdings-vm-trendgate/scripts/vm_results.json")
src = open(os.path.join(BT,"v12-completions/holdings-champion-vm/run_sweep.py")).read()
src = src.replace("def run_episode(pb, dec, sel_set, start, end, start_cash, floor, count,\n                placebo_rng=None):",
"def run_episode(pb, dec, sel_set, start, end, start_cash, floor, count,\n                placebo_rng=None, frac_map=None, scale_set=None):")
src = src.replace("""                pv = portfolio_close(d)
                each = pv / k
                pending = {t: each for t in picks}""",
"""                pv = portfolio_close(d)
                fr = (frac_map or {}).get(d, 1.0)
                each = pv / k * fr
                pending = {t: each for t in picks}""")
src = src.replace("""        if d in sel_set:""",
"""        if scale_set is not None and d in scale_set and d not in sel_set and positions:
            fr = (frac_map or {}).get(d, 1.0)
            pv = portfolio_close(d)
            cur_inv = pv - cash
            if cur_inv > 0.01:
                tgt_inv = fr * pv
                ratio = tgt_inv / cur_inv
                if abs(ratio - 1.0) > 0.005:
                    pending = {t: positions[t] * pb.close_on_or_before(t, d) * ratio
                               for t in positions if pb.close_on_or_before(t, d)}
        if d in sel_set:""")
src = src.replace("def run_house(pb, dec, sel_dates, start, end, count, placebo_seed=None):",
"def run_house(pb, dec, sel_dates, start, end, count, placebo_seed=None, frac_map=None, scale_set=None):")
src = src.replace("r1 = run_episode(pb, dec, sel_set, start, end, START_CASH, floor1,\n                     count, placebo_rng=rng)",
"r1 = run_episode(pb, dec, sel_set, start, end, START_CASH, floor1,\n                     count, placebo_rng=rng, frac_map=frac_map, scale_set=scale_set)")
src = src.replace("r2 = run_episode(pb, dec, sel_set, restart, end, cash,\n                     round(0.85 * cash, 2), count, placebo_rng=rng)",
"r2 = run_episode(pb, dec, sel_set, restart, end, cash,\n                     round(0.85 * cash, 2), count, placebo_rng=rng, frac_map=frac_map, scale_set=scale_set)")
src = src.replace("def run_native(pb, dec, sel_dates, start, end, count, placebo_seed=None):",
"def run_native(pb, dec, sel_dates, start, end, count, placebo_seed=None, frac_map=None, scale_set=None):")
src = src.replace("r = run_episode(pb, dec, set(sel_dates), start, end, START_CASH, None,\n                    count, placebo_rng=rng)",
"r = run_episode(pb, dec, set(sel_dates), start, end, START_CASH, None,\n                    count, placebo_rng=rng, frac_map=frac_map, scale_set=scale_set)")
ns = {"__file__": os.path.join(BT,"v12-completions/holdings-champion-vm/run_sweep.py"), "__name__":"champion_patched"}
exec(compile(src, "champion_patched", "exec"), ns)
COUNTS = ns["COUNTS"]; END = ns["END"]
ROADS = {"LONG":("2010-01-04",END),"DECADE":("2016-11-21",END),
         "CONT":("2019-01-02",END),"VAL":("2023-01-03",END)}

def spy_series(pb):
    bars = pb.bars["SPY"]; return [b["d"] for b in bars], [b["c"] for b in bars]

def frac_trendgate(pb, sel):
    ds, cs = spy_series(pb); idx={d:i for i,d in enumerate(ds)}; out={}
    for d in sel:
        i = idx.get(d)
        if i is None or i < 200: out[d]=1.0; continue
        ma = sum(cs[i-200:i])/200.0
        out[d] = 0.0 if cs[i] <= ma else 1.0
    return out

def frac_panicgate(pb, sel):
    ds, cs = spy_series(pb); idx={d:i for i,d in enumerate(ds)}
    rets=[None]+[cs[i]/cs[i-1]-1 for i in range(1,len(cs))]
    vol60={}
    for i in range(60, len(cs)):
        vol60[ds[i]] = statistics.pstdev(rets[i-59:i+1])*math.sqrt(252)
    out={}
    for d in sel:
        i = idx.get(d)
        if i is None or i < 504: out[d]=1.0; continue
        bear = cs[i]/cs[i-504]-1 < 0
        hist=[v for dd,v in vol60.items() if dd<=d]
        hv = vol60.get(d,0) > statistics.median(hist) if hist else False
        out[d] = 0.5 if (bear and hv) else 1.0
    return out

def month_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start<=d<=end and d[:7] not in seen:
            seen.add(d[:7]); out.append(d)
    return out

def frac_volscale(pb, dec, mdates, sel_set):
    import bisect
    sel_sorted = sorted(sel_set); out={}; picks=[]
    for d in mdates:
        j = bisect.bisect_right(sel_sorted, d)-1
        if j>=0: picks = dec[sel_sorted[j]]["ranked"]
        if not picks: out[d]=1.0; continue
        ds = pb.dlist["SPY"]; i = pb.didx["SPY"].get(d)
        if i is None or i<127: out[d]=1.0; continue
        win = ds[i-126:i+1]
        daily=[]
        for a,b in zip(win[:-1], win[1:]):
            rs=[]
            for t in picks:
                ca, cb = pb.close_on_or_before(t,a), pb.close_on_or_before(t,b)
                if ca and cb: rs.append(cb/ca-1)
            if rs: daily.append(sum(rs)/len(rs))
        if len(daily)<60: out[d]=1.0; continue
        vol = statistics.stdev(daily)*math.sqrt(252)
        out[d] = min(1.0, 0.12/vol) if vol>0 else 1.0
    return out

def fam_frac(fam, pbx, decx, s, e):
    sel = ns["quarter_dates"](pbx, s, e); sel_set=set(sel)
    if fam=="trendgate": return sel, frac_trendgate(pbx, sel), None
    if fam=="panicgate": return sel, frac_panicgate(pbx, sel), None
    md = month_dates(pbx, s, e)
    return sel, frac_volscale(pbx, decx, md, sel_set), set(md)

def main():
    t0=time.time()
    pb, pe, ps, uni = ns["build_fixed_inputs"]()
    all_sel = ns["quarter_dates"](pb, "2016-11-21", END)
    dec_fixed = ns["compute_decisions"](pb, pe, ps, uni, all_sel)
    print("fixed decisions", time.time()-t0, flush=True)
    pbL, peL, psL, pondL, info = ns["build_long_inputs"]()
    selL = ns["quarter_dates"](pbL, "2010-01-04", END)
    dec_long = ns["compute_decisions"](pbL, peL, psL, pondL, selL)
    print("long decisions", time.time()-t0, flush=True)
    for rn,(s,e) in ROADS.items():
        pbx, decx = (pbL, dec_long) if rn=="LONG" else (pb, dec_fixed)
        sel = ns["quarter_dates"](pbx, s, e)
        r = ns["run_house"](pbx, decx, sel, s, e, 5)
        print("INTEGRITY", rn, round(r["final"],2), flush=True)
    fams = {}
    if os.path.exists(OUT):
        fams = json.load(open(OUT))
    for fam in ("trendgate","panicgate","volscale"):
        if fam in fams: continue
        res = {"roads":{}}
        for rn,(s,e) in ROADS.items():
            pbx, decx = (pbL, dec_long) if rn=="LONG" else (pb, dec_fixed)
            sel, fm, ss = fam_frac(fam, pbx, decx, s, e)
            cell={}
            for c in COUNTS:
                h = ns["run_house"](pbx, decx, sel, s, e, c, frac_map=fm, scale_set=ss)
                n = ns["run_native"](pbx, decx, sel, s, e, c, frac_map=fm, scale_set=ss)
                cell[str(c)] = {"house":{"final":round(h["final"],2),"costs":round(h["costs"],2),"halts":h["halts"],"max_dd":ns["diagnostics"](h["curve"])["max_dd_pct"],"curve":h["curve"]},
                                "native":{"final":round(n["final"],2),"costs":round(n["costs"],2),"max_dd":ns["diagnostics"](n["curve"])["max_dd_pct"]}}
            if rn in ("DECADE","LONG"):
                for c in COUNTS:
                    finals=[]
                    for seed in range(1,21):
                        pr = ns["run_house"](pbx, decx, sel, s, e, c, placebo_seed=seed, frac_map=fm, scale_set=ss)
                        finals.append(round(pr["final"],2))
                    cell[str(c)]["placebo_finals"]=finals
                    cell[str(c)]["placebo_beaten"]=sum(1 for f in finals if f < cell[str(c)]["house"]["final"])
            res["roads"][rn]=cell
            print(fam, rn, "done", time.time()-t0, flush=True)
        sums={str(c): sum(res["roads"][rn][str(c)]["house"]["final"] for rn in ROADS) for c in COUNTS}
        beats={str(c): sum(1 for rn in ROADS if res["roads"][rn][str(c)]["house"]["final"]>res["roads"][rn]["5"]["house"]["final"]) for c in COUNTS}
        winner=max(sums, key=sums.get); conf=None
        if winner!="5" and beats[winner]>=3:
            cand = "ALL" if winner=="ALL" else int(winner)
            folds={}
            for yr in range(2017,2027):
                s=f"{yr}-01-01"; e= END if yr==2026 else f"{yr}-12-31"
                sel, fm, ss = fam_frac(fam, pb, dec_fixed, s, e)
                rc=ns["run_house"](pb,dec_fixed,sel,s,e,cand,frac_map=fm,scale_set=ss)
                r5=ns["run_house"](pb,dec_fixed,sel,s,e,5,frac_map=fm,scale_set=ss)
                folds[str(yr)]={"cand":round(rc["final"],2),"native5":round(r5["final"],2),"win":rc["final"]>r5["final"]}
            halves={}
            for hn,(s,e) in {"H1":("2016-11-21","2021-12-31"),"H2":("2022-01-01",END)}.items():
                sel, fm, ss = fam_frac(fam, pb, dec_fixed, s, e)
                rc=ns["run_house"](pb,dec_fixed,sel,s,e,cand,frac_map=fm,scale_set=ss)
                r5=ns["run_house"](pb,dec_fixed,sel,s,e,5,frac_map=fm,scale_set=ss)
                halves[hn]={"cand":round(rc["final"],2),"native5":round(r5["final"],2),"win":rc["final"]>r5["final"]}
            fw=sum(1 for v in folds.values() if v["win"]); hw=sum(1 for v in halves.values() if v["win"])
            conf={"candidate":winner,"folds":folds,"fold_wins":fw,"halves":halves,"half_wins":hw,"confirmed": fw>=6 and hw>=1}
        res["sums"]=sums; res["beats_native"]=beats; res["winner"]=winner; res["confirmation"]=conf
        dist={}
        for c in {winner,"5"}:
            sel=ns["quarter_dates"](pb,"2016-11-21",END)
            dist[c]=ns["period_distribution"](res["roads"]["DECADE"][c]["house"]["curve"], sel)
        res["period_dist_DECADE"]=dist
        fams[fam]=res
        json.dump(fams, open(OUT,"w"))
        print(fam, "COMPLETE winner", winner, "conf", bool(conf and conf["confirmed"]), flush=True)
    print("ALL DONE", time.time()-t0, flush=True)
if __name__=="__main__":
    main()
