"""Shared timer chassis (v12 hunt slice 5): loaders, state simulator with
v9 house floor, circular-shift placebos, per-period distribution stats.
Copied verbatim into each family run script (folders stay self-contained)."""
import json, os, glob, time, random, statistics

STKDATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
START = 100.0
STK_COST = 0.001; STK_FEE = 0.01; CRY_COST = 0.006
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-11-21", "CONT": "2019-01-01", "VAL": "2023-01-01"}
END = "2026-11-20"; CEND = "2026-11-21"
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def load_stock(sym):
    p = os.path.join(STKDATA, f"pxfull_{sym}.json")
    if not os.path.exists(p): return []
    j = json.loads(open(p, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or c == 0: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": o * r, "h": h * r, "l": l * r, "c": a,
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"]); return bars

def load_coin(sym):
    p = os.path.join(CBASE, f"y_{sym}-USD.json")
    if not os.path.exists(p): return []
    rows = json.load(open(p))
    bars = []
    for r in rows:
        o, c = r.get("o"), r.get("c")
        if not o or not c: continue
        bars.append({"d": r["d"], "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 0})
    bars.sort(key=lambda b: b["d"]); return bars

def coin_universe():
    snaps = json.load(open(os.path.join(CBASE, "snapshots.json")))
    syms = set()
    for s in snaps.values():
        for e in s.get("top20", []): syms.add(e["symbol"])
    return sorted(syms)

def simulate(bars, states, cost, sell_fee=0.0, house=False, exec_open=False):
    """states[i] = desired in/out AFTER close of bar i (full-history series).
    Bars must already be sliced to the road window; states aligned to bars.
    exec at close (default) or next open (exec_open=True: state decided at
    close t trades at open t+1). House v9: -15% floor vs episode anchor on
    closes; breach -> exit next open, 90 calendar days cash, one restart;
    second breach ends the run."""
    n = len(bars); eq = START; curve = []; costs = 0.0; orders = 0
    shares = 0.0; inpos = False; halts = 0; halt_until = None; ended = False
    anchor = START; invested_days = 0
    pend = None  # (target_state) to execute at next open
    for i, b in enumerate(bars):
        # execute pending open order
        if pend is not None:
            tgt = pend; pend = None
            if tgt and not inpos:
                px = b["o"]; cst = eq * cost; costs += cst
                shares = (eq - cst) / px; eq = eq - cst; inpos = True; orders += 1
            elif not tgt and inpos:
                px = b["o"]; gross = shares * px; cst = gross * cost + sell_fee
                costs += cst; eq = gross - cst; shares = 0.0; inpos = False; orders += 1
        if inpos: invested_days += 1
        val = shares * b["c"] if inpos else eq
        # house floor check at close
        if house and inpos and not ended and val <= 0.85 * anchor:
            halts += 1
            if halts >= 2:
                pend = False; ended = True
            else:
                pend = False; halt_until = i + 63  # ~90 calendar days in bars
                anchor = None
        if halt_until is not None and i >= halt_until and not ended:
            halt_until = None; anchor = val  # new episode anchor at restart value
        # state decision at close
        if not ended and halt_until is None:
            tgt = states[i] if i < len(states) else inpos
            if exec_open:
                if tgt != inpos: pend = tgt
            else:
                if tgt and not inpos:
                    px = b["c"]; cst = val * cost; costs += cst
                    shares = (val - cst) / px; inpos = True; orders += 1
                    val = val - cst
                elif not tgt and inpos:
                    gross = shares * b["c"]; cst = gross * cost + sell_fee
                    costs += cst; eq = gross - cst; shares = 0.0; inpos = False
                    orders += 1; val = eq
        if inpos: val = shares * b["c"]
        else: val = eq if shares == 0 else val
        curve.append([b["d"], round(val, 4)])
    final = curve[-1][1] if curve else START
    peak = START; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(final, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "halts": halts, "curve": curve,
            "invested_frac": round(invested_days / n, 3) if n else 0.0}

def hold_final(bars):
    if len(bars) < 2: return None
    return round(START * bars[-1]["c"] / bars[0]["o"], 2)

def slice_road(bars, start, end):
    return [b for b in bars if start <= b["d"] <= end]

def period_stats(curve, freq="M"):
    """Monthly distribution from a daily [date, equity] curve."""
    if not curve: return None
    mend = {}
    for d, v in curve: mend[d[:7]] = v
    keys = sorted(mend)
    rets = []
    prev = START
    for k in keys:
        rets.append(mend[k] / prev - 1.0); prev = mend[k]
    if not rets: return None
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = START; since = 0; longest = 0
    for k in keys:
        if mend[k] >= peak: peak = mend[k]; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4),
            "best": round(max(rets), 4), "worst": round(min(rets), 4),
            "longest_losing_streak": streak, "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 4)}

def shifted_states(states, seed, lo=20):
    n = len(states)
    if n < 10: return states
    rng = random.Random(seed)
    off = rng.randrange(lo, n - lo) if n > 2 * lo else rng.randrange(1, n)
    return states[off:] + states[:off]

def placebo_beaten(bars, states, real_final, cost, sell_fee=0.0, exec_open=False, seeds=20):
    beaten = 0; finals = []
    for s in range(1, seeds + 1):
        st = shifted_states(states, 1000 + s)
        r = simulate(bars, st, cost, sell_fee, house=False, exec_open=exec_open)
        finals.append(r["final"])
        if real_final > r["final"]: beaten += 1
    return beaten, finals
