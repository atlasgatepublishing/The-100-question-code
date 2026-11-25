#!/usr/bin/env python3
"""Hash Ribbons (Edwards 2019) — frozen SPEC-FROZEN.md implementation.
HR-BUY-HOLD: published buy signal (hash recovery cross THEN 10/20 price
SMA cross-up while 30d hash SMA still above 60d) + CONSTRUCTED exit on
next capitulation cross. HR-RECOVERY-ONLY: long on recovery cross, cash
on capitulation cross. BTC only. CoinMetrics HashRate + PriceUSD.
Costs 0.60%/side. NATIVE no floor; V9 house -15% floor, run stops.
Placebos: 20-seed random-entry timing control (count & median hold
matched) + 4 shifted-parameter controls. Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from crypto_chassis import simulate, buy_hold, period_stats, sma

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "data", "cm_btc_hash.json")))
days = []
for r in raw:
    if r.get("PriceUSD") and r.get("HashRate"):
        days.append({"d": r["time"][:10], "c": float(r["PriceUSD"]), "h": float(r["HashRate"])})
days.sort(key=lambda x: x["d"])
px = [d["c"] for d in days]; hr = [d["h"] for d in days]
FIRST = days[0]["d"]
WINDOWS = {"FULL": (FIRST, "2026-11-20"), "DESIGN": (FIRST, "2022-12-31"),
           "VALIDATION": ("2023-01-01", "2026-11-20")}

def build_states(hf, hs, pf, ps):
    h30 = sma(hr, hf); h60 = sma(hr, hs); p10 = sma(px, pf); p20 = sma(px, ps)
    rec = [0] * len(days)   # recovery-only state
    bh = [0] * len(days)    # buy-hold (published entry) state
    in_rec = False; in_bh = False; armed = False
    for i in range(1, len(days)):
        if None in (h30[i], h60[i], h30[i-1], h60[i-1]): continue
        cap_cross = h30[i-1] >= h60[i-1] and h30[i] < h60[i]
        rec_cross = h30[i-1] <= h60[i-1] and h30[i] > h60[i]
        if cap_cross:
            in_rec = False; in_bh = False; armed = False
        if rec_cross:
            in_rec = True; armed = True
        if armed and not in_bh and p10[i] is not None and p20[i] is not None \
           and p10[i-1] is not None and p20[i-1] is not None:
            if h30[i] > h60[i] and p10[i-1] <= p20[i-1] and p10[i] > p20[i]:
                in_bh = True; armed = False
        rec[i] = 1 if in_rec else 0
        bh[i] = 1 if in_bh else 0
    return rec, bh

def holds_of(state, start, end):
    """list of (entry_idx, exit_idx) within window for placebo matching"""
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    holds = []; cur = None
    for i in idx:
        if state[i] == 1 and cur is None: cur = i
        if state[i] == 0 and cur is not None: holds.append((cur, i)); cur = None
    if cur is not None: holds.append((cur, idx[-1]))
    return holds

def placebo(state, start, end, seed):
    holds = holds_of(state, start, end)
    if not holds: return None
    med = int(statistics.median([b - a for a, b in holds]))
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    rng = random.Random(seed)
    st = [0] * len(days)
    for _ in holds:
        a = rng.choice(idx[:-max(med, 1)] if len(idx) > med else idx)
        for j in range(a, min(a + med, len(days))): st[j] = 1
    return simulate(days, st, start, end, "native")

def main():
    out = {"family": "hunt-hash-ribbons", "asset": "BTC", "data": "CoinMetrics HashRate+PriceUSD",
           "systems": {}}
    variants = {}
    rec, bh = build_states(30, 60, 10, 20)
    variants["HR-BUY-HOLD"] = bh; variants["HR-RECOVERY-ONLY"] = rec
    for name, st in variants.items():
        out["systems"][name] = {}
        for wname, (s, e) in WINDOWS.items():
            ent = {}
            for form in ("native", "house"):
                r = simulate(days, st, s, e, form)
                ent[form] = {k: v for k, v in r.items() if k != "curve"}
                ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
                if form == "native": ent["curve_native"] = r["curve"]
            ent["btc_buy_hold_bar"] = buy_hold(days, s, e)
            out["systems"][name][wname] = ent
    # placebos on HR-BUY-HOLD (published entry)
    out["placebos"] = {}
    for wname in ("FULL", "VALIDATION"):
        s, e = WINDOWS[wname]
        finals = []
        for seed in range(1, 21):
            r = placebo(bh, s, e, seed)
            if r: finals.append(r["final"])
        out["placebos"][wname] = {"random_timing_finals": finals,
            "median": round(statistics.median(finals), 2) if finals else None,
            "system_native_final": out["systems"]["HR-BUY-HOLD"][wname]["native"]["final"],
            "beats": sum(1 for f in finals if out["systems"]["HR-BUY-HOLD"][wname]["native"]["final"] > f)}
    # shifted-parameter controls (native, FULL + VALIDATION)
    out["param_controls"] = {}
    for (hf, hs, pf, ps) in [(20, 40, 10, 20), (40, 80, 10, 20), (30, 60, 8, 16), (30, 60, 12, 24)]:
        _, b2 = build_states(hf, hs, pf, ps)
        key = f"hash{hf}/{hs}_px{pf}/{ps}"
        out["param_controls"][key] = {w: simulate(days, b2, *WINDOWS[w], "native")["final"]
                                      for w in ("FULL", "VALIDATION")}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for name in variants:
        for w in WINDOWS:
            e = out["systems"][name][w]
            print(name, w, "native", e["native"]["final"], "house", e["house"]["final"], "bar", e["btc_buy_hold_bar"])
    print("placebos", out["placebos"])
    print("controls", out["param_controls"])

if __name__ == "__main__":
    main()
