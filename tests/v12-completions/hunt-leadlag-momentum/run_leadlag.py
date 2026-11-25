#!/usr/bin/env python3
"""Lead-Lag / Cross-Firm Momentum (hunt-leadlag-momentum, v12) —
SPEC-FROZEN legs that free data can build:
LEG 1 Industry momentum (Moskowitz-Grinblatt): rank 2-digit SIC
industries by past-6-month equal-weight return; long-only basket of
stocks in the top-quintile industries, monthly formation, 1-month
hold. (Program adaptation: EW industry returns and EW basket; the
papers are VW long-short — the long-short spread is not holdable in
the $100 long-only pot; adaptation labeled.)
LEG 4 Big-firm lead-lag (Hou 2007): within each SIC-2 industry, the
largest-30% firms by market cap are 'big'; signal = big firms'
past-month EW return; long the OTHER firms in the top-quintile of
industries by that signal, monthly.
LEG 2 (customer momentum, the frozen HEADLINE leg) — STILL
UNBUILDABLE: Compustat principal-customer segment file is paywalled;
EDGAR 10-K major-customer disclosures are unstructured text, not a
point-in-time link database; a survivors-only customer file is
forbidden by the spec. See HUNT-LOG.md.
LEG 3 (IO supplier/customer momentum) — NOT RUN, named gap: BEA tables
are free but no frozen mapping from BEA IO codes to this stack's SIC-2
universe was built; listed as GRID GAP rather than improvised.
LEG 5 (conglomerate segment momentum) — STILL UNBUILDABLE, same
segment-file hole as leg 2. LEG 6 (geographic) — not built; EDGAR
header HQ series not constructed; named GRID GAP.
Universe: w04 candidates with price > $5 (raw) at formation and a
monthly price series. SIC is the candidates file's current SIC
(label: current-SIC backfill flatters industry stability). Roads:
FULL 2016-07->2026-11 (first 6m formation the stack supports),
CONT 2019-01->, VAL 2023-01->. 20-seed placebos; holdings grid for
leg 1 (rank within top industries by own 6m momentum)."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_lib import *

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = D.cand
SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = E.snapshot(F)
    return SNAPS[F]

def sic2(c):
    s = CAND[c].get("sic")
    try: return int(s) // 100
    except Exception: return 0

def eligible(m):
    """Names with raw price > $5 at prior month-end and returns available."""
    i = MONTHS.index(m)
    prev = MONTHS[i - 1]
    out = []
    for c in CAND:
        praw = D.price(c, prev, adj=False)
        if praw and praw > 5 and D.price(c, prev) is not None:
            out.append(c)
    return out

def past_ret(c, m, k):
    """Compounded return over the k months ending at month m (inclusive
    of m's return? No: months m-k+1..m returns use prices m-k..m)."""
    i = MONTHS.index(m)
    if i - k < 0: return None
    p0 = D.price(c, MONTHS[i - k]); p1 = D.price(c, m)
    if not p0 or not p1: return None
    return p1 / p0 - 1

def leg1_ranked(form_m):
    """form_m = last month of formation window; basket held next month.
    Returns (ranked names in top-quintile industries, pool)."""
    elig = eligible(form_m)
    inds = {}
    for c in elig:
        r = past_ret(c, form_m, 6)
        if r is not None: inds.setdefault(sic2(c), []).append((c, r))
    inds = {k: v for k, v in inds.items() if len(v) >= 3}
    if len(inds) < 5: return [], []
    iret = {k: sum(x[1] for x in v) / len(v) for k, v in inds.items()}
    nq = max(1, len(iret) // 5)
    top = sorted(iret, key=lambda k: -iret[k])[:nq]
    ranked = []
    for k in sorted(top, key=lambda k: -iret[k]):
        for c, r in sorted(inds[k], key=lambda x: -x[1]): ranked.append(c)
    return ranked, elig

def leg4_ranked(form_m):
    i = MONTHS.index(form_m)
    prev = MONTHS[i - 1]
    elig = eligible(form_m)
    F = int(form_m[:4]); s = snap(F)
    inds = {}
    for c in elig: inds.setdefault(sic2(c), []).append(c)
    sig = {}
    for k, members in inds.items():
        withcap = [(s[c]["cap"], c) for c in members if s.get(c, {}).get("cap")]
        if len(withcap) < 4: continue
        withcap.sort(reverse=True)
        nbig = max(1, int(0.3 * len(withcap)))
        big = [c for _, c in withcap[:nbig]]
        rets = [mret(c, form_m) for c in big]
        rets = [r for r in rets if r is not None]
        if rets: sig[k] = (sum(rets) / len(rets), [c for c in members if c not in big])
    if len(sig) < 5: return [], []
    nq = max(1, len(sig) // 5)
    top = sorted(sig, key=lambda k: -sig[k][0])[:nq]
    ranked = []
    for k in sorted(top, key=lambda k: -sig[k][0]): ranked.extend(sig[k][1])
    return ranked, elig

HOLD_MONTHS = MONTHS[6:]  # first hold month 2016-07 (formation Jun 2016 needs 6m back to Dec 2015? prices start 2016-01 -> first honest formation is Jun 2016 using Jan-Jun? past_ret k=6 at form_m=2016-06 needs price at 2015-12 -> unavailable; so formation starts 2016-07, hold 2016-08)
HOLD_MONTHS = [m for m in MONTHS if m >= "2016-08"]
ROADS_M = {"FULL": [m for m in HOLD_MONTHS if m <= "2026-11"],
           "CONT": [m for m in HOLD_MONTHS if m >= "2019-01"],
           "VAL": [m for m in HOLD_MONTHS if m >= "2023-01"]}

def build_picks(rankfn):
    picks = {}; pools = {}; ranked_by_M = {}
    for hm in HOLD_MONTHS:
        i = MONTHS.index(hm); form_m = MONTHS[i - 1]
        ranked, pool = rankfn(form_m)
        ranked_by_M[hm] = ranked; pools[hm] = pool
        picks[hm] = ranked  # native = ALL names in top industries (leg1) / all non-big (leg4)
    return picks, pools, ranked_by_M

def run_leg(rankfn, do_grid=False):
    picks, pools, ranked_by_M = build_picks(rankfn)
    out = {"roads": {}}
    for road, months in ROADS_M.items():
        rn = run_monthly(picks, months, "native"); rh = run_monthly(picks, months, "house")
        out["roads"][road] = {"native": rn, "house": rh, "period_stats_monthly": period_stats_monthly(rn["curve"])}
    twins = [run_monthly(picks, ROADS_M["FULL"], "native", pool_by_M=pools, placebo_seed=sd)["final"] for sd in range(1, 21)]
    out["placebo_FULL_native"] = {"finals": twins, "beaten_of_20": sum(1 for t in twins if out["roads"]["FULL"]["native"]["final"] > t)}
    if do_grid:
        grid = {}
        for cnt in COUNTS:
            cell = {}
            for road, months in ROADS_M.items():
                pk = {hm: (ranked_by_M[hm] if cnt == "ALL" else ranked_by_M[hm][:cnt]) for hm in months}
                cell[road] = {"native": run_monthly(pk, months, "native")["final"],
                              "house": run_monthly(pk, months, "house")["final"]}
            grid[str(cnt)] = cell; print("grid", cnt, cell["FULL"], flush=True)
        out["grid"] = grid
    return out

def main():
    res = {"family": "hunt-leadlag-momentum"}
    print("leg1...", flush=True)
    res["leg1_industry_momentum"] = run_leg(leg1_ranked, do_grid=True)
    print("leg1 FULL native", res["leg1_industry_momentum"]["roads"]["FULL"]["native"]["final"], flush=True)
    print("leg4...", flush=True)
    res["leg4_bigfirm_leadlag"] = run_leg(leg4_ranked)
    print("leg4 FULL native", res["leg4_bigfirm_leadlag"]["roads"]["FULL"]["native"]["final"], flush=True)
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump({"leg1_grid": res["leg1_industry_momentum"].pop("grid")}, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
