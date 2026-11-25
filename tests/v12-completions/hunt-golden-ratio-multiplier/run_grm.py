#!/usr/bin/env python3
"""Golden Ratio Multiplier (Swift, Apr 2019) — GRM-SEQ frozen form.
350DMA base; enter long on close < 350DMA x entry_mult (1.0 published
accumulation area); exit on close >= 350DMA x current exit multiple;
exit multiple steps down the author's published sequence 5 -> 3 -> 2 ->
1.6 after each exit (starts at x5, the last multiple hit before
publication). BTC only, CoinMetrics PriceUSD, costs 0.60%/side.
NATIVE no floor; V9 house -15% floor (daily-close, run stops).
Placebos (spec): 20 seeds, entry mult ~ U[0.85,1.15], exit start ~
choice{3,5,8} with same step-down. FULL carries the spec's
IN-SAMPLE-CALIBRATION fence (multiples fit to 2011-2018 tops);
VALIDATION 2023-> is the clean read. Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_chassis import simulate, buy_hold, period_stats, sma

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "data", "cm_btc_hash.json")))
days = []
for r in raw:
    if r.get("PriceUSD"):
        days.append({"d": r["time"][:10], "c": float(r["PriceUSD"])})
days.sort(key=lambda x: x["d"])
px = [d["c"] for d in days]
ma350 = sma(px, 350)
FIRST = next(days[i]["d"] for i in range(len(days)) if ma350[i] is not None)
SEQ = [5, 3, 2, 1.6]
WINDOWS = {"FULL": (FIRST, "2026-11-20"), "DESIGN": (FIRST, "2022-12-31"),
           "VALIDATION": ("2023-01-01", "2026-11-20")}

def build_state(entry_mult=1.0, seq_start_idx=0, seq=None):
    seq = seq if seq is not None else SEQ[seq_start_idx:]
    st = [0] * len(days); pos = 0; step = 0
    for i in range(len(days)):
        if ma350[i] is None: continue
        if pos == 0 and px[i] < ma350[i] * entry_mult:
            pos = 1
        elif pos == 1 and px[i] >= ma350[i] * seq[min(step, len(seq) - 1)]:
            pos = 0; step += 1
        st[i] = pos
    return st

def main():
    out = {"family": "hunt-golden-ratio-multiplier", "asset": "BTC",
           "first_computable": FIRST, "windows": {}}
    st = build_state()
    for wname, (s, e) in WINDOWS.items():
        ent = {}
        for form in ("native", "house"):
            r = simulate(days, st, s, e, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["btc_buy_hold_bar"] = buy_hold(days, s, e)
        out["windows"][wname] = ent
        print(wname, "native", ent["native"]["final"], "house", ent["house"]["final"], "bar", ent["btc_buy_hold_bar"])
    out["placebos"] = {}
    for wname in ("FULL", "VALIDATION"):
        s, e = WINDOWS[wname]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            em = rng.uniform(0.85, 1.15)
            start_idx = rng.choice([0, 1, 2])  # exit starts at 5, 3, or 8-> use seq variants
            seq = [8, 5, 3, 2, 1.6] if start_idx == 2 else SEQ[start_idx:]
            pst = build_state(em, seq=seq)
            finals.append(simulate(days, pst, s, e, "native")["final"])
        sys_final = out["windows"][wname]["native"]["final"]
        out["placebos"][wname] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                  "system_native_final": sys_final,
                                  "beats": sum(1 for f in finals if sys_final > f)}
        print("placebo", wname, out["placebos"][wname])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
