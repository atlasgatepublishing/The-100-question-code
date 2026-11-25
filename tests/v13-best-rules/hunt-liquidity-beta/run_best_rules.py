#!/usr/bin/env python3
"""hunt-liquidity-beta — V13 BEST RULES run. Spec: BEST-RULES-SPEC.md
(frozen before this run). Pastor-Stambaugh liquidity beta, 60-month
rolling OLS on Pastor's published innovation series (author file,
through Dec 2024 — hard boundary), >=48 valid months, universe
price > $5. MY RULES vs published: top QUINTILE equal-weight (not
decile VW), QUARTERLY formation / 3-month hold (not monthly), NO
floor, native tiered costs charged on ACTUAL basket turnover at
quarterly rebalances only. Long-only — labeled adaptation of the
published long/short form. Roads collapse honestly: LONG/DECADE/CONT
= FULL holds Feb 2021..Jan 2025 (60m burn-in + series end); VAL =
standalone pot holds Jan 2023..Jan 2025. 20-seed placebos."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monthly_lib as M

HERE = os.path.dirname(os.path.abspath(__file__))
D, E, MONTHS = M.D, M.E, M.MONTHS
mret = M.mret

PS_INNOV = {
"2015-01": 0.02183311, "2015-02": 0.00119415, "2015-03": -0.02108124, "2015-04": 0.00619738,
"2015-05": 0.00422828, "2015-06": 0.00995177, "2015-07": 0.03323182, "2015-08": 0.07145377,
"2015-09": -0.07751100, "2015-10": 0.10663556, "2015-11": -0.03431734, "2015-12": -0.01288214,
"2016-01": -0.04542063, "2016-02": 0.02972618, "2016-03": 0.00364552, "2016-04": 0.09165088,
"2016-05": -0.05494044, "2016-06": -0.02670500, "2016-07": 0.01055463, "2016-08": -0.00382177,
"2016-09": -0.03142384, "2016-10": 0.08996467, "2016-11": -0.00358364, "2016-12": 0.04941367,
"2017-01": 0.06720165, "2017-02": -0.05258013, "2017-03": -0.06446981, "2017-04": 0.01001715,
"2017-05": 0.08911600, "2017-06": 0.02426171, "2017-07": 0.01387179, "2017-08": 0.06429244,
"2017-09": 0.05560052, "2017-10": 0.03140344, "2017-11": 0.01935147, "2017-12": 0.04636424,
"2018-01": -0.00970587, "2018-02": 0.02959768, "2018-03": 0.08568453, "2018-04": -0.01196645,
"2018-05": 0.08527741, "2018-06": 0.12575545, "2018-07": -0.02265213, "2018-08": 0.04554729,
"2018-09": 0.05793964, "2018-10": -0.03131035, "2018-11": 0.04117140, "2018-12": -0.03937019,
"2019-01": -0.02978301, "2019-02": 0.15376443, "2019-03": -0.00490047, "2019-04": 0.05791674,
"2019-05": -0.02062196, "2019-06": -0.06410421, "2019-07": 0.07291149, "2019-08": 0.02215737,
"2019-09": -0.02237908, "2019-10": 0.00200058, "2019-11": 0.03869783, "2019-12": 0.02122218,
"2020-01": -0.01470322, "2020-02": 0.02405276, "2020-03": -0.16401914, "2020-04": -0.02408057,
"2020-05": -0.06989159, "2020-06": 0.01935011, "2020-07": 0.07282782, "2020-08": -0.01228093,
"2020-09": -0.12009975, "2020-10": 0.03214371, "2020-11": 0.06539280, "2020-12": 0.01275480,
"2021-01": 0.06211251, "2021-02": -0.04761208, "2021-03": -0.00933628, "2021-04": -0.02828946,
"2021-05": -0.01047231, "2021-06": 0.00354027, "2021-07": 0.03830307, "2021-08": 0.03166787,
"2021-09": -0.00183064, "2021-10": -0.00837262, "2021-11": 0.02907322, "2021-12": 0.07439954,
"2022-01": -0.04622693, "2022-02": -0.07207870, "2022-03": -0.02466016, "2022-04": -0.13460513,
"2022-05": 0.02700270, "2022-06": 0.07943401, "2022-07": 0.07561750, "2022-08": 0.02243347,
"2022-09": -0.01592645, "2022-10": 0.00094557, "2022-11": 0.00802682, "2022-12": 0.03832234,
"2023-01": 0.04938161, "2023-02": 0.04054655, "2023-03": 0.00445632, "2023-04": -0.13255066,
"2023-05": -0.00106691, "2023-06": 0.01985003, "2023-07": 0.05309215, "2023-08": -0.01383397,
"2023-09": -0.03251257, "2023-10": 0.17552559, "2023-11": -0.10659695, "2023-12": -0.12649621,
"2024-01": 0.02461798, "2024-02": 0.01820823, "2024-03": -0.00255847, "2024-04": -0.10275165,
"2024-05": 0.00067461, "2024-06": -0.01665431, "2024-07": -0.01036066, "2024-08": 0.02292551,
"2024-09": -0.00892977, "2024-10": 0.17347056, "2024-11": -0.04141490, "2024-12": -0.02242166}

EXCLUDE = {1748790}  # corrupted tape record — see spec ADDENDUM (negative adj prices, fake +1,040,809% month)
RET = {}
def ret(c, m):
    if (c, m) not in RET: RET[(c, m)] = mret(c, m)
    return RET[(c, m)]

def betas(fm):
    i = MONTHS.index(fm)
    win = MONTHS[i - 59:i + 1]
    innov = [PS_INNOV.get(m) for m in win]
    if any(v is None for v in innov): return [], []
    mi = statistics.mean(innov); var = sum((v - mi) ** 2 for v in innov)
    out = {}; elig = []
    for c in D.cand:
        if c in EXCLUDE: continue
        praw = D.price(c, fm, adj=False)
        if not praw or praw <= 5: continue
        elig.append(c)
        pairs = []
        for m in win:
            r = ret(c, m)
            if r is not None: pairs.append((r, PS_INNOV[m]))
        if len(pairs) < 48: continue
        mr = statistics.mean([p[0] for p in pairs])
        cov = sum((r - mr) * (v - mi) for r, v in pairs)
        out[c] = cov / var
    ranked = sorted(out, key=lambda c: -out[c])
    return ranked, elig

_snaps = {}
def cap_of(c, m):
    F = int(m[:4])
    if F not in _snaps: _snaps[F] = E.snapshot(F)
    v = _snaps[F].get(c)
    return v["cap"] if v else None

def rate(c, m):
    return E.cost_rate(cap_of(c, m))

def run_quarterly(schedule, placebo_seed=None, pools=None):
    """schedule: [(basket_list, [hold months]), ...] in time order.
    Costs: at each rebalance, sold fraction of old basket at old names'
    avg tiered rate + bought fraction of new basket at new names' avg
    rate; first basket charged full entry. Monthly curve appended."""
    cash = 100.0; curve = []; total_costs = 0.0; prev = []
    for qi, (basket, holds) in enumerate(schedule):
        basket = list(basket)
        if placebo_seed is not None:
            pool = list(pools[qi]); n = len(basket)
            rng = random.Random(placebo_seed * 104729 + qi * 131)
            rng.shuffle(pool); basket = pool[:n]
        if not basket or not holds:
            for m in holds: curve.append([m, round(cash, 2)])
            continue
        m0 = holds[0]
        if prev:
            sold = [c for c in prev if c not in basket]
            bought = [c for c in basket if c not in prev]
            cst = 0.0
            if sold: cst += cash * (len(sold) / len(prev)) * (sum(rate(c, m0) for c in sold) / len(sold))
            if bought: cst += cash * (len(bought) / len(basket)) * (sum(rate(c, m0) for c in bought) / len(bought))
        else:
            cst = cash * (sum(rate(c, m0) for c in basket) / len(basket))
        total_costs += cst; cash -= cst
        for m in holds:
            rets = [r for r in (ret(c, m) for c in basket) if r is not None]
            if rets: cash = cash * (1 + sum(rets) / len(rets))
            curve.append([m, round(cash, 2)])
        prev = basket
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(cash, 2), "max_dd": round(maxdd, 4),
            "costs": round(total_costs, 2), "curve": curve}

def holds_after(fm, cap_last):
    i = MONTHS.index(fm)
    out = []
    for m in MONTHS[i + 1:i + 4]:
        if m <= cap_last: out.append(m)
    return out

def build_schedule(form_months, cap_last):
    sched = []; pools = []; sizes = []
    for fm in form_months:
        ranked, elig = betas(fm)
        n = max(1, len(ranked) // 5)
        sched.append((ranked[:n], holds_after(fm, cap_last)))
        pools.append(elig); sizes.append(n)
        print("form", fm, "ranked", len(ranked), "quintile", n, flush=True)
    return sched, pools, sizes

def spy_final(first_hold_prev_month, last_hold):
    a = D.spy.get(first_hold_prev_month); b = D.spy.get(last_hold)
    return round(100 * b / a, 2) if a and b else None

def main():
    res = {"family": "hunt-liquidity-beta", "program": "v13-best-rules",
           "form": "long-only top-quintile EW, quarterly, no floor, native tiered costs on actual turnover",
           "roads": {}}
    full_forms = ["2021-01", "2021-04", "2021-07", "2021-10",
                  "2022-01", "2022-04", "2022-07", "2022-10",
                  "2023-01", "2023-04", "2023-07", "2023-10",
                  "2024-01", "2024-04", "2024-07", "2024-10"]
    val_forms = ["2022-12", "2023-03", "2023-06", "2023-09", "2023-12",
                 "2024-03", "2024-06", "2024-09", "2024-12"]
    fs, fpools, fsizes = build_schedule(full_forms, "2025-01")
    vs, vpools, vsizes = build_schedule(val_forms, "2025-01")
    fr = run_quarterly(fs)
    vr = run_quarterly(vs)
    res["roads"]["FULL (LONG=DECADE=CONT honest span, holds 2021-02..2025-01)"] = {
        "run": fr, "period_stats_monthly": M.period_stats_monthly(fr["curve"]),
        "spy_same_window": spy_final("2021-01", "2025-01"), "basket_sizes": fsizes}
    res["roads"]["VAL (holds 2023-01..2025-01)"] = {
        "run": vr, "period_stats_monthly": M.period_stats_monthly(vr["curve"]),
        "spy_same_window": spy_final("2022-12", "2025-01"), "basket_sizes": vsizes}
    print("FULL", fr["final"], "dd", fr["max_dd"], "VAL", vr["final"], "dd", vr["max_dd"], flush=True)
    twins = []
    for sd in range(1, 21):
        t = run_quarterly(fs, placebo_seed=sd, pools=fpools)["final"]
        twins.append(t); print("placebo", sd, t, flush=True)
    res["placebo_FULL"] = {"finals": twins,
        "beaten_of_20": sum(1 for t in twins if fr["final"] > t),
        "twin_median": round(statistics.median(twins), 2)}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
