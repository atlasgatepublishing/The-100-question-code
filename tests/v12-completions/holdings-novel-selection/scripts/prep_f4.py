import sys, json; sys.path.insert(0,'.')
import f4_engine as F
eng=F.eng
ciks=eng.get_ciks(); facts={}
for t in eng.UNIVERSE:
    cik={"XOM":34088}.get(t, ciks[t][0]); facts[t]=eng.get_companyfacts(cik)
bars={t: F.get_prices_local(t) for t in eng.UNIVERSE+["SPY"]}
pb=eng.PriceBook(bars)
sel=F.cadence_dates(pb,"quarterly","2016-11-21","2026-11-20")
out={}
for d in sel:
    scored={}
    for t in eng.UNIVERSE:
        s=eng.score_name(facts[t], d)
        if s is not None: scored[t]=s
    out[d]=sorted(scored, key=lambda t: -scored[t]["EXCESS"])
json.dump(out, open("f4_ranked_cache.json","w"))
print("cached", len(out))
