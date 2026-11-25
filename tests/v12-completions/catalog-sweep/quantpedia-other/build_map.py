import csv, pathlib
out = pathlib.Path(__file__).parent
rows=[]
def add(cat,name,detail,state,fam,notes): rows.append([cat,name,detail,state,fam,notes])
E,N,C="EXISTING","NEW","CLOSED"
GRID_TAA="grid: cadence YES; holdings NO (fixed asset-class set, not top-N stock selection); rulebook YES; crypto cross-run YES (asset-class momentum/trend applies to coin baskets)"
GRID_SCR="grid: cadence YES; holdings YES (top-N screen count); rulebook YES; crypto cross-run NO (US fundamental/estimate data has no coin analogue)"
GRID_SCRP="grid: cadence YES; holdings YES (top-N screen count); rulebook YES; crypto cross-run PARTIAL (price/momentum legs only, fundamental legs no)"

# ---- QUANTPEDIA (free-visible unique titles) ----
QP="Quantpedia"
add(QP,"Asset Class Trend-Following","Monthly; bonds/commodities/equities/REITs; 11.27%",E,"sector-rotation / etf-trend-sleeve (v10-v12)","Faber-style asset-class trend; substance already run")
add(QP,"Time Series Momentum Effect","Monthly; multi-asset TSMOM",E,"hunt-tsmom-portfolio (v12)","Moskowitz-Ooi-Pedersen TSMOM already hunt-frozen")
add(QP,"Payday Anomaly","Daily; equities; seasonality around payday",E,"gap-a1-seasonality / holdings-a1-seasonality","Calendar/seasonality family variant")
add(QP,"Skewness Effect in Commodities","Monthly; commodities skewness sort",E,"hunt-tail-risk-sorts (v12)","Skewness sort substance covered; commodity habitat variant noted")
add(QP,"Asset Class Momentum","QuantConnect #2; cross-asset momentum",E,"sector-rotation / momentum-basket","Duplicate substance of asset-class momentum already run")
add(QP,"Sector Momentum","QuantConnect #3",E,"sector-rotation","Already run")
add(QP,"Overnight Anomaly","QuantConnect #4",E,"overnight-effect (v11/v12)","Already run incl. constructed form")
add(QP,"Forex Carry Trade","QuantConnect #5; FX carry",C,"","CLOSED: no free point-in-time FX forward/interest-differential history in program data stack; carry rules published but tradable FX data not available free at required history")
add(QP,"Volatility Effect in Stocks","QuantConnect #7; low-vol",E,"low-volatility / low-volatility-tournament","Already run")
add(QP,"Forex Momentum","QuantConnect #8",C,"","CLOSED: FX spot history free (Stooq) but Quantpedia form is currency-portfolio sort requiring full G10+EM cross history not in program stack; named data blocker - no free PIT FX universe dataset ingested")
add(QP,"Pairs Trading","QuantConnect #12; copula vs cointegration",N,"catalog-pairs-trading","NEW slug catalog-pairs-trading; "+GRID_SCRP)
add(QP,"Short Term Reversal","QuantConnect #13; 1-week reversal",E,"crypto-x-reversals / residual-momentum shelf","Short-term reversal substance covered in OSAP deep hunt + crypto cross-runs")
add(QP,"Momentum Effect in Stocks","QuantConnect #14; 12-1 momentum",E,"momentum-basket / holdings-momentum-basket","Already run")
add(QP,"Momentum Effect in Country Equity Indexes","QuantConnect #15",E,"sector-rotation (country-ETF form)","Variant of asset-class/sector momentum; universe form = country ETFs")
add(QP,"Mean Reversion Effect in Country Equity Indexes","QuantConnect #16",N,"catalog-country-index-mean-reversion","NEW slug catalog-country-index-mean-reversion; grid: cadence YES; holdings YES (country index count); rulebook YES; crypto cross-run NO (country indexes have no coin analogue)")
add(QP,"Liquidity Effect in Stocks","QuantConnect #18",E,"slow-illiquidity / hunt-liquidity-beta","Already run")
add(QP,"Volatility Risk Premium Effect","QuantConnect #20; options VRP",C,"","CLOSED: no free historical options price history (program-wide named blocker, census §5); index-options overlays were the only testable subset and already run as options-index/re-put-hedge")
add(QP,"Momentum Effect in Commodities","QuantConnect #21",E,"hunt-tsmom-portfolio / crypto-x-momentum shelf","Commodity momentum = TSMOM/cross-sectional momentum substance already run")
add(QP,"Term Structure Effect in Commodities","QuantConnect #22; futures curve roll yield",C,"","CLOSED: no free historical commodity futures term-structure (per-contract) history in program stack")
add(QP,"Small Capitalization Stocks Premium Anomaly","QuantConnect #25; size premium",E,"holdings-novel-selection / OSAP size sorts (deep-hunt-academic)","Size sort covered systematically in OSAP sweep")
add(QP,"Book-to-Market Value Anomaly","QuantConnect #26; HML value",E,"value-momentum-ey / vm-*","Already run")
add(QP,"Momentum Asset Allocation Strategy","Screener free list; 14.49%; multi-asset momentum",E,"sector-rotation / gem-dual-momentum","Variant of Asset Class Momentum")
add(QP,"Sector Momentum - Rotational System","Screener free list; 13.94%; equities",E,"sector-rotation","Variant of Sector Momentum")
add(QP,"FX Carry Trade","Screener free list title variant of Forex Carry Trade",C,"","CLOSED: same family as Forex Carry Trade; same FX data blocker named there")
add(QP,"Low Volatility Factor Effect in Stocks","Screener free list; 11.3%",E,"low-volatility","Variant title of Volatility Effect in Stocks")
add(QP,"Currency Momentum Factor","Screener screenshot; FX momentum factor",C,"","CLOSED: variant of Forex Momentum; same FX universe data blocker")
add(QP,"Currency Value Factor - PPP Strategy","Screener screenshot; PPP currency value",C,"","CLOSED: variant PPP/FX family; same FX universe data blocker plus no free PIT PPP series ingested")
add(QP,"Pairs Trading with Stocks","Screener screenshot title variant",N,"catalog-pairs-trading","Variant of Pairs Trading; maps to same NEW family catalog-pairs-trading")
add(QP,"Quantpedia Premium/Pro full database (900+ strategies; site also claims 1200+ via API)","Names/rules NOT visible free; Screener locked behind Premium/Pro subscription; free tier = ~70-82 strategies of which only the titles above are publicly enumerable without an account",C,"","CLOSED: PAYWALL - strategy names, rules, papers for 900+ Premium entries are not published free; cannot ingest line-by-line without a paid subscription, which Terry's free-everything rule excludes. Cross-check note: Quantpedia's source base is the same academic literature already swept systematically via OSAP/HXZ/HLZ/JKP in deep-hunt-academic, so the underlying papers are largely covered even though Quantpedia's own labels are not")

# ---- CXO ADVISORY ----
CX="CXO Advisory"
add(CX,"SACEMS - Simple Asset Class ETF Momentum Strategy (Top 1 / EW Top 2 / EW Top 3)","CXO's only 2 tracked strategies, momentum leg; 9 asset-class ETFs + cash, monthly",E,"sector-rotation / gem-dual-momentum","Three versions = holdings-count variants (1/2/3) of one family; substance = asset-class momentum already run; holdings grid will cover counts")
add(CX,"SACEVS - Simple Asset Class ETF Value Strategy (Best Value)","Term/credit/equity premium yields; SPY/LQD/TLT/cash, monthly",N,"catalog-cxo-sacevs","NEW slug catalog-cxo-sacevs; "+GRID_TAA)
add(CX,"SACEVS - Simple Asset Class ETF Value Strategy (Weighted)","Weighted version of SACEVS",N,"catalog-cxo-sacevs","Variant of same NEW family; weighting variant noted")
add(CX,"SACEVS-SACEMS Combined (50-50 Best Value-EW Top 2 / Best Value-EW Top 3 / Weighted-EW Top 3)","CXO combined value-momentum horse race",N,"catalog-cxo-sacevs","Blend variant of NEW SACEVS family + EXISTING SACEMS leg; run as blend cell, not separate family")
add(CX,"Seasonal SPY-VFITX","Horse-race comparator; calendar switch SPY/Treasuries",E,"gap-a1-seasonality / holdings-a1-seasonality","Seasonality substance already run")
add(CX,"SPY:SMA10-VFITX","Horse-race comparator / CXO benchmark; 10-month SMA timer",E,"folklore-f8-goldencross / etf-trend-sleeve","10-month MA timing substance already run (Faber SMA10)")
# CXO archive note is in SOURCE.md, not a strategy row (3513 research summaries are papers, covered by academic deep hunt)

# ---- ALLOCATE SMARTLY ----
AS="AllocateSmartly"
taa_existing={
 "Robust Asset Allocation - Balanced":"Alpha Architect RAA; trend/momentum asset allocation",
 "Robust Asset Allocation - Aggressive":"Alpha Architect RAA aggressive variant",
 "Adaptive Asset Allocation":"Butler/ReSolve AAA; momentum+vol weighting variant of asset-class momentum",
 "Tactical Permanent Portfolio":"Permanent-portfolio tactical variant",
 "The Trinity Portfolio":"Faber Trinity = GTAA + value/momentum tilt",
 "Global Tactical Asset Allocation 5":"Faber GTAA5",
 "Global Tactical Asset Allocation 13":"Faber GTAA13 variant (holdings/universe variant)",
 "Global Tactical Asset Allocation - Agg 3":"Faber GTAA aggressive variant",
 "Global Tactical Asset Allocation - Agg 6":"Faber GTAA aggressive variant",
 "Sector Relative Strength":"Faber sector RS",
 "Diversified Dual Momentum":"Hoffstein diversified dual momentum variant",
 "Traditional Dual Momentum":"Antonacci GEM dual momentum",
 "Composite Dual Momentum":"Antonacci composite variant",
 "Permanent Portfolio":"Browne permanent portfolio",
 "Ivy Portfolio":"Faber Ivy = GTAA buy-hold form",
 "Golden Butterfly":"PortfolioCharts buy-hold variant of permanent portfolio",
 "All-Weather/All-Seasons Portfolio":"Dalio all-weather buy-hold allocation",
 "Sell in May/Halloween Indicator":"Seasonality",
 "Annual Seasonality":"Piard annual seasonality",
 "Growth-Trend Timing":"Philosophical Economics GTT (see also hunt-gtt-unemployment for UE variant)",
 "Growth-Trend Timing - UE Rate":"GTT unemployment variant",
}
for name,note in taa_existing.items():
    fam = "permanent-portfolio" if name in ("Permanent Portfolio","Golden Butterfly","All-Weather/All-Seasons Portfolio","Tactical Permanent Portfolio") else ("gap-a1-seasonality / holdings-a1-seasonality" if "Seasonality" in name or "Sell in May" in name else ("gem-dual-momentum" if "Dual Momentum" in name else "sector-rotation / etf-trend-sleeve / blend-etf-chassis"))
    add(AS,name,"Tactical asset allocation (AllocateSmartly tracked list)",E,fam,note+" - substance already run; AllocateSmartly version is a variant")
taa_new={
 "TrendYCMacro":"catalog-taa-trendyieldcurve-macro","Pragmatic Asset Allocation":"catalog-taa-pragmatic-aa",
 "Gold Cross-Asset Momentum":"catalog-taa-gold-crossasset-momentum","Bold Asset Allocation - Aggressive":"catalog-taa-keller-baa",
 "Bold Asset Allocation - Balanced":"catalog-taa-keller-baa","Resilient Asset Allocation":"catalog-taa-keller-raa",
 "Lethargic Asset Allocation":"catalog-taa-keller-laa","Hybrid Asset Allocation - Balanced":"catalog-taa-keller-haa",
 "Hybrid Asset Allocation - Simple":"catalog-taa-keller-haa","Defensive Asset Allocation":"catalog-taa-keller-daa",
 "Vigilant Asset Allocation - Aggressive":"catalog-taa-keller-vaa","Vigilant Asset Allocation - Balanced":"catalog-taa-keller-vaa",
 "Classical Asset Allocation - Offensive":"catalog-taa-classical-aa","Classical Asset Allocation - Defensive":"catalog-taa-classical-aa",
 "Generalized Protective Momentum":"catalog-taa-keller-paa-gpm","Protective Asset Allocation":"catalog-taa-keller-paa",
 "Protective Asset Allocation - CPR":"catalog-taa-keller-paa","Elastic Asset Allocation - Defensive":"catalog-taa-keller-eaa",
 "Elastic Asset Allocation - Offensive":"catalog-taa-keller-eaa","Flexible Asset Allocation":"catalog-taa-keller-faa",
 "Defensive Adaptive Asset Allocation":"catalog-taa-kipnis-daaa","Minimum Correlation Portfolio":"catalog-taa-varadi-mincorr",
 "Percentile Channels":"catalog-taa-varadi-percentile-channels","Growth and Inflation Sector Timing":"catalog-taa-varadi-growth-inflation",
 "Inflation Compass - Original":"catalog-taa-varadi-inflation-compass","Inflation Compass - Enhanced":"catalog-taa-varadi-inflation-compass",
 "Optimal Trend Following":"catalog-taa-zakamulin-optimal-trend","Mama Bear Portfolio":"catalog-taa-muscular-mama-bear",
 "Papa Bear Portfolio":"catalog-taa-muscular-papa-bear","Risk Managed Momentum":"catalog-taa-risk-managed-momentum",
 "Accelerating Dual Momentum":"catalog-taa-accelerating-dual-momentum","SPY-COMP":"catalog-taa-novell-spy-comp",
 "Bond-COMP":"catalog-taa-novell-bond-comp","Tactical Bond Strategy":"catalog-taa-novell-tactical-bond",
 "Bond UI1":"catalog-taa-novell-bond-ui1","Composite Strategy":"catalog-taa-movement-capital-composite",
 "Active Combined Asset":"catalog-taa-stoken-aca","Defense First":"catalog-taa-carlson-defense-first",
 "Hybrid Asset Allocation 60/40":"catalog-taa-nlx-haa-6040","Dividend & Growth Allocation":"catalog-taa-choi-dividend-growth-alloc",
 "US Cross-Asset Momentum":"catalog-taa-us-crossasset-momentum","US Risk Parity Trend-Following":"catalog-taa-clare-riskparity-trend",
 "Global Risk Parity Trend-Following":"catalog-taa-clare-riskparity-trend","Paired Switching Strategy":"catalog-taa-glenn-paired-switching",
 "Quint Switching Filtered":"catalog-taa-glenn-quint-switching","Momentum Turning Points":"catalog-taa-momentum-turning-points",
 "Global Growth Cycle":"catalog-taa-link-global-growth-cycle","Global Growth Cycle Enhanced":"catalog-taa-link-global-growth-cycle",
 "Predicting Bond Returns":"catalog-taa-baltussen-predicting-bond-returns","Momentum Based Balancing":"catalog-taa-virag-momentum-balancing",
 "Excess Earnings Yield Dynamic - Valuation Only":"catalog-taa-elm-excess-earnings-yield","Excess Earnings Yield Dynamic with Momentum":"catalog-taa-elm-excess-earnings-yield",
 "Multi-Asset Momentum":"catalog-taa-vitral-multiasset-momentum","SPF Recession Probability":"catalog-taa-spf-recession-probability",
 "Regime-Based Strategic Asset Allocation":"catalog-taa-regime-based-saa","12-Month High Switch":"catalog-taa-faber-12m-high-switch",
 "Tactical Yield":"catalog-taa-faber-tactical-yield",
}
for name,slug in taa_new.items():
    add(AS,name,"Tactical asset allocation (AllocateSmartly tracked list); published paper/book rules exist outside AllocateSmartly paywall",N,slug,f"NEW slug {slug}; variant grouping as listed; "+GRID_TAA)
taa_closed={
 "OptimumV":"proprietary Financial Mentor (Todd Tresidder) rules never fully published free",
 "Optimum3":"proprietary Financial Mentor rules never fully published free",
 "All-Weather Quad Momentum":"proprietary Financial Mentor rules never fully published free",
 "Three Way Model":"proprietary Ned Davis Research model; rules never published free",
 "Efficiente Index":"proprietary JP Morgan index methodology not fully published free",
}
for name,why in taa_closed.items():
    add(AS,name,"Tactical asset allocation (AllocateSmartly tracked list)",C,"",f"CLOSED: proprietary strategy - {why}; AllocateSmartly tracks it for paid members only and does not publish the rules")
for name in ["Risk Premium Value - Best Value","Risk Premium Value - Weighted"]:
    add(AS,name,"AllocateSmartly meta/blend of tracked TAA strategies",E,"holdings-blends / vm-twosleeve","Blend of already-tracked value/momentum TAA legs; not a standalone published system")
for name in ["Max Diversification Portfolio","Equal Risk Contribution Portfolio","Max Sharpe Portfolio"]:
    add(AS,name,"Portfolio-construction optimiser benchmark on TAA universe",E,"holdings-blends","Optimiser construction already represented in blend/risk-parity work; benchmark, not a distinct alpha system")
add(AS,"60/40 Benchmark","Benchmark, not a strategy",E,"permanent-portfolio / holdings-blends","Benchmark row in source list; program benchmarks already include 60/40/SPY comparators")

# ---- AAII (57 screens, performance page 2026-10-30) ----
AA="AAII"
aaii_existing={
 "ADR Screen":("holdings-novel-selection / OSAP ADR sorts","Non-US ADR value/growth sort covered in academic sweep"),
 "Buffett: Hagstrom Screen":("judgment-buffett-qualitative / hunt-graham-defensive shelf","Hagstrom Buffett interpretation; judgment shelf"),
 "Buffettology: EPS Growth":("judgment-buffett-qualitative","Buffettology variant"),
 "Buffettology: Sustainable Growth Screen":("judgment-buffett-qualitative","Buffettology variant"),
 "Dividend (High Relative Yield) Screen":("dogs-dividend / dividend-growth","High-yield value substance"),
 "Dogs of the Dow Screen":("dogs-dividend / holdings-dogs","Already run native + holdings grid"),
 "Dogs of the Dow: Low Priced 5 Screen":("dogs-dividend / holdings-dogs","Dogs variant (5-stock low-price form) - holdings-count variant"),
 "Graham--Defensive Investor (Non-Utility) Screen":("hunt-graham-defensive","Already hunt-frozen/run"),
 "Graham--Defensive Investor (Utility) Screen":("hunt-graham-defensive","Utility variant of Graham defensive"),
 "Graham--Enterprising Investor Revised":("judgment-graham-enterprising","Already on judgment shelf"),
 "Insider Net Purchases Screen":("insider-cluster / holdings-insider-clusters","Insider-buying substance already run"),
 "Lynch Screen":("judgment-lynch","Already on judgment shelf"),
 "Magic Formula Screen":("magic-formula / holdings-magic-formula","Already run native broad universe"),
 "O'Neil's CAN SLIM No Float Screen":("gap-a8-canslim / canslim-oneil-judgment","CAN SLIM judgment shelf"),
 "O'Neil's CAN SLIM Revised 3rd Edition Screen":("gap-a8-canslim / canslim-oneil-judgment","CAN SLIM variant"),
 "O'Neil's CAN SLIM Screen":("gap-a8-canslim / canslim-oneil-judgment","CAN SLIM variant"),
 "Piotroski: High F-Score Screen":("piotroski / holdings-piotroski","Already run"),
 "Zweig Screen":("hunt-zweig-growth-screen","AAII Zweig stock screen = Zweig growth screen already hunt-frozen"),
 "Est Rev: Top 30 Up":("hunt-analyst-revisions","Analyst-revision family; AAII count-capped variant (30)"),
 "Est Rev: Up 5% Screen":("hunt-analyst-revisions","Analyst-revision variant"),
 "Est Rev: Down 5% Screen":("hunt-analyst-revisions","Down-revision variant (short/avoid leg noted)"),
 "Est Rev: Lowest 30 Down":("hunt-analyst-revisions","Down-revision count-capped variant"),
}
for n,(f,note) in aaii_existing.items(): add(AA,n,"AAII stock screen (performance list, data 2026-10-30)",E,f,note)
aaii_new={
 "Cash Rich Firms Screen":"catalog-aaii-cash-rich","Dual Cash Flow Screen":"catalog-aaii-dual-cash-flow",
 "Dreman Screen":"catalog-aaii-dreman","Dreman With Est Revisions Screen":"catalog-aaii-dreman",
 "Driehaus Screen":"catalog-aaii-driehaus","Driehaus Revised Screen":"catalog-aaii-driehaus",
 "Fisher (Philip) Screen":"catalog-aaii-fisher","Fundamental Rule of Thumb Screen":"catalog-aaii-fundamental-rule-of-thumb",
 "Kirkpatrick Bargain Screen":"catalog-aaii-kirkpatrick","Kirkpatrick Growth Screen":"catalog-aaii-kirkpatrick",
 "Kirkpatrick Value Screen":"catalog-aaii-kirkpatrick","Lakonishok Screen":"catalog-aaii-lakonishok",
 "Muhlenkamp Screen":"catalog-aaii-muhlenkamp","Neff Screen":"catalog-aaii-neff",
 "O'Shaughnessy: All Cap Screen":"catalog-aaii-oshaughnessy","O'Shaughnessy: Growth Market Leaders Screen":"catalog-aaii-oshaughnessy",
 "O'Shaughnessy: Growth Screen II":"catalog-aaii-oshaughnessy","O'Shaughnessy: Small Cap Growth & Value Screen":"catalog-aaii-oshaughnessy",
 "O'Shaughnessy: Tiny Titans Screen":"catalog-aaii-oshaughnessy-tiny-titans","O'Shaughnessy: Value Screen":"catalog-aaii-oshaughnessy",
 "P/E Relative Screen":"catalog-aaii-pe-relative","Price-to-Free-Cash-Flow Screen":"catalog-aaii-price-to-fcf",
 "Price-to-Sales Screen":"catalog-aaii-price-to-sales","Return on Equity Screen":"catalog-aaii-roe",
 "Rule #1 Investing Screen":"catalog-aaii-rule-number-one","Schloss Screen":"catalog-aaii-schloss",
 "Stock Market Winners Screen":"catalog-aaii-stock-market-winners","T. Rowe Price Screen":"catalog-aaii-trowe-price",
 "Templeton Screen":"catalog-aaii-templeton","Value on the Move--PEG With Est Growth Screen":"catalog-aaii-value-on-the-move",
 "Value on the Move--PEG With Hist Growth Screen":"catalog-aaii-value-on-the-move","Wanger Screen":"catalog-aaii-wanger",
 "Weiss Blue Chip Div Yield Screen":"catalog-aaii-weiss-blue-chip-yield",
}
for n,slug in aaii_new.items(): add(AA,n,"AAII stock screen (performance list, data 2026-10-30); AAII publishes full screening criteria free on its site",N,slug,f"NEW slug {slug}; guru/factor screen not previously run as its own named form; variants grouped to same slug where shown; "+GRID_SCR)

with open(out/"CATALOG-MAP-QUANTPEDIA-OTHER.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["catalog","entry_name","entry_detail","state","program_family","notes"]); w.writerows(rows)
from collections import Counter
print(len(rows), Counter(r[3] for r in rows))
for cat in sorted(set(r[0] for r in rows)):
    sub=[r for r in rows if r[0]==cat]; print(cat, len(sub), Counter(r[3] for r in sub))
print("NEW slugs:", sorted(set(r[4] for r in rows if r[3]=="NEW")))
