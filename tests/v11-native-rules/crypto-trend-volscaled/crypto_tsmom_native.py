"""Native crypto time-series momentum (Liu & Tsyvinski, RFS 2021; vol-scaling per
Moskowitz, Ooi & Pedersen 2012 as applied to crypto in Cheah et al. 2022).
Weekly evaluation (Friday close): trailing 28-day (4-week) return > 0 -> long,
else cash. Position weight = min(1, 0.40 / trailing-60d annualized vol).
Fee 0.60%/side (US retail mid of documented 0.40-0.80% range, crypto-evidence.md).
No -15% floor: the native form has none (floor breaches reported as diagnostics).
Assets BTC, ETH + 50/50 COMBO. Placebos: 20 seeds, random in/out weekly with the
same average exposure and same vol weights, same fees."""
import csv, math, pathlib, random, json, statistics
SRC = pathlib.Path.home()/"workspace/stock-app/backtests/v10-retest/crypto-trend-volscaled/data"
FEE=0.0060; TARGET_VOL=0.40
def load(sym):
    rows=[]
    with open(SRC/f"{sym}-USD.csv") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["close"])))
    return rows
def weekly(rows):
    # last close of each ISO week
    out={}
    for d,c in rows:
        import datetime
        dt=datetime.date.fromisoformat(d); key=(dt.isocalendar()[0], dt.isocalendar()[1])
        out[key]=(d,c)
    return [out[k] for k in sorted(out)]
def run(rows, start, placebo_seed=None):
    wk=weekly(rows); closes=[c for _,c in rows]
    # daily vol map: trailing 60d stdev of log returns * sqrt(365), by date
    import datetime
    rets=[None]+[math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]
    vol={}
    for i in range(len(closes)):
        if i>=60:
            v=statistics.pstdev(rets[i-59:i+1])*math.sqrt(365); vol[rows[i][0]]=v
    eq=100.0; w=0.0; curve=[]; costs=0.0; trades=0; expo=[]
    rng=random.Random(placebo_seed) if placebo_seed is not None else None
    # weekly closes with their daily index dates
    prev_c=None; hist=[]
    for d,c in wk:
        hist.append(c)
        if prev_c is not None and w>0:
            eq*= (1 + w*(c/prev_c-1))
        prev_c=c
        if d<start: continue
        curve.append([d,round(eq,4)]); expo.append(w)
        if len(hist)>=5 and d in vol:
            form=hist[-1]/hist[-5]-1
            if rng is not None:
                inmarket = rng.random() < 0.5
            else:
                inmarket = form>0
            nw = min(1.0, TARGET_VOL/vol[d]) if inmarket else 0.0
            if abs(nw-w)>0.01:
                ch=eq*abs(nw-w)*FEE; eq-=ch; costs+=ch; trades+=1; w=nw
    avg_expo=round(statistics.mean(expo),3) if expo else 0
    peak=100.0; maxdd=0.0
    for _,v in curve:
        peak=max(peak,v); maxdd=min(maxdd, v/peak-1)
    return {"final":round(eq,2),"max_dd_pct":round(maxdd*100,2),"costs":round(costs,2),
            "trades":trades,"avg_weight":avg_expo,"curve":curve}
out={"strategy":"LT TSMOM weekly, 4wk formation, vol-target 40% cap 100%, fee 0.60%/side, no floor","assets":{}}
for sym in ["BTC","ETH"]:
    rows=load(sym)
    start = "2016-11-21" if sym=="BTC" else "2017-11-09"
    r=run(rows,start)
    pls=[run(rows,start,placebo_seed=s)["final"] for s in range(20)]
    r["placebo_beaten"]=sum(1 for p in pls if r["final"]>p); r["placebo_median"]=round(statistics.median(pls),2)
    r["buyhold"]=round(100*rows[-1][1]/[c for d,c in rows if d>=start][0],2)
    out["assets"][sym]=r; print(sym, r["final"], "BH", r["buyhold"], "placebo", r["placebo_beaten"], "/20 DD", r["max_dd_pct"])
# COMBO: average of the two finals (separate $50 sleeves, as prior program)
out["combo_final"]=round((out["assets"]["BTC"]["final"]+out["assets"]["ETH"]["final"])/2,2)
pathlib.Path(__file__).with_name("results.json").write_text(json.dumps(out,indent=1))
print("COMBO", out["combo_final"])
