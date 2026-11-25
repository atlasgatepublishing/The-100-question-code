#!/usr/bin/env python3
"""V13 BEST RULES — Dunnigan One-Way, frozen spec BEST-RULES-SPEC.md.
Weekly bars from daily adjusted OHLC (v7 pxfull cache, read-only).
Swing engine (published): bars classified vs previous non-ignored weekly bar;
inside/outside ignored; swing top = high of last up bar before first down bar.
Entry: weekly close > latest confirmed swing top (flat in name) -> next weekly open.
Exit: weekly close < latest confirmed swing bottom -> next weekly open.
Basket: 30 pond names, max 10 slots, first-come (pond order), target slice =
equity/10 capped by cash. SPY single-asset all-in as secondary reference.
Costs 0.10%/side + $0.01/sell. $100 pot. No floor.
Placebos: 20 seeds/road; per name same entry count, random entry weeks,
exit by identical prevailing swing-bottom stop rule."""
import json, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
START = 100.0; COST = 0.001; FEE = 0.01; SLOTS = 10
ROADS = {"LONG": ("2010-01-04","2026-11-20"), "DECADE": ("2016-11-21","2026-11-20"),
         "CONT": ("2019-01-02","2026-11-20"), "VAL": ("2023-01-03","2026-11-20")}
CHAMP = {"LONG":1415.62,"DECADE":667.35,"CONT":544.47,"VAL":288.05}
SPYREF = {"LONG":822.94,"DECADE":367.80,"CONT":313.62,"VAL":187.77}
PUBLISHED = {"basket5_native": {"LONG":308.15,"DECADE":189.23,"CONT":163.28,"VAL":120.16},
             "spy_native_daily": {"LONG":432.08,"DECADE":181.30,"CONT":177.69,"VAL":136.91}}

def load_daily(sym):
    fn = "GOOG" if sym == "GOOGL" else sym  # cache holds GOOG (Class A) for the pond's GOOGL slot
    j = json.load(open(os.path.join(V7, f"pxfull_{fn}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i,t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]): continue
        ratio = adj[i]/q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": q["high"][i]*ratio,
                     "l": q["low"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def to_weekly(daily):
    weeks = {}
    for b in daily:
        y,w,_ = time.strptime(b["d"], "%Y-%m-%d")[:3], None, None
        iso = time.strftime("%G-W%V", time.strptime(b["d"], "%Y-%m-%d"))
        if iso not in weeks: weeks[iso] = dict(b)
        else:
            wk = weeks[iso]; wk["h"] = max(wk["h"], b["h"]); wk["l"] = min(wk["l"], b["l"])
            wk["c"] = b["c"]; wk["d"] = b["d"]
    return [weeks[k] for k in sorted(weeks)]

def swing_state(bars):
    """Per-bar (latest_top, latest_bot) confirmed as of that bar's close — v12 engine logic."""
    tops=[]; bots=[]; last=0; run_dir=0; run_ext=None
    latest_top=None; latest_bot=None; out=[]
    for i in range(len(bars)):
        if i>0:
            if bars[i]["h"]>bars[last]["h"] and bars[i]["l"]>bars[last]["l"]: cls=1
            elif bars[i]["h"]<bars[last]["h"] and bars[i]["l"]<bars[last]["l"]: cls=-1
            else: cls=0
            if cls!=0:
                if run_dir==0: run_dir=cls; run_ext=bars[i]["h"] if cls==1 else bars[i]["l"]
                elif cls==run_dir:
                    if cls==1: run_ext=max(run_ext,bars[i]["h"])
                    else: run_ext=min(run_ext,bars[i]["l"])
                else:
                    if run_dir==1: tops.append(run_ext); latest_top=run_ext
                    else: bots.append(run_ext); latest_bot=run_ext
                    run_dir=cls; run_ext=bars[i]["h"] if cls==1 else bars[i]["l"]
                last=i
        out.append((latest_top, latest_bot))
    return out

def real_signals(bars, st):
    """entry weeks (signal bar idx) for a name: close penetrates latest top while flat;
    flat determined by stop rule replay (single-name state machine)."""
    sig=[]; in_pos=False
    for i in range(len(bars)):
        top,bot = st[i]
        if in_pos:
            if bot is not None and bars[i]["c"]<bot: in_pos=False
        else:
            if top is not None and bars[i]["c"]>top and i+1<len(bars):
                sig.append(i); in_pos=True
    return sig

def placebo_entries(bars, st, count, rng):
    n=len(bars); cand=list(range(2, n-1)); rng.shuffle(cand)
    ents=sorted(cand[:count]); out=[]; in_pos_until=-1
    for e in ents:
        if e<=in_pos_until: continue
        # find exit by stop rule
        ex=n-1
        for j in range(e+1, n):
            bot=st[j][1]
            if bot is not None and bars[j]["c"]<bot: ex=j; break
        out.append(e); in_pos_until=ex
    return out

def run_basket(weekly, signals_by, s, e, single=None):
    """signals_by: sym -> set of signal-bar indices (in that sym's weekly array).
    Simulates on a unified weekly timeline (SPY dates). Returns curve/final/trades."""
    syms = [single] if single else POND
    # unified week dates from SPY weekly bars
    timeline = [b["d"] for b in weekly["SPY"]]
    idx = {sym: {b["d"]: k for k,b in enumerate(weekly[sym])} for sym in weekly}
    cash=START; pos={}  # sym -> shares, basis
    curve=[]; trades=0; costs=0.0; closed=[]
    pending_exits=set(); pending_entries=[]
    for ti,d in enumerate(timeline):
        if d < s or d > e: 
            continue
        # execute pending at this week's open
        for sym in list(pending_exits):
            k=idx[sym].get(d)
            if k is None or sym not in pos: continue
            px=weekly[sym][k]["o"]; sh=pos.pop(sym)
            fee=sh*px*COST+FEE; costs+=fee; cash+=sh*px-fee; trades+=1
            closed.append(sh*px-fee)
        pending_exits=set()
        for sym in pending_entries:
            k=idx[sym].get(d)
            if k is None or sym in pos: continue
            if single is None and len(pos)>=SLOTS: continue
            eq=cash+sum(pos[x]*weekly[x][idx[x][d]]["c"] for x in pos if d in idx[x])
            target = cash if single else min(eq/SLOTS, cash)
            if target<=0: continue
            px=weekly[sym][k]["o"]; spend=target*(1-COST); costs+=target*COST
            pos[sym]=spend/px; cash-=target; trades+=1
        pending_entries=[]
        # mark + generate signals at close
        eq=cash+sum(pos[x]*weekly[x][idx[x][d]]["c"] for x in pos if d in idx[x])
        curve.append({"d":d,"eq":round(eq,4)})
        for sym in syms:
            k=idx[sym].get(d)
            if k is None: continue
            top,bot = SWING[sym][k]
            if sym in pos:
                if bot is not None and weekly[sym][k]["c"]<bot: pending_exits.add(sym)
            else:
                if k in signals_by.get(sym, set()): pending_entries.append(sym)
    final=curve[-1]["eq"] if curve else START
    return {"final":round(final,2),"curve":curve,"trades":trades,"costs":round(costs,2),
            "maxdd_pct":max_dd(curve),"periods_monthly":period_stats(curve)}

def max_dd(curve):
    peak=-1e18; dd=0.0
    for p in curve:
        peak=max(peak,p["eq"]); dd=max(dd,(peak-p["eq"])/peak if peak>0 else 0)
    return round(dd*100,2)

def period_stats(curve):
    if not curve: return {}
    months={}
    for c in curve: months[c["d"][:7]]=c["eq"]
    ks=sorted(months); rets=[]; prev=START
    for k in ks: rets.append(months[k]/prev-1 if prev>0 else 0); prev=months[k]
    pos_n=sum(1 for r in rets if r>0); streak=0; worst=0
    for r in rets: streak=streak+1 if r<0 else 0; worst=max(worst,streak)
    vals=[START]+[months[k] for k in ks]; peak=vals[0]; since=0; longest=0
    for v in vals:
        if v>=peak: peak=v; since=0
        else: since+=1; longest=max(longest,since)
    return {"n_periods":len(rets),"share_positive":round(pos_n/len(rets),4),
            "median_pct":round(statistics.median(rets)*100,3),"best_pct":round(max(rets)*100,3),
            "worst_pct":round(min(rets)*100,3),"longest_losing_streak":worst,
            "longest_between_highs_periods":longest,
            "average_pct_secondary":round(statistics.mean(rets)*100,3)}

# ---- load ----
weekly={}; SWING={}; REAL={}
for sym in POND+["SPY"]:
    weekly[sym]=to_weekly(load_daily(sym)); SWING[sym]=swing_state(weekly[sym])
    REAL[sym]=set(real_signals(weekly[sym], SWING[sym]))

res={"family":"hunt-dunnigan-oneway","label":"V13 BEST RULES — CONSTRUCTED family; CANDIDATE ceiling",
     "spec":"BEST-RULES-SPEC.md (frozen before run)","roads":{},"placebos":{},"spy_single_weekly":{}}
for road,(s,e) in ROADS.items():
    r=run_basket(weekly, REAL, s, e)
    res["roads"][road]={"final":r["final"],"maxdd_pct":r["maxdd_pct"],"trades":r["trades"],
                        "costs":r["costs"],"periods_monthly":r["periods_monthly"],"curve":r["curve"],
                        "champion_VM":CHAMP[road],"spy_ref":SPYREF[road],
                        "published_basket5_native":PUBLISHED["basket5_native"][road]}
    sp=run_basket(weekly, REAL, s, e, single="SPY")
    res["spy_single_weekly"][road]={"final":sp["final"],"maxdd_pct":sp["maxdd_pct"],"trades":sp["trades"],
                                    "published_spy_daily_native":PUBLISHED["spy_native_daily"][road]}
    # placebos: per-name entry counts from real signals falling in road (approx by signal bar date)
    finals=[]
    for seed in range(1,21):
        rng=random.Random(seed*7919+hash(road)%1000)
        sig={}
        for sym in POND:
            bars=weekly[sym]
            cnt=sum(1 for i in REAL[sym] if s<=bars[i]["d"]<=e)
            ents=placebo_entries(bars, SWING[sym], cnt, rng)
            sig[sym]=set(ents)
        pf=run_basket(weekly, sig, s, e)
        finals.append(pf["final"])
    res["placebos"][road]={"median":round(statistics.median(finals),2),
                           "n_beaten_by_real":sum(1 for f in finals if r["final"]>f),"finals":finals}
    print(road, "basket10 weekly:", r["final"], "dd", r["maxdd_pct"], "trades", r["trades"],
          "| SPYsingle:", sp["final"], "| placebo med:", res["placebos"][road]["median"],
          "beaten:", res["placebos"][road]["n_beaten_by_real"], "/20", flush=True)
json.dump(res, open(os.path.join(HERE,"results.json"),"w"), indent=1)
print("DONE")
