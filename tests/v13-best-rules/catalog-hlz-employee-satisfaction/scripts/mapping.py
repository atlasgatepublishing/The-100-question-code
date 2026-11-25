#!/usr/bin/env python3
"""Frozen name -> ticker mapping for the GPTW/Fortune 100 Best panel.
Value: ticker string, or list of (first_year, last_year, ticker) era ranges
for names whose buyable security changed. Names absent here are private /
nonprofit / foreign-parent / partnership firms an investor could not buy
directly on a US exchange in the list year. Ticker is the security traded
AT THE TIME (e.g. WFM for Whole Foods until its 2017 acquisition)."""
MAP = {
 'AbbVie': 'ABBV', 'Accenture': 'ACN', 'Activision Blizzard': 'ATVI',
 'Adobe Systems': 'ADBE', 'Adobe Systems Incorporated': 'ADBE',
 'Aflac': 'AFL', 'Aflac Incorporated': 'AFL', 'Aflac, Inc.': 'AFL',
 'Alight Solutions': 'ALIT', 'Ally Financial Inc.': 'ALLY',
 'American Express': 'AXP', 'AT&T': 'T', 'Atlassian, Inc.': 'TEAM',
 'Autodesk, Inc.': 'ADBE',  # placeholder fixed below
 'Bank of America': 'BAC', 'Booz Allen Hamilton': 'BAH',
 'Box, Inc.': 'BOX', 'Bright Horizons': 'BFAM',
 'Bright Horizons Family Solutions': 'BFAM',
 'Brocade Communications Systems': 'BRCD',
 'Build-A-Bear Workshop': 'BBW', 'Burlington Stores, Inc.': 'BURL',
 'Cadence': 'CDNS', 'Calix': 'CALX', 'Camden Property Trust': 'CPT',
 'Capital One': 'COF', 'CarMax': 'KMX',
 'Chesapeake Energy': [(2021, 2026, 'CHK')],  # pre-2021 series destroyed by bankruptcy re-emergence under same ticker
 'Cisco': 'CSCO', 'Citrix Systems, Inc.': 'CTXS',
 'Colgate-Palmolive': 'CL', 'Comcast NBCUniversal': 'CMCSA',
 'Container Store': 'TCS', 'The Container Store': 'TCS',
 'Credit Acceptance': 'CACC', 'CrowdStrike': 'CRWD',
 'Darden Restaurants': 'DRI', 'Delta Air Lines': 'DAL',
 'Devon Energy': 'DVN', 'Discover': 'DFS', 'Dow': 'DOW',
 'DreamWorks Animation': 'DWA', 'DreamWorks Animation SKG': 'DWA',
 'Dropbox': 'DBX', 'EOG Resources': 'EOG', 'EOG Resources, Inc.': 'EOG',
 'FactSet Research Systems': 'FDS', 'FactSet Research Systems Inc.': 'FDS',
 'FedEx': 'FDX', 'FedEx Corporation': 'FDX',
 'First American Financial Corporation': 'FAF',
 'General Mills': 'GIS', 'GoDaddy': [(2015, 2026, 'GDDY')],
 'Goldman Sachs': 'GS', 'Goldman Sachs Group': 'GS',
 'Goldman Sachs Group, Inc.': 'GS', 'The Goldman Sachs Group, Inc.': 'GS',
 'Google': [(2010, 2013, 'GOOG'), (2014, 2026, 'GOOGL')],
 'Google Inc.': [(2010, 2013, 'GOOG'), (2014, 2026, 'GOOGL')],
 'Google, Inc.': [(2010, 2013, 'GOOG'), (2014, 2026, 'GOOGL')],
 'Grainger': 'GWW', 'W. W. Grainger': 'GWW', 'W.W. Grainger, Inc.': 'GWW',
 'HP Inc.': 'HPQ', 'HPE': 'HPE', 'Hasbro': 'HAS', 'Hasbro, Inc.': 'HAS',
 'Herman Miller': [(2010, 2020, 'MLHR'), (2021, 2026, 'MLKN')],
 'Hilton': 'HLT', 'Horizon Therapeutics': 'HZNP', 'HubSpot': 'HUBS',
 'Hyatt Hotels Corporation': 'H', 'IBM': 'IBM',
 'IHG Hotels & Resorts': 'IHG', 'Intel': 'INTC', 'Intel Corporation': 'INTC',
 'Intuit': 'INTU', 'Intuit Inc.': 'INTU', 'Intuit, Inc.': 'INTU',
 'J. M. Smucker': 'SJM', 'JAMF': 'JAMF', 'Keysight Technologies': 'KEYS',
 'L3Harris Technologies': 'LHX', 'Lennar Corporation': 'LEN',
 'Marriott International': 'MAR', 'Marriott International, Inc.': 'MAR',
 'Mastercard': 'MA', 'Mattel': 'MAT', 'Mattel, Inc.': 'MAT',
 'McCormick and Company': 'MKC', "Men's Wearhouse": 'MW',
 'Merck': 'MRK', 'MetLife': 'MET', 'Microsoft': 'MSFT',
 'Microsoft Corporation': 'MSFT', 'Monsanto': 'MON', 'Morningstar': 'MORN',
 'NVIDIA': 'NVDA', 'National Instruments': 'NATI', 'NetApp': 'NTAP',
 'Nordstrom': 'JWN', 'Nordstrom, Inc.': 'JWN',
 'Novo Nordisk': 'NVO', 'Novo Nordisk Inc.': 'NVO',
 'NuStar Energy': 'NS', 'NuStar Energy L.P.': 'NS', 'Nutanix': 'NTNX',
 'Paychex': 'PAYX', 'Pinnacle Financial Partners': 'PNFP',
 'Pluralsight, Inc.': 'PS', 'PulteGroup, Inc.': 'PHM',
 'Qualcomm': 'QCOM', 'Qualtrics': 'XM',
 'Rackspace Hosting': [(2010, 2016, 'RAX')],
 'Rackspace Technology™': [(2020, 2026, 'RXT')],
 'Red Hat, Inc.': 'RHT', 'Regeneron Pharmaceuticals Inc': 'REGN',
 'Robert Half Inc': 'RHI', 'Rocket Companies': [(2020, 2026, 'RKT')],
 'S&P Global Inc.': 'SPGI', 'Salesforce': 'CRM', 'salesforce': 'CRM',
 'Salesforce.com': 'CRM', 'salesforce.com': 'CRM',
 'SAP America, Inc.': 'SAP', 'ServiceNow': 'NOW', 'Splunk Inc.': 'SPLK',
 'Starbucks': 'SBUX', 'Starbucks Coffee': 'SBUX', 'Stryker': 'SYK',
 'Synchrony': 'SYF', 'Synopsys Inc.': 'SNPS', 'T-Mobile USA': 'TMUS',
 'Target Corporation': 'TGT', 'The Cheesecake Factory Incorporated': 'CAKE',
 'The Progressive Corporation': 'PGR', 'Tri Pointe Homes, Inc.': 'TPH',
 'Twilio Inc.': 'TWLO', 'UKG': None, 'ULTIMATE SOFTWARE': 'ULTI',
 'Ultimate Software': 'ULTI', 'Umpqua Bank': 'UMPQ',
 'United Therapeutics Corporation': 'UTHR', 'VMware, Inc.': 'VMW',
 'Vertex Pharmaceuticals Inc': 'VRTX', 'Visa': 'V',
 'Walker & Dunlop LLC': 'WD', 'Walmart Inc.': 'WMT',
 'Whole Foods Market': 'WFM', 'Workday': 'WDAY', 'Workiva': 'WK',
 'Zillow Group': 'ZG', 'Aéropostale, Inc.': 'ARO',
 'A&eacute;ropostale': 'ARO', 'Bread Financial': 'BFH',
 'Elevance Health': 'ELV', 'Autodesk': 'ADSK',
}
MAP['Autodesk, Inc.'] = 'ADSK'

def ticker_for(name, year):
    v = MAP.get(name)
    if v is None: return None
    if isinstance(v, str): return v
    for a, b, t in v:
        if a <= year <= b: return t
    return None
