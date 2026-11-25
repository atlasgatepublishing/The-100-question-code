#!/usr/bin/env python3
"""V13 BEST RULES — Hash Ribbons HR-BEST (frozen BEST-RULES-SPEC.md).
Entry: first trailing 30/60 hash-SMA recovery cross inside the window
(with a capitulation cross earlier in full history). NO price leg.
Exit: NONE — hold to window end. No floor. BTC only. Costs 0.60%/side
(one entry cost charged; no exit cost — asymmetry vs the two-sided
buy-hold bar is stated in the spec and worth 0.60%).
Placebos: 20 seeds, single random entry in window, hold to end.
Data: v12 cache (read-only) CoinMetrics HashRate + PriceUSD.
Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_chassis import simulate, buy_hold, period_stats, sma, COST

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-hash-ribbons/data/cm_btc_hash.json")
raw = json.load(open(SRC))
days = []
for r in raw:
    if r.get("PriceUSD") and r.get("HashRate"):
        days.append({"d": r["time"][:10], "c": float(r["PriceUSD"]), "h": float(r["HashRate"])})
days.sort(key=lambda x: x["d"])
px = [d["c"] for d in days]; hr = [d["h"] for d in days]
FIRST = days[0]["d"]
WINDOWS = {"FULL": (FIRST, "2026-11-20"), "DESIGN": (FIRST, "2022-12-31"),
           "VALIDATION": ("2023-01-01", "2026-11-20")}

# --- global crosses (trailing SMAs only) ---
h30 = sma(hr, 30); h60 = sma(hr, 60)
cap_dates, rec_dates = [], []
for i in range(1, len(days)):
    if None in (h30[i], h60[i], h30[i-1], h60[i-1]): continue
    if h30[i-1] >= h60[i-1] and h30[i] < h60[i]: cap_dates.append(days[i]["d"])
    if h30[i-1] <= h60[i-1] and h30[i] > h60[i]: rec_dates.append(days[i]["d"])
date_idx = {d["d"]: i for i, d in enumerate(days)}

def entry_for_window(start, end):
    """First recovery cross in [start,end] preceded by a capitulation in full history."""
    for rd in rec_dates:
        if start <= rd <= end and any(cd < rd for cd in cap_dates):
            return rd
    return None

def state_from_entry(entry_date):
    st = [0] * len(days)
    if entry_date is None: return st
    ei = date_idx[entry_date]
    for j in range(ei, len(days)): st[j] = 1
    return st

def bar_max_dd(start, end):
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    peak = days[idx[0]]["c"]; mdd = 0.0
    for i in idx:
        peak = max(peak, days[i]["c"]); mdd = max(mdd, 1 - days[i]["c"] / peak)
    return round(mdd, 4)

def placebo(start, end, seed):
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    rng = random.Random(seed)
    a = rng.choice(idx)
    st = [0] * len(days)
    for j in range(a, len(days)): st[j] = 1
    r = simulate(days, st, start, end, "native")
    return {"entry": days[a]["d"], "final": r["final"]}

def main():
    out = {"family": "hunt-hash-ribbons", "program": "v13-best-rules", "system": "HR-BEST",
           "asset": "BTC", "data": "CoinMetrics HashRate+PriceUSD (v12 cache, read-only)",
           "cost_per_side": COST, "capitulation_crosses_total": len(cap_dates),
           "recovery_crosses_total": len(rec_dates), "roads": {}, "placebos": {}}
    log = [f"data {FIRST}..{days[-1]['d']} n={len(days)} caps={len(cap_dates)} recs={len(rec_dates)}"]
    for wname, (s, e) in WINDOWS.items():
        entry = entry_for_window(s, e)
        st = state_from_entry(entry)
        r = simulate(days, st, s, e, "native")
        bar = buy_hold(days, s, e)
        ei = date_idx[entry] if entry else None
        out["roads"][wname] = {
            "window": [s, e], "entry_date": entry,
            "entry_price": days[ei]["c"] if ei is not None else None,
            "final": r["final"], "trades": r["trades"], "costs": r["costs"],
            "max_dd": r["max_dd"], "halted": r["halted"],
            "period_stats_monthly": period_stats(r["curve"], "M"),
            "btc_buy_hold_bar": bar, "btc_buy_hold_max_dd": bar_max_dd(s, e),
            "curve": r["curve"]}
        log.append(f"{wname}: entry={entry} final={r['final']} bar={bar} maxdd={r['max_dd']}")
        finals = []
        for seed in range(1, 21):
            p = placebo(s, e, seed); finals.append(p["final"])
        med = round(statistics.median(finals), 2)
        out["placebos"][wname] = {"random_entry_hold_finals": finals, "median": med,
            "system_final": r["final"], "system_beats_seeds": sum(1 for f in finals if r["final"] > f)}
        log.append(f"{wname} placebos: median={med} system beats {out['placebos'][wname]['system_beats_seeds']}/20")
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    open(os.path.join(HERE, "run.log"), "w").write("\n".join(log) + "\n")
    print("\n".join(log))

if __name__ == "__main__":
    main()
