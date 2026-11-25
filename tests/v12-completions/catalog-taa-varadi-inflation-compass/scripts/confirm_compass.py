import sys, os, json
sys.path.insert(0, os.path.expanduser("~/workspace/slice8-scratch"))
import engine
from engine import cadence_days, simulate
import runner
from datetime import date
p = runner.sector_panel(extra_fred=[("T5YIE","t5yie.csv")])
dec = cadence_days(p.dates, "monthly")
WINS = {"CONF-A 2010-2018": (date(2010,1,1), date(2018,12,31)),
        "CONF-B 2013-2021": (date(2013,1,1), date(2021,12,31)),
        "CONF-C 2015-2023": (date(2015,1,1), date(2023,12,31))}
out={}
for name,(a,b) in WINS.items():
    idx=[i for i,d in enumerate(p.dates) if a<=d<=b]
    spy = 100.0 * p.close("SPY", idx[-1]) / p.close("SPY", idx[0])
    res={}
    for rb in ("native","house"):
        fn = runner.compass_factory(p)
        r = simulate(p, idx, dec, fn, rulebook=rb)
        res[rb]={"final":r["final"],"max_dd_pct":r["max_dd_pct"]}
    out[name]={"spy_price_only_final":round(spy,2), **res}
    print(name, out[name])
folder=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-varadi-inflation-compass")
json.dump(out, open(os.path.join(folder,"confirmation.json"),"w"), indent=1)
