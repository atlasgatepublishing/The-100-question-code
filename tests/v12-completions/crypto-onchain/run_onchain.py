#!/usr/bin/env python3
"""crypto-onchain v12 runs — frozen CONSTRUCTION-SPEC.md (2026-11-22).
Systems: MVRV-ZONE, MVRV-ACCUM, ZSCORE-ZONE, ZSCORE-ACCUM, SOPR-1LINE, FLOW-NET.
Long/cash, signal t close -> earns t->t+1, 0.60%/side, NATIVE + V9 (-15% floor).
Period record: MONTHLY (native tempo for cycle gauges) + daily in JSON.
"""
import json, os, math, random, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
COST = 0.006
END = "2026-11-20"

def load_cm(coin):
    rows = json.load(open(f"{DATA}/cm_{coin}.json"))
    out = []
    for r in rows:
        try:
            out.append((r["time"][:10], float(r["PriceUSD"]), float(r["CapMVRVCur"]), float(r["CapMrktCurUSD"])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    return [r for r in out if r[1] > 0 and r[2] > 0 and r[3] > 0]

def load_flows(coin):
    rows = json.load(open(f"{DATA}/cm_{coin}_flows.json"))
    out = {}
    for r in rows:
        try:
            out[r["time"][:10]] = float(r["FlowInExNtv"]) - float(r["FlowOutExNtv"])
        except (KeyError, TypeError, ValueError):
            continue
    return out

def zscores(series):
    """PIT expanding z: (MC-RC)/std(MC expanding), RC=MC/MVRV. Warmup 365."""
    mc = [s[3] for s in series]; rc = [s[3] / s[2] for s in series]
    z = [None] * len(series); n = 0; mean = 0.0; m2 = 0.0
    for i in range(len(series)):
        x = mc[i]; n += 1; d = x - mean; mean += d / n; m2 += d * (x - mean)
        if n >= 365 and m2 > 0:
            z[i] = (mc[i] - rc[i]) / math.sqrt(m2 / (n - 1))
    return z

def run_system(dates, prices, pos, floor=False):
    """pos[i] in {0,1}: position decided at close i, earns i->i+1.
    Returns (final, curve list of (date, equity), n_switches, max_dd, stopped_date)."""
    eq = 100.0; curve = [(dates[0], eq)]; prev = 0; switches = 0; peak = eq; maxdd = 0.0
    for i in range(len(dates) - 1):
        p = pos[i]
        if p != prev:
            eq *= (1 - COST); switches += 1; prev = p
        if p == 1:
            eq *= prices[i + 1] / prices[i]
        curve.append((dates[i + 1], eq))
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
        if floor and eq <= 85.0:
            # exit at next day's close if one exists, then stop
            if i + 2 <= len(dates) - 1:
                if prev == 1:
                    eq *= (1 - COST); switches += 1
                curve.append((dates[i + 2], eq))
            return eq, curve, switches, maxdd, dates[min(i + 2, len(dates) - 1)]
    return eq, curve, switches, maxdd, None

def hold(dates, prices):
    eq = 100.0 * (1 - COST); curve = [(dates[0], 100.0)]
    for i in range(len(dates) - 1):
        eq *= prices[i + 1] / prices[i]; curve.append((dates[i + 1], eq))
    return eq * (1 - COST), curve

def monthly_stats(curve):
    """Period-by-period record at monthly tempo from an equity curve."""
    months = {}
    for d, e in curve:
        months[d[:7]] = e  # last equity of month
    keys = sorted(months)
    rets = []
    for a, b in zip(keys, keys[1:]):
        rets.append(months[b] / months[a] - 1)
    if not rets:
        return None
    win = sum(1 for r in rets if r > 0)
    # longest losing streak
    ls = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; ls = max(ls, cur)
    # longest stretch between new highs (months)
    peak = -1; since = 0; longest = 0
    for k in keys:
        if months[k] >= peak:
            peak = months[k]; longest = max(longest, since); since = 0
        else:
            since += 1
    longest = max(longest, since)
    return {"n_periods": len(rets), "pct_positive": round(100 * win / len(rets), 1),
            "median_period_pct": round(100 * st.median(rets), 2),
            "mean_period_pct_secondary": round(100 * st.mean(rets), 2),
            "best_period_pct": round(100 * max(rets), 2), "worst_period_pct": round(100 * min(rets), 2),
            "longest_losing_streak_periods": ls, "longest_stretch_below_high_periods": longest}

def window_slice(dates, *arrs, start=None, end=None):
    idx = [i for i, d in enumerate(dates) if (start is None or d >= start) and (end is None or d <= end)]
    if len(idx) < 30: return None
    sl = slice(idx[0], idx[-1] + 1)
    return (dates[sl],) + tuple(a[sl] for a in arrs)

def evaluate(name, coin, dates, prices, posfn, windows):
    """posfn(full arrays) -> pos list computed on FULL data (PIT: signals use only past)."""
    pos = posfn()
    res = {}
    for wname, (ws, we) in windows.items():
        s = window_slice(dates, prices, pos, start=ws, end=we)
        if s is None: continue
        d2, p2, pos2 = s
        hn, _ = hold(d2, p2)
        entry = {"hold_final": round(hn, 2)}
        for rs, fl in [("native", False), ("v9", True)]:
            f, curve, sw, dd, stop = run_system(d2, p2, pos2, floor=fl)
            entry[rs] = {"final": round(f, 2), "max_dd_pct": round(100 * dd, 1), "switches": sw,
                         "floored_out": stop, "curve": [[d, round(e, 4)] for d, e in curve],
                         "monthly": monthly_stats(curve)}
        res[wname] = entry
    return res

RESULTS = {"meta": {"cost_per_side": COST, "end": END, "spec": "CONSTRUCTION-SPEC.md frozen 2026-11-22"}, "systems": {}, "placebos": {}}
WINDOWS = {"FULL": (None, END), "DESIGN": (None, "2022-12-31"), "VALIDATION": ("2023-01-01", END)}

coin_series = {}
for coin in ["btc", "eth", "ltc", "doge", "bch", "ada", "xrp", "xlm", "zec", "dash", "etc"]:
    p = f"{DATA}/cm_{coin}.json"
    if not os.path.exists(p): continue
    s = load_cm(coin)
    if len(s) >= 1000:
        coin_series[coin] = s
print("coins with >=1000 rows:", {c: (len(s), s[0][0], s[-1][0]) for c, s in coin_series.items()}, flush=True)

for coin, s in coin_series.items():
    dates = [r[0] for r in s]; prices = [r[1] for r in s]; mvrv = [r[2] for r in s]
    z = zscores(s)
    def zone(mvrv=mvrv): return [0 if (m is not None and m >= 3.7) else 1 for m in mvrv]
    def accum(mvrv=mvrv):
        pos = []; state = 0
        for m in mvrv:
            if m < 1.0: state = 1
            elif m >= 3.7: state = 0
            pos.append(state)
        return pos
    def zzone(z=z): return [0 if (zz is not None and zz >= 7) else (1 if zz is not None else 0) for zz in z]
    def zaccum(z=z):
        pos = []; state = 0
        for zz in z:
            if zz is None: pos.append(0); continue
            if zz < 0: state = 1
            elif zz >= 7: state = 0
            pos.append(state)
        return pos
    for sysname, fn in [("MVRV-ZONE", zone), ("MVRV-ACCUM", accum)]:
        RESULTS["systems"][f"{sysname}/{coin}"] = evaluate(sysname, coin, dates, prices, fn, WINDOWS)
    if coin in ("btc", "eth"):
        for sysname, fn in [("ZSCORE-ZONE", zzone), ("ZSCORE-ACCUM", zaccum)]:
            RESULTS["systems"][f"{sysname}/{coin}"] = evaluate(sysname, coin, dates, prices, fn, WINDOWS)
        flows = load_flows(coin)
        nf = [flows.get(d) for d in dates]
        def flownet(nf=nf):
            pos = []; 
            for i in range(len(nf)):
                if i < 30 or any(v is None for v in nf[i-29:i+1]): pos.append(0)
                else: pos.append(1 if sum(nf[i-29:i+1]) / 30 < 0 else 0)
            return pos
        RESULTS["systems"][f"FLOW-NET/{coin}"] = evaluate("FLOW-NET", coin, dates, prices, flownet, WINDOWS)
        def flowflip(nf=nf):
            pos = []
            for i in range(len(nf)):
                if i < 30 or any(v is None for v in nf[i-29:i+1]): pos.append(0)
                else: pos.append(1 if sum(nf[i-29:i+1]) / 30 >= 0 else 0)
            return pos
        RESULTS["systems"][f"FLOW-NET-FLIPPED-CONTROL/{coin}"] = evaluate("FLOWFLIP", coin, dates, prices, flowflip, WINDOWS)
    print("done coin", coin, flush=True)

# ---- SOPR (BTC, BGeometrics truncated window) ----
sopr_rows = json.load(open(f"{DATA}/bgeo_sopr.json"))
sopr = {r["d"]: float(r["sopr"]) for r in sopr_rows}
bs = coin_series["btc"]; bdates = [r[0] for r in bs]; bprices = [r[1] for r in bs]
svals = [sopr.get(d) for d in bdates]
def sopr_pos(svals=svals):
    pos = []
    for i in range(len(svals)):
        if i < 7 or any(v is None for v in svals[i-6:i+1]): pos.append(0)
        else: pos.append(1 if sum(svals[i-6:i+1]) / 7 >= 1.0 else 0)
    return pos
swin = {"SOPR-WINDOW": ("2022-11-23", "2026-11-15")}
RESULTS["systems"]["SOPR-1LINE/btc"] = evaluate("SOPR", "btc", bdates, bprices, sopr_pos, swin)

# ---- Placebos ----
rng = random.Random(20261122)
def placebo_accum(coin, buy, sell):
    s = coin_series[coin]; dates = [r[0] for r in s]; prices = [r[1] for r in s]; mvrv = [r[2] for r in s]
    pos = []; state = 0
    for m in mvrv:
        if m < buy: state = 1
        elif m >= sell: state = 0
        pos.append(state)
    out = {}
    for wname, (ws, we) in [("FULL", (None, END)), ("VALIDATION", ("2023-01-01", END))]:
        sl = window_slice(dates, prices, pos, start=ws, end=we)
        d2, p2, pos2 = sl
        f, _, _, _, _ = run_system(d2, p2, pos2)
        out[wname] = round(f, 2)
    return out
for coin in ["btc", "eth"]:
    seeds = []
    for _ in range(20):
        buy = rng.uniform(0.7, 1.3); sell = rng.uniform(2.5, 5.0)
        r = placebo_accum(coin, buy, sell); r["buy"] = round(buy, 3); r["sell"] = round(sell, 3); seeds.append(r)
    RESULTS["placebos"][f"MVRV-ACCUM/{coin}"] = seeds
# SOPR placebos
seeds = []
for _ in range(20):
    line = rng.uniform(0.97, 1.03)
    def sp(svals=svals, line=line):
        pos = []
        for i in range(len(svals)):
            if i < 7 or any(v is None for v in svals[i-6:i+1]): pos.append(0)
            else: pos.append(1 if sum(svals[i-6:i+1]) / 7 >= line else 0)
        return pos
    r = evaluate("SOPRP", "btc", bdates, bprices, sp, swin)
    seeds.append({"line": round(line, 4), "final_native": r["SOPR-WINDOW"]["native"]["final"]})
RESULTS["placebos"]["SOPR-1LINE/btc"] = seeds
# FLOW placebos: random MA window
for coin in ["btc", "eth"]:
    s = coin_series[coin]; dates = [r[0] for r in s]; prices = [r[1] for r in s]
    flows = load_flows(coin); nf = [flows.get(d) for d in dates]
    seeds = []
    for _ in range(20):
        w = rng.randint(10, 60)
        pos = []
        for i in range(len(nf)):
            if i < w or any(v is None for v in nf[i-w+1:i+1]): pos.append(0)
            else: pos.append(1 if sum(nf[i-w+1:i+1]) / w < 0 else 0)
        out = {}
        for wname, (ws, we) in [("FULL", (None, END)), ("VALIDATION", ("2023-01-01", END))]:
            sl = window_slice(dates, prices, pos, start=ws, end=we)
            d2, p2, pos2 = sl
            f, _, _, _, _ = run_system(d2, p2, pos2)
            out[wname] = round(f, 2)
        out["ma_window"] = w; seeds.append(out)
    RESULTS["placebos"][f"FLOW-NET/{coin}"] = seeds
# MVRV-ZONE shifted thresholds (deterministic controls)
for coin in ["btc", "eth"]:
    s = coin_series[coin]; dates = [r[0] for r in s]; prices = [r[1] for r in s]; mvrv = [r[2] for r in s]
    ctrls = []
    for mult in [0.75, 0.85, 1.15, 1.30]:
        thr = 3.7 * mult
        pos = [0 if m >= thr else 1 for m in mvrv]
        out = {}
        for wname, (ws, we) in [("FULL", (None, END)), ("VALIDATION", ("2023-01-01", END))]:
            sl = window_slice(dates, prices, pos, start=ws, end=we)
            d2, p2, pos2 = sl
            f, _, _, _, _ = run_system(d2, p2, pos2)
            out[wname] = round(f, 2)
        out["exit_threshold"] = round(thr, 3); ctrls.append(out)
    RESULTS["placebos"][f"MVRV-ZONE-SHIFTS/{coin}"] = ctrls

json.dump(RESULTS, open(os.path.join(HERE, "results.json"), "w"))
print("WROTE results.json", flush=True)
for k, v in RESULTS["systems"].items():
    for w, e in v.items():
        print(k, w, "hold", e["hold_final"], "native", e["native"]["final"], "dd", e["native"]["max_dd_pct"], "v9", e["v9"]["final"], flush=True)
