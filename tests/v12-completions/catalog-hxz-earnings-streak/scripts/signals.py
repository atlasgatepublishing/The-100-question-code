import json, os, math, sys
sys.path.insert(0, os.path.join(os.path.expanduser('~'),'workspace/slice11-work'))
from engine import w04_frame, cand

def series(concept, suffix, famdir=None, years=range(2013,2026)):
    out = {}
    for y in years:
        if famdir:
            p = os.path.join(famdir,'data','frames',f'{concept}_{y}{suffix}.json')
            if os.path.exists(p): out[y] = {int(k):v for k,v in json.load(open(p)).items()}; continue
        out[y] = w04_frame(concept, y, suffix)
    return out

def merge_series(concepts, suffix, famdir=None):
    out = {}
    for c in concepts:
        s = series(c, suffix, famdir)
        for y, d in s.items():
            out.setdefault(y, {})
            for k,v in d.items(): out[y].setdefault(k, v)
    return out

class Data:
    def __init__(self, famdir):
        self.dir = famdir
        self.Assets = series('Assets','I'); self.Equity = series('StockholdersEquity','I')
        self.Liab = series('Liabilities','I'); self.Cash = series('CashAndCashEquivalentsAtCarryingValue','I')
        self.PPE = series('PropertyPlantAndEquipmentNet','I'); self.Shares = series('Shares','I')
        self.NI = series('NetIncomeLoss','D'); self.OI = series('OperatingIncomeLoss','D')
        self.CFO = series('NetCashProvidedByUsedInOperatingActivities','D')
        self.GP = series('GrossProfit','D'); self.LTD = series('LongTermDebtNoncurrent','I')
        self.DebtCur = series('DebtCurrent','I'); self.Sales = merge_series(['SalesRevenueNet','Revenues','RevenueFromContractWithCustomerExcludingAssessedTax'],'D')
    def x(self, famdir):
        self.Dep = series('DepreciationDepletionAndAmortization','D',famdir)
        self.Div = series('PaymentsOfDividendsCommonStock','D',famdir)
        self.Inv = series('InventoryNet','I',famdir); self.Rec = series('ReceivablesNetCurrent','I',famdir)
        self.SGA = series('SellingGeneralAndAdministrativeExpense','D',famdir)
        self.Tax = series('IncomeTaxExpenseBenefit','D',famdir)
        self.ProcStock = series('ProceedsFromIssuanceOfCommonStock','D',famdir)
        self.Repurchase = series('PaymentsForRepurchaseOfCommonStock','D',famdir)
        self.ProcLTD = series('ProceedsFromIssuanceOfLongTermDebt','D',famdir)
        self.RepayLTD = series('RepaymentsOfLongTermDebt','D',famdir)
        return self

def g(d, y, cik):
    return d.get(y, {}).get(cik)
def mve(D, cik, F):
    sh = g(D.Shares, F-1, cik); 
    return None  # price-based cap handled in engine pools via cap field not stored here

def by_year(fn, years=range(2015,2026)):
    out = {}
    for F in range(2016,2026):
        pool = {}
        for cik in cand:
            try: v = fn(cik, F)
            except Exception: v = None
            if v is not None and not (isinstance(v,float) and (math.isnan(v) or math.isinf(v))): pool[cik] = v
        if pool: out[F] = pool
    return out
