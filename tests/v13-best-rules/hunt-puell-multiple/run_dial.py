#!/usr/bin/env python3
"""V13 hunt-puell-multiple — PUELL-DIAL per BEST-RULES-SPEC.md (frozen first).

Halving-adjusted Puell P* = (IssTotUSD/subsidy) / SMA365(IssTotUSD/subsidy).
Log-linear dial: w=clip((ln2 - lnP*)/(ln2 - ln0.5),0,1). Weekly rebalance,
+-0.10 no-trade band, 0.60%/side, $100, NO floor. BTC only.
Also re-runs the v12 switch forms on this chassis as a plumbing check
against the published v12 finals. Simulation only."""
import json, math, os, random
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
END = "2026-11-20"
SUBSIDY = [("2012-11-28", 25.0), ("2016-07-09", 12.5), ("2020-05-11", 6.25),
           ("2024-04-20", 3.125)]  # (first date at new subsidy, subsidy BTC/block)

def subsidy(d):
    s = 50.0
    for dt, v in SUBSIDY:
        if d >= dt: s = v
    return s

cm = json.load(open(os.path.join(HERE, "data", "cm_btc.json")))
rows = sorted((r["time"][:10], float(r["PriceUSD"]), float(r["IssTotUSD"]))
              for r in cm if float(r["PriceUSD"]) > 0)
dates = [r[0] for r in rows]; prices = [r[1] for r in rows]
raw_iss = [r[2] for r in rows]
adj_iss = [r[2] / subsidy(r[0]) for r in rows]

def sma365(x):
    out = [None] * len(x); s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= 365: s -= x[i - 365]
        if i >= 364: out[i] = s / 365.0
    return out

sma_raw, sma_adj = sma365(raw_iss), sma365(adj_iss)
puell_raw = [None if sma_raw[i] is None else raw_iss[i] / sma_raw[i] for i in range(len(rows))]
puell_adj = [None if sma_adj[i] is None else adj_iss[i] / sma_adj[i] for i in range(len(rows))]

def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = min(mdd, e / peak - 1.0)
    return mdd

def monthly_stats(curve):
    """curve: [(date, equity)] daily. Month-end marks -> per-period distribution."""
    marks = {}
    for d, e in curve: marks[d[:7]] = e
    months = sorted(marks)
    rets = []
    for i in range(1, len(months)):
        prev, cur = marks[months[i - 1]], marks[months[i]]
        if prev > 0: rets.append(cur / prev - 1.0)
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    peak = -1.0; since = 0; longest = 0
    for m in months:
        if marks[m] >= peak: peak, since = marks[m], 0
        else:
            since += 1; longest = max(longest, since)
    return dict(months=n, median_pct=round(med * 100, 2),
                share_positive_pct=round(100.0 * sum(1 for r in rets if r > 0) / n, 1),
                best_pct=round(max(rets) * 100, 1), worst_pct=round(min(rets) * 100, 1),
                longest_losing_streak=worst_streak, longest_between_highs_months=longest,
                avg_pct_secondary=round(sum(rets) / n * 100, 2))

def run_switch(dates_w, prices_w, pos):
    """v12 chassis: binary position list (signal t close -> earns t->t+1), cost/side on switches."""
    eq, cur, switches = 100.0, 0, 0
    curve = [(dates_w[0], eq)]
    for i in range(len(dates_w) - 1):
        tgt = pos[i]
        if tgt != cur:
            eq *= (1 - COST); switches += 1; cur = tgt
        if cur == 1: eq *= prices_w[i + 1] / prices_w[i]
        curve.append((dates_w[i + 1], eq))
    return eq, curve, switches

def run_dial(dates_w, prices_w, pstar, full_anchor=0.5, zero_anchor=2.0, seed_i0=0):
    """Weekly rebalance to log-linear dial weight, +-0.10 band, cost on traded notional."""
    lnf, lnz = math.log(full_anchor), math.log(zero_anchor)
    def target(p):
        if p is None: return 0.0
        w = (lnz - math.log(p)) / (lnz - lnf)
        return min(1.0, max(0.0, w))
    eq = 100.0; w_cur = 0.0; trades = 0; turnover = 0.0
    curve = [(dates_w[0], eq)]
    for i in range(len(dates_w) - 1):
        if (i - seed_i0) % 7 == 0:
            w_t = target(pstar[i])
            if abs(w_t - w_cur) >= 0.10:
                eq *= (1 - COST * abs(w_t - w_cur)); trades += 1
                turnover += abs(w_t - w_cur); w_cur = w_t
        eq *= (1 - w_cur) + w_cur * (prices_w[i + 1] / prices_w[i])
        curve.append((dates_w[i + 1], eq))
    return eq, curve, trades, turnover, w_cur

def bh(dates_w, prices_w):
    return 100.0 * (prices_w[-1] / prices_w[0]) * (1 - COST) ** 2

def accum_pos(p, buy, sell):
    pos, cur = [], 0
    for v in p:
        if v is not None:
            if cur == 0 and v < buy: cur = 1
            elif cur == 1 and v >= sell: cur = 0
        pos.append(cur)
    return pos

def zone_pos(p, line):
    return [0 if v is None else (0 if v >= line else 1) for v in p]

WIN = {"FULL": (None, END), "DESIGN": (None, "2022-12-31"), "VALIDATION": ("2023-01-01", END)}
def window(a, b):
    idx = [i for i, d in enumerate(dates) if (a is None or d >= a) and d <= b]
    return idx

out = {"family": "hunt-puell-multiple", "program": "v13-best-rules",
       "system": "PUELL-DIAL", "cost_per_side": COST, "roads": {}, "placebos": {},
       "plumbing_check_v12_forms": {}}

# --- plumbing check: reproduce v12 published finals on this chassis ---
for name, pos in [("PUELL-ACCUM", accum_pos(puell_raw, 0.5, 4.0)),
                  ("PUELL-ZONE", zone_pos(puell_raw, 4.0))]:
    out["plumbing_check_v12_forms"][name] = {}
    for w, (a, b) in WIN.items():
        idx = window(a, b)
        dd = [dates[i] for i in idx]; pp = [prices[i] for i in idx]
        f, _, sw = run_switch(dd, pp, [pos[i] for i in idx])
        out["plumbing_check_v12_forms"][name][w] = dict(final=round(f, 2), switches=sw,
                                                        bh_bar=round(bh(dd, pp), 2))

# --- the dial ---
for w, (a, b) in WIN.items():
    idx = window(a, b)
    dd = [dates[i] for i in idx]; pp = [prices[i] for i in idx]
    ps = [puell_adj[i] for i in idx]
    f, curve, trades, turnover, w_end = run_dial(dd, pp, ps)
    out["roads"][w] = dict(final=round(f, 2), max_dd=round(max_dd(curve), 4),
                           trades=trades, turnover=round(turnover, 2),
                           final_weight=round(w_end, 3), bh_bar=round(bh(dd, pp), 2),
                           monthly=monthly_stats(curve),
                           curve=[[d, round(e, 4)] for d, e in curve])

# --- placebos: 20 random anchor pairs, same chassis ---
for w in ["FULL", "VALIDATION"]:
    a, b = WIN[w]; idx = window(a, b)
    dd = [dates[i] for i in idx]; pp = [prices[i] for i in idx]
    ps = [puell_adj[i] for i in idx]
    finals = []
    for s in range(20):
        rng = random.Random(3100 + s)
        fa, za = rng.uniform(0.30, 0.70), rng.uniform(1.5, 2.5)
        f, _, _, _, _ = run_dial(dd, pp, ps, fa, za)
        finals.append(round(f, 2))
    out["placebos"][w] = finals

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for w in WIN:
    r = out["roads"][w]
    print("DIAL", w, "final", r["final"], "maxDD", r["max_dd"], "BH", r["bh_bar"],
          "trades", r["trades"], "monthly", r["monthly"])
for n in out["plumbing_check_v12_forms"]:
    for w in WIN:
        r = out["plumbing_check_v12_forms"][n][w]
        print("CHECK", n, w, r["final"], "BH", r["bh_bar"], "sw", r["switches"])
for w in ["FULL", "VALIDATION"]:
    mine = out["roads"][w]["final"]
    ge = sum(1 for f in out["placebos"][w] if f >= mine)
    print("PLACEBO", w, f"{ge}/20 >= dial ({mine})", "median", sorted(out["placebos"][w])[10])
