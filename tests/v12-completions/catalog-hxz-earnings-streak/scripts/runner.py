import json, os, sys, math, time
sys.path.insert(0,'/tmp/slice11')
import numpy as np
from engine import Family, run_grid, period_stats, ROADS, spy_final, cap_of, cand, px
from signals import Data, g, by_year
from fetch import frame, frame_q

BASE = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
COMMON_FENCES = """## Common fences (all families in this slice)
- Universe = program W04 broad stack (658 candidate CIKs, 630 with monthly Yahoo prices 2016-01..2026-11, current CIK->ticker map). NOT the full CRSP/Compustat cross-section the OPs used. Survivorship at the entry gate FLATTERS every number; prices vanishing mid-hold are written to ZERO.
- Prices start 2016 on every free broad stack in this program, so the program LONG road (2010) is not runnable; roads are the honest analogs: LONGEST 2016-2025 formations, DECADE 2017-2025, CONT 2019-2025, VAL 2023-2025 (June formations, 12-month holds). Same-window SPY is the honest comparator; champion prints (different windows) are reference only.
- Signal data = SEC EDGAR frames (calendarized, restatements folded in, no per-fact filed dates). PIT enforced by formation lag: June formation of year F uses fiscal years <= F-1 only (>=6-month lag). Bias: FLATTERS slightly.
- Costs: program tiered per side by market cap (>= $5B 0.10%; >= $1B 0.25%; < $1B/unknown 0.75%).
- v9 house rulebook: identical picks/costs plus the program floor - at any month-end, if equity <= 85% of road-to-date peak, liquidate to cash until next June formation.
- Published HXZ form: cross-sectional decile/quintile sort, long the OP-signed leg, long-short in the OP; the program habitat is long-only $100, so only the long leg is built (named approximation: removes half the published spread). HXZ holding-period variants (1/6/12 months) map onto the grid cadence dimension (monthly/quarterly-carried/annual re-equalization on the annual signal); the native cell is annual formation, quintile, native rules, broad universe.
- Grid: primary signal full grid (universe {broad, nonfin} x rulebook {native, house} x cadence {annual, quarterly, monthly} x counts {1,2,3,5,8,10,15,20,30,ALL,QUINTILE}); secondary signals annual cadence, both universes/rulebooks, all counts. 20-seed placebos per cell per road. Confirmation: cells beating same-window SPY on all 4 roads with >=15/20 placebos are re-run on FOLD 2016-2020 / FOLD 2021-2025; both folds must beat SPY for a VARIANT-CANDIDATE label.
- Crypto cross-run: NOT-APPLICABLE - accounting/fundamental cross-sectional signal from financial statements; no coin analogue exists mechanically (exception: firm-age, where the catalog map rules the cross-run applies; run separately there).
"""

def write_family(slug, spec, hunt, build):
    famdir = os.path.join(BASE, slug); os.makedirs(os.path.join(famdir,'grid'), exist_ok=True)
    os.makedirs(os.path.join(famdir,'data','frames'), exist_ok=True)
    os.makedirs(os.path.join(famdir,'scripts'), exist_ok=True)
    WK = os.path.join(os.path.expanduser('~'),'workspace/slice11-work')
    for src, dst in [(os.path.join(WK,'engine.py'),'engine.py'),(os.path.join(WK,'signals.py'),'signals.py'),(os.path.join(WK,'fetch.py'),'fetch.py'),(os.path.join(WK,'runner.py'),'runner.py')]:
        import shutil; shutil.copy(src, os.path.join(famdir,'scripts',dst))
    open(os.path.join(famdir,'SPEC-FROZEN.md'),'w').write(spec)
    open(os.path.join(famdir,'HUNT-LOG.md'),'w').write(hunt)
    print('=== ', slug, 'spec frozen; building signals', flush=True)
    signals, directions, primary, secondaries = build(famdir)
    fam = Family(signals, directions)
    pools = {f'{s}|{F}|{u}': len(fam.POOLS.get((s,F,u),{})) for s in signals for F in range(2016,2026) for u in ('broad','nonfin')}
    print('pools sample', list(pools.items())[:4], flush=True)
    grid, conf = run_grid(fam, primary, secondaries)
    stats = period_stats(fam, primary)
    res = {'family': slug, 'spec': 'SPEC-FROZEN.md', 'pool_sizes': pools, 'grid': grid, 'confirmation_folds': conf, 'period_stats_native_quintile': stats}
    json.dump(res, open(os.path.join(famdir,'results.json'),'w'), indent=1)
    # grid file
    lines = ['# FULL GRID — every cell printed (finals $, placebos beaten /20)', '',
             'Roads order: LONGEST / DECADE / CONT / VAL. SPY same-window: ' + ' / '.join(str(spy_final(ROADS[r])) for r in ROADS), '']
    for k in sorted(grid):
        c = grid[k]
        lines.append('| ' + k + ' | ' + ' | '.join(f"${c[r]['final']} ({c[r]['placebos_beaten']}/20)" for r in ROADS) + ' |')
    if conf:
        lines += ['', '## Confirmation folds (cells that beat SPY on all roads, pb>=15)', '']
        for k,c in conf.items():
            lines.append('| ' + k + ' | ' + ' | '.join(f"{r} ${c[r]['final']} (SPY ${c[r]['spy_same_window']}, {c[r]['placebos_beaten']}/20)" for r in c) + ' |')
    open(os.path.join(famdir,'grid','GRID.md'),'w').write('\n'.join(lines))
    return famdir, grid, conf, stats, primary

def verdict_and_results(slug, title, published_desc, practitioner_desc, famdir, grid, conf, stats, primary, extra=''):
    nat = grid[f'{primary}|broad|native|annual|QUINTILE']
    spy = {r: nat[r]['spy_same_window'] for r in ROADS}
    beats_spy_all = all(nat[r]['final'] > spy[r] for r in ROADS)
    pb_ok = nat['LONGEST_2016_2025']['placebos_beaten'] >= 15
    confirmed = []
    for k,c in conf.items():
        if all(c[r]['final'] > c[r]['spy_same_window'] for r in c): confirmed.append(k)
    champ_beat = [k for k,c in grid.items() if c['LONGEST_2016_2025']['final'] > 1415.62 and c['CONT_2019_2025']['final'] > 544.47]
    if beats_spy_all and pb_ok:
        verdict = 'REAL BUT SMALLER — ALIVE AS PUBLISHED (beats same-window SPY on every road and 20-seed placebos, but below the champion prints, which are on longer windows)'
        if champ_beat: verdict = 'ALIVE AS PUBLISHED — and at least one cell clears the champion reference prints (candidate-grade; windows differ, see fences)'
    elif confirmed:
        verdict = 'ALIVE ONLY AS VARIANT — winning cell(s) named below, candidate-grade (confirmation folds passed)'
    elif champ_beat or any(all(c[r]['final']>c[r]['spy_same_window'] for r in ROADS) for c in grid.values()):
        verdict = 'DEAD EVERYWHERE ON THE GRID — isolated cells beat SPY but fail placebos or the confirmation folds, so they print as LUCK, not life'
    else:
        verdict = 'DEAD EVERYWHERE ON THE GRID'
    best = max(grid.items(), key=lambda kv: kv[1]['LONGEST_2016_2025']['final'])
    s = stats
    md = f"""# {slug} — RESULTS (v12, Second-Chance Protocol)

Family: {title}
Spec frozen in `SPEC-FROZEN.md` before any run; hunt in `HUNT-LOG.md`; full grid in `grid/GRID.md`; machine record in `results.json`.
Crypto cross-run: **NOT-APPLICABLE** — accounting/fundamental cross-sectional signal; no coin analogue exists mechanically.

## Verdict: {verdict}

## Headline numbers ($100 start, gains reinvested, program costs)
Published form = {primary} | broad universe | native rules | annual | QUINTILE (long leg only):

| Road | Published form | Placebos beaten | SPY same window | Champion (own road, ref) |
|---|---|---|---|---|
| LONGEST 2016–2025 | **${nat['LONGEST_2016_2025']['final']}** | {nat['LONGEST_2016_2025']['placebos_beaten']}/20 | ${spy['LONGEST_2016_2025']} | V+M $1,415.62 |
| DECADE 2017–2025 | **${nat['DECADE_2017_2025']['final']}** | {nat['DECADE_2017_2025']['placebos_beaten']}/20 | ${spy['DECADE_2017_2025']} | V+M $667.35 |
| CONT 2019–2025 | **${nat['CONT_2019_2025']['final']}** | {nat['CONT_2019_2025']['placebos_beaten']}/20 | ${spy['CONT_2019_2025']} | V+M $544.47 |
| VAL 2023–2025 | **${nat['VAL_2023_2025']['final']}** | {nat['VAL_2023_2025']['placebos_beaten']}/20 | ${spy['VAL_2023_2025']} | V+M $288.05 |

Max drawdown (published form, LONGEST): {nat['LONGEST_2016_2025']['max_dd']*100:.1f}%. Total costs LONGEST: ${nat['LONGEST_2016_2025']['costs']}.
Best LONGEST cell on the whole grid: `{best[0]}` = ${best[1]['LONGEST_2016_2025']['final']} ({best[1]['LONGEST_2016_2025']['placebos_beaten']}/20 placebos) — printed as a grid cell, not a promotion; concentration cells (counts 1–3) carry single-name lottery risk and drawdowns far beyond Terry's −15% floor.
Confirmed variant cells (beat SPY on all roads, placebos ≥15/20, both confirmation folds beat SPY): {confirmed if confirmed else 'none'}.
{extra}
## Per-period distribution — native tempo: ANNUAL (median is the headline)
Published form, LONGEST ({s['periods']} annual periods): made money in {s['positive']} of {s['periods']} · **median period {s['median_pct']:+.1f}%** · best {s['best_pct']:+.1f}% · worst {s['worst_pct']:+.1f}% · longest losing run {s['longest_losing_streak']} · longest stretch between new highs {s['longest_months_between_highs']} months. Year by year (%): {', '.join(f'{r:+.1f}' for r in s['year_by_year_pct'])}. (Secondary, average only: {s['avg_pct_secondary']:+.1f}%.)

## Practitioners vs imposed
{published_desc}
{practitioner_desc}

## Fences
- Long-only adaptation of a long-short published sort; the short leg is not built (removes half the published spread).
- W04 stack survivorship at the entry gate flatters; vanished→ZERO armed mid-hold. EDGAR frames are calendarized/restated (≥6-month PIT lag) — flatters slightly.
- The champions' prints are on 2010-start program roads; every road here starts 2016. Same-window SPY is the honest comparator.
"""
    open(os.path.join(famdir,'RESULTS.md'),'w').write(md)
    print(slug, 'VERDICT:', verdict, '| native LONGEST $', nat['LONGEST_2016_2025']['final'], flush=True)
    return verdict, nat['LONGEST_2016_2025']['final']
