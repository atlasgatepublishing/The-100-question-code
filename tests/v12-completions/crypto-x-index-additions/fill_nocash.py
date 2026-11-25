import json, run_index_additions as R
reg=R.load_registry(); coins={}
for cid,info in reg.items():
    if info["rows"]: coins[cid]=(R.Coin(info["rows"]), info["symbol"])
weekly=json.load(open(R.SNAP))
entries,xs=R.build_events(weekly,reg)
btc=coins[1][0]; cal_all=[d for d in btc.sorted_dates if d<=R.END_ALL]
res=json.load(open("results.json"))
for name,road in R.ROADS.items():
    r0,r1=road; cal=[d for d in cal_all if r0<=d<=r1]
    trades,sk=R.make_trades(entries,xs,coins,road)
    for lab,v9 in (("native",False),("v9",True)):
        sim=R.simulate(trades,coins,cal,0.006,v9)
        assert sim["final"]==res["roads"][name][lab]["final"], (name,lab,sim["final"],res["roads"][name][lab]["final"])
        res["roads"][name][lab]["skipped_nocash"]=sim["skipped_nocash"]
        print(name,lab,"final ok",sim["final"],"nocash",sim["skipped_nocash"],flush=True)
json.dump(res,open("results.json","w"),indent=1)
print("merged")
