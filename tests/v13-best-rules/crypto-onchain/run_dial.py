#!/usr/bin/env python3
"""crypto-onchain V13 MVRV-DIAL runs — BEST-RULES-SPEC.md frozen 2026-11-22 BEFORE this run.
Dial: target weight by MVRV band, weekly rebalance check, 0.10 no-trade band,
0.60%/side on traded notional, NO floor. Roads = v12 exact: FULL / DESIGN / VALIDATION.
Data: v12 cache (read-only). Family-best comparison read from v12 results.json at report time.
"""
import json, os, random, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/crypto-onchain")
DATA = os.path.join(V12, "data")
COST = 0.006
END = "2026-11-20"
WINDOWS = {"FULL": (None, END), "DESIGN": (None, "2022-12-31"), "VALIDATION": ("2023-01-01", END)}
BANDS = [(1.0, 1.00), (2.0, 0.85), (3.0, 0.65), (3.7, 0.45)]  # (upper bound, weight); above last -> 0.25
TOP_W = 0.25

def target_weight(mvrv, scale=1.0):
    for ub, w in BANDS:
        if mvrv < ub * scale:
            return w
    return TOP_W

def load_cm(coin):
    rows = json.load(open(f"{DATA}/cm_{coin}.json"))
    out = []
    for r in rows:
        try:
            out.append((r["time"][:10], float(r["PriceUSD"]), float(r["CapMVRVCur"])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    return [r for r in out if r[1] > 0 and r[2] > 0]

def run_dial(dates, prices, mvrv, scale=1.0):
    """Weekly check (every 7 idx from window start) on close-t MVRV; weight earns t->t+1.
    Trade cost 0.60% * |delta w| when |target-current| >= 0.10 (or first entry)."""
    eq = 100.0; curve = [(dates[0], eq)]; w = 0.0; trades = 0; cost_paid = 0.0
    peak = eq; maxdd = 0.0
    for i in range(len(dates) - 1):
        if i % 7 == 0:
            tw = target_weight(mvrv[i], scale)
            if w == 0.0 and tw > 0:
                c = COST * tw * eq; eq -= c; cost_paid += c; w = tw; trades += 1
            elif abs(tw - w) >= 0.10:
                c = COST * abs(tw - w) * eq; eq -= c; cost_paid += c; w = tw; trades += 1
        eq *= (1 + w * (prices[i + 1] / prices[i] - 1))
        curve.append((dates[i + 1], eq))
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
    return eq, curve, trades, round(cost_paid, 2), maxdd

def hold(dates, prices):
    eq = 100.0 * (1 - COST); curve = [(dates[0], 100.0)]
    for i in range(len(dates) - 1):
        eq *= prices[i + 1] / prices[i]; curve.append((dates[i + 1], eq))
    f = eq * (1 - COST)
    peak = 100.0; maxdd = 0.0
    for _, e in curve:
        peak = max(peak, e); maxdd = min(maxdd, e / peak - 1)
    return f, curve, maxdd

def monthly_stats(curve):
    months = {}
    for d, e in curve:
        months[d[:7]] = e
    keys = sorted(months)
    rets = [months[b] / months[a] - 1 for a, b in zip(keys, keys[1:])]
    if not rets: return None
    win = sum(1 for r in rets if r > 0)
    ls = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; ls = max(ls, cur)
    peak = -1; since = 0; longest = 0
    for k in keys:
        if months[k] >= peak: peak = months[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"n_periods": len(rets), "pct_positive": round(100 * win / len(rets), 1),
            "median_period_pct": round(100 * st.median(rets), 2),
            "mean_period_pct_secondary": round(100 * st.mean(rets), 2),
            "best_period_pct": round(100 * max(rets), 2), "worst_period_pct": round(100 * min(rets), 2),
            "longest_losing_streak_periods": ls, "longest_stretch_below_high_periods": longest}

def slice_win(dates, prices, mvrv, ws, we):
    idx = [i for i, d in enumerate(dates) if (ws is None or d >= ws) and (we is None or d <= we)]
    if len(idx) < 30: return None
    s, e = idx[0], idx[-1] + 1
    return dates[s:e], prices[s:e], mvrv[s:e]

# family best native per coin/road from v12 results.json (reporting-time comparison only)
v12 = json.load(open(os.path.join(V12, "results.json")))
fam_best = {}
for sysname, wins in v12["systems"].items():
    if "/" not in sysname or "FLIPPED" in sysname: continue
    coin = sysname.split("/")[1]
    for wname, e in wins.items():
        if wname not in WINDOWS: continue
        f = e["native"]["final"]
        k = (coin, wname)
        if k not in fam_best or f > fam_best[k][0]:
            fam_best[k] = (f, sysname, e["native"]["max_dd_pct"])

RESULTS = {"meta": {"system": "MVRV-DIAL (V13 best rules)", "cost_per_side_on_traded_notional": COST,
                    "spec": "BEST-RULES-SPEC.md frozen 2026-11-22 before run", "end": END,
                    "verdict_ceiling": "CANDIDATE"},
           "coins": {}, "placebos": {}}

coins = {}
for coin in ["btc", "eth", "ltc", "doge", "bch", "ada", "xrp", "xlm", "zec", "dash", "etc"]:
    if not os.path.exists(f"{DATA}/cm_{coin}.json"): continue
    s = load_cm(coin)
    if len(s) >= 1000: coins[coin] = s
print("coins:", {c: (len(s), s[0][0], s[-1][0]) for c, s in coins.items()}, flush=True)

for coin, s in coins.items():
    dates = [r[0] for r in s]; prices = [r[1] for r in s]; mvrv = [r[2] for r in s]
    entry = {}
    for wname, (ws, we) in WINDOWS.items():
        sl = slice_win(dates, prices, mvrv, ws, we)
        if sl is None: continue
        d2, p2, m2 = sl
        f, curve, trades, cp, dd = run_dial(d2, p2, m2)
        hf, hcurve, hdd = hold(d2, p2)
        fb = fam_best.get((coin, wname))
        entry[wname] = {"dial_final": round(f, 2), "dial_max_dd_pct": round(100 * dd, 1),
                        "rebalances": trades, "cost_paid": cp,
                        "hold_final": round(hf, 2), "hold_max_dd_pct": round(100 * hdd, 1),
                        "family_best_native": ({"final": fb[0], "system": fb[1], "max_dd_pct": fb[2]} if fb else None),
                        "monthly": monthly_stats(curve),
                        "curve": [[d, round(e, 4)] for d, e in curve],
                        "hold_curve": [[d, round(e, 4)] for d, e in hcurve]}
    RESULTS["coins"][coin] = entry
    print("done", coin, flush=True)

rng = random.Random(20261122)
for coin in ["btc", "eth"]:
    s = coins[coin]; dates = [r[0] for r in s]; prices = [r[1] for r in s]; mvrv = [r[2] for r in s]
    seeds = []
    for _ in range(20):
        scale = rng.uniform(0.75, 1.33)
        out = {"scale": round(scale, 3)}
        for wname in ["FULL", "VALIDATION"]:
            ws, we = WINDOWS[wname]
            d2, p2, m2 = slice_win(dates, prices, mvrv, ws, we)
            f, _, _, _, _ = run_dial(d2, p2, m2, scale=scale)
            out[wname] = round(f, 2)
        seeds.append(out)
    RESULTS["placebos"][coin] = seeds
    print("placebos done", coin, flush=True)

json.dump(RESULTS, open(os.path.join(HERE, "results.json"), "w"))
print("WROTE results.json", flush=True)
for coin, entry in RESULTS["coins"].items():
    for wname, e in entry.items():
        fb = e["family_best_native"]
        print(coin.upper(), wname, "DIAL", e["dial_final"], "dd", e["dial_max_dd_pct"],
              "| HOLD", e["hold_final"], "dd", e["hold_max_dd_pct"],
              "| FAMBEST", (fb["final"], fb["system"]) if fb else None, flush=True)
for coin, seeds in RESULTS["placebos"].items():
    for wname in ["FULL", "VALIDATION"]:
        vals = sorted(s[wname] for s in seeds)
        print("PLACEBO", coin.upper(), wname, "median", round(st.median(vals), 2), "min", vals[0], "max", vals[-1], flush=True)
