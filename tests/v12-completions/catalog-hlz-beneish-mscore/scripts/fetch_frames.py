#!/usr/bin/env python3
"""Fetch EDGAR frames for CONCEPTS (2009-2025) into ../data/frames/.
Duration concepts -> CY{y}D ; instant concepts -> CY{y}Q4I."""
import urllib.request, json, os, time, sys
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','frames')
os.makedirs(OUT,exist_ok=True)
DUR=['NetIncomeLoss','NetCashProvidedByUsedInOperatingActivities','DepreciationDepletionAndAmortization','SellingGeneralAndAdministrativeExpense','Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet','CostOfGoodsAndServicesSold','CostOfRevenue','GrossProfit']
INST=['Assets','AssetsCurrent','LiabilitiesCurrent','CashAndCashEquivalentsAtCarryingValue','DebtCurrent','LongTermDebtNoncurrent','LongTermDebt','ReceivablesNetCurrent','InventoryNet','PropertyPlantAndEquipmentNet','StockholdersEquity','Liabilities']
def get(u,tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90).read()
        except Exception:
            if i==tries-1: raise
            time.sleep(2*(i+1))
for c in DUR+INST:
    kind='D' if c in DUR else 'I'
    for y in range(2009,2026):
        p=os.path.join(OUT,f'{c}_{y}{kind}.json')
        if os.path.exists(p): continue
        seg=f'CY{y}' if kind=='D' else f'CY{y}Q4I'
        u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{c}/USD/{seg}.json'
        try:
            d=json.loads(get(u)); json.dump({int(r['cik']):r['val'] for r in d['data']},open(p,'w'))
        except Exception as e: print(c,y,'MISS',e,flush=True)
        time.sleep(0.1)
print('done')
