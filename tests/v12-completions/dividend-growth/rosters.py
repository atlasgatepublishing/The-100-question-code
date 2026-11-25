# Frozen Aristocrat rosters per CONSTRUCTION-SPEC.md / HUNT-LOG.md.
# R(Y) = index roster effective after the close of the last business day of January Y.
# Anchor: enumerated Jan-25-2018 list (53). Changes: published adds/removes,
# count-validated (2018=53, 2019=57, 2020=64, 2022=65, backward chain 2010=52).

R2018 = ["MMM","AFL","ABBV","ABT","APD","AOS","ADM","T","ADP","BDX","BF-B","CAH",
"CVX","CINF","CTAS","CLX","KO","CL","ED","DOV","ECL","EMR","XOM","FRT","BEN","GD",
"GPC","GWW","HRL","ITW","JNJ","KMB","LEG","LOW","MKC","MCD","MDT","NUE","PPG","PEP",
"PNR","PX","PG","ROP","SPGI","SHW","SWK","SYY","TROW","TGT","VFC","WMT","WBA"]

def _s(base, add=(), remove=()):
    out = [t for t in base if t not in set(remove)] + [t for t in add if t not in base]
    return sorted(out)

R2017 = _s(R2018, add=["BCR"], remove=["AOS","PX","ROP"])                    # 51
R2016 = _s(R2017, add=["HCP"], remove=["GD","FRT"])                           # 50
R2015 = _s(R2016, add=["CB","FDO","SIAL"])                                    # 53
R2014 = _s(R2015, add=["BMS"])                                                # 54
R2013 = _s(R2014, add=["PBI"])                                                # 55
R2012 = _s(R2013, add=["CTL"], remove=["T","CL","BEN","GPC","HCP","ITW","MDT","SYY","TROW","NUE"])  # 46
R2011 = _s(R2012, remove=["ECL","HRL","MKC"])                                 # 43
R2010 = _s(R2011, add=["AVY","BBT","GCI","GE","JCI","LM","MTB","PFE","STT","USB"], remove=["BF-B"])  # 52
R2019 = _s(R2018, add=["CB","PBCT","CAT","UTX"])                              # 57
R2020 = _s(R2019, add=["AMCR","ATO","O","ESS","ROST","ALB","EXPD"])           # 64
# UTX renamed RTX Apr-2020; RTX removed at Jan-2021 reconstitution, LEG also out (2021 lists)
R2021 = _s(R2020, add=["IBM","NEE","WST"], remove=["UTX","LEG"])              # 65 (RTX never enters: UTX slot ends)
R2022 = _s(R2021, add=["BRO","CHD"], remove=["T","PBCT"])                     # 65
R2023 = _s(R2022, add=["CHRW","NDSN","SJM","KVUE"], remove=["VFC"])           # 68
R2024 = _s(R2023, add=["FAST"], remove=["WBA","MMM"])                         # 67
R2025 = _s(R2024, add=["ERIE","ES","RGLD","FDS"])                              # 71

ROSTERS = {2010:R2010,2011:R2011,2012:R2012,2013:R2013,2014:R2014,2015:R2015,
2016:R2016,2017:R2017,2018:sorted(R2018),2019:R2019,2020:R2020,2021:R2021,
2022:R2022,2023:R2023,2024:R2024,2025:R2025,2026:R2025}

# Documented successor tapes (Yahoo backfills the successor ticker):
SUCCESSOR = {"PX":"LIN","UTX":"RTX","BBT":"TFC","CTL":"LUMN","HCP":"DOC"}

if __name__ == "__main__":
    for y in sorted(ROSTERS): print(y, len(ROSTERS[y]))
    print("union", len(sorted({t for v in ROSTERS.values() for t in v})))
