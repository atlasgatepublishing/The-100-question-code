#!/usr/bin/env python3
"""
GATED MOMENTUM BASKETS — v12 HOLDINGS-COUNT SWEEP. Simulation only.

Families (frozen house forms, v4/v10 record — the gate stays EXACTLY as
frozen; only the number held varies):
  basket-quality-gate : momentum basket + gross-profitability gate
    GP = (Revenue - COGS)/Total Assets from SEC EDGAR, most recent filing
    filed strictly before the signal day must be POSITIVE; no observation
    also fails. Copied verbatim from v10-retest/basket-quality-gate/
    bqg_v10.py (itself verbatim from v4). *** ARTIFACT WARNING carried
    from the record: in the original windows this gate excluded 386
    names, ALL "no-data", ZERO for GP<=0 — as implemented it is an
    accidental permanent banks-and-big-oil ban (JPM/BAC/WFC/XOM report
    no COGS-based GP under the concept set used), NOT a profitability
    screen. Documented, never patched. ***
  basket-issuance-veto : momentum basket + net-issuance veto
    any ranked name whose trailing-12m point-in-time net share issuance
    (EDGAR, split-adjusted, v4 IssuanceSeries) exceeds +5%/yr is skipped
    and the next-ranked name fills the slot. V4 module imported read-only.

Host (identical to holdings-momentum-basket): Nov-2016 top-30 pond;
monthly selection; eligible = close above own 200-day SMA; rank by 12-1
momentum (signal from prior day's close, trade at open); hold top-N
equal-weighted (1/N of pot each; fewer gate-passing eligible than N ->
hold what's eligible, rest cash). NATIVE COUNT = 5.
Costs (program): 0.10%/side + $0.01 per sell order. $100 pot.

Rule sets:
  house  = v9 protections: plain -15% floor per episode (checked at
           close), liquidate next open; first halt -> 90-day sit-out,
           restart at next monthly selection date, episode-2 floor -15%
           from restart balance; second halt ends the run.
  native = the published momentum-portfolio form carries no stop: same
           selection/gate/cadence/costs, no floor/halt/restart. (Neither
           gate has a published native form of its own — v11 closed both
           UNBUILDABLE-NATIVE; "native" here is the host's published
           no-protection form with the frozen house gate unchanged.)

GRID (pre-registered, fixed): counts 1, 2, 3, 5, 8, 10, 15, 20, 30,
  ALL-ELIGIBLE (N = gate-passing eligible that month, fully invested).
Roads: DECADE 2016-11-21 -> 2026-11-20 ; CONT 2019-01-01 -> 2026-11-20 ;
  VAL 2023-01-01 -> 2026-11-20. LONG 2010 NOT RUN: pond is point-in-time
  Nov-2016, cache starts 2015-01-02 (same closure as the host sweep).
Placebos: 20 seeds per cell — quality gate: random N of the gate-passing
  eligible set; issuance veto: seeded random order of the eligible pool
  with the same veto walk (the v10 convention for this family). For
  ALL-ELIGIBLE the random draw IS the set, so placebos are n/a (null).

CONFIRMATION (Terry's rule, pre-registered): if a non-native count beats
  count 5 on ALL THREE roads under house rules, re-run on different
  years: fresh-$100 calendar-year folds 2017..2026 (house) head-to-head
  vs count 5, plus two continuous half-windows.

GATE-FIRING AUDIT: every ranked run logs, per monthly selection, the
  ungated top-N vs the gated top-N (changed or not) and every exclusion
  among momentum-eligible names (quality: reason no-data / gp<=0;
  veto: names vetoed, and of those which were in the ungated top-N).

Data (READ-ONLY): prices + EDGAR facts from backtests/v4/ caches; the
  v4 basket-issuance-veto module imported read-only for its series.
Engine plumbing: holdings-momentum-basket/run_holdings.py (which
  reproduced the ungated published $439.45 / $208.27 to the cent),
  parameterized by count + floor toggle + gate filter.
Integrity gates for THIS script (must reproduce before sweep counts):
  quality-gate house N=5 DECADE = $508.81 (v10 published);
  issuance-veto house N=5 DECADE = $403.02 (v10 published).
"""
import importlib.util, json, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
CACHE = os.path.join(BT, "v4", "momentum-basket-honest-data")
V4_DATA = os.path.join(BT, "v4", "data")
V4 = os.path.join(BT, "v4")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG",
            "V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC",
            "CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
BENCH = "SPY"
COST_RATE = 0.001; SELL_FEE = 0.01; POT0 = 100.0
COUNTS = [1,2,3,5,8,10,15,20,30,"ALL"]
NATIVE_COUNT = 5
ROADS = {"DECADE": ("2016-11-21","2026-11-20"),
         "CONT":   ("2019-01-01","2026-11-20"),
         "VAL":    ("2023-01-01","2026-11-20")}
SEEDS = list(range(1,21))
VETO_THRESHOLD = 0.05

# ======================================================================
# Quality gate — verbatim from v10 bqg_v10.py (constants + builders).
# ======================================================================
REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                 "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"

def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]

def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) -
                    date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

def build_quality_observations(facts):
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (
            float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:
                    slot[key] = (float(e["val"]), e.get("filed", ""))
        return out

    rev = by_accn_period(REV_CONCEPTS)
    cogs = by_accn_period(COGS_CONCEPTS)
    obs = []
    for accn, periods in rev.items():
        for (start, end), (rval, rfiled) in periods.items():
            c = cogs.get(accn, {}).get((start, end))
            if c is None:
                continue
            a = assets_for(accn, end)
            if a is None or a <= 0:
                continue
            filed = max(rfiled, c[1])
            obs.append((filed, end, (rval - c[0]) / a, "GP"))
    if not obs:
        op = by_accn_period([OPINC_CONCEPT])
        for accn, periods in op.items():
            for (start, end), (oval, ofiled) in periods.items():
                a = assets_for(accn, end)
                if a is None or a <= 0:
                    continue
                obs.append((ofiled, end, oval / a, "OPINC"))
    obs.sort()
    return obs

def quality_at(obs, asof):
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best

def load_quality_obs():
    with open(os.path.join(V4_DATA, "company_tickers.json")) as f:
        raw = json.load(f)
    ciks = {row["ticker"]: int(row["cik_str"]) for row in raw.values()}
    obs = {}
    for t in UNIVERSE:
        path = os.path.join(V4_DATA, f"facts_{ciks[t]:010d}.json")
        with open(path) as f:
            facts = json.load(f)
        obs[t] = build_quality_observations(facts)
    return obs

# ======================================================================
# Issuance veto — v4 module imported read-only (series construction).
# ======================================================================
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def build_issuance_series():
    veto = _load("issuance_veto_v4", os.path.join(V4, "basket-issuance-veto.py"))
    ciks = veto.get_ciks()
    ciks.update(veto.CIK_OVERRIDES)
    series = {}
    for t in UNIVERSE:
        facts = veto.get_companyfacts(ciks[t])
        splits = veto.get_splits(t)
        series[t] = veto.IssuanceSeries(t, facts, splits)
    return series

# ======================================================================
# Market — same plumbing as holdings-momentum-basket.
# ======================================================================
def fetch(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f: return json.load(f)

class Market:
    def __init__(self, tickers):
        self.bars={}; self.closes={}
        spy=fetch(BENCH); self.cal=[r["d"] for r in spy]
        raw={BENCH:spy}
        for t in tickers: raw[t]=fetch(t)
        for t in tickers+[BENCH]:
            self.bars[t]={r["d"]:(r["o"],r["c"]) for r in raw[t]}
            arr,last=[],None
            for d in self.cal:
                if d in self.bars[t]: last=self.bars[t][d][1]
                arr.append(last)
            self.closes[t]=arr
        self.sma200={}; self.mom={}; n=len(self.cal)
        for t in tickers:
            c=self.closes[t]; s=[None]*n; m=[None]*n
            for i in range(n):
                if i+1>=200:
                    seg=c[i-199:i+1]
                    if not any(v is None for v in seg): s[i]=sum(seg)/200.0
                if i-252>=0:
                    a,b=c[i-252],c[i-21]
                    if a is not None and b is not None and a>0: m[i]=b/a-1.0
            self.sma200[t]=s; self.mom[t]=m
    def open_px(self,t,i):
        d=self.cal[i]
        return self.bars[t][d][0] if d in self.bars[t] else None
    def close_px(self,t,i): return self.closes[t][i]

def monthly_indices(mkt,i0,i1):
    out={i0}; prev=mkt.cal[i0][:7]
    for i in range(i0+1,i1+1):
        k=mkt.cal[i][:7]
        if k!=prev: prev=k; out.add(i)
    return out

# ======================================================================
# Gate context: per-signal-day gate state, memoized by calendar index.
# ======================================================================
class GateCtx:
    def __init__(self, mkt, family, quality_obs=None, iss_series=None):
        self.mkt=mkt; self.family=family
        self.qobs=quality_obs; self.series=iss_series
        self._cache={}
    def state(self, j):
        """Returns dict: pass_set (names passing gate), detail per name."""
        if j in self._cache: return self._cache[j]
        asof=self.mkt.cal[j]; st={}
        if self.family=="quality":
            for t in UNIVERSE:
                q=quality_at(self.qobs.get(t,[]), asof)
                if q is None: st[t]=("excluded","no-data",None)
                elif q[2]<=0: st[t]=("excluded","gp<=0",round(q[2],4))
                else: st[t]=("pass",None,round(q[2],4))
        elif self.family=="veto":
            for t in UNIVERSE:
                v=self.series[t].issuance_asof(asof)
                if v is not None and v>VETO_THRESHOLD:
                    st[t]=("excluded","issuance>5%",round(v,4))
                else:
                    st[t]=("pass",None,round(v,4) if v is not None else None)
        self._cache[j]=st
        return st

class Result:
    def __init__(self):
        self.final=None; self.orders=0; self.costs=0.0
        self.halts=[]; self.restarts=[]; self.max_dd=0.0; self.equity_curve=[]
        self.audit=[]

def simulate(mkt,gctx,start_d,end_d,count,house,mode="ranked",seed=42):
    rng=random.Random(seed)
    i0=next(i for i,d in enumerate(mkt.cal) if d>=start_d)
    i1=max(i for i,d in enumerate(mkt.cal) if d<=end_d)
    sel_days=monthly_indices(mkt,i0,i1)
    episode=1; floor=0.85*POT0 if house else None
    restart_idx=None; cash=float(POT0); pos={}; res=Result()
    pending=False
    def equity_at(i,use_open):
        tot=cash
        for t,sh in pos.items():
            px=mkt.open_px(t,i) if use_open else mkt.close_px(t,i)
            if px is None: px=mkt.close_px(t,i)
            tot+=sh*px
        return tot
    for i in range(i0,i1+1):
        d=mkt.cal[i]
        if pending:
            for t in list(pos):
                px=mkt.open_px(t,i)
                if px is None: px=mkt.close_px(t,i)
                val=pos[t]*px; fee=val*COST_RATE+SELL_FEE
                cash+=val-fee; res.costs+=fee; res.orders+=1; del pos[t]
            res.halts.append(d); res.equity_curve.append((d,cash)); pending=False
            if episode==1:
                y,m,dd=(int(x) for x in d.split("-"))
                earliest=(date(y,m,dd)+timedelta(days=90)).isoformat()
                ridx=None
                for j in sorted(sel_days):
                    if j>i and mkt.cal[j]>=earliest: ridx=j; break
                if ridx is not None:
                    restart_idx=ridx; episode=2
                    res.restarts.append({"halt_date":d,"restart_date":mkt.cal[ridx],
                        "restart_balance":round(cash,2),"episode2_floor":round(0.85*cash,2)})
                    floor=0.85*cash; continue
            res.final=cash; break
        if restart_idx is not None and i<restart_idx:
            res.equity_curve.append((d,cash)); continue
        if restart_idx is not None and i==restart_idx: restart_idx=None
        if i in sel_days and i>0:
            j=i-1; elig=[]
            for t in UNIVERSE:
                s=mkt.sma200[t][j]; c=mkt.close_px(t,j)
                if s is None or c is None or c<=s: continue
                mo=mkt.mom[t][j]
                if mo is None: continue
                elig.append((t,mo))
            elig.sort(key=lambda x:-x[1])
            ranked=[t for t,_ in elig]
            gst=gctx.state(j)
            n_req=len(elig) if count=="ALL" else count
            ungated=ranked[:n_req] if count!="ALL" else list(ranked)
            if mode=="ranked":
                picks=[]
                for t in ranked:
                    if len(picks)>=n_req: break
                    if gst[t][0]=="pass": picks.append(t)
                if count=="ALL": picks=[t for t in ranked if gst[t][0]=="pass"]
            else:  # placebo
                if gctx.family=="quality":
                    names=sorted(t for t in ranked if gst[t][0]=="pass")
                    picks=rng.sample(names,min(n_req,len(names))) if names else []
                else:  # veto: random order, same veto walk (v10 convention)
                    order=rng.sample(ranked,len(ranked)) if ranked else []
                    picks=[]
                    for t in order:
                        if len(picks)>=n_req: break
                        if gst[t][0]=="pass": picks.append(t)
            if mode=="ranked":
                excl=[{"t":t,"reason":gst[t][1],"value":gst[t][2]}
                      for t in ranked if gst[t][0]=="excluded"]
                res.audit.append({"date":d,"signal_date":mkt.cal[j],
                    "n_elig":len(ranked),"ungated_picks":ungated,
                    "gated_picks":picks,"changed":picks!=ungated,
                    "exclusions":excl})
            if picks:
                eq_open=equity_at(i,use_open=True)
                w=1.0/len(picks) if count=="ALL" else 1.0/count
                target_val={t:w*eq_open for t in picks}
                for t in list(pos):
                    px=mkt.open_px(t,i)
                    if px is None: continue
                    cur=pos[t]*px; want=target_val.get(t,0.0)
                    if cur>want+0.01:
                        sv=cur-want; fee=sv*COST_RATE+SELL_FEE
                        cash+=sv-fee; res.costs+=fee; res.orders+=1
                        pos[t]-=sv/px
                        if want<=0.0 or pos[t]*px<0.01: del pos[t]
                for t in picks:
                    px=mkt.open_px(t,i)
                    if px is None: continue
                    cur=pos.get(t,0.0)*px; deficit=target_val[t]-cur
                    if deficit<=0.01: continue
                    bv=min(deficit,cash/(1.0+COST_RATE))
                    if bv<=0.01: continue
                    fee=bv*COST_RATE; cash-=bv+fee; res.costs+=fee; res.orders+=1
                    pos[t]=pos.get(t,0.0)+bv/px
        eq_close=equity_at(i,use_open=False)
        res.equity_curve.append((d,eq_close))
        if house and eq_close<=floor:
            pending=True
            if i==i1:
                tot=cash
                for t,sh in list(pos.items()):
                    val=sh*mkt.close_px(t,i); fee=val*COST_RATE+SELL_FEE
                    tot+=val-fee; res.costs+=fee; res.orders+=1
                res.final=tot; res.halts.append(d); pos.clear(); break
    if res.final is None: res.final=res.equity_curve[-1][1]
    peak=-1.0
    for d,eq in res.equity_curve:
        peak=max(peak,eq)
        if peak>0: res.max_dd=min(res.max_dd,eq/peak-1.0)
    return res

def period_distribution(curve):
    """Monthly periods from a daily equity curve (Terry's reporting std)."""
    prev_eq=POT0; prev_key=None; last_eq=None
    month_ends=[]
    for d,eq in curve:
        k=d[:7]
        if prev_key is not None and k!=prev_key: month_ends.append((prev_key,last_eq))
        prev_key=k; last_eq=eq
    if prev_key is not None: month_ends.append((prev_key,last_eq))
    rets=[]
    for k,eq in month_ends:
        rets.append(eq/prev_eq-1.0); prev_eq=eq
    n=len(rets); prof=sum(1 for r in rets if r>0)
    longest_loss=0; run=0
    for r in rets:
        run=run+1 if r<0 else 0; longest_loss=max(longest_loss,run)
    peak=-1; last_high=0; max_gap=0
    eqs=[eq for _,eq in month_ends]
    for idx,eq in enumerate(eqs):
        if eq>=peak: peak=eq; max_gap=max(max_gap,idx-last_high); last_high=idx
    max_gap=max(max_gap,len(eqs)-1-last_high)
    return {"tempo":"monthly","periods":n,
        "pct_periods_profitable":round(100.0*prof/n,1) if n else None,
        "median_period_pct":round(100*statistics.median(rets),2) if rets else None,
        "best_period_pct":round(100*max(rets),2) if rets else None,
        "worst_period_pct":round(100*min(rets),2) if rets else None,
        "longest_losing_run_periods":longest_loss,
        "longest_stretch_between_new_highs_periods":max_gap,
        "average_period_pct_SECONDARY_LABELED":round(100*statistics.mean(rets),2) if rets else None}

def audit_summary(audit):
    n=len(audit); changed=sum(1 for a in audit if a["changed"])
    excl={}
    for a in audit:
        for e in a["exclusions"]:
            excl[e["reason"]]=excl.get(e["reason"],0)+1
    return {"selection_months":n,"months_picks_changed":changed,
            "pct_months_changed":round(100.0*changed/n,1) if n else None,
            "total_exclusion_events_among_eligible":sum(excl.values()),
            "exclusions_by_reason":excl}

def run_family(mkt, family, gctx, published_decade):
    cells={}; curves={}; audits={}
    r=simulate(mkt,gctx,*ROADS["DECADE"],5,True)
    print(f"INTEGRITY {family} house N=5 DECADE={r.final:.2f} (pub {published_decade})",flush=True)
    integrity={"house_N5_DECADE":round(r.final,2),"published":published_decade,
               "match":abs(round(r.final,2)-published_decade)<0.02}
    for rules,house in (("house",True),("native",False)):
        for road,(sd,ed) in ROADS.items():
            for count in COUNTS:
                key=f"{rules}|{road}|{count}"
                res=simulate(mkt,gctx,sd,ed,count,house)
                pfinals=None; beaten=None
                if count!="ALL":
                    pfinals=[]
                    for s in SEEDS:
                        pr=simulate(mkt,gctx,sd,ed,count,house,mode="placebo",seed=s)
                        pfinals.append(round(pr.final,2))
                    beaten=sum(1 for v in pfinals if res.final>v)
                cells[key]={"rules":rules,"road":road,"count":str(count),
                    "final":round(res.final,2),"max_dd_pct":round(res.max_dd*100,2),
                    "costs":round(res.costs,2),"orders":res.orders,
                    "halts":res.halts,"restarts":res.restarts,
                    "placebo_beaten":beaten,"placebo_finals":pfinals}
                curves[key]=[[d,round(e,4)] for d,e in res.equity_curve]
                audits[key]=res.audit
                print(f"{family} {key}: final={res.final:.2f} maxDD={res.max_dd*100:.2f}% costs={res.costs:.2f} orders={res.orders} halts={len(res.halts)} beaten={beaten}",flush=True)
    totals={}
    for count in COUNTS:
        totals[str(count)]=sum(cells[f"house|{road}|{count}"]["final"] for road in ROADS)
    winner=max(totals,key=totals.get)
    print(f"{family} house totals:",{k:round(v,2) for k,v in totals.items()},"winner:",winner,flush=True)
    confirmation=None
    cands=[str(c) for c in COUNTS if str(c)!=str(NATIVE_COUNT) and
           all(cells[f"house|{road}|{c}"]["final"]>cells[f"house|{road}|{NATIVE_COUNT}"]["final"] for road in ROADS)]
    if cands:
        confirmation={}
        for cand in cands:
            cc="ALL" if cand=="ALL" else int(cand)
            folds={}
            for yr in range(2017,2027):
                sd=f"{yr}-01-01"; ed=f"{yr}-12-31"
                a=simulate(mkt,gctx,sd,ed,cc,True); b=simulate(mkt,gctx,sd,ed,NATIVE_COUNT,True)
                folds[str(yr)]={"candidate":round(a.final,2),"native5":round(b.final,2)}
            halves={}
            for lbl,(sd,ed) in {"H1":("2016-11-21","2021-12-31"),"H2":("2022-01-01","2026-11-20")}.items():
                a=simulate(mkt,gctx,sd,ed,cc,True); b=simulate(mkt,gctx,sd,ed,NATIVE_COUNT,True)
                halves[lbl]={"candidate":round(a.final,2),"native5":round(b.final,2)}
            cw=sum(1 for v in folds.values() if v["candidate"]>v["native5"])
            confirmation[cand]={"folds":folds,"fold_wins_of_10":cw,"halves":halves}
            print(f"{family} CONFIRMATION {cand}: fold wins {cw}/10 halves={halves}",flush=True)
    dist={}
    for cnt in {winner,str(NATIVE_COUNT)}:
        for rules in ("house","native"):
            dist[f"{rules}|DECADE|{cnt}"]=period_distribution(curves[f"{rules}|DECADE|{cnt}"])
    gate_audit={
        "winning_count_house_DECADE":audit_summary(audits[f"house|DECADE|{winner}"]),
        "native_count_house_DECADE":audit_summary(audits[f"house|DECADE|{NATIVE_COUNT}"]),
        "winning_count_audit_detail":audits[f"house|DECADE|{winner}"],
    }
    return {"family":family,"native_count":NATIVE_COUNT,"integrity":integrity,
            "cells":cells,"house_totals":{k:round(v,2) for k,v in totals.items()},
            "winner_count_house":winner,"confirmation":confirmation,
            "period_distributions":dist,"gate_audit":gate_audit,
            "curves":{k:curves[k] for k in curves if k.split("|")[2] in (winner,str(NATIVE_COUNT))}}

def main():
    mkt=Market(UNIVERSE)
    out={"wing":"holdings-count sweep — gated momentum baskets",
        "grid_counts":[str(c) for c in COUNTS],"roads":ROADS,
        "long_road_note":"LONG 2010 NOT RUN: pond is point-in-time Nov-2016, cache starts 2015-01-02 (host sweep closure).",
        "spy_dividend_adjusted_reference":{"DECADE":367.80,"CONT":313.62,"VAL":187.77},
        "ungated_host_reference":"holdings-momentum-basket results.json (house N=5: DECADE $439.45, CONT $291.53, VAL $208.27)",
        "families":{}}
    qobs=load_quality_obs()
    qctx=GateCtx(mkt,"quality",quality_obs=qobs)
    out["families"]["basket-quality-gate"]=run_family(mkt,"quality",qctx,508.81)
    iser=build_issuance_series()
    vctx=GateCtx(mkt,"veto",iss_series=iser)
    out["families"]["basket-issuance-veto"]=run_family(mkt,"veto",vctx,403.02)
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("saved results.json",flush=True)

if __name__=="__main__": main()
