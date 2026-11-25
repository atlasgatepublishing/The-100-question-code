"""Monthly basket chassis on the w04 broad stack (monthly Yahoo
adjclose, read-only). A basket month: equal-weight names, gross return
from monthly closes; costs charged on turnover — native tiered habitat
rates (entry+exit each rebalance, i.e. full monthly turnover charged
both sides at each name's tiered rate, averaged); house = program
0.10%/side both sides + v9 floor on monthly closes vs episode anchor
(halt -> 3 months cash, one restart, second halt ends). Vanished
prices: w04 Data.price() carries last price (the stack's convention);
the delisting fence is printed in RESULTS — free tapes lose delisted
names, bias FLATTERS."""
import json, os, random, statistics, importlib.util

ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
E.D = E.Data(); D = E.D
ym = E.ym

MONTHS = []
_y, _m = 2016, 1
while (_y, _m) <= (2026, 11):
    MONTHS.append(ym(_y, _m))
    _m += 1
    if _m > 12: _y += 1; _m = 1

def mret(cik, m):
    i = MONTHS.index(m)
    if i == 0: return None
    p0 = D.price(cik, MONTHS[i - 1]); p1 = D.price(cik, m)
    if not p0 or not p1: return None
    return p1 / p0 - 1

def run_monthly(picks_by_M, months, form, pool_by_M=None, placebo_seed=None):
    """picks_by_M: {month: [cik]} held DURING that month (formed at prior
    month-end). Returns result dict with monthly curve."""
    cash = 100.0; curve = []; total_costs = 0.0
    anchor = 100.0; halts = 0; ended = False; cash_months = 0
    snaps = {}
    def cap_of(c, m):
        F = int(m[:4])
        if F not in snaps: snaps[F] = E.snapshot(F)
        v = snaps[F].get(c)
        return v["cap"] if v else None
    for m in months:
        picks = list(picks_by_M.get(m, []))
        if placebo_seed is not None:
            pool = list(pool_by_M.get(m, []))
            rng = random.Random(placebo_seed * 104729 + int(m[:4]) * 100 + int(m[5:7])); rng.shuffle(pool)
            picks = pool[:len(picks)]
        if ended or cash_months > 0 or not picks:
            if cash_months > 0: cash_months -= 1
            curve.append([m, round(cash, 2)]); continue
        rets = []
        for c in picks:
            r = mret(c, m)
            if r is not None: rets.append(r)
        if not rets:
            curve.append([m, round(cash, 2)]); continue
        gross = sum(rets) / len(rets)
        if form == "native":
            rates = [E.cost_rate(cap_of(c, m)) for c in picks]
            crate = sum(rates) / len(rates)
        else:
            crate = 0.001
        cst = cash * 2 * crate; total_costs += cst
        cash = cash * (1 + gross) - cst
        curve.append([m, round(cash, 2)])
        if form == "house" and cash <= 0.85 * anchor:
            halts += 1
            if halts >= 2: ended = True
            else: cash_months = 3; anchor = cash
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(cash, 2), "max_dd": round(maxdd, 4), "costs": round(total_costs, 2),
            "halts": halts, "curve": curve}

def period_stats_monthly(curve):
    if len(curve) < 2: return None
    rets = [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = 100.0; since = 0; longest = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 4)}

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
