#!/usr/bin/env python3
"""V13 BEST RULES — GTT unemployment timer. Frozen BEST-RULES-SPEC.md.
Signal on FIRST-PUBLISHED UNRATE (ALFRED vintages): FP U <= FP 12MMA ->
exposure 1.0; else price key: SPY month-end TR close > 10MMA -> 1.0,
else 0.5 (the one dial step; published form used 0.0 — also run here as
'pit_binary' for an apples-to-apples PIT comparison, clearly labelled a
diagnostic, not a second spec). Decide at close of last trading day of
month M+1 using print for month M; fill next open. Costs 0.10%/side on
traded fraction + $0.01 on any sell event. Cash 0%. No floor.
Placebos: 20 seeds circular month-shifts (1-60) of the exposure series.
Simulation only."""
import json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-gtt-unemployment"))
from chassis import load_bars, period_stats  # noqa: E402

COST = 0.001; SELLFEE = 0.01
SPY = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
bars = load_bars(SPY)
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 579.21, "DECADE": 259.30, "CONT": 220.43, "VAL": 148.19}

fpj = json.load(open(os.path.join(ROOT, "data", "unrate_first_published.json")))
FP = fpj["fp"]; FLAGS = fpj["flags"]
fmonths = sorted(FP)

import calendar as _cal
def known_by(ref):
    """Date the FP value of ref was certainly public: last day of ref+1,
    or the flagged vintage date for delayed releases."""
    if ref in FLAGS and "first seen in vintage" in FLAGS[ref]:
        return FLAGS[ref].split("vintage ")[1].split(" ")[0]
    y, m = int(ref[:4]), int(ref[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"

def ue_down(ref, decision_date):
    i = fmonths.index(ref)
    if i < 11: return None
    window = [fmonths[i - k] for k in range(12)]
    if any(known_by(w) > decision_date for w in window): return None
    ma = sum(FP[w] for w in window) / 12
    return FP[ref] <= ma

me = {}
for b in bars: me[b["d"][:7]] = b["c"]
me_months = sorted(me)
def price_long(mk):
    i = me_months.index(mk)
    if i < 9: return None
    ma = sum(me[me_months[i - k]] for k in range(10)) / 10
    return me[mk] > ma

def build_exposure(down_state_exposure, shift=0):
    """Monthly decisions: decision month mk (decision at its month-end)
    uses FP print for month mk-1. Returns daily exposure array."""
    dec = {}
    for mk in me_months:
        y, m = int(mk[:4]), int(mk[5:7])
        pm = f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"
        if pm not in FP: continue
        # knowledge cutoff = calendar month-end of the decision month
        # (prints are released early in the month; delayed releases are
        # handled by their flagged vintage dates in known_by)
        last_td = f"{mk}-{_cal.monthrange(int(mk[:4]), int(mk[5:7]))[1]:02d}"
        d = ue_down(pm, last_td)
        if d is None: continue
        if d: dec[mk] = 1.0
        else:
            pl = price_long(mk)
            if pl is None: continue
            dec[mk] = 1.0 if pl else down_state_exposure
    if shift:
        keys = sorted(dec); vals = [dec[k] for k in keys]
        vals = vals[shift:] + vals[:shift]
        dec = dict(zip(keys, vals))
    exp = [0.0] * len(bars); cur = 0.0
    lastday = {}
    for i, b in enumerate(bars): lastday[b["d"][:7]] = i
    for i, b in enumerate(bars):
        mk = b["d"][:7]
        if lastday.get(mk) == i and mk in dec: cur = dec[mk]
        exp[i] = cur
    return exp

def simulate_frac(start, end, exposure):
    """Exposure decided at close of day i executes at open of day i+1."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; pos = 0.0; curve = []; trades = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0; pending = None
    for k, i in enumerate(idx):
        b = bars[i]; prev = bars[idx[k - 1]] if k > 0 else None
        if k > 0:
            if pending is not None and abs(pending - pos) > 1e-9:
                # move to open price with current position, trade, then intraday
                eq *= (1 + pos * (b["o"] / prev["c"] - 1))
                delta = pending - pos
                c = eq * abs(delta) * COST + (SELLFEE if delta < 0 else 0.0)
                eq -= c; costs += c; trades += 1; pos = pending
                eq *= (1 + pos * (b["c"] / b["o"] - 1))
                pending = None
            else:
                eq *= (1 + pos * (b["c"] / prev["c"] - 1))
        pending = exposure[i]
        curve.append([b["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4)}

def buy_hold(start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    eq = 100.0 * (1 - COST) * bars[idx[-1]]["c"] / bars[idx[0]]["c"] * (1 - COST)
    # buy-hold curve for distribution comparison not needed; final only
    return round(eq, 2)

def main():
    out = {"family": "hunt-gtt-unemployment", "program": "v13-best-rules",
           "signal": "FP UNRATE (ALFRED first-published) vs FP 12MMA; else SPY vs 10MMA; double-negative exposure 0.5",
           "fp_flags": FLAGS, "roads": {}}
    exp_dial = build_exposure(0.5)
    exp_bin = build_exposure(0.0)
    for road, (s, e) in ROADS.items():
        ent = {}
        r = simulate_frac(s, e, exp_dial)
        ent["best_rules"] = {k: v for k, v in r.items() if k != "curve"}
        ent["best_rules"]["period_stats_monthly"] = period_stats(r["curve"], "M")
        ent["curve_best_rules"] = r["curve"]
        rb = simulate_frac(s, e, exp_bin)
        ent["pit_binary_diagnostic"] = {k: v for k, v in rb.items() if k != "curve"}
        ent["pit_binary_diagnostic"]["period_stats_monthly"] = period_stats(rb["curve"], "M")
        ent["spy_buy_hold_this_chassis"] = buy_hold(s, e)
        ent["spy_reference_program"] = SPYREF[road]
        ent["champion_vm"] = CHAMP[road]
        ent["published_v12_native_current_vintage"] = PUBLISHED[road]
        out["roads"][road] = ent
        print(road, "best", ent["best_rules"]["final"], "dd", ent["best_rules"]["max_dd"],
              "pitbin", ent["pit_binary_diagnostic"]["final"], "bh", ent["spy_buy_hold_this_chassis"], flush=True)
    out["placebos"] = {}
    for road, (s, e) in ROADS.items():
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); sh = rng.randint(1, 60)
            finals.append(simulate_frac(s, e, build_exposure(0.5, shift=sh))["final"])
        sysf = out["roads"][road]["best_rules"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_final": sysf, "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road]["median"], "beats", out["placebos"][road]["beats"], flush=True)
    json.dump(out, open(os.path.join(ROOT, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
