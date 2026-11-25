import json, os
HERE=os.path.dirname(os.path.abspath(__file__)); FAM=os.path.join(HERE,'..')
FR=os.path.join(FAM,'data','frames')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
def frame(concept,kind,years=range(2009,2026)):
    return {y:{int(k):v for k,v in loadj(os.path.join(FR,f'{concept}_{y}{kind}.json')).items()} for y in years}
def revenue(years=range(2009,2026)):
    out={}
    for y in years:
        d={}
        for c in ('SalesRevenueNet','RevenueFromContractWithCustomerExcludingAssessedTax','Revenues'):
            for k,v in loadj(os.path.join(FR,f'{c}_{y}D.json')).items():
                d.setdefault(int(k),v)
        out[y]=d
    return out
def cogs(years=range(2009,2026)):
    out={}
    for y in years:
        d={}
        for c in ('CostOfGoodsAndServicesSold','CostOfRevenue'):
            for k,v in loadj(os.path.join(FR,f'{c}_{y}D.json')).items():
                d.setdefault(int(k),v)
        out[y]=d
    return out
def g(fr,y,cik):
    return fr.get(y,{}).get(cik)
