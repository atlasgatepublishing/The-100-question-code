#!/usr/bin/env python3
"""
Sin stocks (Hong-Kacperczyk) - v13 BEST RULES run. Spec: BEST-RULES-SPEC.md (frozen first).
Best-rules form: published sin basket (15 names, primary-SIC approx), PIT entry by
first traded bar, equal weight, QUARTERLY rebalance, NO floor.
Controls: comparable basket on identical machinery; 20-seed placebos = random
equal-size baskets from comparable industries. Integrity gate: monthly cadence
replica of the v12 native form.
Prices: Yahoo chart JSON (adjclose total-return series), program pxfull caches
read-only where present, fresh pulls cached into ./data otherwise.
Costs: 0.10%/side + $0.01 per sell order. $100 pots.
"""
import bisect, json, os, random, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
CACHE_DIRS = [
    os.path.join(BT, "v7", "long-hold", "data"),
    os.path.join(BT, "v11-native-rules", "_w04_broad_data"),
]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

SIN = ["MO", "PM", "BTI", "STZ", "TAP", "SAM", "DEO", "BUD",
       "LVS", "WYNN", "MGM", "CZR", "PENN", "BYD", "DKNG"]
COMP = ["KO", "PEP", "GIS", "MCD", "SBUX", "DIS", "CMCSA", "VZ", "T"]  # 9 names: matches v12 results.json actual basket (K tape unrecoverable - Kellanova delisted Aug 2025, Yahoo history purged)

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12_NATIVE = {"LONG": 859.49, "DECADE": 194.82, "CONT": 151.16, "VAL": 106.42}
V12_COMP = {"LONG": 545.08, "DECADE": 183.60, "CONT": 153.81, "VAL": 111.80}


def fetch(t):
    p1, p2 = 1230768000, 1795305600  # 2009-01-01 .. 2026-11-21
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load(t):
    for d in CACHE_DIRS:
        p = os.path.join(d, f"pxfull_{t}.json")
        if os.path.exists(p):
            return parse(json.load(open(p)), t)
    p = os.path.join(DATA, f"yh_{t}.json")
    if not os.path.exists(p):
        j = fetch(t)
        json.dump(j, open(p, "w"))
        time.sleep(0.3)
    else:
        j = json.load(open(p))
    return parse(j, t)


def parse(j, t):
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    bars = {}
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        c = q["close"][i]
        if c is None:
            continue
        bars[d] = adj[i] if adj and adj[i] else c
    return bars


PRICES = {}
for t in SIN + COMP + ["SPY"]:
    PRICES[t] = load(t)
DAYS = {t: sorted(PRICES[t]) for t in PRICES}
ALL_DAYS = sorted(PRICES["SPY"])
DAY_IDX = {d: i for i, d in enumerate(ALL_DAYS)}


def px_on(t, d):
    ds = DAYS[t]
    i = bisect.bisect_right(ds, d) - 1
    return PRICES[t][ds[i]] if i >= 0 else None


def formations(start, end, cadence):
    days = [d for d in ALL_DAYS if start <= d <= end]
    out = []
    seen = set()
    for d in days:
        key = d[:7] if cadence == "monthly" else d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return days, out


def simulate(pool, start, end, cadence="quarterly", seed=None):
    """Equal-weight basket of `pool` names trading at each formation.
    If seed is not None, at each formation pick a random subset of `pool`
    of size = number of SIN names trading then (placebo mode)."""
    days, forms = formations(start, end, cadence)
    form_set = set(forms)
    cash = START_CASH
    shares = {}
    curve = []
    n_trades = 0

    def eligible(d, from_pool):
        return [t for t in from_pool if DAYS[t] and DAYS[t][0] <= d and px_on(t, d)]

    for d in days:
        if d in form_set:
            if seed is not None:
                rng = random.Random(seed * 100000 + DAY_IDX[d])
                k = len(eligible(d, SIN))
                elig_c = eligible(d, pool)
                chosen = rng.sample(elig_c, min(k, len(elig_c))) if elig_c else []
            else:
                chosen = eligible(d, pool)
            value = cash + sum(shares.get(t, 0.0) * px_on(t, d) for t in shares)
            if chosen and value > 0:
                target = value / len(chosen)
                # sells first
                for t in list(shares):
                    cur = shares[t] * px_on(t, d)
                    want = target if t in chosen else 0.0
                    if cur > want + 1e-9:
                        proceeds = (cur - want) * (1 - COST_RATE) - SELL_FEE
                        cash += proceeds
                        shares[t] = want / px_on(t, d)
                        n_trades += 1
                        if shares[t] <= 1e-12:
                            del shares[t]
                # buys
                for t in chosen:
                    cur = shares.get(t, 0.0) * px_on(t, d)
                    if target > cur + 1e-9:
                        need = (target - cur) * (1 + COST_RATE)
                        spend = min(need, cash)
                        if spend > 0:
                            shares[t] = shares.get(t, 0.0) + (spend / (1 + COST_RATE)) / px_on(t, d)
                            cash -= spend
                            n_trades += 1
        value = cash + sum(shares.get(t, 0.0) * px_on(t, d) for t in shares)
        curve.append([d, round(value, 4)])
    return curve, n_trades


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)


def period_stats(curve):
    """Monthly distribution from daily curve."""
    months = {}
    for d, v in curve:
        months[d[:7]] = v
    keys = sorted(months)
    rets = []
    for i in range(1, len(keys)):
        prev, cur = months[keys[i - 1]], months[keys[i]]
        if prev > 0:
            rets.append(cur / prev - 1.0)
    if not rets:
        return {}
    srt = sorted(rets)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    pos = sum(1 for r in rets if r > 0)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (months, on monthly closes)
    peak, since, worst_gap = -1.0, 0, 0
    for k in keys:
        if months[k] >= peak:
            peak, worst_gap, since = months[k], max(worst_gap, since), 0
        else:
            since += 1
    worst_gap = max(worst_gap, since)
    return {
        "periods": n,
        "pct_positive": round(100.0 * pos / n, 1),
        "median_pct": round(median * 100, 2),
        "best_pct": round(max(rets) * 100, 2),
        "worst_pct": round(min(rets) * 100, 2),
        "longest_losing_streak_mo": longest,
        "longest_between_new_highs_mo": worst_gap,
        "mean_pct_secondary": round(100.0 * sum(rets) / n, 2),
    }


def main():
    out = {"family": "hunt-sin-stocks", "form": "v13-best-rules: quarterly EW, PIT entry, no floor",
           "sin_names": SIN, "comparable_names": COMP, "roads": {}}
    log = []
    # integrity gate: monthly replica
    gate = {}
    for road, (s, e) in ROADS.items():
        c, _ = simulate(SIN, s, e, cadence="monthly")
        gate[road] = round(c[-1][1], 2)
    out["integrity_gate_monthly_replica"] = gate
    out["v12_native_reference"] = V12_NATIVE
    log.append(f"integrity gate (monthly replica): {gate} vs v12 native {V12_NATIVE}")

    for road, (s, e) in ROADS.items():
        sin_curve, ntr = simulate(SIN, s, e, cadence="quarterly")
        comp_curve, _ = simulate(COMP, s, e, cadence="quarterly")
        placebo_finals = []
        for seed in range(20):
            pc, _ = simulate(COMP, s, e, cadence="quarterly", seed=seed + 1)
            placebo_finals.append(round(pc[-1][1], 2))
        sin_final = round(sin_curve[-1][1], 2)
        beaten = sum(1 for f in placebo_finals if sin_final > f)
        out["roads"][road] = {
            "best_rules_sin": {"final": sin_final, "max_dd_pct": max_dd(sin_curve),
                               "n_rebalance_trades": ntr, "curve": sin_curve},
            "comparable_basket": {"final": round(comp_curve[-1][1], 2),
                                  "max_dd_pct": max_dd(comp_curve), "curve": comp_curve},
            "placebos_20_random_comparable_baskets": placebo_finals,
            "placebos_beaten": beaten,
            "period_stats_monthly": period_stats(sin_curve),
            "v12_native_sin": V12_NATIVE[road],
            "v12_comparable": V12_COMP[road],
            "champion_vm": CHAMPION[road],
            "spy_ref": SPY_REF[road],
        }
        log.append(f"{road}: best-rules sin ${sin_final} (DD {max_dd(sin_curve)}%) | "
                   f"comp ${round(comp_curve[-1][1],2)} | placebos beaten {beaten}/20 | "
                   f"v12 native ${V12_NATIVE[road]} | champ ${CHAMPION[road]} | SPY ${SPY_REF[road]}")
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    open(os.path.join(HERE, "run.log"), "w").write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
