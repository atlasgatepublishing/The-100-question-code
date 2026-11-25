import json, os, statistics
BASE=os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
SPYRAW={r[0]:r[1] for r in json.load(open(os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/px_SPY.json')))}
ROADS_F={'LONGEST_2016_2025':list(range(2016,2026)),'DECADE_2017_2025':list(range(2017,2026)),'CONT_2019_2025':list(range(2019,2026)),'VAL_2023_2025':list(range(2023,2026)),'FOLD_2016_2020':list(range(2016,2021)),'FOLD_2021_2025':list(range(2021,2026))}
TITLES={'pe-relative':'AAII P/E Relative Screen','price-to-fcf':'AAII Price-to-Free-Cash-Flow Screen','price-to-sales':'AAII Price-to-Sales Screen','roe':'AAII Return on Equity Screen','rule-number-one':'AAII Rule #1 Investing Screen','schloss':'AAII Schloss Screen','stock-market-winners':'AAII Stock Market Winners Screen','templeton':'AAII Templeton Screen','trowe-price':'AAII T. Rowe Price Screen','value-on-the-move':'AAII Value on the Move — PEG With Hist Growth Screen'}
PRACT={'pe-relative':"AAII members run this as a monthly Stock Investor Pro screen and hold the full passing list (median ~36 names in AAII's own tracking) until a name drops off; nobody runs a 3-stock version. Imposed here: June annual formation on annual EDGAR frames instead of monthly re-screening, the W04 ~630-name pool instead of AAII's ~6,600-name universe, program costs (AAII's published tracking charges none and excludes dividends — our prices are dividend-adjusted, which flatters us vs AAII's own prints), and the grid's small-count cells, which are program variants, not practitioner practice.",
'price-to-fcf':"Practitioners hold the full passing list from AAII's monthly screen re-runs; turnover is driven by names failing the positive-FCF / below-average-multiple tests. Imposed: annual June formation, W04 pool, program costs, FCF from slice-fetched capex frames; small-count cells are program variants.",
'price-to-sales':"Practitioners hold the full passing list, re-screened monthly in Stock Investor Pro. Imposed: the exact SIP cut-offs are paywalled, so the pass rule is a labelled construction from AAII's published description; annual formation; W04 pool; program costs.",
'roe':"Practitioners hold the full passing list (~46 names when AAII profiled it in 2005; ~20% monthly turnover in AAII's tracking). Imposed: pool-median substitutes for industry-median on the 1.5x ROE gate, the qualitative secondary filters are not imposed (no published numeric cut-offs), annual formation, program costs.",
'rule-number-one':"Town's actual practitioners do the qualitative half by hand — moat, management, 'meaning to you' — and hold a handful of names for years; AAII's screen is the mechanical shadow of that. Imposed: ROE proxies ROIC, the equity-growth leg is relaxed (named in the spec), sticker price is proxied by a PEG gate, annual formation, program costs. The hand-done half of Town's method is exactly the part no screen can run.",
'schloss':"Schloss himself held ~100 names for years, bought on limit orders near lows, and sold around +50%; AAII's screen is a monthly list. Imposed: the insider-ownership leg is dropped (no free PIT panel), the new-low leg is approximated on monthly closes, annual formation, program costs; no +50% sell rule is imposed (none in AAII's screen form).",
'stock-market-winners':"Reinganum's rules were a study of past winners, not a live practitioner system; AAII's screen is the practitioner form (monthly list, all passing). Imposed: three of the nine rules are unbuildable free (Datagraph rating, quarterly acceleration, the <20M-share rule AAII itself drops) and are named in the spec. The deeper problem is habitat: Reinganum's winners were predominantly small companies, and the program's free broad stack is the top-600 filers by assets — the prey barely exists in this pond, which is why the passing pool is ~0–1 names a year.",
'templeton':"Templeton himself bought globally, at maximum pessimism, and held for years; AAII's screen is a domestic monthly list built from his stated tests. Imposed: analyst-estimate legs dropped (no free PIT consensus), annual formation, W04 pool, program costs. The kept legs include the strictest one — EPS rising every single year for five years — which is why passing pools are small (4–6 names).",
'trowe-price':"T. Rowe Price's own funds run the philosophy with analyst work on top; AAII's screen is the mechanical version (monthly list). Imposed: insider-ownership and 7-year-growth legs dropped and named; annual formation; program costs.",
'value-on-the-move':"Practitioners run both PEG variants as monthly AAII screens and hold the full passing lists. Imposed: only the Hist Growth variant is buildable — the Est Growth variant needs point-in-time consensus estimates that do not exist free, and is closed STILL UNBUILDABLE inside this folder; the quarterly-earnings leg is dropped (annual frames); RS is a 6-month monthly proxy for the 26-week rank."}
def spy_eff(pools, road):
    forms=ROADS_F[road]
    live=[f for f in forms if int(pools.get(str(f),0))>0]
    if not live: return None, None
    a=SPYRAW.get(f'{live[0]:04d}-06'); b=SPYRAW.get(f'{forms[-1]+1:04d}-06')
    return (round(100.0*b/a,2) if a and b else None), live[0]
def pstats(curve):
    vals=[100.0]+[v for _,v in curve]
    rets=[vals[i]/vals[i-12]-1 for i in range(12,len(vals),12)]
    if not rets: return None
    pos=sum(1 for r in rets if r>0); run=0; worst=0
    for r in rets:
        run=run+1 if r<=0 else 0; worst=max(worst,run)
    peak=vals[0]; cur=0; longest=0
    for v in vals:
        if v>=peak: peak=v; cur=0
        else: cur+=1; longest=max(longest,cur)
    return dict(n=len(rets),pos=pos,med=round(statistics.median(rets)*100,1),mean=round(statistics.mean(rets)*100,1),best=round(max(rets)*100,1),worst=round(min(rets)*100,1),yr=[round(r*100,1) for r in rets],loserun=worst,nohigh=longest)
for slug,title in TITLES.items():
    d=os.path.join(BASE,f'catalog-aaii-{slug}')
    res=json.load(open(os.path.join(d,'results.json')))
    g=res['grid']; spy=res['spy']; pools=res['pool_sizes']
    nat=g['native|annual|ALL']; L=nat['LONGEST_2016_2025']
    eff={r: spy_eff(pools,r) for r in ROADS_F}
    spyL=eff['LONGEST_2016_2025'][0]
    cells=sorted(g.items(), key=lambda kv:-kv[1]['LONGEST_2016_2025']['final'])
    confirmed=[]
    for k,c in cells:
        if k=='native|annual|ALL': continue
        f1=c['FOLD_2016_2020']; f2=c['FOLD_2021_2025']
        e1=eff['FOLD_2016_2020'][0]; e2=eff['FOLD_2021_2025'][0]
        if e1 and e2 and f1['final']>e1 and f2['final']>e2 and c['LONGEST_2016_2025']['placebos_beaten']>=15 and f1['placebos_beaten']>=15 and f2['placebos_beaten']>=15:
            confirmed.append(k)
        if len(confirmed)>=3: break
    beats=sum(1 for r in ('LONGEST_2016_2025','DECADE_2017_2025','CONT_2019_2025','VAL_2023_2025') if eff[r][0] is not None and nat[r]['final']>eff[r][0])
    maxpool=max(int(v) for v in pools.values())
    extra=" The Est Growth variant is **STILL UNBUILDABLE** (named blocker: point-in-time analyst consensus history does not exist free)." if slug=='value-on-the-move' else ""
    if maxpool<=1:
        verdict="STILL UNBUILDABLE (on the free broad stack)"
        vtxt=f"the frozen construction passes at most {maxpool} name(s) in any formation year on the W04 top-600-filer stack (pools: {pools}) — the screen's habitat (small, low-P/B, high-RS names) barely exists in this pond, so no honest test is possible here. This is a habitat/data closure, not a death verdict on the screen itself; it is recorded with the pool census as evidence."
    elif beats>=3 and spyL and L['final']>=spyL:
        verdict="REAL BUT SMALLER" if L['final']<1415.62 else "ALIVE AS PUBLISHED"
        vtxt=f"the published-form (ALL-passing, annual) portfolio beats effective-window SPY on {beats}/4 roads but finishes below the champion reference prints — a real ranking with a smaller payoff."
    elif confirmed:
        verdict="ALIVE ONLY AS VARIANT (candidate-grade)"
        vtxt=f"the published form beats effective-window SPY on only {beats}/4 roads, but confirmed variant cell(s) {confirmed} pass Terry's confirmation rule (both folds beat their effective-window SPY, placebos ≥15/20). Candidate-grade only."
    elif spyL and L['final']<=spyL and beats<=1:
        verdict="DEAD EVERYWHERE ON THE GRID"
        vtxt=f"the published form finishes at ${L['final']} vs effective-window SPY ${spyL} on LONGEST and beats effective-window SPY on only {beats}/4 roads; no grid cell passes the confirmation rule (folds + placebos ≥15/20)."
    else:
        verdict="STILL DEAD"
        vtxt=f"the published form finishes at ${L['final']} vs effective-window SPY ${spyL} on LONGEST (beats effective-window SPY on {beats}/4 roads) and no grid cell passes the confirmation rule."
    if confirmed and verdict.startswith("REAL BUT SMALLER"):
        verdict="REAL BUT SMALLER (published form) — plus ALIVE ONLY AS VARIANT cells"
    ps=pstats(L['curve'])
    lines=[]
    lines.append(f"# catalog-aaii-{slug} — RESULTS (v12, Second-Chance Protocol)\n")
    lines.append(f"Family: {title}. Spec frozen in `SPEC-FROZEN.md` (construction labelled there); hunt in `HUNT-LOG.md`. Signals built from SEC EDGAR frames on the program W04 broad stack (monthly prices 2016–2026). Passing pools by formation year: {pools}. Crypto cross-run: **NOT-APPLICABLE** — equity accounting screen, no coin analogue. Daily/weekly/biweekly cadences: NOT-APPLICABLE to an annual accounting signal (grid cadences = annual / quarterly-carried / monthly-carried). Placebos draw random names from the same *passing* pool, so they test the ranking and count, not the screen itself — read them that way.\n")
    lines.append(f"**Effective-window disclosure (binding):** W04 frames begin 2014 and prices begin 2016, so screens needing 5-year histories cannot form until 2019–2020; in earlier formations the portfolio sits in cash (finals include those idle years). The honest comparator is SPY over the *effective invested window* (first non-empty formation → road end), printed beside the full-window SPY. Effective starts: "+", ".join(f"{r} from {eff[r][1]}" for r in ('LONGEST_2016_2025','DECADE_2017_2025','CONT_2019_2025','VAL_2023_2025'))+".\n")
    lines.append(f"## Verdict: {verdict}\n")
    lines.append(f"{vtxt}{extra} Window caveat: champions' prints are on 2010-start program roads; every road here starts 2016 (no free broad price stack reaches 2010), so effective-window SPY is the honest comparator.\n")
    lines.append("## Headline numbers ($100 start, gains reinvested, program costs)\n")
    lines.append("Native form = ALL passing names, equal-weight, annual June formation, native rulebook (the program approximation of AAII's monthly all-passing tracking):\n")
    lines.append("| Road | Native form | SPY effective window | SPY full window | Champion (own road, ref) |")
    lines.append("|---|---|---|---|---|")
    champ={'LONGEST_2016_2025':'V+M $1,415.62 (LONG)','DECADE_2017_2025':'V+M $667.35','CONT_2019_2025':'V+M $544.47','VAL_2023_2025':'V+M $288.05'}
    for r in ('LONGEST_2016_2025','DECADE_2017_2025','CONT_2019_2025','VAL_2023_2025'):
        lines.append(f"| {r} | **${nat[r]['final']}** | ${eff[r][0]} | ${spy[r]} | {champ[r]} |")
    lines.append(f"\nMax drawdown (LONGEST, native): {L['maxdd_pct']}%. Total costs (LONGEST, native): ${L['costs']}. House-rulebook native cell (v9 −15% floor): LONGEST ${g['house|annual|ALL']['LONGEST_2016_2025']['final']}.\n")
    lines.append("Top grid cells by LONGEST final (full grid below):\n")
    lines.append("| Cell | LONGEST | DECADE | CONT | VAL | Placebos (LONGEST) |")
    lines.append("|---|---|---|---|---|---|")
    for k,c in cells[:5]:
        lines.append(f"| {k} | ${c['LONGEST_2016_2025']['final']} | ${c['DECADE_2017_2025']['final']} | ${c['CONT_2019_2025']['final']} | ${c['VAL_2023_2025']['final']} | {c['LONGEST_2016_2025']['placebos_beaten']}/20 |")
    if confirmed: lines.append(f"\nConfirmation rule **passed** by: {confirmed} (both folds beat their effective-window SPY; fold placebos ≥15/20). All other top cells fail it and print as LUCK where they gleam.")
    else: lines.append("\nConfirmation rule: **no cell passes** (any gleaming cell fails a fold or its placebos) — such cells print as LUCK, not life.")
    if ps:
        lines.append(f"\n## Per-period distribution — native tempo: ANNUAL (median is the headline)\n")
        lines.append(f"**Native (ALL) form, LONGEST ({ps['n']} annual periods, including idle cash years at 0%):** made money in {ps['pos']} of {ps['n']} · **median period {ps['med']:+}%** · best {ps['best']:+}% · worst {ps['worst']:+}% · longest losing run {ps['loserun']} · longest stretch between new highs {ps['nohigh']} months. Year by year (%): {', '.join(f'{x:+}' for x in ps['yr'])}. (Secondary, average only: {ps['mean']:+}%.)\n")
    lines.append("## Practitioners vs imposed\n")
    lines.append(PRACT[slug]+"\n")
    lines.append("## Fences\n- Survivorship at the W04 entry gate (current-ticker mapping + Yahoo coverage) **flatters** every number; vanished→ZERO was armed for mid-hold disappearances.\n- EDGAR frames are calendarized with restatements folded in and a ≥6-month PIT lag — flatters slightly.\n- EPS is derived (NetIncome/Shares), not AAII's diluted continuing-operations EPS — unsigned bias, named in the spec.\n- AAII's own published track records for these screens are price-only, costless, monthly — not comparable to these prints; the comparison that counts here is effective-window SPY under program costs.\n")
    lines.append(f"## FULL GRID (60 cells — every cell printed, finals in $, placebos /20; SPY full-window: LONGEST ${spy['LONGEST_2016_2025']} · DECADE ${spy['DECADE_2017_2025']} · CONT ${spy['CONT_2019_2025']} · VAL ${spy['VAL_2023_2025']}; effective-window SPY in the headline table)\n")
    lines.append("| Cell | LONGEST | pb | DECADE | pb | CONT | pb | VAL | pb |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for k in sorted(g):
        c=g[k]
        lines.append(f"| {k} | ${c['LONGEST_2016_2025']['final']} | {c['LONGEST_2016_2025']['placebos_beaten']} | ${c['DECADE_2017_2025']['final']} | {c['DECADE_2017_2025']['placebos_beaten']} | ${c['CONT_2019_2025']['final']} | {c['CONT_2019_2025']['placebos_beaten']} | ${c['VAL_2023_2025']['final']} | {c['VAL_2023_2025']['placebos_beaten']} |")
    open(os.path.join(d,'RESULTS.md'),'w').write('\n'.join(lines))
    print(slug,'—',verdict,'— native LONGEST',L['final'],'vs SPY-eff',spyL)
