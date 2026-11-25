#!/usr/bin/env python3
import sys, os, json, statistics
sys.path.insert(0,"/tmp")
from x1_engine import *

def summarize_percoin(res):
    rows=[v for v in res.values() if "native_final" in v]
    med_nat=statistics.median([r["native_final"] for r in rows])
    med_hold=statistics.median([r["hold_final"] for r in rows])
    beats=sum(1 for r in rows if r["native_final"]>r["hold_final"])
    conf=0; conf_n=0
    for r in rows:
        if r.get("val"):
            conf_n+=1
            if r["native_final"]>r["hold_final"] and r["val"]["native"]>r["val"]["hold"]: conf+=1
    btc=res.get("BTC",{})
    return {"coins_run":len(rows),"median_native_final":round(med_nat,2),"median_hold_final":round(med_hold,2),
            "beats_own_hold":beats,"confirmed_beats":conf,"val_coins":conf_n,
            "btc_native":btc.get("native_final"),"btc_hold":btc.get("hold_final"),"btc_v9":btc.get("v9_final")}

def strip(res):
    out={}
    for k,v in res.items():
        vv={kk:val for kk,val in v.items() if not kk.startswith("_curve") and kk!="_dates"}
        out[k]=vv
    return out

def percoin_period(res, tempo="daily"):
    # BTC curve period stats as representative + pooled median
    btc=res.get("BTC",{})
    if "_curve_nat" in btc:
        return period_stats(btc["_dates"], btc["_curve_nat"], tempo)
    return {}

def do_percoin(slug, stop):
    res=per_coin_family(stop)
    summ=summarize_percoin(res)
    plac=placebo_per_coin(stop, seeds=20)
    btc_hold_full = res.get("BTC",{}).get("hold_final")
    out={"family":slug,"form":"per-coin closes-only translation, 0.60%/side, both rule sets",
         "summary":summ,"placebo_pooled":plac,
         "btc":res.get("BTC"),"per_coin":strip(res),
         "curves":{"BTC_native":res.get("BTC",{}).get("_curve_nat"),"BTC_dates":res.get("BTC",{}).get("_dates")},
         "period_stats_btc_native_daily":percoin_period(res)}
    # remove curve from btc copy duplication
    if out["btc"] and "_curve_nat" in out["btc"]:
        out["btc"]={k:v for k,v in out["btc"].items() if not k.startswith("_")}
    folder=os.path.join(OUT,f"crypto-x-{slug}")
    os.makedirs(folder,exist_ok=True)
    json.dump(out, open(os.path.join(folder,"results.json"),"w"), indent=1)
    return summ, plac, res

def do_basket(slug, cadence, selector, tempo):
    data={"family":slug,"cadence":cadence,"cost_per_side":0.006,"windows":{},"placebos":{}}
    for name,s,e in WINDOWS_BASKET:
        nat=basket_run(s,e,cadence,selector,False)
        v9=basket_run(s,e,cadence,selector,True)
        bh=btc_hold_window(s,e)
        data["windows"][name]={"native":{"final":nat["final"],"max_dd_pct":nat["max_dd_pct"],"costs":nat["costs"],"orders":nat["orders"]},
            "v9":{"final":v9["final"],"max_dd_pct":v9["max_dd_pct"],"costs":v9["costs"],"orders":v9["orders"],"halts":v9["halts"]},
            "btc_hold":bh,
            "native_curve":nat["curve"],"native_dates":nat["dates"],"v9_curve":v9["curve"]}
        if name in ("FULL","VALIDATION"):
            finals=[]
            for seed in range(20):
                pr=basket_run(s,e,cadence,selector,False,seed=seed)
                finals.append(pr["final"])
            beaten=sum(1 for f in finals if nat["final"]>f)
            data["placebos"][name]={"seed_finals":finals,"median":round(statistics.median(finals),2),"beaten":beaten}
        data["windows"][name]["period_stats_native"]=period_stats(nat["dates"],nat["curve"],tempo)
    folder=os.path.join(OUT,f"crypto-x-{slug}")
    os.makedirs(folder,exist_ok=True)
    json.dump(data, open(os.path.join(folder,"results.json"),"w"), indent=1)
    return data

if __name__=="__main__":
    which=sys.argv[1]
    if which=="aggressive-v2":
        print(do_percoin("aggressive-v2",0.08)[:2])
    elif which=="aggressive-v3":
        print(do_percoin("aggressive-v3",0.05)[:2])
    elif which=="breakout-basket":
        d=do_basket("breakout-basket","monthly",lambda m,dt,seed=None: sel_breakout_top5(m,dt,seed,False),"monthly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
    elif which=="breakout-regime":
        d=do_basket("breakout-regime","monthly",lambda m,dt,seed=None: sel_breakout_top5(m,dt,seed,True),"monthly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
    elif which=="disciplined-v2":
        d=do_basket("disciplined-v2","monthly",make_disciplined(2,True,True),"monthly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
    elif which=="disciplined-v3":
        d=do_basket("disciplined-v3","monthly",make_disciplined(3,False,False),"monthly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
    elif which=="etf-trend-sleeve-weekly":
        d=do_basket("etf-trend-sleeve-weekly","weekly",sel_trendsleeve_weekly,"weekly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
    elif which=="momentum-component":
        d=do_basket("momentum-component","monthly",sel_momentum_top5,"monthly")
        print({k:(v["native"],v["btc_hold"]) for k,v in d["windows"].items()}, d["placebos"])
