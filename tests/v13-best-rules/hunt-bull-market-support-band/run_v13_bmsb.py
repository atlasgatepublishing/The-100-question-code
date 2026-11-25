#!/usr/bin/env python3
"""V13 BEST-RULES — Bull Market Support Band (Cowen). Implements BEST-RULES-SPEC.md exactly:
- Band = zone between 20-week SMA and 21-week EMA of weekly closes (UTC weeks ending Sunday).
- HYSTERESIS state machine: if LONG, exit on first weekly close < lower edge; if FLAT,
  re-enter only on first weekly close >= upper edge; closes inside the zone change nothing.
- Execution at the signal (Sunday) close itself — crypto trades 24/7, no Monday lag.
- BTC + ETH, CoinMetrics PriceUSD (read-only cache in v12-completions/crypto-onchain/data).
- 0.60%/side, $100 pots, NO floor in the headline rule (a -15% floor variant is stored as
  a diagnostic only). Controls (SMA20-only / EMA21-only, v12 Monday-lag form) recomputed
  for context. Placebos: 20-seed exposure-matched random weekly timing + 20-seed
  circularly-shifted real signal (>=4-week shift). Chassis functions copied verbatim from
  the family's v12 common.py (read-only input)."""
import json, os, random, statistics, sys
from datetime import date

START = 100.0
CRY_COST = 0.006
HERE = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/hunt-bull-market-support-band")
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/crypto-onchain/data")

# ---- chassis (copied verbatim from v12 common.py) ----
def maxdd(curve):
    peak = -1e18; dd = 0.0
    for p in curve:
        peak = max(peak, p["eq"]); dd = max(dd, (peak - p["eq"]) / peak if peak > 0 else 0.0)
    return round(dd * 100, 2)

def sim_close_exec(bars, states, cost=CRY_COST, house=False):
    cash_frac = 1.0; pos = 0; eq = START; curve = []; trades = 0; costs = 0.0; halted = False
    prev_c = None
    for i, b in enumerate(bars):
        if prev_c is not None and pos == 1 and not halted:
            eq *= b["c"] / prev_c
        if not halted:
            want = states[i]
            if want != pos:
                costs += eq * cost; eq *= (1 - cost); trades += 1; pos = want
        curve.append({"d": b["d"], "eq": round(eq, 4)})
        if house and not halted and eq <= 85.0:
            if pos == 1: costs += eq * cost; eq *= (1 - cost); trades += 1; pos = 0
            halted = True; curve[-1] = {"d": b["d"], "eq": round(eq, 4)}
        prev_c = b["c"]
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve, "trades": trades,
            "costs": round(costs, 2), "maxdd": maxdd(curve),
            "invested_frac": round(sum(1 for s in states if s == 1) / max(1, len(states)), 4), "halted": halted}

def buyhold_close(bars, cost=CRY_COST):
    if len(bars) < 2: return START
    return START * (1 - cost) * (bars[-1]["c"] / bars[0]["c"]) * (1 - cost)

def period_stats(curve, tempo="monthly"):
    if not curve: return {}
    months = {}
    for c in curve: months[c["d"][:7]] = c["eq"]
    ks = sorted(months); rets = []
    prev = START
    for k in ks:
        rets.append(months[k] / prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = 0; worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst_streak = max(worst_streak, streak)
    vals = [START] + [months[k] for k in ks]
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"tempo": tempo, "n_periods": len(rets), "share_positive": round(pos / len(rets), 4),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst_streak, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def ema_series(vals, n):
    k = 2 / (n + 1); out = []; e = None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out

def sma_series(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i - n]
        if i >= n - 1: out[i] = s / n
    return out

# ---- data ----
def load_cm(asset):
    rows = json.load(open(os.path.join(CACHE, f"cm_{asset}.json")))
    bars = [{"d": r["time"][:10], "o": float(r["PriceUSD"]), "c": float(r["PriceUSD"])} for r in rows]
    bars.sort(key=lambda b: b["d"]); return bars

def weekly_sundays(bars):
    sun = {}
    for b in bars:
        if date.fromisoformat(b["d"]).weekday() == 6: sun[b["d"]] = b["c"]
    return sorted(sun.items())

WINDOWS = {"FULL": (None, "2026-11-20"), "DESIGN": (None, "2022-12-31"), "VALIDATION": ("2023-01-01", "2026-11-20")}

def run_asset(asset):
    bars = load_cm(asset)
    wk = weekly_sundays(bars); wdates = [d for d, _ in wk]; wcloses = [c for _, c in wk]
    sma20 = sma_series(wcloses, 20); ema21 = ema_series(wcloses, 21)
    lo = [None if sma20[i] is None else min(sma20[i], ema21[i]) for i in range(len(wk))]
    hi = [None if sma20[i] is None else max(sma20[i], ema21[i]) for i in range(len(wk))]

    # MY RULE: hysteresis over the zone
    def my_states():
        st = []; pos = 0
        for i in range(len(wk)):
            if lo[i] is None: st.append(0); continue
            if pos == 1 and wcloses[i] < lo[i]: pos = 0
            elif pos == 0 and wcloses[i] >= hi[i]: pos = 1
            st.append(pos)
        return st
    # v12 published construction states (lower edge both ways) — for control recompute
    def v12_states(kind):
        st = []
        for i in range(len(wk)):
            if sma20[i] is None: st.append(0); continue
            if kind == "band": st.append(1 if wcloses[i] >= lo[i] else 0)
            elif kind == "sma": st.append(1 if wcloses[i] >= sma20[i] else 0)
            elif kind == "ema": st.append(1 if wcloses[i] >= ema21[i] else 0)
        return st
    # daily mapping: mine executes AT the Sunday close (state effective on Sunday itself);
    # v12 form applies from Monday (strictly after Sunday)
    def daily_states(wstates, at_close):
        st = []; wi = -1
        for b in bars:
            if at_close:
                while wi + 1 < len(wdates) and wdates[wi+1] <= b["d"]: wi += 1
            else:
                while wi + 1 < len(wdates) and wdates[wi+1] < b["d"]: wi += 1
            st.append(wstates[wi] if wi >= 0 else 0)
        return st
    def window_run(dst):
        out = {}
        for wname, (s, e) in WINDOWS.items():
            idx = [i for i, b in enumerate(bars) if (s is None or b["d"] >= s) and b["d"] <= e]
            wb = [bars[i] for i in idx]; st = [dst[i] for i in idx]
            nat = sim_close_exec(wb, st)
            out[wname] = {"native": nat, "house_v9_diag": sim_close_exec(wb, st, house=True),
                          "buyhold": round(buyhold_close(wb), 2),
                          "buyhold_maxdd": maxdd([{"d": b["d"], "eq": round(START * (1 - CRY_COST) * (b["c"] / wb[0]["c"]), 4)} for b in wb]),
                          "periods_monthly": period_stats(nat["curve"], "monthly")}
        return out
    res = {"mine": window_run(daily_states(my_states(), at_close=True))}
    for kind in ["band", "sma", "ema"]:
        r = window_run(daily_states(v12_states(kind), at_close=False))
        res[f"control_{kind}_v12form"] = {w: {"final": r[w]["native"]["final"], "maxdd": r[w]["native"]["maxdd"],
                                              "trades": r[w]["native"]["trades"], "buyhold": r[w]["buyhold"]} for w in WINDOWS}
    # placebos on my rule
    wst = my_states()
    pls = {}
    for wname in ["FULL", "VALIDATION"]:
        s, e = WINDOWS[wname]
        idxw = [i for i, d in enumerate(wdates) if (s is None or d >= s) and d <= e]
        expo = sum(wst[i] for i in idxw) / max(1, len(idxw))
        idx = [i for i, b in enumerate(bars) if (s is None or b["d"] >= s) and b["d"] <= e]
        wb = [bars[i] for i in idx]
        rand_finals, shift_finals = [], []
        for sd in range(1, 21):
            rng = random.Random(1000 + sd)
            pw = [1 if rng.random() < expo else 0 for _ in range(len(wk))]
            dst = daily_states(pw, at_close=True)
            rand_finals.append(sim_close_exec(wb, [dst[i] for i in idx])["final"])
            rng2 = random.Random(5000 + sd)
            k = rng2.randrange(4, len(wk) - 4) if len(wk) > 8 else 4
            sw = wst[k:] + wst[:k]
            dst2 = daily_states(sw, at_close=True)
            shift_finals.append(sim_close_exec(wb, [dst2[i] for i in idx])["final"])
        mine_final = res["mine"][wname]["native"]["final"]
        pls[wname] = {"exposure": round(expo, 3),
                      "random_timing": {"finals": [round(f, 2) for f in rand_finals],
                                        "beaten": sum(1 for f in rand_finals if mine_final > f)},
                      "shifted_signal": {"finals": [round(f, 2) for f in shift_finals],
                                         "beaten": sum(1 for f in shift_finals if mine_final > f)}}
    res["placebos"] = pls
    return res

out = {"family": "hunt-bull-market-support-band", "program": "v13-best-rules",
       "spec": "BEST-RULES-SPEC.md (frozen before run)",
       "published_best_v12_native": {"BTC": {"FULL": 19055991.29, "DESIGN": 12059267.47, "VALIDATION": 158.02},
                                     "ETH": {"FULL": 273791.54, "DESIGN": 343345.57, "VALIDATION": 79.74}},
       "BTC": run_asset("btc"), "ETH": run_asset("eth")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for a in ["BTC", "ETH"]:
    for w in ["FULL", "DESIGN", "VALIDATION"]:
        m = out[a]["mine"][w]
        print(a, w, "mine", m["native"]["final"], "maxdd", m["native"]["maxdd"], "trades", m["native"]["trades"],
              "| buyhold", m["buyhold"], "| pubbest", out["published_best_v12_native"][a][w],
              "| rand beaten", out[a]["placebos"][w]["random_timing"]["beaten"] if w in out[a]["placebos"] else "-",
              "| shift beaten", out[a]["placebos"][w]["shifted_signal"]["beaten"] if w in out[a]["placebos"] else "-")
