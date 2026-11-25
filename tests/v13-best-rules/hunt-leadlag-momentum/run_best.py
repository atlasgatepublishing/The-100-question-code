#!/usr/bin/env python3
"""V13 BEST RULES — hunt-leadlag-momentum. Implements BEST-RULES-SPEC.md
(frozen before this code ran):
ONE leader definition: the industry itself. Signal = EW past-6-month
return of each SIC-2 industry (w04 stack, current-SIC label as in v12).
Universe: raw price > $5 at formation, cap >= $1B (annual snapshot,
stack convention), industries with >= 5 eligible firms. Selection:
top-quintile industries, whole basket, equal weight. Monthly read with
buffered exit: a held industry is kept while in the top 40%, sold only
below that; new buys only from the top quintile. Costs: tiered habitat
rates on ACTUAL traded value only (share-based simulation; continuing
positions are never charged a fictional exit/re-entry). NO floor.
Roads (stack's honest reach): LONG holds 2016-08->2026-11, DECADE
2016-12->2026-11, CONT 2019-01->, VAL 2023-01->. 20-seed placebos on
LONG (same basket size, same universe, same cost accounting).
Confirmation folds/half-windows computed unconditionally, used only
if a champion bar is beaten."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_lib import D, E, MONTHS

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = D.cand
SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = E.snapshot(F)
    return SNAPS[F]

def sic2(c):
    try: return int(CAND[c].get("sic")) // 100
    except Exception: return 0

def cap_of(c, form_m):
    v = snap(int(form_m[:4])).get(c)
    return v["cap"] if v else None

def eligible(form_m):
    out = []
    for c in CAND:
        praw = D.price(c, form_m, adj=False)
        if not praw or praw <= 5: continue
        if D.price(c, form_m) is None: continue
        cap = cap_of(c, form_m)
        if not cap or cap < 1e9: continue
        out.append(c)
    return out

def past_ret(c, m, k=6):
    i = MONTHS.index(m)
    if i - k < 0: return None
    p0 = D.price(c, MONTHS[i - k]); p1 = D.price(c, m)
    if not p0 or not p1: return None
    return p1 / p0 - 1

def industry_scores(form_m):
    inds = {}
    for c in eligible(form_m):
        r = past_ret(c, form_m)
        if r is not None: inds.setdefault(sic2(c), []).append((c, r))
    inds = {k: v for k, v in inds.items() if len(v) >= 5}
    scores = {k: sum(r for _, r in v) / len(v) for k, v in inds.items()}
    members = {k: sorted(c for c, _ in v) for k, v in inds.items()}
    pool = sorted(c for v in inds.values() for c, _ in v)
    return scores, members, pool

def gen_picks(hold_months):
    """Stateful buffered picks {hold_month: [cik]} plus eligible pools."""
    picks = {}; pools = {}; held = set(); basket_sizes = {}
    for hm in hold_months:
        i = MONTHS.index(hm); form_m = MONTHS[i - 1]
        scores, members, pool = industry_scores(form_m)
        pools[hm] = pool
        if len(scores) < 5:
            picks[hm] = []; basket_sizes[hm] = 0; continue
        ranked = sorted(scores, key=lambda k: -scores[k])
        nq = max(1, len(ranked) // 5)
        n40 = max(nq, int(0.4 * len(ranked)))
        held = (held & set(ranked[:n40])) | set(ranked[:nq])
        basket = []
        for k in sorted(held, key=lambda k: -scores[k]):
            basket.extend(members[k])
        picks[hm] = basket; basket_sizes[hm] = len(basket)
    return picks, pools, basket_sizes

def run_shares(picks_by_M, months, pool_by_M=None, placebo_seed=None):
    """Share-based EW simulation. At each hold month's start (formation
    month-end prices): rebalance to equal weight over the basket,
    charging each name's tiered rate on its |trade|; costs come out of
    the pot (targets scaled by (val-costs)/val). Mark at month-end."""
    cash = 100.0; pos = {}
    curve = []; total_costs = 0.0; total_traded = 0.0
    for hm in months:
        i = MONTHS.index(hm); form_m = MONTHS[i - 1]
        picks = list(picks_by_M.get(hm, []))
        if placebo_seed is not None:
            pool = list(pool_by_M.get(hm, []))
            rng = random.Random(placebo_seed * 104729 + int(hm[:4]) * 100 + int(hm[5:7]))
            rng.shuffle(pool)
            picks = pool[:len(picks)]
        val = cash + sum(sh * (D.price(c, form_m) or 0) for c, sh in pos.items())
        tgt = {}
        if picks:
            w = val / len(picks)
            for c in picks: tgt[c] = w
        # trades vs pre-cost targets; untradeable names (no form price) frozen
        trades = {}; cst_total = 0.0
        for c in set(list(pos) + list(tgt)):
            p = D.price(c, form_m)
            if not p: continue
            cur = pos.get(c, 0.0) * p
            t = tgt.get(c, 0.0)
            if c not in tgt and c not in pos: continue
            d = t - cur
            if abs(d) > 1e-9:
                cst = abs(d) * E.cost_rate(cap_of(c, form_m))
                trades[c] = d; cst_total += cst; total_traded += abs(d)
        total_costs += cst_total
        scale = (val - cst_total) / val if val > 0 else 0.0
        newpos = {}
        for c in set(list(pos) + list(tgt)):
            p = D.price(c, form_m)
            if not p:
                if c in pos: newpos[c] = pos[c]
                continue
            t = tgt.get(c, 0.0) * scale
            if t > 0: newpos[c] = t / p
        invested = sum(sh * (D.price(c, form_m) or 0) for c, sh in newpos.items())
        cash = val - cst_total - invested
        pos = newpos
        v = cash + sum(sh * (D.price(c, hm) or D.price(c, form_m) or 0) for c, sh in pos.items())
        curve.append([hm, round(v, 2)])
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": curve[-1][1] if curve else 100.0, "max_dd": round(maxdd, 4),
            "costs": round(total_costs, 2), "traded": round(total_traded, 2), "curve": curve}

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    if not rets: return None
    pos_n = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = 100.0; since = 0; longest = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos_n / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 4)}

def spy_final(first_hold, last_hold):
    i = MONTHS.index(first_hold); start_m = MONTHS[i - 1]
    a = D.spy.get(start_m); b = D.spy.get(last_hold)
    return round(100 * b / a, 2) if a and b else None

HOLD_ALL = [m for m in MONTHS if m >= "2016-08"]
ROADS = {"LONG": HOLD_ALL,
         "DECADE": [m for m in HOLD_ALL if m >= "2016-12"],
         "CONT": [m for m in HOLD_ALL if m >= "2019-01"],
         "VAL": [m for m in HOLD_ALL if m >= "2023-01"]}

def main():
    res = {"family": "hunt-leadlag-momentum", "form": "v13-best-rules",
           "roads": {}, "note_roads": "LONG/DECADE truncated to the w04 stack's honest reach (prices from 2016-01; first 6m formation hold 2016-08)."}
    # one stateful pick generation from the earliest start; later roads
    # re-generate fresh from their own start (fresh pot, empty buffer).
    cache = {}
    def picks_for(months):
        key = months[0]
        if key not in cache: cache[key] = gen_picks(months)
        return cache[key]
    for road, months in ROADS.items():
        picks, pools, sizes = picks_for(months)
        r = run_shares(picks, months)
        res["roads"][road] = {"result": r, "period_stats_monthly": period_stats(r["curve"]),
                              "spy_same_window": spy_final(months[0], months[-1]),
                              "avg_basket": round(statistics.mean(sizes[m] for m in months), 1)}
        print(road, r["final"], "dd", r["max_dd"], "costs", r["costs"], "spy", res["roads"][road]["spy_same_window"], flush=True)
    picks, pools, _ = picks_for(ROADS["LONG"])
    twins = []
    for sd in range(1, 21):
        t = run_shares(picks, ROADS["LONG"], pool_by_M=pools, placebo_seed=sd)
        twins.append(t["final"]); print("twin", sd, t["final"], flush=True)
    res["placebo_LONG"] = {"finals": twins,
                           "beaten_of_20": sum(1 for t in twins if res["roads"]["LONG"]["result"]["final"] > t),
                           "twin_median": round(statistics.median(twins), 2)}
    # confirmation blocks (used only if a champion bar falls)
    folds = {}
    for Y in range(2017, 2026):
        months = [m for m in HOLD_ALL if m[:4] == str(Y)]
        pk, _, _ = gen_picks(months)
        folds[str(Y)] = {"final": run_shares(pk, months)["final"], "spy": spy_final(months[0], months[-1])}
    res["confirmation_folds"] = folds
    halves = {}
    for name, months in [("H1_2017-2021H1", [m for m in HOLD_ALL if "2017-01" <= m <= "2021-06"]),
                         ("H2_2021H2-2026", [m for m in HOLD_ALL if m >= "2021-07"])]:
        pk, _, _ = gen_picks(months)
        halves[name] = {"final": run_shares(pk, months)["final"], "spy": spy_final(months[0], months[-1])}
    res["confirmation_halves"] = halves
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
