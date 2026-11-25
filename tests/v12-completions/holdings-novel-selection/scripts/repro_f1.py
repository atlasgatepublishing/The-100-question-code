import sys; sys.path.insert(0,'.')
import f1_engine as E
C=E.C
ciks=E.nf1.get_ciks(); filings={}
for t in E.UNIVERSE:
    cik=E.nf1.CIK_OVERRIDES.get(t,ciks[t][0]); filings[t]=E.nf1.get_filing_index(cik)
bars={t:C.bars_adj(E.payload_for(t)) for t in E.UNIVERSE+["SPY"]}
pb=C.FastPriceBook(bars)
sdates=E.cadence_dates(pb,"2016-11-21","2026-11-20","quarterly")
pools,_=E.nf1.build_pools(filings,sdates)
td=[d for d in pb.dates if "2016-11-21"<=d<="2026-11-20"]
def run_one(a,b,cash,floor): return E.run_pot_cad(pb,pools,a,b,cash,floor,sdates,n_hold=5)
out=C.run_v9(run_one,td,"2016-11-21","2026-11-20",100.0)
print("F1 repro:",round(out["final"],2),"expect 364.8")
