import json, os
base = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules')
rows = json.load(open(os.path.join(base,'hidden','v13_table.json')))
overrides = {
 'aggressive-v2':'BEATS ITS OWN PUBLISHED FORM','aggressive-v3':'BEATS ITS OWN PUBLISHED FORM',
 'catalog-aronson-cn-extremes-price-volume':'STILL LESS THAN ITS PUBLISHED FORM',
 'crypto-dominance-rotation':'BEATS ITS OWN PUBLISHED FORM','crypto-halving-cycle':'STILL LESS THAN ITS PUBLISHED FORM',
 'crypto-stock-to-flow':'STILL LESS THAN ITS PUBLISHED FORM','disciplined-v2':'BEATS ITS OWN PUBLISHED FORM',
 'disciplined-v3':'BEATS ITS OWN PUBLISHED FORM','etf-trend-sleeve':'BEATS ITS OWN PUBLISHED FORM',
 'etf-trend-sleeve-weekly':'STILL LESS THAN ITS PUBLISHED FORM','folklore-f5-ichimoku':'BEATS ITS OWN PUBLISHED FORM (split: LONG/DECADE only)',
 'hunt-ehlers-mama-fama':'BEATS ITS OWN PUBLISHED FORM','hunt-mcclellan':'BEATS ITS OWN PUBLISHED FORM',
 'hunt-yield-curve-timer':'BEATS ITS OWN PUBLISHED FORM','quality-standalone':'STILL LESS THAN ITS PUBLISHED FORM (tie)',
 'residual-momentum':'BEATS ITS OWN PUBLISHED FORM','v0-aggressive':'BEATS WHAT WE HAVE',
 'v0-disciplined':'BEATS ITS OWN PUBLISHED FORM'}
for r in rows:
    if r['family'] in overrides: r['verdict'] = overrides[r['family']]
# artifact fixes: champion-reference rows misread as the family's own LONG/DECADE
for fam, keys in [('a1-seasonality',['LONG']),('insider-cluster',['LONG','DECADE']),('winners-blend',['LONG'])]:
    for r in rows:
        if r['family']==fam:
            for k in keys: r['roads'].pop(k, None)
from collections import Counter
counts = Counter(r['verdict'].split(' (')[0] for r in rows)
def cell(r,k):
    v = r['roads'].get(k)
    return f"${v}" if v else "—"
lines = []
lines.append('# V13 "BEST RULES" — SCOREBOARD')
lines.append('')
lines.append('**Program:** every strategy family in the record (v0–v12: house, native, constructed, judgment, hunt, catalog, crypto) got ONE more pass under a rule set Claude designed for that family — one spec per family, frozen in `BEST-RULES-SPEC.md` before the run, reasoned from signal mechanics and program-wide lessons only, never from peeking at that family\'s per-cell results. Point-in-time data only, real habitat costs, 20-seed placebos wherever the chassis supports them, per-period distributions as the headline in every folder, max drawdown beside every final.')
lines.append('')
lines.append('**Legality (Terry\'s condition):** public data and published signals only; no non-public information in any form; nothing manipulative; the watcher stays radar-only.')
lines.append('')
lines.append('**Verdict ceiling: CANDIDATE for every family.** Every road here has been seen before; the forward paper trial remains the only promotion court.')
lines.append('')
lines.append('**Roster closure:** 363 family folders, 363 with RESULTS.md — audited against the v12 COMPLETENESS LEDGER and CATALOG-MAP-MASTER.csv. The v12 `crypto-x-*` folders are cross-run determinations accounted inside each family\'s own record (and inside the crypto ledger), not separate families; the v12 `holdings-*` folders are grid sweeps accounted in the ledger\'s §11 reconciliation, not separate families. Two catalog families found as orphans in the final audit (catalog-aaii-pe-relative, catalog-aaii-wanger) were given their passes before this scoreboard was assembled. Every number below is assembled from the saved folder files; each family\'s own RESULTS.md governs over this summary.')
lines.append('')
lines.append('---')
lines.append('')
lines.append('## HEADLINE — what beat what we have, under my best honest rules')
lines.append('')
lines.append('Reference bars (published record, $100 pots): **published champion Value+Momentum — LONG $1,415.62 · DECADE $667.35 · CONT $544.47 · VAL $288.05.** SPY — LONG $822.94 · DECADE $367.80 · CONT $313.62 · VAL $187.77. Roads: LONG 2010→2026 · DECADE 2016→2026 · CONT 2019→2026 · VAL 2023→2026.')
lines.append('')
lines.append('**Twelve confirmed champion-beats (all CANDIDATE — Terry\'s confirmation rule passed on fresh years before counting):**')
lines.append('')
lines.append('| # | Family (my rules) | Result | Risk / fence |')
lines.append('|---|---|---|---|')
lines.append('| 1 | **Value+Momentum, top-2, no floor** | LONG **$2,923.60** · DECADE $906.90 · CONT $691.73 · VAL $461.20 — beat the published champion on ALL FOUR roads; placebos 19–20/20; confirmation 6/10 folds + both half-windows | DD −53.4%; a large share of the recent edge arrived in one shared quarter (2026 Q2); 16 quarters between new highs on LONG; deliberately no floor |')
lines.append('| 2 | **v0-aggressive, rebuilt** (20-day-high breakout only; spike entry deleted; −8% stop + channel exit) | LONG **$2,794.98** · DECADE $859.78 · CONT $826.86 · VAL $412.70 — all four roads over the published champion (the published v0 form was $83.90 LONG, dead everywhere); placebos 16/20 · 14/20 · 18/20 | DD −35.6% — the shallowest drawdown on this list |')
lines.append('| 3 | **hunt-weinstein-stage** (LONG only) | LONG **$2,316.14** vs champion $1,415.62; placebos 20/20 (median twin $262.89); published v12 form was $102.50, nearly inert | DD −35.7%; other roads beat only their own published form |')
lines.append('| 4 | **vm-twosleeve** (pure B/M top-2 + pure 12-1 momentum top-2, 50/50) | LONG $2,098.49 · DECADE **$950.05** · CONT $781.00 · VAL $330.60 — beats the published champion on all four roads AND beats the v13 top-2 host on DECADE and CONT | DD −35.0%; loses LONG and VAL to the v13 top-2 host |')
lines.append('| 5 | **A-1 Seasonality, top-3, semiannual, no floor** | DECADE **$1,309.46** · CONT $724.97 · VAL $472.70; placebos 20/20 | Max DD 63.93%; no honest LONG road; the margin came from 5→3 concentration — floor removal was a small net negative in folds |')
lines.append('| 6 | **crypto-trend-volscaled — COMBO + ETH sleeve only** (my design DELETED the vol scaler: binary 100%/0% sizing) | FULL combo **$8,007.29** vs $4,309.74 buy-hold; ETH $4,865.90 vs $522.96; confirmation road passed for ETH and COMBO | **BTC-only sleeve FAILED confirmation ($268.14 vs $360.02)** — printed exception; DD −74.0%/−75.7% |')
lines.append('| 7 | **N-F3, semiannual, count 5, no floor** (split record) | DECADE $848.79 · CONT $553.73 · VAL $291.28 over the champion | LONG $430.30 trails its own published form — STILL LESS on that road |')
lines.append('| 8 | **switch-blend-to-champion** (binary cliff → weight dial, N-F3 weight to 35%) | DECADE $814.81 · CONT $608.16 · VAL $419.37 — confirmed vs published champion | Trails pure v13 V+M on every road |')
lines.append('| 9 | **winners-blend** (V+M + momentum-basket sub-pots 67/33) | DECADE $759.42 · CONT $573.02 · VAL $397.81 — confirmed vs published champion | No LONG road (basket pond starts Nov 2016); trails v13 pure V+M everywhere; hindsight-selection caveat printed in its file |')
lines.append('| 10 | **osap-brand-capital** (scoped: BrandInvest only, ≥3 yrs ad history, 10 lowest names) | DECADE $721.91 · CONT $604.72 · VAL $381.03 over published champion prints; longest road 2016–2025 $973.54, placebos 20/20 | Data starts 2016 — champion LONG $1,415.62 NOT beaten; removing one driver stock drops the longest road to ~$427; trails all v13 leaders on comparable roads |')
lines.append('| 11 | **novel-x3-window-dressing** (LONG only, by a tie) | LONG $1,420.13 vs champion $1,415.62 (+$4.51, +0.3% — a statistical tie, stated as one); placebos 20/20 | Other roads trail badly |')
lines.append('| 12 | **combo-vm-lazyp and combo-vm-nf3** — beat the PUBLISHED record (confirmed) but NOT ADOPTED | Both trail pure V+M v13 form on every road | What they buy is shallower drawdowns (−35.4% vs −39.9%) and down-year resilience, not the highest final |')
lines.append('')
lines.append('**V13 road leaders (my-rules forms):** LONG — V+M top-2 **$2,923.60** · DECADE — vm-twosleeve **$950.05** · CONT — v0-aggressive **$826.86** · VAL — V+M top-2 **$461.20**.')
lines.append('')
lines.append('**Champion-beats that FAILED confirmation — printed, never counted:** V+M earnings-yield variant (folds 5/10 vs frozen ≥6/10 bar) · short-interest gate (1/7 folds vs ≥4/7) · gap-a4 distress gate (4/10 vs 6) · gap-a6 dividend-initiation (VAL nominally edged the champion; confirmation failed) · ladder-ablation trim form (LONG $1,486.59 nominally over the host; confirmation failed on ties — a fresh $100 pot never reaches the 3× arming level inside a fold, zero statistical power) · vm-plus-trend (LONG $2,163.37 nominal; folds 5/10 vs ≥6/10 → BEATS ITS OWN PUBLISHED FORM only) · hunt-livermore-pivotal (LONG champion-beat NOT CONFIRMED → BEATS ITS OWN PUBLISHED FORM, LONG only).')
lines.append('')
lines.append('**Verdict counts across all 363 families** (each folder\'s own verdict label; the confirmed champion-beats above are the subset of "BEATS WHAT WE HAVE" that passed Terry\'s confirmation rule and are scoped as their folders state):')
lines.append('')
for k in ['BEATS WHAT WE HAVE','BEATS ITS OWN PUBLISHED FORM','STILL LESS THAN ITS PUBLISHED FORM','STILL DEAD','STILL UNBUILDABLE','SEE FILE']:
    if counts.get(k): lines.append(f'- {k}: **{counts[k]}**')
lines.append('')
lines.append('---')
lines.append('')
lines.append('## LESSONS — what my rule choices got right and wrong, in aggregate')
lines.append('')
lines.append('**My simplifications paid.** Fewer names, slower tempo where inputs overlap, deleting floors that fight the signal\'s habitat, deleting the vol scaler (the crypto pass\'s only confirmed beat came from removing machinery), deleting rankings/caps in the disciplined rebuilds, and blend dials — these produced nearly every champion-beat on this board. The single biggest wins were concentration inside value+momentum (top-2, and the two-sleeve split) and rebuilding the dead v0-aggressive down to one honest entry rule.')
lines.append('')
lines.append('**My added machinery lost.** Regime gates as switches, staged exits, scale-ins, dual-confirmation exits, smoothed rankings, and quality/ROA co-equal ranks taxed almost everything they touched. Every overlay tried on the v13 champion host was a tax, even as a dial (trend gate, panic gate, buffer, breadth-10 no-floor): the host\'s edge is concentration plus full exposure.')
lines.append('')
lines.append('**Dials are not universal.** Gates-as-dials paid on continuous signals (breakout-regime breadth caps, the CAPE ladder), but on slow binary macro gauges the authors\' BINARY switch beat my graded dial decisively and repeatedly (both Novell bond families, Mayer 200-week, CBBI, Puell — the Puell dial made $242.52 where the published binary form made $552,249.49 on the full road). Grading the sizing on a threshold gauge dilutes the few real signals it ever gets.')
lines.append('')
lines.append('**Breadth is the recurring hidden variable.** Filters that shrank ponds destroyed diversification (a 10% basket cap left one crypto pot ~35% invested — a protection that works by never being invested is not a protection); breadth added to a bare signal genuinely helped (golden cross across sectors; Keller EAA 7→15 assets; the firm-level translation of a market timer that was never itself tradable).')
lines.append('')
lines.append('**Many "beats its own published form" verdicts are chassis wins, not signal wins.** Placebos sharing the chassis often profit too (the lottery family\'s median random twin finished ABOVE my form on all four roads; several TAA wins lose to a signal-free static mix). The labels in the folders say so wherever it is true.')
lines.append('')
lines.append('**Avoidance signals work modestly as vetoes, not engines** (short-interest gate, CHS gate, N-F1 inverted to an exclusion, Beneish M-score as a veto). **Win rate kept rising in my designs while expectancy fell** (RSI(2) at 76–78% win rate, expectancy down) — win rate is a costume. **Confirmation filters can be the defect** (waiting for exhaustion proof meant buying after the snap-back). **Judgment shelf:** my constructed rules mostly lost or stayed dead — Wyckoff, Buffett-qualitative, market profile, Dow theory, naked trader all STILL DEAD; Darvas, Edwards-Magee, Elliott, O\'Neil-judgment STILL LESS; Minervini-SEPA and Lynch beat only their own (near-zero) published forms. Insider-cluster following failed a third time — its no-signal sales-cluster control beat the purchase pot on both roads again; the watcher stays radar-only.')
lines.append('')
lines.append('---')
lines.append('')
lines.append('## FULL TABLE — every family')
lines.append('')
lines.append('My-rules finals are machine-extracted from each folder\'s own headline table (first figure on the road row); crypto families report on their FULL/confirmation roads. "—" = that road was not runnable for that family (data start, habitat, or construction — the folder states which). Each folder\'s RESULTS.md governs over this table.')
lines.append('')
lines.append('| Family | LONG | DECADE | CONT | VAL | FULL (crypto) | Verdict (folder\'s own label) |')
lines.append('|---|---|---|---|---|---|---|')
for r in sorted(rows, key=lambda x: x['family']):
    lines.append(f"| {r['family']} | {cell(r,'LONG')} | {cell(r,'DECADE')} | {cell(r,'CONT')} | {cell(r,'VAL')} | {cell(r,'FULL')} | {r['verdict']} |")
lines.append('')
lines.append('---')
lines.append('')
lines.append('*Assembled 2026-11-22 from the saved per-family files only. Champions for scale on every road appear in the headline section above and in each folder\'s own comparison table. Nothing in this program promotes: the forward paper trial is the only promotion court.*')
open(os.path.join(base,'SCOREBOARD.md'),'w').write('\n'.join(lines)+'\n')
print('written', len(lines), 'lines; counts:', dict(counts))
